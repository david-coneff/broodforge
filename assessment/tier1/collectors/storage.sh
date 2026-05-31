#!/usr/bin/env bash
# Collector: storage
# Writes: lsblk_json.json, lsblk.txt, df.txt, zpool_status.txt,
#         zpool_list_json.json, zfs_list.txt, pvesm_status.txt
set -euo pipefail
OUTDIR="${1:-.}"

# Block devices — prefer JSON, fall back to text
lsblk -J -b -o NAME,SIZE,TYPE,ROTA,MODEL,TRAN,WWN,MOUNTPOINT 2>/dev/null \
    > "${OUTDIR}/lsblk_json.json" || true
lsblk -b -o NAME,SIZE,TYPE,ROTA,MODEL,TRAN,MOUNTPOINT \
    > "${OUTDIR}/lsblk.txt" 2>/dev/null || true

df -B1 > "${OUTDIR}/df.txt" 2>/dev/null || true

# ZFS — only if available
if command -v zpool &>/dev/null; then
    zpool status -P  > "${OUTDIR}/zpool_status.txt" 2>/dev/null || true
    zpool list -H -p -o name,size,free,health,altroot 2>/dev/null \
        > "${OUTDIR}/zpool_list.txt" || true
    zfs list -H -p -o name,used,avail,refer,mountpoint \
        > "${OUTDIR}/zfs_list.txt" 2>/dev/null || true
fi

# Proxmox storage — only if pvesm available
if command -v pvesm &>/dev/null; then
    pvesm status > "${OUTDIR}/pvesm_status.txt" 2>/dev/null || true
fi
