#!/usr/bin/env python3
"""
_recovery_accounts.py — Constrained, forced-command recovery accounts (Phase 1.J, AD-060).

AD-060 is a firm architectural SHALL-NOT: no autonomous broodforge code path
may read a permanent/full hypervisor root credential from any store and wield
it against a live hypervisor — "root has no boundary by definition." This
module builds the one piece of the recovery surface AD-060 names as safe to
query autonomously *because its blast radius is bounded by construction*: a
dedicated, narrowly-scoped account per hypervisor, gated by `ForceCommand`/
`command=` in `authorized_keys`, restricted to a FIXED menu of read-only
diagnostics and a small set of safe, validated operations (VM start/stop) —
never an arbitrary shell.

This module does not connect to, provision, or otherwise act on a live
hypervisor. It GENERATES STRINGS — an `authorized_keys` restricted-command
line and a fixed-menu shell-script — that the operator (or the forge package's
phase-03 step, as a one-time provisioning action under the same trust boundary
as every other phase-03 step) installs onto the target host. This mirrors how
`_image_builder.py::generate_first_boot_install_sh()` builds a shell-script
*string* for the package to carry, never to execute locally — see that
docstring for the convention this follows.

Why the menu script is structurally safe (the load-bearing property):
  - It is POSIX `sh`, runs under `set -eu`, and is invoked only via
    `command="<path>"` in `authorized_keys` — `$SSH_ORIGINAL_COMMAND` is read
    but NEVER passed to `eval`/`sh -c`/backticks/`$()`; it is matched against
    a fixed, enumerated menu of literal choices only.
  - The only operator-influenced value that reaches an executed command is a
    VMID, and it is validated against `^[0-9]{1,6}$` (numeric-only, bounded
    length) BEFORE being interpolated — no shell metacharacter can survive
    that check, so no path from menu input to arbitrary-shell execution exists.
  - The menu has no "shell" or "exec arbitrary command" entry, by design —
    that is the entire safety property AD-060 asks this account to have.

Stdlib only.
"""

from datetime import datetime, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# Account identity defaults
# ---------------------------------------------------------------------------

DEFAULT_ACCOUNT_NAME = "broodforge-recovery"
DEFAULT_MENU_SCRIPT_PATH = "/usr/local/sbin/broodforge-recovery-menu.sh"
VMID_PATTERN = r"^[0-9]{1,6}$"


# ---------------------------------------------------------------------------
# (a)(i) — authorized_keys restricted-command line
# ---------------------------------------------------------------------------

# Conservative/standard OpenSSH `authorized_keys` restriction options for a
# forced-command account: disable every interactive/tunnelling capability that
# could be combined with the forced command to widen the blast radius. This is
# the standard "jump-host diagnostic account" restriction set documented in
# sshd(8)/AUTHORIZED_KEYS FILE FORMAT — `no-pty` in particular is what removes
# any path back to an interactive shell even if the forced command misbehaves.
AUTHORIZED_KEYS_RESTRICTIONS = (
    "no-port-forwarding",
    "no-X11-forwarding",
    "no-agent-forwarding",
    "no-pty",
)


def build_authorized_keys_line(
    public_key: str,
    menu_script_path: str = DEFAULT_MENU_SCRIPT_PATH,
    comment: Optional[str] = None,
) -> str:
    """
    Build a single restricted `authorized_keys` line that forces every session
    on this key through the fixed-menu script and disables every other
    capability (port/X11/agent forwarding, pty allocation).

    `public_key` must be a single `<algo> <base64> [comment]` OpenSSH public
    key line (or just `<algo> <base64>` — any embedded comment is preserved
    verbatim at the end of the generated line, after our own `comment`).
    `menu_script_path` MUST be an absolute path with no shell metacharacters
    (validated here) — it is interpolated into a double-quoted `command=`
    value, and a malformed path could otherwise break out of that quoting.
    """
    key = (public_key or "").strip()
    if not key:
        raise ValueError("public_key must be a non-empty OpenSSH public key line")
    if any(c in menu_script_path for c in ('"', "\\", "$", "`", "\n", "\r")):
        raise ValueError(f"menu_script_path contains unsafe characters: {menu_script_path!r}")
    if not menu_script_path.startswith("/"):
        raise ValueError(f"menu_script_path must be an absolute path: {menu_script_path!r}")

    options = [f'command="{menu_script_path}"'] + list(AUTHORIZED_KEYS_RESTRICTIONS)
    line = ",".join(options) + " " + key
    if comment:
        line += f" {comment}"
    return line


# ---------------------------------------------------------------------------
# (a)(ii) — fixed-menu shell-script generator
#
# Generated as a STRING the package carries (mirrors
# _image_builder.generate_first_boot_install_sh) — broodforge never runs this.
# ---------------------------------------------------------------------------

