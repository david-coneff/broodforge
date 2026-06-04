#!/usr/bin/env python3
"""
spawn-planner.py — Interactive spawn planner CLI (Phase 12.E.3).

Run on the hatchery to plan and generate a spawn package for a new broodling.

Usage:
    python3 spawn-planner.py \\
        --state bootstrap-state.json \\
        [--hardware hardware-profile-pve02.json] \\
        [--catalog service-catalog.yaml] \\
        [--output-dir /opt/broodforge/spawn-packages]

After the interactive session, produces:
    spawn-plan-{hostname}.json
    spawn-package-{cell_id}-{hostname}-{timestamp}.tar.gz  (via assembler)

Stdlib only.
"""

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))

from hatchery_state import read_hatchery_state
from spawn_planner import (
    ServiceCatalog, SpawnPlannerSession,
    NET_LAN, NET_WAN, NET_SPECIFY,
    EXEC_AUTONOMOUS, EXEC_INTERACTIVE,
    SEL_FULL_MIRROR, SEL_GROUP, SEL_INDIVIDUAL,
    FIT_OK, FIT_MARGINAL, FIT_NO_FIT,
    step0_set_network_mode, step_guided_setup, step1_set_execution_mode,
    step2_select_services, step3_allocate_resources,
    assess_all_services, full_mirror_services,
    build_spawn_plan,
    GROUPS,
)
from guided_setup import SETTING_GROUPS, group_selector_rows, suggest, set_value


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
    """Present a numbered menu, return 1-based selection index."""
    print(f"\n{title}")
    for i, (label, desc) in enumerate(options, 1):
        print(f"  {i}. {label:<22} — {desc}")
    while True:
        raw = _prompt("\nSelection", str(1))
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


# ---------------------------------------------------------------------------
# Step 0 — Network mode
# ---------------------------------------------------------------------------

def _step0_interactive(session: SpawnPlannerSession, state: dict) -> SpawnPlannerSession:
    _header("Step 0 — Network Mode")
    print("\n  Determines how the hatchery reaches the broodling for hardware")
    print("  discovery and how the broodling joins the tailnet (WAN only).\n")

    _nt = state.get("network_topology") or {}
    wan = _nt.get("wan_config") or {}
    headscale_url = wan.get("headscale_url") or _nt.get("headscale_url") or ""

    sel = _choice([
        ("Same LAN",  "direct SSH using temporary root password"),
        ("WAN",       f"Headscale tailnet {headscale_url or '(configure WAN first)'}"),
        ("Specify",   "enter broodling IP or hostname manually"),
    ], "Is the broodling on the same LAN as the hatchery?")

    if sel == 1:
        ip = _prompt("Broodling LAN IP (e.g. 192.168.1.15)")
        step0_set_network_mode(session, NET_LAN, broodling_ip=ip)

    elif sel == 2:
        if not headscale_url:
            print("  WARNING: WAN config not found in bootstrap-state.json.")
            print("  Run setup_network.py to configure WAN profile first.")
            headscale_url = _prompt("Headscale URL", "https://hatchery.example.com:8080")
        auth_key = _generate_headscale_auth_key(headscale_url)
        step0_set_network_mode(session, NET_WAN,
                               wan_auth_key=auth_key,
                               headscale_url=headscale_url)

    else:
        ip = _prompt("Broodling IP or hostname")
        step0_set_network_mode(session, NET_SPECIFY, broodling_ip=ip)

    return session


