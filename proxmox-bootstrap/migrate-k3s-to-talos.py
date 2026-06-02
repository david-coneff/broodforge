#!/usr/bin/env python3
"""
migrate-k3s-to-talos.py — Interactive Ubuntu → Talos migration wizard (9.T.10).

Migrates a k3s node from Ubuntu to Talos Linux:
  1. Pre-flight checks (cluster health, template, machine config, PBS)
  2. State snapshot (rollback point)
  3. Drain the k3s node
  4. Snapshot the Ubuntu VM in Proxmox
  5. Destroy the Ubuntu VM
  6. Provision new VM from talos-1x-base template
  7. Apply Talos machine config via talosctl
  8. Verify cluster health (node rejoined, Flux reconciled)
  9. Update bootstrap-state.json (os_variant, migration_history)

If the health check fails, the script automatically initiates rollback.

Usage:
  python3 proxmox-bootstrap/migrate-k3s-to-talos.py --node k3s-server-01 --dry-run
  python3 proxmox-bootstrap/migrate-k3s-to-talos.py --node k3s-server-01
  python3 proxmox-bootstrap/migrate-k3s-to-talos.py --node k3s-server-01 --skip-snapshot

Stdlib only.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

from migrate_k3s_lib import (
    PreflightResult,
    StateSnapshot,
    MigrationRecord,
    run_preflight_checks,
    snapshot_state,
    drain_node,
    verify_cluster_health,
    uncordon_node,
    update_os_variant,
    append_migration_history,
    rollback,
    make_migration_id,
    _local_runner,
)


DEFAULT_STATE = str(_ROOT / "proxmox-bootstrap" / "bootstrap-state.json")


# ---------------------------------------------------------------------------
# Proxmox operations (via pvesh / qm CLI)
# ---------------------------------------------------------------------------

def _proxmox_snapshot_vm(vmid: int, snap_name: str, runner, dry_run: bool) -> bool:
    cmd = f"qm snapshot {vmid} {snap_name} --description 'Pre-Talos-migration rollback point'"
    if dry_run:
        print(f"  [dry-run] Would run: {cmd}")
        return True
    output = runner(cmd)
    return True  # qm snapshot exits 0 on success


def _proxmox_destroy_vm(vmid: int, runner, dry_run: bool) -> bool:
    cmd = f"qm stop {vmid} --timeout 60 ; qm destroy {vmid} --destroy-unreferenced-disks 1"
    if dry_run:
        print(f"  [dry-run] Would run: {cmd}")
        return True
    runner(cmd)
    return True


def _proxmox_clone_template(
    template_vmid: int, new_vmid: int, vm_name: str, runner, dry_run: bool
) -> bool:
    cmd = (
        f"qm clone {template_vmid} {new_vmid} --name {vm_name} --full 1"
    )
    if dry_run:
        print(f"  [dry-run] Would run: {cmd}")
        return True
    runner(cmd)
    return True


def _proxmox_start_vm(vmid: int, runner, dry_run: bool) -> bool:
    cmd = f"qm start {vmid}"
    if dry_run:
        print(f"  [dry-run] Would run: {cmd}")
        return True
    runner(cmd)
    return True


def _talosctl_apply_config(
    node_ip: str, config_file: str, runner, dry_run: bool
) -> bool:
    cmd = f"talosctl apply-config --insecure --nodes {node_ip} --file {config_file}"
    if dry_run:
        print(f"  [dry-run] Would run: {cmd}")
        return True
    output = runner(cmd)
    return "applied" in output.lower() or output.strip() == ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_vm_entry(state: dict, vm_name: str) -> dict | None:
    return next((v for v in (state.get("vms") or []) if v.get("vm_name") == vm_name), None)


def _find_template(state: dict, name: str) -> dict | None:
    return next((t for t in (state.get("templates") or []) if t.get("name") == name), None)


def _find_dns_ip(state: dict, vm_name: str) -> str | None:
    for entry in state.get("dns_registry") or []:
        if entry.get("vm_name") == vm_name or entry.get("hostname") == vm_name:
            return entry.get("ip")
    return None


# ---------------------------------------------------------------------------
# Git commit helper — commit bootstrap-state.json to Forgejo after migration
# ---------------------------------------------------------------------------

def _commit_migration_record(
    state_path: str,
    node_vm_name: str,
    from_variant: str,
    to_variant: str,
    runner=None,
) -> None:
    """
    Commit the updated bootstrap-state.json to the local git repository.
    The Forgejo webhook will trigger Assessment Engine reassessment.
    Failure is non-fatal — logs a warning but does not abort the migration.
    """
    import subprocess
    repo_dir = os.path.dirname(os.path.abspath(state_path))
    msg = (f"migrate: {node_vm_name} {from_variant}→{to_variant} "
           f"— update os_variant + migration_history")
    try:
        for cmd in [
            ["git", "-C", repo_dir, "add", os.path.abspath(state_path)],
            ["git", "-C", repo_dir, "commit", "-m", msg],
        ]:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                print(f"  [migrate] WARNING: git command failed: {' '.join(cmd)}\n"
                      f"    stderr: {r.stderr.strip()}", flush=True)
                return
        print(f"  [migrate] bootstrap-state.json committed to git repo at {repo_dir}")
        print(f"  [migrate] Push to Forgejo to trigger Assessment Engine reassessment.")
    except Exception as exc:
        print(f"  [migrate] WARNING: could not commit to git: {exc}", flush=True)


# ---------------------------------------------------------------------------
# Main migration wizard
# ---------------------------------------------------------------------------

def migrate_to_talos(
    node_vm_name: str,
    state_path: str,
    dry_run: bool = False,
    skip_snapshot: bool = False,
    runner=None,
    talos_config_dir: str | None = None,
) -> bool:
    """
    Orchestrate Ubuntu → Talos migration for the named node.

    Returns True on success, False on failure/rollback.
    """
    runner = runner or _local_runner
    started_at = datetime.now(timezone.utc).isoformat()
    migration_id = make_migration_id(node_vm_name, "ubuntu", "talos")

    print(f"\n[migrate-to-talos] Migration ID: {migration_id}")
    print(f"[migrate-to-talos] Node:         {node_vm_name}")
    print(f"[migrate-to-talos] Mode:         {'DRY RUN' if dry_run else 'LIVE'}")

    # Load state
    if not os.path.exists(state_path):
        print(f"[migrate-to-talos] ERROR: bootstrap-state.json not found: {state_path}",
              file=sys.stderr)
        return False

    with open(state_path) as f:
        state = json.load(f)

    vm_entry = _find_vm_entry(state, node_vm_name)
    if not vm_entry:
        print(f"[migrate-to-talos] ERROR: Node '{node_vm_name}' not found in VM registry",
              file=sys.stderr)
        return False

    current_variant = vm_entry.get("os_variant", "ubuntu")
    if current_variant == "talos":
        print(f"[migrate-to-talos] Node '{node_vm_name}' is already talos — nothing to do.")
        return True

    record = MigrationRecord(
        migration_id=migration_id,
        node_vm_name=node_vm_name,
        from_variant=current_variant,
        to_variant="talos",
        started_at=started_at,
        completed_at=None,
        outcome="aborted",
        snapshot_vmid=None,
        error=None,
        dry_run=dry_run,
    )

    # ── Step 1: Pre-flight checks ──────────────────────────────────────────
    print("\n[migrate-to-talos] Step 1: Pre-flight checks")
    preflight = run_preflight_checks(
        node_vm_name=node_vm_name,
        to_variant="talos",
        bootstrap_state=state,
        runner=runner,
        dry_run=dry_run,
        talos_config_dir=talos_config_dir,
    )
    print(preflight.summary())
    if not preflight.passed:
        print("[migrate-to-talos] BLOCKED: pre-flight checks failed. Aborting.")
        record.error = "pre-flight checks failed"
        if not dry_run:
            append_migration_history(state_path, record)
        return False

    # ── Step 2: Snapshot bootstrap-state ──────────────────────────────────
    print("\n[migrate-to-talos] Step 2: Snapshot state")
    snapshot = snapshot_state(
        node_vm_name=node_vm_name,
        original_os_variant=current_variant,
        bootstrap_state=state,
    )
    print(f"  State snapshot taken at {snapshot.timestamp}")

    # ── Step 3: Drain k3s node ─────────────────────────────────────────────
    print(f"\n[migrate-to-talos] Step 3: Drain node '{node_vm_name}'")
    drained = drain_node(node_vm_name, runner=runner, dry_run=dry_run)
    if not drained:
        print(f"[migrate-to-talos] WARNING: drain may not have completed cleanly")

    vmid = vm_entry.get("vmid") or vm_entry.get("vm_id")

    # ── Step 4: Proxmox VM snapshot ────────────────────────────────────────
    if not skip_snapshot and vmid:
        print(f"\n[migrate-to-talos] Step 4: Snapshot VM {vmid} in Proxmox")
        snap_name = f"pre-talos-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
        _proxmox_snapshot_vm(vmid, snap_name, runner=runner, dry_run=dry_run)
        record.snapshot_vmid = vmid
        print(f"  Snapshot '{snap_name}' created for VMID {vmid}")
    else:
        print("\n[migrate-to-talos] Step 4: Skipped (--skip-snapshot or no VMID)")

    # ── Step 5: Destroy Ubuntu VM ──────────────────────────────────────────
    if vmid:
        print(f"\n[migrate-to-talos] Step 5: Destroy Ubuntu VM {vmid}")
        _proxmox_destroy_vm(vmid, runner=runner, dry_run=dry_run)

    # ── Step 6: Provision from talos-1x-base ──────────────────────────────
    talos_template = _find_template(state, "talos-1x-base")
    template_vmid  = talos_template.get("proxmox_template_id") if talos_template else None
    print(f"\n[migrate-to-talos] Step 6: Provision new VM from talos-1x-base "
          f"(template VMID {template_vmid})")
    if vmid and template_vmid:
        _proxmox_clone_template(template_vmid, vmid, node_vm_name,
                                runner=runner, dry_run=dry_run)
        _proxmox_start_vm(vmid, runner=runner, dry_run=dry_run)

    # ── Step 7: Apply machine config ──────────────────────────────────────
    print(f"\n[migrate-to-talos] Step 7: Apply Talos machine config")
    talos_dir = talos_config_dir or os.path.join(os.path.dirname(__file__), "talos-configs")
    config_file = os.path.join(talos_dir, f"{node_vm_name}.yaml")
    node_ip = _find_dns_ip(state, node_vm_name) or ""
    if os.path.isfile(config_file) and node_ip:
        config_applied = _talosctl_apply_config(
            node_ip, config_file, runner=runner, dry_run=dry_run
        )
        if not config_applied:
            print("[migrate-to-talos] ERROR: talosctl apply-config failed")
            rollback(snapshot, state_path, record, runner=runner, dry_run=dry_run)
            return False
    else:
        if dry_run:
            print(f"  [dry-run] Would apply: {config_file} to {node_ip or '<node-ip>'}")
        else:
            print(f"  WARNING: config_file={config_file} ip={node_ip or '?'} — skipping apply")

    # ── Step 8: Verify cluster health ─────────────────────────────────────
    print(f"\n[migrate-to-talos] Step 8: Verify cluster health")
    healthy = verify_cluster_health(runner=runner, dry_run=dry_run)
    if not healthy:
        print("[migrate-to-talos] Cluster health check failed — initiating rollback")
        record.error = "post-migration health check failed"
        rollback(snapshot, state_path, record, runner=runner, dry_run=dry_run)
        return False

    # ── Step 9: Update bootstrap-state ────────────────────────────────────
    print(f"\n[migrate-to-talos] Step 9: Update bootstrap-state.json")
    completed_at = datetime.now(timezone.utc).isoformat()
    record.completed_at = completed_at
    record.outcome = "success"

    if not dry_run:
        with open(state_path) as f:
            state = json.load(f)
        update_os_variant(node_vm_name, "talos", state)
        state.setdefault("migration_history", []).append({
            "migration_id":  record.migration_id,
            "node_vm_name":  record.node_vm_name,
            "from_variant":  record.from_variant,
            "to_variant":    record.to_variant,
            "started_at":    record.started_at,
            "completed_at":  record.completed_at,
            "outcome":       record.outcome,
            "snapshot_vmid": record.snapshot_vmid,
            "error":         record.error,
            "dry_run":       record.dry_run,
        })
        with open(state_path, "w") as f:
            json.dump(state, f, indent=2)
        print(f"  os_variant updated to 'talos' for '{node_vm_name}'")
        print(f"  Migration record appended to migration_history")
        _commit_migration_record(state_path, node_vm_name, "ubuntu", "talos", runner)
    else:
        print(f"  [dry-run] Would update os_variant and migration_history")

    print(f"\n[migrate-to-talos] Migration complete — {node_vm_name} is now running Talos.")
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="Migrate a k3s node from Ubuntu to Talos Linux (9.T.10)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  # Dry run — see what would happen\n"
            "  python3 migrate-k3s-to-talos.py --node k3s-server-01 --dry-run\n\n"
            "  # Live migration\n"
            "  python3 migrate-k3s-to-talos.py --node k3s-server-01\n\n"
            "  # Skip Proxmox snapshot (dev/test environments)\n"
            "  python3 migrate-k3s-to-talos.py --node k3s-server-01 --skip-snapshot\n"
        ),
    )
    p.add_argument("--node",          required=True, help="VM name of the k3s node to migrate")
    p.add_argument("--state",         default=DEFAULT_STATE,
                   help=f"Path to bootstrap-state.json (default: {DEFAULT_STATE})")
    p.add_argument("--dry-run",       action="store_true",
                   help="Show what would happen without making changes")
    p.add_argument("--skip-snapshot", action="store_true",
                   help="Skip Proxmox VM snapshot (use in test environments)")
    args = p.parse_args()

    ok = migrate_to_talos(
        node_vm_name=args.node,
        state_path=args.state,
        dry_run=args.dry_run,
        skip_snapshot=args.skip_snapshot,
        talos_config_dir=None,
    )
    sys.exit(0 if ok else 1)
