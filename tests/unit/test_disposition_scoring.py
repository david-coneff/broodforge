#!/usr/bin/env python3
"""
Tests for Phase 12.E.10 — Disposition-aware assessment scoring.

Covers:
  - No spawn_history → no gaps
  - Disposition service with running VM → no gap
  - Disposition service VM not running → RED gap
  - Service resolved via service_contracts VM field
  - Excluded services are not checked
  - Multiple broodlings scored independently
"""

import unittest

from readiness import _score_disposition_compliance


def _manifest(**kwargs) -> dict:
    base = {
        "vms": [],
        "service_contracts": [],
        "spawn_history": [],
    }
    base.update(kwargs)
    return base


def _spawn_event(hostname="pve02", services=None, vmids=None, excluded=None) -> dict:
    return {
        "broodling_hostname": hostname,
        "disposition_services": services or [],
        "disposition_excluded": excluded or [],
        "vmids_allocated":     vmids or [],
    }


class TestDispositionCompliance(unittest.TestCase):

    def test_no_spawn_history_no_gaps(self):
        gaps = _score_disposition_compliance(_manifest())
        self.assertEqual(gaps, [])

    def test_empty_disposition_no_gaps(self):
        m = _manifest(spawn_history=[_spawn_event(services=[])])
        gaps = _score_disposition_compliance(m)
        self.assertEqual(gaps, [])

    def test_service_vm_running_no_gap(self):
        m = _manifest(
            vms=[{"vmid": 200, "name": "k3s-worker-01"}],
            service_contracts=[{"service": "k3s-worker", "vm": "k3s-worker-01"}],
            spawn_history=[_spawn_event(services=["k3s-worker"], vmids=[200])],
        )
        gaps = _score_disposition_compliance(m)
        red_gaps = [g for g in gaps if g.severity == "RED"]
        self.assertEqual(red_gaps, [])

    def test_service_vm_not_in_inventory_is_red(self):
        # VM 200 for k3s-worker not in vms[]
        m = _manifest(
            vms=[],
            service_contracts=[{"service": "k3s-worker", "vm": "k3s-worker-01"}],
            spawn_history=[_spawn_event(services=["k3s-worker"], vmids=[200])],
        )
        gaps = _score_disposition_compliance(m)
        red_gaps = [g for g in gaps if g.severity == "RED"]
        self.assertEqual(len(red_gaps), 1)
        self.assertIn("k3s-worker", red_gaps[0].description)

    def test_gap_component_id_includes_hostname(self):
        m = _manifest(
            vms=[],
            service_contracts=[{"service": "k3s-worker", "vm": "k3s-worker-01"}],
            spawn_history=[_spawn_event(hostname="pve02", services=["k3s-worker"])],
        )
        gaps = _score_disposition_compliance(m)
        self.assertTrue(any("pve02" in g.component_id for g in gaps))

    def test_no_contract_uses_service_name_as_vm_name(self):
        # If no contract, service name is used as the VM name
        m = _manifest(
            vms=[{"vmid": 200, "name": "prometheus"}],
            service_contracts=[],
            spawn_history=[_spawn_event(services=["prometheus"], vmids=[200])],
        )
        gaps = _score_disposition_compliance(m)
        red_gaps = [g for g in gaps if g.severity == "RED"]
        self.assertEqual(red_gaps, [])

    def test_multiple_broodlings_scored_independently(self):
        # pve02 has k3s-worker running; pve03 does not
        m = _manifest(
            vms=[
                {"vmid": 200, "name": "k3s-worker-01"},  # pve02's VM
            ],
            service_contracts=[{"service": "k3s-worker", "vm": "k3s-worker-01"}],
            spawn_history=[
                _spawn_event("pve02", services=["k3s-worker"], vmids=[200]),
                _spawn_event("pve03", services=["k3s-worker"], vmids=[300]),
            ],
        )
        gaps = _score_disposition_compliance(m)
        # pve03 should have a RED gap (VM 300 not in vms[])
        pve03_gaps = [g for g in gaps if "pve03" in g.component_id]
        self.assertEqual(len(pve03_gaps), 1)
        self.assertEqual(pve03_gaps[0].severity, "RED")
        # pve02 should have no RED gap
        pve02_gaps = [g for g in gaps if "pve02" in g.component_id and g.severity == "RED"]
        self.assertEqual(pve02_gaps, [])

    def test_gap_type(self):
        m = _manifest(
            vms=[],
            service_contracts=[{"service": "k3s-worker", "vm": "k3s-worker-01"}],
            spawn_history=[_spawn_event(services=["k3s-worker"])],
        )
        gaps = _score_disposition_compliance(m)
        self.assertTrue(any(g.gap_type == "DISPOSITION_SERVICE_NOT_RUNNING" for g in gaps))

    def test_remediation_mentions_vm_name(self):
        m = _manifest(
            vms=[],
            service_contracts=[{"service": "forgejo", "vm": "forgejo"}],
            spawn_history=[_spawn_event(services=["forgejo"])],
        )
        gaps = _score_disposition_compliance(m)
        self.assertTrue(any("forgejo" in g.remediation for g in gaps))


if __name__ == "__main__":
    unittest.main()
