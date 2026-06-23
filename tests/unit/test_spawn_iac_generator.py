#!/usr/bin/env python3
"""Tests for Phase 12.E.5 — Spawn IaC and config generator."""

import unittest
from pathlib import Path

from spawn_iac_generator import (
    generate_ansible_inventory,
    generate_ansible_k3s_vars,
    generate_cloudinit_network_config,
    generate_cloudinit_user_data,
    generate_tfvars,
    write_all_artifacts,
)

PLAN = {
    "schema_version": "1.0",
    "cell_id": "proxmox-cell-a",
    "generated_at": "2026-06-01T12:00:00Z",
    "package_id": "spawn-proxmox-cell-a-pve02-2026-06-01_12_00_00",
    "hostname": "pve02",
    "domain": "home.example.com",
    "fqdn": "pve02.home.example.com",
    "lan_ip": "192.168.1.15",
    "k3s_role": "worker",
    "disposition": {"services": ["k3s-worker"], "execution_mode": "autonomous"},
    "vmid_block": [200, 201],
    "ip_block": ["192.168.1.50", "192.168.1.51"],
    "vms": [
        {"vmid": 200, "name": "k3s-worker-01", "role": "k3s-worker",
         "template_name": "ubuntu-2204-base", "template_id": 9000,
         "cores": 2, "memory_mb": 4096, "disk_gb": 32,
         "bridge": "vmbr0", "datastore": "local-rpool",
         "ip": "192.168.1.50", "gateway": "192.168.1.1",
         "initial_user": "ubuntu", "hostname": "k3s-worker-01"},
    ],
    "storage": {"pool_name": "rpool", "topology": "mirror",
                "disk_ids": ["/dev/sda", "/dev/sdb"], "datastore_name": "local-rpool"},
    "network": {"management_cidr": "192.168.1.0/24", "gateway": "192.168.1.1",
                "bridge": "vmbr0", "nameservers": ["192.168.1.1", "8.8.8.8"]},
    "k3s": {"role": "worker", "server_url": "https://pve01.home.example.com:6443",
            "worker_join_token": "K10::worker::abc123"},
    "hatchery": {"proxmox_cluster_address": "192.168.1.10"},
    "dns_entries": [
        {"hostname": "pve02.internal", "ip": "192.168.1.15"},
        {"hostname": "k3s-worker-01.internal", "ip": "192.168.1.50", "vmid": 200},
    ],
}


class TestGenerateTfvars(unittest.TestCase):
    def setUp(self): self.tf = generate_tfvars(PLAN)
    def test_has_proxmox_url(self): self.assertIn("proxmox_api_url", self.tf)
    def test_has_target_node(self): self.assertIn("pve02", self.tf)
    def test_has_vmid(self): self.assertIn("200", self.tf)
    def test_has_vm_name(self): self.assertIn("k3s-worker-01", self.tf)
    def test_has_ip_config(self): self.assertIn("192.168.1.50", self.tf)
    def test_has_memory(self): self.assertIn("4096", self.tf)
    def test_has_disk(self): self.assertIn("32G", self.tf)
    def test_has_bridge(self): self.assertIn("vmbr0", self.tf)
    def test_has_datastore(self): self.assertIn("local-rpool", self.tf)
    def test_has_do_not_edit_header(self): self.assertIn("DO NOT EDIT", self.tf)
    def test_empty_vms_produces_vms_block(self):
        tf = generate_tfvars({**PLAN, "vms": []})
        self.assertIn("vms = {", tf)


class TestGenerateCloudInitUserData(unittest.TestCase):
    def setUp(self):
        self.ud = generate_cloudinit_user_data(PLAN["vms"][0], PLAN)
    def test_has_hostname(self): self.assertIn("k3s-worker-01", self.ud)
    def test_has_fqdn(self): self.assertIn("home.example.com", self.ud)
    def test_has_ci_user(self): self.assertIn("ubuntu", self.ud)
    def test_has_cloud_config_header(self): self.assertIn("#cloud-config", self.ud)
    def test_has_qemu_guest_agent(self): self.assertIn("qemu-guest-agent", self.ud)


class TestGenerateCloudInitNetworkConfig(unittest.TestCase):
    def setUp(self):
        self.nc = generate_cloudinit_network_config(PLAN["vms"][0], PLAN)
    def test_has_version(self): self.assertIn("version: 1", self.nc)
    def test_has_ip(self): self.assertIn("192.168.1.50", self.nc)
    def test_has_gateway(self): self.assertIn("192.168.1.1", self.nc)
    def test_has_nameservers(self): self.assertIn("8.8.8.8", self.nc)
    def test_has_interface(self): self.assertIn("ens18", self.nc)


class TestGenerateAnsibleInventory(unittest.TestCase):
    def setUp(self): self.inv = generate_ansible_inventory(PLAN)
    def test_has_broodlings_group(self): self.assertIn("proxmox_broodlings", self.inv)
    def test_has_broodling_host(self): self.assertIn("pve02", self.inv)
    def test_has_vm_in_role_group(self):
        self.assertIn("k3s_worker", self.inv)
        self.assertIn("k3s-worker-01", self.inv)
    def test_has_vm_ip(self): self.assertIn("192.168.1.50", self.inv)
    def test_has_vmid(self): self.assertIn("200", self.inv)
    def test_has_domain(self): self.assertIn("home.example.com", self.inv)


class TestGenerateAnsibleK3sVars(unittest.TestCase):
    def setUp(self): self.v = generate_ansible_k3s_vars(PLAN)
    def test_has_k3s_role(self): self.assertIn("worker", self.v)
    def test_has_server_url(self):
        self.assertIn("pve01.home.example.com", self.v)
    def test_has_join_token(self): self.assertIn("K10::worker::abc123", self.v)
    def test_server_role_uses_server_token(self):
        plan = {**PLAN, "k3s": {**PLAN["k3s"], "role": "server",
                                  "server_join_token": "K10::server::xyz"}}
        v = generate_ansible_k3s_vars(plan)
        self.assertIn("K10::server::xyz", v)


class TestWriteAllArtifacts(unittest.TestCase):
    def test_writes_files(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            written = write_all_artifacts(PLAN, Path(tmp))
            self.assertIn("tfvars", written)
            self.assertIn("ansible_inventory", written)
            self.assertIn("user_data:k3s-worker-01", written)
            self.assertIn("network_config:k3s-worker-01", written)
            for path in written.values():
                self.assertTrue(path.exists(), f"{path} not created")

    def test_tfvars_file_content(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            written = write_all_artifacts(PLAN, Path(tmp))
            content = written["tfvars"].read_text()
            self.assertIn("k3s-worker-01", content)


if __name__ == "__main__":
    unittest.main()
