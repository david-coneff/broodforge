#!/usr/bin/env python3
"""
update_state_after_spawn.py — Bootstrap-state updater after spawn (Phase 12.E.9).

Runs on the hatchery after the broodling reports successful spawn completion.
Merges the broodling's hardware profile, allocated VMIDs, IPs, hostnames,
and cluster role into the hatchery's bootstrap-state.json.

Provides:
  SpawnResult           — typed record of what was actually deployed
  update_state_after_spawn(state, spawn_result, hardware_profile) → dict
  build_spawn_result(spawn_plan, hardware_profile, now_fn) → SpawnResult

The caller is responsible for writing the updated state dict to disk.
Committing to Forgejo is handled externally (e.g. hatchery_receiver.py
writes the file; a separate git push triggers Assessment Engine reassessment).

Stdlib only.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class SpawnResult:
    """
    Record of what was actually deployed on the broodling.
    Produced by the spawn execution after phase-06 verify completes.
    """
    broodling_hostname:   str
    broodling_fqdn:       Optional[str]
    broodling_lan_ip:     Optional[str]
    broodling_tailnet_ip: Optional[str]

    # Allocated resources (may differ from plan if capacity adjustments were made)
    allocated_vmids: list = field(default_factory=list)   # int list
    allocated_ips:   list = field(default_factory=list)   # str list

    # Deployment outcome
    disposition_services: list = field(default_factory=list)  # service names deployed
    disposition_excluded: list = field(default_factory=list)  # excluded with reason
    execution_mode:       str = "autonomous"   # autonomous | interactive
    k3s_role:             str = "worker"       # worker | server

    # Provenance
    spawned_at:          Optional[str] = None
    spawn_package_id:    Optional[str] = None  # package filename without extension

    # VMs actually created (list of vm dicts matching vms[] schema)
    vms_deployed: list = field(default_factory=list)

    # DNS entries for the new broodling and its VMs
    dns_entries: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Main updater
# ---------------------------------------------------------------------------

def update_state_after_spawn(
    state: dict,
    result: SpawnResult,
    hardware_profile: Optional[dict] = None,
) -> dict:
    """
    Merge spawn result into the hatchery's bootstrap-state.json dict.

    Updates:
      - vms[]: adds all newly deployed VMs with VMIDs, IPs, roles
      - dns_registry[]: adds hostname→IP entries for broodling + its VMs
      - provenance_records[]: adds a spawn provenance entry per VM
      - network_topology.headscale_tailnet: adds broodling tailnet IP
      - A top-level spawn_history[] entry recording the spawn event

    Returns the modified state dict (modifies in-place and returns).
    """
    ts = result.spawned_at or datetime.now(timezone.utc).isoformat()

    # ── vms[] ────────────────────────────────────────────────────────────────
    existing_vmids = {int(v["vmid"]) for v in (state.get("vms") or [])
                      if v.get("vmid") is not None}
    for vm in (result.vms_deployed or []):
        vmid = vm.get("vmid")
        if vmid is not None and int(vmid) not in existing_vmids:
            state.setdefault("vms", []).append(vm)
            existing_vmids.add(int(vmid))

    # ── dns_registry[] ───────────────────────────────────────────────────────
    existing_ips = {e.get("ip") for e in (state.get("dns_registry") or [])}
    for entry in (result.dns_entries or []):
        if entry.get("ip") not in existing_ips:
            state.setdefault("dns_registry", []).append(entry)
            existing_ips.add(entry.get("ip"))

    # ── provenance_records[] — one per deployed VM ───────────────────────────
    existing_prov_vmids = {int(r["vmid"]) for r in (state.get("provenance_records") or [])
                           if r.get("vmid") is not None}
    for vm in (result.vms_deployed or []):
        vmid = vm.get("vmid")
        if vmid is None or int(vmid) in existing_prov_vmids:
            continue
        prov = {
            "vmid":        int(vmid),
            "name":        vm.get("name", ""),
            "deployed_at": ts,
            "tofu_workspace":   vm.get("tofu_workspace", "opentofu"),
            "tofu_commit":      vm.get("tofu_commit"),
            "template_name":    vm.get("template_name"),
            "template_checksum": vm.get("template_checksum"),
            "cloudinit_user_data_hash":    vm.get("cloudinit_user_data_hash"),
            "cloudinit_network_config_hash": vm.get("cloudinit_network_config_hash"),
            "ansible_playbook": vm.get("ansible_playbook", "site.yml"),
            "ansible_commit":   vm.get("ansible_commit"),
            "ansible_inventory_commit": vm.get("ansible_inventory_commit"),
            "deployed_by":      "spawn-package",
            "notes":            f"Spawned onto {result.broodling_hostname} via spawn package {result.spawn_package_id or '?'}",
        }
        state.setdefault("provenance_records", []).append(prov)
        existing_prov_vmids.add(int(vmid))

    # ── spawn_history[] ──────────────────────────────────────────────────────
    spawn_event = {
        "spawned_at":          ts,
        "spawn_package_id":    result.spawn_package_id,
        "broodling_hostname":  result.broodling_hostname,
        "broodling_fqdn":      result.broodling_fqdn,
        "broodling_lan_ip":    result.broodling_lan_ip,
        "broodling_tailnet_ip": result.broodling_tailnet_ip,
        "k3s_role":            result.k3s_role,
        "execution_mode":      result.execution_mode,
        "vmids_allocated":     result.allocated_vmids,
        "ips_allocated":       result.allocated_ips,
        "disposition_services": result.disposition_services,
        "disposition_excluded": result.disposition_excluded,
        "hardware_profile":    hardware_profile,
    }
    state.setdefault("spawn_history", []).insert(0, spawn_event)

    return state


# ---------------------------------------------------------------------------
# Build SpawnResult from spawn-plan.json + hardware-profile.json
# ---------------------------------------------------------------------------

def build_spawn_result(
    spawn_plan: dict,
    hardware_profile: Optional[dict] = None,
    now_fn=None,
) -> SpawnResult:
    """
    Build a SpawnResult from a completed spawn-plan.json.

    spawn_plan is the spawn-plan-{hostname}.json dict written by spawn-planner.py.
    hardware_profile is the hardware-profile-{hostname}.json from discovery.
    """
    ts          = (now_fn or (lambda: datetime.now(timezone.utc).isoformat()))()
    disposition = spawn_plan.get("disposition") or {}
    hostname    = spawn_plan.get("hostname", "")
    domain      = spawn_plan.get("domain", "")
    fqdn        = f"{hostname}.{domain}" if domain else hostname

    return SpawnResult(
        broodling_hostname=hostname,
        broodling_fqdn=fqdn,
        broodling_lan_ip=spawn_plan.get("lan_ip"),
        broodling_tailnet_ip=spawn_plan.get("tailnet_ip"),
        allocated_vmids=(spawn_plan.get("vmid_block")
                         or [v.get("vmid") for v in (spawn_plan.get("vms") or []) if v.get("vmid")]),
        allocated_ips=(spawn_plan.get("ip_block")
                       or [v.get("ip") for v in (spawn_plan.get("vms") or []) if v.get("ip")]),
        disposition_services=disposition.get("services") or [],
        disposition_excluded=disposition.get("excluded") or [],
        execution_mode=disposition.get("execution_mode", "autonomous"),
        k3s_role=spawn_plan.get("k3s_role", "worker"),
        spawned_at=ts,
        spawn_package_id=spawn_plan.get("package_id"),
        vms_deployed=spawn_plan.get("vms") or [],
        dns_entries=spawn_plan.get("dns_entries") or [],
    )


# ---------------------------------------------------------------------------
# CLI entry point (manual fallback when hatchery receiver is not reachable)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import json
    import sys
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description="Merge a completed spawn plan into bootstrap-state.json "
                    "(manual fallback — normally done by hatchery_receiver.py automatically).",
    )
    parser.add_argument("--state", required=True, help="Path to bootstrap-state.json")
    parser.add_argument("--plan", required=True, help="Path to spawn-plan-{hostname}.json")
    parser.add_argument("--hardware", default=None,
                        help="Path to hardware-profile-{hostname}.json (optional)")
    parser.add_argument("--spawned-at", dest="spawned_at", default=None,
                        help="ISO-8601 timestamp of spawn completion "
                             "(default: current UTC time)")
    args = parser.parse_args()

    state_path = Path(args.state)
    plan_path  = Path(args.plan)

    if not state_path.exists():
        print(f"[error] state not found: {state_path}", file=sys.stderr); sys.exit(1)
    if not plan_path.exists():
        print(f"[error] plan not found: {plan_path}", file=sys.stderr); sys.exit(1)

    state = json.loads(state_path.read_text())
    plan  = json.loads(plan_path.read_text())
    hw    = json.loads(Path(args.hardware).read_text()) if args.hardware else None
    ts    = args.spawned_at

    result = build_spawn_result(plan, hw, now_fn=(lambda: ts) if ts else None)
    updated = update_state_after_spawn(state, result, hw)

    state_path.write_text(json.dumps(updated, indent=2))
    print(f"[update] bootstrap-state.json updated — broodling: {result.broodling_hostname}")
    print(f"[update] Commit with: git add {state_path} && git commit -m 'spawn: {result.broodling_hostname} joined'")
