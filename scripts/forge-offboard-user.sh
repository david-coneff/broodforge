#!/usr/bin/env bash
# forge-offboard-user.sh — Remove a user from one or all broodforge services.
#
# Offboarding flow per user+service:
#   1. Delete service account (kubectl exec / admin API)
#   2. Delete KeePass credentials (password + totp-secret entries)
#      — skipped if key was already thrown away (key_thrown_away=true)
#   3. Remove service enrollment from user-registry.json
#
# When all services are offboarded, the user record is set to
# "archived" disposition (or removed entirely with --remove-from-registry).
#
# This script is the inverse of forge-onboard-user.sh + forge-provision-users.sh.
# It does NOT delete any user data on the service itself (e.g. git repos,
# Vaultwarden vault contents) — it only removes the account and credentials.
#
# Usage:
#   # Offboard from all services (sets disposition → archived):
#   bash scripts/forge-offboard-user.sh --user alice
#
#   # Offboard from a specific service only:
#   bash scripts/forge-offboard-user.sh --user alice --service vaultwarden
#
#   # Fully remove from registry after offboarding all services:
#   bash scripts/forge-offboard-user.sh --user alice --remove-from-registry
#
# Flags:
#   --user <username>          Required. User to offboard.
#   --service <name>           Offboard from this service only. Default: all.
#   --remove-from-registry     After offboarding, remove user record entirely.
#                              Default: sets disposition to "archived".
#   --dry-run                  Show what would happen; make no changes.
#   --yes                      Skip confirmation prompts.
#
# Exit codes:
#   0 — all targeted service accounts removed
#   1 — one or more removals failed

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LIB_SH="${REPO_ROOT}/lib/forge-lib.sh"
USER_REG_PY="${REPO_ROOT}/proxmox-bootstrap/user_registry.py"
REGISTRY_JSON="${REPO_ROOT}/config/user-registry.json"

# ---------------------------------------------------------------------------

die()  { echo "[offboard] ERROR: $*" >&2; exit 1; }
info() { echo "[offboard] $*"; }
warn() { echo "[offboard] WARN: $*" >&2; }

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------

USERNAME=""
TARGET_SERVICE="all"
REMOVE_FROM_REGISTRY=0
DRY_RUN=0
YES=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --user)                  USERNAME="$2";       shift 2 ;;
    --service)               TARGET_SERVICE="$2"; shift 2 ;;
    --remove-from-registry)  REMOVE_FROM_REGISTRY=1; shift ;;
    --dry-run)               DRY_RUN=1;           shift   ;;
    --yes)                   YES=1;               shift   ;;
    --help)
      grep '^#' "$0" | head -50 | sed 's/^# \?//'
      exit 0
      ;;
    *) die "Unknown argument: $1" ;;
  esac
done

[[ -n "$USERNAME" ]] || die "--user is required"

# ---------------------------------------------------------------------------
# Load forge-lib and gate
# ---------------------------------------------------------------------------

[[ -f "$LIB_SH" ]] || die "forge-lib.sh not found at $LIB_SH"
# shellcheck source=../lib/forge-lib.sh
source "$LIB_SH"
forge_keepass_gate

[[ -f "$REGISTRY_JSON" ]] || die "user-registry.json not found at $REGISTRY_JSON"

# ---------------------------------------------------------------------------
# Resolve services to offboard
# ---------------------------------------------------------------------------

export _OB_USERNAME="$USERNAME"
export _OB_TARGET="$TARGET_SERVICE"

mapfile -t _OFFBOARD_PLAN < <(
  python3 - "$REGISTRY_JSON" <<'PYEOF'
import json, sys, os

username = os.environ["_OB_USERNAME"]
target   = os.environ["_OB_TARGET"]

with open(sys.argv[1]) as f:
    data = json.load(f)

for user in data.get("users", []):
    if user["username"] == username:
        svcs = user.get("services", {})
        for svc, info in svcs.items():
            if target == "all" or target == svc:
                key_gone = info.get("key_thrown_away", False)
                print(f"{svc}\t{str(key_gone).lower()}\t{user.get('email','')}")
        break
else:
    print(f"ERROR:User not found: {username}", file=sys.stderr)
    sys.exit(1)
PYEOF
)

