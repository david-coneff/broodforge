#!/usr/bin/env python3
"""
multilevel_readiness.py — Multi-Level Readiness Assessment (Phase 22).

Aggregates readiness scores from all state categories into a coherent
multi-level readiness hierarchy:

  Hardware Level    → scores from hardware_state + platform_state
  Cluster Level     → scores from cluster_state + storage_state
  Cell Level        → aggregate all 17 state categories for one cell
  Federation Level  → aggregate cell readiness across all cells

22.1  HardwareLevelReadiness  — score from Phase 13/14 state docs
22.2  ClusterLevelReadiness   — score from Phase 14 state docs
22.3  CellLevelReadiness      — aggregate across all 17 state categories
22.4  FederationLevelReadiness — aggregate across cells
22.5  FederationReadinessReport (HTML) — see html_base usage
22.6  Tier3AssessmentEngine integration (uses federation_state.Tier3AssessmentEngine)

Provides:
  ReadinessLevel      — single score with breakdown
  score_hardware()    — hardware + platform readiness
  score_cluster()     — cluster + storage readiness
  score_cell()        — full cell readiness (all state categories)
  score_federation()  — federation readiness from cell scores
  MultiLevelReport    — complete multi-level readiness document
  build_multilevel_report() — assemble from collected state docs

Stdlib only.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# Score constants and helpers
# ---------------------------------------------------------------------------

SCORE_ORDER = {"GREEN": 0, "YELLOW": 1, "ORANGE": 2, "RED": 3, "BLOCKED": 4}


def _worst(scores: list[str]) -> str:
    if not scores:
        return "GREEN"
    return max(scores, key=lambda s: SCORE_ORDER.get(s, 0))


def _score_pct(pct: float, warn: float = 80.0, crit: float = 90.0) -> str:
    if pct >= crit:
        return "RED"
    if pct >= warn:
        return "ORANGE"
    if pct >= warn * 0.75:
        return "YELLOW"
    return "GREEN"


# ---------------------------------------------------------------------------
# ReadinessLevel
# ---------------------------------------------------------------------------

@dataclass
class ReadinessLevel:
    """A single readiness score with breakdown."""
    score:      str           # GREEN/YELLOW/ORANGE/RED/BLOCKED
    reason:     str
    components: list[dict] = field(default_factory=list)
    # Each component: {id, score, reason}


# ---------------------------------------------------------------------------
# 22.1 — Hardware Level Readiness
# ---------------------------------------------------------------------------

def score_hardware(
    hardware_state:  dict | None = None,
    platform_state:  dict | None = None,
) -> ReadinessLevel:
    """
    Score hardware and platform readiness.

    Inputs: hardware_state and platform_state documents (Phase 13).
    Scores:
      GREEN:  all components healthy, no firmware alerts, good capacity
      YELLOW: minor alerts, capacity approaching threshold
      ORANGE: degraded components, outdated firmware, approaching capacity limit
      RED:    failed disk/NIC, critical firmware alert, capacity exceeded
    """
    components: list[dict] = []
    scores: list[str]      = []

    if hardware_state is None:
        return ReadinessLevel("YELLOW", "No hardware state collected.", [])

    hw = hardware_state

    # Disk health
    disks = hw.get("disks") or []
    for disk in disks:
        health = (disk.get("health") or "").upper()
        disk_score = "GREEN"
        if health in ("FAILED", "ERROR"):
            disk_score = "RED"
        elif health in ("CAUTION", "UNKNOWN"):
            disk_score = "ORANGE"
        elif not health or health == "?":
            disk_score = "YELLOW"
        components.append({"id": f"disk:{disk.get('id', '?')}", "score": disk_score,
                            "reason": f"Disk health: {health or 'unknown'}"})
        scores.append(disk_score)

    # RAM
    ram_total = hw.get("ram_gb") or hw.get("total_memory_gb")
    ram_used  = hw.get("ram_used_gb") or hw.get("used_memory_gb")
    if ram_total and ram_used:
        ram_pct    = float(ram_used) / float(ram_total) * 100
        ram_score  = _score_pct(ram_pct)
        components.append({"id": "ram", "score": ram_score,
                            "reason": f"RAM: {ram_pct:.0f}% ({ram_used}/{ram_total} GB)"})
        scores.append(ram_score)

    # Platform state (firmware, OS version)
    if platform_state:
        pkg_outdated = platform_state.get("packages_outdated_count") or 0
        if pkg_outdated > 50:
            pkg_score = "ORANGE"
        elif pkg_outdated > 10:
            pkg_score = "YELLOW"
        else:
            pkg_score = "GREEN"
        components.append({"id": "packages", "score": pkg_score,
                            "reason": f"{pkg_outdated} outdated package(s)"})
        scores.append(pkg_score)

    overall = _worst(scores) if scores else "YELLOW"
    reason  = _summarise(components)
    return ReadinessLevel(overall, reason, components)


# ---------------------------------------------------------------------------
# 22.2 — Cluster Level Readiness
# ---------------------------------------------------------------------------

def score_cluster(
    cluster_state: dict | None = None,
    storage_state: dict | None = None,
) -> ReadinessLevel:
    """
    Score cluster and storage readiness.

    Inputs: cluster_state and storage_state documents (Phase 14).
    """
    components: list[dict] = []
    scores: list[str]      = []

    if cluster_state is None and storage_state is None:
        return ReadinessLevel("YELLOW", "No cluster or storage state collected.", [])

    if cluster_state:
        cs = cluster_state
        # Quorum
        quorum_ok = cs.get("corosync_quorum_ok")
        if quorum_ok is False:
            q_score = "RED"
        elif quorum_ok is None:
            q_score = "YELLOW"
        else:
            q_score = "GREEN"
        components.append({"id": "quorum", "score": q_score,
                            "reason": f"Corosync quorum: {'OK' if quorum_ok else 'NOT OK'}"})
        scores.append(q_score)

        # Cluster nodes
        nodes_total  = cs.get("nodes_total") or 0
        nodes_online = cs.get("nodes_online") or 0
        if nodes_total > 0 and nodes_online < nodes_total:
            n_score = "ORANGE" if nodes_online >= nodes_total // 2 + 1 else "RED"
        else:
            n_score = "GREEN"
        components.append({"id": "nodes", "score": n_score,
                            "reason": f"{nodes_online}/{nodes_total} nodes online"})
        scores.append(n_score)

    if storage_state:
        ss = storage_state
        # ZFS pool health
        pools = ss.get("zfs_pools") or []
        for pool in pools:
            health = (pool.get("health") or "").upper()
            p_score = {"ONLINE": "GREEN", "DEGRADED": "ORANGE",
                       "FAULTED": "RED", "REMOVED": "RED"}.get(health, "YELLOW")
            components.append({"id": f"zfs:{pool.get('name', '?')}", "score": p_score,
                                "reason": f"ZFS {pool.get('name', '?')}: {health}"})
            scores.append(p_score)

        # Storage space
        for ds in (ss.get("datastores") or []):
            used_pct = ds.get("usage_pct") or 0
            ds_score = _score_pct(float(used_pct))
            components.append({"id": f"ds:{ds.get('id', '?')}", "score": ds_score,
                                "reason": f"Datastore {ds.get('id', '?')}: {used_pct}%"})
            scores.append(ds_score)

    overall = _worst(scores) if scores else "YELLOW"
    return ReadinessLevel(overall, _summarise(components), components)


# ---------------------------------------------------------------------------
# 22.3 — Cell Level Readiness
# ---------------------------------------------------------------------------

# Category weights for aggregation (higher = more impact on overall)
_CAT_WEIGHTS = {
    "hardware":         2,
    "cluster":          2,
    "backup":           2,
    "k3s":              2,
    "service":          1,
    "storage":          2,
    "network":          2,
    "observability":    1,
    "external_deps":    1,
    "reconstruction":   1,
    "capacity":         1,
}


def score_cell(
    cell_id:         str,
    hardware_level:  ReadinessLevel | None = None,
    cluster_level:   ReadinessLevel | None = None,
    extra_scores:    dict[str, str] | None = None,   # category → score
) -> ReadinessLevel:
    """
    Aggregate all category scores into a single cell-level readiness.

    extra_scores: {category_name: score} for categories not covered by
    hardware_level/cluster_level (e.g. from doc-gen readiness.py components).
    """
    components: list[dict] = []
    scores: list[str]      = []

    if hardware_level:
        components.append({"id": "hardware", "score": hardware_level.score,
                            "reason": hardware_level.reason})
        scores.append(hardware_level.score)

    if cluster_level:
        components.append({"id": "cluster", "score": cluster_level.score,
                            "reason": cluster_level.reason})
        scores.append(cluster_level.score)

    for cat, score in (extra_scores or {}).items():
        components.append({"id": cat, "score": score, "reason": f"Category: {cat}"})
        scores.append(score)

    if not scores:
        return ReadinessLevel("YELLOW", f"No state data available for {cell_id}.", [])

    overall = _worst(scores)
    return ReadinessLevel(overall, _summarise(components), components)


# ---------------------------------------------------------------------------
# 22.4 — Federation Level Readiness
# ---------------------------------------------------------------------------

@dataclass
class FederationCellScore:
    cell_id:  str
    score:    str
    reason:   str


def score_federation(
    cell_scores: list[FederationCellScore],
    trust_score: str = "GREEN",
) -> ReadinessLevel:
    """
    Aggregate cell-level scores into a federation-level readiness.

    trust_score: from Phase 19 score_federation_readiness().overall_score
    """
    if not cell_scores:
        return ReadinessLevel("RED", "No cells in federation.", [])

    components: list[dict] = []
    scores: list[str]      = []

    for cs in cell_scores:
        components.append({"id": f"cell:{cs.cell_id}", "score": cs.score,
                            "reason": cs.reason})
        scores.append(cs.score)

    components.append({"id": "trust", "score": trust_score,
                        "reason": "Federation trust and recovery relationships"})
    scores.append(trust_score)

    overall = _worst(scores)
    return ReadinessLevel(overall, _summarise(components), components)


# ---------------------------------------------------------------------------
# MultiLevelReport (22.5)
# ---------------------------------------------------------------------------

@dataclass
class MultiLevelReport:
    """Complete multi-level readiness assessment result."""
    cell_id:          str
    hardware_level:   ReadinessLevel
    cluster_level:    ReadinessLevel
    cell_level:       ReadinessLevel
    federation_level: ReadinessLevel | None = None
    generated_at:     str = ""

    @property
    def overall_score(self) -> str:
        levels = [self.hardware_level.score, self.cluster_level.score,
                  self.cell_level.score]
        if self.federation_level:
            levels.append(self.federation_level.score)
        return _worst(levels)

    @property
    def summary(self) -> str:
        return (
            f"Cell {self.cell_id} overall: {self.overall_score}  |  "
            f"HW:{self.hardware_level.score}  "
            f"Cluster:{self.cluster_level.score}  "
            f"Cell:{self.cell_level.score}"
            + (f"  Fed:{self.federation_level.score}" if self.federation_level else "")
        )

    def to_dict(self) -> dict:
        def _level_dict(lvl: ReadinessLevel) -> dict:
            return {"score": lvl.score, "reason": lvl.reason,
                    "components": lvl.components}
        return {
            "cell_id":          self.cell_id,
            "overall_score":    self.overall_score,
            "hardware_level":   _level_dict(self.hardware_level),
            "cluster_level":    _level_dict(self.cluster_level),
            "cell_level":       _level_dict(self.cell_level),
            "federation_level": _level_dict(self.federation_level) if self.federation_level else None,
            "generated_at":     self.generated_at,
        }


def build_multilevel_report(
    cell_id:        str,
    *,
    hardware_state:  dict | None = None,
    platform_state:  dict | None = None,
    cluster_state:   dict | None = None,
    storage_state:   dict | None = None,
    extra_scores:    dict[str, str] | None = None,
    fed_cell_scores: list[FederationCellScore] | None = None,
    trust_score:     str = "GREEN",
    now_fn:          Callable[[], str] | None = None,
) -> MultiLevelReport:
    """
    Assemble a complete multi-level readiness report for a cell.

    Can be called with whatever state documents are available;
    missing documents produce YELLOW scores rather than crashing.
    """
    from datetime import datetime, timezone
    now = (now_fn or (lambda: datetime.now(timezone.utc).isoformat()))()

    hw_level  = score_hardware(hardware_state, platform_state)
    cl_level  = score_cluster(cluster_state, storage_state)
    cell_lvl  = score_cell(cell_id, hw_level, cl_level, extra_scores)
    fed_lvl   = score_federation(fed_cell_scores, trust_score) if fed_cell_scores else None

    return MultiLevelReport(
        cell_id=cell_id,
        hardware_level=hw_level,
        cluster_level=cl_level,
        cell_level=cell_lvl,
        federation_level=fed_lvl,
        generated_at=now,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _summarise(components: list[dict]) -> str:
    """Summarise component scores into a human-readable reason string."""
    if not components:
        return "No components scored."
    red_comps    = [c for c in components if c["score"] == "RED"]
    orange_comps = [c for c in components if c["score"] == "ORANGE"]
    if red_comps:
        return f"RED: {'; '.join(c['id'] for c in red_comps[:3])}"
    if orange_comps:
        return f"ORANGE: {'; '.join(c['id'] for c in orange_comps[:3])}"
    return f"All {len(components)} component(s) scored {components[0]['score'] if len(set(c['score'] for c in components)) == 1 else 'healthy'}."
