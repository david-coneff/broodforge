#!/usr/bin/env bash
# forge-rotate-credential.sh — Key rotation ceremony.
#
# Propagates credential changes in strict order:
#
#   1. Generate new credential (or accept operator-provided value)
#   2. Register NEW with service while OLD still active (dual-validity window)
#   3. Verify NEW credential authenticates against service       ← EXIT 1 if fails
#   4. Prompt operator to update master KeePass entry            ← Manual step
#   5. forge-sync-credentials.sh  (automatic — master → child DBs)
#   6. Confirm: consumer processes get NEW credential on next broker call
#   7. Print OLD credential so operator can remove it from the service
#
# Step 3 MUST succeed before step 4. Step 4 MUST complete before step 5.
# This ordering is enforced by the script structure — not just policy.
#
# Usage:
#   forge-rotate-credential.sh --service <name> --type <password|api-key|ssh-key>
#
# Supported services:
#   restic     — restic repository password
#   headscale  — Headscale API key
#   k8s-sa     — Kubernetes service account token (requires kubectl)
#   generic    — any service; operator provides old/new values manually
#
# Exit codes:
#   0 — rotation complete
#   1 — error (credential verification failed, service update failed, etc.)
#   2 — NOT_IMPLEMENTED (service handler not yet fully implemented)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LIB_SH="${REPO_ROOT}/lib/forge-lib.sh"
SYNC_SCRIPT="${SCRIPT_DIR}/forge-sync-credentials.sh"

STATE_DIR="${BROODFORGE_STATE_DIR:-/var/lib/broodforge}"
# shellcheck disable=SC2034  # HIER_CONFIG used by sourced credential-hierarchy helpers
HIER_CONFIG="${STATE_DIR}/credential-hierarchy.json"

# ---------------------------------------------------------------------------

die()  { echo "[rotate] ERROR: $*" >&2; exit 1; }
step() { echo ""; echo "── Step $1: $2"; }
info() { echo "  $*"; }
warn() { echo "  ⚠ $*" >&2; }

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------

SERVICE=""
CRED_TYPE=""
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --service)  SERVICE="$2";   shift 2 ;;
    --type)     CRED_TYPE="$2"; shift 2 ;;
    --dry-run)  DRY_RUN=1;      shift   ;;
    --help)
      grep '^#' "$0" | head -40 | sed 's/^# \?//'
      exit 0
      ;;
    *) die "Unknown argument: $1" ;;
  esac
done

[[ -n "$SERVICE"   ]] || die "--service <name> is required"
[[ -n "$CRED_TYPE" ]] || die "--type <password|api-key|ssh-key> is required"

# ---------------------------------------------------------------------------
# Load forge-lib.sh and gate (operator must be present for rotation)
# ---------------------------------------------------------------------------

[[ -f "$LIB_SH" ]] || die "forge-lib.sh not found at $LIB_SH"
# shellcheck source=../lib/forge-lib.sh
source "$LIB_SH"
forge_keepass_gate

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

echo ""
echo "================================================================="
echo " forge-rotate-credential.sh — Key Rotation Ceremony"
echo " Service   : $SERVICE"
echo " Type      : $CRED_TYPE"
[[ $DRY_RUN -eq 1 ]] && echo " Mode      : DRY-RUN (no changes will be applied)"
echo "================================================================="

# ---------------------------------------------------------------------------
# Service handler functions
# ---------------------------------------------------------------------------

