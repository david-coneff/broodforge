"""
test_image_builder.py — Tests for Phase 1.H (AD-057):
  _image_builder.py            — bootstrap image staging bundle builder
  html_package_manifest.py     — build_bootstrap_image_manifest_html (AD-051 twin)
"""

import json
import os
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

_ANSWER_FILE_CLI = Path(_ROOT) / "proxmox-bootstrap" / "generate-answer-file.py"

import _image_builder as _ib
import html_package_manifest as _hpm

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _manifest(cell_id="pve01-cell", hostname="pve01", profile="lan"):
    return {
        "schema_version": "1.0",
        "cell_id": cell_id,
        "generated_at": "2026-06-01T12:00:00+00:00",
        "setup_mode": "autonomous",
        "host_identity": {
            "hostname": hostname,
            "domain": "home.example.com",
            "fqdn": f"{hostname}.home.example.com",
            "cell_id": cell_id,
            "timezone": "America/Denver",
        },
        "network_topology": {
            "profile": profile,
            "management_cidr": "192.168.50.0/24",
            "gateway": "192.168.50.1",
            "nameservers": ["192.168.50.1", "1.1.1.1"],
        },
    }


_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


# ===========================================================================
# generate_install_passphrase
# ===========================================================================

class TestInstallPassphrase:
    def test_returns_string(self):
        p = _ib.generate_install_passphrase(seed=1)
        assert isinstance(p, str)

    def test_deterministic_with_seed(self):
        a = _ib.generate_install_passphrase(seed=42)
        b = _ib.generate_install_passphrase(seed=42)
        assert a == b

    def test_varies_without_fixed_seed(self):
        # Different seeds should (overwhelmingly likely) produce different values —
        # guards against a hard-coded/predictable passphrase.
        values = {_ib.generate_install_passphrase(seed=s) for s in range(10)}
        assert len(values) > 1

    def test_format_looks_like_passphrase(self):
        p = _ib.generate_install_passphrase(seed=7)
        parts = p.split(".")
        assert len(parts) == 4
        assert parts[0][0].isupper()
        assert parts[3].isdigit()


# ===========================================================================
# generate_answer_toml
# ===========================================================================

class TestAnswerToml:
    def test_returns_string(self):
        s = _ib.generate_answer_toml(_manifest(), root_passphrase="Test.boot.case.1", now=_NOW)
        assert isinstance(s, str)

    def test_contains_global_section(self):
        s = _ib.generate_answer_toml(_manifest(), root_passphrase="Test.boot.case.1", now=_NOW)
        assert "[global]" in s

    def test_contains_network_section(self):
        s = _ib.generate_answer_toml(_manifest(), root_passphrase="Test.boot.case.1", now=_NOW)
        assert "[network]" in s

    def test_contains_disk_setup_section(self):
        s = _ib.generate_answer_toml(_manifest(), root_passphrase="Test.boot.case.1", now=_NOW)
        assert "[disk-setup]" in s

    def test_derives_fqdn_from_manifest(self):
        s = _ib.generate_answer_toml(_manifest(hostname="hatchery01"), root_passphrase="x", now=_NOW)
        assert "hatchery01.home.example.com" in s

    def test_derives_timezone_from_manifest(self):
        s = _ib.generate_answer_toml(_manifest(), root_passphrase="x", now=_NOW)
        assert "America/Denver" in s

    def test_derives_gateway_from_manifest(self):
        s = _ib.generate_answer_toml(_manifest(), root_passphrase="x", now=_NOW)
        assert "192.168.50.1" in s

    def test_uses_provided_passphrase(self):
        s = _ib.generate_answer_toml(_manifest(), root_passphrase="Unique.boot.value.7", now=_NOW)
        assert "Unique.boot.value.7" in s

    def test_generates_passphrase_when_not_given(self):
        s = _ib.generate_answer_toml(_manifest(), now=_NOW)
        assert "root-password" in s

    def test_no_fixed_default_password(self):
        # Guards the security invariant: never a hard-coded/predictable root password.
        s1 = _ib.generate_answer_toml(_manifest(), now=_NOW)
        s2 = _ib.generate_answer_toml(_manifest(), now=_NOW)

        def _pw(text):
            for line in text.splitlines():
                if line.strip().startswith("root-password"):
                    return line
            return None

        assert _pw(s1) != _pw(s2)

    def test_disk_list_placeholder_when_not_given(self):
        s = _ib.generate_answer_toml(_manifest(), root_passphrase="x", now=_NOW)
        assert "POPULATE" in s

    def test_disk_list_uses_provided_disks(self):
        s = _ib.generate_answer_toml(_manifest(), root_passphrase="x", disk_list=["/dev/sda", "/dev/sdb"], now=_NOW)
        assert "/dev/sda" in s
        assert "/dev/sdb" in s

    def test_keyboard_and_country_overridable(self):
        s = _ib.generate_answer_toml(_manifest(), root_passphrase="x", keyboard="de", country="de", now=_NOW)
        assert 'keyboard = "de"' in s
        assert 'country = "de"' in s

    def test_filesystem_overridable(self):
        s = _ib.generate_answer_toml(_manifest(), root_passphrase="x", filesystem="ext4", now=_NOW)
        assert 'filesystem = "ext4"' in s