unset _OB_USERNAME _OB_TARGET

if (( ${#_OFFBOARD_PLAN[@]} == 0 )); then
  info "No services to offboard for ${USERNAME} (service: ${TARGET_SERVICE})."
  exit 0
fi

# ---------------------------------------------------------------------------
# Confirmation
# ---------------------------------------------------------------------------

info ""
info "Offboarding plan for: $USERNAME"
info "  Services:"
for line in "${_OFFBOARD_PLAN[@]}"; do
  IFS=$'\t' read -r svc key_gone email <<< "$line"
  if [[ "$key_gone" == "true" ]]; then
    info "    $svc  [key already thrown away — only service account deletion]"
  else
    info "    $svc  [will delete service account + KeePass credentials]"
  fi
done
if [[ $REMOVE_FROM_REGISTRY -eq 1 ]]; then
  info "  Post-offboard: REMOVE user record from registry"
else
  info "  Post-offboard: set disposition → archived"
fi
info ""

if [[ $DRY_RUN -eq 1 ]]; then
  info "[dry-run] No changes made."
  exit 0
fi

if [[ $YES -eq 0 ]]; then
  read -r -p "[offboard] Type 'yes' to proceed: " _CONFIRM
  [[ "$_CONFIRM" == "yes" ]] || { info "Aborted."; exit 0; }
fi

# ---------------------------------------------------------------------------
# Service adapters — account deletion
# ---------------------------------------------------------------------------

_offboard_vaultwarden() {
  local username="$1"
  local email="$2"

  local VW_POD VW_ADMIN_TOKEN
  VW_POD=$(kubectl get pod -l app=vaultwarden -o jsonpath='{.items[0].metadata.name}' 2>/dev/null) \
    || { warn "  vaultwarden pod not found — manual deletion required"; return 1; }

  VW_ADMIN_TOKEN=$(kubectl get secret vaultwarden-admin-token \
    -o jsonpath='{.data.token}' 2>/dev/null | base64 -d 2>/dev/null) \
    || { warn "  vaultwarden admin token not found — manual deletion required"; return 1; }

  # Look up user UUID by email first
  local USER_UUID
  USER_UUID=$(kubectl exec "$VW_POD" -- curl -sf \
    -H "Authorization: Bearer ${VW_ADMIN_TOKEN}" \
    "http://localhost:8080/admin/users" 2>/dev/null \
    | python3 -c "
import json, sys
users = json.load(sys.stdin)
for u in users:
    if u.get('Email','').lower() == '${email}'.lower():
        print(u['Id'])
        break
" 2>/dev/null) || true

  if [[ -z "$USER_UUID" ]]; then
    warn "  vaultwarden: user ${email} not found — may already be removed"
    return 0
  fi

  kubectl exec "$VW_POD" -- curl -sf -X DELETE \
    -H "Authorization: Bearer ${VW_ADMIN_TOKEN}" \
    "http://localhost:8080/admin/users/${USER_UUID}" >/dev/null \
    && info "  ✓ vaultwarden: deleted ${username} (${email})" \
    || { warn "  vaultwarden: deletion failed for ${username}"; return 1; }
}

_offboard_headscale() {
  local username="$1"

  local HEADSCALE_POD
  HEADSCALE_POD=$(kubectl get pod -l app=headscale -o jsonpath='{.items[0].metadata.name}' 2>/dev/null) \
    || { warn "  headscale pod not found — manual deletion required"; return 1; }

  kubectl exec "$HEADSCALE_POD" -- headscale namespaces delete "$username" >/dev/null 2>&1 \
    && info "  ✓ headscale: namespace deleted for ${username}" \
    || { warn "  headscale: could not delete namespace for ${username} (may not exist)"; return 0; }
}

_offboard_gitea() {
  local username="$1"

  local GITEA_POD
  GITEA_POD=$(kubectl get pod -l app=gitea -o jsonpath='{.items[0].metadata.name}' 2>/dev/null) \
    || { warn "  gitea pod not found — manual deletion required"; return 1; }

  kubectl exec "$GITEA_POD" -- gitea admin user delete --username "$username" >/dev/null 2>&1 \
    && info "  ✓ gitea: deleted ${username}" \
    || { warn "  gitea: could not delete ${username} (may not exist or has repos)"; return 1; }
}

_offboard_service_account() {
  local service="$1"
  local username="$2"
  local email="$3"

  case "$service" in
    vaultwarden) _offboard_vaultwarden "$username" "$email" ;;
    headscale)   _offboard_headscale   "$username" ;;
    gitea)       _offboard_gitea       "$username" ;;
    *)
      warn "  No offboard adapter for '${service}' — account must be deleted manually."
      warn "  Add _offboard_${service}() to forge-offboard-user.sh to automate this."
      return 0  # Not fatal
      ;;
  esac
}

