#!/usr/bin/env python3
"""
lib/forge-onboarding-pdf.py — Generate a polished onboarding package (HTML primary, PDF optional).

HTML is the primary output — universally readable without extra software, opens
in any browser, prints cleanly.  PDF is an optional secondary step using weasyprint.

Dependencies:
  Required : qrcode[pil]   pip install "qrcode[pil]"   — for TOTP QR codes
  Optional : weasyprint     pip install weasyprint       — for --also-pdf flag

Input JSON (stdin):
{
  "username":     "alice",
  "display_name": "Alice Smith",
  "generated_at": "2026-06-10T07:30:00Z",
  "mode":         "onboarding" | "add-service",
  "services": {
    "vaultwarden": {
      "password":    "...",
      "totp_secret": "...",
      "totp_uri":    "otpauth://totp/..."
    }
  }
}

Usage (from forge-onboard-user.sh):
  echo "$CRED_JSON" | python3 lib/forge-onboarding-pdf.py \\
      --output alice-onboarding.html [--also-pdf]

Exit codes:
  0 — HTML written (and PDF if --also-pdf and weasyprint available)
  1 — error
  2 — --also-pdf requested but weasyprint unavailable (HTML still written; rc=2)
"""

import argparse
import base64
import io
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Dependency probes
# ---------------------------------------------------------------------------

try:
    import qrcode
    from PIL import Image as _PilImage
    _QRCODE_AVAILABLE = True
except ImportError:
    _QRCODE_AVAILABLE = False

try:
    import weasyprint as _weasyprint
    _WEASYPRINT_AVAILABLE = True
except ImportError:
    _WEASYPRINT_AVAILABLE = False


# ---------------------------------------------------------------------------
# QR code generation
# ---------------------------------------------------------------------------

def _qr_png_b64(data: str, box_size: int = 6, border: int = 2) -> str:
    """Generate a QR code PNG from data and return as base64 string."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    font-size: 11pt;
    color: #1a1a2e;
    background: #ffffff;
    padding: 24px 32px;
}
.header {
    background: #16213e;
    color: #e2e8f0;
    padding: 20px 28px;
    border-radius: 8px;
    margin-bottom: 24px;
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
}
.header h1 {
    font-size: 18pt;
    font-weight: 700;
    letter-spacing: 0.5px;
    color: #7dd3fc;
}
.header .subtitle { font-size: 10pt; color: #94a3b8; margin-top: 4px; }
.header .meta     { font-size: 9pt;  color: #64748b;  text-align: right; }
.security-notice {
    background: #fef3c7;
    border: 1.5px solid #f59e0b;
    border-radius: 6px;
    padding: 10px 16px;
    margin-bottom: 24px;
    font-size: 10pt;
    color: #78350f;
}
.security-notice strong { color: #92400e; }
.service-card {
    border: 1.5px solid #e2e8f0;
    border-radius: 8px;
    margin-bottom: 20px;
    overflow: hidden;
    page-break-inside: avoid;
}
.service-header {
    background: #0f3460;
    color: #e2e8f0;
    padding: 10px 18px;
    font-size: 12pt;
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 8px;
}
.service-header .svc-label { font-size: 9pt; color: #93c5fd; margin-left: auto; }
.service-body {
    padding: 16px 18px;
    display: flex;
    gap: 24px;
    align-items: flex-start;
}
.creds-block { flex: 1; }
.cred-row { margin-bottom: 12px; }
.cred-label {
    font-size: 8pt;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    color: #64748b;
    margin-bottom: 3px;
}
.cred-value {
    font-family: 'Courier New', Courier, monospace;
    font-size: 10.5pt;
    background: #f1f5f9;
    border: 1px solid #e2e8f0;
    border-radius: 4px;
    padding: 5px 10px;
    word-break: break-all;
    color: #0f172a;
}
.totp-block { flex: 0 0 auto; text-align: center; }
.totp-block img {
    width: 130px;
    height: 130px;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    display: block;
    margin: 0 auto 6px;
}
.totp-caption { font-size: 8pt; color: #64748b; }
.totp-instructions {
    font-size: 8.5pt;
    color: #475569;
    margin-top: 10px;
    background: #f8fafc;
    border-radius: 4px;
    padding: 7px 10px;
}
.footer {
    margin-top: 28px;
    border-top: 1px solid #e2e8f0;
    padding-top: 14px;
    font-size: 8.5pt;
    color: #94a3b8;
    display: flex;
    justify-content: space-between;
}
.zk-notice {
    background: #ecfdf5;
    border: 1.5px solid #6ee7b7;
    border-radius: 6px;
    padding: 10px 16px;
    margin-top: 20px;
    font-size: 9.5pt;
    color: #065f46;
}
"""


