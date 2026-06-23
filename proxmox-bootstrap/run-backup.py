#!/usr/bin/env python3
"""
run-backup.py — Backup execution CLI for broodforge.

Usage:
  python3 run-backup.py --state bootstrap-state.json [--layer secrets|config|appdata]
                        [--kdbx path/to/database.kdbx] [--dry-run] [--verbose]

Runs the configured backup layers against all destinations in each layer's chain.
Per-destination failures are reported and the chain continues.
All-destination failure for any layer is logged as a RED gap in backup_history.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from backup_engine import BackupEngine


def _configure_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(format="[%(levelname)s] %(message)s", level=level)


def _load_state(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        print(f"Error: bootstrap-state not found: {path}", file=sys.stderr)
        sys.exit(1)
    return json.loads(p.read_text(encoding="utf-8"))


def _save_state(path: str, state: dict):
    Path(path).write_text(json.dumps(state, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="broodforge backup runner")
    parser.add_argument("--state",   required=True, help="Path to bootstrap-state.json")
    parser.add_argument("--layer",   choices=["secrets", "config", "appdata"],
                        help="Run a specific layer only (default: all enabled layers)")
    parser.add_argument("--kdbx",    help="Path to KeePass database (required for secrets layer)")
    parser.add_argument("--source",  nargs="+", default=[],
                        help="Source paths to back up (config/appdata layers)")
    parser.add_argument("--component", default="cell-config",
                        help="Component prefix for this backup (default: cell-config)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be backed up without writing")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    _configure_logging(args.verbose)

    state = _load_state(args.state)
    cell_id = state.get("cell_id", "unknown-cell")
    backup_config = state.get("backup_config")

    if not backup_config:
        print("Error: no backup_config in bootstrap-state.json — run setup-backup.py first",
              file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        print("[DRY RUN] No changes will be made.")

    engine = BackupEngine(
        cell_id=cell_id,
        backup_config=backup_config,
    )

    layers_to_run = [args.layer] if args.layer else ["secrets", "config", "appdata"]
    results = []

    for layer in layers_to_run:
        layer_config = (backup_config.get("layers") or {}).get(layer)
        if not layer_config or not layer_config.get("enabled"):
            continue

        print(f"\n[backup] Layer: {layer}")
        if args.dry_run:
            print(f"  [DRY RUN] Would back up layer '{layer}'")
            continue

        if layer == "secrets":
            if not args.kdbx:
                print("  SKIP — --kdbx not provided", file=sys.stderr)
                continue
            result = engine.run_secrets_backup(args.kdbx)
        else:
            if not args.source:
                print(f"  SKIP — --source not provided for {layer} layer", file=sys.stderr)
                continue
            result = engine.run_restic_backup(layer, args.component, args.source)

        results.append(result)

        # Report
        if result.all_failed:
            print("  ✗ ALL DESTINATIONS FAILED — RED gap will be logged")
        else:
            for dr in result.destination_results:
                status = "✓" if (dr.success and dr.verified) else "✗"
                snap   = f" snap={dr.snapshot_id[:8]}" if dr.snapshot_id else ""
                print(f"  {status} {dr.destination_id}{snap}"
                      + (f" — {dr.error_message}" if not dr.success else ""))

        # Update backup_history in state
        history = backup_config.setdefault("backup_history", [])
        rec = result.to_history_record()
        # Update consecutive_all_fail_count
        prev_fail = 0
        for past in reversed(history):
            if past.get("layer") == layer:
                prev_fail = past.get("consecutive_all_fail_count", 0)
                break
        rec["consecutive_all_fail_count"] = (prev_fail + 1) if result.all_failed else 0
        history.insert(0, rec)
        backup_config["backup_history"] = history[:100]  # trim to 100 entries

    if not args.dry_run and results:
        _save_state(args.state, state)
        print("\n[backup] bootstrap-state.json updated with backup_history")

    failed_layers = [r.layer for r in results if r.all_failed]
    if failed_layers:
        print(f"\n[backup] CRITICAL: all destinations failed for: {', '.join(failed_layers)}",
              file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
