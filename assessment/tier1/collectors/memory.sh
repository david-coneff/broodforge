#!/usr/bin/env bash
# Collector: memory
# Writes: memory.txt, meminfo.txt
set -euo pipefail
OUTDIR="${1:-.}"

free -b > "${OUTDIR}/memory.txt" 2>/dev/null || true
cat /proc/meminfo > "${OUTDIR}/meminfo.txt" 2>/dev/null || true
