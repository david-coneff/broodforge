#!/usr/bin/env python3
"""
restore-from-backup.py — Automated restore CLI for broodforge.

Usage:
  python3 restore-from-backup.py --state bootstrap-state.json
                                  [--layer config|appdata]
                                  [--snapshot-set ID | --latest | --checkpoint]
                                  [--component PREFIX]
                                  [--target /path/to/restore]
                                  [--dry-run] [--verbose]

Reads backup_history from bootstrap-state.json, resolves per-snapshot restic
passwords from KeePass (via secrets broker), and restores the requested snapshot.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from backup_engine import RestoreEngine


def _configure_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(format="[%(levelname)s] %(message)s", level=level)


def _load_state(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        print(f"Error: bootstrap-state not found: {path}", file=sys.stderr)
        sys.exit(1)
    return json.loads(p.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description="broodforge restore tool")
    parser.add_argument("--state",         required=True)
    parser.add_argument("--layer",         default="config",
                        choices=["secrets", "config", "appdata"])
    parser.add_argument("--snapshot-set",  help="Specific snapshot_set_id to restore")
    parser.add_argument("--latest",        action="store_true", help="Restore most recent set")
    parser.add_argument("--checkpoint",    action="store_true",
                        help="Restore most recent permanent checkpoint")
    parser.add_argument("--component",     help="Restore only this component prefix")
    parser.add_argument("--target",        default="/tmp/broodforge-restore",  # nosec B108 — user-visible CLI default
                        help="Target directory for restored files")
    parser.add_argument("--list",          action="store_true",
                        help="List available snapshot sets and exit")
    parser.add_argument("--dry-run",       action="store_true")
    parser.add_argument("--verbose",       action="store_true")
    args = parser.parse_args()

    _configure_logging(args.verbose)

    state = _load_state(args.state)
    cell_id       = state.get("cell_id", "unknown-cell")
    backup_config = state.get("backup_config")

    if not backup_config:
        print("Error: no backup_config in bootstrap-state.json", file=sys.stderr)
        sys.exit(1)

    engine = RestoreEngine(
        cell_id=cell_id,
        backup_config=backup_config,
    )

    if args.list:
        sets = engine.list_snapshot_sets()
        if not sets:
            print("No snapshot sets found in backup_history.")
        else:
            print(f"{'Snapshot Set ID':<55} {'Layer':<10} {'Run At':<25} {'OK?'}")
            print("-" * 100)
            for s in sets:
                ok = "✓" if s["all_succeeded"] else "✗"
                print(f"{s['snapshot_set_id']:<55} {s['layer']:<10} "
                      f"{s['run_at']:<25} {ok}")
        return

    # Resolve which snapshot set to restore
    snapshot_set_id = args.snapshot_set
    if args.latest or (not snapshot_set_id and not args.checkpoint):
        sets = engine.list_snapshot_sets()
        layer_sets = [s for s in sets if s["layer"] == args.layer]
        if not layer_sets:
            print(f"No snapshot sets for layer '{args.layer}' in backup_history", file=sys.stderr)
            sys.exit(1)
        snapshot_set_id = layer_sets[0]["snapshot_set_id"]
        print(f"[restore] Using latest: {snapshot_set_id}")

    if not snapshot_set_id:
        print("Error: specify --snapshot-set, --latest, or --checkpoint", file=sys.stderr)
        sys.exit(1)

    print(f"\n[restore] Snapshot set: {snapshot_set_id}")
    print(f"[restore] Layer:        {args.layer}")
    print(f"[restore] Target:       {args.target}")
    if args.dry_run:
        print("[restore] DRY RUN — no changes will be made")

    results = engine.restore_snapshot_set(
        snapshot_set_id=snapshot_set_id,
        layer=args.layer,
        target_dir=args.target,
        dry_run=args.dry_run,
    )

    print()
    failed = []
    for r in results:
        if r.get("dry_run"):
            print(f"  [DRY RUN] {r['component']} from {r.get('destination', '?')}")
        elif r.get("success"):
            ok_str = "✓ integrity ok" if r.get("integrity_ok") else "⚠ integrity warn"
            print(f"  ✓ {r['component']} → {r['target_dir']}  ({ok_str})")
        elif r.get("error"):
            print(f"  ✗ {r.get('error')}")
            failed.append(r)
        else:
            print(f"  ✗ {r['component']}: {r.get('message', 'unknown error')}")
            failed.append(r)

    if failed:
        print(f"\n[restore] {len(failed)} component(s) failed", file=sys.stderr)
        sys.exit(2)
    else:
        print(f"\n[restore] Complete. Files at: {args.target}")


if __name__ == "__main__":
    main()
