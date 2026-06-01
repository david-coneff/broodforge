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


def _score_template_registry_completeness(manifest: dict) -> list:
    """
    Check template registry completeness and return a list of Gap objects.

    Templates missing → ORANGE (VM reconstruction requires manual base-image
    research; same severity as missing secret registry since it blocks automated
    reconstruction).
    """
    gaps: list[Gap] = []

    templates = manifest.get("templates")
    if not templates:
        gaps.append(Gap(
            component_id="infrastructure:registries",
            gap_type="MISSING_TEMPLATE_REGISTRY",
            severity="ORANGE",
            description=(
                "Template registry not available — base image and template IDs cannot "
                "be pre-populated in recovery runbook"
            ),
            remediation=(
                "Populate base_images and templates in bootstrap-state.json"
            ),
            readiness_impact=(
                "VM reconstruction requires manual research to locate the correct "
                "Proxmox template ID and base image; VMID 9000 may not be obvious "
                "under time pressure"
            ),
        ))

    return gaps


def _score_service_contract_completeness(graph, manifest: dict) -> list:
    """
    Check that every VM node has a declared service contract.

    A VM without a contract gets a YELLOW gap: its dependencies and health checks
    are unknown, so the recovery runbook cannot pre-populate restart sequences or
    verify the service is healthy after reconstruction.
    """
    contracts     = manifest.get("service_contracts") or []
    contracted_vms: set[str] = {c.get("vm") for c in contracts if c.get("vm")}

    if not contracts:
        # No contracts at all — single gap rather than one per VM
        return [Gap(
            component_id="infrastructure:service-contracts",
            gap_type="MISSING_SERVICE_CONTRACTS",
            severity="YELLOW",
            description=(
                "No service contracts declared — inter-service dependencies, "
                "health check endpoints, and startup ordering are unknown"
            ),
            remediation=(
                "Populate proxmox-bootstrap/service-contracts.yaml and include "
                "service_contracts in bootstrap-state.json"
            ),
            readiness_impact=(
                "Recovery runbook cannot pre-populate service restart sequences; "
                "dependency ordering must be determined manually"
            ),
        )]

    gaps: list[Gap] = []
    for node in graph.nodes:
        if node.type != "vm":
            continue
        vm_name = node.metadata.get("name", "")
        if not vm_name or vm_name in contracted_vms:
            continue
        gaps.append(Gap(
            component_id=node.id,
            gap_type="MISSING_SERVICE_CONTRACT",
            severity="YELLOW",
            description=(
                f"No service contract for {node.label} — dependencies and "
                f"health check are undeclared"
            ),
            remediation=(
                f"Add a service contract for '{vm_name}' in "
                f"proxmox-bootstrap/service-contracts.yaml"
            ),
            readiness_impact=(
                f"Recovery runbook cannot verify '{vm_name}' is healthy or "
                f"determine which services depend on it"
            ),
        ))
    return gaps


def _score_phoenix_playbook_existence(manifest: dict) -> list:
    """
    Check whether a phoenix playbook has been generated for this cell.

    Looks for 'phoenix_playbook' in the manifest (injected by engine.py from
    the reconstruction/ directory) or for a 'phoenix_playbook_generated_at'
    timestamp field in bootstrap-state.json.

    YELLOW: no playbook generated — recovery depends on manual steps.
    """
    gaps: list[Gap] = []
    has_playbook = bool(
        manifest.get("phoenix_playbook") or
        manifest.get("phoenix_playbook_generated_at")
    )
    if not has_playbook:
        gaps.append(Gap(
            component_id="infrastructure:phoenix-playbook",
            gap_type="MISSING_PHOENIX_PLAYBOOK",
            severity="YELLOW",
            description=(
                "No phoenix playbook has been generated for this cell — "
                "node reconstruction requires improvised manual steps"
            ),
            remediation=(
                "Generate a phoenix playbook: "
                "python3 proxmox-bootstrap/phoenix_playbook.py "
                "--state proxmox-bootstrap/bootstrap-state.json --output reconstruction/"
            ),
            readiness_impact=(
                "Stargate process (failed node resurrection) has no pre-validated "
                "wave-ordered reconstruction plan; RTO will be significantly higher"
            ),
        ))
    return gaps


