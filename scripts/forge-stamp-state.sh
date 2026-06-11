#!/usr/bin/env bash
# forge-stamp-state.sh — Stamp the broodforge state descriptor.
#
# Computes a SHA-256 digest over the current operational state files and writes
# (or updates) proxmox-bootstrap/state-descriptor.json.
#
# Call this script after any operation that mutates deployment state:
#   - forge-migrate.sh  (called automatically on successful migration)
#   - spawn completion  (TODO: call from forge-spawn.sh when implemented)
#   - phoenix restore   (TODO: call from forge-phoenix-restore.sh when implemented)
#   - manifest changes  (any manual edit to manifest.toml)
#
# State content set hashed:
#   INCLUDED:
#     - *.json and *.toml files directly in --state-dir (top-level only)
#     - migrations/migrate_initial__to__*.py (active migration script)
#   EXCLUDED (mutual exclusion rule — neither descriptor is in the other's set):
#     - state-descriptor.json itself (self-reference loop)
#     - package-descriptor.json (records source integrity, not state)
#     - migration-history.jsonl (append-only log)
#     - *.lock files (transient)
#     - files under backups/ (snapshots, not current state)
#
# Usage:
#   bash scripts/forge-stamp-state.sh [--state-dir <path>]
#
# Arguments:
#   --state-dir <path>  Override state directory (default: repo root for development;
#                       use /var/lib/broodforge for deployed instances)
#
# Exit codes:
#   0 — state descriptor written successfully
#   1 — failed to write descriptor

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON="${PYTHON:-python3}"

VERIFIER="${REPO_ROOT}/proxmox-bootstrap/package_verifier.py"
DESCRIPTOR="${REPO_ROOT}/proxmox-bootstrap/state-descriptor.json"

if [ ! -f "$VERIFIER" ]; then
  echo "[stamp-state] ERROR: package_verifier.py not found at ${VERIFIER}" >&2
  exit 1
fi

# Run the verifier with --stamp-state, forwarding all arguments (e.g. --state-dir)
"$PYTHON" "$VERIFIER" --stamp-state "$@" || {
  echo "[stamp-state] ERROR: package_verifier.py --stamp-state failed." >&2
  exit 1
}

# Print a concise one-liner with the short hash for log/operator confirmation.
if [ -f "$DESCRIPTOR" ]; then
  SHORT_HASH="$("$PYTHON" -c "
import json
from pathlib import Path
d = json.loads(Path('${DESCRIPTOR}').read_text(encoding='utf-8'))
print(d['state_hash'][:12])
")"
  echo "[stamp-state] State descriptor stamped: ${SHORT_HASH}"
fi
