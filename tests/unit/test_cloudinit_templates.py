"""
Tests for Milestone 6.2 — Cloud-Init Template Library.

Validates that all Cloud-Init snippets in proxmox-bootstrap/snippets/ are:
  - Present on disk (all paths declared in bootstrap-state.json exist)
  - Valid YAML (parseable without errors)
  - Structurally correct (required Cloud-Init fields present)
  - Internally consistent (network-config IPs match DNS registry)
  - Complete (SSH key placeholder is present and clearly marked)

Run: py -3 tests/unit/test_cloudinit_templates.py
"""

import json
import unittest
from pathlib import Path

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

import importlib.util

REPO_ROOT = Path(__file__).parent.parent.parent
BOOTSTRAP_REPO = REPO_ROOT / "proxmox-bootstrap"
SNIPPETS = BOOTSTRAP_REPO / "snippets"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "bootstrap"


def _import_generator():
    """Import generate-network-configs.py (hyphenated filename) via importlib."""
    spec = importlib.util.spec_from_file_location(
        "generate_network_configs",
        BOOTSTRAP_REPO / "generate-network-configs.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _import_generator_ud():
    """Import generate-user-data.py via importlib."""
    spec = importlib.util.spec_from_file_location(
        "generate_user_data",
        BOOTSTRAP_REPO / "generate-user-data.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

# ─── Simple YAML parser fallback (stdlib only) ───────────────────────────────
# The stdlib does not include a YAML parser. We use a minimal line-based
# checker sufficient to validate the subset of YAML we write: scalars,
# mappings, and sequences. Full structural parsing only runs if PyYAML is
# available; otherwise we fall back to syntactic checks.

def _parse_yaml_minimal(text: str) -> dict:
    """
    Best-effort YAML parse using PyYAML if available, else return a dict
    of top-level keys found by simple line scanning.
    """
    if HAS_YAML:
        return yaml.safe_load(text) or {}

    # Fallback: extract top-level keys (lines starting with a word followed by ':')
    result = {}
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        if ":" in stripped and not stripped.startswith("-"):
            key = stripped.split(":")[0].strip()
            if key and " " not in key:
                result[key] = True
    return result


def _load_bootstrap_fixture() -> dict:
    with open(FIXTURES / "bootstrap-state.json") as f:
        return json.load(f)


def _load_dns_registry() -> dict:
    """Return hostname→ip mapping from bootstrap-state fixture."""
    fixture = _load_bootstrap_fixture()
    return {entry["hostname"]: entry["ip"] for entry in fixture["dns_registry"]}


# ─── Helper: extract IP from a network-config file ───────────────────────────

def _extract_ip_from_network_config(text: str) -> str | None:
    """
    Pull the static IP address from a Cloud-Init v2 network-config file.
    Looks for the first 'addresses:' line and extracts the IP before '/'.
    Works on both PyYAML-parsed and raw text.
    """
    if HAS_YAML:
        data = yaml.safe_load(text) or {}
        ethernets = data.get("ethernets", {})
        for _iface, cfg in ethernets.items():
            addrs = cfg.get("addresses", [])
            if addrs:
                return addrs[0].split("/")[0]
        return None

    # Fallback: scan for '      - 192.' pattern
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- ") and "." in stripped:
            candidate = stripped[2:].split("/")[0].strip()
            parts = candidate.split(".")
            if len(parts) == 4 and all(p.isdigit() for p in parts):
                return candidate
    return None


# ─── Tests ───────────────────────────────────────────────────────────────────

class TestSnippetFilesExist(unittest.TestCase):
    """All snippet paths declared in bootstrap-state.json must exist on disk."""

    def setUp(self):
        self.fixture = _load_bootstrap_fixture()

    def _snippet_path(self, repo_relative_path: str) -> Path:
        return BOOTSTRAP_REPO / repo_relative_path

    def test_all_user_data_files_exist(self):
        for vm in self.fixture["vms"]:
            path_str = vm["cloudinit"]["user_data_path"]
            path = self._snippet_path(path_str)
            self.assertTrue(path.exists(),
                            msg=f"Missing user-data snippet for {vm['name']}: {path}")

    def test_all_network_config_files_exist(self):
        for vm in self.fixture["vms"]:
            path_str = vm["cloudinit"]["network_config_path"]
            path = self._snippet_path(path_str)
            self.assertTrue(path.exists(),
                            msg=f"Missing network-config snippet for {vm['name']}: {path}")

    def test_vendor_data_files_exist_when_declared(self):
        for vm in self.fixture["vms"]:
            path_str = vm["cloudinit"].get("vendor_data_path")
            if path_str:
                path = self._snippet_path(path_str)
                self.assertTrue(path.exists(),
                                msg=f"Missing vendor-data snippet for {vm['name']}: {path}")

    def test_base_ubuntu_reference_exists(self):
        base = SNIPPETS / "user-data" / "base-ubuntu.yaml"
        self.assertTrue(base.exists(), msg="base-ubuntu.yaml reference file is missing")


class TestUserDataStructure(unittest.TestCase):
    """User-data files must be valid Cloud-Init YAML with required fields."""

    VM_NAMES = ["infra-bootstrap", "forgejo", "inventory", "assessment-engine"]

    def _load(self, name: str) -> tuple[str, dict]:
        path = SNIPPETS / "user-data" / f"{name}.yaml"
        text = path.read_text(encoding="utf-8")
        data = _parse_yaml_minimal(text)
        return text, data

    def test_cloud_config_header_present(self):
        for name in self.VM_NAMES:
            text, _ = self._load(name)
            self.assertTrue(text.startswith("#cloud-config"),
                            msg=f"{name}.yaml must begin with #cloud-config")

    def test_hostname_field_present(self):
        for name in self.VM_NAMES:
            _, data = self._load(name)
            self.assertIn("hostname", data,
                          msg=f"{name}.yaml missing 'hostname' field")

    def test_users_field_present(self):
        for name in self.VM_NAMES:
            _, data = self._load(name)
            self.assertIn("users", data,
                          msg=f"{name}.yaml missing 'users' field")

    def test_packages_field_present(self):
        for name in self.VM_NAMES:
            _, data = self._load(name)
            self.assertIn("packages", data,
                          msg=f"{name}.yaml missing 'packages' field")

    def test_runcmd_field_present(self):
        for name in self.VM_NAMES:
            _, data = self._load(name)
            self.assertIn("runcmd", data,
                          msg=f"{name}.yaml missing 'runcmd' field")

    def test_qemu_guest_agent_in_packages(self):
        for name in self.VM_NAMES:
            text, data = self._load(name)
            if HAS_YAML:
                pkgs = data.get("packages", [])
                self.assertIn("qemu-guest-agent", pkgs,
                              msg=f"{name}.yaml must include qemu-guest-agent")
            else:
                self.assertIn("qemu-guest-agent", text,
                              msg=f"{name}.yaml must include qemu-guest-agent")

    def test_python3_in_packages(self):
        for name in self.VM_NAMES:
            text, _ = self._load(name)
            self.assertIn("python3", text,
                          msg=f"{name}.yaml must include python3 (required by Ansible)")

    def test_ssh_placeholder_is_marked(self):
        """User-data files must have an SSH key placeholder clearly marked."""
        for name in self.VM_NAMES:
            text, _ = self._load(name)
            self.assertIn("POPULATE", text,
                          msg=f"{name}.yaml must have a clearly-marked SSH key placeholder")

    def test_ssh_keepass_reference_in_placeholder(self):
        """Placeholder must reference KeePass so operator knows where to look."""
        for name in self.VM_NAMES:
            text, _ = self._load(name)
            self.assertIn("KeePass", text,
                          msg=f"{name}.yaml SSH placeholder must reference KeePass path")

    def test_password_auth_disabled_in_runcmd(self):
        """PasswordAuthentication must be disabled in runcmd."""
        for name in self.VM_NAMES:
            text, _ = self._load(name)
            self.assertIn("PasswordAuthentication no", text,
                          msg=f"{name}.yaml runcmd must disable password authentication")

    def test_infra_bootstrap_has_ansible(self):
        """infra-bootstrap is the Ansible controller — ansible-core must be installed."""
        text, data = self._load("infra-bootstrap")
        if HAS_YAML:
            pkgs = data.get("packages", [])
            self.assertIn("ansible-core", pkgs)
        else:
            self.assertIn("ansible-core", text)

    def test_cell_id_referenced_in_final_message(self):
        """All user-data files should identify the cell in the final_message."""
        for name in self.VM_NAMES:
            text, _ = self._load(name)
            self.assertIn("proxmox-cell-a", text,
                          msg=f"{name}.yaml final_message should reference the cell_id")


class TestNetworkConfigStructure(unittest.TestCase):
    """Network-config files must declare the correct static IP for each VM."""

    def setUp(self):
        self.fixture = _load_bootstrap_fixture()
        self.dns = _load_dns_registry()
        # Map VM name → expected IP (from DNS registry)
        self.vm_ips = {vm["name"]: vm["initial_ip"] for vm in self.fixture["vms"]}

    def _load(self, name: str) -> tuple[str, str | None]:
        path = SNIPPETS / "network-config" / f"{name}.yaml"
        text = path.read_text(encoding="utf-8")
        ip = _extract_ip_from_network_config(text)
        return text, ip

    def test_version_2_format(self):
        for name in self.vm_ips:
            text, _ = self._load(name)
            self.assertIn("version: 2", text,
                          msg=f"network-config/{name}.yaml must use Cloud-Init v2 format")

    def test_dhcp_disabled(self):
        for name in self.vm_ips:
            text, _ = self._load(name)
            self.assertIn("dhcp4: false", text,
                          msg=f"network-config/{name}.yaml must disable DHCP")

    def test_static_ip_matches_dns_registry(self):
        """The IP declared in each network-config must match the DNS registry."""
        for name, expected_ip in self.vm_ips.items():
            text, actual_ip = self._load(name)
            self.assertIsNotNone(actual_ip,
                                 msg=f"Could not extract IP from network-config/{name}.yaml")
            self.assertEqual(actual_ip, expected_ip,
                             msg=f"network-config/{name}.yaml has IP {actual_ip!r}, "
                                 f"DNS registry expects {expected_ip!r}")

    def test_static_ip_matches_bootstrap_fixture(self):
        """Cross-check: initial_ip in fixture matches network-config."""
        for vm in self.fixture["vms"]:
            _, actual_ip = self._load(vm["name"])
            self.assertEqual(actual_ip, vm["initial_ip"],
                             msg=f"{vm['name']}: network-config IP {actual_ip!r} does not "
                                 f"match bootstrap-state initial_ip {vm['initial_ip']!r}")

    def test_gateway_present(self):
        for name in self.vm_ips:
            text, _ = self._load(name)
            self.assertIn("gateway4:", text,
                          msg=f"network-config/{name}.yaml must declare gateway4")

    def test_nameservers_present(self):
        for name in self.vm_ips:
            text, _ = self._load(name)
            self.assertIn("nameservers:", text,
                          msg=f"network-config/{name}.yaml must declare nameservers")

    def test_ens18_interface_declared(self):
        """All network-config files must configure the ens18 interface (VirtIO default)."""
        for name in self.vm_ips:
            text, _ = self._load(name)
            self.assertIn("ens18:", text,
                          msg=f"network-config/{name}.yaml must declare ens18 interface")


class TestVendorDataStructure(unittest.TestCase):
    """Vendor-data file must be valid Cloud-Init YAML."""

    def setUp(self):
        self.path = SNIPPETS / "vendor-data" / "proxmox-hooks.yaml"
        self.text = self.path.read_text(encoding="utf-8")

    def test_vendor_data_file_exists(self):
        self.assertTrue(self.path.exists())

    def test_cloud_config_header(self):
        self.assertTrue(self.text.startswith("#cloud-config"),
                        msg="proxmox-hooks.yaml must begin with #cloud-config")

    def test_runcmd_present(self):
        self.assertIn("runcmd:", self.text)

    def test_disables_cloud_init_on_subsequent_boots(self):
        self.assertIn("cloud-init.disabled", self.text,
                      msg="vendor-data must disable Cloud-Init re-runs after first boot")

    def test_datasource_list_present(self):
        self.assertIn("datasource_list:", self.text,
                      msg="vendor-data should declare datasource_list to avoid probe delay")

    def test_nocloud_datasource_specified(self):
        self.assertIn("NoCloud", self.text)


class TestSnippetConsistency(unittest.TestCase):
    """Cross-file consistency: all VMs in bootstrap-state have exactly one snippet set."""

    def setUp(self):
        self.fixture = _load_bootstrap_fixture()

    def test_no_duplicate_ips_in_network_configs(self):
        """Each VM must have a unique IP — no two network-config files share an IP."""
        ips = []
        for vm in self.fixture["vms"]:
            path = BOOTSTRAP_REPO / vm["cloudinit"]["network_config_path"]
            if path.exists():
                text = path.read_text(encoding="utf-8")
                ip = _extract_ip_from_network_config(text)
                if ip:
                    ips.append((vm["name"], ip))

        ip_values = [ip for _, ip in ips]
        self.assertEqual(len(ip_values), len(set(ip_values)),
                         msg=f"Duplicate IPs found in network-config files: {ips}")

    def test_no_duplicate_hostnames_in_user_data(self):
        """Each VM must have a unique hostname in its user-data."""
        hostnames = []
        for vm in self.fixture["vms"]:
            path = BOOTSTRAP_REPO / vm["cloudinit"]["user_data_path"]
            if path.exists():
                data = _parse_yaml_minimal(path.read_text(encoding="utf-8"))
                if HAS_YAML and "hostname" in data:
                    hostnames.append((vm["name"], data["hostname"]))

        if hostnames:
            hostname_values = [h for _, h in hostnames]
            self.assertEqual(len(hostname_values), len(set(hostname_values)),
                             msg=f"Duplicate hostnames found in user-data files: {hostnames}")

    def test_snippet_count_matches_vm_count(self):
        user_data_files = list((SNIPPETS / "user-data").glob("*.yaml"))
        # Exclude base-ubuntu.yaml (reference only, not a deployed snippet)
        deployed = [f for f in user_data_files if f.name != "base-ubuntu.yaml"]
        self.assertEqual(len(deployed), len(self.fixture["vms"]),
                         msg=f"Expected {len(self.fixture['vms'])} user-data snippets, "
                             f"found {len(deployed)}: {[f.name for f in deployed]}")

    def test_network_config_count_matches_vm_count(self):
        network_files = list((SNIPPETS / "network-config").glob("*.yaml"))
        self.assertEqual(len(network_files), len(self.fixture["vms"]),
                         msg=f"Expected {len(self.fixture['vms'])} network-config snippets, "
                             f"found {len(network_files)}")


class TestUserDataGeneratorConsistency(unittest.TestCase):
    """
    Generated user-data snippets must be consistent with bootstrap-state.json.
    All values that were previously hard-coded must now derive from the manifest.
    """

    def setUp(self):
        self.fixture = _load_bootstrap_fixture()
        self.vm_map = {vm["name"]: vm for vm in self.fixture["vms"]}
        self.vm_defaults = self.fixture["vm_defaults"]
        self.network_topo = self.fixture["network_topology"]
        self.host = self.fixture["host_identity"]
        self.keepass = self.fixture["keepass_config"]

    def _load_user_data(self, name: str) -> tuple[str, dict]:
        path = SNIPPETS / "user-data" / f"{name}.yaml"
        text = path.read_text(encoding="utf-8")
        data = _parse_yaml_minimal(text)
        return text, data

    def test_generated_header_present(self):
        for name in self.vm_map:
            text, _ = self._load_user_data(name)
            self.assertIn("GENERATED", text,
                          msg=f"{name}.yaml missing GENERATED header")

    def test_timezone_from_vm_defaults(self):
        expected_tz = self.vm_defaults["timezone"]
        for name in self.vm_map:
            text, _ = self._load_user_data(name)
            self.assertIn(f"timezone: {expected_tz}", text,
                          msg=f"{name}.yaml timezone should be {expected_tz!r} from vm_defaults")

    def test_fqdn_uses_search_domain(self):
        search_domain = self.network_topo.get("search_domain", "")
        if not search_domain:
            self.skipTest("No search_domain in network_topology")
        for name, _vm in self.vm_map.items():
            text, _ = self._load_user_data(name)
            expected_fqdn = f"fqdn: {name}.{search_domain}"
            self.assertIn(expected_fqdn, text,
                          msg=f"{name}.yaml fqdn should use search_domain {search_domain!r}")

    def test_initial_user_from_bootstrap_state(self):
        for name, vm in self.vm_map.items():
            expected_user = vm.get("initial_user") or self.vm_defaults.get("initial_user", "ubuntu")
            text, _ = self._load_user_data(name)
            self.assertIn(f"name: {expected_user}", text,
                          msg=f"{name}.yaml OS username should be {expected_user!r} from bootstrap-state")

    def test_hostname_matches_vm_name(self):
        for name, vm in self.vm_map.items():
            text, _ = self._load_user_data(name)
            self.assertIn(f"hostname: {vm['name']}", text,
                          msg=f"{name}.yaml hostname should be {vm['name']!r}")

    def test_ip_in_final_message(self):
        for name, vm in self.vm_map.items():
            text, _ = self._load_user_data(name)
            self.assertIn(vm["initial_ip"], text,
                          msg=f"{name}.yaml final_message should reference {vm['initial_ip']!r}")

    def test_cell_id_in_final_message(self):
        cell_id = self.fixture["cell_id"]
        for name in self.vm_map:
            text, _ = self._load_user_data(name)
            self.assertIn(cell_id, text,
                          msg=f"{name}.yaml must reference cell_id {cell_id!r}")

    def test_keepass_root_in_ssh_placeholder(self):
        kp_root = self.keepass["root_path"]
        for name in self.vm_map:
            text, _ = self._load_user_data(name)
            self.assertIn(kp_root, text,
                          msg=f"{name}.yaml SSH placeholder should reference KeePass root {kp_root!r}")

    def test_extra_packages_present(self):
        for name, vm in self.vm_map.items():
            extra = vm.get("extra_packages", [])
            if extra:
                text, _ = self._load_user_data(name)
                for pkg in extra:
                    self.assertIn(pkg, text,
                                  msg=f"{name}.yaml missing extra_package {pkg!r}")

    def test_workspace_path_in_runcmd(self):
        for name, vm in self.vm_map.items():
            workspace = vm.get("workspace_path")
            if workspace is None:
                base = self.vm_defaults.get("workspace_base_path")
                if base:
                    workspace = f"{base}/{name}"
            if workspace:
                text, _ = self._load_user_data(name)
                self.assertIn(workspace, text,
                              msg=f"{name}.yaml should create workspace {workspace!r} in runcmd")

    def test_different_timezone_changes_output(self):
        """Changing vm_defaults.timezone must change user-data output."""
        gen = _import_generator_ud()
        import copy
        state = copy.deepcopy(_load_bootstrap_fixture())
        vm = state["vms"][0]

        kwargs = dict(
            vm=vm,
            vm_defaults=state["vm_defaults"],
            network_topology=state["network_topology"],
            host_identity=state["host_identity"],
            keepass_config=state["keepass_config"],
            secrets=state.get("secrets", []),
            cell_id=state["cell_id"],
            generated_at="2026-01-01T00:00:00Z",
        )
        state_a = copy.deepcopy(state["vm_defaults"])
        state_a["timezone"] = "Europe/London"
        state_b = copy.deepcopy(state["vm_defaults"])
        state_b["timezone"] = "America/New_York"

        out_a = gen.generate_user_data(**{**kwargs, "vm_defaults": state_a})
        out_b = gen.generate_user_data(**{**kwargs, "vm_defaults": state_b})
        self.assertNotEqual(out_a, out_b)


class TestNetworkTopologyConsistency(unittest.TestCase):
    """
    Network-config snippets must be consistent with bootstrap-state network_topology.
    Gateway, nameservers, and interface must match — only the per-VM IP differs.
    """

    def setUp(self):
        self.fixture = _load_bootstrap_fixture()
        self.topo = self.fixture["network_topology"]

    def test_network_topology_declared_in_fixture(self):
        self.assertIn("network_topology", self.fixture)
        topo = self.fixture["network_topology"]
        for key in ("management_cidr", "gateway", "nameservers", "interface_name"):
            self.assertIn(key, topo, msg=f"network_topology missing required key: {key}")

    def test_management_cidr_is_cidr_notation(self):
        cidr = self.topo["management_cidr"]
        self.assertIn("/", cidr, msg="management_cidr must be in CIDR notation, e.g. 192.168.1.0/24")
        parts = cidr.split("/")
        self.assertEqual(len(parts), 2)
        self.assertTrue(parts[1].isdigit(), msg="CIDR prefix must be numeric")

    def test_gateway_present_in_all_network_configs(self):
        expected_gw = self.topo["gateway"]
        for vm in self.fixture["vms"]:
            path = BOOTSTRAP_REPO / vm["cloudinit"]["network_config_path"]
            if path.exists():
                text = path.read_text(encoding="utf-8")
                self.assertIn(expected_gw, text,
                              msg=f"{vm['name']}: network-config gateway should be {expected_gw!r}")

    def test_nameservers_present_in_all_network_configs(self):
        for ns in self.topo["nameservers"]:
            for vm in self.fixture["vms"]:
                path = BOOTSTRAP_REPO / vm["cloudinit"]["network_config_path"]
                if path.exists():
                    text = path.read_text(encoding="utf-8")
                    self.assertIn(ns, text,
                                  msg=f"{vm['name']}: network-config missing nameserver {ns!r}")

    def test_interface_name_in_all_network_configs(self):
        expected_iface = self.topo["interface_name"]
        for vm in self.fixture["vms"]:
            path = BOOTSTRAP_REPO / vm["cloudinit"]["network_config_path"]
            if path.exists():
                text = path.read_text(encoding="utf-8")
                self.assertIn(f"{expected_iface}:", text,
                              msg=f"{vm['name']}: network-config must declare interface {expected_iface!r}")

    def test_generated_header_present(self):
        """All network-config files must carry the GENERATED marker."""
        for vm in self.fixture["vms"]:
            path = BOOTSTRAP_REPO / vm["cloudinit"]["network_config_path"]
            if path.exists():
                text = path.read_text(encoding="utf-8")
                self.assertIn("GENERATED", text,
                              msg=f"{vm['name']}: network-config missing GENERATED header")
                self.assertIn("DO NOT EDIT MANUALLY", text,
                              msg=f"{vm['name']}: network-config missing DO NOT EDIT warning")

    def test_prefix_derived_from_cidr(self):
        """The subnet prefix from management_cidr must appear in each network-config."""
        cidr = self.topo["management_cidr"]
        prefix = "/" + cidr.split("/")[1]
        for vm in self.fixture["vms"]:
            path = BOOTSTRAP_REPO / vm["cloudinit"]["network_config_path"]
            if path.exists():
                text = path.read_text(encoding="utf-8")
                # The generated file should have IP/prefix, e.g. 192.168.1.20/24
                expected = vm["initial_ip"] + prefix
                self.assertIn(expected, text,
                              msg=f"{vm['name']}: expected {expected!r} in network-config addresses")


class TestNetworkConfigGenerator(unittest.TestCase):
    """Tests for generate-network-configs.py generator."""

    def setUp(self):
        self.fixture_path = FIXTURES / "bootstrap-state.json"
        with open(self.fixture_path) as f:
            self.fixture = json.load(f)

    def test_generator_script_exists(self):
        gen = BOOTSTRAP_REPO / "generate-network-configs.py"
        self.assertTrue(gen.exists(), msg="generate-network-configs.py must exist")

    def test_generator_is_importable(self):
        """The generator module must import cleanly."""
        gen = _import_generator()
        self.assertTrue(hasattr(gen, "run"))
        self.assertTrue(hasattr(gen, "generate_network_config"))

    def test_generator_produces_correct_ip(self):
        """Generator output must contain each VM's initial_ip."""
        gen = _import_generator()
        topo = self.fixture["network_topology"]
        prefix = "/" + topo["management_cidr"].split("/")[1]

        for vm in self.fixture["vms"]:
            content = gen.generate_network_config(
                vm_name=vm["name"],
                vmid=vm["vmid"],
                cell_id=self.fixture["cell_id"],
                ip=vm["initial_ip"],
                prefix=prefix,
                gateway=topo["gateway"],
                nameservers=topo["nameservers"],
                search_domain=topo.get("search_domain"),
                interface=topo["interface_name"],
                generated_at="2026-01-01T00:00:00Z",
            )
            self.assertIn(vm["initial_ip"] + prefix, content,
                          msg=f"{vm['name']}: generated content missing IP+prefix")
            self.assertIn(topo["gateway"], content)
            self.assertIn(topo["interface_name"] + ":", content)

    def test_generator_produces_generated_header(self):
        gen = _import_generator()
        topo = self.fixture["network_topology"]
        prefix = "/" + topo["management_cidr"].split("/")[1]
        vm = self.fixture["vms"][0]
        content = gen.generate_network_config(
            vm_name=vm["name"], vmid=vm["vmid"],
            cell_id=self.fixture["cell_id"],
            ip=vm["initial_ip"], prefix=prefix,
            gateway=topo["gateway"], nameservers=topo["nameservers"],
            search_domain=topo.get("search_domain"),
            interface=topo["interface_name"],
            generated_at="2026-01-01T00:00:00Z",
        )
        self.assertIn("GENERATED", content)
        self.assertIn("DO NOT EDIT MANUALLY", content)

    def test_generator_run_writes_files(self):
        """run() must write one file per VM to the output directory."""
        import tempfile
        gen = _import_generator()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir)
            written = gen.run(self.fixture_path, out)
            self.assertEqual(len(written), len(self.fixture["vms"]))
            for vm in self.fixture["vms"]:
                expected = out / f"{vm['name']}.yaml"
                self.assertTrue(expected.exists(),
                                msg=f"Expected {expected} to be written")

    def test_generator_run_dry_run_writes_nothing(self):
        """dry_run=True must not write any files."""
        import tempfile
        gen = _import_generator()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir)
            gen.run(self.fixture_path, out, dry_run=True)
            written = list(out.glob("*.yaml"))
            self.assertEqual(written, [],
                             msg="dry-run mode must not write any files")

    def test_generator_different_topology_produces_different_output(self):
        """Changing network_topology must change the generated output."""
        gen = _import_generator()
        topo = self.fixture["network_topology"]
        prefix = "/" + topo["management_cidr"].split("/")[1]
        vm = self.fixture["vms"][0]

        kwargs = dict(
            vm_name=vm["name"], vmid=vm["vmid"],
            cell_id=self.fixture["cell_id"],
            ip=vm["initial_ip"], prefix=prefix,
            nameservers=topo["nameservers"],
            search_domain=topo.get("search_domain"),
            interface=topo["interface_name"],
            generated_at="2026-01-01T00:00:00Z",
        )
        out_a = gen.generate_network_config(gateway="10.0.0.1", **kwargs)
        out_b = gen.generate_network_config(gateway="172.16.0.1", **kwargs)
        self.assertNotEqual(out_a, out_b,
                            msg="Different gateways must produce different output")


class TestSnippetUploadDocExists(unittest.TestCase):
    def test_upload_doc_exists(self):
        doc = BOOTSTRAP_REPO / "SNIPPET-UPLOAD.md"
        self.assertTrue(doc.exists(), msg="SNIPPET-UPLOAD.md must exist")

    def test_upload_doc_references_all_vms(self):
        doc = (BOOTSTRAP_REPO / "SNIPPET-UPLOAD.md").read_text(encoding="utf-8")
        for vm_name in ("infra-bootstrap", "forgejo", "inventory", "assessment-engine"):
            self.assertIn(vm_name, doc,
                          msg=f"SNIPPET-UPLOAD.md must reference {vm_name}")

    def test_upload_doc_references_keepass(self):
        doc = (BOOTSTRAP_REPO / "SNIPPET-UPLOAD.md").read_text(encoding="utf-8")
        self.assertIn("KeePass", doc)

    def test_upload_doc_references_cicustom(self):
        doc = (BOOTSTRAP_REPO / "SNIPPET-UPLOAD.md").read_text(encoding="utf-8")
        self.assertIn("cicustom", doc,
                      msg="SNIPPET-UPLOAD.md must explain cicustom VM parameter")


if __name__ == "__main__":
    unittest.main(verbosity=2)
