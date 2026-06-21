#!/usr/bin/env python3
"""
broodforge_dashboard.py — Broodforge sidecar web dashboard (Approach A).

Serves a live HTML dashboard on a dedicated port (default 9322) that reads
bootstrap-state.json and generated reports to give a read-only health view
of the cell without requiring shell access.

Architecture note: this is the Approach A sidecar described in the review
report. It is entirely independent of Proxmox's pveproxy — it runs as its own
systemd service and serves directly from Python's stdlib HTTP server.

Endpoints:
  GET /                       HTML dashboard
  GET /api/state              bootstrap-state.json as-is
  GET /api/readiness          latest readiness scores (from report JSON if present)
  GET /api/nodes              node inventory from bootstrap-state.json
  GET /api/failures           failure package list from storage dir
  GET /api/backup-status      backup config + last-run info from state
  POST /api/analyze-failures  trigger analysis of unanalyzed failure packages

Security model (first pass):
  - Read-only views require no authentication — they show state, not secrets.
  - POST actions are gated: the client must provide X-Broodforge-Token matching
    the token in the config file (auto-generated at first start if absent).
  - The server binds to 0.0.0.0 by default. On a secured hatchery LAN this is
    acceptable. For WAN-capable deployments, bind to a specific interface IP or
    put nginx in front.

Stdlib only.
"""

import argparse
import hashlib
import html as _html
import http.server
import json
import os
import re
import secrets
import ssl
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http import HTTPStatus
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

# Ensure co-located modules are importable when invoked from a different cwd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from remediation_queue import (
        load_queue, save_queue,
        approve_proposal, reject_proposal, batch_approve,
    )
    _HAS_REMEDIATION_QUEUE = True
except ImportError:
    _HAS_REMEDIATION_QUEUE = False

try:
    from backup_manager import BackupManager, BackupScope, _parse_scope_arg
    _HAS_BACKUP_MANAGER = True
except ImportError:
    _HAS_BACKUP_MANAGER = False

try:
    from node_planner import NodePlanner, VALID_ROLES as _NP_VALID_ROLES
    _HAS_NODE_PLANNER = True
except ImportError:
    _HAS_NODE_PLANNER = False

try:
    from continuous_assessment import (
        assess_code_health, CodeHealthScore,
        assess_dynamic_health, DynamicHealthScore,
    )
    _HAS_CODE_HEALTH = True
except ImportError:
    _HAS_CODE_HEALTH = False
    # Minimal stubs so type annotations below don't fail at import time
    class CodeHealthScore:  # type: ignore[no-redef]
        shellcheck_findings: int = 0
        bandit_high_count: int = 0
        bandit_medium_count: int = 0
        vulture_dead_pct: float = 0.0
        coverage_pct: float = 0.0
        overall: int = 0
        assessed_at: str = ""
        error: Optional[str] = "continuous_assessment not available"

    class DynamicHealthScore:  # type: ignore[no-redef]
        hypothesis_findings: int = 0
        mutation_score: Optional[float] = None
        bats_pass: Optional[int] = None
        bats_fail: Optional[int] = None
        schemathesis_findings: int = 0
        dynamic_score: int = 0
        ran_at: str = ""
        error: Optional[str] = "continuous_assessment not available"


def _e(text: object) -> str:
    """HTML-escape a value from bootstrap-state or external data."""
    return _html.escape(str(text) if text is not None else "")


# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

DASHBOARD_VERSION = "7.1"
DEFAULT_PORT      = 9322
DEFAULT_STATE     = "/var/lib/broodforge/bootstrap-state.json"
DEFAULT_REPORTS   = "/var/lib/broodforge/reports"
DEFAULT_FAILURES  = "/var/lib/broodforge/failure-packages"
DEFAULT_CONFIG    = "/etc/broodforge/dashboard.json"
SYSTEMD_SERVICE   = """\
[Unit]
Description=Broodforge Dashboard (sidecar web service)
After=network.target
Wants=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /opt/broodforge/proxmox-bootstrap/broodforge_dashboard.py \\
  --state /var/lib/broodforge/bootstrap-state.json \\
  --reports /var/lib/broodforge/reports \\
  --failures /var/lib/broodforge/failure-packages \\
  --config /etc/broodforge/dashboard.json \\
  --port 9322
Restart=on-failure
RestartSec=10
User=root

[Install]
WantedBy=multi-user.target
"""


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class DashboardConfig:
    state_path:    str = DEFAULT_STATE
    reports_path:  str = DEFAULT_REPORTS
    failures_path: str = DEFAULT_FAILURES
    config_path:   str = DEFAULT_CONFIG
    listen_host:   str = "0.0.0.0"  # nosec B104 — operator-configurable; WAN exposure warned at startup
    listen_port:   int = DEFAULT_PORT
    action_token:  str = ""   # auto-generated on first start if empty
    ssl_cert:      str = ""   # path to PEM fullchain (optional)
    ssl_key:       str = ""   # path to PEM private key (optional)
    docs_path:     str = ""   # explicit path to docs/ dir; auto-detected if empty

    @classmethod
    def load(cls, path: str) -> "DashboardConfig":
        """Load config from JSON file. Missing file → return defaults."""
        cfg = cls(config_path=path)
        if os.path.exists(path):
            with open(path) as f:
                d = json.load(f)
            cfg.state_path   = d.get("state_path",   cfg.state_path)
            cfg.reports_path = d.get("reports_path", cfg.reports_path)
            cfg.failures_path= d.get("failures_path",cfg.failures_path)
            cfg.listen_host  = d.get("listen_host",  cfg.listen_host)
            cfg.listen_port  = d.get("listen_port",  cfg.listen_port)
            cfg.action_token = d.get("action_token", cfg.action_token)
            cfg.ssl_cert     = d.get("ssl_cert",     cfg.ssl_cert)
            cfg.ssl_key      = d.get("ssl_key",      cfg.ssl_key)
            cfg.docs_path    = d.get("docs_path",    cfg.docs_path)
        return cfg

    def save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.config_path) or ".", exist_ok=True)
            with open(self.config_path, "w") as f:
                json.dump({
                    "state_path":    self.state_path,
                    "reports_path":  self.reports_path,
                    "failures_path": self.failures_path,
                    "listen_host":   self.listen_host,
                    "listen_port":   self.listen_port,
                    "action_token":  self.action_token,
                    "ssl_cert":      self.ssl_cert,
                    "ssl_key":       self.ssl_key,
                    "docs_path":     self.docs_path,
                }, f, indent=2)
        except OSError as exc:
            # Fail loudly: a silent save failure leaves action_token empty on the
            # next restart, making all POST endpoints unauthenticated (F-010/F-032).
            print(
                f"[dashboard] CRITICAL: Cannot write config to {self.config_path}: {exc}\n"
                f"[dashboard] The action token is set in memory but will NOT persist.\n"
                f"[dashboard] All POST endpoints will be unprotected after restart.\n"
                f"[dashboard] Fix the config directory permissions, then restart the dashboard.",
                file=sys.stderr,
            )
            raise

    def ensure_token(self) -> bool:
        """Generate and save an action token if none exists. Returns True if generated."""
        if not self.action_token:
            self.action_token = secrets.token_urlsafe(32)
            self.save()
            return True
        return False


# ---------------------------------------------------------------------------
# State readers
# ---------------------------------------------------------------------------

def _read_json(path: str) -> Optional[dict]:
    """Read a JSON file; return None on any error."""
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _read_bootstrap_state(cfg: DashboardConfig) -> dict:
    state = _read_json(cfg.state_path) or {}
    return state


def _provisioning_state_path(cfg: DashboardConfig) -> str:
    """Return path to provisioning-state.json adjacent to bootstrap-state.json."""
    return os.path.join(
        os.path.dirname(os.path.abspath(cfg.state_path)),
        "provisioning-state.json",
    )


def _read_provisioning_state(cfg: DashboardConfig) -> dict:
    """Load provisioning-state.json. Returns {nodes: []} if absent/invalid."""
    path = _provisioning_state_path(cfg)
    data = _read_json(path)
    if not isinstance(data, dict):
        return {"nodes": []}
    if "nodes" not in data:
        data["nodes"] = []
    return data


def _get_node_planner(cfg: DashboardConfig) -> "Optional[NodePlanner]":
    """Return a NodePlanner instance, or None if node_planner module unavailable."""
    if not _HAS_NODE_PLANNER:
        return None
    state_dir = os.path.dirname(os.path.abspath(cfg.state_path))
    return NodePlanner(state_dir=state_dir)


# Key-name fragments that imply a secret value. bootstrap-state.json stores
# k3s join tokens (k3s.worker_join_token / k3s.server_join_token) and may grow
# other secret-bearing fields over time. The read-only GET endpoints are
# unauthenticated by design ("state, not secrets"), so any secret-bearing value
# must be masked before it leaves the process — otherwise a LAN-adjacent client
# could read a k3s join token from /api/state and join a rogue cluster node.
_SECRET_KEY_PARTS = (
    "token", "password", "passphrase", "secret",
    "private_key", "api_key", "apikey", "auth_key", "authkey",
)
_REDACTED = "***REDACTED***"


def _redact_secrets(obj):
    """Return a deep copy of obj with secret-bearing values masked.

    A value is masked when its key name contains a known secret fragment.
    Non-secret containers are recursed into so nested secrets are also caught.
    Empty values are left as-is so the UI can still show "not set".
    """
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if any(part in str(k).lower() for part in _SECRET_KEY_PARTS):
                out[k] = _REDACTED if v not in (None, "", [], {}, 0, False) else v
            else:
                out[k] = _redact_secrets(v)
        return out
    if isinstance(obj, list):
        return [_redact_secrets(x) for x in obj]
    return obj


def _read_readiness(cfg: DashboardConfig) -> dict:
    """Read the latest Readiness-Report.json from the reports directory."""
    candidates = [
        os.path.join(cfg.reports_path, "recovery_tier2", "Readiness-Report.json"),
        os.path.join(cfg.reports_path, "Readiness-Report.json"),
    ]
    for path in candidates:
        data = _read_json(path)
        if data:
            return data
    return {}


def _read_failure_packages(cfg: DashboardConfig) -> list[dict]:
    """List failure packages from the storage directory."""
    results: list[dict] = []
    if not os.path.isdir(cfg.failures_path):
        return results
    for entry in os.scandir(cfg.failures_path):
        if entry.name.endswith(".tar.gz"):
            receipt_path = entry.path + ".receipt.json"
            meta: dict = {"filename": entry.name, "path": entry.path,
                          "analyzed": False}
            if os.path.exists(receipt_path):
                receipt = _read_json(receipt_path)
                if receipt:
                    meta.update(receipt)
            results.append(meta)
    results.sort(key=lambda x: x.get("received_at", ""), reverse=True)
    return results


# ---------------------------------------------------------------------------
# API data builders
# ---------------------------------------------------------------------------

def _nodes_from_state(state: dict) -> list[dict]:
    """Extract node summaries from bootstrap-state.json."""
    nodes = []
    for node in state.get("nodes", []):
        nodes.append({
            "hostname":   node.get("hostname", "unknown"),
            "role":       node.get("role", "unknown"),
            "vmids":      node.get("vmids", []),
            "ip":         node.get("management_ip", ""),
            "status":     node.get("status", "unknown"),
            "disposition": node.get("disposition", {}),
        })
    return nodes


def _backup_status_from_state(state: dict) -> dict:
    backup = state.get("backup_config") or state.get("data_protection") or {}
    return {
        "configured":       bool(backup),
        "destinations":     backup.get("destinations", []),
        "last_run":         backup.get("last_run_at"),
        "last_run_status":  backup.get("last_run_status"),
        "retention_policy": backup.get("retention_policy", {}),
    }


def _cqb_backup_list(state_dir: str) -> list[dict]:
    """Return CQB backup manifests (newest-first) from backup_manager."""
    if not _HAS_BACKUP_MANAGER:
        return []
    try:
        manager = BackupManager(state_dir=state_dir)
        manifests = manager.list_backups()
        return [m.to_dict() for m in manifests]
    except Exception as exc:
        return [{"error": str(exc)}]


def _security_from_state(state: dict) -> dict:
    """Extract security scan summary from bootstrap-state.json."""
    scan = state.get("security_scan") or {}
    last = scan.get("last_result") or {}
    return {
        "scanned_at":  last.get("scanned_at", ""),
        "red_count":   last.get("red_count", 0),
        "orange_count":last.get("orange_count", 0),
        "yellow_count":last.get("yellow_count", 0),
        "files_scanned":last.get("files_scanned", 0),
        "score":       last.get("score", "UNKNOWN"),
        "findings":    last.get("findings", [])[:10],
        "has_scan":    bool(last),
    }


def _remediations_from_state(state: dict) -> dict:
    """Extract remediation queue and policy summary from bootstrap-state.json."""
    proposals = state.get("remediations") or []
    policy    = state.get("remediation_policy") or {}
    autonomous = policy.get("autonomous") or {}

    pending  = [p for p in proposals if p.get("status") == "proposed"]
    approved = [p for p in proposals if p.get("status") == "approved"]
    recent   = sorted(
        [p for p in proposals if p.get("status") in
         ("resolved", "rejected", "failed", "expired")],
        key=lambda x: x.get("resolved_at") or x.get("proposed_at") or "",
        reverse=True,
    )[:20]

    return {
        "pending":          pending,
        "approved":         approved,
        "recent":           recent,
        "total":            len(proposals),
        "auto_enabled":     bool(autonomous.get("enabled")),
        "auto_expires_at":  autonomous.get("expires_at"),
        "auto_enabled_by":  autonomous.get("enabled_by", ""),
        "auto_threshold":   policy.get("auto_approve_threshold"),
    }


def _scores_from_readiness(readiness: dict) -> dict:
    """Extract score dict from readiness report, tolerating various formats.

    Supports two formats:
    - Legacy/future: dict with ACS/RRS/DCS/CRS/OSS/PHS keys
    - Current readiness.py output: dict with overall_score + overall_score_reason
      (ReadinessReport.to_dict() — no per-category abbreviation keys)
    Both formats pass through; the dashboard rendering falls back gracefully.
    """
    scores = readiness.get("scores") or readiness.get("summary") or {}
    # Promote top-level abbreviation keys if present (legacy format)
    for key in ("ACS", "RRS", "DCS", "CRS", "OSS", "PHS"):
        if key not in scores and key in readiness:
            scores[key] = readiness[key]
    # Also pass through overall_score / overall_score_reason produced by
    # readiness.py score_graph() so the dashboard can render a fallback badge
    if "overall_score" in readiness:
        scores.setdefault("overall_score", readiness["overall_score"])
    if "overall_score_reason" in readiness:
        scores.setdefault("overall_score_reason", readiness["overall_score_reason"])
    return scores


