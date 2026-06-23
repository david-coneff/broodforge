#!/usr/bin/env python3
"""
_vault_hierarchy.py — Scoped vault hierarchy and user-provisioning template
builder (Phase 1.K, AD-061 — Granular Secret Access Silos).

KeePass/.kdbx databases are single-master-password — there is no per-user ACL
layer inside one file. AD-061's accepted design is therefore *derived vaults*:
smaller .kdbx files holding only an in-scope subset of secrets, each with its
own freshly-generated passphrase, rather than any broker/ACL system (which
would require a network-dependent identity service and violate broodforge's
offline-first/stdlib-only constraints — see AD-042, AD-061).

This module does NOT open, create, or otherwise manipulate live .kdbx files —
broodforge has no code path that does that anywhere (forge_keepass_init.py and
setup-secrets.py both *generate keepassxc-cli command strings* for an operator
to run; they never touch the binary KDBX format in Python). This module
follows that exact pattern: it reads secret-registry.yaml (the canonical
source of which secrets exist and what they're for) plus a Role/Scope
registry, and produces a *derived-vault plan* — structured data plus the
keepassxc-cli command sequence an operator runs to actually build the vault —
mirroring forge_keepass_init.py::render_init_commands()/describe_init_plan().

Provides:
  RoleScope                — one role's scope declaration (dataclass)
  load_role_scope_registry()    — parse role-scope-registry.yaml
  load_secret_registry()        — parse secret-registry.yaml
  match_scope()                 — does one secret-registry entry match a scope?
  select_scoped_entries()       — filter secret-registry entries by role scope
  vault_record_path()           — AD-044-style KeePass path for a derived
                                  vault's passphrase record in the parent vault
  build_derived_vault_plan()    — compose the full plan (dataclass)
  render_derive_vault_commands()— keepassxc-cli command sequence (operator-run)
  describe_vault_plan()         — human-readable plan description
  generate_vm_account_template()      — additive Cloud-Init account block
  generate_proxmox_account_commands() — pveum command sequence (operator-run)
  plan_to_dict()                — serialise for JSON / testing

Stdlib only (fnmatch for glob matching; PyYAML if present, else a minimal
fallback parser matching generate_talos_config.py::_load_yaml_simple's
established precedent).
"""

import fnmatch
import shlex
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

# deal contracts — graceful no-op when deal is not installed (dev dep only)
try:
    import deal as _deal
    _deal_pre  = _deal.pre
    _deal_post = _deal.post
except ImportError:  # pragma: no cover
    def _deal_pre(_c):   return lambda f: f  # type: ignore
    def _deal_post(_c):  return lambda f: f  # type: ignore

try:
    import os as _os
    import sys as _sys
    _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))
    from passphrase import generate_master_password_suggestion
    _HAS_PASSPHRASE = True
except ImportError:
    _HAS_PASSPHRASE = False

SCHEMA_VERSION = "1.0"

GOD_MODE_TIER = "god-mode"


def _default_now_fn() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Minimal YAML loading (PyYAML if available; else a stdlib fallback)
# ---------------------------------------------------------------------------

def _load_yaml(path: str) -> dict:
    """
    Load a YAML file. Tries PyYAML first (already an optional dependency
    elsewhere — see generate_talos_config.py::_load_yaml_simple,
    setup_dnsmasq.py, validate-metadata.py); falls back to a minimal
    stdlib-only parser sufficient for the flat list-of-mappings shape
    role-scope-registry.yaml and secret-registry.yaml both use.
    """
    try:
        import yaml  # type: ignore
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        pass
    return _parse_simple_registry_yaml(path)


