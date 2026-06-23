#!/usr/bin/env python3
"""
Tests for Phase 11 — Capacity Model.

Covers:
  - collect_capacity_snapshot(): extraction from manifest
  - compute_trend(): trend direction + projection from snapshots
  - check_restoration_headroom(): RAM sufficiency for full recovery
  - merge_capacity_model(): state dict update
  - _score_capacity_model(): readiness gaps (warn/crit/trend/headroom)
  - bootstrap-state-schema.json accepts capacity_model section
"""

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent

from capacity_collector import (
    DEFAULT_THRESHOLDS,
    check_restoration_headroom,
    collect_capacity_snapshot,
    compute_trend,
    merge_capacity_model,
)
from readiness import _score_capacity_model

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _now_iso(offset_days=0) -> str:
    dt = datetime.now(timezone.utc) + timedelta(days=offset_days)
    return dt.isoformat()


def _manifest(ram_total=32, ram_avail=16, stor_total=500, stor_free=200, vms=None):
    m = {
        "memory": {"total_gb": ram_total, "available_gb": ram_avail},
        "storage": {
            "zfs_pools": [{"name": "rpool", "state": "ONLINE",
                           "size_gb": stor_total, "free_gb": stor_free}],
        },
        "vms": vms or [],
    }
    return m


def _capacity_model(ram_pct=50, stor_pct=50, trend=None):
    return {
        "thresholds": DEFAULT_THRESHOLDS,
        "observed": {
            "ram_usage_pct":     ram_pct,
            "storage_usage_pct": stor_pct,
            "ram_total_gb":      32,
            "ram_used_gb":       32 * ram_pct / 100,
        },
        "trend": trend or {},
    }


# ---------------------------------------------------------------------------
# collect_capacity_snapshot
# ---------------------------------------------------------------------------

class TestCollectCapacitySnapshot(unittest.TestCase):

    def test_ram_pct_calculated(self):
        snap = collect_capacity_snapshot(_manifest(ram_total=32, ram_avail=16))
        self.assertAlmostEqual(snap["ram_usage_pct"], 50.0, places=1)

    def test_ram_used_calculated(self):
        snap = collect_capacity_snapshot(_manifest(ram_total=32, ram_avail=20))
        self.assertAlmostEqual(snap["ram_used_gb"], 12.0, places=1)

    def test_storage_pct_calculated(self):
        snap = collect_capacity_snapshot(_manifest(stor_total=500, stor_free=100))
        self.assertAlmostEqual(snap["storage_usage_pct"], 80.0, places=1)

    def test_observed_at_is_set(self):
        snap = collect_capacity_snapshot(_manifest())
        self.assertIsNotNone(snap["observed_at"])

    def test_no_ram_data_returns_none(self):
        snap = collect_capacity_snapshot({})
        self.assertIsNone(snap["ram_usage_pct"])
        self.assertIsNone(snap["ram_total_gb"])

    def test_no_storage_returns_none(self):
        snap = collect_capacity_snapshot({"memory": {"total_gb": 32, "available_gb": 16}})
        self.assertIsNone(snap["storage_usage_pct"])

    def test_vm_ram_summed(self):
        vms = [{"vmid": 100, "ram_gb": 4}, {"vmid": 101, "ram_gb": 8}]
        snap = collect_capacity_snapshot(_manifest(vms=vms))
        self.assertAlmostEqual(snap["vm_ram_total_gb"], 12.0, places=1)

    def test_vm_no_ram_field_returns_none(self):
        vms = [{"vmid": 100, "name": "vm1"}]
        snap = collect_capacity_snapshot(_manifest(vms=vms))
        self.assertIsNone(snap["vm_ram_total_gb"])


# ---------------------------------------------------------------------------
# compute_trend
# ---------------------------------------------------------------------------