def _score_network_topology_completeness(manifest: dict) -> list:
    """
    Check network topology declaration completeness and drift.

    YELLOW: network_topology_declared not present — network reconstruction
            requires manual documentation of bridges and routing.
    ORANGE: drift detected between declared and observed state.
    RED:    declared bridges exist but observed state shows none of them
            present (suggests entire network config is missing or wrong).
    """
    gaps: list[Gap] = []
    ntd = manifest.get("network_topology_declared")

    if not ntd:
        gaps.append(Gap(
            component_id="infrastructure:network-topology",
            gap_type="MISSING_NETWORK_TOPOLOGY",
            severity="YELLOW",
            description=(
                "Network topology not declared — bridge configuration, VLANs, "
                "and firewall policy are not tracked as code"
            ),
            remediation=(
                "Populate network_topology_declared in bootstrap-state.json "
                "with the bridges and VLANs configured on this Proxmox host"
            ),
            readiness_impact=(
                "Recovery Wave 0 (network reconstruction) cannot be pre-populated; "
                "operator must document bridges manually during recovery"
            ),
        ))
        return gaps

    declared = ntd.get("bridges") or []
    observed = ntd.get("observed_bridges")
    drift    = ntd.get("drift_detected", False)
    detail   = ntd.get("drift_details") or ""

    if not declared:
        gaps.append(Gap(
            component_id="infrastructure:network-topology",
            gap_type="MISSING_NETWORK_TOPOLOGY",
            severity="YELLOW",
            description="network_topology_declared present but no bridges declared",
            remediation="Add bridge declarations to network_topology_declared.bridges",
            readiness_impact="Network reconstruction commands cannot be pre-populated",
        ))
        return gaps

    # Drift from observed state
    if observed is not None and drift:
        # Check severity: all declared bridges missing = RED
        observed_names  = {b["name"] for b in observed}
        declared_names  = {b["name"] for b in declared}
        all_missing     = declared_names and not (declared_names & observed_names)
        severity = "RED" if all_missing else "ORANGE"
        gaps.append(Gap(
            component_id="infrastructure:network-topology",
            gap_type="NETWORK_TOPOLOGY_DRIFT",
            severity=severity,
            description=(
                f"Network topology drift detected: {detail[:200]}"
                if detail else
                "Declared network topology does not match observed bridge configuration"
            ),
            remediation=(
                "Run network_topology_collector.py to refresh observed state, "
                "then reconcile differences between declared and actual configuration"
            ),
            readiness_impact=(
                "Recovery Wave 0 commands may not match actual host configuration; "
                "network reconstruction may fail if bridges differ"
            ),
        ))

    return gaps