# ---------------------------------------------------------------------------
# Code Health helpers (Phase 1.L)
# ---------------------------------------------------------------------------

def _code_health_from_assessment(repo_root: str = ".") -> "CodeHealthScore":
    """Call assess_code_health() with the repo root derived from this script's location."""
    if not _HAS_CODE_HEALTH:
        score = CodeHealthScore()
        score.error = "continuous_assessment module not available"
        return score
    try:
        return assess_code_health(repo_root)
    except Exception as exc:
        score = CodeHealthScore()
        score.error = str(exc)
        return score


def _dynamic_health_from_assessment(repo_root: str = ".") -> "DynamicHealthScore":
    """Call assess_dynamic_health() with the repo root derived from this script's location."""
    if not _HAS_CODE_HEALTH:
        score = DynamicHealthScore()
        score.error = "continuous_assessment module not available"
        return score
    try:
        return assess_dynamic_health(repo_root)
    except Exception as exc:
        score = DynamicHealthScore()
        score.error = str(exc)
        return score


def _build_dynamic_health_subcard(dynamic: "Optional[DynamicHealthScore]") -> str:
    """Build an HTML sub-section for the dynamic analysis row of the Code Health card."""
    if dynamic is None:
        return '<p style="color:var(--muted);font-size:.82em">Dynamic score: not assessed</p>'

    dyn_error  = getattr(dynamic, "error", None)
    not_impl   = getattr(dynamic, "not_implemented", False)
    dyn_score  = getattr(dynamic, "overall", -1)
    hyp_fail   = getattr(dynamic, "hypothesis_failures", 0)
    mut_pct    = getattr(dynamic, "mutation_score_pct", -1.0)
    bats_pass  = getattr(dynamic, "bats_passed", 0)
    bats_fail  = getattr(dynamic, "bats_failed", 0)
    bats_total = getattr(dynamic, "bats_total", 0)
    ran_at     = (getattr(dynamic, "assessed_at", "") or "")[:16]

    if not_impl:
        return (
            '<div style="margin-top:.6em;padding:.5em .75em;'
            'border-left:2px solid var(--muted);font-size:.85em">'
            '<strong>Dynamic analysis:</strong> <span style="color:var(--muted)">'
            'not yet configured — add hypothesis tests or bats scripts to enable</span>'
            '</div>'
        )

    if dyn_error:
        return (
            '<div style="margin-top:.6em;padding:.5em .75em;'
            'border-left:2px solid var(--muted);font-size:.85em">'
            f'<strong>Dynamic:</strong> <span style="color:var(--muted)">'
            f'not yet run — {_e(dyn_error)}</span>'
            '</div>'
        )

    dyn_color = (
        "var(--green)"  if dyn_score >= 90 else
        "var(--yellow)" if dyn_score >= 70 else
        "var(--orange)" if dyn_score >= 50 else
        "var(--red)"
    )
    hyp_color = "var(--red)" if hyp_fail > 0 else "var(--green)"

    mut_display = f"{mut_pct:.1f}%" if mut_pct >= 0 else "n/a"
    mut_color   = (
        "var(--green)"  if mut_pct >= 80 else
        "var(--yellow)" if mut_pct >= 60 else
        "var(--orange)" if mut_pct >= 40 else
        "var(--red)"    if mut_pct >= 0 else "var(--muted)"
    )
    bats_color   = "var(--red)" if bats_fail > 0 else "var(--green)"
    bats_display = f"{bats_pass}/{bats_total}" if bats_total > 0 else "n/a"

    ran_note = f' · assessed {_e(ran_at)}' if ran_at else ''
    mut_tip = (
        f'<div class="tip" style="border-color:var(--orange);margin-top:.3em">'
        f'mutation score {mut_pct:.0f}% below 80% target — strengthen test assertions</div>'
        if mut_pct >= 0 and mut_pct < 80 else ''
    )

    return f"""<div style="margin-top:.6em;padding:.5em .75em;border-left:2px solid var(--muted)">
<strong style="font-size:.85em">Dynamic analysis (Phase 1.M){ran_note}:</strong>
<div class="stat-row" style="margin-top:.3em">
  <div class="stat">
    <div class="stat-val" style="color:{dyn_color}">{dyn_score}</div>
    <div class="stat-label">dynamic score</div>
  </div>
  <div class="stat">
    <div class="stat-val" style="color:{hyp_color}">{hyp_fail}</div>
    <div class="stat-label">hypothesis failures</div>
  </div>
  <div class="stat">
    <div class="stat-val" style="color:{mut_color}">{_e(mut_display)}</div>
    <div class="stat-label">mutation score</div>
  </div>
  <div class="stat">
    <div class="stat-val" style="color:{bats_color}">{_e(bats_display)}</div>
    <div class="stat-label">bats pass/total</div>
  </div>
</div>
{('<div class="tip" style="border-color:var(--red);margin-top:.3em">hypothesis falsified a property — run pytest -k hypothesis to reproduce</div>' if hyp_fail > 0 else '')}
{mut_tip}
{('<div class="tip" style="border-color:var(--red);margin-top:.3em">bats test failures detected in tests/bash/</div>' if bats_fail > 0 else '')}
</div>"""


def _build_code_health_card(
    score: "CodeHealthScore",
    dynamic_health: "Optional[DynamicHealthScore]" = None,
) -> str:
    """Build an HTML card for the Code Health section of the dashboard.

    Shows static analysis row (24.8) and — if available — the dynamic
    analysis sub-row (24.9, AD-063) in the same card.
    """
    overall = getattr(score, "overall", 0)
    error = getattr(score, "error", None)
    assessed_at = (getattr(score, "assessed_at", "") or "")[:16]

    if overall >= 90:
        score_color = "var(--green)"
    elif overall >= 70:
        score_color = "var(--yellow)"
    elif overall >= 50:
        score_color = "var(--orange)"
    else:
        score_color = "var(--red)"

    if error:
        body = (
            f'<div class="tip" style="border-color:var(--muted)">'
            f'Code health assessment unavailable: {_e(error)}'
            f'</div>'
            f'<p style="color:var(--muted);font-size:.82em">Run <code>tools/run-static-audit.sh</code> to generate findings.</p>'
        )
    else:
        sc = getattr(score, "shellcheck_findings", 0)
        bh = getattr(score, "bandit_high_count", 0)
        bm = getattr(score, "bandit_medium_count", 0)
        vd = getattr(score, "vulture_dead_pct", 0.0)
        cov = getattr(score, "coverage_pct", 0.0)

        bh_color = "var(--red)" if bh > 0 else "var(--green)"
        sc_color  = "var(--orange)" if sc > 0 else "var(--green)"
        cov_color = "var(--green)" if cov >= 80 else ("var(--yellow)" if cov >= 60 else "var(--red)")

        body = f"""
<div class="stat-row">
  <div class="stat">
    <div class="stat-val" style="color:{score_color}">{overall}</div>
    <div class="stat-label">Static score</div>
  </div>
  <div class="stat">
    <div class="stat-val" style="color:{sc_color}">{sc}</div>
    <div class="stat-label">shellcheck findings</div>
  </div>
  <div class="stat">
    <div class="stat-val" style="color:{bh_color}">{bh}</div>
    <div class="stat-label">bandit HIGH</div>
  </div>
  <div class="stat">
    <div class="stat-val" style="color:var(--yellow)">{bm}</div>
    <div class="stat-label">bandit MEDIUM</div>
  </div>
  <div class="stat">
    <div class="stat-val" style="color:var(--muted);font-size:.95em">{vd:.1f}%</div>
    <div class="stat-label">dead code</div>
  </div>
  <div class="stat">
    <div class="stat-val" style="color:{cov_color}">{cov:.1f}%</div>
    <div class="stat-label">coverage</div>
  </div>
</div>
{('<div class="tip" style="border-color:var(--red)">HIGH bandit findings detected — review <code>.audit/bandit-report.json</code></div>' if bh > 0 else '')}
{('<div class="tip" style="border-color:var(--orange)">shellcheck warnings in .sh files — run <code>tools/run-static-audit.sh</code> for details</div>' if sc > 0 else '')}
{_build_dynamic_health_subcard(dynamic_health)}
"""
        if assessed_at:
            body += f'<p class="refresh-note">Last assessed: {_e(assessed_at)} · Run <code>tools/run-static-audit.sh</code> to refresh</p>'
        else:
            body += '<p class="refresh-note">Run <code>tools/run-static-audit.sh</code> to populate findings</p>'

    return f'<div class="section-wrap">{body}</div>'


def _code_health_to_remediation_candidates(
    score: "CodeHealthScore",
    dynamic: "Optional[DynamicHealthScore]" = None,
) -> list[dict]:
    """
    Thin wrapper — delegates to the shared functions in continuous_assessment.py.

    Merges static findings (code_health_to_remediation_candidates) with dynamic
    findings (dynamic_health_to_remediation_candidates). The authoritative logic
    lives in continuous_assessment.py so assess_code_health() / assess_dynamic_health()
    can feed the remediation pipeline directly without going through the dashboard.
    """
    try:
        from continuous_assessment import (
            code_health_to_remediation_candidates as _static_candidates,
            dynamic_health_to_remediation_candidates as _dynamic_candidates,
        )
    except ImportError:
        return []

    candidates = _static_candidates(score)

    dyn = dynamic or getattr(score, "dynamic", None)
    if dyn is not None:
        candidates = candidates + _dynamic_candidates(dyn)

    return candidates


# ---------------------------------------------------------------------------
# HTML dashboard generator
# ---------------------------------------------------------------------------

_SCORE_COLORS = {
    "GREEN":   ("#a6e3a1", "#1e3a22"),
    "YELLOW":  ("#f9e2af", "#3a2e1a"),
    "ORANGE":  ("#fab387", "#3a2610"),
    "RED":     ("#f38ba8", "#3a1e1e"),
    "BLOCKED": ("#7f8498", "#22262e"),
}

_SCORE_LABELS = {
    "ACS": "Architecture Completeness",
    "RRS": "Recovery Readiness",
    "DCS": "Documentation Currency",
    "CRS": "Capacity Readiness",
    "OSS": "Operational Stability",
    "PHS": "Platform Health",
    "OVR": "Overall Score",
}


def _score_badge(abbr: str, level: str) -> str:
    fg, bg = _SCORE_COLORS.get(level.upper(), ("#7f8498", "#22262e"))
    label  = _SCORE_LABELS.get(abbr, abbr)
    return (
        f'<div class="score-card" style="background:{bg};border-color:{fg}">'
        f'<div class="score-abbr" style="color:{fg}">{_e(abbr)}</div>'
        f'<div class="score-level" style="color:{fg}">{_e(level)}</div>'
        f'<div class="score-name">{label}</div>'
        f'</div>'
    )


def _node_card(node: dict) -> str:
    hostname = _e(node.get("hostname", "unknown"))
    role     = _e(node.get("role", ""))
    ip       = _e(node.get("ip", ""))
    status   = node.get("status", "unknown")
    disp     = node.get("disposition") or {}
    services = disp.get("services", [])
    status_color = "#a6e3a1" if status == "running" else "#f38ba8" if status == "error" else "#f9e2af"
    svc_html = "".join(
        f'<span class="svc-badge">{_e(s)}</span>' for s in services[:8]
    ) if services else '<span style="color:var(--muted);font-size:.8em">No declared services</span>'
    return f"""
<div class="node-card">
  <div class="node-header">
    <span class="node-hostname">{hostname}</span>
    <span class="node-role">{role}</span>
    <span class="node-status" style="color:{status_color}">{_e(status)}</span>
  </div>
  <div class="node-ip"><code>{ip}</code></div>
  <div class="node-services">{svc_html}</div>
</div>"""


def _failure_row(pkg: dict) -> str:
    fname    = _e(pkg.get("filename", "unknown"))
    recv     = pkg.get("received_at", "")
    analyzed = pkg.get("analyzed", False)
    etype    = _e(pkg.get("error_type", ""))
    phase    = _e(pkg.get("failed_phase", ""))
    host     = _e(pkg.get("broodling_host", ""))
    dot_color = "#a6e3a1" if analyzed else "#f9e2af"
    detail   = f"<code>{phase}</code> · <code>{etype}</code>" if etype else ""
    return f"""
<tr>
  <td><span style="color:{dot_color}">●</span></td>
  <td><code style="font-size:.82em">{fname}</code></td>
  <td>{host}</td>
  <td>{detail}</td>
  <td style="color:var(--muted);font-size:.82em">{_e(recv[:19]) if recv else '—'}</td>
  <td>{'<span style="color:var(--green)">✓ analyzed</span>' if analyzed else '<span style="color:var(--yellow)">pending</span>'}</td>
</tr>"""


def _remediation_card(p: dict) -> str:
    sev   = p.get("severity", "YELLOW")
    sev_c = {"RED": "var(--red)", "ORANGE": "var(--orange)", "YELLOW": "var(--yellow)"}.get(sev, "var(--muted)")
    pid   = _e(p.get("proposal_id", "")[:8])
    atype = _e(p.get("action_type", ""))
    target= _e(p.get("target", ""))
    desc  = _e(p.get("action_description", ""))
    rev   = _e(p.get("reversibility", ""))
    kp    = p.get("keepass_gated", False)
    status= p.get("status", "proposed")
    ts    = _e((p.get("proposed_at") or "")[:16])
    raw_pid = p.get("proposal_id", "")

    # json.dumps produces a properly JS-escaped string literal (handles quotes, backslashes)
    pid_js = json.dumps(raw_pid)
    approve_btn = (
        f'<button class="btn-approve" '
        f'onclick="approveProposal({pid_js},this)">'
        f'Approve</button>'
    )
    reject_btn = (
        f'<button class="btn-reject" '
        f'onclick="rejectProposal({pid_js},this)">'
        f'Reject</button>'
    )
    kp_badge = '<span class="kp-badge">🔑 KeePass</span>' if kp else ""

    return f"""
<div class="rem-card" data-id="{_e(raw_pid)}">
  <div class="rem-header">
    <span class="rem-sev" style="color:{sev_c};border-color:{sev_c}">{_e(sev)}</span>
    <span class="rem-type">{atype}</span>
    <code class="rem-target">{target}</code>
    {kp_badge}
    <span class="rem-id" style="color:var(--muted);font-size:.75em;margin-left:auto">{pid}</span>
  </div>
  <div class="rem-desc">{desc}</div>
  <div class="rem-meta" style="font-size:.78em;color:var(--muted);margin-top:4px">
    {rev} · {ts}
  </div>
  <div class="rem-actions" style="margin-top:8px;display:flex;gap:8px">
    {approve_btn}{reject_btn}
  </div>
</div>"""