class TestComputeTrend(unittest.TestCase):

    def _snap(self, offset_days: int, ram_pct: float, stor_pct: float) -> dict:
        return {
            "observed_at":       _now_iso(offset_days),
            "ram_usage_pct":     ram_pct,
            "storage_usage_pct": stor_pct,
        }

    def test_single_snapshot_no_trend(self):
        trend = compute_trend([self._snap(0, 50, 50)])
        self.assertIsNone(trend["ram_trend"])

    def test_empty_snapshots_no_trend(self):
        trend = compute_trend([])
        self.assertIsNone(trend["ram_trend"])

    def test_increasing_ram_trend(self):
        snaps = [self._snap(-30, 40, 50), self._snap(0, 60, 50)]
        trend = compute_trend(snaps)
        self.assertEqual(trend["ram_trend"], "increasing")

    def test_stable_ram_trend(self):
        snaps = [self._snap(-30, 50, 50), self._snap(0, 50.05, 50)]
        trend = compute_trend(snaps)
        self.assertEqual(trend["ram_trend"], "stable")

    def test_decreasing_ram_trend(self):
        snaps = [self._snap(-30, 70, 50), self._snap(0, 50, 50)]
        trend = compute_trend(snaps)
        self.assertEqual(trend["ram_trend"], "decreasing")

    def test_days_to_full_computed_when_increasing(self):
        # 40% → 60% over 30 days = 0.67%/day; at 60%, ~60 days to reach 100%
        snaps = [self._snap(-30, 40, 50), self._snap(0, 60, 50)]
        trend = compute_trend(snaps)
        self.assertIsNotNone(trend["days_to_ram_full"])
        self.assertGreater(trend["days_to_ram_full"], 0)

    def test_days_to_full_none_when_decreasing(self):
        snaps = [self._snap(-30, 70, 50), self._snap(0, 50, 50)]
        trend = compute_trend(snaps)
        self.assertIsNone(trend["days_to_ram_full"])

    def test_snapshots_used_count(self):
        snaps = [self._snap(-30, 40, 50), self._snap(-15, 50, 55), self._snap(0, 60, 60)]
        trend = compute_trend(snaps)
        self.assertEqual(trend["snapshots_used"], 3)


# ---------------------------------------------------------------------------
# check_restoration_headroom
# ---------------------------------------------------------------------------

class TestCheckRestorationHeadroom(unittest.TestCase):

    def _cm(self, ram_total=32, headroom_pct=10):
        return {
            "thresholds": {**DEFAULT_THRESHOLDS, "restoration_headroom_pct": headroom_pct},
            "observed": {"ram_total_gb": ram_total},
        }

    def test_sufficient_headroom_returns_ok(self):
        # 32 GB total, 10% headroom → 28.8 GB available; 4 VMs × 4 GB = 16 GB needed
        vms = [{"vmid": i, "ram_gb": 4} for i in range(4)]
        result = check_restoration_headroom(_manifest(vms=vms), self._cm(ram_total=32))
        self.assertIsNotNone(result)
        self.assertTrue(result["ok"])

    def test_insufficient_headroom_returns_not_ok(self):
        # 32 GB total, 10% headroom → 28.8 GB available; 8 VMs × 4 GB = 32 GB needed
        vms = [{"vmid": i, "ram_gb": 4} for i in range(8)]
        result = check_restoration_headroom(_manifest(vms=vms), self._cm(ram_total=32))
        self.assertIsNotNone(result)
        self.assertFalse(result["ok"])
        self.assertLess(result["gap_gb"], 0)

    def test_no_ram_data_returns_none(self):
        result = check_restoration_headroom({}, {"observed": {}})
        self.assertIsNone(result)

    def test_no_vm_ram_returns_none(self):
        result = check_restoration_headroom(_manifest(), self._cm())
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# merge_capacity_model
# ---------------------------------------------------------------------------

class TestMergeCapacityModel(unittest.TestCase):

    def test_merge_adds_capacity_model(self):
        state = {}
        state = merge_capacity_model(state, _manifest())
        self.assertIn("capacity_model", state)

    def test_merge_includes_observed(self):
        state = {}
        state = merge_capacity_model(state, _manifest(ram_total=32, ram_avail=16))
        obs = state["capacity_model"]["observed"]
        self.assertAlmostEqual(obs["ram_usage_pct"], 50.0, places=1)

    def test_merge_preserves_existing_thresholds(self):
        state = {"capacity_model": {"thresholds": {"ram_crit_pct": 95}}}
        state = merge_capacity_model(state, _manifest())
        self.assertEqual(state["capacity_model"]["thresholds"]["ram_crit_pct"], 95)

    def test_merge_with_history_snapshots(self):
        def _snap(offset, ram_pct):
            return {"observed_at": _now_iso(offset), "ram_usage_pct": ram_pct,
                    "storage_usage_pct": 50}
        snaps = [_snap(-30, 40), _snap(0, 60)]
        state = merge_capacity_model({}, _manifest(), history_snapshots=snaps)
        self.assertIn("trend", state["capacity_model"])
        self.assertIsNotNone(state["capacity_model"]["trend"]["ram_trend"])


# ---------------------------------------------------------------------------
# _score_capacity_model
# ---------------------------------------------------------------------------

