"""Unit tests for kyverno_manager.py — Phase 2.J."""
import json
import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from kyverno_manager import (
    KyvernoDeployment,
    KyvernoManager,
    KyvernoState,
    PolicyRecord,
)

FIXED_TS = datetime(2026, 6, 11, 12, 0, 0, tzinfo=timezone.utc)
def _now():
    return FIXED_TS


@pytest.fixture
def td():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def mgr(td):
    return KyvernoManager(state_dir=td, now_fn=_now)


# ---------------------------------------------------------------------------
# Data-model round-trips
# ---------------------------------------------------------------------------

class TestPolicyRecord:
    def test_roundtrip_full(self):
        p = PolicyRecord(
            name="disallow-latest-tag",
            kind="ClusterPolicy",
            category="best-practices",
            action="Enforce",
            rules_count=2,
            registered_at="2026-06-11T12:00:00+00:00",
            manifest_path="/etc/policies/disallow-latest-tag.yaml",
        )
        assert PolicyRecord.from_dict(p.to_dict()) == p

    def test_roundtrip_defaults(self):
        p = PolicyRecord(name="my-policy")
        p2 = PolicyRecord.from_dict(p.to_dict())
        assert p2.kind == "ClusterPolicy"
        assert p2.action == "Audit"
        assert p2.rules_count == 0
        assert p2.namespace == ""

    def test_namespaced_policy(self):
        p = PolicyRecord(name="ns-policy", kind="Policy", namespace="apps")
        assert PolicyRecord.from_dict(p.to_dict()).namespace == "apps"


class TestKyvernoDeployment:
    def test_roundtrip(self):
        d = KyvernoDeployment(
            installed=True,
            chart_version="kyverno-3.1.4",
            namespace="kyverno",
            replica_count=3,
            installed_at="2026-06-11T12:00:00+00:00",
        )
        assert KyvernoDeployment.from_dict(d.to_dict()) == d

    def test_defaults(self):
        d = KyvernoDeployment()
        assert d.installed is False
        assert d.namespace == "kyverno"
        assert d.replica_count == 1


class TestKyvernoState:
    def test_empty_roundtrip(self):
        s = KyvernoState()
        s2 = KyvernoState.from_dict(s.to_dict())
        assert s2.deployment.installed is False
        assert s2.policies == []

    def test_with_policy(self):
        s = KyvernoState()
        s.policies.append(PolicyRecord(name="test", action="Enforce"))
        s2 = KyvernoState.from_dict(s.to_dict())
        assert len(s2.policies) == 1
        assert s2.policies[0].action == "Enforce"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_load_missing_file(self, mgr):
        state = mgr.load()
        assert isinstance(state, KyvernoState)
        assert not state.deployment.installed

    def test_save_and_reload(self, mgr):
        state = KyvernoState(
            deployment=KyvernoDeployment(installed=True, chart_version="kyverno-3.1.0"),
        )
        state.policies.append(PolicyRecord(name="test-policy", action="Audit"))
        mgr.save(state)
        reloaded = mgr.load()
        assert reloaded.deployment.installed is True
        assert reloaded.deployment.chart_version == "kyverno-3.1.0"
        assert len(reloaded.policies) == 1

    def test_atomic_write(self, td, mgr):
        """Tmp file should not persist after save."""
        mgr.save(KyvernoState())
        tmp = os.path.join(td, "kyverno-state.json.tmp")
        assert not os.path.exists(tmp)

    def test_state_file_name(self, td, mgr):
        mgr.save(KyvernoState())
        assert os.path.exists(os.path.join(td, "kyverno-state.json"))


# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------

