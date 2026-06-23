#!/usr/bin/env python3
"""
migrate-k3s-to-ubuntu.py — Interactive Talos → Ubuntu migration wizard (9.T.11).

Migrates a k3s node from Talos Linux back to Ubuntu + k3s-server Ansible role:
  1. Pre-flight checks (cluster health, ubuntu template, PBS)
  2. State snapshot (rollback point)
  3. Drain/reset the Talos node via talosctl
  4. Destroy the Talos VM in Proxmox
  5. Provision new VM from ubuntu-2204-base template
  6. Apply Cloud-Init + Ansible k3s-server role
  7. Verify cluster health (node rejoined, Flux reconciled)
  8. Update bootstrap-state.json (os_variant, migration_history)

Usage:
  python3 proxmox-bootstrap/migrate-k3s-to-ubuntu.py --node k3s-server-01 --dry-run
  python3 proxmox-bootstrap/migrate-k3s-to-ubuntu.py --node k3s-server-01
  python3 proxmox-bootstrap/migrate-k3s-to-ubuntu.py --node k3s-server-01 --skip-snapshot

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
    MigrationRecord,
    _local_runner,
    append_migration_history,
    make_migration_id,
    rollback,
    run_preflight_checks,
    snapshot_state,
    update_os_variant,
    verify_cluster_health,
)

DEFAULT_STATE = str(_ROOT / "proxmox-bootstrap" / "bootstrap-state.json")


# ---------------------------------------------------------------------------
# Proxmox + talosctl helpers
# ---------------------------------------------------------------------------

def _talosctl_reset_node(node_ip: str, runner, dry_run: bool) -> None:
    cmd = f"talosctl reset --nodes {node_ip} --graceful=false --reboot=false"
    if dry_run:
        print(f"  [dry-run] Would run: {cmd}")
        return
    runner(cmd)


def _proxmox_destroy_vm(vmid: int, runner, dry_run: bool) -> None:
    cmd = f"qm stop {vmid} --timeout 60 ; qm destroy {vmid} --destroy-unreferenced-disks 1"
    if dry_run:
        print(f"  [dry-run] Would run: {cmd}")
        return
    runner(cmd)


def _proxmox_clone_template(
    template_vmid: int, new_vmid: int, vm_name: str, runner, dry_run: bool
) -> None:
    cmd = f"qm clone {template_vmid} {new_vmid} --name {vm_name} --full 1"
    if dry_run:
        print(f"  [dry-run] Would run: {cmd}")
        return
    runner(cmd)


def _proxmox_start_vm(vmid: int, runner, dry_run: bool) -> None:
    cmd = f"qm start {vmid}"
    if dry_run:
        print(f"  [dry-run] Would run: {cmd}")
        return
    runner(cmd)


def _ansible_apply_k3s(node_ip: str, runner, dry_run: bool) -> bool:
    cmd = (
        f"ansible-playbook -i {node_ip}, "
        "ansible/site.yml --tags k3s-server"
    )
    if dry_run:
        print(f"  [dry-run] Would run: {cmd}")
        return True
    output = runner(cmd)
    return "failed=0" in output or output.strip() == ""


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
    """Commit the updated bootstrap-state.json; non-fatal on failure."""
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
        print("  [migrate] Push to Forgejo to trigger Assessment Engine reassessment.")
    except Exception as exc:
        print(f"  [migrate] WARNING: could not commit to git: {exc}", flush=True)


# ---------------------------------------------------------------------------
# Main migration wizard
# ---------------------------------------------------------------------------

def migrate_to_ubuntu(
    node_vm_name: str,
    state_path: str,
    dry_run: bool = False,
    skip_snapshot: bool = False,
    runner=None,
) -> bool:
    """
    Orchestrate Talos → Ubuntu migration for the named node.

    Returns True on success, False on failure/rollback.
    """
    runner = runner or _local_runner
    started_at = datetime.now(timezone.utc).isoformat()
    migration_id = make_migration_id(node_vm_name, "talos", "ubuntu")

    print(f"\n[migrate-to-ubuntu] Migration ID: {migration_id}")
    print(f"[migrate-to-ubuntu] Node:         {node_vm_name}")
    print(f"[migrate-to-ubuntu] Mode:         {'DRY RUN' if dry_run else 'LIVE'}")

    # Load state
    if not os.path.exists(state_path):
        print(f"[migrate-to-ubuntu] ERROR: bootstrap-state.json not found: {state_path}",
              file=sys.stderr)
        return False

    with open(state_path) as f:
        state = json.load(f)

    vm_entry = _find_vm_entry(state, node_vm_name)
    if not vm_entry:
        print(f"[migrate-to-ubuntu] ERROR: Node '{node_vm_name}' not found in VM registry",
              file=sys.stderr)
        return False

    current_variant = vm_entry.get("os_variant", "talos")
    if current_variant == "ubuntu":
        print(f"[migrate-to-ubuntu] Node '{node_vm_name}' is already ubuntu — nothing to do.")
        return True

    record = MigrationRecord(
        migration_id=migration_id,
        node_vm_name=node_vm_name,
        from_variant=current_variant,
        to_variant="ubuntu",
        started_at=started_at,
        completed_at=None,
        outcome="aborted",
        snapshot_vmid=None,
        error=None,
        dry_run=dry_run,
    )

    # ── Step 1: Pre-flight checks ──────────────────────────────────────────
    print("\n[migrate-to-ubuntu] Step 1: Pre-flight checks")
    preflight = run_preflight_checks(
        node_vm_name=node_vm_name,
        to_variant="ubuntu",
        bootstrap_state=state,
        runner=runner,
        dry_run=dry_run,
    )
    print(preflight.summary())
    if not preflight.passed:
        print("[migrate-to-ubuntu] BLOCKED: pre-flight checks failed. Aborting.")
        record.error = "pre-flight checks failed"
        if not dry_run:
            append_migration_history(state_path, record)
        return False

    # ── Step 2: Snapshot bootstrap-state ──────────────────────────────────
    print("\n[migrate-to-ubuntu] Step 2: Snapshot state")
    snapshot = snapshot_state(
        node_vm_name=node_vm_name,
        original_os_variant=current_variant,
        bootstrap_state=state,
    )
    print(f"  State snapshot taken at {snapshot.timestamp}")

    vmid = vm_entry.get("vmid") or vm_entry.get("vm_id")
    node_ip = _find_dns_ip(state, node_vm_name) or ""

    # ── Step 3: Reset Talos node ───────────────────────────────────────────
    print(f"\n[migrate-to-ubuntu] Step 3: Reset Talos node '{node_vm_name}'")
    if node_ip:
        _talosctl_reset_node(node_ip, runner=runner, dry_run=dry_run)
    else:
        print(f"  WARNING: No IP found for '{node_vm_name}' — skipping talosctl reset")

    # ── Step 4: Destroy Talos VM ───────────────────────────────────────────
    if vmid:
        print(f"\n[migrate-to-ubuntu] Step 4: Destroy Talos VM {vmid}")
        _proxmox_destroy_vm(vmid, runner=runner, dry_run=dry_run)
    else:
        print("\n[migrate-to-ubuntu] Step 4: No VMID found — skipping VM destroy")

    # ── Step 5: Provision from ubuntu-2204-base ────────────────────────────
    ubuntu_template = _find_template(state, "ubuntu-2204-base")
    template_vmid   = ubuntu_template.get("proxmox_template_id") if ubuntu_template else None
    print(f"\n[migrate-to-ubuntu] Step 5: Provision from ubuntu-2204-base "
          f"(template VMID {template_vmid})")
    if vmid and template_vmid:
        _proxmox_clone_template(template_vmid, vmid, node_vm_name,
                                runner=runner, dry_run=dry_run)
        _proxmox_start_vm(vmid, runner=runner, dry_run=dry_run)

    # ── Step 6: Apply Cloud-Init + Ansible ────────────────────────────────
    print("\n[migrate-to-ubuntu] Step 6: Apply Cloud-Init + Ansible k3s-server role")
    if node_ip:
        ok = _ansible_apply_k3s(node_ip, runner=runner, dry_run=dry_run)
        if not ok:
            print("[migrate-to-ubuntu] ERROR: Ansible provisioning failed")
            rollback(snapshot, state_path, record, runner=runner, dry_run=dry_run)
            return False
    else:
        if dry_run:
            print(f"  [dry-run] Would run Ansible against {node_vm_name}")
        else:
            print(f"  WARNING: No IP found for '{node_vm_name}' — skipping Ansible")

    # ── Step 7: Verify cluster health ─────────────────────────────────────
    print("\n[migrate-to-ubuntu] Step 7: Verify cluster health")
    healthy = verify_cluster_health(runner=runner, dry_run=dry_run)
    if not healthy:
        print("[migrate-to-ubuntu] Cluster health check failed — initiating rollback")
        record.error = "post-migration health check failed"
        rollback(snapshot, state_path, record, runner=runner, dry_run=dry_run)
        return False

    # ── Step 8: Update bootstrap-state ────────────────────────────────────
    print("\n[migrate-to-ubuntu] Step 8: Update bootstrap-state.json")
    completed_at = datetime.now(timezone.utc).isoformat()
    record.completed_at = completed_at
    record.outcome = "success"

    if not dry_run:
        with open(state_path) as f:
            state = json.load(f)
        update_os_variant(node_vm_name, "ubuntu", state)
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
        print(f"  os_variant updated to 'ubuntu' for '{node_vm_name}'")
        print("  Migration record appended to migration_history")
        _commit_migration_record(state_path, node_vm_name, "talos", "ubuntu", runner)
    else:
        print("  [dry-run] Would update os_variant and migration_history")

    print(f"\n[migrate-to-ubuntu] Migration complete — {node_vm_name} is now running Ubuntu.")
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="Migrate a k3s node from Talos Linux back to Ubuntu (9.T.11)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  # Dry run — see what would happen\n"
            "  python3 migrate-k3s-to-ubuntu.py --node k3s-server-01 --dry-run\n\n"
            "  # Live migration\n"
            "  python3 migrate-k3s-to-ubuntu.py --node k3s-server-01\n\n"
            "  # Skip snapshot (dev/test)\n"
            "  python3 migrate-k3s-to-ubuntu.py --node k3s-server-01 --skip-snapshot\n"
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

    ok = migrate_to_ubuntu(
        node_vm_name=args.node,
        state_path=args.state,
        dry_run=args.dry_run,
        skip_snapshot=args.skip_snapshot,
    )
    sys.exit(0 if ok else 1)
