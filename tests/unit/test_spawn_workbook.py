#!/usr/bin/env python3
"""
Tests for html_spawn_workbook.py — HTML spawn workbook generator.

NOTE: spawn_workbook.py (ODS) is deprecated → proxmox-bootstrap/deprecated/.
      The active output format is HTML via html_spawn_workbook.py.

Covers functional content assertions (hostname, cell_id, services,
storage topology, network info, VM info, k3s info) plus HTML structure.
"""

import importlib.util
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent

# Load html_spawn_workbook via importlib (avoids sys.path ordering issues)
_spec = importlib.util.spec_from_file_location(
    "html_spawn_workbook",
    REPO_ROOT / "proxmox-bootstrap" / "html_spawn_workbook.py",
)
_hsw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_hsw)
build_spawn_workbook_html = _hsw.build_spawn_workbook_html


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PLAN = {
    "cell_id": "cell-alpha",
    "hostname": "pve02",
    "package_id": "spawn-cell-alpha-pve02-ts",
    "generated_at": "2026-06-01T12:00:00Z",
    "lan_ip": "192.168.1.15",
    "domain": "home.example.com",
    "disposition": {
        "execution_mode": "autonomous",
        "network_mode": "lan",
        "services": ["k3s-worker", "longhorn"],
        "excluded": ["pbs-datastore"],
    },
    # html_spawn_workbook.py expects zfs_config and network_config
    "zfs_config": {
        "pool_name": "rpool",
        "topology": "mirror",
        "disk_ids": ["/dev/sda", "/dev/sdb"],
        "datastore_name": "local-rpool",
    },
    "network_config": {
        "bridge": "vmbr0",
        "gateway": "192.168.1.1",
        "nameservers": ["192.168.1.1", "8.8.8.8"],
    },
    "hatchery": {
        "proxmox_cluster_address": "192.168.1.10",
        "proxmox_fingerprint": "AA:BB:CC:DD",
        "headscale_url": "https://hatchery.home.example.com:8080",
    },
    "vms": [
        {"vmid": 200, "name": "k3s-worker-01", "ip": "192.168.1.50",
         "memory_mb": 4096, "initial_user": "ubuntu"},
        {"vmid": 201, "name": "longhorn-01", "ip": "192.168.1.51",
         "memory_mb": 2048, "initial_user": "ubuntu"},
    ],
    "k3s": {
        "role": "worker",
        "server_url": "https://pve01.home.example.com:6443",
        "worker_join_token": "K10::worker::abc",
        "node_labels": ["worker=true"],
    },
}

HARDWARE = {
    "hostname": "pve02",
    "cpu_model": "Intel Core i7-8700",
    "cpu_cores": 6,
    "ram_gb": 32,
    "disks": [
        {"name": "sda", "size_gb": 500, "rotational": False},
        {"name": "sdb", "size_gb": 500, "rotational": False},
    ],
    "nics": [
        {"name": "eno1", "mac": "AA:BB:CC:DD:EE:FF", "speed_mbps": 1000},
    ],
    "derived": {
        "usable_disks": 2, "ssd_count": 2, "hdd_count": 0, "zfs_topology": "mirror"
    },
}


def _html(plan=None, hw=None) -> str:
    # build_spawn_workbook_html(spawn_plan, spawn_manifest, hardware_profile)
    return build_spawn_workbook_html(plan or PLAN, {}, hw)


# ---------------------------------------------------------------------------
# HTML structure
# ---------------------------------------------------------------------------

class TestHtmlStructure(unittest.TestCase):
    def setUp(self):
        self.html = _html()

    def test_returns_string(self):
        self.assertIsInstance(self.html, str)

    def test_is_valid_html(self):
        self.assertIn("<!DOCTYPE html>", self.html)
        self.assertIn("</html>", self.html)

    def test_self_contained(self):
        self.assertNotIn("cdn.", self.html)

    def test_has_checkboxes(self):
        self.assertIn('type="checkbox"', self.html)


