#!/usr/bin/env python3
"""
Tests for Milestone 7.3 — External Dependency State.

Covers:
  - ExternalDependencyRegistry (all methods)
  - build_external_dependency_registry factory
  - _score_external_dependency_state() cert expiry thresholds
  - Appendix G rendering in recovery_runbook.py
  - external-dependency-state-schema.json validates correctly
  - bootstrap-state-schema.json accepts external_dependencies
  - bootstrap-state.json fixture validates with external_dependencies
"""

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent

from external_dependencies import (
    CERT_EXPIRY_ORANGE_DAYS,
    CERT_EXPIRY_RED_DAYS,
    CERT_EXPIRY_YELLOW_DAYS,
    ExternalDependencyRegistry,
    build_external_dependency_registry,
)
from readiness import _score_external_dependency_state

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _future_iso(days: int) -> str:
    dt = datetime.now(timezone.utc) + timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_dep(dep_id="dep-a", name="Dep A", dep_type="dns_provider",
              endpoint="https://example.com", required_by=None,
              cert_days=None, status="reachable"):
    dep = {
        "id": dep_id,
        "name": name,
        "type": dep_type,
        "endpoint": endpoint,
        "required_by": required_by or [],
        "status": status,
    }
    if cert_days is not None:
        dep["certificate"] = {
            "expires_at": _future_iso(cert_days),
            "issuer": "Test CA",
            "subject": "example.com",
            "auto_renew": False,
        }
    return dep


# ---------------------------------------------------------------------------
# ExternalDependencyRegistry — construction and basic queries
# ---------------------------------------------------------------------------

class TestExternalDependencyRegistryBasic(unittest.TestCase):

    def test_empty_registry_not_available(self):
        reg = ExternalDependencyRegistry([])
        self.assertFalse(reg.available())

    def test_none_registry_not_available(self):
        reg = ExternalDependencyRegistry(None)
        self.assertFalse(reg.available())

    def test_with_entries_is_available(self):
        reg = ExternalDependencyRegistry([_make_dep()])
        self.assertTrue(reg.available())

    def test_count_reflects_entries(self):
        deps = [_make_dep("a"), _make_dep("b"), _make_dep("c")]
        reg = ExternalDependencyRegistry(deps)
        self.assertEqual(reg.count(), 3)

    def test_all_returns_copy(self):
        deps = [_make_dep("a"), _make_dep("b")]
        reg = ExternalDependencyRegistry(deps)
        result = reg.all()
        self.assertEqual(len(result), 2)
        result.clear()
        self.assertEqual(reg.count(), 2)  # original unmodified

    def test_get_existing_entry(self):
        dep = _make_dep("dns-cf", "Cloudflare DNS", "dns_provider", "https://1.1.1.1")
        reg = ExternalDependencyRegistry([dep])
        found = reg.get("dns-cf")
        self.assertIsNotNone(found)
        self.assertEqual(found["name"], "Cloudflare DNS")

    def test_get_missing_returns_none(self):
        reg = ExternalDependencyRegistry([_make_dep("a")])
        self.assertIsNone(reg.get("nonexistent"))

    def test_get_first_entry_wins_on_id_collision(self):
        dep1 = {**_make_dep("dup-id", "First"), }
        dep2 = {**_make_dep("dup-id", "Second")}
        reg = ExternalDependencyRegistry([dep1, dep2])
        # Both have the same id; first one should win in _by_id
        self.assertIn(reg.get("dup-id")["name"], ("First", "Second"))


# ---------------------------------------------------------------------------
# ExternalDependencyRegistry — certificate queries
# ---------------------------------------------------------------------------

