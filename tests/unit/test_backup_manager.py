"""
test_backup_manager.py — Unit tests for backup_manager.py (Phase 1.O CQB).

Tests cover BackupScope inference, BackupManifest round-trip, BackupManager
orchestration, clock injection, and error handling.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock, call

# Ensure proxmox-bootstrap is importable
_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "proxmox-bootstrap"))

from backup_manager import (
    BackupScope,
    BackupManifest,
    BackupScopeInferrer,
    BackupManager,
    _generate_backup_id,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fixed_clock(dt: datetime):
    """Return a callable that always returns dt (clock injection helper)."""
    return lambda: dt


def _make_manager(state_dir: Path, now: datetime = None) -> BackupManager:
    now_fn = _fixed_clock(now or datetime(2026, 6, 9, 14, 30, 22, tzinfo=timezone.utc))
    return BackupManager(state_dir=state_dir, now_fn=now_fn)


def _empty_manifest(backup_id: str = "2026-06-09_14-30-22_abc1234") -> BackupManifest:
    return BackupManifest(
        backup_id=backup_id,
        scope="broodforge-only",
        trigger="operator",
        quiesce_level=0,
        broodforge={"phoenix_package_path": None, "schema_version": "unknown", "state_hash": ""},
        proxmox_host_config=None,
        k8s_snapshots={},
        vm_snapshots={},
        completed_at="2026-06-09T14:30:22Z",
        broodforge_version="unknown",
    )


# ---------------------------------------------------------------------------
# BackupScopeInferrer tests
# ---------------------------------------------------------------------------

class TestBackupScopeInferrer(unittest.TestCase):

    def setUp(self):
        self.inferrer = BackupScopeInferrer()

    def test_infer_scope_broodforge_only(self):
        """affects='broodforge-config' → level 0, no etcd/pvc/vzdump."""
        scope = self.inferrer.infer("broodforge-config")
        self.assertEqual(scope.quiesce_level, 0)
        self.assertTrue(scope.include_broodforge)
        self.assertFalse(scope.include_proxmox_host_config)
        self.assertFalse(scope.k8s_etcd_snapshot)
        self.assertFalse(scope.k8s_pvc_backup)
        self.assertFalse(scope.full_vm_disk_snapshot)
        self.assertEqual(scope.vm_ids, [])

    def test_infer_scope_pod(self):
        """affects='pod:default/nginx' → level 1, etcd+pvc=True, full_vm_disk=False."""
        scope = self.inferrer.infer("pod:default/nginx")
        self.assertEqual(scope.quiesce_level, 1)
        self.assertTrue(scope.k8s_etcd_snapshot)
        self.assertTrue(scope.k8s_pvc_backup)
        self.assertFalse(scope.full_vm_disk_snapshot)
        self.assertFalse(scope.include_proxmox_host_config)

    def test_infer_scope_service(self):
        """affects='service:api' → same as pod (level 1)."""
        scope = self.inferrer.infer("service:api")
        self.assertEqual(scope.quiesce_level, 1)
        self.assertTrue(scope.k8s_etcd_snapshot)
        self.assertTrue(scope.k8s_pvc_backup)
        self.assertFalse(scope.full_vm_disk_snapshot)

    def test_infer_scope_vm(self):
        """affects='vm:100' → level 2, include_proxmox_host_config=True, no vzdump."""
        scope = self.inferrer.infer("vm:100")
        self.assertEqual(scope.quiesce_level, 2)
        self.assertTrue(scope.include_proxmox_host_config)
        self.assertTrue(scope.k8s_etcd_snapshot)
        self.assertTrue(scope.k8s_pvc_backup)
        self.assertFalse(scope.full_vm_disk_snapshot)
        self.assertEqual(scope.vm_ids, [100])

    def test_infer_scope_node(self):
        """affects='node:pve1' → level 2, include_proxmox_host_config=True."""
        scope = self.inferrer.infer("node:pve1")
        self.assertEqual(scope.quiesce_level, 2)
        self.assertTrue(scope.include_proxmox_host_config)
        self.assertFalse(scope.full_vm_disk_snapshot)

    def test_infer_scope_unknown_defaults_to_full(self):
        """affects='unknown' → level 3, full_vm_disk_snapshot=True."""
        scope = self.inferrer.infer("unknown")
        self.assertEqual(scope.quiesce_level, 3)
        self.assertTrue(scope.include_proxmox_host_config)
        self.assertTrue(scope.k8s_etcd_snapshot)
        self.assertTrue(scope.k8s_pvc_backup)
        self.assertTrue(scope.full_vm_disk_snapshot)

    def test_infer_scope_unrecognised_defaults_to_full(self):
        """Any unrecognised affects string → full (safe default)."""
        scope = self.inferrer.infer("something-weird")
        self.assertEqual(scope.quiesce_level, 3)
        self.assertTrue(scope.full_vm_disk_snapshot)

    def test_infer_scope_full_string(self):
        """affects='full' → level 3, full_vm_disk_snapshot=True."""
        scope = self.inferrer.infer("full")
        self.assertEqual(scope.quiesce_level, 3)
        self.assertTrue(scope.full_vm_disk_snapshot)


# ---------------------------------------------------------------------------
# BackupManifest round-trip tests
# ---------------------------------------------------------------------------

class TestBackupManifestRoundtrip(unittest.TestCase):

    def test_backup_manifest_roundtrip(self):
        """JSON serialize/deserialize preserves all fields including k8s_snapshots."""
        original = BackupManifest(
            backup_id="2026-06-09_14-30-22_abc1234",
            scope="full",
            trigger="scheduled",
            quiesce_level=3,
            broodforge={
                "phoenix_package_path": "/var/lib/broodforge/backups/x/phoenix.tar.gz",
                "schema_version": "2026-06-09_00-00-00_0000000",
                "state_hash": "deadbeef",
            },
            proxmox_host_config={"snapshot_id": "abc123", "tag": "broodforge-cqb-x"},
            k8s_snapshots={
                "etcd_snapshot": {"path": "/tmp/etcd.db", "status": "ok"},
                "pvc_restic": {"snapshot_id": "def456", "status": "ok"},
            },
            vm_snapshots={"100": {"status": "ok"}, "101": {"status": "ok"}},
            completed_at="2026-06-09T14:30:22Z",
            broodforge_version="2026-06-09_00-00-00_0000000",
        )

        d = original.to_dict()
        restored = BackupManifest.from_dict(d)

        self.assertEqual(restored.backup_id, original.backup_id)
        self.assertEqual(restored.scope, original.scope)
        self.assertEqual(restored.trigger, original.trigger)
        self.assertEqual(restored.quiesce_level, original.quiesce_level)
        self.assertEqual(restored.broodforge, original.broodforge)
        self.assertEqual(restored.proxmox_host_config, original.proxmox_host_config)
        self.assertEqual(restored.k8s_snapshots, original.k8s_snapshots)
        self.assertEqual(restored.vm_snapshots, original.vm_snapshots)
        self.assertEqual(restored.completed_at, original.completed_at)
        self.assertEqual(restored.broodforge_version, original.broodforge_version)

    def test_manifest_roundtrip_json_file(self):
        """save() / load() preserves all fields via a real file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / "2026-06-09_14-30-22_abc1234"
            backup_dir.mkdir()
            m = _empty_manifest()
            m.k8s_snapshots = {"etcd_snapshot": {"path": "/tmp/snap.db", "status": "ok"}}
            m.save(backup_dir)

            loaded = BackupManifest.load(backup_dir)
            self.assertEqual(loaded.k8s_snapshots["etcd_snapshot"]["path"], "/tmp/snap.db")
            self.assertEqual(loaded.backup_id, m.backup_id)


