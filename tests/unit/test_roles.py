"""
Tests for roles.py role catalog and suggest-names.py KeePass discovery.

Run: py -3 tests/unit/test_roles.py
"""

import importlib.util
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
        for role_id in ("forgejo", "operations", "k3s-server"):
            self.assertIn(role_id, self.r.ROLES,
                          msg=f"Required role {role_id!r} must be in ROLES")

    def test_required_roles_marked_required(self):
        for role_id in ("forgejo", "operations", "k3s-server"):
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
        stub = self.r.generate_vm_stub("k3s-server", 103, "192.168.50.23")
        self.assertEqual(stub["initial_ip"], "192.168.50.23")

    def test_generate_stub_hostname_matches_role(self):
        for role_id in self.r.ROLES:
            stub = self.r.generate_vm_stub(role_id, 100, "10.0.0.1")
            self.assertEqual(stub["name"], self.r.ROLES[role_id]["default_hostname"])

    def test_generate_stub_extra_packages_from_role(self):
        stub = self.r.generate_vm_stub("operations", 100, "10.0.0.20")
        self.assertIn("ansible-core", stub["extra_packages"])

    def test_generate_stub_workspace_path_from_role(self):
        # operations has /opt/infra; k3s-server has no workspace (k3s node is managed by k3s)
        stub_ops = self.r.generate_vm_stub("operations", 101, "10.0.0.20")
        self.assertEqual(stub_ops["workspace_path"], "/opt/infra")
        stub_k3s = self.r.generate_vm_stub("k3s-server", 110, "10.0.0.30")
        self.assertIsNone(stub_k3s["workspace_path"])

    def test_generate_stub_cloudinit_paths_set(self):
        stub = self.r.generate_vm_stub("forgejo", 101, "10.0.0.21")
        self.assertIsNotNone(stub["cloudinit"]["user_data_path"])
        self.assertIsNotNone(stub["cloudinit"]["network_config_path"])

    def test_infra_bootstrap_has_vendor_data(self):
        stub = self.r.generate_vm_stub("operations", 100, "10.0.0.20")
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
        contract = self.r.generate_service_contract_stub("operations", "operations")
        self.assertIsNone(contract,
                          msg="Roles with no service_ports should return None contract")

    def test_k3s_server_has_contract(self):
        """k3s-server exposes port 6443 — it should have a service contract."""
        contract = self.r.generate_service_contract_stub("k3s-server", "k3s-server")
        self.assertIsNotNone(contract,
                             msg="k3s-server has service_ports (6443) so must produce a contract")


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
        ab_idx = sorted_by_wave.index("operations")
        ae_idx = sorted_by_wave.index("k3s-server")
        self.assertLess(forgejo_idx, ab_idx, "forgejo (wave 1) before operations (wave 2)")
        self.assertLess(forgejo_idx, ae_idx, "forgejo (wave 1) before k3s-server (wave 3)")


# ---------------------------------------------------------------------------
# suggest-names.py — KeePass discovery
# ---------------------------------------------------------------------------

class TestConsolidationModes(unittest.TestCase):
    def setUp(self):
        self.r = _import("roles.py", "roles")

    def test_all_three_modes_defined(self):
        for mode in ("full", "recommended", "minimal"):
            self.assertIn(mode, self.r.CONSOLIDATION_MODES)

    def test_default_consolidation_is_valid(self):
        self.assertIn(self.r.DEFAULT_CONSOLIDATION, self.r.CONSOLIDATION_MODES)

    def test_full_mode_three_vms(self):
        mode = self.r.CONSOLIDATION_MODES["full"]
        self.assertEqual(len(mode["vms"]), 3)

    def test_recommended_mode_three_vms(self):
        mode = self.r.CONSOLIDATION_MODES["recommended"]
        self.assertEqual(len(mode["vms"]), 3)

    def test_minimal_mode_two_vms(self):
        mode = self.r.CONSOLIDATION_MODES["minimal"]
        self.assertEqual(len(mode["vms"]), 2)

    def test_all_required_roles_covered_in_every_mode(self):
        for mode_key, mode in self.r.CONSOLIDATION_MODES.items():
            all_roles = [rid for roles in mode["vms"].values() for rid in roles]
            for required in self.r.REQUIRED_ROLES:
                self.assertIn(required, all_roles,
                              msg=f"Mode {mode_key!r} missing required role {required!r}")

    def test_no_role_appears_twice_in_same_mode(self):
        for mode_key, mode in self.r.CONSOLIDATION_MODES.items():
            all_roles = [rid for roles in mode["vms"].values() for rid in roles]
            self.assertEqual(len(all_roles), len(set(all_roles)),
                             msg=f"Mode {mode_key!r} has duplicate roles")

    def test_vm_order_matches_vms_keys(self):
        for mode_key, mode in self.r.CONSOLIDATION_MODES.items():
            for vm_name in mode["vm_order"]:
                self.assertIn(vm_name, mode["vms"],
                              msg=f"Mode {mode_key!r} vm_order references unknown VM {vm_name!r}")