# ---------------------------------------------------------------------------
# KeePass credential deletion
# ---------------------------------------------------------------------------

_keepass_rm_entry_if_exists() {
  local entry_path="$1"
  if printf '%s\n' "$KEEPASS_MASTER_PASSWORD" | \
      keepassxc-cli show -q "$FORGE_KDBX_PATH" "$entry_path" >/dev/null 2>&1; then
    printf '%s\n' "$KEEPASS_MASTER_PASSWORD" | \
      keepassxc-cli rm --quiet "$FORGE_KDBX_PATH" "$entry_path" >/dev/null 2>&1 \
      && info "  ✓ Deleted KeePass: $entry_path" \
      || { warn "  Failed to delete KeePass: $entry_path"; return 1; }
  else
    info "  (KeePass entry not found — already deleted or never created: $entry_path)"
  fi
}

# ---------------------------------------------------------------------------
# Main offboarding loop
# ---------------------------------------------------------------------------

_ALL_OK=1

for line in "${_OFFBOARD_PLAN[@]}"; do
  IFS=$'\t' read -r svc key_gone email <<< "$line"

  info ""
  info "Offboarding ${USERNAME} from ${svc}..."

  # Step 1: Delete service account
  if ! _offboard_service_account "$svc" "$USERNAME" "${email:-}"; then
    warn "  Service account deletion failed for ${USERNAME}/${svc}."
    warn "  Continuing with credential cleanup — service may need manual cleanup."
    _ALL_OK=0
  fi

  # Step 2: Delete KeePass credentials (skip if key was already thrown away)
  if [[ "$key_gone" == "false" ]]; then
    pw_path="Broodforge/users/${USERNAME}/${svc}/password"
    totp_path="Broodforge/users/${USERNAME}/${svc}/totp-secret"
    _keepass_rm_entry_if_exists "$pw_path"   || _ALL_OK=0
    _keepass_rm_entry_if_exists "$totp_path" || _ALL_OK=0
  else
    info "  KeePass credentials already thrown away — skipping KeePass deletion."
  fi

  # Step 3: Remove service enrollment from registry
  python3 "$USER_REG_PY" \
    --registry "$REGISTRY_JSON" \
    --remove-service "$USERNAME" "$svc" \
    --yes >/dev/null \
    && info "  ✓ Registry: removed ${USERNAME}/${svc} enrollment" \
    || { warn "  Registry update failed for ${USERNAME}/${svc}"; _ALL_OK=0; }
done

# ---------------------------------------------------------------------------
# Post-offboard: update user record
# ---------------------------------------------------------------------------

info ""
if [[ $REMOVE_FROM_REGISTRY -eq 1 ]]; then
  python3 "$USER_REG_PY" \
    --registry "$REGISTRY_JSON" \
    --remove-user \
    --username "$USERNAME" \
    --yes >/dev/null \
    && info "User ${USERNAME} removed from registry." \
    || { warn "Failed to remove ${USERNAME} from registry"; _ALL_OK=0; }
else
  python3 "$USER_REG_PY" \
    --registry "$REGISTRY_JSON" \
    --disposition "$USERNAME" archived >/dev/null \
    && info "User ${USERNAME} set to archived (retained in registry for audit)." \
    || { warn "Failed to set ${USERNAME} disposition to archived"; _ALL_OK=0; }
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

info ""
if [[ $_ALL_OK -eq 1 ]]; then
  info "Offboarding complete for $USERNAME (service: $TARGET_SERVICE)."
else
  warn "One or more steps failed. Review warnings above."
  warn "Re-run with --user $USERNAME --service <svc> to retry individual services."
  exit 1
fi
