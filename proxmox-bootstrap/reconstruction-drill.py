#!/usr/bin/env python3
"""
reconstruction-drill.py — CLI entry point for the reconstruction drill framework.

Usage:
  python3 proxmox-bootstrap/reconstruction-drill.py start \\
      --playbook path/to/phoenix-playbook.json \\
      --state    path/to/bootstrap-state.json

  python3 proxmox-bootstrap/reconstruction-drill.py last \\
      --state path/to/bootstrap-state.json

  python3 proxmox-bootstrap/reconstruction-drill.py report \\
      --state path/to/bootstrap-state.json

See docs/RECONSTRUCTION-DRILL.md for the full operator runbook.
"""

import argparse
import json
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from reconstruction_drill import (
    start_drill,
    save_drill_record,
    get_last_drill,
    generate_drill_report,
    DrillRecord,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_json(path: str) -> dict:
    if not os.path.exists(path):
        print(f"[drill] ERROR: file not found: {path}", file=sys.stderr)
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def _save_json(path: str, data: dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# Sub-commands
# ---------------------------------------------------------------------------

def cmd_start(args: argparse.Namespace) -> None:
    """Initialise a new drill record from a phoenix playbook and print the drill_id."""
    playbook = _load_json(args.playbook)
    record = start_drill(playbook, cell_id=args.cell_id or None)
    print(f"[drill] Started drill {record.drill_id} for cell {record.cell_id}")
    print(f"[drill] Estimated total: {record.total_estimated_minutes} minutes")
    print(f"[drill] Waves to execute: "
          f"{len(playbook.get('waves', []))}")
    print()
    print(f"[drill] Record drill progress with --record-wave, then --complete.")
    print(f"[drill] Drill ID: {record.drill_id}")

    # Persist to state if --state given
    if args.state:
        state = _load_json(args.state) if os.path.exists(args.state) else {}
        # Save with outcome=in_progress for tracking
        record.outcome = "in_progress"
        state = save_drill_record(state, record)
        _save_json(args.state, state)
        print(f"[drill] Drill record saved to {args.state}")


def cmd_complete(args: argparse.Namespace) -> None:
    """Mark the most recent in-progress drill as completed and generate the report."""
    state = _load_json(args.state)
    last = get_last_drill(state)
    if not last:
        print("[drill] No drill record found in state.", file=sys.stderr)
        sys.exit(1)

    drill_id = last.get("drill_id", "?")
    outcome  = args.outcome or "success"
    last["outcome"]      = outcome
    last["completed_at"] = last.get("completed_at") or \
        __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat()

    # Record gaps if provided via --gaps
    if getattr(args, "gaps", None):
        existing = last.get("gaps_found") or []
        last["gaps_found"] = existing + args.gaps

    # Write back
    drills = state.setdefault("reconstruction_drills", [])
    drills[0] = last
    _save_json(args.state, state)

    from reconstruction_drill import DrillRecord
    record = DrillRecord(
        cell_id=last.get("cell_id", "?"),
        drill_id=drill_id,
    )
    record.__dict__.update({k: last.get(k) for k in last if k in record.__dict__})
    report_md = generate_drill_report(record)

    out_path = args.output or f"drill-report-{drill_id}.md"
    with open(out_path, "w") as f:
        f.write(report_md)
    print(f"[drill] Drill {drill_id} marked {outcome.upper()}.")
    print(f"[drill] Report written to {out_path}")
    print(f"[drill] Commit both bootstrap-state.json and {out_path} to Forgejo.")


def cmd_last(args: argparse.Namespace) -> None:
    """Print the most recent drill record."""
    state = _load_json(args.state)
    last  = get_last_drill(state)
    if not last:
        print("[drill] No drill records found.")
        return
    print(json.dumps(last, indent=2))


def cmd_report(args: argparse.Namespace) -> None:
    """(Re-)generate the Markdown report for the most recent drill."""
    state = _load_json(args.state)
    last  = get_last_drill(state)
    if not last:
        print("[drill] No drill records found.", file=sys.stderr)
        sys.exit(1)

    from reconstruction_drill import DrillRecord
    record = DrillRecord(cell_id=last.get("cell_id", "?"))
    for k, v in last.items():
        if hasattr(record, k):
            object.__setattr__(record, k, v) if hasattr(record, "__dataclass_fields__") \
                else setattr(record, k, v)
    report_md = generate_drill_report(record)
    out_path  = args.output or f"drill-report-{record.drill_id}.md"
    with open(out_path, "w") as f:
        f.write(report_md)
    print(f"[drill] Report written to {out_path}")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(
        description="Broodforge reconstruction drill CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = p.add_subparsers(dest="command", required=True)

    # start
    ps = sub.add_parser("start", help="Start a new drill from a phoenix playbook")
    ps.add_argument("--playbook", required=True,
                    help="Path to phoenix-playbook.json")
    ps.add_argument("--state",    default="proxmox-bootstrap/bootstrap-state.json",
                    help="Path to bootstrap-state.json (updated with drill record)")
    ps.add_argument("--cell-id",  default="",
                    help="Override cell_id from playbook")

    # complete
    pc = sub.add_parser("complete", help="Mark the latest drill completed and write report")
    pc.add_argument("--state",  required=True, help="Path to bootstrap-state.json")
    pc.add_argument("--outcome", default="success",
                    choices=["success", "partial", "failed", "aborted"],
                    help="Final drill outcome")
    pc.add_argument("--gaps", nargs="*", metavar="GAP",
                    help="Gap(s) found during the drill (repeatable strings)")
    pc.add_argument("--output", default="", help="Output Markdown report path")

    # last
    pl = sub.add_parser("last", help="Print the most recent drill record as JSON")
    pl.add_argument("--state", required=True, help="Path to bootstrap-state.json")

    # report
    pr = sub.add_parser("report", help="Regenerate the Markdown report for the last drill")
    pr.add_argument("--state",  required=True, help="Path to bootstrap-state.json")
    pr.add_argument("--output", default="", help="Output Markdown report path")

    args = p.parse_args()
    dispatch = {
        "start":    cmd_start,
        "complete": cmd_complete,
        "last":     cmd_last,
        "report":   cmd_report,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
