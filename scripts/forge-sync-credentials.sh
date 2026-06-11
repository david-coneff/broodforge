#!/usr/bin/env bash
# forge-sync-credentials.sh — Sync master KeePass credentials to child databases.
#
# Propagates the current master KeePass contents to all child databases listed
# in credential-hierarchy.json.  Called automatically by forge-rotate-credential.sh
# as step 5 of the rotation ceremony; also available for standalone re-sync.
#
# Sync mechanism (in preference order):
#
#   1. pykeepass (preferred) — lib/forge-sync-lib.py
#      One-way master-authoritative sync via the pykeepass Python library.
#      Handles add, update, and (with --delete-orphans) removal.
#      Install: pip install pykeepass
#
#   2. keepassxc-cli fallback — per-entry edit/add
#      Used automatically when pykeepass is not installed (forge-sync-lib.py
#      exits 2).  Covers the rotation ceremony case (one known entry at a time).
#      Full group mirroring of new entries still requires a GUI KeeShare sync.
#
# Usage:
#   bash scripts/forge-sync-credentials.sh [--entry <master-entry-path>] [--db <db-name>]
#
#   --entry  Sync only this master entry path (e.g. "Services/restic/repo-password")
#   --db     Sync to only this child DB (e.g. "forge-autonomous")
#   (no args) Sync all entries declared in credential-hierarchy.json
#
# Exit codes:
#   0 — sync complete (all targeted entries propagated or already current)
#   1 — fatal error (DB not found, password retrieval failed, etc.)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LIB_SH="${REPO_ROOT}/lib/forge-lib.sh"
SYNC_LIB_PY="${REPO_ROOT}/lib/forge-sync-lib.py"

STATE_DIR="${BROODFORGE_STATE_DIR:-/var/lib/broodforge}"
HIER_CONFIG="${STATE_DIR}/credential-hierarchy.json"

# ---------------------------------------------------------------------------

die()  { echo "[sync-creds] ERROR: $*" >&2; exit 1; }
info() { echo "[sync-creds] $*"; }

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------

TARGET_ENTRY=""    # if set, sync only this master entry path
TARGET_DB=""       # if set, sync to only this child DB name

while [[ $# -gt 0 ]]; do
  case "$1" in
    --entry) TARGET_ENTRY="$2"; shift 2 ;;
    --db)    TARGET_DB="$2";    shift 2 ;;
    --help)
      grep '^#' "$0" | head -35 | sed 's/^# \?//'
      exit 0
      ;;
    *) die "Unknown argument: $1" ;;
  esac
done

# ---------------------------------------------------------------------------
# Load forge-lib.sh and gate
# ---------------------------------------------------------------------------

echo ""
echo "================================================================="
echo " forge-sync-credentials.sh — OPERATOR-INITIATED ONLY"
echo " Never call this from automated or scheduled contexts."
echo "================================================================="
echo ""

[[ -f "$LIB_SH" ]] || die "forge-lib.sh not found at $LIB_SH"
# shellcheck source=../lib/forge-lib.sh
source "$LIB_SH"
forge_keepass_gate

# ---------------------------------------------------------------------------
# Detect pykeepass availability
# ---------------------------------------------------------------------------

_PYKEEPASS_AVAILABLE=0
if [[ -f "$SYNC_LIB_PY" ]] && command -v python3 &>/dev/null; then
  if python3 -c "import pykeepass" &>/dev/null 2>&1; then
    _PYKEEPASS_AVAILABLE=1
    info "pykeepass available — using forge-sync-lib.py for sync"
  else
    info "pykeepass not installed — using keepassxc-cli fallback"
    info "(install with: pip install pykeepass)"
  fi
fi

# ---------------------------------------------------------------------------
# Load hierarchy config
# ---------------------------------------------------------------------------

[[ -f "$HIER_CONFIG" ]] \
  || die "credential-hierarchy.json not found at $HIER_CONFIG. Run forge-init-credential-hierarchy.sh first."

mapfile -t _ALL_DBS < <(python3 - "$HIER_CONFIG" <<'PYEOF'
import json, sys
with open(sys.argv[1]) as fh:
    d = json.load(fh)
for c in d.get("child_databases", []):
    print(f"{c['name']}|{c['path']}|{c['master_entry']}")
PYEOF
)

