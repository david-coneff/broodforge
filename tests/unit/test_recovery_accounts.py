"""
test_recovery_accounts.py — Tests for Phase 1.J (AD-060):
  _recovery_accounts.py — constrained, forced-command recovery account generator

Covers: authorized_keys restricted-command line correctness and restriction-
flag presence, fixed-menu shell-script command-injection-safety (structural
assertions that no path from menu input to arbitrary-shell execution exists,
and that vmid validation rejects shell metacharacters), the provisioning-plan
shape, the AD-051 HTML twin, the break-glass pointer-only helper (never reads
secret values), and a structural "constraint honored" guard test asserting no
code in this module reads a hypervisor root-credential VALUE.
"""

import re
from pathlib import Path

import pytest

_PB_DIR = Path(__file__).parent.parent.parent / "proxmox-bootstrap"

import _recovery_accounts as ra
import html_package_manifest as _hpm

_TEST_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAItestkeydata operator@workstation"


# ---------------------------------------------------------------------------
# authorized_keys restricted-command line
# ---------------------------------------------------------------------------

class TestAuthorizedKeysLine:
    def test_returns_string(self):
        line = ra.build_authorized_keys_line(_TEST_KEY)
        assert isinstance(line, str)

    def test_contains_command_clause(self):
        line = ra.build_authorized_keys_line(_TEST_KEY)
        assert 'command="' in line
        assert ra.DEFAULT_MENU_SCRIPT_PATH in line

    def test_contains_all_standard_restrictions(self):
        line = ra.build_authorized_keys_line(_TEST_KEY)
        for flag in ra.AUTHORIZED_KEYS_RESTRICTIONS:
            assert flag in line, f"missing restriction flag: {flag}"

    def test_includes_no_pty(self):
        # no-pty is the load-bearing flag — removes any path back to an
        # interactive shell even if the forced command misbehaves
        line = ra.build_authorized_keys_line(_TEST_KEY)
        assert "no-pty" in line

    def test_contains_public_key(self):
        line = ra.build_authorized_keys_line(_TEST_KEY)
        assert "AAAAC3NzaC1lZDI1NTE5" in line

    def test_appends_comment(self):
        line = ra.build_authorized_keys_line(_TEST_KEY, comment="my-comment")
        assert line.endswith("my-comment")

    def test_custom_menu_script_path(self):
        line = ra.build_authorized_keys_line(_TEST_KEY, menu_script_path="/opt/broodforge/menu.sh")
        assert 'command="/opt/broodforge/menu.sh"' in line

    def test_rejects_empty_key(self):
        with pytest.raises(ValueError):
            ra.build_authorized_keys_line("")

    def test_rejects_relative_menu_path(self):
        with pytest.raises(ValueError):
            ra.build_authorized_keys_line(_TEST_KEY, menu_script_path="relative/path.sh")

    def test_rejects_menu_path_with_shell_metacharacters(self):
        for bad in ['/tmp/"; rm -rf / #', "/tmp/$(whoami)", "/tmp/`id`", "/tmp/a\\b"]:
            with pytest.raises(ValueError):
                ra.build_authorized_keys_line(_TEST_KEY, menu_script_path=bad)

    def test_options_precede_key(self):
        line = ra.build_authorized_keys_line(_TEST_KEY)
        cmd_idx = line.index("command=")
        key_idx = line.index("ssh-ed25519")
        assert cmd_idx < key_idx


# ---------------------------------------------------------------------------
# Fixed-menu shell-script generation — command-injection safety
# ---------------------------------------------------------------------------

