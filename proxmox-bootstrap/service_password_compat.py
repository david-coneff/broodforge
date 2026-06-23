#!/usr/bin/env python3
"""
service_password_compat.py — Service credential format compatibility (Phase 1.F.8).

When a service deployment phase fails with an authentication or credential-related
error, this module:
  1. Detects that the failure is credential-format-related (e.g. service rejects '.')
  2. Determines the required password format from service-catalog.yaml metadata
  3. Regenerates the credential in the compatible format via passphrase.py
  4. Records the service restriction in service-catalog metadata for future deployments
  5. Returns the new credential so the calling phase can retry

Shell integration:
  CREDENTIAL_COMPAT_SH — bash library embedded in spawn/forge phase scripts.
  Wraps credential-dependent ansible/service commands with automatic format retry.

Known service restrictions (auto-populated from service-catalog.yaml password_format
fields; extend via record_service_restriction()):
  - Services with password_format: alphanumeric must use letters + digits only,
    no periods, underscores, or special characters.

Stdlib only.
"""

import re
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Credential formats
# ---------------------------------------------------------------------------

FORMAT_DEFAULT      = "default"      # Capital.word.phrase.N — may contain '.'
FORMAT_ALPHANUMERIC = "alphanumeric"  # Letters + digits only; no punctuation

# Known error patterns that indicate a password format incompatibility.
# Each entry: (regex_pattern, detected_format_required)
CREDENTIAL_FAILURE_PATTERNS: list[tuple[str, str]] = [
    # PostgreSQL rejects passwords with certain special characters via psql -c
    (r"psql.*authentication failed", FORMAT_ALPHANUMERIC),
    (r"FATAL:.*password authentication failed", FORMAT_ALPHANUMERIC),
    # Common "invalid password" errors from services that only accept alnum
    (r"invalid password.*character", FORMAT_ALPHANUMERIC),
    (r"password.*contains.*invalid.*character", FORMAT_ALPHANUMERIC),
    (r"credential.*rejected.*special", FORMAT_ALPHANUMERIC),
    # Ansible vault/become password errors (usually format-agnostic but caught here)
    (r"Failed to connect to the host.*Authentication failure", FORMAT_ALPHANUMERIC),
]


# ---------------------------------------------------------------------------
# Restriction detection
# ---------------------------------------------------------------------------

@dataclass
class CompatFinding:
    """Result of analysing an error message for credential format incompatibility."""
    service_name: str
    error_message: str
    detected: bool                     = False
    required_format: str               = FORMAT_DEFAULT
    confidence: str                    = "LOW"    # LOW | MEDIUM | HIGH
    pattern_matched: Optional[str]     = None


def detect_credential_failure(
    service_name:  str,
    error_message: str,
) -> CompatFinding:
    """
    Analyse an error message to determine if it indicates a credential format problem.

    Returns a CompatFinding. If detected=True, required_format is the format
    the service needs and the caller should regenerate the credential.
    """
    finding = CompatFinding(service_name=service_name, error_message=error_message)
    lower   = error_message.lower()

    for pattern, required_format in CREDENTIAL_FAILURE_PATTERNS:
        if re.search(pattern, lower, re.IGNORECASE):
            finding.detected        = True
            finding.required_format = required_format
            finding.confidence      = "MEDIUM"
            finding.pattern_matched = pattern
            return finding

    # Heuristic: if error mentions "password" and a punctuation character
    if "password" in lower and re.search(r"[.!@#$%^&*()\[\]{}<>_|`~]", lower):
        finding.detected        = True
        finding.required_format = FORMAT_ALPHANUMERIC
        finding.confidence      = "LOW"
        finding.pattern_matched = "heuristic: password + special-char in error"

    return finding


# ---------------------------------------------------------------------------
# Service catalog integration
# ---------------------------------------------------------------------------

