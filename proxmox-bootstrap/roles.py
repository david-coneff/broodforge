#!/usr/bin/env python3
"""
Infrastructure role catalog for a self-documenting Proxmox cell.

Defines the minimum set of VM roles required for a cell to:
  - Store all repositories (Forgejo)
  - Apply configuration management (infra-bootstrap / Ansible controller)
  - Run assessments and generate documentation (assessment-engine)
  - Reproduce itself from repository state after failure

All three REQUIRED roles must be deployed for the self-documentation loop
to function without operator involvement. However, they do not each require a
separate VM. Consolidation modes control how roles are distributed across VMs:

  full          3 VMs — one per required role (maximum isolation)
  recommended   2 VMs — forgejo alone, automation (infra-bootstrap +
                         assessment-engine) combined  [DEFAULT]
  minimal       1 VM  — all three roles on one toolchain VM

For a single-node homelab the node itself is the single point of failure
regardless of VM count. The recommended split gives Forgejo an independent
lifecycle (upgrade without touching automation tools) while sharing the
automation VM between the two periodic-runner roles that have the same
operational pattern and package requirements.

Usage (standalone):
    python3 roles.py                         show catalog
    python3 roles.py --consolidation         show consolidation modes
    python3 roles.py --required              show required roles only
    python3 roles.py --generate pve01 100    generate VM stub JSON

Importable by init-bootstrap-state.py and other tooling.
"""

import json
import sys

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
        "vmid_offset": 0,          # added to vmid_base; forgejo = vmid_base + 0
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

    "operations": {
        "description": "Operations VM — Phase A toolchain runner, Ansible controller, "
                       "emergency shell access when k3s is unavailable",
        "required": True,
        "wave": 2,
        "vmid_offset": 1,
        "default_hostname": "operations",
        "extra_packages": ["python3-venv", "ansible-core", "jq", "git"],
        "workspace_path": "/opt/infra",
        "service_ports": [],
        "startup_after": ["forgejo"],
        "why_required": (
            "Must exist outside k3s to enable recovery when k3s is unavailable. "
            "Ansible playbooks that provision k3s nodes run from here. "
            "Provides emergency access to the bootstrap toolchain when the "
            "intelligence layer (k3s workloads) is offline."
        ),
    },

    "k3s-server": {
        "description": "k3s control plane node — hosts the Kubernetes API server, "
                       "scheduler, controller, and all intelligence-layer workloads",
        "required": True,
        "wave": 3,
        "vmid_offset": 10,
        "default_hostname": "k3s-server-01",
        "extra_packages": ["curl", "open-iscsi", "nfs-common"],
            # open-iscsi + nfs-common: required by Longhorn (Phase 11 storage)
        "workspace_path": None,
        "service_ports": [
            {"protocol": "https", "port": 6443, "health_check": "GET /healthz"},
        ],
        "startup_after": ["forgejo", "operations"],
        "why_required": (
            "k3s provides scheduling, failover, HA, and a rich API surface for "
            "the documentation and assessment engines. The intelligence layer "
            "(documentation engine, assessment engine, recovery generator) runs "
            "as k3s workloads — without k3s, the platform cannot document or "
            "assess itself."
        ),
    },

    # ─── Optional roles ──────────────────────────────────────────────────────

    "k3s-worker": {
        "description": "k3s worker node — dedicated workload scheduling; "
                       "required for multi-node HA (Phase 11)",
        "required": False,
        "wave": 4,
        "vmid_offset": 20,
        "default_hostname": "k3s-worker-01",
        "extra_packages": ["curl", "open-iscsi", "nfs-common"],
        "workspace_path": None,
        "service_ports": [],
        "startup_after": ["k3s-server"],
        "note": (
            "Dedicated worker nodes are added in Phase 9/11 when additional "
            "RAM is available or a second physical host is added. In Phase 3 "
            "(single-node), k3s-server-01 also schedules workloads."
        ),
    },

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
# Consolidation modes
# ---------------------------------------------------------------------------
#
# A consolidation mode maps logical roles to VM names.
# Roles sharing the same VM name are deployed together on one machine.
# The combined VM inherits the union of each role's packages, workspace
# paths, service ports, and startup_after constraints.

