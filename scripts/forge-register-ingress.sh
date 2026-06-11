#!/usr/bin/env bash
# forge-register-ingress.sh — Phase 2.F: Register an ingress route
# No KeePass gate (read-only registry operation until --apply is used).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BROODFORGE_STATE_DIR="${BROODFORGE_STATE_DIR:-/var/lib/broodforge}"

usage() {
    cat <<EOF
Usage: forge-register-ingress.sh --name NAME --namespace NS --service SVC \\
         --port PORT --hostname HOST [--path PREFIX] [--tls-secret SECRET] \\
         [--cluster-issuer ISSUER] [--apply] [--dry-run]

  --apply          Also kubectl apply the ingress manifest to the cluster
  --dry-run        Validate only; no state changes

Examples:
  # Register Forgejo ingress route with TLS
  forge-register-ingress.sh \\
    --name forgejo --namespace forge-apps \\
    --service forgejo --port 3000 \\
    --hostname forgejo.home.example.com \\
    --tls-secret forgejo-tls --cluster-issuer letsencrypt-prod \\
    --apply
EOF
    exit 1
}

NAME="" NAMESPACE="" SERVICE="" PORT="" HOSTNAME="" PATH_PREFIX="/"
TLS_SECRET="" CLUSTER_ISSUER="" APPLY=false DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --name)          NAME="$2"; shift 2 ;;
        --namespace)     NAMESPACE="$2"; shift 2 ;;
        --service)       SERVICE="$2"; shift 2 ;;
        --port)          PORT="$2"; shift 2 ;;
        --hostname)      HOSTNAME="$2"; shift 2 ;;
        --path)          PATH_PREFIX="$2"; shift 2 ;;
        --tls-secret)    TLS_SECRET="$2"; shift 2 ;;
        --cluster-issuer) CLUSTER_ISSUER="$2"; shift 2 ;;
        --apply)         APPLY=true; shift ;;
        --dry-run)       DRY_RUN=true; shift ;;
        -h|--help)       usage ;;
        *) echo "Unknown option: $1" >&2; usage ;;
    esac
done

[[ -z "${NAME}" || -z "${NAMESPACE}" || -z "${SERVICE}" || -z "${PORT}" || -z "${HOSTNAME}" ]] && usage

CMD=(
    python3 "${SCRIPT_DIR}/../proxmox-bootstrap/ingress_manager.py"
    --state-dir "${BROODFORGE_STATE_DIR}"
    register
    --name "${NAME}" --namespace "${NAMESPACE}"
    --service "${SERVICE}" --port "${PORT}"
    --hostname "${HOSTNAME}" --path "${PATH_PREFIX}"
)
[[ -n "${TLS_SECRET}" ]] && CMD+=(--tls-secret "${TLS_SECRET}")
[[ -n "${CLUSTER_ISSUER}" ]] && CMD+=(--cluster-issuer "${CLUSTER_ISSUER}")
[[ "${DRY_RUN}" = "true" ]] && CMD+=(--dry-run)

echo "--> Registering ingress route: ${NAMESPACE}/${NAME} → ${HOSTNAME}"
"${CMD[@]}"

if [[ "${APPLY}" = "true" ]]; then
    echo "--> Applying ingress manifest to cluster..."
    APPLY_CMD=(
        python3 "${SCRIPT_DIR}/../proxmox-bootstrap/ingress_manager.py"
        --state-dir "${BROODFORGE_STATE_DIR}"
        apply --name "${NAME}" --namespace "${NAMESPACE}"
    )
    [[ "${DRY_RUN}" = "true" ]] && APPLY_CMD+=(--dry-run)
    "${APPLY_CMD[@]}"
fi