def _render_html(data: dict, qr_map: dict) -> str:
    """Render the onboarding HTML from credential data and pre-built QR map."""
    username     = data.get("username", "")
    display_name = data.get("display_name", username)
    generated_at = data.get("generated_at", datetime.now(timezone.utc).isoformat())
    mode         = data.get("mode", "onboarding")
    services     = data.get("services", {})

    title = "New Service Access" if mode == "add-service" else "Onboarding Package"

    cards_html = ""
    for svc_name, creds in services.items():
        password    = creds.get("password", "")
        totp_secret = creds.get("totp_secret", "")
        totp_uri    = creds.get("totp_uri", "")

        # QR code block
        qr_html = ""
        if totp_uri and svc_name in qr_map:
            qr_b64 = qr_map[svc_name]
            qr_html = f"""
            <div class="totp-block">
                <img src="data:image/png;base64,{qr_b64}" alt="TOTP QR Code for {svc_name}">
                <div class="totp-caption">Scan to set up TOTP</div>
                <div class="totp-instructions">
                    Use Google Authenticator, Aegis, or any TOTP app.<br>
                    Or enter the secret manually:<br>
                    SHA-1 &nbsp;·&nbsp; 6 digits &nbsp;·&nbsp; 30 s period
                </div>
            </div>"""
        elif totp_secret:
            # No QR image available — show raw secret
            qr_html = f"""
            <div class="totp-block" style="max-width:200px;">
                <div class="cred-label">TOTP secret (manual entry)</div>
                <div class="cred-value" style="font-size:9pt">{totp_secret}</div>
                <div class="totp-instructions" style="margin-top:8px">
                    SHA-1 &nbsp;·&nbsp; 6 digits &nbsp;·&nbsp; 30 s period
                </div>
            </div>"""

        # Password row
        pw_html = ""
        if password:
            pw_html = f"""
            <div class="cred-row">
                <div class="cred-label">Password</div>
                <div class="cred-value">{password}</div>
            </div>"""

        # TOTP secret row (always show for manual entry backup)
        totp_row_html = ""
        if totp_secret and totp_uri:
            totp_row_html = f"""
            <div class="cred-row">
                <div class="cred-label">TOTP secret (backup)</div>
                <div class="cred-value" style="font-size:9pt">{totp_secret}</div>
            </div>"""

        cards_html += f"""
        <div class="service-card">
            <div class="service-header">
                ⬡ &nbsp;{svc_name}
                <span class="svc-label">Username: {username}</span>
            </div>
            <div class="service-body">
                <div class="creds-block">
                    {pw_html}
                    {totp_row_html}
                </div>
                {qr_html}
            </div>
        </div>"""

    zk_notice = """
    <div class="zk-notice">
        <strong>🔒 Zero-Knowledge Services</strong><br>
        Your Vaultwarden vault is encrypted with your master password — server
        administrators cannot read your vault contents even with direct server
        access. Your data is yours alone. Once you change your password, the
        admin copy (if retained) becomes invalid.
    </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Broodforge {title} — {display_name}</title>
<style>{_CSS}</style>
</head>
<body>

<div class="header">
    <div>
        <div class="h1">⬡ BROODFORGE</div>
        <h1>{title.upper()}</h1>
        <div class="subtitle">{display_name} ({username})</div>
    </div>
    <div class="meta">
        Generated: {generated_at[:19].replace("T", " ")} UTC<br>
        Services: {len(services)}
    </div>
</div>

<div class="security-notice">
    <strong>⚠ Security notice:</strong>
    This document contains your account credentials. Store it in your personal
    password manager immediately. Do not forward via unencrypted email or chat.
    Shred printed copies once saved.
</div>

{cards_html}

{zk_notice}

<div class="footer">
    <span>Broodforge User Registry — generated by forge-onboard-user.sh</span>
    <span>CONFIDENTIAL — {display_name}</span>
</div>

</body>
</html>"""


