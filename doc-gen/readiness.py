#!/usr/bin/env python3
"""
readiness.py — Recovery readiness scorer.

Scores each component GREEN / YELLOW / ORANGE / RED / BLOCKED.
Propagates BLOCKED through dependency edges.
Identifies single points of failure and recovery blockers.

Scoring inputs (per component):
  - Backup presence
  - Backup age vs. per-type thresholds
  - Restore test history
  - Restore test recency (> 90 days = YELLOW)
  - Dependency information completeness
  - Offsite backup coverage
"""

from dataclasses import dataclass, field
from typing import Optional
from collections import defaultdict

SCORES = ["GREEN", "YELLOW", "ORANGE", "BLOCKED", "RED", "UNKNOWN"]
# RED=4 is the worst named score; UNKNOWN=5 is treated as lower priority than RED
# when computing overall score (UNKNOWN means "no data", not "will definitely fail")
SCORE_RANK = {s: i for i, s in enumerate(SCORES)}
# Override: UNKNOWN should never beat a real score
_WORST_RANK = {s: i for i, s in enumerate(["GREEN", "YELLOW", "ORANGE", "UNKNOWN", "BLOCKED", "RED"])}


def worst(a: str, b: str) -> str:
    return a if _WORST_RANK.get(a, 0) >= _WORST_RANK.get(b, 0) else b


# ---------------------------------------------------------------------------
# Per-type backup age thresholds (days)
# (yellow_threshold, orange_threshold)
# ---------------------------------------------------------------------------
BACKUP_AGE_THRESHOLDS = {
    "host":      (2,  7),
    "vm":        (7,  30),
    "container": (7,  30),
    "storage":   (2,  14),
    "default":   (7,  30),
}

RESTORE_TEST_MAX_DAYS = 90   # YELLOW if last test > 90 days ago


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Gap:
    component_id: str
    gap_type: str          # matches schema enum values
    severity: str          # score string
    description: str
    remediation: Optional[str] = None
    readiness_impact: Optional[str] = None


@dataclass
class ComponentReadiness:
    component_id: str
    score: str
    score_reason: str
    blocked_by: Optional[str] = None
    backup_present: Optional[bool] = None
    backup_age_days: Optional[float] = None
    backup_last_run_state: Optional[str] = None
    restore_tested: Optional[bool] = None
    last_restore_test_at: Optional[str] = None
    restore_test_age_days: Optional[float] = None
    offsite_covered: bool = False
    gaps: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "component_id": self.component_id,
            "score": self.score,
            "score_reason": self.score_reason,
            "blocked_by": self.blocked_by,
            "backup_present": self.backup_present,
            "backup_age_days": self.backup_age_days,
            "restore_tested": self.restore_tested,
            "gaps": [
                {
                    "component_id": g.component_id,
                    "gap_type": g.gap_type,
                    "severity": g.severity,
                    "description": g.description,
                    "remediation": g.remediation,
                    "readiness_impact": g.readiness_impact,
                }
                for g in self.gaps
            ],
        }


@dataclass
class ReadinessReport:
    overall_score: str
    overall_score_reason: str
    components: list = field(default_factory=list)
    single_points_of_failure: list = field(default_factory=list)
    recovery_blockers: list = field(default_factory=list)
    registry_gaps: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "overall_score": self.overall_score,
            "overall_score_reason": self.overall_score_reason,
            "components": [c.to_dict() for c in self.components],
            "single_points_of_failure": self.single_points_of_failure,
            "recovery_blockers": self.recovery_blockers,
            "registry_gaps": [
                {
                    "component_id": g.component_id,
                    "gap_type": g.gap_type,
                    "severity": g.severity,
                    "description": g.description,
                    "remediation": g.remediation,
                    "readiness_impact": g.readiness_impact,
                }
                for g in self.registry_gaps
            ],
        }


# ---------------------------------------------------------------------------
# Backup inventory lookup
# ---------------------------------------------------------------------------

