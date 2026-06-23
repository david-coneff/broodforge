"""
test_remediation.py — Phase 26: Autonomous Remediation.

Covers:
  26.1  RemediationProposal, build_remediation_plan, dry_run_proposal,
        proposal deduplication, serialization
  26.2  RemediationQueue, state machine transitions, load/save,
        approve, reject, batch_approve, expire, supersede
  26.3  RemediationExecutor, execute_proposal, all action handlers,
        failure package, resistance check, KeePass gate
  26.4  Dashboard remediation helpers (_remediations_from_state,
        generate_dashboard_html with remediations)
  26.5  Operational report Section 8 (_section_remediation_summary)
  26.6  RemediationPolicy, is_auto_approvable, is_blocked,
        check_execution_window, CrossCellProposal
  26.7  AutonomousMode: enable, disable, expiry, hard exclusions,
        auto-disable triggers, guard checks
"""



import remediation_executor as _re
import remediation_planner as _rp
import remediation_policy as _pol
import remediation_queue as _rq

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _now():
    return "2026-06-02T12:00:00+00:00"

def _later():
    return "2026-06-02T13:00:00+00:00"


def _state(cell_id="pve01-cell"):
    return {
        "cell_id": cell_id,
        "declared_at": "2026-06-02T11:59:00+00:00",
        "host_identity": {"hostname": "pve01", "fqdn": "pve01.home.example.com"},
        "network_topology": {"ssl_provider": "certbot"},
        "backup_config": {"destinations": [{"type": "local", "path": "/mnt/backup"}]},
        "dns_registry": [{"hostname": "forgejo", "ip": "192.168.1.101"}],
        "remediations": [],
        "remediation_policy": {},
    }


def _gap(gap_type, severity="YELLOW", comp_id="forgejo"):
    return {"gap_type": gap_type, "severity": severity, "component_id": comp_id,
            "description": f"Test gap: {gap_type}"}


class _ReadinessStub:
    def __init__(self, gaps=None):
        self.overall_score = "YELLOW"
        self.components = [_CompStub(gaps or [])]


class _CompStub:
    def __init__(self, gaps):
        self.component_id = "test-component"
        self.gaps = [_GapStub(g) for g in gaps]


class _GapStub:
    def __init__(self, d):
        self.gap_type    = d.get("gap_type", "")
        self.severity    = d.get("severity", "YELLOW")
        self.component_id= d.get("component_id", "test")
        self.description = d.get("description", "")


def _mock_runner(success=True, output="ok"):
    def runner(cmd, cwd=None):
        return (0 if success else 1), output, ("" if success else "mock error")
    return runner


# ===========================================================================
# 26.1 — Remediation Planner
# ===========================================================================

