"""
test_phase22_multilevel_readiness.py — Phase 22: Multi-Level Readiness Assessment.

Covers:
  22.1  score_hardware() — hardware + platform readiness
  22.2  score_cluster()  — cluster + storage readiness
  22.3  score_cell()     — aggregate cell-level readiness
  22.4  score_federation() — federation readiness from cell scores
  22.5  MultiLevelReport — overall score, summary, to_dict()
  22.6  build_multilevel_report() — assemble from state docs
"""

import sys
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "proxmox-bootstrap"))

import multilevel_readiness as _mr


def _now():
    return "2026-06-01T12:00:00+00:00"


# ===========================================================================
# 22.1 — score_hardware
# ===========================================================================

class TestScoreHardware:
    def test_no_state_yellow(self):
        r = _mr.score_hardware()
        assert r.score == "YELLOW"

    def test_healthy_disks_green(self):
        hw = {"disks": [{"id": "sda", "health": "OK"}, {"id": "sdb", "health": "OK"}],
              "ram_gb": 32, "ram_used_gb": 10}
        r = _mr.score_hardware(hw)
        assert r.score == "GREEN"

    def test_failed_disk_red(self):
        hw = {"disks": [{"id": "sda", "health": "FAILED"}]}
        r = _mr.score_hardware(hw)
        assert r.score == "RED"

    def test_caution_disk_orange(self):
        hw = {"disks": [{"id": "sda", "health": "CAUTION"}]}
        r = _mr.score_hardware(hw)
        assert r.score == "ORANGE"

    def test_high_ram_usage_orange(self):
        hw = {"disks": [], "ram_gb": 32, "ram_used_gb": 30}  # 93.75%
        r = _mr.score_hardware(hw)
        assert r.score in ("ORANGE", "RED")

    def test_platform_outdated_packages(self):
        hw = {"disks": []}
        ps = {"packages_outdated_count": 100}
        r = _mr.score_hardware(hw, ps)
        assert r.score in ("ORANGE", "YELLOW")

    def test_components_populated(self):
        hw = {"disks": [{"id": "sda", "health": "OK"}]}
        r = _mr.score_hardware(hw)
        assert len(r.components) >= 1

    def test_returns_readiness_level(self):
        r = _mr.score_hardware({})
        assert isinstance(r, _mr.ReadinessLevel)


# ===========================================================================
# 22.2 — score_cluster
# ===========================================================================

class TestScoreCluster:
    def test_no_state_yellow(self):
        r = _mr.score_cluster()
        assert r.score == "YELLOW"

    def test_quorum_ok_green(self):
        cs = {"corosync_quorum_ok": True, "nodes_total": 1, "nodes_online": 1}
        r = _mr.score_cluster(cluster_state=cs)
        assert r.score == "GREEN"

    def test_quorum_failed_red(self):
        cs = {"corosync_quorum_ok": False, "nodes_total": 1, "nodes_online": 1}
        r = _mr.score_cluster(cluster_state=cs)
        assert r.score == "RED"

    def test_nodes_offline_orange(self):
        cs = {"corosync_quorum_ok": True, "nodes_total": 3, "nodes_online": 2}
        r = _mr.score_cluster(cluster_state=cs)
        assert r.score == "ORANGE"

    def test_zfs_degraded_orange(self):
        ss = {"zfs_pools": [{"name": "rpool", "health": "DEGRADED"}]}
        r = _mr.score_cluster(storage_state=ss)
        assert r.score == "ORANGE"

    def test_zfs_faulted_red(self):
        ss = {"zfs_pools": [{"name": "rpool", "health": "FAULTED"}]}
        r = _mr.score_cluster(storage_state=ss)
        assert r.score == "RED"

    def test_datastore_high_usage_orange(self):
        ss = {"datastores": [{"id": "local-zfs", "usage_pct": 92}]}
        r = _mr.score_cluster(storage_state=ss)
        assert r.score in ("ORANGE", "RED")


# ===========================================================================
# 22.3 — score_cell
# ===========================================================================

class TestScoreCell:
    def test_no_data_yellow(self):
        r = _mr.score_cell("pve01-cell")
        assert r.score == "YELLOW"

    def test_all_green(self):
        hw = _mr.ReadinessLevel("GREEN", "OK", [])
        cl = _mr.ReadinessLevel("GREEN", "OK", [])
        r  = _mr.score_cell("pve01-cell", hw, cl)
        assert r.score == "GREEN"

    def test_hardware_red_propagates(self):
        hw = _mr.ReadinessLevel("RED", "Disk failed", [])
        cl = _mr.ReadinessLevel("GREEN", "OK", [])
        r  = _mr.score_cell("pve01-cell", hw, cl)
        assert r.score == "RED"

    def test_extra_scores_influence(self):
        hw = _mr.ReadinessLevel("GREEN", "OK", [])
        cl = _mr.ReadinessLevel("GREEN", "OK", [])
        r  = _mr.score_cell("pve01-cell", hw, cl, extra_scores={"backup": "ORANGE"})
        assert r.score == "ORANGE"

    def test_components_populated(self):
        hw = _mr.ReadinessLevel("GREEN", "OK", [])
        cl = _mr.ReadinessLevel("GREEN", "OK", [])
        r  = _mr.score_cell("pve01-cell", hw, cl)
        assert len(r.components) >= 2


