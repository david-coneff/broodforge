"""Unit tests for linkerd_manager.py — Phase 2.I."""
import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from linkerd_manager import LinkerdDeployment, LinkerdManager, LinkerdState, MeshedNamespace

FIXED_TS = datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)
def _now():
    return FIXED_TS

@pytest.fixture
def td():
    with tempfile.TemporaryDirectory() as d:
        yield d

@pytest.fixture
def mgr(td):
    return LinkerdManager(state_dir=td, now_fn=_now)


class TestMeshedNamespace:
    def test_roundtrip(self):
        n = MeshedNamespace(namespace="apps", injected=True, mtls_enforced=True,
                            enrolled_at="2026-06-10T12:00:00Z")
        assert MeshedNamespace.from_dict(n.to_dict()) == n

    def test_defaults(self):
        n = MeshedNamespace(namespace="ns")
        assert n.injected is True
        assert n.mtls_enforced is True
        assert n.enrolled_at == ""


class TestLinkerdDeployment:
    def test_roundtrip(self):
        d = LinkerdDeployment(installed=True, version="stable-2.14.0", ha_mode=False,
                              viz_installed=True, crds_installed=True)
        assert LinkerdDeployment.from_dict(d.to_dict()) == d

    def test_defaults(self):
        d = LinkerdDeployment()
        assert d.installed is False
        assert d.ha_mode is False
        assert d.viz_installed is False


class TestLinkerdState:
    def test_empty_roundtrip(self):
        s = LinkerdState()
        s2 = LinkerdState.from_dict(s.to_dict())
        assert s2.deployment.installed is False
        assert s2.meshed_namespaces == []

    def test_roundtrip_with_namespace(self):
        s = LinkerdState()
        s.meshed_namespaces.append(MeshedNamespace(namespace="apps"))
        s2 = LinkerdState.from_dict(s.to_dict())
        assert len(s2.meshed_namespaces) == 1
        assert s2.meshed_namespaces[0].namespace == "apps"


class TestLinkerdManagerIO:
    def test_load_missing_returns_empty(self, mgr):
        s = mgr.load()
        assert s.deployment.installed is False
        assert s.meshed_namespaces == []

    def test_save_and_load(self, mgr):
        s = mgr.load()
        s.deployment.installed = True
        s.deployment.version = "stable-2.14.0"
        mgr.save(s)
        loaded = mgr.load()
        assert loaded.deployment.installed is True
        assert loaded.deployment.version == "stable-2.14.0"

    def test_atomic_write(self, mgr):
        mgr.save(LinkerdState())
        assert os.path.exists(os.path.join(mgr._state_dir, "linkerd-state.json"))
        assert not os.path.exists(os.path.join(mgr._state_dir, "linkerd-state.json.tmp"))


class TestInstall:
    def test_install_records_state_on_success(self, mgr):
        with patch("linkerd_manager.subprocess.run", return_value=MagicMock(returncode=0, stdout="stable-2.14.0\n", stderr="")):
            rc = mgr.install()
        assert rc == 0
        state = mgr.load()
        assert state.deployment.installed is True
        assert state.deployment.installed_at == "2026-06-10T12:00:00Z"

    def test_install_ha_sets_ha_flag(self, mgr):
        with patch("linkerd_manager.subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")):
            mgr.install(ha_mode=True)
        assert mgr.load().deployment.ha_mode is True

    def test_install_failure_no_state_change(self, mgr):
        with patch("linkerd_manager.subprocess.run", return_value=MagicMock(returncode=1, stdout="", stderr="err")):
            rc = mgr.install()
        assert rc == 1
        assert mgr.load().deployment.installed is False

    def test_install_dry_run_returns_0_no_state(self, mgr):
        rc = mgr.install(dry_run=True)
        assert rc == 0
        assert mgr.load().deployment.installed is False

    def test_install_crds_sets_flag(self, mgr):
        with patch("linkerd_manager.subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")):
            rc = mgr.install_crds()
        assert rc == 0
        assert mgr.load().deployment.crds_installed is True

    def test_install_crds_dry_run(self, mgr):
        # dry_run uses subprocess.run to inspect manifest but does not apply
        with patch("linkerd_manager.subprocess.run", return_value=MagicMock(returncode=0, stdout="kind: CustomResourceDefinition\n", stderr="")):
            rc = mgr.install_crds(dry_run=True)
        assert rc == 0
        assert mgr.load().deployment.crds_installed is False

    def test_install_viz_sets_flag(self, mgr):
        with patch("linkerd_manager.subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")):
            rc = mgr.install_viz()
        assert rc == 0
        assert mgr.load().deployment.viz_installed is True


