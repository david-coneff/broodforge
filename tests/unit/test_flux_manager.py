"""Unit tests for flux_manager.py — Phase 2.G."""
import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from flux_manager import FluxManager, FluxState, GitSource, Kustomization

FIXED_TS = datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)
def _now():
    return FIXED_TS

@pytest.fixture
def td():
    with tempfile.TemporaryDirectory() as d:
        yield d

@pytest.fixture
def mgr(td):
    return FluxManager(state_dir=td, now_fn=_now)


class TestGitSource:
    def test_roundtrip(self):
        s = GitSource(name="infra", namespace="flux-system",
                      url="https://github.com/dave/infra", branch="main")
        assert GitSource.from_dict(s.to_dict()) == s

    def test_defaults(self):
        s = GitSource(name="x", namespace="ns", url="https://git/r")
        assert s.branch == "main"
        assert s.interval == "1m"
        assert s.secret_ref == ""


class TestKustomization:
    def test_roundtrip(self):
        k = Kustomization(name="apps", namespace="flux-system",
                          source_ref="infra", source_namespace="flux-system",
                          path="./clusters/home", prune=True)
        assert Kustomization.from_dict(k.to_dict()) == k

    def test_defaults(self):
        k = Kustomization(name="k", namespace="ns", source_ref="s",
                          source_namespace="ns", path="./path")
        assert k.interval == "10m"
        assert k.prune is True
        assert k.depends_on == []


class TestFluxState:
    def test_empty_roundtrip(self):
        s = FluxState()
        s2 = FluxState.from_dict(s.to_dict())
        assert s2.deployment.installed is False
        assert s2.sources == []
        assert s2.kustomizations == []

    def test_roundtrip_with_content(self):
        s = FluxState()
        s.sources.append(GitSource(name="infra", namespace="flux-system",
                                    url="https://git/r", branch="main"))
        s2 = FluxState.from_dict(s.to_dict())
        assert len(s2.sources) == 1
        assert s2.sources[0].url == "https://git/r"


class TestFluxManagerIO:
    def test_load_missing_returns_empty(self, mgr):
        s = mgr.load()
        assert s.deployment.installed is False
        assert s.sources == []

    def test_save_and_load(self, mgr):
        s = mgr.load()
        s.deployment.installed = True
        s.deployment.version = "v2.3.0"
        mgr.save(s)
        loaded = mgr.load()
        assert loaded.deployment.installed is True
        assert loaded.deployment.version == "v2.3.0"

    def test_atomic_write(self, mgr):
        mgr.save(FluxState())
        assert os.path.exists(os.path.join(mgr._state_dir, "flux-state.json"))
        assert not os.path.exists(os.path.join(mgr._state_dir, "flux-state.json.tmp"))


class TestSourceRegistry:
    def test_register_new_source(self, mgr):
        src = mgr.register_source("infra", "flux-system", "https://git/r")
        assert src.name == "infra"
        assert src.registered_at == "2026-06-10T12:00:00Z"
        assert len(mgr.load().sources) == 1

    def test_register_updates_existing(self, mgr):
        mgr.register_source("infra", "flux-system", "https://git/old")
        mgr.register_source("infra", "flux-system", "https://git/new")
        sources = mgr.load().sources
        assert len(sources) == 1
        assert sources[0].url == "https://git/new"

    def test_register_dry_run_no_persist(self, mgr):
        mgr.register_source("infra", "ns", "https://git/r", dry_run=True)
        assert mgr.load().sources == []

    def test_register_with_secret_ref(self, mgr):
        mgr.register_source("infra", "ns", "https://git/r", secret_ref="forgejo-creds")
        assert mgr.load().sources[0].secret_ref == "forgejo-creds"


class TestKustomizationRegistry:
    def test_register_kustomization(self, mgr):
        ks = mgr.register_kustomization("apps", "flux-system", "infra", "flux-system", "./apps")
        assert ks.name == "apps"
        assert ks.registered_at == "2026-06-10T12:00:00Z"
        assert len(mgr.load().kustomizations) == 1

    def test_register_updates_existing(self, mgr):
        mgr.register_kustomization("apps", "flux-system", "infra", "flux-system", "./apps/v1")
        mgr.register_kustomization("apps", "flux-system", "infra", "flux-system", "./apps/v2")
        ks = mgr.load().kustomizations
        assert len(ks) == 1
        assert ks[0].path == "./apps/v2"

    def test_register_with_depends_on(self, mgr):
        mgr.register_kustomization("apps", "ns", "infra", "ns", "./apps", depends_on=["infra"])
        assert mgr.load().kustomizations[0].depends_on == ["infra"]

    def test_register_dry_run(self, mgr):
        mgr.register_kustomization("apps", "ns", "infra", "ns", "./apps", dry_run=True)
        assert mgr.load().kustomizations == []