# ===========================================================================
# 22.4 — score_federation
# ===========================================================================

class TestScoreFederation:
    def test_empty_cells_red(self):
        r = _mr.score_federation([])
        assert r.score == "RED"

    def test_all_green_cells(self):
        cells = [
            _mr.FederationCellScore("cell-a", "GREEN", "OK"),
            _mr.FederationCellScore("cell-b", "GREEN", "OK"),
        ]
        r = _mr.score_federation(cells, trust_score="GREEN")
        assert r.score == "GREEN"

    def test_one_red_cell_propagates(self):
        cells = [
            _mr.FederationCellScore("cell-a", "RED", "Disk failed"),
            _mr.FederationCellScore("cell-b", "GREEN", "OK"),
        ]
        r = _mr.score_federation(cells, trust_score="GREEN")
        assert r.score == "RED"

    def test_trust_score_propagates(self):
        cells = [_mr.FederationCellScore("cell-a", "GREEN", "OK")]
        r = _mr.score_federation(cells, trust_score="ORANGE")
        assert r.score == "ORANGE"

    def test_components_include_trust(self):
        cells = [_mr.FederationCellScore("cell-a", "GREEN", "OK")]
        r = _mr.score_federation(cells, trust_score="GREEN")
        ids = {c["id"] for c in r.components}
        assert "trust" in ids


# ===========================================================================
# 22.5 — MultiLevelReport
# ===========================================================================

class TestMultiLevelReport:
    def _report(self, hw_score="GREEN", cl_score="GREEN", cell_score="GREEN"):
        return _mr.MultiLevelReport(
            cell_id="pve01-cell",
            hardware_level=_mr.ReadinessLevel(hw_score, "hw", []),
            cluster_level=_mr.ReadinessLevel(cl_score, "cl", []),
            cell_level=_mr.ReadinessLevel(cell_score, "cell", []),
            generated_at=_now(),
        )

    def test_overall_score_all_green(self):
        assert self._report().overall_score == "GREEN"

    def test_overall_score_worst_propagates(self):
        assert self._report(hw_score="RED").overall_score == "RED"

    def test_overall_score_orange(self):
        assert self._report(cl_score="ORANGE").overall_score == "ORANGE"

    def test_summary_contains_cell_id(self):
        r = self._report()
        assert "pve01-cell" in r.summary

    def test_to_dict_structure(self):
        d = self._report().to_dict()
        assert "cell_id" in d
        assert "overall_score" in d
        assert "hardware_level" in d
        assert "cluster_level" in d
        assert "cell_level" in d

    def test_to_dict_federation_none(self):
        d = self._report().to_dict()
        assert d["federation_level"] is None


# ===========================================================================
# 22.6 — build_multilevel_report
# ===========================================================================

class TestBuildMultilevelReport:
    def test_returns_report(self):
        r = _mr.build_multilevel_report("pve01-cell", now_fn=_now)
        assert isinstance(r, _mr.MultiLevelReport)

    def test_no_state_yellow_hardware(self):
        r = _mr.build_multilevel_report("pve01-cell", now_fn=_now)
        assert r.hardware_level.score == "YELLOW"

    def test_with_hardware_state(self):
        hw = {"disks": [{"id": "sda", "health": "OK"}], "ram_gb": 32, "ram_used_gb": 8}
        r  = _mr.build_multilevel_report("pve01-cell", hardware_state=hw, now_fn=_now)
        assert r.hardware_level.score == "GREEN"

    def test_with_federation_scores(self):
        fed_scores = [
            _mr.FederationCellScore("pve01-cell", "GREEN", "OK"),
            _mr.FederationCellScore("pve02-cell", "YELLOW", "No coordinator"),
        ]
        r = _mr.build_multilevel_report(
            "pve01-cell", fed_cell_scores=fed_scores, now_fn=_now,
        )
        assert r.federation_level is not None
        assert r.federation_level.score in ("GREEN", "YELLOW", "ORANGE", "RED")

    def test_generated_at_set(self):
        r = _mr.build_multilevel_report("cell-a", now_fn=_now)
        assert r.generated_at == _now()

    def test_extra_scores_reflected(self):
        r = _mr.build_multilevel_report("cell-a",
                                         extra_scores={"backup": "RED"},
                                         now_fn=_now)
        assert r.cell_level.score == "RED"
