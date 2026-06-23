#!/usr/bin/env python3
"""
html_spawn_workbook.py — HTML spawn workbook renderer.

Produces a self-contained HTML workbook for spawn execution tracking.
Checkbox behavior: checked → " done" italic, no strikethrough.

Public API:
  build_spawn_workbook_html(spawn_plan, spawn_manifest, hardware_profile) → str

Stdlib only.
"""

from html_base import (
    checkbox_list,
    divider,
    dl,
    h,
    html_page,
    p,
    pre,
    reset_checkbox_counter,
    section,
    table,
)


def _str(v) -> str:
    if v is None:
        return "[UNRESOLVED]"
    if isinstance(v, list):
        return ", ".join(str(x) for x in v) if v else "(none)"
    return str(v)


def _e(text: str) -> str:
    from html import escape
    return escape(str(text))


def _section_overview(plan: dict, manifest: dict, hw: dict) -> str:
    pairs = [
        ("Package ID",      plan.get("package_id") or "?"),
        ("Cell ID",         manifest.get("cell_id") or plan.get("cell_id") or "?"),
        ("Broodling Host",  plan.get("hostname") or "?"),
        ("Execution Mode",  (plan.get("disposition") or {}).get("execution_mode") or "autonomous"),
        ("Network Mode",    (plan.get("disposition") or {}).get("network_mode") or plan.get("network_mode") or "lan"),
        ("Generated",       plan.get("generated_at") or "?"),
    ]
    if hw:
        pairs += [
            ("RAM",     _str(hw.get("ram_gb")) + " GB"),
            ("Disks",   _str(len(hw.get("disks") or []))),
            ("NICs",    _str(len(hw.get("nics") or []))),
        ]
    return section("Overview", dl(pairs), open_=True)


def _section_discovery(hw: dict) -> str:
    if not hw:
        return section("Discovery", p("Hardware profile not available."), open_=False)

    disks = hw.get("disks") or []
    nics  = hw.get("nics") or []

    disk_rows = [[_e(d.get("id") or d.get("name") or "?"),
                  _e(str(d.get("size_gb") or "?")),
                  "SSD" if d.get("rotational") is False else "HDD"]
                 for d in disks]
    nic_rows  = [[_e(n.get("name") or "?"), _e(n.get("mac") or "—"), _e(n.get("speed") or "—")]
                 for n in nics]

    body = ""
    if disk_rows:
        body += h(3, "Disks")
        body += table(["Device", "Size (GB)", "Type"], disk_rows)
    if nic_rows:
        body += h(3, "Network Interfaces")
        body += table(["Name", "MAC", "Speed"], nic_rows)

    items = [
        "All planned disks present",
        "NIC names match spawn plan",
        f"RAM ≥ {hw.get('ram_gb', '?')} GB confirmed",
        "No ZFS pool name conflicts",
        "No bridge name conflicts",
    ]
    body += checkbox_list(items, id_prefix="disc")
    return section("Discovery (Phase 00 pre-flight)", body, open_=True)


def _section_host_bootstrap(plan: dict) -> str:
    hostname = plan.get("hostname") or "?"
    plan.get("network_config") or {}
    zfs = plan.get("zfs_config") or {}

    items = [
        f"Hostname set to {_e(hostname)}",
        "/etc/hosts updated",
        "Network bridges created (ifreload -a)",
        f"ZFS pool created: {_e(zfs.get('pool_name', '?'))}",
        "Proxmox datastore registered: pvesm status",
    ]
    body = checkbox_list(items, id_prefix="host-boot")
    return section("Phase 00 — Host Bootstrap", body, open_=True)


def _section_proxmox_join(plan: dict, manifest: dict) -> str:
    hatchery_addr = (manifest.get("proxmox_cluster") or {}).get("address") or "[HATCHERY-IP]"
    items = [
        f"pvecm add {_e(hatchery_addr)} succeeded",
        "Broodling visible in Proxmox datacenter",
        "Cluster quorum healthy: pvecm status",
    ]
    body = pre(f"pvecm add {hatchery_addr}") + checkbox_list(items, id_prefix="pve-join")
    return section("Phase 01 — Proxmox Cluster Join", body, open_=True)


def _section_vm_provisioning(plan: dict) -> str:
    vms = plan.get("vms") or []

    items = ["OpenTofu apply succeeded"]
    for vm in vms:
        items.append(f"VM {_e(vm.get('name', '?'))} (VMID {vm.get('vmid', '?')}) created")

    body = pre("cd opentofu/ && tofu apply") + checkbox_list(items, id_prefix="vm-prov")
    return section("Phase 02 — VM Provisioning", body, open_=True)


def _section_cloud_init(plan: dict) -> str:
    vms = plan.get("vms") or []

    items = ["Cloud-Init snippets uploaded to Proxmox snippet store"]
    for vm in vms:
        ip = vm.get("lan_ip") or vm.get("ip") or "[IP]"
        items.append(f"VM {_e(vm.get('name', '?'))} reachable: ssh ubuntu@{_e(str(ip))}")

    body = checkbox_list(items, id_prefix="cloudinit")
    return section("Phase 03 — Cloud-Init and VM Startup", body, open_=True)


def _section_k3s_join(plan: dict) -> str:
    disp = plan.get("disposition") or {}
    services = disp.get("services") or []
    k3s_role = "server" if "k3s-server" in services else "worker"

    items = [
        f"k3s {k3s_role} role joined cluster",
        "Node in Ready state: kubectl get nodes",
        "Flux reconciling on this node: flux get all",
    ]
    body = pre(f"ansible-playbook -i inventory/ playbooks/k3s-{k3s_role}.yml") + \
           checkbox_list(items, id_prefix="k3s-join")
    return section("Phase 04 — k3s Cluster Join", body, open_=True)


def _section_validation(plan: dict) -> str:
    items = [
        "All VMs running: qm list",
        "All k3s nodes Ready: kubectl get nodes",
        "Flux reconciled: flux get all",
        "Assessment Engine updated with broodling",
        "bootstrap-state.json updated and committed",
        "Spawn workbook committed to Forgejo",
    ]
    body = checkbox_list(items, id_prefix="final-valid")
    return section("Phase 06 — Final Validation", body, open_=True)


def build_spawn_workbook_html(
    spawn_plan:       dict,
    spawn_manifest:   dict,
    hardware_profile: dict | None = None,
) -> str:
    """Build a self-contained HTML spawn workbook."""
    reset_checkbox_counter()

    cell_id   = spawn_manifest.get("cell_id") or spawn_plan.get("cell_id") or "unknown"
    hostname  = spawn_plan.get("hostname") or "unknown"
    gen_at    = spawn_plan.get("generated_at") or "?"
    hw        = hardware_profile or {}

    title = f"Spawn Workbook — {hostname}"
    meta  = f"Cell: {cell_id}  |  Generated: {gen_at}"

    body = ""
    body += p("This workbook tracks spawn execution progress. "
              "Check each item as it completes. State saved in browser (localStorage).")
    body += divider()
    body += _section_overview(spawn_plan, spawn_manifest, hw)
    body += _section_discovery(hw)
    body += _section_host_bootstrap(spawn_plan)
    body += _section_proxmox_join(spawn_plan, spawn_manifest)
    body += _section_vm_provisioning(spawn_plan)
    body += _section_cloud_init(spawn_plan)
    body += _section_k3s_join(spawn_plan)
    body += _section_validation(spawn_plan)

    return html_page(title, body, doc_id=f"spawn-workbook-{cell_id}-{hostname}", meta=meta)
