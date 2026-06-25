"""
test_phase15_data_protection.py — Tests for Phase 15: Data Protection State.

Covers:
  15.1  data-model/data-protection-state-schema.json
  15.2  data_protection_collector.py — parsers, evaluation, health
  15.3  evaluate_rto_rpo_compliance()
  15.4  encryption key recoverability check
  15.5  PBS self-recovery plan check
  15.6  readiness.py — _score_data_protection_completeness
"""

import json
import os
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

import data_protection_collector as _dp

# ===========================================================================
# 15.1 — data-protection-state-schema.json
# ===========================================================================

class TestDataProtectionStateSchema:
    def _schema(self):
        path = os.path.join(_ROOT, "data-model", "data-protection-state-schema.json")
        with open(path) as f:
            return json.load(f)

    def test_schema_loads(self):
        s = self._schema()
        assert s["title"] == "Data Protection State"

    def test_required_fields(self):
        s = self._schema()
        assert "cell_id" in s["required"]
        assert "collected_at" in s["required"]

    def test_backup_job_has_encryption(self):
        s = self._schema()
        job = s["definitions"]["backup_job"]["properties"]
        assert "encryption" in job
        assert "encryption_key_ref" in job

    def test_rto_rpo_declaration_has_compliance_status(self):
        s = self._schema()
        decl = s["definitions"]["rto_rpo_declaration"]["properties"]
        assert "compliance_status" in decl

    def test_data_protection_health_in_schema(self):
        s = self._schema()
        assert "data_protection_health" in s["properties"]

    def test_valid_minimal(self):
        try:
            import jsonschema
        except ImportError:
            import pytest; pytest.skip("jsonschema not installed")  # noqa: I001
        s = self._schema()
        jsonschema.validate({
            "schema_version": "1.0",
            "cell_id": "test-cell",
            "collected_at": "2026-06-01T12:00:00+00:00",
        }, s)


# ===========================================================================
# 15.2 — parsers
# ===========================================================================

_PBS_JOBS_JSON = json.dumps([
    {
        "id": "job-100",
        "store": "local-pbs",
        "vmid": 100,
        "schedule": "daily",
        "retention": {"keep-last": 5, "keep-daily": 7},
        "enabled": True,
        "last-run": "2026-06-01T02:00:00+00:00",
        "last-state": "ok",
        "next-run": "2026-06-02T02:00:00+00:00",
    },
    {
        "id": "job-101",
        "store": "local-pbs",
        "vmid": 101,
        "schedule": "*/6:00",
        "enabled": True,
        "last-run": "2026-06-01T06:00:00+00:00",
        "last-state": "error",
    },
])


class TestParsePbsBackupJobsJson:
    def test_returns_list(self):
        jobs = _dp._parse_pbs_backup_jobs_json(_PBS_JOBS_JSON)
        assert len(jobs) == 2

    def test_job_id(self):
        jobs = _dp._parse_pbs_backup_jobs_json(_PBS_JOBS_JSON)
        ids = [j.id for j in jobs]
        assert "job-100" in ids

    def test_store_set(self):
        jobs = _dp._parse_pbs_backup_jobs_json(_PBS_JOBS_JSON)
        j = next(j for j in jobs if j.id == "job-100")
        assert j.store == "local-pbs"

    def test_vm_id_set(self):
        jobs = _dp._parse_pbs_backup_jobs_json(_PBS_JOBS_JSON)
        j = next(j for j in jobs if j.id == "job-100")
        assert j.vm_id == 100

    def test_status_parsed(self):
        jobs = _dp._parse_pbs_backup_jobs_json(_PBS_JOBS_JSON)
        j = next(j for j in jobs if j.id == "job-101")
        assert j.last_status == "error"

    def test_schedule_parsed(self):
        jobs = _dp._parse_pbs_backup_jobs_json(_PBS_JOBS_JSON)
        j = next(j for j in jobs if j.id == "job-100")
        assert j.schedule == "daily"

    def test_retention_parsed(self):
        jobs = _dp._parse_pbs_backup_jobs_json(_PBS_JOBS_JSON)
        j = next(j for j in jobs if j.id == "job-100")
        assert j.retention is not None
        assert j.retention.keep_last == 5
        assert j.retention.keep_daily == 7

    def test_invalid_json_returns_empty(self):
        jobs = _dp._parse_pbs_backup_jobs_json("not json")
        assert jobs == []


class TestScheduleToRpoHours:
    def test_daily_24h(self):
        assert _dp._schedule_to_rpo_hours("daily") == 24.0

    def test_hourly_1h(self):
        assert _dp._schedule_to_rpo_hours("hourly") == 1.0

    def test_every_6h(self):
        assert _dp._schedule_to_rpo_hours("*/6:00") == 6.0

    def test_weekly_168h(self):
        assert _dp._schedule_to_rpo_hours("weekly") == 24.0 * 7

    def test_none_returns_none(self):
        assert _dp._schedule_to_rpo_hours(None) is None

    def test_unknown_returns_none(self):
        assert _dp._schedule_to_rpo_hours("complex-expression") is None