class TestRemediationPlanner:

    def test_allowed_action_types_complete(self):
        assert "restart-service"          in _rp.ALLOWED_ACTION_TYPES
        assert "run-backup"               in _rp.ALLOWED_ACTION_TYPES
        assert "renew-cert"               in _rp.ALLOWED_ACTION_TYPES
        assert "regenerate-phoenix"       in _rp.ALLOWED_ACTION_TYPES
        assert "sync-cert-to-k8s"        in _rp.ALLOWED_ACTION_TYPES
        assert "rotate-join-token"        in _rp.ALLOWED_ACTION_TYPES
        assert "restart-assessment-timer" in _rp.ALLOWED_ACTION_TYPES
        assert "schedule-drill"           in _rp.ALLOWED_ACTION_TYPES
        assert "flag-manual"              in _rp.ALLOWED_ACTION_TYPES

    def test_proposal_dataclass_fields(self):
        p = _rp.RemediationProposal(
            proposal_id="pid", issue_id="comp:type", severity="YELLOW",
            action_type="restart-service", action_description="restart x",
            target="forgejo", dry_run_output="[dry-run]",
            reversibility="reversible", estimated_duration_seconds=10,
            proposed_at=_now(),
        )
        assert p.status == "proposed"
        assert p.proposal_id == "pid"
        assert not p.resisted

    def test_build_plan_service_not_running(self):
        readiness = _ReadinessStub([_gap("service_not_running", "RED", "forgejo")])
        plan = _rp.build_remediation_plan(readiness, _state(), now_fn=_now)
        assert len(plan.proposals) == 1
        assert plan.proposals[0].action_type == "restart-service"
        assert plan.proposals[0].severity == "RED"
        assert plan.proposals[0].target == "forgejo"

    def test_build_plan_backup_stale(self):
        readiness = _ReadinessStub([_gap("backup_stale", "ORANGE", "config")])
        plan = _rp.build_remediation_plan(readiness, _state(), now_fn=_now)
        assert len(plan.proposals) == 1
        assert plan.proposals[0].action_type == "run-backup"

    def test_build_plan_cert_expiry(self):
        readiness = _ReadinessStub([_gap("cert_expiry_critical", "RED", "cloudflare-dns")])
        plan = _rp.build_remediation_plan(readiness, _state(), now_fn=_now)
        assert plan.proposals[0].action_type == "renew-cert"

    def test_build_plan_phoenix_missing(self):
        readiness = _ReadinessStub([_gap("phoenix_playbook_missing", "YELLOW", "pve01")])
        plan = _rp.build_remediation_plan(readiness, _state(), now_fn=_now)
        assert plan.proposals[0].action_type == "regenerate-phoenix"

    def test_build_plan_assessment_timer(self):
        readiness = _ReadinessStub([_gap("assessment_timer_inactive", "ORANGE")])
        plan = _rp.build_remediation_plan(readiness, _state(), now_fn=_now)
        assert plan.proposals[0].action_type == "restart-assessment-timer"

    def test_build_plan_drill_overdue(self):
        readiness = _ReadinessStub([_gap("drill_overdue", "YELLOW")])
        plan = _rp.build_remediation_plan(readiness, _state(), now_fn=_now)
        assert plan.proposals[0].action_type == "schedule-drill"

    def test_build_plan_join_token_stale(self):
        readiness = _ReadinessStub([_gap("join_token_stale", "ORANGE")])
        plan = _rp.build_remediation_plan(readiness, _state(), now_fn=_now)
        assert plan.proposals[0].action_type == "rotate-join-token"
        assert plan.proposals[0].keepass_gated is True

    def test_build_plan_unknown_gap_flags_manual(self):
        readiness = _ReadinessStub([_gap("some_unknown_gap", "YELLOW")])
        plan = _rp.build_remediation_plan(readiness, _state(), now_fn=_now)
        assert plan.proposals[0].action_type == "flag-manual"

    def test_deduplication_skips_active_identical(self):
        existing = [{
            "proposal_id": "existing-1", "issue_id": "forgejo:service_not_running",
            "action_type": "restart-service", "status": "proposed",
        }]
        readiness = _ReadinessStub([_gap("service_not_running", "RED", "forgejo")])
        plan = _rp.build_remediation_plan(readiness, _state(), existing_proposals=existing, now_fn=_now)
        assert len(plan.proposals) == 0  # deduped

    def test_deduplication_allows_after_terminal(self):
        existing = [{
            "proposal_id": "existing-1", "issue_id": "forgejo:service_not_running",
            "action_type": "restart-service", "status": "resolved",
        }]
        readiness = _ReadinessStub([_gap("service_not_running", "RED", "forgejo")])
        plan = _rp.build_remediation_plan(readiness, _state(), existing_proposals=existing, now_fn=_now)
        assert len(plan.proposals) == 1  # new proposal allowed after resolved

    def test_dry_run_restart_service(self):
        p = _rp.RemediationProposal(
            proposal_id="x", issue_id="svc:stop", severity="YELLOW",
            action_type="restart-service", action_description="",
            target="forgejo", dry_run_output="",
            reversibility="reversible", estimated_duration_seconds=10,
            proposed_at=_now(),
        )
        out = _rp.dry_run_proposal(p, _state())
        assert "[dry-run]" in out
        assert "forgejo" in out
        assert "No changes made" in out

    def test_dry_run_run_backup(self):
        p = _rp.RemediationProposal(
            proposal_id="x", issue_id="config:backup", severity="ORANGE",
            action_type="run-backup", action_description="",
            target="config", dry_run_output="",
            reversibility="reversible", estimated_duration_seconds=300,
            proposed_at=_now(),
        )
        out = _rp.dry_run_proposal(p, _state())
        assert "run-backup.py" in out
        assert "config" in out

    def test_dry_run_rotate_token_mentions_keepass(self):
        p = _rp.RemediationProposal(
            proposal_id="x", issue_id="k3s:stale", severity="ORANGE",
            action_type="rotate-join-token", action_description="",
            target="k3s-join-token", dry_run_output="",
            reversibility="manual-rollback", estimated_duration_seconds=30,
            proposed_at=_now(),
        )
        out = _rp.dry_run_proposal(p, _state())
        assert "KeePass" in out

    def test_serialization_roundtrip(self):
        p = _rp.RemediationProposal(
            proposal_id="abc-123", issue_id="comp:gap", severity="RED",
            action_type="renew-cert", action_description="Renew cert",
            target="mydomain", dry_run_output="certbot renew",
            reversibility="reversible", estimated_duration_seconds=60,
            proposed_at=_now(), keepass_gated=False,
        )
        d = _rp.proposal_to_dict(p)
        p2 = _rp.dict_to_proposal(d)
        assert p2.proposal_id == p.proposal_id
        assert p2.severity == p.severity
        assert p2.action_type == p.action_type
        assert p2.keepass_gated == p.keepass_gated

    def test_reversibility_assigned_correctly(self):
        readiness = _ReadinessStub([_gap("join_token_stale")])
        plan = _rp.build_remediation_plan(readiness, _state(), now_fn=_now)
        assert plan.proposals[0].reversibility == "manual-rollback"

    def test_plan_cell_id_set(self):
        readiness = _ReadinessStub([_gap("service_not_running")])
        plan = _rp.build_remediation_plan(readiness, _state("my-cell"), now_fn=_now)
        assert plan.cell_id == "my-cell"
        assert plan.proposals[0].cell_id == "my-cell"


# ===========================================================================
# 26.2 — Approval Queue
# ===========================================================================

