#!/usr/bin/env python3
"""
Tests for Milestone 7.1 — Service Contract Implementation.

Covers:
  - ServiceContractRegistry (lookups, dependency_pairs, startup_order_pairs)
  - ServiceContractValidator (observed vs declared findings)
  - build_service_contract_registry (factory from manifest)
  - _add_service_edges_from_contracts (dependency graph integration)
  - check_service_contract_coverage (Tier 2 collector coverage reader)
"""

import unittest

from collect_tier2 import check_service_contract_coverage
from dependencies import build_graph
from service_contracts import (
    ServiceContractRegistry,
    ServiceContractValidator,
    build_service_contract_registry,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CONTRACTS = [
    {
        "service": "infra-bootstrap",
        "vm": "infra-bootstrap",
        "vmid": 100,
        "provided_interfaces": [{"protocol": "ssh", "port": 22, "health_check": None}],
        "required_interfaces": [],
        "startup_after": [],
        "backup_job": None,
        "secret_references": ["infra-bootstrap-deploy-key"],
        "owner": "infrastructure",
    },
    {
        "service": "forgejo",
        "vm": "forgejo",
        "vmid": 101,
        "provided_interfaces": [
            {"protocol": "https", "port": 3000, "health_check": "GET /api/healthz"},
            {"protocol": "ssh",   "port": 22,   "health_check": None},
        ],
        "required_interfaces": [
            {"service": "postgresql", "protocol": "postgresql", "port": 5432, "critical": True}
        ],
        "startup_after": ["postgresql"],
        "backup_job": "pbs-daily-vms",
        "secret_references": ["forgejo-admin-password", "forgejo-deploy-key"],
        "owner": "infrastructure",
    },
    {
        "service": "assessment-engine",
        "vm": "assessment-engine",
        "vmid": 103,
        "provided_interfaces": [{"protocol": "ssh", "port": 22, "health_check": None}],
        "required_interfaces": [
            {"service": "forgejo", "protocol": "https", "port": 3000, "critical": True}
        ],
        "startup_after": ["forgejo"],
        "backup_job": "pbs-daily-vms",
        "secret_references": ["assessment-engine-deploy-key"],
        "owner": "infrastructure",
    },
]

RUNNING_VMS = [
    {"vmid": 100, "name": "infra-bootstrap",  "status": "running"},
    {"vmid": 101, "name": "forgejo",           "status": "running"},
    {"vmid": 103, "name": "assessment-engine", "status": "running"},
]


# ---------------------------------------------------------------------------
# ServiceContractRegistry
# ---------------------------------------------------------------------------

class TestServiceContractRegistry(unittest.TestCase):

    def setUp(self):
        self.reg = ServiceContractRegistry(CONTRACTS)

    def test_available_true_when_contracts_present(self):
        self.assertTrue(self.reg.available())

    def test_available_false_when_empty(self):
        self.assertFalse(ServiceContractRegistry([]).available())

    def test_count(self):
        self.assertEqual(self.reg.count(), 3)

    def test_get_by_service_id(self):
        c = self.reg.get("forgejo")
        self.assertIsNotNone(c)
        self.assertEqual(c["vm"], "forgejo")

    def test_get_returns_none_for_unknown(self):
        self.assertIsNone(self.reg.get("nonexistent"))

    def test_for_vm(self):
        contracts = self.reg.for_vm("assessment-engine")
        self.assertEqual(len(contracts), 1)
        self.assertEqual(contracts[0]["service"], "assessment-engine")

    def test_for_vm_empty_when_no_match(self):
        self.assertEqual(self.reg.for_vm("no-such-vm"), [])

    def test_all(self):
        self.assertEqual(len(self.reg.all()), 3)

    def test_service_ids(self):
        ids = self.reg.service_ids()
        self.assertIn("forgejo", ids)
        self.assertIn("assessment-engine", ids)
        self.assertIn("infra-bootstrap", ids)

    def test_vm_names(self):
        names = self.reg.vm_names()
        self.assertIn("forgejo", names)
        self.assertIn("assessment-engine", names)

    def test_dependency_pairs_assessment_needs_forgejo(self):
        pairs = self.reg.dependency_pairs()
        consumer_vms = [p[0] for p in pairs]
        provider_vms = [p[1] for p in pairs]
        self.assertIn("assessment-engine", consumer_vms)
        self.assertIn("forgejo", provider_vms)

    def test_dependency_pairs_excludes_undeclared_providers(self):
        # postgresql has no declared contract — pair should not appear
        pairs = self.reg.dependency_pairs()
        provider_vms = [p[1] for p in pairs]
        self.assertNotIn("postgresql", provider_vms)

    def test_dependency_pairs_no_self_loops(self):
        pairs = self.reg.dependency_pairs()
        for consumer, provider, _ in pairs:
            self.assertNotEqual(consumer, provider)

    def test_startup_order_pairs_assessment_after_forgejo(self):
        pairs = self.reg.startup_order_pairs()
        self.assertIn(("assessment-engine", "forgejo"), [(p[0], p[1]) for p in pairs])

    def test_startup_order_excludes_undeclared(self):
        # forgejo starts after postgresql — but postgresql has no contract
        pairs = self.reg.startup_order_pairs()
        self.assertNotIn("postgresql", [p[1] for p in pairs])

    def test_empty_registry_returns_empty_pairs(self):
        reg = ServiceContractRegistry([])
        self.assertEqual(reg.dependency_pairs(), [])
        self.assertEqual(reg.startup_order_pairs(), [])


# ---------------------------------------------------------------------------
# ServiceContractValidator
# ---------------------------------------------------------------------------

class TestServiceContractValidator(unittest.TestCase):

    def setUp(self):
        self.reg = ServiceContractRegistry(CONTRACTS)
        self.val = ServiceContractValidator(self.reg)

    def test_no_findings_when_all_vms_running_and_all_deps_declared(self):
        # Use a self-contained registry where all required services are declared.
        contracts_closed = [
            {
                "service": "forgejo",
                "vm": "forgejo",
                "provided_interfaces": [{"protocol": "https", "port": 3000}],
                "required_interfaces": [],
                "startup_after": [],
            },
            {
                "service": "assessment-engine",
                "vm": "assessment-engine",
                "provided_interfaces": [],
                "required_interfaces": [
                    {"service": "forgejo", "protocol": "https", "port": 3000, "critical": True}
                ],
                "startup_after": ["forgejo"],
            },
        ]
        reg = ServiceContractRegistry(contracts_closed)
        val = ServiceContractValidator(reg)
        vms = [
            {"name": "forgejo",           "status": "running"},
            {"name": "assessment-engine", "status": "running"},
        ]
        self.assertEqual(val.validate(vms), [])

    def test_yellow_finding_for_forgejo_undeclared_postgresql_in_full_contracts(self):
        # In CONTRACTS, forgejo requires postgresql (critical) but postgresql has no
        # declared contract — the validator should surface this as YELLOW.
        findings = self.val.validate(RUNNING_VMS)
        undeclared = [f for f in findings if "postgresql" in f.get("issue", "")]
        self.assertEqual(len(undeclared), 1)
        self.assertEqual(undeclared[0]["severity"], "YELLOW")

    def test_red_finding_when_vm_exists_but_stopped(self):
        vms = [
            {"vmid": 100, "name": "infra-bootstrap",  "status": "running"},
            {"vmid": 101, "name": "forgejo",           "status": "stopped"},
            {"vmid": 103, "name": "assessment-engine", "status": "running"},
        ]
        findings = self.val.validate(vms)
        red = [f for f in findings if f["severity"] == "RED"]
        self.assertTrue(any(f["vm"] == "forgejo" for f in red))

    def test_red_finding_when_critical_dependency_not_running(self):
        # forgejo stopped → assessment-engine (critical dep on forgejo) gets RED finding
        vms = [
            {"vmid": 100, "name": "infra-bootstrap",  "status": "running"},
            {"vmid": 101, "name": "forgejo",           "status": "stopped"},
            {"vmid": 103, "name": "assessment-engine", "status": "running"},
        ]
        findings = self.val.validate(vms)
        red_ae = [f for f in findings
                  if f["severity"] == "RED" and f["service"] == "assessment-engine"]
        self.assertTrue(len(red_ae) >= 1, "Expected RED finding for assessment-engine")

    def test_yellow_finding_when_vm_absent_from_inventory(self):
        vms = [
            {"vmid": 101, "name": "forgejo",           "status": "running"},
            {"vmid": 103, "name": "assessment-engine", "status": "running"},
            # infra-bootstrap absent
        ]
        findings = self.val.validate(vms)
        yellow = [f for f in findings
                  if f["severity"] == "YELLOW" and f["vm"] == "infra-bootstrap"]
        self.assertEqual(len(yellow), 1)

    def test_yellow_finding_for_undeclared_required_service(self):
        # forgejo requires postgresql (critical) but postgresql has no contract
        findings = self.val.validate(RUNNING_VMS)
        yellow = [f for f in findings
                  if "postgresql" in f.get("issue", "")]
        self.assertEqual(len(yellow), 1)
        self.assertEqual(yellow[0]["severity"], "YELLOW")

    def test_empty_vm_list_produces_absent_findings(self):
        findings = self.val.validate([])
        # All 3 declared VMs should get YELLOW (absent from inventory)
        self.assertEqual(len(findings), 3)
        self.assertTrue(all(f["severity"] == "YELLOW" for f in findings))

    def test_no_findings_for_empty_registry(self):
        val = ServiceContractValidator(ServiceContractRegistry([]))
        self.assertEqual(val.validate(RUNNING_VMS), [])


# ---------------------------------------------------------------------------
# build_service_contract_registry
# ---------------------------------------------------------------------------

class TestBuildServiceContractRegistry(unittest.TestCase):

    def test_builds_from_manifest(self):
        manifest = {"service_contracts": CONTRACTS}
        reg = build_service_contract_registry(manifest)
        self.assertTrue(reg.available())
        self.assertEqual(reg.count(), 3)

    def test_empty_registry_when_key_absent(self):
        reg = build_service_contract_registry({})
        self.assertFalse(reg.available())

    def test_empty_registry_when_contracts_empty_list(self):
        reg = build_service_contract_registry({"service_contracts": []})
        self.assertFalse(reg.available())


# ---------------------------------------------------------------------------
# Dependency graph integration
# ---------------------------------------------------------------------------

class TestServiceContractEdgesInGraph(unittest.TestCase):

    def _manifest_with_contracts(self):
        return {
            "host": {"hostname": "pve01"},
            "vms": [
                {"vmid": 101, "name": "forgejo",           "status": "running",
                 "cores": 2, "memory_mb": 2048, "disk_gb": 50},
                {"vmid": 103, "name": "assessment-engine", "status": "running",
                 "cores": 2, "memory_mb": 2048, "disk_gb": 50},
            ],
            "service_contracts": [
                {
                    "service": "forgejo",
                    "vm": "forgejo",
                    "provided_interfaces": [
                        {"protocol": "https", "port": 3000}
                    ],
                    "required_interfaces": [],
                    "startup_after": [],
                },
                {
                    "service": "assessment-engine",
                    "vm": "assessment-engine",
                    "provided_interfaces": [],
                    "required_interfaces": [
                        {"service": "forgejo", "protocol": "https",
                         "port": 3000, "critical": True}
                    ],
                    "startup_after": ["forgejo"],
                },
            ],
        }

    def test_contract_edges_present_in_graph(self):
        manifest = self._manifest_with_contracts()
        g = build_graph(manifest)
        edge_types = {e.type for e in g.edges}
        self.assertIn("SERVICE", edge_types)

    def test_assessment_engine_has_service_edge_to_forgejo(self):
        manifest = self._manifest_with_contracts()
        g = build_graph(manifest)
        service_edges = [
            (e.from_id, e.to_id) for e in g.edges if e.type == "SERVICE"
        ]
        self.assertIn(("vm:assessment-engine", "vm:forgejo"), service_edges)

    def test_depends_on_edge_from_startup_after(self):
        manifest = self._manifest_with_contracts()
        g = build_graph(manifest)
        depends_edges = [
            (e.from_id, e.to_id) for e in g.edges if e.type == "DEPENDS_ON"
        ]
        self.assertIn(("vm:assessment-engine", "vm:forgejo"), depends_edges)

    def test_no_service_edges_when_no_contracts(self):
        manifest = {
            "host": {"hostname": "pve01"},
            "vms": [
                {"vmid": 101, "name": "forgejo",           "status": "running",
                 "cores": 2, "memory_mb": 2048, "disk_gb": 50},
                {"vmid": 103, "name": "assessment-engine", "status": "running",
                 "cores": 2, "memory_mb": 2048, "disk_gb": 50},
            ],
            # no service_contracts key → falls back to heuristics
        }
        g = build_graph(manifest)
        service_edges = [e for e in g.edges if e.type == "SERVICE"]
        # Heuristics produce NETWORK edges, not SERVICE edges
        self.assertEqual(service_edges, [])

    def test_topological_order_forgejo_before_assessment(self):
        manifest = self._manifest_with_contracts()
        g = build_graph(manifest)
        node_order = []
        for wave in g.restore_waves:
            node_order.extend(wave.component_ids)
        forgejo_pos     = node_order.index("vm:forgejo")
        assessment_pos  = node_order.index("vm:assessment-engine")
        self.assertLess(forgejo_pos, assessment_pos,
                        "forgejo must be restored before assessment-engine")

    def test_no_self_loop_edges(self):
        manifest = self._manifest_with_contracts()
        g = build_graph(manifest)
        for edge in g.edges:
            self.assertNotEqual(edge.from_id, edge.to_id,
                                f"Self-loop detected: {edge.from_id}")

    def test_undeclared_provider_not_added_as_node(self):
        # postgresql is required by forgejo but has no contract and no VM in manifest
        manifest = self._manifest_with_contracts()
        manifest["service_contracts"][0]["required_interfaces"] = [
            {"service": "postgresql", "protocol": "postgresql", "port": 5432, "critical": True}
        ]
        g = build_graph(manifest)
        node_ids = {n.id for n in g.nodes}
        self.assertNotIn("vm:postgresql", node_ids)


# ---------------------------------------------------------------------------
# check_service_contract_coverage (collect_tier2 reader)
# ---------------------------------------------------------------------------

class TestCheckServiceContractCoverage(unittest.TestCase):

    def test_no_gaps_when_all_vms_observed(self):
        state = {"service_contracts": CONTRACTS}
        observed = [
            {"name": "infra-bootstrap"},
            {"name": "forgejo"},
            {"name": "assessment-engine"},
        ]
        gaps = check_service_contract_coverage(state, observed)
        self.assertEqual(gaps, [])

    def test_gap_when_vm_not_observed(self):
        state = {"service_contracts": CONTRACTS}
        observed = [
            {"name": "infra-bootstrap"},
            {"name": "forgejo"},
            # assessment-engine absent
        ]
        gaps = check_service_contract_coverage(state, observed)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["service"], "assessment-engine")
        self.assertEqual(gaps[0]["vm"], "assessment-engine")
        self.assertIn("not observed", gaps[0]["issue"])

    def test_multiple_gaps(self):
        state = {"service_contracts": CONTRACTS}
        gaps = check_service_contract_coverage(state, [])
        self.assertEqual(len(gaps), 3)

    def test_no_gaps_when_no_contracts(self):
        state = {}
        gaps = check_service_contract_coverage(state, [])
        self.assertEqual(gaps, [])

    def test_no_gaps_when_empty_contracts(self):
        state = {"service_contracts": []}
        gaps = check_service_contract_coverage(state, [])
        self.assertEqual(gaps, [])


if __name__ == "__main__":
    unittest.main()
