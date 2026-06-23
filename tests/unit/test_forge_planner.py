#!/usr/bin/env python3
"""
Tests for Phase 1.G.4 — Forge Planner.

Covers:
  - ForgePlannerSession construction and defaults
  - step0_set_setup_mode: all valid modes, invalid mode raises
  - step1_run_guided_setup: autonomous no-op, ip-selective pre-populates, group-manual, full-manual
  - step2_set_identity: direct values, guided session cascades, auto-suggest fallback
  - step3_set_network_profile: lan/wan, wan_config stored, headscale in guided session
  - record_manual_field: records in guided session, returns conflicts
  - build_forge_manifest: structure, overrides embedded, warnings embedded
  - auto_suggest_field: returns suggestions from manifest without session
"""

import unittest

from forge_planner import (
    FORGE_MODE_AUTONOMOUS,
    FORGE_MODE_FULL_MANUAL,
    FORGE_MODE_GROUP_MANUAL,
    FORGE_MODE_IP_SELECTIVE,
    FORGE_MODES,
    PROFILE_LAN,
    PROFILE_WAN,
    ForgePlannerSession,
    auto_suggest_field,
    build_forge_manifest,
    record_manual_field,
    step0_set_setup_mode,
    step1_run_guided_setup,
    step2_set_identity,
    step3_set_network_profile,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BASE_MANIFEST = {
    "cell_id": "pve01-cell",
    "host": {"hostname": "pve01"},
    "host_identity": {
        "hostname": "pve01",
        "fqdn":     "pve01.home.example.com",
        "domain":   "home.example.com",
        "cell_id":  "pve01-cell",
    },
    "memory": {"total_gb": 64, "available_gb": 48},
    "cpu": {"total_threads": 16},
    "network": {
        "default_gateway": "192.168.1.1",
        "dns_servers": ["192.168.1.1", "8.8.8.8"],
    },
    "network_topology": {
        "management_cidr": "192.168.1.0/24",
        "gateway":         "192.168.1.1",
        "search_domain":   "home.example.com",
    },
    "storage": {
        "zfs_pools": [{"name": "rpool", "state": "ONLINE", "topology": "mirror"}],
        "block_devices": [{"name": "sda"}, {"name": "sdb"}],
    },
    "vms": [{"vmid": 100, "name": "forgejo"}],
}


def _session(mode=FORGE_MODE_AUTONOMOUS, manifest=None) -> ForgePlannerSession:
    return ForgePlannerSession(
        setup_mode=mode,
        manifest=manifest or BASE_MANIFEST,
    )


# ---------------------------------------------------------------------------
# TestForgePlannerSessionDefaults
# ---------------------------------------------------------------------------

class TestForgePlannerSessionDefaults(unittest.TestCase):

    def test_default_mode_is_autonomous(self):
        s = ForgePlannerSession()
        self.assertEqual(s.setup_mode, FORGE_MODE_AUTONOMOUS)

    def test_default_network_profile_is_lan(self):
        s = ForgePlannerSession()
        self.assertEqual(s.network_profile, PROFILE_LAN)

    def test_default_guided_session_is_none(self):
        s = ForgePlannerSession()
        self.assertIsNone(s.guided_session)

    def test_default_setup_overrides_empty(self):
        s = ForgePlannerSession()
        self.assertEqual(s.setup_overrides, {})

    def test_default_warnings_empty(self):
        s = ForgePlannerSession()
        self.assertEqual(s.warnings, [])

    def test_four_forge_modes_defined(self):
        self.assertEqual(len(FORGE_MODES), 4)
        self.assertIn(FORGE_MODE_AUTONOMOUS, FORGE_MODES)
        self.assertIn(FORGE_MODE_FULL_MANUAL, FORGE_MODES)


# ---------------------------------------------------------------------------
# TestStep0SetMode
# ---------------------------------------------------------------------------

class TestStep0SetMode(unittest.TestCase):

    def test_set_autonomous(self):
        s = ForgePlannerSession()
        step0_set_setup_mode(s, FORGE_MODE_AUTONOMOUS)
        self.assertEqual(s.setup_mode, FORGE_MODE_AUTONOMOUS)

    def test_set_ip_selective(self):
        s = ForgePlannerSession()
        step0_set_setup_mode(s, FORGE_MODE_IP_SELECTIVE)
        self.assertEqual(s.setup_mode, FORGE_MODE_IP_SELECTIVE)

    def test_set_group_manual(self):
        s = ForgePlannerSession()
        step0_set_setup_mode(s, FORGE_MODE_GROUP_MANUAL)
        self.assertEqual(s.setup_mode, FORGE_MODE_GROUP_MANUAL)

    def test_set_full_manual(self):
        s = ForgePlannerSession()
        step0_set_setup_mode(s, FORGE_MODE_FULL_MANUAL)
        self.assertEqual(s.setup_mode, FORGE_MODE_FULL_MANUAL)

    def test_invalid_mode_raises(self):
        s = ForgePlannerSession()
        with self.assertRaises(ValueError):
            step0_set_setup_mode(s, "nonexistent-mode")

    def test_returns_session(self):
        s = ForgePlannerSession()
        result = step0_set_setup_mode(s, FORGE_MODE_FULL_MANUAL)
        self.assertIs(result, s)


# ---------------------------------------------------------------------------
# TestStep1RunGuidedSetup
# ---------------------------------------------------------------------------

class TestStep1RunGuidedSetup(unittest.TestCase):

    def test_autonomous_mode_no_guided_session(self):
        s = _session(FORGE_MODE_AUTONOMOUS)
        step1_run_guided_setup(s)
        self.assertIsNone(s.guided_session)

    def test_ip_selective_creates_guided_session(self):
        s = _session(FORGE_MODE_IP_SELECTIVE)
        step1_run_guided_setup(s)
        self.assertIsNotNone(s.guided_session)

    def test_ip_selective_guided_session_mode(self):
        s = _session(FORGE_MODE_IP_SELECTIVE)
        step1_run_guided_setup(s)
        self.assertEqual(s.guided_session.mode, FORGE_MODE_IP_SELECTIVE)

    def test_group_manual_creates_guided_session(self):
        s = _session(FORGE_MODE_GROUP_MANUAL)
        step1_run_guided_setup(s, selected_groups=["network"])
        self.assertIsNotNone(s.guided_session)

    def test_group_manual_selected_groups_set(self):
        s = _session(FORGE_MODE_GROUP_MANUAL)
        step1_run_guided_setup(s, selected_groups=["network", "storage"])
        self.assertIn("network", s.guided_session.selected_groups)
        self.assertIn("storage", s.guided_session.selected_groups)

    def test_full_manual_creates_guided_session(self):
        s = _session(FORGE_MODE_FULL_MANUAL)
        step1_run_guided_setup(s)
        self.assertIsNotNone(s.guided_session)

    def test_full_manual_guided_session_mode(self):
        s = _session(FORGE_MODE_FULL_MANUAL)
        step1_run_guided_setup(s)
        self.assertEqual(s.guided_session.mode, FORGE_MODE_FULL_MANUAL)

    def test_ip_selective_with_ip_values(self):
        s = _session(FORGE_MODE_IP_SELECTIVE)
        step1_run_guided_setup(s, ip_values={"network.management_cidr": "10.0.0.0/24"})
        self.assertIsNotNone(s.guided_session)
        val = s.guided_session.get_value("network.management_cidr")
        self.assertEqual(val, "10.0.0.0/24")

    def test_ip_selective_auto_populates_non_ip_fields(self):
        s = _session(FORGE_MODE_IP_SELECTIVE)
        step1_run_guided_setup(s)
        # Non-IP fields should be auto-populated
        gs = s.guided_session
        storage_topo = gs.get_value("storage.topology")
        self.assertIsNotNone(storage_topo)

    def test_ip_selective_ip_conflict_adds_to_warnings(self):
        s = _session(FORGE_MODE_IP_SELECTIVE)
        # Invalid CIDR should produce a warning
        step1_run_guided_setup(s, ip_values={"network.management_cidr": "not-a-cidr"})
        self.assertGreater(len(s.warnings), 0)

    def test_returns_session(self):
        s = _session(FORGE_MODE_IP_SELECTIVE)
        result = step1_run_guided_setup(s)
        self.assertIs(result, s)


# ---------------------------------------------------------------------------
# TestStep2SetIdentity
# ---------------------------------------------------------------------------

class TestStep2SetIdentity(unittest.TestCase):

    def test_sets_hostname(self):
        s = _session()
        step2_set_identity(s, hostname="hatchery")
        self.assertEqual(s.hostname, "hatchery")

    def test_sets_domain(self):
        s = _session()
        step2_set_identity(s, domain="infra.local")
        self.assertEqual(s.domain, "infra.local")

    def test_sets_cell_id(self):
        s = _session()
        step2_set_identity(s, cell_id="my-cell")
        self.assertEqual(s.cell_id, "my-cell")

    def test_autonomous_auto_fills_hostname_from_manifest(self):
        s = _session()
        step2_set_identity(s)
        self.assertEqual(s.hostname, "pve01")

    def test_autonomous_auto_fills_domain_from_manifest(self):
        s = _session()
        step2_set_identity(s)
        self.assertEqual(s.domain, "home.example.com")

    def test_autonomous_derives_cell_id(self):
        s = _session()
        step2_set_identity(s)
        self.assertIsNotNone(s.cell_id)

    def test_guided_session_records_hostname(self):
        s = _session(FORGE_MODE_FULL_MANUAL)
        step1_run_guided_setup(s)
        step2_set_identity(s, hostname="hatchery")
        gs = s.guided_session
        self.assertEqual(gs.get_value("host_identity.hostname"), "hatchery")

    def test_guided_session_records_domain(self):
        s = _session(FORGE_MODE_FULL_MANUAL)
        step1_run_guided_setup(s)
        step2_set_identity(s, domain="prod.example.com")
        gs = s.guided_session
        self.assertEqual(gs.get_value("host_identity.domain"), "prod.example.com")

    def test_guided_session_updates_overrides(self):
        s = _session(FORGE_MODE_FULL_MANUAL)
        step1_run_guided_setup(s)
        step2_set_identity(s, hostname="hatchery", domain="test.local")
        self.assertIn("host_identity.hostname", s.setup_overrides)

    def test_invalid_hostname_produces_warning(self):
        s = _session(FORGE_MODE_FULL_MANUAL)
        step1_run_guided_setup(s)
        step2_set_identity(s, hostname="UPPERCASE-BAD")
        # check_conflicts warns about format
        self.assertGreater(len(s.warnings), 0)

    def test_returns_session(self):
        s = _session()
        result = step2_set_identity(s, hostname="pve01")
        self.assertIs(result, s)


# ---------------------------------------------------------------------------
# TestStep3SetNetworkProfile
# ---------------------------------------------------------------------------

class TestStep3SetNetworkProfile(unittest.TestCase):

    def test_set_lan_profile(self):
        s = _session()
        step3_set_network_profile(s, PROFILE_LAN)
        self.assertEqual(s.network_profile, PROFILE_LAN)

    def test_set_wan_profile(self):
        s = _session()
        step3_set_network_profile(s, PROFILE_WAN)
        self.assertEqual(s.network_profile, PROFILE_WAN)

    def test_wan_config_stored(self):
        s = _session()
        wan = {"headscale_url": "https://hatchery.example.com:8080", "dns_provider": "cloudflare"}
        step3_set_network_profile(s, PROFILE_WAN, wan_config=wan)
        self.assertEqual(s.wan_config["headscale_url"], "https://hatchery.example.com:8080")

    def test_invalid_profile_raises(self):
        s = _session()
        with self.assertRaises(ValueError):
            step3_set_network_profile(s, "satellite")

    def test_wan_headscale_recorded_in_guided_session(self):
        s = _session(FORGE_MODE_FULL_MANUAL)
        step1_run_guided_setup(s)
        wan = {"headscale_url": "https://hatchery.example.com:8080"}
        step3_set_network_profile(s, PROFILE_WAN, wan_config=wan)
        gs = s.guided_session
        val = gs.get_value("network.headscale_url")
        self.assertEqual(val, "https://hatchery.example.com:8080")

    def test_lan_profile_wan_config_empty(self):
        s = _session()
        step3_set_network_profile(s, PROFILE_LAN)
        self.assertEqual(s.wan_config, {})

    def test_returns_session(self):
        s = _session()
        result = step3_set_network_profile(s, PROFILE_LAN)
        self.assertIs(result, s)


# ---------------------------------------------------------------------------
# TestRecordManualField
# ---------------------------------------------------------------------------

class TestRecordManualField(unittest.TestCase):

    def test_no_guided_session_returns_empty(self):
        s = _session()  # autonomous
        result = record_manual_field(s, "network.management_cidr", "10.0.0.0/24")
        self.assertEqual(result, [])

    def test_records_value_in_guided_session(self):
        s = _session(FORGE_MODE_FULL_MANUAL)
        step1_run_guided_setup(s)
        record_manual_field(s, "network.management_cidr", "10.0.0.0/24")
        self.assertEqual(
            s.guided_session.get_value("network.management_cidr"), "10.0.0.0/24"
        )

    def test_marked_as_manual_source(self):
        s = _session(FORGE_MODE_FULL_MANUAL)
        step1_run_guided_setup(s)
        record_manual_field(s, "storage.pool_name", "mypool")
        self.assertTrue(s.guided_session.is_manually_set("storage.pool_name"))

    def test_updates_setup_overrides(self):
        s = _session(FORGE_MODE_FULL_MANUAL)
        step1_run_guided_setup(s)
        record_manual_field(s, "storage.pool_name", "mypool")
        self.assertIn("storage.pool_name", s.setup_overrides)

    def test_conflict_returned(self):
        s = _session(FORGE_MODE_FULL_MANUAL)
        step1_run_guided_setup(s)
        conflicts = record_manual_field(s, "network.management_cidr", "bad-cidr")
        self.assertGreater(len(conflicts), 0)

    def test_conflict_added_to_session_warnings(self):
        s = _session(FORGE_MODE_FULL_MANUAL)
        step1_run_guided_setup(s)
        record_manual_field(s, "network.management_cidr", "bad-cidr")
        self.assertGreater(len(s.warnings), 0)


# ---------------------------------------------------------------------------
# TestBuildForgeManifest
# ---------------------------------------------------------------------------

class TestBuildForgeManifest(unittest.TestCase):

    def _fixed_now(self):
        return "2026-06-01T12:00:00+00:00"

    def test_contains_schema_version(self):
        s = _session()
        step2_set_identity(s, hostname="pve01", domain="home.example.com")
        m = build_forge_manifest(s, now_fn=self._fixed_now)
        self.assertIn("schema_version", m)

    def test_contains_cell_id(self):
        s = _session()
        step2_set_identity(s, hostname="pve01", domain="home.example.com", cell_id="pve01-cell")
        m = build_forge_manifest(s, now_fn=self._fixed_now)
        self.assertEqual(m["cell_id"], "pve01-cell")

    def test_contains_generated_at(self):
        s = _session()
        step2_set_identity(s)
        m = build_forge_manifest(s, now_fn=self._fixed_now)
        self.assertEqual(m["generated_at"], "2026-06-01T12:00:00+00:00")

    def test_contains_setup_mode(self):
        s = _session(FORGE_MODE_IP_SELECTIVE)
        step2_set_identity(s)
        m = build_forge_manifest(s, now_fn=self._fixed_now)
        self.assertEqual(m["setup_mode"], FORGE_MODE_IP_SELECTIVE)

    def test_host_identity_fields(self):
        s = _session()
        step2_set_identity(s, hostname="hatchery", domain="prod.example.com")
        m = build_forge_manifest(s, now_fn=self._fixed_now)
        hi = m["host_identity"]
        self.assertEqual(hi["hostname"], "hatchery")
        self.assertEqual(hi["domain"],   "prod.example.com")
        self.assertEqual(hi["fqdn"],     "hatchery.prod.example.com")

    def test_network_topology_lan(self):
        s = _session()
        step2_set_identity(s)
        step3_set_network_profile(s, PROFILE_LAN)
        m = build_forge_manifest(s, now_fn=self._fixed_now)
        self.assertEqual(m["network_topology"]["profile"], "lan")

    def test_network_topology_wan_includes_wan_config(self):
        s = _session()
        step2_set_identity(s)
        step3_set_network_profile(s, PROFILE_WAN, wan_config={"headscale_url": "https://h.ex:8080"})
        m = build_forge_manifest(s, now_fn=self._fixed_now)
        self.assertEqual(m["network_topology"]["profile"], "wan")
        self.assertIn("wan_config", m["network_topology"])

    def test_setup_overrides_embedded_when_present(self):
        s = _session(FORGE_MODE_IP_SELECTIVE)
        step1_run_guided_setup(s, ip_values={"network.management_cidr": "10.1.0.0/24"})
        step2_set_identity(s)
        m = build_forge_manifest(s, now_fn=self._fixed_now)
        self.assertIn("setup_overrides", m)

    def test_setup_overrides_absent_for_autonomous(self):
        s = _session(FORGE_MODE_AUTONOMOUS)
        step2_set_identity(s)
        m = build_forge_manifest(s, now_fn=self._fixed_now)
        # No overrides in autonomous mode
        self.assertNotIn("setup_overrides", m)

    def test_warnings_embedded_when_present(self):
        s = _session(FORGE_MODE_FULL_MANUAL)
        step1_run_guided_setup(s)
        record_manual_field(s, "network.management_cidr", "bad-cidr")
        step2_set_identity(s)
        m = build_forge_manifest(s, now_fn=self._fixed_now)
        self.assertIn("setup_warnings", m)

    def test_warnings_absent_when_none(self):
        s = _session(FORGE_MODE_AUTONOMOUS)
        step2_set_identity(s)
        m = build_forge_manifest(s, now_fn=self._fixed_now)
        self.assertNotIn("setup_warnings", m)

    def test_guided_ip_choice_propagates_to_manifest(self):
        s = _session(FORGE_MODE_IP_SELECTIVE)
        step1_run_guided_setup(s, ip_values={"network.management_cidr": "10.1.0.0/24"})
        step2_set_identity(s)
        m = build_forge_manifest(s, now_fn=self._fixed_now)
        self.assertEqual(m["network_topology"]["management_cidr"], "10.1.0.0/24")

    def test_management_cidr_from_base_manifest_when_autonomous(self):
        s = _session(FORGE_MODE_AUTONOMOUS)
        step2_set_identity(s)
        m = build_forge_manifest(s, now_fn=self._fixed_now)
        self.assertEqual(m["network_topology"]["management_cidr"], "192.168.1.0/24")


# ---------------------------------------------------------------------------
# TestAutoSuggestField
# ---------------------------------------------------------------------------

class TestAutoSuggestField(unittest.TestCase):

    def test_hostname_suggestion(self):
        val = auto_suggest_field("host_identity.hostname", BASE_MANIFEST)
        self.assertEqual(val, "pve01")

    def test_management_cidr_suggestion(self):
        val = auto_suggest_field("network.management_cidr", BASE_MANIFEST)
        self.assertEqual(val, "192.168.1.0/24")

    def test_storage_topology_suggestion(self):
        val = auto_suggest_field("storage.topology", BASE_MANIFEST)
        # 2 block devices → mirror
        self.assertEqual(val, "mirror")

    def test_unknown_field_returns_none(self):
        val = auto_suggest_field("nonexistent.field.path", BASE_MANIFEST)
        self.assertIsNone(val)


class TestStep4SetTimezone(unittest.TestCase):
    """Tests for step4_set_timezone (Phase 1.F.9)."""

    def setUp(self):
        from forge_planner import step4_set_timezone
        self.step4 = step4_set_timezone

    def test_timezone_stored_in_session(self):
        sess = ForgePlannerSession()
        self.step4(sess, "America/Denver")
        self.assertEqual(sess.timezone, "America/Denver")

    def test_no_timezone_leaves_none(self):
        sess = ForgePlannerSession()
        self.step4(sess, None)
        self.assertIsNone(sess.timezone)

    def test_utc_timezone_accepted(self):
        sess = ForgePlannerSession()
        self.step4(sess, "UTC")
        self.assertEqual(sess.timezone, "UTC")

    def test_invalid_format_adds_warning(self):
        sess = ForgePlannerSession()
        self.step4(sess, "Mountain")  # not IANA format
        self.assertEqual(sess.timezone, "Mountain")
        self.assertTrue(len(sess.warnings) > 0)

    def test_valid_format_no_warning(self):
        sess = ForgePlannerSession()
        self.step4(sess, "Europe/London")
        self.assertFalse(any("Timezone" in w for w in sess.warnings))

    def test_timezone_in_manifest(self):
        sess = ForgePlannerSession()
        step2_set_identity(sess, hostname="pve01", domain="home.example.com", cell_id="c")
        self.step4(sess, "America/Denver")
        m = build_forge_manifest(sess)
        self.assertEqual(m["host_identity"]["timezone"], "America/Denver")

    def test_no_timezone_not_in_manifest(self):
        sess = ForgePlannerSession()
        step2_set_identity(sess, hostname="pve01", domain="home.example.com", cell_id="c")
        m = build_forge_manifest(sess)
        self.assertNotIn("timezone", m["host_identity"])


class TestStep5SetBackupConfig(unittest.TestCase):
    """Tests for step5_set_backup_config (Phase 1.F.10)."""

    def setUp(self):
        from forge_planner import step5_set_backup_config
        self.step5 = step5_set_backup_config

    def test_destinations_stored(self):
        sess = ForgePlannerSession()
        dests = [{"type": "b2", "rclone_remote": "b2:bucket"}]
        self.step5(sess, destinations=dests)
        self.assertEqual(sess.backup_destinations, dests)

    def test_no_destinations_leaves_empty(self):
        sess = ForgePlannerSession()
        self.step5(sess)
        self.assertEqual(sess.backup_destinations, [])

    def test_embed_in_packages_false_default(self):
        sess = ForgePlannerSession()
        self.step5(sess)
        self.assertFalse(sess.keepass_embed_in_packages)

    def test_embed_in_packages_true(self):
        sess = ForgePlannerSession()
        self.step5(sess, keepass_embed_in_packages=True)
        self.assertTrue(sess.keepass_embed_in_packages)

    def test_destinations_in_manifest(self):
        sess = ForgePlannerSession()
        step2_set_identity(sess, hostname="pve01", domain="home.example.com", cell_id="c")
        dests = [{"type": "local", "local_path": "/mnt/backup"}]
        self.step5(sess, destinations=dests)
        m = build_forge_manifest(sess)
        self.assertIn("backup_config_ref", m)
        self.assertEqual(m["backup_config_ref"]["destinations"], dests)

    def test_no_destinations_no_backup_config_ref(self):
        sess = ForgePlannerSession()
        step2_set_identity(sess, hostname="pve01", domain="home.example.com", cell_id="c")
        self.step5(sess, destinations=[])
        m = build_forge_manifest(sess)
        self.assertNotIn("backup_config_ref", m)

    def test_keepass_config_in_manifest(self):
        sess = ForgePlannerSession()
        step2_set_identity(sess, hostname="pve01", domain="home.example.com", cell_id="c")
        self.step5(sess, keepass_embed_in_packages=True)
        m = build_forge_manifest(sess)
        self.assertIn("keepass_config", m)
        self.assertTrue(m["keepass_config"]["embed_in_packages"])

    def test_keepass_config_always_present(self):
        sess = ForgePlannerSession()
        step2_set_identity(sess, hostname="pve01", domain="home.example.com", cell_id="c")
        m = build_forge_manifest(sess)
        self.assertIn("keepass_config", m)

    def test_mfa_method_defaults_to_totp(self):
        sess = ForgePlannerSession()
        step2_set_identity(sess, hostname="pve01", domain="home.example.com", cell_id="c")
        m = build_forge_manifest(sess)
        self.assertEqual(m["keepass_config"]["mfa_method"], "totp")

    def test_mfa_method_from_guided_session(self):
        sess = ForgePlannerSession(setup_mode=FORGE_MODE_FULL_MANUAL)
        step1_run_guided_setup(sess)
        record_manual_field(sess, "security.mfa_method", "yubikey")
        step2_set_identity(sess, hostname="pve01", domain="home.example.com", cell_id="c")
        m = build_forge_manifest(sess)
        self.assertEqual(m["keepass_config"]["mfa_method"], "yubikey")


if __name__ == "__main__":
    unittest.main()
