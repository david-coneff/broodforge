#!/usr/bin/env bash
# forge-phoenix-pack.sh — Generate a phoenix recovery package for the current deployment.
#
# The phoenix package is the full disaster-recovery export of the current
# deployment state.  Operators should generate one before any schema migration
# to ensure a recovery baseline exists before state changes are applied.
#
# Usage:
#   bash scripts/forge-phoenix-pack.sh [--state-dir /var/lib/broodforge]
#
# On success: prints the absolute path to the generated package on stdout
#             and exits 0.
#
# Exit codes:
#   0 — package generated successfully (path printed on stdout)
#   1 — generation failed
#
# AD-042: KeePass gate enforces operator presence (via forge-lib.sh).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LIB_SH="${REPO_ROOT}/lib/forge-lib.sh"
PYTHON="${PYTHON:-python3}"

STATE_DIR="/var/lib/broodforge"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --state-dir) STATE_DIR="$2"; shift 2 ;;
    *) echo "[phoenix-pack] Unknown argument: $1" >&2; exit 1 ;;
  esac
done

ASSEMBLER="${REPO_ROOT}/proxmox-bootstrap/assemble_phoenix_package.py"
PHOENIX_OUT_DIR="${STATE_DIR}/phoenix"

# ---------------------------------------------------------------------------
# KeePass gate — operator presence required (AD-042)
# ---------------------------------------------------------------------------

if [ ! -f "$LIB_SH" ]; then
  echo "[phoenix-pack] ERROR: forge-lib.sh not found at ${LIB_SH} — check repo layout." >&2
  exit 1
fi
# shellcheck source=../lib/forge-lib.sh
source "$LIB_SH"
forge_keepass_gate

# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------

if [ ! -f "$ASSEMBLER" ]; then
  echo "[phoenix-pack] ERROR: assembler not found at ${ASSEMBLER}" >&2
  exit 1
fi

mkdir -p "$PHOENIX_OUT_DIR" || {
  echo "[phoenix-pack] ERROR: cannot create output directory ${PHOENIX_OUT_DIR}" >&2
  exit 1
}

TIMESTAMP="$(date -u +"%Y-%m-%d_%H-%M-%S")"
OUT_FILE="${PHOENIX_OUT_DIR}/${TIMESTAMP}.tar.gz"

# ---------------------------------------------------------------------------
# Assemble
# ---------------------------------------------------------------------------

# Run assembler; redirect its stdout to stderr so the only thing on stdout
# is the single path line we emit below (required by forge-migrate.sh).
"$PYTHON" "$ASSEMBLER" \
  --pack \
  --state-dir   "$STATE_DIR" \
  --output      "$OUT_FILE" \
  --repo-root   "$REPO_ROOT" \
  >&2 \
  || { echo "[phoenix-pack] ERROR: assembler failed." >&2; exit 1; }

# Emit the package path on stdout for forge-migrate.sh to capture.
echo "$OUT_FILE"