CONSOLIDATION_MODES: dict[str, dict] = {
    #
    # v7.0 consolidation applies to PRE-K3S VMs only (forgejo + operations).
    # k3s-server is ALWAYS a separate VM — it hosts the k3s cluster and cannot
    # be merged with service VMs. k3s-worker (optional) is always separate.
    #
    # Total VM count = pre-k3s VMs (per mode) + 1 (k3s-server) + N workers

    "full": {
        "description": "3 VMs: forgejo + operations + k3s-server (max isolation)",
        "detail": (
            "Forgejo, the operations VM, and the k3s-server each run independently. "
            "Forgejo and operations have separate lifecycles — upgrade Forgejo "
            "without touching the operations toolchain. Best when RAM allows "
            "and operational isolation matters."
        ),
        "recommended_for": "16 GB+ RAM, multi-node clusters, maximum isolation",
        "vms": {
            "forgejo":    ["forgejo"],
            "operations": ["operations"],
            "k3s-server-01": ["k3s-server"],
        },
        "vm_order": ["forgejo", "operations", "k3s-server-01"],
    },

    "recommended": {
        "description": "2 VMs: forgejo + operations + k3s-server (2 pre-k3s, 1 k3s)",
        "detail": (
            "Identical to 'full' for v7.0 — forgejo and operations are always "
            "separate because Forgejo must be available before the operations VM "
            "can run Ansible against anything. k3s-server is always its own VM. "
            "This is the default for most homelab setups."
        ),
        "recommended_for": "Most homelab setups — single node, any RAM",
        "vms": {
            "forgejo":    ["forgejo"],
            "operations": ["operations"],
            "k3s-server-01": ["k3s-server"],
        },
        "vm_order": ["forgejo", "operations", "k3s-server-01"],
    },

    "minimal": {
        "description": "2 VMs: toolchain (forgejo + operations) + k3s-server",
        "detail": (
            "Forgejo and the operations VM are merged into one 'toolchain' VM. "
            "k3s-server remains separate (k3s cannot co-locate with Forgejo — "
            "Forgejo must exist before k3s bootstraps). "
            "On a single-node Proxmox host, the node is the true SPOF regardless "
            "of VM count, so merging pre-k3s VMs saves RAM without resilience loss. "
            "Best for development or RAM-constrained setups (< 12 GB)."
        ),
        "recommended_for": "Development, RAM-constrained single node (< 12 GB RAM)",
        "vms": {
            "toolchain":     ["forgejo", "operations"],
            "k3s-server-01": ["k3s-server"],
        },
        "vm_order": ["toolchain", "k3s-server-01"],
    },
}

DEFAULT_CONSOLIDATION = "recommended"


# ---------------------------------------------------------------------------
# Consolidation helpers
# ---------------------------------------------------------------------------

def merge_roles(role_ids: list[str]) -> dict:
    """
    Merge multiple role definitions into a single combined role descriptor.

    Used when two or more roles share a VM. The merged result has:
      - extra_packages: union (deduplicated, preserving insertion order)
      - workspace_paths: list of all non-null workspace paths from component roles
      - service_ports: union from all component roles
      - startup_after: union of external deps (roles NOT in this combined VM)
      - wave: minimum wave of all component roles (determines provisioning order)
      - vmid_offset: minimum vmid_offset of all component roles
    """
    packages: list[str] = []
    workspace_paths: list[str] = []
    service_ports: list[dict] = []
    startup_after: list[str] = []
    waves: list[int] = []
    offsets: list[int] = []
    descriptions: list[str] = []

    for rid in role_ids:
        role = ROLES[rid]
        waves.append(role["wave"])
        offsets.append(role["vmid_offset"])
        descriptions.append(role["description"].split(" — ")[0].split(" -")[0])

        for pkg in role["extra_packages"]:
            if pkg not in packages:
                packages.append(pkg)

        if role["workspace_path"] and role["workspace_path"] not in workspace_paths:
            workspace_paths.append(role["workspace_path"])

        for port in role.get("service_ports", []):
            if port not in service_ports:
                service_ports.append(port)

        for dep in role.get("startup_after", []):
            if dep not in role_ids and dep not in startup_after:
                # Only keep external deps (not roles merged into the same VM)
                startup_after.append(dep)

    return {
        "component_roles": role_ids,
        "description": " + ".join(descriptions),
        "wave": min(waves),
        "vmid_offset": min(offsets),
        "extra_packages": packages,
        "workspace_paths": workspace_paths,  # list, not single path
        "service_ports": service_ports,
        "startup_after": startup_after,
    }


def resolve_consolidation(
    mode: str,
    selected_optional_roles: list[str] | None = None,
) -> list[dict]:
    """
    Resolve a consolidation mode into a list of VM descriptors.

    Each VM descriptor is a dict:
      {
        "vm_name":        str,          hostname for this VM
        "component_roles": [str],       role IDs merged into this VM
        "merged":         dict,         merged role definition
        "vmid_offset":    int,
        "wave":           int,
      }

    Optional roles (dns, monitoring, pbs, ipam) are always one-role-per-VM
    and appended after the required VMs.
    """
    if mode not in CONSOLIDATION_MODES:
        raise ValueError(f"Unknown consolidation mode: {mode!r}. "
                         f"Choose from: {list(CONSOLIDATION_MODES)}")

    config = CONSOLIDATION_MODES[mode]
    vms: list[dict] = []

    for vm_name in config["vm_order"]:
        role_ids = config["vms"][vm_name]
        merged = merge_roles(role_ids)
        vms.append({
            "vm_name": vm_name,
            "component_roles": role_ids,
            "merged": merged,
            "vmid_offset": merged["vmid_offset"],
            "wave": merged["wave"],
        })

    # Append selected optional roles (always separate VMs)
    for rid in (selected_optional_roles or []):
        role = ROLES[rid]
        merged = merge_roles([rid])
        vms.append({
            "vm_name": role["default_hostname"],
            "component_roles": [rid],
            "merged": merged,
            "vmid_offset": role["vmid_offset"],
            "wave": role["wave"],
        })

    # Sort by wave
    vms.sort(key=lambda v: v["wave"])
    return vms