# ===========================================================================
# First-boot hook generation
# ===========================================================================

class TestFirstBootUnit:
    def test_returns_string(self):
        s = _ib.generate_first_boot_unit(_manifest())
        assert isinstance(s, str)

    def test_is_systemd_unit(self):
        s = _ib.generate_first_boot_unit(_manifest())
        assert "[Unit]" in s
        assert "[Service]" in s
        assert "[Install]" in s

    def test_runs_forge_sh(self):
        s = _ib.generate_first_boot_unit(_manifest())
        assert "forge.sh" in s

    def test_is_oneshot_idempotent(self):
        s = _ib.generate_first_boot_unit(_manifest())
        assert "Type=oneshot" in s
        assert "ConditionPathExists=!" in s

    def test_disables_itself_after_run(self):
        s = _ib.generate_first_boot_unit(_manifest())
        assert "systemctl disable" in s


class TestFirstBootInstallScript:
    def test_returns_string(self):
        s = _ib.generate_first_boot_install_sh(_manifest())
        assert isinstance(s, str)

    def test_has_shebang(self):
        s = _ib.generate_first_boot_install_sh(_manifest())
        assert s.startswith("#!/usr/bin/env bash")

    def test_extracts_forge_package(self):
        s = _ib.generate_first_boot_install_sh(_manifest())
        assert "forge-package.tar.gz" in s
        assert "tar -xzf" in s

    def test_enables_systemd_unit(self):
        s = _ib.generate_first_boot_install_sh(_manifest())
        assert "systemctl enable" in s
        assert _ib.FIRST_BOOT_SERVICE_NAME in s


# ===========================================================================
# Bundle naming and contents listing
# ===========================================================================

class TestImageBundleName:
    def test_contains_cell_id(self):
        name = _ib.image_bundle_name(_manifest(), now=_NOW)
        assert "pve01-cell" in name

    def test_contains_timestamp(self):
        name = _ib.image_bundle_name(_manifest(), now=_NOW)
        assert "2026-06-01" in name

    def test_starts_with_bootstrap_image(self):
        name = _ib.image_bundle_name(_manifest(), now=_NOW)
        assert name.startswith("bootstrap-image-")

    def test_ends_with_tar_gz(self):
        name = _ib.image_bundle_name(_manifest(), now=_NOW)
        assert name.endswith(".tar.gz")


class TestImageBundleContents:
    def test_returns_list(self):
        items = _ib.image_bundle_contents(_manifest())
        assert isinstance(items, list)

    def test_contains_answer_toml(self):
        items = _ib.image_bundle_contents(_manifest())
        assert "iso-staging/answer.toml" in items

    def test_contains_forge_package(self):
        items = _ib.image_bundle_contents(_manifest())
        assert "iso-staging/forge-package.tar.gz" in items

    def test_contains_first_boot_unit(self):
        items = _ib.image_bundle_contents(_manifest())
        assert any("first-boot" in i and i.endswith(".service") for i in items)

    def test_contains_manifest_html_twin(self):
        items = _ib.image_bundle_contents(_manifest())
        assert "iso-staging/bootstrap-image-manifest.json" in items
        assert "iso-staging/bootstrap-image-manifest.html" in items

    def test_contains_readme(self):
        items = _ib.image_bundle_contents(_manifest())
        assert "iso-staging/README.md" in items


# ===========================================================================
# build_bootstrap_image (full assembly)
# ===========================================================================

