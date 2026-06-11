"""
test_spawn_media_authorization.py — Tests for Phase 1.J (AD-060(c)):
  _image_builder.py            — pre-generated spawn-media credential record
                                 + pending-join-authorization mechanism
  authorize-spawn-media-join.py — human-operated authorization-flip CLI

Covers: build-time passphrase generation + paired authorization-record
structure, `authorized` defaulting False, hash-only recording (never the
plaintext passphrase), state-record append/update helpers, and the CLI's
flip/list/refuse-to-reauthorize/refuse-unknown-bundle behaviour. Also a
structural "constraint honored" guard asserting neither file reads a
hypervisor root-credential VALUE from any store.
"""

import importlib.util
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

_PB_DIR = Path(__file__).parent.parent.parent / "proxmox-bootstrap"

import _image_builder as _ib

_NOW = datetime(2026, 6, 8, 0, 0, 0, tzinfo=timezone.utc)


def _manifest(cell_id="proxmox-cell-a", hostname="pve02"):
    return {
        "cell_id": cell_id,
        "host_identity": {"hostname": hostname, "domain": "home.example.com",
                          "fqdn": f"{hostname}.home.example.com"},
    }


def _load_authorize_cli():
    spec = importlib.util.spec_from_file_location(
        "authorize_spawn_media_join", _PB_DIR / "authorize-spawn-media-join.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_cli = _load_authorize_cli()


# ---------------------------------------------------------------------------
# hash_install_passphrase
# ---------------------------------------------------------------------------

class TestHashInstallPassphrase:
    def test_returns_hex_sha256(self):
        h = _ib.hash_install_passphrase("Anchor.boot.glyph.3")
        assert isinstance(h, str)
        assert len(h) == 64
        assert re.match(r"^[0-9a-f]{64}$", h)

    def test_deterministic(self):
        assert _ib.hash_install_passphrase("x") == _ib.hash_install_passphrase("x")

    def test_changes_with_input(self):
        assert _ib.hash_install_passphrase("a") != _ib.hash_install_passphrase("b")

    def test_never_reversible_obviously_not_the_plaintext(self):
        h = _ib.hash_install_passphrase("Anchor.boot.glyph.3")
        assert "Anchor" not in h
        assert "boot" not in h


# ---------------------------------------------------------------------------
# build_pending_join_authorization
# ---------------------------------------------------------------------------

class TestBuildPendingJoinAuthorization:
    def _record(self):
        return _ib.build_pending_join_authorization(
            _manifest(), "bootstrap-image-proxmox-cell-a-2026-06-08_00_00_00.tar.gz",
            "Anchor.boot.glyph.3", now=_NOW,
        )

    def test_returns_dict_with_expected_keys(self):
        rec = self._record()
        for key in ("schema_version", "record_type", "cell_id", "image_bundle_name",
                    "generated_at", "passphrase_hash", "passphrase_hash_algorithm",
                    "authorized", "authorized_at", "authorized_by", "notes"):
            assert key in rec

    def test_record_type(self):
        assert self._record()["record_type"] == "pending_join_authorization"

    def test_authorized_defaults_false(self):
        rec = self._record()
        assert rec["authorized"] is False
        assert rec["authorized_at"] is None
        assert rec["authorized_by"] is None

    def test_records_hash_not_plaintext(self):
        rec = self._record()
        assert rec["passphrase_hash"] == _ib.hash_install_passphrase("Anchor.boot.glyph.3")
        dumped = json.dumps(rec)
        assert "Anchor.boot.glyph.3" not in dumped

    def test_uses_injected_now(self):
        assert self._record()["generated_at"] == _NOW.isoformat()


# ---------------------------------------------------------------------------
# build_pregenerated_spawn_media_record
# ---------------------------------------------------------------------------

class TestBuildPregeneratedSpawnMediaRecord:
    def test_returns_dict_with_expected_keys(self):
        rec = _ib.build_pregenerated_spawn_media_record(_manifest(), seed=1, now=_NOW)
        for key in ("passphrase", "image_bundle_name", "authorization_record"):
            assert key in rec

    def test_passphrase_uses_install_passphrase_pattern(self):
        rec = _ib.build_pregenerated_spawn_media_record(_manifest(), seed=1, now=_NOW)
        assert re.match(r"^[A-Z][a-z]+\.boot\.[a-z]+\.\d$", rec["passphrase"])

    def test_authorization_record_hash_matches_passphrase(self):
        rec = _ib.build_pregenerated_spawn_media_record(_manifest(), seed=1, now=_NOW)
        assert rec["authorization_record"]["passphrase_hash"] == _ib.hash_install_passphrase(rec["passphrase"])

    def test_authorization_record_starts_unauthorized(self):
        rec = _ib.build_pregenerated_spawn_media_record(_manifest(), seed=1, now=_NOW)
        assert rec["authorization_record"]["authorized"] is False

    def test_image_bundle_name_consistent(self):
        rec = _ib.build_pregenerated_spawn_media_record(_manifest(), seed=1, now=_NOW)
        assert rec["image_bundle_name"] == rec["authorization_record"]["image_bundle_name"]

    def test_accepts_explicit_passphrase(self):
        rec = _ib.build_pregenerated_spawn_media_record(_manifest(), passphrase="Custom.boot.value.7", now=_NOW)
        assert rec["passphrase"] == "Custom.boot.value.7"
        assert rec["authorization_record"]["passphrase_hash"] == _ib.hash_install_passphrase("Custom.boot.value.7")


# ---------------------------------------------------------------------------
# record_pending_join_authorization (state transformation)
# ---------------------------------------------------------------------------

class TestRecordPendingJoinAuthorization:
    def test_appends_to_empty_state(self):
        rec = _ib.build_pending_join_authorization(_manifest(), "bundle.tar.gz", "x", now=_NOW)
        state = _ib.record_pending_join_authorization({}, rec)
        assert state["pending_join_authorizations"] == [rec]

    def test_appends_to_existing_list(self):
        rec1 = _ib.build_pending_join_authorization(_manifest(), "b1.tar.gz", "x", now=_NOW)
        rec2 = _ib.build_pending_join_authorization(_manifest(), "b2.tar.gz", "y", now=_NOW)
        state = _ib.record_pending_join_authorization({"pending_join_authorizations": [rec1]}, rec2)
        assert state["pending_join_authorizations"] == [rec1, rec2]

    def test_does_not_mutate_input_state(self):
        original = {"pending_join_authorizations": []}
        rec = _ib.build_pending_join_authorization(_manifest(), "b.tar.gz", "x", now=_NOW)
        new_state = _ib.record_pending_join_authorization(original, rec)
        assert original["pending_join_authorizations"] == []
        assert new_state is not original


# ---------------------------------------------------------------------------
# authorize-spawn-media-join.py CLI internals
# ---------------------------------------------------------------------------

class TestAuthorizeCli:
    def _state_with_pending(self, bundle="bootstrap-image-proxmox-cell-a-2026-06-08_00_00_00.tar.gz"):
        rec = _ib.build_pending_join_authorization(_manifest(), bundle, "Anchor.boot.glyph.3", now=_NOW)
        return {"pending_join_authorizations": [rec]}

    def test_authorize_flips_flag_and_records_attribution(self):
        state = self._state_with_pending()
        bundle = state["pending_join_authorizations"][0]["image_bundle_name"]
        new_state = _cli._authorize(state, bundle, "dave", lambda: "2026-06-08T01:00:00+00:00")
        rec = new_state["pending_join_authorizations"][0]
        assert rec["authorized"] is True
        assert rec["authorized_by"] == "dave"
        assert rec["authorized_at"] == "2026-06-08T01:00:00+00:00"

    def test_authorize_unknown_bundle_exits_nonzero(self):
        state = self._state_with_pending()
        with pytest.raises(SystemExit) as exc:
            _cli._authorize(state, "no-such-bundle.tar.gz", "dave", lambda: "now")
        assert exc.value.code != 0

    def test_authorize_already_authorized_refuses(self):
        state = self._state_with_pending()
        bundle = state["pending_join_authorizations"][0]["image_bundle_name"]
        once = _cli._authorize(state, bundle, "dave", lambda: "2026-06-08T01:00:00+00:00")
        with pytest.raises(SystemExit) as exc:
            _cli._authorize(once, bundle, "someone-else", lambda: "later")
        assert exc.value.code != 0
        # the original attribution must be preserved (not silently overwritten)
        assert once["pending_join_authorizations"][0]["authorized_by"] == "dave"

    def test_authorize_does_not_mutate_input_state(self):
        state = self._state_with_pending()
        bundle = state["pending_join_authorizations"][0]["image_bundle_name"]
        _cli._authorize(state, bundle, "dave", lambda: "2026-06-08T01:00:00+00:00")
        assert state["pending_join_authorizations"][0]["authorized"] is False

    def test_never_auto_authorizes_without_explicit_call(self):
        # Building a record never sets authorized True — the only path to
        # True is _authorize(), which requires an explicit operator name.
        rec = _ib.build_pending_join_authorization(_manifest(), "b.tar.gz", "x", now=_NOW)
        assert rec["authorized"] is False


# ---------------------------------------------------------------------------
# Constraint-honored guard — structural assertion (mirrors Phase 1.I's
# "no invented score keys" guard): neither file reads a hypervisor
# root-credential VALUE from any store.
# ---------------------------------------------------------------------------

class TestConstraintHonoredNoRootCredentialReads:
    def _sources(self):
        return {
            "_image_builder.py": (_PB_DIR / "_image_builder.py").read_text(encoding="utf-8"),
            "authorize-spawn-media-join.py": (_PB_DIR / "authorize-spawn-media-join.py").read_text(encoding="utf-8"),
        }

    def test_no_root_password_value_read_pattern(self):
        forbidden_patterns = [
            r"get_secret\(.*root.password",
            r"keepass.*\.get\(.*root.password",
            r"\.get_password\(.*root",
            r"unlock.*\(\).*root.*password",
            r"pve0\d.*root.*password.*\)\s*\[",
        ]
        for fname, src in self._sources().items():
            for pat in forbidden_patterns:
                assert not re.search(pat, src, re.IGNORECASE), f"{fname}: forbidden pattern present: {pat}"

    def test_only_passphrase_hash_recorded_never_plaintext_field(self):
        src = self._sources()["_image_builder.py"]
        fn_match = re.search(
            r"def build_pending_join_authorization\([^)]*\)[^:]*:\n((?:    .*\n|\n)*)", src,
        )
        assert fn_match
        body = fn_match.group(1)
        body_code = re.sub(r'"""(?:.|\n)*?"""', "", body, count=1)
        assert '"passphrase_hash"' in body_code
        assert '"passphrase":' not in body_code
        assert '"plaintext"' not in body_code

    def test_no_imports_of_credential_or_ssh_client_libs(self):
        for fname, src in self._sources().items():
            import_lines = [ln for ln in src.splitlines()
                            if re.match(r"^\s*(import|from)\s", ln)]
            joined = "\n".join(import_lines).lower()
            for forbidden_import in ("paramiko", "fabric", "pykeepass", "pykeepass", "keepass"):
                assert forbidden_import not in joined, f"{fname}: forbidden import: {forbidden_import}"

    def test_no_subprocess_or_live_connection_calls(self):
        for fname, src in self._sources().items():
            for forbidden in ("subprocess", "os.system", "SSHClient", "Popen", "socket.connect"):
                assert forbidden not in src, f"{fname}: forbidden call present: {forbidden}"
