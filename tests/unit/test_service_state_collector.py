#!/usr/bin/env python3
"""
Tests for Milestone 7.2 — Service State Schema and Collection.

Covers:
  - service_state_collector.collect_service_state()
  - Services section: contract-covered and uncovered VMs
  - DNS registrations section
  - Backup assignments section
  - Status normalisation
  - Readiness scorer: _score_service_contract_completeness()
  - service-state.json fixture validates against service-state-schema.json
"""

import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent

from service_state_collector import (
    _build_backup_assignments,
    _build_dns_registrations,
    _build_services,
    _normalise_status,
    _primary_interface,
    collect_service_state,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BOOTSTRAP_STATE = {
    "schema_version": "1.0",
    "cell_id": "proxmox-cell-a",
    "vms": [
        {"vmid": 100, "name": "infra-bootstrap", "role": "infra-bootstrap"},
        {"vmid": 101, "name": "forgejo",          "role": "forgejo"},
        {"vmid": 102, "name": "inventory",        "role": "inventory"},
    ],
    "service_contracts": [
        {
            "service": "forgejo",
            "vm": "forgejo",
            "vmid": 101,
            "provided_interfaces": [
                {"protocol": "https", "port": 3000,
                 "url_pattern": "https://forgejo.internal",
                 "health_check": "GET /api/healthz"},
                {"protocol": "ssh", "port": 22},
            ],
            "required_interfaces": [],
            "startup_after": [],
            "backup_job": "pbs-daily-vms",
            "secret_references": ["forgejo-admin-password"],
            "owner": "infrastructure",
        },
        {
            "service": "infra-bootstrap",
            "vm": "infra-bootstrap",
            "vmid": 100,
            "provided_interfaces": [
                {"protocol": "ssh", "port": 22},
            ],
            "required_interfaces": [],
            "startup_after": [],
            "backup_job": None,
            "secret_references": ["infra-bootstrap-deploy-key"],
            "owner": "infrastructure",
        },
    ],
    "dns_registry": [
        {"hostname": "pve01.internal",   "ip": "192.168.1.10", "vmid": None, "role": "proxmox-host"},
        {"hostname": "forgejo.internal", "ip": "192.168.1.21", "vmid": 101,  "role": "forgejo"},
        {"hostname": "inventory.internal","ip": "192.168.1.22", "vmid": 102,  "role": "inventory"},
    ],
}

OBSERVED_VMS = [
    {"vmid": 100, "name": "infra-bootstrap", "status": "running"},
    {"vmid": 101, "name": "forgejo",          "status": "running"},
    {"vmid": 102, "name": "inventory",        "status": "stopped"},
]


# ---------------------------------------------------------------------------
# collect_service_state — top-level
# ---------------------------------------------------------------------------

class TestCollectServiceState(unittest.TestCase):

    def setUp(self):
        self.result = collect_service_state(
            BOOTSTRAP_STATE, OBSERVED_VMS,
            collected_at="2026-05-31T12:00:00Z",
        )

    def test_schema_version(self):
        self.assertEqual(self.result["schema_version"], "1.0")

    def test_cell_id_from_bootstrap_state(self):
        self.assertEqual(self.result["cell_id"], "proxmox-cell-a")

    def test_cell_id_override(self):
        r = collect_service_state(BOOTSTRAP_STATE, OBSERVED_VMS,
                                  cell_id="override-cell",
                                  collected_at="2026-05-31T12:00:00Z")
        self.assertEqual(r["cell_id"], "override-cell")

    def test_collected_at_preserved(self):
        self.assertEqual(self.result["collected_at"], "2026-05-31T12:00:00Z")

    def test_has_all_sections(self):
        for key in ("services", "dns_registrations", "backup_assignments",
                    "collection_errors"):
            self.assertIn(key, self.result)

    def test_collection_errors_empty(self):
        self.assertEqual(self.result["collection_errors"], [])

    def test_default_collected_at_is_set(self):
        r = collect_service_state(BOOTSTRAP_STATE, OBSERVED_VMS)
        self.assertIn("T", r["collected_at"])


# ---------------------------------------------------------------------------
# _build_services
# ---------------------------------------------------------------------------

class TestBuildServices(unittest.TestCase):

    def setUp(self):
        contracts   = BOOTSTRAP_STATE["service_contracts"]
        declared    = BOOTSTRAP_STATE["vms"]
        obs         = {v["name"]: v for v in OBSERVED_VMS}
        self.services = _build_services(contracts, declared, obs)
        self.by_name  = {s["name"]: s for s in self.services}

    def test_forgejo_status_running(self):
        self.assertEqual(self.by_name["forgejo"]["status"], "running")

    def test_infra_bootstrap_status_running(self):
        self.assertEqual(self.by_name["infra-bootstrap"]["status"], "running")

    def test_contract_declared_true_for_contracted_vms(self):
        self.assertTrue(self.by_name["forgejo"]["contract_declared"])
        self.assertTrue(self.by_name["infra-bootstrap"]["contract_declared"])

    def test_contract_declared_false_for_uncovered_vm(self):
        # inventory has no contract in BOOTSTRAP_STATE.service_contracts
        self.assertFalse(self.by_name["inventory"]["contract_declared"])

    def test_forgejo_port_from_non_ssh_interface(self):
        self.assertEqual(self.by_name["forgejo"]["port"], 3000)

    def test_forgejo_protocol(self):
        self.assertEqual(self.by_name["forgejo"]["protocol"], "https")

    def test_forgejo_health_check_url_built(self):
        url = self.by_name["forgejo"]["health_check_url"]
        self.assertIsNotNone(url)
        self.assertIn("healthz", url)
        self.assertIn("forgejo.internal", url)

    def test_infra_bootstrap_port_is_ssh(self):
        # Only SSH interface — primary picks first
        self.assertEqual(self.by_name["infra-bootstrap"]["port"], 22)

    def test_infra_bootstrap_no_health_check(self):
        self.assertIsNone(self.by_name["infra-bootstrap"]["health_check_url"])

    def test_secret_references_populated(self):
        self.assertIn("forgejo-admin-password",
                      self.by_name["forgejo"]["secret_references"])

    def test_uncovered_vm_has_name_and_vmid(self):
        inv = self.by_name["inventory"]
        self.assertEqual(inv["vm"], "inventory")
        self.assertEqual(inv["vmid"], 102)

    def test_stopped_vm_status_in_service(self):
        inv = self.by_name["inventory"]
        self.assertEqual(inv["status"], "stopped")

    def test_all_three_vms_covered(self):
        self.assertEqual(len(self.services), 3)

    def test_no_duplicate_entries(self):
        names = [s["name"] for s in self.services]
        self.assertEqual(len(names), len(set(names)))


# ---------------------------------------------------------------------------
# _build_dns_registrations
# ---------------------------------------------------------------------------

class TestBuildDnsRegistrations(unittest.TestCase):

    def setUp(self):
        self.regs = _build_dns_registrations(BOOTSTRAP_STATE["dns_registry"])

    def test_correct_count(self):
        self.assertEqual(len(self.regs), 3)

    def test_in_dns_registry_always_true(self):
        for r in self.regs:
            self.assertTrue(r["in_dns_registry"])

    def test_drift_from_registry_false(self):
        for r in self.regs:
            self.assertFalse(r["drift_from_registry"])

    def test_hostname_and_ip_present(self):
        hostnames = {r["hostname"] for r in self.regs}
        self.assertIn("forgejo.internal", hostnames)
        self.assertIn("pve01.internal", hostnames)

    def test_skips_entries_without_hostname_or_ip(self):
        dns = [{"hostname": "", "ip": "10.0.0.1"}, {"hostname": "x.local", "ip": ""}]
        regs = _build_dns_registrations(dns)
        self.assertEqual(len(regs), 0)

    def test_empty_registry(self):
        self.assertEqual(_build_dns_registrations([]), [])


# ---------------------------------------------------------------------------
# _build_backup_assignments
# ---------------------------------------------------------------------------

class TestBuildBackupAssignments(unittest.TestCase):

    def setUp(self):
        contracts  = BOOTSTRAP_STATE["service_contracts"]
        declared   = BOOTSTRAP_STATE["vms"]
        obs_vmid   = {v["vmid"]: v for v in OBSERVED_VMS}
        self.assignments = _build_backup_assignments(declared, contracts, obs_vmid)
        self.by_vmid     = {a["vmid"]: a for a in self.assignments}

    def test_one_assignment_per_declared_vm(self):
        self.assertEqual(len(self.assignments), 3)

    def test_forgejo_backup_job_from_contract(self):
        self.assertEqual(self.by_vmid[101]["backup_job_id"], "pbs-daily-vms")
        self.assertTrue(self.by_vmid[101]["in_contract"])

    def test_infra_bootstrap_no_backup_job(self):
        self.assertIsNone(self.by_vmid[100]["backup_job_id"])
        self.assertFalse(self.by_vmid[100]["in_contract"])

    def test_inventory_no_contract_so_no_job(self):
        # inventory has no contract → backup_job_id=None, in_contract=False
        self.assertIsNone(self.by_vmid[102]["backup_job_id"])
        self.assertFalse(self.by_vmid[102]["in_contract"])

    def test_live_backup_fields_are_null(self):
        for a in self.assignments:
            self.assertIsNone(a["last_run_at"])
            self.assertIsNone(a["last_successful_backup_at"])
            self.assertIsNone(a["backup_age_hours"])

    def test_last_run_status_is_never(self):
        for a in self.assignments:
            self.assertEqual(a["last_run_status"], "never")


# ---------------------------------------------------------------------------
# _normalise_status
# ---------------------------------------------------------------------------

class TestNormaliseStatus(unittest.TestCase):

    def test_running(self):
        self.assertEqual(_normalise_status("running"), "running")

    def test_stopped(self):
        self.assertEqual(_normalise_status("stopped"), "stopped")

    def test_paused_maps_to_stopped(self):
        self.assertEqual(_normalise_status("paused"), "stopped")

    def test_unknown(self):
        self.assertEqual(_normalise_status("unknown"), "unknown")

    def test_unrecognised_maps_to_unknown(self):
        self.assertEqual(_normalise_status(""), "unknown")
        self.assertEqual(_normalise_status("crashed"), "unknown")


# ---------------------------------------------------------------------------
# _primary_interface
# ---------------------------------------------------------------------------

class TestPrimaryInterface(unittest.TestCase):

    def test_prefers_non_ssh(self):
        ifaces = [
            {"protocol": "ssh",   "port": 22},
            {"protocol": "https", "port": 3000},
        ]
        result = _primary_interface(ifaces)
        self.assertEqual(result["protocol"], "https")

    def test_falls_back_to_ssh_when_only_ssh(self):
        ifaces = [{"protocol": "ssh", "port": 22}]
        result = _primary_interface(ifaces)
        self.assertEqual(result["protocol"], "ssh")

    def test_empty_list_returns_empty_dict(self):
        self.assertEqual(_primary_interface([]), {})


# ---------------------------------------------------------------------------
# Readiness scorer: service contract completeness
# ---------------------------------------------------------------------------

class TestScoreServiceContractCompleteness(unittest.TestCase):

    def setUp(self):
        from dependencies import build_graph
        from readiness import _score_service_contract_completeness
        self._scorer = _score_service_contract_completeness
        self._build_graph = build_graph

    def _make_manifest(self, contracts, vm_names):
        return {
            "host": {"hostname": "pve01"},
            "vms": [
                {"vmid": i + 100, "name": n, "status": "running",
                 "cores": 2, "memory_mb": 2048, "disk_gb": 50}
                for i, n in enumerate(vm_names)
            ],
            "service_contracts": contracts,
        }

    def test_no_gaps_when_all_vms_have_contracts(self):
        manifest = self._make_manifest(
            contracts=[
                {"service": "forgejo",           "vm": "forgejo"},
                {"service": "assessment-engine", "vm": "assessment-engine"},
            ],
            vm_names=["forgejo", "assessment-engine"],
        )
        graph = self._build_graph(manifest)
        gaps = self._scorer(graph, manifest)
        self.assertEqual(gaps, [])

    def test_yellow_gap_for_vm_without_contract(self):
        manifest = self._make_manifest(
            contracts=[{"service": "forgejo", "vm": "forgejo"}],
            vm_names=["forgejo", "assessment-engine"],
        )
        graph = self._build_graph(manifest)
        gaps = self._scorer(graph, manifest)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].severity, "YELLOW")
        self.assertIn("assessment-engine", gaps[0].description)

    def test_single_gap_when_no_contracts_at_all(self):
        manifest = self._make_manifest(contracts=[], vm_names=["forgejo", "inventory"])
        graph = self._build_graph(manifest)
        gaps = self._scorer(graph, manifest)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].gap_type, "MISSING_SERVICE_CONTRACTS")
        self.assertEqual(gaps[0].severity, "YELLOW")

    def test_gap_type_is_missing_service_contract(self):
        manifest = self._make_manifest(
            contracts=[{"service": "forgejo", "vm": "forgejo"}],
            vm_names=["forgejo", "assessment-engine"],
        )
        graph = self._build_graph(manifest)
        gaps = self._scorer(graph, manifest)
        self.assertEqual(gaps[0].gap_type, "MISSING_SERVICE_CONTRACT")

    def test_non_vm_nodes_not_flagged(self):
        # Storage and network nodes should not produce contract gaps
        manifest = {
            "host": {"hostname": "pve01"},
            "vms": [],
            "storage": {"zfs_pools": [{"name": "tank", "topology": "mirror",
                                        "free_gb": 500, "total_gb": 1000,
                                        "state": "ONLINE", "devices": []}]},
            "service_contracts": [],
        }
        from dependencies import build_graph
        graph = build_graph(manifest)
        gaps = self._scorer(graph, manifest)
        # Only the single MISSING_SERVICE_CONTRACTS gap, not per-storage-node gaps
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].gap_type, "MISSING_SERVICE_CONTRACTS")


# ---------------------------------------------------------------------------
# Fixture validates against schema
# ---------------------------------------------------------------------------

class TestServiceStateFixtureSchema(unittest.TestCase):

    def test_fixture_validates(self):
        import jsonschema
        schema_path  = REPO_ROOT / "data-model" / "service-state-schema.json"
        fixture_path = REPO_ROOT / "tests" / "fixtures" / "bootstrap" / "service-state.json"
        schema  = json.loads(schema_path.read_text(encoding="utf-8"))
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        # Should not raise
        jsonschema.validate(fixture, schema)

    def test_fixture_has_cell_id(self):
        fixture_path = REPO_ROOT / "tests" / "fixtures" / "bootstrap" / "service-state.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        self.assertEqual(fixture["cell_id"], "proxmox-cell-a")

    def test_all_services_have_contract_declared(self):
        fixture_path = REPO_ROOT / "tests" / "fixtures" / "bootstrap" / "service-state.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        for svc in fixture["services"]:
            self.assertTrue(
                svc.get("contract_declared"),
                f"Service '{svc['name']}' should have contract_declared=true after 7.1"
            )


if __name__ == "__main__":
    unittest.main()
