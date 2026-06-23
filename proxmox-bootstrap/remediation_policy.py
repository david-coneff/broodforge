#!/usr/bin/env python3
"""
remediation_policy.py — Phase 26.6: Policy Engine and Autonomous Mode.

Controls what can be auto-approved, what requires human approval, what is
blocked, and manages the fully autonomous execution mode (Phase 26.7).

Public API:
  RemediationPolicy        — policy dataclass
  AutonomousMode           — autonomous mode configuration dataclass
  load_policy(state) → RemediationPolicy
  save_policy(policy, state) → dict
  is_auto_approvable(proposal, policy) → bool
  is_blocked(proposal, policy) → bool
  check_execution_window(policy, now_fn) → bool
  enable_autonomous(policy, scope, operator, channel, now_fn) → AutonomousMode
  disable_autonomous(policy, reason, operator, now_fn) → None
  is_autonomous_active(policy, now_fn) → bool
  evaluate_autonomous_guards(policy, state, drill_active, now_fn) → list[str]
  AUTONOMOUS_CEREMONY_PROMPT  — text shown during enabling ceremony

Stdlib only.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional

from remediation_planner import (
    _NEVER_AUTO_APPROVE,
    _SEVERITY_RANK,
    RemediationProposal,
)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

# Action types safe for autonomous execution by default
_DEFAULT_AUTONOMOUS_TYPES = {
    "restart-service",
    "run-backup",
    "renew-cert",
    "regenerate-phoenix",
    "sync-cert-to-k8s",
    "restart-assessment-timer",
    "schedule-drill",
    "flag-manual",
}
# rotate-join-token is excluded from autonomous by default

_AUTONOMOUS_EXPIRY_DAYS = 30

AUTONOMOUS_CEREMONY_PROMPT = """\
Current policy review
=====================
Cell:            {cell_id}
Assessment:      operational (running every 1 hour)
Pending queue:   {pending_count} proposals awaiting approval
Action types in scope for autonomous execution:
  {action_types}
Maximum severity for autonomous execution: {max_severity}
Execution window: {execution_window}

HARD EXCLUSIONS — these are NEVER executed autonomously regardless of policy:
  ✗ Any action with reversibility: irreversible
  ✗ RED-severity findings
  ✗ Actions requiring KeePass gate (those remain per-action gated)
  ✗ Cross-cell actions (those remain per-cell-operator gated)

What will happen if you continue:
  Approved: new proposals at or below {max_severity} will execute automatically
            on the next assessment cycle after they are proposed.
  NOT approved: the {pending_count} existing proposals in the queue still require
                per-action approval — autonomous mode applies to new proposals
                generated after this point, not retroactively.

This mode will auto-disable after {expiry_days} days ({expires_at}) unless renewed.
To disable at any time: remediation-cli.py disable-autonomous

