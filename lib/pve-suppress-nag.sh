#!/usr/bin/env bash
# pve-suppress-nag.sh — Patch Proxmox web UI to remove subscription nag popup (AD-046).
#
# Proxmox Community Edition is fully functional without a subscription.
# This script removes the recurring UI reminder for homelab operators.
#
# Applied during forge phase-03 (host config) and re-applied automatically
# after Proxmox package upgrades via the dpkg post-invoke hook installed here.
#
# Idempotent: safe to run multiple times.
set -euo pipefail

PROXMOX_LIB="/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js"
MARKER="# broodforge-nag-suppressed"
HOOK_FILE="/etc/apt/apt.conf.d/85pve-nag-suppress"

# ---------------------------------------------------------------------------
patch_proxmox_lib() {
  if [ ! -f "$PROXMOX_LIB" ]; then
    echo "[nag] $PROXMOX_LIB not found — Proxmox not installed or path changed." >&2
    return 1
  fi

  if grep -q "$MARKER" "$PROXMOX_LIB"; then
    echo "[nag] Already patched — nothing to do."
    return 0
  fi

  # Neutralise the subscription dialog Ext.Msg.show call.
  # The target line looks like:
  #   if (data.status !== 'Active') { Ext.Msg.show({...}) }
  # We replace the branch condition so the show() block is never entered.
  if sed -i 's/if\s*(data\.status\s*!==\s*'\''Active'\'')/if (false) \/\/ nag-suppressed/g' \
       "$PROXMOX_LIB"; then
    echo "$MARKER" >> "$PROXMOX_LIB"
    echo "[nag] Patched $PROXMOX_LIB — subscription nag suppressed."
    # Restart pveproxy so the browser serves the patched file
    systemctl restart pveproxy 2>/dev/null || true
  else
    echo "[nag] sed failed — check $PROXMOX_LIB format." >&2
    return 1
  fi
}

# ---------------------------------------------------------------------------
install_dpkg_hook() {
  if [ -f "$HOOK_FILE" ]; then
    echo "[nag] dpkg hook already installed at $HOOK_FILE."
    return 0
  fi
  cat > "$HOOK_FILE" << 'HOOK'
# broodforge: Re-apply Proxmox nag suppression after package upgrades.
DPkg::Post-Invoke {
  "if dpkg -l proxmox-widget-toolkit 2>/dev/null | grep -q '^ii'; then \
     /bin/bash /usr/local/lib/broodforge/pve-suppress-nag.sh; fi";
};
HOOK
  echo "[nag] Installed dpkg post-invoke hook at $HOOK_FILE."

  # Install this script to a stable system path referenced by the hook
  install -Dm755 "$0" /usr/local/lib/broodforge/pve-suppress-nag.sh
  echo "[nag] Installed script to /usr/local/lib/broodforge/pve-suppress-nag.sh"
}

# ---------------------------------------------------------------------------
main() {
  if [ "$(id -u)" -ne 0 ]; then
    echo "[nag] Must be run as root." >&2
    exit 1
  fi
  patch_proxmox_lib
  install_dpkg_hook
  echo "[nag] Done."
}

main "$@"