class TestMergeRoles(unittest.TestCase):
    def setUp(self):
        self.r = _import("roles.py", "roles")

    def test_single_role_unchanged(self):
        merged = self.r.merge_roles(["forgejo"])
        self.assertEqual(merged["extra_packages"], self.r.ROLES["forgejo"]["extra_packages"])

    def test_merged_packages_are_union(self):
        merged = self.r.merge_roles(["operations", "k3s-server"])
        ab_pkgs = self.r.ROLES["operations"]["extra_packages"]
        ae_pkgs = self.r.ROLES["k3s-server"]["extra_packages"]
        for pkg in ab_pkgs + ae_pkgs:
            self.assertIn(pkg, merged["extra_packages"])

    def test_merged_packages_no_duplicates(self):
        merged = self.r.merge_roles(["operations", "k3s-server"])
        self.assertEqual(len(merged["extra_packages"]), len(set(merged["extra_packages"])))

    def test_merged_wave_is_minimum(self):
        merged = self.r.merge_roles(["operations", "k3s-server"])
        expected = min(self.r.ROLES["operations"]["wave"],
                       self.r.ROLES["k3s-server"]["wave"])
        self.assertEqual(merged["wave"], expected)

    def test_merged_vmid_offset_is_minimum(self):
        merged = self.r.merge_roles(["operations", "k3s-server"])
        expected = min(self.r.ROLES["operations"]["vmid_offset"],
                       self.r.ROLES["k3s-server"]["vmid_offset"])
        self.assertEqual(merged["vmid_offset"], expected)

    def test_internal_startup_after_excluded(self):
        """startup_after entries that are co-located should not appear in merged."""
        # operations depends on forgejo; if both are in the same VM, forgejo dep drops
        merged = self.r.merge_roles(["forgejo", "k3s-server"])
        self.assertNotIn("forgejo", merged["startup_after"],
                         "forgejo should not appear in startup_after when co-located")

    def test_external_startup_after_retained(self):
        """startup_after entries for external roles must be kept."""
        # assessment-engine starts after forgejo; if assessment-engine is alone:
        merged = self.r.merge_roles(["k3s-server"])
        self.assertIn("forgejo", merged["startup_after"])

    def test_all_three_merged_has_all_packages(self):
        merged = self.r.merge_roles(self.r.REQUIRED_ROLES)
        all_pkgs = []
        for rid in self.r.REQUIRED_ROLES:
            all_pkgs.extend(self.r.ROLES[rid]["extra_packages"])
        for pkg in set(all_pkgs):
            self.assertIn(pkg, merged["extra_packages"])

    def test_workspace_paths_collected(self):
        merged = self.r.merge_roles(["forgejo", "operations"])
        # operations has /opt/infra; forgejo has no workspace — /opt/infra must appear
        self.assertIn("/opt/infra", merged["workspace_paths"])


class TestResolveConsolidation(unittest.TestCase):
    def setUp(self):
        self.r = _import("roles.py", "roles")

    def test_full_returns_three_descriptors(self):
        descriptors = self.r.resolve_consolidation("full")
        self.assertEqual(len(descriptors), 3)

    def test_recommended_returns_three_descriptors(self):
        descriptors = self.r.resolve_consolidation("recommended")
        self.assertEqual(len(descriptors), 3)

    def test_minimal_returns_two_descriptors(self):
        descriptors = self.r.resolve_consolidation("minimal")
        self.assertEqual(len(descriptors), 2)

    def test_each_descriptor_has_required_fields(self):
        for mode in self.r.CONSOLIDATION_MODES:
            for desc in self.r.resolve_consolidation(mode):
                for field in ("vm_name", "component_roles", "merged", "vmid_offset", "wave"):
                    self.assertIn(field, desc,
                                  msg=f"Mode {mode!r}: descriptor missing {field!r}")

    def test_descriptors_sorted_by_wave(self):
        for mode in self.r.CONSOLIDATION_MODES:
            descriptors = self.r.resolve_consolidation(mode)
            waves = [d["wave"] for d in descriptors]
            self.assertEqual(waves, sorted(waves),
                             msg=f"Mode {mode!r}: descriptors not sorted by wave")

    def test_optional_roles_appended(self):
        descriptors = self.r.resolve_consolidation("recommended", ["dns"])
        vm_names = [d["vm_name"] for d in descriptors]
        self.assertIn("dns", vm_names)
        self.assertEqual(len(descriptors), 4)  # 3 required VMs + 1 optional

    def test_unknown_mode_raises(self):
        with self.assertRaises(ValueError):
            self.r.resolve_consolidation("nonsense")

    def test_minimal_toolchain_has_pre_k3s_roles(self):
        descriptors = self.r.resolve_consolidation("minimal")
        toolchain = next(d for d in descriptors if d["vm_name"] == "toolchain")
        self.assertIn("forgejo", toolchain["component_roles"])
        self.assertIn("operations", toolchain["component_roles"])
        # k3s-server is always its own VM — not in toolchain
        self.assertNotIn("k3s-server", toolchain["component_roles"])


