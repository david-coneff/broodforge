"""
test_phase25_reconstruction_validation.py — Phase 25: Reconstruction Validation.

Covers:
  25.1  DrillSchedule, DrillRun, plan_next_drill()
  25.2  RtoValidation, validate_rto()
  25.3  PostDrillComparison, compare_post_drill()
  25.4  RemediationItem, RemediationTracker
  25.5  FederationDrillScenario, plan_federation_drill()
        build_drill_summary_html()
"""



import federation_state as _fs
import reconstruction_validation as _rv

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _now():
    return "2026-06-01T12:00:00+00:00"


def _fed():
    fed = _fs.build_federation_state("fed-homelab", now_fn=_now)
    _fs.register_cell(fed, "pve01-cell", hostname="pve01", now_fn=_now)
    _fs.register_cell(fed, "pve02-cell", hostname="pve02", now_fn=_now)
    _fs.declare_recovery(fed, "pve01-cell", "pve02-cell", now_fn=_now)
    return fed


class _ReadinessStub:
    def __init__(self, score, components=None):
        self.overall_score = score
        self.components    = components or []

class _Component:
    def __init__(self, cid, score):
        self.component_id = cid
        self.score = score


# ===========================================================================
# 25.1 — Drill Scheduling
# ===========================================================================

class TestDrillSchedule:
    def test_no_last_drill_red_urgent(self):
        sched = _rv.DrillSchedule(cell_id="pve01-cell")
        r     = _rv.plan_next_drill(sched, now_fn=_now)
        assert r["due"] is True
        assert r["urgency"] == "RED"

    def test_recent_drill_green(self):
        recent = "2026-05-01T12:00:00+00:00"  # 31 days ago, interval=90
        sched  = _rv.DrillSchedule(cell_id="pve01-cell", interval_days=90,
                                    last_drill_at=recent)
        r      = _rv.plan_next_drill(sched, now_fn=_now)
        assert r["due"] is False
        assert r["urgency"] == "GREEN"

    def test_overdue_drill_orange(self):
        old    = "2026-02-01T12:00:00+00:00"  # ~120 days ago, interval=90
        sched  = _rv.DrillSchedule(cell_id="pve01-cell", interval_days=90,
                                    last_drill_at=old)
        r      = _rv.plan_next_drill(sched, now_fn=_now)
        assert r["due"] is True

    def test_failed_last_drill_elevates_urgency(self):
        recent = "2026-05-01T12:00:00+00:00"
        sched  = _rv.DrillSchedule(cell_id="pve01-cell", interval_days=90,
                                    last_drill_at=recent, last_drill_passed=False)
        r      = _rv.plan_next_drill(sched, now_fn=_now)
        assert r["urgency"] in ("ORANGE", "RED")

    def test_approaching_due_yellow(self):
        # 83 days ago with 90-day interval → due in 7d → within notify_before_days=7
        old    = "2026-03-10T12:00:00+00:00"  # ~83 days ago
        sched  = _rv.DrillSchedule(cell_id="pve01-cell", interval_days=90,
                                    last_drill_at=old, notify_before_days=7)
        r      = _rv.plan_next_drill(sched, now_fn=_now)
        assert r["urgency"] in ("YELLOW", "ORANGE", "RED")

    def test_reason_present(self):
        sched = _rv.DrillSchedule(cell_id="pve01-cell")
        r     = _rv.plan_next_drill(sched, now_fn=_now)
        assert r["reason"]


# ===========================================================================
# 25.2 — RTO Validation
# ===========================================================================

