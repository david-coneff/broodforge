#!/usr/bin/env python3
"""
Tests for Phase 9.1-9.3, 9.8 — Phoenix Playbook Generator.

Covers:
  - PhoenixPlaybookGenerator.build(): playbook structure
  - Wave 0 (network), Wave 1 (storage), Wave 2 (host),
    Wave 3 (VMs), Wave 4 (k3s)
  - build_phoenix_playbook() factory
  - _zfs_topology_from_disk_count()
  - _score_phoenix_playbook_existence() readiness scorer
  - phoenix-playbook-schema.json validates generated output
"""

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "doc-gen"))
sys.path.insert(0, str(REPO_ROOT / "proxmox-bootstrap"))

from phoenix_playbook import (
    PhoenixPlaybookGenerator,
    build_phoenix_playbook,
    _zfs_topology_from_disk_count,
)
from readiness import _score_phoenix_playbook_existence


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MANIFEST_MINIMAL = {
    "cell_id": "proxmox-cell-a",
    "host_identity": {"hostname": "pve01", "fqdn": "pve01.internal", "proxmox_version": "8.1.3"},
    "vms": [],
    "dns_registry": [],
    "storage_config": {"vm_disks": "local-zfs", "snippets": "local:snippets"},
    "network_topology_declared": {
        "bridges": [{
            "name": "vmbr0", "ports": ["eno1"], "vlan_aware": True,
            "ip": "192.168.1.10/24", "gateway": "192.168.1.1",
            "management_bridge": True,
        }],
    },
}

MANIFEST_WITH_VMS = {
    "cell_id": "proxmox-cell-a",
    "host_identity": {"hostname": "pve01", "fqdn": "pve01.internal", "proxmox_version": "8.1.3"},
    "vms": [
        {"vmid": 101, "name": "forgejo", "role": "forgejo",
         "ssh_key_reference": "forgejo-deploy-key",
         "password_reference": "vm-forgejo-password"},
        {"vmid": 103, "name": "assessment-engine", "role": "assessment-engine"},
    ],
    "dns_registry": [
        {"hostname": "pve01.internal", "ip": "192.168.1.10", "vmid": None, "role": "proxmox-host"},
        {"hostname": "forgejo.internal", "ip": "192.168.1.21", "vmid": 101, "role": "forgejo"},
        {"hostname": "assessment.internal", "ip": "192.168.1.23", "vmid": 103, "role": "assessment-engine"},
    ],
    "storage_config": {"vm_disks": "local-zfs"},
    "network_topology_declared": {
        "bridges": [{
            "name": "vmbr0", "ports": ["eno1"], "vlan_aware": True,
            "ip": "192.168.1.10/24", "gateway": "192.168.1.1",
        }],
    },
    "provenance_registry": [
        {"vmid": 101, "name": "forgejo", "deployed_at": "2026-04-15T12:00:00Z",
         "template_name": "ubuntu-2204-base"},
    ],
}

HW_PROFILE_2_DISKS = {"disks": [{"name": "/dev/sda", "size_gb": 500}, {"name": "/dev/sdb", "size_gb": 500}]}
HW_PROFILE_3_DISKS = {"disks": [{"name": f"/dev/sd{c}", "size_gb": 500} for c in "abc"]}
HW_PROFILE_6_DISKS = {"disks": [{"name": f"/dev/sd{c}", "size_gb": 500} for c in "abcdef"]}


def _build(manifest=None, hw=None, scope="full"):
    return build_phoenix_playbook(manifest or MANIFEST_MINIMAL, hardware_profile=hw,
                                  restoration_scope=scope,
                                  now_fn=lambda: "2026-06-01T03:00:00+00:00")


# ---------------------------------------------------------------------------
# _zfs_topology_from_disk_count
# ---------------------------------------------------------------------------

class TestZfsTopology(unittest.TestCase):

    def test_one_disk_stripe(self):
        self.assertEqual(_zfs_topology_from_disk_count(1), "stripe")

    def test_two_disks_mirror(self):
        self.assertEqual(_zfs_topology_from_disk_count(2), "mirror")

    def test_three_disks_raidz1(self):
        self.assertEqual(_zfs_topology_from_disk_count(3), "raidz1")

    def test_four_disks_raidz2(self):
        self.assertEqual(_zfs_topology_from_disk_count(4), "raidz2")

    def test_six_disks_raidz2(self):
        self.assertEqual(_zfs_topology_from_disk_count(6), "raidz2")

    def test_seven_disks_raidz3(self):
        self.assertEqual(_zfs_topology_from_disk_count(7), "raidz3")


