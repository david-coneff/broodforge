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
    listen_host:   str = "0.0.0.0"
    listen_port:   int = DEFAULT_PORT
    action_token:  str = ""   # auto-generated on first start if empty
    ssl_cert:      str = ""   # path to PEM fullchain (optional)
    ssl_key:       str = ""   # path to PEM private key (optional)

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
        return cfg

    def save(self) -> None:
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
            }, f, indent=2)

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
    """Extract score dict from readiness report, tolerating various formats."""
    scores = readiness.get("scores") or readiness.get("summary") or {}
    # Fall back to top-level keys if "scores" not present
    for key in ("ACS", "RRS", "DCS", "CRS", "OSS", "PHS"):
        if key not in scores and key in readiness:
            scores[key] = readiness[key]
    return scores


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

    approve_btn = (
        f'<button class="btn-approve" '
        f'onclick="approveProposal(\'{_e(raw_pid)}\',this)">'
        f'Approve</button>'
    )
    reject_btn = (
        f'<button class="btn-reject" '
        f'onclick="rejectProposal(\'{_e(raw_pid)}\',this)">'
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
  <td><span style="color:{sc}">{status}</span></td>
  <td><span style="color:{sev_c}">{sev}</span></td>
  <td>{_e(p.get("action_type",""))}</td>
  <td><code>{_e(p.get("target",""))}</code></td>
  <td style="font-size:.82em;color:var(--muted)">{ts}</td>
  <td style="font-size:.82em">{outcome} <span style="color:var(--orange)">{resisted}</span></td>
</tr>"""


def generate_dashboard_html(
    state:    dict,
    scores:   dict,
    nodes:    list[dict],
    failures: list[dict],
    backup:   dict,
    cfg:      DashboardConfig,
    remediations: dict = None,
    security: dict = None,
) -> str:
    cell_id       = state.get("cell_id") or "broodforge"
    gen_at        = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    host_id       = state.get("host_identity") or {}
    hostname      = host_id.get("hostname") or host_id.get("fqdn") or cell_id
    remediations  = remediations or {}
    security      = security or {}

    scores_html = ""
    for abbr in ("PHS", "ACS", "RRS", "DCS", "CRS", "OSS"):
        if abbr in scores:
            lvl = scores[abbr] if isinstance(scores[abbr], str) else (scores[abbr] or {}).get("level", "—")
            scores_html += _score_badge(abbr, lvl)
    if not scores_html:
        scores_html = '<p style="color:var(--muted)">No readiness report found — run <code>engine.py --mode recovery</code> to generate one.</p>'

    nodes_html = "".join(_node_card(n) for n in nodes) if nodes else \
        '<p style="color:var(--muted)">No nodes found in bootstrap-state.json.</p>'

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
    bkp_html  = f'<span style="color:{bkp_color}">{bkp_status}</span>' if bkp_dests else \
        '<span style="color:var(--muted)">Not configured</span>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>Broodforge Dashboard — {cell_id}</title>
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
  <span class="topbar-cell">{cell_id} · {hostname}</span>
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

  <!-- ── Security ── -->
  <h2>Security Posture</h2>
  <div class="section-wrap">
    <div class="stat-row">
      <div class="stat">
        <div class="stat-val" style="color:{sec_score_c}">{sec_score}</div>
        <div class="stat-label">Security score</div>
      </div>
      <div class="stat">
        <div class="stat-val" style="color:var(--red)">{sec_red}</div>
        <div class="stat-label">RED (leaks)</div>
      </div>
      <div class="stat">
        <div class="stat-val" style="color:var(--orange)">{sec_orange}</div>
        <div class="stat-label">ORANGE (unsafe)</div>
      </div>
      <div class="stat">
        <div class="stat-val" style="color:var(--yellow)">{sec_yellow}</div>
        <div class="stat-label">YELLOW (review)</div>
      </div>
      <div class="stat">
        <div class="stat-val" style="font-size:.85em;color:var(--muted)">{sec_scanned}</div>
        <div class="stat-label">Last scan</div>
      </div>
    </div>
    {'<div class="tip">No security scan has been run yet. Run: <code>python3 proxmox-bootstrap/security_analyzer.py --base-dir . --audit</code></div>' if not sec_has_scan else ''}
    {'<a class="nav-link" href="/api/security" target="_blank">🔍 Security JSON</a>' if sec_has_scan else ''}
  </div>

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
    Binds <code>{cfg.listen_host}:{cfg.listen_port}</code>
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
            self._serve_json(_read_bootstrap_state(self._cfg))
        elif path == "/api/nodes":
            state = _read_bootstrap_state(self._cfg)
            self._serve_json(_nodes_from_state(state))
        elif path == "/api/readiness":
            self._serve_json(_read_readiness(self._cfg))
        elif path == "/api/failures":
            self._serve_json(_read_failure_packages(self._cfg))
        elif path == "/api/backup-status":
            state = _read_bootstrap_state(self._cfg)
            self._serve_json(_backup_status_from_state(state))
        elif path == "/api/security":
            state = _read_bootstrap_state(self._cfg)
            self._serve_json(state.get("security_scan") or {})
        elif path == "/api/remediations":
            state = _read_bootstrap_state(self._cfg)
            self._serve_json(state.get("remediations") or [])
        elif path.startswith("/api/remediations/") and not path.endswith(("/approve", "/reject")):
            pid   = path[len("/api/remediations/"):]
            state = _read_bootstrap_state(self._cfg)
            props = state.get("remediations") or []
            match = next((p for p in props if p.get("proposal_id") == pid), None)
            if match:
                self._serve_json(match)
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
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
                self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(e))
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
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

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
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(e))

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
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(e))

    def _handle_remediation_approve_batch(self) -> None:
        body     = self._read_post_body()
        severity = body.get("max_severity", "YELLOW").upper()
        state    = _read_bootstrap_state(self._cfg)
        try:
            queue   = load_queue(state)
            count   = batch_approve(queue, severity, "dashboard", "dashboard")
            updated = save_queue(queue, state)
            with open(self._cfg.state_path, "w") as f:
                json.dump(updated, f, indent=2)
            self._serve_json({"approved": count, "max_severity": severity})
        except Exception as e:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(e))

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
        html         = generate_dashboard_html(state, scores, nodes, failures, backup, self._cfg,
                                               remediations=remediations, security=security)
        body     = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_json(self, data: object) -> None:
        body = json.dumps(data, indent=2, default=str).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_doc_file(self, filename: str) -> None:
        """Serve an HTML file from the docs/ directory next to bootstrap-state.json."""
        state_dir = os.path.dirname(os.path.abspath(self._cfg.state_path))
        # Walk up to find the repo root (contains docs/ directory)
        candidate = state_dir
        for _ in range(5):
            docs_dir = os.path.join(candidate, "docs")
            if os.path.isdir(docs_dir):
                break
            candidate = os.path.dirname(candidate)
        else:
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
        self.end_headers()
        self.wfile.write(body)

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
    if cfg.listen_host == "0.0.0.0":
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
    ap.add_argument("--host",     default="0.0.0.0",       help="Listen address (default: 0.0.0.0)")
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
