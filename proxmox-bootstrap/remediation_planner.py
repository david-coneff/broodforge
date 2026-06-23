#!/usr/bin/env python3
"""
remediation_planner.py — Phase 26.1: Remediation Planner.

Maps assessment gaps to structured RemediationProposals, captures dry-run
output for each action type, and deduplicates against an existing proposal
queue so the same finding does not produce duplicate proposals.

Public API:
  ALLOWED_ACTION_TYPES   — exhaustive set of permitted action types
  RemediationProposal    — single proposal dataclass
  RemediationPlan        — ordered list of proposals
  build_remediation_plan(readiness, state, existing_proposals, now_fn) → RemediationPlan
  dry_run_proposal(proposal, state) → str   (stdout-safe dry-run output)
  proposal_to_dict(p) → dict
  dict_to_proposal(d) → RemediationProposal

Stdlib only.
"""

import uuid
from dataclasses import dataclass, field
from typing import Callable, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_ACTION_TYPES = {
    "restart-service",
    "run-backup",
    "renew-cert",
    "regenerate-phoenix",
    "sync-cert-to-k8s",
    "rotate-join-token",
    "restart-assessment-timer",
    "schedule-drill",
    "flag-manual",
}

_SEVERITY_RANK = {"GREEN": 0, "YELLOW": 1, "ORANGE": 2, "RED": 3, "BLOCKED": 4}

# Action types that always require KeePass gate before execution
_KEEPASS_GATED = {"rotate-join-token", "run-backup"}

# Action types that are never auto-approved regardless of policy
_NEVER_AUTO_APPROVE = {"rotate-join-token"}

# Reversibility per action type
_REVERSIBILITY = {
    "restart-service":          "reversible",
    "run-backup":               "reversible",
    "renew-cert":               "reversible",
    "regenerate-phoenix":       "reversible",
    "sync-cert-to-k8s":        "reversible",
    "rotate-join-token":        "manual-rollback",
    "restart-assessment-timer": "reversible",
    "schedule-drill":           "reversible",
    "flag-manual":              "reversible",
}

# Estimated duration seconds per action type
_ESTIMATED_DURATION = {
    "restart-service":          10,
    "run-backup":               300,
    "renew-cert":               60,
    "regenerate-phoenix":       15,
    "sync-cert-to-k8s":        20,
    "rotate-join-token":        30,
    "restart-assessment-timer": 5,
    "schedule-drill":           5,
    "flag-manual":              0,
}


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class RemediationProposal:
    proposal_id:              str
    issue_id:                 str         # gap/finding identifier that triggered this
    severity:                 str         # YELLOW / ORANGE / RED
    action_type:              str         # from ALLOWED_ACTION_TYPES
    action_description:       str         # human-readable "what will happen"
    target:                   str         # component / service / node
    dry_run_output:           str         # captured without making changes
    reversibility:            str         # reversible / irreversible / manual-rollback
    estimated_duration_seconds: int
    proposed_at:              str
    prerequisite_ids:         List[str]   = field(default_factory=list)
    status:                   str         = "proposed"  # proposed / approved / executing / resolved / rejected / superseded / expired
    approved_by:              Optional[str] = None
    approved_at:              Optional[str] = None
    approval_channel:         Optional[str] = None
    approval_note:            Optional[str] = None
    started_at:               Optional[str] = None
    resolved_at:              Optional[str] = None
    outcome:                  Optional[str] = None
    rejected_by:              Optional[str] = None
    resisted:                 bool          = False
    keepass_gated:            bool          = False
    cell_id:                  Optional[str] = None


@dataclass
class RemediationPlan:
    cell_id:    str
    planned_at: str
    proposals:  List[RemediationProposal] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Proposal construction helpers
# ---------------------------------------------------------------------------

def _make_proposal(
    issue_id:      str,
    severity:      str,
    action_type:   str,
    description:   str,
    target:        str,
    dry_run:       str,
    cell_id:       str,
    prereqs:       Optional[List[str]] = None,
    now_fn:        Callable[[], str]   = None,
) -> RemediationProposal:
    from datetime import datetime, timezone
    ts = now_fn() if now_fn else datetime.now(timezone.utc).isoformat()
    return RemediationProposal(
        proposal_id=str(uuid.uuid4()),
        issue_id=issue_id,
        severity=severity,
        action_type=action_type,
        action_description=description,
        target=target,
        dry_run_output=dry_run,
        reversibility=_REVERSIBILITY.get(action_type, "reversible"),
        estimated_duration_seconds=_ESTIMATED_DURATION.get(action_type, 30),
        proposed_at=ts,
        prerequisite_ids=prereqs or [],
        keepass_gated=(action_type in _KEEPASS_GATED),
        cell_id=cell_id,
    )