class TestRemediationQueue:

    def _make_queue(self, state=None):
        s = state or _state()
        return _rq.load_queue(s)

    def _make_proposal(self, issue_id="comp:gap", action_type="restart-service",
                       severity="YELLOW"):
        return _rp.RemediationProposal(
            proposal_id=f"pid-{issue_id}", issue_id=issue_id, severity=severity,
            action_type=action_type, action_description="test",
            target="test-target", dry_run_output="[dry-run]",
            reversibility="reversible", estimated_duration_seconds=10,
            proposed_at=_now(), cell_id="pve01-cell",
        )

    def test_load_empty_queue(self):
        q = self._make_queue()
        assert len(q.proposals) == 0

    def test_load_queue_with_proposals(self):
        p = self._make_proposal()
        state = _state()
        state["remediations"] = [_rp.proposal_to_dict(p)]
        q = _rq.load_queue(state)
        assert len(q.proposals) == 1
        assert q.proposals[0].proposal_id == p.proposal_id

    def test_save_and_reload(self):
        q = self._make_queue()
        p = self._make_proposal()
        _rq.add_proposal(q, p, apply_auto_policy=False)
        s = _state()
        updated = _rq.save_queue(q, s)
        assert len(updated["remediations"]) == 1

    def test_add_proposal(self):
        q = self._make_queue()
        p = self._make_proposal()
        _rq.add_proposal(q, p, apply_auto_policy=False)
        assert len(q.proposals) == 1
        assert q.get(p.proposal_id) is q.proposals[0]

    def test_approve_proposed(self):
        q = self._make_queue()
        p = self._make_proposal()
        _rq.add_proposal(q, p, apply_auto_policy=False)
        ok = _rq.approve_proposal(q, p.proposal_id, "dave@pve01", "cli", now_fn=_now)
        assert ok is True
        assert q.get(p.proposal_id).status == "approved"
        assert q.get(p.proposal_id).approved_by == "dave@pve01"

    def test_approve_nonexistent_returns_false(self):
        q = self._make_queue()
        assert _rq.approve_proposal(q, "nonexistent", "x", "cli") is False

    def test_approve_already_approved_returns_false(self):
        q = self._make_queue()
        p = self._make_proposal()
        _rq.add_proposal(q, p, apply_auto_policy=False)
        _rq.approve_proposal(q, p.proposal_id, "x", "cli")
        # Cannot approve again from approved state (goes executing, not re-approve)
        ok = _rq.approve_proposal(q, p.proposal_id, "y", "cli")
        assert ok is False

    def test_reject_proposed(self):
        q = self._make_queue()
        p = self._make_proposal()
        _rq.add_proposal(q, p, apply_auto_policy=False)
        ok = _rq.reject_proposal(q, p.proposal_id, reason="not needed")
        assert ok is True
        assert q.get(p.proposal_id).status == "rejected"

    def test_reject_resolved_returns_false(self):
        q = self._make_queue()
        p = self._make_proposal()
        _rq.add_proposal(q, p, apply_auto_policy=False)
        _rq.approve_proposal(q, p.proposal_id, "x", "cli")
        _rq.mark_executing(q, p.proposal_id)
        _rq.mark_resolved(q, p.proposal_id, "done")
        ok = _rq.reject_proposal(q, p.proposal_id, "too late")
        assert ok is False

    def test_mark_executing(self):
        q = self._make_queue()
        p = self._make_proposal()
        _rq.add_proposal(q, p, apply_auto_policy=False)
        _rq.approve_proposal(q, p.proposal_id, "x", "cli")
        ok = _rq.mark_executing(q, p.proposal_id, now_fn=_now)
        assert ok is True
        assert q.get(p.proposal_id).status == "executing"
        assert q.get(p.proposal_id).started_at is not None

    def test_mark_resolved(self):
        q = self._make_queue()
        p = self._make_proposal()
        _rq.add_proposal(q, p, apply_auto_policy=False)
        _rq.approve_proposal(q, p.proposal_id, "x", "cli")
        _rq.mark_executing(q, p.proposal_id)
        ok = _rq.mark_resolved(q, p.proposal_id, "done", now_fn=_now)
        assert ok is True
        assert q.get(p.proposal_id).status == "resolved"

    def test_mark_failed(self):
        q = self._make_queue()
        p = self._make_proposal()
        _rq.add_proposal(q, p, apply_auto_policy=False)
        _rq.approve_proposal(q, p.proposal_id, "x", "cli")
        _rq.mark_executing(q, p.proposal_id)
        ok = _rq.mark_failed(q, p.proposal_id, "exec error")
        assert ok is True
        assert q.get(p.proposal_id).status == "failed"

    def test_supersede_proposal(self):
        q = self._make_queue()
        p1 = self._make_proposal(issue_id="comp:gap")
        p1.proposal_id = "pid-old"
        p2 = self._make_proposal(issue_id="comp:gap")
        p2.proposal_id = "pid-new"
        _rq.add_proposal(q, p1, apply_auto_policy=False)
        ok = _rq.supersede_proposal(q, p1.proposal_id, p2)
        assert ok is True
        assert q.get("pid-old").status == "superseded"
        assert q.get("pid-new").status == "proposed"

    def test_expire_resolved_proposals(self):
        q = self._make_queue()
        p = self._make_proposal(issue_id="comp:gap")
        _rq.add_proposal(q, p, apply_auto_policy=False)
        # issue_id not in current gaps → should expire
        count = _rq.expire_resolved_proposals(q, current_issue_ids=set())
        assert count == 1
        assert q.get(p.proposal_id).status == "expired"

    def test_expire_keeps_active_issues(self):
        q = self._make_queue()
        p = self._make_proposal(issue_id="comp:gap")
        _rq.add_proposal(q, p, apply_auto_policy=False)
        count = _rq.expire_resolved_proposals(q, current_issue_ids={"comp:gap"})
        assert count == 0
        assert q.get(p.proposal_id).status == "proposed"

    def test_batch_approve(self):
        q = self._make_queue()
        p1 = self._make_proposal("a:b", severity="YELLOW")
        p2 = self._make_proposal("c:d", severity="ORANGE")
        p3 = self._make_proposal("e:f", severity="RED")
        for p in (p1, p2, p3):
            _rq.add_proposal(q, p, apply_auto_policy=False)
        count = _rq.batch_approve(q, "ORANGE", "auto", "cli")
        assert count == 2
        assert q.get(p1.proposal_id).status == "approved"
        assert q.get(p2.proposal_id).status == "approved"
        assert q.get(p3.proposal_id).status == "proposed"  # RED not approved

    def test_batch_approve_skips_never_auto(self):
        q = self._make_queue()
        p = self._make_proposal("k3s:token", action_type="rotate-join-token", severity="ORANGE")
        _rq.add_proposal(q, p, apply_auto_policy=False)
        count = _rq.batch_approve(q, "ORANGE", "auto", "cli")
        assert count == 0

    def test_get_pending(self):
        q = self._make_queue()
        p = self._make_proposal()
        _rq.add_proposal(q, p, apply_auto_policy=False)
        assert len(_rq.get_pending(q)) == 1

    def test_get_history(self):
        q = self._make_queue()
        p = self._make_proposal()
        _rq.add_proposal(q, p, apply_auto_policy=False)
        _rq.reject_proposal(q, p.proposal_id, now_fn=_now)
        hist = _rq.get_history(q)
        assert len(hist) == 1
        assert hist[0].status == "rejected"

    def test_queue_summary(self):
        q = self._make_queue()
        p1 = self._make_proposal("a:b", severity="YELLOW")
        p2 = self._make_proposal("c:d", severity="ORANGE")
        for p in (p1, p2):
            _rq.add_proposal(q, p, apply_auto_policy=False)
        s = _rq.queue_summary(q)
        assert s["total"] == 2
        assert s["by_status"].get("proposed", 0) == 2
        assert s["pending_by_severity"].get("YELLOW", 0) == 1

    def test_auto_approve_on_add_with_threshold(self):
        state = _state()
        state["remediation_policy"] = {"auto_approve_threshold": "YELLOW"}
        q = _rq.load_queue(state)
        p = self._make_proposal("a:b", severity="YELLOW")
        _rq.add_proposal(q, p, apply_auto_policy=True, now_fn=_now)
        assert q.get(p.proposal_id).status == "approved"
        assert q.get(p.proposal_id).approval_channel == "auto-policy"

    def test_auto_approve_does_not_approve_red(self):
        state = _state()
        state["remediation_policy"] = {"auto_approve_threshold": "ORANGE"}
        q = _rq.load_queue(state)
        p = self._make_proposal("a:b", severity="RED")
        _rq.add_proposal(q, p, apply_auto_policy=True, now_fn=_now)
        assert q.get(p.proposal_id).status == "proposed"