def generate_recovery_menu_sh(
    node_hostname: str,
    account_name: str = DEFAULT_ACCOUNT_NAME,
    vmid_pattern: str = VMID_PATTERN,
) -> str:
    """
    Generate the fixed-menu diagnostic script text for a recovery account.

    The menu is intentionally small and entirely enumerated — every branch is
    a literal, fixed command (or a command with a single VMID argument that is
    regex-validated against `vmid_pattern` before use). There is NO branch
    that evaluates, sources, or execs `$SSH_ORIGINAL_COMMAND` (or any portion
    of it) as shell — that is what makes an arbitrary-shell escape structurally
    impossible, not merely policy.

    Menu (read-only diagnostics + bounded VM start/stop — per AD-060's named
    "fixed menu of read-only diagnostics and safe operations"):
      1) pvesh get /nodes/<node>/status         — node health/resource status
      2) journalctl -u pve-cluster -n 100       — recent cluster-service log
      3) qm list                                — list VMs and their states
      4) qm start <vmid>                        — start a VM (numeric vmid only)
      5) qm stop <vmid>                         — stop a VM (numeric vmid only)
      6) help                                   — print this menu
    """
    node = (node_hostname or "unknown-node").strip() or "unknown-node"
    acct = (account_name or DEFAULT_ACCOUNT_NAME).strip() or DEFAULT_ACCOUNT_NAME
    return f"""\
#!/bin/sh
# broodforge-recovery-menu.sh — FIXED, READ-ONLY-PLUS-BOUNDED diagnostic menu
# Account: {acct}   Node: {node}
#
# GENERATED by broodforge (_recovery_accounts.py, Phase 1.J, AD-060). This
# script is the ENTIRE safety property of the constrained recovery account —
# it is invoked exclusively via `command="..."` in authorized_keys (see that
# entry's `no-pty,no-port-forwarding,no-X11-forwarding,no-agent-forwarding`
# restrictions), so this is the only code that ever runs in this account's
# session, no matter what the connecting client sends.
#
# STRUCTURAL SAFETY INVARIANT — do not weaken this when editing by hand:
#   $SSH_ORIGINAL_COMMAND is matched against a FIXED set of literal menu
#   choices ONLY. It is NEVER passed to eval/sh -c/`` / $() / source. The only
#   operator-influenced value that reaches an executed command is a VMID, and
#   it is checked against {vmid_pattern!r} (numeric-only, bounded length)
#   BEFORE use — no shell metacharacter can survive that check. There is no
#   "run arbitrary command" branch, by design: that is what AD-060 requires.
set -eu

NODE="{node}"
VMID_RE='{vmid_pattern}'

print_menu() {{
    cat <<'MENU'
broodforge constrained recovery account — fixed diagnostic menu
================================================================
  status              pvesh get /nodes/<node>/status
  logs                journalctl -u pve-cluster -n 100
  vmlist              qm list
  vmstart <vmid>      qm start <vmid>   (numeric vmid only)
  vmstop  <vmid>      qm stop  <vmid>   (numeric vmid only)
  help                show this menu

This account cannot open a shell, forward ports/agents/X11, or run any
command outside this fixed menu — see AD-060 (ARCHITECTURE.md).
MENU
}}

is_valid_vmid() {{
    printf '%s' "$1" | grep -Eq "$VMID_RE"
}}

cmd="${{SSH_ORIGINAL_COMMAND:-help}}"

# Split into a verb and (optional) single argument WITHOUT invoking a shell
# over the input — `set --` performs only whitespace word-splitting, no
# expansion, no command substitution, no globbing of metacharacters into exec.
# shellcheck disable=SC2086
set -- $cmd
verb="${{1:-help}}"
arg="${{2:-}}"

case "$verb" in
    status)
        exec pvesh get "/nodes/$NODE/status"
        ;;
    logs)
        exec journalctl -u pve-cluster -n 100
        ;;
    vmlist)
        exec qm list
        ;;
    vmstart)
        if [ -z "$arg" ] || ! is_valid_vmid "$arg"; then
            echo "vmstart requires a numeric vmid (got: '$arg')" >&2
            exit 2
        fi
        exec qm start "$arg"
        ;;
    vmstop)
        if [ -z "$arg" ] || ! is_valid_vmid "$arg"; then
            echo "vmstop requires a numeric vmid (got: '$arg')" >&2
            exit 2
        fi
        exec qm stop "$arg"
        ;;
    help|"")
        print_menu
        ;;
    *)
        echo "Unrecognized command: '$verb'" >&2
        print_menu
        exit 1
        ;;
esac
"""


# ---------------------------------------------------------------------------
# (b) — break-glass annotation display helper (NEVER reads the secret value)
#
# This function exists ONLY to surface, in generated documentation/menus, the
# *path* an operator should manually look up break-glass root at — it never
# reads, requests, or carries a secret value. See secret-registry.yaml's
# `access_policy: break-glass-human-only` annotation (Phase 1.J, AD-060(b)).
# ---------------------------------------------------------------------------

