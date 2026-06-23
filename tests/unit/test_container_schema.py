"""
Tests for container-state-schema.json and the container_declaration additions
to bootstrap-state-schema.json.

Also tests backup.py volume and PBS archive naming functions.

Run: py -3 tests/unit/test_container_schema.py
"""

import importlib.util
import json
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
BOOTSTRAP_REPO = REPO_ROOT / "proxmox-bootstrap"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "bootstrap"
SCHEMA_DIR = REPO_ROOT / "data-model"

from validate import SchemaValidator


def load_schema(name: str) -> dict:
    with open(SCHEMA_DIR / name) as f:
        return json.load(f)


def load_fixture(name: str) -> dict:
    with open(FIXTURES / name) as f:
        return json.load(f)


def _import_backup():
    spec = importlib.util.spec_from_file_location("backup", BOOTSTRAP_REPO / "backup.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Container State Schema
# ---------------------------------------------------------------------------

class TestContainerStateSchema(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema("container-state-schema.json")
        self.fixture = load_fixture("container-state.json")
        self.v = SchemaValidator(self.schema)

    def test_valid_fixture_passes(self):
        errors = self.v.validate(self.fixture)
        self.assertEqual(errors, [], msg=f"Unexpected errors: {errors}")

    def test_cell_id_required(self):
        bad = deepcopy(self.fixture)
        del bad["cell_id"]
        errors = self.v.validate(bad)
        self.assertTrue(any("cell_id" in e.path for e in errors))

    def test_vmid_required(self):
        bad = deepcopy(self.fixture)
        del bad["vmid"]
        errors = self.v.validate(bad)
        self.assertTrue(any("vmid" in e.path for e in errors))

    def test_vmid_must_be_integer(self):
        bad = deepcopy(self.fixture)
        bad["vmid"] = "101"
        errors = self.v.validate(bad)
        self.assertTrue(len(errors) > 0)

    def test_null_runtime_valid(self):
        doc = deepcopy(self.fixture)
        doc["container_runtime"] = None
        errors = self.v.validate(doc)
        self.assertEqual(errors, [])

    def test_valid_runtimes(self):
        for runtime in ("podman", "docker", "podman-compose", "docker-compose"):
            doc = deepcopy(self.fixture)
            doc["container_runtime"] = runtime
            errors = self.v.validate(doc)
            self.assertEqual(errors, [], msg=f"Runtime {runtime!r} should be valid")

    def test_invalid_runtime_fails(self):
        bad = deepcopy(self.fixture)
        bad["container_runtime"] = "containerd"
        errors = self.v.validate(bad)
        self.assertTrue(len(errors) > 0)

    def test_container_status_enum_enforced(self):
        bad = deepcopy(self.fixture)
        bad["containers"][0]["status"] = "healthy"
        errors = self.v.validate(bad)
        self.assertTrue(len(errors) > 0)

    def test_valid_container_statuses(self):
        for status in ("running", "stopped", "exited", "paused", "unknown"):
            doc = deepcopy(self.fixture)
            doc["containers"][0]["status"] = status
            errors = self.v.validate(doc)
            self.assertEqual(errors, [], msg=f"Status {status!r} should be valid")

    def test_empty_containers_valid(self):
        doc = deepcopy(self.fixture)
        doc["containers"] = []
        errors = self.v.validate(doc)
        self.assertEqual(errors, [])

    def test_digest_drift_boolean(self):
        bad = deepcopy(self.fixture)
        bad["containers"][0]["digest_drift"] = "true"
        errors = self.v.validate(bad)
        self.assertTrue(len(errors) > 0)

    def test_null_image_digest_valid(self):
        doc = deepcopy(self.fixture)
        doc["containers"][0]["image_digest"] = None
        errors = self.v.validate(doc)
        self.assertEqual(errors, [])

    def test_resource_usage_nullable_fields(self):
        doc = deepcopy(self.fixture)
        doc["containers"][0]["resource_usage"] = {
            "cpu_percent": None,
            "ram_usage_mb": None,
            "ram_limit_mb": None,
            "disk_usage_gb": None,
        }
        errors = self.v.validate(doc)
        self.assertEqual(errors, [])

    def test_compose_file_drift_boolean(self):
        bad = deepcopy(self.fixture)
        bad["compose_files"][0]["drift"] = "false"
        errors = self.v.validate(bad)
        self.assertTrue(len(errors) > 0)


# ---------------------------------------------------------------------------
# Bootstrap State Schema — container_declaration additions
# ---------------------------------------------------------------------------

class TestBootstrapContainerDeclaration(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema("bootstrap-state-schema.json")
        self.fixture = load_fixture("bootstrap-state.json")
        self.v = SchemaValidator(self.schema)

    def _add_container(self, vm_idx: int = 1, **overrides) -> dict:
        """Return a valid container_declaration for testing."""
        container = {
            "name": "postgresql",
            "runtime": "podman",
            "image": "registry.hub.docker.com/library/postgres",
            "image_tag": "15-alpine",
            "image_digest": None,
            "compose_file": None,
            "ports": [],
            "volumes": [],
            "data_volumes": [],
            "networks": [],
            "env_vars": {"POSTGRES_DB": "forgejo"},
            "secret_references": [],
            "minimum_capability": {"ram_mb": 512, "cpu_cores": 1, "disk_gb": 5},
            "startup_after": [],
            "health_check": None,
            "notes": None,
        }
        container.update(overrides)
        return container

    def test_fixture_with_containers_validates(self):
        """Adding containers to a VM should not break validation."""
        doc = deepcopy(self.fixture)
        doc["vms"][1]["containers"] = [self._add_container()]
        errors = self.v.validate(doc)
        self.assertEqual(errors, [], msg=f"Errors: {errors}")

    def test_empty_containers_list_valid(self):
        doc = deepcopy(self.fixture)
        doc["vms"][1]["containers"] = []
        errors = self.v.validate(doc)
        self.assertEqual(errors, [])

    def test_container_name_required(self):
        doc = deepcopy(self.fixture)
        c = self._add_container()
        del c["name"]
        doc["vms"][1]["containers"] = [c]
        errors = self.v.validate(doc)
        self.assertTrue(any("name" in e.path for e in errors))

    def test_container_runtime_required(self):
        doc = deepcopy(self.fixture)
        c = self._add_container()
        del c["runtime"]
        doc["vms"][1]["containers"] = [c]
        errors = self.v.validate(doc)
        self.assertTrue(any("runtime" in e.path for e in errors))

    def test_container_image_required(self):
        doc = deepcopy(self.fixture)
        c = self._add_container()
        del c["image"]
        doc["vms"][1]["containers"] = [c]
        errors = self.v.validate(doc)
        self.assertTrue(any("image" in e.path for e in errors))

    def test_valid_container_runtimes(self):
        for runtime in ("podman", "docker", "podman-compose", "docker-compose"):
            doc = deepcopy(self.fixture)
            c = self._add_container(runtime=runtime)
            doc["vms"][1]["containers"] = [c]
            errors = self.v.validate(doc)
            self.assertEqual(errors, [], msg=f"Runtime {runtime!r} should be valid")

    def test_invalid_runtime_fails(self):
        doc = deepcopy(self.fixture)
        c = self._add_container(runtime="containerd")
        doc["vms"][1]["containers"] = [c]
        errors = self.v.validate(doc)
        self.assertTrue(len(errors) > 0)

    def test_compose_file_reference_nullable(self):
        doc = deepcopy(self.fixture)
        c = self._add_container(compose_file=None)
        doc["vms"][1]["containers"] = [c]
        errors = self.v.validate(doc)
        self.assertEqual(errors, [])

    def test_compose_file_reference_with_content(self):
        doc = deepcopy(self.fixture)
        c = self._add_container(compose_file={
            "forgejo_repo_url": "https://forgejo.internal/infra/bootstrap",
            "file_path": "containers/forgejo/compose.yaml",
            "commit_hash": "abc123def456",
            "file_digest": "sha256:111222333444"
        })
        doc["vms"][1]["containers"] = [c]
        errors = self.v.validate(doc)
        self.assertEqual(errors, [])

    def test_data_volume_backup_methods(self):
        for method in ("pbs", "rclone", "encrypted-archive"):
            doc = deepcopy(self.fixture)
            c = self._add_container(data_volumes=[{
                "volume_name": "data",
                "host_path": "/opt/data",
                "backup_method": method,
                "backup_schedule": None,
                "backup_destination": None,
                "retention_count": None,
                "pbs_job": "pbs-daily-vms" if method == "pbs" else None,
                "estimated_size_gb": None,
            }])
            doc["vms"][1]["containers"] = [c]
            errors = self.v.validate(doc)
            self.assertEqual(errors, [], msg=f"Backup method {method!r} should be valid")

    def test_invalid_backup_method_fails(self):
        doc = deepcopy(self.fixture)
        c = self._add_container(data_volumes=[{
            "volume_name": "data",
            "host_path": "/opt/data",
            "backup_method": "s3",
        }])
        doc["vms"][1]["containers"] = [c]
        errors = self.v.validate(doc)
        self.assertTrue(len(errors) > 0)

    def test_minimum_capability_nullable_fields(self):
        doc = deepcopy(self.fixture)
        c = self._add_container(minimum_capability={
            "ram_mb": None,
            "cpu_cores": None,
            "disk_gb": None,
        })
        doc["vms"][1]["containers"] = [c]
        errors = self.v.validate(doc)
        self.assertEqual(errors, [])

    def test_multiple_containers_per_vm(self):
        doc = deepcopy(self.fixture)
        doc["vms"][1]["containers"] = [
            self._add_container(name="app"),
            self._add_container(name="db"),
            self._add_container(name="cache"),
        ]
        errors = self.v.validate(doc)
        self.assertEqual(errors, [])


# ---------------------------------------------------------------------------
# Volume and PBS archive naming (backup.py extensions)
# ---------------------------------------------------------------------------

class TestVolumeArchiveFilename(unittest.TestCase):
    def setUp(self):
        self.bk = _import_backup()
        self.dt = datetime(2026, 5, 31, 2, 0, 0, tzinfo=timezone.utc)

    def _fn(self, **kwargs) -> str:
        return self.bk.volume_archive_filename(
            "proxmox-cell-a", "forgejo", "postgresql", "data",
            dt=self.dt, **kwargs
        )

    def test_encrypted_extension(self):
        self.assertTrue(self._fn(encrypted=True).endswith(".tar.gz.gpg"))

    def test_unencrypted_extension(self):
        self.assertTrue(self._fn(encrypted=False).endswith(".tar.gz"))

    def test_contains_cell_id(self):
        self.assertIn("proxmox-cell-a", self._fn())

    def test_contains_vm_name(self):
        self.assertIn("forgejo", self._fn())

    def test_contains_container_name(self):
        self.assertIn("postgresql", self._fn())

    def test_contains_volume_name(self):
        self.assertIn("data", self._fn())

    def test_contains_timestamp(self):
        self.assertIn("2026-05-31_02_00_00", self._fn())

    def test_contains_6_char_hash(self):
        fn = self._fn()
        base = fn.replace(".tar.gz.gpg", "").replace(".tar.gz", "")
        short_hash = base.split("_")[-1]
        self.assertEqual(len(short_hash), 6)
        self.assertRegex(short_hash, r"^[0-9a-f]{6}$")

    def test_deterministic(self):
        self.assertEqual(self._fn(), self._fn())

    def test_different_volumes_different_names(self):
        fn1 = self.bk.volume_archive_filename("cell-a", "vm1", "app", "data", dt=self.dt)
        fn2 = self.bk.volume_archive_filename("cell-a", "vm1", "app", "logs", dt=self.dt)
        self.assertNotEqual(fn1, fn2)

    def test_no_colons_or_spaces(self):
        fn = self._fn()
        self.assertNotIn(":", fn)
        self.assertNotIn(" ", fn)

    def test_filesystem_safe(self):
        fn = self._fn()
        self.assertRegex(fn, r"^[a-zA-Z0-9\-_\.]+$")


class TestVolumeArchiveParsing(unittest.TestCase):
    def setUp(self):
        self.bk = _import_backup()
        self.dt = datetime(2026, 5, 31, 2, 0, 0, tzinfo=timezone.utc)

    def _roundtrip(self, encrypted: bool = True) -> dict:
        fn = self.bk.volume_archive_filename(
            "proxmox-cell-a", "forgejo", "postgresql", "data",
            dt=self.dt, encrypted=encrypted
        )
        return self.bk.parse_volume_archive_filename(fn)

    def test_parses_encrypted(self):
        result = self._roundtrip(encrypted=True)
        self.assertIsNotNone(result)
        self.assertTrue(result["encrypted"])

    def test_parses_unencrypted(self):
        result = self._roundtrip(encrypted=False)
        self.assertIsNotNone(result)
        self.assertFalse(result["encrypted"])

    def test_cell_id_extracted(self):
        result = self._roundtrip()
        self.assertEqual(result["cell_id"], "proxmox-cell-a")

    def test_vm_name_extracted(self):
        result = self._roundtrip()
        self.assertEqual(result["vm_name"], "forgejo")

    def test_container_name_extracted(self):
        result = self._roundtrip()
        self.assertEqual(result["container_name"], "postgresql")

    def test_volume_name_extracted(self):
        result = self._roundtrip()
        self.assertEqual(result["volume_name"], "data")

    def test_timestamp_extracted(self):
        result = self._roundtrip()
        self.assertEqual(result["timestamp_str"], "2026-05-31_02_00_00")

    def test_invalid_returns_none(self):
        self.assertIsNone(self.bk.parse_volume_archive_filename("invalid.txt"))
        self.assertIsNone(self.bk.parse_volume_archive_filename(""))


class TestPBSOfflineFilename(unittest.TestCase):
    def setUp(self):
        self.bk = _import_backup()
        self.dt = datetime(2026, 5, 31, 2, 0, 0, tzinfo=timezone.utc)

    def test_tar_zst_extension(self):
        fn = self.bk.pbs_offsite_filename("cell-a", 101, "forgejo", dt=self.dt)
        self.assertTrue(fn.endswith(".tar.zst"))

    def test_contains_pbs_marker(self):
        fn = self.bk.pbs_offsite_filename("cell-a", 101, "forgejo", dt=self.dt)
        self.assertIn("pbs", fn)

    def test_contains_vmid(self):
        fn = self.bk.pbs_offsite_filename("cell-a", 101, "forgejo", dt=self.dt)
        self.assertIn("vm101", fn)

    def test_contains_vm_name(self):
        fn = self.bk.pbs_offsite_filename("cell-a", 101, "forgejo", dt=self.dt)
        self.assertIn("forgejo", fn)

    def test_contains_timestamp(self):
        fn = self.bk.pbs_offsite_filename("cell-a", 101, "forgejo", dt=self.dt)
        self.assertIn("2026-05-31_02_00_00", fn)

    def test_deterministic(self):
        fn1 = self.bk.pbs_offsite_filename("cell-a", 101, "forgejo", dt=self.dt)
        fn2 = self.bk.pbs_offsite_filename("cell-a", 101, "forgejo", dt=self.dt)
        self.assertEqual(fn1, fn2)

    def test_different_vms_different_names(self):
        fn1 = self.bk.pbs_offsite_filename("cell-a", 101, "forgejo", dt=self.dt)
        fn2 = self.bk.pbs_offsite_filename("cell-a", 102, "inventory", dt=self.dt)
        self.assertNotEqual(fn1, fn2)

    def test_no_colons_or_spaces(self):
        fn = self.bk.pbs_offsite_filename("cell-a", 101, "forgejo", dt=self.dt)
        self.assertNotIn(":", fn)
        self.assertNotIn(" ", fn)


# ---------------------------------------------------------------------------
# All archive types: naming consistency
# ---------------------------------------------------------------------------

class TestAllArchiveNamesConsistent(unittest.TestCase):
    """All archive naming functions follow the same timestamp and hash conventions."""

    def setUp(self):
        self.bk = _import_backup()
        self.dt = datetime(2026, 5, 31, 14, 30, 0, tzinfo=timezone.utc)

    def test_all_use_same_timestamp_format(self):
        ts = "2026-05-31_14_30_00"
        config_fn = self.bk.archive_filename("cell-a", dt=self.dt)
        volume_fn = self.bk.volume_archive_filename("cell-a", "vm1", "app", "data", dt=self.dt)
        pbs_fn = self.bk.pbs_offsite_filename("cell-a", 100, "vm1", dt=self.dt)
        self.assertIn(ts, config_fn)
        self.assertIn(ts, volume_fn)
        self.assertIn(ts, pbs_fn)

    def test_all_have_6_char_hash(self):
        fns = [
            self.bk.archive_filename("cell-a", dt=self.dt),
            self.bk.volume_archive_filename("cell-a", "vm1", "app", "data", dt=self.dt),
            self.bk.pbs_offsite_filename("cell-a", 100, "vm1", dt=self.dt),
        ]
        for fn in fns:
            # Strip known extensions
            base = fn
            for ext in (".tar.gz.gpg", ".tar.gz", ".tar.zst"):
                if base.endswith(ext):
                    base = base[:-len(ext)]
            short_hash = base.split("_")[-1]
            self.assertEqual(len(short_hash), 6,
                             msg=f"Expected 6-char hash in {fn!r}, got {short_hash!r}")
            self.assertRegex(short_hash, r"^[0-9a-f]{6}$",
                             msg=f"Hash should be hex in {fn!r}")

    def test_all_filesystem_safe(self):
        fns = [
            self.bk.archive_filename("cell-a", dt=self.dt),
            self.bk.volume_archive_filename("cell-a", "vm1", "app", "data", dt=self.dt),
            self.bk.pbs_offsite_filename("cell-a", 100, "vm1", dt=self.dt),
        ]
        for fn in fns:
            self.assertRegex(fn, r"^[a-zA-Z0-9\-_\.]+$",
                             msg=f"Filename {fn!r} contains unsafe characters")


if __name__ == "__main__":
    unittest.main(verbosity=2)
