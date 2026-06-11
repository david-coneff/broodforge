#!/usr/bin/env bash
# forge-restore.sh — Restore broodforge state from a CQB backup.
#
# Phase 1.O: Always KeePass-gated — operator presence is required before any
# restore action. Prompts the operator for explicit confirmation before executing.
#
# Usage:
#   sudo bash scripts/forge-restore.sh <backup_id> [--dry-run]
#
#   backup_id   The backup ID to restore (e.g. 2026-06-09_14-30-22_a3b4c5d).
#               Use forge-list-backups.sh to see available backups.
#   --dry-run   Print what would be done without executing
#
# Exit codes:
#   0 — restore succeeded (or dry-run completed)
#   1 — fatal error or operator abort

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LIB_SH="${REPO_ROOT}/lib/forge-lib.sh"

BACKUP_MANAGER="${REPO_ROOT}/proxmox-bootstrap/backup_manager.py"
STATE_DIR="${BROODFORGE_STATE_DIR:-/var/lib/broodforge}"

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

BACKUP_ID=""
DRY_RUN=""

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN="--dry-run" ;;
    --help|-h)
      sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    -*) echo "[restore] ERROR: Unknown argument: $arg" >&2; exit 1 ;;
    *)  BACKUP_ID="$arg" ;;
  esac
done

die() { echo "[restore] ERROR: $*" >&2; exit 1; }

[ -z "$BACKUP_ID" ] && die "backup_id argument is required. Run forge-list-backups.sh to list available backups."

# ---------------------------------------------------------------------------
# Shared library — KeePass gate (always required for restore)
# ---------------------------------------------------------------------------

if [ ! -f "$LIB_SH" ]; then
  die "forge-lib.sh not found at $LIB_SH — check repo layout."
fi
# shellcheck source=../lib/forge-lib.sh
source "$LIB_SH"

echo "[restore] Restore is a destructive operation. Operator presence required."
forge_keepass_gate

# ---------------------------------------------------------------------------
# Sanity checks
# ---------------------------------------------------------------------------

if [ ! -f "$BACKUP_MANAGER" ]; then
  die "backup_manager.py not found at $BACKUP_MANAGER"
fi

PYTHON="$(command -v python3 2>/dev/null)" || die "python3 not found in PATH"

MANIFEST_FILE="${STATE_DIR}/backups/${BACKUP_ID}/manifest.json"
if [ ! -f "$MANIFEST_FILE" ]; then
  die "Manifest not found: $MANIFEST_FILE. Run forge-list-backups.sh to list available backups."
fi

# ---------------------------------------------------------------------------
# Confirm restore (unless dry-run)
# ---------------------------------------------------------------------------

echo ""
echo "================================================================="
echo " Restore from backup: ${BACKUP_ID}"
echo " Manifest: ${MANIFEST_FILE}"
echo ""
echo " This will:"
echo "   - Print restore procedure for k8s etcd snapshot (manual)"
echo "   - Print restore procedure for VM disk snapshots (manual)"
echo "   - Identify the broodforge phoenix package to restore from"
echo ""
echo " WARNING: Restore requires careful manual steps. The script prints"
echo "          the procedure — it does NOT automatically overwrite live state."
echo "================================================================="

if [ -z "$DRY_RUN" ]; then
  read -rp "[restore] Type 'restore' to confirm: " _confirm </dev/tty
  if [ "$_confirm" != "restore" ]; then
    echo "[restore] Aborted by operator."
    exit 1
  fi
fi

# ---------------------------------------------------------------------------
# Run restore
# ---------------------------------------------------------------------------

echo ""
echo "[restore] Running backup_manager.py --restore ${BACKUP_ID} ${DRY_RUN}..."
echo ""

CMD=("$PYTHON" "$BACKUP_MANAGER" "--restore" "$BACKUP_ID"
     "--state-dir" "$STATE_DIR")

[ -n "$DRY_RUN" ] && CMD+=("--dry-run")

"${CMD[@]}"
RC=$?

if [ $RC -ne 0 ]; then
  echo "" >&2
  echo "[restore] FATAL: restore failed (exit $RC)." >&2
  exit 1
fi

echo ""
echo "[restore] Procedure complete. Follow the printed steps to complete the restore."
exit 0
