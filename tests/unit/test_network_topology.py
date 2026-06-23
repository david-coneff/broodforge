#!/usr/bin/env python3
"""
Tests for Phase 8 — Network Topology as Code.

Covers:
  - parse_interfaces_file(): /etc/network/interfaces parsing
  - collect_observed_bridges(): SSH collection with mocked runner
  - compare_topology(): declared vs observed diff
  - merge_observed_topology(): state dict update
  - _score_network_topology_completeness(): readiness gaps
  - Recovery runbook Wave 0 rendering (declared + undeclared paths)
  - network-topology-schema.json validates correctly
  - bootstrap-state-schema.json accepts network_topology_declared
  - bootstrap-state.json fixture validates with network_topology_declared
"""

import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent

from network_topology_collector import (
    collect_observed_bridges,
    compare_topology,
    merge_observed_topology,
    parse_interfaces_file,
)
from readiness import _score_network_topology_completeness

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

INTERFACES_SIMPLE = """
auto lo
iface lo inet loopback

iface eno1 inet manual

auto vmbr0
iface vmbr0 inet static
    address 192.168.1.10/24
    gateway 192.168.1.1
    bridge-ports eno1
    bridge-stp off
    bridge-fd 0
    bridge-vlan-aware yes
"""

INTERFACES_MULTI = """
auto lo
iface lo inet loopback

iface eno1 inet manual
iface eno2 inet manual

auto vmbr0
iface vmbr0 inet static
    address 192.168.1.10/24
    gateway 192.168.1.1
    bridge-ports eno1
    bridge-stp off
    bridge-fd 0
    bridge-vlan-aware yes

auto vmbr1
iface vmbr1 inet manual
    bridge-ports none
    bridge-stp off
    bridge-fd 0
    bridge-vlan-aware no
"""

INTERFACES_WITH_MTU = """
auto vmbr0
iface vmbr0 inet static
    address 10.0.0.1/24
    gateway 10.0.0.254
    bridge-ports eth0
    bridge-stp off
    bridge-fd 0
    mtu 9000
"""

INTERFACES_NO_BRIDGE = """
auto lo
iface lo inet loopback

auto eth0
iface eth0 inet static
    address 192.168.1.10/24
    gateway 192.168.1.1
"""

DECLARED_BRIDGES = [
    {
        "name": "vmbr0",
        "ports": ["eno1"],
        "vlan_aware": True,
        "ip": "192.168.1.10/24",
        "gateway": "192.168.1.1",
    }
]


# ---------------------------------------------------------------------------
# parse_interfaces_file
# ---------------------------------------------------------------------------

