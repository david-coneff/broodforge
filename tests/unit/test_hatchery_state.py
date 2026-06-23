#!/usr/bin/env python3
"""
Tests for Phase 12.E.1 — Hatchery State Reader.

Covers:
  - read_hatchery_state(): extracts reserved VMIDs, IPs, hostnames, cluster info
  - SpawnManifest properties
  - next_vmid_block(): allocates non-conflicting VMID blocks
  - next_ip_block(): allocates IPs from CIDR avoiding reserved
  - suggest_hostname(): generates next available hostname
  - k3s token embedding
  - empty / minimal state handling
"""

import unittest

from hatchery_state import (
    SPAWN_MANIFEST_VERSION,
    SpawnManifest,
    next_ip_block,
    next_vmid_block,
    read_hatchery_state,
    suggest_hostname,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BASE_STATE = {
    "schema_version": "1.0",
    "cell_id": "proxmox-cell-a",
    "host_identity": {
        "hostname": "pve01",
        "fqdn":     "pve01.home.example.com",
    },
    "network_topology": {
        "management_cidr": "192.168.1.0/24",
        "gateway":         "192.168.1.1",
        "profile":         "lan",
        "headscale_url":   None,
    },
    "vms": [
        {"vmid": 100, "name": "infra-bootstrap", "initial_ip": "192.168.1.20"},
        {"vmid": 101, "name": "forgejo",         "initial_ip": "192.168.1.21"},
        {"vmid": 102, "name": "inventory",       "initial_ip": "192.168.1.22"},
        {"vmid": 103, "name": "assessment-engine","initial_ip": "192.168.1.23"},
    ],
    "dns_registry": [
        {"hostname": "pve01.internal",              "ip": "192.168.1.10", "vmid": None, "role": "proxmox-host"},
        {"hostname": "infra-bootstrap.internal",    "ip": "192.168.1.20", "vmid": 100},
        {"hostname": "forgejo.internal",            "ip": "192.168.1.21", "vmid": 101},
        {"hostname": "inventory.internal",          "ip": "192.168.1.22", "vmid": 102},
        {"hostname": "assessment.internal",         "ip": "192.168.1.23", "vmid": 103},
    ],
    "provenance_records": [],
    "k3s_cluster": {
        "server_nodes": [{"vm": "k3s-server-01"}],
        "worker_nodes":  [],
        "pod_cidr":     "10.42.0.0/16",
        "service_cidr": "10.43.0.0/16",
    },
}

def _fixed_now():
    return "2026-06-01T12:00:00+00:00"

def _manifest(state=None, tokens=None) -> SpawnManifest:
    return read_hatchery_state(state or BASE_STATE, k3s_tokens=tokens, now_fn=_fixed_now)


# ---------------------------------------------------------------------------
# read_hatchery_state / SpawnManifest
# ---------------------------------------------------------------------------

class TestReadHatcheryState(unittest.TestCase):

    def setUp(self):
        self.m = _manifest()

    def test_schema_version(self):
        self.assertEqual(self.m.schema_version, SPAWN_MANIFEST_VERSION)

    def test_cell_id(self):
        self.assertEqual(self.m.cell_id, "proxmox-cell-a")

    def test_generated_at_present(self):
        self.assertIn("generated_at", self.m.raw)

    def test_reserved_vmids_from_vms(self):
        vmids = self.m.reserved_vmids
        self.assertIn(100, vmids)
        self.assertIn(101, vmids)
        self.assertIn(102, vmids)
        self.assertIn(103, vmids)

    def test_template_vmids_9000_reserved(self):
        self.assertIn(9000, self.m.reserved_vmids)

    def test_reserved_ips_from_dns_registry(self):
        ips = self.m.reserved_ips
        self.assertIn("192.168.1.10", ips)
        self.assertIn("192.168.1.21", ips)

    def test_reserved_hostnames_from_dns(self):
        hn = self.m.reserved_hostnames
        self.assertIn("pve01.internal", hn)
        self.assertIn("forgejo.internal", hn)

    def test_short_hostnames_also_reserved(self):
        # Short names (split on '.') are also reserved
        self.assertIn("pve01", self.m.reserved_hostnames)
        self.assertIn("forgejo", self.m.reserved_hostnames)

    def test_proxmox_cluster_address_from_dns_host_role(self):
        self.assertEqual(self.m.proxmox_cluster_address, "192.168.1.10")

    def test_k3s_server_count(self):
        self.assertEqual(self.m.k3s_server_count, 1)

    def test_k3s_worker_count(self):
        self.assertEqual(self.m.k3s_worker_count, 0)

    def test_k3s_tokens_none_by_default(self):
        self.assertIsNone(self.m.worker_join_token)
        self.assertIsNone(self.m.server_join_token)

    def test_k3s_tokens_embedded_when_provided(self):
        m = _manifest(tokens={"worker": "K10::worker::abc123", "server": "K10::server::def456"})
        self.assertEqual(m.worker_join_token, "K10::worker::abc123")
        self.assertEqual(m.server_join_token, "K10::server::def456")

    def test_pod_cidr_from_k3s_cluster(self):
        cidr = self.m.raw["k3s"]["pod_cidr"]
        self.assertEqual(cidr, "10.42.0.0/16")

    def test_headscale_url_none_for_lan_profile(self):
        self.assertIsNone(self.m.headscale_url)

    def test_headscale_url_present_for_wan_profile(self):
        state = {**BASE_STATE, "network_topology": {
            **BASE_STATE["network_topology"],
            "headscale_url": "https://pve01.home.example.com:8080",
        }}
        m = _manifest(state=state)
        self.assertEqual(m.headscale_url, "https://pve01.home.example.com:8080")

    def test_to_dict_is_dict(self):
        self.assertIsInstance(self.m.to_dict(), dict)

    def test_management_cidr_in_reserved(self):
        self.assertIn("management_cidr", self.m.raw["reserved"])
        self.assertEqual(self.m.raw["reserved"]["management_cidr"], "192.168.1.0/24")

    def test_empty_state_does_not_crash(self):
        m = read_hatchery_state({}, now_fn=_fixed_now)
        self.assertIsInstance(m, SpawnManifest)
        self.assertEqual(m.reserved_vmids - {9000,9001,9002,9003,9004,9005,9006,9007,9008,9009}, set())

    def test_hatchery_hostname_in_manifest(self):
        self.assertEqual(self.m.raw["hatchery"]["hostname"], "pve01")

    def test_hatchery_fqdn_in_manifest(self):
        self.assertEqual(self.m.raw["hatchery"]["fqdn"], "pve01.home.example.com")


# ---------------------------------------------------------------------------
# next_vmid_block
# ---------------------------------------------------------------------------

class TestNextVmidBlock(unittest.TestCase):

    def setUp(self):
        self.m = _manifest()

    def test_returns_correct_count(self):
        vmids = next_vmid_block(self.m, 3)
        self.assertEqual(len(vmids), 3)

    def test_returns_no_conflicts(self):
        vmids = next_vmid_block(self.m, 5)
        reserved = self.m.reserved_vmids
        for vmid in vmids:
            self.assertNotIn(vmid, reserved)

    def test_vmids_are_sequential(self):
        vmids = next_vmid_block(self.m, 4)
        self.assertEqual(vmids, sorted(vmids))

    def test_start_hint_respected(self):
        vmids = next_vmid_block(self.m, 1, start_hint=500)
        self.assertGreaterEqual(vmids[0], 500)

    def test_vmids_are_integers(self):
        for vmid in next_vmid_block(self.m, 3):
            self.assertIsInstance(vmid, int)

    def test_below_9000(self):
        for vmid in next_vmid_block(self.m, 5):
            self.assertLess(vmid, 9000)


# ---------------------------------------------------------------------------
# next_ip_block
# ---------------------------------------------------------------------------

class TestNextIpBlock(unittest.TestCase):

    def setUp(self):
        self.m = _manifest()

    def test_returns_correct_count(self):
        ips = next_ip_block(self.m, count=3)
        self.assertEqual(len(ips), 3)

    def test_no_conflicts(self):
        ips = next_ip_block(self.m, count=5)
        reserved = self.m.reserved_ips
        for ip in ips:
            self.assertNotIn(ip, reserved)

    def test_ips_in_correct_subnet(self):
        import ipaddress
        ips  = next_ip_block(self.m, count=3)
        net  = ipaddress.ip_network("192.168.1.0/24", strict=False)
        for ip in ips:
            self.assertIn(ipaddress.ip_address(ip), net)

    def test_custom_cidr(self):
        import ipaddress
        ips = next_ip_block(self.m, cidr="10.0.0.0/24", count=2)
        net = ipaddress.ip_network("10.0.0.0/24", strict=False)
        for ip in ips:
            self.assertIn(ipaddress.ip_address(ip), net)

    def test_invalid_cidr_raises(self):
        with self.assertRaises(ValueError):
            next_ip_block(self.m, cidr="not-a-cidr", count=1)


# ---------------------------------------------------------------------------
# suggest_hostname
# ---------------------------------------------------------------------------

class TestSuggestHostname(unittest.TestCase):

    def setUp(self):
        self.m = _manifest()

    def test_returns_string(self):
        self.assertIsInstance(suggest_hostname(self.m), str)

    def test_not_already_reserved(self):
        hostname = suggest_hostname(self.m, role="pve")
        short    = hostname.split(".")[0]
        self.assertNotIn(short, self.m.reserved_hostnames)

    def test_includes_domain_when_provided(self):
        hostname = suggest_hostname(self.m, role="pve", domain="home.example.com")
        self.assertIn("home.example.com", hostname)

    def test_pve01_is_reserved_pve02_returned(self):
        hostname = suggest_hostname(self.m, role="pve")
        self.assertIn("02", hostname)

    def test_role_prefix_used(self):
        hostname = suggest_hostname(self.m, role="node")
        self.assertTrue(hostname.startswith("node"))


if __name__ == "__main__":
    unittest.main()
