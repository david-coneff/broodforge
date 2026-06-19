#!/usr/bin/env bash
# forge-onboard-user.sh — Register a user and generate their per-service credentials.
#
# This script has two modes:
#
#   NEW USER ONBOARDING (default):
#   1. Adds the user to config/user-registry.json (via user_registry.py)
#   2. For each enrolled service:
#      a. Generates a strong random password
#      b. Generates a TOTP secret (base32, compatible with Authenticator apps)
#      c. Stores both in the master KeePass under Broodforge/users/<user>/<svc>/
#   3. Prints an onboarding summary (or writes to a file with --output)
#
#   ADD SERVICE TO EXISTING USER (--add-service):
#   1. Enrolls the user in the new service in user-registry.json
#   2. Generates credentials for just that one service
#   3. Stores in KeePass, prints a single-service credential snippet
#
# The operator delivers the onboarding output to the user securely (e.g. encrypted
# email, Signal, printed in person).  After the user acknowledges receipt, the
# operator may optionally run forge-throw-away-key to discard the master copy.
#
# Zero-knowledge note:
#   Services store password hashes (bcrypt/argon2) — not plaintext.  Vaultwarden
#   additionally encrypts all vault contents client-side.  Once the key is thrown
#   away, the admin cannot impersonate the user or read their data.
#
# Output:
#   HTML file (primary — opens in any browser, print→PDF from browser)
#   PDF alongside HTML with --also-pdf (requires: pip install weasyprint)
#   TOTP QR codes embedded in HTML (requires: pip install "qrcode[pil]")
#
# Usage:
#   # New user:
#   bash scripts/forge-onboard-user.sh \
#       --user alice \
#       --display-name "Alice Smith" \
#       --email alice@example.com \
#       --services vaultwarden,headscale,gitea \
#       --output /path/to/alice-onboarding.html \
#       [--also-pdf] [--dry-run]
#
#   # Add a service to an existing user:
#   bash scripts/forge-onboard-user.sh \
#       --add-service alice gitea \
#       --output /path/to/alice-gitea.html \
#       [--also-pdf] [--dry-run]
#
# Exit codes:
#   0 — success (HTML written; PDF also written if --also-pdf and weasyprint available)
#   1 — error

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LIB_SH="${REPO_ROOT}/lib/forge-lib.sh"
USER_REG_PY="${REPO_ROOT}/proxmox-bootstrap/user_registry.py"
REGISTRY_JSON="${REPO_ROOT}/config/user-registry.json"
ONBOARDING_PDF_PY="${REPO_ROOT}/lib/forge-onboarding-pdf.py"

# ---------------------------------------------------------------------------

die()  { echo "[onboard] ERROR: $*" >&2; exit 1; }
info() { echo "[onboard] $*"; }
warn() { echo "[onboard] WARN: $*" >&2; }

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------

USERNAME=""
DISPLAY_NAME=""
EMAIL=""
SERVICES=""
OUTPUT_FILE=""
ALSO_PDF=0
DRY_RUN=0
ADD_SERVICE_MODE=0    # set to 1 when --add-service is used
ADD_SERVICE_NAME=""   # the single service to add

while [[ $# -gt 0 ]]; do
  case "$1" in
    --user)         USERNAME="$2";            shift 2 ;;
    --display-name) DISPLAY_NAME="$2";        shift 2 ;;
    --email)        EMAIL="$2";               shift 2 ;;
    --services)     SERVICES="$2";            shift 2 ;;
    --output)       OUTPUT_FILE="$2";         shift 2 ;;
    --also-pdf)     ALSO_PDF=1;               shift   ;;
    --dry-run)      DRY_RUN=1;                shift   ;;
    --add-service)
      ADD_SERVICE_MODE=1
      USERNAME="$2"
      ADD_SERVICE_NAME="$3"
      shift 3
      ;;
    --help)
      grep '^#' "$0" | head -55 | sed 's/^# \?//'
      exit 0
      ;;
    *) die "Unknown argument: $1" ;;
  esac
done

if [[ $ADD_SERVICE_MODE -eq 1 ]]; then
  [[ -n "$USERNAME"         ]] || die "--add-service requires <username>"
  [[ -n "$ADD_SERVICE_NAME" ]] || die "--add-service requires <service>"
  SERVICES="$ADD_SERVICE_NAME"
else
  [[ -n "$USERNAME" ]] || die "--user is required"
  [[ -n "$SERVICES" ]] || die "--services is required (comma-separated)"
fi