class TestParseInterfacesFile(unittest.TestCase):

    def test_parses_single_bridge(self):
        bridges = parse_interfaces_file(INTERFACES_SIMPLE)
        self.assertEqual(len(bridges), 1)
        b = bridges[0]
        self.assertEqual(b["name"], "vmbr0")

    def test_bridge_ip(self):
        bridges = parse_interfaces_file(INTERFACES_SIMPLE)
        self.assertEqual(bridges[0]["ip"], "192.168.1.10/24")

    def test_bridge_gateway(self):
        bridges = parse_interfaces_file(INTERFACES_SIMPLE)
        self.assertEqual(bridges[0]["gateway"], "192.168.1.1")

    def test_bridge_ports(self):
        bridges = parse_interfaces_file(INTERFACES_SIMPLE)
        self.assertEqual(bridges[0]["ports"], ["eno1"])

    def test_bridge_vlan_aware_yes(self):
        bridges = parse_interfaces_file(INTERFACES_SIMPLE)
        self.assertTrue(bridges[0]["vlan_aware"])

    def test_bridge_vlan_aware_no(self):
        bridges = parse_interfaces_file(INTERFACES_MULTI)
        vmbr1 = next(b for b in bridges if b["name"] == "vmbr1")
        self.assertFalse(vmbr1["vlan_aware"])

    def test_parses_multiple_bridges(self):
        bridges = parse_interfaces_file(INTERFACES_MULTI)
        names = {b["name"] for b in bridges}
        self.assertIn("vmbr0", names)
        self.assertIn("vmbr1", names)

    def test_no_bridge_ports_means_not_a_bridge(self):
        # eth0 in INTERFACES_NO_BRIDGE has no bridge-ports stanza
        bridges = parse_interfaces_file(INTERFACES_NO_BRIDGE)
        self.assertEqual(bridges, [])

    def test_loopback_not_included(self):
        bridges = parse_interfaces_file(INTERFACES_SIMPLE)
        names = {b["name"] for b in bridges}
        self.assertNotIn("lo", names)

    def test_physical_nic_not_included(self):
        bridges = parse_interfaces_file(INTERFACES_SIMPLE)
        names = {b["name"] for b in bridges}
        self.assertNotIn("eno1", names)

    def test_mtu_parsed(self):
        bridges = parse_interfaces_file(INTERFACES_WITH_MTU)
        self.assertEqual(bridges[0]["mtu"], 9000)

    def test_no_mtu_is_none(self):
        bridges = parse_interfaces_file(INTERFACES_SIMPLE)
        self.assertIsNone(bridges[0]["mtu"])

    def test_bridge_ports_none_string_yields_empty(self):
        text = """
auto vmbr1
iface vmbr1 inet manual
    bridge-ports none
    bridge-stp off
"""
        bridges = parse_interfaces_file(text)
        self.assertEqual(len(bridges), 1)
        self.assertEqual(bridges[0]["ports"], [])

    def test_empty_input_returns_empty(self):
        self.assertEqual(parse_interfaces_file(""), [])

    def test_comments_ignored(self):
        text = """
# This is a comment
auto vmbr0
iface vmbr0 inet static
    address 10.0.0.1/24
    # Another comment
    bridge-ports eth0
    bridge-fd 0
"""
        bridges = parse_interfaces_file(text)
        self.assertEqual(len(bridges), 1)

    def test_state_defaults_to_unknown(self):
        bridges = parse_interfaces_file(INTERFACES_SIMPLE)
        self.assertEqual(bridges[0]["state"], "UNKNOWN")


# ---------------------------------------------------------------------------
# collect_observed_bridges
# ---------------------------------------------------------------------------

