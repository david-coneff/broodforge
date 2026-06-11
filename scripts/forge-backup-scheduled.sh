#!/usr/bin/env bash
# forge-backup-scheduled.sh — Cron-safe scheduled CQB backup.
#
# Phase 1.O: Intended for use in cron or a systemd timer. Reads a
# backup-schedule.json time window and exits 0 silently if the current time
# is outside the configured window.
#
# backup-schedule.json format (in BROODFORGE_STATE_DIR):
#   {
#     "enabled": true,
#     "window_start_utc": "02:00",   // HH:MM UTC — backup window opens
#     "window_end_utc":   "04:00",   // HH:MM UTC — backup window closes
#     "scope": "broodforge",         // scope passed to backup_manager.py
#     "max_age_hours": 24            // skip if a backup younger than this exists
#   }
#
# If backup-schedule.json is missing, defaults to: window 02:00–04:00 UTC,
# scope=broodforge, max_age_hours=24.
#
# No KeePass gate — scheduled backups use scope=broodforge (quiesce_level=0)
# or another level-0/1 scope. If scope requires level>=2 (full/vm:/node:),
# the script aborts and exits 1 to avoid unattended VM-level operations.
#
# Exit codes:
#   0 — backup succeeded, OR outside time window, OR recent backup exists
#   1 — fatal error

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

BACKUP_MANAGER="${REPO_ROOT}/proxmox-bootstrap/backup_manager.py"
STATE_DIR="${BROODFORGE_STATE_DIR:-/var/lib/broodforge}"
SCHEDULE_FILE="${STATE_DIR}/backup-schedule.json"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log() { echo "[backup-scheduled] $*"; }
die() { echo "[backup-scheduled] ERROR: $*" >&2; exit 1; }

PYTHON="$(command -v python3 2>/dev/null)" || die "python3 not found in PATH"

if [ ! -f "$BACKUP_MANAGER" ]; then
  die "backup_manager.py not found at $BACKUP_MANAGER"
fi

# ---------------------------------------------------------------------------
# Read schedule config
# ---------------------------------------------------------------------------

ENABLED="true"
WINDOW_START="02:00"
WINDOW_END="04:00"
SCOPE="broodforge"
MAX_AGE_HOURS=24

if [ -f "$SCHEDULE_FILE" ]; then
  ENABLED="$("$PYTHON" -c "
import json, sys
d = json.load(open('$SCHEDULE_FILE'))
print(str(d.get('enabled', True)).lower())
" 2>/dev/null || echo "true")"

  WINDOW_START="$("$PYTHON" -c "
import json
d = json.load(open('$SCHEDULE_FILE'))
print(d.get('window_start_utc', '02:00'))
" 2>/dev/null || echo "02:00")"

  WINDOW_END="$("$PYTHON" -c "
import json
d = json.load(open('$SCHEDULE_FILE'))
print(d.get('window_end_utc', '04:00'))
" 2>/dev/null || echo "04:00")"

  SCOPE="$("$PYTHON" -c "
import json
d = json.load(open('$SCHEDULE_FILE'))
print(d.get('scope', 'broodforge'))
" 2>/dev/null || echo "broodforge")"

  MAX_AGE_HOURS="$("$PYTHON" -c "
import json
d = json.load(open('$SCHEDULE_FILE'))
print(d.get('max_age_hours', 24))
" 2>/dev/null || echo "24")"
fi

# ---------------------------------------------------------------------------
# Abort if disabled
# ---------------------------------------------------------------------------

if [ "$ENABLED" != "true" ]; then
  log "Scheduled backups disabled in $SCHEDULE_FILE — exiting."
  exit 0
fi

# ---------------------------------------------------------------------------
# Abort if scope requires operator gate
# ---------------------------------------------------------------------------

_scope_lower="${SCOPE,,}"
case "$_scope_lower" in
  full|vm:*|node:*)
    die "Scope '$SCOPE' requires quiesce_level >= 2 (operator presence). " \
        "Scheduled backups must use scope=broodforge or pod:/service:. Aborting."
    ;;
esac

# ---------------------------------------------------------------------------
# Check time window
# ---------------------------------------------------------------------------

CURRENT_UTC="$(date -u +%H:%M)"

"$PYTHON" - <<EOF
import sys
start = "$WINDOW_START"
end   = "$WINDOW_END"
now   = "$CURRENT_UTC"

def hm(s):
    h, m = s.split(':')
    return int(h) * 60 + int(m)

now_m   = hm(now)
start_m = hm(start)
end_m   = hm(end)

# Handle window that wraps midnight
if start_m <= end_m:
    in_window = start_m <= now_m < end_m
else:
    in_window = now_m >= start_m or now_m < end_m

if not in_window:
    print(f"[backup-scheduled] Outside backup window {start}–{end} UTC (now {now}) — exiting.")
    sys.exit(42)
else:
    print(f"[backup-scheduled] Inside backup window {start}–{end} UTC (now {now}) — proceeding.")
    sys.exit(0)
EOF
TIME_RC=$?

if [ "$TIME_RC" -eq 42 ]; then
  exit 0
elif [ "$TIME_RC" -ne 0 ]; then
  die "Time window check failed (python exited $TIME_RC)"
fi

# ---------------------------------------------------------------------------
# Check if a recent backup already exists
# ---------------------------------------------------------------------------

RECENT="$("$PYTHON" - <<EOF
import json, os, sys
from datetime import datetime, timezone, timedelta
backups_dir = os.path.join("$STATE_DIR", "backups")
max_age = timedelta(hours=$MAX_AGE_HOURS)
now = datetime.now(timezone.utc)
if not os.path.isdir(backups_dir):
    sys.exit(0)
manifests = []
for entry in os.scandir(backups_dir):
    mp = os.path.join(entry.path, "manifest.json")
    if os.path.exists(mp):
        try:
            m = json.load(open(mp))
            manifests.append(m.get("completed_at", ""))
        except Exception:
            pass
manifests.sort(reverse=True)
if manifests:
    latest = manifests[0]
    try:
        ts = datetime.fromisoformat(latest.replace("Z", "+00:00"))
        if (now - ts) < max_age:
            print(f"recent:{latest}")
            sys.exit(0)
    except Exception:
        pass
print("none")
EOF
)"

if [[ "$RECENT" == recent:* ]]; then
  log "Recent backup found (${RECENT#recent:}) — younger than ${MAX_AGE_HOURS}h — skipping."
  exit 0
fi

# ---------------------------------------------------------------------------
# Run backup
# ---------------------------------------------------------------------------

log "Running scheduled backup (scope=${SCOPE})..."

"$PYTHON" "$BACKUP_MANAGER" \
  --backup \
  --scope "$SCOPE" \
  --trigger scheduled \
  --state-dir "$STATE_DIR"

RC=$?

if [ $RC -eq 0 ]; then
  log "Scheduled backup complete."
elif [ $RC -eq 2 ]; then
  log "WARNING: Backup completed with exit 2 (NOT_IMPLEMENTED stubs). Backup may be partial."
  exit 0
else
  die "backup_manager.py exited $RC — scheduled backup failed."
fi

exit 0