# ===========================================================================
# 26.3 — Executor
# ===========================================================================

class TestRemediationExecutor:

    def _approved_proposal(self, action_type="restart-service", severity="YELLOW"):
        # Build a valid proposal then populate dry_run_output from the actual fn
        p = _rp.RemediationProposal(
            proposal_id="test-pid", issue_id="comp:gap",
            severity=severity, action_type=action_type,
            action_description="test action", target="forgejo",
            dry_run_output="",
            reversibility=_rp._REVERSIBILITY.get(action_type, "reversible"),
            estimated_duration_seconds=_rp._ESTIMATED_DURATION.get(action_type, 10),
            proposed_at=_now(), cell_id="pve01-cell",
        )
        # Set dry_run_output to what the executor would produce so the diff check passes
        p.dry_run_output = _rp.dry_run_proposal(p, _state())
        return p

    def _make_executor(self, success=True, keepass_unlocked=False):
        return _re.RemediationExecutor(
            cell_id="pve01-cell",
            state_path="/tmp/test-state.json",
            runner_fn=_mock_runner(success),
            keepass_unlocked=keepass_unlocked,
        )

    def test_execute_requires_approved_status(self):
        p = self._approved_proposal()
        q = _rq.RemediationQueue(cell_id="pve01-cell")
        _rq.add_proposal(q, p, apply_auto_policy=False)
        # Proposal is 'proposed', not 'approved'
        ex = self._make_executor()
        result = _re.execute_proposal(ex, q, p.proposal_id, _state(), now_fn=_now)
        assert result.success is False
        assert "approved" in result.outcome.lower()

    def test_execute_restart_service_success(self):
        p = self._approved_proposal("restart-service")
        q = _rq.RemediationQueue(cell_id="pve01-cell")
        _rq.add_proposal(q, p, apply_auto_policy=False)
        _rq.approve_proposal(q, p.proposal_id, "x", "cli")
        ex = self._make_executor(success=True)
        result = _re.execute_proposal(ex, q, p.proposal_id, _state(), now_fn=_now)
        assert result.success is True
        assert q.get(p.proposal_id).status == "resolved"

    def test_execute_restart_service_failure(self):
        p = self._approved_proposal("restart-service")
        q = _rq.RemediationQueue(cell_id="pve01-cell")
        _rq.add_proposal(q, p, apply_auto_policy=False)
        _rq.approve_proposal(q, p.proposal_id, "x", "cli")
        ex = self._make_executor(success=False)
        result = _re.execute_proposal(ex, q, p.proposal_id, _state(), now_fn=_now)
        assert result.success is False
        assert q.get(p.proposal_id).status == "failed"
        assert result.failure_pkg is not None

    def test_execute_flag_manual_always_succeeds(self):
        p = self._approved_proposal("flag-manual")
        q = _rq.RemediationQueue(cell_id="pve01-cell")
        _rq.add_proposal(q, p, apply_auto_policy=False)
        _rq.approve_proposal(q, p.proposal_id, "x", "cli")
        ex = self._make_executor()
        result = _re.execute_proposal(ex, q, p.proposal_id, _state(), now_fn=_now)
        assert result.success is True

    def test_execute_keepass_gated_blocked_when_not_unlocked(self):
        p = self._approved_proposal("rotate-join-token")
        p.keepass_gated = True
        q = _rq.RemediationQueue(cell_id="pve01-cell")
        _rq.add_proposal(q, p, apply_auto_policy=False)
        _rq.approve_proposal(q, p.proposal_id, "x", "cli")
        ex = self._make_executor(keepass_unlocked=False)
        result = _re.execute_proposal(ex, q, p.proposal_id, _state(), now_fn=_now)
        assert result.success is False
        assert "KeePass" in result.outcome

    def test_execute_keepass_gated_allowed_when_unlocked(self):
        p = self._approved_proposal("rotate-join-token")
        p.keepass_gated = True
        q = _rq.RemediationQueue(cell_id="pve01-cell")
        _rq.add_proposal(q, p, apply_auto_policy=False)
        _rq.approve_proposal(q, p.proposal_id, "x", "cli")
        ex = self._make_executor(success=True, keepass_unlocked=True)
        result = _re.execute_proposal(ex, q, p.proposal_id, _state(), now_fn=_now)
        assert result.success is True

    def test_dry_run_differs_blocks_execution(self):
        p = self._approved_proposal("restart-service")
        p.dry_run_output = "completely different original output that has changed"
        q = _rq.RemediationQueue(cell_id="pve01-cell")
        _rq.add_proposal(q, p, apply_auto_policy=False)
        _rq.approve_proposal(q, p.proposal_id, "x", "cli")
        ex = self._make_executor()
        result = _re.execute_proposal(ex, q, p.proposal_id, _state(), now_fn=_now)
        assert result.success is False
        assert "Re-approval" in result.outcome or "changed" in result.outcome.lower()

    def test_failure_package_built_on_failure(self):
        p = self._approved_proposal("run-backup")
        q = _rq.RemediationQueue(cell_id="pve01-cell")
        _rq.add_proposal(q, p, apply_auto_policy=False)
        _rq.approve_proposal(q, p.proposal_id, "x", "cli")
        ex = self._make_executor(success=False)
        result = _re.execute_proposal(ex, q, p.proposal_id, _state(), now_fn=_now)
        assert result.failure_pkg is not None
        assert result.failure_pkg.action_type == "run-backup"
        assert result.failure_pkg.cell_id == "pve01-cell"

    def test_unknown_proposal_id_returns_failure(self):
        q = _rq.RemediationQueue(cell_id="pve01-cell")
        ex = self._make_executor()
        result = _re.execute_proposal(ex, q, "nonexistent", _state())
        assert result.success is False

    def test_check_resistance_marks_resisted(self):
        q = _rq.RemediationQueue(cell_id="pve01-cell")
        p = _rp.RemediationProposal(
            proposal_id="r1", issue_id="comp:gap", severity="YELLOW",
            action_type="restart-service", action_description="",
            target="svc", dry_run_output="", reversibility="reversible",
            estimated_duration_seconds=10, proposed_at=_now(),
        )
        p.status = "resolved"
        q.proposals.append(p)
        q._rebuild_index()
        resisted = _re.check_resistance(q, {"comp:gap"})
        assert "r1" in resisted
        assert q.get("r1").resisted is True

    def test_check_resistance_clear_when_resolved(self):
        q = _rq.RemediationQueue(cell_id="pve01-cell")
        p = _rp.RemediationProposal(
            proposal_id="r1", issue_id="comp:gap", severity="YELLOW",
            action_type="restart-service", action_description="",
            target="svc", dry_run_output="", reversibility="reversible",
            estimated_duration_seconds=10, proposed_at=_now(),
        )
        p.status = "resolved"
        q.proposals.append(p)
        q._rebuild_index()
        resisted = _re.check_resistance(q, set())  # issue no longer present
        assert "r1" not in resisted
        assert q.get("r1").resisted is False

    def test_all_action_types_have_handlers(self):
        for atype in _rp.ALLOWED_ACTION_TYPES:
            assert atype in _re._HANDLERS, f"Missing handler for {atype}"

    def test_restart_service_uses_shell_quoted_name(self):
        """Service name must be shell-quoted in SSH command to prevent injection."""
        captured_cmds = []

        def capturing_runner(cmd, cwd):
            captured_cmds.append(cmd)
            return (0, "active\n", "")

        p = self._approved_proposal("restart-service")
        p.target = "my-service"
        ex = _re.RemediationExecutor(
            cell_id="pve01-cell",
            state_path="/tmp/test-state.json",
            runner_fn=capturing_runner,
            keepass_unlocked=False,
        )
        from remediation_executor import _exec_restart_service
        _exec_restart_service(p, ex, _state())
        for cmd in captured_cmds:
            if len(cmd) >= 3:
                remote_cmd = cmd[-1]
                assert "my-service" in remote_cmd

    def test_restart_service_shell_quoting_for_special_chars(self):
        """Service name with shell metacharacters must not appear unquoted in SSH command."""
        captured_cmds = []

        def capturing_runner(cmd, cwd):
            captured_cmds.append(cmd)
            return (0, "active\n", "")

        p = self._approved_proposal("restart-service")
        p.target = "svc; echo pwned"
        ex = _re.RemediationExecutor(
            cell_id="pve01-cell",
            state_path="/tmp/test-state.json",
            runner_fn=capturing_runner,
            keepass_unlocked=False,
        )
        from remediation_executor import _exec_restart_service
        _exec_restart_service(p, ex, _state())
        for cmd in captured_cmds:
            if len(cmd) >= 3:
                remote_cmd = cmd[-1]
                # shlex.quote wraps in single-quotes so '; echo pwned' can't escape
                assert "echo pwned" not in remote_cmd or "'" in remote_cmd


