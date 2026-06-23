#!/usr/bin/env python3
"""
Naming planner — Phase A, Layer A.

Generates all names, IPs, KeePass paths, and repository names for the cell
by applying the naming convention (naming-convention.yaml + suggest-names.py)
to the declared metadata.

This bridges Phase 0 (metadata declarations) to Phase 1 (planning output)
by resolving all names before the generators run. Generators consume
naming-plan.json and never need to compute names independently.

Usage:
    python3 planners/naming_planner.py
    python3 planners/naming_planner.py --cell metadata/cell-identity.yaml
                                        --vms metadata/vm-roles.yaml
                                        --network metadata/network-topology.yaml
                                        --out plans/naming-plan.json

Outputs: plans/naming-plan.json
"""

import importlib.util
import json
import os
import re
import sys
from pathlib import Path

BOOTSTRAP_DIR = Path(__file__).parent.parent


def _load_suggest_names():
    spec = importlib.util.spec_from_file_location(
        "suggest_names", BOOTSTRAP_DIR / "suggest-names.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _parse_yaml_text(path: Path) -> dict:
    """Minimal YAML extraction for the fields we need."""
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        pass
    result = {}
    if not path.exists():
        return result
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        line_clean = line.split("#")[0].strip()
        if ":" in line_clean and not line_clean.startswith("-"):
            key, _, val = line_clean.partition(":")
            val = val.strip().strip('"').strip("'")
            if val and "POPULATE" not in val and not val.startswith("{") and not val.startswith("["):
                try:
                    result[key.strip()] = int(val)
                except ValueError:
                    if val.lower() == "true":
                        result[key.strip()] = True
                    elif val.lower() == "false":
                        result[key.strip()] = False
                    else:
                        result[key.strip()] = val
    return result


def _extract_vms_from_yaml(path: Path) -> list[dict]:
    """Extract VM definitions from vm-roles.yaml."""
    if not path.exists():
        return []
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        vms = []
        for section in ("pre_k3s_vms", "k3s_vms"):
            for vm in data.get(section, []):
                if isinstance(vm, dict):
                    vms.append({
                        "name": vm.get("name", ""),
                        "vmid": vm.get("vmid", 0),
                        "role": vm.get("role", vm.get("name", "")),
                    })
        return vms
    except ImportError:
        pass

    # Text fallback: extract vmid and name pairs
    text = path.read_text(encoding="utf-8")
    vms = []
    current_vmid = None
    current_name = None
    for line in text.splitlines():
        clean = line.split("#")[0].strip()
        m_vmid = re.search(r"vmid:\s*(\d+)", clean)
        m_name = re.search(r"name:\s*(\S+)", clean)
        if m_vmid:
            if current_vmid and current_name:
                vms.append({"name": current_name, "vmid": current_vmid, "role": current_name})
            current_vmid = int(m_vmid.group(1))
            current_name = None
        if m_name:
            current_name = m_name.group(1).strip('"').strip("'")
    if current_vmid and current_name:
        vms.append({"name": current_name, "vmid": current_vmid, "role": current_name})
    return vms


def plan_naming(
    cell_meta: dict,
    vms_meta: list[dict],
    network_meta: dict,
    naming_meta: dict,
) -> dict:
    """
    Generate the complete naming plan for a cell.

    Parameters
    ----------
    cell_meta : dict     Parsed cell-identity.yaml
    vms_meta : list      List of {name, vmid, role} from vm-roles.yaml
    network_meta : dict  Parsed network-topology.yaml
    naming_meta : dict   Parsed naming-convention.yaml

    Returns
    -------
    dict — naming-plan.json structure
    """
    sn = _load_suggest_names()
    errors = []
    warnings = []

    cell_id = cell_meta.get("cell_id", "unknown-cell")
    hostname = (cell_meta.get("host_identity") or {}).get(
        "hostname", cell_meta.get("hostname", "pve01")
    )
    if isinstance(hostname, str) and "POPULATE" in hostname:
        hostname = "pve01"
        warnings.append("Proxmox hostname not set — using default 'pve01'")

    # KeePass root from cell metadata or naming convention
    kp_config = cell_meta.get("keepass_config") or {}
    kp_root = (
        kp_config.get("root_path")
        or (naming_meta.get("keepass_paths") or {}).get("root")
        or "Infrastructure"
    )
    if isinstance(kp_root, str) and "POPULATE" in kp_root:
        kp_root = "Infrastructure"
        warnings.append("KeePass root path not set — using default 'Infrastructure'")

    # Management CIDR
    mgmt = network_meta.get("management_network") or {}
    cidr = mgmt.get("cidr", "") if isinstance(mgmt, dict) else network_meta.get("management_cidr", "")
    search_domain = mgmt.get("search_domain", "internal") if isinstance(mgmt, dict) else "internal"
    if isinstance(cidr, str) and "POPULATE" in cidr:
        cidr = "192.168.1.0/24"
        warnings.append("Management CIDR not set — using placeholder 192.168.1.0/24")

    vm_names = [vm["name"] for vm in vms_meta]

    # ── IP assignments ────────────────────────────────────────────────────────
    try:
        ip_plan = sn.suggest_ips(cidr, vm_names) if cidr and "/" in cidr else {}
        host_ip = ip_plan.get("host", "UNRESOLVED")
        vm_ips = ip_plan.get("vms", {})
        prefix = ip_plan.get("prefix", "/24")
    except Exception as e:
        errors.append(f"IP planning failed: {e}")
        host_ip = "UNRESOLVED"
        vm_ips = {name: "UNRESOLVED" for name in vm_names}
        prefix = "/24"

    # ── VM declarations ───────────────────────────────────────────────────────
    vm_declarations = []
    for vm in vms_meta:
        name = vm["name"]
        vmid = vm["vmid"]
        ip = vm_ips.get(name, "UNRESOLVED")
        hostname_fqdn = f"{name}.{search_domain}"
        vm_declarations.append({
            "name": name,
            "vmid": vmid,
            "role": vm.get("role", name),
            "hostname": name,
            "fqdn": hostname_fqdn,
            "ip": ip,
            "cidr_notation": f"{ip}{prefix}" if ip != "UNRESOLVED" else "UNRESOLVED",
        })

    # ── KeePass paths ─────────────────────────────────────────────────────────
    try:
        kp_paths = sn.keepass_paths(kp_root, hostname, vms_meta)
    except Exception as e:
        errors.append(f"KeePass path generation failed: {e}")
        kp_paths = {}

    # ── Secret registry entries ───────────────────────────────────────────────
    try:
        secret_entries = sn.secret_registry_entries(kp_root, hostname, cell_id, vms_meta)
    except Exception as e:
        errors.append(f"Secret registry generation failed: {e}")
        secret_entries = []

    # ── DNS registry entries ──────────────────────────────────────────────────
    try:
        dns_entries = sn.dns_registry_entries(
            hostname=hostname,
            host_ip=host_ip,
            search_domain=search_domain,
            vms=[{**vm, "initial_ip": vm_ips.get(vm["name"], "UNRESOLVED")}
                 for vm in vms_meta],
        )
    except Exception as e:
        errors.append(f"DNS registry generation failed: {e}")
        dns_entries = []

    # ── Repository names ──────────────────────────────────────────────────────
    repo_purposes = ["bootstrap", "infrastructure", "ansible",
                     "platform-config", "docs", "assessment-history"]
    repo_names = {
        purpose: f"{cell_id}-{purpose}" for purpose in repo_purposes
    }

    # ── Archive prefix ────────────────────────────────────────────────────────
    archive_prefix = cell_id

    return {
        "generated_at": _now_utc(),
        "cell_id": cell_id,
        "hostname": hostname,
        "fqdn": f"{hostname}.{search_domain}",
        "kp_root": kp_root,
        "management_cidr": cidr,
        "search_domain": search_domain,
        "host_ip": host_ip,
        "vms": vm_declarations,
        "keepass_paths": kp_paths,
        "secret_registry": secret_entries,
        "dns_registry": dns_entries,
        "repository_names": repo_names,
        "archive_prefix": archive_prefix,
        "warnings": warnings,
        "errors": errors,
    }


def _now_utc() -> str:
    from datetime import datetime, timedelta, timezone
    utc = datetime.now(timezone.utc)
    local = utc + timedelta(hours=int(os.environ.get("LOCAL_TZ_OFFSET", "0")))
    tz_name = os.environ.get("LOCAL_TZ_NAME", "UTC")
    if tz_name == "UTC":
        return utc.strftime("%Y-%m-%d %H:%M:%S UTC")
    return (f"{utc.strftime('%Y-%m-%d %H:%M:%S')} UTC "
            f"({local.strftime('%Y-%m-%d %H:%M:%S')} {tz_name})")


def main() -> None:
    args = sys.argv[1:]
    cell_path = BOOTSTRAP_DIR / "metadata" / "cell-identity.yaml"
    vms_path = BOOTSTRAP_DIR / "metadata" / "vm-roles.yaml"
    network_path = BOOTSTRAP_DIR / "metadata" / "network-topology.yaml"
    naming_path = BOOTSTRAP_DIR / "metadata" / "naming-convention.yaml"
    out_path = BOOTSTRAP_DIR / "plans" / "naming-plan.json"

    i = 0
    while i < len(args):
        if args[i] == "--cell" and i + 1 < len(args):
            cell_path = Path(args[i + 1]); i += 2
        elif args[i] == "--vms" and i + 1 < len(args):
            vms_path = Path(args[i + 1]); i += 2
        elif args[i] == "--network" and i + 1 < len(args):
            network_path = Path(args[i + 1]); i += 2
        elif args[i] == "--out" and i + 1 < len(args):
            out_path = Path(args[i + 1]); i += 2
        else:
            i += 1

    cell_meta = _parse_yaml_text(cell_path) if cell_path.exists() else {}
    vms_meta = _extract_vms_from_yaml(vms_path) if vms_path.exists() else []
    network_meta = _parse_yaml_text(network_path) if network_path.exists() else {}
    naming_meta = _parse_yaml_text(naming_path) if naming_path.exists() else {}

    plan = plan_naming(cell_meta, vms_meta, network_meta, naming_meta)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    print(f"Naming plan written: {out_path}")
    print(f"  Cell: {plan['cell_id']}  Host: {plan['hostname']}  "
          f"KeePass root: {plan['kp_root']}")
    for vm in plan["vms"]:
        print(f"  VM {vm['vmid']:>3}: {vm['name']:<22} {vm['ip']}")
    for w in plan["warnings"]:
        print(f"  WARNING: {w}")
    for e in plan["errors"]:
        print(f"  ERROR: {e}")


if __name__ == "__main__":
    main()
