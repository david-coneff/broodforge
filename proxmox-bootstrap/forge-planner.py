#!/usr/bin/env python3
"""
forge-planner.py — Interactive forge planner CLI (Phase 1.G.4).

Run on the operator workstation (or on the prospective hatchery) to plan
the initial forge of a new hatchery node.

Usage:
    python3 forge-planner.py \\
        [--manifest existing-state.json] \\
        [--output forge-manifest.json]

After the interactive session, produces:
    forge-manifest.json  (operator choices + auto-calculated values)

Stdlib only.
"""

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))

from forge_planner import (
    FORGE_MODE_AUTONOMOUS,
    FORGE_MODE_FULL_MANUAL,
    FORGE_MODE_GROUP_MANUAL,
    FORGE_MODE_IP_SELECTIVE,
    PROFILE_LAN,
    PROFILE_WAN,
    ForgePlannerSession,
    build_forge_manifest,
    record_manual_field,
    step0_set_setup_mode,
    step1_run_guided_setup,
    step2_set_identity,
    step3_set_network_profile,
)
from guided_setup import (
    SETTING_GROUPS,
    group_selector_rows,
    suggest,
)

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
# Step 0 — Setup mode
# ---------------------------------------------------------------------------

def _step0_mode(session: ForgePlannerSession) -> ForgePlannerSession:
    _header("Step 0 — Configuration Mode")
    print("\n  How should forge settings be determined?\n")

    sel = _choice([
        ("Autonomous (default)",
         "all settings auto-calculated from discovery"),
        ("IP-Selective",
         "autonomous except you choose IP addressing"),
        ("Group-Manual",
         "pick which setting groups to configure manually"),
        ("Full-Manual",
         "walk through all settings with suggestions"),
    ], "Configuration mode:")

    mode_map = {
        1: FORGE_MODE_AUTONOMOUS,
        2: FORGE_MODE_IP_SELECTIVE,
        3: FORGE_MODE_GROUP_MANUAL,
        4: FORGE_MODE_FULL_MANUAL,
    }
    step0_set_setup_mode(session, mode_map[sel])
    print(f"\n  Mode: {session.setup_mode}")
    return session


# ---------------------------------------------------------------------------
# Step 1 — Guided setup (non-autonomous)
# ---------------------------------------------------------------------------

def _step1_guided(session: ForgePlannerSession) -> ForgePlannerSession:
    if session.setup_mode == FORGE_MODE_AUTONOMOUS:
        return session

    _header("Step 1 — Guided Setup")

    selected_groups = None

    if session.setup_mode == FORGE_MODE_IP_SELECTIVE:
        print("\n  Auto-calculating all settings; you will set IP addressing only.\n")
        step1_run_guided_setup(session)
        # Now prompt for IP fields
        gs = session.guided_session
        for fp in ("network.management_cidr", "network.gateway", "network.nameservers"):
            current = suggest(fp, gs)
            if fp == "network.nameservers":
                current_str = ",".join(current) if isinstance(current, list) else str(current)
                raw = _prompt(f"  {fp}", current_str)
                val = [s.strip() for s in raw.split(",") if s.strip()]
            else:
                val = _prompt(f"  {fp}", str(current))
            conflicts = record_manual_field(session, fp, val)
            for c in conflicts:
                _warn(c)

    elif session.setup_mode == FORGE_MODE_GROUP_MANUAL:
        print("\n  Select which setting groups to configure manually.\n")
        # Run initial setup with no groups to get suggestions
        step1_run_guided_setup(session)
        rows = group_selector_rows(session.guided_session)
        selected = []
        for row in rows:
            gid  = row["group_id"]
            row["auto_suggestion"]
            desc = row["description"]
            ans  = _prompt(f"  Configure {row['label']:<12} ({desc[:35]}) (y/N)", "n")
            if ans.lower() == "y":
                selected.append(gid)
        selected_groups = selected
        step1_run_guided_setup(session, selected_groups=selected_groups)

        # Prompt for fields in selected groups
        if selected_groups:
            print()
            for gid in selected_groups:
                gdef = SETTING_GROUPS[gid]
                _header(f"Group: {gdef['label']}")
                gs = session.guided_session
                for fp in gdef["fields"]:
                    current = suggest(fp, gs)
                    current_str = (
                        ",".join(current) if isinstance(current, list) else str(current)
                    ) if current is not None else ""
                    val_raw = _prompt(f"  {fp}", current_str)
                    if fp.endswith("nameservers") or isinstance(current, list):
                        val = [s.strip() for s in val_raw.split(",") if s.strip()]
                    elif isinstance(current, bool):
                        val = val_raw.lower() in ("true", "yes", "1", "y")
                    elif isinstance(current, int):
                        try:
                            val = int(val_raw)
                        except ValueError:
                            val = val_raw
                    else:
                        val = val_raw
                    conflicts = record_manual_field(session, fp, val)
                    for c in conflicts:
                        _warn(c)

    elif session.setup_mode == FORGE_MODE_FULL_MANUAL:
        step1_run_guided_setup(session)
        print("\n  Walking through all settings. Press Enter to accept suggestion.\n")
        gs = session.guided_session
        for _gid, gdef in SETTING_GROUPS.items():
            _header(f"Group: {gdef['label']}")
            for fp in gdef["fields"]:
                current = suggest(fp, gs)
                current_str = (
                    ",".join(current) if isinstance(current, list) else str(current)
                ) if current is not None else ""
                val_raw = _prompt(f"  {fp}", current_str)
                if fp.endswith("nameservers") or isinstance(current, list):
                    val = [s.strip() for s in val_raw.split(",") if s.strip()]
                elif isinstance(current, bool):
                    val = val_raw.lower() in ("true", "yes", "1", "y")
                elif isinstance(current, int):
                    try:
                        val = int(val_raw)
                    except ValueError:
                        val = val_raw
                else:
                    val = val_raw
                conflicts = record_manual_field(session, fp, val)
                for c in conflicts:
                    _warn(c)

    return session