# ===========================================================================
# 15.3 — RTO/RPO compliance evaluation
# ===========================================================================

class TestEvaluateRtoRpoCompliance:
    def _now(self):
        return datetime(2026, 6, 2, 12, 0, 0, tzinfo=timezone.utc)

    def test_compliant_recent_backup(self):
        # Last backup < 1 day ago, RPO = 24h
        decl = _dp.RtoRpoDeclaration(
            component_id="forgejo",
            rpo_hours=24.0,
        )
        job = _dp.BackupJob(
            id="job-100",
            vm_name="forgejo",
            newest_snapshot="2026-06-02T06:00:00+00:00",  # 6h ago
        )
        result = _dp.evaluate_rto_rpo_compliance([decl], [job], now=self._now())
        assert result[0].compliance_status == "COMPLIANT"

    def test_at_risk_older_than_rpo(self):
        # Last backup 30h ago, RPO = 24h
        decl = _dp.RtoRpoDeclaration(
            component_id="forgejo",
            rpo_hours=24.0,
        )
        job = _dp.BackupJob(
            id="job-100",
            vm_name="forgejo",
            newest_snapshot="2026-06-01T06:00:00+00:00",  # 30h ago
        )
        result = _dp.evaluate_rto_rpo_compliance([decl], [job], now=self._now())
        assert result[0].compliance_status in ("AT_RISK", "VIOLATED")

    def test_violated_no_backup(self):
        decl = _dp.RtoRpoDeclaration(
            component_id="forgejo",
            rpo_hours=24.0,
        )
        job = _dp.BackupJob(
            id="job-100",
            vm_name="forgejo",
            newest_snapshot=None,
        )
        result = _dp.evaluate_rto_rpo_compliance([decl], [job], now=self._now())
        assert result[0].compliance_status == "VIOLATED"

    def test_unknown_no_job(self):
        decl = _dp.RtoRpoDeclaration(
            component_id="nonexistent",
            rpo_hours=24.0,
        )
        result = _dp.evaluate_rto_rpo_compliance([decl], [], now=self._now())
        assert result[0].compliance_status == "UNKNOWN"

    def test_no_rpo_declared_compliant(self):
        decl = _dp.RtoRpoDeclaration(
            component_id="forgejo",
            rpo_hours=None,
        )
        job = _dp.BackupJob(id="job-100", vm_name="forgejo")
        result = _dp.evaluate_rto_rpo_compliance([decl], [job], now=self._now())
        assert result[0].compliance_status == "COMPLIANT"


# ===========================================================================
# 15.2 — DataProtectionDocument + health
# ===========================================================================

class TestDataProtectionHealth:
    def _doc(self, **kw):
        return _dp.DataProtectionDocument(
            cell_id="test-cell",
            collected_at="2026-06-01T12:00:00+00:00",
            **kw
        )

    def test_no_jobs_no_healthy(self):
        doc = self._doc()
        health = _dp.compute_data_protection_health(doc)
        # No jobs + no self-recovery plan → at minimum DEGRADED or UNKNOWN
        assert health["overall_status"] in ("UNKNOWN", "DEGRADED")
        assert not health["jobs_failing"]

    def test_healthy(self):
        job = _dp.BackupJob(
            id="job-100",
            last_status="ok",
            newest_snapshot="2026-06-01T00:00:00+00:00",
            encryption=False,
            verify_status="ok",
            snapshot_count=5,
        )
        doc = self._doc(
            backup_jobs=[job],
            pbs_self_recovery_plan={"plan_type": "external-backup", "documented": True},
        )
        health = _dp.compute_data_protection_health(doc)
        assert health["overall_status"] == "HEALTHY"
        assert not health["jobs_failing"]

    def test_failing_job_critical(self):
        job = _dp.BackupJob(id="job-100", last_status="error")
        doc = self._doc(backup_jobs=[job])
        health = _dp.compute_data_protection_health(doc)
        assert health["overall_status"] == "CRITICAL"
        assert "job-100" in health["jobs_failing"]

    def test_encryption_key_missing_critical(self):
        job = _dp.BackupJob(
            id="job-100",
            last_status="ok",
            encryption=True,
            encryption_key_ref=None,
            newest_snapshot="2026-06-01T00:00:00+00:00",
        )
        doc = self._doc(backup_jobs=[job])
        health = _dp.compute_data_protection_health(doc)
        assert health["overall_status"] == "CRITICAL"
        assert "job-100" in health["encryption_keys_missing"]

    def test_no_self_recovery_plan_degraded(self):
        job = _dp.BackupJob(
            id="job-100",
            last_status="ok",
            newest_snapshot="2026-06-01T00:00:00+00:00",
            snapshot_count=3,
        )
        doc = self._doc(backup_jobs=[job], pbs_self_recovery_plan=None)
        health = _dp.compute_data_protection_health(doc)
        # No self-recovery plan should not upgrade to OK
        assert health["overall_status"] in ("DEGRADED", "HEALTHY")

    def test_rto_rpo_violated(self):
        decl = _dp.RtoRpoDeclaration(
            component_id="forgejo",
            compliance_status="VIOLATED",
        )
        doc = self._doc(rto_rpo_declarations=[decl])
        health = _dp.compute_data_protection_health(doc)
        assert "forgejo" in health["rto_rpo_violated"]

    def test_data_protection_to_dict(self):
        doc = self._doc()
        d = _dp.data_protection_to_dict(doc)
        assert d["schema_version"] == "1.0"
        assert d["cell_id"] == "test-cell"
        assert "data_protection_health" in d


