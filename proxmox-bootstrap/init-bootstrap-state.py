#!/usr/bin/env python3
"""
Bootstrap state initialization wizard.

Guides an operator through creating a starter bootstrap-state.json for a new
Infrastructure Cell. Discovers what it can from the current environment and
prompts for what cannot be determined automatically.

Run on the Proxmox host OR on an operator workstation with SSH access.

Usage:
    python3 init-bootstrap-state.py
    python3 init-bootstrap-state.py --output /path/to/bootstrap-state.json
    python3 init-bootstrap-state.py --non-interactive  (uses discovered values only)

After running:
    1. Review and edit bootstrap-state.json to add VMs, secrets, DNS entries
    2. Run generate-network-configs.py to generate network-config snippets
    3. Run generate-user-data.py to generate user-data snippets
    4. Populate SSH public keys in generated user-data files
    5. Upload snippets to Proxmox — see SNIPPET-UPLOAD.md

Values marked [DISCOVERED] were read from the current system.
Values marked [DEFAULT] are reasonable defaults for this environment.
Values marked [INPUT] require operator knowledge and cannot be discovered.
"""

import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _load_module(filename: str, mod_name: str):
    spec = importlib.util.spec_from_file_location(
        mod_name, Path(__file__).parent / filename
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------

def _run(cmd: list[str], default: str = "") -> str:
    """Run a shell command and return stripped stdout, or default on failure."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return result.stdout.strip() if result.returncode == 0 else default
    except Exception:
        return default


def discover_hostname() -> tuple[str, str]:
    """Return (hostname, fqdn). Source: hostname command or socket."""
    hostname = _run(["hostname", "-s"]) or socket.gethostname().split(".")[0]
    fqdn = _run(["hostname", "--fqdn"]) or _run(["hostname", "-f"]) or f"{hostname}.local"
    return hostname, fqdn


def discover_timezone() -> str | None:
    """Read timezone from timedatectl or /etc/timezone."""
    tz = _run(["timedatectl", "show", "--property=Timezone", "--value"])
    if tz:
        return tz
    tz_file = Path("/etc/timezone")
    if tz_file.exists():
        return tz_file.read_text().strip()
    # Windows fallback
    import time
    return None


def discover_proxmox_version() -> str | None:
    """Read Proxmox version via pveversion."""
    out = _run(["pveversion", "--verbose"])
    if out:
        for line in out.splitlines():
            if line.startswith("proxmox-ve:"):
                return line.split(":", 1)[1].strip()
    return None


def discover_network_bridges() -> list[str]:
    """Return list of bridge interface names visible on this host."""
    bridges = []
    # Try /sys/class/net first (works on Linux)
    net_path = Path("/sys/class/net")
    if net_path.exists():
        for iface in net_path.iterdir():
            bridge_dir = iface / "bridge"
            if bridge_dir.exists():
                bridges.append(iface.name)
    if not bridges:
        # Fallback: grep ip link output
        out = _run(["ip", "link", "show", "type", "bridge"])
        for line in out.splitlines():
            if ":" in line and not line.startswith(" "):
                name = line.split(":")[1].strip().rstrip("@")
                bridges.append(name)
    return bridges


def discover_proxmox_storage() -> dict:
    """
    Discover Proxmox storage pools via pvesm status.
    Returns dict of content_type -> storage_name for snippets, isos, vm_disks.
    """
    result = {"snippets": None, "isos": None, "vm_disks": None}
    out = _run(["pvesm", "status"])
    if not out:
        return result
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        name, stype = parts[0], parts[1] if len(parts) > 1 else ""
        # pvesm status doesn't show content types; use pvesm list with content filter
        # Just record the storage names and let user pick
    # Simpler: try common defaults
    result["snippets"] = "local:snippets"
    result["isos"] = "local:iso"
    result["vm_disks"] = "local-zfs"
    return result


def discover_vm_interface() -> str:
    """
    Guess the VM NIC interface name.
    VirtIO NICs in Proxmox are typically ens18 (predictable naming).
    """
    # On the Proxmox host itself, we can't see guest interfaces.
    # Return the Proxmox-standard VirtIO name.
    return "ens18"


def discover_management_network() -> dict:
    """
    Discover the management network CIDR and gateway.
    Looks for the default route and its associated interface.
    """
    result = {"cidr": None, "gateway": None, "nameservers": []}

    # Try ip route for default gateway
    out = _run(["ip", "route", "show", "default"])
    for line in out.splitlines():
        parts = line.split()
        if "via" in parts:
            gw_idx = parts.index("via")
            result["gateway"] = parts[gw_idx + 1]

    # Try resolv.conf for nameservers
    resolv = Path("/etc/resolv.conf")
    if resolv.exists():
        for line in resolv.read_text().splitlines():
            if line.startswith("nameserver"):
                ns = line.split()[1]
                result["nameservers"].append(ns)
            if line.startswith("search") or line.startswith("domain"):
                parts = line.split()
                if len(parts) > 1:
                    result["search_domain"] = parts[1]

    return result


# ---------------------------------------------------------------------------
# Interactive prompts
# ---------------------------------------------------------------------------

def _prompt(label: str, default: str | None, tag: str, non_interactive: bool) -> str:
    """Prompt for a value, showing the default. Returns user input or default."""
    if non_interactive:
        val = default or ""
        print(f"  [{tag}] {label}: {val}")
        return val

    display_default = f" [{default}]" if default else ""
    try:
        val = input(f"  {label}{display_default}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        val = ""
    return val if val else (default or "")


def _prompt_list(label: str, default: list, tag: str, non_interactive: bool) -> list:
    """Prompt for a comma-separated list."""
    default_str = ", ".join(default) if default else ""
    raw = _prompt(label + " (comma-separated)", default_str, tag, non_interactive)
    return [x.strip() for x in raw.split(",") if x.strip()]


# ---------------------------------------------------------------------------
# Main wizard
# ---------------------------------------------------------------------------

def build_bootstrap_state(non_interactive: bool = False) -> dict:
    print()
    print("=" * 60)
    print("  Bootstrap State Initialization Wizard")
    print("  Cell: new Infrastructure Cell")
    print("=" * 60)
    print()
    print("Discovering system values...")
    print()

    # --- Discovery phase ---
    hostname, fqdn = discover_hostname()
    timezone = discover_timezone()
    pve_version = discover_proxmox_version()
    bridges = discover_network_bridges()
    storage = discover_proxmox_storage()
    net = discover_management_network()
    vm_iface = discover_vm_interface()

    print(f"  [DISCOVERED] Hostname:         {hostname}")
    print(f"  [DISCOVERED] FQDN:             {fqdn}")
    print(f"  [DISCOVERED] Timezone:         {timezone or '(not found)'}")
    print(f"  [DISCOVERED] Proxmox version:  {pve_version or '(pvesm not available)'}")
    print(f"  [DISCOVERED] Network bridges:  {bridges or '(none found)'}")
    print(f"  [DISCOVERED] Gateway:          {net.get('gateway') or '(not found)'}")
    print(f"  [DISCOVERED] Nameservers:      {net.get('nameservers') or '(not found)'}")
    print()
    print("Answer the following questions. Press Enter to accept a [default].")
    print()

    sn = _load_module("suggest-names.py", "suggest_names")
    roles_mod = _load_module("roles.py", "roles_mod")

    # --- Cell identity ---
    print("--- Cell Identity ---")
    cell_id_variants = sn.suggest_cell_id_variants(hostname)
    suggested_cell_id = cell_id_variants[1]  # e.g. pve01-cell
    print(f"  Suggestions: {', '.join(cell_id_variants)}")
    cell_id = _prompt("Cell ID (unique, kebab-case)", suggested_cell_id, "SUGGESTED", non_interactive)
    print()

    # --- Host identity ---
    print("--- Host Identity ---")
    h_hostname = _prompt("Proxmox hostname", hostname, "DISCOVERED", non_interactive)
    h_fqdn = _prompt("Proxmox FQDN", fqdn, "DISCOVERED", non_interactive)
    print()

    # --- VM defaults ---
    print("--- VM Defaults ---")
    tz = _prompt("Timezone (IANA format)", timezone or "UTC", "DISCOVERED", non_interactive)
    initial_user = _prompt("Default OS username", "ubuntu", "DEFAULT", non_interactive)
    workspace_base = _prompt("Workspace base path (or leave empty to skip)", "/opt", "DEFAULT", non_interactive)
    print()

    # --- Network topology ---
    print("--- Management Network ---")
    gateway = net.get("gateway")
    nameservers = net.get("nameservers", [])
    search_domain = net.get("search_domain", "internal")

    gw = _prompt("Default gateway", gateway, "DISCOVERED", non_interactive)
    cidr_default = f"{gw.rsplit('.', 1)[0]}.0/24" if gw and gw.count('.') == 3 else None
    cidr = _prompt("Management network CIDR", cidr_default, "DERIVED", non_interactive)
    ns_list = _prompt_list("Nameservers", nameservers or ([gw] if gw else []), "DISCOVERED", non_interactive)
    sd = _prompt("Search domain", search_domain, "DISCOVERED", non_interactive)
    iface = _prompt("VM NIC interface name", vm_iface, "DEFAULT", non_interactive)
    print()

    # --- Storage ---
    print("--- Proxmox Storage ---")
    snip_store = _prompt("Snippet storage (pvesm path)", storage["snippets"] or "local:snippets", "DEFAULT", non_interactive)
    iso_store = _prompt("ISO storage (pvesm path)", storage["isos"] or "local:iso", "DEFAULT", non_interactive)
    vm_store = _prompt("VM disk storage (pvesm path)", storage["vm_disks"] or "local-zfs", "DEFAULT", non_interactive)
    print()

    # --- KeePass ---
    print("--- KeePass Configuration ---")
    best_db, db_candidates = sn.suggest_keepass_database()
    if db_candidates:
        print("  KeePass databases found:")
        for i, c in enumerate(db_candidates[:3]):
            print(f"    [{i+1}] {c}")
        kp_hint_default = best_db
    else:
        kp_hint_default = None
    kp_root = _prompt("KeePass root group path", "Infrastructure", "INPUT", non_interactive)
    kp_hint = _prompt("KeePass database path (for reference)", kp_hint_default, "DISCOVERED", non_interactive)
    print()

    # --- Infrastructure role selection ---
    selected_roles = roles_mod.select_roles_interactive(non_interactive)

    # --- VM IP assignment ---
    print("--- VM IP Assignment ---")
    vm_names = [roles_mod.ROLES[r]["default_hostname"] for r in selected_roles]
    vmid_base = 100
    if cidr and "/" in cidr:
        ip_suggestions = sn.suggest_ips(cidr, vm_names)
        host_ip = ip_suggestions["host"]
        print(f"  Suggested host IP:  {host_ip}")
        for name, ip in ip_suggestions["vms"].items():
            print(f"  Suggested {name:<22} {ip}")
        print()
        confirmed_host_ip = _prompt("Proxmox host IP", host_ip, "SUGGESTED", non_interactive)
        vm_ips = {}
        for name, suggested_ip in ip_suggestions["vms"].items():
            vm_ips[name] = _prompt(f"IP for {name}", suggested_ip, "SUGGESTED", non_interactive)
    else:
        confirmed_host_ip = _prompt("Proxmox host IP", None, "INPUT", non_interactive)
        vm_ips = {name: _prompt(f"IP for {name}", None, "INPUT", non_interactive)
                  for name in vm_names}
    print()

    # --- Generate VM definitions from roles ---
    vms = []
    for role_id in selected_roles:
        name = roles_mod.ROLES[role_id]["default_hostname"]
        vmid = roles_mod.vmid_for_role(role_id, vmid_base)
        ip = vm_ips.get(name, "POPULATE")
        vm = roles_mod.generate_vm_stub(role_id, vmid, ip)
        # Apply vm_defaults overrides
        vm["initial_user"] = initial_user
        vm["bridge"] = bridges[0] if bridges else "vmbr0"
        vms.append(vm)

    # --- Generate service contracts from roles ---
    service_contracts = []
    for role_id in selected_roles:
        name = roles_mod.ROLES[role_id]["default_hostname"]
        contract = roles_mod.generate_service_contract_stub(role_id, name)
        if contract:
            service_contracts.append(contract)

    # --- Generate DNS registry from suggested IPs ---
    dns_registry = []
    if confirmed_host_ip:
        dns_registry = sn.dns_registry_entries(
            hostname=h_hostname,
            host_ip=confirmed_host_ip,
            search_domain=sd or "internal",
            vms=[{"name": roles_mod.ROLES[r]["default_hostname"],
                  "vmid": roles_mod.vmid_for_role(r, vmid_base),
                  "initial_ip": vm_ips.get(roles_mod.ROLES[r]["default_hostname"], "POPULATE"),
                  "role": r}
                 for r in selected_roles],
        )

    # --- Generate secret registry from naming convention ---
    secret_registry = sn.secret_registry_entries(
        kp_root=kp_root,
        hostname=h_hostname,
        cell_id=cell_id,
        vms=[{"name": roles_mod.ROLES[r]["default_hostname"],
              "vmid": roles_mod.vmid_for_role(r, vmid_base),
              "role": r}
             for r in selected_roles],
    )

    # Show naming convention preview before writing
    sn.print_preview(
        cell_id=cell_id,
        hostname=h_hostname,
        kp_root=kp_root,
        management_cidr=cidr or "192.168.1.0/24",
        vm_names=vm_names,
        search_domain=sd or "internal",
    )

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "schema_version": "1.0",
        "cell_id": cell_id,
        "declared_at": now,
        "notes": f"Generated by init-bootstrap-state.py on {now}",

        "host_identity": {
            "hostname": h_hostname,
            "fqdn": h_fqdn,
            "proxmox_version": pve_version,
        },

        "vm_defaults": {
            "timezone": tz,
            "initial_user": initial_user,
            "workspace_base_path": workspace_base or None,
        },

        "storage_config": {
            "snippets": snip_store,
            "isos": iso_store,
            "vm_disks": vm_store,
        },

        "keepass_config": {
            "root_path": kp_root,
            "database_hint": kp_hint or None,
        },

        "network_topology": {
            "management_cidr": cidr or "POPULATE: e.g. 192.168.1.0/24",
            "gateway": gw or "POPULATE: e.g. 192.168.1.1",
            "nameservers": ns_list or ["POPULATE: e.g. 192.168.1.1"],
            "search_domain": sd or None,
            "interface_name": iface,
        },

        # VM definitions generated from selected roles
        "vms": vms,
        "base_images": [],
        "templates": [],
        "provenance_records": [],
        "secrets": secret_registry,
        "dns_registry": dns_registry,
        "service_contracts": service_contracts,

        "hardware_requirements": {
            "vtx_required": True,
            "iommu_required": False,
            "secure_boot_required": False,
            "minimum_ram_gb": None,
            "minimum_cores": None,
            "minimum_storage_gb": None,
            "notes": "Populate after reviewing hardware",
        },

        # Wave-ordered first-boot sequence derived from selected roles
        "first_boot_order": [
            roles_mod.ROLES[r]["default_hostname"]
            for r in sorted(selected_roles, key=lambda r: roles_mod.ROLES[r]["wave"])
        ],
    }


def main() -> None:
    args = sys.argv[1:]
    non_interactive = "--non-interactive" in args
    args = [a for a in args if a != "--non-interactive"]

    if "--output" in args:
        idx = args.index("--output")
        out_path = Path(args[idx + 1])
    else:
        out_path = Path(__file__).parent / "bootstrap-state.json"

    if out_path.exists() and not non_interactive:
        try:
            confirm = input(f"\n  {out_path} already exists. Overwrite? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            confirm = "n"
        if confirm != "y":
            print("  Aborted.")
            sys.exit(0)

    state = build_bootstrap_state(non_interactive=non_interactive)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

    print()
    print("=" * 60)
    print(f"  Written: {out_path}")
    print()
    print("  Next steps:")
    print("  1. Edit bootstrap-state.json — add VMs, secrets, DNS entries")
    print("  2. python3 generate-network-configs.py")
    print("  3. python3 generate-user-data.py")
    print("  4. Populate SSH public keys in generated user-data files")
    print("  5. See SNIPPET-UPLOAD.md for Proxmox upload instructions")
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()
