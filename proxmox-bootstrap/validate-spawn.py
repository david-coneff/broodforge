#!/usr/bin/env python3
"""
validate-spawn.py — Spawn conflict validator CLI (Phase 12.E.2).

Thin CLI wrapper around validate_spawn.py. Runs the conflict re-validation
that phase-00-preflight.sh performs on the broodling: it loads the embedded
spawn-manifest.json (the hatchery's point-in-time reservation snapshot) and
the spawn-plan.json (this broodling's proposed allocations) and checks for
VMID / IP / hostname collisions and capacity violations before any host
changes are made.

No live API access is required — only the two JSON files bundled in the
spawn package.

Usage:
    python3 validate-spawn.py --manifest spawn-manifest.json --plan spawn-plan.json

Exit codes:
    0  — no RED findings (spawn may proceed)
    1  — at least one RED finding (collision/violation; abort)
    2  — usage / file error

Stdlib only.
"""

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))

from hatchery_state import SpawnManifest
from validate_spawn import (
    SpawnProposal,
    is_valid,
    summarise,
    validate_spawn,
)


def _proposal_from_plan(plan: dict) -> SpawnProposal:
    """Build a SpawnProposal from a spawn-plan.json dict."""
    vms = plan.get("vms") or []
    vmids = [v.get("vmid") for v in vms if v.get("vmid") is not None]
    ips = [v.get("ip") for v in vms if v.get("ip")]
    lan_ip = plan.get("lan_ip")
    if lan_ip:
        ips.append(lan_ip)

    hostnames = []
    primary = plan.get("hostname")
    if primary:
        hostnames.append(primary)
    hostnames += [v.get("name") for v in vms if v.get("name")]

    roles = [v.get("role") for v in vms if v.get("role")]
    k3s_role = (plan.get("k3s") or {}).get("role")
    if k3s_role:
        roles.append(k3s_role)

    return SpawnProposal(
        vmids=vmids,
        ips=ips,
        hostnames=hostnames,
        hostname=primary,
        roles=roles,
    )


def main() -> None:
    # The validator's summary uses Unicode glyphs (✓/✗). Ensure they encode on
    # any console (Windows cp1252 would otherwise crash on the success message).
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(
        description="Validate a spawn plan against the embedded reservation manifest",
    )
    parser.add_argument("--manifest", required=True,
                        help="Path to spawn-manifest.json (reservation snapshot)")
    parser.add_argument("--plan", required=True,
                        help="Path to spawn-plan.json (proposed allocations)")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    plan_path = Path(args.plan)
    if not manifest_path.exists():
        print(f"[validate-spawn] manifest not found: {manifest_path}", file=sys.stderr)
        sys.exit(2)
    if not plan_path.exists():
        print(f"[validate-spawn] plan not found: {plan_path}", file=sys.stderr)
        sys.exit(2)

    try:
        with open(manifest_path) as f:
            manifest_raw = json.load(f)
        with open(plan_path) as f:
            plan = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[validate-spawn] failed to read input: {exc}", file=sys.stderr)
        sys.exit(2)

    manifest = SpawnManifest(raw=manifest_raw)
    proposal = _proposal_from_plan(plan)
    findings = validate_spawn(manifest, proposal)

    print(summarise(findings))

    if not is_valid(findings):
        print("[validate-spawn] RED findings present — spawn must not proceed.",
              file=sys.stderr)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
