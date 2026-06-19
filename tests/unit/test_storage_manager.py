"""
tests/unit/test_storage_manager.py — Unit tests for storage_manager.py (Phase 2.E).
"""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fixed_now():
    return datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)


def _load_module():
    """Import storage_manager from proxmox-bootstrap/ without package install."""
    import importlib.util, pathlib, sys
    here = pathlib.Path(__file__).parent
    mod_path = here.parent.parent / "proxmox-bootstrap" / "storage_manager.py"
    spec = importlib.util.spec_from_file_location("storage_manager", mod_path)
    mod = importlib.util.module_from_spec(spec)       # type: ignore[union-attr]
    sys.modules[spec.name] = mod  # required so @dataclass can resolve cls.__module__
    spec.loader.exec_module(mod)                      # type: ignore[union-attr]
    return mod


sm = _load_module()


# ---------------------------------------------------------------------------
# StorageState / NodeDisk / VolumeRecord dataclass tests
# ---------------------------------------------------------------------------

class TestNodeDisk:
    def test_new_defaults(self):
        d = sm.NodeDisk.new(node="pve01", path="/var/lib/longhorn", now_fn=_fixed_now)
        assert d.node == "pve01"
        assert d.path == "/var/lib/longhorn"
        assert d.disk_type == "filesystem"
        assert d.allow_scheduling is True
        assert d.storage_reserved_mb == sm.DEFAULT_STORAGE_RESERVED_MB
        assert d.tags == []
        assert d.registered_at == "2026-06-10T12:00:00+00:00"

    def test_new_with_tags(self):
        d = sm.NodeDisk.new(
            node="pve02", path="/dev/sdb",
            disk_type="block", tags=["fast", "ssd"],
            now_fn=_fixed_now,
        )
        assert d.disk_type == "block"
        assert "fast" in d.tags
        assert "ssd" in d.tags


class TestVolumeRecord:
    def test_new_defaults(self):
        v = sm.VolumeRecord.new(name="data-pvc", namespace="default", now_fn=_fixed_now)
        assert v.name == "data-pvc"
        assert v.namespace == "default"
        assert v.replica_count == sm.DEFAULT_REPLICA_COUNT
        assert v.size_gi == 10
        assert v.storage_class == "longhorn"
        assert v.healthy is None

    def test_new_custom(self):
        v = sm.VolumeRecord.new(
            name="pg-data", namespace="authentik",
            replica_count=3, size_gi=50,
            storage_class="longhorn-retain",
            now_fn=_fixed_now,
        )
        assert v.replica_count == 3
        assert v.size_gi == 50
        assert v.storage_class == "longhorn-retain"


# ---------------------------------------------------------------------------
# State I/O
# ---------------------------------------------------------------------------

class TestStateIO:
    def test_round_trip_empty(self):
        with tempfile.TemporaryDirectory() as d:
            state = sm.StorageState()
            sm.save_state(state, d)
            loaded = sm.load_state(d)
        assert loaded.schema_version == "1.0"
        assert loaded.node_disks == []
        assert loaded.volumes == []

    def test_round_trip_with_data(self):
        with tempfile.TemporaryDirectory() as d:
            state = sm.StorageState(
                deployed_at="2026-06-10T00:00:00+00:00",
                default_replica_count=3,
            )
            state.node_disks.append(
                sm.NodeDisk.new("pve01", "/var/lib/longhorn", now_fn=_fixed_now)
            )
            state.volumes.append(
                sm.VolumeRecord.new("pg-pvc", "authentik", now_fn=_fixed_now)
            )
            sm.save_state(state, d)
            loaded = sm.load_state(d)
        assert loaded.deployed_at == "2026-06-10T00:00:00+00:00"
        assert loaded.default_replica_count == 3
        assert len(loaded.node_disks) == 1
        assert loaded.node_disks[0].node == "pve01"
        assert len(loaded.volumes) == 1
        assert loaded.volumes[0].name == "pg-pvc"

    def test_atomic_write(self):
        """save_state uses .tmp → rename (atomic write)."""
        with tempfile.TemporaryDirectory() as d:
            state = sm.StorageState()
            sm.save_state(state, d)
            tmp_files = list(Path(d).glob("*.tmp"))
        assert tmp_files == []


# ---------------------------------------------------------------------------
# StorageManager
# ---------------------------------------------------------------------------