# ---------------------------------------------------------------------------
# PhoenixPlaybookGenerator — top-level structure
# ---------------------------------------------------------------------------

class TestPhoenixPlaybookStructure(unittest.TestCase):

    def setUp(self):
        self.playbook = _build()

    def test_schema_version(self):
        self.assertEqual(self.playbook["schema_version"], "1.0")

    def test_cell_id(self):
        self.assertEqual(self.playbook["cell_id"], "proxmox-cell-a")

    def test_generated_at_present(self):
        self.assertIn("generated_at", self.playbook)
        self.assertTrue(self.playbook["generated_at"])

    def test_target_node_hostname(self):
        self.assertEqual(self.playbook["target_node"]["hostname"], "pve01")

    def test_target_node_proxmox_version(self):
        self.assertEqual(self.playbook["target_node"]["proxmox_version"], "8.1.3")

    def test_identity_has_bridge_names(self):
        self.assertIn("vmbr0", self.playbook["identity"]["bridge_names"])

    def test_five_waves(self):
        self.assertEqual(len(self.playbook["waves"]), 5)

    def test_waves_ordered(self):
        wave_nums = [w["wave"] for w in self.playbook["waves"]]
        self.assertEqual(wave_nums, sorted(wave_nums))

    def test_validation_checklist_not_empty(self):
        self.assertGreater(len(self.playbook["validation_checklist"]), 0)

    def test_estimated_total_minutes_is_sum(self):
        expected = sum(w.get("estimated_minutes", 0) for w in self.playbook["waves"])
        self.assertEqual(self.playbook["estimated_total_minutes"], expected)

    def test_restoration_scope_full(self):
        self.assertEqual(self.playbook["restoration_scope"], "full")

    def test_deferred_services_empty_by_default(self):
        self.assertEqual(self.playbook["deferred_services"], [])


# ---------------------------------------------------------------------------
# Wave 0 — Network
# ---------------------------------------------------------------------------

class TestWave0Network(unittest.TestCase):

    def setUp(self):
        self.playbook  = _build()
        self.wave0     = next(w for w in self.playbook["waves"] if w["wave"] == 0)

    def test_wave0_name(self):
        self.assertIn("Network", self.wave0["name"])

    def test_wave0_has_steps(self):
        self.assertGreater(len(self.wave0["steps"]), 0)

    def test_wave0_bridge_vmbr0_mentioned(self):
        all_cmds = " ".join(
            cmd for step in self.wave0["steps"] for cmd in step["commands"]
        )
        self.assertIn("vmbr0", all_cmds)

    def test_wave0_ifreload_mentioned(self):
        all_cmds = " ".join(
            cmd for step in self.wave0["steps"] for cmd in step["commands"]
        )
        self.assertIn("ifreload", all_cmds)

    def test_wave0_ip_in_validation(self):
        all_val = " ".join(
            cmd for step in self.wave0["steps"] for cmd in step.get("validation", [])
        )
        self.assertIn("192.168.1.10", all_val)

    def test_wave0_no_declared_bridges_has_manual_step(self):
        manifest_no_bridges = dict(MANIFEST_MINIMAL)
        manifest_no_bridges["network_topology_declared"] = {"bridges": []}
        pb = _build(manifest=manifest_no_bridges)
        w0 = next(w for w in pb["waves"] if w["wave"] == 0)
        all_cmds = " ".join(cmd for s in w0["steps"] for cmd in s["commands"])
        self.assertIn("manual", all_cmds.lower())


# ---------------------------------------------------------------------------
# Wave 1 — Storage
# ---------------------------------------------------------------------------

