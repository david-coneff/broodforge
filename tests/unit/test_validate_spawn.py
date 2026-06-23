#!/usr/bin/env python3
"""
Tests for Phase 12.E.2 — Spawn Conflict Validator.

Covers:
  - VMID collision with hatchery reservations
  - VMID duplicate within proposal
  - VMID out-of-range (< 100, >= 9000)
  - IP collision with hatchery reservations
  - IP duplicate within proposal
  - IP outside management CIDR (YELLOW)
  - Invalid IP format
  - Hostname collision with hatchery
  - Hostname duplicate within proposal
  - Hostname format warning
  - Capacity: RAM exceeds headroom (RED)
  - Capacity: RAM marginal (YELLOW)
  - Placement policy violations (YELLOW)
  - is_valid() / summarise()
  - Clean proposal → no findings
"""

import unittest

from hatchery_state import SpawnManifest, read_hatchery_state
from validate_spawn import (
    SEVERITY_RED,
    SEVERITY_YELLOW,
    SpawnFinding,
    SpawnProposal,
    is_valid,
    summarise,
    validate_spawn,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BASE_STATE = {
    "cell_id": "proxmox-cell-a",
    "host_identity": {"hostname": "pve01", "fqdn": "pve01.home.example.com"},
    "network_topology": {"management_cidr": "192.168.1.0/24", "profile": "lan"},
    "vms": [
        {"vmid": 100, "name": "infra-bootstrap"},
        {"vmid": 101, "name": "forgejo"},
    ],
    "dns_registry": [
        {"hostname": "pve01.internal",   "ip": "192.168.1.10", "vmid": None, "role": "proxmox-host"},
        {"hostname": "forgejo.internal", "ip": "192.168.1.21", "vmid": 101},
    ],
    "provenance_records": [],
    "k3s_cluster": {"server_nodes": [{"vm": "k3s-server-01"}], "worker_nodes": []},
}

def _manifest() -> SpawnManifest:
    return read_hatchery_state(BASE_STATE, now_fn=lambda: "2026-06-01T00:00:00+00:00")

def _proposal(**kwargs) -> SpawnProposal:
    defaults = dict(
        vmids=[200, 201],
        ips=["192.168.1.50", "192.168.1.51"],
        hostnames=["pve02.internal"],
        hostname="pve02",
        ram_gb=8,
        host_ram_gb=32,
    )
    defaults.update(kwargs)
    return SpawnProposal(**defaults)

def _findings(**kwargs) -> list[SpawnFinding]:
    return validate_spawn(_manifest(), _proposal(**kwargs))

def _reds(**kwargs):
    return [f for f in _findings(**kwargs) if f.severity == SEVERITY_RED]

def _yellows(**kwargs):
    return [f for f in _findings(**kwargs) if f.severity == SEVERITY_YELLOW]


# ---------------------------------------------------------------------------
# Clean proposal
# ---------------------------------------------------------------------------

class TestCleanProposal(unittest.TestCase):

    def test_clean_proposal_no_findings(self):
        findings = validate_spawn(_manifest(), _proposal())
        self.assertEqual(findings, [])

    def test_is_valid_true_for_clean(self):
        self.assertTrue(is_valid(validate_spawn(_manifest(), _proposal())))

    def test_summarise_clean(self):
        summary = summarise([])
        self.assertIn("No conflicts", summary)


# ---------------------------------------------------------------------------
# VMID checks
# ---------------------------------------------------------------------------

class TestVmidChecks(unittest.TestCase):

    def test_existing_vmid_collision_is_red(self):
        reds = _reds(vmids=[100, 200])   # 100 is taken
        self.assertTrue(any("100" in f.message for f in reds))

    def test_vmid_below_100_is_red(self):
        reds = _reds(vmids=[50, 200])
        self.assertTrue(any("below 100" in f.message for f in reds))

    def test_vmid_9000_plus_is_red(self):
        reds = _reds(vmids=[9001, 200])
        self.assertTrue(any("9000" in f.message for f in reds))

    def test_vmid_duplicate_in_proposal_is_red(self):
        reds = _reds(vmids=[200, 200])
        self.assertTrue(any("Duplicate" in f.message for f in reds))

    def test_valid_vmids_no_finding(self):
        reds = _reds(vmids=[200, 201])
        vmid_reds = [f for f in reds if f.field == "vmids"]
        self.assertEqual(vmid_reds, [])

    def test_non_integer_vmid_is_red(self):
        reds = _reds(vmids=["not-a-vmid", 200])
        self.assertTrue(len(reds) > 0)


# ---------------------------------------------------------------------------
# IP checks
# ---------------------------------------------------------------------------

class TestIpChecks(unittest.TestCase):

    def test_reserved_ip_collision_is_red(self):
        reds = _reds(ips=["192.168.1.10", "192.168.1.50"])  # .10 is taken
        self.assertTrue(any("192.168.1.10" in f.message for f in reds))

    def test_ip_duplicate_in_proposal_is_red(self):
        reds = _reds(ips=["192.168.1.50", "192.168.1.50"])
        self.assertTrue(any("Duplicate" in f.message for f in reds))

    def test_invalid_ip_format_is_red(self):
        reds = _reds(ips=["not-an-ip", "192.168.1.50"])
        self.assertTrue(any("valid IP" in f.message for f in reds))

    def test_ip_outside_cidr_is_yellow(self):
        yellows = _yellows(ips=["10.0.0.5", "192.168.1.50"])
        self.assertTrue(any("management CIDR" in f.message for f in yellows))

    def test_ip_inside_cidr_no_warning(self):
        findings = _findings(ips=["192.168.1.50", "192.168.1.51"])
        ip_findings = [f for f in findings if f.field == "ips"]
        self.assertEqual(ip_findings, [])

    def test_empty_ips_no_finding(self):
        findings = validate_spawn(_manifest(), SpawnProposal(vmids=[200], ips=[]))
        ip_findings = [f for f in findings if f.field == "ips"]
        self.assertEqual(ip_findings, [])


# ---------------------------------------------------------------------------
# Hostname checks
# ---------------------------------------------------------------------------

class TestHostnameChecks(unittest.TestCase):

    def test_reserved_hostname_collision_is_red(self):
        reds = _reds(hostnames=["pve01.internal"], hostname="pve02")
        self.assertTrue(any("pve01" in f.message for f in reds))

    def test_short_hostname_collision_is_red(self):
        # "pve01" (short form) should also be blocked
        reds = _reds(hostname="pve01", hostnames=[])
        self.assertTrue(any("pve01" in f.message for f in reds))

    def test_hostname_duplicate_in_proposal_is_red(self):
        reds = _reds(hostnames=["pve02.internal", "pve02.internal"])
        self.assertTrue(any("Duplicate" in f.message for f in reds))

    def test_bad_hostname_format_is_yellow(self):
        yellows = _yellows(hostname="UPPER_CASE!", hostnames=[])
        self.assertTrue(any("naming convention" in f.message.lower() for f in yellows))

    def test_valid_hostname_no_finding(self):
        findings = _findings(hostname="pve02", hostnames=["pve02.internal"])
        hn_reds = [f for f in findings if f.field == "hostnames" and f.severity == SEVERITY_RED]
        self.assertEqual(hn_reds, [])


# ---------------------------------------------------------------------------
# Capacity checks
# ---------------------------------------------------------------------------

class TestCapacityChecks(unittest.TestCase):

    def test_insufficient_ram_is_red(self):
        # 32 GB host, 10% headroom → 28.8 GB available; need 30 GB → RED
        reds = _reds(ram_gb=30, host_ram_gb=32)
        cap_reds = [f for f in reds if "ram" in f.field]
        self.assertTrue(len(cap_reds) >= 1)
        self.assertEqual(cap_reds[0].severity, SEVERITY_RED)

    def test_marginal_ram_is_yellow(self):
        # 32 GB host, 10% headroom → 28.8 GB available; need 26 GB → YELLOW (>85%)
        yellows = _yellows(ram_gb=26, host_ram_gb=32)
        cap_yellows = [f for f in yellows if "ram" in f.field]
        self.assertTrue(len(cap_yellows) >= 1)

    def test_sufficient_ram_no_finding(self):
        findings = _findings(ram_gb=8, host_ram_gb=32)
        cap = [f for f in findings if "ram" in f.field]
        self.assertEqual(cap, [])

    def test_no_ram_data_no_finding(self):
        findings = validate_spawn(_manifest(), SpawnProposal(vmids=[200]))
        cap = [f for f in findings if "ram" in f.field]
        self.assertEqual(cap, [])


# ---------------------------------------------------------------------------
# Placement checks
# ---------------------------------------------------------------------------

class TestPlacementChecks(unittest.TestCase):

    def test_role_not_in_policy_is_yellow(self):
        proposal = _proposal(
            roles=["k3s-server", "pbs-datastore"],
            placement_policy={"allowed_roles": ["k3s-worker", "monitoring"]},
        )
        findings = validate_spawn(_manifest(), proposal)
        yellows = [f for f in findings if f.severity == SEVERITY_YELLOW and f.field == "roles"]
        self.assertTrue(len(yellows) >= 1)

    def test_role_in_policy_no_warning(self):
        proposal = _proposal(
            roles=["k3s-worker"],
            placement_policy={"allowed_roles": ["k3s-worker", "k3s-server"]},
        )
        findings = validate_spawn(_manifest(), proposal)
        role_yellows = [f for f in findings if f.field == "roles"]
        self.assertEqual(role_yellows, [])

    def test_no_policy_no_finding(self):
        proposal = _proposal(roles=["anything"], placement_policy=None)
        findings = validate_spawn(_manifest(), proposal)
        role_findings = [f for f in findings if f.field == "roles"]
        self.assertEqual(role_findings, [])


# ---------------------------------------------------------------------------
# is_valid / summarise
# ---------------------------------------------------------------------------

class TestIsValidSummarise(unittest.TestCase):

    def test_is_valid_false_when_red(self):
        proposal = _proposal(vmids=[100])  # collision
        self.assertFalse(is_valid(validate_spawn(_manifest(), proposal)))

    def test_is_valid_true_when_only_yellows(self):
        proposal = _proposal(ips=["10.0.0.5", "192.168.1.50"])  # outside CIDR = YELLOW
        findings = validate_spawn(_manifest(), proposal)
        self.assertTrue(is_valid(findings))

    def test_summarise_shows_blocked_when_red(self):
        proposal = _proposal(vmids=[100])
        summary = summarise(validate_spawn(_manifest(), proposal))
        self.assertIn("BLOCKED", summary)

    def test_summarise_shows_counts(self):
        proposal = _proposal(vmids=[100], ips=["10.0.0.5", "192.168.1.50"])
        findings = validate_spawn(_manifest(), proposal)
        summary  = summarise(findings)
        self.assertIn("error", summary.lower())
        self.assertIn("warning", summary.lower())


if __name__ == "__main__":
    unittest.main()
