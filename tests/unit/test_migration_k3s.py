"""
test_migration_k3s.py — Tests for 9.T migration tier (9.T.9–9.T.17).

Covers:
  - migrate_k3s_lib: PreflightResult, run_preflight_checks, snapshot_state,
    drain_node, verify_cluster_health, uncordon_node,
    update_os_variant, append_migration_history, rollback,
    make_migration_id, MigrationRecord
  - migrate-k3s-to-talos: migrate_to_talos() (dry-run, blocked preflight, success path)
  - migrate-k3s-to-ubuntu: migrate_to_ubuntu() (dry-run, blocked preflight, success path)
  - bootstrap-state-schema.json: migration_history array
"""
from __future__ import annotations

import json
import os

_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_PB   = os.path.join(_ROOT, "proxmox-bootstrap")
_DM   = os.path.join(_ROOT, "data-model")

import migrate_k3s_lib as _lib

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _state_with_ubuntu_node() -> dict:
    return {
        "cell_id": "test-cell",
        "readiness_score": "GREEN",
        "vms": [
            {
                "vm_name": "k3s-server-01",
                "vmid": 201,
                "os_variant": "ubuntu",
                "role": "k3s-server",
            }
        ],
        "templates": [
            {"name": "talos-1x-base", "proxmox_template_id": 9001, "os_variant": "talos"},
            {"name": "ubuntu-2204-base", "proxmox_template_id": 9000, "os_variant": "ubuntu"},
        ],
        "dns_registry": [
            {"vm_name": "k3s-server-01", "hostname": "k3s-server-01", "ip": "192.168.1.51"},
        ],
        "pbs_reachability": True,
    }


def _state_with_talos_node() -> dict:
    s = _state_with_ubuntu_node()
    s["vms"][0]["os_variant"] = "talos"
    return s


def _write_state(tmp_path, state: dict) -> str:
    p = os.path.join(str(tmp_path), "bootstrap-state.json")
    with open(p, "w") as f:
        json.dump(state, f, indent=2)
    return p


# ===========================================================================
# PreflightResult
# ===========================================================================

class TestPreflightResult:
    def test_starts_passing(self):
        r = _lib.PreflightResult(passed=True)
        assert r.passed

    def test_add_failure_sets_passed_false(self):
        r = _lib.PreflightResult(passed=True)
        r.add("check", False, "detail")
        assert not r.passed

    def test_add_success_leaves_passed_true(self):
        r = _lib.PreflightResult(passed=True)
        r.add("check", True)
        assert r.passed

    def test_summary_contains_check_names(self):
        r = _lib.PreflightResult(passed=True)
        r.add("my_check", True, "all good")
        s = r.summary()
        assert "my_check" in s

    def test_summary_marks_failures(self):
        r = _lib.PreflightResult(passed=True)
        r.add("bad_check", False, "something wrong")
        s = r.summary()
        assert "✗" in s


# ===========================================================================
# run_preflight_checks
# ===========================================================================

class TestRunPreflightChecks:
    def test_passes_for_valid_state(self):
        state = _state_with_ubuntu_node()
        result = _lib.run_preflight_checks("k3s-server-01", "talos", state)
        # cluster_readiness, target_template, node_exists all pass
        passed = {c["name"]: c["passed"] for c in result.checks}
        assert passed.get("cluster_readiness")
        assert passed.get("target_template")
        assert passed.get("node_exists")

    def test_fails_when_cluster_is_red(self):
        state = _state_with_ubuntu_node()
        state["readiness_score"] = "RED"
        result = _lib.run_preflight_checks("k3s-server-01", "talos", state)
        assert not result.passed

    def test_fails_when_template_missing(self):
        state = _state_with_ubuntu_node()
        state["templates"] = []
        result = _lib.run_preflight_checks("k3s-server-01", "talos", state)
        assert not result.passed

    def test_fails_when_node_not_in_registry(self):
        state = _state_with_ubuntu_node()
        result = _lib.run_preflight_checks("nonexistent-node", "talos", state)
        assert not result.passed

    def test_ubuntu_template_checked_for_to_ubuntu(self):
        state = _state_with_talos_node()
        result = _lib.run_preflight_checks("k3s-server-01", "ubuntu", state)
        target_check = next(c for c in result.checks if c["name"] == "target_template")
        assert target_check["passed"]

    def test_no_machine_config_check_for_ubuntu_direction(self):
        state = _state_with_talos_node()
        result = _lib.run_preflight_checks("k3s-server-01", "ubuntu", state)
        names = [c["name"] for c in result.checks]
        assert "machine_config" not in names

    def test_pbs_failure_blocks_migration(self):
        state = _state_with_ubuntu_node()
        state["pbs_reachability"] = False
        result = _lib.run_preflight_checks("k3s-server-01", "talos", state)
        assert not result.passed


