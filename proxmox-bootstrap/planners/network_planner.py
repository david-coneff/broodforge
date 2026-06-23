#!/usr/bin/env python3
"""
Network planner — Phase A, Layer A.

Validates the declared network topology (metadata/network-topology.yaml) against
what was discovered on the host (discovery/network-report.json).

Catches configuration errors before provisioning:
  - Declared bridge exists on host?
  - Declared management CIDR consistent with host addresses?
  - Declared gateway reachable (in routing table)?
  - Declared DNS servers match resolv.conf?
  - VM NIC interface name matches Proxmox convention?

Usage:
    python3 planners/network_planner.py
    python3 planners/network_planner.py --network discovery/network-report.json
                                         --metadata metadata/network-topology.yaml
                                         --out plans/network-plan.json

Outputs: plans/network-plan.json
"""

import json
import os
import re
import sys
from pathlib import Path

BOOTSTRAP_DIR = Path(__file__).parent.parent


def _load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def _parse_topology_yaml(path: Path) -> dict:
    """
    Parse the fields we need from network-topology.yaml.
    Handles simple key: value pairs; returns dict with discovered values.
    """
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        pass

    # Text fallback: extract known keys
    result = {}
    if not path.exists():
        return result

    text = path.read_text(encoding="utf-8")
    patterns = {
        "management_cidr": r"^\s*cidr:\s*(.+)$",
        "gateway": r"^\s*gateway:\s*(.+)$",
        "vm_nic_interface": r"^\s*vm_nic_interface:\s*(.+)$",
        "search_domain": r"^\s*search_domain:\s*(.+)$",
    }
    for key, pattern in patterns.items():
        m = re.search(pattern, text, re.MULTILINE)
        if m:
            val = m.group(1).split("#")[0].strip().strip('"').strip("'")
            if "POPULATE" not in val:
                result[key] = val

    # Extract nameservers list
    ns_section = re.search(r"nameservers:\s*\n((?:\s*-\s*.+\n?)+)", text)
    if ns_section:
        result["nameservers"] = re.findall(r"-\s*([\d.]+)", ns_section.group(1))

    return result


# ---------------------------------------------------------------------------
# Individual validation checks
# ---------------------------------------------------------------------------

def check_bridge_exists(discovered: dict, declared_bridge: str) -> tuple[str, str]:
    if not declared_bridge or "POPULATE" in declared_bridge:
        return "YELLOW", "No management bridge declared — update network-topology.yaml"
    bridges = [b["name"] for b in discovered.get("bridges", [])]
    if declared_bridge in bridges:
        return "GREEN", f"Bridge '{declared_bridge}' exists on host"
    return "RED", (
        f"Declared bridge '{declared_bridge}' not found on host. "
        f"Discovered bridges: {bridges or '(none)'}"
    )


def check_gateway_reachable(discovered: dict, declared_gw: str) -> tuple[str, str]:
    if not declared_gw or "POPULATE" in declared_gw:
        return "YELLOW", "No gateway declared — update network-topology.yaml"
    routes = discovered.get("routes", [])
    default_gw = discovered.get("default_gateway")
    gateways_in_routes = {r.get("gateway") for r in routes if r.get("gateway")}
    if default_gw == declared_gw:
        return "GREEN", f"Declared gateway {declared_gw} matches default route"
    if declared_gw in gateways_in_routes:
        return "YELLOW", (
            f"Declared gateway {declared_gw} found in routes but is not the default gateway. "
            f"Default: {default_gw}"
        )
    return "RED", (
        f"Declared gateway {declared_gw} not found in routing table. "
        f"Default gateway: {default_gw}"
    )


def check_dns_servers(discovered: dict, declared_ns: list) -> tuple[str, str]:
    if not declared_ns:
        return "YELLOW", "No nameservers declared — update network-topology.yaml"
    declared = set(declared_ns)
    discovered_ns = set(discovered.get("dns_servers", []))
    overlap = declared & discovered_ns
    if overlap == declared:
        return "GREEN", f"All declared nameservers found in resolv.conf: {list(declared)}"
    if overlap:
        missing = declared - discovered_ns
        return "YELLOW", (
            f"Partial DNS match. Missing from resolv.conf: {list(missing)}. "
            f"These will be set via Cloud-Init network-config."
        )
    return "YELLOW", (
        f"Declared nameservers {list(declared)} not in resolv.conf "
        f"(discovered: {list(discovered_ns)}). "
        f"Will be set via Cloud-Init — verify DNS is reachable."
    )


def check_nic_interface(discovered: dict, declared_iface: str) -> tuple[str, str]:
    if not declared_iface or "POPULATE" in declared_iface:
        return "YELLOW", "VM NIC interface not declared — update network-topology.yaml"
    [n["name"] for n in discovered.get("physical_nics", [])]
    # ens18 is the interface name INSIDE VMs, not on the host — we can't verify
    # directly. Check if the Proxmox host has VirtIO-style interface naming.
    if declared_iface.startswith("ens") or declared_iface.startswith("eth"):
        return "GREEN", (
            f"VM NIC interface '{declared_iface}' is conventional for VirtIO NICs. "
            f"(Verified inside VMs after first boot, not verifiable on host.)"
        )
    return "YELLOW", (
        f"VM NIC interface '{declared_iface}' — verify this matches the interface "
        f"name inside VMs after first boot."
    )