def _parse_simple_registry_yaml(path: str) -> dict:
    """
    Minimal fallback parser for the specific shape these two registries use:
    a top-level `key:` followed by a list of mappings, each mapping made of
    `field: scalar`, `field: [a, b]`, or `field:` followed by an indented list
    or nested mapping. Not a general YAML parser — sufficient for these files.
    """
    with open(path, encoding="utf-8") as f:
        raw_lines = f.readlines()

    lines = []
    for line in raw_lines:
        stripped = line.split(" #", 1)[0].rstrip("\n")
        if stripped.strip().startswith("#") or not stripped.strip():
            continue
        lines.append(stripped)

    def indent_of(s: str) -> int:
        return len(s) - len(s.lstrip(" "))

    def parse_scalar(s: str):
        s = s.strip()
        if s in ("", "{}", "null", "~"):
            return {} if s == "{}" else None
        if s == "[]":
            return []
        if s.startswith("[") and s.endswith("]"):
            inner = s[1:-1].strip()
            if not inner:
                return []
            return [parse_scalar(part) for part in _split_top_level(inner)]
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            return s[1:-1]
        if s.lower() in ("true", "yes"):
            return True
        if s.lower() in ("false", "no"):
            return False
        try:
            if "." not in s:
                return int(s)
        except ValueError:
            pass
        return s

    def _split_top_level(s: str) -> list:
        parts, depth, cur = [], 0, ""
        for ch in s:
            if ch in "[{":
                depth += 1
            elif ch in "]}":
                depth -= 1
            if ch == "," and depth == 0:
                parts.append(cur)
                cur = ""
            else:
                cur += ch
        if cur.strip():
            parts.append(cur)
        return [p.strip() for p in parts]

    def parse_block(start: int, base_indent: int):
        """Parse a sequence of `key: value` / `- item` lines at base_indent."""
        result_list = None
        result_map = None
        i = start
        while i < len(lines):
            line = lines[i]
            ind = indent_of(line)
            if ind < base_indent:
                break
            if ind > base_indent:
                i += 1
                continue
            stripped = line.strip()
            if stripped.startswith("- "):
                if result_list is None:
                    result_list = []
                item_line = stripped[2:]
                if ":" in item_line and not item_line.startswith(("[", "{", '"', "'")):
                    key, _, rest = item_line.partition(":")
                    key = key.strip()
                    rest = rest.strip()
                    if rest:
                        item = {key: parse_scalar(rest)}
                        i += 1
                    else:
                        item_indent = ind + 2
                        sub, i = parse_block(i + 1, item_indent)
                        item = {key: sub}
                    nested, i = parse_block(i, ind + 2)
                    if isinstance(nested, dict):
                        item.update(nested)
                    result_list.append(item)
                else:
                    result_list.append(parse_scalar(item_line))
                    i += 1
            elif ":" in stripped:
                if result_map is None:
                    result_map = {}
                key, _, rest = stripped.partition(":")
                key = key.strip()
                rest = rest.strip()
                if rest == ">" or rest == "|":
                    block_indent = ind + 2
                    text_lines = []
                    i += 1
                    while i < len(lines) and (not lines[i].strip() or indent_of(lines[i]) >= block_indent):
                        if lines[i].strip():
                            text_lines.append(lines[i].strip())
                        i += 1
                    result_map[key] = " ".join(text_lines)
                elif rest:
                    result_map[key] = parse_scalar(rest)
                    i += 1
                else:
                    sub, i = parse_block(i + 1, ind + 2)
                    result_map[key] = sub if sub is not None else None
            else:
                i += 1
        if result_list is not None:
            return result_list, i
        return result_map, i

    parsed, _ = parse_block(0, 0)
    return parsed or {}


def load_role_scope_registry(path: str) -> list[dict]:
    """Load role-scope-registry.yaml; returns the list of raw role mappings."""
    data = _load_yaml(path)
    return list(data.get("roles") or [])


def load_secret_registry(path: str) -> list[dict]:
    """Load secret-registry.yaml; returns the list of raw secret mappings."""
    data = _load_yaml(path)
    return list(data.get("secrets") or [])


# ---------------------------------------------------------------------------
# Role/Scope dataclass + matching
# ---------------------------------------------------------------------------

