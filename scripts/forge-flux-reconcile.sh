#!/usr/bin/env bash
# forge-flux-reconcile.sh — Phase 2.G: Trigger immediate Flux reconciliation
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BROODFORGE_STATE_DIR="${BROODFORGE_STATE_DIR:-/var/lib/broodforge}"
KIND="${1:-source}" NAME="${2:-}" NAMESPACE="${3:-flux-system}"
[[ -z "$NAME" ]] && { echo "Usage: $0 <kind> <name> <namespace>" >&2; exit 1; }
exec python3 "${SCRIPT_DIR}/../proxmox-bootstrap/flux_manager.py" \
    --state-dir "${BROODFORGE_STATE_DIR}" reconcile \
    --kind "$KIND" --name "$NAME" --namespace "$NAMESPACE"
