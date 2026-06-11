#!/usr/bin/env bash
# forge-throw-away-key.sh — Atomically delete credentials from KeePass and mark
#                           key_thrown_away=true in the user registry.
#
# IMPORTANT — Order of operations is strict and intentional:
#   1. Delete password entry from KeePass
#   2. Delete TOTP-secret entry from KeePass
#   3. Set key_thrown_away flag in user-registry.json
#
# The flag is NEVER set if KeePass deletion fails.  This guarantees that the
# registry accurately reflects whether admin-held credentials exist.
#
# After this runs:
#   - The admin can no longer read or use the user's password for this service.
#   - forge-provision-users.sh will use the "reset" flow for this user+service
#     on any future rebuild (temporary password + notify).
#   - The user can still access the service with their own password.
#   - The admin can still delete the account (but not log in as the user).
#
# Usage:
#   bash scripts/forge-throw-away-key.sh --user <username> --service <service>
#   bash scripts/forge-throw-away-key.sh --user alice --service vaultwarden
#   bash scripts/forge-throw-away-key.sh --user alice --service all
#   bash scripts/forge-throw-away-key.sh --user alice  # same as --service all
#
# Flags:
#   --user <username>    Required. User whose key to throw away.
#   --service <name>     Service name, or "all" to throw away all services.
#                        Defaults to "all" if omitted.
#   --dry-run            Show what would be deleted without making changes.
#   --yes                Skip confirmation prompt.
#
# Exit codes:
#   0 — all targeted keys successfully thrown away
#   1 — error (KeePass deletion failed; flag NOT set)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LIB_SH="${REPO_ROOT}/lib/forge-lib.sh"
USER_REG_PY="${REPO_ROOT}/proxmox-bootstrap/user_registry.py"
REGISTRY_JSON="${REPO_ROOT}/config/user-registry.json"

# ---------------------------------------------------------------------------

die()  { echo "[throw-away-key] ERROR: $*" >&2; exit 1; }
info() { echo "[throw-away-key] $*"; }
warn() { echo "[throw-away-key] WARN: $*" >&2; }

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------

USERNAME=""
TARGET_SERVICE="all"
DRY_RUN=0
YES=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --user)     USERNAME="$2";        shift 2 ;;
    --service)  TARGET_SERVICE="$2";  shift 2 ;;
    --dry-run)  DRY_RUN=1;            shift   ;;
    --yes)      YES=1;                shift   ;;
    --help)
      grep '^#' "$0" | head -45 | sed 's/^# \?//'
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
# Resolve services to target
# ---------------------------------------------------------------------------

# Get the services list for this user from the registry
mapfile -t _USER_SERVICES < <(
  python3 "$USER_REG_PY" \
    --registry "$REGISTRY_JSON" \
    --list \
    2>/dev/null \
  | python3 - <<'PYEOF'
import json, sys, os

username = os.environ.get("_TAK_USERNAME", "")
target   = os.environ.get("_TAK_TARGET", "all")

data = json.load(sys.stdin)
for user in data.get("users", []):
    if user["username"] == username:
        svcs = user.get("services", {})
        if target == "all":
            for svc, info in svcs.items():
                if not info.get("key_thrown_away", False):
                    print(svc)
        else:
            if target in svcs and not svcs[target].get("key_thrown_away", False):
                print(target)
        break
PYEOF
) || true

# Fall back: parse registry JSON directly (simpler, no stdin piping complications)
export _TAK_USERNAME="$USERNAME"
export _TAK_TARGET="$TARGET_SERVICE"

mapfile -t _USER_SERVICES < <(
  python3 - "$REGISTRY_JSON" <<'PYEOF'
import json, sys, os

username = os.environ["_TAK_USERNAME"]
target   = os.environ["_TAK_TARGET"]

with open(sys.argv[1]) as f:
    data = json.load(f)

for user in data.get("users", []):
    if user["username"] == username:
        svcs = user.get("services", {})
        if target == "all":
            for svc, info in svcs.items():
                if not info.get("key_thrown_away", False):
                    print(svc)
        else:
            if target in svcs:
                if svcs[target].get("key_thrown_away", False):
                    print(f"ALREADY_THROWN_AWAY:{target}", file=sys.stderr)
                else:
                    print(target)
        break
else:
    print(f"USER_NOT_FOUND:{username}", file=sys.stderr)
PYEOF
)

