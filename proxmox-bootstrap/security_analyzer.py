#!/usr/bin/env python3
"""
security_analyzer.py — Continuous security leak analyzer (new feature).

Scans logs, generated shell scripts, and bootstrap-state manifests for
security issues grouped by severity:

  RED    — plaintext secrets confirmed in files (must remediate immediately)
  ORANGE — unsafe patterns that could expose secrets (should remediate)
  YELLOW — suspicious patterns that warrant review (should investigate)

Scan targets:
  1. Log files (forge.log, spawn.log, *.log) — TOTP seeds, passphrases,
     tokens, k3s join tokens, SSH private keys, API keys
  2. Generated shell scripts (phase-*.sh, spawn.sh, forge.sh) — unsafe SSH
     options, passwords on command lines, secrets in env var exports
  3. bootstrap-state.json and manifests — fields that must never contain
     plaintext secret values

Modes:
  one-shot audit:     scan(paths, options) → SecurityReport
  continuous:         watch(paths, callback, stop_event) — tails log files as
                      they grow, emitting new findings in real time

HTML output:
  build_security_report_html(report) → str

Public API:
  SecurityFinding     — a single finding dataclass
  SecurityReport      — aggregated set of findings with metadata
  scan_logs(paths)    → list[SecurityFinding]
  scan_scripts(paths) → list[SecurityFinding]
  scan_manifest(state) → list[SecurityFinding]
  scan(base_dir, state) → SecurityReport
  build_security_report_html(report) → str
  SECURITY_POSTURE_SCORE(report) → str   (GREEN/YELLOW/ORANGE/RED)

Stdlib only.
Usage (CLI):
  python3 security_analyzer.py --base-dir /path/to/repo [--state path/to/bootstrap-state.json]
                               [--audit | --report report.html]
"""

import argparse
import json
import os
import re
import stat
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import escape as _e
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class SecurityFinding:
    severity:    str           # RED / ORANGE / YELLOW
    category:    str           # "log-leak" / "script-unsafe" / "manifest-plaintext"
    file_path:   str
    line_number: int
    line_content: str          # sanitised (secret values redacted)
    description: str
    remediation: str
    rule_id:     str           # stable identifier for this rule


@dataclass
class SecurityReport:
    cell_id:     str
    scanned_at:  str
    base_dir:    str
    findings:    List[SecurityFinding] = field(default_factory=list)
    files_scanned: int = 0
    errors:      List[str] = field(default_factory=list)

    @property
    def red_count(self):
        return sum(1 for f in self.findings if f.severity == "RED")

    @property
    def orange_count(self):
        return sum(1 for f in self.findings if f.severity == "ORANGE")

    @property
    def yellow_count(self):
        return sum(1 for f in self.findings if f.severity == "YELLOW")

    @property
    def total_count(self):
        return len(self.findings)


# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------