def describe_break_glass_pointer(secret_registry_entries: list) -> list[dict]:
    """
    Build a list of {id, keepass_path, description} pointers — for display in
    a recovery runbook ONLY — for any secret-registry entry annotated
    `access_policy: break-glass-human-only`.

    This function reads `keepass_path` strings (locations) for documentation
    display. It NEVER reads, requests, decrypts, or returns a secret VALUE —
    there is no code path here (or anywhere in this module) that opens a
    KeePass database or connects to a hypervisor with a credential. The
    operator is expected to open KeePass themselves and unlock it under the
    existing AD-042 human-unlock gate.
    """
    pointers = []
    for entry in (secret_registry_entries or []):
        if (entry or {}).get("access_policy") == "break-glass-human-only":
            pointers.append({
                "id": entry.get("id"),
                "keepass_path": entry.get("keepass_path"),
                "description": entry.get("description"),
            })
    return pointers


# ---------------------------------------------------------------------------
# Provisioning plan — structured artifact (manifest-shaped, AD-051 candidate)
# ---------------------------------------------------------------------------

def build_recovery_account_plan(
    node_hostname: str,
    public_key: str,
    cell_id: Optional[str] = None,
    account_name: str = DEFAULT_ACCOUNT_NAME,
    menu_script_path: str = DEFAULT_MENU_SCRIPT_PATH,
    secret_registry_entries: Optional[list] = None,
    now_fn=None,
) -> dict:
    """
    Build a "recovery account provisioning plan" — a manifest-shaped dict
    describing what phase-03 (or an operator) should install on the target
    hypervisor: the account name, the generated `authorized_keys` line, the
    fixed-menu script text, and (display-only) break-glass pointers.

    Nothing here is executed by broodforge — see module docstring. `now_fn`
    follows the established `(now_fn or (lambda: datetime.now(timezone.utc)
    .isoformat()))()` convention.
    """
    gen_at = (now_fn or (lambda: datetime.now(timezone.utc).isoformat()))()
    authorized_keys_line = build_authorized_keys_line(
        public_key, menu_script_path=menu_script_path,
        comment=f"broodforge-recovery@{node_hostname or 'unknown-node'}",
    )
    menu_script_text = generate_recovery_menu_sh(node_hostname, account_name=account_name)
    break_glass = describe_break_glass_pointer(secret_registry_entries or [])

    return {
        "schema_version": "1.0",
        "artifact_type": "recovery-account-provisioning-plan",
        "cell_id": cell_id or "unknown-cell",
        "node_hostname": node_hostname or "unknown-node",
        "generated_at": gen_at,
        "account": {
            "name": account_name,
            "menu_script_path": menu_script_path,
            "shell_restriction": "/usr/sbin/nologin",
            "authorized_keys_line": authorized_keys_line,
            "authorized_keys_restrictions": list(AUTHORIZED_KEYS_RESTRICTIONS),
        },
        "menu_script": {
            "path": menu_script_path,
            "contents": menu_script_text,
            "vmid_validation_pattern": VMID_PATTERN,
            "menu_commands": ["status", "logs", "vmlist", "vmstart <vmid>", "vmstop <vmid>"],
        },
        "break_glass_pointers": break_glass,
        "constraint": {
            "ad": "AD-060",
            "statement": (
                "This account is the one piece of the recovery surface AD-060 names "
                "as safe to query autonomously, BECAUSE its blast radius is bounded "
                "by construction (fixed menu, no-pty, no forwarding, regex-validated "
                "vmid). It can never become a root-equivalent shell. broodforge does "
                "not, and must never, read a permanent hypervisor root credential and "
                "act on a live hypervisor — see ARCHITECTURE.md AD-060."
            ),
        },
        "notes": [
            "broodforge does not connect to, provision, or act on a live hypervisor "
            "via this plan — it generates strings for an operator/phase-03 step to "
            "install, mirroring _image_builder.generate_first_boot_install_sh.",
            "The menu script never evaluates $SSH_ORIGINAL_COMMAND as shell; VMIDs "
            "are validated against ^[0-9]{1,6}$ before reaching any executed command.",
            "Break-glass root pointers (if any) are KeePass PATHS for operator "
            "lookup only — never secret values; see secret-registry.yaml access_policy.",
        ],
    }


def plan_to_dict(plan: dict) -> dict:
    """Identity passthrough — plan is already a plain dict (AD-051 convention parity)."""
    return dict(plan)


# AD-051 HTML twin: see html_package_manifest.build_recovery_account_plan_html —
# AD-051 twins live there (mirrors build_scoped_vault_plan_html / Phase 1.K),
# not alongside the data-builder module.