# ---------------------------------------------------------------------------
# VM definition generation
# ---------------------------------------------------------------------------

def generate_vm_stub_from_descriptor(
    descriptor: dict,
    vmid: int,
    ip: str,
    template_name: str = "ubuntu-2204-base",
) -> dict:
    """
    Generate a vm_bootstrap entry from a resolved VM descriptor (from resolve_consolidation).
    Handles both single-role and combined-role VMs.
    """
    vm_name = descriptor["vm_name"]
    merged = descriptor["merged"]
    role_ids = descriptor["component_roles"]

    # Primary role for snippet naming (lowest wave in the combined set)
    sorted(role_ids, key=lambda r: ROLES[r]["wave"])[0]
    snippet_base = "snippets"

    # For combined VMs: vendor-data only if operations (or legacy infra-bootstrap) is one of the roles
    needs_vendor_data = any(r in role_ids for r in ("operations", "infra-bootstrap"))

    # workspace_paths: use the first if only one; multiple need runcmd generation
    workspace_paths = merged.get("workspace_paths", [])

    return {
        "vmid": vmid,
        "name": vm_name,
        "role": "+".join(role_ids) if len(role_ids) > 1 else role_ids[0],
        "component_roles": role_ids,
        "template_name": template_name,
        "cloudinit": {
            "user_data_path": f"{snippet_base}/user-data/{vm_name}.yaml",
            "user_data_hash": None,
            "network_config_path": f"{snippet_base}/network-config/{vm_name}.yaml",
            "network_config_hash": None,
            "vendor_data_path": (
                f"{snippet_base}/vendor-data/proxmox-hooks.yaml"
                if needs_vendor_data else None
            ),
            "vendor_data_hash": None,
        },
        "initial_ip": ip,
        "initial_hostname": vm_name,
        "bridge": "vmbr0",
        "initial_user": "ubuntu",
        "ssh_key_reference": f"{vm_name}-deploy-key",
        "password_reference": f"vm-{vm_name}-password",
        "extra_packages": list(merged["extra_packages"]),
        "workspace_path": workspace_paths[0] if len(workspace_paths) == 1 else None,
        "workspace_paths": workspace_paths,   # all paths for combined VMs
        "notes": (
            f"Combined: {', '.join(role_ids)}" if len(role_ids) > 1 else None
        ),
    }


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
                if role_id in ("operations", "infra-bootstrap") else None
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

def select_consolidation_interactive(
    total_ram_gb: float | None = None,
    non_interactive: bool = False,
) -> str:
    """
    Prompt the operator to choose a consolidation mode.
    Returns the chosen mode key (e.g. 'recommended').
    """
    print()
    print("─" * 64)
    print("  VM Consolidation Mode")
    print("─" * 64)
    print()
    print("  All three required roles can be deployed as separate VMs")
    print("  or combined onto fewer machines.")
    print()

    for key, mode in CONSOLIDATION_MODES.items():
        vm_count = len(mode["vms"])
        default_marker = " [DEFAULT]" if key == DEFAULT_CONSOLIDATION else ""
        print(f"  {key}{default_marker}")
        print(f"    {vm_count} VM(s): {', '.join(mode['vms'].keys())}")
        print(f"    {mode['description']}")
        print(f"    Best for: {mode['recommended_for']}")
        print()

    # Auto-suggest based on RAM if available
    suggestion = DEFAULT_CONSOLIDATION
    if total_ram_gb is not None:
        suggestion = "minimal" if total_ram_gb < 16 else "recommended"
        print(f"  [SUGGESTED based on {total_ram_gb:.0f} GB RAM: {suggestion!r}]")
        print()

    if non_interactive:
        print(f"  [non-interactive] Using: {suggestion}")
        return suggestion

    try:
        raw = input(f"  Choose consolidation mode [{suggestion}]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return suggestion

    chosen = raw if raw in CONSOLIDATION_MODES else suggestion
    print(f"  Selected: {chosen} — {CONSOLIDATION_MODES[chosen]['description']}")
    return chosen


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
            for line_out in lines:
                print(line_out.rstrip())
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
    print("  v7.0 self-documentation loop:")
    print("    forgejo        ← documentation-engine pushes generated docs (k3s workload)")
    print("    forgejo        ← flux-cd pulls manifests and reconciles k3s cluster")
    print("    operations-vm  → runs Ansible to provision k3s nodes → k3s comes up")
    print("    k3s-server-01  → hosts documentation-engine + assessment-engine workloads")
    print("    assessment-engine (k3s) → scores platform → feeds documentation-engine")
    print("    documentation-engine (k3s) → generates docs → pushes to forgejo")
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
        args[idx + 1] if idx + 1 < len(args) else "pve01"
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