class TestBuildBootstrapImage:
    def _build(self, tmp_path, manifest=None, **kw):
        m = manifest or _manifest()
        return _ib.build_bootstrap_image(
            manifest=m, output_dir=tmp_path, now=_NOW,
            root_passphrase="Fixed.boot.test.5", **kw
        )

    def test_returns_path(self, tmp_path):
        bundle = self._build(tmp_path)
        assert isinstance(bundle, Path)

    def test_file_exists(self, tmp_path):
        bundle = self._build(tmp_path)
        assert bundle.exists()

    def test_is_tar_gz(self, tmp_path):
        bundle = self._build(tmp_path)
        assert tarfile.is_tarfile(str(bundle))

    def test_contains_answer_toml(self, tmp_path):
        bundle = self._build(tmp_path)
        with tarfile.open(str(bundle), "r:gz") as tar:
            names = tar.getnames()
        assert "iso-staging/answer.toml" in names

    def test_contains_forge_package(self, tmp_path):
        bundle = self._build(tmp_path)
        with tarfile.open(str(bundle), "r:gz") as tar:
            names = tar.getnames()
        assert "iso-staging/forge-package.tar.gz" in names

    def test_embedded_forge_package_is_valid_tar(self, tmp_path):
        bundle = self._build(tmp_path)
        with tarfile.open(str(bundle), "r:gz") as tar:
            member = tar.extractfile("iso-staging/forge-package.tar.gz")
            data = member.read()
        inner_path = tmp_path / "extracted-forge-package.tar.gz"
        inner_path.write_bytes(data)
        assert tarfile.is_tarfile(str(inner_path))
        with tarfile.open(str(inner_path), "r:gz") as inner:
            assert "forge-manifest.json" in inner.getnames()
            assert "forge.sh" in inner.getnames()

    def test_contains_first_boot_unit(self, tmp_path):
        bundle = self._build(tmp_path)
        with tarfile.open(str(bundle), "r:gz") as tar:
            names = tar.getnames()
        assert f"iso-staging/first-boot/{_ib.FIRST_BOOT_SERVICE_NAME}" in names
        assert "iso-staging/first-boot/install-first-boot-hook.sh" in names

    def test_contains_manifest_json_and_html(self, tmp_path):
        bundle = self._build(tmp_path)
        with tarfile.open(str(bundle), "r:gz") as tar:
            names = tar.getnames()
        assert "iso-staging/bootstrap-image-manifest.json" in names
        assert "iso-staging/bootstrap-image-manifest.html" in names

    def test_contains_readme(self, tmp_path):
        bundle = self._build(tmp_path)
        with tarfile.open(str(bundle), "r:gz") as tar:
            names = tar.getnames()
        assert "iso-staging/README.md" in names

    def test_image_manifest_content_correct(self, tmp_path):
        m = _manifest(cell_id="testcell")
        bundle = self._build(tmp_path, manifest=m)
        with tarfile.open(str(bundle), "r:gz") as tar:
            data = tar.extractfile("iso-staging/bootstrap-image-manifest.json").read()
        loaded = json.loads(data)
        assert loaded["cell_id"] == "testcell"
        assert "embedded_forge_package" in loaded
        assert loaded["embedded_forge_package"]["sha256"]

    def test_no_real_secrets_only_install_passphrase(self, tmp_path):
        # Security invariant: the bundle must not contain a KeePass-managed
        # secret value. The only "secret-shaped" string allowed is the
        # single-use install passphrase, which is documented as such.
        bundle = self._build(tmp_path)
        with tarfile.open(str(bundle), "r:gz") as tar:
            answer = tar.extractfile("iso-staging/answer.toml").read().decode("utf-8")
        assert "Fixed.boot.test.5" in answer
        assert "kdbx" not in answer.lower()

    def test_package_name_in_output_dir(self, tmp_path):
        bundle = self._build(tmp_path)
        assert bundle.parent == tmp_path

    def test_different_cells_different_bundles(self, tmp_path):
        m1 = _manifest(cell_id="cell-a")
        m2 = _manifest(cell_id="cell-b")
        b1 = self._build(tmp_path, manifest=m1)
        b2 = self._build(tmp_path, manifest=m2)
        assert b1.name != b2.name


# ===========================================================================
# build_image_manifest
# ===========================================================================

class TestBuildImageManifest:
    def test_includes_hash_of_forge_package(self, tmp_path):
        fake_pkg = tmp_path / "forge-package-test.tar.gz"
        fake_pkg.write_bytes(b"fake package bytes")
        m = _ib.build_image_manifest(_manifest(), fake_pkg, "answer toml text", now=_NOW)
        assert m["embedded_forge_package"]["sha256"] == \
            __import__("hashlib").sha256(b"fake package bytes").hexdigest()

    def test_includes_artifact_type(self, tmp_path):
        fake_pkg = tmp_path / "p.tar.gz"
        fake_pkg.write_bytes(b"x")
        m = _ib.build_image_manifest(_manifest(), fake_pkg, "x", now=_NOW)
        assert m["artifact_type"] == "bootstrap-image-staging-bundle"

    def test_includes_cell_id(self, tmp_path):
        fake_pkg = tmp_path / "p.tar.gz"
        fake_pkg.write_bytes(b"x")
        m = _ib.build_image_manifest(_manifest(cell_id="xyz"), fake_pkg, "x", now=_NOW)
        assert m["cell_id"] == "xyz"


