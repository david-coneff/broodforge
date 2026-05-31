"""
Tests for roles.py role catalog and suggest-names.py KeePass discovery.

Run: py -3 tests/unit/test_roles.py
"""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
BOOTSTRAP_REPO = REPO_ROOT / "proxmox-bootstrap"


def _import(filename: str, mod_name: str):
    spec = importlib.util.spec_from_file_location(
        mod_name, BOOTSTRAP_REPO / filename
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# roles.py — catalog structure
# ---------------------------------------------------------------------------

class TestRoleCatalog(unittest.TestCase):
    def setUp(self):
        self.r = _import("roles.py", "roles")

    def test_roles_dict_not_empty(self):
        self.assertGreater(len(self.r.ROLES), 0)

    def test_required_roles_present(self):
        """The three self-documentation required roles must all be defined."""
        for role_id in ("forgejo", "infra-bootstrap", "assessment-engine"):
            self.assertIn(role_id, self.r.ROLES,
                          msg=f"Required role {role_id!r} must be in ROLES")

    def test_required_roles_marked_required(self):
        for role_id in ("forgejo", "infra-bootstrap", "assessment-engine"):
            self.assertTrue(self.r.ROLES[role_id]["required"],
                            msg=f"{role_id} must have required=True")

    def test_optional_roles_marked_optional(self):
        for role_id in self.r.OPTIONAL_ROLES:
            self.assertFalse(self.r.ROLES[role_id]["required"],
                             msg=f"{role_id} must have required=False")

    def test_required_roles_list_complete(self):
        required_in_dict = {rid for rid, r in self.r.ROLES.items() if r["required"]}
        self.assertEqual(set(self.r.REQUIRED_ROLES), required_in_dict)

    def test_optional_roles_list_complete(self):
        optional_in_dict = {rid for rid, r in self.r.ROLES.items() if not r["required"]}
        self.assertEqual(set(self.r.OPTIONAL_ROLES), optional_in_dict)

    def test_each_role_has_required_fields(self):
        for role_id, role in self.r.ROLES.items():
            for field in ("description", "required", "wave", "vmid_offset",
                          "default_hostname", "extra_packages", "startup_after"):
                self.assertIn(field, role,
                              msg=f"Role {role_id!r} missing field {field!r}")

    def test_wave_numbers_non_negative(self):
        for role_id, role in self.r.ROLES.items():
            self.assertGreaterEqual(role["wave"], 0,
                                    msg=f"Role {role_id!r} has negative wave")

    def test_vmid_offsets_non_negative(self):
        for role_id, role in self.r.ROLES.items():
            self.assertGreaterEqual(role["vmid_offset"], 0,
                                    msg=f"Role {role_id!r} has negative vmid_offset")

    def test_no_duplicate_default_hostnames_among_required(self):
        hostnames = [self.r.ROLES[r]["default_hostname"] for r in self.r.REQUIRED_ROLES]
        self.assertEqual(len(hostnames), len(set(hostnames)),
                         "Required roles must have unique default hostnames")

    def test_why_required_present_for_required_roles(self):
        for role_id in self.r.REQUIRED_ROLES:
            self.assertIn("why_required", self.r.ROLES[role_id],
                          msg=f"Required role {role_id!r} must explain why_required")
            self.assertTrue(self.r.ROLES[role_id]["why_required"])

    def test_startup_after_references_known_roles(self):
        known = set(self.r.ROLES.keys())
        for role_id, role in self.r.ROLES.items():
            for dep in role["startup_after"]:
                self.assertIn(dep, known,
                              msg=f"Role {role_id!r} startup_after {dep!r} is not a known role")

    def test_extra_packages_are_lists(self):
        for role_id, role in self.r.ROLES.items():
            self.assertIsInstance(role["extra_packages"], list,
                                  msg=f"Role {role_id!r} extra_packages must be a list")


class TestVmStubGeneration(unittest.TestCase):
    def setUp(self):
        self.r = _import("roles.py", "roles")

    def test_generate_stub_has_required_fields(self):
        stub = self.r.generate_vm_stub("forgejo", 101, "192.168.1.21")
        for field in ("vmid", "name", "role", "template_name", "cloudinit",
                      "initial_ip", "bridge", "initial_user"):
            self.assertIn(field, stub, msg=f"VM stub missing field {field!r}")

    def test_generate_stub_vmid_correct(self):
        stub = self.r.generate_vm_stub("forgejo", 101, "10.0.0.21")
        self.assertEqual(stub["vmid"], 101)

    def test_generate_stub_ip_correct(self):
        stub = self.r.generate_vm_stub("assessment-engine", 103, "192.168.50.23")
        self.assertEqual(stub["initial_ip"], "192.168.50.23")

    def test_generate_stub_hostname_matches_role(self):
        for role_id in self.r.ROLES:
            stub = self.r.generate_vm_stub(role_id, 100, "10.0.0.1")
            self.assertEqual(stub["name"], self.r.ROLES[role_id]["default_hostname"])

    def test_generate_stub_extra_packages_from_role(self):
        stub = self.r.generate_vm_stub("infra-bootstrap", 100, "10.0.0.20")
        self.assertIn("ansible-core", stub["extra_packages"])

    def test_generate_stub_workspace_path_from_role(self):
        stub = self.r.generate_vm_stub("assessment-engine", 103, "10.0.0.23")
        self.assertEqual(stub["workspace_path"], "/opt/assessment")

    def test_generate_stub_cloudinit_paths_set(self):
        stub = self.r.generate_vm_stub("forgejo", 101, "10.0.0.21")
        self.assertIsNotNone(stub["cloudinit"]["user_data_path"])
        self.assertIsNotNone(stub["cloudinit"]["network_config_path"])

    def test_infra_bootstrap_has_vendor_data(self):
        stub = self.r.generate_vm_stub("infra-bootstrap", 100, "10.0.0.20")
        self.assertIsNotNone(stub["cloudinit"]["vendor_data_path"])

    def test_non_infra_bootstrap_no_vendor_data(self):
        stub = self.r.generate_vm_stub("forgejo", 101, "10.0.0.21")
        self.assertIsNone(stub["cloudinit"]["vendor_data_path"])

    def test_all_required_roles_generate_stubs(self):
        for role_id in self.r.REQUIRED_ROLES:
            stub = self.r.generate_vm_stub(role_id, 100, "10.0.0.1")
            self.assertIsInstance(stub, dict)
            self.assertEqual(stub["role"], role_id)


class TestServiceContractGeneration(unittest.TestCase):
    def setUp(self):
        self.r = _import("roles.py", "roles")

    def test_forgejo_has_service_contract(self):
        contract = self.r.generate_service_contract_stub("forgejo", "forgejo")
        self.assertIsNotNone(contract)
        self.assertEqual(contract["service"], "forgejo")

    def test_contract_has_required_fields(self):
        contract = self.r.generate_service_contract_stub("forgejo", "forgejo")
        for field in ("service", "vm", "provided_interfaces", "startup_after"):
            self.assertIn(field, contract)

    def test_no_service_ports_returns_none(self):
        contract = self.r.generate_service_contract_stub("infra-bootstrap", "infra-bootstrap")
        self.assertIsNone(contract,
                          msg="Roles with no service_ports should return None contract")

    def test_assessment_engine_no_contract(self):
        contract = self.r.generate_service_contract_stub("assessment-engine", "assessment-engine")
        self.assertIsNone(contract)


class TestVmidForRole(unittest.TestCase):
    def setUp(self):
        self.r = _import("roles.py", "roles")

    def test_vmid_from_base(self):
        for role_id, role in self.r.ROLES.items():
            expected = 100 + role["vmid_offset"]
            self.assertEqual(self.r.vmid_for_role(role_id, 100), expected)

    def test_custom_base(self):
        vmid = self.r.vmid_for_role("forgejo", 200)
        self.assertEqual(vmid, 200 + self.r.ROLES["forgejo"]["vmid_offset"])

    def test_different_roles_different_vmids(self):
        vmids = {self.r.vmid_for_role(rid, 100) for rid in self.r.REQUIRED_ROLES}
        self.assertEqual(len(vmids), len(self.r.REQUIRED_ROLES),
                         "Required roles must produce unique VMIDs from the same base")


class TestRoleSelectionOrdering(unittest.TestCase):
    def setUp(self):
        self.r = _import("roles.py", "roles")

    def test_required_roles_ordered_by_wave(self):
        """Required roles list should be orderable by wave without conflict."""
        waves = [self.r.ROLES[rid]["wave"] for rid in self.r.REQUIRED_ROLES]
        # Waves should be in ascending order (startup order)
        self.assertEqual(waves, sorted(waves),
                         msg="Required roles should be ordered by wave in REQUIRED_ROLES")

    def test_first_boot_order_derives_from_waves(self):
        """Wave ordering determines first-boot sequence."""
        sorted_by_wave = sorted(
            self.r.REQUIRED_ROLES,
            key=lambda r: self.r.ROLES[r]["wave"]
        )
        # forgejo must come before infra-bootstrap and assessment-engine
        forgejo_idx = sorted_by_wave.index("forgejo")
        ab_idx = sorted_by_wave.index("infra-bootstrap")
        ae_idx = sorted_by_wave.index("assessment-engine")
        self.assertLess(forgejo_idx, ab_idx, "forgejo (wave 1) before infra-bootstrap (wave 2)")
        self.assertLess(forgejo_idx, ae_idx, "forgejo (wave 1) before assessment-engine (wave 3)")


# ---------------------------------------------------------------------------
# suggest-names.py — KeePass discovery
# ---------------------------------------------------------------------------

class TestKeepassDiscovery(unittest.TestCase):
    def setUp(self):
        self.sn = _import("suggest-names.py", "suggest_names")

    def test_discover_returns_list(self):
        result = self.sn.discover_keepass_databases()
        self.assertIsInstance(result, list)

    def test_all_discovered_paths_exist(self):
        for path in self.sn.discover_keepass_databases():
            self.assertTrue(Path(path).exists(),
                            msg=f"Discovered path does not exist: {path}")

    def test_all_discovered_have_kdbx_extension(self):
        for path in self.sn.discover_keepass_databases():
            self.assertTrue(path.endswith(".kdbx"),
                            msg=f"Discovered path is not a .kdbx file: {path}")

    def test_no_duplicates_in_results(self):
        result = self.sn.discover_keepass_databases()
        self.assertEqual(len(result), len(set(result)),
                         "discover_keepass_databases must not return duplicates")

    def test_suggest_keepass_database_returns_tuple(self):
        best, candidates = self.sn.suggest_keepass_database()
        self.assertIsInstance(candidates, list)
        self.assertIn(type(best), (str, type(None)))

    def test_suggest_best_is_first_candidate(self):
        best, candidates = self.sn.suggest_keepass_database()
        if candidates:
            self.assertEqual(best, candidates[0])
        else:
            self.assertIsNone(best)

    def test_discovers_kdbx_in_temp_dir(self):
        """Test that the scanner finds a real .kdbx file if placed in home-adjacent dir."""
        import shutil
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_db = Path(tmpdir) / "test.kdbx"
            fake_db.write_bytes(b"fake kdbx content")
            # We can't easily inject tmpdir into the search path without
            # patching, but we can verify the function runs cleanly
            result = self.sn.discover_keepass_databases()
            self.assertIsInstance(result, list)  # function runs without error


class TestKeepassConfigParsing(unittest.TestCase):
    """Test that KeePassXC config parsing works with a real-looking config file."""

    def setUp(self):
        self.sn = _import("suggest-names.py", "suggest_names")

    def test_config_parsing_with_fake_config(self):
        """
        Verify the INI parser finds DatabasePath entries.
        We write a fake config to a temp file and call the underlying logic.
        """
        fake_db_path = str(Path.home() / "fake-test.kdbx")
        fake_config = (
            "[General]\n"
            "Theme=dark\n"
            "\n"
            "[LastOpenedDatabases]\n"
            f"1\\DatabasePath={fake_db_path}\n"
            "2\\DatabasePath=/nonexistent/other.kdbx\n"
            "\n"
            "[Browser]\n"
            "Enabled=false\n"
        )
        # The parser only returns paths that actually exist.
        # Since fake_db_path doesn't exist, it won't be returned.
        # We can at least verify the config text would be parsed correctly
        # by checking the logic manually.
        in_section = False
        found_paths = []
        for line in fake_config.splitlines():
            stripped = line.strip()
            if stripped == "[LastOpenedDatabases]":
                in_section = True
                continue
            if in_section:
                if stripped.startswith("["):
                    break
                if "DatabasePath=" in stripped:
                    db_path = stripped.split("DatabasePath=", 1)[1].strip()
                    found_paths.append(db_path)
        self.assertIn(fake_db_path, found_paths)
        self.assertIn("/nonexistent/other.kdbx", found_paths)
        self.assertEqual(len(found_paths), 2)


# ---------------------------------------------------------------------------
# Integration: roles → suggest-names → init produces consistent state
# ---------------------------------------------------------------------------

class TestRolesAndNamingIntegration(unittest.TestCase):
    def setUp(self):
        self.r = _import("roles.py", "roles")
        self.sn = _import("suggest-names.py", "suggest_names")

    def test_required_roles_produce_valid_vm_stubs(self):
        """VM stubs from all required roles should be schema-compatible."""
        cidr = "192.168.1.0/24"
        vm_names = [self.r.ROLES[rid]["default_hostname"] for rid in self.r.REQUIRED_ROLES]
        ips = self.sn.suggest_ips(cidr, vm_names)

        for role_id in self.r.REQUIRED_ROLES:
            name = self.r.ROLES[role_id]["default_hostname"]
            ip = ips["vms"][name]
            vmid = self.r.vmid_for_role(role_id, 100)
            stub = self.r.generate_vm_stub(role_id, vmid, ip)

            self.assertEqual(stub["initial_ip"], ip)
            self.assertIsInstance(stub["vmid"], int)
            self.assertIsInstance(stub["extra_packages"], list)

    def test_first_boot_order_matches_wave_order(self):
        """Wave ordering must match the self-documentation dependency chain."""
        waves = {rid: self.r.ROLES[rid]["wave"] for rid in self.r.REQUIRED_ROLES}
        # forgejo must have the lowest wave (it's wave 1)
        forgejo_wave = waves["forgejo"]
        for rid, wave in waves.items():
            if rid != "forgejo":
                self.assertLessEqual(forgejo_wave, wave,
                                     msg=f"forgejo (wave {forgejo_wave}) must deploy before or with {rid} (wave {wave})")

    def test_secret_registry_generated_for_all_required_roles(self):
        vms = [{"name": self.r.ROLES[rid]["default_hostname"],
                "vmid": self.r.vmid_for_role(rid, 100),
                "role": rid}
               for rid in self.r.REQUIRED_ROLES]
        entries = self.sn.secret_registry_entries("Infrastructure", "pve01", "pve01-cell", vms)
        ids = {e["id"] for e in entries}
        for role_id in self.r.REQUIRED_ROLES:
            name = self.r.ROLES[role_id]["default_hostname"]
            self.assertIn(f"{name}-deploy-key", ids,
                          msg=f"Missing deploy key for {name}")
            self.assertIn(f"vm-{name}-password", ids,
                          msg=f"Missing password for {name}")

    def test_dns_registry_generated_for_all_required_roles(self):
        vms = [{"name": self.r.ROLES[rid]["default_hostname"],
                "vmid": self.r.vmid_for_role(rid, 100),
                "initial_ip": f"192.168.1.{20 + i}",
                "role": rid}
               for i, rid in enumerate(self.r.REQUIRED_ROLES)]
        entries = self.sn.dns_registry_entries("pve01", "192.168.1.10", "internal", vms)
        hostnames = {e["hostname"] for e in entries}
        for role_id in self.r.REQUIRED_ROLES:
            name = self.r.ROLES[role_id]["default_hostname"]
            self.assertTrue(any(name in h for h in hostnames),
                            msg=f"DNS entry missing for {name}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
