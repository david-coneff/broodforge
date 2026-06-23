#!/usr/bin/env python3
"""
_recovery_readiness_certificate.py — Recovery-Readiness Conformance Certificate
builder (Phase 1.I, AD-059).

Composes one timestamped, generated record — `recovery-readiness-certificate.json`
(+ HTML, AD-051 pattern) — out of evidence broodforge already produces:

  - manifest_hash   SHA-256 over the canonical (sorted-keys JSON) serialization
                    of the manifest broodforge collected for this cell
  - graph_hash      SHA-256 over the canonical form of the dependency graph
                    `doc-gen/dependencies.py::build_graph` derives from it
  - readiness       the real `ReadinessReport` signal from `doc-gen/readiness.py`
                    (overall_score / overall_score_reason / a components summary)
  - drift           a summary (severity + diff counts) of the latest drift record
                    from `doc-gen/drift.py::compute_drift`
  - latest_drill    a summary of the most recent reconstruction drill
                    (`proxmox-bootstrap/reconstruction_drill.py::DrillRecord`)

AD-059 names this "the one genuinely new artifact worth drafting" — a
Deployment-Certificate-shaped bundle that says "as of this run, here is the
evidence that this cell could recover, and here is what it was declared to
be," built as an *additive composition* of existing modules — no new scoring
system, no Ed25519/category-theoretic apparatus (explicitly out of scope).

CORRECTION TO AD-059's PREMISE (documented here deliberately — see also
FEATURE-HISTORY.md): AD-059's text describes "RRS/ACS/DCS/CRS/OSS scores
already in readiness.py." That is aspirational, not actual — `readiness.py`'s
`score_graph()` produces a single `overall_score` (GREEN/YELLOW/ORANGE/RED/
BLOCKED) plus `overall_score_reason` and a `components` list; the five-letter
abbreviation scheme appears only in `proxmox-bootstrap/broodforge_dashboard.py`
as defensive UI code reading a `scores`/`summary` dict that nothing populates.
This certificate composes the *real* signal — `overall_score` /
`overall_score_reason` / a per-score-level component count — rather than
inventing or perpetuating the five-category fiction.

Stdlib only.
"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Callable, Optional

SCHEMA_VERSION = "1.0"

_READINESS_NOTE = (
    "AD-059 envisioned this field as 'RRS/ACS/DCS/CRS/OSS scores from "
    "readiness.py' — but readiness.py computes a single overall_score "
    "(GREEN/YELLOW/ORANGE/RED/BLOCKED) plus overall_score_reason and a "
    "components list, not five distinctly-scored categories. The five-letter "
    "abbreviation scheme appears only as aspirational/defensive UI code in "
    "broodforge_dashboard.py, reading a 'scores' dict nothing populates. This "
    "certificate documents the real overall_score signal broodforge produces "
    "today rather than perpetuating that fiction."
)


def _default_now_fn() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(obj: dict) -> str:
    """Canonical serialization: sorted keys, stable separators — for hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def hash_dict(obj: dict) -> str:
    """SHA-256 hex digest of an object's canonical-JSON serialization."""
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Component summaries (compose from real structures — no invented scoring)
# ---------------------------------------------------------------------------

def summarize_readiness(readiness_report: dict) -> dict:
    """
    Build the certificate's readiness section from a real `ReadinessReport.to_dict()`.

    Carries `overall_score` / `overall_score_reason` (the actual signal
    broodforge produces) plus a per-score-level count of `components` — the
    closest faithful analogue to "a composite readiness summary" without
    inventing distinct RRS/ACS/DCS/CRS/OSS categories that have no backing
    computation (see module docstring "CORRECTION").
    """
    components = readiness_report.get("components") or []
    counts: dict = {}
    for c in components:
        score = c.get("score") or "UNKNOWN"
        counts[score] = counts.get(score, 0) + 1

    return {
        "overall_score": readiness_report.get("overall_score"),
        "overall_score_reason": readiness_report.get("overall_score_reason"),
        "component_count": len(components),
        "component_score_counts": counts,
        "single_points_of_failure_count": len(readiness_report.get("single_points_of_failure") or []),
        "recovery_blockers_count": len(readiness_report.get("recovery_blockers") or []),
        "registry_gaps_count": len(readiness_report.get("registry_gaps") or []),
        "note": _READINESS_NOTE,
    }


