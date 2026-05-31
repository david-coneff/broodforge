#!/usr/bin/env bash
# Bootstrap Assessment — Tier 1
#
# Usage:
#   chmod +x bootstrap.sh
#   ./bootstrap.sh
#
# Requirements: bash, python3 (stdlib only)
# No network access required. Runs as root for full output; partial output if unprivileged.
#
# Output:
#   bootstrap_<timestamp>/          raw collector outputs + manifest.json
#   bootstrap_<timestamp>.tar.gz    self-contained archive for transfer

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COLLECTORS_DIR="${SCRIPT_DIR}/collectors"
ANALYZE_PY="${SCRIPT_DIR}/analyze.py"

TS=$(date -u +%Y-%m-%d_%H_%M_%S)
OUTDIR="${SCRIPT_DIR}/bootstrap_${TS}"
ARCHIVE="${SCRIPT_DIR}/bootstrap_${TS}.tar.gz"

# ---------------------------------------------------------------------------
log() { echo "[bootstrap $(date -u +%H:%M:%S)] $*"; }

log "Starting Tier 1 assessment: ${TS}"
log "Output directory: ${OUTDIR}"

mkdir -p "${OUTDIR}"

# ---------------------------------------------------------------------------
# Run collectors
# Each collector is non-fatal: errors are logged, not propagated.
COLLECTORS=(cpu memory storage network proxmox software)

for name in "${COLLECTORS[@]}"; do
    collector="${COLLECTORS_DIR}/${name}.sh"
    if [ -x "${collector}" ]; then
        log "Collecting: ${name}"
        bash "${collector}" "${OUTDIR}" \
            2>>"${OUTDIR}/collection_errors.log" || {
            echo "${name}: collector exited non-zero" >> "${OUTDIR}/collection_warnings.log"
        }
    else
        log "WARNING: collector not found or not executable: ${collector}"
        echo "${name}: collector script missing" >> "${OUTDIR}/collection_warnings.log"
    fi
done

# ---------------------------------------------------------------------------
# Build manifest
log "Building manifest.json"
if python3 "${ANALYZE_PY}" "${OUTDIR}"; then
    log "manifest.json created"
else
    log "WARNING: analyze.py exited non-zero — manifest may be incomplete"
fi

# ---------------------------------------------------------------------------
# Package archive
log "Creating archive: ${ARCHIVE}"
tar -czf "${ARCHIVE}" -C "$(dirname "${OUTDIR}")" "$(basename "${OUTDIR}")"

log "Done."
echo ""
echo "  Archive : ${ARCHIVE}"
echo "  Manifest: ${OUTDIR}/manifest.json"
echo ""
echo "  Copy the archive to your workstation, then run:"
echo "    python3 doc-gen/engine.py --mode bootstrap --archive $(basename "${ARCHIVE}")"