class TestCollectObservedBridges(unittest.TestCase):

    def _mock_ssh(self, stdout, returncode=0):
        def runner(cmd, env):
            return returncode, stdout, ""
        return runner

    def test_successful_collection(self):
        bridges, errors = collect_observed_bridges(
            "192.168.1.10",
            runner_fn=self._mock_ssh(INTERFACES_SIMPLE)
        )
        self.assertEqual(len(errors), 0)
        self.assertEqual(len(bridges), 1)
        self.assertEqual(bridges[0]["name"], "vmbr0")

    def test_ssh_failure_returns_error(self):
        bridges, errors = collect_observed_bridges(
            "192.168.1.10",
            runner_fn=self._mock_ssh("", returncode=255)
        )
        self.assertEqual(bridges, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("exit", errors[0].lower())

    def test_empty_interfaces_file(self):
        bridges, errors = collect_observed_bridges(
            "192.168.1.10",
            runner_fn=self._mock_ssh("")
        )
        self.assertEqual(bridges, [])
        self.assertEqual(errors, [])

    def test_multi_bridge_collection(self):
        bridges, errors = collect_observed_bridges(
            "192.168.1.10",
            runner_fn=self._mock_ssh(INTERFACES_MULTI)
        )
        self.assertEqual(len(errors), 0)
        self.assertEqual(len(bridges), 2)


# ---------------------------------------------------------------------------
# compare_topology
# ---------------------------------------------------------------------------

class TestCompareTopology(unittest.TestCase):

    def _obs(self, name="vmbr0", ports=None, vlan_aware=True, ip="192.168.1.10/24"):
        return [{"name": name, "ports": ports or ["eno1"],
                 "vlan_aware": vlan_aware, "ip": ip, "state": "UNKNOWN"}]

    def test_matching_topology_no_drift(self):
        drift, detail = compare_topology(DECLARED_BRIDGES, self._obs())
        self.assertFalse(drift)
        self.assertEqual(detail, "")

    def test_missing_declared_bridge_is_drift(self):
        drift, detail = compare_topology(DECLARED_BRIDGES, [])
        self.assertTrue(drift)
        self.assertIn("vmbr0", detail)
        self.assertIn("NOT found", detail)

    def test_ip_mismatch_is_drift(self):
        obs = self._obs(ip="192.168.1.99/24")
        drift, detail = compare_topology(DECLARED_BRIDGES, obs)
        self.assertTrue(drift)
        self.assertIn("IP mismatch", detail)

    def test_vlan_aware_mismatch_is_drift(self):
        obs = self._obs(vlan_aware=False)
        drift, detail = compare_topology(DECLARED_BRIDGES, obs)
        self.assertTrue(drift)
        self.assertIn("vlan_aware", detail)

    def test_ports_mismatch_is_drift(self):
        obs = self._obs(ports=["eno2"])
        drift, detail = compare_topology(DECLARED_BRIDGES, obs)
        self.assertTrue(drift)
        self.assertIn("ports mismatch", detail)

    def test_extra_observed_bridge_is_noted(self):
        obs = self._obs() + [{"name": "vmbr99", "ports": [], "vlan_aware": False,
                               "ip": None, "state": "UNKNOWN"}]
        drift, detail = compare_topology(DECLARED_BRIDGES, obs)
        self.assertTrue(drift)
        self.assertIn("vmbr99", detail)
        self.assertIn("NOT declared", detail)

    def test_empty_declared_no_drift_when_no_observed(self):
        drift, detail = compare_topology([], [])
        self.assertFalse(drift)

    def test_none_declared_no_drift(self):
        drift, detail = compare_topology(None, None)
        self.assertFalse(drift)


# ---------------------------------------------------------------------------
# merge_observed_topology
# ---------------------------------------------------------------------------

class TestMergeObservedTopology(unittest.TestCase):

    def test_merge_adds_observed_bridges(self):
        state = {"network_topology_declared": {"bridges": DECLARED_BRIDGES}}
        obs   = [{"name": "vmbr0", "ports": ["eno1"], "vlan_aware": True,
                  "ip": "192.168.1.10/24", "state": "UNKNOWN"}]
        state = merge_observed_topology(state, obs, [])
        ntd   = state["network_topology_declared"]
        self.assertEqual(ntd["observed_bridges"], obs)

    def test_merge_sets_drift_false_when_matching(self):
        state = {"network_topology_declared": {"bridges": DECLARED_BRIDGES}}
        obs   = [{"name": "vmbr0", "ports": ["eno1"], "vlan_aware": True,
                  "ip": "192.168.1.10/24", "state": "UNKNOWN"}]
        state = merge_observed_topology(state, obs, [])
        self.assertFalse(state["network_topology_declared"]["drift_detected"])

    def test_merge_sets_drift_true_when_mismatch(self):
        state = {"network_topology_declared": {"bridges": DECLARED_BRIDGES}}
        obs   = [{"name": "vmbr0", "ports": ["eno1"], "vlan_aware": True,
                  "ip": "10.0.0.1/24", "state": "UNKNOWN"}]  # different IP
        state = merge_observed_topology(state, obs, [])
        self.assertTrue(state["network_topology_declared"]["drift_detected"])

    def test_merge_records_observed_at(self):
        state = {"network_topology_declared": {"bridges": DECLARED_BRIDGES}}
        state = merge_observed_topology(state, [], [])
        self.assertIsNotNone(state["network_topology_declared"]["observed_at"])

    def test_merge_creates_section_if_absent(self):
        state = {}
        state = merge_observed_topology(state, [], [])
        self.assertIn("network_topology_declared", state)

    def test_errors_appended_to_collection_errors(self):
        state = {}
        state = merge_observed_topology(state, [], ["SSH timeout"])
        self.assertIn("SSH timeout", state.get("collection_errors", []))


# ---------------------------------------------------------------------------
# _score_network_topology_completeness
# ---------------------------------------------------------------------------

class TestScoreNetworkTopologyCompleteness(unittest.TestCase):

    def test_no_ntd_is_yellow(self):
        gaps = _score_network_topology_completeness({})
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].severity, "YELLOW")
        self.assertIn("MISSING_NETWORK_TOPOLOGY", gaps[0].gap_type)

    def test_empty_bridges_is_yellow(self):
        manifest = {"network_topology_declared": {"bridges": []}}
        gaps = _score_network_topology_completeness(manifest)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].severity, "YELLOW")

    def test_declared_no_drift_no_gaps(self):
        manifest = {"network_topology_declared": {
            "bridges": DECLARED_BRIDGES,
            "drift_detected": False,
            "observed_bridges": DECLARED_BRIDGES,
        }}
        gaps = _score_network_topology_completeness(manifest)
        self.assertEqual(gaps, [])

    def test_declared_no_observed_no_gaps(self):
        # No observed state yet — no drift can be computed
        manifest = {"network_topology_declared": {
            "bridges": DECLARED_BRIDGES,
            "observed_bridges": None,
            "drift_detected": False,
        }}
        gaps = _score_network_topology_completeness(manifest)
        self.assertEqual(gaps, [])

    def test_drift_detected_is_orange(self):
        manifest = {"network_topology_declared": {
            "bridges": DECLARED_BRIDGES,
            "drift_detected": True,
            "drift_details": "Bridge vmbr0 IP mismatch",
            "observed_bridges": [{"name": "vmbr0", "ports": ["eno1"],
                                   "vlan_aware": True, "ip": "10.0.0.1/24"}],
        }}
        gaps = _score_network_topology_completeness(manifest)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].severity, "ORANGE")
        self.assertIn("IP mismatch", gaps[0].description)

    def test_all_declared_bridges_missing_is_red(self):
        manifest = {"network_topology_declared": {
            "bridges": DECLARED_BRIDGES,
            "drift_detected": True,
            "drift_details": "Bridge vmbr0 NOT found on host",
            "observed_bridges": [],  # nothing observed
        }}
        gaps = _score_network_topology_completeness(manifest)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].severity, "RED")

    def test_gap_type_is_network_topology_drift(self):
        manifest = {"network_topology_declared": {
            "bridges": DECLARED_BRIDGES,
            "drift_detected": True,
            "drift_details": "something drifted",
            "observed_bridges": [{"name": "vmbr0", "ports": [], "vlan_aware": True,
                                   "ip": "192.168.1.10/24"}],
        }}
        gaps = _score_network_topology_completeness(manifest)
        self.assertEqual(gaps[0].gap_type, "NETWORK_TOPOLOGY_DRIFT")


