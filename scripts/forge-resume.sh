#!/usr/bin/env bash
# forge-resume.sh — Re-enable broodforge after migration completes or rolls back.
#
# Verifies the migration lock exists (prevents accidental use outside a migration
# context), removes it, restarts the broodforge timers, and runs a brief health
# check to confirm the assessment pipeline is operational.
#
# Usage:
#   sudo bash scripts/forge-resume.sh
#
# Exit codes:
#   0 — resumed successfully (health check passed or warned)
#   1 — lock file missing, timer restart failed, or unrecoverable error

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

LOCK_FILE="${BROODFORGE_STATE_DIR:-/var/lib/broodforge}/migration.lock"
MANIFEST_PATH_FILE="/etc/broodforge/manifest-path"
DEFAULT_MANIFEST="${REPO_ROOT}/manifest.toml"

TIMERS=(
  "broodforge-continuous-assessment.timer"
  "broodforge-operational-schedule.timer"
)

PYTHON="${PYTHON:-python3}"

# ---------------------------------------------------------------------------

die() { echo "[resume] ERROR: $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Guard: lock must exist
# ---------------------------------------------------------------------------

if [ ! -f "$LOCK_FILE" ]; then
  die "migration.lock not found at $LOCK_FILE. " \
      "forge-resume.sh must only be called after forge-quiesce.sh."
fi

echo "[resume] Migration lock found — proceeding with resume."

# ---------------------------------------------------------------------------
# Remove lock
# ---------------------------------------------------------------------------

rm -f "$LOCK_FILE" || die "Cannot remove migration lock at $LOCK_FILE"
echo "[resume] Migration lock removed."

# ---------------------------------------------------------------------------
# Restart timers
# ---------------------------------------------------------------------------

echo "[resume] Restarting broodforge timers..."

for timer in "${TIMERS[@]}"; do
  echo "[resume]   starting $timer"
  systemctl start "$timer" || die "Failed to start $timer"
done

echo "[resume] Timers restarted."

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

# Resolve manifest path
if [ -f "$MANIFEST_PATH_FILE" ]; then
  MANIFEST="$(cat "$MANIFEST_PATH_FILE")"
else
  MANIFEST="$DEFAULT_MANIFEST"
fi

echo "[resume] Running health check (manifest: $MANIFEST)..."

ASSESSMENT_SCRIPT="${REPO_ROOT}/proxmox-bootstrap/continuous_assessment.py"

HEALTH_OK=0
if [ -f "$ASSESSMENT_SCRIPT" ]; then
  if "$PYTHON" "$ASSESSMENT_SCRIPT" \
       --manifest "$MANIFEST" \
       --repo-root "$REPO_ROOT" 2>/dev/null; then
    HEALTH_OK=1
  fi
else
  echo "[resume] WARNING: assessment script not found at $ASSESSMENT_SCRIPT — skipping health check." >&2
  HEALTH_OK=1  # not a failure; health check is best-effort
fi

if [ "$HEALTH_OK" -eq 1 ]; then
  echo "broodforge resumed"
else
  echo "broodforge resumed with health warnings — check dashboard"
fi