def _score_backup_config_completeness(manifest: dict) -> list:
    """
    Score backup configuration completeness.

    RED:    No backup_config, or secrets/config layers have no destinations.
    RED:    consecutive_all_fail_count >= 2 for any layer (chain is broken).
    ORANGE: consecutive_all_fail_count == 1, or last backup > 2× schedule interval.
    YELLOW: No permanent checkpoint exists in history, or last backup > 1× interval.
    """
    from datetime import datetime, timezone, timedelta

    gaps: list[Gap] = []
    bc = manifest.get("backup_config")

    if not bc:
        gaps.append(Gap(
            component_id="infrastructure:backup",
            gap_type="MISSING_BACKUP_CONFIG",
            severity="RED",
            description=(
                "No backup_config declared — KeePass database and configuration state "
                "are not protected by external backup"
            ),
            remediation=(
                "Run proxmox-bootstrap/setup-backup.py to configure backup destinations"
            ),
            readiness_impact=(
                "Infrastructure state and secrets cannot be recovered after catastrophic loss"
            ),
        ))
        return gaps

    layers = bc.get("layers") or {}
    now = datetime.now(timezone.utc)

    # Default schedule interval: assume daily (24h) for config, weekly for appdata
    default_intervals = {
        "secrets": timedelta(hours=48),
        "config":  timedelta(hours=48),
        "appdata": timedelta(days=7),
    }

    for layer_name in ("secrets", "config", "appdata"):
        layer = layers.get(layer_name) or {}
        if not layer.get("enabled", False):
            continue

        dests = layer.get("destinations") or []
        consec_fail = layer.get("consecutive_all_fail_count", 0)
        last_backup = layer.get("last_backup_at")

        # No destinations configured
        if not dests and layer_name in ("secrets", "config"):
            gaps.append(Gap(
                component_id=f"infrastructure:backup:{layer_name}",
                gap_type="MISSING_BACKUP_DESTINATION",
                severity="RED",
                description=(
                    f"Backup layer '{layer_name}' is enabled but has no destinations configured"
                ),
                remediation="Run setup-backup.py to add at least one destination",
                readiness_impact=f"'{layer_name}' data is not being backed up",
            ))
            continue

        # Consecutive all-fail
        if consec_fail >= 2:
            gaps.append(Gap(
                component_id=f"infrastructure:backup:{layer_name}",
                gap_type="BACKUP_ALL_DESTINATIONS_FAILED",
                severity="RED",
                description=(
                    f"Backup layer '{layer_name}': all destinations have failed on "
                    f"{consec_fail} consecutive runs — backup chain is broken"
                ),
                remediation="Check destination connectivity and run run-backup.py manually",
                readiness_impact=f"'{layer_name}' data is not being backed up to any destination",
            ))
        elif consec_fail == 1:
            gaps.append(Gap(
                component_id=f"infrastructure:backup:{layer_name}",
                gap_type="BACKUP_ALL_DESTINATIONS_FAILED",
                severity="ORANGE",
                description=(
                    f"Backup layer '{layer_name}': all destinations failed on the last run"
                ),
                remediation="Check destination connectivity and run run-backup.py",
                readiness_impact="Last backup run produced no successful copy",
            ))

        # Last backup age
        if last_backup:
            try:
                last_dt = datetime.fromisoformat(last_backup.replace("Z", "+00:00"))
                age = now - last_dt
                interval = default_intervals.get(layer_name, timedelta(hours=48))
                if age > interval * 3:
                    gaps.append(Gap(
                        component_id=f"infrastructure:backup:{layer_name}",
                        gap_type="STALE_BACKUP",
                        severity="RED",
                        description=(
                            f"Backup layer '{layer_name}': last backup was "
                            f"{int(age.total_seconds() / 3600)}h ago (expected every "
                            f"{int(interval.total_seconds() / 3600)}h) — likely broken"
                        ),
                        remediation="Run run-backup.py and investigate why scheduled backup stopped",
                        readiness_impact="Backup data may be dangerously stale",
                    ))
                elif age > interval * 2:
                    gaps.append(Gap(
                        component_id=f"infrastructure:backup:{layer_name}",
                        gap_type="STALE_BACKUP",
                        severity="ORANGE",
                        description=(
                            f"Backup layer '{layer_name}': last backup was "
                            f"{int(age.total_seconds() / 3600)}h ago (expected every "
                            f"{int(interval.total_seconds() / 3600)}h)"
                        ),
                        remediation="Run run-backup.py to update the backup",
                        readiness_impact="Backup data is older than expected",
                    ))
                elif age > interval:
                    gaps.append(Gap(
                        component_id=f"infrastructure:backup:{layer_name}",
                        gap_type="STALE_BACKUP",
                        severity="YELLOW",
                        description=(
                            f"Backup layer '{layer_name}': last backup was "
                            f"{int(age.total_seconds() / 3600)}h ago (expected every "
                            f"{int(interval.total_seconds() / 3600)}h)"
                        ),
                        remediation="Run run-backup.py",
                        readiness_impact="Backup may not meet RPO",
                    ))
            except (ValueError, TypeError):
                pass
        elif layer_name in ("secrets", "config"):
            # Never backed up
            gaps.append(Gap(
                component_id=f"infrastructure:backup:{layer_name}",
                gap_type="STALE_BACKUP",
                severity="ORANGE",
                description=f"Backup layer '{layer_name}': no backup has ever been run",
                remediation="Run run-backup.py to create the first backup",
                readiness_impact="No backup exists for this layer",
            ))

    # Checkpoint check: is there at least one permanent checkpoint in history?
    history = bc.get("backup_history") or []
    checkpoint_tag = bc.get("checkpoint_tag", "checkpoint")
    has_checkpoint = any(
        any(
            checkpoint_tag in (c.get("restic_snapshot_id") or "")
            for c in (r.get("components") or [])
        )
        for r in history
    )
    # Simpler check: look for checkpoint in snapshot_set_id or any tagged field
    # (actual checkpoint detection requires querying restic; approximate from history)
    if history and not has_checkpoint and len(history) >= 5:
        gaps.append(Gap(
            component_id="infrastructure:backup",
            gap_type="MISSING_CHECKPOINT",
            severity="YELLOW",
            description=(
                "No permanent checkpoint has been created — all snapshots are subject "
                "to retention policy rotation"
            ),
            remediation=(
                f"Tag a snapshot as a permanent checkpoint: "
                f"restic tag --set {checkpoint_tag} <snapshot-id>"
            ),
            readiness_impact="Historical recovery points may be pruned automatically",
        ))

    return gaps


