#!/usr/bin/env bash
# forge-migrate.sh — High-level migration orchestrator for broodforge state.
#
# This is the script the operator actually runs to apply schema migrations.
# It runs a package-hash pre-flight check, quiesces broodforge, generates a
# phoenix recovery package, backs up current state, runs the migration manager,
# and resumes broodforge (or restores from backup on failure).
#
# Usage:
#   sudo bash scripts/forge-migrate.sh [--state-dir /var/lib/broodforge]
#                                       [--migrations-dir ./migrations]
#                                       [--dry-run]
#                                       [--skip-phoenix]
#
# Flags:
#   --state-dir      Override state directory (default: /var/lib/broodforge)
#   --migrations-dir Override migrations directory (default: <repo>/migrations)
#   --dry-run        Print pending migrations but do not execute them
#   --skip-phoenix   Skip phoenix package generation and the export prompt.
#                    WARNING: skipping means no disaster-recovery snapshot
#                    will exist before the migration runs.
#
# Exit codes:
#   0 — migration completed successfully
#   1 — migration failed (state restored from backup)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

STATE_DIR="/var/lib/broodforge"
MIGRATIONS_DIR="${REPO_ROOT}/migrations"
PYTHON="${PYTHON:-python3}"
DRY_RUN=0
SKIP_PHOENIX=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --state-dir)      STATE_DIR="$2";      shift 2 ;;
    --migrations-dir) MIGRATIONS_DIR="$2"; shift 2 ;;
    --dry-run)        DRY_RUN=1;           shift   ;;
    --skip-phoenix)   SKIP_PHOENIX=1;      shift   ;;
    *) echo "[migrate] Unknown argument: $1" >&2; exit 1 ;;
  esac
done

# Export so forge-quiesce.sh and forge-resume.sh use the same state dir for their lock.
export BROODFORGE_STATE_DIR="${STATE_DIR}"

BACKUP_BASE="${STATE_DIR}/backups"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="${BACKUP_BASE}/pre-migration-${TIMESTAMP}"

MIGRATION_MANAGER="${REPO_ROOT}/proxmox-bootstrap/migration_manager.py"
QUIESCE_SH="${SCRIPT_DIR}/forge-quiesce.sh"
RESUME_SH="${SCRIPT_DIR}/forge-resume.sh"
PHOENIX_PACK_SH="${SCRIPT_DIR}/forge-phoenix-pack.sh"
VERIFY_SH="${SCRIPT_DIR}/forge-verify-package.sh"
STAMP_STATE_SH="${SCRIPT_DIR}/forge-stamp-state.sh"

# ---------------------------------------------------------------------------

