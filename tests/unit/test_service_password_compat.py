"""
Tests for service_password_compat.py — Phase 1.F.8 credential format compatibility.
"""
import tempfile
import unittest
from pathlib import Path

from service_password_compat import (
    CREDENTIAL_COMPAT_SH,
    FORMAT_ALPHANUMERIC,
    detect_credential_failure,
    load_service_password_formats,
    record_service_restriction,
    regenerate_credential_alphanumeric,
    service_requires_alphanumeric,
)

_CATALOG_YAML = """\
services:
  - name: forgejo
    display_name: Forgejo
    group: Infrastructure
    ram_gb: 2
    description: Git hosting
    dependencies: []
    baseline: false
    vm_count: 1

  - name: postgresql
    display_name: PostgreSQL
    group: Platform
    ram_gb: 2
    description: Database
    dependencies: []
    baseline: false
    vm_count: 1
    password_format: alphanumeric

  - name: monitoring
    display_name: Monitoring
    group: Monitoring
    ram_gb: 4
    description: Prometheus stack
    dependencies: []
    baseline: false
    vm_count: 1
"""


class TestDetectCredentialFailure(unittest.TestCase):

    def test_detects_psql_auth_failure(self):
        f = detect_credential_failure(
            "postgresql",
            "psql: FATAL: password authentication failed for user \"postgres\"",
        )
        self.assertTrue(f.detected)
        self.assertEqual(f.required_format, FORMAT_ALPHANUMERIC)
        self.assertEqual(f.service_name, "postgresql")

    def test_detects_fatal_password_failure(self):
        f = detect_credential_failure(
            "some-service",
            "FATAL: password authentication failed",
        )
        self.assertTrue(f.detected)
        self.assertEqual(f.required_format, FORMAT_ALPHANUMERIC)

    def test_no_detection_on_unrelated_error(self):
        f = detect_credential_failure(
            "forgejo",
            "Connection refused: host unreachable",
        )
        self.assertFalse(f.detected)

    def test_no_detection_on_empty_error(self):
        f = detect_credential_failure("svc", "")
        self.assertFalse(f.detected)

    def test_heuristic_detection_password_plus_special_char(self):
        f = detect_credential_failure(
            "some-svc",
            "Error: password contains invalid character: .",
        )
        self.assertTrue(f.detected)
        self.assertEqual(f.required_format, FORMAT_ALPHANUMERIC)

    def test_finding_fields_populated(self):
        f = detect_credential_failure(
            "my-db",
            "FATAL: password authentication failed",
        )
        self.assertIsNotNone(f.pattern_matched)
        self.assertIn(f.confidence, ("LOW", "MEDIUM", "HIGH"))


