"""
tests/unit/test_forge_sync_lib.py — Unit tests for lib/forge-sync-lib.py

Test groups:
  TestPathHelpers      — split_entry_path / split_group_path (always run; no pykeepass)
  TestMainNoPykeepass  — main() returns 2 when pykeepass unavailable (mock-based)
  TestSyncEntry        — sync_entry() with real kdbx files   (skip if no pykeepass)
  TestSyncGroup        — sync_group() with real kdbx files   (skip if no pykeepass)
  TestDryRun           — dry_run flag makes no file changes   (skip if no pykeepass)
"""

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Load forge-sync-lib.py (hyphenated name — cannot use plain import)
# ---------------------------------------------------------------------------

_LIB_PATH = Path(__file__).resolve().parents[2] / "lib" / "forge-sync-lib.py"

def _load_module(name="forge_sync_lib"):
    spec = importlib.util.spec_from_file_location(name, _LIB_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_mod = _load_module()

# Probe pykeepass availability
try:
    from pykeepass import PyKeePass as _PyKeePass  # type: ignore
    try:
        from pykeepass import create_database as _create_database  # type: ignore
    except ImportError:
        # Older pykeepass — fall back to constructor trick
        def _create_database(path, password):
            import pykeepass
            kp = pykeepass.PyKeePass.__new__(pykeepass.PyKeePass)
            kp._filepath = path
            kp._password = password
            kp._keyfile = None
            import libkeepass  # noqa
            raise ImportError("create_database not available")
    _PYKEEPASS_AVAILABLE = True
except ImportError:
    _PYKEEPASS_AVAILABLE = False

SKIP_IF_NO_PYKEEPASS = unittest.skipUnless(
    _PYKEEPASS_AVAILABLE, "pykeepass not installed (pip install pykeepass)"
)


# ---------------------------------------------------------------------------
# Helpers for integration tests
# ---------------------------------------------------------------------------

def _make_db(path: str, password: str) -> "_PyKeePass":
    """Create a fresh kdbx database at path with given password."""
    return _create_database(path, password=password)


def _open_db(path: str, password: str) -> "_PyKeePass":
    return _PyKeePass(path, password=password)


# ---------------------------------------------------------------------------
# TestPathHelpers — pure logic, no pykeepass dependency
# ---------------------------------------------------------------------------

class TestSplitEntryPath(unittest.TestCase):

    def test_simple_two_parts(self):
        groups, title = _mod.split_entry_path("Group/Title")
        self.assertEqual(groups, ["Group"])
        self.assertEqual(title, "Title")

    def test_nested_three_parts(self):
        groups, title = _mod.split_entry_path("A/B/Title")
        self.assertEqual(groups, ["A", "B"])
        self.assertEqual(title, "Title")

    def test_deep_path(self):
        groups, title = _mod.split_entry_path("Broodforge/services/restic/repo-password")
        self.assertEqual(groups, ["Broodforge", "services", "restic"])
        self.assertEqual(title, "repo-password")

    def test_single_component(self):
        groups, title = _mod.split_entry_path("JustTitle")
        self.assertEqual(groups, [])
        self.assertEqual(title, "JustTitle")

    def test_strips_leading_trailing_slashes(self):
        groups, title = _mod.split_entry_path("/Group/Title/")
        self.assertEqual(groups, ["Group"])
        self.assertEqual(title, "Title")

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            _mod.split_entry_path("")

    def test_only_slashes_raises(self):
        with self.assertRaises(ValueError):
            _mod.split_entry_path("///")


class TestSplitGroupPath(unittest.TestCase):

    def test_single(self):
        self.assertEqual(_mod.split_group_path("Group"), ["Group"])

    def test_nested(self):
        self.assertEqual(_mod.split_group_path("A/B/C"), ["A", "B", "C"])

    def test_strips_slashes(self):
        self.assertEqual(_mod.split_group_path("/Group/Sub/"), ["Group", "Sub"])

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            _mod.split_group_path("")


# ---------------------------------------------------------------------------
# TestMainNoPykeepass — returns 2 when pykeepass not importable
# ---------------------------------------------------------------------------

class TestMainNoPykeepass(unittest.TestCase):

    def test_returns_2_when_pykeepass_missing(self):
        """main() must exit 2 (not crash) when pykeepass is absent."""
        mod = _load_module("forge_sync_lib_no_pk")
        # Patch _PYKEEPASS_AVAILABLE to False
        original = mod._PYKEEPASS_AVAILABLE
        mod._PYKEEPASS_AVAILABLE = False
        try:
            rc = mod.main([
                "--master", "x.kdbx",
                "--child",  "y.kdbx",
                "--entry",  "Group/title",
            ])
            self.assertEqual(rc, 2)
        finally:
            mod._PYKEEPASS_AVAILABLE = original


# ---------------------------------------------------------------------------
# Integration tests — require pykeepass
# ---------------------------------------------------------------------------

@SKIP_IF_NO_PYKEEPASS
class TestSyncEntry(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        d = self._tmp.name
        self.master_path = os.path.join(d, "master.kdbx")
        self.child_path  = os.path.join(d, "child.kdbx")
        self.master_pw   = "master-pw"
        self.child_pw    = "child-pw"

        # Master: Broodforge/services/restic/repo-password
        master = _make_db(self.master_path, self.master_pw)
        bf = master.add_group(master.root_group, "Broodforge")
        svc = master.add_group(bf, "services")
        restic = master.add_group(svc, "restic")
        master.add_entry(restic, "repo-password", "broodforge", "secret-v1")
        master.save()

        # Child: empty
        _make_db(self.child_path, self.child_pw).save()

    def tearDown(self):
        self._tmp.cleanup()

    def test_sync_adds_new_entry(self):
        rc = _mod.sync_entry(
            self.master_path, self.master_pw,
            self.child_path,  self.child_pw,
            "Broodforge/services/restic/repo-password",
        )
        self.assertEqual(rc, 0)

        child = _open_db(self.child_path, self.child_pw)
        grp = child.root_group
        for part in ["Broodforge", "services", "restic"]:
            grp = next((g for g in grp.subgroups if g.name == part), None)
            self.assertIsNotNone(grp, f"group '{part}' missing in child")
        entry = next((e for e in grp.entries if e.title == "repo-password"), None)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.password, "secret-v1")

    def test_sync_updates_existing_entry(self):
        # Pre-populate child with old password
        child = _open_db(self.child_path, self.child_pw)
        bf = child.add_group(child.root_group, "Broodforge")
        svc = child.add_group(bf, "services")
        restic = child.add_group(svc, "restic")
        child.add_entry(restic, "repo-password", "broodforge", "old-secret")
        child.save()

        rc = _mod.sync_entry(
            self.master_path, self.master_pw,
            self.child_path,  self.child_pw,
            "Broodforge/services/restic/repo-password",
        )
        self.assertEqual(rc, 0)

        child2 = _open_db(self.child_path, self.child_pw)
        bf = next(g for g in child2.root_group.subgroups if g.name == "Broodforge")
        svc = next(g for g in bf.subgroups if g.name == "services")
        restic = next(g for g in svc.subgroups if g.name == "restic")
        entry = next(e for e in restic.entries if e.title == "repo-password")
        self.assertEqual(entry.password, "secret-v1")

    def test_missing_entry_in_master_returns_1(self):
        rc = _mod.sync_entry(
            self.master_path, self.master_pw,
            self.child_path,  self.child_pw,
            "Broodforge/services/nonexistent/entry",
        )
        self.assertEqual(rc, 1)

    def test_wrong_master_password_returns_1(self):
        rc = _mod.sync_entry(
            self.master_path, "WRONG",
            self.child_path,  self.child_pw,
            "Broodforge/services/restic/repo-password",
        )
        self.assertEqual(rc, 1)

    def test_wrong_child_password_returns_1(self):
        rc = _mod.sync_entry(
            self.master_path, self.master_pw,
            self.child_path,  "WRONG",
            "Broodforge/services/restic/repo-password",
        )
        self.assertEqual(rc, 1)


@SKIP_IF_NO_PYKEEPASS
class TestSyncGroup(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        d = self._tmp.name
        self.master_path = os.path.join(d, "master.kdbx")
        self.child_path  = os.path.join(d, "child.kdbx")
        self.master_pw   = "master-pw"
        self.child_pw    = "child-pw"

        master = _make_db(self.master_path, self.master_pw)
        bf = master.add_group(master.root_group, "Broodforge")
        svc = master.add_group(bf, "services")
        restic = master.add_group(svc, "restic")
        master.add_entry(restic, "repo-password", "broodforge", "restic-secret")
        headscale = master.add_group(svc, "headscale")
        master.add_entry(headscale, "api-key", "broodforge", "headscale-secret")
        master.save()

        _make_db(self.child_path, self.child_pw).save()

    def tearDown(self):
        self._tmp.cleanup()

    def test_sync_group_copies_all_entries(self):
        rc = _mod.sync_group(
            self.master_path, self.master_pw,
            self.child_path,  self.child_pw,
            "Broodforge/services",
        )
        self.assertEqual(rc, 0)

        child = _open_db(self.child_path, self.child_pw)
        bf = next(g for g in child.root_group.subgroups if g.name == "Broodforge")
        svc = next(g for g in bf.subgroups if g.name == "services")
        restic = next(g for g in svc.subgroups if g.name == "restic")
        hs = next(g for g in svc.subgroups if g.name == "headscale")
        self.assertEqual(restic.entries[0].password, "restic-secret")
        self.assertEqual(hs.entries[0].password, "headscale-secret")

    def test_missing_group_in_master_returns_1(self):
        rc = _mod.sync_group(
            self.master_path, self.master_pw,
            self.child_path,  self.child_pw,
            "Broodforge/nonexistent",
        )
        self.assertEqual(rc, 1)


@SKIP_IF_NO_PYKEEPASS
class TestDryRun(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        d = self._tmp.name
        self.master_path = os.path.join(d, "master.kdbx")
        self.child_path  = os.path.join(d, "child.kdbx")
        self.master_pw   = "master-pw"
        self.child_pw    = "child-pw"

        master = _make_db(self.master_path, self.master_pw)
        restic = master.add_group(master.root_group, "restic")
        master.add_entry(restic, "repo-password", "broodforge", "secret")
        master.save()

        _make_db(self.child_path, self.child_pw).save()

    def tearDown(self):
        self._tmp.cleanup()

    def test_dry_run_makes_no_changes(self):
        # Record child mtime before
        mtime_before = os.path.getmtime(self.child_path)

        rc = _mod.sync_entry(
            self.master_path, self.master_pw,
            self.child_path,  self.child_pw,
            "restic/repo-password",
            dry_run=True,
        )
        self.assertEqual(rc, 0)

        # Child file must not have been modified
        mtime_after = os.path.getmtime(self.child_path)
        self.assertEqual(mtime_before, mtime_after)

        # Entry must not exist in child
        child = _open_db(self.child_path, self.child_pw)
        entries = child.find_entries(title="repo-password")
        self.assertEqual(entries, [] if entries is not None else [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