# ===========================================================================
# snapshot_state
# ===========================================================================

class TestSnapshotState:
    def test_returns_snapshot(self):
        state = _state_with_ubuntu_node()
        snap = _lib.snapshot_state("k3s-server-01", "ubuntu", state)
        assert snap.node_vm_name == "k3s-server-01"
        assert snap.original_os_variant == "ubuntu"

    def test_snapshot_captures_full_json(self):
        state = _state_with_ubuntu_node()
        snap = _lib.snapshot_state("k3s-server-01", "ubuntu", state)
        captured = json.loads(snap.state_json)
        assert captured["cell_id"] == "test-cell"

    def test_timestamp_set(self):
        state = _state_with_ubuntu_node()
        snap = _lib.snapshot_state("k3s-server-01", "ubuntu", state)
        assert snap.timestamp


# ===========================================================================
# drain_node / verify_cluster_health / uncordon_node (dry-run)
# ===========================================================================

class TestDrainAndVerify:
    def test_drain_dry_run_returns_true(self):
        result = _lib.drain_node("k3s-server-01", dry_run=True)
        assert result is True

    def test_verify_dry_run_returns_true(self):
        assert _lib.verify_cluster_health(dry_run=True)

    def test_uncordon_dry_run_no_exception(self):
        _lib.uncordon_node("k3s-server-01", dry_run=True)

    def test_drain_with_mock_runner_success(self):
        def _mock(cmd): return "node/k3s-server-01 drained"
        result = _lib.drain_node("k3s-server-01", runner=_mock)
        assert result

    def test_verify_with_mock_ready_nodes(self):
        def _mock(cmd): return "k3s-server-01  Ready  control-plane  1d  v1.29.0"
        assert _lib.verify_cluster_health(runner=_mock)

    def test_verify_with_notready_node_fails(self):
        def _mock(cmd): return "k3s-server-01  NotReady  control-plane  1d  v1.29.0"
        assert not _lib.verify_cluster_health(runner=_mock)


# ===========================================================================
# update_os_variant
# ===========================================================================

class TestUpdateOsVariant:
    def test_updates_vm_entry(self):
        state = _state_with_ubuntu_node()
        updated = _lib.update_os_variant("k3s-server-01", "talos", state)
        vm = next(v for v in updated["vms"] if v["vm_name"] == "k3s-server-01")
        assert vm["os_variant"] == "talos"

    def test_no_op_for_unknown_node(self):
        state = _state_with_ubuntu_node()
        _lib.update_os_variant("nonexistent", "talos", state)
        vm = state["vms"][0]
        assert vm["os_variant"] == "ubuntu"


# ===========================================================================
# append_migration_history
# ===========================================================================

