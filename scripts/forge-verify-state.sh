#!/usr/bin/env bash
# forge-verify-state.sh — Verify the broodforge state descriptor.
#
# Calls package_verifier.py --verify-state and prints a human-readable
# pass/fail line.  Use this as a sanity check after any state-mutating
# operation, or as a pre-flight before operations that depend on state being
# in a known-good condition.
#
# State content set verified (same files as forge-stamp-state.sh):
#   INCLUDED:
#     - *.json and *.toml files directly in --state-dir (top-level only)
#     - migrations/migrate_initial__to__*.py (active migration script)
#   EXCLUDED (mutual exclusion rule):
#     - state-descriptor.json (self-reference loop)
#     - package-descriptor.json (source integrity — separate descriptor)
#     - migration-history.jsonl, *.lock, files under backups/
#
# Usage:
#   bash scripts/forge-verify-state.sh [--state-dir <path>]
#
# Arguments:
#   --state-dir <path>  Override state directory (default: repo root for development;
#                       use /var/lib/broodforge for deployed instances)
#
# Exit codes (mirrors package_verifier.py --verify-state):
#   0 — hash matches descriptor  (State integrity: OK)
#   1 — hash mismatch            (State integrity: MISMATCH)
#   2 — descriptor not found     (run forge-stamp-state.sh first)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON="${PYTHON:-python3}"

VERIFIER="${REPO_ROOT}/proxmox-bootstrap/package_verifier.py"

if [ ! -f "$VERIFIER" ]; then
  echo "[verify-state] ERROR: package_verifier.py not found at ${VERIFIER}" >&2
  exit 1
fi

VERIFY_EXIT=0
"$PYTHON" "$VERIFIER" --verify-state "$@" || VERIFY_EXIT=$?

case "$VERIFY_EXIT" in
  0) echo "State integrity: OK" ;;
  1)
    # Count mismatched files from verifier stderr if available; otherwise report generically.
    echo "State integrity: MISMATCH — run 'bash scripts/forge-stamp-state.sh' if changes are intentional." >&2
    ;;
  2) echo "[verify-state] WARN — no state descriptor found. Run: bash scripts/forge-stamp-state.sh" >&2 ;;
  *) echo "[verify-state] WARN — unexpected exit code ${VERIFY_EXIT} from package_verifier.py" >&2 ;;
esac

exit "$VERIFY_EXIT"
