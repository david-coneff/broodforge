#!/usr/bin/env bash
# forge-init-flux.sh — Phase 2.G: Bootstrap Flux CD on the cluster
# KeePass gate required (AD-060): Flux bootstrap modifies cluster and git repo.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../lib/forge-lib.sh"

BROODFORGE_STATE_DIR="${BROODFORGE_STATE_DIR:-/var/lib/broodforge}"
GITOPS_URL="${GITOPS_URL:-}"          # e.g. ssh://git@forgejo.home/dave/infra.git
GITOPS_PATH="${GITOPS_PATH:-./clusters/home}"
GITOPS_BRANCH="${GITOPS_BRANCH:-main}"
FLUX_NAMESPACE="${FLUX_NAMESPACE:-flux-system}"
SECRET_REF="${SECRET_REF:-}"          # k8s secret for git credentials
DRY_RUN="${DRY_RUN:-false}"

forge_keepass_gate "Flux CD bootstrap"

[[ -z "${GITOPS_URL}" ]] && { echo "ERROR: GITOPS_URL must be set" >&2; exit 1; }
for bin in flux kubectl; do
    command -v "$bin" &>/dev/null || { echo "ERROR: $bin not found" >&2; exit 1; }
done

echo "==> Phase 2.G: Bootstrapping Flux CD"
echo "    Git URL:   ${GITOPS_URL}"
echo "    Path:      ${GITOPS_PATH}"
echo "    Branch:    ${GITOPS_BRANCH}"
echo "    Namespace: ${FLUX_NAMESPACE}"
[ "${DRY_RUN}" = "true" ] && echo "    DRY RUN"

echo "--> Running flux check --pre..."
flux check --pre || { echo "WARNING: pre-flight check failed; proceeding anyway" >&2; }

CMD=(python3 "${SCRIPT_DIR}/../proxmox-bootstrap/flux_manager.py"
     --state-dir "${BROODFORGE_STATE_DIR}" bootstrap-git
     --url "${GITOPS_URL}" --path "${GITOPS_PATH}"
     --branch "${GITOPS_BRANCH}" --namespace "${FLUX_NAMESPACE}")
[ -n "${SECRET_REF}" ] && CMD+=(--secret-ref "${SECRET_REF}")
[ "${DRY_RUN}" = "true" ] && CMD+=(--dry-run)

if "${CMD[@]}"; then
    echo "==> Flux CD bootstrapped successfully."
    echo "    Monitor: flux get all -n ${FLUX_NAMESPACE}"
else
    echo "ERROR: Flux bootstrap failed" >&2; exit 1
fi