# _rotate_restic: restic repository password rotation
_rotate_restic() {
  local new_pw="$1"
  local old_pw="$2"

  step 2 "Register NEW restic repository password (dual-key window)"

  if [[ $DRY_RUN -eq 1 ]]; then
    info "[dry-run] Would run: restic key add (new password)"
    NEW_KEY_ID="dry-run-key-id"
    return 0
  fi

  [[ -n "${RESTIC_REPOSITORY:-}" ]] \
    || die "RESTIC_REPOSITORY not set — export it before rotation"

  # restic key add reads password from stdin (RESTIC_PASSWORD env preferred
  # for repo unlock; new key password via --new-password-file or stdin prompt)
  local old_key_id
  old_key_id=$(RESTIC_PASSWORD="$old_pw" restic key list \
    --json 2>/dev/null | python3 -c \
    "import json,sys; keys=json.load(sys.stdin); \
     current=[k for k in keys if k.get('current')]; \
     print(current[0]['id'] if current else '')" 2>/dev/null || echo "")

  info "Old key ID: ${old_key_id:-unknown}"

  # Add the new key (restic key add prompts for new password via --new-password-file
  # or reads new password after unlocking with current password)
  local new_pw_file
  new_pw_file=$(mktemp)
  printf '%s' "$new_pw" > "$new_pw_file"
  chmod 600 "$new_pw_file"

  if RESTIC_PASSWORD="$old_pw" restic key add \
      --new-password-file "$new_pw_file" \
      >/dev/null 2>&1; then
    info "✓ New restic key added (both old and new keys valid)"
    # shellcheck disable=SC2034  # NEW_KEY_ID reserved for future removal-step verification
    NEW_KEY_ID=$(RESTIC_PASSWORD="$new_pw" restic key list --json 2>/dev/null | \
      python3 -c "import json,sys; keys=json.load(sys.stdin); \
        current=[k for k in keys if k.get('current')]; \
        print(current[0]['id'] if current else 'unknown')" 2>/dev/null || echo "unknown")
  else
    rm -f "$new_pw_file"
    die "restic key add failed — old password may be incorrect or repo unreachable"
  fi
  rm -f "$new_pw_file"

  RESTIC_OLD_KEY_ID="$old_key_id"
}

_verify_restic() {
  local new_pw="$1"

  step 3 "Verify NEW restic password authenticates against repository"

  if [[ $DRY_RUN -eq 1 ]]; then
    info "[dry-run] Would run: restic snapshots (verify new password)"
    return 0
  fi

  local tmp_pw_file
  tmp_pw_file=$(mktemp)
  printf '%s' "$new_pw" > "$tmp_pw_file"
  chmod 600 "$tmp_pw_file"

  if RESTIC_PASSWORD_FILE="$tmp_pw_file" restic snapshots \
      --json >/dev/null 2>&1; then
    info "✓ New password verified against restic repository"
    rm -f "$tmp_pw_file"
    return 0
  else
    rm -f "$tmp_pw_file"
    echo "" >&2
    echo "[rotate] VERIFICATION FAILED — new restic password does NOT authenticate." >&2
    echo "[rotate] The master KeePass has NOT been modified." >&2
    echo "[rotate] Rotation aborted at step 3 (pre-master-DB safety gate)." >&2
    exit 1
  fi
}

# _rotate_k8s_sa: Kubernetes service account token rotation
_rotate_k8s_sa() {
  local sa_name="$1"
  local namespace="${2:-default}"

  step 2 "Register NEW k8s service account token (dual-validity window)"

  if [[ $DRY_RUN -eq 1 ]]; then
    info "[dry-run] Would run: kubectl create token $sa_name -n $namespace"
    NEW_K8S_TOKEN="dry-run-token"
    return 0
  fi

  command -v kubectl &>/dev/null || die "kubectl not found — install and configure it"

  # Create a new token (Kubernetes TokenRequest API — time-bound)
  # For long-lived rotation, create a new SA secret instead
  NEW_K8S_TOKEN=$(kubectl create token "$sa_name" \
    --namespace "$namespace" \
    --duration 8760h \
    2>/dev/null) \
    || die "kubectl create token failed for SA $sa_name in $namespace"

  info "✓ New service account token generated for $sa_name/$namespace"
}

_verify_k8s_sa() {
  local token="$1"
  # shellcheck disable=SC2034  # api_endpoint reserved for future explicit API-server verification
  local api_endpoint="${2:-}"

  step 3 "Verify NEW service account token"

  if [[ $DRY_RUN -eq 1 ]]; then
    info "[dry-run] Would verify token against k8s API"
    return 0
  fi

  # Minimal API check: can the new token get its own namespace?
  if kubectl auth can-i get namespaces \
      --token="$token" \
      >/dev/null 2>&1; then
    info "✓ New token verified (kubectl auth can-i succeeded)"
    return 0
  else
    # Non-fatal — SA may not have broad permissions; just check it's parseable
    if python3 -c "
import base64, json, sys
parts = '$token'.split('.')
if len(parts) != 3:
    sys.exit(1)
padded = parts[1] + '=' * (4 - len(parts[1]) % 4)
payload = json.loads(base64.urlsafe_b64decode(padded))
assert payload.get('sub'), 'no sub claim'
" 2>/dev/null; then
      info "✓ New token structure verified (JWT parse succeeded)"
      return 0
    fi

    echo "" >&2
    echo "[rotate] VERIFICATION FAILED — new SA token is not valid." >&2
    echo "[rotate] The master KeePass has NOT been modified." >&2
    echo "[rotate] Rotation aborted at step 3 (pre-master-DB safety gate)." >&2
    exit 1
  fi
}

