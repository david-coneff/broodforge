#!/usr/bin/env python3
"""
Tests for Phase 1.G.5-6 — Guided Setup Wiring.

1.G.5 (spawn):
  - SpawnPlannerSession has guided_session and setup_overrides fields
  - step_guided_setup(): autonomous no-op, ip-selective, group-manual, full-manual
  - setup_overrides embedded in spawn-plan.json via build_spawn_plan()

1.G.6 (phoenix):
  - PhoenixGuidedSetupSession construction and defaults
  - restoration_wave_options(): returns sorted wave list
  - step0_set_restoration_scope(): full/partial, partial requires waves, empty warns
  - step1_run_identity_overrides(): autonomous no-op, manual records overrides
  - apply_overrides_to_playbook(): scope filter, identity overrides, setup_overrides key
  - build_phoenix_guided_session(): convenience factory
"""

import unittest

from hatchery_state import read_hatchery_state

# ── Phoenix guided setup imports ────────────────────────────────────────────
from phoenix_guided_setup import (
    PHOENIX_IDENTITY_FIELDS,
    RESTORATION_SCOPE_FULL,
    RESTORATION_SCOPE_PARTIAL,
    PhoenixGuidedSetupSession,
    apply_overrides_to_playbook,
    build_phoenix_guided_session,
    restoration_wave_options,
    step0_set_restoration_scope,
    step1_run_identity_overrides,
)