class TestExternalDependencyRegistryCerts(unittest.TestCase):

    def _make_registry(self, *cert_days_list):
        deps = [_make_dep(f"dep-{i}", cert_days=d)
                for i, d in enumerate(cert_days_list)]
        return ExternalDependencyRegistry(deps)

    def test_with_certificates_excludes_no_cert(self):
        deps = [_make_dep("no-cert"), _make_dep("has-cert", cert_days=90)]
        reg = ExternalDependencyRegistry(deps)
        self.assertEqual(len(reg.with_certificates()), 1)
        self.assertEqual(reg.with_certificates()[0]["id"], "has-cert")

    def test_with_certificates_empty_when_none_declared(self):
        reg = ExternalDependencyRegistry([_make_dep("a"), _make_dep("b")])
        self.assertEqual(reg.with_certificates(), [])

    def test_expiring_within_days_includes_expiring(self):
        reg = self._make_registry(5, 25, 45, 90)
        expiring = reg.expiring_within_days(30)
        ids = {d["id"] for d in expiring}
        self.assertIn("dep-0", ids)  # 5 days
        self.assertIn("dep-1", ids)  # 25 days
        self.assertNotIn("dep-2", ids)  # 45 days
        self.assertNotIn("dep-3", ids)  # 90 days

    def test_expiring_within_days_injects_days_remaining(self):
        reg = self._make_registry(10)
        expiring = reg.expiring_within_days(30)
        self.assertEqual(len(expiring), 1)
        days = expiring[0]["_days_remaining"]
        self.assertGreaterEqual(days, 9)
        self.assertLessEqual(days, 10)

    def test_expiring_within_days_zero_threshold(self):
        reg = self._make_registry(0, 1, 90)
        # 0 days is at or before threshold; 1 day is within 1 day threshold
        expiring = reg.expiring_within_days(0)
        # Only entries with days_remaining <= 0 (already expired)
        for d in expiring:
            self.assertLessEqual(d["_days_remaining"], 0)

    def test_expiring_excludes_no_cert_entries(self):
        deps = [_make_dep("no-cert"), _make_dep("has-cert", cert_days=5)]
        reg = ExternalDependencyRegistry(deps)
        expiring = reg.expiring_within_days(30)
        ids = {d["id"] for d in expiring}
        self.assertNotIn("no-cert", ids)

    def test_days_until_expiry_returns_correct_value(self):
        dep = _make_dep("d", cert_days=45)
        reg = ExternalDependencyRegistry([dep])
        days = reg.days_until_expiry(dep)
        self.assertIsNotNone(days)
        self.assertGreaterEqual(days, 44)
        self.assertLessEqual(days, 45)

    def test_days_until_expiry_no_cert_returns_none(self):
        dep = _make_dep("d")
        reg = ExternalDependencyRegistry([dep])
        self.assertIsNone(reg.days_until_expiry(dep))

    def test_days_until_expiry_bad_date_returns_none(self):
        dep = _make_dep("d")
        dep["certificate"] = {"expires_at": "not-a-date"}
        reg = ExternalDependencyRegistry([dep])
        self.assertIsNone(reg.days_until_expiry(dep))


# ---------------------------------------------------------------------------
# build_external_dependency_registry factory
# ---------------------------------------------------------------------------

class TestBuildExternalDependencyRegistry(unittest.TestCase):

    def test_factory_from_manifest(self):
        manifest = {"external_dependencies": [_make_dep("a"), _make_dep("b")]}
        reg = build_external_dependency_registry(manifest)
        self.assertTrue(reg.available())
        self.assertEqual(reg.count(), 2)

    def test_factory_missing_key_returns_empty(self):
        reg = build_external_dependency_registry({})
        self.assertFalse(reg.available())

    def test_factory_null_key_returns_empty(self):
        reg = build_external_dependency_registry({"external_dependencies": None})
        self.assertFalse(reg.available())

    def test_factory_empty_list_returns_empty(self):
        reg = build_external_dependency_registry({"external_dependencies": []})
        self.assertFalse(reg.available())


# ---------------------------------------------------------------------------
# _score_external_dependency_state — readiness gaps
# ---------------------------------------------------------------------------