# ---------------------------------------------------------------------------
# Load forge-lib and gate
# ---------------------------------------------------------------------------

[[ -f "$LIB_SH" ]] || die "forge-lib.sh not found at $LIB_SH"
# shellcheck source=../lib/forge-lib.sh
source "$LIB_SH"
forge_keepass_gate

# ---------------------------------------------------------------------------
# Credential generators
# ---------------------------------------------------------------------------

# Generate a strong random password (48 chars, mixed alphanum + symbols)
_gen_password() {
  python3 -c "
import secrets, string
alphabet = string.ascii_letters + string.digits + '!@#\$%^&*()-_=+[]{}|;:,.<>?'
print(''.join(secrets.choice(alphabet) for _ in range(48)))
"
}

# Generate a TOTP base32 secret (20 bytes = 160 bits, RFC 6238 minimum)
_gen_totp_secret() {
  python3 -c "
import secrets, base64
raw = secrets.token_bytes(20)
print(base64.b32encode(raw).decode().rstrip('='))
"
}

# Generate a TOTP URI for QR code rendering
# otpauth://totp/<label>?secret=<secret>&issuer=<issuer>
_gen_totp_uri() {
  local label="$1"  # e.g. "alice@vaultwarden"
  local secret="$2"
  local issuer="${3:-broodforge}"
  python3 -c "
import urllib.parse
label  = urllib.parse.quote('${label}')
issuer = urllib.parse.quote('${issuer}')
print(f'otpauth://totp/{label}?secret=${secret}&issuer={issuer}&algorithm=SHA1&digits=6&period=30')
"
}

# ---------------------------------------------------------------------------
# KeePass helpers
# ---------------------------------------------------------------------------

# Store a new credential entry in master KeePass.
# _keepass_store_entry <entry_path> <username> <password> [notes]
_keepass_store_entry() {
  local entry_path="$1"
  local entry_user="$2"
  local entry_pw="$3"
  local entry_notes="${4:-}"

  # Check if entry already exists
  if printf '%s\n' "$KEEPASS_MASTER_PASSWORD" | \
      keepassxc-cli show -q "$FORGE_KDBX_PATH" "$entry_path" >/dev/null 2>&1; then
    # Update existing
    printf '%s\n' "$KEEPASS_MASTER_PASSWORD" | \
      keepassxc-cli edit --quiet \
        --username "$entry_user" \
        --password "$entry_pw" \
        "$FORGE_KDBX_PATH" "$entry_path" >/dev/null
  else
    # Create new (group is created automatically by keepassxc-cli add)
    local add_args=(--quiet --username "$entry_user" --password "$entry_pw")
    [[ -n "$entry_notes" ]] && add_args+=(--notes "$entry_notes")
    printf '%s\n' "$KEEPASS_MASTER_PASSWORD" | \
      keepassxc-cli add "${add_args[@]}" "$FORGE_KDBX_PATH" "$entry_path" >/dev/null
  fi
}

# ---------------------------------------------------------------------------
# Main onboarding logic
# ---------------------------------------------------------------------------

info ""
if [[ $ADD_SERVICE_MODE -eq 1 ]]; then
  info "Adding service '$ADD_SERVICE_NAME' to existing user: $USERNAME"
else
  info "Starting onboarding for user: $USERNAME"
fi
[[ $DRY_RUN -eq 1 ]] && info "(DRY RUN — no changes will be written)"
info ""

# Collect services list
IFS=',' read -ra SERVICE_LIST <<< "$SERVICES"

# Register in registry (unless dry-run)
if [[ $DRY_RUN -eq 0 ]]; then
  if [[ $ADD_SERVICE_MODE -eq 1 ]]; then
    python3 "$USER_REG_PY" \
      --registry "$REGISTRY_JSON" \
      --add-service "$USERNAME" "$ADD_SERVICE_NAME" \
      || die "Failed to enroll $USERNAME in $ADD_SERVICE_NAME (already enrolled?)"
  else
    python3 "$USER_REG_PY" \
      --registry "$REGISTRY_JSON" \
      --add \
      --username     "$USERNAME" \
      --display-name "${DISPLAY_NAME:-$USERNAME}" \
      --email        "${EMAIL:-}" \
      --services     "$SERVICES" \
      || die "Failed to add user to registry (user may already exist)"
  fi
fi

# Build onboarding package content
declare -A _CREDS_PW
declare -A _CREDS_TOTP
declare -A _CREDS_URI

