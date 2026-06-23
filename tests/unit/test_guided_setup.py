#!/usr/bin/env python3
"""
Tests for Phase 1.G — Guided Setup Framework.

Covers:
  - SETTING_GROUPS structure and field paths
  - GuidedSetupSession: mode, is_manual_field, get_value, is_manually_set
  - suggest(): auto-suggestions for all major field paths
  - suggest() revision: subnet change cascades to gateway/k3s/headscale suggestions
  - set_value(): records choice, returns conflict warnings, updates session
  - check_conflicts(): all conflict rules (CIDR overlap, gateway not in subnet,
      VMID collision, hostname format, RAM exceeding host)
  - run_ip_selective_suggestions(): populates non-IP fields automatically
  - group_selector_rows(): builds display rows for all groups
  - session_to_overrides(): serializes only manual choices
"""

import unittest

from guided_setup import (
    IP_SELECTIVE_FIELDS,
    SETTING_GROUPS,
    GuidedSetupSession,
    check_conflicts,
    group_selector_rows,
    run_ip_selective_suggestions,
    session_to_overrides,
    set_value,
    suggest,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BASE_MANIFEST = {
    "cell_id": "proxmox-cell-a",
    "host": {"hostname": "pve01"},
    "host_identity": {"hostname": "pve01", "fqdn": "pve01.internal", "domain": "home.example.com"},
    "memory": {"total_gb": 32, "available_gb": 16},
    "cpu": {"total_threads": 8},
    "network": {"default_gateway": "192.168.1.1", "dns_servers": ["192.168.1.1", "8.8.8.8"]},
    "network_topology": {"management_cidr": "192.168.1.0/24", "gateway": "192.168.1.1",
                         "search_domain": "internal"},
    "storage": {
        "zfs_pools": [{"name": "rpool", "state": "ONLINE", "topology": "mirror"}],
        "block_devices": [{"name": "sda"}, {"name": "sdb"}],
    },
    "vms": [{"vmid": 100, "name": "forgejo"}, {"vmid": 101, "name": "inventory"}],
}


def _session(mode="autonomous", manifest=None, groups=None) -> GuidedSetupSession:
    s = GuidedSetupSession(
        mode=mode,
        manifest=manifest or BASE_MANIFEST,
        selected_groups=set(groups or []),
    )
    return s


# ---------------------------------------------------------------------------
# SETTING_GROUPS structure
# ---------------------------------------------------------------------------

class TestSettingGroups(unittest.TestCase):

    def test_all_seven_groups_defined(self):
        self.assertEqual(set(SETTING_GROUPS.keys()),
                         {"network", "storage", "vm_sizing", "identity",
                          "security", "k3s", "backup"})

    def test_each_group_has_required_keys(self):
        for gid, gdef in SETTING_GROUPS.items():
            for key in ("label", "description", "fields", "representative_field"):
                self.assertIn(key, gdef, f"Group '{gid}' missing key '{key}'")

    def test_representative_field_in_fields(self):
        for gid, gdef in SETTING_GROUPS.items():
            self.assertIn(gdef["representative_field"], gdef["fields"],
                          f"Group '{gid}' representative_field not in fields")

    def test_ip_selective_fields_are_in_network_group(self):
        network_fields = set(SETTING_GROUPS["network"]["fields"])
        for f in IP_SELECTIVE_FIELDS:
            self.assertIn(f, network_fields)


# ---------------------------------------------------------------------------
# GuidedSetupSession
# ---------------------------------------------------------------------------

class TestGuidedSetupSession(unittest.TestCase):

    def test_autonomous_mode_no_manual_fields(self):
        s = _session(mode="autonomous")
        for group_fields in (g["fields"] for g in SETTING_GROUPS.values()):
            for fp in group_fields:
                self.assertFalse(s.is_manual_field(fp))

    def test_ip_selective_mode_only_ip_fields_manual(self):
        s = _session(mode="ip-selective")
        self.assertTrue(s.is_manual_field("network.management_cidr"))
        self.assertTrue(s.is_manual_field("network.gateway"))
        self.assertFalse(s.is_manual_field("storage.pool_name"))
        self.assertFalse(s.is_manual_field("identity.hostname"))

    def test_group_manual_mode_only_selected_groups_manual(self):
        s = _session(mode="group-manual", groups=["storage"])
        self.assertTrue(s.is_manual_field("storage.pool_name"))
        self.assertFalse(s.is_manual_field("network.management_cidr"))

    def test_full_manual_all_fields_are_manual(self):
        s = _session(mode="full-manual")
        for group_fields in (g["fields"] for g in SETTING_GROUPS.values()):
            for fp in group_fields:
                self.assertTrue(s.is_manual_field(fp))

    def test_get_value_returns_none_before_set(self):
        s = _session()
        self.assertIsNone(s.get_value("network.management_cidr"))

    def test_is_manually_set_false_for_auto_choice(self):
        s = _session()
        set_value("network.management_cidr", "192.168.1.0/24", s, source="auto")
        self.assertFalse(s.is_manually_set("network.management_cidr"))

    def test_is_manually_set_true_for_manual_choice(self):
        s = _session()
        set_value("network.management_cidr", "10.0.0.0/24", s, source="manual")
        self.assertTrue(s.is_manually_set("network.management_cidr"))


# ---------------------------------------------------------------------------
# suggest() — base suggestions
# ---------------------------------------------------------------------------

class TestSuggestBase(unittest.TestCase):

    def setUp(self):
        self.s = _session()

    def test_suggest_cidr_from_manifest(self):
        val = suggest("network.management_cidr", self.s)
        self.assertEqual(val, "192.168.1.0/24")

    def test_suggest_gateway_from_manifest(self):
        val = suggest("network.gateway", self.s)
        self.assertEqual(val, "192.168.1.1")

    def test_suggest_pool_name_from_manifest(self):
        val = suggest("storage.pool_name", self.s)
        self.assertEqual(val, "rpool")

    def test_suggest_hostname_from_manifest(self):
        val = suggest("host_identity.hostname", self.s)
        self.assertEqual(val, "pve01")

    def test_suggest_fqdn_from_hostname_and_domain(self):
        val = suggest("host_identity.fqdn", self.s)
        self.assertIn("pve01", val)
        self.assertIn("home.example.com", val)

    def test_suggest_vmid_start_above_existing(self):
        val = suggest("vms.vmid_start", self.s)
        existing = max(100, 101)
        self.assertGreater(int(val), existing)

    def test_suggest_k3s_pod_cidr(self):
        val = suggest("k3s.pod_cidr", self.s)
        self.assertIn("/", val)   # is CIDR notation

    def test_suggest_k3s_service_cidr_not_overlap_pod(self):
        import ipaddress
        pod = suggest("k3s.pod_cidr", self.s)
        svc = suggest("k3s.service_cidr", self.s)
        pod_net = ipaddress.ip_network(pod, strict=False)
        svc_net = ipaddress.ip_network(svc, strict=False)
        self.assertFalse(pod_net.overlaps(svc_net))

    def test_suggest_headscale_url_contains_fqdn(self):
        val = suggest("network.headscale_url", self.s)
        self.assertIn("pve01", val)
        self.assertIn("8080", val)

    def test_suggest_password_format_is_passphrase(self):
        val = suggest("security.password_format", self.s)
        self.assertEqual(val, "passphrase")

    def test_suggest_mfa_method_is_totp(self):
        # AD-058: second-factor auth defaults ON; "totp" is the suggested baseline
        val = suggest("security.mfa_method", self.s)
        self.assertEqual(val, "totp")


# ---------------------------------------------------------------------------
# suggest() — revision from prior choices
# ---------------------------------------------------------------------------

class TestSuggestRevision(unittest.TestCase):

    def test_gateway_revised_when_cidr_changed(self):
        s = _session()
        set_value("network.management_cidr", "10.50.0.0/24", s, source="manual")
        gw = suggest("network.gateway", s)
        # Gateway should come from the new subnet
        self.assertTrue(gw.startswith("10.50.0."), f"Expected 10.50.0.x, got {gw}")

    def test_fqdn_revised_when_hostname_changed(self):
        s = _session()
        set_value("host_identity.hostname", "broodling-01", s, source="manual")
        fqdn = suggest("host_identity.fqdn", s)
        self.assertIn("broodling-01", fqdn)

    def test_fqdn_revised_when_domain_changed(self):
        s = _session()
        set_value("host_identity.domain", "my.custom.lab", s, source="manual")
        fqdn = suggest("host_identity.fqdn", s)
        self.assertIn("my.custom.lab", fqdn)

    def test_datastore_name_revised_when_pool_changed(self):
        s = _session()
        set_value("storage.pool_name", "tank", s, source="manual")
        ds = suggest("storage.datastore_name", s)
        self.assertIn("tank", ds)

    def test_headscale_revised_when_fqdn_changed(self):
        s = _session()
        set_value("host_identity.hostname", "myhatch", s, source="manual")
        set_value("host_identity.domain", "corp.net", s, source="manual")
        url = suggest("network.headscale_url", s)
        self.assertIn("myhatch", url)
        self.assertIn("corp.net", url)

    def test_k3s_pod_cidr_avoids_overlap_with_management(self):
        # If management is 10.42.0.0/16, pod CIDR should shift
        s = _session()
        set_value("network.management_cidr", "10.42.0.0/16", s, source="manual")
        pod = suggest("k3s.pod_cidr", s)
        import ipaddress
        pod_net = ipaddress.ip_network(pod, strict=False)
        mgmt    = ipaddress.ip_network("10.42.0.0/16", strict=False)
        self.assertFalse(pod_net.overlaps(mgmt))

    def test_suggest_returns_existing_choice_if_already_set(self):
        s = _session()
        set_value("storage.pool_name", "mypool", s, source="manual")
        self.assertEqual(suggest("storage.pool_name", s), "mypool")

    def test_cell_id_revised_from_hostname(self):
        s = _session(manifest={**BASE_MANIFEST, "cell_id": None})
        set_value("host_identity.hostname", "node42", s, source="manual")
        cell_id = suggest("host_identity.cell_id", s)
        self.assertIn("node42", cell_id)


# ---------------------------------------------------------------------------
# check_conflicts
# ---------------------------------------------------------------------------

class TestCheckConflicts(unittest.TestCase):

    def test_valid_cidr_no_conflict(self):
        s = _session()
        warnings = check_conflicts("network.management_cidr", "192.168.2.0/24", s)
        self.assertEqual(warnings, [])

    def test_invalid_cidr_format_is_warning(self):
        s = _session()
        warnings = check_conflicts("network.management_cidr", "not-a-cidr", s)
        self.assertTrue(len(warnings) > 0)

    def test_cidr_overlap_with_k3s_pod_is_warning(self):
        s = _session()
        set_value("k3s.pod_cidr", "10.42.0.0/16", s, source="auto")
        warnings = check_conflicts("network.management_cidr", "10.42.0.0/24", s)
        self.assertTrue(any("overlap" in w.lower() for w in warnings))

    def test_gateway_outside_cidr_is_warning(self):
        s = _session()
        set_value("network.management_cidr", "192.168.1.0/24", s, source="auto")
        warnings = check_conflicts("network.gateway", "10.0.0.1", s)
        self.assertTrue(any("not within" in w.lower() for w in warnings))

    def test_gateway_inside_cidr_no_conflict(self):
        s = _session()
        set_value("network.management_cidr", "192.168.1.0/24", s, source="auto")
        warnings = check_conflicts("network.gateway", "192.168.1.1", s)
        self.assertEqual(warnings, [])

    def test_vmid_collision_with_existing(self):
        s = _session()
        warnings = check_conflicts("vms.vmid_start", 100, s)  # 100 is taken
        self.assertTrue(any("100" in w for w in warnings))

    def test_vmid_below_100_is_warning(self):
        s = _session()
        warnings = check_conflicts("vms.vmid_start", 50, s)
        self.assertTrue(any("100" in w for w in warnings))

    def test_vmid_9000_plus_is_warning(self):
        s = _session()
        warnings = check_conflicts("vms.vmid_start", 9001, s)
        self.assertTrue(any("9000" in w for w in warnings))

    def test_valid_vmid_no_conflict(self):
        s = _session()
        warnings = check_conflicts("vms.vmid_start", 200, s)
        self.assertEqual(warnings, [])

    def test_invalid_hostname_format_warning(self):
        s = _session()
        warnings = check_conflicts("host_identity.hostname", "My Hostname!", s)
        self.assertTrue(len(warnings) > 0)

    def test_valid_hostname_no_warning(self):
        s = _session()
        warnings = check_conflicts("host_identity.hostname", "pve-node-01", s)
        self.assertEqual(warnings, [])

    def test_excessive_ram_per_vm_warning(self):
        s = _session()
        # 30 GB per VM on a 32 GB host is > 90%
        warnings = check_conflicts("vms.default_ram_gb", 30, s)
        self.assertTrue(any("exhaust" in w.lower() for w in warnings))

    def test_reasonable_ram_no_warning(self):
        s = _session()
        warnings = check_conflicts("vms.default_ram_gb", 4, s)
        self.assertEqual(warnings, [])

    def test_k3s_pod_cidr_overlap_with_management(self):
        s = _session()
        set_value("network.management_cidr", "192.168.1.0/24", s, source="auto")
        warnings = check_conflicts("k3s.pod_cidr", "192.168.1.0/16", s)
        self.assertTrue(any("overlap" in w.lower() for w in warnings))

    def test_mfa_method_totp_no_conflict(self):
        s = _session()
        warnings = check_conflicts("security.mfa_method", "totp", s)
        self.assertEqual(warnings, [])

    def test_mfa_method_yubikey_no_conflict(self):
        s = _session()
        warnings = check_conflicts("security.mfa_method", "yubikey", s)
        self.assertEqual(warnings, [])

    def test_mfa_method_none_is_warning(self):
        # AD-058: opting out of the default second-factor protection is
        # allowed but flagged — an explicit, deliberate choice.
        s = _session()
        warnings = check_conflicts("security.mfa_method", "none", s)
        self.assertTrue(any("second-factor" in w.lower() for w in warnings))

    def test_mfa_method_sms_rejected(self):
        # SMS/email OTP are never offered as choices (AD-058).
        s = _session()
        warnings = check_conflicts("security.mfa_method", "sms", s)
        self.assertTrue(any("not a supported mfa method" in w.lower() for w in warnings))


# ---------------------------------------------------------------------------
# set_value
# ---------------------------------------------------------------------------

class TestSetValue(unittest.TestCase):

    def test_set_value_records_choice(self):
        s = _session()
        set_value("storage.pool_name", "mypool", s)
        self.assertEqual(s.get_value("storage.pool_name"), "mypool")

    def test_set_value_appends_warnings_to_session(self):
        s = _session()
        set_value("network.management_cidr", "not-a-cidr", s)
        self.assertGreater(len(s.warnings), 0)

    def test_set_value_returns_conflict_list(self):
        s = _session()
        result = set_value("network.management_cidr", "invalid", s)
        self.assertIsInstance(result, list)

    def test_set_value_clean_input_empty_conflicts(self):
        s = _session()
        result = set_value("storage.pool_name", "tank", s)
        self.assertEqual(result, [])

    def test_set_value_source_preserved(self):
        s = _session()
        set_value("storage.pool_name", "auto-pool", s, source="auto")
        self.assertFalse(s.is_manually_set("storage.pool_name"))


# ---------------------------------------------------------------------------
# run_ip_selective_suggestions
# ---------------------------------------------------------------------------

class TestRunIpSelectiveSuggestions(unittest.TestCase):

    def test_returns_ip_fields_only(self):
        s = _session(mode="ip-selective")
        ip_fields = run_ip_selective_suggestions(s)
        self.assertEqual(set(ip_fields.keys()), IP_SELECTIVE_FIELDS)

    def test_non_ip_fields_auto_populated_in_session(self):
        s = _session(mode="ip-selective")
        run_ip_selective_suggestions(s)
        # Non-IP fields should now be auto-set
        self.assertIsNotNone(s.get_value("storage.pool_name"))
        self.assertIsNotNone(s.get_value("host_identity.hostname"))

    def test_non_ip_fields_marked_as_auto(self):
        s = _session(mode="ip-selective")
        run_ip_selective_suggestions(s)
        self.assertFalse(s.is_manually_set("storage.pool_name"))


# ---------------------------------------------------------------------------
# group_selector_rows
# ---------------------------------------------------------------------------

class TestGroupSelectorRows(unittest.TestCase):

    def test_returns_seven_rows(self):
        s = _session()
        rows = group_selector_rows(s)
        self.assertEqual(len(rows), 7)

    def test_rows_have_required_keys(self):
        s = _session()
        for row in group_selector_rows(s):
            for key in ("group_id", "label", "description",
                        "representative_field", "auto_suggestion", "selected"):
                self.assertIn(key, row)

    def test_unselected_by_default(self):
        s = _session(mode="group-manual")
        rows = group_selector_rows(s)
        self.assertTrue(all(not r["selected"] for r in rows))

    def test_selected_groups_reflected(self):
        s = _session(mode="group-manual", groups=["storage", "k3s"])
        rows = group_selector_rows(s)
        selected = {r["group_id"] for r in rows if r["selected"]}
        self.assertEqual(selected, {"storage", "k3s"})

    def test_auto_suggestion_present_for_all_rows(self):
        s = _session()
        for row in group_selector_rows(s):
            # Auto suggestion may be None for backup destinations (not yet configured)
            # but label and group_id must be non-empty
            self.assertTrue(row["label"])
            self.assertTrue(row["group_id"])


# ---------------------------------------------------------------------------
# session_to_overrides
# ---------------------------------------------------------------------------

class TestSessionToOverrides(unittest.TestCase):

    def test_empty_session_empty_overrides(self):
        s = _session()
        self.assertEqual(session_to_overrides(s), {})

    def test_auto_choices_not_in_overrides(self):
        s = _session()
        set_value("storage.pool_name", "rpool", s, source="auto")
        self.assertNotIn("storage.pool_name", session_to_overrides(s))

    def test_manual_choices_in_overrides(self):
        s = _session()
        set_value("storage.pool_name", "tank", s, source="manual")
        overrides = session_to_overrides(s)
        self.assertIn("storage.pool_name", overrides)
        self.assertEqual(overrides["storage.pool_name"]["value"], "tank")
        self.assertEqual(overrides["storage.pool_name"]["source"], "manual")

    def test_mixed_choices_only_manual_exported(self):
        s = _session()
        set_value("storage.pool_name", "auto-pool", s, source="auto")
        set_value("host_identity.hostname", "myhost", s, source="manual")
        overrides = session_to_overrides(s)
        self.assertIn("host_identity.hostname", overrides)
        self.assertNotIn("storage.pool_name", overrides)


if __name__ == "__main__":
    unittest.main()