# Log file patterns — match lines that reveal secret values
_LOG_PATTERNS: List[Dict] = [
    {
        "rule_id": "LOG-001",
        "severity": "RED",
        "pattern": re.compile(
            r"(?i)(totp[_\-]?secret|otp[_\-]?seed|google[_\-]?authenticator)\s*[=:]\s*\S+",
            re.IGNORECASE,
        ),
        "description": "TOTP seed or OTP secret value appears in log output.",
        "remediation": "Ensure TOTP seeds are never logged. Redact or rotate the exposed secret.",
    },
    {
        "rule_id": "LOG-002",
        "severity": "RED",
        "pattern": re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
        ),
        "description": "SSH or TLS private key content appears in log output.",
        "remediation": "Rotate the exposed key immediately. Never log private key material.",
    },
    {
        "rule_id": "LOG-003",
        "severity": "RED",
        "pattern": re.compile(
            r"(?i)(?:password|passphrase|passwd)\s*[=:]\s*(?!null|none|''\s|\"\"|\[\])\S{6,}",
        ),
        "description": "Password or passphrase value appears in log output.",
        "remediation": "Rotate the exposed credential. Add log sanitisation before this output.",
    },
    {
        "rule_id": "LOG-004",
        "severity": "RED",
        "pattern": re.compile(
            r"(?i)(?:k3s[_\-]?token|K3S_TOKEN|cluster[_\-]?secret)\s*[=:]\s*K1[0-9a-f:]{20,}",
        ),
        "description": "k3s join token appears in log output.",
        "remediation": "Rotate the k3s join token immediately (remediation-cli.py rotate-join-token).",
    },
    {
        "rule_id": "LOG-005",
        "severity": "RED",
        "pattern": re.compile(
            r"(?i)(?:api[_\-]?key|api[_\-]?token|auth[_\-]?token|bearer)\s*[=:]\s*[A-Za-z0-9+/=_\-]{20,}",
        ),
        "description": "API key or bearer token value appears in log output.",
        "remediation": "Rotate the exposed token. Never log authentication tokens.",
    },
    {
        "rule_id": "LOG-006",
        "severity": "RED",
        "pattern": re.compile(
            r"(?i)(?:restic[_\-]?password|RESTIC_PASSWORD)\s*[=:]\s*\S{8,}",
        ),
        "description": "Restic repository password appears in log output.",
        "remediation": "Rotate the restic repo password. Ensure RESTIC_PASSWORD is not logged.",
    },
    {
        "rule_id": "LOG-007",
        "severity": "ORANGE",
        "pattern": re.compile(
            r"(?i)(?:secret|token|key|credential|auth)\s*[=:]\s*(?!null|none|true|false|''\s|\"\"|\[\])[A-Za-z0-9+/=_\-]{12,}",
        ),
        "description": "Possible secret value in log output (keyword match).",
        "remediation": "Review this line — if it contains a real secret, rotate it and add sanitisation.",
    },
    {
        "rule_id": "LOG-008",
        "severity": "YELLOW",
        "pattern": re.compile(
            r"(?i)Authorization:\s*(?:Bearer|Basic)\s+\S+",
        ),
        "description": "HTTP Authorization header value appears in log output.",
        "remediation": "Ensure HTTP client logs do not include full Authorization headers.",
    },
]

# Shell script patterns — unsafe practices that can expose secrets
_SCRIPT_PATTERNS: List[Dict] = [
    {
        "rule_id": "SCRIPT-001",
        "severity": "ORANGE",
        "pattern": re.compile(r"StrictHostKeyChecking\s*=\s*no", re.IGNORECASE),
        "description": "SSH StrictHostKeyChecking=no disables host key verification, enabling MITM attacks.",
        "remediation": "Use StrictHostKeyChecking=accept-new for first connections, or add known host keys explicitly.",
        "allow_in_files": ["phase-00", "first_connect"],  # allowed in explicit first-connect scripts
    },
    {
        "rule_id": "SCRIPT-002",
        "severity": "RED",
        "pattern": re.compile(
            r"(?:(?:sshpass|expect|spawn)\s+['\"]?-p\s+['\"]?\S+|(?:-pass(?:word)?|--password)\s+['\"]?\S{4,})",
            re.IGNORECASE,
        ),
        "description": "Password passed on command line — visible in process list and shell history.",
        "remediation": "Use stdin/file redirection or a secrets-broker script; never pass passwords as arguments.",
    },
    {
        "rule_id": "SCRIPT-003",
        "severity": "RED",
        "pattern": re.compile(
            r"export\s+(?:PASSWORD|PASSWD|SECRET|TOKEN|API_KEY|RESTIC_PASSWORD|K3S_TOKEN)\s*=\s*['\"]?\S{4,}",
            re.IGNORECASE,
        ),
        "description": "Secret value exported as environment variable — visible to all child processes.",
        "remediation": "Use a secrets-broker script or pass values via stdin; never export plaintext secrets.",
    },
    {
        "rule_id": "SCRIPT-004",
        "severity": "ORANGE",
        "pattern": re.compile(
            r"echo\s+['\"]?\S{8,}['\"]?\s*\|\s*(?:openssl|gpg|restic|keepassxc-cli)",
            re.IGNORECASE,
        ),
        "description": "Secret piped via echo to a crypto/KeePass tool — visible in process list.",
        "remediation": "Use process substitution or a named pipe; never echo secrets to crypto tools.",
    },
    {
        "rule_id": "SCRIPT-005",
        "severity": "ORANGE",
        "pattern": re.compile(
            r"curl\b.*?-H\s+['\"]?Authorization:\s*Bearer\s+\S{10,}",
            re.IGNORECASE,
        ),
        "description": "Bearer token hardcoded in curl command.",
        "remediation": "Read token from a secrets file or environment variable set via secrets-broker.",
    },
    {
        "rule_id": "SCRIPT-006",
        "severity": "YELLOW",
        "pattern": re.compile(
            r"(?i)set\s+-x|set\s+[^\n]*x[^\n]",
        ),
        "description": "Shell debug mode (set -x) enabled — all commands including secret values will be logged.",
        "remediation": "Disable set -x before sections that handle secrets, or use { set +x; ...; set -x; }.",
    },
    {
        "rule_id": "SCRIPT-007",
        "severity": "ORANGE",
        "pattern": re.compile(
            r"UserKnownHostsFile\s*=\s*/dev/null",
            re.IGNORECASE,
        ),
        "description": "UserKnownHostsFile=/dev/null discards host key trust — enables MITM on all connections.",
        "remediation": "Use a real known_hosts file; pre-populate it with the expected host keys.",
    },
]