def _remediation_history_row(p: dict) -> str:
    status = p.get("status", "")
    sev    = p.get("severity", "")
    sev_c  = {"RED": "var(--red)", "ORANGE": "var(--orange)", "YELLOW": "var(--yellow)"}.get(sev, "var(--muted)")
    sc     = {"resolved": "var(--green)", "rejected": "var(--muted)", "failed": "var(--red)"}.get(status, "var(--muted)")
    ts     = (p.get("resolved_at") or p.get("proposed_at") or "")[:16]
    outcome= _e((p.get("outcome") or "")[:80])
    resisted = "⚠ resisted" if p.get("resisted") else ""
    return f"""
<tr>
  <td><span style="color:{sc}">{_e(status)}</span></td>
  <td><span style="color:{sev_c}">{_e(sev)}</span></td>
  <td>{_e(p.get("action_type",""))}</td>
  <td><code>{_e(p.get("target",""))}</code></td>
  <td style="font-size:.82em;color:var(--muted)">{_e(ts)}</td>
  <td style="font-size:.82em">{outcome} <span style="color:var(--orange)">{resisted}</span></td>
</tr>"""


def _build_cqb_backup_panel(cqb_backups: list[dict], cfg: DashboardConfig) -> str:
    """Build the CQB Backup & Restore panel HTML section."""
    has_bm = _HAS_BACKUP_MANAGER

    # Backup list table rows
    if cqb_backups and not (len(cqb_backups) == 1 and "error" in cqb_backups[0]):
        rows = ""
        for b in cqb_backups[:20]:
            bid     = _e(b.get("backup_id", ""))
            scope   = _e(b.get("scope", ""))
            trigger = _e(b.get("trigger", ""))
            ql      = _e(str(b.get("quiesce_level", "")))
            ts      = _e(b.get("completed_at", "")[:16])
            k8s     = b.get("k8s_snapshots", {})
            etcd_ok = k8s.get("etcd_snapshot", {}).get("status") == "ok" if isinstance(k8s.get("etcd_snapshot"), dict) else False
            pvc_ok  = k8s.get("pvc_restic", {}).get("status") == "ok" if isinstance(k8s.get("pvc_restic"), dict) else False
            etcd_badge = (
                '<span style="color:var(--green);font-size:.75em">etcd✓</span>' if etcd_ok else
                '<span style="color:var(--muted);font-size:.75em">etcd–</span>'
            )
            pvc_badge = (
                '<span style="color:var(--green);font-size:.75em">pvc✓</span>' if pvc_ok else
                '<span style="color:var(--muted);font-size:.75em">pvc–</span>'
            )
            bid_js = json.dumps(b.get("backup_id", ""))
            restore_btn = (
                f'<button class="btn-reject" style="font-size:.72em" '
                f'onclick="cqbRestorePrompt({bid_js},this)">Restore…</button>'
            )
            rows += f"""<tr>
  <td><code style="font-size:.78em">{bid}</code></td>
  <td>{scope}</td>
  <td>{trigger}</td>
  <td style="text-align:center">{ql}</td>
  <td>{etcd_badge} {pvc_badge}</td>
  <td style="color:var(--muted);font-size:.82em">{ts}</td>
  <td>{restore_btn}</td>
</tr>"""
        table_html = f"""<table>
  <tr>
    <th>Backup ID</th><th>Scope</th><th>Trigger</th>
    <th>QL</th><th>k8s</th><th>Completed</th><th>Actions</th>
  </tr>
  {rows}
</table>"""
    elif not has_bm:
        table_html = '<p style="color:var(--muted)">backup_manager module not available — restart dashboard from the broodforge repo root.</p>'
    elif cqb_backups and "error" in cqb_backups[0]:
        table_html = f'<div class="tip" style="border-color:var(--red)">Error loading backups: {_e(cqb_backups[0].get("error",""))}</div>'
    else:
        table_html = '<p style="color:var(--muted)">No CQB backups yet. Run <code>bash scripts/forge-backup.sh</code> or use the form below.</p>'

    # Scheduled backup note
    schedule_note = ""
    state_dir_hint = _e(cfg.state_path.replace("bootstrap-state.json", ""))
    if has_bm:
        schedule_note = (
            f'<div class="tip" style="border-color:var(--border);margin-top:8px">'
            f'<strong>Scheduled backups:</strong> edit <code>{state_dir_hint}backup-schedule.json</code> '
            f'and run <code>bash scripts/forge-backup-scheduled.sh</code> from cron or a systemd timer. '
            f'Default window: 02:00–04:00 UTC, scope=broodforge, max_age=24h.</div>'
        )

    # Trigger backup form
    trigger_form = ""
    if has_bm:
        trigger_form = f"""<div style="margin-top:12px;padding:12px 14px;background:var(--bg3);border:1px solid var(--border);border-radius:var(--radius)">
  <strong style="font-size:.88em">Trigger Backup</strong>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px;align-items:center">
    <select id="cqb-scope" style="background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:3px;padding:4px 8px;font-size:.85em">
      <option value="broodforge">broodforge (level 0 — fast, state only)</option>
      <option value="pod:default/app">pod: (level 1 — k8s etcd + PVC)</option>
      <option value="service:my-service">service: (level 1 — k8s etcd + PVC)</option>
      <option value="vm:100">vm:100 (level 2 — host config + k8s)</option>
      <option value="full">full (level 3 — everything + vzdump)</option>
    </select>
    <label style="font-size:.82em;color:var(--muted)">
      <input type="checkbox" id="cqb-dryrun"> dry-run
    </label>
    <button class="btn-approve" onclick="cqbTriggerBackup(this)">Run Backup</button>
  </div>
  <div id="cqb-backup-result" style="margin-top:6px;font-size:.82em"></div>
</div>"""

    # Restore form
    restore_form = ""
    if has_bm:
        restore_form = f"""<div style="margin-top:8px;padding:12px 14px;background:var(--bg3);border:1px solid var(--border);border-radius:var(--radius)">
  <strong style="font-size:.88em">Restore from Backup</strong>
  <p style="color:var(--muted);font-size:.8em;margin:4px 0 8px">Restore prints a procedure — it does not automatically overwrite live state. Use the Restore… buttons in the table above, or enter a backup ID:</p>
  <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
    <input id="cqb-restore-id" type="text" placeholder="2026-06-09_14-30-22_abc1234"
      style="background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:3px;padding:4px 10px;font-size:.82em;font-family:monospace;width:280px">
    <label style="font-size:.82em;color:var(--muted)">
      <input type="checkbox" id="cqb-restore-dryrun" checked> dry-run
    </label>
    <button class="btn-reject" style="border-color:var(--orange);color:var(--orange)" onclick="cqbRestore(this)">Restore</button>
  </div>
  <div id="cqb-restore-result" style="margin-top:6px;font-size:.82em;font-family:monospace;white-space:pre-wrap"></div>
</div>"""

    count = len([b for b in cqb_backups if "error" not in b])
    return f"""<div class="section-wrap">
  <div class="stat-row" style="margin-bottom:8px">
    <div class="stat"><div class="stat-val">{count}</div><div class="stat-label">Total backups</div></div>
    <div class="stat"><div class="stat-val" style="font-size:.85em;color:var(--muted)">{_e(cqb_backups[0].get("completed_at","Never")[:16]) if cqb_backups and "error" not in cqb_backups[0] else "Never"}</div><div class="stat-label">Most recent</div></div>
  </div>
  {table_html}
  {trigger_form}
  {restore_form}
  {schedule_note}
</div>"""


_STATE_COLORS = {
    "planned":          "var(--muted)",
    "iso-built":        "var(--accent)",
    "joining":          "var(--accent)",
    "pending-approval": "var(--yellow)",
    "active":           "var(--green)",
    "blacklisted":      "var(--red)",
    "decommissioned":   "#666",
}


def _prov_state_badge(state: str) -> str:
    color = _STATE_COLORS.get(state, "var(--muted)")
    return (
        f'<span style="background:{color};color:#000;font-size:.72em;'
        f'font-weight:700;padding:2px 7px;border-radius:3px;'
        f'white-space:nowrap">{_e(state)}</span>'
    )