die() { echo "[migrate] ERROR: $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Pre-flight: verify package hash
#
# A mismatch means the package was modified after the last forge-stamp-version.sh
# run.  This is non-fatal — the operator may have patched in-place — but it is
# worth knowing before migration starts.
# ---------------------------------------------------------------------------

echo "[migrate] === Pre-flight: Package hash verification ==="
VERIFY_EXIT=0
bash "$VERIFY_SH" || VERIFY_EXIT=$?

if [ "$VERIFY_EXIT" -eq 0 ]; then
  echo "[migrate] Package hash: OK"
elif [ "$VERIFY_EXIT" -eq 2 ]; then
  echo "[migrate] WARNING: No package descriptor found — package integrity is unverified."
  echo "[migrate]   Run 'bash scripts/forge-stamp-version.sh' to establish a baseline."
  echo "[migrate]   Continuing (non-fatal pre-flight warning)."
else
  echo "[migrate] WARNING: Package hash mismatch — package may have been modified since last stamp."
  echo "[migrate]   Run 'bash scripts/forge-stamp-version.sh' if changes are intentional."
  echo "[migrate]   Continuing (non-fatal pre-flight warning)."
fi

# ---------------------------------------------------------------------------
# Step 1: Quiesce
# ---------------------------------------------------------------------------

echo "[migrate] === Step 1: Quiesce ==="
bash "$QUIESCE_SH" || die "forge-quiesce.sh failed — aborting migration."

# ---------------------------------------------------------------------------
# Step 2: Phoenix recovery package
#
# Generate a full disaster-recovery export before touching state.
# Operators should copy the resulting archive to an external device.
# Skip with --skip-phoenix (logs a warning).
# ---------------------------------------------------------------------------

echo "[migrate] === Step 2: Phoenix recovery package ==="

if [ "$SKIP_PHOENIX" -eq 1 ]; then
  echo "[migrate] WARNING: Skipping phoenix package — running without recovery snapshot."
else
  PHOENIX_PKG_PATH=""
  PHOENIX_EXIT=0
  PHOENIX_PKG_PATH="$(bash "$PHOENIX_PACK_SH" --state-dir "$STATE_DIR" 2>/dev/null)" \
    || PHOENIX_EXIT=$?

  if [ "$PHOENIX_EXIT" -eq 0 ] && [ -n "$PHOENIX_PKG_PATH" ]; then
    # Phoenix package generated — prompt operator to export it
    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║  RECOVERY PACKAGE READY                                     ║"
    echo "║  Path: ${PHOENIX_PKG_PATH}"
    echo "║                                                              ║"
    echo "║  It is STRONGLY RECOMMENDED to copy this to an external     ║"
    echo "║  device before proceeding.                                   ║"
    echo "║                                                              ║"
    echo "║  Press ENTER to continue without exporting,                  ║"
    echo "║  or Ctrl-C to abort and export manually.                    ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
    read -r _
  elif [ "$PHOENIX_EXIT" -eq 2 ]; then
    # FORGE_INCOMPLETE: phoenix CLI not yet wired — continue without a package
    echo "[migrate] NOTE: forge-phoenix-pack.sh is not yet fully wired (FORGE_INCOMPLETE)."
    echo "[migrate]   No recovery package was generated before this migration."
    echo "[migrate]   To generate manually: python3 ${REPO_ROOT}/proxmox-bootstrap/assemble_phoenix_package.py"
    echo "[migrate]   Continuing without a recovery snapshot."
  else
    echo "[migrate] WARNING: forge-phoenix-pack.sh failed (exit ${PHOENIX_EXIT})." >&2
    echo "[migrate]   No recovery package was generated. Operator assumes risk." >&2
    echo "[migrate]   Continuing." >&2
  fi
fi

# ---------------------------------------------------------------------------
# Step 3: Backup current state
# ---------------------------------------------------------------------------

echo "[migrate] === Step 3: Backup state to $BACKUP_DIR ==="
mkdir -p "$BACKUP_DIR" || die "Cannot create backup directory $BACKUP_DIR"

# Copy bootstrap-state.json
if [ -f "${STATE_DIR}/bootstrap-state.json" ]; then
  cp "${STATE_DIR}/bootstrap-state.json" "$BACKUP_DIR/"
  echo "[migrate]   backed up bootstrap-state.json"
fi

# Copy manifest.toml if present
if [ -f "${STATE_DIR}/manifest.toml" ]; then
  cp "${STATE_DIR}/manifest.toml" "$BACKUP_DIR/"
  echo "[migrate]   backed up manifest.toml"
fi

# Copy any other .json state files
shopt -s nullglob
for json_file in "${STATE_DIR}"/*.json; do
  fname="$(basename "$json_file")"
  if [ "$fname" != "bootstrap-state.json" ]; then
    cp "$json_file" "$BACKUP_DIR/"
    echo "[migrate]   backed up $fname"
  fi
done
shopt -u nullglob

# F-5: Post-write checksum verification — compute SHA-256 of every file we
# just copied and store the manifest so restore can detect corruption.
CHECKSUM_FILE="${BACKUP_DIR}/checksums.sha256"
info_msg() { echo "[migrate] $*"; }

info_msg "Computing post-write checksums ..."
(
  cd "$BACKUP_DIR"
  # sha256sum writes "<hash>  <filename>" lines; works on Debian/Ubuntu/Alpine
  sha256sum -- *.json manifest.toml 2>/dev/null > checksums.sha256 || true
)

# Sanity-verify each file immediately after writing the checksum manifest
CHECKSUM_FAIL=0
while IFS= read -r line; do
  expected_hash="${line%% *}"
  fname="${line##* }"
  fname="${fname#\*}"   # strip leading * that sha256sum sometimes adds
  fpath="${BACKUP_DIR}/${fname}"
  if [[ ! -f "$fpath" ]]; then
    echo "[migrate] WARNING: checksum entry references missing file: $fname" >&2
    continue
  fi
  actual_hash="$(sha256sum -- "$fpath" | awk '{print $1}')"
  if [[ "$actual_hash" != "$expected_hash" ]]; then
    echo "[migrate] ERROR: post-write integrity check FAILED for $fname" >&2
    echo "[migrate]   expected: $expected_hash" >&2
    echo "[migrate]   actual:   $actual_hash" >&2
    CHECKSUM_FAIL=1
  fi
done < "$CHECKSUM_FILE"

if [[ "$CHECKSUM_FAIL" -ne 0 ]]; then
  die "Backup integrity check failed — one or more files are corrupt. Aborting migration."
fi

echo "[migrate] Backup complete: $BACKUP_DIR (checksums verified)"

# ---------------------------------------------------------------------------
# Step 4: Run migration_manager.py
# ---------------------------------------------------------------------------

echo "[migrate] === Step 4: Run migration_manager.py ==="

MIGRATION_ARGS=(
  "$PYTHON"
  "$MIGRATION_MANAGER"
  "--state-dir" "$STATE_DIR"
  "--migrations-dir" "$MIGRATIONS_DIR"
)

if [ "$DRY_RUN" -eq 1 ]; then
  MIGRATION_ARGS+=("--dry-run")
  echo "[migrate] DRY RUN — no state will be modified."
fi

MIGRATION_EXIT=0
"${MIGRATION_ARGS[@]}" || MIGRATION_EXIT=$?

# ---------------------------------------------------------------------------
# Step 5: Resume (success or rollback)
# ---------------------------------------------------------------------------

if [ "$MIGRATION_EXIT" -eq 0 ]; then
  echo "[migrate] === Step 5: Migration succeeded — stamping state descriptor ==="
  # Update state-descriptor.json to reflect the post-migration state.
  # This ensures the state hash tracks the new schema version and any state
  # file changes produced by the migration.
  STAMP_STATE_EXIT=0
  bash "$STAMP_STATE_SH" --state-dir "$STATE_DIR" || STAMP_STATE_EXIT=$?
  if [ "$STAMP_STATE_EXIT" -ne 0 ]; then
    echo "[migrate] WARNING: forge-stamp-state.sh failed (exit ${STAMP_STATE_EXIT}) — state descriptor may be stale." >&2
    echo "[migrate]   Run 'bash scripts/forge-stamp-state.sh --state-dir ${STATE_DIR}' manually." >&2
  fi

  echo "[migrate] === Step 5 (cont.): Resuming ==="
  bash "$RESUME_SH"
  echo "[migrate] Migration complete."
  exit 0
else
  echo "[migrate] === Step 5: Migration FAILED (exit $MIGRATION_EXIT) — restoring backup ===" >&2

  # F-5: Verify backup checksums before restoring
  RESTORE_CHECKSUM_FILE="${BACKUP_DIR}/checksums.sha256"
  if [[ -f "$RESTORE_CHECKSUM_FILE" ]]; then
    echo "[migrate] Verifying backup checksums before restore ..."
    RESTORE_FAIL=0
    while IFS= read -r line; do
      expected_hash="${line%% *}"
      fname="${line##* }"
      fname="${fname#\*}"
      fpath="${BACKUP_DIR}/${fname}"
      [[ -f "$fpath" ]] || continue
      actual_hash="$(sha256sum -- "$fpath" | awk '{print $1}')"
      if [[ "$actual_hash" != "$expected_hash" ]]; then
        echo "[migrate] ERROR: backup file corrupt — $fname (checksum mismatch)" >&2
        RESTORE_FAIL=1
      fi
    done < "$RESTORE_CHECKSUM_FILE"
    if [[ "$RESTORE_FAIL" -ne 0 ]]; then
      echo "[migrate] CRITICAL: backup files are corrupt — manual intervention required." >&2
      echo "[migrate]   Backup dir: ${BACKUP_DIR}" >&2
      exit 1
    fi
    echo "[migrate] Backup checksums OK."
  else
    echo "[migrate] WARNING: no checksums.sha256 found in backup — restoring without verification." >&2
  fi

  # Restore backed-up files (skipping checksum sidecar files)
  for backup_file in "$BACKUP_DIR"/*; do
    fname="$(basename "$backup_file")"
    # Skip the checksum manifest itself — it belongs in the backup dir, not state dir
    [[ "$fname" == "checksums.sha256" ]] && continue
    cp "$backup_file" "${STATE_DIR}/${fname}" && \
      echo "[migrate]   restored $fname" || \
      echo "[migrate]   WARNING: could not restore $fname" >&2
  done

  echo "[migrate] State restored from backup at $BACKUP_DIR"
  bash "$RESUME_SH"
  echo "[migrate] Migration failed — state restored from backup" >&2
  exit 1
fi