# Manifest / state file patterns — fields that must not contain plaintext secrets
_MANIFEST_SENSITIVE_FIELD_RE = re.compile(
    r"(?i)^(?:password|passphrase|secret|private_key|api_key|api_token|"
    r"auth_token|bearer_token|totp_seed|totp_secret|restic_password|"
    r"k3s_token|join_token|encryption_key|master_password|credential)$",
)
_KEEPASS_REF_RE  = re.compile(r"^[A-Za-z][A-Za-z0-9 _/\-]+/[A-Za-z][A-Za-z0-9 _\-]+$")
_SECRET_REF_RE   = re.compile(r"^(?:secret|ref|keepass|vault):", re.IGNORECASE)
_PRIVATE_KEY_RE  = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")
_BEARER_TOKEN_RE = re.compile(r"^(?:ey[A-Za-z0-9+/=_]{20,}|[A-Za-z0-9+/=_\-]{40,})$")


# ---------------------------------------------------------------------------
# Helper: sanitise a log line for display (redact the value portion)
# ---------------------------------------------------------------------------

def _sanitise_line(line: str) -> str:
    """Replace likely secret values with [REDACTED] for safe display."""
    line = re.sub(
        r"((?:password|passphrase|secret|token|key|api[_\-]?key)\s*[=:]\s*)\S+",
        r"\1[REDACTED]",
        line,
        flags=re.IGNORECASE,
    )
    line = re.sub(
        r"(Bearer\s+)\S+",
        r"\1[REDACTED]",
        line,
        flags=re.IGNORECASE,
    )
    line = re.sub(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----.*",
                  "-----BEGIN PRIVATE KEY----- [REDACTED]", line, flags=re.DOTALL)
    return line.strip()[:200]


# ---------------------------------------------------------------------------
# Log file scanner
# ---------------------------------------------------------------------------

def scan_logs(paths: List[str]) -> List[SecurityFinding]:
    """Scan log files for plaintext secret patterns."""
    findings: List[SecurityFinding] = []
    for path in paths:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, errors="replace") as f:
                for lineno, raw_line in enumerate(f, 1):
                    line = raw_line.rstrip()
                    for pat in _LOG_PATTERNS:
                        if pat["pattern"].search(line):
                            findings.append(SecurityFinding(
                                severity=pat["severity"],
                                category="log-leak",
                                file_path=path,
                                line_number=lineno,
                                line_content=_sanitise_line(line),
                                description=pat["description"],
                                remediation=pat["remediation"],
                                rule_id=pat["rule_id"],
                            ))
        except (PermissionError, OSError):
            pass
    return findings


# ---------------------------------------------------------------------------
# Shell script scanner
# ---------------------------------------------------------------------------

def _is_first_connect_script(path: str) -> bool:
    """Return True if this script is explicitly a first-connect / bootstrap script."""
    name = os.path.basename(path).lower()
    return any(k in name for k in ("phase-00", "first_connect", "phase_00", "bootstrap"))


def scan_scripts(paths: List[str]) -> List[SecurityFinding]:
    """Scan shell scripts for unsafe security patterns."""
    findings: List[SecurityFinding] = []
    for path in paths:
        if not os.path.isfile(path):
            continue
        is_first = _is_first_connect_script(path)
        try:
            with open(path, errors="replace") as f:
                for lineno, raw_line in enumerate(f, 1):
                    line = raw_line.rstrip()
                    # Skip comment lines
                    stripped = line.lstrip()
                    if stripped.startswith("#"):
                        continue
                    for pat in _SCRIPT_PATTERNS:
                        if pat["pattern"].search(line):
                            # StrictHostKeyChecking=no is allowed in first-connect scripts
                            if pat["rule_id"] == "SCRIPT-001" and is_first:
                                continue
                            findings.append(SecurityFinding(
                                severity=pat["severity"],
                                category="script-unsafe",
                                file_path=path,
                                line_number=lineno,
                                line_content=_sanitise_line(line),
                                description=pat["description"],
                                remediation=pat["remediation"],
                                rule_id=pat["rule_id"],
                            ))
        except (PermissionError, OSError):
            pass
    return findings