# ===========================================================================
# build_bootstrap_image_manifest_html (AD-051 twin)
# ===========================================================================

class TestBootstrapImageManifestHtml:
    def _image_manifest(self, tmp_path):
        fake_pkg = tmp_path / "forge-package-test.tar.gz"
        fake_pkg.write_bytes(b"fake package bytes")
        return _ib.build_image_manifest(_manifest(), fake_pkg, "answer toml text", now=_NOW)

    def test_returns_html_string(self, tmp_path):
        im = self._image_manifest(tmp_path)
        html = _hpm.build_bootstrap_image_manifest_html(_manifest(), im, now_fn=lambda: _NOW.isoformat())
        assert isinstance(html, str)
        assert html.startswith("<!DOCTYPE html>")

    def test_mentions_staging_bundle(self, tmp_path):
        im = self._image_manifest(tmp_path)
        html = _hpm.build_bootstrap_image_manifest_html(_manifest(), im, now_fn=lambda: _NOW.isoformat())
        assert "staging bundle" in html.lower()

    def test_includes_package_hash(self, tmp_path):
        im = self._image_manifest(tmp_path)
        html = _hpm.build_bootstrap_image_manifest_html(_manifest(), im, now_fn=lambda: _NOW.isoformat())
        assert im["embedded_forge_package"]["sha256"] in html

    def test_includes_cell_id(self, tmp_path):
        im = self._image_manifest(tmp_path)
        html = _hpm.build_bootstrap_image_manifest_html(_manifest(cell_id="htmlcell"), im, now_fn=lambda: _NOW.isoformat())
        assert "htmlcell" in html

    def test_warns_about_passphrase(self, tmp_path):
        im = self._image_manifest(tmp_path)
        html = _hpm.build_bootstrap_image_manifest_html(_manifest(), im, now_fn=lambda: _NOW.isoformat())
        assert "single-use" in html.lower()
        assert "keepass" in html.lower()


# ===========================================================================
# build_pregenerated_spawn_media_record + record_pending_join_authorization
# (N-004: Phase 1.J authorization pipeline wiring)
# ===========================================================================

class TestBuildPregeneratedSpawnMediaRecord:
    def test_returns_dict_with_passphrase(self):
        result = _ib.build_pregenerated_spawn_media_record(_manifest(), now=_NOW)
        assert "passphrase" in result
        assert isinstance(result["passphrase"], str)

    def test_returns_dict_with_authorization_record(self):
        result = _ib.build_pregenerated_spawn_media_record(_manifest(), now=_NOW)
        assert "authorization_record" in result
        assert isinstance(result["authorization_record"], dict)

    def test_returns_dict_with_image_bundle_name(self):
        result = _ib.build_pregenerated_spawn_media_record(_manifest(), now=_NOW)
        assert "image_bundle_name" in result
        assert result["image_bundle_name"].endswith(".tar.gz")

    def test_authorization_record_has_correct_shape(self):
        result = _ib.build_pregenerated_spawn_media_record(_manifest(), now=_NOW)
        rec = result["authorization_record"]
        assert rec["record_type"] == "pending_join_authorization"
        assert rec["authorized"] is False
        assert "passphrase_hash" in rec
        assert rec["passphrase_hash_algorithm"] == "sha256"
        assert rec["authorized_at"] is None
        assert rec["authorized_by"] is None

    def test_passphrase_not_in_authorization_record(self):
        # Security invariant: only the hash is recorded, never the plaintext.
        result = _ib.build_pregenerated_spawn_media_record(_manifest(cell_id="sectest"), now=_NOW)
        plaintext = result["passphrase"]
        rec = result["authorization_record"]
        assert plaintext not in str(rec), "plaintext passphrase must not appear in authorization record"

    def test_passphrase_hash_matches(self):
        result = _ib.build_pregenerated_spawn_media_record(_manifest(), seed=99, now=_NOW)
        expected_hash = _ib.hash_install_passphrase(result["passphrase"])
        assert result["authorization_record"]["passphrase_hash"] == expected_hash

    def test_cell_id_in_authorization_record(self):
        result = _ib.build_pregenerated_spawn_media_record(_manifest(cell_id="my-cell"), now=_NOW)
        assert result["authorization_record"]["cell_id"] == "my-cell"

    def test_deterministic_with_seed(self):
        a = _ib.build_pregenerated_spawn_media_record(_manifest(), seed=7, now=_NOW)
        b = _ib.build_pregenerated_spawn_media_record(_manifest(), seed=7, now=_NOW)
        assert a["passphrase"] == b["passphrase"]
        assert a["authorization_record"]["passphrase_hash"] == b["authorization_record"]["passphrase_hash"]