class TestWave1Storage(unittest.TestCase):

    def setUp(self):
        self.wave1 = next(w for w in _build(hw=HW_PROFILE_2_DISKS)["waves"] if w["wave"] == 1)

    def test_wave1_name_contains_storage(self):
        self.assertIn("Storage", self.wave1["name"])

    def test_wave1_mirror_topology_for_2_disks(self):
        desc = self.wave1["description"]
        self.assertIn("mirror", desc)

    def test_wave1_raidz1_for_3_disks(self):
        pb = _build(hw=HW_PROFILE_3_DISKS)
        w1 = next(w for w in pb["waves"] if w["wave"] == 1)
        self.assertIn("raidz1", w1["description"])

    def test_wave1_has_zpool_commands(self):
        all_cmds = " ".join(cmd for s in self.wave1["steps"] for cmd in s["commands"])
        self.assertIn("zpool", all_cmds)

    def test_wave1_pvesm_registration(self):
        all_cmds = " ".join(cmd for s in self.wave1["steps"] for cmd in s["commands"])
        self.assertIn("pvesm add", all_cmds)

    def test_wave1_abort_on_failure(self):
        # Storage failure should abort the playbook
        for step in self.wave1["steps"]:
            if "Import or recreate" in step["action"]:
                self.assertEqual(step["on_failure"], "abort")


# ---------------------------------------------------------------------------
# Wave 2 — Host
# ---------------------------------------------------------------------------

class TestWave2Host(unittest.TestCase):

    def setUp(self):
        self.wave2 = next(w for w in _build()["waves"] if w["wave"] == 2)

    def test_wave2_name(self):
        self.assertIn("Host", self.wave2["name"])

    def test_wave2_hostname_in_commands(self):
        all_cmds = " ".join(cmd for s in self.wave2["steps"] for cmd in s["commands"])
        self.assertIn("pve01", all_cmds)

    def test_wave2_pveversion_in_validation(self):
        all_val = " ".join(cmd for s in self.wave2["steps"] for cmd in s.get("validation", []))
        self.assertIn("pveversion", all_val)


# ---------------------------------------------------------------------------
# Wave 3 — VMs
# ---------------------------------------------------------------------------

class TestWave3VMs(unittest.TestCase):

    def setUp(self):
        self.pb    = _build(manifest=MANIFEST_WITH_VMS)
        self.wave3 = next(w for w in self.pb["waves"] if w["wave"] == 3)

    def test_wave3_name(self):
        self.assertIn("VM", self.wave3["name"])

    def test_wave3_has_step_per_vm(self):
        vm_steps = [s for s in self.wave3["steps"] if s["method"] == "RESTORE"]
        self.assertEqual(len(vm_steps), 2)

    def test_wave3_vmid_in_commands(self):
        all_cmds = " ".join(cmd for s in self.wave3["steps"] for cmd in s["commands"])
        self.assertIn("101", all_cmds)
        self.assertIn("103", all_cmds)

    def test_wave3_vm_ip_in_validation(self):
        all_val = " ".join(cmd for s in self.wave3["steps"] for cmd in s.get("validation", []))
        self.assertIn("192.168.1.21", all_val)  # forgejo IP

    def test_wave3_qmrestore_in_commands(self):
        all_cmds = " ".join(cmd for s in self.wave3["steps"] for cmd in s["commands"])
        self.assertIn("qmrestore", all_cmds)

    def test_wave3_secret_refs_included(self):
        forgejo_step = next(s for s in self.wave3["steps"]
                           if "forgejo" in s.get("action", "").lower()
                           or "101" in s.get("action", ""))
        self.assertIn("forgejo-deploy-key", forgejo_step.get("secret_refs", []))

    def test_wave3_provenance_mentioned(self):
        all_cmds = " ".join(cmd for s in self.wave3["steps"] for cmd in s["commands"])
        self.assertIn("ubuntu-2204-base", all_cmds)

    def test_wave3_empty_vms_has_fallback_step(self):
        pb = _build(manifest=MANIFEST_MINIMAL)
        w3 = next(w for w in pb["waves"] if w["wave"] == 3)
        self.assertEqual(len(w3["steps"]), 1)


# ---------------------------------------------------------------------------
# Wave 4 — k3s
# ---------------------------------------------------------------------------

class TestWave4K3s(unittest.TestCase):

    def setUp(self):
        self.wave4 = next(w for w in _build()["waves"] if w["wave"] == 4)

    def test_wave4_name_contains_k3s(self):
        self.assertIn("k3s", self.wave4["name"])

    def test_wave4_kubectl_in_validation(self):
        all_val = " ".join(cmd for s in self.wave4["steps"] for cmd in s.get("validation", []))
        self.assertIn("kubectl", all_val)

    def test_wave4_flux_check_present(self):
        all_cmds = " ".join(cmd for s in self.wave4["steps"] for cmd in s["commands"])
        self.assertIn("flux", all_cmds)