def _build_prov_nodes_panel(prov_nodes: list[dict], pending: list[dict]) -> str:
    """
    Build the HTML for the Phase 1.Q Provisioning Nodes panel.

    - Pending-approval queue at top with codename + PIN visible.
    - Search/filter bar.
    - Full lifecycle table.
    - Active node detail panel (edit display_name/notes/role, decommission).
    """
    # ── Pending approval queue ──────────────────────────────────────────
    if pending:
        pending_rows = ""
        for n in pending:
            codename = _e(n.get("codename", ""))
            join_pin = _e(n.get("join_pin") or "—")
            joined   = _e((n.get("joined_at") or "")[:16])
            deadline = _e(n.get("join_deadline") or "none")
            fp       = _e(n.get("broodling_public_key_fingerprint") or "—")
            role     = _e(n.get("role") or "")
            pending_rows += f"""
<tr>
  <td><strong style="font-family:monospace">{codename}</strong></td>
  <td><code style="font-size:.85em;letter-spacing:.05em">{join_pin}</code></td>
  <td style="color:var(--muted);font-size:.8em">{fp}</td>
  <td>{role}</td>
  <td style="color:var(--muted)">{joined}</td>
  <td style="color:var(--muted)">{deadline}</td>
  <td>
    <button class="btn-approve" onclick="provApprove('{codename}', this)">Approve</button>
    <button class="btn-reject"  style="margin-left:4px" onclick="provBlacklist('{codename}', this)">Blacklist</button>
  </td>
</tr>"""
        pending_section = f"""
<div style="margin-bottom:14px">
  <strong style="font-size:.9em;color:var(--yellow)">⏳ Pending Approval ({len(pending)})</strong>
  <p style="color:var(--muted);font-size:.8em;margin:4px 0 8px">
    Verify both the codename AND the PIN match what was burned into the ISO before approving.
  </p>
  <div id="prov-approve-msg" style="font-size:.82em;margin-bottom:6px"></div>
  <table>
    <tr>
      <th>Codename</th><th>Join PIN</th><th>Key Fingerprint</th>
      <th>Role</th><th>Joined at</th><th>Deadline</th><th>Actions</th>
    </tr>
    {pending_rows}
  </table>
</div>"""
    else:
        pending_section = '<p style="color:var(--muted);font-size:.85em">No nodes awaiting approval.</p>'

    # ── Full lifecycle table ─────────────────────────────────────────────
    if prov_nodes:
        all_rows = ""
        for n in prov_nodes:
            codename = _e(n.get("codename", ""))
            display  = _e(n.get("display_name") or "")
            role     = _e(n.get("role") or "")
            state    = n.get("state", "")
            badge    = _prov_state_badge(state)
            created  = _e((n.get("created_at") or "")[:16])
            updated  = _e((n.get("updated_at") or "")[:16])
            address  = _e(n.get("assigned_address") or "—")
            hs_name  = _e(n.get("headscale_device_name") or "—")
            bl_reason= _e(n.get("blacklist_reason") or "")
            detail_btn = ""
            if state == "active":
                detail_btn = f'<button class="btn-approve" style="font-size:.75em;padding:2px 8px" onclick="showNodeDetail(\'{codename}\')" >Manage</button>'
            elif state == "blacklisted":
                detail_btn = f'<button class="btn-reject" style="font-size:.75em;padding:2px 8px" onclick="provUnblacklist(\'{codename}\', this)">Un-blacklist</button>'
            all_rows += f"""
<tr class="prov-row" data-codename="{codename}" data-state="{_e(state)}">
  <td><span style="font-family:monospace">{codename}</span>{"<br><small style='color:var(--muted)'>"+display+"</small>" if display else ""}</td>
  <td>{badge}{"<br><small style='color:var(--muted);font-size:.75em'>"+bl_reason+"</small>" if bl_reason else ""}</td>
  <td>{role}</td>
  <td style="color:var(--muted)">{address}</td>
  <td style="color:var(--muted)">{hs_name}</td>
  <td style="color:var(--muted)">{created}</td>
  <td style="color:var(--muted)">{updated}</td>
  <td>{detail_btn}</td>
</tr>"""
        table_section = f"""
<div style="margin-bottom:8px;display:flex;gap:8px;align-items:center">
  <input id="prov-search" type="text" placeholder="🔍 Filter by codename, role, or state…"
    style="flex:1;background:var(--bg3);border:1px solid var(--border);color:var(--text);
           padding:5px 10px;border-radius:var(--radius);font-size:.85em"
    oninput="filterProvNodes(this.value)">
  <select id="prov-state-filter" onchange="filterProvNodes(document.getElementById('prov-search').value)"
    style="background:var(--bg3);border:1px solid var(--border);color:var(--text);
           padding:5px 10px;border-radius:var(--radius);font-size:.85em">
    <option value="">All states</option>
    <option value="planned">planned</option>
    <option value="iso-built">iso-built</option>
    <option value="joining">joining</option>
    <option value="pending-approval">pending-approval</option>
    <option value="active">active</option>
    <option value="blacklisted">blacklisted</option>
    <option value="decommissioned">decommissioned</option>
  </select>
</div>
<table id="prov-table">
  <tr>
    <th>Codename / Display</th><th>State</th><th>Role</th>
    <th>Address</th><th>HS Device</th><th>Created</th><th>Updated</th><th></th>
  </tr>
  {all_rows}
</table>"""
    else:
        table_section = '<p style="color:var(--muted)">No provisioning nodes found. Run <code>forge-plan-nodes.sh</code> to plan nodes.</p>'

    # ── Active node detail panel (hidden by default) ─────────────────────
    detail_panel = """
<div id="prov-detail-panel"
  style="display:none;margin-top:12px;padding:14px 16px;background:var(--bg3);
         border:1px solid var(--border);border-radius:var(--radius)">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
    <strong style="font-size:.95em">Node Details: <span id="detail-codename"></span></strong>
    <button onclick="closeNodeDetail()" style="background:none;border:none;color:var(--muted);
      cursor:pointer;font-size:1.1em">✕</button>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
    <!-- Read-only info -->
    <div>
      <p style="font-size:.8em;color:var(--muted);margin:0 0 4px">Codename (read-only)</p>
      <p id="detail-ro-codename" style="font-family:monospace;font-size:.9em;margin:0 0 10px"></p>
      <p style="font-size:.8em;color:var(--muted);margin:0 0 4px">State</p>
      <p id="detail-ro-state" style="margin:0 0 10px"></p>
      <p style="font-size:.8em;color:var(--muted);margin:0 0 4px">Headscale Node ID</p>
      <p id="detail-ro-hsid" style="font-family:monospace;font-size:.85em;margin:0 0 10px"></p>
      <p style="font-size:.8em;color:var(--muted);margin:0 0 4px">Key Fingerprint</p>
      <p id="detail-ro-fp" style="font-family:monospace;font-size:.78em;word-break:break-all;margin:0 0 10px"></p>
      <p style="font-size:.8em;color:var(--muted);margin:0 0 4px">Approved at</p>
      <p id="detail-ro-approved" style="color:var(--muted);font-size:.85em;margin:0"></p>
    </div>
    <!-- Editable fields -->
    <div>
      <label style="font-size:.8em;color:var(--muted)">Display name</label><br>
      <input id="detail-display-name" type="text" placeholder="e.g. 'rack-a-node-1'"
        style="width:100%;background:var(--bg2);border:1px solid var(--border);
               color:var(--text);padding:5px 9px;border-radius:var(--radius);
               font-size:.87em;margin:3px 0 10px"><br>
      <label style="font-size:.8em;color:var(--muted)">Role</label><br>
      <select id="detail-role"
        style="width:100%;background:var(--bg2);border:1px solid var(--border);
               color:var(--text);padding:5px 9px;border-radius:var(--radius);
               font-size:.87em;margin:3px 0 10px">
        <option value="worker">worker</option>
        <option value="control-plane">control-plane</option>
        <option value="storage">storage</option>
        <option value="general">general</option>
      </select><br>
      <label style="font-size:.8em;color:var(--muted)">Notes</label><br>
      <textarea id="detail-notes" rows="3"
        style="width:100%;background:var(--bg2);border:1px solid var(--border);
               color:var(--text);padding:5px 9px;border-radius:var(--radius);
               font-size:.87em;margin:3px 0 10px;resize:vertical"></textarea><br>
      <button class="btn-approve" onclick="saveNodeFields()" style="font-size:.82em">Save fields</button>
      <span id="detail-save-msg" style="font-size:.8em;margin-left:8px"></span>
    </div>
  </div>
  <!-- Actions row -->
  <div style="margin-top:12px;border-top:1px solid var(--border);padding-top:10px;display:flex;flex-wrap:wrap;gap:8px;align-items:flex-start">
    <!-- Rename Headscale -->
    <div style="display:flex;gap:6px;align-items:center">
      <input id="detail-hs-name" type="text" placeholder="New Headscale name"
        style="background:var(--bg2);border:1px solid var(--border);color:var(--text);
               padding:5px 9px;border-radius:var(--radius);font-size:.82em;width:180px">
      <button class="btn-approve" onclick="renameHeadscale()" style="font-size:.8em">Rename in HS</button>
    </div>
    <!-- Reassign IP -->
    <div style="display:flex;gap:6px;align-items:center">
      <input id="detail-address" type="text" placeholder="IP / CIDR"
        style="background:var(--bg2);border:1px solid var(--border);color:var(--text);
               padding:5px 9px;border-radius:var(--radius);font-size:.82em;width:160px">
      <button class="btn-approve" onclick="reassignAddress()" style="font-size:.8em">Assign IP</button>
    </div>
    <span id="detail-action-msg" style="font-size:.8em;align-self:center"></span>
    <!-- Join deadline -->
    <div style="display:flex;gap:6px;align-items:center;margin-left:auto">
      <input id="detail-deadline" type="datetime-local"
        style="background:var(--bg2);border:1px solid var(--border);color:var(--text);
               padding:5px 9px;border-radius:var(--radius);font-size:.82em">
      <button class="btn-approve" onclick="setDeadline()" style="font-size:.8em">Set deadline</button>
      <button onclick="clearDeadline()" style="font-size:.8em;background:var(--bg2);
        border:1px solid var(--border);color:var(--muted);padding:5px 9px;
        border-radius:var(--radius);cursor:pointer">Clear</button>
    </div>
  </div>
  <!-- Decommission (destructive) -->
  <div style="margin-top:10px;padding:10px;background:#2a1a1a;border:1px solid var(--red);border-radius:var(--radius)">
    <strong style="color:var(--red);font-size:.85em">Decommission node</strong>
    <p style="color:var(--muted);font-size:.78em;margin:4px 0 8px">
      Removes the Headscale device. Type the codename to confirm.
    </p>
    <div style="display:flex;gap:8px;align-items:center">
      <input id="detail-decom-confirm" type="text" placeholder="Type codename to confirm"
        style="background:var(--bg3);border:1px solid var(--red);color:var(--text);
               padding:5px 9px;border-radius:var(--radius);font-size:.82em;width:220px">
      <button class="btn-reject" onclick="decommissionNode()" style="font-size:.8em">Decommission</button>
      <span id="detail-decom-msg" style="font-size:.8em;color:var(--red)"></span>
    </div>
  </div>
</div>"""

    return pending_section + "\n" + table_section + "\n" + detail_panel


def generate_dashboard_html(
    state:    dict,
    scores:   dict,
    nodes:    list[dict],
    failures: list[dict],
    backup:   dict,
    cfg:      DashboardConfig,
    remediations: dict = None,
    security: dict = None,
    code_health: "CodeHealthScore" = None,
    dynamic_health: "Optional[DynamicHealthScore]" = None,
    cqb_backups: list[dict] = None,
    prov_nodes: list[dict] = None,
) -> str:
    cell_id       = state.get("cell_id") or "broodforge"
    gen_at        = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    host_id       = state.get("host_identity") or {}
    hostname      = host_id.get("hostname") or host_id.get("fqdn") or cell_id
    remediations  = remediations or {}
    security      = security or {}
    cqb_backups   = cqb_backups or []
    prov_nodes    = prov_nodes or []
    # code_health defaults to an empty CodeHealthScore with no data
    if code_health is None:
        code_health = CodeHealthScore()

    scores_html = ""
    for abbr in ("PHS", "ACS", "RRS", "DCS", "CRS", "OSS"):
        if abbr in scores:
            lvl = scores[abbr] if isinstance(scores[abbr], str) else (scores[abbr] or {}).get("level", "—")
            scores_html += _score_badge(abbr, lvl)
    # Fallback: readiness.py score_graph() produces overall_score / overall_score_reason
    # (no per-category abbreviation keys). Render a single OVR badge so the section is
    # never blank when a valid readiness report exists.
    if not scores_html and scores.get("overall_score"):
        scores_html = _score_badge("OVR", scores["overall_score"])
        if scores.get("overall_score_reason"):
            scores_html += (
                f'<p style="color:var(--muted);margin-top:6px;font-size:.85em">'
                f'{_e(scores["overall_score_reason"])}</p>'
            )
    if not scores_html:
        scores_html = '<p style="color:var(--muted)">No readiness report found — run <code>engine.py --mode recovery</code> to generate one.</p>'

    nodes_html = "".join(_node_card(n) for n in nodes) if nodes else \
        '<p style="color:var(--muted)">No nodes found in bootstrap-state.json.</p>'

    # Phase 1.Q — Provisioning nodes panel
    _prov_pending   = [n for n in prov_nodes if n.get("state") == "pending-approval"]
    _prov_all_count = len(prov_nodes)
    _prov_active    = sum(1 for n in prov_nodes if n.get("state") == "active")
    _prov_planned   = sum(1 for n in prov_nodes if n.get("state") == "planned")
    _prov_blacklisted = sum(1 for n in prov_nodes if n.get("state") == "blacklisted")
    prov_nodes_panel_html = _build_prov_nodes_panel(prov_nodes, _prov_pending)

    fail_rows  = "".join(_failure_row(p) for p in failures[:50]) if failures else \
        '<tr><td colspan="6" style="color:var(--muted);padding:12px">No failure packages received.</td></tr>'
    fail_count = len(failures)
    fail_pending = sum(1 for p in failures if not p.get("analyzed"))

    # Remediations
    rem_pending  = remediations.get("pending", [])
    rem_approved = remediations.get("approved", [])
    rem_recent   = remediations.get("recent", [])
    auto_active  = remediations.get("auto_enabled", False)
    auto_expires = (remediations.get("auto_expires_at") or "")[:16]
    rem_pending_html = "".join(_remediation_card(p) for p in rem_pending) if rem_pending else \
        '<p style="color:var(--muted)">No pending proposals.</p>'
    rem_hist_rows = "".join(_remediation_history_row(p) for p in rem_recent) if rem_recent else \
        '<tr><td colspan="6" style="color:var(--muted);padding:10px">No history yet.</td></tr>'
    auto_badge = (
        '<span class="auto-badge auto-active">AUTO</span>'
        if auto_active else
        '<span class="auto-badge auto-gated">GATED</span>'
    )

    # Security
    sec_score     = security.get("score", "UNKNOWN")
    sec_red       = security.get("red_count", 0)
    sec_orange    = security.get("orange_count", 0)
    sec_yellow    = security.get("yellow_count", 0)
    sec_scanned   = security.get("scanned_at", "")[:16] or "Never"
    sec_has_scan  = security.get("has_scan", False)
    sec_score_c   = {"GREEN": "var(--green)", "YELLOW": "var(--yellow)",
                     "ORANGE": "var(--orange)", "RED": "var(--red)"}.get(sec_score, "var(--muted)")
    sec_findings  = security.get("findings", [])

    bkp_dests = backup.get("destinations", [])
    bkp_last  = backup.get("last_run") or "Never"
    bkp_status= backup.get("last_run_status") or "—"
    bkp_color = "#a6e3a1" if bkp_status == "success" else "#f38ba8" if bkp_status == "error" else "#f9e2af"
    bkp_html  = f'<span style="color:{bkp_color}">{_e(bkp_status)}</span>' if bkp_dests else \
        '<span style="color:var(--muted)">Not configured</span>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>Broodforge Dashboard — {_e(cell_id)}</title>
<style>
  :root{{--bg:#1a1d23;--bg2:#22262e;--bg3:#2a2f3a;--border:#3a3f4d;--text:#cdd6f4;--muted:#7f8498;
    --accent:#89b4fa;--green:#a6e3a1;--yellow:#f9e2af;--orange:#fab387;--red:#f38ba8;--code-bg:#181b21;--radius:6px}}
  .auto-badge{{padding:2px 10px;border-radius:99px;font-size:.75em;font-weight:700;letter-spacing:.05em}}
  .auto-active{{background:#1e3a22;color:var(--green);border:1px solid var(--green)}}
  .auto-gated{{background:var(--bg3);color:var(--muted);border:1px solid var(--border)}}
  .rem-card{{background:var(--bg3);border:1px solid var(--border);border-radius:var(--radius);padding:12px 14px;margin-bottom:8px}}
  .rem-header{{display:flex;align-items:center;gap:8px;margin-bottom:4px;flex-wrap:wrap}}
  .rem-sev{{font-size:.75em;font-weight:700;border:1px solid;padding:1px 7px;border-radius:99px}}
  .rem-type{{font-family:monospace;font-size:.85em;color:var(--accent)}}
  .rem-target{{font-size:.85em}}
  .rem-desc{{font-size:.88em;color:var(--text)}}
  .kp-badge{{font-size:.72em;background:var(--bg2);border:1px solid var(--border);padding:1px 6px;border-radius:3px}}
  .btn-approve{{background:#1e3a22;color:var(--green);border:1px solid var(--green);border-radius:3px;
    padding:3px 12px;cursor:pointer;font-size:.82em}}
  .btn-approve:hover{{background:#2a5c30}}
  .btn-reject{{background:var(--bg2);color:var(--muted);border:1px solid var(--border);border-radius:3px;
    padding:3px 12px;cursor:pointer;font-size:.82em}}
  .btn-reject:hover{{border-color:var(--red);color:var(--red)}}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--text);font-family:'Segoe UI',system-ui,-apple-system,sans-serif;
    font-size:14px;line-height:1.6;padding:0}}
  .topbar{{background:#0e1117;border-bottom:1px solid var(--border);padding:10px 24px;
    display:flex;align-items:center;gap:16px;position:sticky;top:0;z-index:100}}
  .topbar-title{{color:var(--accent);font-size:1.1em;font-weight:700}}
  .topbar-cell{{color:var(--muted);font-size:.88em}}
  .topbar-time{{color:var(--muted);font-size:.78em;margin-left:auto}}
  .topbar-ver{{color:var(--muted);font-size:.75em}}
  .content{{padding:20px 24px;max-width:1200px;margin:0 auto}}
  h2{{color:var(--accent);font-size:.95em;text-transform:uppercase;letter-spacing:.06em;
    margin:20px 0 8px;padding-bottom:4px;border-bottom:1px solid var(--border)}}
  .score-grid{{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin:8px 0}}
  @media(max-width:800px){{.score-grid{{grid-template-columns:repeat(3,1fr)}}}}
  .score-card{{border:1px solid var(--border);border-radius:var(--radius);padding:8px 10px;text-align:center}}
  .score-abbr{{font-size:1em;font-weight:700;font-family:monospace}}
  .score-level{{font-size:.85em;font-weight:700}}
  .score-name{{font-size:.7em;color:var(--muted);margin-top:2px}}
  .node-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:10px;margin:8px 0}}
  .node-card{{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:12px 14px}}
  .node-header{{display:flex;align-items:center;gap:8px;margin-bottom:4px}}
  .node-hostname{{font-weight:700;font-family:monospace;color:var(--text)}}
  .node-role{{font-size:.75em;color:var(--muted);background:var(--bg3);padding:1px 7px;border-radius:99px}}
  .node-status{{font-size:.78em;margin-left:auto;font-weight:600}}
  .node-ip{{color:var(--muted);font-size:.82em;margin-bottom:6px}}
  .node-services{{display:flex;flex-wrap:wrap;gap:4px}}
  .svc-badge{{background:var(--bg3);border:1px solid var(--border);border-radius:3px;
    padding:1px 6px;font-size:.72em;color:var(--muted)}}
  table{{width:100%;border-collapse:collapse;font-size:.88em;margin:8px 0}}
  th{{background:var(--bg2);color:var(--muted);text-align:left;padding:6px 8px;
    border-bottom:1px solid var(--border);font-size:.78em;text-transform:uppercase;letter-spacing:.05em}}
  td{{padding:5px 8px;border-bottom:1px solid var(--bg3);vertical-align:top}}
  tr:last-child td{{border-bottom:none}}
  code{{background:var(--code-bg);color:var(--green);padding:1px 4px;border-radius:3px;
    font-family:'Cascadia Code','Fira Code',Consolas,monospace;font-size:.88em}}
  .stat-row{{display:flex;gap:20px;flex-wrap:wrap;margin:8px 0}}
  .stat{{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);
    padding:8px 14px;min-width:120px}}
  .stat-val{{font-size:1.4em;font-weight:700;color:var(--accent)}}
  .stat-label{{font-size:.75em;color:var(--muted)}}
  .tip{{background:#1e2d3a;border-left:3px solid var(--accent);padding:8px 12px;
    border-radius:0 var(--radius) var(--radius) 0;margin:8px 0;font-size:.88em}}
  .nav-links{{display:flex;gap:10px;flex-wrap:wrap;margin:8px 0}}
  .nav-link{{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);
    padding:5px 14px;text-decoration:none;color:var(--muted);font-size:.82em}}
  .nav-link:hover{{border-color:var(--accent);color:var(--accent)}}
  .section-wrap{{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);
    padding:14px 16px;margin-bottom:16px}}
  .refresh-note{{font-size:.75em;color:var(--muted);margin-top:4px}}
  @media print{{.topbar,.nav-links{{display:none!important}}body{{padding:12px}}}}
