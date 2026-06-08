#!/usr/bin/env python3
"""
authorize-spawn-media-join.py — explicit, auditable human authorization gate
for pre-generated spawn-media joins (Phase 1.J, AD-060(c)).

A node installed from pre-generated spawn media (built-time AD-043 passphrase
embedded on the media — `_image_builder.build_pregenerated_spawn_media_record`)
must NOT be allowed to join the cell until a human operator explicitly
authorizes it. That gate is a STATE RECORD in bootstrap-state.json's
`pending_join_authorizations` list — exactly the shape AD-041's autonomous-
mode service-selection confirmation already uses: a recorded operator
decision broodforge reads back, never a live prompt it runs against itself
or a hypervisor.

This CLI is the ONLY thing that flips `authorized` to `true`. It:
  - requires the operator to name the exact `image_bundle_name` to authorize
  - requires `--operator <name>` (an audit attribution — who decided this)
  - never auto-authorizes; running it with no record present is an error
  - never reads, requests, or displays a passphrase or hash value as a secret
    (the hash is shown only as a non-reversible cross-check identifier)

Usage:
    python3 authorize-spawn-media-join.py \\
        --state bootstrap-state.json \\
        --bundle bootstrap-image-proxmox-cell-a-2026-06-08_00_00_00.tar.gz \\
        --operator dave

    python3 authorize-spawn-media-join.py --state bootstrap-state.json --list
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_state(path: Path) -> dict:
    if not path.exists():
        print(f"[error] State file not found: {path}", file=sys.stderr)
        sys.exit(1)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[error] Could not parse {path}: {exc}", file=sys.stderr)
        sys.exit(1)


def _list_records(state: dict) -> None:
    records = state.get("pending_join_authorizations") or []
    if not records:
        print("No pending_join_authorizations records found.")
        return
    print(f"\n{'=' * 72}")
    print("  Pending Join Authorizations")
    print(f"{'=' * 72}")
    for rec in records:
        status = "AUTHORIZED" if rec.get("authorized") else "pending"
        print(f"  [{status:10}] {rec.get('image_bundle_name')}")
        print(f"               hash: {rec.get('passphrase_hash')}")
        if rec.get("authorized"):
            print(f"               by:   {rec.get('authorized_by')}  at: {rec.get('authorized_at')}")
    print(f"{'=' * 72}\n")


def _authorize(state: dict, bundle_name: str, operator: str, now_fn) -> dict:
    records = [dict(rec) for rec in (state.get("pending_join_authorizations") or [])]
    target = None
    for rec in records:
        if rec.get("image_bundle_name") == bundle_name:
            target = rec
            break

    if target is None:
        print(f"[error] No pending_join_authorizations record for bundle "
              f"'{bundle_name}'. broodforge never auto-creates or auto-authorizes "
              f"these — build the spawn media first (generate-bootstrap-image.py "
              f"with pre-generated credentials), which records the pending entry.",
              file=sys.stderr)
        sys.exit(1)

    if target.get("authorized"):
        print(f"[error] Bundle '{bundle_name}' is already authorized "
              f"(by {target.get('authorized_by')} at {target.get('authorized_at')}). "
              f"Refusing to re-authorize — this is an explicit, one-time, "
              f"auditable human decision, not a togglable flag.", file=sys.stderr)
        sys.exit(1)

    target["authorized"] = True
    target["authorized_at"] = now_fn()
    target["authorized_by"] = operator

    state = dict(state)
    state["pending_join_authorizations"] = records
    return state


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Explicitly authorize a pre-generated spawn-media bundle to join the "
                    "cell (Phase 1.J, AD-060(c)) — a human-operated, auditable gate; "
                    "broodforge never authorizes a bundle on its own initiative.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--state", default="bootstrap-state.json",
        help="Path to bootstrap-state.json (default: ./bootstrap-state.json)",
    )
    parser.add_argument(
        "--bundle", default=None,
        help="Exact image_bundle_name to authorize (e.g. "
             "bootstrap-image-proxmox-cell-a-2026-06-08_00_00_00.tar.gz)",
    )
    parser.add_argument(
        "--operator", default=None,
        help="Name/identifier of the human operator making this authorization decision "
             "(recorded as authorized_by — required when authorizing)",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List all pending_join_authorizations records and their status, then exit",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would change without writing the state file",
    )
    args = parser.parse_args()

    state_path = Path(args.state)
    state = _load_state(state_path)

    if args.list:
        _list_records(state)
        return

    if not args.bundle:
        print("[error] --bundle is required to authorize (or pass --list to inspect "
              "pending records)", file=sys.stderr)
        sys.exit(1)
    if not args.operator:
        print("[error] --operator is required — every authorization is an attributed, "
              "auditable human decision (who decided this matters as much as that it "
              "happened)", file=sys.stderr)
        sys.exit(1)

    new_state = _authorize(state, args.bundle, args.operator, _now_iso)

    print(f"\n{'=' * 72}")
    print(f"  Spawn-Media Join Authorization Recorded")
    print(f"{'=' * 72}")
    print(f"  Bundle:    {args.bundle}")
    print(f"  Operator:  {args.operator}")
    rec = next(r for r in new_state["pending_join_authorizations"]
               if r.get("image_bundle_name") == args.bundle)
    print(f"  Recorded:  {rec['authorized_at']}")
    print(f"  Hash:      {rec.get('passphrase_hash')}  (cross-check only — never the passphrase)")
    print(f"{'=' * 72}\n")

    if args.dry_run:
        print("[dry-run] Not writing state file — this is a preview only.")
        return

    state_path.write_text(json.dumps(new_state, indent=2), encoding="utf-8")
    print(f"[ok] {state_path} updated. A node installed from this bundle may now join the cell.")


if __name__ == "__main__":
    main()
