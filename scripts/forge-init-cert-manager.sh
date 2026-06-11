#!/usr/bin/env bash
# forge-init-cert-manager.sh — Deploy cert-manager to the k3s cluster (Phase 2.B).
#
# PAP constraints:
#   - KeePass gate required before cluster operations (AD-060)
#   - No credentials in env, argv, or logs
#   - All network operations are operator-supervised
#
# Usage:
#   ./forge-init-cert-manager.sh [--namespace cert-manager] [--version v1.14.4]
#       [--staging] [--email <acme-email>] [--state-dir <dir>]
#
# What this does:
#   1. KeePass gate (operator must unlock master DB)
#   2. Add jetstack Helm repo
#   3. Generate cert-manager-values.yaml via cert_manager.py
#   4. helm upgrade --install cert-manager
#   5. Generate + apply ClusterIssuer (selfsigned bootstrap + ACME production)
#   6. Record deployment in cert-manager-state.json

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="$(cd "${SCRIPT_DIR}/../lib" && pwd)"
BOOTSTRAP_DIR="$(cd "${SCRIPT_DIR}/../proxmox-bootstrap" && pwd)"

# shellcheck source=../lib/forge-lib.sh
source "${LIB_DIR}/forge-lib.sh"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
NAMESPACE="cert-manager"
CHART_VERSION="v1.14.4"
STAGING=false
ACME_EMAIL=""
STATE_DIR="${BROODFORGE_STATE_DIR:-/var/lib/broodforge}"

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --namespace)   NAMESPACE="$2"; shift 2 ;;
        --version)     CHART_VERSION="$2"; shift 2 ;;
        --staging)     STAGING=true; shift ;;
        --email)       ACME_EMAIL="$2"; shift 2 ;;
        --state-dir)   STATE_DIR="$2"; shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

# ---------------------------------------------------------------------------
# Step 1: KeePass gate
# ---------------------------------------------------------------------------
echo "[forge-init-cert-manager] Step 1: KeePass gate"
forge_keepass_gate

# ---------------------------------------------------------------------------
# Step 2: Add Helm repo
# ---------------------------------------------------------------------------
echo "[forge-init-cert-manager] Step 2: Adding jetstack Helm repo"
helm repo add jetstack https://charts.jetstack.io --force-update
helm repo update jetstack

# ---------------------------------------------------------------------------
# Step 3: Generate values.yaml
# ---------------------------------------------------------------------------
VALUES_FILE="${STATE_DIR}/cert-manager-values.yaml"
echo "[forge-init-cert-manager] Step 3: Generating values.yaml → ${VALUES_FILE}"
python3 "${BOOTSTRAP_DIR}/cert_manager.py" --state "${STATE_DIR}" \
    generate-values --output "${VALUES_FILE}"

# ---------------------------------------------------------------------------
# Step 4: Deploy cert-manager
# ---------------------------------------------------------------------------
echo "[forge-init-cert-manager] Step 4: Deploying cert-manager ${CHART_VERSION}"
helm upgrade --install cert-manager jetstack/cert-manager \
    --namespace "${NAMESPACE}" \
    --create-namespace \
    --version "${CHART_VERSION}" \
    --values "${VALUES_FILE}" \
    --wait \
    --timeout 300s

# ---------------------------------------------------------------------------
# Step 5: Generate + apply ClusterIssuers
# ---------------------------------------------------------------------------
ISSUER_DIR="${STATE_DIR}/issuers"
mkdir -p "${ISSUER_DIR}"

# 5a. Self-signed bootstrap issuer (always created)
echo "[forge-init-cert-manager] Step 5a: Creating selfsigned ClusterIssuer"
SELFSIGNED_ISSUER="${ISSUER_DIR}/cluster-issuer-selfsigned.yaml"
python3 "${BOOTSTRAP_DIR}/cert_manager.py" --state "${STATE_DIR}" \
    generate-issuer --issuer broodforge-selfsigned --type selfsigned \
    --output "${SELFSIGNED_ISSUER}"
kubectl apply -f "${SELFSIGNED_ISSUER}"

# 5b. ACME issuer (only if email provided)
if [[ -n "${ACME_EMAIL}" ]]; then
    echo "[forge-init-cert-manager] Step 5b: Creating ACME ClusterIssuer (staging=${STAGING})"
    ACME_ISSUER="${ISSUER_DIR}/cluster-issuer-acme.yaml"
    STAGING_FLAG=""
    [[ "${STAGING}" == "true" ]] && STAGING_FLAG="--staging"
    python3 "${BOOTSTRAP_DIR}/cert_manager.py" --state "${STATE_DIR}" \
        generate-issuer --issuer broodforge-acme --type acme \
        --email "${ACME_EMAIL}" ${STAGING_FLAG} \
        --output "${ACME_ISSUER}"
    kubectl apply -f "${ACME_ISSUER}"
else
    echo "[forge-init-cert-manager] Step 5b: Skipping ACME issuer (no --email provided)"
fi

# ---------------------------------------------------------------------------
# Step 6: Record deployment in state
# ---------------------------------------------------------------------------
echo "[forge-init-cert-manager] Step 6: Recording deployment in state"
python3 - <<PYEOF
import sys; sys.path.insert(0, "${BOOTSTRAP_DIR}")
from cert_manager import CertManager
mgr = CertManager(state_dir="${STATE_DIR}")
mgr.mark_deployed(chart_version="${CHART_VERSION}")
PYEOF

echo ""
echo "[forge-init-cert-manager] cert-manager deployed successfully."
echo "  Namespace:     ${NAMESPACE}"
echo "  Chart version: ${CHART_VERSION}"
echo "  Issuers:       broodforge-selfsigned$([ -n "${ACME_EMAIL}" ] && echo ", broodforge-acme")"
echo ""
echo "Next steps:"
echo "  Register certificates: python3 proxmox-bootstrap/cert_manager.py --state ${STATE_DIR} register-cert --domain <domain> --issuer broodforge-acme"
echo "  View status:           python3 proxmox-bootstrap/cert_manager.py --state ${STATE_DIR} status"
