"""
test_phoenix_session_credential.py — Tests for Phase 1.J (AD-060(d)):
  phoenix_playbook.py — phoenix-session temporary-credential extension
                        (generate_phoenix_session_credential,
                        phoenix_session_credential_section,
                        PhoenixPlaybookGenerator.build's
                        `temporary_session_credential` section)

Covers: passphrase generation shape/determinism (mirrors AD-039/AD-043),
the runbook section's rotation-requirement presence and wording, integration
into build()/build_phoenix_playbook(), and a structural "constraint honored"
guard asserting the extension never reads a permanent hypervisor root
credential value.
"""

import os
import re
import sys
from pathlib import Path

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_PB_DIR = Path(_ROOT) / "proxmox-bootstrap"
sys.path.insert(0, str(_PB_DIR))

import phoenix_playbook as pp


_MANIFEST = {
    "cell_id": "proxmox-cell-a",
    "host_identity": {"hostname": "pve01", "fqdn": "pve01.home.example.com",
                      "proxmox_version": "8.2"},
    "network_topology_declared": {"bridges": []},
    "vms": [],
    "dns_registry": [],
}


# ---------------------------------------------------------------------------
# generate_phoenix_session_credential
# ---------------------------------------------------------------------------

class TestGeneratePhoenixSessionCredential:
    def test_returns_string(self):
        assert isinstance(pp.generate_phoenix_session_credential(seed=1), str)

    def test_deterministic_with_seed(self):
        assert pp.generate_phoenix_session_credential(seed=5) == pp.generate_phoenix_session_credential(seed=5)

    def test_format_is_capital_phoenix_word_n(self):
        cred = pp.generate_phoenix_session_credential(seed=1)
        assert re.match(r"^[A-Z][a-z]+\.phoenix\.[a-z]+\.\d$", cred)

    def test_varies_without_fixed_seed(self):
        creds = {pp.generate_phoenix_session_credential() for _ in range(20)}
        assert len(creds) > 1

    def test_distinct_from_spawn_and_install_passphrase_namespaces(self):
        # Different middle-word ("phoenix") from spawn (".to.") and image-build (".boot.")
        # patterns — session-scoped credentials must be distinguishable in logs/output.
        cred = pp.generate_phoenix_session_credential(seed=1)
        assert ".phoenix." in cred
        assert ".to." not in cred
        assert ".boot." not in cred


# ---------------------------------------------------------------------------
# phoenix_session_credential_section
# ---------------------------------------------------------------------------

class TestPhoenixSessionCredentialSection:
    def _section(self, **kw):
        return pp.phoenix_session_credential_section(
            "pve01", seed=1, now_fn=lambda: "2026-06-08T00:00:00+00:00", **kw,
        )

    def test_returns_dict_with_expected_keys(self):
        sec = self._section()
        for key in ("schema_version", "scope", "hostname", "generated_at", "credential",
                    "credential_format", "valid_window", "rotation_requirement",
                    "constraint", "notes"):
            assert key in sec

    def test_scope_is_session_only(self):
        assert self._section()["scope"] == "phoenix-setup-session-only"

    def test_uses_injected_clock(self):
        assert self._section()["generated_at"] == "2026-06-08T00:00:00+00:00"

    def test_rotation_requirement_present_and_required(self):
        sec = self._section()
        rr = sec["rotation_requirement"]
        assert rr["required"] is True
        assert "rotate" in rr["statement"].lower()
        assert "session" in rr["statement"].lower()

    def test_rotation_requirement_says_before_resuming_normal_operations(self):
        sec = self._section()
        assert "before resuming normal operations" in sec["rotation_requirement"]["statement"].lower()

    def test_constraint_references_ad060(self):
        sec = self._section()
        assert sec["constraint"]["ad"] == "AD-060"
        assert "exception" in sec["constraint"]["statement"].lower()

    def test_never_the_permanent_keystore_language_present(self):
        sec = self._section()
        full_text = " ".join([
            sec["rotation_requirement"]["statement"],
            sec["constraint"]["statement"],
            " ".join(sec["notes"]),
        ]).lower()
        assert "permanent" in full_text
        assert "never" in full_text

    def test_accepts_explicit_credential(self):
        sec = pp.phoenix_session_credential_section("pve01", credential="Custom.phoenix.x.1",
                                                      now_fn=lambda: "now")
        assert sec["credential"] == "Custom.phoenix.x.1"

    def test_credential_generated_when_not_given(self):
        sec = self._section()
        assert sec["credential"] == pp.generate_phoenix_session_credential(seed=1)


