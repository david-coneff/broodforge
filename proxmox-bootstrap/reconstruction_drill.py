#!/usr/bin/env python3
"""
reconstruction_drill.py — Reconstruction drill framework (Phase 12).

Provides:
  DrillRecord         — tracks a single reconstruction drill run
  start_drill()       — initialize a new drill record from a phoenix playbook
  save_drill_record() — merge completed drill record into bootstrap-state.json
  generate_drill_report() — produce a Markdown drill summary
  get_last_drill()    — retrieve the most recent drill record from state

A reconstruction drill exercises the phoenix playbook against the real
(or a test) environment to:
  - Validate that the playbook is accurate and complete
  - Measure actual vs. estimated restoration time per wave
  - Surface gaps that only appear during live execution
  - Produce a committed drill record as evidence of tested recoverability

Stdlib only.
"""

from datetime import datetime, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def _ts(dt: Optional[datetime] = None) -> str:
    if dt is None:
        dt = _now_utc()
    return dt.strftime("%Y-%m-%d_%H_%M_%S")


# ---------------------------------------------------------------------------
# DrillRecord
# ---------------------------------------------------------------------------

class DrillRecord:
    """
    Tracks the execution of one reconstruction drill run.

    Usage:
        rec = start_drill(playbook, cell_id="proxmox-cell-a")
        for wave in waves:
            # ... execute wave steps ...
            rec.record_wave(wave_num=wave["wave"], wave_name=wave["name"],
                            estimated_minutes=wave["estimated_minutes"],
                            actual_minutes=measured_minutes, completed=True)
        rec.complete(outcome="success", gaps_found=["Bridge vmbr1 was missing"],
                     gaps_remediated=["Added vmbr1 to network-topology.yaml"])
        save_drill_record(state, rec)
    """

    def __init__(
        self,
        cell_id: str,
        playbook_generated_at: Optional[str] = None,
        total_estimated_minutes: Optional[int] = None,
        now_fn=None,
    ):
        self._now     = now_fn or _now_utc
        start         = self._now()
        self.drill_id = f"{cell_id}_{_ts(start)}"
        self.started_at            = start.isoformat()
        self.completed_at          = None
        self.playbook_generated_at = playbook_generated_at
        self.outcome               = None
        self.total_estimated_minutes = total_estimated_minutes
        self.total_actual_minutes    = None
        self.wave_timings: list[dict] = []
        self.gaps_found:       list[str] = []
        self.gaps_remediated:  list[str] = []
        self.notes: Optional[str] = None

    def record_wave(
        self,
        wave_num,
        wave_name: str,
        estimated_minutes: Optional[int] = None,
        actual_minutes: Optional[int] = None,
        completed: bool = True,
    ) -> "DrillRecord":
        """Record timing for a completed (or skipped) wave."""
        self.wave_timings.append({
            "wave":              wave_num,
            "name":              wave_name,
            "estimated_minutes": estimated_minutes,
            "actual_minutes":    actual_minutes,
            "completed":         completed,
        })
        return self

    def complete(
        self,
        outcome: str,
        gaps_found: Optional[list[str]] = None,
        gaps_remediated: Optional[list[str]] = None,
        notes: Optional[str] = None,
    ) -> "DrillRecord":
        """
        Finalize the drill record.
        outcome: 'success' | 'partial' | 'failed' | 'aborted'
        """
        end_time = self._now()
        self.completed_at     = end_time.isoformat()
        self.outcome          = outcome
        self.gaps_found       = list(gaps_found or [])
        self.gaps_remediated  = list(gaps_remediated or [])
        self.notes            = notes

        # Calculate actual total minutes from wave timings
        wave_actuals = [w["actual_minutes"] for w in self.wave_timings
                        if w.get("actual_minutes") is not None]
        if wave_actuals:
            self.total_actual_minutes = sum(wave_actuals)

        return self

    def to_dict(self) -> dict:
        """Serialize to the reconstruction_drill_record schema dict."""
        return {
            "drill_id":              self.drill_id,
            "started_at":            self.started_at,
            "completed_at":          self.completed_at,
            "playbook_generated_at": self.playbook_generated_at,
            "outcome":               self.outcome,
            "total_estimated_minutes": self.total_estimated_minutes,
            "total_actual_minutes":    self.total_actual_minutes,
            "wave_timings":           self.wave_timings,
            "gaps_found":             self.gaps_found,
            "gaps_remediated":        self.gaps_remediated,
            "notes":                  self.notes,
        }

    @property
    def accuracy_pct(self) -> Optional[float]:
        """Estimate accuracy: actual / estimated × 100.  None if not calculable."""
        if self.total_actual_minutes and self.total_estimated_minutes:
            return round(self.total_actual_minutes / self.total_estimated_minutes * 100, 1)
        return None

    @property
    def completed_waves(self) -> int:
        return sum(1 for w in self.wave_timings if w.get("completed"))

    @property
    def total_waves(self) -> int:
        return len(self.wave_timings)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def start_drill(
    playbook: dict,
    cell_id: Optional[str] = None,
    now_fn=None,
) -> DrillRecord:
    """
    Initialize a DrillRecord from a phoenix playbook dict.

    Args:
        playbook: phoenix playbook dict from build_phoenix_playbook()
        cell_id:  override cell_id (uses playbook value if None)
        now_fn:   injectable datetime function for tests
    """
    cid = cell_id or playbook.get("cell_id", "unknown-cell")
    return DrillRecord(
        cell_id=cid,
        playbook_generated_at=playbook.get("generated_at"),
        total_estimated_minutes=playbook.get("estimated_total_minutes"),
        now_fn=now_fn,
    )


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def save_drill_record(state: dict, record: DrillRecord) -> dict:
    """
    Merge a completed drill record into bootstrap-state.json dict.
    Keeps all drills (no rotation — drill history is permanent record).
    Returns the modified state.
    """
    drills = state.setdefault("reconstruction_drills", [])
    drills.insert(0, record.to_dict())   # most recent first
    return state