# ===========================================================================
# 26.4 — Dashboard
# ===========================================================================

class TestDashboardRemediation:

    def _state_with_proposals(self):
        s = _state()
        proposals = []
        for i, (sev, status) in enumerate([
            ("YELLOW", "proposed"),
            ("ORANGE", "approved"),
            ("RED",    "resolved"),
        ]):
            proposals.append({
                "proposal_id": f"pid-{i}",
                "issue_id": f"comp:gap{i}",
                "severity": sev,
                "action_type": "restart-service",
                "action_description": f"Test action {i}",
                "target": "forgejo",
                "dry_run_output": "[dry-run]",
                "reversibility": "reversible",
                "estimated_duration_seconds": 10,
                "proposed_at": _now(),
                "status": status,
                "resisted": False,
                "keepass_gated": False,
            })
        s["remediations"] = proposals
        s["remediation_policy"] = {
            "autonomous": {"enabled": False},
        }
        return s

    def test_remediations_from_state(self):
        from broodforge_dashboard import _remediations_from_state
        s = self._state_with_proposals()
        rem = _remediations_from_state(s)
        assert len(rem["pending"]) == 1
        assert len(rem["approved"]) == 1
        assert len(rem["recent"]) == 1
        assert rem["auto_enabled"] is False

    def test_remediations_auto_enabled_flag(self):
        from broodforge_dashboard import _remediations_from_state
        s = _state()
        s["remediation_policy"] = {"autonomous": {"enabled": True, "expires_at": "2026-07-02T12:00:00+00:00"}}
        rem = _remediations_from_state(s)
        assert rem["auto_enabled"] is True

    def test_generate_dashboard_html_includes_remediations(self):
        from broodforge_dashboard import DashboardConfig, generate_dashboard_html
        s = self._state_with_proposals()
        cfg = DashboardConfig()
        rem = {
            "pending": s["remediations"][:1],
            "approved": s["remediations"][1:2],
            "recent": s["remediations"][2:],
            "auto_enabled": False,
            "auto_expires_at": None,
            "auto_enabled_by": "",
            "auto_threshold": None,
        }
        html = generate_dashboard_html(s, {}, [], [], {}, cfg, remediations=rem)
        assert "Remediations" in html
        assert "GATED" in html or "AUTO" in html

    def test_dashboard_html_auto_badge_active(self):
        from broodforge_dashboard import DashboardConfig, generate_dashboard_html
        s = _state()
        cfg = DashboardConfig()
        rem = {"pending": [], "approved": [], "recent": [],
               "auto_enabled": True, "auto_expires_at": "2026-07-02",
               "auto_enabled_by": "dave", "auto_threshold": "ORANGE"}
        html = generate_dashboard_html(s, {}, [], [], {}, cfg, remediations=rem)
        assert "AUTO" in html


