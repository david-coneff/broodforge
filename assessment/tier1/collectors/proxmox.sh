#!/usr/bin/env bash
# Collector: proxmox
# Writes: pveversion.txt, qm_list.txt, pct_list.txt, pve_nodes.txt,
#         hostname.txt, uname.txt, dmidecode.txt
set -euo pipefail
OUTDIR="${1:-.}"

hostname -f > "${OUTDIR}/hostname.txt" 2>/dev/null || hostname > "${OUTDIR}/hostname.txt" 2>/dev/null || true
uname -a > "${OUTDIR}/uname.txt" 2>/dev/null || true
date -u +"%Y-%m-%dT%H:%M:%SZ" > "${OUTDIR}/collected_at.txt" 2>/dev/null || true
cat /proc/uptime > "${OUTDIR}/uptime.txt" 2>/dev/null || true
cat /etc/timezone > "${OUTDIR}/timezone.txt" 2>/dev/null || true

# Proxmox-specific — gracefully absent on non-PVE hosts
pveversion -v > "${OUTDIR}/pveversion.txt" 2>/dev/null || true
qm list > "${OUTDIR}/qm_list.txt" 2>/dev/null || true
pct list > "${OUTDIR}/pct_list.txt" 2>/dev/null || true
pvecm nodes > "${OUTDIR}/pve_nodes.txt" 2>/dev/null || true

# Hardware info — needs root; partial output is still useful
dmidecode > "${OUTDIR}/dmidecode.txt" 2>/dev/null || \
    echo "dmidecode not available or requires root" > "${OUTDIR}/dmidecode.txt"
