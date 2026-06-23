#!/usr/bin/env python3
"""
Tests for Phase 12.E.9 — Bootstrap-state updater after spawn.

Covers:
  - update_state_after_spawn(): adds VMs, DNS entries, provenance, spawn_history
  - No duplicate VMIDs or IPs added on repeat calls
  - spawn_history records spawn event fields
  - build_spawn_result(): constructs SpawnResult from spawn-plan.json dict
  - SpawnResult properties
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent

from update_state_after_spawn import (
    SpawnResult,
    build_spawn_result,
    update_state_after_spawn,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _result(**kwargs) -> SpawnResult:
    defaults = dict(
        broodling_hostname="pve02",
        broodling_fqdn="pve02.home.example.com",
        broodling_lan_ip="192.168.1.15",
        broodling_tailnet_ip="100.64.0.2",
        allocated_vmids=[200, 201, 202],
        allocated_ips=["192.168.1.50", "192.168.1.51", "192.168.1.52"],
        disposition_services=["k3s-worker", "monitoring"],
        disposition_excluded=[],
        execution_mode="autonomous",
        k3s_role="worker",
        spawned_at="2026-06-01T12:00:00+00:00",
        spawn_package_id="spawn-package-proxmox-cell-a-pve02-2026-06-01",
        vms_deployed=[
            {"vmid": 200, "name": "k3s-worker-01", "role": "k3s-worker",
             "template_name": "ubuntu-2204-base"},
            {"vmid": 201, "name": "monitoring-01", "role": "monitoring",
             "template_name": "ubuntu-2204-base"},
        ],
        dns_entries=[
            {"hostname": "pve02.internal", "ip": "192.168.1.15", "vmid": None, "role": "proxmox-host"},
            {"hostname": "k3s-worker-01.internal", "ip": "192.168.1.50", "vmid": 200},
        ],
    )
    defaults.update(kwargs)
    return SpawnResult(**defaults)

BASE_STATE = {
    "cell_id": "proxmox-cell-a",
    "vms": [{"vmid": 100, "name": "infra-bootstrap"}],
    "dns_registry": [
        {"hostname": "pve01.internal", "ip": "192.168.1.10", "vmid": None, "role": "proxmox-host"},
    ],
    "provenance_records": [],
}


# ---------------------------------------------------------------------------
# update_state_after_spawn
# ---------------------------------------------------------------------------

class TestUpdateStateAfterSpawn(unittest.TestCase):

    def setUp(self):
        import copy
        self.state  = copy.deepcopy(BASE_STATE)
        self.result = _result()
        self.updated = update_state_after_spawn(self.state, self.result)

    def test_new_vms_added(self):
        vmids = [v["vmid"] for v in self.updated["vms"]]
        self.assertIn(200, vmids)
        self.assertIn(201, vmids)

    def test_original_vm_still_present(self):
        vmids = [v["vmid"] for v in self.updated["vms"]]
        self.assertIn(100, vmids)

    def test_new_dns_entries_added(self):
        ips = {e["ip"] for e in self.updated["dns_registry"]}
        self.assertIn("192.168.1.15", ips)
        self.assertIn("192.168.1.50", ips)

    def test_original_dns_entry_still_present(self):
        ips = {e["ip"] for e in self.updated["dns_registry"]}
        self.assertIn("192.168.1.10", ips)

    def test_provenance_records_added_per_vm(self):
        prov_vmids = [r["vmid"] for r in self.updated.get("provenance_records", [])]
        self.assertIn(200, prov_vmids)
        self.assertIn(201, prov_vmids)

    def test_provenance_notes_mention_spawn(self):
        prov = self.updated["provenance_records"][0]
        self.assertIn("spawn", prov.get("notes", "").lower())

    def test_spawn_history_entry_created(self):
        history = self.updated.get("spawn_history", [])
        self.assertEqual(len(history), 1)

    def test_spawn_history_contains_broodling_info(self):
        event = self.updated["spawn_history"][0]
        self.assertEqual(event["broodling_hostname"], "pve02")
        self.assertEqual(event["broodling_lan_ip"], "192.168.1.15")
        self.assertIn("k3s-worker", event.get("disposition_services", []))

    def test_spawn_history_contains_vmids(self):
        event = self.updated["spawn_history"][0]
        self.assertIn(200, event.get("vmids_allocated", []))

    def test_spawn_history_most_recent_first(self):
        import copy
        state2   = copy.deepcopy(self.updated)
        result2  = _result(broodling_hostname="pve03", spawned_at="2026-06-02T00:00:00+00:00")
        updated2 = update_state_after_spawn(state2, result2)
        self.assertEqual(updated2["spawn_history"][0]["broodling_hostname"], "pve03")


class TestNoDuplicatesOnRepeat(unittest.TestCase):

    def test_repeat_call_does_not_duplicate_vms(self):
        import copy
        state  = copy.deepcopy(BASE_STATE)
        result = _result()
        update_state_after_spawn(state, result)
        update_state_after_spawn(state, result)   # second call
        vmids = [v["vmid"] for v in state["vms"]]
        self.assertEqual(len(vmids), len(set(vmids)))

    def test_repeat_call_does_not_duplicate_dns(self):
        import copy
        state  = copy.deepcopy(BASE_STATE)
        result = _result()
        update_state_after_spawn(state, result)
        update_state_after_spawn(state, result)
        ips = [e["ip"] for e in state["dns_registry"]]
        self.assertEqual(len(ips), len(set(ips)))

    def test_repeat_call_does_not_duplicate_provenance(self):
        import copy
        state  = copy.deepcopy(BASE_STATE)
        result = _result()
        update_state_after_spawn(state, result)
        update_state_after_spawn(state, result)
        prov_vmids = [r["vmid"] for r in state.get("provenance_records", [])]
        self.assertEqual(len(prov_vmids), len(set(prov_vmids)))


class TestHardwareProfileStored(unittest.TestCase):

    def test_hardware_profile_in_spawn_history(self):
        import copy
        state   = copy.deepcopy(BASE_STATE)
        hw      = {"hostname": "pve02", "ram_gb": 32, "disk_count": 2}
        update_state_after_spawn(state, _result(), hardware_profile=hw)
        event = state["spawn_history"][0]
        self.assertEqual(event["hardware_profile"]["ram_gb"], 32)

    def test_no_hardware_profile_is_none(self):
        import copy
        state = copy.deepcopy(BASE_STATE)
        update_state_after_spawn(state, _result())
        self.assertIsNone(state["spawn_history"][0]["hardware_profile"])


# ---------------------------------------------------------------------------
# build_spawn_result
# ---------------------------------------------------------------------------

class TestBuildSpawnResult(unittest.TestCase):

    def _plan(self, **kwargs) -> dict:
        defaults = dict(
            hostname="pve02",
            domain="home.example.com",
            lan_ip="192.168.1.15",
            tailnet_ip="100.64.0.2",
            vmid_block=[200, 201],
            ip_block=["192.168.1.50", "192.168.1.51"],
            k3s_role="worker",
            package_id="spawn-pve02",
            disposition={
                "services": ["k3s-worker"],
                "excluded": [],
                "execution_mode": "autonomous",
            },
            vms=[{"vmid": 200, "name": "k3s-worker-01"}],
            dns_entries=[{"hostname": "pve02.internal", "ip": "192.168.1.15"}],
        )
        defaults.update(kwargs)
        return defaults

    def test_basic_build(self):
        result = build_spawn_result(self._plan(), now_fn=lambda: "2026-06-01T00:00:00+00:00")
        self.assertEqual(result.broodling_hostname, "pve02")
        self.assertEqual(result.broodling_fqdn, "pve02.home.example.com")
        self.assertEqual(result.k3s_role, "worker")

    def test_disposition_services_extracted(self):
        result = build_spawn_result(self._plan())
        self.assertIn("k3s-worker", result.disposition_services)

    def test_execution_mode_extracted(self):
        result = build_spawn_result(self._plan())
        self.assertEqual(result.execution_mode, "autonomous")

    def test_vmid_block_extracted(self):
        result = build_spawn_result(self._plan())
        self.assertEqual(result.allocated_vmids, [200, 201])

    def test_vmids_derived_from_vms_list_when_no_vmid_block(self):
        """Current spawn_planner.py doesn't include vmid_block; VMIDs come from vms[]."""
        plan = self._plan(vmid_block=None)  # Remove vmid_block
        plan["vms"] = [{"vmid": 200, "name": "vm01"}, {"vmid": 201, "name": "vm02"}]
        result = build_spawn_result(plan)
        self.assertIn(200, result.allocated_vmids)
        self.assertIn(201, result.allocated_vmids)

    def test_spawn_timestamp_auto_set(self):
        result = build_spawn_result(self._plan())
        self.assertIsNotNone(result.spawned_at)

    def test_hostname_without_domain_no_dot(self):
        result = build_spawn_result(self._plan(domain=""))
        self.assertNotIn(".", result.broodling_fqdn)