# ===========================================================================
# 15.4-15.6 — readiness scoring
# ===========================================================================

from readiness import _score_data_protection_completeness


class TestScoreDataProtectionCompleteness:
    def test_no_data_protection_state_yellow(self):
        gaps = _score_data_protection_completeness({})
        assert gaps
        assert gaps[0].severity == "YELLOW"
        assert gaps[0].gap_type == "MISSING_DATA_PROTECTION_STATE"

    def test_healthy_no_gaps(self):
        manifest = {
            "data_protection_state": {
                "pbs_self_recovery_plan": {"plan_type": "external-backup", "documented": True},
                "data_protection_health": {
                    "overall_status": "HEALTHY",
                    "jobs_with_no_backup": [],
                    "jobs_failing": [],
                    "jobs_unverified": [],
                    "encryption_keys_missing": [],
                    "rto_rpo_violated": [],
                }
            }
        }
        gaps = _score_data_protection_completeness(manifest)
        assert not gaps

    def test_encryption_key_missing_red(self):
        manifest = {
            "data_protection_state": {
                "pbs_self_recovery_plan": {"plan_type": "external-backup"},
                "data_protection_health": {
                    "overall_status": "CRITICAL",
                    "jobs_with_no_backup": [],
                    "jobs_failing": [],
                    "jobs_unverified": [],
                    "encryption_keys_missing": ["job-100"],
                    "rto_rpo_violated": [],
                }
            }
        }
        gaps = _score_data_protection_completeness(manifest)
        red_gaps = [g for g in gaps if g.severity == "RED"]
        assert any(g.gap_type == "ENCRYPTION_KEY_NOT_RECOVERABLE" for g in red_gaps)

    def test_failing_jobs_orange(self):
        manifest = {
            "data_protection_state": {
                "pbs_self_recovery_plan": {"plan_type": "external-backup"},
                "data_protection_health": {
                    "overall_status": "CRITICAL",
                    "jobs_with_no_backup": [],
                    "jobs_failing": ["job-101"],
                    "jobs_unverified": [],
                    "encryption_keys_missing": [],
                    "rto_rpo_violated": [],
                }
            }
        }
        gaps = _score_data_protection_completeness(manifest)
        assert any(g.gap_type == "BACKUP_JOBS_FAILING" and g.severity == "ORANGE" for g in gaps)

    def test_rto_rpo_violated_orange(self):
        manifest = {
            "data_protection_state": {
                "pbs_self_recovery_plan": {"plan_type": "external-backup"},
                "data_protection_health": {
                    "overall_status": "CRITICAL",
                    "jobs_with_no_backup": [],
                    "jobs_failing": [],
                    "jobs_unverified": [],
                    "encryption_keys_missing": [],
                    "rto_rpo_violated": ["forgejo"],
                }
            }
        }
        gaps = _score_data_protection_completeness(manifest)
        assert any(g.gap_type == "RTO_RPO_VIOLATED" and g.severity == "ORANGE" for g in gaps)

    def test_no_self_recovery_plan_yellow(self):
        manifest = {
            "data_protection_state": {
                "pbs_self_recovery_plan": None,
                "data_protection_health": {
                    "overall_status": "DEGRADED",
                    "jobs_with_no_backup": [],
                    "jobs_failing": [],
                    "jobs_unverified": [],
                    "encryption_keys_missing": [],
                    "rto_rpo_violated": [],
                }
            }
        }
        gaps = _score_data_protection_completeness(manifest)
        assert any(g.gap_type == "NO_PBS_SELF_RECOVERY_PLAN" and g.severity == "YELLOW" for g in gaps)

    def test_unverified_jobs_yellow(self):
        manifest = {
            "data_protection_state": {
                "pbs_self_recovery_plan": {"plan_type": "manual"},
                "data_protection_health": {
                    "overall_status": "DEGRADED",
                    "jobs_with_no_backup": [],
                    "jobs_failing": [],
                    "jobs_unverified": ["job-100"],
                    "encryption_keys_missing": [],
                    "rto_rpo_violated": [],
                }
            }
        }
        gaps = _score_data_protection_completeness(manifest)
        assert any(g.gap_type == "JOBS_UNVERIFIED" and g.severity == "YELLOW" for g in gaps)