def load_service_password_formats(catalog_path: str) -> dict[str, str]:
    """
    Parse service-catalog.yaml and return {service_name: password_format}.

    Only services with an explicit password_format field are included.
    Services without the field default to FORMAT_DEFAULT at call time.
    """
    formats: dict[str, str] = {}
    try:
        text = Path(catalog_path).read_text(encoding="utf-8")
    except OSError:
        return formats

    current_name: Optional[str] = None
    for line in text.splitlines():
        stripped = line.strip()
        # Match "- name: svc" or "name: svc"
        if re.match(r"^-?\s*name\s*:", stripped):
            current_name = re.split(r"name\s*:", stripped, maxsplit=1)[1].strip()
        elif stripped.startswith("password_format:") and current_name:
            fmt = stripped.split(":", 1)[1].strip()
            if fmt in (FORMAT_DEFAULT, FORMAT_ALPHANUMERIC):
                formats[current_name] = fmt
    return formats


def service_requires_alphanumeric(
    service_name:  str,
    catalog_path:  str = "service-catalog.yaml",
) -> bool:
    """Return True if this service is declared to require alphanumeric-only passwords."""
    formats = load_service_password_formats(catalog_path)
    return formats.get(service_name, FORMAT_DEFAULT) == FORMAT_ALPHANUMERIC


def record_service_restriction(
    service_name:  str,
    catalog_path:  str = "service-catalog.yaml",
) -> bool:
    """
    Add or update password_format: alphanumeric for a service in service-catalog.yaml.

    Called after a credential failure confirms that a service rejects the default
    passphrase format. Returns True if the file was updated, False otherwise.
    """
    try:
        text = Path(catalog_path).read_text(encoding="utf-8")
    except OSError:
        return False

    lines       = text.splitlines()
    result      = []
    in_service  = False
    found       = False

    for _i, line in enumerate(lines):
        stripped = line.strip()

        # Detect start of target service block ("  - name: svc_name")
        if re.match(r"^-?\s*name\s*:", stripped):
            block_name = re.split(r"name\s*:", stripped, maxsplit=1)[1].strip()
            if block_name == service_name:
                in_service = True
            else:
                if in_service and not found:
                    # We've passed our service without finding password_format — inject it
                    # Insert before this next service entry
                    result.append(f"    password_format: {FORMAT_ALPHANUMERIC}")
                    found = True
                in_service = False

        if in_service and stripped.startswith("password_format:"):
            # Update existing field
            indent = len(line) - len(line.lstrip())
            result.append(" " * indent + f"password_format: {FORMAT_ALPHANUMERIC}")
            found = True
            continue

        result.append(line)

    # If service was the last block in the file
    if in_service and not found:
        result.append(f"    password_format: {FORMAT_ALPHANUMERIC}")
        found = True

    if not found:
        return False

    Path(catalog_path).write_text("\n".join(result) + "\n", encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# Credential regeneration
# ---------------------------------------------------------------------------

def regenerate_credential_alphanumeric(service_name: str) -> str:
    """
    Generate an alphanumeric-only credential for a service known to reject passphrases.

    Delegates to lib/passphrase.py if available. Falls back to a simple
    alphanumeric token (24 chars) using secrets if passphrase.py is not importable.
    """
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
        from passphrase import generate_alphanumeric  # type: ignore
        return generate_alphanumeric()
    except ImportError:
        import string
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(24))


# ---------------------------------------------------------------------------
# Bash library (embedded in generated spawn / forge phase scripts)
# ---------------------------------------------------------------------------