Type 'enable autonomous' to confirm, or Ctrl-C to cancel:
> """


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class AutonomousMode:
    enabled:              bool   = False
    enabled_by:           str    = ""
    enabled_at:           str    = ""
    enabled_via:          str    = "cli"
    expires_at:           Optional[str] = None
    scope:                dict   = field(default_factory=dict)
    disable_reason:       Optional[str] = None
    disabled_at:          Optional[str] = None
    consecutive_failures: int    = 0
    consecutive_resisted: int    = 0


@dataclass
class RemediationPolicy:
    auto_approve_threshold:       Optional[str] = None   # null | YELLOW | ORANGE
    blocked_action_types:         List[str]     = field(default_factory=list)
    require_approval_action_types: List[str]    = field(default_factory=list)
    max_concurrent_executions:    int           = 1
    execution_window:             Optional[str] = None   # cron-style or null
    notify_on_proposal:           bool          = False
    notify_on_approval:           bool          = False
    notify_on_outcome:            bool          = True
    autonomous:                   AutonomousMode = field(default_factory=AutonomousMode)
    # Autonomous-specific scope fields
    autonomous_action_types:      List[str]     = field(
        default_factory=lambda: list(_DEFAULT_AUTONOMOUS_TYPES)
    )
    autonomous_max_severity:      str           = "ORANGE"
    autonomous_execution_window:  Optional[str] = None
    autonomous_max_concurrent:    int           = 1
    autonomous_expires_at:        Optional[str] = None
    autonomous_notify:            bool          = True
    # Failure/resistance auto-disable thresholds
    auto_disable_on_failures:     int           = 3
    auto_disable_on_resisted:     int           = 2


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def _autonomous_to_dict(a: AutonomousMode) -> dict:
    return {
        "enabled":              a.enabled,
        "enabled_by":           a.enabled_by,
        "enabled_at":           a.enabled_at,
        "enabled_via":          a.enabled_via,
        "expires_at":           a.expires_at,
        "scope":                a.scope,
        "disable_reason":       a.disable_reason,
        "disabled_at":          a.disabled_at,
        "consecutive_failures": a.consecutive_failures,
        "consecutive_resisted": a.consecutive_resisted,
    }


def _autonomous_from_dict(d: dict) -> AutonomousMode:
    return AutonomousMode(
        enabled=d.get("enabled", False),
        enabled_by=d.get("enabled_by", ""),
        enabled_at=d.get("enabled_at", ""),
        enabled_via=d.get("enabled_via", "cli"),
        expires_at=d.get("expires_at"),
        scope=d.get("scope", {}),
        disable_reason=d.get("disable_reason"),
        disabled_at=d.get("disabled_at"),
        consecutive_failures=d.get("consecutive_failures", 0),
        consecutive_resisted=d.get("consecutive_resisted", 0),
    )


def policy_to_dict(policy: RemediationPolicy) -> dict:
    return {
        "auto_approve_threshold":        policy.auto_approve_threshold,
        "blocked_action_types":          policy.blocked_action_types,
        "require_approval_action_types": policy.require_approval_action_types,
        "max_concurrent_executions":     policy.max_concurrent_executions,
        "execution_window":              policy.execution_window,
        "notify_on_proposal":            policy.notify_on_proposal,
        "notify_on_approval":            policy.notify_on_approval,
        "notify_on_outcome":             policy.notify_on_outcome,
        "autonomous":                    _autonomous_to_dict(policy.autonomous),
        "autonomous_action_types":       policy.autonomous_action_types,
        "autonomous_max_severity":       policy.autonomous_max_severity,
        "autonomous_execution_window":   policy.autonomous_execution_window,
        "autonomous_max_concurrent":     policy.autonomous_max_concurrent,
        "autonomous_expires_at":         policy.autonomous_expires_at,
        "autonomous_notify":             policy.autonomous_notify,
        "auto_disable_on_failures":      policy.auto_disable_on_failures,
        "auto_disable_on_resisted":      policy.auto_disable_on_resisted,
    }


def dict_to_policy(d: dict) -> RemediationPolicy:
    auto_raw = d.get("autonomous") or {}
    return RemediationPolicy(
        auto_approve_threshold=d.get("auto_approve_threshold"),
        blocked_action_types=d.get("blocked_action_types", []),
        require_approval_action_types=d.get("require_approval_action_types", []),
        max_concurrent_executions=d.get("max_concurrent_executions", 1),
        execution_window=d.get("execution_window"),
        notify_on_proposal=d.get("notify_on_proposal", False),
        notify_on_approval=d.get("notify_on_approval", False),
        notify_on_outcome=d.get("notify_on_outcome", True),
        autonomous=_autonomous_from_dict(auto_raw),
        autonomous_action_types=d.get("autonomous_action_types", list(_DEFAULT_AUTONOMOUS_TYPES)),
        autonomous_max_severity=d.get("autonomous_max_severity", "ORANGE"),
        autonomous_execution_window=d.get("autonomous_execution_window"),
        autonomous_max_concurrent=d.get("autonomous_max_concurrent", 1),
        autonomous_expires_at=d.get("autonomous_expires_at"),
        autonomous_notify=d.get("autonomous_notify", True),
        auto_disable_on_failures=d.get("auto_disable_on_failures", 3),
        auto_disable_on_resisted=d.get("auto_disable_on_resisted", 2),
    )


def load_policy(state: dict) -> RemediationPolicy:
    raw = state.get("remediation_policy") or {}
    return dict_to_policy(raw)


def save_policy(policy: RemediationPolicy, state: dict) -> dict:
    updated = dict(state)
    updated["remediation_policy"] = policy_to_dict(policy)
    return updated


# ---------------------------------------------------------------------------
# Policy evaluation
# ---------------------------------------------------------------------------

def is_blocked(proposal: RemediationProposal, policy: RemediationPolicy) -> bool:
    """Return True if this proposal is blocked by policy and must not execute."""
    return proposal.action_type in policy.blocked_action_types


def is_auto_approvable(proposal: RemediationProposal, policy: RemediationPolicy) -> bool:
    """Return True if this proposal can be auto-approved per policy."""
    threshold = policy.auto_approve_threshold
    if threshold is None:
        return False
    if proposal.action_type in _NEVER_AUTO_APPROVE:
        return False
    if proposal.reversibility == "irreversible":
        return False
    if proposal.severity == "RED":
        return False
    if proposal.action_type in policy.require_approval_action_types:
        return False
    threshold_rank = _SEVERITY_RANK.get(threshold, 0)
    proposal_rank  = _SEVERITY_RANK.get(proposal.severity, 0)
    return proposal_rank <= threshold_rank


def check_execution_window(
    policy: RemediationPolicy,
    now_fn: Optional[Callable] = None,
) -> bool:
    """
    Return True if current time is within the configured execution window.
    Window format: "HH:MM-HH:MM" (daily, 24h) or None (any time).
    """
    window = policy.execution_window or policy.autonomous_execution_window
    if not window:
        return True

    now_str = now_fn() if now_fn else datetime.now(timezone.utc).isoformat()
    try:
        now_dt = datetime.fromisoformat(now_str.replace("Z", "+00:00"))
    except ValueError:
        return False  # unparseable timestamp → deny (fail-safe)

    m = re.match(r"^(\d{2}):(\d{2})-(\d{2}):(\d{2})$", window.strip())
    if not m:
        return False  # malformed window → deny (fail-safe)

    start_h, start_m, end_h, end_m = (int(x) for x in m.groups())
    now_minutes = now_dt.hour * 60 + now_dt.minute
    start_minutes = start_h * 60 + start_m
    end_minutes   = end_h * 60 + end_m

    if start_minutes <= end_minutes:
        return start_minutes <= now_minutes <= end_minutes
    else:
        # Wraps midnight
        return now_minutes >= start_minutes or now_minutes <= end_minutes


# ---------------------------------------------------------------------------
# Autonomous mode
# ---------------------------------------------------------------------------

def is_autonomous_active(
    policy: RemediationPolicy,
    now_fn: Optional[Callable] = None,
) -> bool:
    """Return True if autonomous mode is currently active (enabled and not expired)."""
    if not policy.autonomous.enabled:
        return False
    expires = policy.autonomous.expires_at or policy.autonomous_expires_at
    if expires:
        now_str = now_fn() if now_fn else datetime.now(timezone.utc).isoformat()
        try:
            now_dt = datetime.fromisoformat(now_str.replace("Z", "+00:00"))
            exp_dt = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            if now_dt >= exp_dt:
                return False
        except ValueError:
            pass
    return True


def enable_autonomous(
    policy:    RemediationPolicy,
    scope:     dict,
    operator:  str,
    channel:   str = "cli",
    now_fn:    Optional[Callable] = None,
    expiry_days: int = _AUTONOMOUS_EXPIRY_DAYS,
) -> AutonomousMode:
    """
    Enable autonomous mode. Records the enabling ceremony result.
    scope should contain the reviewed policy snapshot.
    """
    now_str = now_fn() if now_fn else datetime.now(timezone.utc).isoformat()
    try:
        now_dt  = datetime.fromisoformat(now_str.replace("Z", "+00:00"))
        exp_dt  = now_dt + timedelta(days=expiry_days)
        expires = exp_dt.isoformat()
    except ValueError:
        expires = None

    policy.autonomous = AutonomousMode(
        enabled=True,
        enabled_by=operator,
        enabled_at=now_str,
        enabled_via=channel,
        expires_at=expires,
        scope=scope,
        consecutive_failures=0,
        consecutive_resisted=0,
    )
    policy.autonomous_expires_at = expires
    return policy.autonomous


def disable_autonomous(
    policy:   RemediationPolicy,
    reason:   str = "operator disabled",
    operator: str = "",
    now_fn:   Optional[Callable] = None,
) -> None:
    """Disable autonomous mode. No confirmation required."""
    now_str = now_fn() if now_fn else datetime.now(timezone.utc).isoformat()
    policy.autonomous.enabled     = False
    policy.autonomous.disable_reason = reason
    policy.autonomous.disabled_at = now_str


def evaluate_autonomous_guards(
    policy:        RemediationPolicy,
    state:         dict,
    drill_active:  bool = False,
    now_fn:        Optional[Callable] = None,
    assessment_interval_hours: float = 1.0,
) -> List[str]:
    """
    Hard-exclusion guard checks for autonomous mode.
    Returns list of blocking reasons (empty = all clear to proceed).
    """
    reasons = []

    if not is_autonomous_active(policy, now_fn):
        reasons.append("Autonomous mode is not active.")
        return reasons

    # Drill guard
    if drill_active:
        reasons.append("A reconstruction drill is active — autonomous execution suspended.")

    # Stale state guard
    declared_at = state.get("declared_at") or ""
    if declared_at and assessment_interval_hours:
        now_str = now_fn() if now_fn else datetime.now(timezone.utc).isoformat()
        try:
            now_dt  = datetime.fromisoformat(now_str.replace("Z", "+00:00"))
            decl_dt = datetime.fromisoformat(declared_at.replace("Z", "+00:00"))
            staleness_hours = (now_dt - decl_dt).total_seconds() / 3600.0
            if staleness_hours > 2.0 * assessment_interval_hours:
                reasons.append(
                    f"State is stale ({staleness_hours:.1f}h old, threshold "
                    f"{2*assessment_interval_hours:.1f}h) — autonomous execution suspended."
                )
        except ValueError:
            pass

    # Execution window
    if not check_execution_window(policy, now_fn):
        reasons.append("Current time is outside the configured execution window.")

    return reasons


def should_auto_disable(
    policy:    RemediationPolicy,
    cell_readiness_level: str = "GREEN",
) -> Optional[str]:
    """
    Check if autonomous mode should be auto-disabled.
    Returns a reason string if it should be disabled, None if not.
    """
    if not policy.autonomous.enabled:
        return None

    if cell_readiness_level == "RED":
        return "Cell readiness dropped to RED — autonomous mode auto-disabled."

    if policy.autonomous.consecutive_failures >= policy.auto_disable_on_failures:
        return (
            f"Autonomous mode auto-disabled after "
            f"{policy.autonomous.consecutive_failures} consecutive execution failures."
        )

    if policy.autonomous.consecutive_resisted >= policy.auto_disable_on_resisted:
        return (
            f"Autonomous mode auto-disabled after "
            f"{policy.autonomous.consecutive_resisted} consecutive resisted remediations."
        )

    return None


def is_eligible_for_autonomous(
    proposal: RemediationProposal,
    policy:   RemediationPolicy,
) -> bool:
    """
    Return True if this proposal can be executed in autonomous mode.
    Checks all hard exclusions and scope constraints.
    """
    if not is_autonomous_active(policy):
        return False

    # Hard exclusions
    if proposal.reversibility == "irreversible":
        return False
    if proposal.severity == "RED":
        return False
    if proposal.keepass_gated:
        return False

    # Scope constraints
    if proposal.action_type not in policy.autonomous_action_types:
        return False

    sev_rank = _SEVERITY_RANK.get(proposal.severity, 0)
    max_rank  = _SEVERITY_RANK.get(policy.autonomous_max_severity, 2)
    if sev_rank > max_rank:
        return False

    return True


# ---------------------------------------------------------------------------
# Cross-cell support (Phase 26.6 federation)
# ---------------------------------------------------------------------------

@dataclass
class CrossCellProposal:
    """A remediation proposal that requires coordination across cells."""
    owning_cell_id:      str
    requires_cell_approval: List[str]   = field(default_factory=list)
    approved_cells:      List[str]      = field(default_factory=list)

    def is_fully_approved(self) -> bool:
        return set(self.requires_cell_approval).issubset(set(self.approved_cells))
