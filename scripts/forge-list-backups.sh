#!/usr/bin/env bash
# forge-list-backups.sh — List available CQB backups.
#
# Phase 1.O: No gate required — backup listing is read-only and shows
# no secret material.
#
# Usage:
#   bash scripts/forge-list-backups.sh [--json]
#
#   --json   Output raw JSON array (for scripting)
#
# Exit codes:
#   0 — success (including no backups found)
#   1 — fatal error

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

BACKUP_MANAGER="${REPO_ROOT}/proxmox-bootstrap/backup_manager.py"
STATE_DIR="${BROODFORGE_STATE_DIR:-/var/lib/broodforge}"

JSON=""

for arg in "$@"; do
  case "$arg" in
    --json)   JSON="--json" ;;
    --help|-h)
      sed -n '2,15p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "[list-backups] ERROR: Unknown argument: $arg" >&2; exit 1 ;;
  esac
done

die() { echo "[list-backups] ERROR: $*" >&2; exit 1; }

if [ ! -f "$BACKUP_MANAGER" ]; then
  die "backup_manager.py not found at $BACKUP_MANAGER"
fi

PYTHON="$(command -v python3 2>/dev/null)" || die "python3 not found in PATH"

CMD=("$PYTHON" "$BACKUP_MANAGER" "--list" "--state-dir" "$STATE_DIR")
[ -n "$JSON" ] && CMD+=("--json")

"${CMD[@]}"