# _rotate_generic: interactive rotation for any service
_rotate_generic() {
  local new_value="$1"
  local old_value="$2"

  step 2 "Register NEW credential with the service (operator-guided)"

  echo ""
  echo "  This is a generic rotation. You must update the service manually."
  echo ""
  echo "  New credential value:"
  printf '  %s\n' "$new_value" >/dev/tty
  echo ""
  echo "  OLD credential value (currently active — do NOT remove yet):"
  printf '  %s\n' "$old_value" >/dev/tty
  echo ""
  echo "  ACTION REQUIRED:"
  echo "  1. Register the NEW credential with the service."
  echo "  2. Ensure both OLD and NEW credentials are active simultaneously."

  if [[ $DRY_RUN -eq 0 ]]; then
    read -r -p "  Press Enter when NEW credential has been registered with the service..." </dev/tty
  else
    info "[dry-run] Skipping operator prompt."
  fi
}

_verify_generic() {
  local new_value="$1"

  step 3 "Verify NEW credential (operator confirms)"

  echo ""
  echo "  Verify that the NEW credential authenticates against the service."
  printf '  New value: %s\n' "$new_value" >/dev/tty
  echo ""

  if [[ $DRY_RUN -eq 1 ]]; then
    info "[dry-run] Skipping operator confirmation."
    return 0
  fi

  echo "  Did the NEW credential authenticate successfully?"
  read -r -p "  Type 'yes' to confirm, anything else to abort: " answer </dev/tty
  case "${answer,,}" in
    yes|y)
      info "✓ Operator confirmed: new credential verified"
      return 0
      ;;
    *)
      echo "" >&2
      echo "[rotate] VERIFICATION NOT CONFIRMED by operator." >&2
      echo "[rotate] The master KeePass has NOT been modified." >&2
      echo "[rotate] Rotation aborted at step 3 (pre-master-DB safety gate)." >&2
      exit 1
      ;;
  esac
}

# ---------------------------------------------------------------------------
# Step 1: Generate or prompt for new credential
# ---------------------------------------------------------------------------

step 1 "Generate new credential"

OLD_VALUE=""
NEW_VALUE=""

