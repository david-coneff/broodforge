#!/usr/bin/env python3
"""
twin_consistency_checker.py — Digital Twin consistency checker (Phase 17.5).

Detects stale, missing, and conflicting state in the digital twin for a cell.
Produces a consistency report that feeds into assessment scoring.

Consistency checks:
  Missing state:    a state category file does not exist in the twin
  Stale state:      a state category was last written beyond its threshold
  Cell ID conflict: a state document's cell_id does not match the twin's cell_id
  Version mismatch: a state document's schema_version is not the current version

Provides:
  ConsistencyFinding         — a single finding (severity, category, message)
  ConsistencyReport          — collection of findings for one cell
  check_twin_consistency()   — main entry point
  summarise_consistency()    — human-readable summary
  is_twin_consistent()       — True if no ERROR findings

Stdlib only.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import json

try:
    from twin_state_writer import (
        TwinPaths, StalenessManifest, update_staleness,
        ALL_STATE_CATEGORIES, STALENESS_THRESHOLDS,
    )
except ImportError:
    # Graceful import for testing without the full module chain
    TwinPaths = None  # type: ignore
    StalenessManifest = None  # type: ignore


# ---------------------------------------------------------------------------
# Severity constants
# ---------------------------------------------------------------------------

SEVERITY_ERROR   = "ERROR"
SEVERITY_WARNING = "WARNING"
SEVERITY_INFO    = "INFO"

# Current expected schema version across all Track 2 state documents
CURRENT_SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# ConsistencyFinding + ConsistencyReport
# ---------------------------------------------------------------------------

@dataclass
class ConsistencyFinding:
    """A single consistency check result."""
    severity:    str        # ERROR | WARNING | INFO
    category:    str        # state category or "identity"
    check_type:  str        # MISSING | STALE | CELL_ID_CONFLICT | VERSION_MISMATCH | etc.
    message:     str
    remediation: str = ""


@dataclass
class ConsistencyReport:
    """Consistency check results for one cell."""
    cell_id:    str
    checked_at: str
    findings:   list[ConsistencyFinding] = field(default_factory=list)

    @property
    def errors(self) -> list[ConsistencyFinding]:
        return [f for f in self.findings if f.severity == SEVERITY_ERROR]

    @property
    def warnings(self) -> list[ConsistencyFinding]:
        return [f for f in self.findings if f.severity == SEVERITY_WARNING]


# ---------------------------------------------------------------------------
# Consistency checker
# ---------------------------------------------------------------------------

def check_twin_consistency(
    twin_root:   str,
    cell_id:     str,
    now_fn:      Optional[any] = None,
) -> ConsistencyReport:
    """
    Run all consistency checks against the digital twin for a single cell.

    twin_root: path to the twin/ root directory
    cell_id:   cell to check

    Returns a ConsistencyReport (empty findings = twin is consistent).
    """
    now_str = (now_fn or (lambda: datetime.now(timezone.utc).isoformat()))()
    now_ts  = datetime.fromisoformat(now_str.replace("Z", "+00:00"))

    report = ConsistencyReport(cell_id=cell_id, checked_at=now_str)
    paths  = TwinPaths(twin_root, cell_id)

    # 1. Check cell identity
    _check_cell_identity(paths, cell_id, report)

    # 2. Check each state category
    staleness = update_staleness(paths, now_ts)
    present_categories = {e.category for e in staleness.entries}

    for category in ALL_STATE_CATEGORIES:
        path = paths.state_path(category)

        # Missing state
        if not path.exists():
            report.findings.append(ConsistencyFinding(
                severity=SEVERITY_WARNING,
                category=category,
                check_type="MISSING",
                message=f"State category '{category}' not present in twin",
                remediation=(
                    f"Run the {category} state collector to populate twin/cells/"
                    f"{cell_id}/state/{category}.json"
                ),
            ))
            continue

        # Read the state document
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            report.findings.append(ConsistencyFinding(
                severity=SEVERITY_ERROR,
                category=category,
                check_type="PARSE_ERROR",
                message=f"Cannot parse {category}.json: {e}",
                remediation="Re-run the collector to regenerate the state file",
            ))
            continue

        # Cell ID conflict
        doc_cell_id = state.get("cell_id")
        if doc_cell_id and doc_cell_id != cell_id:
            report.findings.append(ConsistencyFinding(
                severity=SEVERITY_ERROR,
                category=category,
                check_type="CELL_ID_CONFLICT",
                message=(
                    f"State category '{category}' has cell_id={doc_cell_id!r} "
                    f"but twin expects {cell_id!r}"
                ),
                remediation=(
                    "Re-run the collector with the correct cell_id, or update "
                    "the state document's cell_id field"
                ),
            ))

        # Schema version mismatch
        doc_version = state.get("schema_version")
        if doc_version and doc_version != CURRENT_SCHEMA_VERSION:
            report.findings.append(ConsistencyFinding(
                severity=SEVERITY_WARNING,
                category=category,
                check_type="VERSION_MISMATCH",
                message=(
                    f"State category '{category}' schema_version={doc_version!r}; "
                    f"current version is {CURRENT_SCHEMA_VERSION!r}"
                ),
                remediation="Re-run the collector to regenerate with the current schema version",
            ))

    # 3. Check staleness for all present categories
    for entry in staleness.entries:
        if entry.is_stale:
            age_h = round((entry.staleness_age_sec or 0) / 3600, 1)
            thresh_h = round(entry.threshold_sec / 3600, 1)
            report.findings.append(ConsistencyFinding(
                severity=SEVERITY_WARNING,
                category=entry.category,
                check_type="STALE",
                message=(
                    f"State category '{entry.category}' is stale "
                    f"({age_h}h old, threshold {thresh_h}h)"
                ),
                remediation=(
                    f"Re-run the {entry.category} state collector to refresh the twin"
                ),
            ))

    return report


def _check_cell_identity(
    paths:   "TwinPaths",
    cell_id: str,
    report:  ConsistencyReport,
) -> None:
    """Check the cell identity record for existence and correctness."""
    if not paths.identity_path.exists():
        report.findings.append(ConsistencyFinding(
            severity=SEVERITY_WARNING,
            category="identity",
            check_type="MISSING",
            message="Cell identity record not present in twin",
            remediation=(
                f"Run: python3 twin_state_writer.py --forge-manifest forge-manifest.json "
                f"--cell {cell_id}"
            ),
        ))
        return

    try:
        identity = json.loads(paths.identity_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        report.findings.append(ConsistencyFinding(
            severity=SEVERITY_ERROR,
            category="identity",
            check_type="PARSE_ERROR",
            message=f"Cannot parse identity.json: {e}",
            remediation="Regenerate the cell identity record",
        ))
        return

    id_cell_id = identity.get("cell_id")
    if id_cell_id != cell_id:
        report.findings.append(ConsistencyFinding(
            severity=SEVERITY_ERROR,
            category="identity",
            check_type="CELL_ID_CONFLICT",
            message=(
                f"Identity record cell_id={id_cell_id!r} does not match "
                f"expected {cell_id!r}"
            ),
            remediation="Regenerate the cell identity record with the correct cell_id",
        ))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_twin_consistent(report: ConsistencyReport) -> bool:
    """Return True if no ERROR findings (WARNINGs are acceptable)."""
    return len(report.errors) == 0


def summarise_consistency(report: ConsistencyReport) -> str:
    """Return a human-readable summary of the consistency report."""
    if not report.findings:
        return f"Twin for cell '{report.cell_id}' is consistent."
    errors   = report.errors
    warnings = report.warnings
    lines    = [f"Twin consistency report for '{report.cell_id}' ({report.checked_at}):"]
    if errors:
        lines.append(f"  {len(errors)} ERROR(s):")
        for f in errors:
            lines.append(f"    [{f.check_type}] {f.category}: {f.message}")
    if warnings:
        lines.append(f"  {len(warnings)} WARNING(s):")
        for f in warnings:
            lines.append(f"    [{f.check_type}] {f.category}: {f.message}")
    return "\n".join(lines)
