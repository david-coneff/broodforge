#!/usr/bin/env python3
"""
readiness_report.py — Standalone readiness report generator.

Produces:
  Readiness-Report.json  — machine-readable full report
  Readiness-Report.md    — human-readable summary with recommended actions
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SCORE_ICON = {
    "GREEN":   "✓",
    "YELLOW":  "⚠",
    "ORANGE":  "⚠",
    "RED":     "✗",
    "BLOCKED": "⛔",
    "UNKNOWN": "?",
}

GAP_PRIORITY = {
    "RED":    1,
    "ORANGE": 2,
    "YELLOW": 3,
    "GREEN":  4,
}


def build_readiness_report_json(
    manifest: dict,
    graph,
    readiness,
    generation_meta: dict,
) -> dict:
    """Build the full machine-readable readiness report dict."""
    node_map = graph.node_map()
    all_gaps = [g for c in readiness.components for g in c.gaps]

    return {
        "schema_version":  "1.0",
        "generated_at":    generation_meta.get("generated_at"),
        "assessment_id":   generation_meta.get("collected_at"),
        "host":            manifest.get("host", {}).get("hostname"),

        "dependency_graph": graph.to_dict(),

        "readiness_report": {
            "overall_score":         readiness.overall_score,
            "overall_score_reason":  readiness.overall_score_reason,
            "components":            [c.to_dict() for c in readiness.components],
            "single_points_of_failure": readiness.single_points_of_failure,
            "recovery_blockers":     readiness.recovery_blockers,
        },

        "summary": {
            "total_components": len(readiness.components),
            "score_counts": _score_counts(readiness),
            "total_gaps": len(all_gaps),
            "gap_counts": _gap_counts(all_gaps),
            "spof_count": len(readiness.single_points_of_failure),
            "blocker_count": len(readiness.recovery_blockers),
            "estimated_restore_minutes": sum(
                w.estimated_minutes or 0 for w in graph.restore_waves
            ),
        },
    }


def build_readiness_report_md(
    manifest: dict,
    graph,
    readiness,
    generation_meta: dict,
) -> str:
    node_map = graph.node_map()
    hostname    = manifest.get("host", {}).get("hostname", "unknown")
    collected   = manifest.get("collected_at", "unknown")
    generated   = generation_meta.get("generated_at", "unknown")
    all_gaps    = sorted(
        [g for c in readiness.components for g in c.gaps],
        key=lambda g: (GAP_PRIORITY.get(g.severity, 9), g.component_id)
    )
    total_mins  = sum(w.estimated_minutes or 0 for w in graph.restore_waves)
    sc          = _score_counts(readiness)

    lines = [
        f"# Recovery Readiness Report",
        f"",
        f"**Host:**        {hostname}",
        f"**Assessment:**  {collected}",
        f"**Generated:**   {generated}",
        f"",
        "---",
        "",
        f"## Overall: {SCORE_ICON.get(readiness.overall_score, '?')} {readiness.overall_score}",
        f"",
        f"{readiness.overall_score_reason}",
        "",
    ]

    # Score summary table
    lines += [
        "## Component Scores",
        "",
        "| Score | Count |",
        "|-------|-------|",
    ]
    for s in ("GREEN", "YELLOW", "ORANGE", "RED", "BLOCKED"):
        n = sc.get(s, 0)
        if n:
            lines.append(f"| {SCORE_ICON.get(s,'')} {s} | {n} |")

    lines += [""]

    # Per-component table
    lines += [
        "### Detail",
        "",
        "| Component | Score | Backup Age | Tested | Note |",
        "|-----------|-------|-----------|--------|------|",
    ]
    for cr in sorted(readiness.components,
                     key=lambda c: (SCORE_RANK_DESC(c.score), c.component_id)):
        node = node_map.get(cr.component_id)
        label = node.label if node else cr.component_id
        icon  = SCORE_ICON.get(cr.score, "?")
        age   = f"{cr.backup_age_days:.0f}d" if cr.backup_age_days is not None else "—"
        tested = "✓" if cr.restore_tested else ("—" if cr.restore_tested is None else "✗")
        note  = cr.score_reason[:60] + "…" if len(cr.score_reason) > 60 else cr.score_reason
        lines.append(f"| {label} | {icon} {cr.score} | {age} | {tested} | {note} |")

    lines += [""]

    # Gaps — prioritised
    if all_gaps:
        lines += [
            f"## Gaps Requiring Attention ({len(all_gaps)})",
            "",
        ]
        for gap in all_gaps:
            node  = node_map.get(gap.component_id)
            label = node.label if node else gap.component_id
            icon  = SCORE_ICON.get(gap.severity, "?")
            lines += [
                f"### {icon} [{gap.severity}] {label} — {gap.gap_type}",
                f"",
                f"**Issue:** {gap.description}",
            ]
            if gap.remediation:
                lines.append(f"**Fix:** {gap.remediation}")
            if gap.readiness_impact:
                lines.append(f"**Impact:** {gap.readiness_impact}")
            lines.append("")

    # Recommended actions (prioritised)
    lines += [
        "## Recommended Actions",
        "",
    ]
    actions = _recommended_actions(readiness, node_map, all_gaps)
    for i, action in enumerate(actions, 1):
        lines.append(f"{i}. {action}")
    lines.append("")

    # SPOFs
    if readiness.single_points_of_failure:
        lines += [
            "## Single Points of Failure",
            "",
        ]
        for spof_id in readiness.single_points_of_failure:
            node = node_map.get(spof_id)
            dep_count = sum(1 for e in graph.edges if e.to_id == spof_id)
            label = node.label if node else spof_id
            lines.append(
                f"- **{label}** — {dep_count} component(s) depend on this. "
                "Consider offsite backup or redundancy."
            )
        lines.append("")

    # Restore sequence summary
    lines += [
        "## Restore Sequence Summary",
        "",
        f"Total estimated time: **{total_mins} minutes** across {len(graph.restore_waves)} wave(s).",
        "",
        "| Wave | Components | Est. Time |",
        "|------|-----------|----------|",
    ]
    for wave in graph.restore_waves:
        labels = [node_map[c].label for c in wave.component_ids if c in node_map]
        est = f"{wave.estimated_minutes}m" if wave.estimated_minutes else "—"
        lines.append(f"| {wave.wave} | {', '.join(labels)} | {est} |")

    lines += [
        "",
        "---",
        f"*Generated by Assessment Engine doc-gen — {generated}*",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def SCORE_RANK_DESC(score: str) -> int:
    """Higher rank = worse score (for sorting worst-first)."""
    return -SCORE_RANK_ASCE(score)

def SCORE_RANK_ASCE(score: str) -> int:
    return {"GREEN": 0, "YELLOW": 1, "ORANGE": 2, "RED": 3, "BLOCKED": 4, "UNKNOWN": 5}.get(score, 9)


def _score_counts(readiness) -> dict:
    from collections import Counter
    return dict(Counter(c.score for c in readiness.components))


def _gap_counts(gaps: list) -> dict:
    from collections import Counter
    return dict(Counter(g.severity for g in gaps))


def _recommended_actions(readiness, node_map: dict, gaps: list) -> list[str]:
    """Generate a prioritised list of recommended remediation actions."""
    actions = []

    # RED first
    red_gaps = [g for g in gaps if g.severity == "RED"]
    for g in red_gaps:
        node = node_map.get(g.component_id)
        label = node.label if node else g.component_id
        if g.remediation:
            actions.append(f"**[CRITICAL]** {label}: {g.remediation}")

    # Recovery blockers
    for bid in readiness.recovery_blockers:
        node = node_map.get(bid)
        if node:
            blocked = [
                node_map[c.component_id].label
                for c in readiness.components
                if c.blocked_by == bid and c.component_id in node_map
            ]
            if blocked:
                actions.append(
                    f"**[CRITICAL]** Resolve RED status of {node.label} "
                    f"to unblock: {', '.join(blocked)}"
                )

    # ORANGE gaps
    for g in [g for g in gaps if g.severity == "ORANGE"]:
        node = node_map.get(g.component_id)
        label = node.label if node else g.component_id
        if g.remediation:
            actions.append(f"**[HIGH]** {label}: {g.remediation}")

    # Untested restores (YELLOW)
    untested = [
        g for g in gaps
        if g.gap_type == "UNTESTED_RESTORE" and g.severity == "YELLOW"
    ]
    if untested:
        labels = [
            (node_map[g.component_id].label if g.component_id in node_map else g.component_id)
            for g in untested
        ]
        actions.append(
            f"**[MEDIUM]** Perform restore tests for: {', '.join(labels)}"
        )

    # SPOFs
    if readiness.single_points_of_failure:
        spof_labels = [
            node_map[s].label for s in readiness.single_points_of_failure
            if s in node_map
        ]
        actions.append(
            f"**[MEDIUM]** Review single points of failure: {', '.join(spof_labels)} "
            "— consider offsite backup or replication"
        )

    # Stale backups (YELLOW)
    stale = [g for g in gaps if g.gap_type == "STALE_BACKUP" and g.severity == "YELLOW"]
    for g in stale:
        node = node_map.get(g.component_id)
        label = node.label if node else g.component_id
        actions.append(f"**[LOW]** {label}: {g.remediation or 'Verify backup schedule'}")

    if not actions:
        actions.append("No immediate actions required — all components within acceptable thresholds.")

    return actions