# ---------------------------------------------------------------------------
# Integration into PhoenixPlaybookGenerator.build / build_phoenix_playbook
# ---------------------------------------------------------------------------

class TestPlaybookIncludesSessionCredential:
    def test_build_includes_section_by_default(self):
        gen = pp.PhoenixPlaybookGenerator(_MANIFEST, now_fn=lambda: "2026-06-08T00:00:00+00:00")
        playbook = gen.build(session_credential_seed=1)
        sec = playbook["temporary_session_credential"]
        assert sec is not None
        assert sec["hostname"] == "pve01"
        assert sec["credential"] == pp.generate_phoenix_session_credential(seed=1)

    def test_build_can_omit_section(self):
        gen = pp.PhoenixPlaybookGenerator(_MANIFEST, now_fn=lambda: "2026-06-08T00:00:00+00:00")
        playbook = gen.build(include_session_credential=False)
        assert playbook["temporary_session_credential"] is None

    def test_factory_threads_session_credential_options(self):
        playbook = pp.build_phoenix_playbook(
            _MANIFEST, now_fn=lambda: "2026-06-08T00:00:00+00:00", session_credential_seed=1,
        )
        assert playbook["temporary_session_credential"]["credential"] == \
            pp.generate_phoenix_session_credential(seed=1)

    def test_factory_can_omit_session_credential(self):
        playbook = pp.build_phoenix_playbook(
            _MANIFEST, now_fn=lambda: "2026-06-08T00:00:00+00:00", include_session_credential=False,
        )
        assert playbook["temporary_session_credential"] is None

    def test_section_uses_generator_clock_not_real_clock(self):
        gen = pp.PhoenixPlaybookGenerator(_MANIFEST, now_fn=lambda: "2099-01-01T00:00:00+00:00")
        playbook = gen.build(session_credential_seed=1)
        assert playbook["temporary_session_credential"]["generated_at"] == "2099-01-01T00:00:00+00:00"
        assert playbook["generated_at"] == "2099-01-01T00:00:00+00:00"


# ---------------------------------------------------------------------------
# Constraint-honored guard — structural assertion (mirrors Phase 1.I's
# "no invented score keys" guard): the extension never reads a permanent
# hypervisor root-credential VALUE from any store.
# ---------------------------------------------------------------------------

class TestConstraintHonoredNoRootCredentialReads:
    def _source(self):
        return (_PB_DIR / "phoenix_playbook.py").read_text(encoding="utf-8")

    def test_no_root_password_value_read_pattern(self):
        src = self._source()
        forbidden_patterns = [
            r"get_secret\(.*root.password",
            r"keepass.*\.get\(.*root.password",
            r"\.get_password\(.*root",
            r"unlock.*\(\).*root.*password",
            r"pve0\d.*root.*password.*\)\s*\[",
        ]
        for pat in forbidden_patterns:
            assert not re.search(pat, src, re.IGNORECASE), f"forbidden pattern present: {pat}"

    def test_session_credential_is_freshly_generated_not_looked_up(self):
        src = self._source()
        fn_match = re.search(
            r"def phoenix_session_credential_section\([^)]*\)[^:]*:\n((?:    .*\n|\n)*)", src,
        )
        assert fn_match
        body = fn_match.group(1)
        body_code = re.sub(r'"""(?:.|\n)*?"""', "", body, count=1)
        assert "generate_phoenix_session_credential" in body_code
        # Strip string-literal contents (generated runbook prose may
        # legitimately mention "keepass-managed" while documenting the
        # rotation flow) — what must be absent is an actual CALL shape.
        body_no_strings = re.sub(r'"(?:[^"\\]|\\.)*"', '""', body_code)
        for forbidden_call in ("get_secret(", "keepass.", "load_secret_registry(",
                               ".get_password(", "unlock("):
            assert forbidden_call not in body_no_strings.lower()

    def test_no_imports_of_credential_or_ssh_client_libs(self):
        src = self._source()
        import_lines = [ln for ln in src.splitlines()
                        if re.match(r"^\s*(import|from)\s", ln)]
        joined = "\n".join(import_lines).lower()
        for forbidden_import in ("paramiko", "fabric", "pykeepass", "keepass"):
            assert forbidden_import not in joined

    def test_no_subprocess_or_live_connection_calls(self):
        src = self._source()
        for forbidden in ("subprocess", "os.system", "SSHClient", "Popen", "socket.connect"):
            assert forbidden not in src