# ---------------------------------------------------------------------------
# BackupManager tests
# ---------------------------------------------------------------------------

class TestBackupCreatesManifestFile(unittest.TestCase):
    """backup() with real scope writes manifest.json; subprocess calls are mocked."""

    def _mock_subprocess(self):
        """Return a mock subprocess.run that always succeeds."""
        mock = MagicMock()
        mock.return_value.returncode = 0
        mock.return_value.stdout = json.dumps({
            "message_type": "summary",
            "snapshot_id": "abc123456",
        })
        mock.return_value.stderr = ""
        return mock

    def test_backup_creates_manifest_file(self):
        """Backup with broodforge-only scope writes manifest.json to backup_dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            now = datetime(2026, 6, 9, 14, 30, 22, tzinfo=timezone.utc)
            manager = _make_manager(state_dir, now)

            scope = BackupScope(
                quiesce_level=0,
                vm_ids=[],
                include_proxmox_host_config=False,
                k8s_etcd_snapshot=False,
                k8s_pvc_backup=False,
                full_vm_disk_snapshot=False,
            )

            with patch("backup_manager.subprocess.run", self._mock_subprocess()):
                manifest = manager.backup(scope=scope, trigger="operator", dry_run=False)

            # manifest.json must exist
            manifest_path = state_dir / "backups" / manifest.backup_id / "manifest.json"
            self.assertTrue(manifest_path.exists(), f"manifest.json not found at {manifest_path}")

            # Loaded manifest round-trips correctly
            loaded = BackupManifest.load(manifest_path.parent)
            self.assertEqual(loaded.backup_id, manifest.backup_id)
            self.assertEqual(loaded.trigger, "operator")
            self.assertEqual(loaded.quiesce_level, 0)

    def test_backup_dry_run_writes_no_files(self):
        """Dry-run backup returns manifest but writes no files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            manager = _make_manager(state_dir)
            scope = BackupScope(quiesce_level=0, vm_ids=[], k8s_etcd_snapshot=False,
                                k8s_pvc_backup=False, full_vm_disk_snapshot=False)

            manifest = manager.backup(scope=scope, trigger="operator", dry_run=True)
            self.assertIsNotNone(manifest.backup_id)

            # No files should have been created
            backups_dir = state_dir / "backups"
            if backups_dir.exists():
                entries = list(backups_dir.iterdir())
                self.assertEqual(entries, [], "No backup directories should exist after dry-run")


