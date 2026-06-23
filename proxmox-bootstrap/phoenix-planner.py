#!/usr/bin/env python3
"""
phoenix-planner.py — Interactive phoenix planner CLI (Phase 1.G.6).

Run on the hatchery (or recovery workstation) to customize a phoenix playbook
before generating a phoenix package for a failed node.

Usage:
    python3 phoenix-planner.py \\
        --state  bootstrap-state.json \\
        --playbook phoenix-playbook.json \\
        [--output  phoenix-playbook-custom.json]

Two customisation points are offered:
  1. Restoration scope (full / partial wave selection)
  2. Identity overrides (hostname, domain, FQDN, cell_id)

After the interactive session, produces an updated playbook JSON with the
operator's choices embedded.

Stdlib only.
"""

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))

from phoenix_guided_setup import (
    RESTORATION_SCOPE_FULL,
    RESTORATION_SCOPE_PARTIAL,
    PhoenixGuidedSetupSession,
    apply_overrides_to_playbook,
    restoration_wave_options,
    step0_set_restoration_scope,
    step1_run_identity_overrides,
)
from phoenix_playbook import build_phoenix_playbook

# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _prompt(msg: str, default: str = "") -> str:
    if default:
        msg = f"{msg} [{default}]: "
    else:
        msg = f"{msg}: "
    try:
        val = input(msg).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)
    return val or default


def _choice(options: list[tuple[str, str]], title: str) -> int:
    print(f"\n{title}")
    for i, (label, desc) in enumerate(options, 1):
        line = f"  {i}. {label:<28}"
        if desc:
            line += f" — {desc}"
        print(line)
    while True:
        raw = _prompt("\nSelection", "1")
        try:
            n = int(raw)
            if 1 <= n <= len(options):
                return n
        except ValueError:
            pass
        print(f"  Enter a number 1–{len(options)}")


def _header(title: str):
    print(f"\n{'─' * 64}")
    print(f"  {title}")
    print(f"{'─' * 64}")


def _warn(msg: str):
    print(f"  ⚠  {msg}")


# ---------------------------------------------------------------------------
# Step 0 — Restoration scope
# ---------------------------------------------------------------------------

def _step0_scope(session: PhoenixGuidedSetupSession, playbook: dict) -> None:
    _header("Step 0 — Restoration Scope")
    print("\n  Choose which restoration waves to include.\n")

    sel = _choice([
        ("Full (default)", "all waves — complete node rebuild"),
        ("Partial",        "select specific waves to run"),
    ], "Restoration scope:")

    if sel == 1:
        step0_set_restoration_scope(session, RESTORATION_SCOPE_FULL)
        return

    # Partial scope — show wave options
    options = restoration_wave_options(playbook)
    if not options:
        print("  No waves found in playbook — defaulting to full scope.")
        step0_set_restoration_scope(session, RESTORATION_SCOPE_FULL)
        return

    print("\n  Select which waves to include:\n")
    selected = []
    for opt in options:
        label = f"  Wave {opt['wave']}: {opt['name']}"
        label += f"  (~{opt['estimated_minutes']} min, {opt['step_count']} step(s))"
        ans = _prompt(f"{label} (y/N)", "n")
        if ans.lower() == "y":
            selected.append(opt["wave"])

    if not selected:
        print("  No waves selected — defaulting to full scope.")
        step0_set_restoration_scope(session, RESTORATION_SCOPE_FULL)
    else:
        step0_set_restoration_scope(session, RESTORATION_SCOPE_PARTIAL, selected)
        print(f"\n  Selected waves: {sorted(selected)}")


# ---------------------------------------------------------------------------
# Step 1 — Identity overrides
# ---------------------------------------------------------------------------