class TestInstall:
    @patch("kyverno_manager.subprocess.run")
    def test_install_calls_helm(self, mock_run, mgr):
        mock_run.return_value = MagicMock(returncode=0, stdout="[]")
        mgr.install(replica_count=1)
        calls = [str(c) for c in mock_run.call_args_list]
        assert any("repo" in c and "add" in c for c in calls)
        assert any("upgrade" in c and "install" in c for c in calls)

    @patch("kyverno_manager.subprocess.run")
    def test_install_sets_deployed_true(self, mock_run, mgr):
        mock_run.return_value = MagicMock(returncode=0, stdout="[]")
        state = mgr.install()
        assert state.deployment.installed is True

    @patch("kyverno_manager.subprocess.run")
    def test_install_records_timestamp(self, mock_run, mgr):
        mock_run.return_value = MagicMock(returncode=0, stdout="[]")
        state = mgr.install()
        assert state.deployment.installed_at == FIXED_TS.isoformat()

    @patch("kyverno_manager.subprocess.run")
    def test_install_with_chart_version(self, mock_run, mgr):
        mock_run.return_value = MagicMock(returncode=0, stdout="[]")
        state = mgr.install(chart_version="3.1.4")
        assert state.deployment.chart_version == "3.1.4"

    @patch("kyverno_manager.subprocess.run")
    def test_install_replicas_param(self, mock_run, mgr):
        mock_run.return_value = MagicMock(returncode=0, stdout="[]")
        mgr.install(replica_count=3)
        upgrade_call = [
            c for c in mock_run.call_args_list
            if "upgrade" in str(c)
        ]
        assert any("replicaCount=3" in str(c) for c in upgrade_call)

    @patch("kyverno_manager.subprocess.run")
    def test_install_custom_namespace(self, mock_run, mgr):
        mock_run.return_value = MagicMock(returncode=0, stdout="[]")
        state = mgr.install(namespace="policy-system")
        assert state.deployment.namespace == "policy-system"

    @patch("kyverno_manager.subprocess.run")
    def test_install_persists_state(self, mock_run, mgr, td):
        mock_run.return_value = MagicMock(returncode=0, stdout="[]")
        mgr.install()
        assert os.path.exists(os.path.join(td, "kyverno-state.json"))


# ---------------------------------------------------------------------------
# uninstall
# ---------------------------------------------------------------------------

class TestUninstall:
    @patch("kyverno_manager.subprocess.run")
    def test_uninstall_clears_deployment(self, mock_run, mgr):
        mock_run.return_value = MagicMock(returncode=0, stdout="[]")
        # pre-populate
        state = KyvernoState(deployment=KyvernoDeployment(installed=True))
        mgr.save(state)
        result = mgr.uninstall()
        assert result.deployment.installed is False

    @patch("kyverno_manager.subprocess.run")
    def test_uninstall_calls_helm(self, mock_run, mgr):
        mock_run.return_value = MagicMock(returncode=0)
        mgr.save(KyvernoState(deployment=KyvernoDeployment(installed=True)))
        mgr.uninstall()
        assert any("uninstall" in str(c) for c in mock_run.call_args_list)


# ---------------------------------------------------------------------------
# register_policy
# ---------------------------------------------------------------------------

class TestRegisterPolicy:
    @patch("kyverno_manager.subprocess.run")
    def test_register_policy_apply(self, mock_run, mgr, tmp_path):
        manifest = tmp_path / "policy.yaml"
        manifest.write_text("kind: ClusterPolicy\n")
        mock_run.return_value = MagicMock(returncode=0)
        rec = mgr.register_policy(
            name="disallow-latest",
            manifest_path=str(manifest),
            action="Enforce",
            rules_count=1,
        )
        assert rec.name == "disallow-latest"
        assert rec.action == "Enforce"
        assert rec.rules_count == 1
        assert rec.registered_at == FIXED_TS.isoformat()

    @patch("kyverno_manager.subprocess.run")
    def test_register_policy_no_apply(self, mock_run, mgr, tmp_path):
        manifest = tmp_path / "policy.yaml"
        manifest.write_text("kind: ClusterPolicy\n")
        mgr.register_policy(
            name="audit-only",
            manifest_path=str(manifest),
            apply=False,
        )
        mock_run.assert_not_called()

    @patch("kyverno_manager.subprocess.run")
    def test_register_policy_persists(self, mock_run, mgr, tmp_path):
        manifest = tmp_path / "policy.yaml"
        manifest.write_text("kind: ClusterPolicy\n")
        mock_run.return_value = MagicMock(returncode=0)
        mgr.register_policy(name="test", manifest_path=str(manifest))
        assert len(mgr.list_policies()) == 1

    @patch("kyverno_manager.subprocess.run")
    def test_register_policy_upsert(self, mock_run, mgr, tmp_path):
        """Re-registering same name+kind replaces the record."""
        manifest = tmp_path / "policy.yaml"
        manifest.write_text("kind: ClusterPolicy\n")
        mock_run.return_value = MagicMock(returncode=0)
        mgr.register_policy(name="pol", manifest_path=str(manifest), action="Audit")
        mgr.register_policy(name="pol", manifest_path=str(manifest), action="Enforce")
        policies = mgr.list_policies()
        assert len(policies) == 1
        assert policies[0].action == "Enforce"

    @patch("kyverno_manager.subprocess.run")
    def test_register_multiple_policies(self, mock_run, mgr, tmp_path):
        mock_run.return_value = MagicMock(returncode=0)
        for name in ("pol-a", "pol-b", "pol-c"):
            m = tmp_path / f"{name}.yaml"
            m.write_text("kind: ClusterPolicy\n")
            mgr.register_policy(name=name, manifest_path=str(m))
        assert len(mgr.list_policies()) == 3