def summarize_drift(drift_summary: Optional[dict]) -> dict:
    """
    Build the certificate's drift section from a `compute_drift()` result.

    Kept as a *summary* (severity + diff counts), not the full diff list —
    the certificate documents "what was the drift posture as of this run,"
    not a second copy of the drift report itself.
    """
    if not drift_summary:
        return {
            "available": False,
            "from_snapshot": None,
            "to_snapshot": None,
            "generated_at": None,
            "drift_severity": None,
            "diff_count": 0,
            "diff_severity_counts": {},
            "note": (
                "Drift data unavailable — at least two history snapshots are "
                "required to compute drift. Run the assessment pipeline after "
                "the first snapshot is stored to generate a baseline, then run "
                "it again to produce a drift comparison. Until then, drift "
                "posture cannot be reported."
            ),
        }

    diffs = drift_summary.get("diffs") or []
    counts: dict = {}
    for d in diffs:
        sev = d.get("severity") or "LOW"
        counts[sev] = counts.get(sev, 0) + 1

    return {
        "available": True,
        "from_snapshot": drift_summary.get("from_snapshot"),
        "to_snapshot": drift_summary.get("to_snapshot"),
        "generated_at": drift_summary.get("generated_at"),
        "drift_severity": drift_summary.get("drift_severity"),
        "diff_count": len(diffs),
        "diff_severity_counts": counts,
    }


def summarize_drill(latest_drill: Optional[dict]) -> dict:
    """
    Build the certificate's drill section from a `DrillRecord.to_dict()`.

    `accuracy_pct` compares estimated vs. actual total minutes (a measure of
    "how well does broodforge predict its own recovery timing") — derived
    here, not stored on the drill record, so it stays a read-only composition.
    """
    if not latest_drill:
        return {
            "available": False,
            "drill_id": None,
            "outcome": None,
            "completed_at": None,
            "completed_waves": 0,
            "total_waves": 0,
            "accuracy_pct": None,
            "gaps_found_count": 0,
            "gaps_remediated_count": 0,
        }

    wave_timings = latest_drill.get("wave_timings") or []
    completed_waves = sum(1 for w in wave_timings if w.get("completed"))

    accuracy_pct = None
    est = latest_drill.get("total_estimated_minutes")
    act = latest_drill.get("total_actual_minutes")
    if est and act and est > 0:
        accuracy_pct = round(100.0 * (1.0 - abs(act - est) / est), 1)

    return {
        "available": True,
        "drill_id": latest_drill.get("drill_id"),
        "outcome": latest_drill.get("outcome"),
        "completed_at": latest_drill.get("completed_at"),
        "completed_waves": completed_waves,
        "total_waves": len(wave_timings),
        "accuracy_pct": accuracy_pct,
        "gaps_found_count": len(latest_drill.get("gaps_found") or []),
        "gaps_remediated_count": len(latest_drill.get("gaps_remediated") or []),
    }


# ---------------------------------------------------------------------------
# Certificate composition
# ---------------------------------------------------------------------------

def certificate_id(cell_id: str, gen_at: str) -> str:
    ts = gen_at.replace(":", "").replace("-", "").split("+")[0].split(".")[0]
    return f"rrcc_{cell_id}_{ts}"


def build_recovery_readiness_certificate(
    manifest: dict,
    graph: dict,
    readiness_report: dict,
    drift_summary: Optional[dict] = None,
    latest_drill: Optional[dict] = None,
    now_fn: Optional[Callable[[], str]] = None,
) -> dict:
    """
    Compose a `recovery-readiness-certificate.json`-shaped dict.

    Args:
        manifest:         raw manifest dict (e.g. bootstrap-state.json content
                          or a Tier 1/2 manifest.json) — hashed for manifest_hash
        graph:            `DependencyGraph.to_dict()` — hashed for graph_hash
        readiness_report: `ReadinessReport.to_dict()` (real overall_score signal)
        drift_summary:    `compute_drift()` result, or None if unavailable
        latest_drill:     `DrillRecord.to_dict()`, or None if no drill has run
        now_fn:           injectable clock (datetime sweep convention)

    Returns:
        dict ready for `json.dumps` as `recovery-readiness-certificate.json`.
    """
    gen_at = (now_fn or _default_now_fn)()
    cell_id = manifest.get("cell_id") or "unknown-cell"

    manifest_hash = hash_dict(manifest)
    graph_hash = hash_dict(graph)

    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "recovery-readiness-conformance-certificate",
        "certificate_id": certificate_id(cell_id, gen_at),
        "generated_at": gen_at,
        "cell_id": cell_id,
        "manifest_hash": manifest_hash,
        "graph_hash": graph_hash,
        "readiness": summarize_readiness(readiness_report),
        "drift": summarize_drift(drift_summary),
        "latest_drill": summarize_drill(latest_drill),
        "notes": [
            "This certificate is a READ-ONLY composition of evidence broodforge "
            "already produces (readiness.py, drift.py, dependencies.py, the "
            "history/ snapshot store, and Phase 12 reconstruction drills) — it "
            "does not introduce a new scoring system, Ed25519 signing, or "
            "category-theoretic proof apparatus (explicitly out of scope per AD-059).",
            "manifest_hash and graph_hash are SHA-256 over the canonical "
            "(sorted-keys JSON) serialization of the manifest and dependency "
            "graph respectively — independently recomputable via replay-snapshot.py.",
            "Trust anchors remain git + KeePass + restic, exactly as AD-040 scopes "
            "them — these hashes are tamper-evidence, not a parallel trust model.",
        ],
    }


