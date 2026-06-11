#!/usr/bin/env bash
# forge-quiesce.sh — Stop broodforge-managed timers and set migration lock.
#
# Prevents state from changing during a schema migration by stopping the
# continuous-assessment and operational-schedule timers, waiting for any
# running service instances to complete, and creating a migration.lock file.
#
# Usage:
#   sudo bash scripts/forge-quiesce.sh
#
# AD-065: Migration requires operator presence (KeePass gate enforced here).
#         No autonomous pathway may initiate migration.
#
# Exit codes:
#   0 — quiesced successfully; migration.lock created
#   1 — timer stop failed or lock could not be created
#   2 — NOT_IMPLEMENTED (stub placeholder, should never occur in production)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LIB_SH="${REPO_ROOT}/lib/forge-lib.sh"

LOCK_DIR="${BROODFORGE_STATE_DIR:-/var/lib/broodforge}"
LOCK_FILE="${LOCK_DIR}/migration.lock"
QUIESCE_TIMEOUT=30  # seconds to wait for running services to complete

TIMERS=(
  "broodforge-continuous-assessment.timer"
  "broodforge-operational-schedule.timer"
)

# ---------------------------------------------------------------------------

die() { echo "[quiesce] ERROR: $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# KeePass gate — operator presence required (AD-065)
# ---------------------------------------------------------------------------

if [ ! -f "$LIB_SH" ]; then
  die "forge-lib.sh not found at $LIB_SH — check repo layout."
fi
# shellcheck source=../lib/forge-lib.sh
source "$LIB_SH"
forge_keepass_gate

# ---------------------------------------------------------------------------
# Stop timers
# ---------------------------------------------------------------------------

echo "[quiesce] Stopping broodforge timers..."

for timer in "${TIMERS[@]}"; do
  if systemctl is-active --quiet "$timer" 2>/dev/null; then
    echo "[quiesce]   stopping $timer"
    systemctl stop "$timer" || die "Failed to stop $timer"
  else
    echo "[quiesce]   $timer is not active — skipping stop"
  fi
done

# ---------------------------------------------------------------------------
# Wait for running service instances to complete
# ---------------------------------------------------------------------------

SERVICE_NAMES=(
  "broodforge-continuous-assessment.service"
  "broodforge-operational-schedule.service"
)

echo "[quiesce] Waiting up to ${QUIESCE_TIMEOUT}s for running service instances..."

deadline=$(( $(date +%s) + QUIESCE_TIMEOUT ))

for svc in "${SERVICE_NAMES[@]}"; do
  while systemctl is-active --quiet "$svc" 2>/dev/null; do
    now=$(date +%s)
    if [ "$now" -ge "$deadline" ]; then
      die "Timed out waiting for $svc to complete after ${QUIESCE_TIMEOUT}s. " \
          "Check 'systemctl status $svc' and try again."
    fi
    echo "[quiesce]   $svc still running — waiting..."
    sleep 2
  done
done

echo "[quiesce] All service instances idle."

# ---------------------------------------------------------------------------
# Create migration lock
# ---------------------------------------------------------------------------

mkdir -p "$LOCK_DIR" || die "Cannot create lock directory $LOCK_DIR"

if [ -f "$LOCK_FILE" ]; then
  echo "[quiesce] WARNING: migration.lock already exists:" >&2
  cat "$LOCK_FILE" >&2
  die "Another migration may be in progress. Remove $LOCK_FILE to override."
fi

ISO_TIMESTAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf '{"locked_at": "%s", "pid": "%s", "reason": "migration"}\n' \
  "$ISO_TIMESTAMP" "$$" > "$LOCK_FILE" \
  || die "Cannot write migration lock to $LOCK_FILE"

echo "[quiesce] Migration lock created at $LOCK_FILE"
echo "broodforge quiesced — safe to migrate"
