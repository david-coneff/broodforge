"""Unit tests for velero_manager.py — Phase 2.H."""
import json
import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from velero_manager import (
    BackupRecord,
    BackupSchedule,
    BackupStorageLocation,
    VeleroManager,
    VeleroState,
)

FIXED_TS = datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)
def _now():
    return FIXED_TS

@pytest.fixture
def td():
    with tempfile.TemporaryDirectory() as d:
        yield d

@pytest.fixture
def mgr(td):
    return VeleroManager(state_dir=td, now_fn=_now)


class TestBackupStorageLocation:
    def test_roundtrip(self):
        b = BackupStorageLocation(name="default", provider="aws", bucket="my-bucket",
                                   prefix="velero", region="us-east-1", is_default=True)
        assert BackupStorageLocation.from_dict(b.to_dict()) == b

    def test_defaults(self):
        b = BackupStorageLocation(name="x", provider="aws", bucket="b")
        assert b.prefix == ""
        assert b.region == ""
        assert b.is_default is False
        assert b.credential_secret == ""


class TestBackupSchedule:
    def test_roundtrip(self):
        s = BackupSchedule(name="daily", schedule="0 2 * * *", ttl="720h",
                           namespaces=["default", "apps"])
        assert BackupSchedule.from_dict(s.to_dict()) == s

    def test_defaults(self):
        s = BackupSchedule(name="x", schedule="0 * * * *")
        assert s.namespaces == []
        assert s.exclude_namespaces == []
        assert s.include_cluster_resources is True
        assert s.storage_location == "default"
        assert s.ttl == "720h"
        assert s.snapshot_volumes is True


class TestBackupRecord:
    def test_roundtrip(self):
        r = BackupRecord(name="daily-20260610", schedule="daily",
                         phase="Completed", warnings=0, errors=0)
        assert BackupRecord.from_dict(r.to_dict()) == r


class TestVeleroState:
    def test_empty_roundtrip(self):
        s = VeleroState()
        s2 = VeleroState.from_dict(s.to_dict())
        assert s2.deployment.deployed is False
        assert s2.schedules == []
        assert s2.storage_locations == []

    def test_roundtrip_with_content(self):
        s = VeleroState()
        s.schedules.append(BackupSchedule(name="daily", schedule="0 2 * * *"))
        s2 = VeleroState.from_dict(s.to_dict())
        assert len(s2.schedules) == 1
        assert s2.schedules[0].schedule == "0 2 * * *"


class TestVeleroManagerIO:
    def test_load_missing_returns_empty(self, mgr):
        s = mgr.load()
        assert s.deployment.deployed is False

    def test_save_and_load(self, mgr):
        s = mgr.load()
        s.deployment.deployed = True
        s.deployment.provider = "aws"
        mgr.save(s)
        loaded = mgr.load()
        assert loaded.deployment.deployed is True
        assert loaded.deployment.provider == "aws"

    def test_atomic_write(self, mgr):
        mgr.save(VeleroState())
        assert os.path.exists(os.path.join(mgr._state_dir, "velero-state.json"))
        assert not os.path.exists(os.path.join(mgr._state_dir, "velero-state.json.tmp"))


class TestStorageLocationRegistry:
    def test_register_new(self, mgr):
        bsl = mgr.register_storage_location("default", "aws", "my-bucket")
        assert bsl.name == "default"
        assert bsl.registered_at == "2026-06-10T12:00:00Z"
        assert len(mgr.load().storage_locations) == 1

    def test_register_updates_existing(self, mgr):
        mgr.register_storage_location("default", "aws", "old-bucket")
        mgr.register_storage_location("default", "aws", "new-bucket")
        locs = mgr.load().storage_locations
        assert len(locs) == 1
        assert locs[0].bucket == "new-bucket"

    def test_default_flag_exclusive(self, mgr):
        mgr.register_storage_location("a", "aws", "bucket-a", is_default=True)
        mgr.register_storage_location("b", "aws", "bucket-b", is_default=True)
        locs = mgr.load().storage_locations
        defaults = [loc for loc in locs if loc.is_default]
        assert len(defaults) == 1
        assert defaults[0].name == "b"

    def test_dry_run_no_persist(self, mgr):
        mgr.register_storage_location("x", "aws", "bucket", dry_run=True)
        assert mgr.load().storage_locations == []

    def test_register_with_region(self, mgr):
        mgr.register_storage_location("r", "aws", "b", region="eu-west-1")
        assert mgr.load().storage_locations[0].region == "eu-west-1"