# ---------------------------------------------------------------------------
# Manifest / state file scanner
# ---------------------------------------------------------------------------

def _check_value_for_secret(field_name: str, value, path: str, field_path: str) -> Optional[SecurityFinding]:
    """Check if a manifest field value looks like a plaintext secret."""
    if value is None or value == "" or isinstance(value, (bool, int, float)):
        return None

    val_str = str(value)

    # Clearly a KeePass or reference path — OK
    if _KEEPASS_REF_RE.match(val_str) or _SECRET_REF_RE.match(val_str):
        return None

    # Private key material
    if _PRIVATE_KEY_RE.search(val_str):
        return SecurityFinding(
            severity="RED",
            category="manifest-plaintext",
            file_path=path,
            line_number=0,
            line_content=f"{field_path}: -----BEGIN PRIVATE KEY----- [REDACTED]",
            description=f"Private key material in manifest field '{field_path}'.",
            remediation="Remove the private key from the manifest. Store in KeePass and use a secret reference path.",
            rule_id="MANIFEST-001",
        )

    # Field name is a known sensitive field
    if _MANIFEST_SENSITIVE_FIELD_RE.match(field_name):
        if len(val_str) >= 6 and not val_str.startswith("$"):
            return SecurityFinding(
                severity="RED",
                category="manifest-plaintext",
                file_path=path,
                line_number=0,
                line_content=f"{field_path}: [REDACTED]",
                description=f"Sensitive field '{field_name}' contains a plaintext value.",
                remediation="Replace with a KeePass reference path (e.g. 'Infrastructure/service/password').",
                rule_id="MANIFEST-002",
            )

    return None


def _walk_manifest(obj, path: str, field_path: str, findings: List[SecurityFinding]) -> None:
    """Recursively walk a manifest dict/list, checking values."""
    if isinstance(obj, dict):
        for key, val in obj.items():
            child_path = f"{field_path}.{key}" if field_path else key
            finding = _check_value_for_secret(key, val, path, child_path)
            if finding:
                findings.append(finding)
            _walk_manifest(val, path, child_path, findings)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _walk_manifest(item, path, f"{field_path}[{i}]", findings)


def scan_manifest(state: dict, path: str = "<bootstrap-state.json>") -> List[SecurityFinding]:
    """Scan a bootstrap-state.json dict for plaintext secret fields."""
    findings: List[SecurityFinding] = []
    _walk_manifest(state, path, "", findings)
    return findings


# ---------------------------------------------------------------------------
# File discovery helpers
# ---------------------------------------------------------------------------

def _find_log_files(base_dir: str) -> List[str]:
    results = []
    log_dirs = [
        base_dir,
        os.path.join(base_dir, "logs"),
        os.path.join(base_dir, "var/log/broodforge"),
        "/var/log/broodforge",
    ]
    for d in log_dirs:
        if not os.path.isdir(d):
            continue
        for entry in os.scandir(d):
            if entry.name.endswith((".log", ".out", ".err")):
                results.append(entry.path)
    return results


def _find_shell_scripts(base_dir: str) -> List[str]:
    results = []
    script_dirs = [
        base_dir,
        os.path.join(base_dir, "proxmox-bootstrap"),
        os.path.join(base_dir, "scripts"),
        os.path.join(base_dir, "spawn-packages"),
        os.path.join(base_dir, "forge-package"),
        os.path.join(base_dir, "output"),
    ]
    seen = set()
    for d in script_dirs:
        if not os.path.isdir(d):
            continue
        for root, dirs, files in os.walk(d):
            # Skip hidden directories
            dirs[:] = [x for x in dirs if not x.startswith(".")]
            for fname in files:
                if fname.endswith(".sh"):
                    full = os.path.join(root, fname)
                    if full not in seen:
                        seen.add(full)
                        results.append(full)
    return results


# ---------------------------------------------------------------------------
# Main scan entry point
# ---------------------------------------------------------------------------

