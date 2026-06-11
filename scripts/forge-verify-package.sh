#!/usr/bin/env bash
# forge-verify-package.sh — Verify the broodforge package hash against its descriptor.
#
# Calls package_verifier.py --verify and prints a human-readable pass/fail line.
# Intended as a pre-flight sanity check before running forge-migrate.sh or any
# other operation that depends on the package being in a known state.
#
# Hash scope — what is verified
# ------------------------------
# Only *static source files* are included in the hash: files that are identical
# on every deployment of a given package version and never modified after install.
# This means verification works correctly on a live deployed instance — runtime
# state changes never cause spurious mismatches.
#
# Included:  *.py under proxmox-bootstrap/, engine/, tests/, migrations/
#            *.sh under scripts/, lib/, assessment/, tools/
#            *.md under migrations/  (naming convention docs)
#
# Excluded:  *.json, *.jsonl  (runtime state and migration history logs)
#            *.log, *.lock    (log output and lock files)
#            *.toml           (operator-configured: manifest.toml, answer.toml)
#            .secrets.baseline, __pycache__/, .audit/, backups/
#            package-descriptor.json  (records our own hash — would be circular)
#
# Usage:
#   bash scripts/forge-verify-package.sh
#
# Exit codes (mirrors package_verifier.py --verify):
#   0 — hash matches descriptor  (PASS)
#   1 — hash mismatch             (FAIL — package may have been modified)
#   2 — descriptor not found      (WARN — run forge-stamp-version.sh first)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON="${PYTHON:-python3}"

VERIFIER="${REPO_ROOT}/proxmox-bootstrap/package_verifier.py"

if [ ! -f "$VERIFIER" ]; then
  echo "[verify-pkg] ERROR: package_verifier.py not found at ${VERIFIER}" >&2
  exit 1
fi

VERIFY_EXIT=0
"$PYTHON" "$VERIFIER" --verify || VERIFY_EXIT=$?

case "$VERIFY_EXIT" in
  0) echo "[verify-pkg] PASS — package hash matches descriptor." ;;
  1) echo "[verify-pkg] FAIL — package hash mismatch (see above)." >&2 ;;
  2) echo "[verify-pkg] WARN — no descriptor found. Run: bash scripts/forge-stamp-version.sh" >&2 ;;
  *) echo "[verify-pkg] WARN — unexpected exit code ${VERIFY_EXIT} from package_verifier.py" >&2 ;;
esac

exit "$VERIFY_EXIT"