class TestStorageManager:
    def test_mark_deployed(self):
        with tempfile.TemporaryDirectory() as d:
            mgr = sm.StorageManager(state_dir=d, now_fn=_fixed_now)
            mgr.mark_deployed(version="1.6.3", default_replica_count=3)
            assert mgr.state.deployed_at == "2026-06-10T12:00:00+00:00"
            assert mgr.state.chart_version == "1.6.3"
            assert mgr.state.default_replica_count == 3

    def test_register_node_disk_new(self):
        with tempfile.TemporaryDirectory() as d:
            mgr = sm.StorageManager(state_dir=d, now_fn=_fixed_now)
            disk = mgr.register_node_disk(
                node="pve01", path="/var/lib/longhorn", tags=["fast"]
            )
            assert disk.node == "pve01"
            assert "fast" in disk.tags
            assert len(mgr.state.node_disks) == 1

    def test_register_node_disk_update(self):
        with tempfile.TemporaryDirectory() as d:
            mgr = sm.StorageManager(state_dir=d, now_fn=_fixed_now)
            mgr.register_node_disk(node="pve01", path="/var/lib/longhorn")
            mgr.register_node_disk(
                node="pve01", path="/var/lib/longhorn", tags=["updated"]
            )
            assert len(mgr.state.node_disks) == 1
            assert "updated" in mgr.state.node_disks[0].tags

    def test_register_node_disk_invalid_type(self):
        with tempfile.TemporaryDirectory() as d:
            mgr = sm.StorageManager(state_dir=d)
            with pytest.raises(sm.StorageError, match="Invalid disk_type"):
                mgr.register_node_disk(node="pve01", path="/dev/sdb", disk_type="nfs")

    def test_list_disks_no_filter(self):
        with tempfile.TemporaryDirectory() as d:
            mgr = sm.StorageManager(state_dir=d, now_fn=_fixed_now)
            mgr.register_node_disk("pve01", "/var/lib/longhorn")
            mgr.register_node_disk("pve02", "/var/lib/longhorn")
            assert len(mgr.list_disks()) == 2

    def test_list_disks_node_filter(self):
        with tempfile.TemporaryDirectory() as d:
            mgr = sm.StorageManager(state_dir=d, now_fn=_fixed_now)
            mgr.register_node_disk("pve01", "/var/lib/longhorn")
            mgr.register_node_disk("pve02", "/var/lib/longhorn")
            assert len(mgr.list_disks(node_filter="pve01")) == 1

    def test_register_volume_new(self):
        with tempfile.TemporaryDirectory() as d:
            mgr = sm.StorageManager(state_dir=d, now_fn=_fixed_now)
            vol = mgr.register_volume("pg-data", "authentik", size_gi=20)
            assert vol.name == "pg-data"
            assert vol.size_gi == 20
            assert len(mgr.state.volumes) == 1

    def test_register_volume_update(self):
        with tempfile.TemporaryDirectory() as d:
            mgr = sm.StorageManager(state_dir=d, now_fn=_fixed_now)
            mgr.register_volume("pg-data", "authentik", replica_count=2)
            mgr.register_volume("pg-data", "authentik", replica_count=3)
            assert len(mgr.state.volumes) == 1
            assert mgr.state.volumes[0].replica_count == 3

    def test_list_volumes_namespace_filter(self):
        with tempfile.TemporaryDirectory() as d:
            mgr = sm.StorageManager(state_dir=d, now_fn=_fixed_now)
            mgr.register_volume("pvc-a", "authentik")
            mgr.register_volume("pvc-b", "nextcloud")
            assert len(mgr.list_volumes(namespace_filter="authentik")) == 1

    def test_set_backup_target(self):
        with tempfile.TemporaryDirectory() as d:
            mgr = sm.StorageManager(state_dir=d, now_fn=_fixed_now)
            mgr.set_backup_target("s3://mybucket/longhorn", "s3")
            assert mgr.state.backup_target == "s3://mybucket/longhorn"
            assert mgr.state.backup_target_type == "s3"

    def test_set_backup_target_invalid_type(self):
        with tempfile.TemporaryDirectory() as d:
            mgr = sm.StorageManager(state_dir=d)
            with pytest.raises(sm.StorageError):
                mgr.set_backup_target("smb://nas/share", "smb")

    def test_summary(self):
        with tempfile.TemporaryDirectory() as d:
            mgr = sm.StorageManager(state_dir=d, now_fn=_fixed_now)
            mgr.mark_deployed(version="1.6.2")
            mgr.register_node_disk("pve01", "/var/lib/longhorn")
            mgr.register_node_disk("pve02", "/var/lib/longhorn")
            mgr.register_volume("pvc-a", "default")
            s = mgr.summary()
        assert s["deployed"] is True
        assert s["version"] == "1.6.2"
        assert s["node_disk_count"] == 2
        assert s["volume_count"] == 1
        assert "pve01" in s["nodes"]
        assert "pve02" in s["nodes"]