# ---------------------------------------------------------------------------
# Plain-text fallback
# ---------------------------------------------------------------------------

def _render_plaintext(data: dict) -> str:
    username     = data.get("username", "")
    display_name = data.get("display_name", username)
    generated_at = data.get("generated_at", "")
    services     = data.get("services", {})
    lines = [
        "=" * 70,
        f"  BROODFORGE ONBOARDING PACKAGE — {display_name.upper()}",
        f"  Generated: {generated_at}",
        "  Keep this document secure. Store in your password manager.",
        "=" * 70, "",
    ]
    for svc, creds in services.items():
        lines += [
            f"  ── Service: {svc} ──",
            f"  Username    : {username}",
            f"  Password    : {creds.get('password', '')}",
            f"  TOTP secret : {creds.get('totp_secret', '')}",
            f"  TOTP URI    : {creds.get('totp_uri', '')}",
            "",
        ]
    lines += ["=" * 70]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate an HTML onboarding package (+ optional PDF) from credential JSON on stdin"
    )
    parser.add_argument("--output", required=True,
                        help="Output path for the HTML file (e.g. alice-onboarding.html)")
    parser.add_argument("--also-pdf", action="store_true",
                        help="Also write a PDF alongside the HTML (requires weasyprint)")
    args = parser.parse_args(argv)

    # Read credential JSON from stdin
    raw = sys.stdin.read()
    if not raw.strip():
        print("[onboarding-pdf] ERROR: no input on stdin", file=sys.stderr)
        return 1
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"[onboarding-pdf] ERROR: invalid JSON: {exc}", file=sys.stderr)
        return 1

    output_path = Path(args.output).with_suffix(".html")

    # Build QR code map
    qr_map = {}
    if _QRCODE_AVAILABLE:
        for svc_name, creds in data.get("services", {}).items():
            uri = creds.get("totp_uri", "")
            if uri:
                try:
                    qr_map[svc_name] = _qr_png_b64(uri)
                except Exception as exc:
                    print(f"[onboarding-pdf] WARN: QR for {svc_name} failed: {exc}",
                          file=sys.stderr)
    else:
        print(
            "[onboarding-pdf] WARN: qrcode/pillow not installed — QR codes omitted.\n"
            "  Install: pip install \"qrcode[pil]\"",
            file=sys.stderr,
        )

    # Always write HTML (primary format)
    html = _render_html(data, qr_map)
    output_path.write_text(html, encoding="utf-8")
    print(f"[onboarding-pdf] HTML written: {output_path}")
    print(f"[onboarding-pdf] Open in any browser to view; use browser Print → Save as PDF if needed.")

    # Optional PDF step
    rc = 0
    if args.also_pdf:
        if not _WEASYPRINT_AVAILABLE:
            print(
                "[onboarding-pdf] WARN: --also-pdf requested but weasyprint not installed.\n"
                "  Install: pip install weasyprint",
                file=sys.stderr,
            )
            rc = 2
        else:
            try:
                pdf_path = output_path.with_suffix(".pdf")
                _weasyprint.HTML(string=html).write_pdf(str(pdf_path))
                print(f"[onboarding-pdf] PDF also written: {pdf_path}")
            except Exception as exc:
                print(f"[onboarding-pdf] WARN: weasyprint failed: {exc}", file=sys.stderr)
                rc = 2

    return rc


if __name__ == "__main__":
    sys.exit(main())