class TestManifestGeneration:
    def test_git_repository_manifest(self, mgr):
        src = GitSource(name="infra", namespace="flux-system",
                        url="https://github.com/dave/infra", branch="main", interval="5m")
        m = mgr.generate_git_repository_manifest(src)
        assert m["kind"] == "GitRepository"
        assert m["apiVersion"] == "source.toolkit.fluxcd.io/v1"
        assert m["spec"]["url"] == "https://github.com/dave/infra"
        assert m["spec"]["ref"]["branch"] == "main"
        assert m["spec"]["interval"] == "5m"

    def test_git_repository_with_secret(self, mgr):
        src = GitSource(name="infra", namespace="ns", url="https://git/r",
                        branch="main", secret_ref="my-secret")
        m = mgr.generate_git_repository_manifest(src)
        assert m["spec"]["secretRef"]["name"] == "my-secret"

    def test_git_repository_no_secret(self, mgr):
        src = GitSource(name="infra", namespace="ns", url="https://git/r", branch="main")
        m = mgr.generate_git_repository_manifest(src)
        assert "secretRef" not in m["spec"]

    def test_kustomization_manifest(self, mgr):
        ks = Kustomization(name="apps", namespace="flux-system",
                           source_ref="infra", source_namespace="flux-system",
                           path="./clusters/home", interval="5m", prune=True)
        m = mgr.generate_kustomization_manifest(ks)
        assert m["kind"] == "Kustomization"
        assert m["apiVersion"] == "kustomize.toolkit.fluxcd.io/v1"
        assert m["spec"]["path"] == "./clusters/home"
        assert m["spec"]["prune"] is True
        assert m["spec"]["sourceRef"]["name"] == "infra"

    def test_kustomization_depends_on(self, mgr):
        ks = Kustomization(name="apps", namespace="ns", source_ref="s",
                           source_namespace="ns", path="./x", depends_on=["infra"])
        m = mgr.generate_kustomization_manifest(ks)
        assert m["spec"]["dependsOn"] == [{"name": "infra"}]

    def test_kustomization_no_depends_on(self, mgr):
        ks = Kustomization(name="apps", namespace="ns", source_ref="s",
                           source_namespace="ns", path="./x")
        m = mgr.generate_kustomization_manifest(ks)
        assert "dependsOn" not in m["spec"]


class TestBootstrapGit:
    def test_records_state_on_success(self, mgr):
        mock_r = MagicMock(returncode=0)
        with patch("flux_manager.subprocess.run", return_value=mock_r):
            rc = mgr.bootstrap_git("https://forgejo.home/dave/infra", "./clusters/home")
        assert rc == 0
        assert mgr.load().deployment.installed is True
        assert mgr.load().deployment.installed_at == "2026-06-10T12:00:00Z"

    def test_no_state_on_failure(self, mgr):
        with patch("flux_manager.subprocess.run", return_value=MagicMock(returncode=1, stderr="")):
            mgr.bootstrap_git("https://git/r", "./path")
        assert mgr.load().deployment.installed is False

    def test_dry_run_no_state_change(self, mgr):
        with patch("flux_manager.subprocess.run", return_value=MagicMock(returncode=0)):
            mgr.bootstrap_git("https://git/r", "./path", dry_run=True)
        assert mgr.load().deployment.installed is False


class TestReconcile:
    def test_reconcile_calls_flux(self, mgr):
        calls = []
        def capture(*a, **kw):
            calls.append(list(a[0]))
            return MagicMock(returncode=0, stdout="OK", stderr="")
        with patch("flux_manager.subprocess.run", side_effect=capture):
            rc, _ = mgr.reconcile("source", "infra", "flux-system")
        assert rc == 0
        assert any("reconcile" in c for c in calls)


class TestCLI:
    def test_list_empty(self, td):
        from flux_manager import main
        assert main(["--state-dir", td, "list"]) == 0

    def test_register_source_cli(self, td):
        from flux_manager import main
        rc = main(["--state-dir", td, "register-source",
                   "--name", "infra", "--namespace", "flux-system",
                   "--url", "https://git/r"])
        assert rc == 0

    def test_register_kustomization_cli(self, td):
        from flux_manager import main
        rc = main(["--state-dir", td, "register-kustomization",
                   "--name", "apps", "--namespace", "flux-system",
                   "--source-ref", "infra", "--source-namespace", "flux-system",
                   "--path", "./apps"])
        assert rc == 0
