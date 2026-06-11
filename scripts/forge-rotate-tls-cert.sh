#!/usr/bin/env bash
# forge-rotate-tls-cert.sh — Force renewal of a tracked TLS certificate (Phase 2.B).
#
# PAP constraints:
#   - KeePass gate required (AD-060)
#   - No credentials in env, argv, or logs
#
# Usage:
#   ./forge-rotate-tls-cert.sh --domain <domain> [--state-dir <dir>]
#
# What this does:
#   1. KeePass gate
#   2. Annotate the Certificate object to trigger immediate renewal
#   3. Wait for cert-manager to issue the new cert
#   4. Query the new expiry and record it in cert-manager-state.json

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="$(cd "${SCRIPT_DIR}/../lib" && pwd)"
BOOTSTRAP_DIR="$(cd "${SCRIPT_DIR}/../proxmox-bootstrap" && pwd)"

# shellcheck source=../lib/forge-lib.sh
source "${LIB_DIR}/forge-lib.sh"

DOMAIN=""
STATE_DIR="${BROODFORGE_STATE_DIR:-/var/lib/broodforge}"
TIMEOUT=120

while [[ $# -gt 0 ]]; do
    case "$1" in
        --domain)    DOMAIN="$2"; shift 2 ;;
        --state-dir) STATE_DIR="$2"; shift 2 ;;
        --timeout)   TIMEOUT="$2"; shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

if [[ -z "${DOMAIN}" ]]; then
    echo "Usage: $0 --domain <domain> [--state-dir <dir>]" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Step 1: KeePass gate
# ---------------------------------------------------------------------------
echo "[forge-rotate-tls-cert] Step 1: KeePass gate"
forge_keepass_gate

# Derive cert object name from domain (dots → dashes, append -tls)
CERT_NAME="${DOMAIN//./-}-tls"

# Query state for namespace
NAMESPACE=$(python3 - <<PYEOF
import sys, json
sys.path.insert(0, "${BOOTSTRAP_DIR}")
from cert_manager import load_state
state = load_state("${STATE_DIR}")
cert = state.find_cert("${DOMAIN}")
print(cert.namespace if cert else "default")
PYEOF
)

echo "[forge-rotate-tls-cert] Domain:     ${DOMAIN}"
echo "[forge-rotate-tls-cert] Cert name:  ${CERT_NAME}"
echo "[forge-rotate-tls-cert] Namespace:  ${NAMESPACE}"

# ---------------------------------------------------------------------------
# Step 2: Trigger renewal via annotation
# ---------------------------------------------------------------------------
echo "[forge-rotate-tls-cert] Step 2: Triggering cert-manager renewal"
kubectl annotate certificate "${CERT_NAME}" \
    -n "${NAMESPACE}" \
    cert-manager.io/issue-temporary-certificate="true" \
    --overwrite

# The standard renewal trigger annotation
kubectl annotate certificate "${CERT_NAME}" \
    -n "${NAMESPACE}" \
    "cert-manager.io/renew-before=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --overwrite

# ---------------------------------------------------------------------------
# Step 3: Wait for new certificate
# ---------------------------------------------------------------------------
echo "[forge-rotate-tls-cert] Step 3: Waiting up to ${TIMEOUT}s for renewal"
DEADLINE=$(( $(date +%s) + TIMEOUT ))
while true; do
    READY=$(kubectl get certificate "${CERT_NAME}" -n "${NAMESPACE}" \
        -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "False")
    if [[ "${READY}" == "True" ]]; then
        echo "[forge-rotate-tls-cert] Certificate is Ready."
        break
    fi
    if (( $(date +%s) >= DEADLINE )); then
        echo "[forge-rotate-tls-cert] Timeout waiting for renewal." >&2
        exit 1
    fi
    sleep 5
done

# ---------------------------------------------------------------------------
# Step 4: Query new expiry and record
# ---------------------------------------------------------------------------
echo "[forge-rotate-tls-cert] Step 4: Recording new expiry"
NOT_AFTER=$(kubectl get certificate "${CERT_NAME}" -n "${NAMESPACE}" \
    -o jsonpath='{.status.notAfter}' 2>/dev/null || echo "")

if [[ -n "${NOT_AFTER}" ]]; then
    python3 "${BOOTSTRAP_DIR}/cert_manager.py" --state "${STATE_DIR}" \
        record-renewal --domain "${DOMAIN}" --expires "${NOT_AFTER}"
    echo "[forge-rotate-tls-cert] Recorded expiry: ${NOT_AFTER}"
else
    echo "[forge-rotate-tls-cert] Warning: could not query notAfter; state not updated." >&2
fi

echo ""
echo "[forge-rotate-tls-cert] TLS certificate for ${DOMAIN} rotated successfully."
