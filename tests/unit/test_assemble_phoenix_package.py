#!/usr/bin/env python3
"""Tests for Phase 9.T — Phoenix package assembler.

Also covers pack_state() / read_phoenix_manifest() (--pack / --list CLI additions).
"""

import io
import json
import sys
import tarfile
import tempfile
import unittest
import warnings
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "proxmox-bootstrap"))

from assemble_phoenix_package import (
    assemble_phoenix_package,
    package_contents,
    package_name,
    pack_state,
    read_phoenix_manifest,
    _CHECKPOINT_SH,
    _load_version_from,
)

_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _playbook(
    cell_id: str = "cell-alpha",
    hostname: str = "pve01",
    scope: str = "full",
    n_waves: int = 2,
) -> dict:
    waves = [
        {
            "wave": i,
            "name": f"wave{i}",
            "description": f"Wave {i} description",
            "estimated_minutes": 10,
            "prerequisites": [],
            "steps": [
                {"id": f"{i}.1", "action": f"step {i}.1", "commands": ["echo done"], "on_failure": "abort"},
            ],
        }
        for i in range(n_waves)
    ]
    return {
        "cell_id": cell_id,
        "target_node": {"hostname": hostname, "role": "hatchery"},
        "restoration_scope": scope,
        "waves": waves,
        "estimated_total_minutes": n_waves * 10,
        "generated_at": "2026-06-01T12:00:00Z",
        "validation_checklist": ["Cluster healthy", "VMs running"],
    }


class TestPackageName(unittest.TestCase):
    def test_contains_cell_id(self):
        name = package_name(_playbook(cell_id="cell-alpha"), _NOW)
        self.assertIn("cell-alpha", name)

    def test_contains_hostname(self):
        name = package_name(_playbook(hostname="pve01"), _NOW)
        self.assertIn("pve01", name)

    def test_contains_timestamp(self):
        name = package_name(_playbook(), _NOW)
        self.assertIn("2026-06-01", name)

    def test_ends_with_tar_gz(self):
        name = package_name(_playbook())
        self.assertTrue(name.endswith(".tar.gz"))

    def test_starts_with_phoenix_package(self):
        name = package_name(_playbook())
        self.assertTrue(name.startswith("phoenix-package-"))

    def test_unknown_fallback(self):
        name = package_name({}, _NOW)
        self.assertIn("unknown-cell", name)
        self.assertIn("unknown", name)


class TestCheckpointLibrary(unittest.TestCase):
    def test_checkpoint_sh_has_done(self):
        self.assertIn("checkpoint_done", _CHECKPOINT_SH)

    def test_checkpoint_sh_has_start(self):
        self.assertIn("checkpoint_start", _CHECKPOINT_SH)

    def test_checkpoint_sh_has_is_done(self):
        self.assertIn("is_done", _CHECKPOINT_SH)


