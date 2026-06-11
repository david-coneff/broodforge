#!/usr/bin/env bash
# forge-backup.sh — Coordinated Quiesce + Backup (CQB) trigger script.
#
# Phase 1.O: Runs a broodforge CQB backup. KeePass gate is enforced for
# quiesce_level >= 2 or --scope full (operator presence required before any
# VM-level operation).
#
# Usage:
#   sudo bash scripts/forge-backup.sh [--scope <scope>] [--trigger <trigger>] [--dry-run]
#
#   --scope     full|broodforge|vm:100,101|pod:ns/name|service:name  (default: full)
#   --trigger   operator|autonomous|scheduled  (default: operator)
#   --dry-run   Print plan without writing any backup files
#
# Exit codes:
#   0 — backup succeeded (or dry-run completed)
#   1 — fatal error
#   2 — NOT_IMPLEMENTED (some backup sub-operations used exit 2 stubs)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LIB_SH="${REPO_ROOT}/lib/forge-lib.sh"

BACKUP_MANAGER="${REPO_ROOT}/proxmox-bootstrap/backup_manager.py"
STATE_DIR="${BROODFORGE_STATE_DIR:-/var/lib/broodforge}"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

SCOPE="full"
TRIGGER="operator"
DRY_RUN=""

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

while [[ $# -gt 0 ]]; do
  case "$1" in
    --scope)    SCOPE="$2";   shift 2 ;;
    --trigger)  TRIGGER="$2"; shift 2 ;;
    --dry-run)  DRY_RUN="--dry-run"; shift ;;
    -h|--help)
      sed -n '2,25p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "[backup] ERROR: Unknown argument: $1" >&2; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# Shared library
# ---------------------------------------------------------------------------

die() { echo "[backup] ERROR: $*" >&2; exit 1; }

if [ ! -f "$LIB_SH" ]; then
  die "forge-lib.sh not found at $LIB_SH — check repo layout."
fi
# shellcheck source=../lib/forge-lib.sh
source "$LIB_SH"

# ---------------------------------------------------------------------------
# KeePass gate — required for level >= 2 or full scope
# ---------------------------------------------------------------------------

_scope_lower="${SCOPE,,}"
_needs_gate=0

case "$_scope_lower" in
  full|vm:*|node:*) _needs_gate=1 ;;
esac

if [ "$_needs_gate" -eq 1 ]; then
  echo "[backup] Scope '$SCOPE' requires operator presence (quiesce_level >= 2)."
  forge_keepass_gate
fi

# ---------------------------------------------------------------------------
# Sanity checks
# ---------------------------------------------------------------------------

if [ ! -f "$BACKUP_MANAGER" ]; then
  die "backup_manager.py not found at $BACKUP_MANAGER"
fi

PYTHON="$(command -v python3 2>/dev/null)" || die "python3 not found in PATH"

echo "[backup] Starting CQB backup"
echo "[backup]   scope:   ${SCOPE}"
echo "[backup]   trigger: ${TRIGGER}"
echo "[backup]   dry-run: ${DRY_RUN:-no}"
echo ""

# ---------------------------------------------------------------------------
# Run backup
# ---------------------------------------------------------------------------

CMD=("$PYTHON" "$BACKUP_MANAGER" "--backup"
     "--scope"   "$SCOPE"
     "--trigger" "$TRIGGER"
     "--state-dir" "$STATE_DIR")

[ -n "$DRY_RUN" ] && CMD+=("--dry-run")

"${CMD[@]}"
RC=$?

case $RC in
  0)
    echo ""
    echo "[backup] Backup complete."
    ;;
  2)
    echo "" >&2
    echo "[backup] WARNING: Backup completed with exit 2 (NOT_IMPLEMENTED — some sub-operations are stubs)." >&2
    echo "[backup]   Backup may be partial. Check the manifest in ${STATE_DIR}/backups/." >&2
    ;;
  *)
    echo "" >&2
    echo "[backup] FATAL: backup_manager.py exited $RC — backup failed." >&2
    exit 1
    ;;
esac

exit $RC