class TestCLI(unittest.TestCase):
    """Tests for the __main__ CLI entry point of update_state_after_spawn.py."""

    def _plan(self):
        return {
            "hostname": "pve02",
            "domain": "home.example.com",
            "lan_ip": "192.168.1.15",
            "vmid_block": [200, 201],
            "ip_block": ["192.168.1.50", "192.168.1.51"],
            "disposition": {
                "execution_mode": "autonomous",
                "services": ["k3s-worker"],
                "excluded": [],
            },
            "k3s_role": "worker",
            "package_id": "spawn-pkg-001",
            "vms": [{"vmid": 200, "name": "k3s-worker-01"}],
            "dns_entries": [{"hostname": "pve02.home.example.com", "ip": "192.168.1.15"}],
        }

    def test_cli_updates_state_file(self):
        import json
        import subprocess
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "bootstrap-state.json"
            plan_path  = Path(tmp) / "spawn-plan.json"
            state_path.write_text(json.dumps({"cell_id": "cell-alpha", "vms": []}))
            plan_path.write_text(json.dumps(self._plan()))

            result = subprocess.run(
                [sys.executable,
                 str(REPO_ROOT / "proxmox-bootstrap" / "update_state_after_spawn.py"),
                 "--state", str(state_path),
                 "--plan", str(plan_path),
                 "--spawned-at", "2026-06-01T12:00:00+00:00"],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            updated = json.loads(state_path.read_text())
            self.assertEqual(len(updated["vms"]), 1)
            self.assertIn("spawn_history", updated)

    def test_cli_missing_plan_exits_1(self):
        import subprocess
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "bootstrap-state.json"
            state_path.write_text('{"cell_id": "x"}')
            result = subprocess.run(
                [sys.executable,
                 str(REPO_ROOT / "proxmox-bootstrap" / "update_state_after_spawn.py"),
                 "--state", str(state_path),
                 "--plan", str(Path(tmp) / "nonexistent.json")],
                capture_output=True, text=True, timeout=10,
            )
            self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
