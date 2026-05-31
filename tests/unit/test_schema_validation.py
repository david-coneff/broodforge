#!/usr/bin/env python3
"""
Schema validation tests for Milestone 5.1.
Uses Python stdlib unittest only.

Run: python3 -m pytest tests/unit/test_schema_validation.py -v
  or: python3 tests/unit/test_schema_validation.py
"""

import json
import sys
import unittest
from pathlib import Path
from copy import deepcopy

# Allow running from repo root or tests/unit/
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "data-model"))

from validate import SchemaValidator, validate_file, detect_schema

SCHEMA_DIR = REPO_ROOT / "data-model"
FIXTURES = REPO_ROOT / "tests" / "fixtures"


def load_schema(name: str) -> dict:
    with open(SCHEMA_DIR / name) as f:
        return json.load(f)


def load_fixture(path: str) -> dict:
    with open(FIXTURES / path) as f:
        return json.load(f)


class TestObservedStateTier1(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema("observed-state-schema.json")
        self.fixture = load_fixture("tier1/manifest.json")
        self.validator = SchemaValidator(self.schema)

    def test_valid_fixture_passes(self):
        errors = self.validator.validate(self.fixture)
        self.assertEqual(errors, [], msg=f"Unexpected errors: {errors}")

    def test_schema_auto_detected(self):
        detected = detect_schema(self.fixture)
        self.assertIsNotNone(detected)
        self.assertEqual(detected.name, "observed-state-schema.json")

    def test_missing_required_host_field_fails(self):
        bad = deepcopy(self.fixture)
        del bad["host"]["hostname"]
        errors = self.validator.validate(bad)
        self.assertTrue(any("hostname" in e.path for e in errors),
                        msg="Expected 'hostname required' error")

    def test_missing_top_level_required_fails(self):
        bad = deepcopy(self.fixture)
        del bad["collected_at"]
        errors = self.validator.validate(bad)
        self.assertTrue(any("collected_at" in e.path for e in errors))

    def test_wrong_type_total_threads_fails(self):
        bad = deepcopy(self.fixture)
        bad["cpu"]["total_threads"] = "48"  # should be integer
        errors = self.validator.validate(bad)
        self.assertTrue(len(errors) > 0)

    def test_block_device_required_fields(self):
        bad = deepcopy(self.fixture)
        del bad["storage"]["block_devices"][0]["name"]
        errors = self.validator.validate(bad)
        self.assertTrue(len(errors) > 0)

    def test_empty_vms_and_containers_valid(self):
        # Fresh host has no VMs or containers
        fixture = deepcopy(self.fixture)
        fixture["vms"] = []
        fixture["containers"] = []
        errors = self.validator.validate(fixture)
        self.assertEqual(errors, [])

    def test_invalid_assessment_tier_fails(self):
        bad = deepcopy(self.fixture)
        bad["assessment_tier"] = 3
        errors = self.validator.validate(bad)
        self.assertTrue(len(errors) > 0)

    def test_null_allowed_for_optional_cpu_fields(self):
        fixture = deepcopy(self.fixture)
        fixture["cpu"]["model"] = None
        fixture["cpu"]["virtualization"] = None
        errors = self.validator.validate(fixture)
        self.assertEqual(errors, [])

    def test_collection_errors_list_valid(self):
        fixture = deepcopy(self.fixture)
        fixture["collection_errors"] = [
            {"collector": "storage", "message": "lsblk failed", "field": "storage.block_devices"}
        ]
        errors = self.validator.validate(fixture)
        self.assertEqual(errors, [])

    def test_collection_error_missing_required_field_fails(self):
        bad = deepcopy(self.fixture)
        bad["collection_errors"] = [{"collector": "storage"}]  # missing message
        errors = self.validator.validate(bad)
        self.assertTrue(len(errors) > 0)

    def test_zfs_pool_optional_fields_null(self):
        fixture = deepcopy(self.fixture)
        fixture["storage"]["zfs_pools"][0]["topology"] = None
        fixture["storage"]["zfs_pools"][0]["total_gb"] = None
        errors = self.validator.validate(fixture)
        self.assertEqual(errors, [])

    def test_vm_entry_valid(self):
        fixture = deepcopy(self.fixture)
        fixture["vms"] = [
            {"vmid": 100, "name": "test-vm", "status": "running",
             "cores": 4, "memory_mb": 8192, "disk_gb": 64.0}
        ]
        errors = self.validator.validate(fixture)
        self.assertEqual(errors, [])

    def test_vm_missing_required_fails(self):
        bad = deepcopy(self.fixture)
        bad["vms"] = [{"vmid": 100, "name": "test-vm"}]  # missing status
        errors = self.validator.validate(bad)
        self.assertTrue(len(errors) > 0)


class TestObservedStateTier2(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema("observed-state-schema.json")
        self.fixture = load_fixture("tier2/manifest.json")
        self.validator = SchemaValidator(self.schema)

    def test_valid_tier2_fixture_passes(self):
        errors = self.validator.validate(self.fixture)
        self.assertEqual(errors, [], msg=f"Unexpected errors: {errors}")

    def test_multiple_vms_valid(self):
        errors = self.validator.validate(self.fixture)
        self.assertEqual(errors, [])
        self.assertEqual(len(self.fixture["vms"]), 4)


class TestRecoveryStateSchema(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema("recovery-state-schema.json")
        self.fixture = load_fixture("tier2/recovery-state.json")
        self.validator = SchemaValidator(self.schema)

    def test_valid_fixture_passes(self):
        errors = self.validator.validate(self.fixture)
        self.assertEqual(errors, [], msg=f"Unexpected errors: {errors}")

    def test_schema_auto_detected(self):
        detected = detect_schema(self.fixture)
        self.assertIsNotNone(detected)
        self.assertEqual(detected.name, "recovery-state-schema.json")

    def test_invalid_readiness_score_fails(self):
        bad = deepcopy(self.fixture)
        bad["readiness_report"]["overall_score"] = "PURPLE"
        errors = self.validator.validate(bad)
        self.assertTrue(len(errors) > 0)

    def test_invalid_edge_type_fails(self):
        bad = deepcopy(self.fixture)
        bad["dependency_graph"]["edges"][0]["type"] = "MAGIC"
        errors = self.validator.validate(bad)
        self.assertTrue(len(errors) > 0)

    def test_restore_waves_optional(self):
        fixture = deepcopy(self.fixture)
        del fixture["dependency_graph"]["restore_waves"]
        errors = self.validator.validate(fixture)
        self.assertEqual(errors, [])

    def test_gap_missing_required_fails(self):
        bad = deepcopy(self.fixture)
        bad["readiness_report"]["components"][0]["gaps"] = [
            {"component_id": "pve:host"}  # missing gap_type, severity, description
        ]
        errors = self.validator.validate(bad)
        self.assertTrue(len(errors) > 0)


class TestHistoricalStateSchema(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema("historical-state-schema.json")
        self.fixture = load_fixture("history-index.json")
        self.validator = SchemaValidator(self.schema)

    def test_valid_index_passes(self):
        errors = self.validator.validate(self.fixture)
        self.assertEqual(errors, [], msg=f"Unexpected errors: {errors}")

    def test_schema_auto_detected(self):
        detected = detect_schema(self.fixture)
        self.assertIsNotNone(detected)
        self.assertEqual(detected.name, "historical-state-schema.json")


class TestDeclaredStateSchema(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema("declared-state-schema.json")
        self.validator = SchemaValidator(self.schema)

    def test_minimal_valid_instance(self):
        instance = {
            "schema_version": "1.0",
            "collected_at": "2026-05-29T02:00:00Z",
            "tofu_workspaces": [],
            "repositories": []
        }
        errors = self.validator.validate(instance)
        self.assertEqual(errors, [])

    def test_workspace_with_resources(self):
        instance = {
            "schema_version": "1.0",
            "collected_at": "2026-05-29T02:00:00Z",
            "tofu_workspaces": [
                {
                    "name": "proxmox-vms",
                    "path": "/opt/tofu/proxmox-vms",
                    "backend_type": "local",
                    "resource_count": 4,
                    "last_apply_at": "2026-05-20T10:00:00Z",
                    "resources": [
                        {
                            "type": "proxmox_vm_qemu",
                            "name": "forgejo",
                            "provider": "registry.terraform.io/telmate/proxmox",
                            "depends_on": [],
                            "attributes": {"vmid": 101, "memory": 4096}
                        }
                    ],
                    "outputs": {},
                    "variables": {"proxmox_host": "192.168.1.10"}
                }
            ],
            "repositories": []
        }
        errors = self.validator.validate(instance)
        self.assertEqual(errors, [])


class TestConfiguredStateSchema(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema("configured-state-schema.json")
        self.validator = SchemaValidator(self.schema)

    def test_minimal_valid_instance(self):
        instance = {
            "schema_version": "1.0",
            "collected_at": "2026-05-29T02:00:00Z"
        }
        errors = self.validator.validate(instance)
        self.assertEqual(errors, [])

    def test_full_ansible_inventory(self):
        instance = {
            "schema_version": "1.0",
            "collected_at": "2026-05-29T02:00:00Z",
            "ansible_inventory": {
                "inventory_path": "/opt/inventory/hosts.yaml",
                "hosts": [
                    {"name": "forgejo", "address": "192.168.1.21",
                     "groups": ["git_servers", "all"], "variables": {"ansible_user": "ubuntu"}}
                ],
                "groups": [
                    {"name": "git_servers", "hosts": ["forgejo"], "children": [], "variables": {}}
                ]
            },
            "role_assignments": [
                {"playbook": "site.yml", "hosts": "git_servers",
                 "roles": ["forgejo"], "tags": ["deploy"]}
            ],
            "repositories": [
                {"name": "ansible-platform", "url": "http://forgejo.internal/infra/ansible-platform",
                 "default_branch": "main", "last_commit_at": "2026-05-28T14:00:00Z",
                 "repo_type": "ansible"}
            ]
        }
        errors = self.validator.validate(instance)
        self.assertEqual(errors, [])


class TestValidateFileCLI(unittest.TestCase):
    """Integration tests using validate_file() directly."""

    def test_tier1_fixture_validates(self):
        ok, errors = validate_file(FIXTURES / "tier1" / "manifest.json")
        self.assertTrue(ok, msg=f"Errors: {errors}")

    def test_tier2_fixture_validates(self):
        ok, errors = validate_file(FIXTURES / "tier2" / "manifest.json")
        self.assertTrue(ok, msg=f"Errors: {errors}")

    def test_recovery_fixture_validates(self):
        ok, errors = validate_file(FIXTURES / "tier2" / "recovery-state.json")
        self.assertTrue(ok, msg=f"Errors: {errors}")

    def test_history_index_validates(self):
        ok, errors = validate_file(FIXTURES / "history-index.json")
        self.assertTrue(ok, msg=f"Errors: {errors}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