def check_management_cidr(discovered: dict, declared_cidr: str,
                           host_ip: str) -> tuple[str, str]:
    if not declared_cidr or "POPULATE" in declared_cidr:
        return "YELLOW", "Management CIDR not declared — update network-topology.yaml"
    if not host_ip or "POPULATE" in host_ip:
        return "YELLOW", "Proxmox host IP not declared — cannot validate CIDR"

    # Check if host_ip is within declared_cidr
    try:
        network_str, prefix_len = declared_cidr.split("/")
        net_parts = network_str.split(".")
        host_parts = host_ip.split(".")
        prefix = int(prefix_len)
        # For /24: check first 3 octets match
        octets_to_check = prefix // 8
        if net_parts[:octets_to_check] == host_parts[:octets_to_check]:
            return "GREEN", f"Host IP {host_ip} is within declared CIDR {declared_cidr}"
        return "YELLOW", (
            f"Host IP {host_ip} may not be within declared CIDR {declared_cidr}. "
            f"Verify the correct subnet."
        )
    except Exception:
        return "YELLOW", f"Could not validate CIDR {declared_cidr!r} — check format"


# ---------------------------------------------------------------------------
# Plan generation
# ---------------------------------------------------------------------------

STATUS_ORDER = {"RED": 0, "YELLOW": 1, "GREEN": 2}


def plan_network(network: dict, topology_meta: dict) -> dict:
    """
    Validate declared network topology against discovered network state.
    """
    findings = []

    def _check(name: str, status: str, message: str) -> None:
        findings.append({"check": name, "status": status, "message": message})

    # Extract declared values
    mgmt = topology_meta.get("management_network") or {}
    cidr = mgmt.get("cidr", "") if isinstance(mgmt, dict) else topology_meta.get("management_cidr", "")
    gateway = mgmt.get("gateway", "") if isinstance(mgmt, dict) else topology_meta.get("gateway", "")
    nameservers = mgmt.get("nameservers", []) if isinstance(mgmt, dict) else topology_meta.get("nameservers", [])

    pve_host = topology_meta.get("proxmox_host") or {}
    host_ip = pve_host.get("ip", "") if isinstance(pve_host, dict) else ""

    bridges_meta = topology_meta.get("bridges") or []
    mgmt_bridge = bridges_meta[0].get("name") if bridges_meta else "vmbr0"

    vm_iface = topology_meta.get("vm_nic_interface", "ens18")

    # Run checks
    _check("Management bridge", *check_bridge_exists(network, mgmt_bridge))
    _check("Default gateway", *check_gateway_reachable(network, gateway))
    _check("DNS servers", *check_dns_servers(network, nameservers))
    _check("VM NIC interface", *check_nic_interface(network, vm_iface))
    _check("Management CIDR", *check_management_cidr(network, cidr, host_ip))

    statuses = [f["status"] for f in findings]
    if "RED" in statuses:
        overall = "RED"
    elif "YELLOW" in statuses:
        overall = "YELLOW"
    else:
        overall = "GREEN"

    # Validated topology: resolved values for generators to use
    validated = {
        "management_cidr": cidr or "UNRESOLVED",
        "gateway": gateway or network.get("default_gateway") or "UNRESOLVED",
        "nameservers": nameservers or network.get("dns_servers", []),
        "management_bridge": mgmt_bridge,
        "vm_nic_interface": vm_iface,
        "host_ip": host_ip or "UNRESOLVED",
    }

    return {
        "generated_at": _now_utc(),
        "overall": overall,
        "findings": findings,
        "validated_topology": validated,
        "discovered_bridges": [b["name"] for b in network.get("bridges", [])],
        "discovered_gateway": network.get("default_gateway"),
        "discovered_dns": network.get("dns_servers", []),
        "red_count": statuses.count("RED"),
        "yellow_count": statuses.count("YELLOW"),
        "green_count": statuses.count("GREEN"),
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
    network_path = BOOTSTRAP_DIR / "discovery" / "network-report.json"
    meta_path = BOOTSTRAP_DIR / "metadata" / "network-topology.yaml"
    out_path = BOOTSTRAP_DIR / "plans" / "network-plan.json"

    i = 0
    while i < len(args):
        if args[i] == "--network" and i + 1 < len(args):
            network_path = Path(args[i + 1]); i += 2
        elif args[i] == "--metadata" and i + 1 < len(args):
            meta_path = Path(args[i + 1]); i += 2
        elif args[i] == "--out" and i + 1 < len(args):
            out_path = Path(args[i + 1]); i += 2
        else:
            i += 1

    if not network_path.exists():
        print(f"Network report not found: {network_path}")
        print("Run: python3 discovery/discover.py --collector network")
        sys.exit(1)

    network = _load_json(network_path)
    topology = _parse_topology_yaml(meta_path) if meta_path.exists() else {}
    plan = plan_network(network, topology)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    print(f"Network plan written: {out_path}  [{plan['overall']}]")
    for f in plan["findings"]:
        marker = {"GREEN": "[OK] ", "YELLOW": "[!!] ", "RED": "[XX] "}[f["status"]]
        print(f"  {marker}{f['check']}: {f['message']}")


if __name__ == "__main__":
    main()
