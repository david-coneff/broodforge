#!/usr/bin/env python3
"""
remediation-cli.py — Phase 26.2 / 26.7: Remediation queue CLI.

Commands:
  list                     Show pending proposals with dry-run summary
  approve <id>             Approve a single proposal
  approve-all [--severity YELLOW|ORANGE]  Batch approve by max severity
  reject <id> [--reason TEXT]  Reject a proposal
  dry-run <id>             Re-run dry-run and display output
  history [--limit N]      Show resolved/rejected proposals
  enable-autonomous        Run the two-step enabling ceremony
  disable-autonomous       Disable autonomous mode (immediate, no confirmation)
  status                   Show queue summary and autonomous mode status

Usage:
  python3 remediation-cli.py --state /path/to/bootstrap-state.json <command> [args]

Stdlib only.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)

from remediation_policy import (
    _AUTONOMOUS_EXPIRY_DAYS,
    _DEFAULT_AUTONOMOUS_TYPES,
    AUTONOMOUS_CEREMONY_PROMPT,
    disable_autonomous,
    enable_autonomous,
    is_autonomous_active,
    load_policy,
    policy_to_dict,
    save_policy,
)
from remediation_queue import (
    approve_proposal,
    batch_approve,
    get_history,
    get_pending,
    load_queue,
    queue_summary,
    reject_proposal,
    save_queue,
)

# ---------------------------------------------------------------------------
# State I/O helpers
# ---------------------------------------------------------------------------

def _load_state(state_path: str) -> dict:
    if not os.path.exists(state_path):
        print(f"[error] State file not found: {state_path}", file=sys.stderr)
        sys.exit(1)
    with open(state_path) as f:
        return json.load(f)


def _save_state(state_path: str, state: dict) -> None:
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)


def _operator_id() -> str:
    import getpass
    import socket
    user = getpass.getuser() if hasattr(os, "getlogin") else os.environ.get("USER", "unknown")
    host = socket.gethostname()
    return f"{user}@{host}"


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

_SEV_COLOR = {
    "RED":    "\033[91m",
    "ORANGE": "\033[33m",
    "YELLOW": "\033[93m",
    "GREEN":  "\033[92m",
}
_RESET = "\033[0m"
_BOLD  = "\033[1m"

def _sev(s: str) -> str:
    return f"{_SEV_COLOR.get(s, '')}{s}{_RESET}"

def _status_color(s: str) -> str:
    colors = {
        "proposed":  "\033[94m",
        "approved":  "\033[92m",
        "executing": "\033[93m",
        "resolved":  "\033[92m",
        "rejected":  "\033[91m",
        "failed":    "\033[91m",
        "expired":   "\033[90m",
        "superseded":"\033[90m",
    }
    return f"{colors.get(s, '')}{s}{_RESET}"


def _print_proposal(p, verbose: bool = False) -> None:
    print(f"  {_BOLD}{p.proposal_id[:8]}{_RESET}  {_sev(p.severity):<20}  {p.action_type:<28}  {p.target}")
    print(f"           {p.action_description}")
    if verbose:
        print(f"           Status: {_status_color(p.status)}")
        print(f"           Reversibility: {p.reversibility}")
        print(f"           KeePass gated: {p.keepass_gated}")
        print("           Dry-run:")
        for line in p.dry_run_output.splitlines():
            print(f"             {line}")
    print()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_list(args, state: dict) -> int:
    queue = load_queue(state)
    pending = get_pending(queue)
    if not pending:
        print("No pending proposals.")
        return 0
    print(f"{_BOLD}Pending proposals ({len(pending)}){_RESET}\n")
    print(f"  {'ID':<10}  {'Severity':<14}  {'Action':<28}  Target")
    print(f"  {'-'*8}  {'-'*12}  {'-'*26}  ------")
    for p in pending:
        _print_proposal(p, verbose=args.verbose if hasattr(args, "verbose") else False)
    return 0


def cmd_approve(args, state: dict, state_path: str) -> int:
    queue  = load_queue(state)
    pid    = args.id
    p      = queue.get(pid)
    if p is None:
        # Try prefix match
        matches = [q for q in queue.proposals if q.proposal_id.startswith(pid)]
        if len(matches) == 1:
            p = matches[0]
            pid = p.proposal_id
        elif len(matches) > 1:
            print(f"[error] Ambiguous ID prefix '{pid}' — matches {len(matches)} proposals.")
            return 1
        else:
            print(f"[error] Proposal '{pid}' not found.")
            return 1

    ok = approve_proposal(queue, pid, _operator_id(), "cli", note=getattr(args, "note", None))
    if not ok:
        print(f"[error] Cannot approve proposal {pid[:8]} — current status: {p.status}")
        return 1

    updated = save_queue(queue, state)
    _save_state(state_path, updated)
    print(f"[ok] Proposal {pid[:8]} approved.")
    return 0


def cmd_approve_all(args, state: dict, state_path: str) -> int:
    severity = (args.severity or "YELLOW").upper()
    if severity not in ("YELLOW", "ORANGE"):
        print("[error] --severity must be YELLOW or ORANGE")
        return 1

    queue = load_queue(state)
    count = batch_approve(queue, severity, _operator_id(), "cli")
    updated = save_queue(queue, state)
    _save_state(state_path, updated)
    print(f"[ok] Approved {count} proposals at or below {severity}.")
    return 0


def cmd_reject(args, state: dict, state_path: str) -> int:
    queue  = load_queue(state)
    pid    = args.id
    p      = queue.get(pid)
    if p is None:
        matches = [q for q in queue.proposals if q.proposal_id.startswith(pid)]
        if len(matches) == 1:
            p = matches[0]
            pid = p.proposal_id
        else:
            print(f"[error] Proposal '{pid}' not found.")
            return 1

    reason = getattr(args, "reason", None) or "rejected by operator"
    ok = reject_proposal(queue, pid, reason=reason, rejected_by=_operator_id())
    if not ok:
        print(f"[error] Cannot reject proposal {pid[:8]} — status: {p.status}")
        return 1

    updated = save_queue(queue, state)
    _save_state(state_path, updated)
    print(f"[ok] Proposal {pid[:8]} rejected: {reason}")
    return 0


def cmd_dry_run(args, state: dict) -> int:
    from remediation_planner import dry_run_proposal
    queue = load_queue(state)
    pid   = args.id
    p     = queue.get(pid)
    if p is None:
        matches = [q for q in queue.proposals if q.proposal_id.startswith(pid)]
        if len(matches) == 1:
            p = matches[0]
        else:
            print(f"[error] Proposal '{pid}' not found.")
            return 1

    print(f"Dry-run for proposal {p.proposal_id[:8]} ({p.action_type} / {p.target}):\n")
    output = dry_run_proposal(p, state)
    print(output)
    return 0


def cmd_history(args, state: dict) -> int:
    queue = load_queue(state)
    limit = getattr(args, "limit", 20) or 20
    hist  = get_history(queue, limit=limit)
    if not hist:
        print("No resolved/rejected proposals in history.")
        return 0

    print(f"{_BOLD}Proposal history (last {len(hist)}){_RESET}\n")
    for p in hist:
        ts = (p.resolved_at or p.proposed_at or "")[:19]
        print(f"  {p.proposal_id[:8]}  {_status_color(p.status):<30}  {_sev(p.severity):<20}  {p.action_type:<24}  {ts}")
        if p.outcome:
            print(f"           {p.outcome[:100]}")
        if p.resisted:
            print(f"           {_SEV_COLOR['RED']}⚠ resisted — issue persisted after execution{_RESET}")
        print()
    return 0


def cmd_status(args, state: dict) -> int:
    queue  = load_queue(state)
    policy = load_policy(state)
    summ   = queue_summary(queue)

    print(f"{_BOLD}Remediation Queue Status{_RESET}")
    print(f"  Cell:    {queue.cell_id}")
    print(f"  Total:   {summ['total']} proposals")
    for st, cnt in sorted(summ["by_status"].items()):
        print(f"    {_status_color(st):<30}  {cnt}")
    print()

    print(f"{_BOLD}Pending by severity:{_RESET}")
    for sev, cnt in sorted(summ["pending_by_severity"].items()):
        print(f"    {_sev(sev):<20}  {cnt}")
    print()

    print(f"{_BOLD}Autonomous mode:{_RESET}")
    if is_autonomous_active(policy):
        am = policy.autonomous
        expires = (am.expires_at or "no expiry")[:19]
        print(f"  Status:  {_SEV_COLOR['GREEN']}ACTIVE{_RESET}")
        print(f"  Enabled: {am.enabled_at[:19] if am.enabled_at else '?'}  by {am.enabled_by}")
        print(f"  Expires: {expires}")
        print(f"  Max severity: {policy.autonomous_max_severity}")
        print(f"  Action types: {', '.join(sorted(policy.autonomous_action_types))}")
    else:
        print("  Status:  GATED (per-action approval required)")
    print()

    print(f"{_BOLD}Policy:{_RESET}")
    threshold = policy.auto_approve_threshold
    print(f"  Auto-approve threshold: {threshold or 'disabled'}")
    if policy.blocked_action_types:
        print(f"  Blocked actions: {', '.join(policy.blocked_action_types)}")
    return 0


def cmd_enable_autonomous(args, state: dict, state_path: str) -> int:
    policy = load_policy(state)

    if is_autonomous_active(policy):
        print("[warn] Autonomous mode is already active.")
        am = policy.autonomous
        print(f"  Enabled at: {am.enabled_at}")
        print(f"  Expires at: {am.expires_at or 'no expiry'}")
        return 0

    queue = load_queue(state)
    pending_count = len([p for p in queue.proposals if p.status == "proposed"])

    action_types = sorted(policy.autonomous_action_types or _DEFAULT_AUTONOMOUS_TYPES)
    max_severity = policy.autonomous_max_severity or "ORANGE"
    exec_window  = policy.autonomous_execution_window or "any time (no restriction)"
    expiry_days  = _AUTONOMOUS_EXPIRY_DAYS

    now_dt  = datetime.now(timezone.utc)
    exp_dt  = now_dt + timedelta(days=expiry_days)
    expires = exp_dt.strftime("%Y-%m-%d")

    prompt = AUTONOMOUS_CEREMONY_PROMPT.format(
        cell_id=state.get("cell_id", "unknown"),
        pending_count=pending_count,
        action_types=",\n  ".join(action_types),
        max_severity=max_severity,
        execution_window=exec_window,
        expiry_days=expiry_days,
        expires_at=expires,
    )
    print(prompt, end="")

    try:
        answer = input().strip()
    except (EOFError, KeyboardInterrupt):
        print("\n[abort] Autonomous mode NOT enabled.")
        return 0

    if answer != "enable autonomous":
        print("[abort] Confirmation phrase incorrect. Autonomous mode NOT enabled.")
        return 0

    scope = {
        "action_types":     action_types,
        "max_severity":     max_severity,
        "execution_window": exec_window,
        "policy_snapshot":  policy_to_dict(policy),
    }
    operator = _operator_id()
    am = enable_autonomous(policy, scope, operator, "cli")

    updated = save_policy(policy, state)
    _save_state(state_path, updated)

    print("\n[ok] Autonomous mode enabled.")
    print(f"  Enabled by: {am.enabled_by}")
    print(f"  Enabled at: {am.enabled_at[:19]}")
    print(f"  Expires at: {am.expires_at[:19] if am.expires_at else 'no expiry'}")
    print("  Scope recorded in bootstrap-state.json remediation_policy.autonomous.scope")
    return 0


def cmd_disable_autonomous(args, state: dict, state_path: str) -> int:
    policy = load_policy(state)

    if not policy.autonomous.enabled:
        print("[info] Autonomous mode is not currently active.")
        return 0

    queue = load_queue(state)
    active = [p for p in queue.proposals if p.status == "approved"]

    operator = _operator_id()
    disable_autonomous(policy, "operator disabled via CLI", operator=operator)

    updated = save_policy(policy, state)
    _save_state(state_path, updated)

    print("[remediation] Autonomous mode disabled.")
    if active:
        print(f"[remediation] Proposals in queue: {len(active)} now require per-action approval.")
    print(f"[remediation] Disable recorded: {policy.autonomous.disabled_at[:19] if policy.autonomous.disabled_at else '?'} by {operator}")
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="remediation-cli.py",
        description="Broodforge remediation queue management",
    )
    parser.add_argument(
        "--state",
        default=os.environ.get("BROODFORGE_STATE", "/var/lib/broodforge/bootstrap-state.json"),
        help="Path to bootstrap-state.json",
    )

    sub = parser.add_subparsers(dest="command")

    # list
    p_list = sub.add_parser("list", help="Show pending proposals")
    p_list.add_argument("--verbose", "-v", action="store_true")

    # approve
    p_approve = sub.add_parser("approve", help="Approve a proposal")
    p_approve.add_argument("id", help="Proposal ID or prefix")
    p_approve.add_argument("--note", help="Optional approval note")

    # approve-all
    p_aall = sub.add_parser("approve-all", help="Batch approve by max severity")
    p_aall.add_argument("--severity", default="YELLOW",
                        choices=["YELLOW", "ORANGE"], help="Max severity to approve")

    # reject
    p_reject = sub.add_parser("reject", help="Reject a proposal")
    p_reject.add_argument("id", help="Proposal ID or prefix")
    p_reject.add_argument("--reason", help="Optional rejection reason")

    # dry-run
    p_dr = sub.add_parser("dry-run", help="Re-run dry-run for a proposal")
    p_dr.add_argument("id", help="Proposal ID or prefix")

    # history
    p_hist = sub.add_parser("history", help="Show resolved/rejected proposals")
    p_hist.add_argument("--limit", type=int, default=20, help="Max entries to show")

    # status
    sub.add_parser("status", help="Show queue summary and autonomous mode status")

    # enable-autonomous
    sub.add_parser("enable-autonomous", help="Enable fully autonomous mode (ceremony required)")

    # disable-autonomous
    sub.add_parser("disable-autonomous", help="Disable autonomous mode (immediate)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    state = _load_state(args.state)

    if args.command == "list":
        return cmd_list(args, state)
    elif args.command == "approve":
        return cmd_approve(args, state, args.state)
    elif args.command == "approve-all":
        return cmd_approve_all(args, state, args.state)
    elif args.command == "reject":
        return cmd_reject(args, state, args.state)
    elif args.command == "dry-run":
        return cmd_dry_run(args, state)
    elif args.command == "history":
        return cmd_history(args, state)
    elif args.command == "status":
        return cmd_status(args, state)
    elif args.command == "enable-autonomous":
        return cmd_enable_autonomous(args, state, args.state)
    elif args.command == "disable-autonomous":
        return cmd_disable_autonomous(args, state, args.state)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
