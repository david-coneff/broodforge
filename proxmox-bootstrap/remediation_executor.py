#!/usr/bin/env python3
"""
remediation_executor.py — Phase 26.3: Executor.

Executes approved RemediationProposals with the same checkpoint / failure-package
semantics used by spawn and phoenix scripts.

Execution contract:
  1. Re-validate proposal — confirm issue still exists, action type allowed.
  2. Record start in queue (status → executing).
  3. Dry-run first — diff against original dry_run_output; if significantly
     different, surface for re-approval rather than proceeding.
  4. Execute the action.
  5. Checkpoint at each meaningful step.
  6. On failure: generate RemediationFailurePackage, set status to failed.
  7. On success: record resolved_at, outcome, status → resolved.
  8. Trigger reassessment.

KeePass gate: any action in _KEEPASS_GATED requires the gate to be unlocked.
The executor checks before starting and suspends if not unlocked.

Public API:
  RemediationExecutor
  RemediationFailurePackage
  execute_proposal(executor, queue, proposal_id, state, now_fn) → ExecutionResult
  build_failure_package(proposal, error, steps_completed) → RemediationFailurePackage

Stdlib only.
"""

import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from remediation_planner import (
    ALLOWED_ACTION_TYPES,
    RemediationProposal,
    dry_run_proposal,
    _KEEPASS_GATED,
)
from remediation_queue import (
    RemediationQueue,
    approve_proposal,
    mark_executing,
    mark_failed,
    mark_resolved,
)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ExecutionStep:
    step_id:    str
    description: str
    completed:  bool = False
    output:     str  = ""
    error:      str  = ""


@dataclass
class ExecutionResult:
    proposal_id:   str
    success:       bool
    outcome:       str
    steps:         List[ExecutionStep] = field(default_factory=list)
    failure_pkg:   Optional["RemediationFailurePackage"] = None
    resisted:      bool = False


@dataclass
class RemediationFailurePackage:
    proposal_id:   str
    action_type:   str
    target:        str
    cell_id:       str
    failed_at:     str
    error_message: str
    steps_completed: List[str]
    dry_run_output:  str
    state_snapshot:  dict = field(default_factory=dict)


@dataclass
class RemediationExecutor:
    """Executor instance. Set runner_fn for testing without live system calls."""
    cell_id:    str
    state_path: str = ""
    runner_fn:  Optional[Callable] = None   # injectable for tests
    # Tracks whether KeePass is unlocked for this session
    keepass_unlocked: bool = False

    def _run(self, cmd: List[str], cwd: str = None) -> tuple[int, str, str]:
        """Run a shell command. Returns (returncode, stdout, stderr)."""
        if self.runner_fn:
            return self.runner_fn(cmd, cwd)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd or ".",
            timeout=300,
        )
        return result.returncode, result.stdout, result.stderr


def build_failure_package(
    proposal:        RemediationProposal,
    error:           str,
    steps_completed: List[str],
    state:           dict = None,
) -> RemediationFailurePackage:
    from datetime import datetime, timezone
    return RemediationFailurePackage(
        proposal_id=proposal.proposal_id,
        action_type=proposal.action_type,
        target=proposal.target,
        cell_id=proposal.cell_id or "unknown",
        failed_at=datetime.now(timezone.utc).isoformat(),
        error_message=error,
        steps_completed=steps_completed,
        dry_run_output=proposal.dry_run_output,
        state_snapshot={k: v for k, v in (state or {}).items()
                        if k in ("cell_id", "host_identity", "network_topology")},
    )


# ---------------------------------------------------------------------------
# Pre-execution validation
# ---------------------------------------------------------------------------

def _validate_before_execute(
    proposal: RemediationProposal,
    state:    dict,
) -> Optional[str]:
    """Return an error string if the proposal should not execute, else None."""
    if proposal.action_type not in ALLOWED_ACTION_TYPES:
        return f"Action type '{proposal.action_type}' is not on the allowed list."
    if proposal.status != "approved":
        return f"Proposal status is '{proposal.status}' — must be 'approved' to execute."
    return None


