#!/usr/bin/env python3
"""
Naming convention engine for Infrastructure Cell bootstrap state.

Given a small set of root facts (cell_id, hostname, KeePass root, network CIDR,
and VM role list) this module derives ALL names used throughout the cell:
  - Secret IDs and KeePass entry paths
  - SSH key file names
  - VM IP assignments
  - DNS registry entries
  - Secret registry entries

The convention is deterministic: the same inputs always produce the same names.
This eliminates ad-hoc naming decisions and ensures all tooling agrees.

Importable as a library by setup-secrets.py and init-bootstrap-state.py.
Also usable as a standalone CLI to preview names before committing.

Usage:
    python3 suggest-names.py --hostname pve01 --kp-root Infrastructure \\
        --cidr 192.168.50.0/24 --cell-id pve01-cell \\
        --vms forgejo inventory assessment-engine

Convention:
    {kp_root}/
      {hostname}/
        root-password          Proxmox host root account
        api-token-tofu         OpenTofu Proxmox provider token
        api-token-pve          Proxmox UI/API token (if separate)
      vms/
        {vmid}-{vmname}/
          password             Initial OS user password
      ssh/
        deploy-keys/
          {vmname}             SSH private key (stored as KeePass attachment)
      services/
        {service}/
          admin-password       Service admin passwords (added later per-service)

    IPs (default layout, offset from gateway's .1 address):
      Host:        {prefix}.10
      VMs:         {prefix}.20, .21, .22, ... (sequential)
      Reserved:    .1 (gateway), .2–.9 (infrastructure), .11–.19 (reserved)
"""

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# IP suggestion
# ---------------------------------------------------------------------------

def suggest_ips(
    management_cidr: str,
    vm_names: list[str],
    host_offset: int = 10,
    vm_start_offset: int = 20,
) -> dict:
    """
    Suggest IP assignments for host and VMs from a CIDR.

    Returns:
        {
          "host": "192.168.50.10",
          "vms": {"forgejo": "192.168.50.20", ...},
          "prefix": "/24",
          "network_prefix": "192.168.50",
        }
    """
    if "/" not in management_cidr:
        raise ValueError(f"management_cidr must be CIDR notation, got: {management_cidr!r}")
    network, prefix_len = management_cidr.rsplit("/", 1)
    # Compute the network prefix (all but last octet for /24; caller may need to adjust for /16 etc.)
    parts = network.split(".")
    # For /24: prefix is first 3 octets. For /16: first 2. General: prefix_len // 8 octets fixed.
    fixed_octets = int(prefix_len) // 8
    net_prefix = ".".join(parts[:fixed_octets])

    return {
        "host": f"{net_prefix}.{host_offset}",
        "vms": {
            name: f"{net_prefix}.{vm_start_offset + i}"
            for i, name in enumerate(vm_names)
        },
        "prefix": f"/{prefix_len}",
        "network_prefix": net_prefix,
    }


def suggest_gateway(management_cidr: str) -> str:
    """Suggest gateway as the .1 address of the subnet."""
    network = management_cidr.split("/")[0]
    parts = network.split(".")
    prefix_len = int(management_cidr.split("/")[1])
    fixed_octets = prefix_len // 8
    net_prefix = ".".join(parts[:fixed_octets])
    return f"{net_prefix}.1"


# ---------------------------------------------------------------------------
# Name suggestion
# ---------------------------------------------------------------------------

def suggest_cell_id(hostname: str, suffix: str = "cell") -> str:
    """Suggest a cell ID from the hostname: pve01 → pve01-cell."""
    return f"{hostname}-{suffix}"


def suggest_cell_id_variants(hostname: str) -> list[str]:
    """Return ordered list of cell ID suggestions from most to least specific."""
    return [
        hostname,
        f"{hostname}-cell",
        f"{hostname}-primary",
        f"{hostname}-homelab",
    ]


# ---------------------------------------------------------------------------
# KeePass path convention
# ---------------------------------------------------------------------------

def keepass_paths(
    kp_root: str,
    hostname: str,
    vms: list[dict],  # list of {name, vmid}
) -> dict:
    """
    Generate the complete KeePass path map for a cell.

    All paths are relative to the database root.
    Returns a flat dict of {secret_id: keepass_path}.
    """
    h = hostname
    r = kp_root

    paths = {
        # Host-level secrets
        f"{h}-root-password":    f"{r}/{h}/root-password",
        f"{h}-api-token-tofu":   f"{r}/{h}/api-token-tofu",

        # Per-VM secrets
        **{
            f"vm-{vm['name']}-password":   f"{r}/vms/{vm['vmid']}-{vm['name']}/password"
            for vm in vms
        },
        **{
            f"{vm['name']}-deploy-key":    f"{r}/ssh/deploy-keys/{vm['name']}"
            for vm in vms
        },
    }
    return paths