def scan(
    base_dir:       str,
    state:          Optional[dict] = None,
    state_path:     str = "",
    extra_log_paths: Optional[List[str]] = None,
    extra_script_paths: Optional[List[str]] = None,
    now_fn:         Optional[Callable] = None,
) -> SecurityReport:
    """
    Full one-shot security audit.
    Scans logs, shell scripts, and the bootstrap-state manifest.
    """
    ts = now_fn() if now_fn else datetime.now(timezone.utc).isoformat()
    cell_id = (state or {}).get("cell_id") or "unknown"
    report = SecurityReport(cell_id=cell_id, scanned_at=ts, base_dir=base_dir)

    log_paths = _find_log_files(base_dir) + (extra_log_paths or [])
    script_paths = _find_shell_scripts(base_dir) + (extra_script_paths or [])

    report.files_scanned = len(log_paths) + len(script_paths) + (1 if state else 0)

    report.findings.extend(scan_logs(log_paths))
    report.findings.extend(scan_scripts(script_paths))
    if state:
        spath = state_path or os.path.join(base_dir, "bootstrap-state.json")
        report.findings.extend(scan_manifest(state, spath))

    return report


# ---------------------------------------------------------------------------
# Readiness score
# ---------------------------------------------------------------------------

def security_posture_score(report: SecurityReport) -> str:
    """
    Map a SecurityReport to a readiness score.
    RED:    any confirmed plaintext secrets in logs or manifests
    ORANGE: unsafe patterns in scripts (ORANGE or RED findings)
    YELLOW: suspicious patterns in logs (YELLOW findings only)
    GREEN:  no findings
    """
    if report.red_count > 0:
        return "RED"
    if report.orange_count > 0:
        return "ORANGE"
    if report.yellow_count > 0:
        return "YELLOW"
    return "GREEN"


def security_posture_reason(report: SecurityReport) -> str:
    score = security_posture_score(report)
    if score == "RED":
        return (
            f"{report.red_count} confirmed secret leak(s) found. "
            f"Immediate remediation required."
        )
    if score == "ORANGE":
        return (
            f"{report.orange_count} unsafe script pattern(s) found. "
            f"Remediate to reduce exposure risk."
        )
    if score == "YELLOW":
        return (
            f"{report.yellow_count} suspicious pattern(s) found. "
            f"Review and confirm they are not secret leaks."
        )
    return "No security issues detected."


# ---------------------------------------------------------------------------
# HTML report generator
# ---------------------------------------------------------------------------

_SEVERITY_COLORS = {
    "RED":    ("#721c24", "#f8d7da"),
    "ORANGE": ("#7c3c00", "#fde8d0"),
    "YELLOW": ("#856404", "#fff3cd"),
}

_CATEGORY_LABELS = {
    "log-leak":          "Log File — Secret Leak",
    "script-unsafe":     "Shell Script — Unsafe Pattern",
    "manifest-plaintext":"Manifest — Plaintext Secret",
}


def _finding_row(f: SecurityFinding, idx: int) -> str:
    fg, bg = _SEVERITY_COLORS.get(f.severity, ("#333", "#f0f0f0"))
    cat = _CATEGORY_LABELS.get(f.category, f.category)
    fname = os.path.basename(f.file_path)
    loc = f"{fname}:{f.line_number}" if f.line_number else fname
    return f"""
<tr>
  <td><span class="sec-badge" style="background:{bg};color:{fg};border:1px solid {fg}">{f.severity}</span></td>
  <td style="font-size:.82em;color:#555">{_e(f.rule_id)}</td>
  <td style="font-size:.85em">{_e(cat)}</td>
  <td><code style="font-size:.78em">{_e(loc)}</code></td>
  <td style="font-size:.85em">{_e(f.description)}</td>
  <td style="font-size:.82em;color:#555">{_e(f.line_content)}</td>
</tr>"""