# ---------------------------------------------------------------------------
# Assembler — load real files and build the certificate
#
# `doc-gen` is a hyphenated directory (not an importable package name), so —
# matching the convention `doc-gen/engine.py` and `tests/unit/test_drift.py`
# already use — callers add it to `sys.path` before importing this module's
# assembler. We additionally insert it here, defensively, so the assembler
# works whether or not the caller already did so (the CLI wrapper does).
# ---------------------------------------------------------------------------

import sys
from pathlib import Path

_DOC_GEN_DIR = Path(__file__).parent.parent / "doc-gen"
if str(_DOC_GEN_DIR) not in sys.path:
    sys.path.insert(0, str(_DOC_GEN_DIR))

try:
    from dependencies import build_graph as _build_graph
    from drift import compute_drift as _compute_drift
    from readiness import score_graph as _score_graph
    _HAS_DOC_GEN = True
except ImportError:
    _build_graph = None  # type: ignore
    _score_graph = None  # type: ignore
    _compute_drift = None  # type: ignore
    _HAS_DOC_GEN = False


def _load_manifest(repo_root: Path) -> dict:
    candidates = [
        repo_root / "proxmox-bootstrap" / "bootstrap-state.json",
        repo_root / "tests" / "fixtures" / "bootstrap" / "bootstrap-state.json",
    ]
    for path in candidates:
        if path.exists():
            return json.loads(path.read_text())
    raise FileNotFoundError(
        "No manifest found — looked for bootstrap-state.json in: "
        + ", ".join(str(c) for c in candidates)
    )


def _load_latest_drift(repo_root: Path, manifest: dict, now_fn=None) -> Optional[dict]:
    index_path = repo_root / "history" / "index.json"
    if not index_path.exists():
        return None
    try:
        index = json.loads(index_path.read_text())
    except Exception:
        return None

    snapshots = sorted(index.get("snapshots") or [], key=lambda s: s.get("collected_at") or "")
    if len(snapshots) < 2:
        return None

    prior, current = snapshots[-2], snapshots[-1]
    prior_path = repo_root / prior["manifest_path"]
    if not prior_path.exists():
        return None

    try:
        prior_manifest = json.loads(prior_path.read_text())
    except Exception:
        return None

    return _compute_drift(prior_manifest, manifest, prior["id"], current["id"], now_fn=now_fn)


def _load_latest_drill(repo_root: Path) -> Optional[dict]:
    candidates = [
        repo_root / "proxmox-bootstrap" / "bootstrap-state.json",
        repo_root / "tests" / "fixtures" / "bootstrap" / "bootstrap-state.json",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            state = json.loads(path.read_text())
        except Exception:
            continue
        drills = state.get("reconstruction_drills") or []
        if drills:
            # drills[0] is the MOST RECENT drill — reconstruction_drill.py
            # prepends new records with drills.insert(0, record), so index 0
            # is always the newest entry, not the oldest.
            return drills[0]
    return None


def assemble_recovery_readiness_certificate(
    repo_root,
    manifest: Optional[dict] = None,
    now_fn: Optional[Callable[[], str]] = None,
):
    """
    Load manifest.json/bootstrap-state.json + history/index.json from a repo
    checkout, build the dependency graph + readiness report, locate the latest
    drift summary and drill record, and compose the certificate.

    Mirrors the loading pattern `assemble_forge_package`/`build_bootstrap_image`
    use: read what exists on disk, tolerate absence of optional inputs.

    Returns (certificate_dict, manifest_dict, graph_dict, readiness_report_dict).
    """
    if not _HAS_DOC_GEN:
        raise RuntimeError(
            "doc-gen modules (dependencies/readiness/drift) are required to "
            "assemble a recovery-readiness certificate"
        )

    repo_root = Path(repo_root)

    if manifest is None:
        manifest = _load_manifest(repo_root)

    graph_obj = _build_graph(manifest)
    graph_dict = graph_obj.to_dict()
    readiness_obj = _score_graph(graph_obj, manifest)
    readiness_dict = readiness_obj.to_dict()

    drift_summary = _load_latest_drift(repo_root, manifest, now_fn=now_fn)
    latest_drill = _load_latest_drill(repo_root)

    certificate = build_recovery_readiness_certificate(
        manifest=manifest,
        graph=graph_dict,
        readiness_report=readiness_dict,
        drift_summary=drift_summary,
        latest_drill=latest_drill,
        now_fn=now_fn,
    )
    return certificate, manifest, graph_dict, readiness_dict