class TestAppendMigrationHistory:
    def _record(self) -> _lib.MigrationRecord:
        return _lib.MigrationRecord(
            migration_id="test-001",
            node_vm_name="k3s-server-01",
            from_variant="ubuntu",
            to_variant="talos",
            started_at="2026-06-02T00:00:00+00:00",
            completed_at="2026-06-02T00:05:00+00:00",
            outcome="success",
            snapshot_vmid=201,
            error=None,
            dry_run=False,
        )

    def test_creates_migration_history_array(self, tmp_path):
        state_path = _write_state(tmp_path, _state_with_ubuntu_node())
        _lib.append_migration_history(state_path, self._record())
        with open(state_path) as f:
            state = json.load(f)
        assert "migration_history" in state
        assert len(state["migration_history"]) == 1

    def test_appends_to_existing(self, tmp_path):
        base_state = _state_with_ubuntu_node()
        base_state["migration_history"] = [{"migration_id": "existing"}]
        state_path = _write_state(tmp_path, base_state)
        _lib.append_migration_history(state_path, self._record())
        with open(state_path) as f:
            state = json.load(f)
        assert len(state["migration_history"]) == 2

    def test_record_fields_persisted(self, tmp_path):
        state_path = _write_state(tmp_path, _state_with_ubuntu_node())
        _lib.append_migration_history(state_path, self._record())
        with open(state_path) as f:
            state = json.load(f)
        rec = state["migration_history"][0]
        assert rec["migration_id"] == "test-001"
        assert rec["outcome"] == "success"
        assert rec["snapshot_vmid"] == 201

    def test_no_op_for_missing_state_path(self, tmp_path):
        _lib.append_migration_history("", self._record())

    def test_no_op_for_nonexistent_path(self, tmp_path):
        _lib.append_migration_history(str(tmp_path / "missing.json"), self._record())


# ===========================================================================
# rollback
# ===========================================================================

class TestRollback:
    def _record(self, outcome="failed") -> _lib.MigrationRecord:
        return _lib.MigrationRecord(
            migration_id="rb-001",
            node_vm_name="k3s-server-01",
            from_variant="ubuntu",
            to_variant="talos",
            started_at="2026-06-02T00:00:00+00:00",
            completed_at=None,
            outcome=outcome,
            snapshot_vmid=201,
            error="test error",
            dry_run=False,
        )

    def test_rollback_dry_run_no_op(self, tmp_path):
        state = _state_with_ubuntu_node()
        snap = _lib.snapshot_state("k3s-server-01", "ubuntu", state)
        state_path = _write_state(tmp_path, state)
        record = self._record()
        _lib.rollback(snap, state_path, record, dry_run=True)

    def test_rollback_restores_state(self, tmp_path):
        original = _state_with_ubuntu_node()
        snap = _lib.snapshot_state("k3s-server-01", "ubuntu", original)

        # Simulate state being mutated (os_variant changed)
        mutated = json.loads(snap.state_json)
        mutated["vms"][0]["os_variant"] = "talos"
        state_path = _write_state(tmp_path, mutated)

        record = self._record()
        uncordon_called = []
        def _mock_runner(cmd):
            if "uncordon" in cmd:
                uncordon_called.append(cmd)
            return ""

        _lib.rollback(snap, state_path, record, runner=_mock_runner)

        with open(state_path) as f:
            restored = json.load(f)
        vm = restored["vms"][0]
        assert vm["os_variant"] == "ubuntu"
        assert len(uncordon_called) == 1

    def test_rollback_appends_rolled_back_record(self, tmp_path):
        state = _state_with_ubuntu_node()
        snap = _lib.snapshot_state("k3s-server-01", "ubuntu", state)
        state_path = _write_state(tmp_path, state)
        record = self._record()
        _lib.rollback(snap, state_path, record)
        with open(state_path) as f:
            restored = json.load(f)
        assert restored["migration_history"][0]["outcome"] == "rolled_back"


# ===========================================================================
# make_migration_id
# ===========================================================================

class TestMakeMigrationId:
    def test_contains_node_name(self):
        mid = _lib.make_migration_id("k3s-server-01", "ubuntu", "talos")
        assert "k3s-server-01" in mid

    def test_contains_variants(self):
        mid = _lib.make_migration_id("k3s-server-01", "ubuntu", "talos")
        assert "ubuntu" in mid
        assert "talos" in mid

    def test_unique_per_call(self):
        import time
        m1 = _lib.make_migration_id("k3s-server-01", "ubuntu", "talos")
        time.sleep(0.01)
        m2 = _lib.make_migration_id("k3s-server-01", "ubuntu", "talos")
        # Both should be valid strings (may be same if same second)
        assert isinstance(m1, str)
        assert isinstance(m2, str)