class TestNamespaceEnrollment:
    def test_enroll_namespace(self, mgr):
        with patch("linkerd_manager.subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")):
            ns = mgr.enroll_namespace("apps")
        assert ns.namespace == "apps"
        assert ns.enrolled_at == "2026-06-10T12:00:00Z"
        assert len(mgr.load().meshed_namespaces) == 1

    def test_enroll_updates_existing(self, mgr):
        with patch("linkerd_manager.subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")):
            mgr.enroll_namespace("apps", inject=True, enforce_mtls=True)
            mgr.enroll_namespace("apps", inject=False, enforce_mtls=False)
        ns_list = mgr.load().meshed_namespaces
        assert len(ns_list) == 1
        assert ns_list[0].injected is False
        assert ns_list[0].mtls_enforced is False

    def test_enroll_dry_run_no_persist(self, mgr):
        ns = mgr.enroll_namespace("apps", dry_run=True)
        assert ns.namespace == "apps"
        assert mgr.load().meshed_namespaces == []

    def test_enroll_calls_kubectl_annotate(self, mgr):
        calls = []
        def capture(*a, **kw):
            calls.append(list(a[0]) if a else [])
            return MagicMock(returncode=0, stdout="", stderr="")
        with patch("linkerd_manager.subprocess.run", side_effect=capture):
            mgr.enroll_namespace("apps", inject=True, enforce_mtls=False)
        annotate_call = next((c for c in calls if "annotate" in c), None)
        assert annotate_call is not None
        assert "linkerd.io/inject=enabled" in annotate_call

    def test_disenroll_removes_namespace(self, mgr):
        with patch("linkerd_manager.subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")):
            mgr.enroll_namespace("apps")
            removed = mgr.disenroll_namespace("apps")
        assert removed is True
        assert mgr.load().meshed_namespaces == []

    def test_disenroll_missing_returns_false(self, mgr):
        with patch("linkerd_manager.subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")):
            removed = mgr.disenroll_namespace("nonexistent")
        assert removed is False

    def test_list_meshed(self, mgr):
        with patch("linkerd_manager.subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")):
            mgr.enroll_namespace("apps")
            mgr.enroll_namespace("monitoring", enforce_mtls=False)
        ns_list = mgr.list_meshed()
        assert len(ns_list) == 2
        names = {n.namespace for n in ns_list}
        assert names == {"apps", "monitoring"}


class TestHealthCheck:
    def test_check_pre_ok(self, mgr):
        with patch("linkerd_manager.subprocess.run",
                   return_value=MagicMock(returncode=0, stdout="Status check results are √\n", stderr="")):
            ok, out = mgr.check()
        assert ok is True
        assert "√" in out

    def test_check_pre_fail(self, mgr):
        with patch("linkerd_manager.subprocess.run",
                   return_value=MagicMock(returncode=1, stdout="× failed\n", stderr="")):
            ok, _ = mgr.check()
        assert ok is False

    def test_check_health(self, mgr):
        with patch("linkerd_manager.subprocess.run",
                   return_value=MagicMock(returncode=0, stdout="all checks passed\n", stderr="")):
            ok, out = mgr.check_health()
        assert ok is True


class TestCLI:
    def test_list_empty(self, td):
        from linkerd_manager import main
        assert main(["--state-dir", td, "list"]) == 0

    def test_enroll_dry_run(self, td):
        from linkerd_manager import main
        rc = main(["--state-dir", td, "enroll", "--namespace", "apps", "--dry-run"])
        assert rc == 0

    def test_disenroll_not_found(self, td):
        from linkerd_manager import main
        with patch("linkerd_manager.subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")):
            rc = main(["--state-dir", td, "disenroll", "--namespace", "nothere"])
        assert rc == 0  # returns 0, prints "not found"