def secret_registry_entries(
    kp_root: str,
    hostname: str,
    cell_id: str,
    vms: list[dict],  # list of {name, vmid, role}
) -> list[dict]:
    """
    Generate the full secret_registry entries list for bootstrap-state.json.
    All KeePass paths follow the naming convention automatically.
    """
    h = hostname
    r = kp_root
    entries = []

    # Host root password
    entries.append({
        "id": f"{h}-root-password",
        "description": f"Proxmox host root password ({h})",
        "keepass_path": f"{r}/{h}/root-password",
        "owning_cell": cell_id,
        "secret_type": "password",
        "required_by": [f"host:{h}"],
        "required_for": ["ssh-access", "pve-api-auth"],
        "rotation_schedule": "annually",
        "recovery_path": None,
    })

    # Host OpenTofu API token
    entries.append({
        "id": f"{h}-api-token-tofu",
        "description": f"Proxmox API token for OpenTofu ({h})",
        "keepass_path": f"{r}/{h}/api-token-tofu",
        "owning_cell": cell_id,
        "secret_type": "api-token",
        "required_by": [f"host:{h}"],
        "required_for": ["opentofu-execution"],
        "rotation_schedule": "annually",
        "recovery_path": None,
    })

    # Per-VM SSH deploy keys and initial passwords
    for vm in vms:
        name = vm["name"]
        vmid = vm["vmid"]

        entries.append({
            "id": f"{name}-deploy-key",
            "description": f"SSH deploy key for {name} VM",
            "keepass_path": f"{r}/ssh/deploy-keys/{name}",
            "owning_cell": cell_id,
            "secret_type": "ssh-private-key",
            "required_by": [f"vm:{name}"],
            "required_for": ["ansible-execution"],
            "rotation_schedule": None,
            "recovery_path": None,
        })

        entries.append({
            "id": f"vm-{name}-password",
            "description": f"Initial OS user password for {name} (VM {vmid})",
            "keepass_path": f"{r}/vms/{vmid}-{name}/password",
            "owning_cell": cell_id,
            "secret_type": "password",
            "required_by": [f"vm:{name}"],
            "required_for": ["first-boot-access"],
            "rotation_schedule": None,
            "recovery_path": None,
        })

    return entries


def dns_registry_entries(
    hostname: str,
    host_ip: str,
    search_domain: str,
    vms: list[dict],  # list of {name, vmid, initial_ip}
) -> list[dict]:
    """Generate DNS registry entries for host and all VMs."""
    sd = search_domain
    entries = [
        {
            "hostname": f"{hostname}.{sd}",
            "ip": host_ip,
            "vmid": None,
            "role": "proxmox-host",
            "notes": None,
        }
    ]
    for vm in vms:
        entries.append({
            "hostname": f"{vm['name']}.{sd}",
            "ip": vm["initial_ip"],
            "vmid": vm["vmid"],
            "role": vm.get("role", vm["name"]),
            "notes": None,
        })
    return entries


# ---------------------------------------------------------------------------
# KeePass database discovery
# ---------------------------------------------------------------------------