def _generate_headscale_auth_key(headscale_url: str) -> str:
    """Attempt to generate a Headscale auth key. Returns key or placeholder."""
    import subprocess
    try:
        result = subprocess.run(
            ["headscale", "authkeys", "generate",
             "--expiration", "1h",
             "--user", "broodforge"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            key = result.stdout.strip()
            print("  [headscale] Auth key generated — embedded in spawn package.")
            return key
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    print("  [headscale] Could not generate auth key automatically.")
    return _prompt("Enter Headscale auth key (or leave blank to embed manually)")


# ---------------------------------------------------------------------------
# Step 0.5 — Guided setup (optional)
# ---------------------------------------------------------------------------

def _step0_5_guided_setup(
    session: SpawnPlannerSession, state: dict
) -> SpawnPlannerSession:
    """Offer guided setup for customising spawn settings."""
    _header("Step 0.5 — Spawn Settings (Guided Setup)")
    print("\n  Auto-calculated settings cover most cases. You can optionally")
    print("  customise IP addressing, storage topology, VM sizing, and more.\n")

    sel = _choice([
        ("Skip (default)",    "use auto-calculated settings"),
        ("IP-Selective",      "choose IP addressing only"),
        ("Group-Manual",      "select setting groups to configure"),
        ("Full-Manual",       "walk through all settings with suggestions"),
    ], "Customise spawn settings?")

    if sel == 1:
        return session

    mode_map = {2: "ip-selective", 3: "group-manual", 4: "full-manual"}
    mode = mode_map[sel]

    if mode == "ip-selective":
        # Show IP field suggestions and prompt
        from guided_setup import GuidedSetupSession, suggest as gs_suggest
        _gs = GuidedSetupSession(mode=mode, manifest=state)
        ip_values = {}
        for fp in ("network.management_cidr", "network.gateway"):
            current = gs_suggest(fp, _gs)
            val = _prompt(f"  {fp}", str(current))
            ip_values[fp] = val
        step_guided_setup(session, mode, state, ip_values=ip_values)

    elif mode == "group-manual":
        # Show group selector
        from guided_setup import GuidedSetupSession, group_selector_rows as _gsr
        _gs = GuidedSetupSession(mode=mode, manifest=state)
        rows = _gsr(_gs)
        selected_groups = []
        for row in rows:
            auto = row["auto_suggestion"]
            ans = _prompt(
                f"  Configure {row['label']:<12} (auto: {str(auto)[:25]}) (y/N)", "n"
            )
            if ans.lower() == "y":
                selected_groups.append(row["group_id"])

        field_values = {}
        for gid in selected_groups:
            gdef = SETTING_GROUPS[gid]
            _header(f"Group: {gdef['label']}")
            from guided_setup import GuidedSetupSession, suggest as gs_suggest
            _gs2 = GuidedSetupSession(mode=mode, manifest=state,
                                       selected_groups=set(selected_groups))
            for fp in gdef["fields"]:
                current = gs_suggest(fp, _gs2)
                current_str = (
                    ",".join(current) if isinstance(current, list) else str(current)
                ) if current is not None else ""
                val_raw = _prompt(f"  {fp}", current_str)
                if isinstance(current, list):
                    field_values[fp] = [s.strip() for s in val_raw.split(",") if s.strip()]
                elif isinstance(current, bool):
                    field_values[fp] = val_raw.lower() in ("true", "yes", "1", "y")
                elif isinstance(current, int):
                    try:
                        field_values[fp] = int(val_raw)
                    except ValueError:
                        field_values[fp] = val_raw
                else:
                    field_values[fp] = val_raw
        step_guided_setup(session, mode, state,
                         selected_groups=selected_groups, field_values=field_values)

    elif mode == "full-manual":
        field_values = {}
        from guided_setup import GuidedSetupSession, suggest as gs_suggest
        _gs = GuidedSetupSession(mode=mode, manifest=state)
        for gid, gdef in SETTING_GROUPS.items():
            _header(f"Group: {gdef['label']}")
            for fp in gdef["fields"]:
                current = gs_suggest(fp, _gs)
                current_str = (
                    ",".join(current) if isinstance(current, list) else str(current)
                ) if current is not None else ""
                val_raw = _prompt(f"  {fp}", current_str)
                if isinstance(current, list):
                    field_values[fp] = [s.strip() for s in val_raw.split(",") if s.strip()]
                elif isinstance(current, bool):
                    field_values[fp] = val_raw.lower() in ("true", "yes", "1", "y")
                elif isinstance(current, int):
                    try:
                        field_values[fp] = int(val_raw)
                    except ValueError:
                        field_values[fp] = val_raw
                else:
                    field_values[fp] = val_raw
        step_guided_setup(session, mode, state, field_values=field_values)

    if session.setup_overrides:
        print(f"\n  {len(session.setup_overrides)} manual setting(s) recorded.")

    return session


# ---------------------------------------------------------------------------
# Step 1 — Execution mode
# ---------------------------------------------------------------------------

def _step1_interactive(session: SpawnPlannerSession) -> SpawnPlannerSession:
    _header("Step 1 — Execution Mode")

    sel = _choice([
        ("Autonomous (default)", "finalise service selection now; spawn.sh runs automatically"),
        ("Interactive",          "service menu evaluated on the broodling at runtime"),
    ], "How should the spawn package run on the broodling?")

    step1_set_execution_mode(session, EXEC_AUTONOMOUS if sel == 1 else EXEC_INTERACTIVE)

    if session.execution_mode == EXEC_AUTONOMOUS:
        pw = session.temp_root_password
        print(f"\n  Suggested temporary root password (use during Proxmox install):")
        print(f"    {pw}")
        print(f"  This password is held in session memory and used for SSH discovery.")
        print(f"  It will be replaced by a KeePass-managed credential during spawn.")
        _prompt("\nPress Enter when you have noted the password")

    return session


# ---------------------------------------------------------------------------
# Step 2 — Service selection (autonomous only)
# ---------------------------------------------------------------------------

def _display_fit(fit_results: dict, catalog: ServiceCatalog):
    symbols = {FIT_OK: "[✓]", FIT_MARGINAL: "[!]", FIT_NO_FIT: "[✗]"}
    print()
    for svc in catalog.all():
        name = svc["name"]
        fit  = fit_results.get(name)
        if fit:
            sym  = symbols.get(fit.status, "[?]")
            desc = svc.get("description", "")[:45]
            print(f"  {sym} {name:<22} {fit.reason[:40]}")


def _step2_interactive(
    session:    SpawnPlannerSession,
    catalog:    ServiceCatalog,
    hardware:   dict,
    host_ram_gb: float,
) -> SpawnPlannerSession:
    _header("Step 2 — Service Selection")
    print("\n  Hardware fit assessment:")

    fit_results = assess_all_services(catalog, hardware, host_ram_gb)
    _display_fit(fit_results, catalog)

    sel = _choice([
        ("Full mirror",      "all services that fit this hardware"),
        ("By group",         "select groups, then fine-tune individual services"),
        ("Individually",     "pick each service one by one"),
    ], "\nService selection mode:")

    if sel == 1:
        step2_select_services(session, catalog, hardware, host_ram_gb, SEL_FULL_MIRROR)

    elif sel == 2:
        selected = _group_selection(catalog, fit_results)
        step2_select_services(session, catalog, hardware, host_ram_gb,
                              SEL_GROUP, manual_selection=selected)

    else:
        selected = _individual_selection(catalog, fit_results)
        step2_select_services(session, catalog, hardware, host_ram_gb,
                              SEL_INDIVIDUAL, manual_selection=selected)

    # Show summary
    print(f"\n  Selected ({len(session.selected_services)}):")
    for s in session.selected_services:
        print(f"    + {s}")
    if session.excluded_services:
        print(f"\n  Excluded ({len(session.excluded_services)}):")
        for e in session.excluded_services:
            print(f"    - {e['service']}: {e['reason']}")

    return session


def _group_selection(catalog: ServiceCatalog, fit_results: dict) -> list[str]:
    selected = []
    for group in catalog.groups():
        svcs = [s for s in catalog.by_group(group) if not s.get("baseline")]
        if not svcs:
            continue
        opts = [
            (f"Include {group}", f"{len(svcs)} service(s)"),
            (f"Skip {group}", ""),
        ]
        choice = _choice(opts, f"Group: {group}")
        if choice == 1:
            selected.extend(s["name"] for s in svcs
                           if fit_results.get(s["name"], {}).get("status") != FIT_NO_FIT)
    return selected


def _individual_selection(catalog: ServiceCatalog, fit_results: dict) -> list[str]:
    selected = []
    symbols = {FIT_OK: "✓", FIT_MARGINAL: "!", FIT_NO_FIT: "✗"}
    for svc in catalog.all():
        if svc.get("baseline"):
            continue
        fit = fit_results.get(svc["name"])
        if fit and fit.status == FIT_NO_FIT:
            print(f"  [✗] {svc['name']:<22} SKIPPED — {fit.reason}")
            continue
        sym = symbols.get(fit.status if fit else "?", "?")
        val = _prompt(f"  [{sym}] Include {svc['name']}? (y/N)", "n")
        if val.lower() == "y":
            selected.append(svc["name"])
    return selected


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Broodforge spawn planner")
    parser.add_argument("--state",    required=True, help="Path to bootstrap-state.json")
    parser.add_argument("--hardware", default=None,  help="Path to hardware-profile.json")
    parser.add_argument("--catalog",  default=None,  help="Path to service-catalog.yaml")
    parser.add_argument("--output-dir", default=".",  help="Output directory for spawn plan")
    args = parser.parse_args()

    # Load inputs
    with open(args.state) as f:
        state = json.load(f)

    hardware: dict = {}
    if args.hardware:
        with open(args.hardware) as f:
            hardware = json.load(f)

    catalog = ServiceCatalog.from_file(args.catalog or None)
    manifest = read_hatchery_state(state, {})
    host_ram_gb = float((state.get("capacity_model") or {}).get("host_ram_gb") or 32)

    # Run planner steps
    cell_id = state.get("cell_id", "unknown")
    print(f"\n{'=' * 64}")
    print(f"  Broodforge Spawn Planner — Cell: {cell_id}")
    print(f"{'=' * 64}")

    session = SpawnPlannerSession()
    _step0_interactive(session, state)
    _step0_5_guided_setup(session, state)
    _step1_interactive(session)

    if session.execution_mode == EXEC_AUTONOMOUS:
        _step2_interactive(session, catalog, hardware, host_ram_gb)

    step3_allocate_resources(session, manifest, state, catalog, hardware or None)

    # Build and write plan
    plan = build_spawn_plan(session, manifest, state, catalog, hardware or None)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    hostname  = plan.get("hostname", "broodling")
    plan_path = output_dir / f"spawn-plan-{hostname}.json"
    plan_path.write_text(json.dumps(plan, indent=2))

    _header("Spawn Plan Generated")
    print(f"\n  Plan written to: {plan_path}")
    print(f"  Hostname:        {hostname}")
    print(f"  VMIDs:           {[v['vmid'] for v in plan.get('vms', [])]}")
    print(f"  IPs:             {[v['ip'] for v in plan.get('vms', [])]}")
    print(f"  k3s role:        {plan.get('k3s', {}).get('role', '?')}")
    print(f"\n  Next steps:")
    print(f"    1. Review spawn-plan-{hostname}.json")
    print(f"    2. Run: python3 assemble-spawn-package.py --plan {plan_path} --state bootstrap-state.json")
    print(f"    3. Copy spawn package to broodling and run: bash spawn.sh")
    print()


if __name__ == "__main__":
    main()