# ---------------------------------------------------------------------------
# build_phoenix_playbook factory
# ---------------------------------------------------------------------------

class TestBuildPhoenixPlaybook(unittest.TestCase):

    def test_returns_dict(self):
        pb = build_phoenix_playbook(MANIFEST_MINIMAL)
        self.assertIsInstance(pb, dict)

    def test_partial_scope(self):
        pb = build_phoenix_playbook(MANIFEST_MINIMAL, restoration_scope="partial",
                                    deferred_services=["nextcloud"])
        self.assertEqual(pb["restoration_scope"], "partial")
        self.assertIn("nextcloud", pb["deferred_services"])

    def test_hardware_profile_stored(self):
        pb = build_phoenix_playbook(MANIFEST_MINIMAL, hardware_profile=HW_PROFILE_2_DISKS)
        self.assertIsNotNone(pb["hardware_profile"])

    def test_identity_vmids(self):
        pb = build_phoenix_playbook(MANIFEST_WITH_VMS)
        self.assertIn(101, pb["identity"]["vmids"])
        self.assertIn(103, pb["identity"]["vmids"])

    def test_generated_by_stored(self):
        pb = build_phoenix_playbook(MANIFEST_MINIMAL, generated_by="test-runner-v1")
        self.assertEqual(pb["generated_by"], "test-runner-v1")


# ---------------------------------------------------------------------------
# _score_phoenix_playbook_existence
# ---------------------------------------------------------------------------

class TestScorePhoenixPlaybookExistence(unittest.TestCase):

    def test_no_playbook_is_yellow(self):
        gaps = _score_phoenix_playbook_existence({})
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].severity, "YELLOW")
        self.assertIn("MISSING_PHOENIX_PLAYBOOK", gaps[0].gap_type)

    def test_phoenix_playbook_key_present_no_gap(self):
        gaps = _score_phoenix_playbook_existence({"phoenix_playbook": {"schema_version": "1.0"}})
        self.assertEqual(gaps, [])

    def test_timestamp_key_present_no_gap(self):
        gaps = _score_phoenix_playbook_existence({"phoenix_playbook_generated_at": "2026-06-01T00:00:00Z"})
        self.assertEqual(gaps, [])

    def test_gap_mentions_remediation_command(self):
        gaps = _score_phoenix_playbook_existence({})
        self.assertIn("phoenix_playbook.py", gaps[0].remediation)


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class TestPhoenixPlaybookSchema(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        try:
            import jsonschema
            cls.jsonschema = jsonschema
            cls.skip = False
        except ImportError:
            cls.skip = True
        schema_path = REPO_ROOT / "data-model" / "phoenix-playbook-schema.json"
        cls.schema = json.loads(schema_path.read_text(encoding="utf-8"))

    def _validate(self, instance):
        if self.skip:
            self.skipTest("jsonschema not installed")
        self.jsonschema.validate(instance, self.schema)

    def test_generated_playbook_validates(self):
        pb = build_phoenix_playbook(MANIFEST_WITH_VMS)
        self._validate(pb)

    def test_minimal_playbook_validates(self):
        pb = build_phoenix_playbook(MANIFEST_MINIMAL)
        self._validate(pb)

    def test_missing_cell_id_fails(self):
        if self.skip:
            self.skipTest("jsonschema not installed")
        pb = build_phoenix_playbook(MANIFEST_MINIMAL)
        del pb["cell_id"]
        with self.assertRaises(self.jsonschema.ValidationError):
            self._validate(pb)

    def test_invalid_restoration_scope_fails(self):
        if self.skip:
            self.skipTest("jsonschema not installed")
        pb = build_phoenix_playbook(MANIFEST_MINIMAL)
        pb["restoration_scope"] = "everything"
        with self.assertRaises(self.jsonschema.ValidationError):
            self._validate(pb)

    def test_invalid_k3s_role_fails(self):
        if self.skip:
            self.skipTest("jsonschema not installed")
        pb = build_phoenix_playbook(MANIFEST_MINIMAL)
        pb["target_node"]["k3s_role"] = "leader"
        with self.assertRaises(self.jsonschema.ValidationError):
            self._validate(pb)


if __name__ == "__main__":
    unittest.main()