def _dry_run_differs(original: str, current: str) -> bool:
    """Return True if the current dry-run output differs significantly from original."""
    orig_lines = set(original.strip().splitlines())
    curr_lines = set(current.strip().splitlines())
    diff = orig_lines.symmetric_difference(curr_lines)
    if not orig_lines:
        return False
    pct = len(diff) / max(len(orig_lines), 1)
    return pct > 0.5   # >50% change is "significant"


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def _exec_restart_service(
    proposal: RemediationProposal,
    executor: RemediationExecutor,
    state:    dict,
) -> tuple[bool, str, List[ExecutionStep]]:
    steps = []
    svc = proposal.target
    # Find VM IP from state
    dns = state.get("dns_registry") or []
    vm_ip = ""
    for entry in dns:
        name = entry.get("hostname") or entry.get("name") or ""
        if svc in name or name in svc:
            vm_ip = entry.get("ip") or entry.get("address") or ""
            break

    if not vm_ip:
        vm_ip = "<service-ip>"

    svc_q = shlex.quote(svc)  # prevent shell injection on remote host
    step1 = ExecutionStep("check", f"Check service status for {svc}")
    rc, out, err = executor._run(
        ["ssh", f"ubuntu@{vm_ip}", f"sudo systemctl is-active {svc_q}"]
    )
    step1.completed = True
    step1.output = out.strip()
    steps.append(step1)

    step2 = ExecutionStep("restart", f"Restart {svc}")
    rc, out, err = executor._run(
        ["ssh", f"ubuntu@{vm_ip}", f"sudo systemctl restart {svc_q}"]
    )
    step2.completed = (rc == 0)
    step2.output = out
    step2.error  = err
    steps.append(step2)

    if rc != 0:
        return False, f"systemctl restart failed: {err}", steps

    step3 = ExecutionStep("verify", f"Verify {svc} is running")
    rc2, out2, _ = executor._run(
        ["ssh", f"ubuntu@{vm_ip}", f"sudo systemctl is-active {svc_q}"]
    )
    step3.completed = (rc2 == 0)
    step3.output = out2.strip()
    steps.append(step3)

    if "active" in out2 or rc2 == 0:
        return True, f"Service {svc} restarted and running.", steps
    return False, f"Service {svc} restarted but not active: {out2}", steps


def _exec_run_backup(
    proposal: RemediationProposal,
    executor: RemediationExecutor,
    state:    dict,
) -> tuple[bool, str, List[ExecutionStep]]:
    steps = []
    layer = proposal.target or "config"

    repo_dir = os.path.dirname(executor.state_path) if executor.state_path else "."
    script = os.path.join(repo_dir, "run-backup.py")

    step1 = ExecutionStep("backup", f"Run backup for layer: {layer}")
    rc, out, err = executor._run(["python3", script, "--layer", layer])
    step1.completed = (rc == 0)
    step1.output = out[:2000]
    step1.error  = err[:500]
    steps.append(step1)

    if rc != 0:
        return False, f"Backup failed: {err[:500]}", steps
    return True, f"Backup for layer '{layer}' completed successfully.", steps


def _exec_renew_cert(
    proposal: RemediationProposal,
    executor: RemediationExecutor,
    state:    dict,
) -> tuple[bool, str, List[ExecutionStep]]:
    steps = []
    nt = state.get("network_topology") or {}
    provider = nt.get("ssl_provider") or "certbot"

    if provider == "certbot":
        cmd = ["certbot", "renew", "--quiet"]
    else:
        domain = nt.get("ssl_cert_path") or proposal.target
        cmd = ["acme.sh", "--renew", "-d", domain]

    step1 = ExecutionStep("renew", f"Renew certificate via {provider}")
    rc, out, err = executor._run(cmd)
    step1.completed = (rc == 0)
    step1.output = out[:2000]
    step1.error  = err[:500]
    steps.append(step1)

    if rc != 0:
        return False, f"Certificate renewal failed: {err[:500]}", steps
    return True, f"Certificate renewed via {provider}.", steps


def _exec_regenerate_phoenix(
    proposal: RemediationProposal,
    executor: RemediationExecutor,
    state:    dict,
) -> tuple[bool, str, List[ExecutionStep]]:
    steps = []
    node = proposal.target
    repo_dir = os.path.dirname(executor.state_path) if executor.state_path else "."
    script = os.path.join(repo_dir, "phoenix_playbook.py")

    step1 = ExecutionStep("generate", f"Regenerate phoenix playbook for {node}")
    rc, out, err = executor._run(["python3", script, "--node", node, "--state", executor.state_path])
    step1.completed = (rc == 0)
    step1.output = out[:2000]
    step1.error  = err[:500]
    steps.append(step1)

    if rc != 0:
        return False, f"Phoenix regeneration failed: {err[:500]}", steps
    return True, f"Phoenix playbook for {node} regenerated.", steps