# ===========================================================================
# 26.5 — Operational Report Section 8
# ===========================================================================

class TestOperationalReportSection8:

    def _manifest_with_proposals(self):
        m = _state()
        m["remediations"] = [
            {"proposal_id": "p1", "severity": "ORANGE", "action_type": "restart-service",
             "target": "forgejo", "status": "proposed", "proposed_at": _now(),
             "resisted": False},
            {"proposal_id": "p2", "severity": "YELLOW", "action_type": "run-backup",
             "target": "config", "status": "resolved", "proposed_at": _now(),
             "resolved_at": _later(), "outcome": "backup completed",
             "approval_channel": "auto-policy", "resisted": False},
        ]
        return m

    def test_section_remediation_summary_no_proposals(self):
        import html_operational_report as _hor
        html = _hor._section_remediation_summary(_state())
        assert "No remediation proposals" in html

    def test_section_remediation_summary_with_proposals(self):
        import html_operational_report as _hor
        html = _hor._section_remediation_summary(self._manifest_with_proposals())
        assert "Pending" in html or "ORANGE" in html

    def test_section_remediation_shows_auto_executions(self):
        import html_operational_report as _hor
        html = _hor._section_remediation_summary(self._manifest_with_proposals())
        assert "auto-policy" in html or "Autonomous" in html


# ===========================================================================
# 26.6 — Policy Engine
# ===========================================================================

