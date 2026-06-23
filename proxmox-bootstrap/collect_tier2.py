#!/usr/bin/env python3
"""
collect_tier2 — Tier 2 Bootstrap State Collector (library)

Connects to a Proxmox host over SSH and populates bootstrap-state.json with
live system state:

  provenance_records  — one entry per running VM/CT (vmid, name, deployed_at,
                        template_name; other fields left for manual entry)
  templates           — one entry per Proxmox template (template: 1 in qm config)
  base_images         — inferred from template descriptions/notes where available

Merge behaviour: existing entries are NEVER overwritten. Only absent entries are
added. This means manually recorded fields (tofu_commit, ansible_commit, etc.) are
preserved across collection runs.

Usage:
    python3 proxmox-bootstrap/collect-tier2.py --host <proxmox-ip> --user <user>
    python3 proxmox-bootstrap/collect-tier2.py --host 192.168.1.10 --dry-run

Options:
    --host HOST         Proxmox host IP or hostname (required)
    --user USER         SSH user (default: root)
    --port PORT         SSH port (default: 22)
    --key KEY           Path to SSH private key (default: ~/.ssh/id_rsa)
    --state FILE        Path to bootstrap-state.json (default: auto-detected)
    --dry-run           Print what would be written; do not modify bootstrap-state.json
    --verbose           Print raw command output for debugging

Design constraints:
    - stdlib only (no pip)
    - SSH via subprocess (avoids paramiko dependency)
    - Must not overwrite existing manually-entered provenance fields
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
DEFAULT_STATE_PATH = REPO_ROOT / "proxmox-bootstrap" / "bootstrap-state.json"

# ---------------------------------------------------------------------------
# SSH wrapper
# ---------------------------------------------------------------------------

class SSHClient:
    def __init__(self, host: str, user: str = "root", port: int = 22,
                 key: str | None = None, verbose: bool = False):
        self.host = host
        self.user = user
        self.port = port
        self.key = key
        self.verbose = verbose

    def run(self, command: str) -> str:
        """Run a command on the remote host; return stdout. Raises on non-zero exit."""
        cmd = [
            "ssh",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=10",
            "-p", str(self.port),
        ]
        if self.key:
            cmd += ["-i", self.key]
        cmd += [f"{self.user}@{self.host}", command]

        if self.verbose:
            print(f"[ssh] {command}", file=sys.stderr)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"SSH command failed (exit {result.returncode}): {command!r}\n"
                f"stderr: {result.stderr.strip()}"
            )
        if self.verbose and result.stdout.strip():
            print(result.stdout, file=sys.stderr)
        return result.stdout

    def test_connection(self) -> bool:
        try:
            self.run("echo ok")
            return True
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Proxmox command parsers
# ---------------------------------------------------------------------------

def parse_qm_list(output: str) -> list[dict]:
    """
    Parse `qm list` output into a list of {vmid, name, status} dicts.

    qm list output format:
          VMID NAME                 STATUS     MEM(MB)    BOOTDISK(GB) PID
           100 forgejo              running    2048              50.00 12345
    """
    vms = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("VMID"):
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            vms.append({
                "vmid": int(parts[0]),
                "name": parts[1],
                "status": parts[2],
            })
        except (ValueError, IndexError):
            continue
    return vms


def parse_qm_config(vmid: int, output: str) -> dict:
    """
    Parse `qm config <vmid>` output into a flat key→value dict.

    Lines are either:
        key: value
        #key: value   (pending changes — skip)
    """
    config = {}
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        config[key.strip()] = value.strip()
    return config


def parse_pveversion(output: str) -> str:
    """Extract the Proxmox VE version string from `pveversion` output."""
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("pve-manager"):
            # pve-manager/8.1.3/...
            parts = line.split("/")
            if len(parts) >= 2:
                return parts[1]
    return output.strip().splitlines()[0] if output.strip() else "unknown"


def _extract_iso_name(config: dict) -> str | None:
    """
    Try to extract a source ISO name from a template's qm config.

    Proxmox doesn't have a dedicated field for the source ISO used to build
    a template. We look in common locations: description, notes, ide2 (CD-ROM drive).
    Returns the ISO filename if found, else None.
    """
    # Check description and notes fields for ISO filename patterns
    for field in ("description", "notes"):
        value = config.get(field, "")
        for word in value.replace("\\n", " ").replace("\n", " ").split():
            if word.endswith(".iso"):
                return word.strip("\"'()[]")

    # Check ide2 (common CD-ROM slot) — value like "local:iso/ubuntu-22.04.4-live-server-amd64.iso,media=cdrom"
    for key in ("ide0", "ide1", "ide2", "ide3", "sata0", "sata1"):
        value = config.get(key, "")
        if ".iso" in value:
            # Extract filename from path
            for part in value.split(","):
                part = part.strip()
                if ".iso" in part:
                    return part.split("/")[-1]

    return None


# ---------------------------------------------------------------------------
# Collectors
# ---------------------------------------------------------------------------

def collect_templates(ssh: SSHClient) -> tuple[list[dict], list[dict]]:
    """
    Discover all Proxmox templates and infer base images.

    Returns (templates_list, base_images_list).
    """
    raw_list = ssh.run("qm list")
    vms = parse_qm_list(raw_list)

    templates = []
    base_images = []
    seen_isos: set[str] = set()

    for vm in vms:
        vmid = vm["vmid"]
        try:
            raw_config = ssh.run(f"qm config {vmid}")
        except RuntimeError as e:
            print(f"[collect-tier2] WARNING: could not read config for vmid={vmid}: {e}",
                  file=sys.stderr)
            continue

        config = parse_qm_config(vmid, raw_config)
        if config.get("template") != "1":
            continue

        name = vm["name"]
        created_at = _infer_created_at(ssh, vmid)
        iso_name = _extract_iso_name(config)

        # Derive a base_image name from the ISO filename or fall back to template name
        if iso_name:
            # ubuntu-22.04.4-live-server-amd64.iso → ubuntu-2204-base
            base_image_name = _iso_to_base_image_name(iso_name)
        else:
            base_image_name = name

        templates.append({
            "name": name,
            "base_image": base_image_name,
            "proxmox_template_id": vmid,
            "created_at": created_at,
            "additional_packages": [],
            "build_notes": f"Collected by collect-tier2.py from vmid={vmid}",
        })

        if iso_name and iso_name not in seen_isos:
            seen_isos.add(iso_name)
            base_images.append({
                "name": base_image_name,
                "source_iso": iso_name,
                "source_url": None,
                "checksum": None,
                "created_at": created_at,
                "included_packages": [],
                "notes": (
                    "Collected by collect-tier2.py — "
                    "populate source_url and checksum manually"
                ),
            })

    return templates, base_images


def collect_provenance_records(ssh: SSHClient) -> list[dict]:
    """
    Collect a minimal provenance record for each running VM.

    Fields populated automatically: vmid, name, deployed_at (config mtime).
    Fields left for manual entry: tofu_workspace, tofu_commit, ansible_commit, etc.
    """
    raw_list = ssh.run("qm list")
    vms = parse_qm_list(raw_list)

    records = []
    for vm in vms:
        vmid = vm["vmid"]
        try:
            raw_config = ssh.run(f"qm config {vmid}")
        except RuntimeError as e:
            print(f"[collect-tier2] WARNING: could not read config for vmid={vmid}: {e}",
                  file=sys.stderr)
            continue

        config = parse_qm_config(vmid, raw_config)
        if config.get("template") == "1":
            continue  # skip templates — they go in templates[], not provenance_records

        # Infer the template name from the VM's parent template (if recorded in config)
        template_name = _infer_template_name(config)

        deployed_at = _infer_deployed_at(ssh, vmid)

        records.append({
            "vmid": vmid,
            "name": vm["name"],
            "deployed_at": deployed_at,
            "tofu_workspace": None,
            "tofu_commit": None,
            "template_name": template_name,
            "template_checksum": None,
            "cloudinit_user_data_hash": None,
            "cloudinit_network_config_hash": None,
            "ansible_playbook": None,
            "ansible_commit": None,
            "ansible_inventory_commit": None,
            "deployed_by": None,
            "notes": "Collected by collect-tier2.py — populate deployment fields manually",
        })

    return records


def _infer_created_at(ssh: SSHClient, vmid: int) -> str:
    """
    Infer a creation timestamp for a VM from the mtime of its config file.
    Falls back to current UTC time if stat fails.
    """
    try:
        # Proxmox stores VM configs at /etc/pve/qemu-server/<vmid>.conf
        out = ssh.run(f"stat -c %Y /etc/pve/qemu-server/{vmid}.conf 2>/dev/null || echo 0")
        epoch = int(out.strip())
        if epoch:
            dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        pass
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _infer_deployed_at(ssh: SSHClient, vmid: int) -> str:
    """Same as _infer_created_at but named for provenance context."""
    return _infer_created_at(ssh, vmid)


def _infer_template_name(config: dict) -> str | None:
    """
    Try to determine which template a VM was cloned from.

    Proxmox doesn't record this directly after clone. We check:
    1. A custom description/notes field set by our own bootstrap tooling.
    2. The ostype + scsi0 disk name heuristic (less reliable).
    """
    for field in ("description", "notes"):
        value = config.get(field, "")
        # qm config encodes newlines as literal \n in description/notes
        for line in value.replace("\\n", "\n").splitlines():
            line = line.strip()
            if line.lower().startswith("template:"):
                return line.split(":", 1)[1].strip()
    return None


def _iso_to_base_image_name(iso_filename: str) -> str:
    """
    Derive a normalized base image name from an ISO filename.

    ubuntu-22.04.4-live-server-amd64.iso → ubuntu-2204-base
    debian-12.5.0-amd64-netinst.iso      → debian-12-base
    talos-v1.7.0-metal-amd64.iso         → talos-17-base
    other.iso                             → other-base
    """
    name = iso_filename.lower().removesuffix(".iso")

    # Ubuntu: ubuntu-22.04.4-... → ubuntu-2204-base
    if name.startswith("ubuntu-"):
        parts = name.split("-")
        if len(parts) >= 2:
            version = parts[1].replace(".", "")[:4]  # 22.04.4 → 2204
            return f"ubuntu-{version}-base"

    # Debian: debian-12.5.0-... → debian-12-base
    if name.startswith("debian-"):
        parts = name.split("-")
        if len(parts) >= 2:
            major = parts[1].split(".")[0]
            return f"debian-{major}-base"

    # Talos: talos-v1.7.0-... → talos-17-base
    if name.startswith("talos-"):
        parts = name.split("-")
        if len(parts) >= 2:
            version = parts[1].lstrip("v").replace(".", "")[:2]
            return f"talos-{version}-base"

    # Fallback: take first segment before first hyphen + "-base"
    base = name.split("-")[0]
    return f"{base}-base"


# ---------------------------------------------------------------------------
# Merge logic
# ---------------------------------------------------------------------------

def _merge_list_by_key(existing: list, incoming: list, key: str) -> tuple[list, int]:
    """
    Merge incoming entries into existing list, keyed by `key`.

    Existing entries are never modified. Only entries whose key value is
    absent from existing are appended.

    Returns (merged_list, added_count).
    """
    existing_keys = {entry.get(key) for entry in existing if entry.get(key) is not None}
    added = 0
    merged = list(existing)
    for entry in incoming:
        k = entry.get(key)
        if k not in existing_keys:
            merged.append(entry)
            existing_keys.add(k)
            added += 1
    return merged, added


# ---------------------------------------------------------------------------
# Service contract coverage reader
# ---------------------------------------------------------------------------

def check_service_contract_coverage(state: dict, observed_vms: list) -> list:
    """
    Read declared service contracts from state and cross-reference against
    the observed VM list collected from the live Proxmox host.

    Returns a list of coverage gap dicts:
      {service, vm, issue}  — one entry per declared contract whose VM was
                               not observed in the running system.

    This is the "service contract reader" step in Tier 2 collection:
    contracts are declared in bootstrap-state.json (mirrored from
    proxmox-bootstrap/service-contracts.yaml), and Tier 2 collection
    compares declarations against observed reality.
    """
    contracts = state.get("service_contracts") or []
    if not contracts:
        return []

    observed_names = {v.get("name", "") for v in observed_vms}
    gaps = []
    for contract in contracts:
        vm_name = contract.get("vm")
        svc     = contract.get("service", "?")
        if vm_name and vm_name not in observed_names:
            gaps.append({
                "service": svc,
                "vm":      vm_name,
                "issue":   (f"Contract declared for service '{svc}' on VM '{vm_name}', "
                             f"but that VM was not observed on the Proxmox host"),
            })
    return gaps


def merge_into_state(state: dict, new_provenance: list, new_templates: list,
                     new_base_images: list) -> tuple[dict, dict]:
    """
    Merge collected data into bootstrap-state.json content.

    Returns (updated_state, summary) where summary counts added entries.
    """
    existing_prov     = state.get("provenance_records") or []
    existing_templates = state.get("templates") or []
    existing_bi       = state.get("base_images") or []

    merged_prov,   added_prov   = _merge_list_by_key(existing_prov,      new_provenance,  "vmid")
    merged_tmpl,   added_tmpl   = _merge_list_by_key(existing_templates,  new_templates,   "proxmox_template_id")
    merged_bi,     added_bi     = _merge_list_by_key(existing_bi,         new_base_images, "name")

    updated = dict(state)
    updated["provenance_records"] = merged_prov
    updated["templates"]          = merged_tmpl
    updated["base_images"]        = merged_bi

    summary = {
        "provenance_records_added": added_prov,
        "templates_added":          added_tmpl,
        "base_images_added":        added_bi,
        "provenance_records_total": len(merged_prov),
        "templates_total":          len(merged_tmpl),
        "base_images_total":        len(merged_bi),
    }
    return updated, summary


# ---------------------------------------------------------------------------
# State file I/O
# ---------------------------------------------------------------------------

def _find_state_file() -> Path:
    candidates = [
        DEFAULT_STATE_PATH,
        Path("proxmox-bootstrap/bootstrap-state.json"),
        Path("bootstrap-state.json"),
    ]
    for p in candidates:
        if p.exists():
            return p
    return DEFAULT_STATE_PATH


def load_state(path: Path) -> dict:
    if not path.exists():
        print(f"[collect-tier2] bootstrap-state.json not found at {path}; "
              f"starting with empty state.", file=sys.stderr)
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: dict) -> None:
    path.write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Collect live Proxmox state into bootstrap-state.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--host",    required=True,  help="Proxmox host IP or hostname")
    p.add_argument("--user",    default="root",  help="SSH user (default: root)")
    p.add_argument("--port",    type=int, default=22, help="SSH port (default: 22)")
    p.add_argument("--key",     default=None,    help="Path to SSH private key")
    p.add_argument("--state",   default=None,    help="Path to bootstrap-state.json")
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would be written; do not modify bootstrap-state.json")
    p.add_argument("--verbose", action="store_true",
                   help="Print raw command output for debugging")
    return p


def main(argv=None):
    args = build_arg_parser().parse_args(argv)

    state_path = Path(args.state) if args.state else _find_state_file()
    print(f"[collect-tier2] Bootstrap state file: {state_path}")

    ssh = SSHClient(
        host=args.host,
        user=args.user,
        port=args.port,
        key=args.key,
        verbose=args.verbose,
    )

    print(f"[collect-tier2] Connecting to {args.user}@{args.host}:{args.port} ...")
    if not ssh.test_connection():
        print("[collect-tier2] ERROR: SSH connection failed.", file=sys.stderr)
        sys.exit(1)
    print("[collect-tier2] Connection OK")

    print("[collect-tier2] Collecting templates and base images ...")
    templates, base_images = collect_templates(ssh)
    print(f"[collect-tier2]   Found {len(templates)} template(s), "
          f"{len(base_images)} base image(s)")

    print("[collect-tier2] Collecting provenance records ...")
    provenance = collect_provenance_records(ssh)
    print(f"[collect-tier2]   Found {len(provenance)} VM(s)")

    state = load_state(state_path)

    # Service contract coverage check — read declared contracts from state
    # and cross-reference against observed VMs before merge.
    contract_gaps = check_service_contract_coverage(state, provenance)
    if contract_gaps:
        print(f"[collect-tier2] Service contract gaps ({len(contract_gaps)}):")
        for gap in contract_gaps:
            print(f"  WARNING: {gap['issue']}")
    elif state.get("service_contracts"):
        print(f"[collect-tier2] Service contracts: "
              f"{len(state['service_contracts'])} declared, "
              f"all VMs observed — OK")
    else:
        print("[collect-tier2] Service contracts: none declared in bootstrap-state.json")

    updated_state, summary = merge_into_state(state, provenance, templates, base_images)

    print("[collect-tier2] Merge summary:")
    print(f"  provenance_records: +{summary['provenance_records_added']} "
          f"({summary['provenance_records_total']} total)")
    print(f"  templates:          +{summary['templates_added']} "
          f"({summary['templates_total']} total)")
    print(f"  base_images:        +{summary['base_images_added']} "
          f"({summary['base_images_total']} total)")

    # Build service-state document from declared contracts + observed VMs
    # doc-gen is a sibling directory; idempotent insert.
    _doc_gen_path = str(REPO_ROOT / "doc-gen")
    if _doc_gen_path not in sys.path:
        sys.path.insert(0, _doc_gen_path)
    try:
        from service_state_collector import collect_service_state
        service_state = collect_service_state(
            bootstrap_state=state,
            observed_vms=provenance,
        )
        service_state_path = state_path.parent / "service-state.json"
        n_svc = len(service_state.get("services") or [])
        print(f"[collect-tier2] Service state: {n_svc} service(s) collected")
    except Exception as exc:
        service_state = None
        service_state_path = None
        print(f"[collect-tier2] WARNING: service state collection failed: {exc}",
              file=sys.stderr)

    if args.dry_run:
        print("[collect-tier2] --dry-run: would write the following to "
              f"{state_path}:\n")
        print(json.dumps(updated_state, indent=2, ensure_ascii=False))
        if service_state:
            print(f"\n[collect-tier2] --dry-run: would write service-state to "
                  f"{service_state_path}:\n")
            print(json.dumps(service_state, indent=2, ensure_ascii=False))
        print("\n[collect-tier2] --dry-run: no changes written.")
        return

    save_state(state_path, updated_state)
    print(f"[collect-tier2] Written to {state_path}")

    if service_state and service_state_path:
        save_state(service_state_path, service_state)
        print(f"[collect-tier2] Service state written to {service_state_path}")

    print("[collect-tier2] Done.")


if __name__ == "__main__":
    main()