class BackupInventory:
    """Wrapper around manifest backup_inventory for fast lookups."""

    def __init__(self, inventory: Optional[dict]):
        self._inv = inventory or {}
        self._pbs_by_vmid: dict[int, dict] = {}
        self._vzdump_by_vmid: dict[int, dict] = {}
        self._offsite_covers: set[str] = set()
        self._restore_tests_by_component: dict[str, dict] = {}

        for job in self._inv.get("pbs_jobs", []):
            vmid = job.get("vmid")
            if vmid is not None:
                # Keep best (most recent) job per vmid
                existing = self._pbs_by_vmid.get(vmid)
                if existing is None or (job.get("age_days") or 999) < (existing.get("age_days") or 999):
                    self._pbs_by_vmid[vmid] = job

        for sched in self._inv.get("vzdump_schedules", []):
            vmid = sched.get("vmid")
            if vmid is not None:
                self._vzdump_by_vmid[vmid] = sched

        for offsite in self._inv.get("offsite_backups", []):
            for cid in offsite.get("covers", []):
                self._offsite_covers.add(cid)

        for test in self._inv.get("restore_tests", []):
            cid = test.get("component_id")
            if cid:
                existing = self._restore_tests_by_component.get(cid)
                if existing is None or test.get("tested_at", "") > existing.get("tested_at", ""):
                    self._restore_tests_by_component[cid] = test

    def available(self) -> bool:
        return bool(self._inv)

    def find_job(self, node_id: str, node_type: str, metadata: dict) -> Optional[dict]:
        """Find the best backup job for a node."""
        # For VMs/containers, match by vmid
        vmid = metadata.get("vmid") or metadata.get("ctid")
        if vmid is not None:
            job = self._pbs_by_vmid.get(vmid) or self._vzdump_by_vmid.get(vmid)
            if job:
                return job

        # For host nodes, find the job with vmid=0 or name containing hostname
        if node_type == "host":
            job = self._pbs_by_vmid.get(0)
            if job:
                return job
            hostname = metadata.get("hostname", "")
            for j in self._inv.get("pbs_jobs", []):
                if hostname and hostname in (j.get("name") or ""):
                    return j

        return None

    def is_offsite_covered(self, node_id: str) -> bool:
        return node_id in self._offsite_covers

    def get_restore_test(self, node_id: str) -> Optional[dict]:
        return self._restore_tests_by_component.get(node_id)


# ---------------------------------------------------------------------------
# Component scorer
# ---------------------------------------------------------------------------

