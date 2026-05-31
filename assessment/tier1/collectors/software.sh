#!/usr/bin/env bash
# Collector: software
# Writes: dpkg_list.txt, systemctl_list.txt
set -euo pipefail
OUTDIR="${1:-.}"

# Installed packages
dpkg-query -W -f='${Package}\t${Version}\t${Status}\n' \
    > "${OUTDIR}/dpkg_list.txt" 2>/dev/null || true

# Running services
systemctl list-units --type=service --state=running --no-legend --no-pager \
    > "${OUTDIR}/systemctl_list.txt" 2>/dev/null || true

# Spot-check automation tools
for cmd in git python3 ansible ansible-playbook terraform tofu curl wget rsync; do
    if command -v "$cmd" &>/dev/null; then
        echo "${cmd} $($cmd --version 2>&1 | head -1)" >> "${OUTDIR}/tool_versions.txt"
    fi
done 2>/dev/null || true
