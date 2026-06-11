#!/usr/bin/env bash
# forge-stamp-version.sh — Stamp the broodforge package with a new schema version.
#
# Run this after any change to the package (Python source, shell scripts, or
# migration scripts).  It updates proxmox-bootstrap/version.py with the new
# SCHEMA_VERSION and recomputes the package-descriptor.json hash.
#
# Usage:
#   bash scripts/forge-stamp-version.sh [<version>]
#
# If <version> is omitted, it is derived automatically:
#   - timestamp : current UTC date/time formatted as YYYY-MM-DD_HH-MM-SS
#   - hash      : git rev-parse --short=7 HEAD (falls back to 0000000)
#
# The version string format is:  YYYY-MM-DD_HH-MM-SS_<7-char-hex-hash>
# Example:                        2026-06-09_14-30-22_a3b4c5d
#
# Exit codes:
#   0 — version stamped and descriptor updated
#   1 — validation or descriptor update failed

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON="${PYTHON:-python3}"

VERSION_PY="${REPO_ROOT}/proxmox-bootstrap/version.py"
VERIFIER="${REPO_ROOT}/proxmox-bootstrap/package_verifier.py"

# ---------------------------------------------------------------------------
# Determine version string
# ---------------------------------------------------------------------------

if [[ $# -ge 1 ]]; then
  VERSION="$1"
else
  TS="$(date -u +"%Y-%m-%d_%H-%M-%S")"
  HASH="$(git -C "$REPO_ROOT" rev-parse --short=7 HEAD 2>/dev/null || echo "0000000")"
  VERSION="${TS}_${HASH}"
fi

echo "[stamp] Version: ${VERSION}"

# Validate format: YYYY-MM-DD_HH-MM-SS_<exactly 7 alphanumeric chars>
if ! echo "$VERSION" | grep -qE '^[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}-[0-9]{2}-[0-9]{2}_[0-9a-f]{7}$'; then
  echo "[stamp] ERROR: version '${VERSION}' does not match required format." >&2
  echo "[stamp]   Expected: YYYY-MM-DD_HH-MM-SS_<7-char-lowercase-hex>" >&2
  echo "[stamp]   Example : 2026-06-09_14-30-22_a3b4c5d" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Update version.py
# ---------------------------------------------------------------------------

cat > "$VERSION_PY" <<EOF
# This file is updated by scripts/forge-stamp-version.sh at release time.
# Format: YYYY-MM-DD_HH-MM-SS_<7-char-git-hash>
# The zeroed hash (0000000) indicates the baseline before the versioning
# system was introduced.
SCHEMA_VERSION: str = "${VERSION}"
EOF

echo "[stamp] Updated ${VERSION_PY##*/} → SCHEMA_VERSION = '${VERSION}'"

# ---------------------------------------------------------------------------
# Recompute package descriptor
# ---------------------------------------------------------------------------

echo "[stamp] Recomputing package-descriptor.json ..."
"$PYTHON" "$VERIFIER" --stamp || {
  echo "[stamp] ERROR: package_verifier.py --stamp failed." >&2
  exit 1
}

echo "[stamp] Done."
