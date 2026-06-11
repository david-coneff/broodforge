#!/usr/bin/env bash
# forge-add-longhorn-disk.sh — Register a node disk/path with Longhorn (Phase 2.E).
#
# This script records the disk in broodforge's storage registry AND patches the
# Longhorn Node CR so that Longhorn actually starts using the disk.
#
# PAP constraints: KeePass gate; no credentials in env/argv/logs.
#
# Usage:
#   ./forge-add-longhorn-disk.sh --node <hostname> --path <path>
#       [--disk-type filesystem|block] [--tags ssd,fast]
#       [--storage-reserved <MB>] [--no-scheduling] [--state-dir <dir>]

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="$(cd "${SCRIPT_DIR}/../lib" && pwd)"
BOOTSTRAP_DIR="$(cd "${SCRIPT_DIR}/../proxmox-bootstrap" && pwd)"
# shellcheck source=../lib/forge-lib.sh
source "${LIB_DIR}/forge-lib.sh"

NODE_HOSTNAME=""
DISK_PATH=""
DISK_TYPE="filesystem"
TAGS=""
STORAGE_RESERVED_MB="2048"
ALLOW_SCHEDULING="true"
LONGHORN_NAMESPACE="longhorn-system"
STATE_DIR="${BROODFORGE_STATE_DIR:-/var/lib/broodforge}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --node)             NODE_HOSTNAME="$2";     shift 2 ;;
        --path)             DISK_PATH="$2";         shift 2 ;;
        --disk-type)        DISK_TYPE="$2";         shift 2 ;;
        --tags)             TAGS="$2";              shift 2 ;;
        --storage-reserved) STORAGE_RESERVED_MB="$2"; shift 2 ;;
        --no-scheduling)    ALLOW_SCHEDULING="false"; shift 1 ;;
        --namespace)        LONGHORN_NAMESPACE="$2"; shift 2 ;;
        --state-dir)        STATE_DIR="$2";         shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

if [[ -z "${NODE_HOSTNAME}" || -z "${DISK_PATH}" ]]; then
    echo "Error: --node and --path are required" >&2
    exit 1
fi

echo "[forge-add-longhorn-disk] Step 1: KeePass gate"
forge_keepass_gate

echo "[forge-add-longhorn-disk] Step 2: Recording disk in storage registry"
SCHED_FLAG="--allow-scheduling"
[[ "${ALLOW_SCHEDULING}" == "false" ]] && SCHED_FLAG="--no-scheduling"

python3 "${BOOTSTRAP_DIR}/storage_manager.py" --state "${STATE_DIR}" \
    register-node-disk \
    --node "${NODE_HOSTNAME}" \
    --path "${DISK_PATH}" \
    --disk-type "${DISK_TYPE}" \
    ${TAGS:+--tags "${TAGS}"} \
    "${SCHED_FLAG}" \
    --storage-reserved "${STORAGE_RESERVED_MB}"

echo "[forge-add-longhorn-disk] Step 3: Patching Longhorn Node CR"
# Build the disks patch — Longhorn Node CRs use a 'disks' map keyed by disk name.
DISK_KEY="disk-$(echo "${DISK_PATH}" | tr '/' '-' | sed 's/^-//')"
ALLOW_JSON=$([ "${ALLOW_SCHEDULING}" == "true" ] && echo "true" || echo "false")

PATCH_JSON=$(python3 - <<EOF
import json, sys
disk_key = "${DISK_KEY}"
patch = {"spec": {"disks": {disk_key: {
    "path": "${DISK_PATH}",
    "allowScheduling": ${ALLOW_JSON},
    "diskType": "${DISK_TYPE}",
    "storageReserved": ${STORAGE_RESERVED_MB} * 1024 * 1024,
    "tags": [t.strip() for t in "${TAGS}".split(",") if t.strip()],
}}}}
print(json.dumps(patch))
EOF
)

kubectl patch node.longhorn.io "${NODE_HOSTNAME}" \
    -n "${LONGHORN_NAMESPACE}" \
    --type=merge \
    -p "${PATCH_JSON}" 2>/dev/null || \
    echo "  Note: Longhorn Node CR not found (may not be deployed yet — disk recorded in registry only)"

echo ""
echo "[forge-add-longhorn-disk] Disk registered: ${NODE_HOSTNAME}:${DISK_PATH}"
echo "  Type: ${DISK_TYPE}  Scheduling: ${ALLOW_SCHEDULING}  Reserved: ${STORAGE_RESERVED_MB}MB"
echo "  Disks: python3 proxmox-bootstrap/storage_manager.py --state ${STATE_DIR} list-disks"