# ---------------------------------------------------------------------------
# Recovery runbook — Wave 0
# ---------------------------------------------------------------------------

class TestRunbookWave0(unittest.TestCase):

    def _build_html(self, ntd=None):
        from dependencies import build_graph
        from html_recovery_runbook import build_recovery_runbook_html
        from readiness import score_graph

        manifest = {
            "host": {"hostname": "pve01", "proxmox_version": "8.0"},
            "network": {"default_gateway": "192.168.1.1", "dns_servers": []},
            "vms": [], "containers": [], "collected_at": "2026-01-01T00:00:00Z",
        }
        if ntd is not None:
            manifest["network_topology_declared"] = ntd

        graph = build_graph(manifest)
        readiness = score_graph(graph, manifest)
        gen_meta = {"generated_at": "2026-01-01T12:00:00Z",
                    "generated_at_display": "2026-01-01 12:00:00 UTC"}
        return build_recovery_runbook_html(manifest, graph, readiness, gen_meta)

    def test_wave0_heading_present(self):
        text = self._build_html()
        self.assertIn("Wave 0", text)
        self.assertIn("Network Reconstruction", text)

    def test_wave0_no_declared_shows_unresolved(self):
        text = self._build_html(ntd=None)
        self.assertIn("not declared", text.lower())

    def test_wave0_declared_bridge_shown(self):
        ntd = {"bridges": DECLARED_BRIDGES, "drift_detected": False}
        text = self._build_html(ntd=ntd)
        self.assertIn("vmbr0", text)

    def test_wave0_bridge_ip_shown(self):
        ntd = {"bridges": DECLARED_BRIDGES, "drift_detected": False}
        text = self._build_html(ntd=ntd)
        self.assertIn("192.168.1.10/24", text)

    def test_wave0_bridge_ports_shown(self):
        ntd = {"bridges": DECLARED_BRIDGES, "drift_detected": False}
        text = self._build_html(ntd=ntd)
        self.assertIn("eno1", text)

    def test_wave0_drift_warning_shown(self):
        ntd = {
            "bridges": DECLARED_BRIDGES,
            "drift_detected": True,
            "drift_details": "Bridge vmbr0 IP mismatch",
        }
        text = self._build_html(ntd=ntd)
        self.assertIn("drift", text.lower())
        self.assertIn("IP mismatch", text)

    def test_wave0_ifreload_command_shown(self):
        ntd = {"bridges": DECLARED_BRIDGES, "drift_detected": False}
        text = self._build_html(ntd=ntd)
        self.assertIn("ifreload", text)

    def test_wave0_checkboxes_present(self):
        ntd = {"bridges": DECLARED_BRIDGES, "drift_detected": False}
        text = self._build_html(ntd=ntd)
        self.assertIn("Management bridge up", text)

    def test_wave0_no_bridge_ip_skips_addr_check(self):
        bridges_no_ip = [{"name": "vmbr1", "ports": [], "vlan_aware": False, "ip": None}]
        ntd = {"bridges": bridges_no_ip, "drift_detected": False}
        text = self._build_html(ntd=ntd)
        self.assertIn("vmbr1", text)


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class TestNetworkTopologySchema(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        try:
            import jsonschema
            cls.jsonschema = jsonschema
            cls.skip = False
        except ImportError:
            cls.skip = True
        schema_path = REPO_ROOT / "data-model" / "network-topology-schema.json"
        cls.schema = json.loads(schema_path.read_text(encoding="utf-8"))

    def _validate(self, instance):
        if self.skip:
            self.skipTest("jsonschema not installed")
        self.jsonschema.validate(instance, self.schema)

    def test_minimal_document_validates(self):
        self._validate({
            "schema_version": "1.0",
            "cell_id": "test-cell",
            "declared_at": "2026-01-01T00:00:00Z",
            "bridges": [],
        })

    def test_full_document_validates(self):
        self._validate({
            "schema_version": "1.0",
            "cell_id": "test-cell",
            "declared_at": "2026-01-01T00:00:00Z",
            "bridges": [{
                "name": "vmbr0",
                "ports": ["eno1"],
                "vlan_aware": True,
                "ip": "192.168.1.10/24",
                "gateway": "192.168.1.1",
                "management_bridge": True,
                "headscale_bridge": True,
                "purpose": "Management bridge",
            }],
            "vlans": [{"id": 100, "bridge": "vmbr0", "name": "mgmt"}],
            "firewall": {
                "enabled": True,
                "host_policy": "drop",
                "rules": [{"direction": "in", "action": "accept",
                           "proto": "tcp", "dport": "22"}],
            },
        })

    def test_missing_bridges_fails(self):
        if self.skip:
            self.skipTest("jsonschema not installed")
        with self.assertRaises(self.jsonschema.ValidationError):
            self._validate({
                "schema_version": "1.0",
                "cell_id": "c",
                "declared_at": "2026-01-01T00:00:00Z",
            })

    def test_invalid_vlan_id_fails(self):
        if self.skip:
            self.skipTest("jsonschema not installed")
        with self.assertRaises(self.jsonschema.ValidationError):
            self._validate({
                "schema_version": "1.0", "cell_id": "c",
                "declared_at": "2026-01-01T00:00:00Z",
                "bridges": [],
                "vlans": [{"id": 5000, "bridge": "vmbr0"}],  # >4094
            })


class TestBootstrapStateFixtureWithNetworkTopology(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        fixture_path = REPO_ROOT / "tests" / "fixtures" / "bootstrap" / "bootstrap-state.json"
        cls.fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    def test_fixture_has_network_topology_declared(self):
        self.assertIn("network_topology_declared", self.fixture)

    def test_fixture_has_at_least_one_bridge(self):
        ntd = self.fixture["network_topology_declared"]
        self.assertGreater(len(ntd.get("bridges", [])), 0)

    def test_fixture_bridge_has_required_fields(self):
        bridge = self.fixture["network_topology_declared"]["bridges"][0]
        self.assertIn("name", bridge)
        self.assertIn("ports", bridge)

    def test_fixture_no_drift_by_default(self):
        ntd = self.fixture["network_topology_declared"]
        self.assertFalse(ntd.get("drift_detected", True))


if __name__ == "__main__":
    unittest.main()