# ---------------------------------------------------------------------------
# Dry-run implementations (read-only; return description of what would happen)
# ---------------------------------------------------------------------------

def _dry_run_restart_service(target: str, state: dict) -> str:
    return f"[dry-run] Would execute: ssh ubuntu@<{target}-ip> 'sudo systemctl restart {target}'\nNo changes made."


def _dry_run_run_backup(target: str, state: dict) -> str:
    layers = []
    bc = state.get("backup_config") or {}
    if bc:
        layers = ["secrets", "config"]
        appdata = bc.get("appdata_destinations") or []
        if appdata:
            layers.append("appdata")
    layer_str = target if target else " ".join(layers) or "config"
    return (
        f"[dry-run] Would execute: python3 run-backup.py --layer {layer_str}\n"
        f"Restic snapshot would be created at configured destinations.\n"
        f"No changes made."
    )


def _dry_run_renew_cert(target: str, state: dict) -> str:
    nt = state.get("network_topology") or {}
    provider = nt.get("ssl_provider") or "certbot"
    if provider == "certbot":
        cmd = "certbot renew --quiet"
    else:
        cmd = "acme.sh --renew -d <domain>"
    return (
        f"[dry-run] Would execute: {cmd}\n"
        f"Certificate for {target} would be renewed if within renewal window.\n"
        f"No changes made."
    )


def _dry_run_regenerate_phoenix(target: str, state: dict) -> str:
    return (
        f"[dry-run] Would execute: python3 phoenix_playbook.py --node {target}\n"
        f"Phoenix playbook for {target} would be regenerated from current state.\n"
        f"Old playbook would be retained as backup.\n"
        f"No changes made."
    )


def _dry_run_sync_cert_to_k8s(target: str, state: dict) -> str:
    return (
        "[dry-run] Would execute: bash sync-cert-to-k8s.sh\n"
        "Current TLS certificate would be pushed into k8s TLS secrets in all namespaces.\n"
        "No changes made."
    )


def _dry_run_rotate_join_token(target: str, state: dict) -> str:
    return (
        "[dry-run] Would execute: k3s token rotate\n"
        "New k3s join token would be generated and stored in bootstrap-state.json.\n"
        "Old token would be invalidated — any pending spawn packages would need regeneration.\n"
        "Requires KeePass gate.\n"
        "No changes made."
    )


def _dry_run_restart_assessment_timer(target: str, state: dict) -> str:
    return (
        "[dry-run] Would execute: systemctl enable --now broodforge-operational.timer\n"
        "Operational assessment timer would be started/re-enabled.\n"
        "No changes made."
    )


def _dry_run_schedule_drill(target: str, state: dict) -> str:
    return (
        "[dry-run] Would append a drill reminder entry to bootstrap-state.json reconstruction_drills.\n"
        "Next drill due date would be set to 90 days from now.\n"
        "No changes made."
    )


def _dry_run_flag_manual(target: str, state: dict) -> str:
    return (
        f"[dry-run] No system action — this finding requires manual operator attention for: {target}\n"
        f"The finding will be marked in the queue as needing manual review.\n"
        f"No changes made."
    )


_DRY_RUN_FN = {
    "restart-service":          _dry_run_restart_service,
    "run-backup":               _dry_run_run_backup,
    "renew-cert":               _dry_run_renew_cert,
    "regenerate-phoenix":       _dry_run_regenerate_phoenix,
    "sync-cert-to-k8s":        _dry_run_sync_cert_to_k8s,
    "rotate-join-token":        _dry_run_rotate_join_token,
    "restart-assessment-timer": _dry_run_restart_assessment_timer,
    "schedule-drill":           _dry_run_schedule_drill,
    "flag-manual":              _dry_run_flag_manual,
}


def dry_run_proposal(proposal: "RemediationProposal", state: dict) -> str:
    fn = _DRY_RUN_FN.get(proposal.action_type)
    if fn:
        return fn(proposal.target, state)
    return f"[dry-run] Unknown action type: {proposal.action_type}"


# ---------------------------------------------------------------------------
# Gap → proposal mapping
# ---------------------------------------------------------------------------