class TestAssembleBasicContents(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.pkg = assemble_phoenix_package(
            playbook=_playbook(n_waves=2),
            output_dir=tmp,
            now=_NOW,
        )
        self.contents = package_contents(self.pkg)

    def tearDown(self):
        self._tmp.cleanup()

    def test_pkg_exists(self):
        self.assertTrue(self.pkg.exists())

    def test_is_tar_gz(self):
        self.assertTrue(tarfile.is_tarfile(str(self.pkg)))

    def test_contains_playbook_json(self):
        self.assertIn("phoenix-playbook.json", self.contents)

    def test_contains_run_all_sh(self):
        self.assertIn("run-all.sh", self.contents)

    def test_contains_checkpoint_sh(self):
        self.assertIn("lib/checkpoint.sh", self.contents)

    def test_contains_wave_scripts(self):
        wave_scripts = [n for n in self.contents if n.startswith("phase-")]
        self.assertEqual(len(wave_scripts), 2)

    def test_contains_manifest_html(self):
        html_files = [n for n in self.contents if n.endswith(".html")]
        self.assertTrue(html_files, "Expected at least one HTML file in package")

    def test_playbook_json_content_correct(self):
        with tarfile.open(str(self.pkg), "r:gz") as tar:
            data = tar.extractfile("phoenix-playbook.json").read()
        loaded = json.loads(data)
        self.assertEqual(loaded["cell_id"], "cell-alpha")

    def test_no_kdbx_by_default(self):
        self.assertFalse(any(".kdbx" in n for n in self.contents))


class TestAssembleWithKdbx(unittest.TestCase):
    def test_embed_kdbx(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            kdbx = tmp / "test.kdbx"
            kdbx.write_bytes(b"fake kdbx content")
            pkg = assemble_phoenix_package(
                playbook=_playbook(),
                output_dir=tmp,
                kdbx_path=kdbx,
                now=_NOW,
            )
            contents = package_contents(pkg)
        self.assertTrue(any(".kdbx" in n for n in contents))

    def test_missing_kdbx_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg = assemble_phoenix_package(
                playbook=_playbook(),
                output_dir=Path(tmpdir),
                kdbx_path=Path("/nonexistent/path.kdbx"),
                now=_NOW,
            )
            contents = package_contents(pkg)
        self.assertFalse(any(".kdbx" in n for n in contents))


class TestPackageNaming(unittest.TestCase):
    def test_different_cells_produce_different_names(self):
        name1 = package_name(_playbook(cell_id="cell-a"), _NOW)
        name2 = package_name(_playbook(cell_id="cell-b"), _NOW)
        self.assertNotEqual(name1, name2)

    def test_different_hosts_produce_different_names(self):
        name1 = package_name(_playbook(hostname="pve01"), _NOW)
        name2 = package_name(_playbook(hostname="pve02"), _NOW)
        self.assertNotEqual(name1, name2)

    def test_output_in_output_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg = assemble_phoenix_package(
                playbook=_playbook(),
                output_dir=Path(tmpdir),
                now=_NOW,
            )
        self.assertEqual(str(pkg.parent), tmpdir)


class TestWaveScripts(unittest.TestCase):
    def test_wave_script_named_correctly(self):
        pb = _playbook(n_waves=1)
        pb["waves"][0]["name"] = "network"
        pb["waves"][0]["wave"] = 0
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg = assemble_phoenix_package(
                playbook=pb,
                output_dir=Path(tmpdir),
                now=_NOW,
            )
            contents = package_contents(pkg)
        self.assertTrue(
            any("phase-0-network" in n for n in contents),
            f"Expected wave script in {contents}",
        )

    def test_run_all_sh_references_waves(self):
        pb = _playbook(n_waves=2)
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg = assemble_phoenix_package(
                playbook=pb,
                output_dir=Path(tmpdir),
                now=_NOW,
            )
            with tarfile.open(str(pkg), "r:gz") as tar:
                content = tar.extractfile("run-all.sh").read().decode()
        self.assertIn("Wave", content)


if __name__ == "__main__":
    unittest.main()


class TestPhoenixKeepassGate:
    def test_keepass_gate_included(self):
        import tempfile
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg = assemble_phoenix_package(
                playbook=_playbook(n_waves=1),
                output_dir=Path(tmpdir),
                now=datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
            )
            contents = package_contents(pkg)
        assert "lib/phoenix-keepass-gate.sh" in contents

    def test_run_all_sh_sources_gate(self):
        import tempfile, tarfile
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg = assemble_phoenix_package(
                playbook=_playbook(n_waves=1),
                output_dir=Path(tmpdir),
                now=datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
            )
            with tarfile.open(str(pkg), "r:gz") as tar:
                content = tar.extractfile("run-all.sh").read().decode()
        assert "phoenix-keepass-gate.sh" in content
        assert "phoenix_keepass_gate" in content


class TestPhoenixWorkbook:
    def test_workbook_html_included(self):
        import tempfile
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg = assemble_phoenix_package(
                playbook=_playbook(n_waves=1),
                output_dir=Path(tmpdir),
                now=datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
            )
            contents = package_contents(pkg)
        assert "phoenix-workbook.html" in contents


# ===========================================================================
# pack_state() / read_phoenix_manifest() — current-state pack CLI tests
# ===========================================================================

_PACK_NOW = datetime(2026, 6, 9, 12, 0, 0, tzinfo=timezone.utc)


def _make_fake_repo(tmp: Path) -> Path:
    """Create a minimal fake repo layout for pack_state() tests."""
    (tmp / "proxmox-bootstrap").mkdir(exist_ok=True)
    (tmp / "proxmox-bootstrap" / "version.py").write_text(
        'SCHEMA_VERSION: str = "2026-06-09_00-00-00_0000000"\n',
        encoding="utf-8",
    )
    (tmp / "proxmox-bootstrap" / "package-descriptor.json").write_text(
        '{"package_hash": "abc123"}\n', encoding="utf-8"
    )
    (tmp / "proxmox-bootstrap" / "state-descriptor.json").write_text(
        '{"state_hash": "def456"}\n', encoding="utf-8"
    )
    (tmp / "migrations").mkdir(exist_ok=True)
    (tmp / "migrations" / "migrate_initial__to__v1.py").write_text(
        "# migration\n", encoding="utf-8"
    )
    return tmp


def _make_fake_state_dir(tmp: Path, subdir: str = "state") -> Path:
    """Create a fake state directory with manifest.toml and bootstrap-state.json."""
    state = tmp / subdir
    state.mkdir(exist_ok=True)
    (state / "manifest.toml").write_text('[deployment]\ncell_id = "test"\n', encoding="utf-8")
    (state / "bootstrap-state.json").write_text('{"schema_version": "v1"}\n', encoding="utf-8")
    return state


class TestPackState(unittest.TestCase):
    """pack_state() creates a valid .tar.gz with all expected members."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.repo_root = _make_fake_repo(self.tmp)
        self.state_dir = _make_fake_state_dir(self.tmp)
        self.output = self.tmp / "out" / "2026-06-09_12-00-00.tar.gz"

    def tearDown(self):
        self._td.cleanup()

    def _pack(self) -> Path:
        return pack_state(
            state_dir=self.state_dir,
            output=self.output,
            repo_root=self.repo_root,
            now=_PACK_NOW,
        )

    def test_returns_the_output_path(self):
        result = self._pack()
        self.assertEqual(result, self.output)

    def test_creates_a_tar_gz(self):
        self._pack()
        self.assertTrue(self.output.exists(), "tar.gz was not created")
        self.assertTrue(tarfile.is_tarfile(str(self.output)))

    def test_expected_members_present(self):
        self._pack()
        members = set(tarfile.open(str(self.output), "r:gz").getnames())
        expected = {
            "phoenix-manifest.json",
            "manifest.toml",
            "bootstrap-state.json",
            "package-descriptor.json",
            "state-descriptor.json",
            "proxmox-bootstrap/version.py",
            "migrations/migrate_initial__to__v1.py",
        }
        self.assertTrue(
            expected.issubset(members),
            f"Missing members: {expected - members}",
        )

    def test_parent_dirs_created_automatically(self):
        nested = self.tmp / "a" / "b" / "c" / "package.tar.gz"
        pack_state(
            state_dir=self.state_dir,
            output=nested,
            repo_root=self.repo_root,
            now=_PACK_NOW,
        )
        self.assertTrue(nested.exists())


class TestPhoenixManifestFields(unittest.TestCase):
    """phoenix-manifest.json inside the package has all required fields."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.repo_root = _make_fake_repo(self.tmp)
        self.state_dir = _make_fake_state_dir(self.tmp)
        self.output = self.tmp / "package.tar.gz"

    def tearDown(self):
        self._td.cleanup()

    def _manifest(self) -> dict:
        pack_state(
            state_dir=self.state_dir,
            output=self.output,
            repo_root=self.repo_root,
            now=_PACK_NOW,
        )
        return read_phoenix_manifest(self.output)

    def test_packed_at_present(self):
        self.assertIn("packed_at", self._manifest())

    def test_packed_at_matches_injected_now(self):
        self.assertEqual(self._manifest()["packed_at"], "2026-06-09T12:00:00Z")

    def test_packed_at_ends_with_z(self):
        ts = self._manifest()["packed_at"]
        self.assertTrue(ts.endswith("Z"), f"packed_at should end with Z: {ts!r}")

    def test_schema_version_present_and_non_empty(self):
        m = self._manifest()
        self.assertIn("schema_version", m)
        self.assertTrue(len(m["schema_version"]) > 0)

    def test_schema_version_from_version_py(self):
        self.assertEqual(
            self._manifest()["schema_version"],
            "2026-06-09_00-00-00_0000000",
        )

    def test_hostname_present_and_non_empty(self):
        m = self._manifest()
        self.assertIn("hostname", m)
        self.assertIsInstance(m["hostname"], str)
        self.assertTrue(len(m["hostname"]) > 0)

    def test_broodforge_version_present(self):
        self.assertIn("broodforge_version", self._manifest())

    def test_broodforge_version_matches_schema_version(self):
        m = self._manifest()
        self.assertEqual(m["broodforge_version"], m["schema_version"])


class TestReadPhoenixManifest(unittest.TestCase):
    """read_phoenix_manifest() reads back the manifest written by pack_state()."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.repo_root = _make_fake_repo(self.tmp)
        self.state_dir = _make_fake_state_dir(self.tmp)
        self.output = self.tmp / "test-package.tar.gz"

    def tearDown(self):
        self._td.cleanup()

    def test_roundtrip(self):
        pack_state(
            state_dir=self.state_dir,
            output=self.output,
            repo_root=self.repo_root,
            now=_PACK_NOW,
        )
        manifest = read_phoenix_manifest(self.output)
        self.assertIsInstance(manifest, dict)
        self.assertEqual(manifest["packed_at"], "2026-06-09T12:00:00Z")

    def test_missing_manifest_member_raises(self):
        """Raises KeyError when phoenix-manifest.json is absent from the archive."""
        pkg_path = self.tmp / "no-manifest.tar.gz"
        with tarfile.open(str(pkg_path), "w:gz") as tar:
            data = b"hello"
            info = tarfile.TarInfo(name="other-file.txt")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        with self.assertRaises(KeyError):
            read_phoenix_manifest(pkg_path)

    def test_corrupt_json_raises(self):
        """Raises json.JSONDecodeError when the manifest contains invalid JSON."""
        pkg_path = self.tmp / "corrupt.tar.gz"
        with tarfile.open(str(pkg_path), "w:gz") as tar:
            data = b"not-json"
            info = tarfile.TarInfo(name="phoenix-manifest.json")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        with self.assertRaises((json.JSONDecodeError, ValueError)):
            read_phoenix_manifest(pkg_path)


class TestMissingStateFiles(unittest.TestCase):
    """Missing optional state files are skipped with a warning, not a fatal error."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.repo_root = _make_fake_repo(self.tmp)
        self.output = self.tmp / "package.tar.gz"

    def tearDown(self):
        self._td.cleanup()

    def _pack_with_capture(self, state_dir: Path) -> tuple:
        """Pack and capture stderr WARNING lines."""
        captured: list[str] = []
        old_stderr = sys.stderr

        class _Capture(io.StringIO):
            def write(self_, s: str) -> int:  # noqa: N805
                if "[pack] WARNING" in s:
                    captured.append(s.strip())
                return super().write(s)

        sys.stderr = _Capture()
        try:
            pkg = pack_state(
                state_dir=state_dir,
                output=self.output,
                repo_root=self.repo_root,
                now=_PACK_NOW,
            )
        finally:
            sys.stderr = old_stderr
        return pkg, captured

    def test_pack_succeeds_with_empty_state_dir(self):
        empty_state = self.tmp / "empty"
        empty_state.mkdir()
        pkg, _ = self._pack_with_capture(empty_state)
        self.assertTrue(pkg.exists())
        self.assertTrue(tarfile.is_tarfile(str(pkg)))

    def test_warning_for_missing_manifest_toml(self):
        empty_state = self.tmp / "empty2"
        empty_state.mkdir()
        _, warnings_list = self._pack_with_capture(empty_state)
        self.assertTrue(
            any("manifest.toml" in w for w in warnings_list),
            f"Expected warning about manifest.toml; got: {warnings_list}",
        )

    def test_warning_for_missing_bootstrap_state(self):
        empty_state = self.tmp / "empty3"
        empty_state.mkdir()
        _, warnings_list = self._pack_with_capture(empty_state)
        self.assertTrue(
            any("bootstrap-state.json" in w for w in warnings_list),
            f"Expected warning about bootstrap-state.json; got: {warnings_list}",
        )

    def test_phoenix_manifest_present_even_when_state_missing(self):
        empty_state = self.tmp / "empty4"
        empty_state.mkdir()
        pkg, _ = self._pack_with_capture(empty_state)
        manifest = read_phoenix_manifest(pkg)
        self.assertIn("packed_at", manifest)

    def test_missing_migrations_dir_is_non_fatal(self):
        import shutil
        shutil.rmtree(self.repo_root / "migrations")
        state = self.tmp / "state_nomig"
        state.mkdir()
        output = self.tmp / "no-migrations.tar.gz"
        # Should complete without raising
        pack_state(
            state_dir=state,
            output=output,
            repo_root=self.repo_root,
            now=_PACK_NOW,
        )
        self.assertTrue(output.exists())

    def test_missing_version_py_uses_fallback(self):
        """version.py absent → fallback zeroed version, no crash."""
        (self.repo_root / "proxmox-bootstrap" / "version.py").unlink()
        state = self.tmp / "state_nover"
        state.mkdir()
        output = self.tmp / "no-version.tar.gz"
        with warnings.catch_warnings(record=True):
            pack_state(
                state_dir=state,
                output=output,
                repo_root=self.repo_root,
                now=_PACK_NOW,
            )
        manifest = read_phoenix_manifest(output)
        self.assertIn("schema_version", manifest)
        self.assertIn("0000", manifest["schema_version"])


class TestLoadVersionFrom(unittest.TestCase):
    """_load_version_from() loads SCHEMA_VERSION or returns a safe fallback."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_loads_correct_value(self):
        vpy = self.tmp / "version.py"
        vpy.write_text('SCHEMA_VERSION: str = "2026-01-01_00-00-00_abc1234"\n')
        self.assertEqual(_load_version_from(vpy), "2026-01-01_00-00-00_abc1234")

    def test_returns_fallback_when_file_missing(self):
        result = _load_version_from(self.tmp / "nonexistent.py")
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)
        self.assertIn("0000", result)

    def test_returns_fallback_when_attribute_missing(self):
        vpy = self.tmp / "empty_version.py"
        vpy.write_text("# no SCHEMA_VERSION here\n")
        with warnings.catch_warnings(record=True):
            result = _load_version_from(vpy)
        self.assertIsInstance(result, str)
        self.assertIn("0000", result)
