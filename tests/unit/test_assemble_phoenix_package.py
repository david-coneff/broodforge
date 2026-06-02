#!/usr/bin/env python3
"""Tests for Phase 9.T — Phoenix package assembler."""

import json
import sys
import tarfile
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "proxmox-bootstrap"))

from assemble_phoenix_package import (
    assemble_phoenix_package,
    package_contents,
    package_name,
    _CHECKPOINT_SH,
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