# ── Spawn wiring imports ────────────────────────────────────────────────────
from spawn_planner import (
    EXEC_AUTONOMOUS,
    NET_LAN,
    ServiceCatalog,
    SpawnPlannerSession,
    build_spawn_plan,
    step_guided_setup,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BASE_STATE = {
    "cell_id": "pve01-cell",
    "host_identity": {
        "hostname": "pve01",
        "fqdn":     "pve01.home.example.com",
        "domain":   "home.example.com",
    },
    "memory": {"total_gb": 64},
    "cpu": {"total_threads": 16},
    "network": {"default_gateway": "192.168.1.1"},
    "network_topology": {
        "management_cidr": "192.168.1.0/24",
        "gateway":         "192.168.1.1",
    },
    "storage": {
        "zfs_pools": [{"name": "rpool", "state": "ONLINE", "topology": "mirror"}],
    },
    "vms": [{"vmid": 100, "name": "forgejo"}, {"vmid": 101, "name": "inventory"}],
    "dns_registry": [
        {"hostname": "forgejo", "ip": "192.168.1.50", "vmid": 100},
        {"hostname": "inventory", "ip": "192.168.1.51", "vmid": 101},
    ],
    "k3s": {
        "worker_join_token": "test-worker-token-abc123",
        "server_join_token": "test-server-token-def456",
    },
}

MINIMAL_CATALOG_SERVICES = [
    {"name": "k3s-worker",   "group": "Infrastructure", "ram_gb": 4,  "disk_gb": 20, "baseline": True},
    {"name": "forgejo",      "group": "Platform",        "ram_gb": 4,  "disk_gb": 50},
]

SAMPLE_PLAYBOOK = {
    "schema_version": "1.0",
    "cell_id":        "pve01-cell",
    "restoration_scope": "full",
    "target_node": {
        "hostname": "pve01",
        "fqdn":     "pve01.home.example.com",
        "role":     "hatchery",
    },
    "waves": [
        {
            "wave": 0,
            "name": "Network Reconstruction",
            "estimated_minutes": 10,
            "steps": [{"id": "0.1", "action": "Verify bridges"}],
        },
        {
            "wave": 1,
            "name": "Storage Pool Reconstruction",
            "estimated_minutes": 15,
            "steps": [{"id": "1.1", "action": "Scan disks"}, {"id": "1.2", "action": "Import pool"}],
        },
        {
            "wave": 2,
            "name": "Proxmox Host Configuration",
            "estimated_minutes": 10,
            "steps": [{"id": "2.1", "action": "Set hostname"}],
        },
        {
            "wave": 3,
            "name": "VM Restoration",
            "estimated_minutes": 30,
            "steps": [{"id": "3.1", "action": "Restore VMs"}],
        },
    ],
}


def _catalog() -> ServiceCatalog:
    return ServiceCatalog.from_list(MINIMAL_CATALOG_SERVICES)


def _manifest():
    return read_hatchery_state(BASE_STATE, {})


# ===========================================================================
# 1.G.5 — Spawn Guided Setup Wiring
# ===========================================================================

class TestSpawnSessionHasGuidedFields(unittest.TestCase):

    def test_guided_session_field_exists(self):
        s = SpawnPlannerSession()
        self.assertTrue(hasattr(s, "guided_session"))

    def test_guided_session_default_none(self):
        s = SpawnPlannerSession()
        self.assertIsNone(s.guided_session)

    def test_setup_overrides_field_exists(self):
        s = SpawnPlannerSession()
        self.assertTrue(hasattr(s, "setup_overrides"))

    def test_setup_overrides_default_empty(self):
        s = SpawnPlannerSession()
        self.assertEqual(s.setup_overrides, {})


class TestStepGuidedSetup(unittest.TestCase):

    def test_autonomous_mode_no_guided_session(self):
        s = SpawnPlannerSession()
        step_guided_setup(s, "autonomous", BASE_STATE)
        self.assertIsNone(s.guided_session)

    def test_autonomous_mode_overrides_empty(self):
        s = SpawnPlannerSession()
        step_guided_setup(s, "autonomous", BASE_STATE)
        self.assertEqual(s.setup_overrides, {})

    def test_ip_selective_creates_guided_session(self):
        s = SpawnPlannerSession()
        step_guided_setup(s, "ip-selective", BASE_STATE)
        self.assertIsNotNone(s.guided_session)

    def test_ip_selective_with_cidr_records_override(self):
        s = SpawnPlannerSession()
        step_guided_setup(s, "ip-selective", BASE_STATE,
                         ip_values={"network.management_cidr": "10.5.0.0/24"})
        self.assertIn("network.management_cidr", s.setup_overrides)

    def test_ip_selective_override_value_correct(self):
        s = SpawnPlannerSession()
        step_guided_setup(s, "ip-selective", BASE_STATE,
                         ip_values={"network.management_cidr": "10.5.0.0/24"})
        self.assertEqual(s.setup_overrides["network.management_cidr"]["value"], "10.5.0.0/24")

    def test_ip_selective_override_source_manual(self):
        s = SpawnPlannerSession()
        step_guided_setup(s, "ip-selective", BASE_STATE,
                         ip_values={"network.management_cidr": "10.5.0.0/24"})
        self.assertEqual(s.setup_overrides["network.management_cidr"]["source"], "manual")

    def test_group_manual_creates_guided_session(self):
        s = SpawnPlannerSession()
        step_guided_setup(s, "group-manual", BASE_STATE, selected_groups=["storage"])
        self.assertIsNotNone(s.guided_session)

    def test_group_manual_selected_groups_set(self):
        s = SpawnPlannerSession()
        step_guided_setup(s, "group-manual", BASE_STATE, selected_groups=["network", "storage"])
        self.assertIn("network", s.guided_session.selected_groups)
        self.assertIn("storage", s.guided_session.selected_groups)

    def test_group_manual_field_values_recorded(self):
        s = SpawnPlannerSession()
        step_guided_setup(s, "group-manual", BASE_STATE,
                         selected_groups=["storage"],
                         field_values={"storage.pool_name": "mypool"})
        self.assertIn("storage.pool_name", s.setup_overrides)

    def test_full_manual_creates_guided_session(self):
        s = SpawnPlannerSession()
        step_guided_setup(s, "full-manual", BASE_STATE)
        self.assertIsNotNone(s.guided_session)

    def test_full_manual_field_values_recorded(self):
        s = SpawnPlannerSession()
        step_guided_setup(s, "full-manual", BASE_STATE,
                         field_values={"storage.pool_name": "fullpool"})
        self.assertIn("storage.pool_name", s.setup_overrides)

    def test_returns_session(self):
        s = SpawnPlannerSession()
        result = step_guided_setup(s, "autonomous", BASE_STATE)
        self.assertIs(result, s)


class TestSpawnPlanEmbeddsOverrides(unittest.TestCase):
    """setup_overrides are embedded in spawn-plan.json when present."""

    def _make_plan(self, overrides_set=False):
        catalog = _catalog()
        state   = BASE_STATE
        m       = _manifest()
        s       = SpawnPlannerSession()
        s.network_mode    = NET_LAN
        s.execution_mode  = EXEC_AUTONOMOUS
        s.selected_services = ["k3s-worker"]
        s.allocated_vmids   = [200]
        s.allocated_ips     = ["192.168.1.100"]
        s.suggested_hostname = "pve02"
        if overrides_set:
            step_guided_setup(s, "ip-selective", state,
                             ip_values={"network.management_cidr": "10.5.0.0/24"})
        return build_spawn_plan(s, m, state, catalog)

    def test_no_overrides_key_absent_from_plan(self):
        plan = self._make_plan(overrides_set=False)
        self.assertNotIn("setup_overrides", plan)

    def test_overrides_present_key_in_plan(self):
        plan = self._make_plan(overrides_set=True)
        self.assertIn("setup_overrides", plan)

    def test_overrides_value_correct_in_plan(self):
        plan = self._make_plan(overrides_set=True)
        cidr_override = plan["setup_overrides"].get("network.management_cidr")
        self.assertIsNotNone(cidr_override)
        self.assertEqual(cidr_override["value"], "10.5.0.0/24")


# ===========================================================================
# 1.G.6 — Phoenix Guided Setup
# ===========================================================================

class TestPhoenixGuidedSetupSessionDefaults(unittest.TestCase):

    def test_default_scope_is_full(self):
        s = PhoenixGuidedSetupSession()
        self.assertEqual(s.restoration_scope, RESTORATION_SCOPE_FULL)

    def test_default_selected_waves_empty(self):
        s = PhoenixGuidedSetupSession()
        self.assertEqual(s.selected_waves, [])

    def test_default_identity_overrides_empty(self):
        s = PhoenixGuidedSetupSession()
        self.assertEqual(s.identity_overrides, {})

    def test_default_guided_session_none(self):
        s = PhoenixGuidedSetupSession()
        self.assertIsNone(s.guided_session)

    def test_default_warnings_empty(self):
        s = PhoenixGuidedSetupSession()
        self.assertEqual(s.warnings, [])


class TestRestorationWaveOptions(unittest.TestCase):

    def test_returns_all_waves(self):
        opts = restoration_wave_options(SAMPLE_PLAYBOOK)
        self.assertEqual(len(opts), 4)

    def test_sorted_by_wave_number(self):
        opts = restoration_wave_options(SAMPLE_PLAYBOOK)
        wave_nums = [o["wave"] for o in opts]
        self.assertEqual(wave_nums, sorted(wave_nums))

    def test_wave_has_name(self):
        opts = restoration_wave_options(SAMPLE_PLAYBOOK)
        self.assertEqual(opts[0]["name"], "Network Reconstruction")

    def test_wave_has_estimated_minutes(self):
        opts = restoration_wave_options(SAMPLE_PLAYBOOK)
        self.assertEqual(opts[0]["estimated_minutes"], 10)

    def test_wave_has_step_count(self):
        opts = restoration_wave_options(SAMPLE_PLAYBOOK)
        self.assertEqual(opts[1]["step_count"], 2)  # Wave 1 has 2 steps

    def test_empty_playbook_returns_empty(self):
        opts = restoration_wave_options({})
        self.assertEqual(opts, [])

    def test_wave_missing_number_skipped(self):
        pb = {"waves": [{"name": "Bad Wave"}, {"wave": 1, "name": "Good Wave"}]}
        opts = restoration_wave_options(pb)
        self.assertEqual(len(opts), 1)
        self.assertEqual(opts[0]["wave"], 1)


class TestStep0SetRestorationScope(unittest.TestCase):

    def test_set_full_scope(self):
        s = PhoenixGuidedSetupSession()
        step0_set_restoration_scope(s, RESTORATION_SCOPE_FULL)
        self.assertEqual(s.restoration_scope, RESTORATION_SCOPE_FULL)

    def test_set_partial_scope(self):
        s = PhoenixGuidedSetupSession()
        step0_set_restoration_scope(s, RESTORATION_SCOPE_PARTIAL, [0, 1])
        self.assertEqual(s.restoration_scope, RESTORATION_SCOPE_PARTIAL)

    def test_partial_scope_stores_wave_numbers(self):
        s = PhoenixGuidedSetupSession()
        step0_set_restoration_scope(s, RESTORATION_SCOPE_PARTIAL, [0, 1, 3])
        self.assertEqual(sorted(s.selected_waves), [0, 1, 3])

    def test_partial_scope_wave_numbers_are_ints(self):
        s = PhoenixGuidedSetupSession()
        step0_set_restoration_scope(s, RESTORATION_SCOPE_PARTIAL, ["0", "1"])
        self.assertIsInstance(s.selected_waves[0], int)

    def test_partial_scope_empty_waves_warns_and_defaults_full(self):
        s = PhoenixGuidedSetupSession()
        step0_set_restoration_scope(s, RESTORATION_SCOPE_PARTIAL, [])
        self.assertEqual(s.restoration_scope, RESTORATION_SCOPE_FULL)
        self.assertGreater(len(s.warnings), 0)

    def test_partial_scope_none_waves_warns_and_defaults_full(self):
        s = PhoenixGuidedSetupSession()
        step0_set_restoration_scope(s, RESTORATION_SCOPE_PARTIAL, None)
        self.assertEqual(s.restoration_scope, RESTORATION_SCOPE_FULL)
        self.assertGreater(len(s.warnings), 0)

    def test_invalid_scope_raises(self):
        s = PhoenixGuidedSetupSession()
        with self.assertRaises(ValueError):
            step0_set_restoration_scope(s, "semi-partial")

    def test_returns_session(self):
        s = PhoenixGuidedSetupSession()
        result = step0_set_restoration_scope(s, RESTORATION_SCOPE_FULL)
        self.assertIs(result, s)


class TestStep1RunIdentityOverrides(unittest.TestCase):

    def test_autonomous_no_guided_session(self):
        s = PhoenixGuidedSetupSession()
        step1_run_identity_overrides(s, {}, mode="autonomous")
        self.assertIsNone(s.guided_session)

    def test_autonomous_overrides_empty(self):
        s = PhoenixGuidedSetupSession()
        step1_run_identity_overrides(s, {}, mode="autonomous")
        self.assertEqual(s.identity_overrides, {})

    def test_manual_mode_records_hostname(self):
        s = PhoenixGuidedSetupSession()
        step1_run_identity_overrides(
            s, BASE_STATE, mode="full-manual",
            overrides={"host_identity.hostname": "pve02"}
        )
        self.assertEqual(s.identity_overrides["host_identity.hostname"], "pve02")

    def test_manual_mode_records_domain(self):
        s = PhoenixGuidedSetupSession()
        step1_run_identity_overrides(
            s, BASE_STATE, mode="full-manual",
            overrides={"host_identity.domain": "prod.example.com"}
        )
        self.assertEqual(s.identity_overrides["host_identity.domain"], "prod.example.com")

    def test_invalid_hostname_warns(self):
        s = PhoenixGuidedSetupSession()
        step1_run_identity_overrides(
            s, BASE_STATE, mode="full-manual",
            overrides={"host_identity.hostname": "UPPERCASE_BAD"}
        )
        self.assertGreater(len(s.warnings), 0)

    def test_creates_guided_session(self):
        s = PhoenixGuidedSetupSession()
        step1_run_identity_overrides(
            s, BASE_STATE, mode="full-manual",
            overrides={"host_identity.hostname": "pve02"}
        )
        self.assertIsNotNone(s.guided_session)

    def test_returns_session(self):
        s = PhoenixGuidedSetupSession()
        result = step1_run_identity_overrides(s, {}, mode="autonomous")
        self.assertIs(result, s)


class TestApplyOverridesToPlaybook(unittest.TestCase):

    def test_full_scope_includes_all_waves(self):
        s = PhoenixGuidedSetupSession()
        step0_set_restoration_scope(s, RESTORATION_SCOPE_FULL)
        updated = apply_overrides_to_playbook(s, SAMPLE_PLAYBOOK)
        self.assertEqual(len(updated["waves"]), 4)

    def test_partial_scope_filters_waves(self):
        s = PhoenixGuidedSetupSession()
        step0_set_restoration_scope(s, RESTORATION_SCOPE_PARTIAL, [0, 3])
        updated = apply_overrides_to_playbook(s, SAMPLE_PLAYBOOK)
        wave_nums = [w["wave"] for w in updated["waves"]]
        self.assertEqual(sorted(wave_nums), [0, 3])

    def test_partial_scope_sets_restoration_scope_field(self):
        s = PhoenixGuidedSetupSession()
        step0_set_restoration_scope(s, RESTORATION_SCOPE_PARTIAL, [1, 2])
        updated = apply_overrides_to_playbook(s, SAMPLE_PLAYBOOK)
        self.assertEqual(updated["restoration_scope"], RESTORATION_SCOPE_PARTIAL)

    def test_full_scope_sets_restoration_scope_field(self):
        s = PhoenixGuidedSetupSession()
        step0_set_restoration_scope(s, RESTORATION_SCOPE_FULL)
        updated = apply_overrides_to_playbook(s, SAMPLE_PLAYBOOK)
        self.assertEqual(updated["restoration_scope"], RESTORATION_SCOPE_FULL)

    def test_partial_scope_records_selected_waves(self):
        s = PhoenixGuidedSetupSession()
        step0_set_restoration_scope(s, RESTORATION_SCOPE_PARTIAL, [0, 1])
        updated = apply_overrides_to_playbook(s, SAMPLE_PLAYBOOK)
        self.assertIn("partial_waves_selected", updated)
        self.assertEqual(updated["partial_waves_selected"], [0, 1])

    def test_identity_override_updates_target_node(self):
        s = PhoenixGuidedSetupSession()
        step1_run_identity_overrides(
            s, BASE_STATE, mode="full-manual",
            overrides={"host_identity.hostname": "pve02"}
        )
        updated = apply_overrides_to_playbook(s, SAMPLE_PLAYBOOK)
        self.assertEqual(updated["target_node"]["hostname"], "pve02")

    def test_identity_override_domain_updates_target_node(self):
        s = PhoenixGuidedSetupSession()
        step1_run_identity_overrides(
            s, BASE_STATE, mode="full-manual",
            overrides={"host_identity.domain": "prod.example.com"}
        )
        updated = apply_overrides_to_playbook(s, SAMPLE_PLAYBOOK)
        self.assertEqual(updated["target_node"]["domain"], "prod.example.com")

    def test_setup_overrides_key_added_when_identity_changed(self):
        s = PhoenixGuidedSetupSession()
        step1_run_identity_overrides(
            s, BASE_STATE, mode="full-manual",
            overrides={"host_identity.hostname": "pve02"}
        )
        updated = apply_overrides_to_playbook(s, SAMPLE_PLAYBOOK)
        self.assertIn("setup_overrides", updated)

    def test_no_setup_overrides_key_when_no_changes(self):
        s = PhoenixGuidedSetupSession()
        step0_set_restoration_scope(s, RESTORATION_SCOPE_FULL)
        updated = apply_overrides_to_playbook(s, SAMPLE_PLAYBOOK)
        self.assertNotIn("setup_overrides", updated)

    def test_original_playbook_not_mutated(self):
        original_scope = SAMPLE_PLAYBOOK.get("restoration_scope")
        original_wave_count = len(SAMPLE_PLAYBOOK["waves"])
        s = PhoenixGuidedSetupSession()
        step0_set_restoration_scope(s, RESTORATION_SCOPE_PARTIAL, [0])
        apply_overrides_to_playbook(s, SAMPLE_PLAYBOOK)
        # Original unchanged
        self.assertEqual(SAMPLE_PLAYBOOK.get("restoration_scope"), original_scope)
        self.assertEqual(len(SAMPLE_PLAYBOOK["waves"]), original_wave_count)

    def test_warnings_embedded_when_present(self):
        s = PhoenixGuidedSetupSession()
        step1_run_identity_overrides(
            s, BASE_STATE, mode="full-manual",
            overrides={"host_identity.hostname": "INVALID_HOST"}
        )
        updated = apply_overrides_to_playbook(s, SAMPLE_PLAYBOOK)
        self.assertIn("setup_warnings", updated)

    def test_warnings_absent_when_none(self):
        s = PhoenixGuidedSetupSession()
        step0_set_restoration_scope(s, RESTORATION_SCOPE_FULL)
        updated = apply_overrides_to_playbook(s, SAMPLE_PLAYBOOK)
        self.assertNotIn("setup_warnings", updated)


class TestBuildPhoenixGuidedSession(unittest.TestCase):

    def test_full_scope_session(self):
        s = build_phoenix_guided_session(restoration_scope=RESTORATION_SCOPE_FULL)
        self.assertEqual(s.restoration_scope, RESTORATION_SCOPE_FULL)

    def test_partial_scope_session(self):
        s = build_phoenix_guided_session(
            restoration_scope=RESTORATION_SCOPE_PARTIAL,
            selected_waves=[0, 1],
        )
        self.assertEqual(s.restoration_scope, RESTORATION_SCOPE_PARTIAL)
        self.assertIn(0, s.selected_waves)

    def test_identity_overrides_recorded(self):
        s = build_phoenix_guided_session(
            restoration_scope=RESTORATION_SCOPE_FULL,
            identity_overrides={"host_identity.hostname": "pve02"},
            manifest=BASE_STATE,
        )
        self.assertIn("host_identity.hostname", s.identity_overrides)

    def test_default_is_full_scope(self):
        s = build_phoenix_guided_session()
        self.assertEqual(s.restoration_scope, RESTORATION_SCOPE_FULL)

    def test_phoenix_identity_fields_list(self):
        self.assertIn("host_identity.hostname", PHOENIX_IDENTITY_FIELDS)
        self.assertIn("host_identity.fqdn",     PHOENIX_IDENTITY_FIELDS)
        self.assertIn("host_identity.cell_id",  PHOENIX_IDENTITY_FIELDS)


if __name__ == "__main__":
    unittest.main()
