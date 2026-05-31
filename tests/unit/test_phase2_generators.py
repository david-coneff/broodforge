"""
Tests for Phase 2 generators.

Covers:
  - tofu-vars.py:              HCL variable generation, per-VM files, cell file
  - cloud-init-gen.py:         bootstrap-state bridge, naming plan translation
  - ansible-inventory-gen.py:  group assignment, YAML structure, role routing
  - k3s-config-gen.py:         single-node vs HA config, TLS SANs, etcd mode
  - flux-bootstrap-gen.py:     script content, Forgejo URL, prerequisite comments

Run: py -3 tests/unit/test_phase2_generators.py
"""

import importlib.util
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
BOOTSTRAP_DIR = REPO_ROOT / "proxmox-bootstrap"
GENERATORS_DIR = BOOTSTRAP_DIR / "generators"


def _import(rel_path: str, mod_name: str):
    spec = importlib.util.spec_from_file_location(
        mod_name, BOOTSTRAP_DIR / rel_path
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

NAMING_PLAN = {
    "generated_at": "2026-05-31 17:00:00 UTC",
    "cell_id": "proxmox-cell-a",
    "hostname": "pve01",
    "fqdn": "pve01.internal",
    "kp_root": "Infrastructure",
    "management_cidr": "192.168.1.0/24",
    "search_domain": "internal",
    "host_ip": "192.168.1.10",
    "vms": [
        {
            "name": "forgejo",
            "vmid": 100,
            "role": "forgejo",
            "hostname": "forgejo",
            "fqdn": "forgejo.internal",
            "ip": "192.168.1.20",
            "cidr_notation": "192.168.1.20/24",
        },
        {
            "name": "operations",
            "vmid": 101,
            "role": "operations",
            "hostname": "operations",
            "fqdn": "operations.internal",
            "ip": "192.168.1.21",
            "cidr_notation": "192.168.1.21/24",
        },
        {
            "name": "k3s-server-01",
            "vmid": 110,
            "role": "k3s-server",
            "hostname": "k3s-server-01",
            "fqdn": "k3s-server-01.internal",
            "ip": "192.168.1.30",
            "cidr_notation": "192.168.1.30/24",
        },
    ],
    "keepass_paths": {"forgejo": "Infrastructure/VMs/forgejo"},
    "secret_registry": [],
    "dns_registry": [],
    "repository_names": {
        "bootstrap": "proxmox-cell-a-bootstrap",
        "infrastructure": "proxmox-cell-a-infrastructure",
        "ansible": "proxmox-cell-a-ansible",
        "platform-config": "proxmox-cell-a-platform-config",
        "docs": "proxmox-cell-a-docs",
        "assessment-history": "proxmox-cell-a-assessment-history",
    },
    "archive_prefix": "proxmox-cell-a",
    "warnings": [],
    "errors": [],
}

CLUSTER_PLAN_SINGLE = {
    "generated_at": "2026-05-31 17:00:00 UTC",
    "ha": {"enabled": False, "threshold": 3, "current_physical_hosts": 1},
    "server_nodes": {
        "count": 1,
        "ram_mb_each": 3072,
        "vcpus_each": 4,
        "disk_gb_each": 60,
        "embedded_etcd": False,
        "also_worker": True,
    },
    "pre_k3s_vms": {
        "forgejo": {"ram_mb": 1536, "vcpus": 2, "disk_gb": 40},
        "operations": {"ram_mb": 1536, "vcpus": 2, "disk_gb": 20},
    },
    "storage": {"initial_class": "local-path", "phase11_class": "longhorn"},
    "warnings": [],
    "recommendations": [],
}

CLUSTER_PLAN_HA = {
    **CLUSTER_PLAN_SINGLE,
    "ha": {"enabled": True, "threshold": 3, "current_physical_hosts": 3},
    "server_nodes": {
        "count": 3,
        "ram_mb_each": 3072,
        "vcpus_each": 4,
        "disk_gb_each": 60,
        "embedded_etcd": True,
        "also_worker": False,
    },
}

NAMING_PLAN_HA = {
    **NAMING_PLAN,
    "vms": [
        *NAMING_PLAN["vms"],
        {
            "name": "k3s-server-02",
            "vmid": 111,
            "role": "k3s-server",
            "hostname": "k3s-server-02",
            "fqdn": "k3s-server-02.internal",
            "ip": "192.168.1.31",
            "cidr_notation": "192.168.1.31/24",
        },
        {
            "name": "k3s-server-03",
            "vmid": 112,
            "role": "k3s-server",
            "hostname": "k3s-server-03",
            "fqdn": "k3s-server-03.internal",
            "ip": "192.168.1.32",
            "cidr_notation": "192.168.1.32/24",
        },
    ],
}

STORAGE_PLAN = {
    "pools": [{"name": "rpool", "topology": "mirror", "purpose": "primary"}],
    "recommended_datastores": [
        {"name": "local", "use": "iso_templates"},
        {"name": "local-lvm", "use": "vm_disks"},
    ],
    "ashift": 12,
    "warnings": [],
    "errors": [],
    "disk_inventory": [],
}

NETWORK_PLAN = {
    "overall": "GREEN",
    "red_count": 0,
    "yellow_count": 0,
    "green_count": 5,
    "validated_topology": {
        "gateway": "192.168.1.1",
        "nameservers": ["192.168.1.1", "8.8.8.8"],
        "search_domain": "internal",
        "bridge": "vmbr0",
    },
    "findings": [],
}

K3S_META = {
    "cluster_name": "homelab-k3s",
    "networking": {
        "pod_cidr": "10.42.0.0/16",
        "service_cidr": "10.43.0.0/16",
    },
}


# ---------------------------------------------------------------------------
# tofu-vars.py tests
# ---------------------------------------------------------------------------

class TestTofuVarsGenerator(unittest.TestCase):
    def setUp(self):
        self.gen = _import("generators/tofu-vars.py", "tofu_vars")

    def test_cell_file_in_output(self):
        outputs = self.gen.generate_tofu_vars(NAMING_PLAN, CLUSTER_PLAN_SINGLE, STORAGE_PLAN)
        self.assertIn("cell.auto.tfvars", outputs)

    def test_cell_file_has_cell_id(self):
        outputs = self.gen.generate_tofu_vars(NAMING_PLAN, CLUSTER_PLAN_SINGLE, STORAGE_PLAN)
        self.assertEqual(outputs["cell.auto.tfvars"]["cell_id"], "proxmox-cell-a")

    def test_per_vm_files_generated(self):
        outputs = self.gen.generate_tofu_vars(NAMING_PLAN, CLUSTER_PLAN_SINGLE, STORAGE_PLAN)
        self.assertIn("forgejo/terraform.auto.tfvars", outputs)
        self.assertIn("operations/terraform.auto.tfvars", outputs)
        self.assertIn("k3s-server-01/terraform.auto.tfvars", outputs)

    def test_vm_file_has_required_fields(self):
        outputs = self.gen.generate_tofu_vars(NAMING_PLAN, CLUSTER_PLAN_SINGLE, STORAGE_PLAN)
        vm = outputs["forgejo/terraform.auto.tfvars"]
        for field in ("cell_id", "vm_name", "vmid", "vm_ip", "vm_cidr",
                      "vcpus", "ram_mb", "disk_gb", "bridge"):
            self.assertIn(field, vm, msg=f"Missing field: {field}")

    def test_vm_ip_from_naming_plan(self):
        outputs = self.gen.generate_tofu_vars(NAMING_PLAN, CLUSTER_PLAN_SINGLE, STORAGE_PLAN)
        self.assertEqual(outputs["forgejo/terraform.auto.tfvars"]["vm_ip"], "192.168.1.20")

    def test_vmid_correct(self):
        outputs = self.gen.generate_tofu_vars(NAMING_PLAN, CLUSTER_PLAN_SINGLE, STORAGE_PLAN)
        self.assertEqual(outputs["forgejo/terraform.auto.tfvars"]["vmid"], 100)
        self.assertEqual(outputs["k3s-server-01/terraform.auto.tfvars"]["vmid"], 110)

    def test_gateway_from_network_plan(self):
        outputs = self.gen.generate_tofu_vars(
            NAMING_PLAN, CLUSTER_PLAN_SINGLE, STORAGE_PLAN, NETWORK_PLAN
        )
        self.assertEqual(outputs["cell.auto.tfvars"]["gateway"], "192.168.1.1")
        self.assertEqual(outputs["forgejo/terraform.auto.tfvars"]["gateway"], "192.168.1.1")

    def test_gateway_unresolved_without_network_plan(self):
        outputs = self.gen.generate_tofu_vars(NAMING_PLAN, CLUSTER_PLAN_SINGLE, STORAGE_PLAN)
        self.assertEqual(outputs["cell.auto.tfvars"]["gateway"], "UNRESOLVED")

    def test_nameservers_list(self):
        outputs = self.gen.generate_tofu_vars(
            NAMING_PLAN, CLUSTER_PLAN_SINGLE, STORAGE_PLAN, NETWORK_PLAN
        )
        ns = outputs["cell.auto.tfvars"]["nameservers"]
        self.assertIsInstance(ns, list)
        self.assertIn("192.168.1.1", ns)

    def test_primary_pool_from_storage_plan(self):
        outputs = self.gen.generate_tofu_vars(NAMING_PLAN, CLUSTER_PLAN_SINGLE, STORAGE_PLAN)
        self.assertEqual(outputs["cell.auto.tfvars"]["primary_pool"], "rpool")

    def test_hcl_value_string(self):
        self.assertEqual(self.gen._hcl_value("hello"), '"hello"')

    def test_hcl_value_int(self):
        self.assertEqual(self.gen._hcl_value(42), "42")

    def test_hcl_value_list(self):
        result = self.gen._hcl_value(["a", "b"])
        self.assertIn('"a"', result)
        self.assertIn('"b"', result)

    def test_hcl_value_bool(self):
        self.assertEqual(self.gen._hcl_value(True), "true")
        self.assertEqual(self.gen._hcl_value(False), "false")

    def test_output_count_matches_vms_plus_cell(self):
        outputs = self.gen.generate_tofu_vars(NAMING_PLAN, CLUSTER_PLAN_SINGLE, STORAGE_PLAN)
        vm_count = len(NAMING_PLAN["vms"])
        self.assertEqual(len(outputs), vm_count + 1)  # +1 for cell.auto.tfvars


# ---------------------------------------------------------------------------
# cloud-init-gen.py tests
# ---------------------------------------------------------------------------

class TestCloudInitGen(unittest.TestCase):
    def setUp(self):
        self.gen = _import("generators/cloud-init-gen.py", "cloud_init_gen")

    def test_bridge_naming_plan_to_bootstrap_state(self):
        state = self.gen._naming_plan_to_bootstrap_state(NAMING_PLAN, NETWORK_PLAN)
        self.assertEqual(state["cell_id"], "proxmox-cell-a")
        self.assertEqual(len(state["vms"]), 3)

    def test_bootstrap_state_has_gateway(self):
        state = self.gen._naming_plan_to_bootstrap_state(NAMING_PLAN, NETWORK_PLAN)
        self.assertEqual(state["network_topology"]["gateway"], "192.168.1.1")

    def test_bootstrap_state_gateway_unresolved_without_network_plan(self):
        state = self.gen._naming_plan_to_bootstrap_state(NAMING_PLAN, None)
        self.assertEqual(state["network_topology"]["gateway"], "UNRESOLVED")

    def test_bootstrap_state_vm_has_required_fields(self):
        state = self.gen._naming_plan_to_bootstrap_state(NAMING_PLAN, NETWORK_PLAN)
        for vm in state["vms"]:
            for field in ("name", "vmid", "initial_ip", "initial_user",
                          "workspace_path", "ssh_key_reference"):
                self.assertIn(field, vm, msg=f"Missing field {field} in vm {vm.get('name')}")

    def test_bootstrap_state_keepass_root(self):
        state = self.gen._naming_plan_to_bootstrap_state(NAMING_PLAN, None)
        self.assertEqual(state["keepass_config"]["root_path"], "Infrastructure")

    def test_bootstrap_state_vm_ips_propagated(self):
        state = self.gen._naming_plan_to_bootstrap_state(NAMING_PLAN, None)
        forgejo = next(v for v in state["vms"] if v["name"] == "forgejo")
        self.assertEqual(forgejo["initial_ip"], "192.168.1.20")


# ---------------------------------------------------------------------------
# ansible-inventory-gen.py tests
# ---------------------------------------------------------------------------

class TestAnsibleInventoryGen(unittest.TestCase):
    def setUp(self):
        self.gen = _import("generators/ansible-inventory-gen.py", "ansible_inventory_gen")

    def test_inventory_is_string(self):
        result = self.gen.generate_inventory(NAMING_PLAN)
        self.assertIsInstance(result, str)

    def test_inventory_has_all_group(self):
        result = self.gen.generate_inventory(NAMING_PLAN)
        self.assertIn("all:", result)

    def test_inventory_has_pre_k3s_group(self):
        result = self.gen.generate_inventory(NAMING_PLAN)
        self.assertIn("pre_k3s:", result)

    def test_inventory_has_k3s_servers_group(self):
        result = self.gen.generate_inventory(NAMING_PLAN)
        self.assertIn("k3s_servers:", result)

    def test_inventory_has_k3s_workers_group(self):
        result = self.gen.generate_inventory(NAMING_PLAN)
        self.assertIn("k3s_workers:", result)

    def test_forgejo_in_pre_k3s(self):
        result = self.gen.generate_inventory(NAMING_PLAN)
        # forgejo should appear under pre_k3s section
        lines = result.splitlines()
        in_pre_k3s = False
        found_forgejo = False
        for line in lines:
            if "pre_k3s:" in line:
                in_pre_k3s = True
            elif in_pre_k3s and line.strip().startswith("k3s_servers:"):
                break
            if in_pre_k3s and "forgejo:" in line:
                found_forgejo = True
        self.assertTrue(found_forgejo, "forgejo should be in pre_k3s group")

    def test_k3s_server_in_k3s_servers(self):
        result = self.gen.generate_inventory(NAMING_PLAN)
        lines = result.splitlines()
        in_k3s = False
        found = False
        for line in lines:
            if "k3s_servers:" in line:
                in_k3s = True
            elif in_k3s and line.strip().startswith("k3s_workers:"):
                break
            if in_k3s and "k3s-server-01:" in line:
                found = True
        self.assertTrue(found, "k3s-server-01 should be in k3s_servers group")

    def test_vm_ips_in_inventory(self):
        result = self.gen.generate_inventory(NAMING_PLAN)
        self.assertIn("192.168.1.20", result)
        self.assertIn("192.168.1.30", result)

    def test_cell_id_in_vars(self):
        result = self.gen.generate_inventory(NAMING_PLAN)
        self.assertIn("proxmox-cell-a", result)

    def test_empty_vms_produces_empty_groups(self):
        empty_plan = {**NAMING_PLAN, "vms": []}
        result = self.gen.generate_inventory(empty_plan)
        self.assertIn("pre_k3s:", result)
        self.assertNotIn("ansible_host: 192.168.1", result)

    def test_all_vms_group_contains_all(self):
        result = self.gen.generate_inventory(NAMING_PLAN)
        self.assertIn("all_vms:", result)
        for vm in NAMING_PLAN["vms"]:
            self.assertIn(vm["name"], result)


# ---------------------------------------------------------------------------
# k3s-config-gen.py tests
# ---------------------------------------------------------------------------

class TestK3sConfigGen(unittest.TestCase):
    def setUp(self):
        self.gen = _import("generators/k3s-config-gen.py", "k3s_config_gen")

    def test_single_node_produces_one_config(self):
        outputs = self.gen.generate_k3s_configs(NAMING_PLAN, CLUSTER_PLAN_SINGLE, K3S_META)
        self.assertIn("config.yaml", outputs)
        self.assertEqual(len(outputs), 1)

    def test_single_node_config_has_cluster_name(self):
        outputs = self.gen.generate_k3s_configs(NAMING_PLAN, CLUSTER_PLAN_SINGLE, K3S_META)
        self.assertIn("homelab-k3s", outputs["config.yaml"])

    def test_single_node_config_has_node_ip(self):
        outputs = self.gen.generate_k3s_configs(NAMING_PLAN, CLUSTER_PLAN_SINGLE, K3S_META)
        self.assertIn("192.168.1.30", outputs["config.yaml"])

    def test_single_node_has_tls_san(self):
        outputs = self.gen.generate_k3s_configs(NAMING_PLAN, CLUSTER_PLAN_SINGLE, K3S_META)
        self.assertIn("tls-san:", outputs["config.yaml"])
        self.assertIn("k3s-server-01.internal", outputs["config.yaml"])

    def test_single_node_has_pod_cidr(self):
        outputs = self.gen.generate_k3s_configs(NAMING_PLAN, CLUSTER_PLAN_SINGLE, K3S_META)
        self.assertIn("10.42.0.0/16", outputs["config.yaml"])

    def test_single_node_has_service_cidr(self):
        outputs = self.gen.generate_k3s_configs(NAMING_PLAN, CLUSTER_PLAN_SINGLE, K3S_META)
        self.assertIn("10.43.0.0/16", outputs["config.yaml"])

    def test_single_node_embedded_registry_enabled(self):
        outputs = self.gen.generate_k3s_configs(NAMING_PLAN, CLUSTER_PLAN_SINGLE, K3S_META)
        self.assertIn("embedded-registry: true", outputs["config.yaml"])

    def test_ha_produces_per_server_configs(self):
        outputs = self.gen.generate_k3s_configs(NAMING_PLAN_HA, CLUSTER_PLAN_HA, K3S_META)
        self.assertIn("k3s-server-01-config.yaml", outputs)
        self.assertIn("k3s-server-02-config.yaml", outputs)
        self.assertIn("k3s-server-03-config.yaml", outputs)
        self.assertNotIn("config.yaml", outputs)

    def test_ha_first_server_has_cluster_init(self):
        outputs = self.gen.generate_k3s_configs(NAMING_PLAN_HA, CLUSTER_PLAN_HA, K3S_META)
        self.assertIn("cluster-init: true", outputs["k3s-server-01-config.yaml"])

    def test_ha_additional_server_has_server_url(self):
        outputs = self.gen.generate_k3s_configs(NAMING_PLAN_HA, CLUSTER_PLAN_HA, K3S_META)
        second = outputs["k3s-server-02-config.yaml"]
        self.assertIn("server: https://192.168.1.30:6443", second)
        self.assertNotIn("cluster-init:", second)

    def test_ha_embedded_registry_disabled(self):
        outputs = self.gen.generate_k3s_configs(NAMING_PLAN_HA, CLUSTER_PLAN_HA, K3S_META)
        self.assertIn("embedded-registry: false", outputs["k3s-server-01-config.yaml"])

    def test_no_k3s_vms_returns_placeholder(self):
        plan_no_k3s = {**NAMING_PLAN, "vms": [
            vm for vm in NAMING_PLAN["vms"] if vm["role"] != "k3s-server"
        ]}
        outputs = self.gen.generate_k3s_configs(plan_no_k3s, CLUSTER_PLAN_SINGLE, K3S_META)
        self.assertIn("config.yaml", outputs)
        self.assertIn("No k3s server VMs", outputs["config.yaml"])

    def test_etcd_snapshot_config_present(self):
        outputs = self.gen.generate_k3s_configs(NAMING_PLAN, CLUSTER_PLAN_SINGLE, K3S_META)
        self.assertIn("etcd-snapshot-schedule-cron", outputs["config.yaml"])


# ---------------------------------------------------------------------------
# flux-bootstrap-gen.py tests
# ---------------------------------------------------------------------------

class TestFluxBootstrapGen(unittest.TestCase):
    def setUp(self):
        self.gen = _import("generators/flux-bootstrap-gen.py", "flux_bootstrap_gen")

    def test_returns_string(self):
        result = self.gen.generate_flux_bootstrap(NAMING_PLAN, CLUSTER_PLAN_SINGLE)
        self.assertIsInstance(result, str)

    def test_has_shebang(self):
        result = self.gen.generate_flux_bootstrap(NAMING_PLAN, CLUSTER_PLAN_SINGLE)
        self.assertTrue(result.startswith("#!/usr/bin/env bash"))

    def test_has_set_euo(self):
        result = self.gen.generate_flux_bootstrap(NAMING_PLAN, CLUSTER_PLAN_SINGLE)
        self.assertIn("set -euo pipefail", result)

    def test_forgejo_url_in_script(self):
        result = self.gen.generate_flux_bootstrap(NAMING_PLAN, CLUSTER_PLAN_SINGLE)
        self.assertIn("forgejo.internal", result)

    def test_forgejo_ip_in_script(self):
        result = self.gen.generate_flux_bootstrap(NAMING_PLAN, CLUSTER_PLAN_SINGLE)
        self.assertIn("192.168.1.20", result)

    def test_platform_config_repo_in_script(self):
        result = self.gen.generate_flux_bootstrap(NAMING_PLAN, CLUSTER_PLAN_SINGLE)
        self.assertIn("proxmox-cell-a-platform-config", result)

    def test_cell_id_in_script(self):
        result = self.gen.generate_flux_bootstrap(NAMING_PLAN, CLUSTER_PLAN_SINGLE)
        self.assertIn("proxmox-cell-a", result)

    def test_flux_bootstrap_gitea_command(self):
        result = self.gen.generate_flux_bootstrap(NAMING_PLAN, CLUSTER_PLAN_SINGLE)
        self.assertIn("flux bootstrap gitea", result)

    def test_gitea_token_check_present(self):
        result = self.gen.generate_flux_bootstrap(NAMING_PLAN, CLUSTER_PLAN_SINGLE)
        self.assertIn("GITEA_TOKEN", result)

    def test_k3s_server_ip_in_script(self):
        result = self.gen.generate_flux_bootstrap(NAMING_PLAN, CLUSTER_PLAN_SINGLE)
        self.assertIn("192.168.1.30", result)

    def test_flux_check_verification_present(self):
        result = self.gen.generate_flux_bootstrap(NAMING_PLAN, CLUSTER_PLAN_SINGLE)
        self.assertIn("flux check", result)

    def test_ha_note_in_ha_mode(self):
        result = self.gen.generate_flux_bootstrap(NAMING_PLAN_HA, CLUSTER_PLAN_HA)
        self.assertIn("HA mode", result)

    def test_no_ha_note_in_single_node(self):
        result = self.gen.generate_flux_bootstrap(NAMING_PLAN, CLUSTER_PLAN_SINGLE)
        self.assertNotIn("HA mode", result)

    def test_cluster_path_in_script(self):
        result = self.gen.generate_flux_bootstrap(NAMING_PLAN, CLUSTER_PLAN_SINGLE)
        self.assertIn("clusters/homelab", result)

    def test_token_auth_flag_present(self):
        result = self.gen.generate_flux_bootstrap(NAMING_PLAN, CLUSTER_PLAN_SINGLE)
        self.assertIn("--token-auth", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
