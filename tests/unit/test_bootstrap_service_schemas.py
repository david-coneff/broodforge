"""
Schema validation tests for Milestone 6.1 — Bootstrap State and Service State schemas.

Run: py -3 tests/unit/test_bootstrap_service_schemas.py
"""

import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "data-model"))

from validate import SchemaValidator, detect_schema

SCHEMA_DIR = REPO_ROOT / "data-model"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "bootstrap"


def load_schema(name):
    with open(SCHEMA_DIR / name) as f:
        return json.load(f)


def load_fixture(name):
    with open(FIXTURES / name) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Bootstrap State Schema
# ---------------------------------------------------------------------------

class TestBootstrapStateSchemaStructure(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema("bootstrap-state-schema.json")
        self.fixture = load_fixture("bootstrap-state.json")
        self.v = SchemaValidator(self.schema)

    def test_valid_fixture_passes(self):
        errors = self.v.validate(self.fixture)
        self.assertEqual(errors, [], msg=f"Unexpected errors: {errors}")

    def test_cell_id_required(self):
        bad = deepcopy(self.fixture)
        del bad["cell_id"]
        errors = self.v.validate(bad)
        self.assertTrue(any("cell_id" in e.path for e in errors))

    def test_schema_version_required(self):
        bad = deepcopy(self.fixture)
        del bad["schema_version"]
        errors = self.v.validate(bad)
        self.assertTrue(any("schema_version" in e.path for e in errors))

    def test_declared_at_required(self):
        bad = deepcopy(self.fixture)
        del bad["declared_at"]
        errors = self.v.validate(bad)
        self.assertTrue(any("declared_at" in e.path for e in errors))

    def test_invalid_schema_version_fails(self):
        bad = deepcopy(self.fixture)
        bad["schema_version"] = "99.0"
        errors = self.v.validate(bad)
        self.assertTrue(len(errors) > 0)

    def test_empty_vms_valid(self):
        doc = deepcopy(self.fixture)
        doc["vms"] = []
        errors = self.v.validate(doc)
        self.assertEqual(errors, [])

    def test_empty_secrets_valid(self):
        doc = deepcopy(self.fixture)
        doc["secrets"] = []
        errors = self.v.validate(doc)
        self.assertEqual(errors, [])


class TestBootstrapStateVmBootstrap(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema("bootstrap-state-schema.json")
        self.fixture = load_fixture("bootstrap-state.json")
        self.v = SchemaValidator(self.schema)

    def test_vm_missing_vmid_fails(self):
        bad = deepcopy(self.fixture)
        del bad["vms"][0]["vmid"]
        errors = self.v.validate(bad)
        self.assertTrue(any("vmid" in e.path for e in errors))

    def test_vm_missing_name_fails(self):
        bad = deepcopy(self.fixture)
        del bad["vms"][0]["name"]
        errors = self.v.validate(bad)
        self.assertTrue(any("name" in e.path for e in errors))

    def test_vm_missing_cloudinit_fails(self):
        bad = deepcopy(self.fixture)
        del bad["vms"][0]["cloudinit"]
        errors = self.v.validate(bad)
        self.assertTrue(len(errors) > 0)

    def test_cloudinit_missing_user_data_path_fails(self):
        bad = deepcopy(self.fixture)
        del bad["vms"][0]["cloudinit"]["user_data_path"]
        errors = self.v.validate(bad)
        self.assertTrue(any("user_data_path" in e.path for e in errors))

    def test_cloudinit_null_vendor_data_valid(self):
        doc = deepcopy(self.fixture)
        doc["vms"][0]["cloudinit"]["vendor_data_path"] = None
        errors = self.v.validate(doc)
        self.assertEqual(errors, [])

    def test_ssh_key_reference_nullable(self):
        doc = deepcopy(self.fixture)
        doc["vms"][0]["ssh_key_reference"] = None
        errors = self.v.validate(doc)
        self.assertEqual(errors, [])

    def test_vmid_must_be_integer(self):
        bad = deepcopy(self.fixture)
        bad["vms"][0]["vmid"] = "100"
        errors = self.v.validate(bad)
        self.assertTrue(len(errors) > 0)


class TestBootstrapStateSecretRegistry(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema("bootstrap-state-schema.json")
        self.fixture = load_fixture("bootstrap-state.json")
        self.v = SchemaValidator(self.schema)

    def test_secret_missing_id_fails(self):
        bad = deepcopy(self.fixture)
        del bad["secrets"][0]["id"]
        errors = self.v.validate(bad)
        self.assertTrue(any("id" in e.path for e in errors))

    def test_secret_missing_keepass_path_fails(self):
        bad = deepcopy(self.fixture)
        del bad["secrets"][0]["keepass_path"]
        errors = self.v.validate(bad)
        self.assertTrue(any("keepass_path" in e.path for e in errors))

    def test_secret_missing_owning_cell_fails(self):
        bad = deepcopy(self.fixture)
        del bad["secrets"][0]["owning_cell"]
        errors = self.v.validate(bad)
        self.assertTrue(any("owning_cell" in e.path for e in errors))

    def test_secret_type_enum_enforced(self):
        bad = deepcopy(self.fixture)
        bad["secrets"][0]["secret_type"] = "plaintext-password"
        errors = self.v.validate(bad)
        self.assertTrue(len(errors) > 0)

    def test_valid_secret_types(self):
        for stype in ("password", "ssh-private-key", "api-token",
                      "certificate-private-key", "other"):
            doc = deepcopy(self.fixture)
            doc["secrets"][0]["secret_type"] = stype
            errors = self.v.validate(doc)
            self.assertEqual(errors, [], msg=f"Type {stype!r} should be valid")

    def test_rotation_schedule_nullable(self):
        doc = deepcopy(self.fixture)
        doc["secrets"][0]["rotation_schedule"] = None
        errors = self.v.validate(doc)
        self.assertEqual(errors, [])

    def test_recovery_path_nullable(self):
        doc = deepcopy(self.fixture)
        doc["secrets"][0]["recovery_path"] = None
        errors = self.v.validate(doc)
        self.assertEqual(errors, [])


class TestBootstrapStateDnsRegistry(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema("bootstrap-state-schema.json")
        self.fixture = load_fixture("bootstrap-state.json")
        self.v = SchemaValidator(self.schema)

    def test_dns_entry_missing_hostname_fails(self):
        bad = deepcopy(self.fixture)
        del bad["dns_registry"][0]["hostname"]
        errors = self.v.validate(bad)
        self.assertTrue(any("hostname" in e.path for e in errors))

    def test_dns_entry_missing_ip_fails(self):
        bad = deepcopy(self.fixture)
        del bad["dns_registry"][0]["ip"]
        errors = self.v.validate(bad)
        self.assertTrue(any("ip" in e.path for e in errors))

    def test_dns_entry_null_vmid_valid(self):
        doc = deepcopy(self.fixture)
        doc["dns_registry"][0]["vmid"] = None
        errors = self.v.validate(doc)
        self.assertEqual(errors, [])

    def test_empty_dns_registry_valid(self):
        doc = deepcopy(self.fixture)
        doc["dns_registry"] = []
        errors = self.v.validate(doc)
        self.assertEqual(errors, [])


class TestBootstrapStateServiceContracts(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema("bootstrap-state-schema.json")
        self.fixture = load_fixture("bootstrap-state.json")
        self.v = SchemaValidator(self.schema)

    def test_contract_missing_service_fails(self):
        bad = deepcopy(self.fixture)
        del bad["service_contracts"][0]["service"]
        errors = self.v.validate(bad)
        self.assertTrue(any("service" in e.path for e in errors))

    def test_contract_missing_vm_fails(self):
        bad = deepcopy(self.fixture)
        del bad["service_contracts"][0]["vm"]
        errors = self.v.validate(bad)
        self.assertTrue(any("vm" in e.path for e in errors))

    def test_provided_interface_missing_port_fails(self):
        bad = deepcopy(self.fixture)
        del bad["service_contracts"][0]["provided_interfaces"][0]["port"]
        errors = self.v.validate(bad)
        self.assertTrue(any("port" in e.path for e in errors))

    def test_required_interface_missing_service_fails(self):
        bad = deepcopy(self.fixture)
        del bad["service_contracts"][0]["required_interfaces"][0]["service"]
        errors = self.v.validate(bad)
        self.assertTrue(any("service" in e.path for e in errors))

    def test_empty_contracts_valid(self):
        doc = deepcopy(self.fixture)
        doc["service_contracts"] = []
        errors = self.v.validate(doc)
        self.assertEqual(errors, [])


class TestBootstrapStateHardwareRequirements(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema("bootstrap-state-schema.json")
        self.fixture = load_fixture("bootstrap-state.json")
        self.v = SchemaValidator(self.schema)

    def test_hardware_requirements_present(self):
        errors = self.v.validate(self.fixture)
        self.assertEqual(errors, [])

    def test_minimum_ram_nullable(self):
        doc = deepcopy(self.fixture)
        doc["hardware_requirements"]["minimum_ram_gb"] = None
        errors = self.v.validate(doc)
        self.assertEqual(errors, [])

    def test_vtx_required_must_be_boolean(self):
        bad = deepcopy(self.fixture)
        bad["hardware_requirements"]["vtx_required"] = "yes"
        errors = self.v.validate(bad)
        self.assertTrue(len(errors) > 0)


class TestBootstrapStateBaseImages(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema("bootstrap-state-schema.json")
        self.fixture = load_fixture("bootstrap-state.json")
        self.v = SchemaValidator(self.schema)

    def test_base_image_missing_name_fails(self):
        bad = deepcopy(self.fixture)
        del bad["base_images"][0]["name"]
        errors = self.v.validate(bad)
        self.assertTrue(any("name" in e.path for e in errors))

    def test_base_image_missing_checksum_fails(self):
        bad = deepcopy(self.fixture)
        del bad["base_images"][0]["checksum"]
        errors = self.v.validate(bad)
        self.assertTrue(any("checksum" in e.path for e in errors))

    def test_base_image_source_url_nullable(self):
        doc = deepcopy(self.fixture)
        doc["base_images"][0]["source_url"] = None
        errors = self.v.validate(doc)
        self.assertEqual(errors, [])

    def test_empty_base_images_valid(self):
        doc = deepcopy(self.fixture)
        doc["base_images"] = []
        errors = self.v.validate(doc)
        self.assertEqual(errors, [])


# ---------------------------------------------------------------------------
# Service State Schema
# ---------------------------------------------------------------------------

class TestServiceStateSchemaStructure(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema("service-state-schema.json")
        self.fixture = load_fixture("service-state.json")
        self.v = SchemaValidator(self.schema)

    def test_valid_fixture_passes(self):
        errors = self.v.validate(self.fixture)
        self.assertEqual(errors, [], msg=f"Unexpected errors: {errors}")

    def test_cell_id_required(self):
        bad = deepcopy(self.fixture)
        del bad["cell_id"]
        errors = self.v.validate(bad)
        self.assertTrue(any("cell_id" in e.path for e in errors))

    def test_schema_version_required(self):
        bad = deepcopy(self.fixture)
        del bad["schema_version"]
        errors = self.v.validate(bad)
        self.assertTrue(any("schema_version" in e.path for e in errors))

    def test_collected_at_required(self):
        bad = deepcopy(self.fixture)
        del bad["collected_at"]
        errors = self.v.validate(bad)
        self.assertTrue(any("collected_at" in e.path for e in errors))

    def test_empty_services_valid(self):
        doc = deepcopy(self.fixture)
        doc["services"] = []
        errors = self.v.validate(doc)
        self.assertEqual(errors, [])

    def test_empty_backup_assignments_valid(self):
        doc = deepcopy(self.fixture)
        doc["backup_assignments"] = []
        errors = self.v.validate(doc)
        self.assertEqual(errors, [])


class TestServiceStateServiceEntry(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema("service-state-schema.json")
        self.fixture = load_fixture("service-state.json")
        self.v = SchemaValidator(self.schema)

    def test_service_missing_name_fails(self):
        bad = deepcopy(self.fixture)
        del bad["services"][0]["name"]
        errors = self.v.validate(bad)
        self.assertTrue(any("name" in e.path for e in errors))

    def test_service_missing_vm_fails(self):
        bad = deepcopy(self.fixture)
        del bad["services"][0]["vm"]
        errors = self.v.validate(bad)
        self.assertTrue(any("vm" in e.path for e in errors))

    def test_service_missing_vmid_fails(self):
        bad = deepcopy(self.fixture)
        del bad["services"][0]["vmid"]
        errors = self.v.validate(bad)
        self.assertTrue(any("vmid" in e.path for e in errors))

    def test_status_enum_enforced(self):
        bad = deepcopy(self.fixture)
        bad["services"][0]["status"] = "healthy"
        errors = self.v.validate(bad)
        self.assertTrue(len(errors) > 0)

    def test_valid_statuses(self):
        for status in ("running", "stopped", "degraded", "unknown"):
            doc = deepcopy(self.fixture)
            doc["services"][0]["status"] = status
            errors = self.v.validate(doc)
            self.assertEqual(errors, [], msg=f"Status {status!r} should be valid")

    def test_url_nullable(self):
        doc = deepcopy(self.fixture)
        doc["services"][0]["url"] = None
        errors = self.v.validate(doc)
        self.assertEqual(errors, [])

    def test_last_health_check_nullable(self):
        doc = deepcopy(self.fixture)
        doc["services"][0]["last_health_check"] = None
        errors = self.v.validate(doc)
        self.assertEqual(errors, [])


class TestServiceStateBackupAssignment(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema("service-state-schema.json")
        self.fixture = load_fixture("service-state.json")
        self.v = SchemaValidator(self.schema)

    def test_backup_missing_vmid_fails(self):
        bad = deepcopy(self.fixture)
        del bad["backup_assignments"][0]["vmid"]
        errors = self.v.validate(bad)
        self.assertTrue(any("vmid" in e.path for e in errors))

    def test_backup_missing_vm_name_fails(self):
        bad = deepcopy(self.fixture)
        del bad["backup_assignments"][0]["vm_name"]
        errors = self.v.validate(bad)
        self.assertTrue(any("vm_name" in e.path for e in errors))

    def test_last_run_status_enum_enforced(self):
        bad = deepcopy(self.fixture)
        bad["backup_assignments"][0]["last_run_status"] = "success"
        errors = self.v.validate(bad)
        self.assertTrue(len(errors) > 0)

    def test_valid_last_run_statuses(self):
        for status in ("ok", "failed", "partial", "never", None):
            doc = deepcopy(self.fixture)
            doc["backup_assignments"][0]["last_run_status"] = status
            errors = self.v.validate(doc)
            self.assertEqual(errors, [], msg=f"Status {status!r} should be valid")

    def test_backup_job_id_nullable(self):
        doc = deepcopy(self.fixture)
        doc["backup_assignments"][0]["backup_job_id"] = None
        errors = self.v.validate(doc)
        self.assertEqual(errors, [])


class TestServiceStateDnsRegistration(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema("service-state-schema.json")
        self.fixture = load_fixture("service-state.json")
        self.v = SchemaValidator(self.schema)

    def test_dns_missing_hostname_fails(self):
        bad = deepcopy(self.fixture)
        del bad["dns_registrations"][0]["hostname"]
        errors = self.v.validate(bad)
        self.assertTrue(any("hostname" in e.path for e in errors))

    def test_dns_missing_ip_fails(self):
        bad = deepcopy(self.fixture)
        del bad["dns_registrations"][0]["ip"]
        errors = self.v.validate(bad)
        self.assertTrue(any("ip" in e.path for e in errors))

    def test_record_type_enum_enforced(self):
        bad = deepcopy(self.fixture)
        bad["dns_registrations"][0]["record_type"] = "MX"
        errors = self.v.validate(bad)
        self.assertTrue(len(errors) > 0)

    def test_valid_record_types(self):
        for rt in ("A", "AAAA", "CNAME", "PTR", "other"):
            doc = deepcopy(self.fixture)
            doc["dns_registrations"][0]["record_type"] = rt
            errors = self.v.validate(doc)
            self.assertEqual(errors, [], msg=f"Record type {rt!r} should be valid")

    def test_empty_dns_registrations_valid(self):
        doc = deepcopy(self.fixture)
        doc["dns_registrations"] = []
        errors = self.v.validate(doc)
        self.assertEqual(errors, [])


# ---------------------------------------------------------------------------
# Cross-schema: cell_id consistency
# ---------------------------------------------------------------------------

class TestCellIdPresence(unittest.TestCase):
    """Verify that cell_id is present and non-empty in all new schemas."""

    def _assert_cell_id(self, fixture_name, schema_name):
        schema_path = SCHEMA_DIR / schema_name
        fixture_path = REPO_ROOT / "tests" / "fixtures" / "bootstrap" / fixture_name
        with open(schema_path) as f:
            schema = json.load(f)
        with open(fixture_path) as f:
            fixture = json.load(f)
        # Must be in required list
        self.assertIn("cell_id", schema.get("required", []),
                      msg=f"cell_id not in required[] of {schema_name}")
        # Fixture must have a non-empty value
        self.assertIn("cell_id", fixture,
                      msg=f"cell_id missing from {fixture_name}")
        self.assertTrue(fixture["cell_id"],
                        msg=f"cell_id is empty in {fixture_name}")

    def test_bootstrap_state_has_cell_id(self):
        self._assert_cell_id("bootstrap-state.json", "bootstrap-state-schema.json")

    def test_service_state_has_cell_id(self):
        self._assert_cell_id("service-state.json", "service-state-schema.json")


if __name__ == "__main__":
    unittest.main(verbosity=2)
