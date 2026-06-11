#!/usr/bin/env bash
# forge-init-ingress.sh — Phase 2.F: Deploy nginx-ingress-controller
# KeePass gate required (AD-060): deploying ingress touches cluster networking.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../lib/forge-lib.sh"

BROODFORGE_STATE_DIR="${BROODFORGE_STATE_DIR:-/var/lib/broodforge}"
NAMESPACE="${NAMESPACE:-ingress-nginx}"
SERVICE_TYPE="${SERVICE_TYPE:-LoadBalancer}"
REPLICAS="${REPLICAS:-1}"
CHART_VERSION="${CHART_VERSION:-}"
DRY_RUN="${DRY_RUN:-false}"

# ---------------------------------------------------------------------------
# KeePass gate — operator must be present
# ---------------------------------------------------------------------------
forge_keepass_gate "ingress controller deployment"

echo "==> Phase 2.F: Deploying nginx-ingress-controller"
echo "    Namespace:    ${NAMESPACE}"
echo "    Service type: ${SERVICE_TYPE}"
echo "    Replicas:     ${REPLICAS}"
[ -n "${CHART_VERSION}" ] && echo "    Chart version: ${CHART_VERSION}"
[ "${DRY_RUN}" = "true" ] && echo "    DRY RUN — no changes will be applied"
echo ""

# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------
if ! command -v helm &>/dev/null; then
    echo "ERROR: helm not found. Install helm before running this script." >&2
    exit 1
fi
if ! command -v kubectl &>/dev/null; then
    echo "ERROR: kubectl not found." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Add Helm repo
# ---------------------------------------------------------------------------
echo "--> Adding ingress-nginx Helm repo..."
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx 2>/dev/null || true
helm repo update

# ---------------------------------------------------------------------------
# Deploy
# ---------------------------------------------------------------------------
CMD=(
    python3 "${SCRIPT_DIR}/../proxmox-bootstrap/ingress_manager.py"
    --state-dir "${BROODFORGE_STATE_DIR}"
    deploy
    --namespace "${NAMESPACE}"
    --replicas "${REPLICAS}"
    --service-type "${SERVICE_TYPE}"
)
[ -n "${CHART_VERSION}" ] && CMD+=(--chart-version "${CHART_VERSION}")
[ "${DRY_RUN}" = "true" ] && CMD+=(--dry-run)

if "${CMD[@]}"; then
    echo ""
    echo "==> nginx-ingress-controller deployed successfully."
    echo "    Run 'kubectl get svc -n ${NAMESPACE}' to see the LoadBalancer IP."
else
    echo "ERROR: ingress deployment failed." >&2
    exit 1
fi
