#!/usr/bin/env bash
# forge-init-openbao.sh — Phase 3.L: OpenBao Bootstrap Ceremony
# ==============================================================
# One-time operator-gated script to seed OpenBao from KeePass child DBs.
#
# Prerequisites:
#   1. OpenBao installed and running (but not yet initialized)
#   2. KeePass master DB accessible via keepassxc-cli
#   3. Python 3.9+ with openbao_manager.py in proxmox-bootstrap/
#   4. UNSEAL_STRATEGY and KEEPASS_MODE set in /etc/broodforge/openbao-config.json
#
# Usage:  sudo bash scripts/forge-init-openbao.sh [--dry-run] [--skip-totp]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BAO_MGR="$REPO_ROOT/proxmox-bootstrap/openbao_manager.py"
CONFIG_FILE="${OPENBAO_CONFIG:-/etc/broodforge/openbao-config.json}"
TOKEN_DIR="/run/broodforge"
LOG_FILE="/var/log/broodforge/forge-init-openbao.log"
DRY_RUN=false
SKIP_TOTP=false

RED='\033[0;31m'; YELLOW='\033[0;33m'; GREEN='\033[0;32m'; NC='\033[0m'
info()  { echo -e "${GREEN}[forge-init]${NC} $*" | tee -a "$LOG_FILE"; }
warn()  { echo -e "${YELLOW}[forge-init]${NC} $*" | tee -a "$LOG_FILE"; }
error() { echo -e "${RED}[forge-init] ERROR:${NC} $*" | tee -a "$LOG_FILE"; exit 1; }
prompt(){ echo -e "${YELLOW}[forge-init] >>>${NC} $*"; }

for arg in "$@"; do
  case "$arg" in
    --dry-run)   DRY_RUN=true ;;
    --skip-totp) SKIP_TOTP=true ;;
    --help|-h) sed -n '2,10p' "$0" | sed 's/^# //'; exit 0 ;;
  esac
done

preflight() {
  info "Pre-flight checks..."
  command -v keepassxc-cli >/dev/null 2>&1 || error "keepassxc-cli not found"
  command -v python3       >/dev/null 2>&1 || error "python3 not found"
  [[ -f "$BAO_MGR" ]]     || error "openbao_manager.py not found at $BAO_MGR"
  [[ -f "$CONFIG_FILE" ]] || warn "Config not found at $CONFIG_FILE — using defaults"

  OPENBAO_ADDR="${OPENBAO_ADDR:-http://127.0.0.1:8200}"
  curl -sf "$OPENBAO_ADDR/v1/sys/health" --max-time 5 >/dev/null 2>&1 \
    || error "OpenBao not reachable at $OPENBAO_ADDR"
  info "OpenBao reachable at $OPENBAO_ADDR"

  INIT_STATUS="$(curl -sf "$OPENBAO_ADDR/v1/sys/init" \
    | python3 -c 'import sys,json; print(json.load(sys.stdin).get("initialized",False))')"
  [[ "$INIT_STATUS" == "True" ]] && ALREADY_INITIALIZED=true || ALREADY_INITIALIZED=false

  mkdir -p "$TOKEN_DIR" /var/log/broodforge
  info "Pre-flight OK"
}

bao_init() {
  [[ "$ALREADY_INITIALIZED" == "true" ]] && { info "Already initialized — skipping"; return; }
  info "Initializing OpenBao..."
  [[ "$DRY_RUN" == "true" ]] && { warn "[dry-run] Would init"; return; }

  python3 "$BAO_MGR" --config "$CONFIG_FILE" init

  UNSEAL_STRATEGY="$(python3 -c "
import json,pathlib; cfg={}
p=pathlib.Path('$CONFIG_FILE')
if p.exists(): cfg=json.loads(p.read_text())
print(cfg.get('unseal_strategy','shamir'))
")"
  if [[ "$UNSEAL_STRATEGY" == "shamir" ]]; then
    warn ""
    warn "=== SHAMIR UNSEAL KEYS ABOVE — STORE THEM SECURELY NOW ==="
    warn "  Shards 1-2 → KeePass master DB (forge-master/openbao)"
    warn "  Shards 3-4 → Offline USB keys"
    warn "  Shard  5   → governance VM TPM-sealed key file"
    warn "================================================================"
    prompt "Press ENTER when all shards are stored..."
    read -r _
  fi
}