def _step1_identity(
    session:  PhoenixGuidedSetupSession,
    state:    dict,
    playbook: dict,
) -> None:
    _header("Step 1 — Identity Overrides")
    print("\n  Override identity fields if rebuilding under a different identity.")
    print("  Press Enter to keep the existing value from the playbook.\n")

    target = playbook.get("target_node") or {}
    hi     = state.get("host_identity") or {}

    ans = _prompt("  Override any identity fields? (y/N)", "n")
    if ans.lower() != "y":
        return

    field_labels = {
        "host_identity.hostname": ("Hostname",  target.get("hostname") or hi.get("hostname") or ""),
        "host_identity.domain":   ("Domain",    target.get("domain")   or hi.get("domain")   or ""),
        "host_identity.fqdn":     ("FQDN",      target.get("fqdn")     or hi.get("fqdn")     or ""),
        "host_identity.cell_id":  ("Cell ID",   target.get("cell_id")  or state.get("cell_id") or ""),
    }

    overrides = {}
    for fp, (label, current) in field_labels.items():
        val = _prompt(f"  {label:<10}", current)
        if val and val != current:
            overrides[fp] = val

    if overrides:
        step1_run_identity_overrides(
            session,
            manifest=state,
            mode="full-manual",
            overrides=overrides,
        )
        print(f"\n  {len(overrides)} identity field(s) overridden.")
    else:
        print("  No changes.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Broodforge phoenix planner")
    parser.add_argument("--state",    required=True,
                        help="Path to bootstrap-state.json")
    parser.add_argument("--playbook", default=None,
                        help="Existing phoenix-playbook.json to customise "
                             "(omit to GENERATE the base playbook from --state)")
    parser.add_argument("--hardware", default=None,
                        help="Replacement node hardware-profile.json (optional; "
                             "used when generating from --state)")
    parser.add_argument("--output",   default=None,
                        help="Output path (default: phoenix-playbook.json, "
                             "or update --playbook in place)")
    args = parser.parse_args()

    with open(args.state) as f:
        state = json.load(f)
    if args.playbook:
        with open(args.playbook) as f:
            playbook = json.load(f)
    else:
        hardware = None
        if args.hardware:
            with open(args.hardware) as f:
                hardware = json.load(f)
        playbook = build_phoenix_playbook(
            state, hardware_profile=hardware, generated_by="phoenix-planner"
        )
        print("  Generated base phoenix playbook from bootstrap-state.json.")

    cell_id   = state.get("cell_id", "unknown")
    node_name = (playbook.get("target_node") or {}).get("hostname", "unknown")

    print(f"\n{'=' * 64}")
    print("  Broodforge Phoenix Planner")
    print(f"  Cell: {cell_id}  |  Node: {node_name}")
    print(f"{'=' * 64}")
    print("\n  This planner customises a phoenix playbook before generating")
    print("  a phoenix package for a failed node.")

    session = PhoenixGuidedSetupSession()

    _step0_scope(session, playbook)
    _step1_identity(session, state, playbook)

    updated = apply_overrides_to_playbook(session, playbook)

    out = Path(args.output or args.playbook or "phoenix-playbook.json")
    out.write_text(json.dumps(updated, indent=2))

    _header("Phoenix Playbook Updated")
    print(f"\n  Output:             {out}")
    print(f"  Restoration scope:  {updated['restoration_scope']}")
    if session.restoration_scope == RESTORATION_SCOPE_PARTIAL:
        print(f"  Selected waves:     {sorted(session.selected_waves)}")
        wave_count = len(updated.get("waves") or [])
        print(f"  Waves included:     {wave_count}")
    if session.identity_overrides:
        print(f"  Identity overrides: {len(session.identity_overrides)}")
    if session.warnings:
        print(f"\n  Warnings ({len(session.warnings)}):")
        for w in session.warnings:
            print(f"    ⚠  {w}")
    print("\n  Next steps:")
    print(f"    1. Review {out}")
    print(f"    2. Run: python3 assemble-phoenix-package.py --playbook {out}")
    print()


if __name__ == "__main__":
    main()
