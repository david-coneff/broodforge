#!/usr/bin/env python3
"""
derive-scoped-vault.py — CLI entry point for the scoped-vault-plan builder
(Phase 1.K, AD-061 — Granular Secret Access Silos: Vault Hierarchy and User
Provisioning).

Loads role-scope-registry.yaml + secret-registry.yaml, builds a derived-vault
plan for the named role (which canonical entries are in scope, a freshly-
generated passphrase + the keepassxc-cli command sequence to actually build
the vault, the parent-vault record path for vault-of-vaults recordkeeping,
and VM/Proxmox user-provisioning templates), and writes
scoped-vault-plan-{role}-{timestamp}.json (+ .html, AD-051 twin) to an output
directory.

This is plan generation only — broodforge does not open, create, or write
live .kdbx files anywhere (see _vault_hierarchy.py's module docstring); the
operator runs the printed command sequence by hand.

Usage:
    python3 derive-scoped-vault.py --role service-operator \\
        [--registry role-scope-registry.yaml] \\
        [--secrets secret-registry.yaml] \\
        [--output-dir /opt/broodforge/vault-plans] \\
        [--repo /path/to/broodforge]

Produces:
    scoped-vault-plan-{role}-{timestamp}.json
    scoped-vault-plan-{role}-{timestamp}.html
"""

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))

from _vault_hierarchy import (
    GOD_MODE_TIER,
    build_derived_vault_plan,
    describe_vault_plan,
    generate_proxmox_account_commands,
    generate_vm_account_template,
    load_role_scope_registry,
    load_secret_registry,
    plan_to_dict,
    render_derive_vault_commands,
)

try:
    from html_package_manifest import build_scoped_vault_plan_html as _build_plan_html
    _HAS_PLAN_HTML = True
except ImportError:
    _build_plan_html = None  # type: ignore
    _HAS_PLAN_HTML = False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a derived-vault plan for one role/scope (Phase 1.K, AD-061)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--role", required=True,
        help="Role name from role-scope-registry.yaml to derive a scoped vault for "
             "(e.g. service-operator, node-sysadmin)",
    )
    parser.add_argument(
        "--registry", default=None,
        help="Path to role-scope-registry.yaml (default: alongside this script)",
    )
    parser.add_argument(
        "--secrets", default=None,
        help="Path to secret-registry.yaml (default: alongside this script)",
    )
    parser.add_argument(
        "--output-dir", default=".",
        help="Directory to write the plan into (default: current directory)",
    )
    args = parser.parse_args()

    registry_path = Path(args.registry) if args.registry else (_HERE / "role-scope-registry.yaml")
    secrets_path = Path(args.secrets) if args.secrets else (_HERE / "secret-registry.yaml")

    if not registry_path.exists():
        print(f"[error] Role/scope registry not found: {registry_path}", file=sys.stderr)
        sys.exit(1)
    if not secrets_path.exists():
        print(f"[error] Secret registry not found: {secrets_path}", file=sys.stderr)
        sys.exit(1)

    roles = load_role_scope_registry(str(registry_path))
    role_raw = next((r for r in roles if r.get("role") == args.role), None)
    if role_raw is None:
        known = ", ".join(r.get("role", "?") for r in roles)
        print(f"[error] Role '{args.role}' not found in {registry_path}. Known roles: {known}",
              file=sys.stderr)
        sys.exit(1)

    if (role_raw.get("tier") or "") == GOD_MODE_TIER:
        print(f"[error] Role '{args.role}' is tier '{GOD_MODE_TIER}' — refusing to derive a "
              f"vault from the canonical vault into itself (AD-061: 'god-mode IS the canonical "
              f"vault'). There is nothing to derive.", file=sys.stderr)
        sys.exit(1)

    secret_entries = load_secret_registry(str(secrets_path))

    plan = build_derived_vault_plan(role_raw, secret_entries)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = plan.generated_at[:19].replace(":", "_").replace("T", "_")
    base_name = f"scoped-vault-plan-{plan.role}-{timestamp}"

    plan_dict = plan_to_dict(plan, include_passphrase=False)
    json_path = output_dir / f"{base_name}.json"
    json_path.write_text(json.dumps(plan_dict, indent=2), encoding="utf-8")

    if _HAS_PLAN_HTML:
        html_text = _build_plan_html(plan_dict)
    else:
        html_text = "<html><body><pre>" + json.dumps(plan_dict, indent=2) + "</pre></body></html>"
    html_path = output_dir / f"{base_name}.html"
    html_path.write_text(html_text, encoding="utf-8")

    vm_account = generate_vm_account_template(role_raw, plan)
    pve_commands = generate_proxmox_account_commands(role_raw, plan)
    vault_commands = render_derive_vault_commands(plan)

    print(f"\n{'=' * 64}")
    print(f"  Derived Vault Plan Built — role: {plan.role} (tier: {plan.tier})")
    print(f"{'=' * 64}")
    print(f"  Plan JSON:  {json_path}")
    print(f"  HTML twin:  {html_path}")
    print(f"  In scope:   {len(plan.entries)} of {plan.total_registry_count} canonical entries "
          f"({plan.excluded_count} excluded)")
    print()
    print(describe_vault_plan(plan))
    print()
    print("-" * 64)
    print("  keepassxc-cli command sequence (operator-run — copy/paste into a shell")
    print("  with DERIVED_VAULT_PASSWORD and KEEPASS_MASTER_PASSWORD set):")
    print("-" * 64)
    for cmd in vault_commands:
        print(f"  {cmd}")
    print()
    print("-" * 64)
    print("  VM-level user-provisioning template (additive Cloud-Init account block —")
    print("  splice into spawn_iac_generator.generate_cloudinit_user_data()'s users: list):")
    print("-" * 64)
    print(vm_account["yaml_block"])
    print("-" * 64)
    print("  Proxmox-level user-provisioning template (operator-run pveum commands):")
    print("-" * 64)
    for cmd in pve_commands:
        print(f"  {cmd}")
    print()
    print("=" * 64)
    print("  IMPORTANT — single-use, shown-once derived-vault passphrase:")
    print(f"    {plan.passphrase}")
    print(f"  (source: {plan.passphrase_source})")
    print("  Note this down now — it will not be recoverable from the plan files later.")
    print("  Store it ONLY at this path inside the PARENT (canonical) vault:")
    print(f"    {plan.parent_record_path}")
    print("  That parent-vault record is the entire 'vault of vaults' recovery path —")
    print("  see the HTML twin for the authorization-model and revocation design notes.")
    print("=" * 64)
    print()


if __name__ == "__main__":
    main()
