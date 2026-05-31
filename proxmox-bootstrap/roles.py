#!/usr/bin/env python3
"""
Infrastructure role catalog for a self-documenting Proxmox cell.

Defines the minimum set of VM roles required for a cell to:
  - Store all repositories (Forgejo)
  - Apply configuration management (infra-bootstrap / Ansible controller)
  - Run assessments and generate documentation (assessment-engine)
  - Reproduce itself from repository state after failure

All three REQUIRED roles must be deployed for the self-documentation loop
to function without operator involvement.

Optional roles extend capability but are not needed for basic operation.

Usage (standalone):
    python3 roles.py                         show catalog
    python3 roles.py --required              show required roles only
    python3 roles.py --generate pve01 100    generate VM stub JSON

Importable by init-bootstrap-state.py and other tooling.
"""

import json
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Role definitions
# ---------------------------------------------------------------------------

ROLES: dict[str, dict] = {

    # ─── Required roles ─────────────────────────────────────────────────────

    "forgejo": {
        "description": "Git hosting — stores all infrastructure, bootstrap, "
                       "configuration, and documentation repositories",
        "required": True,
        "wave": 1,
        "vmid_offset": 1,          # added to vmid_base; wave-ordered
        "default_hostname": "forgejo",
        "extra_packages": ["ca-certificates", "gnupg"],
        "workspace_path": None,
        "service_ports": [{"protocol": "https", "port": 3000,
                           "health_check": "GET /api/healthz"}],
        "startup_after": [],
        "why_required": (
            "Forgejo is the repository server. All repos — infrastructure, "
            "bootstrap, Ansible, assessment engine — are stored here. "
            "The assessment engine pushes generated documentation back to "
            "Forgejo. Without Forgejo, nothing is versioned or stored."
        ),
    },

    "infra-bootstrap": {
        "description": "Ansible controller — provisions and configures all VMs; "
                       "makes the cell reproducible from repository state",
        "required": True,
        "wave": 2,
        "vmid_offset": 0,
        "default_hostname": "infra-bootstrap",
        "extra_packages": ["python3-venv", "ansible-core", "jq"],
        "workspace_path": "/opt/infra",
        "service_ports": [],
        "startup_after": ["forgejo"],
        "why_required": (
            "The Ansible controller applies configuration to all VMs and can "
            "re-provision everything from Forgejo repos after a failure. "
            "Without it, reconstructing VMs after loss requires manual work "
            "and the cell is not self-reproducible."
        ),
    },

    "assessment-engine": {
        "description": "Infrastructure Digital Twin Platform — runs assessments, "
                       "generates documentation, detects drift, pushes docs to Forgejo",
        "required": True,
        "wave": 3,
        "vmid_offset": 3,
        "default_hostname": "assessment-engine",
        "extra_packages": ["python3-venv", "jq"],
        "workspace_path": "/opt/assessment",
        "service_ports": [],
        "startup_after": ["forgejo"],
        "why_required": (
            "This is the documentation system. It runs Tier 1/2 assessments "
            "on a schedule, generates Bootstrap/Recovery/Operational docs, and "
            "pushes them back to Forgejo. Without it, the cell is not "
            "self-documenting — docs must be maintained manually."
        ),
    },

    # ─── Optional roles ──────────────────────────────────────────────────────

    "dns": {
        "description": "Internal DNS server — hostname resolution independent "
                       "of the Proxmox host",
        "required": False,
        "wave": 0,
        "vmid_offset": 10,
        "default_hostname": "dns",
        "extra_packages": [],
        "workspace_path": None,
        "service_ports": [{"protocol": "dns", "port": 53, "health_check": None}],
        "startup_after": [],
        "note": (
            "If not deployed, configure dnsmasq on the Proxmox host "
            "(apt install dnsmasq; add to /etc/dnsmasq.d/). A dedicated DNS "
            "VM is preferable once the cell is stable — it survives host "
            "reboots without dependency on the host's init sequence."
        ),
    },

    "pbs": {
        "description": "Proxmox Backup Server — VM backup and restore; "
                       "provides the recovery capability the assessment engine scores",
        "required": False,
        "wave": 5,
        "vmid_offset": 5,
        "default_hostname": "pbs",
        "extra_packages": [],
        "workspace_path": None,
        "service_ports": [{"protocol": "https", "port": 8007, "health_check": None}],
        "startup_after": [],
        "note": (
            "PBS is often better on separate physical hardware so that a host "
            "failure does not take out both VMs and their backups. A PBS VM on "
            "the same host is acceptable for development but not for production "
            "recovery capability."
        ),
    },

    "monitoring": {
        "description": "Observability stack — metrics, dashboards, and alerting; "
                       "feeds the Digital Twin's Observability State",
        "required": False,
        "wave": 4,
        "vmid_offset": 4,
        "default_hostname": "monitoring",
        "extra_packages": ["ca-certificates", "gnupg", "apt-transport-https"],
        "workspace_path": "/opt/monitoring",
        "service_ports": [
            {"protocol": "https", "port": 3001, "health_check": "GET /api/health"},
        ],
        "startup_after": ["forgejo"],
        "note": (
            "Typically Grafana + Prometheus or Victoria Metrics. Provides "
            "capacity trend data, service health history, and alert delivery. "
            "The assessment engine's Observability State collector queries this."
        ),
    },

    "ipam": {
        "description": "IP Address Management — authoritative source for IP "
                       "assignments; enables dynamic Ansible inventory",
        "required": False,
        "wave": 6,
        "vmid_offset": 6,
        "default_hostname": "ipam",
        "extra_packages": ["ca-certificates", "gnupg"],
        "workspace_path": None,
        "service_ports": [{"protocol": "https", "port": 8080, "health_check": None}],
        "startup_after": ["forgejo"],
        "note": (
            "Typically Netbox or phpIPAM. Provides IPAM/DCIM data for Ansible "
            "dynamic inventory. For simple deployments, static inventory files "
            "in Forgejo are sufficient and no IPAM VM is needed."
        ),
    },
}

