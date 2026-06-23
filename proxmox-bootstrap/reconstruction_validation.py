#!/usr/bin/env python3
"""
reconstruction_validation.py — Reconstruction Validation (Phase 25).

Provides the framework for scheduled reconstruction drills and validation:
  - Drill scheduling (every 90 days; live or tabletop mode)
  - Reconstruction time measurement and RTO validation
  - Automated post-reconstruction assessment and comparison
  - Gap identification and remediation tracking
  - Federation drill (multi-cell coordinated scenario)

25.1  DrillSchedule     — schedule reconstruction drills
25.2  RtoValidation     — validate actual vs declared RTO
25.3  PostDrillAssessment — compare before/after readiness
25.4  RemediationTracker — track gaps found during drill
25.5  FederationDrill   — multi-cell coordinated drill scenario

Provides:
  DrillSchedule              — drill schedule definition
  DrillRun                   — a single drill execution record
  plan_next_drill()          — determine if a drill is overdue
  RtoValidation              — RTO target vs actual comparison
  validate_rto()             — score RTO compliance
  PostDrillComparison        — readiness before vs after comparison
  compare_post_drill()       — build before/after comparison
  RemediationItem            — a gap found during drill
  RemediationTracker         — track gap status across drills
  FederationDrillScenario    — multi-cell coordinated drill
  plan_federation_drill()    — build a federation drill plan
  build_drill_summary_html() — HTML drill summary report

Stdlib only.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

# ---------------------------------------------------------------------------
# 25.1 — Drill Scheduling
# ---------------------------------------------------------------------------

@dataclass
class DrillSchedule:
    """Definition of the reconstruction drill schedule for a cell."""
    cell_id:               str
    interval_days:         int   = 90
    last_drill_at:         Optional[str] = None
    last_drill_passed:     Optional[bool] = None
    drill_mode:            str   = "tabletop"   # "tabletop" | "live"
    notify_before_days:    int   = 7


@dataclass
class DrillRun:
    """Record of a single drill execution."""
    run_id:              str
    cell_id:             str
    mode:                str    # "tabletop" | "live"
    started_at:          str
    completed_at:        Optional[str]   = None
    status:              str   = "pending"   # pending|running|passed|failed|aborted
    rto_target_minutes:  Optional[int]   = None
    rto_actual_minutes:  Optional[int]   = None
    gaps_found:          list[str]       = field(default_factory=list)
    gaps_remediated:     int             = 0
    notes:               Optional[str]   = None


def plan_next_drill(
    schedule: DrillSchedule,
    *,
    now_fn: Optional[Callable[[], str]] = None,
) -> dict:
    """
    Determine if a drill is due and when.

    Returns: {due: bool, overdue_days: int, next_drill_at: str, urgency: str}
    """
    now_str = (now_fn or (lambda: datetime.now(timezone.utc).isoformat()))()
    now     = datetime.fromisoformat(now_str.replace("Z", "+00:00"))

    if schedule.last_drill_at is None:
        return {
            "due": True,
            "overdue_days": schedule.interval_days,
            "next_drill_at": now_str,
            "urgency": "RED",
            "reason": "No drill on record — schedule immediately.",
        }

    try:
        last = datetime.fromisoformat(schedule.last_drill_at.replace("Z", "+00:00"))
        days_since = (now - last).days
    except (ValueError, AttributeError):
        days_since = schedule.interval_days

    due_at    = last + timedelta(days=schedule.interval_days)
    notify_at = due_at - timedelta(days=schedule.notify_before_days)
    is_due    = now >= due_at
    overdue   = max(0, (now - due_at).days)

    urgency = "GREEN"
    if is_due and overdue > 30:
        urgency = "RED"
    elif is_due:
        urgency = "ORANGE"
    elif now >= notify_at:
        urgency = "YELLOW"

    if schedule.last_drill_passed is False:
        urgency = max(urgency, "ORANGE", key=lambda s: {"GREEN":0,"YELLOW":1,"ORANGE":2,"RED":3}.get(s,0))

    return {
        "due":           is_due,
        "overdue_days":  overdue,
        "days_until_due": max(0, (due_at - now).days),
        "next_drill_at": due_at.isoformat(),
        "urgency":       urgency,
        "reason":        (
            f"Last drill: {days_since} days ago. "
            + ("OVERDUE." if is_due else f"Due in {max(0,(due_at-now).days)} days.")
            + (" Last drill FAILED — remediation required." if schedule.last_drill_passed is False else "")
        ),
    }


# ---------------------------------------------------------------------------
# 25.2 — RTO Validation
# ---------------------------------------------------------------------------

@dataclass
class RtoValidation:
    """Result of RTO compliance check."""
    rto_target_minutes: int
    rto_actual_minutes: int
    compliant:          bool
    margin_pct:         float    # % under target (+) or over (-)
    score:              str      # GREEN/YELLOW/ORANGE/RED
    reason:             str


def validate_rto(
    target_minutes: int,
    actual_minutes: int,
) -> RtoValidation:
    """
    Score RTO compliance.

    GREEN:  actual < target × 0.80 (more than 20% margin)
    YELLOW: actual < target (met, but close)
    ORANGE: actual < target × 1.25 (over by ≤25%)
    RED:    actual >= target × 1.25 (over by >25%)
    """
    if target_minutes <= 0:
        return RtoValidation(target_minutes, actual_minutes, False, 0.0, "RED",
                             "Invalid RTO target (≤0).")
    margin = (target_minutes - actual_minutes) / target_minutes * 100.0
    compliant = actual_minutes <= target_minutes

    if actual_minutes < target_minutes * 0.80:
        score = "GREEN"
    elif actual_minutes <= target_minutes:
        score = "YELLOW"
    elif actual_minutes <= target_minutes * 1.25:
        score = "ORANGE"
    else:
        score = "RED"

    return RtoValidation(
        rto_target_minutes=target_minutes,
        rto_actual_minutes=actual_minutes,
        compliant=compliant,
        margin_pct=margin,
        score=score,
        reason=(
            f"Target: {target_minutes}m  Actual: {actual_minutes}m  "
            f"Margin: {margin:+.0f}%  {'PASS' if compliant else 'FAIL'}."
        ),
    )


# ---------------------------------------------------------------------------
# 25.3 — Post-Drill Assessment
# ---------------------------------------------------------------------------

@dataclass
class PostDrillComparison:
    """Readiness before vs after a drill."""
    drill_run_id:       str
    cell_id:            str
    pre_drill_score:    str
    post_drill_score:   str
    score_improved:     bool
    score_regressed:    bool
    component_changes:  list[dict] = field(default_factory=list)
    # [{id, pre_score, post_score}]


_SCORE_ORDER = {"GREEN": 0, "YELLOW": 1, "ORANGE": 2, "RED": 3, "BLOCKED": 4}


def compare_post_drill(
    drill_run_id:     str,
    cell_id:          str,
    pre_readiness:    Any,    # readiness object with .overall_score and .components
    post_readiness:   Any,
) -> PostDrillComparison:
    """Build a before/after readiness comparison for a drill."""
    pre_score  = getattr(pre_readiness, "overall_score", "?")
    post_score = getattr(post_readiness, "overall_score", "?")
    pre_ord    = _SCORE_ORDER.get(pre_score, 99)
    post_ord   = _SCORE_ORDER.get(post_score, 99)

    # Per-component changes
    changes: list[dict] = []
    pre_comps  = {c.component_id: c.score for c in getattr(pre_readiness, "components", [])}
    post_comps = {c.component_id: c.score for c in getattr(post_readiness, "components", [])}
    all_ids    = set(pre_comps) | set(post_comps)
    for cid in sorted(all_ids):
        pre_s  = pre_comps.get(cid, "?")
        post_s = post_comps.get(cid, "?")
        if pre_s != post_s:
            changes.append({"id": cid, "pre_score": pre_s, "post_score": post_s})

    return PostDrillComparison(
        drill_run_id=drill_run_id,
        cell_id=cell_id,
        pre_drill_score=pre_score,
        post_drill_score=post_score,
        score_improved=post_ord < pre_ord,
        score_regressed=post_ord > pre_ord,
        component_changes=changes,
    )


# ---------------------------------------------------------------------------
# 25.4 — Gap / Remediation Tracking
# ---------------------------------------------------------------------------

@dataclass
class RemediationItem:
    """A gap identified during a reconstruction drill."""
    item_id:        str
    drill_run_id:   str
    description:    str
    severity:       str   # "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"
    status:         str   = "open"   # open|in-progress|resolved|deferred
    found_at:       Optional[str] = None
    resolved_at:    Optional[str] = None
    resolution:     Optional[str] = None
    assigned_to:    Optional[str] = None

    @property
    def is_open(self) -> bool:
        return self.status in ("open", "in-progress")


class RemediationTracker:
    """Tracks gaps found across multiple drills."""

    def __init__(self) -> None:
        self._items: list[RemediationItem] = []

    def add(self, item: RemediationItem) -> None:
        self._items.append(item)

    def resolve(self, item_id: str, resolution: str, *, now_fn: Optional[Callable] = None) -> bool:
        now = (now_fn or (lambda: datetime.now(timezone.utc).isoformat()))()
        for item in self._items:
            if item.item_id == item_id:
                item.status       = "resolved"
                item.resolved_at  = now
                item.resolution   = resolution
                return True
        return False

    def open_items(self) -> list[RemediationItem]:
        return [i for i in self._items if i.is_open]

    def critical_open(self) -> list[RemediationItem]:
        return [i for i in self.open_items() if i.severity == "CRITICAL"]

    def summary(self) -> dict:
        return {
            "total":    len(self._items),
            "open":     len(self.open_items()),
            "resolved": sum(1 for i in self._items if i.status == "resolved"),
            "critical_open": len(self.critical_open()),
        }


# ---------------------------------------------------------------------------
# 25.5 — Federation Drill
# ---------------------------------------------------------------------------

@dataclass
class FederationDrillStep:
    step_number: int
    name:        str
    cells:       list[str]    # cells involved in this step
    description: str
    expected_minutes: Optional[int] = None


@dataclass
class FederationDrillScenario:
    """Multi-cell coordinated reconstruction drill scenario."""
    scenario_id:   str
    federation_id: str
    subject_cell:  str
    mode:          str    # "tabletop" | "live"
    steps:         list[FederationDrillStep] = field(default_factory=list)
    total_estimated_minutes: Optional[int] = None
    rto_target_minutes:      Optional[int] = None


def plan_federation_drill(
    federation_state:  Any,
    subject_cell_id:   str,
    *,
    mode:     str = "tabletop",
    rto_minutes: Optional[int] = None,
    now_fn: Optional[Callable[[], str]] = None,
) -> FederationDrillScenario:
    """
    Build a federation drill scenario: coordinator recovers subject.

    Steps model the full federated reconstruction sequence in tabletop or live mode.
    """
    import hashlib
    now  = (now_fn or (lambda: datetime.now(timezone.utc).isoformat()))()
    sid  = hashlib.sha256(f"drill:{subject_cell_id}:{now}".encode()).hexdigest()[:10]

    coordinators = federation_state.coordinators_for(subject_cell_id)
    coord_label  = coordinators[0] if coordinators else "[COORDINATOR]"
    all_cells    = [subject_cell_id] + coordinators

    steps = [
        FederationDrillStep(1, "Declare failure scenario", all_cells,
                            f"{'Simulate' if mode == 'tabletop' else 'Confirm'} {subject_cell_id} failure",
                            expected_minutes=5),
        FederationDrillStep(2, "Activate coordinator", [coord_label],
                            f"{coord_label} activates as recovery coordinator",
                            expected_minutes=5),
        FederationDrillStep(3, "Establish trust", all_cells,
                            "Generate and verify temporary cross-cell trust tokens",
                            expected_minutes=10),
        FederationDrillStep(4, "Retrieve bootstrap state", [coord_label],
                            f"{coord_label} locates latest {subject_cell_id} bootstrap state from backup",
                            expected_minutes=10),
        FederationDrillStep(5, "Provision hardware", [subject_cell_id],
                            f"{'Simulate' if mode == 'tabletop' else 'Provision'} replacement hardware for {subject_cell_id}",
                            expected_minutes=30 if mode == "live" else 5),
        FederationDrillStep(6, "Restore from backup", [coord_label, subject_cell_id],
                            f"{coord_label} executes restore-from-backup.py → {subject_cell_id}",
                            expected_minutes=45 if mode == "live" else 10),
        FederationDrillStep(7, "Verify services", [subject_cell_id],
                            "Run post-reconstruction assessment on restored cell",
                            expected_minutes=15),
        FederationDrillStep(8, "Rejoin federation", all_cells,
                            f"{subject_cell_id} re-registers in federation; run Tier 3 assessment",
                            expected_minutes=10),
    ]

    total = sum(s.expected_minutes or 0 for s in steps)

    return FederationDrillScenario(
        scenario_id=sid,
        federation_id=getattr(federation_state, "federation_id", "?"),
        subject_cell=subject_cell_id,
        mode=mode,
        steps=steps,
        total_estimated_minutes=total,
        rto_target_minutes=rto_minutes,
    )


# ---------------------------------------------------------------------------
# HTML drill summary (for embedding in reports)
# ---------------------------------------------------------------------------

def build_drill_summary_html(
    drill_run:       DrillRun,
    rto_validation:  Optional[RtoValidation]     = None,
    post_comparison: Optional[PostDrillComparison] = None,
    remediation:     Optional[RemediationTracker]  = None,
) -> str:
    """Build an HTML snippet summarising a drill run."""
    from html import escape

    status_badges = {
        "passed":  '<span class="score score-green">PASSED</span>',
        "failed":  '<span class="score score-red">FAILED</span>',
        "aborted": '<span class="score score-yellow">ABORTED</span>',
        "pending": '<span class="score score-blocked">PENDING</span>',
    }
    badge = status_badges.get(drill_run.status, drill_run.status)

    lines = [
        f"<h3>Drill: {escape(drill_run.run_id)}</h3>",
        f"<p>Cell: {escape(drill_run.cell_id)}  |  Mode: {escape(drill_run.mode)}  |  Status: {badge}</p>",
        f"<p>Started: {escape(drill_run.started_at or '?')}</p>",
    ]
    if drill_run.rto_target_minutes and drill_run.rto_actual_minutes:
        lines.append(
            f"<p>RTO: target {drill_run.rto_target_minutes}m, "
            f"actual {drill_run.rto_actual_minutes}m</p>"
        )
    if rto_validation:
        rto_badge = status_badges.get("passed" if rto_validation.compliant else "failed",
                                       rto_validation.score)
        lines.append(f"<p>RTO compliance: {rto_badge} — {escape(rto_validation.reason)}</p>")
    if drill_run.gaps_found:
        gaps_html = "".join(f"<li>{escape(g)}</li>" for g in drill_run.gaps_found)
        lines.append(f"<h4>Gaps Found</h4><ul>{gaps_html}</ul>")
    if post_comparison:
        arrow = "⬆" if post_comparison.score_improved else ("⬇" if post_comparison.score_regressed else "↔")
        lines.append(
            f"<p>Readiness: {escape(post_comparison.pre_drill_score)} → "
            f"{escape(post_comparison.post_drill_score)} {arrow}</p>"
        )
    if remediation:
        s = remediation.summary()
        lines.append(
            f"<p>Remediation: {s['open']} open / {s['resolved']} resolved / "
            f"{s['critical_open']} critical open</p>"
        )
    return "\n".join(lines)