</style>
</head>
<body>

<div class="topbar">
  <span class="topbar-title">🔥 Broodforge</span>
  <span class="topbar-cell">{_e(cell_id)} · {_e(hostname)}</span>
  {auto_badge}
  <span class="topbar-time">Generated: {gen_at}</span>
  <span class="topbar-ver">v{DASHBOARD_VERSION}</span>
</div>

<div class="content">

  <div class="nav-links" style="margin-top:12px">
    <a class="nav-link" href="/api/state" target="_blank">📄 State JSON</a>
    <a class="nav-link" href="/api/readiness" target="_blank">📊 Readiness JSON</a>
    <a class="nav-link" href="/api/nodes" target="_blank">🖥 Nodes JSON</a>
    <a class="nav-link" href="/api/failures" target="_blank">❌ Failures JSON</a>
    <a class="nav-link" href="/api/cqb-backups" target="_blank">💾 CQB Backups JSON</a>
    <a class="nav-link" href="/api/provisioning-nodes" target="_blank">🖥 Provisioning Nodes JSON</a>
    <a class="nav-link" href="docs/SETUP-GUIDE.html" target="_blank">📋 Setup Guide</a>
    <a class="nav-link" href="docs/ARCHITECTURE.html" target="_blank">🏗 Architecture</a>
    <button class="nav-link" onclick="location.reload()">↻ Refresh</button>
  </div>

  <!-- ── Assessment Scores ── -->
  <h2>Assessment Scores</h2>
  <div class="section-wrap">
    <div class="score-grid">{scores_html}</div>
    <p class="refresh-note">Scores sourced from latest Readiness-Report.json · page auto-refreshes every 60 s</p>
  </div>

  <!-- ── Node Inventory ── -->
  <h2>Node Inventory</h2>
  <div class="section-wrap">
    <div class="stat-row">
      <div class="stat"><div class="stat-val">{len(nodes)}</div><div class="stat-label">Nodes</div></div>
      <div class="stat"><div class="stat-val">{sum(1 for n in nodes if n.get("status")=="running")}</div><div class="stat-label">Running</div></div>
      <div class="stat"><div class="stat-val">{sum(len(n.get("vmids",[])) for n in nodes)}</div><div class="stat-label">Total VMIDs</div></div>
    </div>
    <div class="node-grid">{nodes_html}</div>
  </div>

  <!-- ── Provisioning Nodes (Phase 1.Q) ── -->
  <h2 id="prov-nodes">Provisioning Nodes</h2>
  <div class="section-wrap" id="prov-nodes-section">
    <div class="stat-row">
      <div class="stat"><div class="stat-val">{_prov_all_count}</div><div class="stat-label">Total planned</div></div>
      <div class="stat"><div class="stat-val" style="color:var(--green)">{_prov_active}</div><div class="stat-label">Active</div></div>
      <div class="stat"><div class="stat-val" style="color:var(--yellow)">{len(_prov_pending)}</div><div class="stat-label">Pending approval</div></div>
      <div class="stat"><div class="stat-val">{_prov_planned}</div><div class="stat-label">Planned/ISO</div></div>
      <div class="stat"><div class="stat-val" style="color:var(--red)">{_prov_blacklisted}</div><div class="stat-label">Blacklisted</div></div>
    </div>
    {prov_nodes_panel_html}
  </div>

  <!-- ── Failure Packages ── -->
  <h2>Failure Packages</h2>
  <div class="section-wrap">
    <div class="stat-row">
      <div class="stat"><div class="stat-val">{fail_count}</div><div class="stat-label">Total received</div></div>
      <div class="stat"><div class="stat-val" style="color:var(--yellow)">{fail_pending}</div><div class="stat-label">Pending analysis</div></div>
    </div>
    {'<div class="tip">Run <code>python3 proxmox-bootstrap/hatchery_receiver.py --analyze ' + cfg.failures_path + '</code> to analyze pending packages.</div>' if fail_pending > 0 else ''}
    <table>
      <tr><th>·</th><th>Package</th><th>Broodling</th><th>Error</th><th>Received</th><th>Status</th></tr>
      {fail_rows}
    </table>
  </div>

  <!-- ── Backup Status ── -->
  <h2>Backup Status</h2>
  <div class="section-wrap">
    <div class="stat-row">
      <div class="stat"><div class="stat-val">{len(bkp_dests)}</div><div class="stat-label">Destinations</div></div>
      <div class="stat"><div class="stat-val">{bkp_html}</div><div class="stat-label">Last run status</div></div>
      <div class="stat"><div class="stat-val" style="font-size:.9em;color:var(--muted)">{str(bkp_last)[:16] if bkp_last != "Never" else "Never"}</div><div class="stat-label">Last run at</div></div>
    </div>
    {'<div class="tip">No backup destinations configured. Run <code>python3 proxmox-bootstrap/setup-backup.py</code> to configure.</div>' if not bkp_dests else ''}
    {''.join(f'<div style="margin:3px 0;font-size:.85em"><span style="color:var(--muted)">{i+1}.</span> <code>{_e(d.get("provider","?"))}</code> · {_e(d.get("bucket") or d.get("path",""))}</div>' for i, d in enumerate(bkp_dests))}
  </div>

  <!-- ── CQB Backup & Restore ── -->
  <h2>CQB Backup &amp; Restore</h2>
  {_build_cqb_backup_panel(cqb_backups, cfg)}

  <!-- ── Security ── -->
  <h2>Security Posture</h2>
  <div class="section-wrap">
    <div class="stat-row">
      <div class="stat">
        <div class="stat-val" style="color:{sec_score_c}">{_e(sec_score)}</div>
        <div class="stat-label">Security score</div>
      </div>
      <div class="stat">
        <div class="stat-val" style="color:var(--red)">{_e(str(sec_red))}</div>
        <div class="stat-label">RED (leaks)</div>
      </div>
      <div class="stat">
        <div class="stat-val" style="color:var(--orange)">{_e(str(sec_orange))}</div>
        <div class="stat-label">ORANGE (unsafe)</div>
      </div>
      <div class="stat">
        <div class="stat-val" style="color:var(--yellow)">{_e(str(sec_yellow))}</div>
        <div class="stat-label">YELLOW (review)</div>
      </div>
      <div class="stat">
        <div class="stat-val" style="font-size:.85em;color:var(--muted)">{_e(sec_scanned)}</div>
        <div class="stat-label">Last scan</div>
      </div>
    </div>
    {'<div class="tip">No security scan has been run yet. Run: <code>python3 proxmox-bootstrap/security_analyzer.py --base-dir . --audit</code></div>' if not sec_has_scan else ''}
    {'<a class="nav-link" href="/api/security" target="_blank">🔍 Security JSON</a>' if sec_has_scan else ''}
  </div>

  <!-- ── Code Health ── -->
  <h2>Code Health</h2>
  {_build_code_health_card(code_health, dynamic_health)}

  <!-- ── Remediations ── -->
  <h2>Remediations</h2>
  <div class="section-wrap">
    <div class="stat-row">
      <div class="stat">
        <div class="stat-val">{len(rem_pending)}</div>
        <div class="stat-label">Pending approval</div>
      </div>
      <div class="stat">
        <div class="stat-val">{len(rem_approved)}</div>
        <div class="stat-label">Approved (ready)</div>
      </div>
      <div class="stat">
        <div class="stat-val">{auto_badge}</div>
        <div class="stat-label">Autonomous mode</div>
      </div>
      {'<div class="stat"><div class="stat-val" style="font-size:.85em;color:var(--muted)">' + auto_expires + '</div><div class="stat-label">Auto expires</div></div>' if auto_active and auto_expires else ''}
    </div>

    {'<div class="tip">Approve proposals via CLI: <code>python3 proxmox-bootstrap/remediation-cli.py approve-all --severity ORANGE</code></div>' if rem_pending else ''}

    <div id="rem-pending-list">
      {rem_pending_html}
    </div>

    {'<h2 style="margin-top:16px">Remediation History</h2>' if rem_recent else ''}
    {'<table><tr><th>Status</th><th>Severity</th><th>Action</th><th>Target</th><th>Time</th><th>Outcome</th></tr>' + rem_hist_rows + '</table>' if rem_recent else ''}
  </div>

  <p style="color:var(--muted);font-size:.78em;margin-top:16px;text-align:center">
    Broodforge Dashboard v{DASHBOARD_VERSION} · <a href="/api/state" style="color:var(--muted)">state</a> ·
    Binds <code>{_e(cfg.listen_host)}:{cfg.listen_port}</code>
  </p>

</div>

<script>
const _token = document.cookie.split(';').map(c=>c.trim()).find(c=>c.startsWith('bf-token='));
const _tok = _token ? _token.split('=')[1] : '';

function _post(url, body) {{
  return fetch(url, {{
    method: 'POST',
    headers: {{'Content-Type':'application/json','X-Broodforge-Token':_tok}},
    body: JSON.stringify(body),
  }});
}}

function approveProposal(pid, btn) {{
  if (!_tok) {{ alert('Set X-Broodforge-Token cookie to approve proposals.'); return; }}
  _post('/api/remediations/' + pid + '/approve', {{}})
    .then(r => {{ if (r.ok) {{ btn.closest('.rem-card').style.opacity='0.4'; btn.textContent='✓ Approved'; }} else {{ alert('Approve failed: ' + r.status); }} }});
}}

function rejectProposal(pid, btn) {{
  const reason = prompt('Rejection reason (optional):');
  if (reason === null) return;
  if (!_tok) {{ alert('Set X-Broodforge-Token cookie to reject proposals.'); return; }}
  _post('/api/remediations/' + pid + '/reject', {{reason}})
    .then(r => {{ if (r.ok) {{ btn.closest('.rem-card').style.opacity='0.4'; btn.textContent='✗ Rejected'; }} else {{ alert('Reject failed: ' + r.status); }} }});
}}

// ── CQB Backup & Restore ──────────────────────────────────────────────────

function cqbTriggerBackup(btn) {{
  const scope  = document.getElementById('cqb-scope').value;
  const dryRun = document.getElementById('cqb-dryrun').checked;
  const result = document.getElementById('cqb-backup-result');
  if (!_tok) {{ alert('Set X-Broodforge-Token cookie to trigger backups.'); return; }}
  btn.disabled = true;
  btn.textContent = 'Running…';
  result.textContent = '';
  _post('/api/cqb-backup', {{ scope, dry_run: dryRun }})
    .then(async r => {{
      const data = await r.json().catch(() => ({{}}));
      if (r.ok) {{
        result.style.color = 'var(--green)';
        result.textContent = '✓ ' + (dryRun ? '[dry-run] ' : '') + 'backup_id: ' + (data.backup_id || '?');
        setTimeout(() => location.reload(), 2000);
      }} else {{
        result.style.color = 'var(--red)';
        result.textContent = '✗ ' + (data.error || r.status);
      }}
      btn.disabled = false; btn.textContent = 'Run Backup';
    }})
    .catch(e => {{
      result.style.color = 'var(--red)';
      result.textContent = '✗ ' + e.message;
      btn.disabled = false; btn.textContent = 'Run Backup';
    }});
}}

function cqbRestorePrompt(backupId, btn) {{
  document.getElementById('cqb-restore-id').value = backupId;
  document.getElementById('cqb-restore-id').scrollIntoView({{ behavior: 'smooth' }});
}}