class TestRemediationPolicy:

    def _policy(self, threshold=None, blocked=None, window=None):
        p = _pol.RemediationPolicy(
            auto_approve_threshold=threshold,
            blocked_action_types=blocked or [],
            execution_window=window,
        )
        return p

    def _proposal(self, severity="YELLOW", action_type="restart-service",
                  reversibility="reversible"):
        return _rp.RemediationProposal(
            proposal_id="p", issue_id="x:y", severity=severity,
            action_type=action_type, action_description="",
            target="t", dry_run_output="", reversibility=reversibility,
            estimated_duration_seconds=10, proposed_at=_now(),
        )

    def test_is_auto_approvable_within_threshold(self):
        policy = self._policy(threshold="ORANGE")
        p = self._proposal(severity="YELLOW")
        assert _pol.is_auto_approvable(p, policy) is True

    def test_is_auto_approvable_exceeds_threshold(self):
        policy = self._policy(threshold="YELLOW")
        p = self._proposal(severity="ORANGE")
        assert _pol.is_auto_approvable(p, policy) is False

    def test_is_auto_approvable_red_never(self):
        policy = self._policy(threshold="ORANGE")
        p = self._proposal(severity="RED")
        assert _pol.is_auto_approvable(p, policy) is False

    def test_is_auto_approvable_irreversible_never(self):
        policy = self._policy(threshold="ORANGE")
        p = self._proposal(severity="YELLOW", reversibility="irreversible")
        assert _pol.is_auto_approvable(p, policy) is False

    def test_is_auto_approvable_never_auto_type(self):
        policy = self._policy(threshold="ORANGE")
        p = self._proposal(severity="YELLOW", action_type="rotate-join-token")
        assert _pol.is_auto_approvable(p, policy) is False

    def test_is_blocked_by_policy(self):
        policy = self._policy(blocked=["restart-service"])
        p = self._proposal(action_type="restart-service")
        assert _pol.is_blocked(p, policy) is True

    def test_not_blocked_by_policy(self):
        policy = self._policy(blocked=["run-backup"])
        p = self._proposal(action_type="restart-service")
        assert _pol.is_blocked(p, policy) is False

    def test_execution_window_any_time(self):
        policy = self._policy(window=None)
        assert _pol.check_execution_window(policy, now_fn=_now) is True

    def test_execution_window_within(self):
        # _now() returns 12:00 UTC
        policy = self._policy(window="10:00-14:00")
        assert _pol.check_execution_window(policy, now_fn=_now) is True

    def test_execution_window_outside(self):
        policy = self._policy(window="08:00-10:00")
        assert _pol.check_execution_window(policy, now_fn=_now) is False

    def test_execution_window_malformed_denies(self):
        policy = self._policy(window="not-a-window")
        assert _pol.check_execution_window(policy, now_fn=_now) is False

    def test_policy_serialization_roundtrip(self):
        policy = _pol.RemediationPolicy(
            auto_approve_threshold="YELLOW",
            blocked_action_types=["run-backup"],
            max_concurrent_executions=2,
        )
        d = _pol.policy_to_dict(policy)
        p2 = _pol.dict_to_policy(d)
        assert p2.auto_approve_threshold == "YELLOW"
        assert "run-backup" in p2.blocked_action_types
        assert p2.max_concurrent_executions == 2

    def test_load_and_save_policy(self):
        state = _state()
        state["remediation_policy"] = {"auto_approve_threshold": "ORANGE"}
        policy = _pol.load_policy(state)
        assert policy.auto_approve_threshold == "ORANGE"
        updated = _pol.save_policy(policy, state)
        assert updated["remediation_policy"]["auto_approve_threshold"] == "ORANGE"

    def test_cross_cell_proposal_fully_approved(self):
        cc = _pol.CrossCellProposal(
            owning_cell_id="cell-a",
            requires_cell_approval=["cell-a", "cell-b"],
            approved_cells=["cell-a", "cell-b"],
        )
        assert cc.is_fully_approved() is True

    def test_cross_cell_proposal_not_fully_approved(self):
        cc = _pol.CrossCellProposal(
            owning_cell_id="cell-a",
            requires_cell_approval=["cell-a", "cell-b"],
            approved_cells=["cell-a"],
        )
        assert cc.is_fully_approved() is False


# ===========================================================================
# 26.7 — Fully Autonomous Mode
# ===========================================================================