class TestRtoValidation:
    def test_well_under_target_green(self):
        r = _rv.validate_rto(60, 40)   # 33% margin
        assert r.score == "GREEN"
        assert r.compliant is True

    def test_just_under_target_yellow(self):
        r = _rv.validate_rto(60, 58)   # 3% margin
        assert r.score == "YELLOW"
        assert r.compliant is True

    def test_slightly_over_target_orange(self):
        r = _rv.validate_rto(60, 70)   # 17% over
        assert r.score == "ORANGE"
        assert r.compliant is False

    def test_far_over_target_red(self):
        r = _rv.validate_rto(60, 120)   # 100% over
        assert r.score == "RED"
        assert r.compliant is False

    def test_exactly_at_target_yellow(self):
        r = _rv.validate_rto(60, 60)
        assert r.score == "YELLOW"
        assert r.compliant is True

    def test_invalid_target_red(self):
        r = _rv.validate_rto(0, 10)
        assert r.score == "RED"

    def test_margin_pct_calculated(self):
        r = _rv.validate_rto(100, 80)  # 20% margin
        assert abs(r.margin_pct - 20.0) < 0.1

    def test_reason_includes_times(self):
        r = _rv.validate_rto(60, 45)
        assert "60" in r.reason
        assert "45" in r.reason


# ===========================================================================
# 25.3 — Post-Drill Assessment
# ===========================================================================

class TestPostDrillComparison:
    def test_improved(self):
        pre  = _ReadinessStub("ORANGE")
        post = _ReadinessStub("GREEN")
        r    = _rv.compare_post_drill("run-1", "cell-a", pre, post)
        assert r.score_improved is True
        assert r.score_regressed is False

    def test_regressed(self):
        pre  = _ReadinessStub("GREEN")
        post = _ReadinessStub("RED")
        r    = _rv.compare_post_drill("run-1", "cell-a", pre, post)
        assert r.score_regressed is True
        assert r.score_improved is False

    def test_no_change(self):
        pre  = _ReadinessStub("GREEN")
        post = _ReadinessStub("GREEN")
        r    = _rv.compare_post_drill("run-1", "cell-a", pre, post)
        assert r.score_improved is False
        assert r.score_regressed is False

    def test_component_changes_tracked(self):
        pre  = _ReadinessStub("GREEN", [_Component("db", "GREEN"), _Component("net", "ORANGE")])
        post = _ReadinessStub("GREEN", [_Component("db", "GREEN"), _Component("net", "GREEN")])
        r    = _rv.compare_post_drill("run-1", "cell-a", pre, post)
        assert any(c["id"] == "net" for c in r.component_changes)

    def test_fields_set(self):
        pre  = _ReadinessStub("YELLOW")
        post = _ReadinessStub("GREEN")
        r    = _rv.compare_post_drill("run-1", "cell-a", pre, post)
        assert r.drill_run_id  == "run-1"
        assert r.cell_id       == "cell-a"
        assert r.pre_drill_score  == "YELLOW"
        assert r.post_drill_score == "GREEN"


# ===========================================================================
# 25.4 — Remediation Tracker
# ===========================================================================

class TestRemediationTracker:
    def _tracker(self):
        t = _rv.RemediationTracker()
        t.add(_rv.RemediationItem("gap-01", "run-1", "ZFS pool health degraded",
                                   "CRITICAL", found_at=_now()))
        t.add(_rv.RemediationItem("gap-02", "run-1", "k3s token expired",
                                   "HIGH", found_at=_now()))
        return t

    def test_add_items(self):
        t = self._tracker()
        assert len(t.open_items()) == 2

    def test_resolve_item(self):
        t = self._tracker()
        t.resolve("gap-01", "Replaced failed disk", now_fn=_now)
        assert not any(i.item_id == "gap-01" and i.is_open for i in t._items)

    def test_resolve_unknown_returns_false(self):
        t = self._tracker()
        assert t.resolve("nonexistent", "fix") is False

    def test_critical_open(self):
        t = self._tracker()
        assert len(t.critical_open()) == 1

    def test_summary(self):
        t = self._tracker()
        t.resolve("gap-01", "fixed")
        s = t.summary()
        assert s["total"] == 2
        assert s["open"] == 1
        assert s["resolved"] == 1
        assert s["critical_open"] == 0

    def test_resolved_item_not_in_open(self):
        t = self._tracker()
        t.resolve("gap-01", "fixed")
        open_ids = {i.item_id for i in t.open_items()}
        assert "gap-01" not in open_ids

    def test_is_open_property(self):
        item = _rv.RemediationItem("x", "r", "desc", "LOW")
        assert item.is_open is True
        item.status = "resolved"
        assert item.is_open is False