@dataclass
class RoleScope:
    """One role's declared scope over secret-registry.yaml entries."""
    role:         str
    description:  str = ""
    tier:         str = "service-operator"
    required_by:  list[str] = field(default_factory=list)
    owning_cell:  list[str] = field(default_factory=list)
    secret_type:  list[str] = field(default_factory=list)
    required_for: list[str] = field(default_factory=list)
    excludes:     list[str] = field(default_factory=list)
    holders:      list[str] = field(default_factory=list)


def role_scope_from_dict(raw: dict) -> RoleScope:
    """Build a RoleScope from one raw role-scope-registry.yaml mapping."""
    scope = raw.get("scope") or {}
    return RoleScope(
        role=raw.get("role") or "unnamed-role",
        description=(raw.get("description") or "").strip(),
        tier=raw.get("tier") or "service-operator",
        required_by=list(scope.get("required_by") or []),
        owning_cell=list(scope.get("owning_cell") or []),
        secret_type=list(scope.get("secret_type") or []),
        required_for=list(scope.get("required_for") or []),
        excludes=list(raw.get("excludes") or []),
        holders=list(raw.get("holders") or []),
    )


def _any_glob_match(patterns: list[str], values) -> bool:
    """True if any of `patterns` glob-matches any of `values` (str or list)."""
    if not patterns:
        return False
    candidates = values if isinstance(values, (list, tuple)) else [values]
    for pattern in patterns:
        for value in candidates:
            if value and fnmatch.fnmatch(str(value), pattern):
                return True
    return False


def match_scope(scope: RoleScope, entry: dict) -> bool:
    """
    Does this secret-registry.yaml entry fall within this role's scope?

    A union match (AD-061's "hierarchical scope expressed as glob patterns
    over owning_cell/required_by … or by secret_type/required_for facets") —
    an entry is in-scope if ANY populated facet matches, then dropped if it
    additionally matches an `excludes` glob against its `id`. An empty scope
    (god-mode) matches nothing here by design — see build_derived_vault_plan,
    which refuses to derive a vault for the god-mode tier rather than
    special-casing "empty scope means everything" into this matcher.
    """
    facets_populated = any([scope.required_by, scope.owning_cell,
                            scope.secret_type, scope.required_for])
    if not facets_populated:
        return False

    matched = (
        _any_glob_match(scope.required_by, entry.get("required_by") or [])
        or _any_glob_match(scope.owning_cell, entry.get("owning_cell"))
        or _any_glob_match(scope.secret_type, entry.get("secret_type"))
        or _any_glob_match(scope.required_for, entry.get("required_for") or [])
    )
    if not matched:
        return False
    if scope.excludes and _any_glob_match(scope.excludes, entry.get("id")):
        return False
    return True


def select_scoped_entries(scope: RoleScope, secret_entries: list[dict]) -> list[dict]:
    """Return the subset of secret-registry entries that fall in `scope`."""
    return [e for e in secret_entries if match_scope(scope, e)]


# ---------------------------------------------------------------------------
# Vault-of-vaults recordkeeping (AD-044 path-naming convention, generalised)
# ---------------------------------------------------------------------------

def vault_record_path(role: str, timestamp: str) -> str:
    """
    KeePass path under which a derived vault's freshly-generated passphrase
    is recorded in the *next tier up's* vault — generalising AD-044's
    `Backup/{layer}/{component}/{timestamp}/repo-password` per-run unique-
    secret bookkeeping convention to "Vaults/{scope-name}/{timestamp}/passphrase".

    This is where the higher-tier (ultimately god-mode/canonical) vault's
    operator stores the record that lets them recover any scoped vault's
    passphrase from their own vault — AD-061's "vault of vaults" expansion.
    """
    return f"Vaults/{role}/{timestamp}/passphrase"


# ---------------------------------------------------------------------------
# Derived-vault plan
# ---------------------------------------------------------------------------