class TestLoadServicePasswordFormats(unittest.TestCase):

    def test_loads_alphanumeric_service(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
            f.write(_CATALOG_YAML)
            path = f.name
        try:
            formats = load_service_password_formats(path)
            self.assertIn("postgresql", formats)
            self.assertEqual(formats["postgresql"], FORMAT_ALPHANUMERIC)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_does_not_include_default_format_services(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
            f.write(_CATALOG_YAML)
            path = f.name
        try:
            formats = load_service_password_formats(path)
            self.assertNotIn("forgejo", formats)
            self.assertNotIn("monitoring", formats)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_returns_empty_dict_for_missing_file(self):
        formats = load_service_password_formats("/nonexistent/path/service-catalog.yaml")
        self.assertEqual(formats, {})

    def test_empty_catalog(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
            f.write("services:\n")
            path = f.name
        try:
            formats = load_service_password_formats(path)
            self.assertEqual(formats, {})
        finally:
            Path(path).unlink(missing_ok=True)


class TestServiceRequiresAlphanumeric(unittest.TestCase):

    def test_known_alphanumeric_service(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
            f.write(_CATALOG_YAML)
            path = f.name
        try:
            self.assertTrue(service_requires_alphanumeric("postgresql", path))
        finally:
            Path(path).unlink(missing_ok=True)

    def test_default_format_service(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
            f.write(_CATALOG_YAML)
            path = f.name
        try:
            self.assertFalse(service_requires_alphanumeric("forgejo", path))
        finally:
            Path(path).unlink(missing_ok=True)

    def test_unknown_service_defaults_to_false(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
            f.write(_CATALOG_YAML)
            path = f.name
        try:
            self.assertFalse(service_requires_alphanumeric("no-such-service", path))
        finally:
            Path(path).unlink(missing_ok=True)


class TestRecordServiceRestriction(unittest.TestCase):

    def test_records_new_restriction(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
            f.write(_CATALOG_YAML)
            path = f.name
        try:
            result = record_service_restriction("forgejo", path)
            self.assertTrue(result)
            # Verify the format was written
            self.assertTrue(service_requires_alphanumeric("forgejo", path))
        finally:
            Path(path).unlink(missing_ok=True)

    def test_updates_existing_restriction(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
            f.write(_CATALOG_YAML)
            path = f.name
        try:
            # postgresql already has alphanumeric — should not break
            result = record_service_restriction("postgresql", path)
            self.assertTrue(result)
            self.assertTrue(service_requires_alphanumeric("postgresql", path))
        finally:
            Path(path).unlink(missing_ok=True)

    def test_returns_false_for_missing_file(self):
        result = record_service_restriction("svc", "/nonexistent/catalog.yaml")
        self.assertFalse(result)


class TestRegenerateCredential(unittest.TestCase):

    def test_returns_string(self):
        cred = regenerate_credential_alphanumeric("postgresql")
        self.assertIsInstance(cred, str)

    def test_alphanumeric_only(self):
        # Run several times to reduce probability of false pass
        for _ in range(20):
            cred = regenerate_credential_alphanumeric("test-svc")
            self.assertTrue(cred.isalnum(), f"Non-alphanumeric credential: {cred!r}")

    def test_minimum_length(self):
        cred = regenerate_credential_alphanumeric("test-svc")
        self.assertGreaterEqual(len(cred), 16)


class TestBashLibraryGenerated(unittest.TestCase):

    def test_credential_compat_sh_is_string(self):
        self.assertIsInstance(CREDENTIAL_COMPAT_SH, str)

    def test_contains_detect_function(self):
        self.assertIn("_detect_credential_failure", CREDENTIAL_COMPAT_SH)

    def test_contains_with_compat_function(self):
        self.assertIn("with_credential_compat", CREDENTIAL_COMPAT_SH)

    def test_no_secret_values_hardcoded(self):
        # Ensure the shell library doesn't contain any hardcoded secrets
        import re
        self.assertFalse(re.search(r'KDBX_MASTER_PASSWORD\s*=\s*"[^$]', CREDENTIAL_COMPAT_SH))


class TestServiceCatalogIntegration(unittest.TestCase):
    """Test that spawn_planner.ServiceCatalog exposes password_format."""

    def setUp(self):
        from spawn_planner import ServiceCatalog
        self._catalog = ServiceCatalog.from_list([
            {"name": "forgejo", "group": "Infrastructure", "ram_gb": 2, "disk_gb": 10,
             "vm_count": 1, "dependencies": [], "baseline": False},
            {"name": "postgresql", "group": "Platform", "ram_gb": 2, "disk_gb": 20,
             "vm_count": 1, "dependencies": [], "baseline": False,
             "password_format": "alphanumeric"},
        ])

    def test_password_format_default_service(self):
        self.assertEqual(self._catalog.password_format("forgejo"), "default")

    def test_password_format_alphanumeric_service(self):
        self.assertEqual(self._catalog.password_format("postgresql"), "alphanumeric")

    def test_password_format_unknown_service(self):
        self.assertEqual(self._catalog.password_format("no-such-service"), "default")

    def test_alphanumeric_services_filter(self):
        result = self._catalog.alphanumeric_services(["forgejo", "postgresql"])
        self.assertEqual(result, ["postgresql"])

    def test_alphanumeric_services_empty_selection(self):
        result = self._catalog.alphanumeric_services([])
        self.assertEqual(result, [])

    def test_alphanumeric_services_none_match(self):
        result = self._catalog.alphanumeric_services(["forgejo"])
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