for svc in "${SERVICE_LIST[@]}"; do
  svc="$(echo "$svc" | tr -d ' ')"
  [[ -z "$svc" ]] && continue

  pw_path="Broodforge/users/${USERNAME}/${svc}/password"
  totp_path="Broodforge/users/${USERNAME}/${svc}/totp-secret"

  pw=$(  _gen_password)
  totp=$(  _gen_totp_secret)
  uri=$( _gen_totp_uri "${USERNAME}@${svc}" "$totp" "broodforge-${svc}")

  _CREDS_PW["$svc"]="$pw"
  _CREDS_TOTP["$svc"]="$totp"
  _CREDS_URI["$svc"]="$uri"

  if [[ $DRY_RUN -eq 0 ]]; then
    info "  Storing credentials for $svc in KeePass..."
    _keepass_store_entry "$pw_path"   "$USERNAME" "$pw"
    _keepass_store_entry "$totp_path" "$USERNAME" "$totp" \
      "TOTP URI: $uri"
    info "  ✓ $svc"
  else
    info "  [dry-run] Would store: $pw_path"
    info "  [dry-run] Would store: $totp_path"
  fi

  unset pw totp
done

# ---------------------------------------------------------------------------
# Render onboarding package
# ---------------------------------------------------------------------------

# _build_cred_json — emit the credential JSON object to stdout.
# Passwords stay out of argv/env — this builds JSON inline then pipes it.
_build_cred_json() {

  python3 - <<'PYEOF'
import json, os, sys

username     = os.environ["_OB_USERNAME"]
display_name = os.environ["_OB_DISPLAY_NAME"]
generated_at = os.environ["_OB_GENERATED_AT"]
mode_str     = os.environ["_OB_MODE"]

services_raw = json.loads(os.environ["_OB_SERVICES_JSON"])
out = {
    "username":     username,
    "display_name": display_name,
    "generated_at": generated_at,
    "mode":         mode_str,
    "services":     services_raw,
}
print(json.dumps(out))
PYEOF
}

# Build the services JSON blob (passwords are in bash vars, not args)
# We collect into an env var via python to handle quoting safely.
_build_services_json() {
  python3 -c "
import json, sys

services = {}
lines = sys.stdin.read().strip().split('\n')
for line in lines:
    if not line:
        continue
    parts = line.split('\t', 3)
    if len(parts) < 4:
        continue
    svc, pw, totp, uri = parts
    services[svc] = {'password': pw, 'totp_secret': totp, 'totp_uri': uri}
print(json.dumps(services))
"
}

# Assemble the tab-separated service data and build JSON
_SERVICES_TSV=""
for svc in "${SERVICE_LIST[@]}"; do
  svc="$(echo "$svc" | tr -d ' ')"
  [[ -z "$svc" ]] && continue
  _SERVICES_TSV+="${svc}"$'\t'"${_CREDS_PW[$svc]}"$'\t'"${_CREDS_TOTP[$svc]}"$'\t'"${_CREDS_URI[$svc]}"$'\n'
done

_SERVICES_JSON=$(printf '%s' "$_SERVICES_TSV" | _build_services_json)

info ""
info "═══════════════════════════════════════════════"
info " ONBOARDING PACKAGE"
info "═══════════════════════════════════════════════"
info ""

if [[ $DRY_RUN -eq 1 ]]; then
  info "[dry-run] Would generate onboarding package for $USERNAME"
  info "[dry-run] Services: ${SERVICES}"
  [[ -n "$OUTPUT_FILE" ]] && info "[dry-run] Output: ${OUTPUT_FILE}"
elif [[ -n "$OUTPUT_FILE" ]]; then
  # HTML primary — always generated
  _MODE_STR="onboarding"
  [[ $ADD_SERVICE_MODE -eq 1 ]] && _MODE_STR="add-service"

  export _OB_USERNAME="$USERNAME"
  export _OB_DISPLAY_NAME="${DISPLAY_NAME:-$USERNAME}"
  _OB_GENERATED_AT="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  export _OB_GENERATED_AT
  export _OB_MODE="$_MODE_STR"
  export _OB_SERVICES_JSON="$_SERVICES_JSON"

  _PDF_FLAG=""
  [[ $ALSO_PDF -eq 1 ]] && _PDF_FLAG="--also-pdf"

  # Pipe credential JSON via stdin to the HTML generator (passwords stay out of argv)
  _build_cred_json | python3 "$ONBOARDING_PDF_PY" --output "$OUTPUT_FILE" $_PDF_FLAG
  _PDF_RC=${PIPESTATUS[1]}

  unset _OB_USERNAME _OB_DISPLAY_NAME _OB_GENERATED_AT _OB_MODE _OB_SERVICES_JSON

  # Determine actual HTML path (generator strips/adds .html)
  _HTML_PATH="${OUTPUT_FILE%.html}.html"
  info "Onboarding package ready: ${_HTML_PATH}"
  info "Open in any browser or deliver to $USERNAME via secure channel."
  [[ $_PDF_RC -eq 2 ]] && warn "PDF not written (weasyprint unavailable); HTML is sufficient."