@dataclass
class DerivedVaultPlan:
    """A complete plan for deriving one scoped vault — data, never live KDBX."""
    role:               str
    tier:               str
    description:        str
    db_path:            str
    parent_db_path:     str
    generated_at:       str
    passphrase:         str
    passphrase_source:  str
    parent_record_path: str
    holders:            list[str] = field(default_factory=list)
    entries:            list[dict] = field(default_factory=list)
    excluded_count:     int = 0
    total_registry_count: int = 0


@_deal_pre(lambda role_raw, secret_entries, **_kw: isinstance(role_raw, dict) and isinstance(secret_entries, list))
@_deal_post(lambda result: hasattr(result, "role") and hasattr(result, "entries") and hasattr(result, "db_path"))
def build_derived_vault_plan(
    role_raw:          dict,
    secret_entries:    list[dict],
    parent_db_path:    str = "/etc/broodforge/keepass.kdbx",
    derived_db_dir:    str = "/etc/broodforge/vaults",
    now_fn:            Optional[Callable[[], str]] = None,
    passphrase:        Optional[str] = None,
    passphrase_source: Optional[str] = None,
) -> DerivedVaultPlan:
    """
    Compose a DerivedVaultPlan for one role.

    Generates a fresh passphrase via lib/passphrase.generate_master_password_suggestion()
    (unless the caller supplies one — tests do, to stay deterministic) and computes
    the parent-vault record path the passphrase must be written to (vault-of-vaults).

    Refuses to build a plan for the god-mode tier: deriving "everything" from
    "everything" under a freshly-generated (and therefore *weaker*, single-use-
    suggestion-strength) passphrase would only produce a second copy of the
    canonical vault with strictly worse properties — not a meaningful silo.
    God-mode is, and remains, the canonical vault itself (AD-061).
    """
    scope = role_scope_from_dict(role_raw)
    if scope.tier == GOD_MODE_TIER:
        raise ValueError(
            f"refusing to derive a scoped vault for tier '{GOD_MODE_TIER}' — "
            "god-mode IS the canonical vault; deriving it from itself would "
            "only produce a weaker duplicate (AD-061)."
        )

    now = (now_fn or _default_now_fn)()
    timestamp = now[:19].replace(":", "_").replace("T", "_")

    if passphrase is None:
        if _HAS_PASSPHRASE:
            passphrase, passphrase_source = generate_master_password_suggestion()
        else:
            import secrets as _secrets
            passphrase = _secrets.token_urlsafe(24)
            passphrase_source = "secrets.token_urlsafe (passphrase lib unavailable)"
    elif passphrase_source is None:
        passphrase_source = "operator-supplied"

    in_scope = select_scoped_entries(scope, secret_entries)
    db_path = f"{derived_db_dir.rstrip('/')}/{scope.role}.kdbx"

    return DerivedVaultPlan(
        role=scope.role,
        tier=scope.tier,
        description=scope.description,
        db_path=db_path,
        parent_db_path=parent_db_path,
        generated_at=now,
        passphrase=passphrase,
        passphrase_source=passphrase_source,
        parent_record_path=vault_record_path(scope.role, timestamp),
        holders=scope.holders,
        entries=in_scope,
        excluded_count=len(secret_entries) - len(in_scope),
        total_registry_count=len(secret_entries),
    )


# ---------------------------------------------------------------------------
# keepassxc-cli command rendering — mirrors render_init_commands()'s shape
# ---------------------------------------------------------------------------