# ---------------------------------------------------------------------------
# Helm values / StorageClass generation
# ---------------------------------------------------------------------------

class TestHelmValuesGeneration:
    def test_generate_longhorn_values_contains_replicas(self):
        yaml = sm.generate_longhorn_values_yaml(default_replica_count=3)
        assert "defaultReplicaCount: 3" in yaml

    def test_generate_longhorn_values_backup_target(self):
        yaml = sm.generate_longhorn_values_yaml(
            backup_target="s3://bucket@us-east-1/prefix",
            backup_target_credential_secret="longhorn-s3-secret",
        )
        assert "backupTarget:" in yaml
        assert "s3://bucket@us-east-1/prefix" in yaml
        assert "backupTargetCredentialSecret:" in yaml

    def test_generate_longhorn_values_no_backup_target(self):
        yaml = sm.generate_longhorn_values_yaml()
        assert "backupTarget:" not in yaml

    def test_generate_storage_class_default(self):
        yaml = sm.generate_storage_class_yaml(name="longhorn")
        assert 'name: longhorn' in yaml
        assert "is-default-class" in yaml
        assert '"true"' in yaml
        assert 'numberOfReplicas: "2"' in yaml

    def test_generate_storage_class_not_default(self):
        yaml = sm.generate_storage_class_yaml(name="longhorn-retain", is_default=False)
        assert '"false"' in yaml

    def test_generate_storage_class_retain(self):
        yaml = sm.generate_storage_class_yaml(
            name="longhorn-retain", reclaim_policy="Retain"
        )
        assert "reclaimPolicy: Retain" in yaml

    def test_generate_storage_class_replica_count(self):
        yaml = sm.generate_storage_class_yaml(name="longhorn-3r", replica_count=3)
        assert 'numberOfReplicas: "3"' in yaml


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class TestCLI:
    def test_generate_values_stdout(self, capsys):
        rc = sm.main(["generate-values", "--default-replica-count", "2"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "defaultReplicaCount: 2" in out

    def test_generate_storage_class_stdout(self, capsys):
        rc = sm.main(["generate-storage-class", "--name", "longhorn-test",
                      "--replica-count", "1"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "name: longhorn-test" in out

    def test_mark_deployed(self, tmp_path, capsys):
        rc = sm.main(["--state", str(tmp_path), "mark-deployed", "--version", "1.6.5"])
        assert rc == 0
        state = sm.load_state(str(tmp_path))
        assert state.chart_version == "1.6.5"
        assert state.deployed_at is not None

    def test_register_and_list_disks(self, tmp_path, capsys):
        sm.main(["--state", str(tmp_path), "register-node-disk",
                 "--node", "pve01", "--path", "/var/lib/longhorn"])
        rc = sm.main(["--state", str(tmp_path), "list-disks"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "pve01" in out

    def test_status_undeployed(self, tmp_path, capsys):
        rc = sm.main(["--state", str(tmp_path), "status"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "deployed" in out

    def test_status_json(self, tmp_path, capsys):
        sm.main(["--state", str(tmp_path), "mark-deployed"])
        capsys.readouterr()  # flush human-readable output from mark-deployed
        rc = sm.main(["--state", str(tmp_path), "status", "--json"])
        out = capsys.readouterr().out
        assert rc == 0
        data = json.loads(out)
        assert data["deployed"] is True

    def test_list_volumes_json(self, tmp_path, capsys):
        sm.main(["--state", str(tmp_path), "register-volume",
                 "--name", "my-pvc", "--namespace", "default"])
        capsys.readouterr()  # flush human-readable output from register-volume
        rc = sm.main(["--state", str(tmp_path), "list-volumes", "--json"])
        out = capsys.readouterr().out
        assert rc == 0
        data = json.loads(out)
        assert data[0]["name"] == "my-pvc"