class TestScheduleRegistry:
    def test_register_new_schedule(self, mgr):
        s = mgr.register_schedule("daily", "0 2 * * *")
        assert s.name == "daily"
        assert s.schedule == "0 2 * * *"
        assert s.registered_at == "2026-06-10T12:00:00Z"

    def test_register_updates_existing(self, mgr):
        mgr.register_schedule("daily", "0 2 * * *")
        mgr.register_schedule("daily", "0 3 * * *")
        scheds = mgr.load().schedules
        assert len(scheds) == 1
        assert scheds[0].schedule == "0 3 * * *"

    def test_register_with_namespaces(self, mgr):
        mgr.register_schedule("ns-backup", "0 1 * * *", namespaces=["default", "apps"])
        assert mgr.load().schedules[0].namespaces == ["default", "apps"]

    def test_register_with_exclude_namespaces(self, mgr):
        mgr.register_schedule("full", "0 0 * * *", exclude_namespaces=["kube-system"])
        assert mgr.load().schedules[0].exclude_namespaces == ["kube-system"]

    def test_dry_run_no_persist(self, mgr):
        mgr.register_schedule("dry", "0 2 * * *", dry_run=True)
        assert mgr.load().schedules == []


class TestHelmValues:
    def test_aws_values(self, mgr):
        v = mgr.generate_helm_values("aws", "my-bucket", region="us-east-1")
        assert v["configuration"]["provider"] == "aws"
        assert v["configuration"]["backupStorageLocation"]["bucket"] == "my-bucket"
        assert v["configuration"]["backupStorageLocation"]["config"]["region"] == "us-east-1"

    def test_gcp_values(self, mgr):
        v = mgr.generate_helm_values("gcp", "gcp-bucket")
        assert v["configuration"]["provider"] == "gcp"
        plugin_names = [c["name"] for c in v["initContainers"]]
        assert "velero-plugin-for-gcp" in plugin_names

    def test_restic_enabled_by_default(self, mgr):
        v = mgr.generate_helm_values("aws", "bucket")
        assert v["deployRestic"] is True

    def test_restic_disabled(self, mgr):
        v = mgr.generate_helm_values("aws", "bucket", use_restic=False)
        assert v["deployRestic"] is False

    def test_metrics_enabled(self, mgr):
        v = mgr.generate_helm_values("aws", "bucket")
        assert v["metrics"]["enabled"] is True
        assert v["metrics"]["serviceMonitor"]["enabled"] is True

    def test_credential_secret_referenced_not_inlined(self, mgr):
        v = mgr.generate_helm_values("aws", "bucket", credential_secret="my-secret")
        # credentials reference the secret by name only — no literal values
        assert v["credentials"]["existingSecret"] == "my-secret"
        assert "secretKey" not in v["credentials"]
        assert "accessKey" not in v.get("credentials", {})