class TestScoreCapacityModel(unittest.TestCase):

    def test_no_capacity_model_is_yellow(self):
        gaps = _score_capacity_model({})
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].severity, "YELLOW")
        self.assertIn("MISSING_CAPACITY_MODEL", gaps[0].gap_type)

    def test_healthy_utilization_no_gaps(self):
        gaps = _score_capacity_model({"capacity_model": _capacity_model(50, 50)})
        storage_and_ram = [g for g in gaps if g.gap_type in ("CAPACITY_EXCEEDED", "CAPACITY_WARN")]
        self.assertEqual(storage_and_ram, [])

    def test_ram_above_warning_is_yellow(self):
        gaps = _score_capacity_model({"capacity_model": _capacity_model(ram_pct=80)})
        ram_gaps = [g for g in gaps if "ram" in g.component_id and g.gap_type == "CAPACITY_WARN"]
        self.assertTrue(len(ram_gaps) >= 1)
        self.assertEqual(ram_gaps[0].severity, "YELLOW")

    def test_ram_above_critical_is_orange(self):
        gaps = _score_capacity_model({"capacity_model": _capacity_model(ram_pct=92)})
        ram_gaps = [g for g in gaps if "ram" in g.component_id and g.gap_type == "CAPACITY_EXCEEDED"]
        self.assertTrue(len(ram_gaps) >= 1)
        self.assertEqual(ram_gaps[0].severity, "ORANGE")

    def test_storage_above_critical_is_orange(self):
        gaps = _score_capacity_model({"capacity_model": _capacity_model(stor_pct=93)})
        stor_gaps = [g for g in gaps if "storage" in g.component_id and g.gap_type == "CAPACITY_EXCEEDED"]
        self.assertTrue(len(stor_gaps) >= 1)

    def test_trend_projection_within_30_days_is_orange(self):
        cm = _capacity_model(trend={"days_to_ram_full": 20, "days_to_storage_full": None})
        gaps = _score_capacity_model({"capacity_model": cm})
        trend_gaps = [g for g in gaps if g.gap_type == "CAPACITY_TREND"]
        self.assertTrue(len(trend_gaps) >= 1)
        self.assertEqual(trend_gaps[0].severity, "ORANGE")

    def test_trend_projection_within_90_days_is_yellow(self):
        cm = _capacity_model(trend={"days_to_ram_full": 60, "days_to_storage_full": None})
        gaps = _score_capacity_model({"capacity_model": cm})
        trend_gaps = [g for g in gaps if g.gap_type == "CAPACITY_TREND"]
        self.assertTrue(len(trend_gaps) >= 1)
        self.assertEqual(trend_gaps[0].severity, "YELLOW")

    def test_trend_beyond_90_days_no_gap(self):
        cm = _capacity_model(trend={"days_to_ram_full": 120, "days_to_storage_full": None})
        gaps = _score_capacity_model({"capacity_model": cm})
        trend_gaps = [g for g in gaps if g.gap_type == "CAPACITY_TREND"]
        self.assertEqual(trend_gaps, [])

    def test_insufficient_headroom_is_orange(self):
        # 32 GB RAM, 8 VMs × 4 GB = 32 GB needed, only 28.8 GB available (90% headroom)
        vms = [{"vmid": i, "ram_gb": 4} for i in range(8)]
        cm = {
            "thresholds": DEFAULT_THRESHOLDS,
            "observed": {"ram_total_gb": 32, "ram_usage_pct": 50},
            "trend": {},
        }
        gaps = _score_capacity_model({"capacity_model": cm, "vms": vms})
        headroom_gaps = [g for g in gaps if g.gap_type == "INSUFFICIENT_RESTORATION_HEADROOM"]
        self.assertTrue(len(headroom_gaps) >= 1)
        self.assertEqual(headroom_gaps[0].severity, "ORANGE")


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class TestBootstrapStateSchemaCapacityModel(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        try:
            import jsonschema
            cls.jsonschema = jsonschema
            cls.skip = False
        except ImportError:
            cls.skip = True
        schema_path = REPO_ROOT / "data-model" / "bootstrap-state-schema.json"
        cls.schema = json.loads(schema_path.read_text(encoding="utf-8"))

    def _validate(self, instance):
        if self.skip:
            self.skipTest("jsonschema not installed")
        self.jsonschema.validate(instance, self.schema)

    def test_fixture_with_capacity_model_validates(self):
        if self.skip:
            self.skipTest("jsonschema not installed")
        fixture_path = REPO_ROOT / "tests" / "fixtures" / "bootstrap" / "bootstrap-state.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        fixture["capacity_model"] = {
            "thresholds": DEFAULT_THRESHOLDS,
            "observed": {"observed_at": "2026-06-01T00:00:00Z",
                         "ram_usage_pct": 55, "ram_total_gb": 32},
            "trend": {"ram_trend": "stable", "snapshots_used": 3},
        }
        self._validate(fixture)


if __name__ == "__main__":
    unittest.main()
