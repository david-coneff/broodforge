"""
Tests for backup.py — external backup utilities.

Tests filename generation, archive creation, parsing, listing, pruning,
and encryption detection. GPG encryption tests only run when gpg is available.

Run: py -3 tests/unit/test_backup.py
"""

import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
BOOTSTRAP_REPO = REPO_ROOT / "proxmox-bootstrap"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "bootstrap"


def _import(filename: str, mod_name: str):
    spec = importlib.util.spec_from_file_location(
        mod_name, BOOTSTRAP_REPO / filename
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_fixture() -> dict:
    with open(FIXTURES / "bootstrap-state.json") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Timestamp format
# ---------------------------------------------------------------------------

class TestArchiveTimestamp(unittest.TestCase):
    def setUp(self):
        self.bk = _import("backup.py", "backup")

    def test_format_is_24_hour(self):
        # 14:30:00 should appear as 14 not 02
        dt = datetime(2026, 5, 31, 14, 30, 0, tzinfo=timezone.utc)
        ts = self.bk.archive_timestamp(dt)
        self.assertIn("14", ts)
        self.assertNotIn("2 PM", ts)

    def test_format_matches_spec(self):
        dt = datetime(2026, 5, 31, 14, 30, 0, tzinfo=timezone.utc)
        ts = self.bk.archive_timestamp(dt)
        self.assertEqual(ts, "2026-05-31_14_30_00")

    def test_midnight(self):
        dt = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        ts = self.bk.archive_timestamp(dt)
        self.assertEqual(ts, "2026-01-01_00_00_00")

    def test_end_of_day(self):
        dt = datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
        ts = self.bk.archive_timestamp(dt)
        self.assertEqual(ts, "2026-12-31_23_59_59")

    def test_defaults_to_now(self):
        ts = self.bk.archive_timestamp()
        self.assertIsInstance(ts, str)
        self.assertRegex(ts, r"^\d{4}-\d{2}-\d{2}_\d{2}_\d{2}_\d{2}$")

    def test_underscores_not_colons(self):
        ts = self.bk.archive_timestamp(datetime(2026, 5, 31, 14, 30, 0, tzinfo=timezone.utc))
        self.assertNotIn(":", ts)


# ---------------------------------------------------------------------------
# Short hash
# ---------------------------------------------------------------------------

class TestArchiveHash(unittest.TestCase):
    def setUp(self):
        self.bk = _import("backup.py", "backup")

    def test_returns_6_hex_chars(self):
        h = self.bk.archive_hash("proxmox-cell-a", "2026-05-31_14_30_00")
        self.assertEqual(len(h), 6)
        self.assertRegex(h, r"^[0-9a-f]{6}$")

    def test_deterministic(self):
        h1 = self.bk.archive_hash("proxmox-cell-a", "2026-05-31_14_30_00")
        h2 = self.bk.archive_hash("proxmox-cell-a", "2026-05-31_14_30_00")
        self.assertEqual(h1, h2)

    def test_different_cell_ids_produce_different_hashes(self):
        h1 = self.bk.archive_hash("cell-a", "2026-05-31_14_30_00")
        h2 = self.bk.archive_hash("cell-b", "2026-05-31_14_30_00")
        self.assertNotEqual(h1, h2)

    def test_different_timestamps_produce_different_hashes(self):
        h1 = self.bk.archive_hash("cell-a", "2026-05-31_14_30_00")
        h2 = self.bk.archive_hash("cell-a", "2026-05-31_14_30_01")
        self.assertNotEqual(h1, h2)

    def test_empty_inputs_do_not_crash(self):
        h = self.bk.archive_hash("", "")
        self.assertEqual(len(h), 6)


# ---------------------------------------------------------------------------
# Filename generation
# ---------------------------------------------------------------------------

class TestArchiveFilename(unittest.TestCase):
    def setUp(self):
        self.bk = _import("backup.py", "backup")
        self.dt = datetime(2026, 5, 31, 14, 30, 0, tzinfo=timezone.utc)
        self.cell_id = "proxmox-cell-a"

    def _fn(self, **kwargs) -> str:
        return self.bk.archive_filename(self.cell_id, dt=self.dt, **kwargs)

    def test_encrypted_extension(self):
        fn = self._fn(encrypted=True)
        self.assertTrue(fn.endswith(".tar.gz.gpg"))

    def test_unencrypted_extension(self):
        fn = self._fn(encrypted=False)
        self.assertTrue(fn.endswith(".tar.gz"))
        self.assertFalse(fn.endswith(".gpg"))

    def test_contains_cell_id(self):
        fn = self._fn()
        self.assertIn(self.cell_id, fn)

    def test_contains_timestamp(self):
        fn = self._fn()
        self.assertIn("2026-05-31_14_30_00", fn)

    def test_contains_6_char_hash(self):
        fn = self._fn()
        # Last segment before extension should be 6 hex chars
        base = fn.replace(".tar.gz.gpg", "").replace(".tar.gz", "")
        short_hash = base.split("_")[-1]
        self.assertEqual(len(short_hash), 6)
        self.assertRegex(short_hash, r"^[0-9a-f]{6}$")

    def test_deterministic(self):
        fn1 = self._fn()
        fn2 = self._fn()
        self.assertEqual(fn1, fn2)

    def test_different_timestamps_different_names(self):
        dt2 = datetime(2026, 5, 31, 14, 30, 1, tzinfo=timezone.utc)
        fn1 = self._fn()
        fn2 = self.bk.archive_filename(self.cell_id, dt=dt2)
        self.assertNotEqual(fn1, fn2)

    def test_different_cells_different_names(self):
        fn1 = self.bk.archive_filename("cell-a", dt=self.dt)
        fn2 = self.bk.archive_filename("cell-b", dt=self.dt)
        self.assertNotEqual(fn1, fn2)

    def test_prefix_prepended(self):
        fn = self._fn(prefix="test")
        self.assertTrue(fn.startswith("test_"))
        self.assertIn(self.cell_id, fn)

    def test_no_colons_in_filename(self):
        fn = self._fn()
        self.assertNotIn(":", fn)

    def test_no_spaces_in_filename(self):
        fn = self._fn()
        self.assertNotIn(" ", fn)

    def test_filesystem_safe_characters_only(self):
        fn = self._fn()
        # Only alphanumeric, hyphens, underscores, dots should appear
        self.assertRegex(fn, r"^[a-zA-Z0-9\-_\.]+$")


# ---------------------------------------------------------------------------
# Filename parsing
# ---------------------------------------------------------------------------

class TestParseArchiveFilename(unittest.TestCase):
    def setUp(self):
        self.bk = _import("backup.py", "backup")
        self.dt = datetime(2026, 5, 31, 14, 30, 0, tzinfo=timezone.utc)

    def _roundtrip(self, cell_id: str, encrypted: bool = True) -> dict:
        fn = self.bk.archive_filename(cell_id, dt=self.dt, encrypted=encrypted)
        return self.bk.parse_archive_filename(fn)

    def test_parses_encrypted(self):
        result = self._roundtrip("proxmox-cell-a", encrypted=True)
        self.assertIsNotNone(result)
        self.assertTrue(result["encrypted"])

    def test_parses_unencrypted(self):
        result = self._roundtrip("proxmox-cell-a", encrypted=False)
        self.assertIsNotNone(result)
        self.assertFalse(result["encrypted"])

    def test_timestamp_roundtrips(self):
        result = self._roundtrip("proxmox-cell-a")
        self.assertEqual(result["timestamp_str"], "2026-05-31_14_30_00")

    def test_hash_roundtrips(self):
        result = self._roundtrip("proxmox-cell-a")
        expected_hash = self.bk.archive_hash("proxmox-cell-a", "2026-05-31_14_30_00")
        self.assertEqual(result["short_hash"], expected_hash)

    def test_invalid_filename_returns_none(self):
        self.assertIsNone(self.bk.parse_archive_filename("not-a-valid-filename.txt"))
        self.assertIsNone(self.bk.parse_archive_filename("random.tar.gz.gpg"))


# ---------------------------------------------------------------------------
# Archive creation (no encryption — tests tar creation only)
# ---------------------------------------------------------------------------

class TestCreateTarArchive(unittest.TestCase):
    def setUp(self):
        self.bk = _import("backup.py", "backup")

    def test_creates_archive_from_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "src"
            src_dir.mkdir()
            (src_dir / "file1.txt").write_text("hello")
            (src_dir / "file2.json").write_text('{"key": "value"}')

            out_dir = Path(tmpdir) / "out"
            out_dir.mkdir()
            archive_path = out_dir / "test.tar.gz"

            sources = [
                ("file1.txt", src_dir / "file1.txt"),
                ("file2.json", src_dir / "file2.json"),
            ]
            result = self.bk.create_tar_archive(sources, archive_path)

            self.assertTrue(result.exists())
            self.assertGreater(result.stat().st_size, 0)

    def test_archive_contains_expected_files(self):
        import tarfile
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "testfile.txt"
            src.write_text("test content")
            archive_path = Path(tmpdir) / "test.tar.gz"

            self.bk.create_tar_archive([("testfile.txt", src)], archive_path)

            with tarfile.open(archive_path, "r:gz") as tar:
                names = tar.getnames()
            self.assertIn("testfile.txt", names)

    def test_missing_source_skipped_gracefully(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_path = Path(tmpdir) / "test.tar.gz"
            sources = [("nonexistent.txt", Path(tmpdir) / "nonexistent.txt")]
            result = self.bk.create_tar_archive(sources, archive_path)
            self.assertTrue(result.exists())  # archive created even if empty

    def test_directory_included(self):
        import tarfile
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "snippets"
            src_dir.mkdir()
            (src_dir / "user-data.yaml").write_text("#cloud-config\nhostname: test")

            archive_path = Path(tmpdir) / "test.tar.gz"
            self.bk.create_tar_archive([("snippets", src_dir)], archive_path)

            with tarfile.open(archive_path, "r:gz") as tar:
                names = tar.getnames()
            self.assertTrue(any("user-data.yaml" in n for n in names))


# ---------------------------------------------------------------------------
# Archive listing and pruning
# ---------------------------------------------------------------------------

class TestArchiveListing(unittest.TestCase):
    def setUp(self):
        self.bk = _import("backup.py", "backup")

    def _make_fake_archive(self, directory: Path, cell_id: str, ts_offset: int = 0) -> Path:
        dt = datetime(2026, 5, 31, 14, ts_offset % 60, 0, tzinfo=timezone.utc)
        fn = self.bk.archive_filename(cell_id, dt=dt, encrypted=True)
        path = directory / fn
        path.write_bytes(b"fake gpg content")
        return path

    def test_lists_archives_for_cell(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            self._make_fake_archive(d, "cell-a", 0)
            self._make_fake_archive(d, "cell-a", 1)
            self._make_fake_archive(d, "cell-b", 0)

            archives = self.bk.list_archives(d, "cell-a")
            self.assertEqual(len(archives), 2)

    def test_excludes_other_cells(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            self._make_fake_archive(d, "cell-a", 0)
            self._make_fake_archive(d, "cell-b", 0)

            archives = self.bk.list_archives(d, "cell-a")
            for a in archives:
                self.assertIn("cell-a", a["filename"])

    def test_sorted_newest_first(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            self._make_fake_archive(d, "cell-a", 0)
            self._make_fake_archive(d, "cell-a", 1)
            self._make_fake_archive(d, "cell-a", 2)

            archives = self.bk.list_archives(d, "cell-a")
            timestamps = [a["timestamp_str"] for a in archives]
            self.assertEqual(timestamps, sorted(timestamps, reverse=True))

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            archives = self.bk.list_archives(Path(tmpdir), "cell-a")
            self.assertEqual(archives, [])


class TestArchivePruning(unittest.TestCase):
    def setUp(self):
        self.bk = _import("backup.py", "backup")

    def _make_archives(self, directory: Path, cell_id: str, count: int) -> list[Path]:
        paths = []
        for i in range(count):
            dt = datetime(2026, 5, 31, i % 24, i % 60, 0, tzinfo=timezone.utc)
            fn = self.bk.archive_filename(cell_id, dt=dt, encrypted=True)
            path = directory / fn
            path.write_bytes(b"x")
            paths.append(path)
        return paths

    def test_prunes_to_keep_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            self._make_archives(d, "cell-a", 10)
            deleted = self.bk.prune_archives(d, "cell-a", keep_count=3)
            remaining = self.bk.list_archives(d, "cell-a")
            self.assertEqual(len(remaining), 3)
            self.assertEqual(len(deleted), 7)

    def test_prune_keeps_newest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            self._make_archives(d, "cell-a", 5)
            self.bk.prune_archives(d, "cell-a", keep_count=2)
            remaining = self.bk.list_archives(d, "cell-a")
            timestamps = [a["timestamp_str"] for a in remaining]
            self.bk.list_archives(d, "cell-a")
            # Remaining should be sorted newest first
            self.assertEqual(timestamps, sorted(timestamps, reverse=True))

    def test_keep_more_than_exist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            self._make_archives(d, "cell-a", 3)
            deleted = self.bk.prune_archives(d, "cell-a", keep_count=10)
            self.assertEqual(deleted, [])
            remaining = self.bk.list_archives(d, "cell-a")
            self.assertEqual(len(remaining), 3)


# ---------------------------------------------------------------------------
# Schema validation: external_backup in bootstrap-state
# ---------------------------------------------------------------------------

class TestExternalBackupSchema(unittest.TestCase):
    def setUp(self):
        import json

        from validate import SchemaValidator
        with open(REPO_ROOT / "data-model" / "bootstrap-state-schema.json") as f:
            self.schema = json.load(f)
        self.v = SchemaValidator(self.schema)
        self.fixture = _load_fixture()

    def test_fixture_has_external_backup(self):
        self.assertIn("external_backup", self.fixture)

    def test_fixture_validates_with_null_provider(self):
        errors = self.v.validate(self.fixture)
        self.assertEqual(errors, [], msg=f"Fixture validation failed: {errors}")

    def test_github_provider_config(self):
        from copy import deepcopy
        doc = deepcopy(self.fixture)
        doc["external_backup"] = {
            "provider": "github",
            "github": {
                "repos": {
                    "infrastructure": "git@github.com:user/cell-infrastructure.git",
                    "bootstrap": "git@github.com:user/cell-bootstrap.git",
                    "configuration": None,
                    "docs": None,
                    "assessment_history": None,
                },
                "deploy_key_reference": "github-config-deploy-key",
                "github_username": "myuser",
            },
            "encrypted_archive": None,
            "what_is_backed_up": "config repos",
        }
        errors = self.v.validate(doc)
        self.assertEqual(errors, [])

    def test_encrypted_archive_provider_config(self):
        from copy import deepcopy
        doc = deepcopy(self.fixture)
        doc["external_backup"] = {
            "provider": "encrypted-archive",
            "github": None,
            "encrypted_archive": {
                "destination": "gdrive:/backups/cell-a",
                "destination_type": "rclone",
                "passphrase_reference": "backup-encryption-passphrase",
                "schedule": "0 2 * * *",
                "retention_count": 30,
                "filename_prefix": None,
            },
            "what_is_backed_up": "bootstrap state, snippets, docs",
        }
        errors = self.v.validate(doc)
        self.assertEqual(errors, [])

    def test_null_provider_valid(self):
        from copy import deepcopy
        doc = deepcopy(self.fixture)
        doc["external_backup"] = {
            "provider": None,
            "github": None,
            "encrypted_archive": None,
            "what_is_backed_up": None,
        }
        errors = self.v.validate(doc)
        self.assertEqual(errors, [])

    def test_missing_external_backup_fails(self):
        from copy import deepcopy
        doc = deepcopy(self.fixture)
        del doc["external_backup"]
        errors = self.v.validate(doc)
        self.assertTrue(any("external_backup" in e.path for e in errors))

    def test_invalid_provider_fails(self):
        from copy import deepcopy
        doc = deepcopy(self.fixture)
        doc["external_backup"]["provider"] = "dropbox"
        errors = self.v.validate(doc)
        self.assertTrue(len(errors) > 0)


# ---------------------------------------------------------------------------
# GPG availability detection
# ---------------------------------------------------------------------------

class TestToolDetection(unittest.TestCase):
    def setUp(self):
        self.bk = _import("backup.py", "backup")

    def test_gpg_available_returns_bool(self):
        result = self.bk.gpg_available()
        self.assertIsInstance(result, bool)

    def test_rclone_available_returns_bool(self):
        result = self.bk.rclone_available()
        self.assertIsInstance(result, bool)


# ---------------------------------------------------------------------------
# GPG encryption round-trip (only if gpg is installed)
# ---------------------------------------------------------------------------

class TestGPGEncryption(unittest.TestCase):
    def setUp(self):
        self.bk = _import("backup.py", "backup")

    def test_encrypt_decrypt_roundtrip(self):
        if not self.bk.gpg_available():
            self.skipTest("gpg not installed — skipping encryption tests")

        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            src = d / "test.tar.gz"
            src.write_bytes(b"this is test content " * 100)

            encrypted = d / "test.tar.gz.gpg"
            decrypted = d / "test-decrypted.tar.gz"

            passphrase = "test-passphrase-for-unit-tests"

            self.bk.encrypt_archive(src, encrypted, passphrase)
            self.assertTrue(encrypted.exists())
            self.assertGreater(encrypted.stat().st_size, 0)
            self.assertNotEqual(encrypted.read_bytes(), src.read_bytes())

            self.bk.decrypt_archive(encrypted, decrypted, passphrase)
            self.assertEqual(decrypted.read_bytes(), src.read_bytes())

    def test_wrong_passphrase_raises(self):
        if not self.bk.gpg_available():
            self.skipTest("gpg not installed — skipping encryption tests")

        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            src = d / "test.tar.gz"
            src.write_bytes(b"test data")
            encrypted = d / "test.tar.gz.gpg"

            self.bk.encrypt_archive(src, encrypted, "correct-passphrase")

            with self.assertRaises(RuntimeError):
                self.bk.decrypt_archive(encrypted, d / "out.tar.gz", "wrong-passphrase")


if __name__ == "__main__":
    unittest.main(verbosity=2)
