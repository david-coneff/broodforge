#!/usr/bin/env bash
# Collector: cpu
# Writes: lscpu.txt, lscpu_json.json (if supported), cpuinfo.txt
set -euo pipefail
OUTDIR="${1:-.}"

lscpu > "${OUTDIR}/lscpu.txt" 2>/dev/null || true
lscpu -J > "${OUTDIR}/lscpu_json.json" 2>/dev/null || true
cat /proc/cpuinfo > "${OUTDIR}/cpuinfo.txt" 2>/dev/null || true