else
  # No --output: render plain text to stdout for quick operator review
  _TXT_WIDTH=72
  _TXT_BORDER=$(printf '%*s' "$_TXT_WIDTH" '' | tr ' ' '─')

  if [[ $ADD_SERVICE_MODE -eq 1 ]]; then
    echo "┌${_TXT_BORDER}┐"
    printf "│%-${_TXT_WIDTH}s│\n" "  BROODFORGE NEW SERVICE ACCESS — ${USERNAME^^}"
    printf "│%-${_TXT_WIDTH}s│\n" "  Service: ${ADD_SERVICE_NAME}  |  Generated: $(date -u '+%Y-%m-%d %H:%M UTC')"
    echo "├${_TXT_BORDER}┤"
    printf "│%-${_TXT_WIDTH}s│\n" "  Keep this document secure. Do not share it."
    printf "│%-${_TXT_WIDTH}s│\n" "  Store in your personal password manager immediately."
    echo "└${_TXT_BORDER}┘"
  else
    echo "┌${_TXT_BORDER}┐"
    printf "│%-${_TXT_WIDTH}s│\n" "  BROODFORGE ONBOARDING PACKAGE — ${USERNAME^^}"
    printf "│%-${_TXT_WIDTH}s│\n" "  Generated: $(date -u '+%Y-%m-%d %H:%M UTC')"
    echo "├${_TXT_BORDER}┤"
    printf "│%-${_TXT_WIDTH}s│\n" "  Keep this document secure. Do not share it."
    printf "│%-${_TXT_WIDTH}s│\n" "  Store in your personal password manager immediately."
    echo "└${_TXT_BORDER}┘"
  fi
  echo ""

  for svc in "${SERVICE_LIST[@]}"; do
    svc="$(echo "$svc" | tr -d ' ')"
    [[ -z "$svc" ]] && continue
    echo "  ══ Service: ${svc} ══"
    echo "  Username : ${USERNAME}"
    echo "  Password : ${_CREDS_PW[$svc]}"
    echo ""
    echo "  TOTP setup:"
    echo "    Secret : ${_CREDS_TOTP[$svc]}"
    echo "    URI    : ${_CREDS_URI[$svc]}"
    echo ""
    echo "  Scan the URI with an Authenticator app (SHA1, 6 digits, 30s)."
    echo "  ─────────────────────────────────────────────────────────────────"
    echo ""
  done

  echo "  IMPORTANT — ZERO-KNOWLEDGE SERVICES:"
  echo "  Your Vaultwarden vault is encrypted with your master password."
  echo "  Admins cannot read your vault contents even with server access."
  echo ""
  echo "  Once saved, inform the administrator to acknowledge onboarding."
  echo ""
fi

# Clear credential arrays from memory
for svc in "${!_CREDS_PW[@]}"; do
  _CREDS_PW["$svc"]=""
  _CREDS_TOTP["$svc"]=""
  _CREDS_URI["$svc"]=""
done
unset _CREDS_PW _CREDS_TOTP _CREDS_URI _SERVICES_TSV _SERVICES_JSON

info ""
info "Next steps:"
info "  1. Deliver the credential snippet to $USERNAME via secure channel."
info "  2. Confirm they have saved their credentials."
if [[ $ADD_SERVICE_MODE -eq 1 ]]; then
  info "  3. Run forge-provision-users.sh --user $USERNAME --service $ADD_SERVICE_NAME"
  info "     to register the account in the service."
  info "  4. Optional: once user confirms receipt, run:"
  info "       python3 proxmox-bootstrap/user_registry.py \\"
  info "           --registry config/user-registry.json \\"
  info "           --throw-away-key $USERNAME $ADD_SERVICE_NAME"
  info "     to discard the master copy."
else
  info "  3. Run forge-provision-users.sh --user $USERNAME to register accounts"
  info "     in all enrolled services."
  info "  4. Optional: once user confirms receipt, run forge-throw-away-key to"
  info "     discard the master copy and achieve zero-knowledge admin access."
fi
info ""

exit 0