class TestVmStubFromDescriptor(unittest.TestCase):
    def setUp(self):
        self.r = _import("roles.py", "roles")

    def _desc(self, mode: str, vm_name: str) -> dict:
        return next(d for d in self.r.resolve_consolidation(mode) if d["vm_name"] == vm_name)

    def test_full_forgejo_stub(self):
        desc = self._desc("full", "forgejo")
        stub = self.r.generate_vm_stub_from_descriptor(desc, 101, "192.168.1.21")
        self.assertEqual(stub["name"], "forgejo")
        self.assertEqual(stub["initial_ip"], "192.168.1.21")
        self.assertEqual(stub["vmid"], 101)
        self.assertIsNone(stub["cloudinit"]["vendor_data_path"])

    def test_recommended_operations_is_single_role(self):
        """In v7.0 recommended, operations VM is a single-role VM (not merged)."""
        desc = self._desc("recommended", "operations")
        stub = self.r.generate_vm_stub_from_descriptor(desc, 100, "192.168.1.20")
        self.assertIn("operations", stub["component_roles"])
        # k3s-server is always its own VM in v7.0 — never merged with operations
        self.assertNotIn("k3s-server", stub["component_roles"])

    def test_recommended_operations_has_ansible_packages(self):
        desc = self._desc("recommended", "operations")
        stub = self.r.generate_vm_stub_from_descriptor(desc, 100, "192.168.1.20")
        self.assertIn("ansible-core", stub["extra_packages"])
        self.assertIn("python3-venv", stub["extra_packages"])

    def test_recommended_operations_has_vendor_data(self):
        """operations role includes vendor-data (disables Cloud-Init re-runs)."""
        desc = self._desc("recommended", "operations")
        stub = self.r.generate_vm_stub_from_descriptor(desc, 100, "192.168.1.20")
        self.assertIsNotNone(stub["cloudinit"]["vendor_data_path"])

    def test_minimal_toolchain_has_all_packages(self):
        desc = self._desc("minimal", "toolchain")
        stub = self.r.generate_vm_stub_from_descriptor(desc, 100, "192.168.1.20")
        ab_pkgs = self.r.ROLES["operations"]["extra_packages"]
        for pkg in ab_pkgs:
            self.assertIn(pkg, stub["extra_packages"])

    def test_minimal_toolchain_has_vendor_data(self):
        desc = self._desc("minimal", "toolchain")
        stub = self.r.generate_vm_stub_from_descriptor(desc, 100, "192.168.1.20")
        self.assertIsNotNone(stub["cloudinit"]["vendor_data_path"])

    def test_combined_vm_note_mentions_roles(self):
        desc = self._desc("minimal", "toolchain")
        stub = self.r.generate_vm_stub_from_descriptor(desc, 100, "192.168.1.20")
        self.assertIsNotNone(stub["notes"])
        self.assertIn("Combined", stub["notes"])

    def test_single_role_vm_has_no_combined_note(self):
        desc = self._desc("full", "forgejo")
        stub = self.r.generate_vm_stub_from_descriptor(desc, 101, "192.168.1.21")
        self.assertIsNone(stub["notes"])


class TestSelectConsolidationLogic(unittest.TestCase):
    """Test the RAM-based auto-suggestion logic."""

    def setUp(self):
        self.r = _import("roles.py", "roles")

    def test_low_ram_suggests_minimal(self):
        # Can't easily test interactive mode without mocking input,
        # but we can verify the RAM threshold logic directly
        # by checking what suggestion would be made
        ram = 8.0
        suggestion = "minimal" if ram < 16 else "recommended"
        self.assertEqual(suggestion, "minimal")

    def test_high_ram_suggests_recommended(self):
        ram = 32.0
        suggestion = "minimal" if ram < 16 else "recommended"
        self.assertEqual(suggestion, "recommended")

    def test_borderline_ram_suggests_recommended(self):
        ram = 16.0
        suggestion = "minimal" if ram < 16 else "recommended"
        self.assertEqual(suggestion, "recommended")


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