# ===========================================================================
# 25.5 — Federation Drill
# ===========================================================================

class TestFederationDrill:
    def test_builds_scenario(self):
        fed = _fed()
        s   = _rv.plan_federation_drill(fed, "pve01-cell", now_fn=_now)
        assert isinstance(s, _rv.FederationDrillScenario)

    def test_has_steps(self):
        fed = _fed()
        s   = _rv.plan_federation_drill(fed, "pve01-cell", now_fn=_now)
        assert len(s.steps) >= 5

    def test_subject_cell_set(self):
        fed = _fed()
        s   = _rv.plan_federation_drill(fed, "pve01-cell", now_fn=_now)
        assert s.subject_cell == "pve01-cell"

    def test_federation_id_set(self):
        fed = _fed()
        s   = _rv.plan_federation_drill(fed, "pve01-cell", now_fn=_now)
        assert s.federation_id == "fed-homelab"

    def test_tabletop_default(self):
        fed = _fed()
        s   = _rv.plan_federation_drill(fed, "pve01-cell", now_fn=_now)
        assert s.mode == "tabletop"

    def test_live_mode(self):
        fed = _fed()
        s   = _rv.plan_federation_drill(fed, "pve01-cell", mode="live", now_fn=_now)
        assert s.mode == "live"

    def test_total_minutes_positive(self):
        fed = _fed()
        s   = _rv.plan_federation_drill(fed, "pve01-cell", now_fn=_now)
        assert s.total_estimated_minutes and s.total_estimated_minutes > 0

    def test_rto_target_set(self):
        fed = _fed()
        s   = _rv.plan_federation_drill(fed, "pve01-cell", rto_minutes=120, now_fn=_now)
        assert s.rto_target_minutes == 120

    def test_steps_sequential(self):
        fed  = _fed()
        s    = _rv.plan_federation_drill(fed, "pve01-cell", now_fn=_now)
        nums = [st.step_number for st in s.steps]
        assert nums == sorted(nums)


# ===========================================================================
# build_drill_summary_html
# ===========================================================================

class TestBuildDrillSummaryHtml:
    def _run(self, status="passed"):
        return _rv.DrillRun(
            run_id="run-2026-06-01", cell_id="pve01-cell",
            mode="tabletop", started_at=_now(), status=status,
            rto_target_minutes=60, rto_actual_minutes=45,
            gaps_found=["ZFS status DEGRADED", "k3s token near expiry"],
        )

    def test_returns_string(self):
        html = _rv.build_drill_summary_html(self._run())
        assert isinstance(html, str)

    def test_includes_run_id(self):
        html = _rv.build_drill_summary_html(self._run())
        assert "run-2026-06-01" in html

    def test_includes_status_badge(self):
        html = _rv.build_drill_summary_html(self._run(status="passed"))
        assert "PASSED" in html

    def test_includes_gaps(self):
        html = _rv.build_drill_summary_html(self._run())
        assert "ZFS" in html

    def test_includes_rto_with_validation(self):
        rto_v = _rv.validate_rto(60, 45)
        html  = _rv.build_drill_summary_html(self._run(), rto_validation=rto_v)
        assert "60" in html

    def test_includes_remediation_summary(self):
        t = _rv.RemediationTracker()
        t.add(_rv.RemediationItem("g1", "r1", "Disk issue", "CRITICAL"))
        html = _rv.build_drill_summary_html(self._run(), remediation=t)
        assert "Remediation" in html