def render_derive_vault_commands(plan: DerivedVaultPlan) -> list[str]:
    """
    Return ordered keepassxc-cli command strings an operator runs to build
    the derived vault and record its passphrase in the parent vault.

    Mirrors forge_keepass_init.py::render_init_commands()'s "describe what to
    run, don't run it" shape exactly: passwords are piped via stdin (never
    passed as CLI args, to avoid `ps aux`/shell-history exposure), and the
    operator supplies both DERIVED_VAULT_PASSWORD and KEEPASS_MASTER_PASSWORD
    (the parent/canonical vault's password) via environment variables.
    """
    derived_q = shlex.quote(plan.db_path)
    parent_q = shlex.quote(plan.parent_db_path)

    cmds = [
        f"# Phase 1.K — derive scoped vault for role '{plan.role}' (tier: {plan.tier})",
        f"# Source: {plan.total_registry_count} canonical entries → "
        f"{len(plan.entries)} in-scope ({plan.excluded_count} excluded by scope/excludes)",
        "apt-get install -y keepassxc 2>/dev/null || true",
        f"install -d -m 700 {shlex.quote('/'.join(plan.db_path.split('/')[:-1]))}",
        f"printf '%s\\n' \"$DERIVED_VAULT_PASSWORD\" | "
        f"keepassxc-cli db-create --set-password - {derived_q}",
        "",
    ]

    for entry in plan.entries:
        path = entry.get("keepass_path") or entry.get("id") or "unknown"
        group = "/".join(path.split("/")[:-1])
        description = entry.get("description") or entry.get("id") or ""
        cmds.append(
            f"printf '%s\\n' \"$DERIVED_VAULT_PASSWORD\" | "
            f"keepassxc-cli mkdir --password - {derived_q} '/{group}' 2>/dev/null || true"
        )
        cmds.append(
            f"# Copy '{path}' from canonical vault into the derived vault by hand —"
            f" broodforge does not read or copy live secret values."
        )
        cmds.append(
            f"printf '%s\\n' \"$DERIVED_VAULT_PASSWORD\" | "
            f"keepassxc-cli add --password - {derived_q} "
            f"--no-password '/{path}' --notes '{description} [copy value from canonical vault]'"
        )

    cmds += [
        "",
        f"echo '[derive-scoped-vault] {plan.role} vault created at {derived_q} "
        f"with {len(plan.entries)} entries.'",
        "",
        "# Vault-of-vaults recordkeeping — record this vault's passphrase in the",
        "# parent (canonical) vault so a higher-tier holder can always recover it.",
        f"printf '%s\\n' \"$KEEPASS_MASTER_PASSWORD\" | "
        f"keepassxc-cli mkdir --password - {parent_q} "
        f"'/{'/'.join(plan.parent_record_path.split('/')[:-1])}' 2>/dev/null || true",
        f"printf '%s\\n' \"$KEEPASS_MASTER_PASSWORD\" | "
        f"keepassxc-cli add --password - {parent_q} "
        f"'/{plan.parent_record_path}' "
        f"--notes 'Derived-vault passphrase for role {plan.role} ({plan.tier}), "
        f"generated {plan.generated_at[:19]}' "
        f"<<< \"$DERIVED_VAULT_PASSWORD\"",
        f"echo '[derive-scoped-vault] Recorded {plan.role} passphrase at "
        f"/{plan.parent_record_path} in the parent vault.'",
    ]
    return cmds