function cqbRestore(btn) {{
  const backupId = document.getElementById('cqb-restore-id').value.trim();
  const dryRun   = document.getElementById('cqb-restore-dryrun').checked;
  const result   = document.getElementById('cqb-restore-result');
  if (!backupId) {{ alert('Enter a backup ID first.'); return; }}
  if (!dryRun && !confirm('Restore from backup ' + backupId + '?\\n\\nThis will print the restore procedure. Confirm?')) return;
  if (!_tok) {{ alert('Set X-Broodforge-Token cookie to run restore.'); return; }}
  btn.disabled = true; btn.textContent = 'Restoring…';
  result.textContent = '';
  _post('/api/cqb-restore', {{ backup_id: backupId, dry_run: dryRun }})
    .then(async r => {{
      const data = await r.json().catch(() => ({{}}));
      if (r.ok) {{
        result.style.color = 'var(--green)';
        result.textContent = data.output || '✓ Restore procedure complete';
      }} else {{
        result.style.color = 'var(--red)';
        result.textContent = '✗ ' + (data.error || r.status);
      }}
      btn.disabled = false; btn.textContent = 'Restore';
    }})
    .catch(e => {{
      result.style.color = 'var(--red)';
      result.textContent = '✗ ' + e.message;
      btn.disabled = false; btn.textContent = 'Restore';
    }});
}}

// ── Phase 1.Q — Provisioning Nodes ───────────────────────────────────────

let _provCurrentCodename = null;

function filterProvNodes(query) {{
  const stateFilter = (document.getElementById('prov-state-filter') || {{}}).value || '';
  const q = (query || '').toLowerCase().trim();
  document.querySelectorAll('#prov-table .prov-row').forEach(row => {{
    const cn    = (row.dataset.codename || '').toLowerCase();
    const state = (row.dataset.state || '').toLowerCase();
    const text  = row.textContent.toLowerCase();
    const matchQ = !q || cn.includes(q) || text.includes(q);
    const matchS = !stateFilter || state === stateFilter;
    row.style.display = (matchQ && matchS) ? '' : 'none';
  }});
}}

function provApprove(codename, btn) {{
  if (!_tok) {{ alert('Action token required.'); return; }}
  if (!confirm('Approve node "' + codename + '"?\\n\\nVerify the codename AND PIN match your ISO manifest before approving.')) return;
  const msg = document.getElementById('prov-approve-msg');
  btn.disabled = true;
  _post('/api/provisioning-nodes/' + codename + '/approve', {{}})
    .then(async r => {{
      const d = await r.json().catch(() => ({{}}));
      if (r.ok && d.approved) {{
        msg.style.color = 'var(--green)';
        msg.textContent = '✓ ' + codename + ' approved — activating…';
        setTimeout(() => location.reload(), 1500);
      }} else {{
        msg.style.color = 'var(--red)';
        msg.textContent = '✗ ' + (d.error || r.status);
        btn.disabled = false;
      }}
    }}).catch(e => {{ msg.style.color='var(--red)'; msg.textContent='✗ '+e.message; btn.disabled=false; }});
}}

function provBlacklist(codename, btn) {{
  if (!_tok) {{ alert('Action token required.'); return; }}
  const reason = prompt('Reason for blacklisting "' + codename + '"?', 'Rejected via dashboard');
  if (!reason) return;
  const msg = document.getElementById('prov-approve-msg');
  btn.disabled = true;
  _post('/api/provisioning-nodes/' + codename + '/blacklist', {{ reason }})
    .then(async r => {{
      const d = await r.json().catch(() => ({{}}));
      if (r.ok) {{
        msg.style.color = 'var(--yellow)';
        msg.textContent = '⛔ ' + codename + ' blacklisted.';
        setTimeout(() => location.reload(), 1500);
      }} else {{
        msg.style.color = 'var(--red)';
        msg.textContent = '✗ ' + (d.error || r.status);
        btn.disabled = false;
      }}
    }}).catch(e => {{ msg.style.color='var(--red)'; msg.textContent='✗ '+e.message; btn.disabled=false; }});
}}

function provUnblacklist(codename, btn) {{
  if (!_tok) {{ alert('Action token required.'); return; }}
  if (!confirm('Un-blacklist "' + codename + '"? Node will return to iso-built state.')) return;
  btn.disabled = true;
  _post('/api/provisioning-nodes/' + codename + '/unblacklist', {{}})
    .then(async r => {{
      const d = await r.json().catch(() => ({{}}));
      if (r.ok) {{ setTimeout(() => location.reload(), 1000); }}
      else {{ btn.disabled=false; alert(d.error || r.status); }}
    }}).catch(e => {{ btn.disabled=false; alert(e.message); }});
}}

function showNodeDetail(codename) {{
  _provCurrentCodename = codename;
  fetch('/api/provisioning-nodes/' + codename)
    .then(r => r.json())
    .then(n => {{
      document.getElementById('detail-codename').textContent       = codename;
      document.getElementById('detail-ro-codename').textContent    = n.codename || codename;
      document.getElementById('detail-ro-state').innerHTML         = '{{}}'.replace('{{}}', n.state || '');
      document.getElementById('detail-ro-hsid').textContent        = n.headscale_node_id || '—';
      document.getElementById('detail-ro-fp').textContent          = n.broodling_public_key_fingerprint || '—';
      document.getElementById('detail-ro-approved').textContent    = (n.approved_at || '—').slice(0,16);
      document.getElementById('detail-display-name').value         = n.display_name || '';
      document.getElementById('detail-notes').value                = n.notes || '';
      document.getElementById('detail-role').value                 = n.role || 'worker';
      document.getElementById('detail-hs-name').value              = n.headscale_device_name || '';
      document.getElementById('detail-address').value              = n.assigned_address || '';
      document.getElementById('detail-decom-confirm').value        = '';
      document.getElementById('detail-save-msg').textContent       = '';
      document.getElementById('detail-action-msg').textContent     = '';
      document.getElementById('detail-decom-msg').textContent      = '';
      document.getElementById('prov-detail-panel').style.display   = 'block';
      document.getElementById('prov-detail-panel').scrollIntoView({{ behavior: 'smooth' }});
    }}).catch(e => alert('Could not load node: ' + e.message));
}}

function closeNodeDetail() {{
  document.getElementById('prov-detail-panel').style.display = 'none';
  _provCurrentCodename = null;
}}

function saveNodeFields() {{
  if (!_tok) {{ alert('Action token required.'); return; }}
  if (!_provCurrentCodename) return;
  const msg = document.getElementById('detail-save-msg');
  const payload = {{
    display_name: document.getElementById('detail-display-name').value,
    notes:        document.getElementById('detail-notes').value,
    role:         document.getElementById('detail-role').value,
  }};
  msg.style.color = 'var(--muted)'; msg.textContent = 'Saving…';
  _post('/api/provisioning-nodes/' + _provCurrentCodename, payload)
    .then(async r => {{
      const d = await r.json().catch(() => ({{}}));
      if (r.ok) {{ msg.style.color='var(--green)'; msg.textContent='✓ Saved'; }}
      else {{ msg.style.color='var(--red)'; msg.textContent='✗ '+(d.error||r.status); }}
    }}).catch(e => {{ msg.style.color='var(--red)'; msg.textContent='✗ '+e.message; }});
}}

function renameHeadscale() {{
  if (!_tok) {{ alert('Action token required.'); return; }}
  if (!_provCurrentCodename) return;
  const newName = document.getElementById('detail-hs-name').value.trim();
  if (!newName) {{ alert('Enter a new Headscale device name.'); return; }}
  const msg = document.getElementById('detail-action-msg');
  msg.style.color='var(--muted)'; msg.textContent='Renaming…';
  _post('/api/provisioning-nodes/'+_provCurrentCodename+'/rename-headscale', {{new_name: newName}})
    .then(async r => {{
      const d = await r.json().catch(()=>({{}}));
      if (r.ok) {{ msg.style.color='var(--green)'; msg.textContent='✓ Renamed to '+newName; }}
      else {{ msg.style.color='var(--red)'; msg.textContent='✗ '+(d.error||r.status); }}
    }}).catch(e=>{{ msg.style.color='var(--red)'; msg.textContent='✗ '+e.message; }});
}}

function reassignAddress() {{
  if (!_tok) {{ alert('Action token required.'); return; }}
  if (!_provCurrentCodename) return;
  const address = document.getElementById('detail-address').value.trim();
  if (!address) {{ alert('Enter an IP address or CIDR.'); return; }}
  const msg = document.getElementById('detail-action-msg');
  msg.style.color='var(--muted)'; msg.textContent='Assigning…';
  _post('/api/provisioning-nodes/'+_provCurrentCodename+'/reassign-address', {{assigned_address: address}})
    .then(async r => {{
      const d = await r.json().catch(()=>({{}}));
      if (r.ok) {{ msg.style.color='var(--green)'; msg.textContent='✓ Address set to '+address; }}
      else {{ msg.style.color='var(--red)'; msg.textContent='✗ '+(d.error||r.status); }}
    }}).catch(e=>{{ msg.style.color='var(--red)'; msg.textContent='✗ '+e.message; }});
}}

function setDeadline() {{
  if (!_tok) {{ alert('Action token required.'); return; }}
  if (!_provCurrentCodename) return;
  const val = document.getElementById('detail-deadline').value;
  if (!val) {{ alert('Select a deadline datetime.'); return; }}
  const iso = new Date(val).toISOString();
  const msg = document.getElementById('detail-action-msg');
  msg.style.color='var(--muted)'; msg.textContent='Setting deadline…';
  _post('/api/provisioning-nodes/'+_provCurrentCodename+'/set-deadline', {{deadline: iso}})
    .then(async r => {{
      const d = await r.json().catch(()=>({{}}));
      if (r.ok) {{ msg.style.color='var(--green)'; msg.textContent='✓ Deadline set to '+val; }}
      else {{ msg.style.color='var(--red)'; msg.textContent='✗ '+(d.error||r.status); }}
    }}).catch(e=>{{ msg.style.color='var(--red)'; msg.textContent='✗ '+e.message; }});
}}

function clearDeadline() {{
  if (!_tok) {{ alert('Action token required.'); return; }}
  if (!_provCurrentCodename) return;
  const msg = document.getElementById('detail-action-msg');
  msg.style.color='var(--muted)'; msg.textContent='Clearing deadline…';
  _post('/api/provisioning-nodes/'+_provCurrentCodename+'/set-deadline', {{deadline: null}})
    .then(async r => {{
      const d = await r.json().catch(()=>({{}}));
      if (r.ok) {{ msg.style.color='var(--green)'; msg.textContent='✓ Deadline cleared (permissive)'; }}
      else {{ msg.style.color='var(--red)'; msg.textContent='✗ '+(d.error||r.status); }}
    }}).catch(e=>{{ msg.style.color='var(--red)'; msg.textContent='✗ '+e.message; }});
}}

function decommissionNode() {{
  if (!_tok) {{ alert('Action token required.'); return; }}
  if (!_provCurrentCodename) return;
  const confirm_name = document.getElementById('detail-decom-confirm').value.trim();
  const msg = document.getElementById('detail-decom-msg');
  if (confirm_name !== _provCurrentCodename) {{
    msg.style.color='var(--red)';
    msg.textContent = 'Codename mismatch. Type exactly: ' + _provCurrentCodename;
    return;
  }}
  if (!confirm('FINAL CONFIRM: Decommission "' + _provCurrentCodename + '"?\\n\\nThis removes the Headscale device. The record is retained for audit.')) return;
  msg.style.color='var(--muted)'; msg.textContent='Decommissioning…';
  _post('/api/provisioning-nodes/'+_provCurrentCodename+'/decommission', {{confirm_codename: confirm_name}})
    .then(async r => {{
      const d = await r.json().catch(()=>({{}}));
      if (r.ok) {{
        msg.style.color='var(--green)';
        msg.textContent='✓ Decommissioned.';
        setTimeout(()=>location.reload(), 1500);
      }} else {{
        msg.style.color='var(--red)';
        msg.textContent='✗ '+(d.error||r.status);
      }}
    }}).catch(e=>{{ msg.style.color='var(--red)'; msg.textContent='✗ '+e.message; }});
}}
</script>