class TestRecordPendingJoinAuthorization:
    def _record(self, cell_id="pve01-cell"):
        return _ib.build_pregenerated_spawn_media_record(
            _manifest(cell_id=cell_id), now=_NOW
        )["authorization_record"]

    def test_appends_record_to_empty_state(self):
        state = {}
        rec = self._record()
        new_state = _ib.record_pending_join_authorization(state, rec)
        assert len(new_state["pending_join_authorizations"]) == 1
        assert new_state["pending_join_authorizations"][0] is rec

    def test_appends_to_existing_list(self):
        first = self._record()
        state = {"pending_join_authorizations": [first]}
        second = self._record()
        new_state = _ib.record_pending_join_authorization(state, second)
        assert len(new_state["pending_join_authorizations"]) == 2

    def test_does_not_mutate_original_state(self):
        state = {}
        rec = self._record()
        _ib.record_pending_join_authorization(state, rec)
        assert "pending_join_authorizations" not in state

    def test_returned_state_has_all_original_keys(self):
        state = {"cell_id": "pve01-cell", "nodes": []}
        rec = self._record()
        new_state = _ib.record_pending_join_authorization(state, rec)
        assert new_state["cell_id"] == "pve01-cell"
        assert new_state["nodes"] == []


# ===========================================================================
# generate_staging_readme
# ===========================================================================

class TestStagingReadme:
    def test_returns_string(self):
        s = _ib.generate_staging_readme(_manifest(), now=_NOW)
        assert isinstance(s, str)

    def test_explains_not_a_real_iso(self):
        s = _ib.generate_staging_readme(_manifest(), now=_NOW)
        assert "not a bootable ISO" in s or "not a bootable iso" in s.lower()

    def test_mentions_official_proxmox_iso(self):
        s = _ib.generate_staging_readme(_manifest(), now=_NOW)
        assert "Proxmox VE ISO" in s

    def test_mentions_optional_alternative_path(self):
        s = _ib.generate_staging_readme(_manifest(), now=_NOW)
        assert "OPTIONAL" in s or "optional" in s.lower()


# ===========================================================================
# generate-answer-file.py CLI (R7-001 — PAP audit fix)
# ===========================================================================

class TestAnswerFileCLI:
    """CLI-level tests for generate-answer-file.py (thin wrapper over _image_builder)."""

    def _run(self, args: list, tmp_path: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_ANSWER_FILE_CLI)] + args,
            capture_output=True, text=True, timeout=15, cwd=str(tmp_path),
        )

    def test_missing_manifest_exits_1(self, tmp_path):
        result = self._run(["--manifest", str(tmp_path / "nonexistent.json")], tmp_path)
        assert result.returncode == 1
        assert "not found" in result.stderr.lower() or "manifest" in result.stderr.lower()

    def test_invalid_json_manifest_exits_1(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{ this is not valid json }")
        result = self._run(["--manifest", str(bad)], tmp_path)
        assert result.returncode == 1
        assert "json" in result.stderr.lower() or "valid" in result.stderr.lower()

    def test_valid_manifest_outputs_answer_toml(self, tmp_path):
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(_manifest()))
        result = self._run(["--manifest", str(manifest_path)], tmp_path)
        assert result.returncode == 0
        assert "[global]" in result.stdout
        assert "[network]" in result.stdout

    def test_valid_manifest_with_output_flag(self, tmp_path):
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(_manifest()))
        out_path = tmp_path / "answer.toml"
        result = self._run(["--manifest", str(manifest_path), "--output", str(out_path)], tmp_path)
        assert result.returncode == 0
        assert out_path.exists()
        assert "[global]" in out_path.read_text()

    def test_passphrase_warning_on_stderr(self, tmp_path):
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(_manifest()))
        result = self._run(["--manifest", str(manifest_path)], tmp_path)
        assert result.returncode == 0
        assert "PASSPHRASE" in result.stderr or "passphrase" in result.stderr.lower()