class TestListBackupsSortedNewestFirst(unittest.TestCase):

    def test_list_backups_sorted_newest_first(self):
        """list_backups() returns manifests in descending completed_at order."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            backups_dir = state_dir / "backups"

            timestamps = [
                ("2026-06-09_10-00-00_aaaaaaa", "2026-06-09T10:00:00Z"),
                ("2026-06-09_14-00-00_bbbbbbb", "2026-06-09T14:00:00Z"),
                ("2026-06-09_08-00-00_ccccccc", "2026-06-09T08:00:00Z"),
            ]
            for bid, completed_at in timestamps:
                d = backups_dir / bid
                d.mkdir(parents=True)
                m = _empty_manifest(bid)
                m.completed_at = completed_at
                with open(d / "manifest.json", "w") as f:
                    json.dump(m.to_dict(), f)

            manager = BackupManager(state_dir=state_dir)
            result = manager.list_backups()

            self.assertEqual(len(result), 3)
            # Newest first
            self.assertEqual(result[0].backup_id, "2026-06-09_14-00-00_bbbbbbb")
            self.assertEqual(result[1].backup_id, "2026-06-09_10-00-00_aaaaaaa")
            self.assertEqual(result[2].backup_id, "2026-06-09_08-00-00_ccccccc")

    def test_list_backups_empty(self):
        """list_backups() returns [] when no backups exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = BackupManager(state_dir=Path(tmpdir))
            result = manager.list_backups()
            self.assertEqual(result, [])