# ---------------------------------------------------------------------------
# remove_policy
# ---------------------------------------------------------------------------

class TestRemovePolicy:
    @patch("kyverno_manager.subprocess.run")
    def test_remove_policy(self, mock_run, mgr, tmp_path):
        mock_run.return_value = MagicMock(returncode=0)
        manifest = tmp_path / "policy.yaml"
        manifest.write_text("kind: ClusterPolicy\n")
        mgr.register_policy(name="to-remove", manifest_path=str(manifest), apply=False)
        mgr.remove_policy(name="to-remove")
        assert len(mgr.list_policies()) == 0

    @patch("kyverno_manager.subprocess.run")
    def test_remove_nonexistent(self, mock_run, mgr):
        mock_run.return_value = MagicMock(returncode=0)
        # should not raise
        mgr.remove_policy(name="does-not-exist")

    @patch("kyverno_manager.subprocess.run")
    def test_remove_calls_kubectl_delete(self, mock_run, mgr, tmp_path):
        mock_run.return_value = MagicMock(returncode=0)
        manifest = tmp_path / "policy.yaml"
        manifest.write_text("kind: ClusterPolicy\n")
        mgr.register_policy(name="del-me", manifest_path=str(manifest), apply=False)
        mgr.remove_policy(name="del-me")
        assert any("delete" in str(c) for c in mock_run.call_args_list)


# ---------------------------------------------------------------------------
# list / get
# ---------------------------------------------------------------------------

class TestListGet:
    def test_list_empty(self, mgr):
        assert mgr.list_policies() == []

    @patch("kyverno_manager.subprocess.run")
    def test_get_policy(self, mock_run, mgr, tmp_path):
        mock_run.return_value = MagicMock(returncode=0)
        manifest = tmp_path / "p.yaml"
        manifest.write_text("kind: ClusterPolicy\n")
        mgr.register_policy(name="target", manifest_path=str(manifest), apply=False)
        p = mgr.get_policy("target")
        assert p is not None
        assert p.name == "target"

    def test_get_missing_returns_none(self, mgr):
        assert mgr.get_policy("nope") is None


# ---------------------------------------------------------------------------
# health / live count
# ---------------------------------------------------------------------------

class TestHealth:
    @patch("kyverno_manager.subprocess.run")
    def test_check_health_ok(self, mock_run, mgr):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="deployment rolled out", stderr=""
        )
        result = mgr.check_health()
        assert result["ok"] is True

    @patch("kyverno_manager.subprocess.run")
    def test_check_health_degraded(self, mock_run, mgr):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="error: not found"
        )
        result = mgr.check_health()
        assert result["ok"] is False

    @patch("kyverno_manager.subprocess.run")
    def test_get_live_policy_count(self, mock_run, mgr):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"items": [{}, {}, {}]}),
        )
        result = mgr.get_live_policy_count()
        assert result["cluster_policies"] == 3

    @patch("kyverno_manager.subprocess.run")
    def test_get_live_policy_count_invalid_json(self, mock_run, mgr):
        mock_run.return_value = MagicMock(returncode=1, stdout="not-json")
        result = mgr.get_live_policy_count()
        assert result["cluster_policies"] == 0


# ---------------------------------------------------------------------------
# Subprocess timeout enforcement
# ---------------------------------------------------------------------------

class TestSubprocessTimeouts:
    @patch("kyverno_manager.subprocess.run")
    def test_install_has_timeout(self, mock_run, mgr):
        mock_run.return_value = MagicMock(returncode=0, stdout="[]")
        mgr.install()
        for c in mock_run.call_args_list:
            assert c.kwargs.get("timeout") is not None or (
                len(c.args) > 1 and "timeout" in str(c)
            ), f"subprocess.run call missing timeout: {c}"

    @patch("kyverno_manager.subprocess.run")
    def test_register_policy_has_timeout(self, mock_run, mgr, tmp_path):
        mock_run.return_value = MagicMock(returncode=0)
        manifest = tmp_path / "p.yaml"
        manifest.write_text("kind: ClusterPolicy\n")
        mgr.register_policy(name="t", manifest_path=str(manifest))
        for c in mock_run.call_args_list:
            assert c.kwargs.get("timeout") is not None, \
                f"subprocess.run call missing timeout: {c}"
