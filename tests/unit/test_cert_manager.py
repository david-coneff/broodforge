"""
tests/unit/test_cert_manager.py — Unit tests for Phase 2.B cert_manager.py

Real objects only; no mocks. Uses temporary directories for state isolation.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../proxmox-bootstrap"))

from cert_manager import (
    CertRecord,
    CertManagerState,
    CertManager,
    CertManagerError,
    cert_expiry_status,
    generate_values_yaml,
    generate_cluster_issuer_yaml,
    load_state,
    save_state,
    EXPIRY_CRITICAL_DAYS,
    EXPIRY_WARNING_DAYS,
    _days_until_expiry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fixed_now(dt: datetime):
    return lambda: dt


_BASE_TIME = datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# CertRecord.new
# ---------------------------------------------------------------------------

class TestCertRecordNew:
    def test_basic_fields(self):
        cert = CertRecord.new(
            domain="forge.example.com",
            issuer_name="broodforge-acme",
            issuer_type="acme",
            secret_name="forge-example-com-tls",
            now_fn=_fixed_now(_BASE_TIME),
        )
        assert cert.domain == "forge.example.com"
        assert cert.issuer_name == "broodforge-acme"
        assert cert.issuer_type == "acme"
        assert cert.secret_name == "forge-example-com-tls"
        assert cert.status == "pending"
        assert cert.renewal_count == 0
        assert cert.expires_at is None
        assert cert.registered_at == _BASE_TIME.isoformat()

    def test_san_defaults_empty(self):
        cert = CertRecord.new(
            domain="a.example.com",
            issuer_name="si",
            issuer_type="selfsigned",
            secret_name="a-tls",
        )
        assert cert.san_domains == []

    def test_san_populated(self):
        cert = CertRecord.new(
            domain="a.example.com",
            issuer_name="si",
            issuer_type="selfsigned",
            secret_name="a-tls",
            san_domains=["b.example.com", "c.example.com"],
        )
        assert cert.san_domains == ["b.example.com", "c.example.com"]


# ---------------------------------------------------------------------------
# Expiry helpers
# ---------------------------------------------------------------------------

class TestExpiryHelpers:
    def _cert(self, days_from_now: int) -> CertRecord:
        c = CertRecord.new("x.test", "iss", "acme", "x-tls", now_fn=_fixed_now(_BASE_TIME))
        expire = _BASE_TIME + timedelta(days=days_from_now)
        c.expires_at = expire.isoformat()
        c.status = "active"
        return c

    def test_days_until_critical(self):
        c = self._cert(3)
        assert _days_until_expiry(c, _fixed_now(_BASE_TIME)) == 3

    def test_days_until_warning(self):
        c = self._cert(15)
        assert _days_until_expiry(c, _fixed_now(_BASE_TIME)) == 15

    def test_days_until_ok(self):
        c = self._cert(90)
        assert _days_until_expiry(c, _fixed_now(_BASE_TIME)) == 90

    def test_days_until_none(self):
        c = CertRecord.new("y.test", "i", "acme", "y-tls")
        assert _days_until_expiry(c, _fixed_now(_BASE_TIME)) is None

    def test_status_critical(self):
        c = self._cert(EXPIRY_CRITICAL_DAYS - 1)
        assert cert_expiry_status(c, _fixed_now(_BASE_TIME)) == "critical"

    def test_status_critical_boundary(self):
        c = self._cert(EXPIRY_CRITICAL_DAYS)
        assert cert_expiry_status(c, _fixed_now(_BASE_TIME)) == "critical"

    def test_status_warning(self):
        c = self._cert(EXPIRY_WARNING_DAYS - 1)
        assert cert_expiry_status(c, _fixed_now(_BASE_TIME)) == "warning"

    def test_status_ok(self):
        c = self._cert(EXPIRY_WARNING_DAYS + 1)
        assert cert_expiry_status(c, _fixed_now(_BASE_TIME)) == "ok"

    def test_status_unknown(self):
        c = CertRecord.new("z.test", "i", "acme", "z-tls")
        assert cert_expiry_status(c, _fixed_now(_BASE_TIME)) == "unknown"


# ---------------------------------------------------------------------------
# State I/O
# ---------------------------------------------------------------------------

class TestStateIO:
    def test_roundtrip_empty(self, tmp_path):
        state = CertManagerState()
        save_state(state, str(tmp_path))
        loaded = load_state(str(tmp_path))
        assert loaded.schema_version == "1.0"
        assert loaded.certificates == []

    def test_roundtrip_with_certs(self, tmp_path):
        state = CertManagerState()
        c = CertRecord.new("a.test", "iss", "acme", "a-tls", now_fn=_fixed_now(_BASE_TIME))
        c.expires_at = "2027-01-01T00:00:00+00:00"
        state.certificates.append(c)
        save_state(state, str(tmp_path))
        loaded = load_state(str(tmp_path))
        assert len(loaded.certificates) == 1
        assert loaded.certificates[0].domain == "a.test"
        assert loaded.certificates[0].expires_at == "2027-01-01T00:00:00+00:00"

    def test_atomic_write_uses_tmp(self, tmp_path):
        """Verify .tmp file is not left behind after save."""
        state = CertManagerState()
        save_state(state, str(tmp_path))
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []

    def test_load_nonexistent_returns_default(self, tmp_path):
        loaded = load_state(str(tmp_path / "nonexistent"))
        assert loaded.certificates == []


# ---------------------------------------------------------------------------
# CertManager operations
# ---------------------------------------------------------------------------

class TestCertManager:
    def test_register_cert(self, tmp_path):
        mgr = CertManager(state_dir=str(tmp_path), now_fn=_fixed_now(_BASE_TIME))
        cert = mgr.register_cert("forge.local", "broodforge-selfsigned")
        assert cert.domain == "forge.local"
        assert cert.status == "pending"
        assert cert.secret_name == "forge-local-tls"

    def test_register_cert_duplicate_raises(self, tmp_path):
        mgr = CertManager(state_dir=str(tmp_path))
        mgr.register_cert("dup.local", "iss")
        with pytest.raises(CertManagerError, match="already registered"):
            mgr.register_cert("dup.local", "iss")

    def test_record_renewal(self, tmp_path):
        mgr = CertManager(state_dir=str(tmp_path), now_fn=_fixed_now(_BASE_TIME))
        mgr.register_cert("renew.local", "iss")
        cert = mgr.record_renewal("renew.local", "2027-06-10T00:00:00+00:00")
        assert cert.status == "active"
        assert cert.renewal_count == 1
        assert cert.expires_at == "2027-06-10T00:00:00+00:00"

    def test_record_renewal_increments_count(self, tmp_path):
        mgr = CertManager(state_dir=str(tmp_path), now_fn=_fixed_now(_BASE_TIME))
        mgr.register_cert("multi.local", "iss")
        mgr.record_renewal("multi.local", "2027-01-01T00:00:00+00:00")
        mgr.record_renewal("multi.local", "2028-01-01T00:00:00+00:00")
        cert = mgr.state.find_cert("multi.local")
        assert cert.renewal_count == 2

    def test_record_renewal_unknown_domain_raises(self, tmp_path):
        mgr = CertManager(state_dir=str(tmp_path))
        with pytest.raises(CertManagerError, match="No certificate registered"):
            mgr.record_renewal("ghost.local", "2027-01-01T00:00:00+00:00")

    def test_mark_deployed(self, tmp_path):
        mgr = CertManager(state_dir=str(tmp_path), now_fn=_fixed_now(_BASE_TIME))
        mgr.mark_deployed("v1.14.5")
        loaded = load_state(str(tmp_path))
        assert loaded.deployed_at is not None
        assert loaded.chart_version == "v1.14.5"

    def test_register_issuer(self, tmp_path):
        mgr = CertManager(state_dir=str(tmp_path), now_fn=_fixed_now(_BASE_TIME))
        mgr.register_issuer("broodforge-acme", "acme")
        assert len(mgr.state.issuers) == 1
        assert mgr.state.issuers[0]["name"] == "broodforge-acme"

    def test_register_issuer_idempotent(self, tmp_path):
        mgr = CertManager(state_dir=str(tmp_path), now_fn=_fixed_now(_BASE_TIME))
        mgr.register_issuer("iss", "acme")
        mgr.register_issuer("iss", "selfsigned")
        assert len(mgr.state.issuers) == 1
        assert mgr.state.issuers[0]["issuer_type"] == "selfsigned"

    def test_summary_all_unknown(self, tmp_path):
        mgr = CertManager(state_dir=str(tmp_path), now_fn=_fixed_now(_BASE_TIME))
        mgr.register_cert("a.local", "iss")
        mgr.register_cert("b.local", "iss")
        summary = mgr.summary()
        assert summary["cert_count"] == 2
        assert summary["expiry_summary"]["unknown"] == 2

    def test_list_certs_critical_filter(self, tmp_path):
        mgr = CertManager(state_dir=str(tmp_path), now_fn=_fixed_now(_BASE_TIME))
        mgr.register_cert("critical.local", "iss")
        mgr.record_renewal(
            "critical.local",
            (_BASE_TIME + timedelta(days=3)).isoformat()
        )
        mgr.register_cert("ok.local", "iss")
        mgr.record_renewal(
            "ok.local",
            (_BASE_TIME + timedelta(days=90)).isoformat()
        )
        certs = mgr.list_certs(critical_only=True)
        assert len(certs) == 1
        assert certs[0].domain == "critical.local"


# ---------------------------------------------------------------------------
# Helm values generation
# ---------------------------------------------------------------------------

class TestGenerateValuesYaml:
    def test_contains_install_crds(self):
        yaml = generate_values_yaml()
        assert "installCRDs: true" in yaml

    def test_prometheus_disabled(self):
        yaml = generate_values_yaml(prometheus_enabled=False)
        assert "enabled: false" in yaml

    def test_replica_count(self):
        yaml = generate_values_yaml(replicas=3)
        assert "replicaCount: 3" in yaml


# ---------------------------------------------------------------------------
# ClusterIssuer generation
# ---------------------------------------------------------------------------

class TestGenerateClusterIssuerYaml:
    def test_selfsigned(self):
        yaml = generate_cluster_issuer_yaml("my-issuer", "selfsigned")
        assert "kind: ClusterIssuer" in yaml
        assert "selfSigned" in yaml
        assert "name: my-issuer" in yaml

    def test_acme(self):
        yaml = generate_cluster_issuer_yaml(
            "acme-issuer", "acme", email="ops@example.com"
        )
        assert "acme:" in yaml
        assert "ops@example.com" in yaml
        assert "acme-v02.api.letsencrypt.org" in yaml

    def test_acme_staging(self):
        yaml = generate_cluster_issuer_yaml(
            "acme-staging", "acme", email="ops@example.com", staging=True
        )
        assert "acme-staging-v02" in yaml

    def test_ca(self):
        yaml = generate_cluster_issuer_yaml("ca-issuer", "ca")
        assert "ca:" in yaml
        assert "secretName:" in yaml

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError, match="Unknown issuer type"):
            generate_cluster_issuer_yaml("x", "invalid")