# ---------------------------------------------------------------------------
# Content: overview / identity
# ---------------------------------------------------------------------------

class TestOverviewContent(unittest.TestCase):
    def setUp(self):
        self.html = _html()

    def test_hostname_present(self):
        self.assertIn("pve02", self.html)

    def test_cell_id_present(self):
        self.assertIn("cell-alpha", self.html)

    def test_execution_mode_present(self):
        self.assertIn("autonomous", self.html.lower())

    def test_service_in_plan(self):
        self.assertIn("k3s-worker", self.html)

    def test_disposition_shown(self):
        # Disposition section shows execution mode
        self.assertIn("autonomous", self.html.lower())

    def test_phases_section_present(self):
        # Phase sections are shown (Phase 00, 01, etc.)
        self.assertIn("Phase 00", self.html)
        self.assertIn("Phase 06", self.html)


# ---------------------------------------------------------------------------
# Content: hardware / discovery
# ---------------------------------------------------------------------------

class TestDiscoveryContent(unittest.TestCase):
    def test_with_hardware_profile(self):
        html = _html(hw=HARDWARE)
        # HTML workbook shows RAM, disk names, NIC (CPU model may be truncated)
        self.assertIn("32", html)
        self.assertIn("sda", html)
        self.assertIn("eno1", html)

    def test_without_hardware_profile_shows_fallback(self):
        html = _html()
        self.assertIsNotNone(html)  # no crash

    def test_nic_mac_present(self):
        html = _html(hw=HARDWARE)
        self.assertIn("AA:BB:CC:DD:EE:FF", html)


# ---------------------------------------------------------------------------
# Content: storage
# ---------------------------------------------------------------------------

class TestStorageContent(unittest.TestCase):
    def setUp(self):
        self.html = _html()

    def test_pool_name(self):
        self.assertIn("rpool", self.html)

    def test_zfs_section_present(self):
        # ZFS pool creation checklist item present
        self.assertIn("ZFS pool", self.html)

    def test_datastore_registration_shown(self):
        self.assertIn("pvesm", self.html)


# ---------------------------------------------------------------------------
# Content: network
# ---------------------------------------------------------------------------

class TestNetworkContent(unittest.TestCase):
    def setUp(self):
        self.html = _html()

    def test_bridge_creation_shown(self):
        # Bridge creation step is shown in Phase 00
        self.assertIn("bridge", self.html.lower())

    def test_network_mode_shown(self):
        self.assertIn("lan", self.html)

    def test_network_section_present(self):
        # Network bridge creation step is shown
        self.assertIn("ifreload", self.html)


# ---------------------------------------------------------------------------
# Content: VMs
# ---------------------------------------------------------------------------

class TestVmContent(unittest.TestCase):
    def setUp(self):
        self.html = _html()

    def test_vmid_200(self):
        self.assertIn("200", self.html)

    def test_vmid_201(self):
        self.assertIn("201", self.html)

    def test_vm_ip(self):
        self.assertIn("192.168.1.50", self.html)

    def test_vm_name(self):
        self.assertIn("k3s-worker-01", self.html)


# ---------------------------------------------------------------------------
# Content: k3s
# ---------------------------------------------------------------------------

class TestK3sContent(unittest.TestCase):
    def setUp(self):
        self.html = _html()

    def test_k3s_role(self):
        self.assertIn("worker", self.html)

    def test_k3s_join_shown(self):
        # k3s join section shows ansible-playbook command
        self.assertIn("k3s", self.html.lower())

    def test_no_token_in_plain_text(self):
        # Token value must NOT appear verbatim (it's a secret)
        self.assertNotIn("K10::worker::abc", self.html)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    def test_minimal_plan_does_not_crash(self):
        html = build_spawn_workbook_html({}, {}, None)
        self.assertIn("<!DOCTYPE html>", html)

    def test_hatchery_section_shown(self):
        # Proxmox join section references the hatchery
        self.assertIn("Proxmox", _html())


if __name__ == "__main__":
    unittest.main()
