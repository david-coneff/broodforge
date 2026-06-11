"""Unit tests for ingress_manager.py — Phase 2.F."""
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../proxmox-bootstrap"))
from ingress_manager import (
    IngressDeployment,
    IngressManager,
    IngressRoute,
    IngressState,
    TlsConfig,
)

FIXED_TS = datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)
_now = lambda: FIXED_TS  # noqa: E731


@pytest.fixture
def tmpdir_state():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def mgr(tmpdir_state):
    return IngressManager(state_dir=tmpdir_state, now_fn=_now)


# ---------------------------------------------------------------------------
# TlsConfig
# ---------------------------------------------------------------------------

class TestTlsConfig:
    def test_roundtrip(self):
        tc = TlsConfig(secret_name="my-tls", hosts=["foo.example.com"], cluster_issuer="le-prod")
        assert TlsConfig.from_dict(tc.to_dict()) == tc

    def test_defaults(self):
        tc = TlsConfig(secret_name="s")
        assert tc.hosts == []
        assert tc.cluster_issuer == ""


# ---------------------------------------------------------------------------
# IngressRoute
# ---------------------------------------------------------------------------

class TestIngressRoute:
    def test_roundtrip_no_tls(self):
        r = IngressRoute(
            name="forgejo", namespace="apps",
            service_name="forgejo", service_port=3000,
            hostname="forgejo.example.com",
        )
        r2 = IngressRoute.from_dict(r.to_dict())
        assert r2.name == "forgejo"
        assert r2.tls is None

    def test_roundtrip_with_tls(self):
        tls = TlsConfig(secret_name="forgejo-tls", cluster_issuer="le-prod")
        r = IngressRoute(
            name="forgejo", namespace="apps",
            service_name="forgejo", service_port=3000,
            hostname="forgejo.example.com", tls=tls,
        )
        r2 = IngressRoute.from_dict(r.to_dict())
        assert r2.tls is not None
        assert r2.tls.secret_name == "forgejo-tls"
        assert r2.tls.cluster_issuer == "le-prod"

    def test_defaults(self):
        r = IngressRoute(
            name="x", namespace="default",
            service_name="svc", service_port=80,
            hostname="x.example.com",
        )
        assert r.path_prefix == "/"
        assert r.enabled is True
        assert r.annotations == {}


# ---------------------------------------------------------------------------
# IngressState
# ---------------------------------------------------------------------------

class TestIngressState:
    def test_empty_roundtrip(self):
        s = IngressState()
        s2 = IngressState.from_dict(s.to_dict())
        assert s2.deployment.deployed is False
        assert s2.routes == []

    def test_roundtrip_with_routes(self):
        s = IngressState()
        s.routes.append(IngressRoute(
            name="app", namespace="ns",
            service_name="app", service_port=8080,
            hostname="app.example.com",
        ))
        s2 = IngressState.from_dict(s.to_dict())
        assert len(s2.routes) == 1
        assert s2.routes[0].hostname == "app.example.com"


# ---------------------------------------------------------------------------
# IngressManager — state I/O
# ---------------------------------------------------------------------------

class TestIngressManagerIO:
    def test_load_missing_returns_empty(self, mgr):
        state = mgr.load()
        assert state.deployment.deployed is False
        assert state.routes == []

    def test_save_and_load(self, mgr):
        state = mgr.load()
        state.deployment.deployed = True
        state.deployment.namespace = "ingress-nginx"
        mgr.save(state)
        loaded = mgr.load()
        assert loaded.deployment.deployed is True

    def test_atomic_write_creates_file(self, mgr):
        mgr.save(IngressState())
        assert os.path.exists(os.path.join(mgr._state_dir, "ingress-state.json"))

    def test_no_tmp_file_left_after_save(self, mgr):
        mgr.save(IngressState())
        tmp = os.path.join(mgr._state_dir, "ingress-state.json.tmp")
        assert not os.path.exists(tmp)


# ---------------------------------------------------------------------------
# Route registry
# ---------------------------------------------------------------------------