# ---------------------------------------------------------------------------
# Step 2 — Identity
# ---------------------------------------------------------------------------

def _step2_identity(session: ForgePlannerSession) -> ForgePlannerSession:
    _header("Step 2 — Identity")
    gs = session.guided_session

    # Show suggestions or defaults
    hostname_default = suggest("host_identity.hostname", gs) if gs else (
        session.manifest.get("host", {}).get("hostname") or "pve01"
    )
    domain_default = suggest("host_identity.domain", gs) if gs else "home.example.com"

    hostname = _prompt("  Hostname (e.g. pve01, hatchery)", hostname_default)
    domain   = _prompt("  Domain   (e.g. home.example.com)", domain_default)

    print(f"\n  FQDN will be: {hostname}.{domain}")

    cell_id_default = f"{hostname}-cell"
    if gs:
        from guided_setup import suggest as _suggest
        cell_id_default = _suggest("host_identity.cell_id", gs) or cell_id_default
    cell_id = _prompt("  Cell ID", cell_id_default)

    step2_set_identity(session, hostname=hostname, domain=domain, cell_id=cell_id)

    if session.warnings:
        for w in session.warnings[-3:]:   # show last few
            _warn(w)

    return session


# ---------------------------------------------------------------------------
# Step 3 — Network profile
# ---------------------------------------------------------------------------

def _step3_network(session: ForgePlannerSession) -> ForgePlannerSession:
    _header("Step 3 — Network Profile")
    print()

    sel = _choice([
        ("LAN-only",
         "hatchery accessible only on your local network"),
        ("WAN-capable",
         "hatchery reachable from the internet via Headscale"),
    ], "Network profile:")

    if sel == 1:
        step3_set_network_profile(session, PROFILE_LAN)
    else:
        print("\n  WAN-capable profile requires:")
        print("    - A registered domain name")
        print("    - Port 8080 forwarded on your router to the hatchery")
        print("    - External DNS A record pointing to your WAN IP (or DDNS)\n")

        domain   = session.domain or "home.example.com"
        hostname = session.hostname or "hatchery"
        headscale_url = f"https://{hostname}.{domain}:8080"
        headscale_url = _prompt("  Headscale URL", headscale_url)

        dns_provider = _prompt("  DNS provider for DDNS/TLS (cloudflare/duckdns/other)", "cloudflare")

        wan = {
            "headscale_url": headscale_url,
            "dns_provider":  dns_provider,
        }
        step3_set_network_profile(session, PROFILE_WAN, wan_config=wan)

    return session


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Broodforge forge planner")
    parser.add_argument("--manifest",  default=None, help="Path to existing bootstrap-state.json")
    parser.add_argument("--output",    default="forge-manifest.json", help="Output path")
    args = parser.parse_args()

    manifest: dict = {}
    if args.manifest:
        with open(args.manifest) as f:
            manifest = json.load(f)

    print(f"\n{'=' * 64}")
    print("  Broodforge Forge Planner")
    print(f"{'=' * 64}")
    print("\n  This planner generates a forge-manifest.json that captures")
    print("  your configuration choices for the initial hatchery forge.\n")

    session = ForgePlannerSession(manifest=manifest)

    _step0_mode(session)
    _step1_guided(session)
    _step2_identity(session)
    _step3_network(session)

    plan = build_forge_manifest(session)
    out  = Path(args.output)
    out.write_text(json.dumps(plan, indent=2))

    _header("Forge Manifest Generated")
    print(f"\n  Output:    {out}")
    print(f"  Cell ID:   {plan['cell_id']}")
    print(f"  FQDN:      {plan['host_identity']['fqdn']}")
    print(f"  Mode:      {plan['setup_mode']}")
    print(f"  Profile:   {plan['network_topology']['profile']}")
    if session.setup_overrides:
        print(f"  Overrides: {len(session.setup_overrides)} manual setting(s) recorded")
    if session.warnings:
        print(f"\n  Warnings ({len(session.warnings)}):")
        for w in session.warnings:
            print(f"    ⚠  {w}")
    print("\n  Next steps:")
    print(f"    1. Review {out}")
    print(f"    2. Run: python3 assemble-forge-package.py --manifest {out}")
    print()


if __name__ == "__main__":
    main()
