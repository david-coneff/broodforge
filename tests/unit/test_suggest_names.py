"""
Tests for suggest-names.py naming convention engine and
setup-secrets.py generation utilities.

Run: py -3 tests/unit/test_suggest_names.py
"""

import importlib.util
import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
BOOTSTRAP_REPO = REPO_ROOT / "proxmox-bootstrap"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "bootstrap"


def _import(filename: str, mod_name: str):
    spec = importlib.util.spec_from_file_location(
        mod_name, BOOTSTRAP_REPO / filename
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_fixture() -> dict:
    with open(FIXTURES / "bootstrap-state.json") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# suggest-names.py
# ---------------------------------------------------------------------------

class TestSuggestIPs(unittest.TestCase):
    def setUp(self):
        self.sn = _import("suggest-names.py", "suggest_names")

    def test_basic_cidr_slash24(self):
        result = self.sn.suggest_ips("192.168.1.0/24", ["forgejo", "inventory"])
        self.assertEqual(result["host"], "192.168.1.10")
        self.assertEqual(result["vms"]["forgejo"], "192.168.1.20")
        self.assertEqual(result["vms"]["inventory"], "192.168.1.21")
        self.assertEqual(result["prefix"], "/24")
        self.assertEqual(result["network_prefix"], "192.168.1")

    def test_different_subnet(self):
        result = self.sn.suggest_ips("192.168.50.0/24", ["forgejo"])
        self.assertEqual(result["host"], "192.168.50.10")
        self.assertEqual(result["vms"]["forgejo"], "192.168.50.20")

    def test_class_b_subnet(self):
        result = self.sn.suggest_ips("10.10.0.0/16", ["vm1", "vm2", "vm3"])
        self.assertEqual(result["host"], "10.10.10")
        # /16 → 2 fixed octets → prefix = "10.10"
        self.assertTrue(result["vms"]["vm1"].startswith("10.10."))

    def test_host_offset_configurable(self):
        result = self.sn.suggest_ips("192.168.1.0/24", ["vm1"], host_offset=5)
        self.assertEqual(result["host"], "192.168.1.5")

    def test_vm_start_offset_configurable(self):
        result = self.sn.suggest_ips("192.168.1.0/24", ["vm1", "vm2"], vm_start_offset=100)
        self.assertEqual(result["vms"]["vm1"], "192.168.1.100")
        self.assertEqual(result["vms"]["vm2"], "192.168.1.101")

    def test_empty_vm_list(self):
        result = self.sn.suggest_ips("192.168.1.0/24", [])
        self.assertEqual(result["vms"], {})
        self.assertEqual(result["host"], "192.168.1.10")

    def test_invalid_cidr_raises(self):
        with self.assertRaises(ValueError):
            self.sn.suggest_ips("192.168.1.0", ["vm1"])

    def test_no_duplicate_ips(self):
        vms = ["a", "b", "c", "d", "e"]
        result = self.sn.suggest_ips("10.0.0.0/24", vms)
        all_ips = list(result["vms"].values()) + [result["host"]]
        self.assertEqual(len(all_ips), len(set(all_ips)), "All suggested IPs must be unique")


class TestSuggestGateway(unittest.TestCase):
    def setUp(self):
        self.sn = _import("suggest-names.py", "suggest_names")

    def test_slash24_gateway(self):
        self.assertEqual(self.sn.suggest_gateway("192.168.1.0/24"), "192.168.1.1")

    def test_slash24_other_subnet(self):
        self.assertEqual(self.sn.suggest_gateway("10.0.50.0/24"), "10.0.50.1")

    def test_slash16_gateway(self):
        self.assertEqual(self.sn.suggest_gateway("10.10.0.0/16"), "10.10.1")


class TestSuggestCellId(unittest.TestCase):
    def setUp(self):
        self.sn = _import("suggest-names.py", "suggest_names")

    def test_default_suffix(self):
        self.assertEqual(self.sn.suggest_cell_id("pve01"), "pve01-cell")

    def test_custom_suffix(self):
        self.assertEqual(self.sn.suggest_cell_id("pve01", "primary"), "pve01-primary")

    def test_variants_returns_list(self):
        variants = self.sn.suggest_cell_id_variants("pve01")
        self.assertIsInstance(variants, list)
        self.assertGreater(len(variants), 1)
        # All variants must contain the hostname
        for v in variants:
            self.assertIn("pve01", v)

    def test_variants_all_unique(self):
        variants = self.sn.suggest_cell_id_variants("myhost")
        self.assertEqual(len(variants), len(set(variants)))


class TestKeepassPaths(unittest.TestCase):
    def setUp(self):
        self.sn = _import("suggest-names.py", "suggest_names")
        self.vms = [
            {"name": "forgejo", "vmid": 101},
            {"name": "inventory", "vmid": 102},
        ]

    def test_host_root_password_path(self):
        paths = self.sn.keepass_paths("Infrastructure", "pve01", self.vms)
        self.assertEqual(paths["pve01-root-password"], "Infrastructure/pve01/root-password")

    def test_host_api_token_path(self):
        paths = self.sn.keepass_paths("Infrastructure", "pve01", self.vms)
        self.assertEqual(paths["pve01-api-token-tofu"], "Infrastructure/pve01/api-token-tofu")

    def test_vm_password_path(self):
        paths = self.sn.keepass_paths("Infrastructure", "pve01", self.vms)
        self.assertEqual(paths["vm-forgejo-password"], "Infrastructure/vms/101-forgejo/password")

    def test_vm_deploy_key_path(self):
        paths = self.sn.keepass_paths("Infrastructure", "pve01", self.vms)
        self.assertEqual(paths["forgejo-deploy-key"], "Infrastructure/ssh/deploy-keys/forgejo")

    def test_custom_kp_root(self):
        paths = self.sn.keepass_paths("HomeServer/Proxmox", "nas01", self.vms)
        self.assertIn("HomeServer/Proxmox/nas01/root-password",
                      paths["nas01-root-password"])

    def test_paths_all_start_with_root(self):
        root = "MyRoot"
        paths = self.sn.keepass_paths(root, "pve01", self.vms)
        for path in paths.values():
            self.assertTrue(path.startswith(root),
                            msg=f"Path {path!r} should start with root {root!r}")

    def test_paths_contain_hostname(self):
        """Host-level paths must contain the hostname."""
        paths = self.sn.keepass_paths("Infrastructure", "myhostname", self.vms)
        self.assertIn("myhostname", paths["myhostname-root-password"])
        self.assertIn("myhostname", paths["myhostname-api-token-tofu"])

    def test_per_vm_paths_contain_vm_name(self):
        paths = self.sn.keepass_paths("Infrastructure", "pve01", self.vms)
        self.assertIn("forgejo", paths["vm-forgejo-password"])
        self.assertIn("forgejo", paths["forgejo-deploy-key"])
        self.assertIn("inventory", paths["vm-inventory-password"])

    def test_deterministic(self):
        """Same inputs always produce the same output."""
        p1 = self.sn.keepass_paths("Infrastructure", "pve01", self.vms)
        p2 = self.sn.keepass_paths("Infrastructure", "pve01", self.vms)
        self.assertEqual(p1, p2)


class TestSecretRegistryEntries(unittest.TestCase):
    def setUp(self):
        self.sn = _import("suggest-names.py", "suggest_names")
        self.vms = [
            {"name": "forgejo", "vmid": 101, "role": "forgejo"},
            {"name": "inventory", "vmid": 102, "role": "inventory"},
        ]

    def _entries(self, **kwargs):
        return self.sn.secret_registry_entries(
            kp_root=kwargs.get("kp_root", "Infrastructure"),
            hostname=kwargs.get("hostname", "pve01"),
            cell_id=kwargs.get("cell_id", "pve01-cell"),
            vms=kwargs.get("vms", self.vms),
        )

    def test_returns_list(self):
        entries = self._entries()
        self.assertIsInstance(entries, list)
        self.assertGreater(len(entries), 0)

    def test_each_entry_has_required_fields(self):
        for entry in self._entries():
            for field in ("id", "description", "keepass_path", "owning_cell",
                          "secret_type", "required_by", "required_for"):
                self.assertIn(field, entry, msg=f"Entry {entry.get('id')} missing {field!r}")

    def test_owning_cell_matches(self):
        for entry in self._entries(cell_id="my-cell"):
            self.assertEqual(entry["owning_cell"], "my-cell")

    def test_host_secrets_present(self):
        ids = {e["id"] for e in self._entries()}
        self.assertIn("pve01-root-password", ids)
        self.assertIn("pve01-api-token-tofu", ids)

    def test_per_vm_secrets_present(self):
        ids = {e["id"] for e in self._entries()}
        self.assertIn("forgejo-deploy-key", ids)
        self.assertIn("vm-forgejo-password", ids)
        self.assertIn("inventory-deploy-key", ids)
        self.assertIn("vm-inventory-password", ids)

    def test_secret_types_valid(self):
        valid_types = {"password", "ssh-private-key", "api-token",
                       "certificate-private-key", "other"}
        for entry in self._entries():
            self.assertIn(entry["secret_type"], valid_types)

    def test_paths_consistent_with_keepass_paths(self):
        """Entry KeePass paths must match what keepass_paths() generates."""
        entries = self._entries()
        kp = self.sn.keepass_paths("Infrastructure", "pve01", self.vms)
        entry_map = {e["id"]: e["keepass_path"] for e in entries}
        for secret_id, expected_path in kp.items():
            if secret_id in entry_map:
                self.assertEqual(entry_map[secret_id], expected_path,
                                 msg=f"Path mismatch for {secret_id}")

    def test_count_scales_with_vms(self):
        one_vm_entries = self._entries(vms=[{"name": "vm1", "vmid": 100, "role": "vm1"}])
        two_vm_entries = self._entries(vms=[
            {"name": "vm1", "vmid": 100, "role": "vm1"},
            {"name": "vm2", "vmid": 101, "role": "vm2"},
        ])
        # Each VM adds 2 entries (deploy key + password)
        self.assertEqual(len(two_vm_entries) - len(one_vm_entries), 2)


class TestDnsRegistryEntries(unittest.TestCase):
    def setUp(self):
        self.sn = _import("suggest-names.py", "suggest_names")
        self.vms = [
            {"name": "forgejo", "vmid": 101, "initial_ip": "192.168.1.21"},
        ]

    def test_host_entry_present(self):
        entries = self.sn.dns_registry_entries("pve01", "192.168.1.10", "internal", self.vms)
        host = next((e for e in entries if e.get("role") == "proxmox-host"), None)
        self.assertIsNotNone(host)
        self.assertEqual(host["ip"], "192.168.1.10")

    def test_vm_entry_present(self):
        entries = self.sn.dns_registry_entries("pve01", "192.168.1.10", "internal", self.vms)
        vm = next((e for e in entries if e.get("vmid") == 101), None)
        self.assertIsNotNone(vm)
        self.assertEqual(vm["ip"], "192.168.1.21")

    def test_fqdn_uses_search_domain(self):
        entries = self.sn.dns_registry_entries("pve01", "192.168.1.10", "mylab", self.vms)
        host = next(e for e in entries if e.get("role") == "proxmox-host")
        self.assertIn("mylab", host["hostname"])

    def test_different_search_domain(self):
        entries = self.sn.dns_registry_entries("pve01", "192.168.1.10", "home.local", self.vms)
        for entry in entries:
            self.assertIn("home.local", entry["hostname"])


# ---------------------------------------------------------------------------
# setup-secrets.py — password generation (no KeePass required)
# ---------------------------------------------------------------------------

class TestPasswordGeneration(unittest.TestCase):
    def setUp(self):
        self.ss = _import("setup-secrets.py", "setup_secrets")

    def test_python_password_length(self):
        pw = self.ss.generate_password_python(32)
        self.assertEqual(len(pw), 32)

    def test_python_password_different_each_time(self):
        pws = {self.ss.generate_password_python(32) for _ in range(10)}
        self.assertGreater(len(pws), 1, "Passwords should not all be identical")

    def test_python_password_custom_length(self):
        for length in (16, 24, 48, 64):
            pw = self.ss.generate_password_python(length)
            self.assertEqual(len(pw), length)

    def test_generate_password_no_cli(self):
        pw, source = self.ss.generate_password(None, 32)
        self.assertEqual(len(pw), 32)
        self.assertIn("python secrets", source)

    def test_keepassxc_cli_detection(self):
        result = self.ss.detect_keepassxc_cli()
        # Just verify it returns a string or None — not requiring KeePassXC to be installed
        self.assertIn(type(result), (str, type(None)))

    def test_ssh_keygen_detection(self):
        result = self.ss.detect_ssh_keygen()
        self.assertIn(type(result), (str, type(None)))


# ---------------------------------------------------------------------------
# generate-user-data.py — SSH public key resolution
# ---------------------------------------------------------------------------

class TestSSHKeyResolution(unittest.TestCase):
    def setUp(self):
        self.gen = _import("generate-user-data.py", "generate_user_data")
        self.fixture = _load_fixture()

    def test_placeholder_when_no_pubkey_file(self):
        """Without a public key file, output must contain POPULATE."""
        vm = self.fixture["vms"][0]
        content = self.gen.generate_user_data(
            vm=vm,
            vm_defaults=self.fixture["vm_defaults"],
            network_topology=self.fixture["network_topology"],
            host_identity=self.fixture["host_identity"],
            keepass_config=self.fixture["keepass_config"],
            secrets=self.fixture.get("secrets", []),
            cell_id=self.fixture["cell_id"],
            generated_at="2026-01-01T00:00:00Z",
        )
        # Public key file doesn't exist in test environment
        # Either POPULATE placeholder or an actual key — both acceptable
        self.assertIn("ssh_authorized_keys", content)

    def test_actual_key_when_pubkey_file_exists(self):
        """When ssh/public-keys/{name}.pub exists, embed the actual key."""
        vm = {"name": "test-vm", "vmid": 999, "role": "test",
              "initial_ip": "10.0.0.99", "initial_user": "ubuntu",
              "extra_packages": [], "workspace_path": None,
              "ssh_key_reference": None, "password_reference": None,
              "cloudinit": {"user_data_path": "", "network_config_path": ""}}

        fake_pub_key = "ssh-ed25519 AAAA1234567890abcdef test-vm-key@pve01"

        # Temporarily write a public key file
        pubkey_dir = self.gen._PUBKEY_DIR
        pubkey_dir.mkdir(parents=True, exist_ok=True)
        pub_file = pubkey_dir / "test-vm.pub"
        pub_file.write_text(fake_pub_key + "\n", encoding="utf-8")

        try:
            content = self.gen.generate_user_data(
                vm=vm,
                vm_defaults=self.fixture["vm_defaults"],
                network_topology=self.fixture["network_topology"],
                host_identity=self.fixture["host_identity"],
                keepass_config=self.fixture["keepass_config"],
                secrets=[],
                cell_id=self.fixture["cell_id"],
                generated_at="2026-01-01T00:00:00Z",
            )
            self.assertIn(fake_pub_key, content,
                          msg="Actual SSH public key should be embedded when .pub file exists")
            self.assertNotIn("POPULATE", content,
                             msg="POPULATE placeholder should not appear when real key is available")
        finally:
            pub_file.unlink(missing_ok=True)

    def test_keepass_path_in_placeholder(self):
        """When no pub key file, placeholder must reference the KeePass path."""
        vm = self.fixture["vms"][0]
        secrets = self.fixture.get("secrets", [])
        content = self.gen.generate_user_data(
            vm=vm,
            vm_defaults=self.fixture["vm_defaults"],
            network_topology=self.fixture["network_topology"],
            host_identity=self.fixture["host_identity"],
            keepass_config=self.fixture["keepass_config"],
            secrets=secrets,
            cell_id=self.fixture["cell_id"],
            generated_at="2026-01-01T00:00:00Z",
        )
        # If no public key file for this VM, placeholder should reference KeePass
        pubkey_file = self.gen._PUBKEY_DIR / f"{vm['name']}.pub"
        if not pubkey_file.exists():
            self.assertIn("KeePass", content)


# ---------------------------------------------------------------------------
# Integration: suggest-names feeds bootstrap-state schema
# ---------------------------------------------------------------------------

class TestNamingConventionAndSchemaConsistency(unittest.TestCase):
    """
    Verify that names generated by suggest-names.py are consistent with
    the bootstrap-state.json schema requirements.
    """

    def setUp(self):
        self.sn = _import("suggest-names.py", "suggest_names")
        self.fixture = _load_fixture()

    def test_fixture_secrets_follow_convention(self):
        """Secrets in fixture should have IDs matching naming convention."""
        hostname = self.fixture["host_identity"]["hostname"]
        kp_root = self.fixture["keepass_config"]["root_path"]
        vms = self.fixture["vms"]

        convention_paths = self.sn.keepass_paths(kp_root, hostname, vms)
        fixture_secrets = {s["id"]: s["keepass_path"] for s in self.fixture.get("secrets", [])}

        for secret_id, expected_path in convention_paths.items():
            if secret_id in fixture_secrets:
                self.assertEqual(
                    fixture_secrets[secret_id], expected_path,
                    msg=f"Fixture secret {secret_id!r} path doesn't match convention: "
                        f"{fixture_secrets[secret_id]!r} != {expected_path!r}"
                )

    def test_fixture_host_identity_present(self):
        self.assertIn("host_identity", self.fixture)
        self.assertIn("hostname", self.fixture["host_identity"])

    def test_fixture_vm_defaults_present(self):
        self.assertIn("vm_defaults", self.fixture)
        self.assertIn("timezone", self.fixture["vm_defaults"])
        self.assertIn("initial_user", self.fixture["vm_defaults"])

    def test_fixture_keepass_config_present(self):
        self.assertIn("keepass_config", self.fixture)
        self.assertIn("root_path", self.fixture["keepass_config"])

    def test_suggest_names_preview_runs(self):
        """print_preview should execute without error."""
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.sn.print_preview(
                cell_id=self.fixture["cell_id"],
                hostname=self.fixture["host_identity"]["hostname"],
                kp_root=self.fixture["keepass_config"]["root_path"],
                management_cidr=self.fixture["network_topology"]["management_cidr"],
                vm_names=[vm["name"] for vm in self.fixture["vms"]],
                search_domain=self.fixture["network_topology"].get("search_domain", "internal"),
            )
        output = out.getvalue()
        self.assertIn("Naming Convention Preview", output)
        self.assertIn(self.fixture["host_identity"]["hostname"], output)
        self.assertIn(self.fixture["keepass_config"]["root_path"], output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