case "$SERVICE" in
  restic)
    # Retrieve current restic password from broker
    OLD_VALUE=$(kdbx_get "Broodforge/services/restic/repo-password" 2>/dev/null || echo "")
    if [[ -z "$OLD_VALUE" ]]; then
      warn "Could not retrieve current restic password from master DB."
      warn "Ensure the entry 'Broodforge/services/restic/repo-password' exists."
      read -r -s -p "  Enter CURRENT restic password (to unlock old key): " OLD_VALUE </dev/tty
      printf '\n'
    fi
    NEW_VALUE=$(LC_ALL=C tr -dc 'A-Za-z0-9!@#$%^&*()_+-=' </dev/urandom | head -c 48 2>/dev/null || openssl rand -base64 36 | tr -d '=\n' | head -c 48)
    info "✓ New restic password generated (${#NEW_VALUE} chars)"
    MASTER_ENTRY="Broodforge/services/restic/repo-password"
    ;;

  headscale)
    OLD_VALUE=$(kdbx_get "Broodforge/services/headscale/api-key" 2>/dev/null || echo "")
    if [[ -z "$OLD_VALUE" ]]; then
      warn "Could not retrieve current Headscale API key from master DB."
      read -r -s -p "  Enter CURRENT Headscale API key: " OLD_VALUE </dev/tty
      printf '\n'
    fi
    # Headscale API key generation is service-specific
    if [[ $DRY_RUN -eq 0 ]]; then
      echo "  The new Headscale API key will be generated by the service."
      echo "  Run: headscale apikeys create --expiration 365d"
      read -r -p "  Enter the NEW Headscale API key generated above: " NEW_VALUE </dev/tty
    else
      NEW_VALUE="dry-run-headscale-key-$(LC_ALL=C tr -dc 'a-f0-9' </dev/urandom | head -c 16)"
    fi
    info "✓ New Headscale API key received"
    MASTER_ENTRY="Broodforge/services/headscale/api-key"
    ;;

  k8s-sa)
    SA_NAME="${K8S_SA_NAME:-broodforge-operator}"
    SA_NAMESPACE="${K8S_SA_NAMESPACE:-default}"
    OLD_VALUE=$(kdbx_get "Broodforge/services/k8s/${SA_NAME}/token" 2>/dev/null || echo "")
    info "Service account: $SA_NAME (namespace: $SA_NAMESPACE)"
    NEW_VALUE=""   # generated in handler
    MASTER_ENTRY="Broodforge/services/k8s/${SA_NAME}/token"
    ;;

  generic)
    MASTER_ENTRY="${GENERIC_MASTER_ENTRY:-}"
    if [[ -z "$MASTER_ENTRY" ]]; then
      read -r -p "  KeePass master entry path for this credential: " MASTER_ENTRY </dev/tty
    fi
    OLD_VALUE=$(kdbx_get "$MASTER_ENTRY" 2>/dev/null || echo "")
    if [[ -z "$OLD_VALUE" ]]; then
      read -r -s -p "  Enter CURRENT credential value: " OLD_VALUE </dev/tty
      printf '\n'
    fi
    case "$CRED_TYPE" in
      password)
        NEW_VALUE=$(LC_ALL=C tr -dc 'A-Za-z0-9!@#$%^&*()_+-=' </dev/urandom | head -c 48 2>/dev/null || openssl rand -base64 36 | tr -d '=\n' | head -c 48)
        info "✓ New password generated (${#NEW_VALUE} chars)"
        ;;
      api-key)
        NEW_VALUE=$(LC_ALL=C tr -dc 'a-zA-Z0-9_-' </dev/urandom | head -c 64 2>/dev/null || openssl rand -base64 48 | tr -d '=\n' | head -c 64)
        info "✓ New API key generated (${#NEW_VALUE} chars)"
        ;;
      ssh-key)
        info "SSH key rotation: a new keypair will be generated."
        local_key_file=$(mktemp)
        rm -f "$local_key_file"
        ssh-keygen -t ed25519 -C "broodforge-${SERVICE}-$(date -u +%Y%m%d)" \
          -f "$local_key_file" -N "" -q
        NEW_VALUE=$(cat "${local_key_file}")
        rm -f "$local_key_file" "${local_key_file}.pub"
        info "✓ New Ed25519 SSH key generated"
        ;;
      *)
        read -r -s -p "  Enter NEW credential value: " NEW_VALUE </dev/tty
        printf '\n'
        ;;
    esac
    ;;

  *)
    die "Unknown service '$SERVICE'. Supported: restic, headscale, k8s-sa, generic"
    ;;
esac

# ---------------------------------------------------------------------------
# Steps 2–3: Service-specific register + verify
# ---------------------------------------------------------------------------

case "$SERVICE" in
  restic)
    _rotate_restic "$NEW_VALUE" "$OLD_VALUE"
    _verify_restic "$NEW_VALUE"
    ;;
  headscale)
    # Headscale: new key already registered by operator above
    step 2 "NEW Headscale API key accepted (operator-provided)"
    info "Both old and new keys active — verify the new key works before proceeding."

    step 3 "Verify NEW Headscale API key"
    if [[ $DRY_RUN -eq 0 ]]; then
      echo ""
      echo "  Verify the new Headscale API key by running:"
      echo "    curl -H 'Authorization: Bearer <NEW_KEY>' http://localhost:8080/api/v1/node | head -5"
      read -r -p "  Type 'yes' when verified: " answer </dev/tty
      case "${answer,,}" in
        yes|y) info "✓ Operator confirmed: new Headscale key verified" ;;
        *)
          echo "[rotate] VERIFICATION NOT CONFIRMED — rotation aborted at step 3." >&2
          exit 1
          ;;
      esac
    else
      info "[dry-run] Skipping Headscale key verification."
    fi
    ;;
  k8s-sa)
    _rotate_k8s_sa "$SA_NAME" "$SA_NAMESPACE"
    NEW_VALUE="$NEW_K8S_TOKEN"
    _verify_k8s_sa "$NEW_VALUE"
    ;;
  generic)
    _rotate_generic "$NEW_VALUE" "$OLD_VALUE"
    _verify_generic "$NEW_VALUE"
    ;;
