"""
test_replay_snapshot.py — Tests for Phase 1.I (AD-059): replay-snapshot.py
conformance check (re-derive a stored snapshot's hashes and assert a match).
"""

import importlib.util
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_PB = os.path.join(_ROOT, "proxmox-bootstrap")

import _recovery_readiness_certificate as _rrc
from dependencies import build_graph
from readiness import score_graph

_spec = importlib.util.spec_from_file_location(
    "replay_snapshot", os.path.join(_PB, "replay-snapshot.py")
)
_replay = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_replay)


def _manifest(cell_id="pve01-cell"):
    return {
        "schema_version": "1.0",
        "cell_id": cell_id,
        "assessment_tier": 2,
        "collected_at": "2026-06-01T00:00:00Z",
        "host": {
            "hostname": "pve01",
            "proxmox_version": "8.2",
            "kernel_version": "6.8.0",
        },
        "storage": {
            "zfs_pools": [
                {"name": "rpool", "topology": "mirror", "total_gb": 1000,
                 "free_gb": 500, "state": "ONLINE", "devices": ["sda", "sdb"]},
            ],
            "pve_storage": [],
        },
        "network": {"bridges": []},
        "vms": [],
        "containers": [],
        "backup_inventory": {},
    }


# ===========================================================================
# replay_snapshot — recomputation
# ===========================================================================

class TestReplaySnapshot:
    def test_recomputes_manifest_hash(self):
        manifest = _manifest()
        result = _replay.replay_snapshot(manifest)
        assert result["manifest_hash"] == _rrc.hash_dict(manifest)

    def test_recomputes_graph_hash(self):
        manifest = _manifest()
        graph = build_graph(manifest)
        result = _replay.replay_snapshot(manifest)
        assert result["graph_hash"] == _rrc.hash_dict(graph.to_dict())

    def test_recomputes_overall_score(self):
        manifest = _manifest()
        graph = build_graph(manifest)
        readiness = score_graph(graph, manifest)
        result = _replay.replay_snapshot(manifest)
        assert result["overall_score"] == readiness.overall_score
        assert result["overall_score_reason"] == readiness.overall_score_reason

    def test_deterministic_across_runs(self):
        manifest = _manifest()
        r1 = _replay.replay_snapshot(manifest)
        r2 = _replay.replay_snapshot(manifest)
        assert r1 == r2


# ===========================================================================
# compare_replay — match / mismatch detection
# ===========================================================================

class TestCompareReplay:
    def test_match_when_hashes_equal(self):
        manifest = _manifest()
        recomputed = _replay.replay_snapshot(manifest)
        result = _replay.compare_replay(
            recomputed, recomputed["manifest_hash"], recomputed["graph_hash"]
        )
        assert result["match"] is True
        assert result["mismatches"] == []

    def test_mismatch_on_manifest_hash(self):
        manifest = _manifest()
        recomputed = _replay.replay_snapshot(manifest)
        result = _replay.compare_replay(
            recomputed, "deadbeef" * 8, recomputed["graph_hash"]
        )
        assert result["match"] is False
        assert any("manifest_hash" in m for m in result["mismatches"])

    def test_mismatch_on_graph_hash(self):
        manifest = _manifest()
        recomputed = _replay.replay_snapshot(manifest)
        result = _replay.compare_replay(
            recomputed, recomputed["manifest_hash"], "deadbeef" * 8
        )
        assert result["match"] is False
        assert any("graph_hash" in m for m in result["mismatches"])

    def test_both_mismatch_reported(self):
        manifest = _manifest()
        recomputed = _replay.replay_snapshot(manifest)
        result = _replay.compare_replay(recomputed, "a" * 64, "b" * 64)
        assert result["match"] is False
        assert len(result["mismatches"]) == 2

    def test_none_recorded_values_skipped(self):
        manifest = _manifest()
        recomputed = _replay.replay_snapshot(manifest)
        result = _replay.compare_replay(recomputed, None, None)
        assert result["match"] is True


# ===========================================================================
# CLI plumbing — direct manifest replay against expected hashes
# ===========================================================================

class TestReplayCli:
    def _write_manifest(self, tmp_path, manifest):
        path = tmp_path / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def test_cli_exits_zero_on_match(self, tmp_path, capsys, monkeypatch):
        manifest = _manifest()
        path = self._write_manifest(tmp_path, manifest)
        recomputed = _replay.replay_snapshot(manifest)

        monkeypatch.setattr(sys, "argv", [
            "replay-snapshot.py",
            "--manifest", str(path),
            "--expect-manifest-hash", recomputed["manifest_hash"],
            "--expect-graph-hash", recomputed["graph_hash"],
        ])
        try:
            _replay.main()
        except SystemExit as exc:
            assert exc.code == 0
        else:
            raise AssertionError("expected SystemExit")

        out = capsys.readouterr().out
        assert "PASS" in out

    def test_cli_exits_one_on_mismatch(self, tmp_path, capsys, monkeypatch):
        manifest = _manifest()
        path = self._write_manifest(tmp_path, manifest)

        monkeypatch.setattr(sys, "argv", [
            "replay-snapshot.py",
            "--manifest", str(path),
            "--expect-manifest-hash", "0" * 64,
            "--expect-graph-hash", "1" * 64,
        ])
        try:
            _replay.main()
        except SystemExit as exc:
            assert exc.code == 1
        else:
            raise AssertionError("expected SystemExit")

        out = capsys.readouterr().out
        assert "FAIL" in out
        assert "mismatch" in out.lower()

    def test_cli_errors_on_missing_manifest(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "argv", [
            "replay-snapshot.py",
            "--manifest", str(tmp_path / "does-not-exist.json"),
        ])
        try:
            _replay.main()
        except SystemExit as exc:
            assert exc.code == 1
        else:
            raise AssertionError("expected SystemExit")