# Canonical ordering: required first (by wave), then optional (by wave)
REQUIRED_ROLES = [rid for rid, r in ROLES.items() if r["required"]]
OPTIONAL_ROLES = [rid for rid, r in ROLES.items() if not r["required"]]


# ---------------------------------------------------------------------------
# VM definition generation
# ---------------------------------------------------------------------------

def generate_vm_stub(
    role_id: str,
    vmid: int,
    ip: str,
    template_name: str = "ubuntu-2204-base",
) -> dict:
    """
    Generate a vm_bootstrap entry for a given role.
    The caller supplies vmid and ip (from suggest_ips).
    """
    role = ROLES[role_id]
    hostname = role["default_hostname"]
    snippet_base = "snippets"

    return {
        "vmid": vmid,
        "name": hostname,
        "role": role_id,
        "template_name": template_name,
        "cloudinit": {
            "user_data_path": f"{snippet_base}/user-data/{hostname}.yaml",
            "user_data_hash": None,
            "network_config_path": f"{snippet_base}/network-config/{hostname}.yaml",
            "network_config_hash": None,
            "vendor_data_path": (
                f"{snippet_base}/vendor-data/proxmox-hooks.yaml"
                if role_id == "infra-bootstrap" else None
            ),
            "vendor_data_hash": None,
        },
        "initial_ip": ip,
        "initial_hostname": hostname,
        "bridge": "vmbr0",          # overridden from network topology at generation time
        "initial_user": "ubuntu",   # overridden from vm_defaults at generation time
        "ssh_key_reference": f"{hostname}-deploy-key",
        "password_reference": f"vm-{hostname}-password",
        "extra_packages": list(role["extra_packages"]),
        "workspace_path": role["workspace_path"],
        "notes": None,
    }


def generate_service_contract_stub(role_id: str, vm_name: str) -> dict | None:
    """Generate a service contract stub for a role, or None if no ports."""
    role = ROLES[role_id]
    if not role["service_ports"]:
        return None
    return {
        "service": role_id,
        "vm": vm_name,
        "provided_interfaces": [
            {
                "protocol": p["protocol"],
                "port": p["port"],
                "url_pattern": None,
                "health_check": p.get("health_check"),
            }
            for p in role["service_ports"]
        ],
        "required_interfaces": [],
        "startup_after": list(role["startup_after"]),
        "backup_job": None,
        "secret_references": [],
        "owner": "infrastructure",
    }