class TestRouteRegistry:
    def test_register_new_route(self, mgr):
        route = mgr.register_route(
            name="grafana", namespace="monitoring",
            service_name="grafana", service_port=3000,
            hostname="grafana.example.com",
        )
        assert route.name == "grafana"
        assert route.registered_at == "2026-06-10T12:00:00Z"
        routes = mgr.list_routes()
        assert len(routes) == 1

    def test_register_updates_existing(self, mgr):
        mgr.register_route(
            name="app", namespace="ns",
            service_name="app-v1", service_port=8080,
            hostname="app.example.com",
        )
        mgr.register_route(
            name="app", namespace="ns",
            service_name="app-v2", service_port=9090,
            hostname="app.example.com",
        )
        routes = mgr.list_routes()
        assert len(routes) == 1
        assert routes[0].service_name == "app-v2"
        assert routes[0].service_port == 9090

    def test_register_dry_run_no_persist(self, mgr):
        mgr.register_route(
            name="dry", namespace="ns",
            service_name="svc", service_port=80,
            hostname="dry.example.com",
            dry_run=True,
        )
        assert mgr.list_routes() == []

    def test_disable_route(self, mgr):
        mgr.register_route(
            name="app", namespace="ns",
            service_name="app", service_port=80,
            hostname="app.example.com",
        )
        result = mgr.disable_route("app", "ns")
        assert result is True
        routes = mgr.list_routes(enabled_only=True)
        assert len(routes) == 0
        all_routes = mgr.list_routes()
        assert len(all_routes) == 1

    def test_disable_missing_route_returns_false(self, mgr):
        assert mgr.disable_route("nonexistent", "ns") is False

    def test_list_routes_filter_namespace(self, mgr):
        mgr.register_route("a", "ns1", "svc-a", 80, "a.example.com")
        mgr.register_route("b", "ns2", "svc-b", 80, "b.example.com")
        assert len(mgr.list_routes(namespace="ns1")) == 1
        assert len(mgr.list_routes(namespace="ns2")) == 1
        assert len(mgr.list_routes()) == 2

    def test_route_with_tls(self, mgr):
        tls = TlsConfig(secret_name="app-tls", cluster_issuer="le-prod")
        mgr.register_route(
            name="app", namespace="ns",
            service_name="app", service_port=443,
            hostname="app.example.com", tls=tls,
        )
        routes = mgr.list_routes()
        assert routes[0].tls is not None
        assert routes[0].tls.secret_name == "app-tls"


# ---------------------------------------------------------------------------
# Helm values generation
# ---------------------------------------------------------------------------

class TestHelmValuesGeneration:
    def test_default_values_structure(self, mgr):
        v = mgr.generate_helm_values()
        ctrl = v["controller"]
        assert ctrl["replicaCount"] == 1
        assert ctrl["service"]["type"] == "LoadBalancer"
        assert ctrl["metrics"]["enabled"] is True

    def test_nodeport_values(self, mgr):
        v = mgr.generate_helm_values(
            service_type="NodePort",
            node_port_http=30080,
            node_port_https=30443,
        )
        assert v["controller"]["service"]["nodePorts"]["http"] == 30080
        assert v["controller"]["service"]["nodePorts"]["https"] == 30443

    def test_no_nodeports_for_loadbalancer(self, mgr):
        v = mgr.generate_helm_values(service_type="LoadBalancer")
        assert "nodePorts" not in v["controller"]["service"]

    def test_replica_count_propagated(self, mgr):
        v = mgr.generate_helm_values(replica_count=3)
        assert v["controller"]["replicaCount"] == 3


# ---------------------------------------------------------------------------
# Ingress manifest generation
# ---------------------------------------------------------------------------