unset _TAK_USERNAME _TAK_TARGET

if (( ${#_USER_SERVICES[@]} == 0 )); then
  info "No keys to throw away for ${USERNAME} (service: ${TARGET_SERVICE})."
  info "User may not exist, service may not be enrolled, or key already thrown away."
  exit 0
fi

# ---------------------------------------------------------------------------
# Confirmation prompt
# ---------------------------------------------------------------------------

info ""
info "This will PERMANENTLY delete credentials from KeePass for:"
info "  User    : $USERNAME"
info "  Service : $TARGET_SERVICE"
info ""
info "  Affected services:"
for svc in "${_USER_SERVICES[@]}"; do
  info "    - Broodforge/users/${USERNAME}/${svc}/password"
  info "    - Broodforge/users/${USERNAME}/${svc}/totp-secret"
done
info ""
warn "This action cannot be undone.  The admin copy of the password will be gone."
warn "On rebuild, the user will receive a temporary password and must reset it."
info ""

if [[ $DRY_RUN -eq 1 ]]; then
  info "[dry-run] No changes made."
  exit 0
fi

if [[ $YES -eq 0 ]]; then
  read -r -p "[throw-away-key] Type 'yes' to confirm: " _CONFIRM
  [[ "$_CONFIRM" == "yes" ]] || { info "Aborted."; exit 0; }
fi

# ---------------------------------------------------------------------------
# Deletion loop — strict order: KeePass first, flag second
# ---------------------------------------------------------------------------

_ALL_OK=1

_keepass_rm_entry() {
  local entry_path="$1"
  # Check if entry exists first
  if printf '%s\n' "$KEEPASS_MASTER_PASSWORD" | \
      keepassxc-cli show -q "$FORGE_KDBX_PATH" "$entry_path" >/dev/null 2>&1; then
    printf '%s\n' "$KEEPASS_MASTER_PASSWORD" | \
      keepassxc-cli rm --quiet "$FORGE_KDBX_PATH" "$entry_path" >/dev/null 2>&1 \
      || { warn "Failed to delete $entry_path from KeePass"; return 1; }
    info "  ✓ Deleted: $entry_path"
  else
    warn "  Entry not found (may already be deleted): $entry_path"
    # Not fatal — entry may never have existed (e.g. service with no TOTP)
  fi
}

for svc in "${_USER_SERVICES[@]}"; do
  info ""
  info "Throwing away key for ${USERNAME}/${svc}..."

  pw_path="Broodforge/users/${USERNAME}/${svc}/password"
  totp_path="Broodforge/users/${USERNAME}/${svc}/totp-secret"

  # Step 1: Delete password entry from KeePass
  if ! _keepass_rm_entry "$pw_path"; then
    warn "Password deletion failed for ${USERNAME}/${svc} — NOT setting flag. Fix and retry."
    _ALL_OK=0
    continue
  fi

  # Step 2: Delete TOTP entry from KeePass
  if ! _keepass_rm_entry "$totp_path"; then
    warn "TOTP deletion failed for ${USERNAME}/${svc} — NOT setting flag. Fix and retry."
    warn "Password entry was already deleted. Re-run to retry TOTP deletion."
    _ALL_OK=0
    continue
  fi

  # Step 3: Set flag in registry (only reached if both KeePass deletes succeeded)
  if python3 "$USER_REG_PY" \
      --registry "$REGISTRY_JSON" \
      --throw-away-key "$USERNAME" "$svc" >/dev/null; then
    info "  ✓ Registry updated: ${USERNAME}/${svc} key_thrown_away=true"
  else
    warn "Registry flag update failed for ${USERNAME}/${svc}."
    warn "KeePass entries were deleted. Manually set key_thrown_away in registry."
    _ALL_OK=0
  fi
done

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

info ""
if [[ $_ALL_OK -eq 1 ]]; then
  info "All targeted keys thrown away successfully."
  info "On next rebuild, ${USERNAME} will receive a temp password for affected services."
else
  warn "One or more services encountered errors. Review warnings above."
  exit 1
fi