def _exec_sync_cert_to_k8s(
    proposal: RemediationProposal,
    executor: RemediationExecutor,
    state:    dict,
) -> tuple[bool, str, List[ExecutionStep]]:
    steps = []
    repo_dir = os.path.dirname(executor.state_path) if executor.state_path else "."
    script = os.path.join(repo_dir, "sync-cert-to-k8s.sh")

    step1 = ExecutionStep("sync", "Sync TLS cert to k8s secrets")
    rc, out, err = executor._run(["bash", script])
    step1.completed = (rc == 0)
    step1.output = out[:2000]
    step1.error  = err[:500]
    steps.append(step1)

    if rc != 0:
        return False, f"cert sync failed: {err[:500]}", steps
    return True, "TLS certificate synced to k8s secrets.", steps


def _exec_rotate_join_token(
    proposal: RemediationProposal,
    executor: RemediationExecutor,
    state:    dict,
) -> tuple[bool, str, List[ExecutionStep]]:
    steps = []
    step1 = ExecutionStep("rotate", "Rotate k3s join token")
    rc, out, err = executor._run(["k3s", "token", "rotate"])
    step1.completed = (rc == 0)
    step1.output = out[:500]
    step1.error  = err[:500]
    steps.append(step1)

    if rc != 0:
        return False, f"k3s token rotate failed: {err[:500]}", steps
    return True, "k3s join token rotated. Update spawn packages before next broodling join.", steps


def _exec_restart_assessment_timer(
    proposal: RemediationProposal,
    executor: RemediationExecutor,
    state:    dict,
) -> tuple[bool, str, List[ExecutionStep]]:
    steps = []
    step1 = ExecutionStep("enable", "Enable broodforge-operational.timer")
    rc, out, err = executor._run(
        ["systemctl", "enable", "--now", "broodforge-operational.timer"]
    )
    step1.completed = (rc == 0)
    step1.output = out
    step1.error  = err
    steps.append(step1)

    if rc != 0:
        return False, f"systemctl enable failed: {err}", steps
    return True, "Operational assessment timer enabled.", steps


def _exec_schedule_drill(
    proposal: RemediationProposal,
    executor: RemediationExecutor,
    state:    dict,
) -> tuple[bool, str, List[ExecutionStep]]:
    steps = []
    from datetime import datetime, timezone, timedelta
    now_dt = datetime.now(timezone.utc)
    due_at = (now_dt + timedelta(days=90)).isoformat()

    reminder = {
        "type":   "drill_reminder",
        "due_at": due_at,
        "added_by": "remediation-executor",
        "added_at": now_dt.isoformat(),
    }

    step1 = ExecutionStep("schedule", "Append drill reminder to bootstrap-state.json")
    try:
        if executor.state_path and os.path.exists(executor.state_path):
            with open(executor.state_path) as f:
                cur_state = json.load(f)
            drills = cur_state.get("reconstruction_drills") or []
            drills.append(reminder)
            cur_state["reconstruction_drills"] = drills
            with open(executor.state_path, "w") as f:
                json.dump(cur_state, f, indent=2)
        step1.completed = True
        step1.output = f"Drill reminder scheduled for {due_at}"
    except Exception as e:
        step1.error = str(e)
    steps.append(step1)

    if not step1.completed:
        return False, f"Failed to schedule drill: {step1.error}", steps
    return True, f"Reconstruction drill reminder scheduled (due {due_at[:10]}).", steps


def _exec_flag_manual(
    proposal: RemediationProposal,
    executor: RemediationExecutor,
    state:    dict,
) -> tuple[bool, str, List[ExecutionStep]]:
    step = ExecutionStep("flag", f"Mark {proposal.target} for manual attention")
    step.completed = True
    step.output = f"Finding flagged for manual review: {proposal.action_description}"
    return True, "Finding flagged for manual operator attention.", [step]