def score_component(
    node_id: str,
    node_type: str,
    node_metadata: dict,
    backup_inv: BackupInventory,
    dep_info_complete: bool = True,
) -> ComponentReadiness:

    gaps: list[Gap] = []
    score = "GREEN"

    backup_present: Optional[bool] = None
    backup_age_days: Optional[float] = None
    backup_last_run_state: Optional[str] = None
    restore_tested: Optional[bool] = None
    last_restore_test_at: Optional[str] = None
    restore_test_age_days: Optional[float] = None
    offsite_covered = backup_inv.is_offsite_covered(node_id)

    if not backup_inv.available():
        # Tier 1 — no backup data collected
        gaps.append(Gap(
            component_id=node_id,
            gap_type="MISSING_BACKUP",
            severity="YELLOW",
            description="Backup status unknown — Tier 2 assessment required",
            remediation="Run Tier 2 assessment with backup inventory collection",
            readiness_impact="Cannot verify recovery point; RPO unknown",
        ))
        gaps.append(Gap(
            component_id=node_id,
            gap_type="MISSING_RESTORE_PROCEDURE",
            severity="YELLOW",
            description="Restore procedure not documented",
            remediation="Generate and validate recovery runbook",
            readiness_impact="Operator must improvise; increases RTO",
        ))
        score = worst(score, "YELLOW")

    else:
        # Tier 2 — evaluate actual backup data
        job = backup_inv.find_job(node_id, node_type, node_metadata)

        if job is None:
            # Storage nodes and network nodes don't need individual backups
            if node_type in ("storage", "network"):
                # Covered implicitly by host backup or ZFS replication
                pass
            else:
                backup_present = False
                gaps.append(Gap(
                    component_id=node_id,
                    gap_type="MISSING_BACKUP",
                    severity="RED",
                    description=f"No backup job found for {node_id}",
                    remediation="Configure PBS job or vzdump schedule immediately",
                    readiness_impact="Component is unrecoverable without backup",
                ))
                score = worst(score, "RED")
        else:
            backup_present = True
            backup_age_days = job.get("age_days")
            backup_last_run_state = job.get("last_run_state")
            restore_tested = job.get("restore_tested", False)
            last_restore_test_at = job.get("last_restore_test_at")

            # --- Backup run state ---
            if backup_last_run_state == "failed":
                gaps.append(Gap(
                    component_id=node_id,
                    gap_type="MISSING_BACKUP",
                    severity="RED",
                    description=f"Last backup run FAILED for {node_id}",
                    remediation="Investigate and fix backup job immediately",
                    readiness_impact="Most recent backup may be corrupt or absent",
                ))
                score = worst(score, "RED")
            elif backup_last_run_state == "warning":
                gaps.append(Gap(
                    component_id=node_id,
                    gap_type="STALE_BACKUP",
                    severity="YELLOW",
                    description=f"Last backup run completed with warnings for {node_id}",
                    remediation="Review PBS job log for warnings",
                    readiness_impact="Backup integrity uncertain",
                ))
                score = worst(score, "YELLOW")

            # --- Backup age ---
            if backup_age_days is not None:
                yellow_days, orange_days = BACKUP_AGE_THRESHOLDS.get(
                    node_type, BACKUP_AGE_THRESHOLDS["default"]
                )
                if backup_age_days > orange_days:
                    gaps.append(Gap(
                        component_id=node_id,
                        gap_type="STALE_BACKUP",
                        severity="ORANGE",
                        description=(
                            f"Backup is {backup_age_days:.0f} days old "
                            f"(threshold: {orange_days} days for {node_type})"
                        ),
                        remediation="Run manual backup or verify scheduled backup is active",
                        readiness_impact="Recovery point may be significantly out of date",
                    ))
                    score = worst(score, "ORANGE")
                elif backup_age_days > yellow_days:
                    gaps.append(Gap(
                        component_id=node_id,
                        gap_type="STALE_BACKUP",
                        severity="YELLOW",
                        description=(
                            f"Backup is {backup_age_days:.0f} days old "
                            f"(threshold: {yellow_days} days for {node_type})"
                        ),
                        remediation="Run manual backup or verify schedule",
                        readiness_impact="Recovery point may not meet RPO",
                    ))
                    score = worst(score, "YELLOW")

            # --- Restore tested ---
            if not restore_tested:
                gaps.append(Gap(
                    component_id=node_id,
                    gap_type="UNTESTED_RESTORE",
                    severity="YELLOW",
                    description=f"Restore procedure never tested for {node_id}",
                    remediation="Perform restore test to isolated environment",
                    readiness_impact="Restore procedure unvalidated; actual RTO unknown",
                ))
                score = worst(score, "YELLOW")
            elif last_restore_test_at:
                # Check recency of restore test
                try:
                    from datetime import datetime, timezone
                    test_dt = datetime.fromisoformat(
                        last_restore_test_at.replace("Z", "+00:00")
                    )
                    now = datetime.now(timezone.utc)
                    test_age = (now - test_dt).days
                    restore_test_age_days = float(test_age)
                    if test_age > RESTORE_TEST_MAX_DAYS:
                        gaps.append(Gap(
                            component_id=node_id,
                            gap_type="UNTESTED_RESTORE",
                            severity="YELLOW",
                            description=(
                                f"Last restore test was {test_age} days ago "
                                f"(threshold: {RESTORE_TEST_MAX_DAYS} days)"
                            ),
                            remediation="Perform restore test to verify procedure still works",
                            readiness_impact="Procedure may be stale; infrastructure may have changed",
                        ))
                        score = worst(score, "YELLOW")
                except (ValueError, TypeError):
                    pass

    # --- Dependency info completeness ---
    if not dep_info_complete:
        gaps.append(Gap(
            component_id=node_id,
            gap_type="MISSING_DEPENDENCY_INFO",
            severity="YELLOW",
            description="Dependency information is incomplete",
            remediation="Run Tier 2 assessment with full dependency discovery",
            readiness_impact="Restore sequence may be incorrect",
        ))
        score = worst(score, "YELLOW")

    # --- Offsite backup ---
    if backup_present and not offsite_covered and node_type in ("host", "storage"):
        gaps.append(Gap(
            component_id=node_id,
            gap_type="MISSING_BACKUP",
            severity="YELLOW",
            description=f"No offsite backup coverage detected for {node_id}",
            remediation="Configure PBS replication or offsite rsync for critical components",
            readiness_impact="Local disaster (fire, flood) would result in data loss",
        ))
        score = worst(score, "YELLOW")

    # --- Score reason ---
    if not gaps:
        age_str = f"{backup_age_days:.0f}d old" if backup_age_days is not None else ""
        test_str = f", restore tested" if restore_tested else ""
        score_reason = f"Backup present ({age_str}{test_str}), all checks passed"
    elif score == "GREEN":
        score_reason = "Minor informational gaps only"
    elif score == "YELLOW":
        yellow_gaps = [g for g in gaps if g.severity == "YELLOW"]
        score_reason = "; ".join(g.description for g in yellow_gaps[:2])
        if len(yellow_gaps) > 2:
            score_reason += f" (+{len(yellow_gaps)-2} more)"
    elif score == "ORANGE":
        orange_gaps = [g for g in gaps if g.severity == "ORANGE"]
        score_reason = "; ".join(g.description for g in orange_gaps[:1])
    elif score == "RED":
        red_gaps = [g for g in gaps if g.severity == "RED"]
        score_reason = "; ".join(g.description for g in red_gaps[:1])
    else:
        score_reason = "Unknown"

    return ComponentReadiness(
        component_id=node_id,
        score=score,
        score_reason=score_reason,
        backup_present=backup_present,
        backup_age_days=backup_age_days,
        backup_last_run_state=backup_last_run_state,
        restore_tested=restore_tested,
        last_restore_test_at=last_restore_test_at,
        restore_test_age_days=restore_test_age_days,
        offsite_covered=offsite_covered,
        gaps=gaps,
    )