CREDENTIAL_COMPAT_SH = r"""
# ---------------------------------------------------------------------------
# Credential format compatibility retry — 1.F.8
# ---------------------------------------------------------------------------
# Wraps a deployment command with automatic password-format retry.
# Usage:
#   with_credential_compat SERVICE_NAME KEEPASS_PATH COMMAND...
#
# If COMMAND fails and the error looks like a password format rejection,
# a new alphanumeric credential is generated, stored in KeePass, and the
# command is retried once with the updated credential.
#
# Requires: kdbx_get / kdbx_set functions from forge-keepass-gate.sh.
# ---------------------------------------------------------------------------

_detect_credential_failure() {
  local output="$1"
  echo "$output" | grep -qiE \
    "authentication failed|password.*invalid.*char|credential.*rejected|FATAL.*password"
}

with_credential_compat() {
  local service_name="$1"
  local keepass_path="$2"
  shift 2
  local cmd=("$@")

  local output
  output=$("${cmd[@]}" 2>&1)
  local rc=$?

  if [ "$rc" -eq 0 ]; then
    echo "$output"
    return 0
  fi

  # Check if this looks like a credential format failure
  if _detect_credential_failure "$output"; then
    echo "[compat] Credential format failure detected for ${service_name}." >&2
    echo "[compat] Regenerating ${keepass_path} as alphanumeric..." >&2

    # Generate new alphanumeric credential
    local new_cred
    new_cred=$(python3 -c "
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath('$0')), '..', 'lib'))
try:
    from passphrase import generate_alphanumeric
    print(generate_alphanumeric())
except Exception:
    import secrets, string
    print(''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(24)))
" 2>/dev/null)

    if [ -z "$new_cred" ]; then
      echo "[compat] Failed to generate new credential — aborting retry." >&2
      echo "$output" >&2
      return "$rc"
    fi

    # Store in KeePass (requires keepassxc-cli + unlocked database)
    if command -v keepassxc-cli &>/dev/null && [ -n "${FORGE_KDBX_PATH:-}" ]; then
      printf '%s\n' "$KEEPASS_MASTER_PASSWORD" | \
        keepassxc-cli edit --password "$new_cred" "$FORGE_KDBX_PATH" "$keepass_path" 2>/dev/null \
        || printf '%s\n' "$KEEPASS_MASTER_PASSWORD" | \
           keepassxc-cli add --password "$new_cred" "$FORGE_KDBX_PATH" "$keepass_path" 2>/dev/null
      echo "[compat] New credential stored at KeePass path: ${keepass_path}" >&2
    else
      echo "[compat] KeePass CLI unavailable — new credential: ${new_cred}" >/dev/tty
    fi

    # Retry with new credential exported as SVCPASS for ansible/scripts to pick up
    export SVCPASS="$new_cred"
    echo "[compat] Retrying with alphanumeric credential..." >&2
    output=$("${cmd[@]}" 2>&1)
    rc=$?
    if [ "$rc" -eq 0 ]; then
      echo "[compat] Retry succeeded. Recording format restriction for ${service_name}." >&2
      python3 -c "
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath('$0')))
from service_password_compat import record_service_restriction
record_service_restriction('${service_name}')
" 2>/dev/null || true
    else
      echo "[compat] Retry also failed — format restriction may not be the root cause." >&2
    fi
  fi

  echo "$output"
  return "$rc"
}
"""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Service password compatibility tool")
    sub = ap.add_subparsers(dest="cmd")

    p_detect = sub.add_parser("detect", help="Detect credential failure in an error message")
    p_detect.add_argument("service_name")
    p_detect.add_argument("error_message")

    p_list = sub.add_parser("list", help="List password format overrides in service-catalog.yaml")
    p_list.add_argument("--catalog", default="service-catalog.yaml")

    p_record = sub.add_parser("record", help="Record alphanumeric restriction for a service")
    p_record.add_argument("service_name")
    p_record.add_argument("--catalog", default="service-catalog.yaml")

    args = ap.parse_args()

    if args.cmd == "detect":
        f = detect_credential_failure(args.service_name, args.error_message)
        print(json.dumps({
            "detected":        f.detected,
            "required_format": f.required_format,
            "confidence":      f.confidence,
            "pattern":         f.pattern_matched,
        }, indent=2))

    elif args.cmd == "list":
        formats = load_service_password_formats(args.catalog)
        for name, fmt in sorted(formats.items()):
            print(f"  {name}: {fmt}")

    elif args.cmd == "record":
        ok = record_service_restriction(args.service_name, args.catalog)
        print(f"[compat] {'Recorded' if ok else 'Failed to record'} restriction for {args.service_name}")

    else:
        ap.print_help()
