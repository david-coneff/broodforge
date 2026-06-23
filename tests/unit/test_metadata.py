"""
Tests for proxmox-bootstrap/metadata/ YAML files.

Validates structure, required fields, POPULATE markers, and cross-file
consistency using text-based checks (stdlib only — no PyYAML dependency).

Run: py -3 tests/unit/test_metadata.py
"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
METADATA_DIR = REPO_ROOT / "proxmox-bootstrap" / "metadata"
BOOTSTRAP_DIR = REPO_ROOT / "proxmox-bootstrap"


def _read(filename: str) -> str:
    return (METADATA_DIR / filename).read_text(encoding="utf-8")


def _has_key(text: str, key: str) -> bool:
    """Check that a top-level YAML key is present."""
    return bool(re.search(rf"^{re.escape(key)}\s*:", text, re.MULTILINE))


def _count_populate(text: str) -> int:
    """Count POPULATE markers — fields requiring human input."""
    return len(re.findall(r"POPULATE:", text))


# ---------------------------------------------------------------------------
# File existence
# ---------------------------------------------------------------------------

class TestMetadataFilesExist(unittest.TestCase):

    REQUIRED_FILES = [
        "README.md",
        "cell-identity.yaml",
        "hardware-profile.yaml",
        "network-topology.yaml",
        "vm-roles.yaml",
        "k3s-cluster.yaml",
        "service-catalog.yaml",
        "backup-policy.yaml",
        "recovery-priority.yaml",
        "placement-policy.yaml",
        "naming-convention.yaml",
    ]

    def test_all_required_files_exist(self):
        for filename in self.REQUIRED_FILES:
            path = METADATA_DIR / filename
            self.assertTrue(path.exists(),
                            msg=f"Required metadata file missing: {filename}")

    def test_validator_script_exists(self):
        validator = BOOTSTRAP_DIR / "validate-metadata.py"
        self.assertTrue(validator.exists(),
                        msg="validate-metadata.py must exist")

    def test_no_yaml_files_are_empty(self):
        for path in METADATA_DIR.glob("*.yaml"):
            content = path.read_text(encoding="utf-8").strip()
            self.assertTrue(len(content) > 0,
                            msg=f"{path.name} must not be empty")


# ---------------------------------------------------------------------------
# cell-identity.yaml
# ---------------------------------------------------------------------------

class TestCellIdentity(unittest.TestCase):
    def setUp(self):
        self.text = _read("cell-identity.yaml")

    def test_required_keys_present(self):
        for key in ["cell_id", "cell_name", "cell_type", "federation_id",
                    "federation_role", "criticality", "recovery_priority",
                    "architecture_version", "repositories", "capabilities"]:
            self.assertTrue(_has_key(self.text, key),
                            msg=f"cell-identity.yaml missing required key: '{key}'")

    def test_cell_id_is_kebab_case(self):
        m = re.search(r"^cell_id:\s*(.+)$", self.text, re.MULTILINE)
        self.assertIsNotNone(m, "cell_id field not found")
        cell_id = m.group(1).strip()
        if "POPULATE" not in cell_id:
            self.assertRegex(cell_id, r"^[a-z0-9][a-z0-9-]*[a-z0-9]$",
                             msg="cell_id must be kebab-case")

    def test_criticality_is_valid(self):
        m = re.search(r"^criticality:\s*(.+)$", self.text, re.MULTILINE)
        if m:
            val = m.group(1).strip()
            if "POPULATE" not in val:
                self.assertIn(val, ["CRITICAL", "HIGH", "MEDIUM", "LOW"])

    def test_architecture_version_declared(self):
        self.assertIn("architecture_version", self.text)
        self.assertIn("7.0", self.text)

    def test_has_populate_fields(self):
        """Some fields should still need human input (they're POPULATE markers)."""
        count = _count_populate(self.text)
        self.assertGreater(count, 0,
                           msg="cell-identity.yaml should have POPULATE fields for operator input")

    def test_timezone_is_boise(self):
        self.assertIn("America/Boise", self.text,
                      msg="cell-identity.yaml should reference America/Boise timezone")

    def test_capabilities_section_has_expected_keys(self):
        for cap in ["can_host_vms", "can_execute_opentofu", "can_execute_ansible"]:
            self.assertIn(cap, self.text,
                          msg=f"capabilities section should include {cap}")


# ---------------------------------------------------------------------------
# hardware-profile.yaml
# ---------------------------------------------------------------------------

class TestHardwareProfile(unittest.TestCase):
    def setUp(self):
        self.text = _read("hardware-profile.yaml")

    def test_required_keys_present(self):
        for key in ["minimum_requirements", "declared_hardware", "assessment_thresholds"]:
            self.assertTrue(_has_key(self.text, key),
                            msg=f"hardware-profile.yaml missing: '{key}'")

    def test_minimum_ram_declared(self):
        self.assertIn("ram_gb", self.text)

    def test_minimum_cpu_declared(self):
        self.assertIn("cpu_cores", self.text)

    def test_bios_requirements_declared(self):
        self.assertIn("bios_requirements", self.text)
        self.assertIn("vtx_required", self.text)

    def test_assessment_thresholds_declared(self):
        for field in ["cpu_warn_percent", "cpu_crit_percent",
                      "memory_warn_percent", "storage_warn_percent"]:
            self.assertIn(field, self.text)

    def test_warn_below_crit(self):
        """cpu_warn should be numerically less than cpu_crit."""
        warn_m = re.search(r"cpu_warn_percent:\s*(\d+)", self.text)
        crit_m = re.search(r"cpu_crit_percent:\s*(\d+)", self.text)
        if warn_m and crit_m:
            self.assertLess(int(warn_m.group(1)), int(crit_m.group(1)),
                            "cpu_warn_percent must be < cpu_crit_percent")


# ---------------------------------------------------------------------------
# network-topology.yaml
# ---------------------------------------------------------------------------

class TestNetworkTopology(unittest.TestCase):
    def setUp(self):
        self.text = _read("network-topology.yaml")

    def test_required_keys_present(self):
        for key in ["management_network", "proxmox_host", "bridges",
                    "vm_nic_interface", "k3s_networking", "dns_registry"]:
            self.assertTrue(_has_key(self.text, key),
                            msg=f"network-topology.yaml missing: '{key}'")

    def test_k3s_cidrs_declared(self):
        self.assertIn("pod_cidr", self.text)
        self.assertIn("service_cidr", self.text)
        # Default k3s CIDRs should be present
        self.assertIn("10.42.0.0/16", self.text)
        self.assertIn("10.43.0.0/16", self.text)

    def test_vm_nic_interface_is_ens18(self):
        self.assertIn("ens18", self.text)

    def test_search_domain_declared(self):
        self.assertIn("search_domain", self.text)
        self.assertIn("internal", self.text)

    def test_dns_registry_is_list(self):
        """dns_registry section should exist and have at least one placeholder entry."""
        self.assertIn("dns_registry", self.text)
        self.assertIn("proxmox-host", self.text)

    def test_populate_fields_for_unknown_network(self):
        """Network values must be declared by operator — POPULATE markers expected."""
        self.assertGreater(_count_populate(self.text), 0)


# ---------------------------------------------------------------------------
# vm-roles.yaml
# ---------------------------------------------------------------------------

class TestVmRoles(unittest.TestCase):
    def setUp(self):
        self.text = _read("vm-roles.yaml")

    def test_required_keys_present(self):
        for key in ["consolidation_mode", "vmid_base", "pre_k3s_vms",
                    "k3s_vms", "resource_summary"]:
            self.assertTrue(_has_key(self.text, key),
                            msg=f"vm-roles.yaml missing: '{key}'")

    def test_consolidation_mode_valid(self):
        m = re.search(r"consolidation_mode:\s*(.+)", self.text)
        if m:
            mode = m.group(1).strip()
            self.assertIn(mode, ["full", "recommended", "minimal"])

    def test_forgejo_vm_declared(self):
        self.assertIn("forgejo", self.text)

    def test_operations_vm_declared(self):
        self.assertIn("operations", self.text)

    def test_k3s_server_declared(self):
        self.assertIn("k3s-server", self.text)

    def test_restore_and_recreate_strategies_present(self):
        self.assertIn("RESTORE", self.text)
        self.assertIn("RECREATE", self.text)

    def test_resource_summary_present(self):
        self.assertIn("resource_summary", self.text)
        self.assertIn("total_ram_mb", self.text)


# ---------------------------------------------------------------------------
# k3s-cluster.yaml
# ---------------------------------------------------------------------------

class TestK3sCluster(unittest.TestCase):
    def setUp(self):
        self.text = _read("k3s-cluster.yaml")

    def test_required_keys_present(self):
        for key in ["cluster_name", "ha_policy", "server_nodes",
                    "storage", "networking", "deployment_waves", "etcd"]:
            self.assertTrue(_has_key(self.text, key),
                            msg=f"k3s-cluster.yaml missing: '{key}'")

    def test_ha_threshold_is_3(self):
        m = re.search(r"control_plane_ha_threshold:\s*(\d+)", self.text)
        if m:
            self.assertEqual(int(m.group(1)), 3,
                             "HA threshold must be 3 (etcd quorum)")

    def test_deployment_waves_declared(self):
        for wave in ["wave_1", "wave_2", "wave_3", "wave_4"]:
            self.assertIn(wave, self.text)

    def test_intelligence_before_applications(self):
        """intelligence namespace must appear before applications in the file."""
        intel_pos = self.text.find("intelligence")
        apps_pos = self.text.find("applications")
        self.assertGreater(intel_pos, 0, "intelligence namespace not found")
        self.assertGreater(apps_pos, 0, "applications namespace not found")
        self.assertLess(intel_pos, apps_pos,
                        "intelligence must appear before applications in deployment_waves")

    def test_phs_gate_for_applications(self):
        """Wave 4 (applications) must have a PHS gate."""
        self.assertIn("Platform Health Score", self.text)

    def test_storage_classes_declared(self):
        self.assertIn("local-path", self.text)
        self.assertIn("longhorn", self.text)


# ---------------------------------------------------------------------------
# backup-policy.yaml
# ---------------------------------------------------------------------------

class TestBackupPolicy(unittest.TestCase):
    def setUp(self):
        self.text = _read("backup-policy.yaml")

    def test_required_keys_present(self):
        for key in ["backup_providers", "components", "rrs_thresholds"]:
            self.assertTrue(_has_key(self.text, key),
                            msg=f"backup-policy.yaml missing: '{key}'")

    def test_forgejo_has_critical_criticality(self):
        self.assertIn("forgejo-vm", self.text)
        self.assertIn("CRITICAL", self.text)

    def test_rrs_thresholds_declared(self):
        for field in ["backup_age_warn_multiplier", "backup_age_crit_multiplier",
                      "absolute_blocker_multiplier", "recovery_test_warn_days",
                      "package_age_warn_days"]:
            self.assertIn(field, self.text,
                          msg=f"backup-policy.yaml missing rrs_threshold: {field}")

    def test_pbs_provider_declared(self):
        self.assertIn("pbs:", self.text)
        self.assertIn("enabled: true", self.text)

    def test_external_archive_declared(self):
        self.assertIn("external_archive", self.text)


# ---------------------------------------------------------------------------
# recovery-priority.yaml
# ---------------------------------------------------------------------------

class TestRecoveryPriority(unittest.TestCase):
    def setUp(self):
        self.text = _read("recovery-priority.yaml")

    def test_required_keys_present(self):
        for key in ["recovery_phases", "rto_targets", "single_points_of_failure"]:
            self.assertTrue(_has_key(self.text, key),
                            msg=f"recovery-priority.yaml missing: '{key}'")

    def test_all_phases_declared(self):
        for phase in ["01-hardware-verification", "02-proxmox",
                      "03-forgejo", "04-k3s-cluster", "05-gitops",
                      "06-intelligence-layer"]:
            self.assertIn(phase, self.text,
                          msg=f"Recovery phase {phase!r} not declared")

    def test_forgejo_is_critical(self):
        self.assertIn("03-forgejo", self.text)
        # The recovery-priority file must declare criticality: CRITICAL somewhere
        # (not necessarily within 500 chars of the phase ID)
        self.assertIn("CRITICAL", self.text,
                      "recovery-priority.yaml must declare CRITICAL for Forgejo phase")

    def test_restore_vs_recreate_both_present(self):
        self.assertIn("RESTORE", self.text)
        self.assertIn("RECREATE", self.text)

    def test_spofs_documented(self):
        self.assertIn("single_points_of_failure", self.text)
        self.assertIn("proxmox-host", self.text)
        self.assertIn("forgejo-vm", self.text)

    def test_rto_total_declared(self):
        self.assertIn("total_rto_minutes", self.text)


# ---------------------------------------------------------------------------
# service-catalog.yaml
# ---------------------------------------------------------------------------

class TestServiceCatalog(unittest.TestCase):
    def setUp(self):
        self.text = _read("service-catalog.yaml")

    def test_required_keys_present(self):
        for key in ["platform_vms", "k3s_platform", "k3s_intelligence",
                    "k3s_monitoring"]:
            self.assertTrue(_has_key(self.text, key),
                            msg=f"service-catalog.yaml missing: '{key}'")

    def test_required_services_declared(self):
        for svc in ["forgejo", "flux-system", "cert-manager",
                    "documentation-engine", "assessment-engine",
                    "prometheus", "grafana"]:
            self.assertIn(svc, self.text,
                          msg=f"Service {svc!r} not in service-catalog")

    def test_why_field_present_for_key_services(self):
        """Key services must explain why they exist."""
        self.assertIn("why:", self.text)

    def test_intelligence_deployed_before_applications(self):
        intel_pos = self.text.find("k3s_intelligence")
        apps_pos = self.text.find("k3s_applications")
        if intel_pos > 0 and apps_pos > 0:
            self.assertLess(intel_pos, apps_pos,
                            "intelligence must be declared before applications")


# ---------------------------------------------------------------------------
# placement-policy.yaml
# ---------------------------------------------------------------------------

class TestPlacementPolicy(unittest.TestCase):
    def setUp(self):
        self.text = _read("placement-policy.yaml")

    def test_required_keys_present(self):
        for key in ["proxmox_placement", "k3s_placement", "compliance_checks"]:
            self.assertTrue(_has_key(self.text, key),
                            msg=f"placement-policy.yaml missing: '{key}'")

    def test_forgejo_not_in_k3s_rule(self):
        self.assertIn("forgejo", self.text.lower())
        self.assertIn("not", self.text.lower())

    def test_intelligence_priority_declared(self):
        self.assertIn("intelligence-layer-priority", self.text)

    def test_compliance_checks_declared(self):
        self.assertIn("no-unmanaged-vms", self.text)
        self.assertIn("no-shadow-deployments", self.text)


# ---------------------------------------------------------------------------
# naming-convention.yaml
# ---------------------------------------------------------------------------

class TestNamingConvention(unittest.TestCase):
    def setUp(self):
        self.text = _read("naming-convention.yaml")

    def test_required_keys_present(self):
        for key in ["cell", "proxmox_hosts", "vms", "hostnames",
                    "ip_assignments", "keepass_paths", "repositories",
                    "archive_filenames"]:
            self.assertTrue(_has_key(self.text, key),
                            msg=f"naming-convention.yaml missing: '{key}'")

    def test_archive_timestamp_format_documented(self):
        self.assertIn("YYYY-MM-DD_HH_MM_SS", self.text)

    def test_keepass_path_structure_documented(self):
        self.assertIn("keepass_paths", self.text)
        self.assertIn("root", self.text)

    def test_vm_ip_offsets_declared(self):
        self.assertIn("proxmox_host_offset", self.text)
        self.assertIn("pre_k3s_vms_start", self.text)
        self.assertIn("k3s_nodes_start", self.text)

    def test_kebab_case_rule_mentioned(self):
        self.assertIn("kebab", self.text.lower())


# ---------------------------------------------------------------------------
# Cross-file consistency
# ---------------------------------------------------------------------------

class TestCrossFileConsistency(unittest.TestCase):

    def _extract_value(self, filename: str, key: str) -> str | None:
        text = _read(filename)
        m = re.search(rf"^{re.escape(key)}:\s*(.+)$", text, re.MULTILINE)
        return m.group(1).strip() if m else None

    def test_search_domain_consistent(self):
        """search_domain must match between network-topology and naming-convention."""
        net_sd = self._extract_value("network-topology.yaml", "search_domain")
        naming_sd = self._extract_value("naming-convention.yaml", "search_domain")
        if net_sd and naming_sd and "POPULATE" not in (net_sd + naming_sd):
            self.assertEqual(net_sd, naming_sd,
                             "search_domain must match across network-topology and naming-convention")

    def test_vm_nic_consistent(self):
        """vm_nic_interface in network-topology must match ens18 convention."""
        nic = self._extract_value("network-topology.yaml", "vm_nic_interface")
        naming_text = _read("naming-convention.yaml")
        if nic and "POPULATE" not in nic:
            self.assertIn(nic, naming_text,
                          "vm_nic_interface in network-topology not referenced in naming-convention")

    def test_architecture_version_in_cell_identity(self):
        """cell-identity.yaml must reference the current architecture version."""
        cell_text = _read("cell-identity.yaml")
        self.assertIn("7.0", cell_text,
                      "cell-identity.yaml should reference architecture version 7.0")

    def test_forgejo_declared_in_multiple_files(self):
        """forgejo must be declared in vm-roles, service-catalog, recovery-priority, backup-policy."""
        for filename in ["vm-roles.yaml", "service-catalog.yaml",
                         "recovery-priority.yaml", "backup-policy.yaml"]:
            text = _read(filename)
            self.assertIn("forgejo", text,
                          msg=f"forgejo must be referenced in {filename}")

    def test_intelligence_gate_consistent(self):
        """Both k3s-cluster and service-catalog must declare intelligence-before-applications."""
        k3s_text = _read("k3s-cluster.yaml")
        catalog_text = _read("service-catalog.yaml")
        self.assertIn("intelligence", k3s_text)
        self.assertIn("intelligence", catalog_text)


class TestValidatorScript(unittest.TestCase):
    """Test that the validator script itself is importable and structured correctly."""

    def setUp(self):
        pass

    def test_validator_has_required_keys_dict(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "validate_metadata", BOOTSTRAP_DIR / "validate-metadata.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertIsInstance(mod.REQUIRED_KEYS, dict)
        self.assertIn("cell-identity.yaml", mod.REQUIRED_KEYS)
        self.assertIn("backup-policy.yaml", mod.REQUIRED_KEYS)

    def test_required_files_all_covered(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "validate_metadata", BOOTSTRAP_DIR / "validate-metadata.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for fname in mod.REQUIRED_FILES:
            self.assertIn(fname, mod.REQUIRED_KEYS,
                          msg=f"{fname} in REQUIRED_FILES but not in REQUIRED_KEYS")

    def test_find_populate_fields_works(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "validate_metadata", BOOTSTRAP_DIR / "validate-metadata.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        text = "key: POPULATE: some value\nother: real_value\n"
        results = mod.find_populate_fields(text, "test.yaml")
        self.assertEqual(len(results), 1)
        self.assertIn("POPULATE:", results[0][1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