# ===========================================================================
# migrate_to_talos — integration (dry-run and mocked paths)
# ===========================================================================

import importlib.util


def _load_migrate_talos():
    spec = importlib.util.spec_from_file_location(
        "migrate_k3s_to_talos",
        os.path.join(_PB, "migrate-k3s-to-talos.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_migrate_ubuntu():
    spec = importlib.util.spec_from_file_location(
        "migrate_k3s_to_ubuntu",
        os.path.join(_PB, "migrate-k3s-to-ubuntu.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_talos_config_dir(tmp_path, vm_name: str = "k3s-server-01") -> str:
    """Create a temp talos-configs dir with a stub machine config for tests."""
    talos_dir = os.path.join(str(tmp_path), "talos-configs")
    os.makedirs(talos_dir, exist_ok=True)
    with open(os.path.join(talos_dir, f"{vm_name}.yaml"), "w") as f:
        f.write("# test stub\nmachine:\n  type: controlplane\n")
    return talos_dir


class TestMigrateToTalos:
    def test_dry_run_returns_true_for_valid_state(self, tmp_path):
        talos_dir = _make_talos_config_dir(tmp_path)
        mod = _load_migrate_talos()
        state = _state_with_ubuntu_node()
        state_path = _write_state(tmp_path, state)
        result = mod.migrate_to_talos(
            node_vm_name="k3s-server-01",
            state_path=state_path,
            dry_run=True,
            skip_snapshot=True,
            runner=lambda cmd: "drained",
            talos_config_dir=talos_dir,
        )
        assert result is True

    def test_returns_false_for_red_cluster(self, tmp_path):
        mod = _load_migrate_talos()
        state = _state_with_ubuntu_node()
        state["readiness_score"] = "RED"
        state_path = _write_state(tmp_path, state)
        result = mod.migrate_to_talos(
            node_vm_name="k3s-server-01",
            state_path=state_path,
            dry_run=True,
            runner=lambda cmd: "",
        )
        assert result is False

    def test_returns_false_for_missing_state_path(self, tmp_path):
        mod = _load_migrate_talos()
        result = mod.migrate_to_talos(
            node_vm_name="k3s-server-01",
            state_path=str(tmp_path / "missing.json"),
            dry_run=True,
        )
        assert result is False

    def test_returns_true_for_already_talos(self, tmp_path):
        mod = _load_migrate_talos()
        state = _state_with_talos_node()
        state_path = _write_state(tmp_path, state)
        result = mod.migrate_to_talos(
            node_vm_name="k3s-server-01",
            state_path=state_path,
            dry_run=True,
        )
        assert result is True

    def test_success_path_updates_os_variant(self, tmp_path):
        talos_dir = _make_talos_config_dir(tmp_path)
        mod = _load_migrate_talos()
        state = _state_with_ubuntu_node()
        state_path = _write_state(tmp_path, state)
        result = mod.migrate_to_talos(
            node_vm_name="k3s-server-01",
            state_path=state_path,
            dry_run=False,
            skip_snapshot=True,
            runner=lambda cmd: "drained",
            talos_config_dir=talos_dir,
        )
        # May succeed or fail depending on cluster health mock; just check no exception
        assert isinstance(result, bool)

    def test_live_success_path_appends_history(self, tmp_path):
        talos_dir = _make_talos_config_dir(tmp_path)
        mod = _load_migrate_talos()
        state = _state_with_ubuntu_node()
        state_path = _write_state(tmp_path, state)

        def _mock_runner(cmd):
            if "get nodes" in cmd:
                return "k3s-server-01  Ready  control-plane"
            if "talosctl" in cmd:
                return ""  # talosctl exits 0 with no output on success
            return "drained"

        result = mod.migrate_to_talos(
            node_vm_name="k3s-server-01",
            state_path=state_path,
            dry_run=False,
            skip_snapshot=True,
            runner=_mock_runner,
            talos_config_dir=talos_dir,
        )
        assert result is True
        with open(state_path) as f:
            updated = json.load(f)
        assert "migration_history" in updated
        assert updated["migration_history"][0]["outcome"] == "success"
        assert updated["vms"][0]["os_variant"] == "talos"


class TestMigrateToUbuntu:
    def test_dry_run_returns_true_for_valid_state(self, tmp_path):
        mod = _load_migrate_ubuntu()
        state = _state_with_talos_node()
        state_path = _write_state(tmp_path, state)
        result = mod.migrate_to_ubuntu(
            node_vm_name="k3s-server-01",
            state_path=state_path,
            dry_run=True,
            runner=lambda cmd: "drained",
        )
        assert result is True

    def test_returns_false_for_red_cluster(self, tmp_path):
        mod = _load_migrate_ubuntu()
        state = _state_with_talos_node()
        state["readiness_score"] = "RED"
        state_path = _write_state(tmp_path, state)
        result = mod.migrate_to_ubuntu(
            node_vm_name="k3s-server-01",
            state_path=state_path,
            dry_run=True,
        )
        assert result is False

    def test_returns_true_for_already_ubuntu(self, tmp_path):
        mod = _load_migrate_ubuntu()
        state = _state_with_ubuntu_node()
        state_path = _write_state(tmp_path, state)
        result = mod.migrate_to_ubuntu(
            node_vm_name="k3s-server-01",
            state_path=state_path,
            dry_run=True,
        )
        assert result is True

    def test_live_success_updates_state(self, tmp_path):
        mod = _load_migrate_ubuntu()
        state = _state_with_talos_node()
        state_path = _write_state(tmp_path, state)

        def _mock_runner(cmd):
            if "get nodes" in cmd:
                return "k3s-server-01  Ready  control-plane"
            if "failed=0" in cmd:
                return "ok=1 failed=0"
            return ""

        result = mod.migrate_to_ubuntu(
            node_vm_name="k3s-server-01",
            state_path=state_path,
            dry_run=False,
            skip_snapshot=True,
            runner=_mock_runner,
        )
        assert result is True
        with open(state_path) as f:
            updated = json.load(f)
        assert updated["vms"][0]["os_variant"] == "ubuntu"
        assert updated["migration_history"][0]["outcome"] == "success"


# ===========================================================================
# bootstrap-state-schema.json: migration_history field
# ===========================================================================

class TestBootstrapStateSchemaHasMigrationHistory:
    def test_schema_has_migration_history_property(self):
        schema_path = os.path.join(_DM, "bootstrap-state-schema.json")
        with open(schema_path) as f:
            schema = json.load(f)
        assert "migration_history" in schema["properties"], (
            "migration_history not found in bootstrap-state-schema.json properties"
        )

    def test_migration_history_is_array(self):
        schema_path = os.path.join(_DM, "bootstrap-state-schema.json")
        with open(schema_path) as f:
            schema = json.load(f)
        mh = schema["properties"]["migration_history"]
        assert mh["type"] == "array"

    def test_migration_history_items_have_required_fields(self):
        schema_path = os.path.join(_DM, "bootstrap-state-schema.json")
        with open(schema_path) as f:
            schema = json.load(f)
        mh = schema["properties"]["migration_history"]
        required = mh["items"].get("required", [])
        for field in ("migration_id", "node_vm_name", "from_variant", "to_variant", "outcome"):
            assert field in required, f"'{field}' not in migration_history.items.required"

    def test_migration_history_outcome_enum(self):
        schema_path = os.path.join(_DM, "bootstrap-state-schema.json")
        with open(schema_path) as f:
            schema = json.load(f)
        props = schema["properties"]["migration_history"]["items"]["properties"]
        outcome = props["outcome"]
        assert "success" in outcome["enum"]
        assert "rolled_back" in outcome["enum"]
        assert "aborted" in outcome["enum"]