</body>
</html>"""


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class _DashboardHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler for the Broodforge dashboard."""

    _cfg: DashboardConfig = DashboardConfig()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path   = parsed.path.rstrip("/") or "/"

        if path == "/":
            self._serve_dashboard()
        elif path == "/api/state":
            self._serve_json(_redact_secrets(_read_bootstrap_state(self._cfg)))
        elif path == "/api/nodes":
            state = _read_bootstrap_state(self._cfg)
            self._serve_json(_redact_secrets(_nodes_from_state(state)))
        elif path == "/api/readiness":
            self._serve_json(_read_readiness(self._cfg))
        elif path == "/api/failures":
            self._serve_json(_read_failure_packages(self._cfg))
        elif path == "/api/backup-status":
            state = _read_bootstrap_state(self._cfg)
            self._serve_json(_backup_status_from_state(state))
        elif path == "/api/cqb-backups":
            state_dir = os.path.dirname(os.path.abspath(self._cfg.state_path))
            self._serve_json(_cqb_backup_list(state_dir))
        elif path == "/api/security":
            state = _read_bootstrap_state(self._cfg)
            self._serve_json(_redact_secrets(state.get("security_scan") or {}))
        elif path == "/api/remediations":
            state = _read_bootstrap_state(self._cfg)
            self._serve_json(_redact_secrets(state.get("remediations") or []))
        elif path.startswith("/api/remediations/") and not path.endswith(("/approve", "/reject")):
            pid   = path[len("/api/remediations/"):]
            state = _read_bootstrap_state(self._cfg)
            props = state.get("remediations") or []
            match = next((p for p in props if p.get("proposal_id") == pid), None)
            if match:
                self._serve_json(_redact_secrets(match))
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        elif path == "/api/provisioning-nodes":
            prov_state = _read_provisioning_state(self._cfg)
            # Mask join_pin and headscale key from list response (show only to operator via UI)
            nodes_safe = []
            for n in prov_state.get("nodes", []):
                nc = dict(n)
                nc.pop("broodling_public_key_pem", None)
                nodes_safe.append(nc)
            self._serve_json(nodes_safe)
        elif path.startswith("/api/provisioning-nodes/"):
            self._handle_get_provisioning_node(path)
        elif path.startswith("/docs/"):
            self._serve_doc_file(path[6:])
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path   = parsed.path

        if path == "/api/analyze-failures":
            if not self._check_action_token():
                return
            try:
                from failure_package_analyzer import analyze_all_unanalyzed
                results = analyze_all_unanalyzed(self._cfg.failures_path)
                self._serve_json({"analyzed": len(results)})
            except Exception as e:
                print(f"[dashboard] ERROR analyzing failures: {e}", file=sys.stderr)
                self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Internal server error")
        elif path == "/api/cqb-backup":
            if not self._check_action_token():
                return
            self._handle_cqb_backup()
        elif path == "/api/cqb-restore":
            if not self._check_action_token():
                return
            self._handle_cqb_restore()
        elif path.startswith("/api/remediations/") and path.endswith("/approve"):
            if not self._check_action_token():
                return
            self._handle_remediation_approve(path)
        elif path.startswith("/api/remediations/") and path.endswith("/reject"):
            if not self._check_action_token():
                return
            self._handle_remediation_reject(path)
        elif path == "/api/remediations/approve-batch":
            if not self._check_action_token():
                return
            self._handle_remediation_approve_batch()
        # ---------------------------------------------------------------------------
        # Phase 1.Q — Provisioning node endpoints
        # ---------------------------------------------------------------------------
        elif path == "/api/node-register":
            # No token required — broodling doesn't have one; payload is encrypted
            self._handle_node_register()
        elif path.startswith("/api/provisioning-nodes/") and path.endswith("/approve"):
            if not self._check_action_token():
                return
            self._handle_prov_node_approve(path)
        elif path.startswith("/api/provisioning-nodes/") and path.endswith("/blacklist"):
            if not self._check_action_token():
                return
            self._handle_prov_node_blacklist(path)
        elif path.startswith("/api/provisioning-nodes/") and path.endswith("/unblacklist"):
            if not self._check_action_token():
                return
            self._handle_prov_node_unblacklist(path)
        elif path.startswith("/api/provisioning-nodes/") and path.endswith("/decommission"):
            if not self._check_action_token():
                return
            self._handle_prov_node_decommission(path)
        elif path.startswith("/api/provisioning-nodes/") and path.endswith("/rename-headscale"):
            if not self._check_action_token():
                return
            self._handle_prov_node_rename_headscale(path)
        elif path.startswith("/api/provisioning-nodes/") and path.endswith("/reassign-address"):
            if not self._check_action_token():
                return
            self._handle_prov_node_reassign_address(path)
        elif path.startswith("/api/provisioning-nodes/") and path.endswith("/set-deadline"):
            if not self._check_action_token():
                return
            self._handle_prov_node_set_deadline(path)
        elif re.match(r"^/api/provisioning-nodes/[^/]+$", path):
            # PATCH handled elsewhere; POST to bare codename path is not defined
            if not self._check_action_token():
                return
            self._handle_prov_node_update(path)
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_PATCH(self) -> None:  # noqa: N802
        """PATCH /api/provisioning-nodes/<codename> — update editable fields."""
        parsed = urlparse(self.path)
        path   = parsed.path
        if re.match(r"^/api/provisioning-nodes/[^/]+$", path):
            if not self._check_action_token():
                return
            self._handle_prov_node_update(path)
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    # ------------------------------------------------------------------
    # Phase 1.Q — provisioning node handler methods
    # ------------------------------------------------------------------

    def _handle_get_provisioning_node(self, path: str) -> None:
        """GET /api/provisioning-nodes/<codename>[/<action>] — fetch single node."""
        # Strip trailing /action segments to get codename
        parts = path[len("/api/provisioning-nodes/"):].split("/")
        codename = parts[0]
        if not codename:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        planner = _get_node_planner(self._cfg)
        if planner is None:
            self._serve_json({"error": "node_planner module not available"})
            return
        node = planner.get_node(codename)
        if node is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        # Mask raw PEM (keep fingerprint)
        node.pop("broodling_public_key_pem", None)
        self._serve_json(node)

    def _handle_node_register(self) -> None:
        """
        POST /api/node-register — broodling registers with hatchery.

        Expected payload (optionally RSA-encrypted with hatchery public key):
          {
            "codename":       "swift-falcon",
            "join_pin":       "1234-5678-9012-3456",
            "public_key_pem": "<base64-encoded PEM>"
          }

        Or encrypted:
          {
            "encrypted": true,
            "key":       "<base64 RSA-OAEP encrypted AES key:IV>",
            "payload":   "<base64 AES-CBC ciphertext of JSON above>"
          }
        """
        body = self._read_post_body()

        # Decrypt if payload is encrypted
        if body.get("encrypted"):
            hatchery_priv_path = "/etc/broodforge/hatchery-private.pem"
            try:
                import base64
                import subprocess as _sp
                enc_key_b64     = body["key"]
                enc_payload_b64 = body["payload"]
                enc_key_bytes   = base64.b64decode(enc_key_b64)
                enc_payload_bytes = base64.b64decode(enc_payload_b64)
                # Decrypt AES key with RSA private key
                dec_result = _sp.run(
                    ["openssl", "pkeyutl", "-decrypt",
                     "-inkey", hatchery_priv_path,
                     "-pkeyopt", "rsa_padding_mode:oaep"],
                    input=enc_key_bytes,
                    capture_output=True,
                    timeout=60,
                )
                if dec_result.returncode != 0:
                    print(
                        f"[dashboard] node-register: RSA decrypt failed: "
                        f"{dec_result.stderr.decode()[:200]}",
                        file=sys.stderr,
                    )
                    self.send_error(HTTPStatus.BAD_REQUEST, "Decryption failed")
                    return
                aes_key_iv = dec_result.stdout.decode().strip()
                if ":" not in aes_key_iv:
                    self.send_error(HTTPStatus.BAD_REQUEST, "Malformed encrypted payload")
                    return
                aes_key, aes_iv = aes_key_iv.split(":", 1)
                dec_payload = _sp.run(
                    ["openssl", "enc", "-d", "-aes-256-cbc",
                     "-K", aes_key, "-iv", aes_iv],
                    input=enc_payload_bytes,
                    capture_output=True,
                    timeout=60,
                )
                if dec_payload.returncode != 0:
                    self.send_error(HTTPStatus.BAD_REQUEST, "Payload decryption failed")
                    return
                body = json.loads(dec_payload.stdout)
            except Exception as exc:
                print(f"[dashboard] node-register: decrypt error: {exc}", file=sys.stderr)
                self.send_error(HTTPStatus.BAD_REQUEST, "Encrypted payload error")
                return

        codename = (body.get("codename") or "").strip()
        join_pin = (body.get("join_pin") or "").strip()
        pub_key_b64 = (body.get("public_key_pem") or "").strip()

        if not codename or not join_pin or not pub_key_b64:
            self._serve_json({
                "error": "Missing required fields: codename, join_pin, public_key_pem"
            })
            return

        import base64 as _b64
        try:
            public_key_pem = _b64.b64decode(pub_key_b64).decode("utf-8")
        except Exception:
            public_key_pem = pub_key_b64  # assume already PEM string

        planner = _get_node_planner(self._cfg)
        if planner is None:
            self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, "node_planner module not available")
            return

        try:
            planner.store_broodling_registration(
                codename       = codename,
                public_key_pem = public_key_pem,
                join_pin       = join_pin,
            )
            print(
                f"[dashboard] Node '{codename}' registered — pending-approval.",
                file=sys.stderr,
            )
            self._serve_json({"status": "pending-approval", "codename": codename})
        except KeyError as exc:
            print(f"[dashboard] node-register: unknown codename: {exc}", file=sys.stderr)
            self.send_error(HTTPStatus.NOT_FOUND, str(exc))
        except ValueError as exc:
            err = str(exc)
            print(f"[dashboard] node-register: rejected: {err}", file=sys.stderr)
            self._serve_json({"error": err})
        except Exception as exc:
            print(f"[dashboard] node-register: ERROR: {exc}", file=sys.stderr)
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Registration error")

    def _prov_codename_from_path(self, path: str, suffix: str = "") -> str:
        """Extract codename from /api/provisioning-nodes/<codename>[/<suffix>]."""
        base = path[len("/api/provisioning-nodes/"):]
        if suffix and base.endswith("/" + suffix):
            base = base[: -(len(suffix) + 1)]
        return base.strip("/")

    def _handle_prov_node_approve(self, path: str) -> None:
        """POST /api/provisioning-nodes/<codename>/approve"""
        codename = self._prov_codename_from_path(path, "approve")
        planner  = _get_node_planner(self._cfg)
        if planner is None:
            self.send_error(HTTPStatus.SERVICE_UNAVAILABLE)
            return
        try:
            planner.approve(codename)
            self._serve_json({"approved": codename})
        except (KeyError, ValueError) as exc:
            self._serve_json({"error": str(exc)})
        except Exception as exc:
            print(f"[dashboard] prov approve error: {exc}", file=sys.stderr)
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_prov_node_blacklist(self, path: str) -> None:
        """POST /api/provisioning-nodes/<codename>/blacklist"""
        codename = self._prov_codename_from_path(path, "blacklist")
        body     = self._read_post_body()
        reason   = body.get("reason", "Blacklisted via dashboard")
        planner  = _get_node_planner(self._cfg)
        if planner is None:
            self.send_error(HTTPStatus.SERVICE_UNAVAILABLE)
            return
        try:
            planner.blacklist(codename, reason=reason)
            self._serve_json({"blacklisted": codename})
        except (KeyError, ValueError) as exc:
            self._serve_json({"error": str(exc)})
        except Exception as exc:
            print(f"[dashboard] prov blacklist error: {exc}", file=sys.stderr)
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_prov_node_unblacklist(self, path: str) -> None:
        """POST /api/provisioning-nodes/<codename>/unblacklist"""
        codename = self._prov_codename_from_path(path, "unblacklist")
        planner  = _get_node_planner(self._cfg)
        if planner is None:
            self.send_error(HTTPStatus.SERVICE_UNAVAILABLE)
            return
        try:
            planner.unblacklist(codename)
            self._serve_json({"unblacklisted": codename})
        except (KeyError, ValueError) as exc:
            self._serve_json({"error": str(exc)})
        except Exception as exc:
            print(f"[dashboard] prov unblacklist error: {exc}", file=sys.stderr)
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_prov_node_decommission(self, path: str) -> None:
        """POST /api/provisioning-nodes/<codename>/decommission"""
        codename = self._prov_codename_from_path(path, "decommission")
        body     = self._read_post_body()
        confirm  = body.get("confirm_codename", "").strip()
        if confirm != codename:
            self._serve_json({
                "error": f"Codename confirmation mismatch. "
                         f"Expected '{codename}', got '{confirm}'."
            })
            return
        planner = _get_node_planner(self._cfg)
        if planner is None:
            self.send_error(HTTPStatus.SERVICE_UNAVAILABLE)
            return
        try:
            planner.decommission(codename)
            self._serve_json({"decommissioned": codename})
        except (KeyError, ValueError) as exc:
            self._serve_json({"error": str(exc)})
        except Exception as exc:
            print(f"[dashboard] prov decommission error: {exc}", file=sys.stderr)
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_prov_node_rename_headscale(self, path: str) -> None:
        """POST /api/provisioning-nodes/<codename>/rename-headscale"""
        codename = self._prov_codename_from_path(path, "rename-headscale")
        body     = self._read_post_body()
        new_name = body.get("new_name", "").strip()
        if not new_name:
            self._serve_json({"error": "new_name is required"})
            return
        planner = _get_node_planner(self._cfg)
        if planner is None:
            self.send_error(HTTPStatus.SERVICE_UNAVAILABLE)
            return
        try:
            planner.rename_headscale(codename, new_name)
            self._serve_json({"renamed": codename, "new_name": new_name})
        except (KeyError, ValueError, RuntimeError) as exc:
            self._serve_json({"error": str(exc)})
        except Exception as exc:
            print(f"[dashboard] prov rename-headscale error: {exc}", file=sys.stderr)
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_prov_node_reassign_address(self, path: str) -> None:
        """POST /api/provisioning-nodes/<codename>/reassign-address"""
        codename = self._prov_codename_from_path(path, "reassign-address")
        body     = self._read_post_body()
        address  = body.get("assigned_address", "").strip()
        if not address:
            self._serve_json({"error": "assigned_address is required"})
            return
        planner = _get_node_planner(self._cfg)
        if planner is None:
            self.send_error(HTTPStatus.SERVICE_UNAVAILABLE)
            return
        try:
            planner.update_state(codename, assigned_address=address)
            self._serve_json({"codename": codename, "assigned_address": address})
        except (KeyError, ValueError) as exc:
            self._serve_json({"error": str(exc)})
        except Exception as exc:
            print(f"[dashboard] prov reassign-address error: {exc}", file=sys.stderr)
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_prov_node_set_deadline(self, path: str) -> None:
        """POST /api/provisioning-nodes/<codename>/set-deadline"""
        codename = self._prov_codename_from_path(path, "set-deadline")
        body     = self._read_post_body()
        deadline = body.get("deadline")  # None = clear deadline
        planner  = _get_node_planner(self._cfg)
        if planner is None:
            self.send_error(HTTPStatus.SERVICE_UNAVAILABLE)
            return
        try:
            planner.set_join_deadline(codename, deadline)
            self._serve_json({"codename": codename, "join_deadline": deadline})
        except (KeyError, ValueError) as exc:
            self._serve_json({"error": str(exc)})
        except Exception as exc:
            print(f"[dashboard] prov set-deadline error: {exc}", file=sys.stderr)
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_prov_node_update(self, path: str) -> None:
        """PATCH/POST /api/provisioning-nodes/<codename> — update editable fields."""
        codename = self._prov_codename_from_path(path)
        body     = self._read_post_body()
        # Only allow editable operator fields
        allowed  = {"display_name", "notes", "role"}
        updates  = {k: v for k, v in body.items() if k in allowed}
        if not updates:
            self._serve_json({"error": "No editable fields provided. Allowed: display_name, notes, role"})
            return
        if "role" in updates and updates["role"] not in (_NP_VALID_ROLES if _HAS_NODE_PLANNER else set()):
            self._serve_json({"error": f"Invalid role. Valid roles: {sorted(_NP_VALID_ROLES)}"})
            return
        planner = _get_node_planner(self._cfg)
        if planner is None:
            self.send_error(HTTPStatus.SERVICE_UNAVAILABLE)
            return
        try:
            planner.update_state(codename, **updates)
            node = planner.get_node(codename)
            if node:
                node.pop("broodling_public_key_pem", None)
            self._serve_json({"updated": codename, "fields": list(updates.keys()), "node": node})
        except (KeyError, ValueError) as exc:
            self._serve_json({"error": str(exc)})
        except Exception as exc:
            print(f"[dashboard] prov update error: {exc}", file=sys.stderr)
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_cqb_backup(self) -> None:
        """POST /api/cqb-backup — trigger a CQB backup."""
        if not _HAS_BACKUP_MANAGER:
            self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, "backup_manager module not available")
            return
        body = self._read_post_body()
        scope_str = body.get("scope", "broodforge")
        dry_run   = bool(body.get("dry_run", False))

        # Refuse level-2+ scopes from dashboard — KeePass gate not available here
        _scope_lower = str(scope_str).lower()
        if any(_scope_lower.startswith(p) for p in ("full", "vm:", "node:")):
            self._serve_json({
                "error": (
                    f"Scope '{scope_str}' requires quiesce_level >= 2 and an operator KeePass gate. "
                    "Use forge-backup.sh from the command line instead."
                )
            })
            return

        state_dir = os.path.dirname(os.path.abspath(self._cfg.state_path))
        try:
            scope    = _parse_scope_arg(scope_str)
            manager  = BackupManager(state_dir=state_dir)
            manifest = manager.backup(scope=scope, trigger="operator", dry_run=dry_run)
            self._serve_json({
                "backup_id":    manifest.backup_id,
                "scope":        manifest.scope,
                "completed_at": manifest.completed_at,
                "dry_run":      dry_run,
            })
        except Exception as exc:
            print(f"[dashboard] ERROR in cqb-backup: {exc}", file=sys.stderr)
            self._serve_json({"error": str(exc)})

    def _handle_cqb_restore(self) -> None:
        """POST /api/cqb-restore — print restore procedure for a backup."""
        if not _HAS_BACKUP_MANAGER:
            self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, "backup_manager module not available")
            return
        body      = self._read_post_body()
        backup_id = body.get("backup_id", "").strip()
        dry_run   = bool(body.get("dry_run", True))  # dashboard always defaults to dry-run

        if not backup_id:
            self._serve_json({"error": "backup_id is required"})
            return

        state_dir = os.path.dirname(os.path.abspath(self._cfg.state_path))
        import io, contextlib
        buf = io.StringIO()
        try:
            manager = BackupManager(state_dir=state_dir)
            with contextlib.redirect_stdout(buf):
                manager.restore(backup_id=backup_id, dry_run=dry_run)
            self._serve_json({"output": buf.getvalue(), "backup_id": backup_id, "dry_run": dry_run})
        except FileNotFoundError as exc:
            self._serve_json({"error": str(exc)})
        except Exception as exc:
            print(f"[dashboard] ERROR in cqb-restore: {exc}", file=sys.stderr)
            self._serve_json({"error": str(exc)})

    def _read_post_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        if length > 1 * 1024 * 1024:  # 1 MB cap — dashboard actions are small JSON
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except Exception:
            return {}

    def _handle_remediation_approve(self, path: str) -> None:
        pid   = path[len("/api/remediations/"):-len("/approve")]
        body  = self._read_post_body()
        state = _read_bootstrap_state(self._cfg)
        try:
            queue = load_queue(state)
            ok    = approve_proposal(queue, pid, "dashboard", "dashboard",
                                     note=body.get("note"))
            if ok:
                updated = save_queue(queue, state)
                with open(self._cfg.state_path, "w") as f:
                    json.dump(updated, f, indent=2)
                self._serve_json({"approved": pid})
            else:
                self.send_error(HTTPStatus.CONFLICT, "Cannot approve proposal in current state")
        except Exception as e:
            print(f"[dashboard] ERROR in approve: {e}", file=sys.stderr)
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Internal server error")

    def _handle_remediation_reject(self, path: str) -> None:
        pid   = path[len("/api/remediations/"):-len("/reject")]
        body  = self._read_post_body()
        state = _read_bootstrap_state(self._cfg)
        try:
            queue = load_queue(state)
            ok    = reject_proposal(queue, pid, reason=body.get("reason", "rejected via dashboard"),
                                    rejected_by="dashboard")
            if ok:
                updated = save_queue(queue, state)
                with open(self._cfg.state_path, "w") as f:
                    json.dump(updated, f, indent=2)
                self._serve_json({"rejected": pid})
            else:
                self.send_error(HTTPStatus.CONFLICT, "Cannot reject proposal in current state")
        except Exception as e:
            print(f"[dashboard] ERROR in reject: {e}", file=sys.stderr)
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Internal server error")

    _VALID_SEVERITIES = {"RED", "ORANGE", "YELLOW", "GREEN", "BLOCKED"}

    def _handle_remediation_approve_batch(self) -> None:
        body     = self._read_post_body()
        severity = body.get("max_severity", "YELLOW").upper()
        if severity not in self._VALID_SEVERITIES:
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid severity level")
            return
        state    = _read_bootstrap_state(self._cfg)
        try:
            queue   = load_queue(state)
            count   = batch_approve(queue, severity, "dashboard", "dashboard")
            updated = save_queue(queue, state)
            with open(self._cfg.state_path, "w") as f:
                json.dump(updated, f, indent=2)
            self._serve_json({"approved": count, "max_severity": severity})
        except Exception as e:
            print(f"[dashboard] ERROR in batch approve: {e}", file=sys.stderr)
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Internal server error")

    def _check_action_token(self) -> bool:
        """Verify X-Broodforge-Token header matches configured token."""
        token = self.headers.get("X-Broodforge-Token", "")
        expected = self._cfg.action_token
        if not expected:
            return True   # no token configured; allow (dev mode)
        if not secrets.compare_digest(token.encode(), expected.encode()):
            self.send_error(HTTPStatus.UNAUTHORIZED, "Invalid action token")
            return False
        return True

    def _serve_dashboard(self) -> None:
        state        = _read_bootstrap_state(self._cfg)
        readiness    = _read_readiness(self._cfg)
        nodes        = _nodes_from_state(state)
        failures     = _read_failure_packages(self._cfg)
        backup       = _backup_status_from_state(state)
        scores       = _scores_from_readiness(readiness)
        remediations = _remediations_from_state(state)
        security     = _security_from_state(state)
        # Derive repo root from the script location (one level up from proxmox-bootstrap/)
        _script_dir = os.path.dirname(os.path.abspath(__file__))
        _repo_root  = os.path.dirname(_script_dir)
        code_health     = _code_health_from_assessment(_repo_root)
        dynamic_health  = _dynamic_health_from_assessment(_repo_root)
        _state_dir      = os.path.dirname(os.path.abspath(self._cfg.state_path))
        cqb_backups     = _cqb_backup_list(_state_dir)
        prov_state      = _read_provisioning_state(self._cfg)
        prov_nodes      = prov_state.get("nodes", [])
        html            = generate_dashboard_html(
            state, scores, nodes, failures, backup, self._cfg,
            remediations=remediations, security=security,
            code_health=code_health, dynamic_health=dynamic_health,
            cqb_backups=cqb_backups,
            prov_nodes=prov_nodes,
        )
        body     = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._add_security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _serve_json(self, data: object) -> None:
        body = json.dumps(data, indent=2, default=str).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._add_security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _serve_doc_file(self, filename: str) -> None:
        """Serve an HTML file from the docs/ directory.

        Resolution order:
        1. Explicit docs_path from dashboard.json config (most reliable in production)
        2. docs/ adjacent to the dashboard script itself (covers the common deploy pattern
           where the whole repo is present at /opt/broodforge or similar)
        3. Walk up from bootstrap-state.json directory up to 5 levels (legacy fallback)
        """
        docs_dir: str = ""

        # 1. Explicit config path
        if self._cfg.docs_path and os.path.isdir(self._cfg.docs_path):
            docs_dir = self._cfg.docs_path

        # 2. Adjacent to this script file
        if not docs_dir:
            script_docs = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "..", "docs"
            )
            if os.path.isdir(script_docs):
                docs_dir = os.path.normpath(script_docs)

        # 3. Walk up from state file directory
        if not docs_dir:
            candidate = os.path.dirname(os.path.abspath(self._cfg.state_path))
            for _ in range(5):
                candidate_docs = os.path.join(candidate, "docs")
                if os.path.isdir(candidate_docs):
                    docs_dir = candidate_docs
                    break
                candidate = os.path.dirname(candidate)

        if not docs_dir:
            self.send_error(HTTPStatus.NOT_FOUND, "docs/ directory not found")
            return
        # Sanitise filename to prevent path traversal
        safe_name = os.path.basename(filename)
        if not safe_name.endswith(".html"):
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        full_path = os.path.join(docs_dir, safe_name)
        if not os.path.isfile(full_path):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        with open(full_path, "rb") as f:
            body = f.read()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._add_security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _add_security_headers(self) -> None:
        """Add security-hardening HTTP response headers to all responses."""
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:;",
        )

    def log_message(self, fmt: str, *args: object) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        print(f"[dashboard] {ts} {fmt % args}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Server runner
# ---------------------------------------------------------------------------

def run_server(cfg: DashboardConfig) -> None:
    """Start the dashboard HTTP server (blocks until interrupted)."""
    os.makedirs(cfg.failures_path, exist_ok=True)

    generated = cfg.ensure_token()
    if generated:
        print(f"[dashboard] Generated action token — stored in {cfg.config_path}", file=sys.stderr)

    class _Handler(_DashboardHandler):
        _cfg = cfg

    server = http.server.HTTPServer((cfg.listen_host, cfg.listen_port), _Handler)

    # Optional TLS
    if cfg.ssl_cert and cfg.ssl_key:
        if os.path.exists(cfg.ssl_cert) and os.path.exists(cfg.ssl_key):
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(cfg.ssl_cert, cfg.ssl_key)
            server.socket = ctx.wrap_socket(server.socket, server_side=True)
            proto = "https"
        else:
            print(f"[dashboard] WARNING: ssl_cert/ssl_key not found — running HTTP", file=sys.stderr)
            proto = "http"
    else:
        proto = "http"

    # WAN exposure warning: if network_profile is "wan" and listening on all interfaces
    if cfg.listen_host == "0.0.0.0":  # nosec B104 — string comparison, not a binding call
        state = _read_json(cfg.state_path) or {}
        nt = state.get("network_topology") or {}
        if nt.get("profile") == "wan":
            print(
                "\n"
                "[dashboard] WARNING: Dashboard is listening on 0.0.0.0 with network_profile=wan.\n"
                "[dashboard] WARNING: This exposes the dashboard to the WAN interface.\n"
                "[dashboard] WARNING: Restrict listen_host to 127.0.0.1 or a LAN IP unless\n"
                "[dashboard] WARNING: TLS and a strong action_token are configured.\n",
                file=sys.stderr,
            )

    print(
        f"[dashboard] Broodforge Dashboard v{DASHBOARD_VERSION}\n"
        f"[dashboard] {proto}://{cfg.listen_host}:{cfg.listen_port}/\n"
        f"[dashboard] State:    {cfg.state_path}\n"
        f"[dashboard] Reports:  {cfg.reports_path}\n"
        f"[dashboard] Failures: {cfg.failures_path}",
        file=sys.stderr,
    )
    if cfg.action_token:
        print(f"[dashboard] Action token set — POST endpoints require X-Broodforge-Token header",
              file=sys.stderr)
    else:
        print("[dashboard] WARNING: No auth token configured — all POST endpoints are unprotected",
              file=sys.stderr)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("[dashboard] Stopped.", file=sys.stderr)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Broodforge sidecar dashboard server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  # Start with default paths (hatchery production)\n"
            "  python3 broodforge_dashboard.py\n\n"
            "  # Development: point at local state file\n"
            "  python3 broodforge_dashboard.py --state ./proxmox-bootstrap/bootstrap-state.json \\\n"
            "    --failures /tmp/broodforge-failures --port 9322\n\n"
            "  # Install systemd service\n"
            "  python3 broodforge_dashboard.py --install-service\n"
        ),
    )
    ap.add_argument("--state",    default=DEFAULT_STATE,   help=f"Path to bootstrap-state.json (default: {DEFAULT_STATE})")
    ap.add_argument("--reports",  default=DEFAULT_REPORTS, help=f"Path to reports directory (default: {DEFAULT_REPORTS})")
    ap.add_argument("--failures", default=DEFAULT_FAILURES,help=f"Path to failure packages directory (default: {DEFAULT_FAILURES})")
    ap.add_argument("--config",   default=DEFAULT_CONFIG,  help=f"Path to dashboard config JSON (default: {DEFAULT_CONFIG})")
    ap.add_argument("--host",     default="0.0.0.0",       help="Listen address (default: 0.0.0.0)")  # nosec B104
    ap.add_argument("--port",     type=int, default=DEFAULT_PORT, help=f"Listen port (default: {DEFAULT_PORT})")
    ap.add_argument("--ssl-cert", default="",              help="Path to TLS fullchain PEM (optional; uses /etc/pve/local/pveproxy-ssl.pem if present)")
    ap.add_argument("--ssl-key",  default="",              help="Path to TLS private key PEM")
    ap.add_argument("--install-service", action="store_true", help="Print systemd service unit and exit")
    ap.add_argument("--show-token",      action="store_true", help="Show action token and exit")
    args = ap.parse_args()

    if args.install_service:
        print(SYSTEMD_SERVICE)
        print("# Install with:")
        print("# cp /dev/stdin /etc/systemd/system/broodforge-dashboard.service")
        print("# systemctl daemon-reload && systemctl enable --now broodforge-dashboard")
        sys.exit(0)

    cfg = DashboardConfig.load(args.config)
    cfg.state_path    = args.state
    cfg.reports_path  = args.reports
    cfg.failures_path = args.failures
    cfg.listen_host   = args.host
    cfg.listen_port   = args.port
    cfg.config_path   = args.config

    # Auto-detect Proxmox TLS cert if no cert specified and file exists
    if not args.ssl_cert:
        pve_cert = "/etc/pve/local/pveproxy-ssl.pem"
        pve_key  = "/etc/pve/local/pveproxy-ssl.key"
        if os.path.exists(pve_cert) and os.path.exists(pve_key):
            cfg.ssl_cert = pve_cert
            cfg.ssl_key  = pve_key
    else:
        cfg.ssl_cert = args.ssl_cert
        cfg.ssl_key  = args.ssl_key

    if args.show_token:
        cfg.ensure_token()
        print(f"Action token: {cfg.action_token}")
        sys.exit(0)

    run_server(cfg)