(( ${#_ALL_DBS[@]} > 0 )) || die "No child databases found in $HIER_CONFIG"

# ---------------------------------------------------------------------------
# pykeepass sync (preferred path)
# ---------------------------------------------------------------------------

# _sync_entry_pykeepass <child_db_path> <child_db_name> <master_entry_path>
# Uses forge-sync-lib.py.  Returns 0 on success, 1 on error, 2 if pykeepass absent.
_sync_entry_pykeepass() {
  local child_db_path="$1"
  local child_db_name="$2"
  local master_entry_path="$3"

  _broker_ensure_child_password "$child_db_name" || return 1

  local _out _rc
  _out=$(printf '%s\n%s\n' \
    "$KEEPASS_MASTER_PASSWORD" \
    "${_CHILD_DB_PASSWORD_CACHE[$child_db_name]}" | \
    python3 "$SYNC_LIB_PY" \
      --master "$FORGE_KDBX_PATH" \
      --child  "$child_db_path" \
      --entry  "$master_entry_path" 2>&1)
  _rc=$?

  # Indent output for readability
  echo "$_out" | sed 's/^/  /'
  return $_rc
}

# ---------------------------------------------------------------------------
# keepassxc-cli fallback (used when pykeepass is absent or errors)
# ---------------------------------------------------------------------------

# _sync_entry_to_child_cli <child_db_path> <child_db_name> <master_entry_path>
_sync_entry_to_child_cli() {
  local child_db_path="$1"
  local child_db_name="$2"
  local master_entry_path="$3"

  local entry_title="${master_entry_path##*/}"

  local new_password
  new_password=$(printf '%s\n' "$KEEPASS_MASTER_PASSWORD" | \
    keepassxc-cli show -q -a Password "$FORGE_KDBX_PATH" "$master_entry_path" 2>/dev/null) \
    || { info "  ⚠ Could not read master entry: $master_entry_path — skipping"; return 0; }

  _broker_ensure_child_password "$child_db_name" || {
    info "  ⚠ Cannot unlock child DB $child_db_name — skipping"
    return 0
  }
  local child_pw="${_CHILD_DB_PASSWORD_CACHE[$child_db_name]}"

  local child_entry_path
  if [[ "$master_entry_path" == Broodforge/child-dbs/* ]]; then
    child_entry_path="child-db-passwords/${entry_title}"
  else
    child_entry_path="$master_entry_path"
  fi

  if printf '%s\n' "$child_pw" | \
      keepassxc-cli edit --quiet --password "$new_password" \
        "$child_db_path" "$child_entry_path" >/dev/null 2>&1; then
    info "  ✓ Updated (cli): $child_entry_path in $child_db_name"
  else
    if printf '%s\n' "$child_pw" | \
        keepassxc-cli add --quiet --username "broodforge-sync" \
          --password "$new_password" \
          "$child_db_path" "$child_entry_path" >/dev/null 2>&1; then
      info "  ✓ Added   (cli): $child_entry_path in $child_db_name"
    else
      info "  ⚠ Could not update/add $child_entry_path in $child_db_name"
      info "    Sync this entry manually in KeePassXC GUI."
    fi
  fi

  unset new_password child_pw
}

# ---------------------------------------------------------------------------
# Dispatcher: pykeepass first, keepassxc-cli fallback
# ---------------------------------------------------------------------------

# _sync_entry_to_child <child_db_path> <child_db_name> <master_entry_path>
_sync_entry_to_child() {
  local child_db_path="$1"
  local child_db_name="$2"
  local master_entry_path="$3"

  [[ -f "$child_db_path" ]] \
    || { info "  ⚠ Database file not found: $child_db_path — skipping"; return 0; }

  if [[ $_PYKEEPASS_AVAILABLE -eq 1 ]]; then
    local _rc
    _sync_entry_pykeepass "$child_db_path" "$child_db_name" "$master_entry_path"
    _rc=$?
    if [[ $_rc -eq 0 ]]; then return 0; fi
    if [[ $_rc -ne 2 ]]; then
      info "  ⚠ pykeepass sync failed (rc=$_rc) — trying keepassxc-cli fallback"
    fi
  fi

  _sync_entry_to_child_cli "$child_db_path" "$child_db_name" "$master_entry_path"
}

# ---------------------------------------------------------------------------
# Main sync loop
# ---------------------------------------------------------------------------

info ""
info "Starting credential sync (master → child databases)..."
info ""

_SYNCED=0
_SKIPPED=0

for db_record in "${_ALL_DBS[@]}"; do
  IFS='|' read -r db_name db_path master_entry <<< "$db_record"

  [[ -z "$TARGET_DB" || "$TARGET_DB" == "$db_name" ]] || continue

  info "Child DB: $db_name ($db_path)"

  if [[ ! -f "$db_path" ]]; then
    info "  ⚠ Database file not found: $db_path — skipping"
    _SKIPPED=$(( _SKIPPED + 1 ))
    continue
  fi

  if [[ -z "$TARGET_ENTRY" ]]; then
    _sync_entry_to_child "$db_path" "$db_name" "$master_entry"
  else
    _sync_entry_to_child "$db_path" "$db_name" "$TARGET_ENTRY"
  fi

  _SYNCED=$(( _SYNCED + 1 ))
done

info ""
if [[ $_SYNCED -eq 0 && -n "$TARGET_DB" ]]; then
  die "Child DB '$TARGET_DB' not found in hierarchy config."
fi

info "Sync complete. Child databases updated: $_SYNCED, skipped: $_SKIPPED"
info ""
info "Services receive new credentials on their next broker call (kdbx_get_child)."
info ""

# ---------------------------------------------------------------------------
# KeeShare GUI reminder when pykeepass unavailable and new entries may exist
# ---------------------------------------------------------------------------

if [[ $_PYKEEPASS_AVAILABLE -eq 0 ]]; then
  echo ""
  echo "┌────────────────────────────────────────────────────────────────────"
  echo "│  pykeepass not installed — keepassxc-cli fallback used."
  echo "│  This covers rotation of existing entries."
  echo "│  For new entries not yet in a child DB, install pykeepass:"
  echo "│    pip install pykeepass"
  echo "│  or open each child DB in KeePassXC GUI:"
  echo "│    Database → Synchronise → Synchronise with KeeShare"
  echo "└────────────────────────────────────────────────────────────────────"
  echo ""
fi

exit 0