def _proposals_from_gaps(gaps: list, state: dict, cell_id: str, now_fn) -> List[RemediationProposal]:
    """Map readiness gaps to proposals. Returns list (may be empty)."""
    proposals = []

    for gap in gaps:
        gap_type  = gap.get("gap_type") or gap.get("type") or ""
        severity  = gap.get("severity") or "YELLOW"
        comp_id   = gap.get("component_id") or gap.get("component") or "unknown"
        desc      = gap.get("description") or gap.get("message") or gap_type

        issue_id  = f"{comp_id}:{gap_type}"

        # -- Service not running --
        if gap_type in ("service_not_running", "service_stopped"):
            svc = comp_id
            p = _make_proposal(
                issue_id=issue_id, severity=severity,
                action_type="restart-service",
                description=f"Restart service '{svc}' — currently stopped.",
                target=svc,
                dry_run=_dry_run_restart_service(svc, state),
                cell_id=cell_id, now_fn=now_fn,
            )
            proposals.append(p)

        # -- Backup missing or stale --
        elif gap_type in ("backup_missing", "backup_stale", "backup_all_fail",
                          "no_backup_configured", "backup_overdue"):
            layer = "config" if "config" in comp_id else "secrets"
            p = _make_proposal(
                issue_id=issue_id, severity=severity,
                action_type="run-backup",
                description=f"Run backup for {comp_id} — backup is missing or overdue.",
                target=layer,
                dry_run=_dry_run_run_backup(layer, state),
                cell_id=cell_id, now_fn=now_fn,
            )
            proposals.append(p)

        # -- Certificate expiry --
        elif gap_type in ("cert_expiry_critical", "cert_expiry_warning", "cert_near_expiry"):
            p = _make_proposal(
                issue_id=issue_id, severity=severity,
                action_type="renew-cert",
                description=f"Renew certificate for {comp_id} — expiry approaching.",
                target=comp_id,
                dry_run=_dry_run_renew_cert(comp_id, state),
                cell_id=cell_id, now_fn=now_fn,
            )
            proposals.append(p)

        # -- Phoenix playbook stale or missing --
        elif gap_type in ("phoenix_playbook_missing", "phoenix_playbook_stale"):
            p = _make_proposal(
                issue_id=issue_id, severity=severity,
                action_type="regenerate-phoenix",
                description=f"Regenerate phoenix playbook for {comp_id} — playbook is missing or stale.",
                target=comp_id,
                dry_run=_dry_run_regenerate_phoenix(comp_id, state),
                cell_id=cell_id, now_fn=now_fn,
            )
            proposals.append(p)

        # -- Assessment timer not running --
        elif gap_type in ("assessment_timer_inactive", "no_continuous_assessment"):
            p = _make_proposal(
                issue_id=issue_id, severity=severity,
                action_type="restart-assessment-timer",
                description="Enable the operational assessment timer — continuous assessment is not running.",
                target="broodforge-operational.timer",
                dry_run=_dry_run_restart_assessment_timer("", state),
                cell_id=cell_id, now_fn=now_fn,
            )
            proposals.append(p)

        # -- Reconstruction drill overdue --
        elif gap_type in ("drill_overdue", "no_reconstruction_drill"):
            p = _make_proposal(
                issue_id=issue_id, severity=severity,
                action_type="schedule-drill",
                description="Schedule a reconstruction drill — last drill is overdue or no drill has been run.",
                target="reconstruction_drills",
                dry_run=_dry_run_schedule_drill("", state),
                cell_id=cell_id, now_fn=now_fn,
            )
            proposals.append(p)

        # -- k3s join token stale --
        elif gap_type in ("join_token_stale", "join_token_missing"):
            p = _make_proposal(
                issue_id=issue_id, severity=severity,
                action_type="rotate-join-token",
                description="Rotate k3s join token — current token is stale or missing.",
                target="k3s-join-token",
                dry_run=_dry_run_rotate_join_token("", state),
                cell_id=cell_id, now_fn=now_fn,
            )
            proposals.append(p)

        # -- Cert not synced to k8s --
        elif gap_type == "cert_not_in_k8s":
            p = _make_proposal(
                issue_id=issue_id, severity=severity,
                action_type="sync-cert-to-k8s",
                description="Sync TLS certificate to k8s secrets — cluster secret is out of date.",
                target="k8s-tls-secrets",
                dry_run=_dry_run_sync_cert_to_k8s("", state),
                cell_id=cell_id, now_fn=now_fn,
            )
            proposals.append(p)

        # -- Everything else → flag for manual attention --
        else:
            p = _make_proposal(
                issue_id=issue_id, severity=severity,
                action_type="flag-manual",
                description=f"Manual attention required: {desc}",
                target=comp_id,
                dry_run=_dry_run_flag_manual(desc, state),
                cell_id=cell_id, now_fn=now_fn,
            )
            proposals.append(p)

    return proposals


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _dedup_proposals(
    existing:  List[dict],
    new_props: List[RemediationProposal],
) -> List[RemediationProposal]:
    """
    For each new proposal, check if an identical (same issue_id + action_type)
    proposal already exists in the queue in a non-terminal state.
    If so, skip the new one (don't create duplicate).
    Returns only truly new proposals.
    """
    _terminal = {"resolved", "rejected", "superseded", "expired"}
    active_keys = set()
    for ep in existing:
        if ep.get("status") not in _terminal:
            key = f"{ep.get('issue_id')}:{ep.get('action_type')}"
            active_keys.add(key)

    result = []
    for p in new_props:
        key = f"{p.issue_id}:{p.action_type}"
        if key not in active_keys:
            result.append(p)
    return result