class TestRestoreAbortsIfManifestMissing(unittest.TestCase):

    def test_restore_aborts_if_manifest_missing(self):
        """restore() raises FileNotFoundError when the manifest does not exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = BackupManager(state_dir=Path(tmpdir))
            with self.assertRaises(FileNotFoundError):
                manager.restore("nonexistent-backup-id", dry_run=False)

    def test_restore_dry_run_aborts_if_manifest_missing(self):
        """restore() raises FileNotFoundError even in dry-run mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = BackupManager(state_dir=Path(tmpdir))
            with self.assertRaises(FileNotFoundError):
                manager.restore("nonexistent-backup-id", dry_run=True)


class TestBackupIdUsesNowFn(unittest.TestCase):

    def test_backup_id_uses_now_fn(self):
        """backup_id is derived from the injected clock, not a bare datetime.now()."""
        fixed_dt = datetime(2026, 1, 15, 9, 5, 30, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = BackupManager(
                state_dir=Path(tmpdir),
                now_fn=_fixed_clock(fixed_dt),
            )
            scope = BackupScope(
                quiesce_level=0, vm_ids=[],
                k8s_etcd_snapshot=False, k8s_pvc_backup=False, full_vm_disk_snapshot=False,
            )
            with patch("backup_manager.subprocess.run") as mock_run:
                mock_run.return_value.returncode = 0
                mock_run.return_value.stdout = ""
                mock_run.return_value.stderr = ""
                manifest = manager.backup(scope=scope, trigger="operator", dry_run=False)

            # backup_id must start with the fixed date
            self.assertTrue(
                manifest.backup_id.startswith("2026-01-15_09-05-30"),
                f"Expected backup_id to start with '2026-01-15_09-05-30', got: {manifest.backup_id}",
            )

    def test_backup_id_format(self):
        """_generate_backup_id returns YYYY-MM-DD_HH-MM-SS_<7char> format."""
        dt = datetime(2026, 6, 9, 14, 30, 22, tzinfo=timezone.utc)
        bid = _generate_backup_id(dt)
        parts = bid.split("_")
        self.assertEqual(len(parts), 3, f"Expected 3 underscore-separated parts, got: {bid}")
        self.assertEqual(parts[0], "2026-06-09")
        self.assertEqual(parts[1], "14-30-22")
        self.assertEqual(len(parts[2]), 7, f"Expected 7-char hash, got: {parts[2]}")


# ---------------------------------------------------------------------------
# BackupScope dataclass tests
# ---------------------------------------------------------------------------

class TestBackupScope(unittest.TestCase):

    def test_include_broodforge_forced_true(self):
        """Setting include_broodforge=False is silently corrected to True."""
        import warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            scope = BackupScope(include_broodforge=False)
        self.assertTrue(scope.include_broodforge)
        self.assertTrue(any(issubclass(ww.category, UserWarning) for ww in w))

    def test_quiesce_level_2_auto_enables_host_config(self):
        """quiesce_level >= 2 forces include_proxmox_host_config=True."""
        scope = BackupScope(quiesce_level=2, include_proxmox_host_config=False)
        self.assertTrue(scope.include_proxmox_host_config)

    def test_scope_roundtrip(self):
        """to_dict() / from_dict() preserves all Phase 1.O fields."""
        original = BackupScope(
            quiesce_level=1,
            vm_ids=[100, 200],
            k8s_etcd_snapshot=True,
            k8s_pvc_backup=False,
            full_vm_disk_snapshot=False,
        )
        restored = BackupScope.from_dict(original.to_dict())
        self.assertEqual(restored.quiesce_level, 1)
        self.assertEqual(restored.vm_ids, [100, 200])
        self.assertTrue(restored.k8s_etcd_snapshot)
        self.assertFalse(restored.k8s_pvc_backup)
        self.assertFalse(restored.full_vm_disk_snapshot)


if __name__ == "__main__":
    unittest.main()