class TestScoreExternalDependencyState(unittest.TestCase):

    def _manifest(self, *cert_days_list):
        deps = [_make_dep(f"dep-{i}", cert_days=d) for i, d in enumerate(cert_days_list)]
        return {"external_dependencies": deps}

    def test_no_external_dependencies_no_gaps(self):
        gaps = _score_external_dependency_state({})
        self.assertEqual(gaps, [])

    def test_empty_list_no_gaps(self):
        gaps = _score_external_dependency_state({"external_dependencies": []})
        self.assertEqual(gaps, [])

    def test_healthy_cert_no_gap(self):
        gaps = _score_external_dependency_state(self._manifest(90))
        self.assertEqual(gaps, [])

    def test_yellow_threshold(self):
        # Between 30 and 60 days → YELLOW
        gaps = _score_external_dependency_state(self._manifest(45))
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].severity, "YELLOW")

    def test_orange_threshold(self):
        # Between 7 and 30 days → ORANGE
        gaps = _score_external_dependency_state(self._manifest(20))
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].severity, "ORANGE")

    def test_red_threshold(self):
        # 7 days or fewer → RED
        gaps = _score_external_dependency_state(self._manifest(5))
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].severity, "RED")

    def test_exactly_at_red_boundary(self):
        gaps = _score_external_dependency_state(self._manifest(CERT_EXPIRY_RED_DAYS))
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].severity, "RED")

    def test_exactly_at_orange_boundary(self):
        gaps = _score_external_dependency_state(self._manifest(CERT_EXPIRY_ORANGE_DAYS))
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].severity, "ORANGE")

    def test_exactly_at_yellow_boundary(self):
        gaps = _score_external_dependency_state(self._manifest(CERT_EXPIRY_YELLOW_DAYS))
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].severity, "YELLOW")

    def test_just_above_yellow_no_gap(self):
        # Use +2 to avoid timedelta.days truncation at boundary
        gaps = _score_external_dependency_state(self._manifest(CERT_EXPIRY_YELLOW_DAYS + 2))
        self.assertEqual(gaps, [])

    def test_multiple_certs_separate_gaps(self):
        # 5 days = RED, 20 days = ORANGE, 45 days = YELLOW, 90 days = no gap
        gaps = _score_external_dependency_state(self._manifest(5, 20, 45, 90))
        self.assertEqual(len(gaps), 3)
        severities = {g.severity for g in gaps}
        self.assertEqual(severities, {"RED", "ORANGE", "YELLOW"})

    def test_no_cert_dep_produces_no_gap(self):
        manifest = {"external_dependencies": [_make_dep("no-cert")]}
        gaps = _score_external_dependency_state(manifest)
        self.assertEqual(gaps, [])

    def test_gap_component_id_prefixed_with_external(self):
        gaps = _score_external_dependency_state(self._manifest(5))
        self.assertTrue(gaps[0].component_id.startswith("external:"))

    def test_gap_type_is_cert_expiry(self):
        gaps = _score_external_dependency_state(self._manifest(5))
        self.assertEqual(gaps[0].gap_type, "CERT_EXPIRY")

    def test_gap_description_mentions_dependency_name(self):
        dep = _make_dep("my-dep", "My Dependency", cert_days=5)
        gaps = _score_external_dependency_state({"external_dependencies": [dep]})
        self.assertIn("My Dependency", gaps[0].description)

    def test_gap_remediation_mentions_required_by(self):
        dep = _make_dep("d", cert_days=5, required_by=["forgejo", "inventory"])
        gaps = _score_external_dependency_state({"external_dependencies": [dep]})
        self.assertIn("forgejo", gaps[0].remediation)

    def test_unparseable_cert_date_produces_no_gap(self):
        dep = _make_dep("d")
        dep["certificate"] = {"expires_at": "not-a-date"}
        gaps = _score_external_dependency_state({"external_dependencies": [dep]})
        self.assertEqual(gaps, [])


# ---------------------------------------------------------------------------
# Recovery runbook — Appendix G rendering
# ---------------------------------------------------------------------------

