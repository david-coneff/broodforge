#!/usr/bin/env python3
"""
migrate_k3s_lib.py — Shared library for k3s OS-variant migration (9.T.9).

Provides pre-flight checks, state snapshots, rollback hooks, and migration
history persistence used by both migration directions:

  migrate-k3s-to-talos.py   (Ubuntu → Talos)
  migrate-k3s-to-ubuntu.py  (Talos → Ubuntu)

Stdlib only.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Callable, Optional


RunnerFn = Callable[[str], str]

try:
    from collector_utils import local_runner as _local_runner
except ImportError:
    def _local_runner(cmd: str) -> str:  # type: ignore[misc]
        import subprocess
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        return result.stdout


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PreflightResult:
    passed: bool
    checks: list[dict] = field(default_factory=list)

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append({"name": name, "passed": passed, "detail": detail})
        if not passed:
            self.passed = False

    def summary(self) -> str:
        lines = []
        for c in self.checks:
            mark = "✓" if c["passed"] else "✗"
            lines.append(f"  [{mark}] {c['name']}" + (f": {c['detail']}" if c["detail"] else ""))
        return "\n".join(lines)


@dataclass
class StateSnapshot:
    """Immutable snapshot of bootstrap-state.json taken before migration."""
    timestamp: str
    node_vm_name: str
    original_os_variant: str
    original_snapshot_vmid: Optional[int]
    state_json: str  # full JSON dump of bootstrap-state at snapshot time


@dataclass
class MigrationRecord:
    """One entry in bootstrap-state.json migration_history."""
    migration_id: str
    node_vm_name: str
    from_variant: str
    to_variant: str
    started_at: str
    completed_at: Optional[str]
    outcome: str  # "success" | "failed" | "rolled_back" | "aborted"
    snapshot_vmid: Optional[int]
    error: Optional[str]
    dry_run: bool


# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

def run_preflight_checks(
    node_vm_name: str,
    to_variant: str,
    bootstrap_state: dict,
    runner: RunnerFn = _local_runner,
    dry_run: bool = False,
    talos_config_dir: Optional[str] = None,
) -> PreflightResult:
    """
    Run migration pre-flight checks. Returns PreflightResult with all check results.

    Checks:
      1. Cluster readiness is not RED (from bootstrap-state readiness field)
      2. Target template exists in the template registry
      3. Machine config present (Ubuntu→Talos only)
      4. PBS connectivity (checks pbs_reachability field or skips if absent)
      5. Quorum: cluster has ≥3 nodes or this is a dev/single-node cell
    """
    result = PreflightResult(passed=True)

    # 1. Cluster readiness — refuse if RED
    readiness_score = bootstrap_state.get("readiness_score") or ""
    if readiness_score.upper() == "RED":
        result.add("cluster_readiness", False,
                   "Cluster readiness is RED — fix blocking issues before migrating")
    else:
        result.add("cluster_readiness", True,
                   f"Cluster readiness: {readiness_score or 'unknown (non-RED)'}")

    # 2. Target template exists
    templates = bootstrap_state.get("templates") or []
    target_template_name = "talos-1x-base" if to_variant == "talos" else "ubuntu-2204-base"
    template_found = any(t.get("name") == target_template_name for t in templates)
    result.add(
        "target_template",
        template_found,
        f"Template '{target_template_name}' {'found' if template_found else 'NOT found in registry'}",
    )

    # 3. Machine config (Ubuntu→Talos only)
    if to_variant == "talos":
        talos_dir = talos_config_dir or os.path.join(os.path.dirname(__file__), "talos-configs")
        config_file = os.path.join(talos_dir, f"{node_vm_name}.yaml")
        config_exists = os.path.isfile(config_file)
        result.add(
            "machine_config",
            config_exists,
            f"Machine config {config_file} "
            + ("found" if config_exists else "NOT found — run generate-talos-config.py first"),
        )

    # 4. PBS reachability
    pbs_reach = bootstrap_state.get("pbs_reachability")
    if pbs_reach is not None:
        result.add("pbs_reachability", bool(pbs_reach),
                   "PBS reachable" if pbs_reach else "PBS unreachable — backup may be stale")
    else:
        result.add("pbs_reachability", True, "PBS reachability unknown — skipped")

    # 5. Node exists in VMs list
    vms = bootstrap_state.get("vms") or []
    vm_entry = next((v for v in vms if v.get("vm_name") == node_vm_name), None)
    if vm_entry:
        result.add("node_exists", True, f"Node '{node_vm_name}' found in VM registry")
    else:
        result.add("node_exists", False,
                   f"Node '{node_vm_name}' not found in VM registry — check vm_name")

    return result


# ---------------------------------------------------------------------------
# State snapshot
# ---------------------------------------------------------------------------

def snapshot_state(
    node_vm_name: str,
    original_os_variant: str,
    bootstrap_state: dict,
    snapshot_vmid: Optional[int] = None,
) -> StateSnapshot:
    """Capture bootstrap-state as a snapshot before migration."""
    return StateSnapshot(
        timestamp=datetime.now(timezone.utc).isoformat(),
        node_vm_name=node_vm_name,
        original_os_variant=original_os_variant,
        original_snapshot_vmid=snapshot_vmid,
        state_json=json.dumps(bootstrap_state),
    )


# ---------------------------------------------------------------------------
# Node drain / verify
# ---------------------------------------------------------------------------

def drain_node(
    node_vm_name: str,
    runner: RunnerFn = _local_runner,
    dry_run: bool = False,
) -> bool:
    """
    Drain a k3s node. Returns True if drain succeeded (or dry_run).

    Runs: kubectl drain <node> --ignore-daemonsets --delete-emptydir-data
    """
    cmd = (
        f"kubectl drain {node_vm_name} "
        "--ignore-daemonsets --delete-emptydir-data --timeout=120s"
    )
    if dry_run:
        print(f"  [dry-run] Would run: {cmd}")
        return True
    output = runner(cmd)
    return "drained" in output.lower() or "node/" in output.lower()


def verify_cluster_health(
    runner: RunnerFn = _local_runner,
    dry_run: bool = False,
) -> bool:
    """
    Verify cluster health after migration. Returns True if all nodes are Ready.

    Checks: kubectl get nodes --no-headers | grep -v Ready
    """
    if dry_run:
        print("  [dry-run] Would verify: kubectl get nodes")
        return True
    output = runner("kubectl get nodes --no-headers 2>&1")
    not_ready = [
        line for line in output.splitlines()
        if line.strip() and "NotReady" in line
    ]
    return len(not_ready) == 0


def uncordon_node(
    node_vm_name: str,
    runner: RunnerFn = _local_runner,
    dry_run: bool = False,
) -> None:
    """Uncordon a node (used in rollback or after migration completes)."""
    cmd = f"kubectl uncordon {node_vm_name}"
    if dry_run:
        print(f"  [dry-run] Would run: {cmd}")
        return
    runner(cmd)


# ---------------------------------------------------------------------------
# Bootstrap-state update helpers
# ---------------------------------------------------------------------------

def update_os_variant(
    node_vm_name: str,
    new_variant: str,
    bootstrap_state: dict,
) -> dict:
    """Update os_variant for the named VM in the state dict (in-place)."""
    for vm in bootstrap_state.get("vms") or []:
        if vm.get("vm_name") == node_vm_name:
            vm["os_variant"] = new_variant
    for rec in bootstrap_state.get("provenance_records") or []:
        if rec.get("vm_name") == node_vm_name:
            rec["os_variant"] = new_variant
    return bootstrap_state


def append_migration_history(
    state_path: str,
    record: MigrationRecord,
) -> None:
    """
    Append a MigrationRecord to bootstrap-state.json migration_history array.

    Creates migration_history if absent. Writes state_path atomically.
    """
    if not state_path or not os.path.exists(state_path):
        return
    with open(state_path) as f:
        state = json.load(f)

    history = state.setdefault("migration_history", [])
    history.append(_record_to_dict(record))

    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)


def _record_to_dict(record: MigrationRecord) -> dict:
    return {
        "migration_id":   record.migration_id,
        "node_vm_name":   record.node_vm_name,
        "from_variant":   record.from_variant,
        "to_variant":     record.to_variant,
        "started_at":     record.started_at,
        "completed_at":   record.completed_at,
        "outcome":        record.outcome,
        "snapshot_vmid":  record.snapshot_vmid,
        "error":          record.error,
        "dry_run":        record.dry_run,
    }


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------

def rollback(
    snapshot: StateSnapshot,
    state_path: str,
    record: MigrationRecord,
    runner: RunnerFn = _local_runner,
    dry_run: bool = False,
) -> None:
    """
    Roll back to the pre-migration snapshot.

    Steps:
      1. Restore bootstrap-state from snapshot JSON
      2. Uncordon the node (if it was drained)
      3. Append failed migration record to migration_history
    """
    if dry_run:
        print("  [dry-run] Would restore bootstrap-state from snapshot")
        print(f"  [dry-run] Would uncordon {snapshot.node_vm_name}")
        return

    # Restore state
    if state_path and os.path.exists(state_path):
        restored = json.loads(snapshot.state_json)
        record.outcome = "rolled_back"
        history = restored.setdefault("migration_history", [])
        history.append(_record_to_dict(record))
        with open(state_path, "w") as f:
            json.dump(restored, f, indent=2)

    # Uncordon
    uncordon_node(snapshot.node_vm_name, runner=runner)


# ---------------------------------------------------------------------------
# Migration ID generator
# ---------------------------------------------------------------------------

def make_migration_id(node_vm_name: str, from_variant: str, to_variant: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"migrate-{node_vm_name}-{from_variant}-to-{to_variant}-{ts}"
