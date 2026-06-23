#!/usr/bin/env python3
"""
test_hatchery_receiver_wiring.py — I1 audit: verify update_state_after_spawn
is wired into the hatchery receiver's spawn-complete handler.

Covers:
  - update_state_after_spawn + build_spawn_result round-trip (the logic called
    by hatchery_receiver._handle_spawn_complete)
  - _ReceiverHandler routes /api/spawn-complete to _handle_spawn_complete
  - phase-06-verify.sh contains the /api/spawn-complete POST call
"""

import unittest

import hatchery_receiver as _hr
import spawn_scripts as _ss
from update_state_after_spawn import (
    build_spawn_result,
    update_state_after_spawn,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SPAWN_PLAN = {
    "hostname": "pve03",
    "domain": "brood.local",
    "lan_ip": "192.168.1.30",
    "tailnet_ip": "100.64.0.30",
    "k3s_role": "worker",
    "vmid_block": [210, 211],
    "ip_block": ["192.168.1.30", "192.168.1.31"],
    "package_id": "spawn-pve03-20260601",
    "disposition": {
        "services": ["prometheus", "grafana"],
        "excluded": [],
        "execution_mode": "autonomous",
    },
    "vms": [
        {"vmid": 210, "name": "pve03-k3s", "tofu_workspace": "opentofu"},
    ],
    "dns_entries": [
        {"hostname": "pve03", "ip": "192.168.1.30"},
    ],
}

_BASE_STATE = {
    "cell_id": "proxmox-cell-a",
    "schema_version": "1.0",
    "vms": [],
    "dns_registry": [],
    "provenance_records": [],
    "spawn_history": [],
}


# ---------------------------------------------------------------------------
# Tests: update_state_after_spawn + build_spawn_result round-trip
# ---------------------------------------------------------------------------

class TestSpawnCompleteLogic(unittest.TestCase):
    def setUp(self):
        import copy
        self.state = copy.deepcopy(_BASE_STATE)
        self.result = build_spawn_result(_SPAWN_PLAN)

    def test_spawn_result_hostname(self):
        self.assertEqual(self.result.broodling_hostname, "pve03")

    def test_spawn_result_fqdn(self):
        self.assertEqual(self.result.broodling_fqdn, "pve03.brood.local")

    def test_spawn_result_k3s_role(self):
        self.assertEqual(self.result.k3s_role, "worker")

    def test_spawn_result_vmids(self):
        self.assertEqual(self.result.allocated_vmids, [210, 211])

    def test_update_adds_vms(self):
        updated = update_state_after_spawn(self.state, self.result)
        self.assertEqual(len(updated["vms"]), 1)
        self.assertEqual(updated["vms"][0]["vmid"], 210)

    def test_update_adds_dns_entry(self):
        updated = update_state_after_spawn(self.state, self.result)
        ips = [e["ip"] for e in updated["dns_registry"]]
        self.assertIn("192.168.1.30", ips)

    def test_update_adds_spawn_history(self):
        updated = update_state_after_spawn(self.state, self.result)
        self.assertEqual(len(updated["spawn_history"]), 1)
        self.assertEqual(updated["spawn_history"][0]["broodling_hostname"], "pve03")

    def test_update_adds_provenance_record(self):
        updated = update_state_after_spawn(self.state, self.result)
        self.assertEqual(len(updated["provenance_records"]), 1)
        self.assertEqual(updated["provenance_records"][0]["vmid"], 210)

    def test_idempotent_vm_add(self):
        updated = update_state_after_spawn(self.state, self.result)
        updated2 = update_state_after_spawn(updated, self.result)
        self.assertEqual(len(updated2["vms"]), 1)

    def test_build_with_hardware_profile(self):
        hp = {"cpu_cores": 16, "ram_gb": 64}
        updated = update_state_after_spawn(self.state, self.result, hardware_profile=hp)
        self.assertEqual(updated["spawn_history"][0]["hardware_profile"], hp)


# ---------------------------------------------------------------------------
# Tests: receiver routing (route table coverage)
# ---------------------------------------------------------------------------

class TestReceiverRouting(unittest.TestCase):
    def test_spawn_complete_route_exists(self):
        """_ReceiverHandler.do_POST must branch on /api/spawn-complete."""
        import inspect
        src = inspect.getsource(_hr._ReceiverHandler.do_POST)
        self.assertIn("/api/spawn-complete", src)

    def test_spawn_complete_calls_handle_method(self):
        """do_POST must delegate to _handle_spawn_complete for that path."""
        import inspect
        src = inspect.getsource(_hr._ReceiverHandler.do_POST)
        self.assertIn("_handle_spawn_complete", src)


# ---------------------------------------------------------------------------
# Tests: generated phase-06-verify.sh wiring
# ---------------------------------------------------------------------------

_PLAN = {
    "hostname": "pve02",
    "network": {"gateway": "192.168.1.1"},
    "vms": [{"vmid": 200, "name": "pve02-k3s"}],
    "k3s_role": "worker",
}


class TestPhase06SpawnCompleteWiring(unittest.TestCase):
    def setUp(self):
        self.script = _ss.generate_phase_06_verify(_PLAN)

    def test_posts_to_spawn_complete_endpoint(self):
        self.assertIn("api/spawn-complete", self.script)

    def test_reads_hatchery_url_from_manifest(self):
        self.assertIn("HATCHERY_URL", self.script)

    def test_includes_spawn_plan_in_payload(self):
        self.assertIn("spawn-plan.json", self.script)

    def test_fallback_mentions_manual_update(self):
        self.assertIn("update_state_after_spawn", self.script)


if __name__ == "__main__":
    unittest.main(verbosity=2)