class TestRecoveryMenuScript:
    def test_returns_string(self):
        text = ra.generate_recovery_menu_sh("pve01")
        assert isinstance(text, str)
        assert text.startswith("#!/bin/sh")

    def test_contains_node_hostname(self):
        text = ra.generate_recovery_menu_sh("pve02")
        assert 'NODE="pve02"' in text

    def test_contains_fixed_menu_commands(self):
        text = ra.generate_recovery_menu_sh("pve01")
        for expected in ("status)", "logs)", "vmlist)", "vmstart)", "vmstop)", "help|"):
            assert expected in text

    def test_uses_set_eu(self):
        text = ra.generate_recovery_menu_sh("pve01")
        assert "set -eu" in text

    def test_never_evals_original_command_as_shell(self):
        """
        STRUCTURAL SAFETY: the menu script must never pass
        $SSH_ORIGINAL_COMMAND (or any portion derived from it) to a shell
        evaluator. This is the entire guarantee against arbitrary-shell
        escape — assert the dangerous constructs are categorically absent.
        """
        text = ra.generate_recovery_menu_sh("pve01")
        dangerous = ["eval $", 'eval "$', "eval $cmd", "sh -c $cmd", 'sh -c "$cmd"',
                     "sh -c \"$SSH_ORIGINAL_COMMAND\"", "eval $SSH_ORIGINAL_COMMAND",
                     "bash -c $cmd", "source $cmd", ". $cmd"]
        for d in dangerous:
            assert d not in text, f"found dangerous construct: {d!r}"

    def test_only_word_splits_original_command_no_expansion(self):
        text = ra.generate_recovery_menu_sh("pve01")
        # `set -- $cmd` performs only whitespace word-splitting (no glob/eval)
        assert "set -- $cmd" in text

    def test_validates_vmid_before_use(self):
        text = ra.generate_recovery_menu_sh("pve01")
        assert "is_valid_vmid" in text
        assert "VMID_RE=" in text
        # both vmstart and vmstop must validate before exec
        assert text.count("is_valid_vmid \"$arg\"") == 2

    def test_vmid_pattern_rejects_shell_metacharacters(self):
        pattern = ra.VMID_PATTERN
        for bad in ["1; rm -rf /", "1 && id", "$(whoami)", "`id`", "1|cat /etc/passwd",
                    "../../etc/passwd", "1\nid", "1 2", "", "abc", "1.2"]:
            assert not re.match(pattern, bad), f"pattern incorrectly matched: {bad!r}"

    def test_vmid_pattern_accepts_plain_numbers(self):
        pattern = ra.VMID_PATTERN
        for good in ["1", "100", "999999"]:
            assert re.match(pattern, good)

    def test_vmid_pattern_bounded_length(self):
        # 7-digit vmid should be rejected (bounded length prevents pathological input)
        assert not re.match(ra.VMID_PATTERN, "1234567")

    def test_no_arbitrary_shell_branch_in_menu(self):
        text = ra.generate_recovery_menu_sh("pve01")
        for forbidden in ["exec sh", "exec bash", "exec /bin/sh", "exec $SHELL",
                          "exec \"$cmd\"", "exec $cmd"]:
            assert forbidden not in text

    def test_only_fixed_commands_reach_exec(self):
        text = ra.generate_recovery_menu_sh("pve01")
        exec_lines = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("exec ")]
        assert exec_lines, "expected at least one exec line"
        allowed_prefixes = (
            'exec pvesh get "/nodes/$NODE/status"',
            "exec journalctl -u pve-cluster -n 100",
            "exec qm list",
            'exec qm start "$arg"',
            'exec qm stop "$arg"',
        )
        for ln in exec_lines:
            assert ln in allowed_prefixes, f"unexpected exec target: {ln!r}"


# ---------------------------------------------------------------------------
# Break-glass pointer helper — never touches secret values
# ---------------------------------------------------------------------------

class TestBreakGlassPointer:
    def _entries(self):
        return [
            {"id": "pve01-root-password", "keepass_path": "Infrastructure/proxmox/pve01-root",
             "description": "Proxmox host root password", "access_policy": "break-glass-human-only"},
            {"id": "pve01-api-token", "keepass_path": "Infrastructure/proxmox/pve01-tofu-token",
             "description": "Proxmox API token"},
        ]

    def test_returns_only_annotated_entries(self):
        pointers = ra.describe_break_glass_pointer(self._entries())
        assert len(pointers) == 1
        assert pointers[0]["id"] == "pve01-root-password"

    def test_pointer_carries_no_value_field(self):
        pointers = ra.describe_break_glass_pointer(self._entries())
        for p in pointers:
            assert "value" not in p
            assert "password" not in p
            assert "secret" not in p
            assert set(p.keys()) == {"id", "keepass_path", "description"}

    def test_empty_list_when_no_annotations(self):
        entries = [{"id": "x", "keepass_path": "y", "description": "z"}]
        assert ra.describe_break_glass_pointer(entries) == []

    def test_handles_empty_input(self):
        assert ra.describe_break_glass_pointer([]) == []
        assert ra.describe_break_glass_pointer(None) == []


# ---------------------------------------------------------------------------
# Provisioning plan
# ---------------------------------------------------------------------------