class TestDeploy:
    def test_records_state_on_success(self, mgr):
        with patch("velero_manager.subprocess.run", return_value=MagicMock(returncode=0)):
            rc = mgr.deploy("aws", "my-bucket", dry_run=False)
        assert rc == 0
        state = mgr.load()
        assert state.deployment.deployed is True
        assert state.deployment.provider == "aws"
        assert state.deployment.deployed_at == "2026-06-10T12:00:00Z"

    def test_dry_run_no_state_change(self, mgr):
        with patch("velero_manager.subprocess.run", return_value=MagicMock(returncode=0)):
            mgr.deploy("aws", "bucket", dry_run=True)
        assert mgr.load().deployment.deployed is False

    def test_failure_no_state_change(self, mgr):
        with patch("velero_manager.subprocess.run", return_value=MagicMock(returncode=1, stderr="")):
            rc = mgr.deploy("aws", "bucket")
        assert rc == 1
        assert mgr.load().deployment.deployed is False

    def test_chart_version_passed(self, mgr):
        calls = []
        def capture(*a, **kw):
            calls.append(list(a[0]))
            return MagicMock(returncode=0)
        with patch("velero_manager.subprocess.run", side_effect=capture):
            mgr.deploy("aws", "bucket", chart_version="6.0.0")
        helm_call = next((c for c in calls if len(c) > 1 and c[0] == "helm"), None)
        assert helm_call and "--version" in helm_call and "6.0.0" in helm_call


class TestListBackups:
    def test_empty_on_error(self, mgr):
        with patch("velero_manager.subprocess.run", return_value=MagicMock(returncode=1, stdout="", stderr="")):
            assert mgr.list_backups() == []

    def test_parses_velero_output(self, mgr):
        fake_output = json.dumps({"items": [{
            "metadata": {"name": "daily-20260610",
                         "labels": {"velero.io/schedule-name": "daily"}},
            "status": {"phase": "Completed", "warnings": 0, "errors": 0,
                       "startTimestamp": "2026-06-10T02:00:00Z",
                       "completionTimestamp": "2026-06-10T02:05:00Z"},
            "spec": {"storageLocation": "default"},
        }]})
        with patch("velero_manager.subprocess.run",
                   return_value=MagicMock(returncode=0, stdout=fake_output)):
            records = mgr.list_backups()
        assert len(records) == 1
        assert records[0].name == "daily-20260610"
        assert records[0].phase == "Completed"
        assert records[0].schedule == "daily"


class TestSyncRecentBackups:
    def test_sync_updates_state(self, mgr):
        fake_output = json.dumps({"items": [
            {"metadata": {"name": f"bk-{i}", "labels": {}},
             "status": {"phase": "Completed", "warnings": 0, "errors": 0},
             "spec": {"storageLocation": "default"}}
            for i in range(3)
        ]})
        with patch("velero_manager.subprocess.run",
                   return_value=MagicMock(returncode=0, stdout=fake_output)):
            n = mgr.sync_recent_backups()
        assert n == 3
        assert len(mgr.load().recent_backups) == 3

    def test_sync_caps_at_max(self, mgr):
        items = [
            {"metadata": {"name": f"bk-{i}", "labels": {}},
             "status": {"phase": "Completed", "warnings": 0, "errors": 0},
             "spec": {"storageLocation": "default"}}
            for i in range(60)
        ]
        fake_output = json.dumps({"items": items})
        with patch("velero_manager.subprocess.run",
                   return_value=MagicMock(returncode=0, stdout=fake_output)):
            mgr.sync_recent_backups()
        assert len(mgr.load().recent_backups) == mgr.MAX_RECENT_BACKUPS


class TestCLI:
    def test_list_empty(self, td):
        from velero_manager import main
        assert main(["--state-dir", td, "list"]) == 0

    def test_register_storage_cli(self, td):
        from velero_manager import main
        rc = main(["--state-dir", td, "register-storage",
                   "--name", "default", "--provider", "aws", "--bucket", "my-bucket",
                   "--region", "us-east-1", "--default"])
        assert rc == 0

    def test_register_schedule_cli(self, td):
        from velero_manager import main
        rc = main(["--state-dir", td, "register-schedule",
                   "--name", "daily", "--schedule", "0 2 * * *",
                   "--ttl", "720h"])
        assert rc == 0

    def test_apply_schedule_missing(self, td):
        from velero_manager import main
        rc = main(["--state-dir", td, "apply-schedule", "--name", "nonexistent"])
        assert rc == 1