def build_security_report_html(
    report:   SecurityReport,
    now_fn:   Optional[Callable] = None,
) -> str:
    """Build a self-contained HTML security report."""
    ts = now_fn() if now_fn else datetime.now(timezone.utc).isoformat()
    score  = security_posture_score(report)
    reason = security_posture_reason(report)

    score_colors = {
        "GREEN":  ("#155724", "#d4edda"),
        "YELLOW": ("#856404", "#fff3cd"),
        "ORANGE": ("#7c3c00", "#fde8d0"),
        "RED":    ("#721c24", "#f8d7da"),
    }
    sfg, sbg = score_colors.get(score, ("#333", "#eee"))

    # Group findings by severity
    reds    = [f for f in report.findings if f.severity == "RED"]
    oranges = [f for f in report.findings if f.severity == "ORANGE"]
    yellows = [f for f in report.findings if f.severity == "YELLOW"]

    def _findings_section(title: str, findings: List[SecurityFinding], open_: bool) -> str:
        if not findings:
            return f"""
<details {'open' if open_ else ''}>
<summary>{_e(title)} (0)</summary>
<div class="sec-body"><p style="color:#777">No {title.lower()} findings.</p></div>
</details>"""
        rows = "".join(_finding_row(f, i) for i, f in enumerate(findings))
        return f"""
<details {'open' if open_ else ''}>
<summary>{_e(title)} ({len(findings)})</summary>
<div class="sec-body">
<table>
  <tr>
    <th>Severity</th><th>Rule</th><th>Category</th>
    <th>Location</th><th>Finding</th><th>Line (sanitised)</th>
  </tr>
  {rows}
</table>
</div>
</details>"""

    remediation_items = ""
    for f in reds + oranges:
        remediation_items += f"""
<div class="rem-item">
  <span class="sec-badge" style="background:{_SEVERITY_COLORS[f.severity][1]};
    color:{_SEVERITY_COLORS[f.severity][0]};border:1px solid {_SEVERITY_COLORS[f.severity][0]}">
    {f.severity}</span>
  <strong>{_e(f.rule_id)}</strong>
  <code>{_e(os.path.basename(f.file_path))}</code>
  <span style="color:#555;font-size:.88em">{_e(f.remediation)}</span>
</div>"""

    if not remediation_items:
        remediation_items = "<p>No immediate remediation required.</p>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Security Posture Report — {_e(report.cell_id)}</title>
<style>
  :root{{--bg:#1a1d23;--bg2:#22262e;--bg3:#2a2f3a;--border:#3a3f4d;--text:#cdd6f4;
    --muted:#7f8498;--accent:#89b4fa;--green:#a6e3a1;--yellow:#f9e2af;
    --orange:#fab387;--red:#f38ba8;--radius:6px}}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--text);font-family:'Segoe UI',system-ui,sans-serif;
    font-size:14px;line-height:1.6;padding:0}}
  .topbar{{background:#0e1117;border-bottom:1px solid var(--border);padding:10px 24px;
    display:flex;align-items:center;gap:16px;position:sticky;top:0;z-index:100}}
  .topbar-title{{color:var(--accent);font-size:1.1em;font-weight:700}}
  .topbar-cell{{color:var(--muted);font-size:.88em}}
  .topbar-ts{{color:var(--muted);font-size:.78em;margin-left:auto}}
  .content{{padding:20px 24px;max-width:1200px;margin:0 auto}}
  h2{{color:var(--accent);font-size:.95em;text-transform:uppercase;letter-spacing:.06em;
    margin:20px 0 8px;padding-bottom:4px;border-bottom:1px solid var(--border)}}
  .score-banner{{border-radius:var(--radius);padding:14px 18px;margin:12px 0;
    background:{sbg};border:2px solid {sfg}}}
  .score-banner .score-level{{font-size:1.4em;font-weight:700;color:{sfg}}}
  .score-banner .score-reason{{color:{sfg};font-size:.9em;margin-top:4px}}
  .stat-row{{display:flex;gap:14px;flex-wrap:wrap;margin:10px 0}}
  .stat{{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);
    padding:8px 14px;min-width:100px}}
  .stat-val{{font-size:1.4em;font-weight:700}}
  .stat-label{{font-size:.75em;color:var(--muted)}}
  details{{border:1px solid var(--border);border-radius:var(--radius);margin:8px 0}}
  details>summary{{cursor:pointer;padding:9px 14px;background:var(--bg2);
    font-weight:600;list-style:none;border-radius:var(--radius);user-select:none}}
  details[open]>summary{{border-radius:var(--radius) var(--radius) 0 0}}
  .sec-body{{padding:10px 14px 14px}}
  table{{width:100%;border-collapse:collapse;font-size:.86em;margin:8px 0}}
  th{{background:var(--bg3);color:var(--muted);text-align:left;padding:6px 8px;
    font-size:.78em;text-transform:uppercase;letter-spacing:.05em;
    border-bottom:1px solid var(--border)}}
  td{{padding:5px 8px;border-bottom:1px solid var(--bg3);vertical-align:top}}
  tr:last-child td{{border-bottom:none}}
  code{{background:var(--bg3);color:var(--green);padding:1px 5px;border-radius:3px;
    font-family:'Cascadia Code',Consolas,monospace;font-size:.86em}}
  .sec-badge{{padding:1px 8px;border-radius:99px;font-size:.75em;font-weight:700;
    letter-spacing:.04em}}
  .rem-item{{background:var(--bg2);border:1px solid var(--border);
    border-radius:var(--radius);padding:10px 14px;margin:6px 0;
    display:flex;flex-wrap:wrap;align-items:center;gap:8px;font-size:.88em}}
  .tip{{background:#1e2d3a;border-left:3px solid var(--accent);padding:8px 12px;
    border-radius:0 var(--radius) var(--radius) 0;margin:8px 0;font-size:.88em}}
  @media print{{.topbar{{display:none}}body{{padding:12px}}}}