class TestRecoveryAccountPlan:
    def _plan(self, **kw):
        return ra.build_recovery_account_plan(
            "pve01", _TEST_KEY, cell_id="proxmox-cell-a",
            now_fn=lambda: "2026-06-08T00:00:00+00:00", **kw,
        )

    def test_returns_dict_with_expected_keys(self):
        plan = self._plan()
        for key in ("schema_version", "artifact_type", "cell_id", "node_hostname",
                    "generated_at", "account", "menu_script", "break_glass_pointers",
                    "constraint", "notes"):
            assert key in plan

    def test_artifact_type(self):
        assert self._plan()["artifact_type"] == "recovery-account-provisioning-plan"

    def test_uses_injected_clock(self):
        assert self._plan()["generated_at"] == "2026-06-08T00:00:00+00:00"

    def test_account_section_shape(self):
        account = self._plan()["account"]
        assert account["name"] == ra.DEFAULT_ACCOUNT_NAME
        assert account["shell_restriction"] == "/usr/sbin/nologin"
        assert "command=" in account["authorized_keys_line"]

    def test_menu_script_section_shape(self):
        menu = self._plan()["menu_script"]
        assert menu["path"] == ra.DEFAULT_MENU_SCRIPT_PATH
        assert menu["vmid_validation_pattern"] == ra.VMID_PATTERN
        assert "vmstart <vmid>" in menu["menu_commands"]

    def test_constraint_references_ad060(self):
        constraint = self._plan()["constraint"]
        assert constraint["ad"] == "AD-060"
        assert "root" in constraint["statement"].lower()

    def test_break_glass_pointers_passthrough(self):
        entries = [{"id": "pve01-root-password", "keepass_path": "Infrastructure/proxmox/pve01-root",
                    "description": "Proxmox host root password", "access_policy": "break-glass-human-only"}]
        plan = ra.build_recovery_account_plan(
            "pve01", _TEST_KEY, secret_registry_entries=entries,
            now_fn=lambda: "2026-06-08T00:00:00+00:00",
        )
        assert len(plan["break_glass_pointers"]) == 1
        assert plan["break_glass_pointers"][0]["id"] == "pve01-root-password"

    def test_plan_to_dict_is_passthrough(self):
        plan = self._plan()
        assert ra.plan_to_dict(plan) == plan
        assert ra.plan_to_dict(plan) is not plan


# ---------------------------------------------------------------------------
# AD-051 HTML twin
# ---------------------------------------------------------------------------

class TestRecoveryAccountPlanHtml:
    def _plan(self):
        return ra.build_recovery_account_plan(
            "pve01", _TEST_KEY, cell_id="proxmox-cell-a",
            now_fn=lambda: "2026-06-08T00:00:00+00:00",
        )

    def test_returns_html_string(self):
        html = _hpm.build_recovery_account_plan_html(self._plan())
        assert html.strip().lower().startswith("<!doctype html>")

    def test_contains_authorized_keys_line(self):
        plan = self._plan()
        html = _hpm.build_recovery_account_plan_html(plan)
        assert "no-pty" in html

    def test_contains_node_and_cell(self):
        html = _hpm.build_recovery_account_plan_html(self._plan())
        assert "pve01" in html
        assert "proxmox-cell-a" in html

    def test_mentions_ad060(self):
        html = _hpm.build_recovery_account_plan_html(self._plan())
        assert "AD-060" in html

    def test_break_glass_section_present_and_says_never_read(self):
        html = _hpm.build_recovery_account_plan_html(self._plan())
        assert "Break-Glass" in html
        assert "never read" in html.lower() or "never reads" in html.lower()


# ---------------------------------------------------------------------------
# Constraint-honored guard — structural assertion (mirrors Phase 1.I's
# "no invented score keys" guard): no code in this module reads a hypervisor
# root-credential VALUE from any store.
# ---------------------------------------------------------------------------

