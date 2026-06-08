#!/usr/bin/env python3
"""
setup_recovery_account.py — constrained recovery account plan generator/writer
(Phase 1.J, AD-060(a)).

Mirrors setup_dnsmasq.py / setup_headscale.py's CLI shape (a config/plan
generator invocable during forge phase-03, or standalone by an operator) —
NOT a live-account-provisioning tool. It builds a recovery-account-
provisioning-plan (_recovery_accounts.build_recovery_account_plan) and writes
its artifacts (plan JSON, AD-051 HTML twin, the fixed-menu script text, and
an authorized_keys snippet) to an output directory for an operator or phase-03
step to install on the target hypervisor.

broodforge does NOT install, enable, or run any of this on a live host — see
_recovery_accounts.py's module docstring for why that boundary matters
(AD-060: "no autonomous pathway may read or wield full root credentials
against live hypervisors" — this account is the bounded-by-construction
exception, but *installing* it is still a one-time, human-supervised,
phase-03-class action, like every other phase-03 step).

Usage:
    python3 setup_recovery_account.py \\
        --hostname pve01 --public-key "ssh-ed25519 AAAA... operator@workstation" \\
        --cell-id proxmox-cell-a [--secrets secret-registry.yaml] \\
        --output-dir /opt/broodforge/recovery-plans

Produces (in --output-dir):
    recovery-account-plan-{hostname}-{timestamp}.json
    recovery-account-plan-{hostname}-{timestamp}.html
    recovery-account-plan-{hostname}-{timestamp}.menu.sh
    recovery-account-plan-{hostname}-{timestamp}.authorized_keys
"""

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))

from _recovery_accounts import build_recovery_account_plan, DEFAULT_ACCOUNT_NAME, DEFAULT_MENU_SCRIPT_PATH

try:
    from _vault_hierarchy import load_secret_registry
    _HAS_SECRET_LOADER = True
except ImportError:
    load_secret_registry = None  # type: ignore
    _HAS_SECRET_LOADER = False

try:
    from html_package_manifest import build_recovery_account_plan_html as _build_plan_html
    _HAS_PLAN_HTML = True
except ImportError:
    _build_plan_html = None  # type: ignore
    _HAS_PLAN_HTML = False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a constrained recovery account provisioning plan "
                    "(Phase 1.J, AD-060(a)) — generates strings only; never "
                    "installs, runs, or connects with them.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--hostname", required=True,
                        help="Target hypervisor hostname (e.g. pve01)")
    parser.add_argument("--public-key", required=True,
                        help="Operator's OpenSSH public key line for the recovery account")
    parser.add_argument("--cell-id", default=None, help="Cell identifier for the plan")
    parser.add_argument("--account-name", default=DEFAULT_ACCOUNT_NAME,
                        help=f"Recovery account name (default: {DEFAULT_ACCOUNT_NAME})")
    parser.add_argument("--menu-script-path", default=DEFAULT_MENU_SCRIPT_PATH,
                        help=f"Absolute path the menu script will live at on the target host "
                             f"(default: {DEFAULT_MENU_SCRIPT_PATH})")
    parser.add_argument("--secrets", default=None,
                        help="Path to secret-registry.yaml (for break-glass pointer display only "
                             "— PATHS, never values; default: alongside this script)")
    parser.add_argument("--output-dir", default=".",
                        help="Directory to write the plan artifacts into (default: current directory)")
    args = parser.parse_args()

    secret_entries = []
    if _HAS_SECRET_LOADER:
        secrets_path = Path(args.secrets) if args.secrets else (_HERE / "secret-registry.yaml")
        if secrets_path.exists():
            secret_entries = load_secret_registry(str(secrets_path))

    plan = build_recovery_account_plan(
        node_hostname=args.hostname,
        public_key=args.public_key,
        cell_id=args.cell_id,
        account_name=args.account_name,
        menu_script_path=args.menu_script_path,
        secret_registry_entries=secret_entries,
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = (plan["generated_at"] or "")[:19].replace(":", "_").replace("T", "_")
    base_name = f"recovery-account-plan-{plan['node_hostname']}-{timestamp}"

    json_path = output_dir / f"{base_name}.json"
    json_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")

    if _HAS_PLAN_HTML:
        html_text = _build_plan_html(plan)
    else:
        html_text = "<html><body><pre>" + json.dumps(plan, indent=2) + "</pre></body></html>"
    html_path = output_dir / f"{base_name}.html"
    html_path.write_text(html_text, encoding="utf-8")

    menu_path = output_dir / f"{base_name}.menu.sh"
    menu_path.write_text(plan["menu_script"]["contents"], encoding="utf-8")

    keys_path = output_dir / f"{base_name}.authorized_keys"
    keys_path.write_text(plan["account"]["authorized_keys_line"] + "\n", encoding="utf-8")

    print(f"\n{'=' * 72}")
    print(f"  Recovery Account Plan Built — node: {plan['node_hostname']}")
    print(f"{'=' * 72}")
    print(f"  Plan JSON:        {json_path}")
    print(f"  HTML twin:        {html_path}")
    print(f"  Menu script:      {menu_path}")
    print(f"  authorized_keys:  {keys_path}")
    print()
    print("-" * 72)
    print("  MANUAL INSTALLATION STEPS (operator/phase-03 — broodforge does NOT")
    print("  install, enable, or run any of this on a live hypervisor):")
    print("-" * 72)
    print(f"  1. Create the account:")
    print(f"       useradd -r -m -s /usr/sbin/nologin {plan['account']['name']}")
    print(f"  2. Install the menu script (root-owned, executable):")
    print(f"       install -o root -g root -m 0755 {menu_path.name} {plan['account']['menu_script_path']}")
    print(f"  3. Install the authorized_keys entry:")
    print(f"       mkdir -p ~{plan['account']['name']}/.ssh")
    print(f"       cat {keys_path.name} >> ~{plan['account']['name']}/.ssh/authorized_keys")
    print(f"       chown -R {plan['account']['name']}:{plan['account']['name']} ~{plan['account']['name']}/.ssh")
    print(f"       chmod 700 ~{plan['account']['name']}/.ssh && chmod 600 ~{plan['account']['name']}/.ssh/authorized_keys")
    print("-" * 72)
    if plan["break_glass_pointers"]:
        print()
        print("  Break-glass root pointers (KeePass PATHS for operator lookup ONLY —")
        print("  broodforge never reads these entries' values):")
        for p in plan["break_glass_pointers"]:
            print(f"    {p['id']}: {p['keepass_path']}")
    print()
    print("=" * 72)
    print("  AD-060: this account's blast radius is bounded BY CONSTRUCTION —")
    print("  fixed menu, no-pty, no port/X11/agent forwarding, regex-validated")
    print("  vmid. It can never become a root-equivalent shell. It is the ONE")
    print("  piece of the recovery surface AD-060 names as safe to query")
    print("  autonomously. See ARCHITECTURE.md AD-060 for the full constraint.")
    print("=" * 72)
    print()


if __name__ == "__main__":
    main()
