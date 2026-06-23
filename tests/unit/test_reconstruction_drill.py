#!/usr/bin/env python3
"""
Tests for Phase 12 — Full Single-Cell Reconstruction Test.

Covers:
  - DrillRecord: initialization, record_wave, complete, to_dict
  - start_drill() factory from playbook
  - save_drill_record() / get_last_drill()
  - generate_drill_report() Markdown output
  - DrillRecord.accuracy_pct / completed_waves / total_waves
  - _score_reconstruction_drill(): no drills, stale, failed, recent success
  - bootstrap-state-schema.json accepts reconstruction_drills
"""

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent

from readiness import _score_reconstruction_drill
from reconstruction_drill import (
    DrillRecord,
    generate_drill_report,
    get_last_drill,
    save_drill_record,
    start_drill,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CELL_ID = "proxmox-cell-a"

PLAYBOOK = {
    "cell_id": CELL_ID,
    "generated_at": "2026-06-01T00:00:00Z",
    "estimated_total_minutes": 80,
    "waves": [
        {"wave": 0, "name": "Network", "estimated_minutes": 10},
        {"wave": 1, "name": "Storage", "estimated_minutes": 15},
        {"wave": 3, "name": "VMs",     "estimated_minutes": 30},
    ],
}

def _fixed_now():
    return datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

def _past_now(days_ago: int):
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return lambda: dt


# ---------------------------------------------------------------------------
# DrillRecord
# ---------------------------------------------------------------------------

class TestDrillRecord(unittest.TestCase):

    def setUp(self):
        self.rec = DrillRecord(CELL_ID, now_fn=_fixed_now)

    def test_drill_id_contains_cell_id(self):
        self.assertIn(CELL_ID, self.rec.drill_id)

    def test_drill_id_contains_timestamp(self):
        self.assertIn("2026-06-01", self.rec.drill_id)

    def test_started_at_is_set(self):
        self.assertIsNotNone(self.rec.started_at)

    def test_initial_outcome_is_none(self):
        self.assertIsNone(self.rec.outcome)

    def test_record_wave_adds_entry(self):
        self.rec.record_wave(0, "Network", estimated_minutes=10, actual_minutes=12)
        self.assertEqual(len(self.rec.wave_timings), 1)

    def test_record_wave_stores_all_fields(self):
        self.rec.record_wave(0, "Network", 10, 12, True)
        w = self.rec.wave_timings[0]
        self.assertEqual(w["wave"], 0)
        self.assertEqual(w["name"], "Network")
        self.assertEqual(w["estimated_minutes"], 10)
        self.assertEqual(w["actual_minutes"], 12)
        self.assertTrue(w["completed"])

    def test_complete_sets_outcome(self):
        self.rec.complete("success")
        self.assertEqual(self.rec.outcome, "success")

    def test_complete_sets_completed_at(self):
        self.rec.complete("success")
        self.assertIsNotNone(self.rec.completed_at)

    def test_complete_stores_gaps_found(self):
        self.rec.complete("partial", gaps_found=["Bridge missing"])
        self.assertIn("Bridge missing", self.rec.gaps_found)

    def test_complete_stores_gaps_remediated(self):
        self.rec.complete("success", gaps_remediated=["Updated network-topology.yaml"])
        self.assertIn("Updated network-topology.yaml", self.rec.gaps_remediated)

    def test_total_actual_minutes_summed_from_waves(self):
        self.rec.record_wave(0, "Net", actual_minutes=12)
        self.rec.record_wave(1, "Storage", actual_minutes=18)
        self.rec.complete("success")
        self.assertEqual(self.rec.total_actual_minutes, 30)

    def test_accuracy_pct_correct(self):
        self.rec.record_wave(0, "Net", actual_minutes=80)
        self.rec.complete("success")
        self.rec.total_estimated_minutes = 100
        self.assertAlmostEqual(self.rec.accuracy_pct, 80.0, places=1)

    def test_accuracy_pct_none_without_data(self):
        self.assertIsNone(self.rec.accuracy_pct)

    def test_completed_waves_count(self):
        self.rec.record_wave(0, "Net", completed=True)
        self.rec.record_wave(1, "Stor", completed=False)
        self.assertEqual(self.rec.completed_waves, 1)

    def test_total_waves(self):
        self.rec.record_wave(0, "Net")
        self.rec.record_wave(1, "Stor")
        self.assertEqual(self.rec.total_waves, 2)

    def test_to_dict_contains_all_fields(self):
        self.rec.complete("success")
        d = self.rec.to_dict()
        for field in ("drill_id", "started_at", "completed_at", "outcome",
                      "wave_timings", "gaps_found", "gaps_remediated"):
            self.assertIn(field, d)


# ---------------------------------------------------------------------------
# start_drill / save / get_last
# ---------------------------------------------------------------------------

class TestDrillFactoryAndPersistence(unittest.TestCase):

    def test_start_drill_from_playbook(self):
        rec = start_drill(PLAYBOOK, now_fn=_fixed_now)
        self.assertIn(CELL_ID, rec.drill_id)
        self.assertEqual(rec.total_estimated_minutes, 80)
        self.assertEqual(rec.playbook_generated_at, "2026-06-01T00:00:00Z")

    def test_save_drill_record_adds_to_state(self):
        rec = start_drill(PLAYBOOK, now_fn=_fixed_now)
        rec.complete("success")
        state = {}
        save_drill_record(state, rec)
        self.assertIn("reconstruction_drills", state)
        self.assertEqual(len(state["reconstruction_drills"]), 1)

    def test_save_drill_record_most_recent_first(self):
        state = {}
        r1 = start_drill(PLAYBOOK, now_fn=_past_now(10))
        r1.complete("success")
        save_drill_record(state, r1)

        r2 = start_drill(PLAYBOOK, now_fn=_fixed_now)
        r2.complete("success")
        save_drill_record(state, r2)

        # r2 was inserted last but should be at index 0 (most recent first)
        self.assertEqual(state["reconstruction_drills"][0]["drill_id"], r2.drill_id)

    def test_get_last_drill_returns_most_recent(self):
        state = {}
        r1 = start_drill(PLAYBOOK, now_fn=_past_now(10))
        r1.complete("success")
        save_drill_record(state, r1)
        r2 = start_drill(PLAYBOOK, now_fn=_fixed_now)
        r2.complete("success")
        save_drill_record(state, r2)
        last = get_last_drill(state)
        self.assertEqual(last["drill_id"], r2.drill_id)

    def test_get_last_drill_none_when_empty(self):
        self.assertIsNone(get_last_drill({}))


# ---------------------------------------------------------------------------
# generate_drill_report
# ---------------------------------------------------------------------------

class TestGenerateDrillReport(unittest.TestCase):

    def setUp(self):
        self.rec = start_drill(PLAYBOOK, now_fn=_fixed_now)
        self.rec.record_wave(0, "Network", 10, 12, True)
        self.rec.record_wave(1, "Storage", 15, 14, True)
        self.rec.complete("success", gaps_found=["Bridge step unclear"],
                          gaps_remediated=["Added clarification to network-topology.yaml"])

    def test_report_contains_drill_id(self):
        report = generate_drill_report(self.rec)
        self.assertIn(self.rec.drill_id, report)

    def test_report_contains_outcome(self):
        report = generate_drill_report(self.rec)
        self.assertIn("SUCCESS", report)

    def test_report_contains_wave_table(self):
        report = generate_drill_report(self.rec)
        self.assertIn("Wave Timings", report)
        self.assertIn("Network", report)
        self.assertIn("Storage", report)

    def test_report_contains_gaps_found(self):
        report = generate_drill_report(self.rec)
        self.assertIn("Gaps Found", report)
        self.assertIn("Bridge step unclear", report)

    def test_report_contains_gaps_remediated(self):
        report = generate_drill_report(self.rec)
        self.assertIn("Gaps Remediated", report)
        self.assertIn("network-topology.yaml", report)

    def test_report_is_markdown(self):
        report = generate_drill_report(self.rec)
        self.assertTrue(report.startswith("#"))

    def test_report_has_timing_section(self):
        report = generate_drill_report(self.rec)
        self.assertIn("Timing", report)
        self.assertIn("Estimated", report)
        self.assertIn("Actual", report)


# ---------------------------------------------------------------------------
# _score_reconstruction_drill
# ---------------------------------------------------------------------------

class TestScoreReconstructionDrill(unittest.TestCase):

    def test_no_drills_is_yellow(self):
        gaps = _score_reconstruction_drill({})
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].severity, "YELLOW")
        self.assertIn("MISSING_RECONSTRUCTION_DRILL", gaps[0].gap_type)

    def test_empty_drills_list_is_yellow(self):
        gaps = _score_reconstruction_drill({"reconstruction_drills": []})
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].severity, "YELLOW")

    def test_recent_successful_drill_no_gap(self):
        rec = start_drill(PLAYBOOK, now_fn=_fixed_now)
        rec.complete("success")
        state = {}
        save_drill_record(state, rec)
        gaps = _score_reconstruction_drill(state)
        self.assertEqual(gaps, [])

    def test_failed_drill_is_orange(self):
        rec = start_drill(PLAYBOOK, now_fn=_fixed_now)
        rec.complete("failed")
        state = {}
        save_drill_record(state, rec)
        gaps = _score_reconstruction_drill(state)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].severity, "ORANGE")
        self.assertIn("FAILED", gaps[0].gap_type)

    def test_aborted_drill_is_orange(self):
        rec = start_drill(PLAYBOOK, now_fn=_fixed_now)
        rec.complete("aborted")
        state = {}
        save_drill_record(state, rec)
        gaps = _score_reconstruction_drill(state)
        self.assertEqual(gaps[0].severity, "ORANGE")

    def test_in_progress_drill_is_yellow(self):
        rec = start_drill(PLAYBOOK, now_fn=_fixed_now)
        # outcome stays "in_progress" — drill never completed
        rec.outcome = "in_progress"
        state = {}
        save_drill_record(state, rec)
        gaps = _score_reconstruction_drill(state)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].severity, "YELLOW")
        self.assertIn("INCOMPLETE", gaps[0].gap_type)

    def test_stale_drill_is_yellow(self):
        rec = start_drill(PLAYBOOK, now_fn=_past_now(95))
        rec.complete("success")
        state = {}
        save_drill_record(state, rec)
        gaps = _score_reconstruction_drill(state)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].severity, "YELLOW")
        self.assertIn("STALE", gaps[0].gap_type)

    def test_recent_drill_under_90_days_no_gap(self):
        rec = start_drill(PLAYBOOK, now_fn=_past_now(30))
        rec.complete("success")
        state = {}
        save_drill_record(state, rec)
        gaps = _score_reconstruction_drill(state)
        self.assertEqual(gaps, [])


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class TestBootstrapStateSchemaReconstructionDrills(unittest.TestCase):

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

    def test_fixture_with_drill_record_validates(self):
        if self.skip:
            self.skipTest("jsonschema not installed")
        fixture_path = REPO_ROOT / "tests" / "fixtures" / "bootstrap" / "bootstrap-state.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        rec = start_drill(PLAYBOOK, now_fn=_past_now(30))
        rec.record_wave(0, "Network", 10, 12, True)
        rec.complete("success", gaps_found=["Nothing"], gaps_remediated=[])
        fixture["reconstruction_drills"] = [rec.to_dict()]
        self._validate(fixture)


if __name__ == "__main__":
    unittest.main()