class TestConstraintHonoredNoRootCredentialReads:
    def _source(self) -> str:
        return (_PB_DIR / "_recovery_accounts.py").read_text(encoding="utf-8")

    def test_no_root_password_value_read_pattern(self):
        src = self._source()
        # No code path may fetch a *value* for a pve0X-root-password-shaped entry
        forbidden_patterns = [
            r"get_secret\(.*root.password",
            r"get_secret\(.*root.password.*\)\s*[\.\[]",
            r"keepass.*\.get\(.*root.password",
            r"\.get_password\(.*root",
            r"unlock.*\(\).*root.*password",
            r"pve0\d.*root.*password.*\)\s*\[",
        ]
        for pat in forbidden_patterns:
            assert not re.search(pat, src, re.IGNORECASE), f"forbidden pattern present: {pat}"

    def test_break_glass_function_reads_only_pointer_fields(self):
        """
        The only function that touches break-glass-annotated entries must
        read keepass_path/description/id (location/metadata) — never a
        "value"/"password"/"secret" field that would carry the credential
        itself. We isolate the function BODY (stripping its docstring, which
        legitimately discusses the boundary in prose) and assert the only
        `entry.get(...)` calls present are the pointer-field reads.
        """
        src = self._source()
        fn_match = re.search(
            r"def describe_break_glass_pointer\([^)]*\)[^:]*:\n((?:    .*\n|\n)*)", src,
        )
        assert fn_match, "describe_break_glass_pointer not found"
        body = fn_match.group(1)
        # Strip the triple-quoted docstring (prose may legitimately mention
        # "value"/"password" while explaining what the function does NOT do)
        body_code = re.sub(r'"""(?:.|\n)*?"""', "", body, count=1)

        gets = re.findall(r'entry\.get\(\s*"([a-zA-Z_]+)"', body_code)
        assert gets, "expected entry.get(...) field reads in function body"
        assert set(gets) <= {"id", "keepass_path", "description", "access_policy"}, (
            f"unexpected field reads in describe_break_glass_pointer body: {gets}"
        )
        for forbidden_field in ("value", "password", "secret"):
            assert f'entry.get("{forbidden_field}")' not in body_code

    def test_module_never_imports_credential_or_ssh_client_libs(self):
        """
        This module generates strings only — it must never IMPORT anything
        that could open a credential store or connect to a live host. We
        scan only `import`/`from ... import` lines (not prose, which
        legitimately discusses KeePass/AD-042 as the human-operated boundary).
        """
        src = self._source()
        import_lines = [ln for ln in src.splitlines()
                        if re.match(r"^\s*(import|from)\s", ln)]
        joined = "\n".join(import_lines).lower()
        for forbidden_import in ("paramiko", "fabric", "pykeepass", "keepass", "ssh"):
            assert forbidden_import not in joined, f"forbidden import found: {forbidden_import}"

    def test_module_never_invokes_subprocess_or_live_connections(self):
        src = self._source()
        for forbidden in ("subprocess", "os.system", "SSHClient", "Popen", "socket.connect"):
            assert forbidden not in src

    def test_html_twin_function_only_displays_pointer_fields(self):
        """
        build_recovery_account_plan_html (html_package_manifest.py) renders the
        break-glass section — assert it reads only id/keepass_path/description
        (display fields), never a value/password/secret field, and never opens
        a credential store.
        """
        hpm_src = (_PB_DIR / "html_package_manifest.py").read_text(encoding="utf-8")
        fn_match = re.search(
            r"def build_recovery_account_plan_html\([^)]*\)[^:]*:\n((?:    .*\n|\n)*)", hpm_src,
        )
        assert fn_match, "build_recovery_account_plan_html not found"
        body = fn_match.group(1)
        body_code = re.sub(r'"""(?:.|\n)*?"""', "", body, count=1)
        gets = re.findall(r'p\.get\(\s*"([a-zA-Z_]+)"', body_code)
        assert gets
        assert set(gets) <= {"id", "keepass_path", "description"}
        for forbidden_field in ("value", "password", "secret"):
            assert f'p.get("{forbidden_field}")' not in body_code
        # Strip out string-literal contents entirely (sentence prose like
        # "...look in KeePass. They open..." would otherwise false-positive
        # on a "keepass." substring check) — what must be absent is an
        # actual attribute-access/call shape in CODE, not in HTML text.
        body_no_strings = re.sub(r"'(?:[^'\\]|\\.)*'", "''", body_code)
        body_no_strings = re.sub(r'"(?:[^"\\]|\\.)*"', '""', body_no_strings)
        for forbidden_call in ("get_secret(", "keepass.get", "keepass.open",
                               "keepass.unlock", ".get_password(", "unlock("):
            assert forbidden_call not in body_no_strings.lower()

    def test_grep_repo_for_root_password_value_reads_in_new_module(self):
        """
        Mirror of the operator-specified guard: grep for the value-read
        shape and assert this new module contains none of it.
        """
        src = self._source()
        assert not re.search(r"pve0\d[-_]root[-_]password.*=.*get", src, re.IGNORECASE)
        assert not re.search(r"root[-_]password['\"]\s*\)\s*\.\s*(get_value|value|password|secret)",
                             src, re.IGNORECASE)
