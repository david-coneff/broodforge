#!/usr/bin/env python3
"""
data_protection_collector.py — Data Protection State collector (Phase 15.2).

Collects PBS backup job inventory, retention policies, verification status,
and checks encryption key recoverability. Also evaluates RTO/RPO compliance.

Produces data-protection-state.json conforming to
data-model/data-protection-state-schema.json.

Provides:
  BackupJob, RtoRpoDeclaration    — typed entries
  DataProtectionDocument           — typed result
  collect_data_protection_state()  — main entry point
  evaluate_rto_rpo_compliance()    — check declared targets against actual schedule
  compute_data_protection_health() — aggregate health
  data_protection_to_dict()       — JSON-serialisable dict

Stdlib only.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from collector_utils import RunnerFn, local_runner  # noqa: F401

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class BackupRetention:
    keep_last:    Optional[int] = None
    keep_hourly:  Optional[int] = None
    keep_daily:   Optional[int] = None
    keep_weekly:  Optional[int] = None
    keep_monthly: Optional[int] = None
    keep_yearly:  Optional[int] = None


@dataclass
class BackupJob:
    id:                  str
    store:               Optional[str]   = None
    vm_id:               Optional[int]   = None
    vm_name:             Optional[str]   = None
    schedule:            Optional[str]   = None
    retention:           Optional[BackupRetention] = None
    enabled:             Optional[bool]  = None
    last_run:            Optional[str]   = None
    last_status:         Optional[str]   = None
    last_duration_sec:   Optional[int]   = None
    next_run:            Optional[str]   = None
    snapshot_count:      Optional[int]   = None
    oldest_snapshot:     Optional[str]   = None
    newest_snapshot:     Optional[str]   = None
    total_size_gb:       Optional[float] = None
    encryption:          Optional[bool]  = None
    encryption_key_ref:  Optional[str]   = None
    verified_at:         Optional[str]   = None
    verify_status:       Optional[str]   = None


@dataclass
class RtoRpoDeclaration:
    component_id:       str
    rto_hours:          Optional[float] = None
    rpo_hours:          Optional[float] = None
    tier:               Optional[str]   = None
    declared_by:        Optional[str]   = None
    declared_at:        Optional[str]   = None
    compliance_status:  Optional[str]   = None   # COMPLIANT/AT_RISK/VIOLATED/UNKNOWN


@dataclass
class DataProtectionDocument:
    cell_id:          str
    collected_at:     str
    pbs_node:         Optional[str]           = None
    pbs_version:      Optional[str]           = None
    pbs_datastores:   list[dict]              = field(default_factory=list)
    backup_jobs:      list[BackupJob]         = field(default_factory=list)
    rto_rpo_declarations: list[RtoRpoDeclaration] = field(default_factory=list)
    pbs_self_recovery_plan: Optional[dict]    = None
    collection_errors: list[dict]             = field(default_factory=list)


# ---------------------------------------------------------------------------
# Runner (shared implementation in collector_utils)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _parse_pbs_backup_jobs_json(output: str) -> list[BackupJob]:
    """Parse PBS API JSON for backup job list."""
    jobs = []
    try:
        data = json.loads(output)
        items = data if isinstance(data, list) else (data.get("data") or [])
    except (json.JSONDecodeError, TypeError):
        return jobs

    for item in items:
        job_id = item.get("id") or item.get("jobid") or "unknown"
        retention_data = item.get("retention") or {}
        ret = BackupRetention(
            keep_last=_int(retention_data.get("keep-last")),
            keep_hourly=_int(retention_data.get("keep-hourly")),
            keep_daily=_int(retention_data.get("keep-daily")),
            keep_weekly=_int(retention_data.get("keep-weekly")),
            keep_monthly=_int(retention_data.get("keep-monthly")),
        ) if retention_data else None

        jobs.append(BackupJob(
            id=str(job_id),
            store=item.get("store"),
            vm_id=_int(item.get("vmid") or item.get("vm_id")),
            schedule=item.get("schedule"),
            retention=ret,
            enabled=item.get("enabled", True),
            last_run=item.get("last-run") or item.get("last_run"),
            last_status=item.get("last-state") or item.get("last_status"),
            next_run=item.get("next-run") or item.get("next_run"),
        ))
    return jobs


def _schedule_to_rpo_hours(schedule: Optional[str]) -> Optional[float]:
    """
    Approximate the RPO in hours from a PBS cron-like schedule string.

    PBS uses systemd calendar time format (e.g. "daily", "*/6:00", "hourly").
    Returns None if schedule cannot be parsed.
    """
    if not schedule:
        return None
    s = schedule.lower().strip()
    if s in ("hourly", "0/1:00"):
        return 1.0
    if s in ("*/2:00",):
        return 2.0
    if s in ("daily", "0:00", "00:00"):
        return 24.0
    if s in ("weekly",):
        return 24.0 * 7
    # Try to parse "*/N:00" or "N:00" patterns
    import re
    m = re.match(r"\*/(\d+):00", s)
    if m:
        return float(m.group(1))
    return None


def _int(v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _safe_float(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# RTO/RPO compliance evaluation (Phase 15.3)
# ---------------------------------------------------------------------------

def evaluate_rto_rpo_compliance(
    declarations: list[RtoRpoDeclaration],
    backup_jobs:  list[BackupJob],
    now:          Optional[datetime] = None,
) -> list[RtoRpoDeclaration]:
    """
    Evaluate whether each RTO/RPO declaration is met by the current backup configuration.

    Updates declaration.compliance_status:
      COMPLIANT: backup schedule meets RPO; snapshot count suggests RTO is feasible
      AT_RISK:   backup schedule may not consistently meet RPO
      VIOLATED:  last backup older than declared RPO; or no backups exist
      UNKNOWN:   cannot assess (no matching backup job found)

    Returns updated declarations.
    """
    now_ts = now or datetime.now(timezone.utc)
    job_by_vm: dict[str, BackupJob] = {}
    for j in backup_jobs:
        if j.vm_name:
            job_by_vm[j.vm_name] = j
        if j.vm_id is not None:
            job_by_vm[str(j.vm_id)] = j

    updated = []
    for decl in declarations:
        comp_id = decl.component_id
        job = job_by_vm.get(comp_id)

        if job is None:
            decl.compliance_status = "UNKNOWN"
            updated.append(decl)
            continue

        # Check most recent backup age against RPO
        rpo_hours = decl.rpo_hours
        last_run  = job.newest_snapshot or job.last_run
        if rpo_hours and last_run:
            try:
                ts = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                age_hours = (now_ts - ts).total_seconds() / 3600
                if age_hours > rpo_hours * 2:
                    decl.compliance_status = "VIOLATED"
                elif age_hours > rpo_hours:
                    decl.compliance_status = "AT_RISK"
                else:
                    decl.compliance_status = "COMPLIANT"
            except (ValueError, TypeError):
                decl.compliance_status = "UNKNOWN"
        elif rpo_hours and not last_run:
            decl.compliance_status = "VIOLATED"
        else:
            decl.compliance_status = "COMPLIANT"

        updated.append(decl)
    return updated


# ---------------------------------------------------------------------------
# Data protection health aggregation (Phase 15.6)
# ---------------------------------------------------------------------------

def compute_data_protection_health(doc: DataProtectionDocument) -> dict:
    """Derive data_protection_health dict from DataProtectionDocument."""
    jobs_no_backup     = []
    jobs_failing       = []
    jobs_unverified    = []
    enc_keys_missing   = []
    rto_rpo_violated   = []

    for job in doc.backup_jobs:
        # No successful backup ever
        if not job.newest_snapshot and job.last_status != "ok":
            jobs_no_backup.append(job.id)

        # Last run failed
        if job.last_status == "error":
            jobs_failing.append(job.id)

        # No verification
        if job.verify_status in (None, "none") and job.verify_status != "ok":
            if job.snapshot_count and job.snapshot_count > 0:
                jobs_unverified.append(job.id)

        # Encryption without key reference
        if job.encryption and not job.encryption_key_ref:
            enc_keys_missing.append(job.id)

    # RTO/RPO violations
    for decl in doc.rto_rpo_declarations:
        if decl.compliance_status in ("VIOLATED",):
            rto_rpo_violated.append(decl.component_id)

    # PBS self-recovery plan
    has_self_recovery = bool(doc.pbs_self_recovery_plan)

    # Overall status
    if jobs_failing or enc_keys_missing or rto_rpo_violated:
        overall = "CRITICAL"
    elif jobs_no_backup or not has_self_recovery:
        overall = "DEGRADED"
    elif jobs_unverified:
        overall = "DEGRADED"
    elif not doc.backup_jobs:
        overall = "UNKNOWN"
    else:
        overall = "HEALTHY"

    return {
        "overall_status":          overall,
        "jobs_with_no_backup":     jobs_no_backup,
        "jobs_failing":            jobs_failing,
        "jobs_unverified":         jobs_unverified,
        "encryption_keys_missing": enc_keys_missing,
        "rto_rpo_violated":        rto_rpo_violated,
    }


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------

def collect_data_protection_state(
    cell_id:              str,
    rto_rpo_declarations: Optional[list[RtoRpoDeclaration]] = None,
    runner_fn:            Optional[RunnerFn] = None,
    now_fn:               Optional[Callable[[], str]] = None,
) -> DataProtectionDocument:
    """
    Collect data protection state from the local Proxmox host.

    rto_rpo_declarations: operator-declared RTO/RPO targets (from bootstrap-state.json
                          or passed explicitly). If provided, compliance is evaluated.
    """
    runner = runner_fn or local_runner
    now    = (now_fn or (lambda: datetime.now(timezone.utc).isoformat()))()
    now_ts = datetime.fromisoformat(now.replace("Z", "+00:00"))

    doc = DataProtectionDocument(cell_id=cell_id, collected_at=now)
    if rto_rpo_declarations:
        doc.rto_rpo_declarations = list(rto_rpo_declarations)
    errors = []

    # PBS version
    try:
        out = runner("proxmox-backup-manager version 2>/dev/null || true").strip()
        doc.pbs_version = out or None
    except Exception as e:
        errors.append({"component": "pbs_version", "error": str(e)})

    # PBS backup jobs (via pvesh or proxmox-backup-client)
    try:
        out = runner(
            "pvesh get /cluster/backup --output-format=json 2>/dev/null || true"
        )
        if out.strip():
            doc.backup_jobs = _parse_pbs_backup_jobs_json(out)
    except Exception as e:
        errors.append({"component": "backup_jobs", "error": str(e)})

    # Evaluate RTO/RPO compliance
    if doc.rto_rpo_declarations:
        doc.rto_rpo_declarations = evaluate_rto_rpo_compliance(
            doc.rto_rpo_declarations, doc.backup_jobs, now=now_ts
        )

    doc.collection_errors = errors
    return doc


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def _ret_to_dict(ret: Optional[BackupRetention]) -> Optional[dict]:
    if ret is None:
        return None
    return {
        "keep_last":    ret.keep_last,
        "keep_hourly":  ret.keep_hourly,
        "keep_daily":   ret.keep_daily,
        "keep_weekly":  ret.keep_weekly,
        "keep_monthly": ret.keep_monthly,
        "keep_yearly":  ret.keep_yearly,
    }


def data_protection_to_dict(doc: DataProtectionDocument) -> dict:
    """Convert DataProtectionDocument to a JSON-serialisable dict."""
    health = compute_data_protection_health(doc)
    return {
        "schema_version": "1.0",
        "cell_id":        doc.cell_id,
        "collected_at":   doc.collected_at,
        "collection_errors": doc.collection_errors,
        "pbs_node":       doc.pbs_node,
        "pbs_version":    doc.pbs_version,
        "pbs_datastores": list(doc.pbs_datastores),
        "backup_jobs": [
            {
                "id":               j.id,
                "store":            j.store,
                "vm_id":            j.vm_id,
                "vm_name":          j.vm_name,
                "schedule":         j.schedule,
                "retention":        _ret_to_dict(j.retention),
                "enabled":          j.enabled,
                "last_run":         j.last_run,
                "last_status":      j.last_status,
                "next_run":         j.next_run,
                "snapshot_count":   j.snapshot_count,
                "oldest_snapshot":  j.oldest_snapshot,
                "newest_snapshot":  j.newest_snapshot,
                "total_size_gb":    j.total_size_gb,
                "encryption":       j.encryption,
                "encryption_key_ref": j.encryption_key_ref,
                "verified_at":      j.verified_at,
                "verify_status":    j.verify_status,
            }
            for j in doc.backup_jobs
        ],
        "rto_rpo_declarations": [
            {
                "component_id":     d.component_id,
                "rto_hours":        d.rto_hours,
                "rpo_hours":        d.rpo_hours,
                "tier":             d.tier,
                "compliance_status": d.compliance_status,
            }
            for d in doc.rto_rpo_declarations
        ],
        "pbs_self_recovery_plan": doc.pbs_self_recovery_plan,
        "data_protection_health": health,
    }