def get_last_drill(state: dict) -> Optional[dict]:
    """Return the most recent drill record, or None."""
    drills = state.get("reconstruction_drills") or []
    return drills[0] if drills else None


# ---------------------------------------------------------------------------
# 12.2 — Drill report generator (Markdown)
# ---------------------------------------------------------------------------

def generate_drill_report(record: DrillRecord, cell_id: Optional[str] = None) -> str:
    """
    Generate a Markdown summary of a completed drill run.
    Suitable for committing to Forgejo alongside bootstrap-state.json.
    """
    lines = [
        "# Reconstruction Drill Report",
        "",
        f"**Drill ID:** `{record.drill_id}`",
        f"**Started:**  {record.started_at}",
        f"**Completed:** {record.completed_at or '(not completed)'}",
        f"**Outcome:** {(record.outcome or 'unknown').upper()}",
        "",
    ]

    if record.total_estimated_minutes and record.total_actual_minutes:
        pct = record.accuracy_pct
        lines += [
            "## Timing",
            "",
            "| | Minutes |",
            "|---|---|",
            f"| Estimated | {record.total_estimated_minutes} |",
            f"| Actual    | {record.total_actual_minutes} |",
            f"| Accuracy  | {pct}% of estimate |",
            "",
        ]

    if record.wave_timings:
        lines += [
            "## Wave Timings",
            "",
            "| Wave | Name | Estimated (min) | Actual (min) | Completed |",
            "|---|---|---|---|---|",
        ]
        for w in record.wave_timings:
            done = "✓" if w.get("completed") else "✗"
            est  = str(w.get("estimated_minutes") or "—")
            act  = str(w.get("actual_minutes") or "—")
            lines.append(f"| {w['wave']} | {w['name']} | {est} | {act} | {done} |")
        lines.append("")

    if record.gaps_found:
        lines += [
            "## Gaps Found",
            "",
        ] + [f"- {g}" for g in record.gaps_found] + [""]

    if record.gaps_remediated:
        lines += [
            "## Gaps Remediated",
            "",
        ] + [f"- {g}" for g in record.gaps_remediated] + [""]

    if record.notes:
        lines += ["## Notes", "", record.notes, ""]

    lines += [
        "---",
        "",
        "*Generated by broodforge reconstruction-drill.py. "
        "Commit this report to Forgejo alongside the updated bootstrap-state.json.*",
    ]

    return "\n".join(lines) + "\n"
