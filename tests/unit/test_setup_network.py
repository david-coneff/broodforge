#!/usr/bin/env python3
"""
Tests for network profile setup and migration (Phase 1.G / Phase 1.F).

Covers:
  - LanNetworkConfig / WanNetworkConfig dataclass construction
  - suggest_lan() / suggest_wan(): auto-suggestions from manifest, including revision
  - validate_lan_config() / validate_wan_config(): error and warning conditions
  - plan_migration_to_wan(): step list, warnings when domain missing
  - plan_migration_to_lan(): steps with/without preserving Headscale
  - lan_config_to_state() / wan_config_to_state(): correct field mapping
  - apply_network_config_to_state(): merges into bootstrap-state dict
  - generate_dnsmasq_config(): LAN and WAN profile output
  - bootstrap-state-schema.json accepts network profile fields
"""

import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent

from setup_network import (
    PROFILE_LAN,
    PROFILE_WAN,
    LanNetworkConfig,
    WanNetworkConfig,
    apply_network_config_to_state,
    generate_dnsmasq_config,
    lan_config_to_state,
    plan_migration_to_lan,
    plan_migration_to_wan,
    suggest_lan,
    suggest_wan,
    validate_lan_config,
    validate_wan_config,
    wan_config_to_state,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BASE_MANIFEST = {
    "host": {"hostname": "pve01"},
    "host_identity": {"hostname": "pve01", "domain": "home.example.com"},
    "network": {"default_gateway": "192.168.1.1", "dns_servers": ["192.168.1.1"]},
    "network_topology": {
        "management_cidr": "192.168.1.0/24",
        "gateway": "192.168.1.1",
        "search_domain": "internal",
    },
}

DNS_REGISTRY = [
    {"hostname": "pve01.internal", "ip": "192.168.1.10", "role": "proxmox-host", "vmid": None},
    {"hostname": "forgejo.internal", "ip": "192.168.1.21", "role": "forgejo", "vmid": 101},
]

def _lan(**kwargs) -> LanNetworkConfig:
    defaults = dict(management_cidr="192.168.1.0/24", gateway="192.168.1.1")
    defaults.update(kwargs)
    return LanNetworkConfig(**defaults)

def _wan(**kwargs) -> WanNetworkConfig:
    defaults = dict(management_cidr="192.168.1.0/24", gateway="192.168.1.1",
                    domain="home.example.com", fqdn="hatchery.home.example.com",
                    dns_provider="cloudflare",
                    dns_provider_credential_reference="Infrastructure/cloudflare/api-token")
    defaults.update(kwargs)
    return WanNetworkConfig(**defaults)


# ---------------------------------------------------------------------------
# LanNetworkConfig
# ---------------------------------------------------------------------------

class TestLanNetworkConfig(unittest.TestCase):

    def test_profile_is_lan(self):
        self.assertEqual(_lan().profile, PROFILE_LAN)

    def test_default_values_reasonable(self):
        c = _lan()
        self.assertIn("/", c.management_cidr)   # is CIDR
        self.assertTrue(c.dnsmasq_enabled)

    def test_custom_values_stored(self):
        c = _lan(management_cidr="10.0.0.0/24", gateway="10.0.0.1")
        self.assertEqual(c.management_cidr, "10.0.0.0/24")
        self.assertEqual(c.gateway, "10.0.0.1")


# ---------------------------------------------------------------------------
# WanNetworkConfig
# ---------------------------------------------------------------------------

class TestWanNetworkConfig(unittest.TestCase):

    def test_profile_is_wan(self):
        self.assertEqual(_wan().profile, PROFILE_WAN)

    def test_headscale_enabled_by_default(self):
        self.assertTrue(_wan().headscale_enabled)

    def test_ddns_enabled_by_default(self):
        self.assertTrue(_wan().ddns_enabled)

    def test_dnsmasq_enabled_for_split_horizon(self):
        self.assertTrue(_wan().dnsmasq_enabled)


# ---------------------------------------------------------------------------
# suggest_lan
# ---------------------------------------------------------------------------

class TestSuggestLan(unittest.TestCase):

    def _suggest(self, field, manifest=None, partial=None):
        return suggest_lan(field, manifest or BASE_MANIFEST, partial or _lan())

    def test_cidr_from_manifest(self):
        self.assertEqual(self._suggest("management_cidr"), "192.168.1.0/24")

    def test_gateway_from_manifest(self):
        self.assertEqual(self._suggest("gateway"), "192.168.1.1")

    def test_nameservers_from_manifest(self):
        ns = self._suggest("nameservers")
        self.assertIn("192.168.1.1", ns)

    def test_search_domain_from_manifest(self):
        self.assertEqual(self._suggest("search_domain"), "internal")

    def test_tls_mode_default_self_signed(self):
        self.assertEqual(self._suggest("tls_mode"), "self-signed")

    def test_gateway_revised_from_partial_cidr(self):
        # If partial has a different CIDR, gateway suggestion should reflect it
        partial = _lan(management_cidr="10.50.0.0/24")
        gw = suggest_lan("gateway", {}, partial)
        self.assertTrue(gw.startswith("10.50.0."), f"Expected 10.50.0.x, got {gw}")

    def test_nameservers_fallback_uses_gateway(self):
        # No discovered DNS servers → fallback to gateway + 8.8.8.8
        partial = _lan(gateway="192.168.5.1")
        ns = suggest_lan("nameservers", {}, partial)
        self.assertIn("192.168.5.1", ns)


# ---------------------------------------------------------------------------
# suggest_wan
# ---------------------------------------------------------------------------

class TestSuggestWan(unittest.TestCase):

    def _suggest(self, field, manifest=None, partial=None):
        return suggest_wan(field, manifest or BASE_MANIFEST, partial or _wan())

    def test_domain_from_manifest(self):
        self.assertEqual(self._suggest("domain"), "home.example.com")

    def test_fqdn_built_from_hostname_and_domain(self):
        fqdn = self._suggest("fqdn")
        self.assertIn("pve01", fqdn)
        self.assertIn("home.example.com", fqdn)

    def test_headscale_url_built_from_fqdn(self):
        url = self._suggest("headscale_url")
        self.assertIn("hatchery.home.example.com", url)
        self.assertIn("8080", url)

    def test_tls_provider_cloudflare_for_cloudflare_dns(self):
        partial = _wan(dns_provider="cloudflare")
        self.assertEqual(suggest_wan("tls_provider", {}, partial), "certbot-cloudflare")

    def test_tls_provider_acme_for_duckdns(self):
        partial = _wan(dns_provider="duckdns")
        self.assertEqual(suggest_wan("tls_provider", {}, partial), "acme.sh-duckdns")

    def test_fqdn_revised_when_domain_changes(self):
        partial = _wan(domain="corp.net")
        partial.fqdn = ""  # reset to trigger suggestion
        fqdn = suggest_wan("fqdn", BASE_MANIFEST, partial)
        self.assertIn("corp.net", fqdn)

    def test_headscale_url_revised_when_fqdn_changes(self):
        partial = _wan(fqdn="myhost.mylab.io")
        url = suggest_wan("headscale_url", {}, partial)
        self.assertIn("myhost.mylab.io", url)


# ---------------------------------------------------------------------------
# validate_lan_config
# ---------------------------------------------------------------------------

class TestValidateLanConfig(unittest.TestCase):

    def test_valid_config_passes(self):
        result = validate_lan_config(_lan())
        self.assertTrue(result.valid)
        self.assertEqual(result.errors, [])

    def test_invalid_cidr_is_error(self):
        result = validate_lan_config(_lan(management_cidr="not-a-cidr"))
        self.assertFalse(result.valid)
        self.assertTrue(any("CIDR" in e for e in result.errors))

    def test_gateway_outside_cidr_is_warning(self):
        result = validate_lan_config(
            _lan(management_cidr="192.168.1.0/24", gateway="10.0.0.1")
        )
        # Should warn but may not error
        self.assertTrue(any("not within" in w.lower() for w in result.warnings))

    def test_invalid_tls_mode_is_error(self):
        result = validate_lan_config(_lan(tls_mode="certbot"))
        self.assertFalse(result.valid)


# ---------------------------------------------------------------------------
# validate_wan_config
# ---------------------------------------------------------------------------

class TestValidateWanConfig(unittest.TestCase):

    def test_valid_config_passes(self):
        result = validate_wan_config(_wan())
        self.assertTrue(result.valid)

    def test_missing_domain_is_error(self):
        result = validate_wan_config(_wan(domain=""))
        self.assertFalse(result.valid)
        self.assertTrue(any("domain" in e.lower() for e in result.errors))

    def test_bad_domain_format_is_warning(self):
        result = validate_wan_config(_wan(domain="notadomain"))
        warnings_lower = " ".join(result.warnings).lower()
        self.assertIn("domain", warnings_lower)

    def test_missing_credential_reference_is_warning(self):
        c = _wan(dns_provider="cloudflare", dns_provider_credential_reference=None)
        result = validate_wan_config(c)
        self.assertTrue(any("credential" in w.lower() for w in result.warnings))

    def test_invalid_tls_provider_is_error(self):
        result = validate_wan_config(_wan(tls_provider="invalid"))
        self.assertFalse(result.valid)


# ---------------------------------------------------------------------------
# plan_migration_to_wan
# ---------------------------------------------------------------------------

class TestPlanMigrationToWan(unittest.TestCase):

    def setUp(self):
        current = _lan()
        target  = _wan()
        self.plan = plan_migration_to_wan(current, target)

    def test_from_to_profiles_correct(self):
        self.assertEqual(self.plan.from_profile, PROFILE_LAN)
        self.assertEqual(self.plan.to_profile, PROFILE_WAN)

    def test_has_multiple_steps(self):
        self.assertGreater(len(self.plan.steps), 3)

    def test_steps_have_required_keys(self):
        for step in self.plan.steps:
            for key in ("id", "description", "action", "autonomous_possible"):
                self.assertIn(key, step)

    def test_router_step_not_autonomous(self):
        router_steps = [s for s in self.plan.steps if "router" in s["id"].lower()]
        self.assertTrue(len(router_steps) >= 1)
        self.assertFalse(router_steps[0]["autonomous_possible"])

    def test_no_domain_produces_warning(self):
        plan = plan_migration_to_wan(_lan(), _wan(domain=""))
        self.assertTrue(len(plan.warnings) > 0)

    def test_step_ids_are_unique(self):
        ids = [s["id"] for s in self.plan.steps]
        self.assertEqual(len(ids), len(set(ids)))


# ---------------------------------------------------------------------------
# plan_migration_to_lan
# ---------------------------------------------------------------------------

class TestPlanMigrationToLan(unittest.TestCase):

    def test_from_to_profiles_correct(self):
        plan = plan_migration_to_lan(_wan())
        self.assertEqual(plan.from_profile, PROFILE_WAN)
        self.assertEqual(plan.to_profile, PROFILE_LAN)

    def test_ddns_disable_step_present(self):
        plan = plan_migration_to_lan(_wan())
        self.assertTrue(any("ddns" in s["id"].lower() for s in plan.steps))

    def test_headscale_stop_when_not_preserving(self):
        plan = plan_migration_to_lan(_wan(), preserve_headscale=False)
        headscale_steps = [s for s in plan.steps if "headscale" in s["id"].lower()]
        self.assertTrue(any("Stop" in s["description"] for s in headscale_steps))

    def test_headscale_retained_when_preserving(self):
        plan = plan_migration_to_lan(_wan(), preserve_headscale=True)
        headscale_steps = [s for s in plan.steps if "headscale" in s["id"].lower()]
        self.assertTrue(any("Keep" in s["description"] or "retain" in s["description"].lower()
                            for s in headscale_steps))

    def test_commit_step_is_autonomous(self):
        plan = plan_migration_to_lan(_wan())
        commit_steps = [s for s in plan.steps if "commit" in s["id"].lower()]
        self.assertTrue(commit_steps[0]["autonomous_possible"])


# ---------------------------------------------------------------------------
# lan_config_to_state
# ---------------------------------------------------------------------------

class TestLanConfigToState(unittest.TestCase):

    def setUp(self):
        self.state = lan_config_to_state(_lan())

    def test_profile_is_lan(self):
        self.assertEqual(self.state["profile"], PROFILE_LAN)

    def test_wan_config_is_none(self):
        self.assertIsNone(self.state["wan_config"])

    def test_lan_config_present(self):
        self.assertIsNotNone(self.state["lan_config"])

    def test_headscale_url_is_none(self):
        self.assertIsNone(self.state["headscale_url"])

    def test_management_cidr_present(self):
        self.assertIn("management_cidr", self.state)


# ---------------------------------------------------------------------------
# wan_config_to_state
# ---------------------------------------------------------------------------

class TestWanConfigToState(unittest.TestCase):

    def setUp(self):
        self.state = wan_config_to_state(_wan())

    def test_profile_is_wan(self):
        self.assertEqual(self.state["profile"], PROFILE_WAN)

    def test_lan_config_is_none(self):
        self.assertIsNone(self.state["lan_config"])

    def test_wan_config_present(self):
        self.assertIsNotNone(self.state["wan_config"])
        self.assertIn("domain", self.state["wan_config"])

    def test_headscale_url_present(self):
        self.assertIsNotNone(self.state["headscale_url"])

    def test_ssl_cert_path_set_for_certbot(self):
        c = _wan(tls_provider="certbot-cloudflare")
        s = wan_config_to_state(c)
        self.assertIsNotNone(s["ssl_cert_path"])
        self.assertIn("letsencrypt", s["ssl_cert_path"])

    def test_ssl_cert_path_set_for_acme_sh(self):
        c = _wan(tls_provider="acme.sh-duckdns")
        s = wan_config_to_state(c)
        self.assertIsNotNone(s["ssl_cert_path"])
        self.assertIn("broodforge", s["ssl_cert_path"])

    def test_ddns_zone_is_domain(self):
        s = wan_config_to_state(_wan(domain="mylab.io"))
        self.assertEqual(s["ddns_zone"], "mylab.io")


# ---------------------------------------------------------------------------
# apply_network_config_to_state
# ---------------------------------------------------------------------------

class TestApplyNetworkConfigToState(unittest.TestCase):

    def test_writes_network_topology(self):
        state = {}
        nt = lan_config_to_state(_lan())
        apply_network_config_to_state(state, nt)
        self.assertIn("network_topology", state)

    def test_merges_with_existing_fields(self):
        state = {"network_topology": {"interface_name": "ens18", "extra_field": "keep_me"}}
        nt = lan_config_to_state(_lan())
        apply_network_config_to_state(state, nt)
        # existing extra_field should survive
        self.assertEqual(state["network_topology"].get("extra_field"), "keep_me")

    def test_profile_updated(self):
        state = {"network_topology": {"profile": PROFILE_LAN}}
        nt = wan_config_to_state(_wan())
        apply_network_config_to_state(state, nt)
        self.assertEqual(state["network_topology"]["profile"], PROFILE_WAN)


# ---------------------------------------------------------------------------
# generate_dnsmasq_config
# ---------------------------------------------------------------------------

class TestGenerateDnsmasqConfig(unittest.TestCase):

    def _lan_nt(self):
        return lan_config_to_state(_lan())

    def _wan_nt(self):
        return wan_config_to_state(_wan())

    def test_lan_config_has_address_lines(self):
        cfg = generate_dnsmasq_config(self._lan_nt(), DNS_REGISTRY)
        self.assertIn("address=/pve01.internal/192.168.1.10", cfg)
        self.assertIn("address=/forgejo.internal/192.168.1.21", cfg)

    def test_lan_config_has_upstream_servers(self):
        cfg = generate_dnsmasq_config(self._lan_nt(), DNS_REGISTRY)
        self.assertIn("server=8.8.8.8", cfg)
        self.assertIn("server=1.1.1.1", cfg)

    def test_lan_config_has_domain(self):
        cfg = generate_dnsmasq_config(self._lan_nt(), DNS_REGISTRY)
        self.assertIn("domain=internal", cfg)

    def test_wan_config_has_split_horizon_comment(self):
        cfg = generate_dnsmasq_config(self._wan_nt(), DNS_REGISTRY)
        self.assertIn("Split-horizon", cfg)

    def test_wan_config_has_address_lines(self):
        cfg = generate_dnsmasq_config(self._wan_nt(), DNS_REGISTRY)
        self.assertIn("address=/", cfg)

    def test_listen_address_set_when_registry_has_host(self):
        cfg = generate_dnsmasq_config(self._lan_nt(), DNS_REGISTRY)
        self.assertIn("listen-address=192.168.1.10", cfg)

    def test_empty_registry_no_address_lines(self):
        cfg = generate_dnsmasq_config(self._lan_nt(), [])
        self.assertNotIn("address=/", cfg)

    def test_profile_shown_in_header(self):
        cfg = generate_dnsmasq_config(self._lan_nt(), DNS_REGISTRY)
        self.assertIn("profile=lan", cfg)


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class TestBootstrapStateSchemaNetworkProfile(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        try:
            import jsonschema
            cls.jsonschema = jsonschema
            cls.skip = False
        except ImportError:
            cls.skip = True
        schema_path = REPO_ROOT / "data-model" / "bootstrap-state-schema.json"
        cls.schema = json.loads(schema_path.read_text(encoding="utf-8"))

    def _validate(self, instance):
        if self.skip:
            self.skipTest("jsonschema not installed")
        self.jsonschema.validate(instance, self.schema)

    def test_fixture_with_lan_profile_validates(self):
        if self.skip:
            self.skipTest("jsonschema not installed")
        fixture_path = REPO_ROOT / "tests" / "fixtures" / "bootstrap" / "bootstrap-state.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        nt = lan_config_to_state(_lan())
        fixture["network_topology"] = {**fixture.get("network_topology", {}), **nt}
        self._validate(fixture)

    def test_fixture_with_wan_profile_validates(self):
        if self.skip:
            self.skipTest("jsonschema not installed")
        fixture_path = REPO_ROOT / "tests" / "fixtures" / "bootstrap" / "bootstrap-state.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        nt = wan_config_to_state(_wan())
        fixture["network_topology"] = {**fixture.get("network_topology", {}), **nt}
        self._validate(fixture)


if __name__ == "__main__":
    unittest.main()