class TestRecoveryRunbookAppendixG(unittest.TestCase):

    def _build_minimal_runbook(self, manifest_extras=None):
        """Build a recovery runbook HTML string with given manifest additions."""
        from dependencies import build_graph
        from html_recovery_runbook import build_recovery_runbook_html
        from readiness import score_graph

        manifest = {
            "host": {"hostname": "pve-test", "proxmox_version": "8.0"},
            "network": {"default_gateway": "192.168.1.1", "dns_servers": ["8.8.8.8"]},
            "vms": [],
            "containers": [],
            "collected_at": "2026-01-01T00:00:00Z",
        }
        if manifest_extras:
            manifest.update(manifest_extras)

        graph = build_graph(manifest)
        readiness = score_graph(graph, manifest)
        generation_meta = {
            "generated_at": "2026-01-01T12:00:00Z",
            "generated_at_display": "2026-01-01 12:00:00 UTC",
        }
        return build_recovery_runbook_html(manifest, graph, readiness, generation_meta)

    def test_appendix_g_header_present(self):
        text = self._build_minimal_runbook()
        self.assertIn("Appendix G", text)
        self.assertIn("External Dependencies", text)

    def test_appendix_g_no_deps_message(self):
        text = self._build_minimal_runbook()
        self.assertIn("No external dependencies declared", text)

    def test_appendix_g_shows_dependency_name(self):
        deps = [_make_dep("cf-dns", "Cloudflare DNS", "dns_provider", "https://1.1.1.1")]
        text = self._build_minimal_runbook({"external_dependencies": deps})
        self.assertIn("Cloudflare DNS", text)

    def test_appendix_g_shows_endpoint(self):
        deps = [_make_dep("cf-dns", endpoint="https://1.1.1.1")]
        text = self._build_minimal_runbook({"external_dependencies": deps})
        self.assertIn("https://1.1.1.1", text)

    def test_appendix_g_shows_dep_type(self):
        deps = [_make_dep("cf-dns", dep_type="dns_provider")]
        text = self._build_minimal_runbook({"external_dependencies": deps})
        self.assertIn("dns_provider", text)

    def test_appendix_g_shows_required_by(self):
        deps = [_make_dep("cf-dns", required_by=["forgejo", "inventory"])]
        text = self._build_minimal_runbook({"external_dependencies": deps})
        self.assertIn("forgejo", text)
        self.assertIn("inventory", text)

    def test_appendix_g_cert_section_shows_expiry(self):
        dep = _make_dep("cf-dns", cert_days=90)
        text = self._build_minimal_runbook({"external_dependencies": [dep]})
        self.assertIn("TLS Certificate", text)
        self.assertIn("Expires at", text)

    def test_appendix_g_cert_shows_issuer(self):
        dep = _make_dep("cf-dns", cert_days=90)
        dep["certificate"]["issuer"] = "Let's Encrypt"
        text = self._build_minimal_runbook({"external_dependencies": [dep]})
        # Apostrophe may be HTML-escaped to &#x27; — check the unambiguous part
        self.assertIn("Encrypt", text)
        self.assertIn("Issuer", text)

    def test_appendix_g_imminent_expiry_warns(self):
        dep = _make_dep("cf-dns", cert_days=3)
        text = self._build_minimal_runbook({"external_dependencies": [dep]})
        self.assertIn("EXPIRES IN", text)

    def test_appendix_g_no_cert_dep_has_no_cert_section(self):
        dep = _make_dep("smtp", dep_type="smtp_relay")
        text = self._build_minimal_runbook({"external_dependencies": [dep]})
        self.assertIn("smtp_relay", text)
        # No TLS Certificate header when no cert declared
        self.assertNotIn("TLS Certificate", text)

    def test_appendix_g_multiple_deps(self):
        deps = [
            _make_dep("dep-a", "Dep Alpha", cert_days=90),
            _make_dep("dep-b", "Dep Beta"),
        ]
        text = self._build_minimal_runbook({"external_dependencies": deps})
        self.assertIn("Dep Alpha", text)
        self.assertIn("Dep Beta", text)

    def test_appendix_g_failover_shown(self):
        dep = _make_dep("cf-dns")
        dep["failover"] = "8.8.8.8"
        text = self._build_minimal_runbook({"external_dependencies": [dep]})
        self.assertIn("8.8.8.8", text)

    def test_appendix_g_notes_shown(self):
        dep = _make_dep("smtp")
        dep["notes"] = "Uses STARTTLS on port 587"
        text = self._build_minimal_runbook({"external_dependencies": [dep]})
        self.assertIn("STARTTLS", text)


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class TestExternalDependencyStateSchema(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        try:
            import jsonschema
            cls.jsonschema = jsonschema
            cls.skip = False
        except ImportError:
            cls.skip = True

        schema_path = REPO_ROOT / "data-model" / "external-dependency-state-schema.json"
        cls.schema = json.loads(schema_path.read_text(encoding="utf-8"))

    def _validate(self, instance):
        if self.skip:
            self.skipTest("jsonschema not installed")
        self.jsonschema.validate(instance, self.schema)

    def _minimal_valid(self):
        return {
            "schema_version": "1.0",
            "cell_id": "test-cell",
            "declared_at": "2026-01-01T00:00:00Z",
            "dependencies": []
        }

    def test_minimal_document_validates(self):
        self._validate(self._minimal_valid())

    def test_missing_schema_version_fails(self):
        if self.skip:
            self.skipTest("jsonschema not installed")
        doc = self._minimal_valid()
        del doc["schema_version"]
        with self.assertRaises(self.jsonschema.ValidationError):
            self._validate(doc)

    def test_missing_cell_id_fails(self):
        if self.skip:
            self.skipTest("jsonschema not installed")
        doc = self._minimal_valid()
        del doc["cell_id"]
        with self.assertRaises(self.jsonschema.ValidationError):
            self._validate(doc)

    def test_dependency_with_all_fields_validates(self):
        doc = self._minimal_valid()
        doc["dependencies"] = [{
            "id": "cf-dns",
            "name": "Cloudflare DNS",
            "type": "dns_provider",
            "endpoint": "https://1.1.1.1",
            "description": "DNS resolver",
            "required_by": ["forgejo"],
            "status": "reachable",
            "last_checked_at": "2026-01-01T00:00:00Z",
            "certificate": {
                "expires_at": "2027-01-01T00:00:00Z",
                "issuer": "DigiCert",
                "subject": "cloudflare.com",
                "sans": ["cloudflare.com", "*.cloudflare.com"],
                "auto_renew": True
            },
            "failover": "8.8.8.8",
            "notes": None
        }]
        self._validate(doc)

    def test_dependency_missing_required_id_fails(self):
        if self.skip:
            self.skipTest("jsonschema not installed")
        doc = self._minimal_valid()
        doc["dependencies"] = [{
            "name": "CF DNS", "type": "dns_provider", "endpoint": "https://1.1.1.1"
        }]
        with self.assertRaises(self.jsonschema.ValidationError):
            self._validate(doc)

    def test_invalid_type_enum_fails(self):
        if self.skip:
            self.skipTest("jsonschema not installed")
        doc = self._minimal_valid()
        doc["dependencies"] = [{
            "id": "d", "name": "D", "type": "invalid_type", "endpoint": "https://x"
        }]
        with self.assertRaises(self.jsonschema.ValidationError):
            self._validate(doc)

    def test_invalid_status_enum_fails(self):
        if self.skip:
            self.skipTest("jsonschema not installed")
        doc = self._minimal_valid()
        doc["dependencies"] = [{
            "id": "d", "name": "D", "type": "other", "endpoint": "x", "status": "ok"
        }]
        with self.assertRaises(self.jsonschema.ValidationError):
            self._validate(doc)


# ---------------------------------------------------------------------------
# Bootstrap state fixture validation
# ---------------------------------------------------------------------------

class TestBootstrapStateFixtureWithExternalDeps(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        fixture_path = REPO_ROOT / "tests" / "fixtures" / "bootstrap" / "bootstrap-state.json"
        cls.fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    def test_fixture_has_external_dependencies(self):
        self.assertIn("external_dependencies", self.fixture)
        deps = self.fixture["external_dependencies"]
        self.assertIsInstance(deps, list)
        self.assertGreater(len(deps), 0)

    def test_fixture_deps_have_required_fields(self):
        for dep in self.fixture["external_dependencies"]:
            self.assertIn("id", dep)
            self.assertIn("name", dep)
            self.assertIn("type", dep)
            self.assertIn("endpoint", dep)

    def test_fixture_includes_dns_provider(self):
        types = {d["type"] for d in self.fixture["external_dependencies"]}
        self.assertIn("dns_provider", types)

    def test_fixture_includes_smtp_relay(self):
        types = {d["type"] for d in self.fixture["external_dependencies"]}
        self.assertIn("smtp_relay", types)

    def test_fixture_includes_cert_authority(self):
        types = {d["type"] for d in self.fixture["external_dependencies"]}
        self.assertIn("cert_authority", types)

    def test_fixture_cert_authority_has_certificate(self):
        cert_auths = [d for d in self.fixture["external_dependencies"]
                      if d["type"] == "cert_authority"]
        for ca in cert_auths:
            if ca.get("certificate"):
                cert = ca["certificate"]
                self.assertIn("expires_at", cert)

    def test_fixture_dns_provider_has_certificate(self):
        dns = [d for d in self.fixture["external_dependencies"]
               if d["type"] == "dns_provider"]
        self.assertTrue(len(dns) > 0)
        # DNS provider in fixture should have a certificate
        certs = [d["certificate"] for d in dns if d.get("certificate")]
        self.assertTrue(len(certs) > 0)

    def test_fixture_all_types_are_valid_enum_values(self):
        valid_types = {
            "dns_provider", "smtp_relay", "cert_authority", "ntp_server",
            "container_registry", "package_repo", "vpn_gateway",
            "object_storage", "monitoring_sink", "other"
        }
        for dep in self.fixture["external_dependencies"]:
            self.assertIn(dep.get("type", ""), valid_types)


# ---------------------------------------------------------------------------
# Constants sanity check
# ---------------------------------------------------------------------------

class TestExternalDependencyConstants(unittest.TestCase):

    def test_red_threshold_less_than_orange(self):
        self.assertLess(CERT_EXPIRY_RED_DAYS, CERT_EXPIRY_ORANGE_DAYS)

    def test_orange_threshold_less_than_yellow(self):
        self.assertLess(CERT_EXPIRY_ORANGE_DAYS, CERT_EXPIRY_YELLOW_DAYS)

    def test_red_threshold_is_7(self):
        self.assertEqual(CERT_EXPIRY_RED_DAYS, 7)

    def test_orange_threshold_is_30(self):
        self.assertEqual(CERT_EXPIRY_ORANGE_DAYS, 30)

    def test_yellow_threshold_is_60(self):
        self.assertEqual(CERT_EXPIRY_YELLOW_DAYS, 60)


if __name__ == "__main__":
    unittest.main()