class TestAutonomousMode:

    def _policy_with_autonomous(self, enabled=False, expires_at=None):
        policy = _pol.RemediationPolicy()
        if enabled:
            policy.autonomous = _pol.AutonomousMode(
                enabled=True, enabled_by="dave@pve01",
                enabled_at=_now(), enabled_via="cli",
                expires_at=expires_at,
            )
            policy.autonomous_expires_at = expires_at
        return policy

    def test_autonomous_inactive_by_default(self):
        policy = _pol.RemediationPolicy()
        assert _pol.is_autonomous_active(policy, now_fn=_now) is False

    def test_autonomous_active_when_enabled(self):
        policy = self._policy_with_autonomous(enabled=True)
        assert _pol.is_autonomous_active(policy, now_fn=_now) is True

    def test_autonomous_inactive_when_expired(self):
        policy = self._policy_with_autonomous(enabled=True, expires_at="2026-01-01T00:00:00+00:00")
        assert _pol.is_autonomous_active(policy, now_fn=_now) is False

    def test_autonomous_active_not_expired(self):
        policy = self._policy_with_autonomous(enabled=True, expires_at="2027-01-01T00:00:00+00:00")
        assert _pol.is_autonomous_active(policy, now_fn=_now) is True

    def test_enable_autonomous_ceremony(self):
        policy = _pol.RemediationPolicy()
        scope = {"action_types": ["restart-service"], "max_severity": "ORANGE"}
        am = _pol.enable_autonomous(policy, scope, "dave@pve01", "cli", now_fn=_now)
        assert am.enabled is True
        assert am.enabled_by == "dave@pve01"
        assert am.expires_at is not None
        assert policy.autonomous.enabled is True

    def test_disable_autonomous(self):
        policy = self._policy_with_autonomous(enabled=True)
        _pol.disable_autonomous(policy, "test disable", "dave@pve01", now_fn=_later)
        assert policy.autonomous.enabled is False
        assert policy.autonomous.disable_reason == "test disable"
        assert policy.autonomous.disabled_at is not None

    def test_hard_exclusion_red_severity(self):
        policy = self._policy_with_autonomous(enabled=True)
        p = _rp.RemediationProposal(
            proposal_id="p", issue_id="x:y", severity="RED",
            action_type="restart-service", action_description="",
            target="t", dry_run_output="", reversibility="reversible",
            estimated_duration_seconds=10, proposed_at=_now(),
        )
        assert _pol.is_eligible_for_autonomous(p, policy) is False

    def test_hard_exclusion_irreversible(self):
        policy = self._policy_with_autonomous(enabled=True)
        p = _rp.RemediationProposal(
            proposal_id="p", issue_id="x:y", severity="YELLOW",
            action_type="restart-service", action_description="",
            target="t", dry_run_output="", reversibility="irreversible",
            estimated_duration_seconds=10, proposed_at=_now(),
        )
        assert _pol.is_eligible_for_autonomous(p, policy) is False

    def test_hard_exclusion_keepass_gated(self):
        policy = self._policy_with_autonomous(enabled=True)
        p = _rp.RemediationProposal(
            proposal_id="p", issue_id="x:y", severity="YELLOW",
            action_type="rotate-join-token", action_description="",
            target="t", dry_run_output="", reversibility="manual-rollback",
            estimated_duration_seconds=30, proposed_at=_now(),
            keepass_gated=True,
        )
        assert _pol.is_eligible_for_autonomous(p, policy) is False

    def test_scope_action_type_filter(self):
        policy = self._policy_with_autonomous(enabled=True)
        policy.autonomous_action_types = ["restart-service"]  # only this type allowed
        p = _rp.RemediationProposal(
            proposal_id="p", issue_id="x:y", severity="YELLOW",
            action_type="run-backup", action_description="",
            target="t", dry_run_output="", reversibility="reversible",
            estimated_duration_seconds=300, proposed_at=_now(),
        )
        assert _pol.is_eligible_for_autonomous(p, policy) is False

    def test_scope_severity_cap(self):
        policy = self._policy_with_autonomous(enabled=True)
        policy.autonomous_max_severity = "YELLOW"  # cap at YELLOW
        p = _rp.RemediationProposal(
            proposal_id="p", issue_id="x:y", severity="ORANGE",
            action_type="restart-service", action_description="",
            target="t", dry_run_output="", reversibility="reversible",
            estimated_duration_seconds=10, proposed_at=_now(),
        )
        assert _pol.is_eligible_for_autonomous(p, policy) is False

    def test_eligible_for_autonomous_all_clear(self):
        policy = self._policy_with_autonomous(enabled=True)
        p = _rp.RemediationProposal(
            proposal_id="p", issue_id="x:y", severity="YELLOW",
            action_type="restart-service", action_description="",
            target="t", dry_run_output="", reversibility="reversible",
            estimated_duration_seconds=10, proposed_at=_now(),
        )
        assert _pol.is_eligible_for_autonomous(p, policy) is True

    def test_auto_disable_red_cell(self):
        policy = self._policy_with_autonomous(enabled=True)
        reason = _pol.should_auto_disable(policy, cell_readiness_level="RED")
        assert reason is not None
        assert "RED" in reason

    def test_auto_disable_consecutive_failures(self):
        policy = self._policy_with_autonomous(enabled=True)
        policy.autonomous.consecutive_failures = 3
        reason = _pol.should_auto_disable(policy)
        assert reason is not None
        assert "consecutive" in reason.lower()

    def test_auto_disable_consecutive_resisted(self):
        policy = self._policy_with_autonomous(enabled=True)
        policy.autonomous.consecutive_resisted = 2
        reason = _pol.should_auto_disable(policy)
        assert reason is not None

    def test_no_auto_disable_when_all_good(self):
        policy = self._policy_with_autonomous(enabled=True)
        assert _pol.should_auto_disable(policy) is None

    def test_guard_drill_active(self):
        policy = self._policy_with_autonomous(enabled=True)
        reasons = _pol.evaluate_autonomous_guards(policy, _state(), drill_active=True, now_fn=_now)
        assert any("drill" in r.lower() for r in reasons)

    def test_guard_stale_state(self):
        policy = self._policy_with_autonomous(enabled=True)
        # State declared 3 hours ago; interval is 1 hour → stale
        old_state = _state()
        old_state["declared_at"] = "2026-06-02T09:00:00+00:00"  # 3h before _now()
        reasons = _pol.evaluate_autonomous_guards(policy, old_state,
                                                  drill_active=False,
                                                  now_fn=_now,
                                                  assessment_interval_hours=1.0)
        assert any("stale" in r.lower() for r in reasons)

    def test_guard_all_clear(self):
        policy = self._policy_with_autonomous(enabled=True)
        # State is fresh (only 1 min old)
        fresh_state = _state()
        fresh_state["declared_at"] = "2026-06-02T11:59:00+00:00"
        reasons = _pol.evaluate_autonomous_guards(policy, fresh_state,
                                                  drill_active=False,
                                                  now_fn=_now,
                                                  assessment_interval_hours=1.0)
        assert reasons == []

    def test_guard_inactive_mode_returns_blocking(self):
        policy = _pol.RemediationPolicy()  # not enabled
        reasons = _pol.evaluate_autonomous_guards(policy, _state(), now_fn=_now)
        assert any("not active" in r.lower() for r in reasons)