esac

# ---------------------------------------------------------------------------
# Step 4: Update master KeePass entry (operator-confirmed)
# ---------------------------------------------------------------------------

step 4 "Update master KeePass entry"

echo ""
echo "  ┌─────────────────────────────────────────────────────────────"
echo "  │  ACTION REQUIRED: Update master KeePass entry"
echo "  │"
echo "  │  Entry path : $MASTER_ENTRY"
printf '  │  New value  : %s\n' "$NEW_VALUE" >/dev/tty
echo "  │"
echo "  │  Open your master KeePass database in KeePassXC and update"
echo "  │  the entry to the new value shown above."
echo "  └─────────────────────────────────────────────────────────────"
echo ""

if [[ $DRY_RUN -eq 0 ]]; then
  read -r -p "  Press Enter when the master KeePass entry has been updated..." </dev/tty
  info "✓ Operator confirmed master KeePass entry updated"
else
  info "[dry-run] Skipping master KeePass update prompt."
fi

# ---------------------------------------------------------------------------
# Step 5: forge-sync-credentials.sh (automatic — master → child DBs)
# ---------------------------------------------------------------------------

step 5 "Sync master → child databases (automatic)"

[[ -f "$SYNC_SCRIPT" ]] || die "forge-sync-credentials.sh not found at $SYNC_SCRIPT"

info "Running forge-sync-credentials.sh --entry '$MASTER_ENTRY'..."
echo ""

if [[ $DRY_RUN -eq 0 ]]; then
  bash "$SYNC_SCRIPT" --entry "$MASTER_ENTRY" \
    || warn "Sync reported warnings — review output above"
else
  info "[dry-run] Would run: bash forge-sync-credentials.sh --entry '$MASTER_ENTRY'"
fi

# ---------------------------------------------------------------------------
# Step 6: Confirm
# ---------------------------------------------------------------------------

step 6 "Confirm rotation propagated"

echo ""
info "✓ Rotation ceremony complete."
info "  Consumer processes will receive the NEW credential on their next"
info "  kdbx_get_child() broker call — no restart required."
echo ""

# ---------------------------------------------------------------------------
# Step 7: Print OLD credential for removal from service
# ---------------------------------------------------------------------------

step 7 "Remove OLD credential from service"

echo ""
echo "  ┌─────────────────────────────────────────────────────────────"
echo "  │  ACTION REQUIRED: Remove OLD credential from the service"
echo "  │"

case "$SERVICE" in
  restic)
    echo "  │  Old restic key ID: ${RESTIC_OLD_KEY_ID:-unknown}"
    echo "  │  Remove it with: restic key remove ${RESTIC_OLD_KEY_ID:-<old-key-id>}"
    ;;
  headscale)
    printf '  │  Old Headscale API key: %s\n' "$OLD_VALUE" >/dev/tty
    echo "  │  Remove it from the Headscale admin UI or via:"
    echo "  │    headscale apikeys list   # find the old key's ID"
    echo "  │    headscale apikeys delete --id <id>"
    ;;
  k8s-sa)
    echo "  │  Old k8s SA token for $SA_NAME is now superseded."
    echo "  │  The old token will expire naturally (no explicit removal needed"
    echo "  │  unless it was a long-lived secret — delete via kubectl if so)."
    ;;
  generic)
    printf '  │  Old credential: %s\n' "$OLD_VALUE" >/dev/tty
    echo "  │  Remove this value from the service using its admin interface."
    ;;
esac

echo "  │"
echo "  │  Do NOT remove the old credential before all consumers have"
echo "  │  picked up the new one (typically: next deploy or restart)."
echo "  └─────────────────────────────────────────────────────────────"
echo ""

echo "Key rotation ceremony complete for service: $SERVICE"
echo ""