def discover_keepass_databases() -> list[str]:
    """
    Search for KeePass database files (.kdbx) in common locations.

    Resolution order:
      1. KeePassXC recently-opened databases (most likely to be the right one)
      2. Common filesystem locations for the current user
      3. Mounted drives and cloud sync folders (Windows)

    Returns a list of absolute path strings, deduplicated, most-likely first.
    """
    import os
    import platform

    found: list[str] = []
    seen: set[str] = set()

    def _add(path: str | Path) -> None:
        p = str(Path(path).resolve())
        if p not in seen and Path(p).exists():
            seen.add(p)
            found.append(p)

    system = platform.system()

    # ── 1. KeePassXC recently-opened databases ─────────────────────────────
    config_candidates: list[Path] = []
    if system == "Windows":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            config_candidates.append(
                Path(appdata) / "KeePassXC" / "KeePassXC.ini"
            )
    elif system == "Darwin":
        config_candidates.append(
            Path.home() / "Library" / "Application Support" / "KeePassXC" / "KeePassXC.ini"
        )
    else:  # Linux / BSD
        xdg_config = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
        config_candidates.append(Path(xdg_config) / "KeePassXC" / "KeePassXC.ini")

    for config_path in config_candidates:
        if config_path.exists():
            try:
                text = config_path.read_text(encoding="utf-8", errors="replace")
                in_section = False
                for line in text.splitlines():
                    stripped = line.strip()
                    if stripped == "[LastOpenedDatabases]":
                        in_section = True
                        continue
                    if in_section:
                        if stripped.startswith("["):
                            break  # new section
                        if "DatabasePath=" in stripped:
                            db_path = stripped.split("DatabasePath=", 1)[1].strip()
                            _add(db_path)
            except Exception:
                pass

    # ── 2. Common filesystem locations ────────────────────────────────────
    home = Path.home()
    search_dirs: list[Path] = [
        home,
        home / "Documents",
        home / "Desktop",
    ]

    # Windows: OneDrive, Google Drive, Dropbox
    if system == "Windows":
        for env_var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
            od = os.environ.get(env_var)
            if od:
                search_dirs.extend([Path(od), Path(od) / "Documents"])
        # Dropbox
        dropbox_info = Path(os.environ.get("APPDATA", "")) / "Dropbox" / "info.json"
        if dropbox_info.exists():
            try:
                import json
                info = json.loads(dropbox_info.read_text())
                db_path = info.get("personal", {}).get("path")
                if db_path:
                    search_dirs.append(Path(db_path))
            except Exception:
                pass
        # Check common drive letters for mapped network drives
        for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
            drive = Path(f"{letter}:\\")
            if drive.exists():
                search_dirs.append(drive)
    else:
        # Linux/Mac: Dropbox, Google Drive, Nextcloud
        for cloud_dir in ("Dropbox", "Google Drive", "Nextcloud", "ownCloud"):
            candidate = home / cloud_dir
            if candidate.exists():
                search_dirs.append(candidate)

    for search_dir in search_dirs:
        try:
            for kdbx in search_dir.glob("*.kdbx"):
                _add(kdbx)
        except (PermissionError, OSError):
            pass

    return found


def suggest_keepass_database() -> tuple[str | None, list[str]]:
    """
    Suggest the most likely KeePass database path.

    Returns (best_suggestion, all_candidates).
    best_suggestion is None if nothing found.
    """
    candidates = discover_keepass_databases()
    best = candidates[0] if candidates else None
    return best, candidates


# ---------------------------------------------------------------------------
# CLI preview
# ---------------------------------------------------------------------------

def print_preview(
    cell_id: str,
    hostname: str,
    kp_root: str,
    management_cidr: str,
    vm_names: list[str],
    search_domain: str = "internal",
) -> None:
    print()
    print("=" * 64)
    print("  Naming Convention Preview")
    print("=" * 64)

    # Cell IDs
    variants = suggest_cell_id_variants(hostname)
    print(f"\nCell ID suggestions (from hostname {hostname!r}):")
    for i, v in enumerate(variants):
        marker = " ← recommended" if i == 1 else ""
        print(f"  {v}{marker}")

    # IPs
    vms_stub = [{"name": n, "vmid": 100 + i, "role": n} for i, n in enumerate(vm_names)]
    ips = suggest_ips(management_cidr, vm_names)
    gw = suggest_gateway(management_cidr)
    print(f"\nIP assignments (from CIDR {management_cidr}):")
    print(f"  {hostname}.{search_domain:<30} {ips['host']}  (host)")
    for name, ip in ips["vms"].items():
        print(f"  {name}.{search_domain:<30} {ip}")
    print(f"  gateway                              {gw}")

    # KeePass paths
    kp = keepass_paths(kp_root, hostname, vms_stub)
    print(f"\nKeePass paths (root: {kp_root!r}):")
    for secret_id, path in kp.items():
        print(f"  {secret_id:<35} {path}")

    # SSH public keys
    print("\nSSH public keys (saved to proxmox-bootstrap/ssh/public-keys/):")
    for name in vm_names:
        print(f"  ssh/public-keys/{name}.pub")

    print()


def main() -> None:
    args = sys.argv[1:]
    if not args or "--help" in args or "-h" in args:
        print(__doc__)
        sys.exit(0)

    def _get(flag, default=None):
        if flag in args:
            idx = args.index(flag)
            return args[idx + 1] if idx + 1 < len(args) else default
        return default

    def _get_list(flag):
        if flag in args:
            idx = args.index(flag)
            vals = []
            i = idx + 1
            while i < len(args) and not args[i].startswith("--"):
                vals.append(args[i])
                i += 1
            return vals
        return []

    hostname = _get("--hostname", "pve01")
    kp_root = _get("--kp-root", "Infrastructure")
    cidr = _get("--cidr", "192.168.1.0/24")
    cell_id = _get("--cell-id") or suggest_cell_id(hostname)
    vm_names = _get_list("--vms") or ["infra-bootstrap", "forgejo", "inventory", "assessment-engine"]
    search_domain = _get("--search-domain", "internal")

    print_preview(cell_id, hostname, kp_root, cidr, vm_names, search_domain)


if __name__ == "__main__":
    main()