# ---------------------------------------------------------------------------
# Main planner entry point
# ---------------------------------------------------------------------------

def build_remediation_plan(
    readiness,
    state:              dict,
    existing_proposals: List[dict] = None,
    now_fn:             Callable[[], str] = None,
) -> RemediationPlan:
    """
    Build a RemediationPlan from a readiness assessment and current state.

    readiness: object with .overall_score, .components (list of ComponentReadiness)
               OR a dict with "components" list containing gap dicts.
    state:     bootstrap-state.json dict.
    existing_proposals: list of proposal dicts already in the queue
                        (used for deduplication).
    now_fn:    injectable for tests.
    """
    from datetime import datetime, timezone
    ts = now_fn() if now_fn else datetime.now(timezone.utc).isoformat()

    cell_id = state.get("cell_id") or "unknown"
    existing = existing_proposals or []

    # Collect all gaps from the readiness object
    all_gaps: list = []

    if hasattr(readiness, "components"):
        for comp in (readiness.components or []):
            gaps = getattr(comp, "gaps", [])
            for g in gaps:
                if hasattr(g, "gap_type"):
                    all_gaps.append({
                        "gap_type":    g.gap_type,
                        "severity":    g.severity,
                        "component_id": g.component_id,
                        "description": g.description,
                    })
                elif isinstance(g, dict):
                    all_gaps.append(g)
    elif isinstance(readiness, dict):
        for comp in readiness.get("components", []):
            for g in comp.get("gaps", []):
                all_gaps.append(g)

    new_proposals = _proposals_from_gaps(all_gaps, state, cell_id, now_fn)
    deduped       = _dedup_proposals(existing, new_proposals)

    return RemediationPlan(
        cell_id=cell_id,
        planned_at=ts,
        proposals=deduped,
    )


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def proposal_to_dict(p: RemediationProposal) -> dict:
    return {
        "proposal_id":               p.proposal_id,
        "issue_id":                  p.issue_id,
        "severity":                  p.severity,
        "action_type":               p.action_type,
        "action_description":        p.action_description,
        "target":                    p.target,
        "dry_run_output":            p.dry_run_output,
        "reversibility":             p.reversibility,
        "estimated_duration_seconds": p.estimated_duration_seconds,
        "proposed_at":               p.proposed_at,
        "prerequisite_ids":          p.prerequisite_ids,
        "status":                    p.status,
        "approved_by":               p.approved_by,
        "approved_at":               p.approved_at,
        "approval_channel":          p.approval_channel,
        "approval_note":             p.approval_note,
        "started_at":                p.started_at,
        "resolved_at":               p.resolved_at,
        "outcome":                   p.outcome,
        "resisted":                  p.resisted,
        "keepass_gated":             p.keepass_gated,
        "cell_id":                   p.cell_id,
    }


def dict_to_proposal(d: dict) -> RemediationProposal:
    return RemediationProposal(
        proposal_id=d.get("proposal_id", str(uuid.uuid4())),
        issue_id=d.get("issue_id", ""),
        severity=d.get("severity", "YELLOW"),
        action_type=d.get("action_type", "flag-manual"),
        action_description=d.get("action_description", ""),
        target=d.get("target", ""),
        dry_run_output=d.get("dry_run_output", ""),
        reversibility=d.get("reversibility", "reversible"),
        estimated_duration_seconds=d.get("estimated_duration_seconds", 30),
        proposed_at=d.get("proposed_at", ""),
        prerequisite_ids=d.get("prerequisite_ids", []),
        status=d.get("status", "proposed"),
        approved_by=d.get("approved_by"),
        approved_at=d.get("approved_at"),
        approval_channel=d.get("approval_channel"),
        approval_note=d.get("approval_note"),
        started_at=d.get("started_at"),
        resolved_at=d.get("resolved_at"),
        outcome=d.get("outcome"),
        resisted=d.get("resisted", False),
        keepass_gated=d.get("keepass_gated", False),
        cell_id=d.get("cell_id"),
    )
