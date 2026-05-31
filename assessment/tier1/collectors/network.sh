#!/usr/bin/env bash
# Collector: network
# Writes: ip_addr.txt, ip_addr_json.json, ip_route.txt, ip_route_json.json,
#         network_interfaces.txt, resolv_conf.txt
set -euo pipefail
OUTDIR="${1:-.}"

ip addr show > "${OUTDIR}/ip_addr.txt" 2>/dev/null || true
ip -j addr show > "${OUTDIR}/ip_addr_json.json" 2>/dev/null || true
ip route show > "${OUTDIR}/ip_route.txt" 2>/dev/null || true
ip -j route show > "${OUTDIR}/ip_route_json.json" 2>/dev/null || true

# Proxmox network config
[ -f /etc/network/interfaces ] && \
    cat /etc/network/interfaces > "${OUTDIR}/network_interfaces.txt" 2>/dev/null || true

# DNS config
[ -f /etc/resolv.conf ] && \
    cat /etc/resolv.conf > "${OUTDIR}/resolv_conf.txt" 2>/dev/null || true