def _score_external_dependency_state(manifest: dict) -> list:
    """
    Check external dependency certificate expiry.

    Certificate expiry thresholds:
      ≤ 7 days  → RED    (imminent — services will start failing)
      ≤ 30 days → ORANGE (critical action required)
      ≤ 60 days → YELLOW (plan renewal now)

    Missing external_dependencies is not a gap — the field is optional.
    """
    from external_dependencies import (
        build_external_dependency_registry,
        CERT_EXPIRY_RED_DAYS, CERT_EXPIRY_ORANGE_DAYS, CERT_EXPIRY_YELLOW_DAYS,
    )
    ext_reg = build_external_dependency_registry(manifest)
    if not ext_reg.available():
        return []

    gaps: list[Gap] = []
    for dep in ext_reg.with_certificates():
        days = ext_reg.days_until_expiry(dep)
        if days is None:
            continue
        dep_id   = dep.get("id", "unknown")
        dep_name = dep.get("name", dep_id)
        endpoint = dep.get("endpoint", "")

        if days <= CERT_EXPIRY_RED_DAYS:
            gaps.append(Gap(
                component_id=f"external:{dep_id}",
                gap_type="CERT_EXPIRY",
                severity="RED",
                description=(
                    f"Certificate for '{dep_name}' ({endpoint}) expires in {days} day(s) "
                    f"— services depending on this endpoint will fail when the cert expires"
                ),
                remediation=(
                    f"Renew TLS certificate for {endpoint} immediately. "
                    f"Required by: {', '.join(dep.get('required_by') or []) or 'unknown'}"
                ),
                readiness_impact=(
                    "Dependent services will fail on TLS handshake once the certificate expires"
                ),
            ))
        elif days <= CERT_EXPIRY_ORANGE_DAYS:
            gaps.append(Gap(
                component_id=f"external:{dep_id}",
                gap_type="CERT_EXPIRY",
                severity="ORANGE",
                description=(
                    f"Certificate for '{dep_name}' ({endpoint}) expires in {days} day(s) "
                    f"— renewal required within 30 days"
                ),
                remediation=(
                    f"Renew TLS certificate for {endpoint} before expiry. "
                    f"Required by: {', '.join(dep.get('required_by') or []) or 'unknown'}"
                ),
                readiness_impact=(
                    "Certificate expiry will disrupt dependent services if not renewed"
                ),
            ))
        elif days <= CERT_EXPIRY_YELLOW_DAYS:
            gaps.append(Gap(
                component_id=f"external:{dep_id}",
                gap_type="CERT_EXPIRY",
                severity="YELLOW",
                description=(
                    f"Certificate for '{dep_name}' ({endpoint}) expires in {days} day(s) "
                    f"— plan renewal soon"
                ),
                remediation=(
                    f"Schedule TLS certificate renewal for {endpoint}. "
                    f"Required by: {', '.join(dep.get('required_by') or []) or 'unknown'}"
                ),
                readiness_impact=(
                    "Certificate will expire within 60 days; plan renewal to avoid disruption"
                ),
            ))

    return gaps


def _score_provenance_completeness(graph, manifest: dict) -> list:
    """
    Check deployment provenance completeness for every VM node in the graph.

    Each VM without a provenance record gets a YELLOW gap. Non-VM nodes
    (host, storage, network) are not checked — they are not provisioned
    by OpenTofu + Ansible and have no meaningful provenance record.
    """
    prov_reg = manifest.get("provenance_registry") or []
    by_vmid = {}
    for r in prov_reg:
        vmid = r.get("vmid")
        if vmid is not None:
            try:
                by_vmid[int(vmid)] = r
            except (TypeError, ValueError):
                pass

    gaps: list[Gap] = []
    for node in graph.nodes:
        if node.type != "vm":
            continue
        vmid = node.metadata.get("vmid")
        if vmid is None:
            continue
        try:
            if int(vmid) not in by_vmid:
                gaps.append(Gap(
                    component_id=node.id,
                    gap_type="MISSING_PROVENANCE",
                    severity="YELLOW",
                    description=(
                        f"No provenance record for {node.label} (vmid={vmid}) — "
                        f"deployed state cannot be verified against repository"
                    ),
                    remediation=(
                        "Record tofu workspace, ansible commit, and cloud-init hashes "
                        "in bootstrap-state.json provenance_records after deployment"
                    ),
                    readiness_impact=(
                        "Cannot confirm reconstruction will reproduce the original deployment; "
                        "drift between repository and running state is undetectable"
                    ),
                ))
        except (TypeError, ValueError):
            pass

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

    # Registry, provenance, service contract, external dependency, backup, network, phoenix
    registry_gaps = _score_registry_completeness(manifest)
    registry_gaps += _score_provenance_completeness(graph, manifest)
    registry_gaps += _score_template_registry_completeness(manifest)
    registry_gaps += _score_service_contract_completeness(graph, manifest)
    registry_gaps += _score_external_dependency_state(manifest)
    registry_gaps += _score_backup_config_completeness(manifest)
    registry_gaps += _score_network_topology_completeness(manifest)
    registry_gaps += _score_phoenix_playbook_existence(manifest)

    # Overall score — worst of component scores and infrastructure gaps
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