</style>
</head>
<body>

<div class="topbar">
  <span class="topbar-title">🔒 Broodforge Security</span>
  <span class="topbar-cell">{_e(report.cell_id)}</span>
  <span class="topbar-ts">Generated: {_e(ts[:19])}</span>
</div>

<div class="content">

  <div class="score-banner">
    <div class="score-level">Security Posture: {score}</div>
    <div class="score-reason">{_e(reason)}</div>
  </div>

  <div class="stat-row">
    <div class="stat">
      <div class="stat-val" style="color:var(--muted)">{report.files_scanned}</div>
      <div class="stat-label">Files scanned</div>
    </div>
    <div class="stat">
      <div class="stat-val" style="color:var(--red)">{report.red_count}</div>
      <div class="stat-label">RED (critical)</div>
    </div>
    <div class="stat">
      <div class="stat-val" style="color:var(--orange)">{report.orange_count}</div>
      <div class="stat-label">ORANGE (warn)</div>
    </div>
    <div class="stat">
      <div class="stat-val" style="color:var(--yellow)">{report.yellow_count}</div>
      <div class="stat-label">YELLOW (info)</div>
    </div>
    <div class="stat">
      <div class="stat-val">{_e(ts[:10])}</div>
      <div class="stat-label">Scan date</div>
    </div>
  </div>

  <h2>Remediation Required</h2>
  <div style="margin:8px 0">
    {remediation_items}
  </div>

  <h2>Findings by Severity</h2>

  {_findings_section("RED — Confirmed Secret Leaks", reds, open_=bool(reds))}
  {_findings_section("ORANGE — Unsafe Patterns", oranges, open_=bool(oranges))}
  {_findings_section("YELLOW — Suspicious Patterns", yellows, open_=False)}

  {'<div class="tip">All findings are sanitised — actual secret values are never displayed in this report. Rotate any secrets that appear in RED findings.</div>' if reds else ''}

  <p style="color:var(--muted);font-size:.78em;margin-top:20px;text-align:center">
    Broodforge Security Analyzer · Cell: {_e(report.cell_id)} · Scanned: {report.files_scanned} files
  </p>
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def write_security_scan_result(state_path: str, report: "SecurityReport") -> None:
    """
    Serialize a SecurityReport into the ``security_scan.last_result`` field of
    bootstrap-state.json.  Creates the key if absent; leaves all other state
    fields untouched.
    """
    state_path = str(state_path)
    try:
        with open(state_path) as fh:
            state: dict = json.load(fh)
    except (OSError, json.JSONDecodeError):
        state = {}

    state.setdefault("security_scan", {})
    state["security_scan"]["last_result"] = {
        "scanned_at":    report.scanned_at,
        "cell_id":       report.cell_id,
        "files_scanned": report.files_scanned,
        "posture":       security_posture_score(report),
        "red_count":     report.red_count,
        "orange_count":  report.orange_count,
        "yellow_count":  report.yellow_count,
        "findings": [
            {
                "severity":    f.severity,
                "category":    f.category,
                "rule_id":     f.rule_id,
                "file_path":   f.file_path,
                "line_number": f.line_number,
                "description": f.description,
                "remediation": f.remediation,
            }
            for f in report.findings
        ],
    }

    with open(state_path, "w") as fh:
        json.dump(state, fh, indent=2)