# ---------------------------------------------------------------------------
# Registry completeness check
# ---------------------------------------------------------------------------

def _score_registry_completeness(manifest: dict) -> list:
    """
    Check registry completeness and return a list of Gap objects.

    Secret registry missing → ORANGE (KeePass paths unavailable, recovery steps incomplete)
    DNS registry missing    → YELLOW (VM IPs unavailable, [VM_IP] placeholders remain)
    """
    gaps: list[Gap] = []

    secret_reg = manifest.get("secret_registry")
    if not secret_reg:
        gaps.append(Gap(
            component_id="infrastructure:registries",
            gap_type="MISSING_SECRET_REGISTRY",
            severity="ORANGE",
            description=(
                "Secret registry not available — KeePass paths cannot be pre-populated "
                "in recovery runbook"
            ),
            remediation=(
                "Populate proxmox-bootstrap/secret-registry.yaml and ensure it is "
                "included in bootstrap-state.json"
            ),
            readiness_impact=(
                "Recovery commands will have [KEEPASS_PATH] placeholders; "
                "operator must locate secrets manually under time pressure"
            ),
        ))

    dns_reg = manifest.get("dns_registry")
    if not dns_reg:
        gaps.append(Gap(
            component_id="infrastructure:registries",
            gap_type="MISSING_DNS_REGISTRY",
            severity="YELLOW",
            description=(
                "DNS registry not available — VM IP addresses cannot be pre-populated "
                "in recovery runbook"
            ),
            remediation=(
                "Populate proxmox-bootstrap/dns-registry.yaml and ensure it is "
                "included in bootstrap-state.json"
            ),
            readiness_impact=(
                "Recovery commands will have [VM_IP] placeholders; "
                "operator must look up IPs manually"
            ),
        ))

    return gaps


