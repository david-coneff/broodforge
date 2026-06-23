#!/usr/bin/env python3
"""
remediation_queue.py — Phase 26.2: Approval Queue.

Manages the lifecycle of RemediationProposals from creation through execution.

State machine per proposal:
  proposed → approved → executing → resolved
          ↘ rejected
          ↘ superseded   (newer proposal for same issue replaces this one)
          ↘ expired      (underlying issue resolved before approval)

Queue storage: `remediations` array in bootstrap-state.json.
Every state transition is recorded with actor, timestamp, and channel.

Public API:
  RemediationQueue                  — in-memory queue manager
  load_queue(state) → RemediationQueue
  save_queue(queue, state) → dict   (returns updated state dict)
  add_proposal(queue, proposal)
  approve_proposal(queue, pid, approved_by, channel, note) → bool
  reject_proposal(queue, pid, reason) → bool
  expire_resolved_proposals(queue, current_issue_ids) → int
  supersede_proposal(queue, old_pid, new_proposal) → bool
  get_pending(queue) → list[RemediationProposal]
  get_history(queue, limit) → list[RemediationProposal]

Stdlib only.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from remediation_planner import (
    RemediationProposal,
    dict_to_proposal,
    proposal_to_dict,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TERMINAL_STATES = {"resolved", "rejected", "superseded", "expired"}
_VALID_TRANSITIONS = {
    "proposed":  {"approved", "rejected", "superseded", "expired"},
    "approved":  {"executing", "rejected", "superseded", "expired"},
    "executing": {"resolved", "failed"},
    "resolved":  set(),
    "rejected":  set(),
    "superseded": set(),
    "expired":   set(),
    "failed":    set(),
}


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------

@dataclass
class RemediationQueue:
    cell_id:   str
    proposals: List[RemediationProposal] = field(default_factory=list)
    policy:    dict                       = field(default_factory=dict)
    _index:    Dict[str, int]             = field(default_factory=dict, repr=False)

    def _rebuild_index(self) -> None:
        self._index = {p.proposal_id: i for i, p in enumerate(self.proposals)}

    def get(self, proposal_id: str) -> Optional[RemediationProposal]:
        idx = self._index.get(proposal_id)
        if idx is not None and idx < len(self.proposals):
            return self.proposals[idx]
        # linear fallback
        for p in self.proposals:
            if p.proposal_id == proposal_id:
                return p
        return None


def load_queue(state: dict) -> RemediationQueue:
    """Deserialize queue from bootstrap-state.json dict."""
    cell_id = state.get("cell_id") or "unknown"
    raw = state.get("remediations") or []
    proposals = [dict_to_proposal(d) for d in raw]
    policy = state.get("remediation_policy") or {}
    q = RemediationQueue(cell_id=cell_id, proposals=proposals, policy=policy)
    q._rebuild_index()
    return q


def save_queue(queue: RemediationQueue, state: dict) -> dict:
    """Serialize queue back into state dict (returns updated dict copy)."""
    updated = dict(state)
    updated["remediations"] = [proposal_to_dict(p) for p in queue.proposals]
    if queue.policy:
        updated["remediation_policy"] = queue.policy
    return updated


def _now_str(now_fn=None) -> str:
    if now_fn:
        return now_fn()
    return datetime.now(timezone.utc).isoformat()


def _can_transition(current: str, target: str) -> bool:
    return target in _VALID_TRANSITIONS.get(current, set())


# ---------------------------------------------------------------------------
# Mutation helpers
# ---------------------------------------------------------------------------

def add_proposal(
    queue:    RemediationQueue,
    proposal: RemediationProposal,
    *,
    apply_auto_policy: bool = True,
    now_fn:   Optional[Callable] = None,
) -> None:
    """Add a new proposal to the queue, applying auto-approve policy if set."""
    queue.proposals.append(proposal)
    queue._rebuild_index()

    if not apply_auto_policy:
        return

    # Apply auto-approve policy
    threshold = queue.policy.get("auto_approve_threshold")
    if threshold is None:
        return

    from remediation_planner import _NEVER_AUTO_APPROVE, _SEVERITY_RANK
    if proposal.action_type in _NEVER_AUTO_APPROVE:
        return
    if proposal.reversibility == "irreversible":
        return
    if proposal.severity == "RED":
        return

    threshold_rank = _SEVERITY_RANK.get(threshold, 0)
    proposal_rank  = _SEVERITY_RANK.get(proposal.severity, 0)
    if proposal_rank <= threshold_rank:
        approve_proposal(
            queue, proposal.proposal_id,
            approved_by="auto-policy",
            channel="auto-policy",
            note=f"Auto-approved per policy threshold {threshold}",
            now_fn=now_fn,
        )


def approve_proposal(
    queue:       RemediationQueue,
    proposal_id: str,
    approved_by: str,
    channel:     str,
    note:        Optional[str] = None,
    now_fn:      Optional[Callable] = None,
) -> bool:
    """Approve a proposal. Returns True if successful."""
    p = queue.get(proposal_id)
    if p is None:
        return False
    if not _can_transition(p.status, "approved"):
        return False
    p.status           = "approved"
    p.approved_by      = approved_by
    p.approved_at      = _now_str(now_fn)
    p.approval_channel = channel
    p.approval_note    = note
    return True


def reject_proposal(
    queue:       RemediationQueue,
    proposal_id: str,
    reason:      Optional[str] = None,
    rejected_by: Optional[str] = None,
    now_fn:      Optional[Callable] = None,
) -> bool:
    """Reject a proposal. Returns True if successful."""
    p = queue.get(proposal_id)
    if p is None:
        return False
    if not _can_transition(p.status, "rejected"):
        return False
    p.status      = "rejected"
    p.outcome     = reason or "rejected by operator"
    p.rejected_by = rejected_by
    p.resolved_at = _now_str(now_fn)
    return True


def mark_executing(
    queue:       RemediationQueue,
    proposal_id: str,
    now_fn:      Optional[Callable] = None,
) -> bool:
    p = queue.get(proposal_id)
    if p is None:
        return False
    if not _can_transition(p.status, "executing"):
        return False
    p.status     = "executing"
    p.started_at = _now_str(now_fn)
    return True


def mark_resolved(
    queue:       RemediationQueue,
    proposal_id: str,
    outcome:     str,
    resisted:    bool = False,
    now_fn:      Optional[Callable] = None,
) -> bool:
    p = queue.get(proposal_id)
    if p is None:
        return False
    if not _can_transition(p.status, "resolved"):
        return False
    p.status      = "resolved"
    p.outcome     = outcome
    p.resolved_at = _now_str(now_fn)
    p.resisted    = resisted
    return True


def mark_failed(
    queue:       RemediationQueue,
    proposal_id: str,
    outcome:     str,
    now_fn:      Optional[Callable] = None,
) -> bool:
    p = queue.get(proposal_id)
    if p is None:
        return False
    if not _can_transition(p.status, "failed"):
        return False
    p.status      = "failed"
    p.outcome     = outcome
    p.resolved_at = _now_str(now_fn)
    return True


def supersede_proposal(
    queue:        RemediationQueue,
    old_pid:      str,
    new_proposal: RemediationProposal,
    now_fn:       Optional[Callable] = None,
) -> bool:
    """Replace an existing proposal with a newer one for the same issue."""
    old = queue.get(old_pid)
    if old is None:
        return False
    old.status     = "superseded"
    old.resolved_at = _now_str(now_fn)
    add_proposal(queue, new_proposal, now_fn=now_fn)
    return True


def expire_resolved_proposals(
    queue:            RemediationQueue,
    current_issue_ids: set,
    now_fn:           Optional[Callable] = None,
) -> int:
    """
    Mark proposed/approved proposals as 'expired' if their underlying issue
    is no longer present in the current assessment.
    Returns count of proposals expired.
    """
    count = 0
    for p in queue.proposals:
        if p.status in ("proposed", "approved"):
            if p.issue_id not in current_issue_ids:
                p.status     = "expired"
                p.resolved_at = _now_str(now_fn)
                p.outcome    = "underlying issue resolved before approval"
                count += 1
    return count


def batch_approve(
    queue:       RemediationQueue,
    max_severity: str,
    approved_by: str,
    channel:     str = "cli",
    now_fn:      Optional[Callable] = None,
) -> int:
    """Approve all pending proposals at or below max_severity. Returns count approved."""
    from remediation_planner import _NEVER_AUTO_APPROVE, _SEVERITY_RANK
    threshold_rank = _SEVERITY_RANK.get(max_severity, 0)
    count = 0
    for p in queue.proposals:
        if p.status != "proposed":
            continue
        if p.action_type in _NEVER_AUTO_APPROVE:
            continue
        if p.reversibility == "irreversible":
            continue
        if _SEVERITY_RANK.get(p.severity, 0) <= threshold_rank:
            ok = approve_proposal(queue, p.proposal_id, approved_by, channel, now_fn=now_fn)
            if ok:
                count += 1
    return count


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_pending(queue: RemediationQueue) -> List[RemediationProposal]:
    """Return all proposed (not yet approved) proposals."""
    return [p for p in queue.proposals if p.status == "proposed"]


def get_approved(queue: RemediationQueue) -> List[RemediationProposal]:
    """Return all approved (ready to execute) proposals."""
    return [p for p in queue.proposals if p.status == "approved"]


def get_history(
    queue: RemediationQueue,
    limit: int = 50,
) -> List[RemediationProposal]:
    """Return resolved/rejected/failed proposals, most recent first."""
    terminal = [p for p in queue.proposals if p.status in _TERMINAL_STATES | {"failed"}]
    terminal.sort(key=lambda p: p.resolved_at or p.proposed_at, reverse=True)
    return terminal[:limit]


def get_active(queue: RemediationQueue) -> List[RemediationProposal]:
    """Return all non-terminal proposals."""
    return [p for p in queue.proposals if p.status not in _TERMINAL_STATES | {"failed"}]


def get_by_severity(
    queue:    RemediationQueue,
    severity: str,
) -> List[RemediationProposal]:
    """Return active proposals at a given severity."""
    return [p for p in get_active(queue) if p.severity == severity]


def queue_summary(queue: RemediationQueue) -> dict:
    """Return a count summary of the queue."""
    from collections import Counter
    status_counts = Counter(p.status for p in queue.proposals)
    severity_pending = Counter(
        p.severity for p in queue.proposals if p.status == "proposed"
    )
    return {
        "total":          len(queue.proposals),
        "by_status":      dict(status_counts),
        "pending_by_severity": dict(severity_pending),
    }