bao_unseal() {
  SEALED="$(python3 "$BAO_MGR" --config "$CONFIG_FILE" status 2>/dev/null \
    | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("seal_status",{}).get("sealed",True))')"
  [[ "$SEALED" == "False" || "$SEALED" == "false" ]] && { info "Already unsealed"; return; }

  STRATEGY="$(python3 -c "
import json,pathlib; cfg={}
p=pathlib.Path('$CONFIG_FILE')
if p.exists(): cfg=json.loads(p.read_text())
print(cfg.get('unseal_strategy','shamir'))
")"

  if [[ "$STRATEGY" == "transit" ]]; then
    python3 "$BAO_MGR" --config "$CONFIG_FILE" unseal
  else
    SHARDS_FILE="$(mktemp /tmp/bao-shards.XXXXXX.json)"
    trap 'rm -f "$SHARDS_FILE"' EXIT
    SHARDS="[]"
    for i in 1 2 3; do
      prompt "Enter unseal shard $i/3 (hidden):"
      read -rs SHARD; echo
      SHARDS="$(echo "$SHARDS" | python3 -c "
import sys,json; lst=json.load(sys.stdin); lst.append('$SHARD'); print(json.dumps(lst))
")"
    done
    echo "$SHARDS" > "$SHARDS_FILE"
    [[ "$DRY_RUN" == "true" ]] \
      && warn "[dry-run] Would unseal with 3 shards" \
      || python3 "$BAO_MGR" --config "$CONFIG_FILE" unseal --keys-file "$SHARDS_FILE"
  fi
  info "OpenBao unsealed"
}

get_root_token() {
  prompt "Enter root token (from init output, hidden):"
  read -rs ROOT_TOKEN; echo
  export OPENBAO_TOKEN="$ROOT_TOKEN"
}

bao_mounts() {
  info "Enabling mounts..."
  [[ "$DRY_RUN" == "true" ]] && { warn "[dry-run] Would mount KV + TOTP"; return; }
  python3 "$BAO_MGR" --config "$CONFIG_FILE" mount-setup
}

bao_policies() {
  info "Applying policies..."
  [[ "$DRY_RUN" == "true" ]] && { warn "[dry-run] Would apply-all"; return; }
  python3 "$BAO_MGR" --config "$CONFIG_FILE" policy apply-all
}

migrate_db() {
  local DB_PATH="$1" DB_ALIAS="$2" DB_PASS
  [[ -f "$DB_PATH" ]] || { warn "Skipping $DB_ALIAS: $DB_PATH not found"; return; }
  prompt "KeePass password for $DB_ALIAS ($DB_PATH, hidden):"
  read -rs DB_PASS; echo
  info "Migrating $DB_ALIAS entries..."
  while IFS= read -r ENTRY; do
    [[ -z "$ENTRY" ]] && continue
    VALUE="$(keepassxc-cli show "$DB_PATH" "$ENTRY" --no-password -a Password - <<< "$DB_PASS" 2>/dev/null || true)"
    [[ -z "$VALUE" ]] && continue
    BAO_PATH="forge/$DB_ALIAS/$ENTRY"
    if [[ "$DRY_RUN" == "true" ]]; then
      warn "[dry-run] Would write: $BAO_PATH"
    else
      python3 "$BAO_MGR" --config "$CONFIG_FILE" write "$BAO_PATH" --value "$VALUE"
      info "  Written: $BAO_PATH"
    fi
  done < <(keepassxc-cli ls -R "$DB_PATH" --no-password - <<< "$DB_PASS" 2>/dev/null || true)
  info "$DB_ALIAS migration done"
}

migrate_secrets() {
  info "=== Secret Migration: KeePass → OpenBao ==="
  migrate_db "${DB_AUTONOMOUS:-/etc/broodforge/kdbx/forge-autonomous.kdbx}" "autonomous"
  migrate_db "${DB_SPAWN:-/etc/broodforge/kdbx/forge-spawn.kdbx}"           "spawn"
  migrate_db "${DB_MIGRATE:-/etc/broodforge/kdbx/forge-migrate.kdbx}"       "migrate"
}