def vmid_for_role(role_id: str, vmid_base: int) -> int:
    """Compute the VMID for a role from the base VMID."""
    return vmid_base + ROLES[role_id]["vmid_offset"]


# ---------------------------------------------------------------------------
# Interactive role selection
# ---------------------------------------------------------------------------

def select_roles_interactive(non_interactive: bool = False) -> list[str]:
    """
    Show the role catalog and prompt the operator to select optional roles.
    Returns the full list of selected role IDs (required + chosen optional).
    """
    print()
    print("─" * 64)
    print("  Infrastructure Role Selection")
    print("─" * 64)
    print()
    print("  Required roles (always deployed):")
    for rid in REQUIRED_ROLES:
        role = ROLES[rid]
        print(f"    [REQUIRED] {rid}")
        print(f"               {role['description']}")
    print()
    print("  Optional roles:")
    for rid in OPTIONAL_ROLES:
        role = ROLES[rid]
        print(f"    [ ] {rid}")
        print(f"        {role['description']}")
        if "note" in role:
            # Wrap note at 60 chars
            note = role["note"]
            words = note.split()
            line = "        Note: "
            lines = []
            for word in words:
                if len(line) + len(word) + 1 > 72:
                    lines.append(line)
                    line = "               " + word
                else:
                    line += word + " "
            lines.append(line)
            for l in lines:
                print(l.rstrip())
    print()

    selected = list(REQUIRED_ROLES)

    if non_interactive:
        print("  [non-interactive] Deploying required roles only.")
        return selected

    try:
        raw = input(
            "  Optional roles to add (space-separated, or Enter for none): "
        ).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return selected

    if raw:
        for token in raw.split():
            if token in OPTIONAL_ROLES and token not in selected:
                selected.append(token)
            elif token not in ROLES:
                print(f"  Warning: unknown role {token!r} — skipped")

    # Sort by wave order for display
    selected.sort(key=lambda r: ROLES[r]["wave"])
    print()
    print("  Selected roles:")
    for rid in selected:
        role = ROLES[rid]
        tag = "REQUIRED" if role["required"] else "optional"
        print(f"    [{tag}] wave {role['wave']} — {rid}: {role['description']}")
    return selected


# ---------------------------------------------------------------------------
# CLI preview
# ---------------------------------------------------------------------------

def print_catalog() -> None:
    print()
    print("=" * 64)
    print("  Infrastructure Role Catalog")
    print("=" * 64)
    for rid, role in ROLES.items():
        tag = "REQUIRED" if role["required"] else "optional"
        print(f"\n  [{tag}] {rid}  (wave {role['wave']})")
        print(f"  {role['description']}")
        if role["extra_packages"]:
            print(f"  Packages: {', '.join(role['extra_packages'])}")
        if role.get("service_ports"):
            ports = ", ".join(f"{p['protocol']}:{p['port']}"
                             for p in role["service_ports"])
            print(f"  Ports:    {ports}")
        if role.get("why_required"):
            print(f"  Why:      {role['why_required'][:80]}...")
        if role.get("note"):
            print(f"  Note:     {role['note'][:80]}...")
    print()
    print("  Self-documentation loop:")
    print("    forgejo ← assessment-engine pushes generated docs")
    print("    forgejo ← infra-bootstrap reads repos to provision VMs")
    print("    assessment-engine → runs assessments → generates docs → pushes to forgejo")
    print("    infra-bootstrap → configures assessment-engine → it runs on a schedule")
    print()


def main() -> None:
    args = sys.argv[1:]
    if "--required" in args:
        for rid in REQUIRED_ROLES:
            role = ROLES[rid]
            print(f"{rid}: {role['description']}")
        return
    if "--generate" in args:
        idx = args.index("--generate")
        hostname = args[idx + 1] if idx + 1 < len(args) else "pve01"
        base = int(args[idx + 2]) if idx + 2 < len(args) else 100
        stubs = []
        for rid in REQUIRED_ROLES:
            ip = f"192.168.1.{20 + ROLES[rid]['wave']}"
            stubs.append(generate_vm_stub(rid, vmid_for_role(rid, base), ip))
        print(json.dumps(stubs, indent=2))
        return
    print_catalog()


if __name__ == "__main__":
    main()