# ---------------------------------------------------------------------------
# Graph-level scorer
# ---------------------------------------------------------------------------

def score_graph(graph, manifest: dict) -> ReadinessReport:
    """Score all nodes; propagate BLOCKED; identify SPOFs and blockers."""
    backup_inv = BackupInventory(manifest.get("backup_inventory"))
    node_map = graph.node_map()

    component_scores: dict[str, ComponentReadiness] = {}
    for node in graph.nodes:
        cr = score_component(
            node_id=node.id,
            node_type=node.type,
            node_metadata=node.metadata,
            backup_inv=backup_inv,
        )
        # Copy score back onto the node for rendering
        node.readiness = cr.score
        component_scores[node.id] = cr

    # BLOCKED propagation
    prereqs: dict[str, list] = defaultdict(list)
    for edge in graph.edges:
        prereqs[edge.from_id].append(edge.to_id)

    changed = True
    while changed:
        changed = False
        for nid, cr in component_scores.items():
            if cr.score == "BLOCKED":
                continue
            for prereq_id in prereqs.get(nid, []):
                prereq_cr = component_scores.get(prereq_id)
                if prereq_cr and prereq_cr.score == "RED":
                    cr.score = "BLOCKED"
                    node_map[nid].readiness = "BLOCKED"
                    cr.blocked_by = prereq_id
                    prereq_node = node_map.get(prereq_id)
                    cr.score_reason = (
                        f"Blocked by RED: "
                        f"{prereq_node.label if prereq_node else prereq_id}"
                    )
                    changed = True
                    break

    # Single points of failure: nodes with ≥2 vm/container dependents
    dependent_counts: dict[str, int] = defaultdict(int)
    vm_ct_ids = {n.id for n in graph.nodes if n.type in ("vm", "container")}
    for edge in graph.edges:
        if edge.from_id in vm_ct_ids:
            dependent_counts[edge.to_id] += 1

    spof = [
        nid for nid, count in dependent_counts.items()
        if count >= 2 and nid in node_map
    ]

    # Recovery blockers: RED nodes that others depend on
    blockers = [
        nid for nid, cr in component_scores.items()
        if cr.score == "RED" and dependent_counts.get(nid, 0) > 0
    ]

    # Registry completeness
    registry_gaps = _score_registry_completeness(manifest)

    # Overall score — worst of component scores and registry gaps
    overall = "GREEN"
    for cr in component_scores.values():
        overall = worst(overall, cr.score)
    for gap in registry_gaps:
        overall = worst(overall, gap.severity)

    # Overall reason
    from collections import Counter
    sc = Counter(c.score for c in component_scores.values())
    if sc.get("RED", 0):
        overall_reason = f"{sc['RED']} RED component(s) — recovery at risk"
    elif sc.get("BLOCKED", 0):
        overall_reason = f"{sc['BLOCKED']} BLOCKED component(s) due to RED dependencies"
    elif sc.get("ORANGE", 0):
        reg_orange = [g for g in registry_gaps if g.severity == "ORANGE"]
        if reg_orange and sc.get("ORANGE", 0) == len(reg_orange):
            overall_reason = "Secret registry missing — KeePass paths unavailable"
        else:
            overall_reason = f"{sc['ORANGE']} component(s) with significant gaps"
    elif sc.get("YELLOW", 0) or any(g.severity == "YELLOW" for g in registry_gaps):
        overall_reason = f"{sc.get('YELLOW', 0)} component(s) with minor gaps"
        if any(g.severity == "YELLOW" for g in registry_gaps):
            overall_reason += "; DNS registry missing"
    else:
        overall_reason = "All components GREEN"

    return ReadinessReport(
        overall_score=overall,
        overall_score_reason=overall_reason,
        components=list(component_scores.values()),
        single_points_of_failure=spof,
        recovery_blockers=blockers,
        registry_gaps=registry_gaps,
    )