def describe_vault_plan(plan: DerivedVaultPlan) -> str:
    """Human-readable description of a derived-vault plan — mirrors describe_init_plan()."""
    lines = [
        f"Derived Vault Plan — role: {plan.role} (tier: {plan.tier})",
        "=" * (28 + len(plan.role) + len(plan.tier)),
        f"Description:        {plan.description or '(none declared)'}",
        f"Derived vault path: {plan.db_path}",
        f"Parent vault path:  {plan.parent_db_path}",
        f"Generated:          {plan.generated_at}",
        f"Holders:            {', '.join(plan.holders) or '(none declared)'}",
        "",
        f"Scope match: {len(plan.entries)} of {plan.total_registry_count} canonical "
        f"entries in scope ({plan.excluded_count} excluded).",
        "",
        "Generated passphrase (SHOWN ONCE — store it ONLY in the parent vault, at):",
        f"  {plan.parent_record_path}",
        f"  {plan.passphrase}",
        f"  (source: {plan.passphrase_source})",
        "",
        "  This is the only time broodforge displays this passphrase. It is never",
        "  written to disk by this tool. Record it in the parent/canonical vault",
        "  at the path above (vault-of-vaults recordkeeping, AD-061) — that record",
        "  is how a god-mode operator recovers this scoped vault's passphrase later.",
        "",
        f"In-scope entries ({len(plan.entries)}):",
    ]
    for e in plan.entries:
        lines.append(f"  {e.get('keepass_path') or e.get('id')}")
        lines.append(f"    → {e.get('description') or ''}")

    n_secrets = len(plan.entries)
    lines += [
        "",
        f"Operator steps required ({n_secrets} entries to populate manually):",
        "  1. Run: render_derive_vault_commands() to get the keepassxc-cli",
        "     command sequence (or use derive-scoped-vault.py --run).",
        f"  2. Execute each command — creates {plan.db_path}",
        f"     with {n_secrets} entries copied from the canonical vault.",
        "  3. Record the passphrase above in the parent vault at:",
        f"     {plan.parent_record_path}",
        f"  4. Distribute {plan.db_path} to the holder(s): "
        + (", ".join(plan.holders) if plan.holders else "(none declared)"),
        "",
        "Authorization model (AD-061 — true by construction, nothing to enforce):",
        "  Only someone who can already read secret-registry.yaml AND open the",
        "  canonical vault in full could have produced this plan — the same trust",
        "  boundary as running forge-planner.py/spawn-planner.py. There is no",
        "  separate permission check because there is nothing left to check: you",
        "  cannot derive a scope you could not already see in its entirety.",
        "",
        "Revocation = rotate + reissue (AD-061 — an honest non-guarantee):",
        "  This derived vault has no live link back to the canonical vault and",
        "  cannot be remotely revoked. If it is lost, stale, or compromised,",
        "  rotate every secret it contains (per each entry's rotation_schedule)",
        "  and reissue a fresh derivative with a fresh passphrase. A derived",
        "  vault cannot leak ciphertext it never received — a static-by-design",
        "  property of the offline-first model, arguably stronger than an",
        "  access-list edit on a database its holder already possesses whole.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# User-provisioning templates
# ---------------------------------------------------------------------------

_TIER_GROUPS = {
    "service-operator": ["docker"],
    "node-sysadmin":    ["sudo", "docker"],
    "god-mode":         ["sudo"],
}

_TIER_SUDO = {
    "service-operator": None,
    "node-sysadmin":    "ALL=(ALL) NOPASSWD:ALL",
    "god-mode":         "ALL=(ALL) NOPASSWD:ALL",
}


def generate_vm_account_template(role_raw: dict, plan: Optional[DerivedVaultPlan] = None) -> dict:
    """
    Build an additive Cloud-Init account block for a scoped role — the same
    shape spawn_iac_generator.py::generate_cloudinit_user_data() already emits
    for its one `initial_user` account, generalised to a role-appropriate,
    non-root, additional account whose SSH-key lookup is documented as coming
    from this role's scoped vault (not the canonical one).

    Returns a dict (account name, groups, sudo, shell, ssh-key-reference
    comment, and the rendered YAML block) rather than a full cloud-config —
    callers splice `yaml_block` into the existing `users:` list alongside the
    primary initial_user account spawn_iac_generator already produces.
    """
    scope = role_scope_from_dict(role_raw)
    account_name = f"{scope.role}"
    groups = _TIER_GROUPS.get(scope.tier, ["docker"])
    sudo = _TIER_SUDO.get(scope.tier)
    vault_path = plan.db_path if plan else f"/etc/broodforge/vaults/{scope.role}.kdbx"
    ssh_ref = f"{vault_path}::ssh-keys/{scope.role}"

    groups_yaml = ", ".join(groups)
    sudo_lines = f"    sudo: {sudo}\n" if sudo else "    sudo: false\n"
    yaml_block = (
        f"  - name: '{account_name}'\n"
        f"    groups: [{groups_yaml}]\n"
        f"    shell: /bin/bash\n"
        f"{sudo_lines}"
        f"    lock_passwd: false\n"
        f"    # SSH key injected from scoped vault ref: {ssh_ref}\n"
        f"    # Tier: {scope.tier} — provisioned with access to its own scoped vault only\n"
    )

    return {
        "name": account_name,
        "tier": scope.tier,
        "groups": groups,
        "sudo": sudo,
        "ssh_key_reference": ssh_ref,
        "scoped_vault_path": vault_path,
        "yaml_block": yaml_block,
    }


_TIER_PVE_ROLE = {
    "service-operator": "PVEVMUser",
    "node-sysadmin":    "PVEAdmin",
    "god-mode":         "Administrator",
}


def generate_proxmox_account_commands(
    role_raw: dict,
    plan: Optional[DerivedVaultPlan] = None,
    realm: str = "pve",
    acl_path: str = "/",
) -> list[str]:
    """
    Return a templated `pveum user add`/`pveum aclmod` command sequence for a
    Proxmox-level account corresponding to this role — generated as data for
    an operator to run, exactly like render_init_commands()/
    render_derive_vault_commands(). broodforge has no live-Proxmox-API-mutation
    code path (confirmed: no module shells out to pveum or the Proxmox API
    directly) — this module does not add one; it documents the commands.
    """
    scope = role_scope_from_dict(role_raw)
    user_id = f"{scope.role}@{realm}"
    pve_role = _TIER_PVE_ROLE.get(scope.tier, "PVEVMUser")
    vault_path = plan.db_path if plan else f"/etc/broodforge/vaults/{scope.role}.kdbx"

    cmds = [
        f"# Phase 1.K — Proxmox account template for role '{scope.role}' (tier: {scope.tier})",
        "# Operator-run commands — broodforge does not call the Proxmox API directly.",
        f"pveum user add {shlex.quote(user_id)} --comment {shlex.quote(scope.description or scope.role)}",
        f"pveum aclmod {shlex.quote(acl_path)} -user {shlex.quote(user_id)} -role {shlex.quote(pve_role)}",
        f"# Generate this account's API token from its scoped vault at: {vault_path}",
        f"pveum user token add {shlex.quote(user_id)} {shlex.quote(scope.role + '-token')} --privsep 1",
        f"echo '[provision-proxmox-user] {user_id} created with role {pve_role} on {acl_path}.'",
        f"echo '[provision-proxmox-user] Store the generated token in the scoped vault: {vault_path}'",
    ]
    return cmds


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def plan_to_dict(plan: DerivedVaultPlan, include_passphrase: bool = True) -> dict:
    """
    Serialise a DerivedVaultPlan to a plain dict.

    include_passphrase=False omits the generated passphrase — for any context
    where the plan dict might be persisted to disk or logged (the passphrase
    itself must remain shown-once/never-written, mirroring _image_builder.py's
    install-passphrase handling). The CLI always passes False when writing the
    JSON artifact, and True only for the in-memory print-once summary.
    """
    d = {
        "schema_version":      SCHEMA_VERSION,
        "role":                plan.role,
        "tier":                plan.tier,
        "description":         plan.description,
        "db_path":             plan.db_path,
        "parent_db_path":      plan.parent_db_path,
        "generated_at":        plan.generated_at,
        "passphrase_source":   plan.passphrase_source,
        "parent_record_path":  plan.parent_record_path,
        "holders":             plan.holders,
        "entry_count":         len(plan.entries),
        "excluded_count":      plan.excluded_count,
        "total_registry_count": plan.total_registry_count,
        "entries": [
            {
                "id": e.get("id"),
                "keepass_path": e.get("keepass_path"),
                "description": e.get("description"),
                "secret_type": e.get("secret_type"),
            }
            for e in plan.entries
        ],
    }
    if include_passphrase:
        d["passphrase"] = plan.passphrase
        d["passphrase_shown_once"] = True
        d["passphrase_note"] = (
            "Shown once at generation time, never written to disk by broodforge. "
            "Store it ONLY at parent_record_path inside the parent/canonical vault "
            "(vault-of-vaults recordkeeping, AD-061)."
        )
    return d
