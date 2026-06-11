#!/usr/bin/env bash
# forge-init-longhorn.sh — Deploy Longhorn distributed block storage (Phase 2.E).
#
# PAP constraints: KeePass gate; no credentials in env/argv/logs.
#
# Usage:
#   ./forge-init-longhorn.sh [--namespace longhorn-system] [--version 1.6.2]
#       [--replica-count 2] [--storage-class longhorn] [--state-dir <dir>]

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="$(cd "${SCRIPT_DIR}/../lib" && pwd)"
BOOTSTRAP_DIR="$(cd "${SCRIPT_DIR}/../proxmox-bootstrap" && pwd)"
# shellcheck source=../lib/forge-lib.sh
source "${LIB_DIR}/forge-lib.sh"

NAMESPACE="longhorn-system"
VERSION="1.6.2"
REPLICA_COUNT="2"
STORAGE_CLASS="longhorn"
STATE_DIR="${BROODFORGE_STATE_DIR:-/var/lib/broodforge}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --namespace)      NAMESPACE="$2";      shift 2 ;;
        --version)        VERSION="$2";        shift 2 ;;
        --replica-count)  REPLICA_COUNT="$2";  shift 2 ;;
        --storage-class)  STORAGE_CLASS="$2";  shift 2 ;;
        --state-dir)      STATE_DIR="$2";      shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

echo "[forge-init-longhorn] Step 1: KeePass gate"
forge_keepass_gate

echo "[forge-init-longhorn] Step 2: Installing Longhorn prerequisites"
# open-iscsi and nfs-common are required on every node Longhorn will use
echo "  Checking iscsi-initiator-utils / open-iscsi on this node..."
if command -v apt-get &>/dev/null; then
    apt-get install -y open-iscsi nfs-common >/dev/null 2>&1 || true
elif command -v yum &>/dev/null; then
    yum install -y iscsi-initiator-utils nfs-utils >/dev/null 2>&1 || true
fi
systemctl enable --now iscsid 2>/dev/null || true

echo "[forge-init-longhorn] Step 3: Adding Longhorn Helm repo"
helm repo add longhorn https://charts.longhorn.io --force-update
helm repo update longhorn

LONGHORN_VALUES="${STATE_DIR}/longhorn-values.yaml"
echo "[forge-init-longhorn] Step 4: Generating Longhorn values → ${LONGHORN_VALUES}"
python3 "${BOOTSTRAP_DIR}/storage_manager.py" --state "${STATE_DIR}" \
    generate-values \
    --default-replica-count "${REPLICA_COUNT}" \
    --storage-class "${STORAGE_CLASS}" \
    --output "${LONGHORN_VALUES}"

echo "[forge-init-longhorn] Step 5: Deploying Longhorn ${VERSION}"
helm upgrade --install longhorn longhorn/longhorn \
    --namespace "${NAMESPACE}" \
    --create-namespace \
    --version "${VERSION}" \
    --values "${LONGHORN_VALUES}" \
    --wait --timeout 600s

echo "[forge-init-longhorn] Step 6: Generating default StorageClass manifest"
SC_MANIFEST="${STATE_DIR}/longhorn-storageclass.yaml"
python3 "${BOOTSTRAP_DIR}/storage_manager.py" --state "${STATE_DIR}" \
    generate-storage-class \
    --name "${STORAGE_CLASS}" \
    --replica-count "${REPLICA_COUNT}" \
    --output "${SC_MANIFEST}"
kubectl apply -f "${SC_MANIFEST}"

echo "[forge-init-longhorn] Step 7: Recording deployment"
python3 "${BOOTSTRAP_DIR}/storage_manager.py" --state "${STATE_DIR}" \
    mark-deployed \
    --version "${VERSION}" \
    --default-replica-count "${REPLICA_COUNT}" \
    --storage-class "${STORAGE_CLASS}"

echo ""
echo "[forge-init-longhorn] Longhorn ${VERSION} deployed in ${NAMESPACE}."
echo "  Default storage class: ${STORAGE_CLASS} (replicas=${REPLICA_COUNT})"
echo "  Status:  python3 proxmox-bootstrap/storage_manager.py --state ${STATE_DIR} status"
echo "  Add disk: bash scripts/forge-add-longhorn-disk.sh --node <hostname> --path <path>"