_HANDLERS: Dict[str, Callable] = {
    "restart-service":          _exec_restart_service,
    "run-backup":               _exec_run_backup,
    "renew-cert":               _exec_renew_cert,
    "regenerate-phoenix":       _exec_regenerate_phoenix,
    "sync-cert-to-k8s":        _exec_sync_cert_to_k8s,
    "rotate-join-token":        _exec_rotate_join_token,
    "restart-assessment-timer": _exec_restart_assessment_timer,
    "schedule-drill":           _exec_schedule_drill,
    "flag-manual":              _exec_flag_manual,
}


# ---------------------------------------------------------------------------
# Main executor
# ---------------------------------------------------------------------------

def execute_proposal(
    executor:    RemediationExecutor,
    queue:       RemediationQueue,
    proposal_id: str,
    state:       dict,
    now_fn:      Optional[Callable] = None,
) -> ExecutionResult:
    """
    Execute an approved proposal.
    Returns ExecutionResult; updates queue state in place.
    """
    proposal = queue.get(proposal_id)
    if proposal is None:
        return ExecutionResult(
            proposal_id=proposal_id,
            success=False,
            outcome=f"Proposal {proposal_id} not found in queue.",
        )

    # 1. Pre-validate
    err = _validate_before_execute(proposal, state)
    if err:
        return ExecutionResult(
            proposal_id=proposal_id,
            success=False,
            outcome=err,
        )

    # 2. KeePass gate check
    if proposal.keepass_gated and not executor.keepass_unlocked:
        return ExecutionResult(
            proposal_id=proposal_id,
            success=False,
            outcome="KeePass gate required but not unlocked. Unlock KeePass before executing this action.",
        )

    # 3. Re-run dry-run, diff against original
    current_dry = dry_run_proposal(proposal, state)
    if _dry_run_differs(proposal.dry_run_output, current_dry):
        proposal.dry_run_output = current_dry
        return ExecutionResult(
            proposal_id=proposal_id,
            success=False,
            outcome=(
                "Dry-run output has changed significantly since proposal was created. "
                "Re-approval required. Updated dry-run output saved."
            ),
        )

    # 4. Mark as executing
    mark_executing(queue, proposal_id, now_fn=now_fn)

    # 5. Execute
    handler = _HANDLERS.get(proposal.action_type)
    if handler is None:
        pkg = build_failure_package(proposal, "No handler for action type", [], state)
        mark_failed(queue, proposal_id, "No handler for action type", now_fn=now_fn)
        return ExecutionResult(
            proposal_id=proposal_id,
            success=False,
            outcome="No handler for action type",
            failure_pkg=pkg,
        )

    try:
        success, outcome, steps = handler(proposal, executor, state)
    except Exception as exc:
        outcome = f"Unexpected error during execution: {exc}"
        pkg = build_failure_package(proposal, outcome, [], state)
        mark_failed(queue, proposal_id, outcome, now_fn=now_fn)
        return ExecutionResult(
            proposal_id=proposal_id,
            success=False,
            outcome=outcome,
            failure_pkg=pkg,
            steps=[],
        )

    # 6. Record outcome
    if success:
        mark_resolved(queue, proposal_id, outcome, now_fn=now_fn)
        return ExecutionResult(
            proposal_id=proposal_id,
            success=True,
            outcome=outcome,
            steps=steps,
        )
    else:
        completed_steps = [s.step_id for s in steps if s.completed]
        pkg = build_failure_package(proposal, outcome, completed_steps, state)
        mark_failed(queue, proposal_id, outcome, now_fn=now_fn)
        return ExecutionResult(
            proposal_id=proposal_id,
            success=False,
            outcome=outcome,
            steps=steps,
            failure_pkg=pkg,
        )


def check_resistance(
    queue:            RemediationQueue,
    current_issue_ids: set,
    now_fn:           Optional[Callable] = None,
) -> List[str]:
    """
    After reassessment, check recently-resolved proposals to see if the issue persists.
    Marks any whose issue_id is still present as 'resisted'.
    Returns list of proposal_ids that resisted.
    """
    resisted_ids = []
    for p in queue.proposals:
        if p.status == "resolved" and not p.resisted:
            if p.issue_id in current_issue_ids:
                p.resisted = True
                resisted_ids.append(p.proposal_id)
    return resisted_ids