migrate_totp() {
  [[ "$SKIP_TOTP" == "true" ]] && { info "Skipping TOTP migration"; return; }
  TOTP_DB="${TOTP_DB:-/etc/broodforge/kdbx/forge-autonomous.kdbx}"
  [[ -f "$TOTP_DB" ]] || { warn "TOTP DB not found — skipping"; return; }
  info "=== TOTP Migration ==="
  prompt "KeePass password for TOTP DB (hidden):"
  read -rs TOTP_PASS; echo
  while IFS= read -r ENTRY; do
    [[ -z "$ENTRY" ]] && continue
    TOTP_CODE="$(keepassxc-cli show "$TOTP_DB" "$ENTRY" --no-password --totp - <<< "$TOTP_PASS" 2>/dev/null || true)"
    [[ "$TOTP_CODE" =~ ^[0-9]{6}$ ]] || continue
    OTP_URL="$(keepassxc-cli show "$TOTP_DB" "$ENTRY" --no-password -a otp - <<< "$TOTP_PASS" 2>/dev/null || true)"
    [[ "$OTP_URL" =~ secret=([A-Z2-7]+) ]] || continue
    SECRET_B32="${BASH_REMATCH[1]}"
    ACCOUNT="${ENTRY##*/}"
    if [[ "$DRY_RUN" == "true" ]]; then
      warn "[dry-run] Would register TOTP: $ACCOUNT"
    else
      python3 - << PYEOF
import sys; sys.path.insert(0,'$REPO_ROOT/proxmox-bootstrap')
from openbao_manager import OpenBaoManager, load_config
from pathlib import Path
mgr = OpenBaoManager(load_config(Path('$CONFIG_FILE')))
mgr.totp_create('$ACCOUNT','broodforge','$SECRET_B32')
print('TOTP registered: $ACCOUNT')
PYEOF
    fi
  done < <(keepassxc-cli ls "$TOTP_DB" --no-password - <<< "$TOTP_PASS" 2>/dev/null || true)
  info "TOTP migration done"
}

create_service_tokens() {
  info "Creating service tokens..."
  for ROLE in autonomous spawn migrate; do
    TOKEN_FILE="$TOKEN_DIR/openbao-token-$ROLE"
    [[ "$DRY_RUN" == "true" ]] && { warn "[dry-run] Would create token: forge-$ROLE"; continue; }
    TOK="$(python3 - << PYEOF
import sys,json; sys.path.insert(0,'$REPO_ROOT/proxmox-bootstrap')
from openbao_manager import OpenBaoManager, load_config
from pathlib import Path
mgr = OpenBaoManager(load_config(Path('$CONFIG_FILE')))
resp = mgr.token_create(['forge-$ROLE'],ttl='720h',display_name='broodforge-$ROLE',no_parent=True)
print(resp['auth']['client_token'])
PYEOF
)"
    echo "$TOK" > "$TOKEN_FILE"
    chmod 600 "$TOKEN_FILE"
    info "  Token → $TOKEN_FILE"
  done
}

revoke_root_token() {
  warn ""
  warn "=== FINAL STEP: Revoke root token ==="
  [[ "$DRY_RUN" == "true" ]] && { warn "[dry-run] Would revoke root token"; return; }
  prompt "Revoke root token now? [y/N]"
  read -r CONFIRM
  if [[ "$CONFIRM" =~ ^[Yy]$ ]]; then
    curl -sf -X POST "$OPENBAO_ADDR/v1/auth/token/revoke-self" \
      -H "X-Vault-Token: $OPENBAO_TOKEN" >/dev/null
    unset OPENBAO_TOKEN
    info "Root token revoked."
  else
    warn "Root token NOT revoked — run: bao token revoke-self"
  fi
}

summary() {
  info ""
  info "=== Bootstrap complete! Next steps ==="
  info "1. Set keepass_mode in /etc/broodforge/openbao-config.json"
  info "2. Update lib/forge-lib.sh: replace kdbx_get_child/kdbx_totp with openbao_manager.py calls"
  info "3. Test: OPENBAO_TOKEN=\$(cat /run/broodforge/openbao-token-autonomous)"
  info "         python3 proxmox-bootstrap/openbao_manager.py read forge/autonomous/proxmox/api_token"
  info "4. Mount ramfs at /run/broodforge via systemd (tokens must not touch disk)"
  [[ "$SKIP_TOTP" == "true" ]] && info "5. Re-run without --skip-totp to migrate TOTP accounts"
}

main() {
  [[ "$DRY_RUN" == "true" ]] && warn "=== DRY RUN — no changes will be made ==="
  info "OpenBao Bootstrap Ceremony: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  preflight; bao_init; bao_unseal; get_root_token
  bao_mounts; bao_policies; migrate_secrets; migrate_totp
  create_service_tokens; revoke_root_token; summary
}

main "$@"