class TestManifestGeneration:
    def _make_route(self, tls=None):
        return IngressRoute(
            name="forgejo", namespace="apps",
            service_name="forgejo", service_port=3000,
            hostname="forgejo.example.com", tls=tls,
        )

    def test_manifest_structure(self, mgr):
        m = mgr.generate_ingress_manifest(self._make_route())
        assert m["kind"] == "Ingress"
        assert m["apiVersion"] == "networking.k8s.io/v1"
        assert m["metadata"]["name"] == "forgejo"
        assert m["metadata"]["namespace"] == "apps"

    def test_manifest_backend(self, mgr):
        m = mgr.generate_ingress_manifest(self._make_route())
        paths = m["spec"]["rules"][0]["http"]["paths"]
        assert paths[0]["backend"]["service"]["name"] == "forgejo"
        assert paths[0]["backend"]["service"]["port"]["number"] == 3000

    def test_manifest_no_tls_section_when_no_tls(self, mgr):
        m = mgr.generate_ingress_manifest(self._make_route())
        assert "tls" not in m["spec"]

    def test_manifest_tls_section(self, mgr):
        tls = TlsConfig(secret_name="forgejo-tls", hosts=["forgejo.example.com"], cluster_issuer="le-prod")
        m = mgr.generate_ingress_manifest(self._make_route(tls=tls))
        assert "tls" in m["spec"]
        assert m["spec"]["tls"][0]["secretName"] == "forgejo-tls"
        assert "cert-manager.io/cluster-issuer" in m["metadata"]["annotations"]

    def test_manifest_tls_uses_hostname_when_no_hosts(self, mgr):
        tls = TlsConfig(secret_name="app-tls")
        route = self._make_route(tls=tls)
        m = mgr.generate_ingress_manifest(route)
        assert m["spec"]["tls"][0]["hosts"] == ["forgejo.example.com"]

    def test_manifest_annotations_merged(self, mgr):
        route = IngressRoute(
            name="app", namespace="ns", service_name="app", service_port=80,
            hostname="app.example.com",
            annotations={"nginx.ingress.kubernetes.io/ssl-redirect": "true"},
        )
        m = mgr.generate_ingress_manifest(route)
        assert "nginx.ingress.kubernetes.io/ssl-redirect" in m["metadata"]["annotations"]
        assert "kubernetes.io/ingress.class" in m["metadata"]["annotations"]


# ---------------------------------------------------------------------------
# Helm deploy (subprocess mocked)
# ---------------------------------------------------------------------------

class TestHelmDeploy:
    def test_deploy_records_state_on_success(self, mgr):
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("ingress_manager.subprocess.run", return_value=mock_result):
            rc = mgr.deploy(dry_run=False)
        assert rc == 0
        state = mgr.load()
        assert state.deployment.deployed is True
        assert state.deployment.deployed_at == "2026-06-10T12:00:00Z"

    def test_deploy_dry_run_no_state_change(self, mgr):
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("ingress_manager.subprocess.run", return_value=mock_result):
            mgr.deploy(dry_run=True)
        state = mgr.load()
        assert state.deployment.deployed is False

    def test_deploy_failure_no_state_change(self, mgr):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "helm error"
        with patch("ingress_manager.subprocess.run", return_value=mock_result):
            rc = mgr.deploy()
        assert rc == 1
        state = mgr.load()
        assert state.deployment.deployed is False

    def test_deploy_passes_chart_version(self, mgr):
        calls = []
        mock_result = MagicMock(returncode=0)
        def capture(*a, **kw):
            calls.append(a[0])
            return mock_result
        with patch("ingress_manager.subprocess.run", side_effect=capture):
            mgr.deploy(chart_version="4.10.0")
        helm_call = next((c for c in calls if "helm" in c[0] and "upgrade" in c), None)
        assert helm_call is not None
        assert "--version" in helm_call
        assert "4.10.0" in helm_call


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

class TestCLI:
    def test_list_empty(self, tmpdir_state):
        from ingress_manager import main
        rc = main(["--state-dir", tmpdir_state, "list"])
        assert rc == 0

    def test_register_and_list(self, tmpdir_state):
        from ingress_manager import main
        main([
            "--state-dir", tmpdir_state,
            "register",
            "--name", "app",
            "--namespace", "default",
            "--service", "app-svc",
            "--port", "8080",
            "--hostname", "app.example.com",
        ])
        rc = main(["--state-dir", tmpdir_state, "list"])
        assert rc == 0