# ---------------------------------------------------------------------------
# Continuous watch mode
# ---------------------------------------------------------------------------

def watch(
    paths: List[str],
    callback: Callable[["SecurityFinding"], None],
    stop_event,  # threading.Event or any object with .is_set()
    poll_interval: float = 1.0,
) -> None:
    """
    Tail one or more log files in real time, emitting SecurityFinding objects
    to ``callback`` as new matching lines appear.

    Uses inotify on Linux if available (via the ``inotify`` stdlib-compatible
    shim); falls back to polling on all other platforms (including Windows).

    Args:
        paths:         list of file paths to watch
        callback:      called with each new SecurityFinding
        stop_event:    polling stops when stop_event.is_set() returns True
        poll_interval: seconds between poll iterations (fallback mode)
    """
    import time
    import threading

    # Track file positions so we only emit new content
    positions: Dict[str, int] = {}
    for p in paths:
        try:
            positions[p] = os.path.getsize(p)
        except OSError:
            positions[p] = 0

    def _check_file(path: str) -> None:
        try:
            size = os.path.getsize(path)
        except OSError:
            return
        prev = positions.get(path, 0)
        if size <= prev:
            if size < prev:
                positions[path] = 0  # file was rotated
            return
        try:
            with open(path, errors="replace") as fh:
                fh.seek(prev)
                new_content = fh.read(size - prev)
        except OSError:
            return
        positions[path] = size
        for lineno_offset, raw_line in enumerate(new_content.splitlines(), 1):
            line = raw_line.rstrip()
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            for pat in _LOG_PATTERNS:
                m = pat["pattern"].search(line)
                if not m:
                    continue
                callback(SecurityFinding(
                    severity=pat["severity"],
                    category="log-leak",
                    rule_id=pat["rule_id"],
                    file_path=path,
                    line_number=lineno_offset,
                    line_content=_sanitise_line(line),
                    description=pat["description"],
                    remediation=pat["remediation"],
                ))

    # Try inotify (Linux only); fall back to polling
    _use_inotify = False
    if hasattr(os, "inotify_init"):  # pragma: no cover — Linux only path
        _use_inotify = True

    if _use_inotify:  # pragma: no cover
        try:
            import inotify.adapters  # type: ignore
            inot = inotify.adapters.Inotify()
            for p in paths:
                if os.path.exists(p):
                    inot.add_watch(p)
            for event in inot.event_gen(yield_nones=False):
                if stop_event.is_set():
                    break
                (_, type_names, path, _filename) = event
                if "IN_MODIFY" in type_names or "IN_MOVED_TO" in type_names:
                    _check_file(path)
        except Exception:
            _use_inotify = False

    if not _use_inotify:
        while not stop_event.is_set():
            for p in paths:
                _check_file(p)
            time.sleep(poll_interval)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Broodforge security analyzer — one-shot audit of logs, scripts, and manifest",
    )
    parser.add_argument(
        "--base-dir", default=".",
        help="Base directory to scan (default: current directory)",
    )
    parser.add_argument(
        "--state", default=None,
        help="Path to bootstrap-state.json for manifest scan (optional)",
    )
    parser.add_argument(
        "--write-state", default=None, metavar="PATH",
        help="Persist scan results into bootstrap-state.json at PATH",
    )
    parser.add_argument(
        "--report", default=None, metavar="PATH",
        help="Write HTML report to PATH (optional)",
    )
    args = parser.parse_args()

    import sys

    state: Optional[dict] = None
    state_path_str = args.state or ""
    if args.state:
        try:
            with open(args.state) as fh:
                state = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[warn] Could not load state: {exc}", file=sys.stderr)

    report = scan(
        base_dir=args.base_dir,
        state=state,
        state_path=state_path_str,
    )

    score  = security_posture_score(report)
    reason = security_posture_reason(report)

    print(f"Security Posture: {score}")
    print(f"  {reason}")
    print(f"  Files scanned: {report.files_scanned}")
    print(f"  RED: {report.red_count}  ORANGE: {report.orange_count}  YELLOW: {report.yellow_count}")

    if args.write_state:
        write_security_scan_result(args.write_state, report)
        print(f"  Results written to: {args.write_state}")

    if args.report:
        html = build_security_report_html(report)
        Path(args.report).write_text(html, encoding="utf-8")
        print(f"  HTML report: {args.report}")

    if report.red_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
