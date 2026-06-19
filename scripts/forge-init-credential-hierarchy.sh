#!/usr/bin/env bash
# forge-init-credential-hierarchy.sh — One-time credential hierarchy setup.
#
# Creates the three child KeePass databases (forge-autonomous, forge-spawn,
# forge-migrate), generates passwords for each, stores those passwords as
# entries in the master KeePass, writes credential-hierarchy.json, and prints
# KeeShare GUI setup instructions.
#
# Run exactly once during initial broodforge setup (Phase 1.P).
# Re-running is safe: existing files are skipped; existing config is preserved.
#
# Requirements:
#   - keepassxc-cli in PATH (KeePassXC >= 2.7)
#   - Master KeePass database accessible (forge_keepass_gate will prompt)
#   - BROODFORGE_STATE_DIR set or defaults to /var/lib/broodforge
#
# Exit codes:
#   0 — success
#   1 — error (keepassxc-cli not found, master DB locked, etc.)
#   2 — NOT_IMPLEMENTED (partial — see message)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LIB_SH="${REPO_ROOT}/lib/forge-lib.sh"

STATE_DIR="${BROODFORGE_STATE_DIR:-/var/lib/broodforge}"
HIER_CONFIG="${STATE_DIR}/credential-hierarchy.json"

CHILD_DBS=(
  "forge-autonomous"
  "forge-spawn"
  "forge-migrate"
)

# Scope descriptions (parallel array — same order as CHILD_DBS)
# shellcheck disable=SC2034  # CHILD_DB_SCOPES is documentation-only; used by deploy scripts that source this
CHILD_DB_SCOPES=(
  "Autonomous operation credentials: restic repo password, k8s service account tokens, monitoring API keys, Headscale API key"
  "Spawn-phase credentials: Cloud-Init keypairs, spawn-phase node credentials, Headscale pre-auth keys"
  "Migration-phase credentials: temporary elevated access (mostly empty; populated during migration ceremony only)"
)

# ---------------------------------------------------------------------------

die() { echo "[init-hierarchy] ERROR: $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Load forge-lib.sh
# ---------------------------------------------------------------------------

[[ -f "$LIB_SH" ]] || die "forge-lib.sh not found at $LIB_SH"
# shellcheck source=../lib/forge-lib.sh
source "$LIB_SH"

# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------

echo ""
echo "================================================================="
echo " forge-init-credential-hierarchy.sh — Phase 1.P setup"
echo "================================================================="
echo ""

command -v keepassxc-cli &>/dev/null \
  || die "keepassxc-cli not found — install KeePassXC >= 2.7 and add to PATH"

command -v python3 &>/dev/null \
  || die "python3 not found — required for hierarchy config management"

mkdir -p "$STATE_DIR" || die "Cannot create state directory: $STATE_DIR"

# KeePass gate — operator must be present
forge_keepass_gate

# ---------------------------------------------------------------------------
# Step 1: Create child databases
# ---------------------------------------------------------------------------

echo ""
echo "── Creating child databases ─────────────────────────────────────"

declare -A CHILD_DB_PASSWORDS

for db_name in "${CHILD_DBS[@]}"; do
  db_path="${STATE_DIR}/${db_name}.kdbx"

  if [[ -f "$db_path" ]]; then
    echo "  ○ ${db_name}.kdbx already exists — skipping creation"
    # We still need a password — generate a placeholder; operator must set it manually
    # if it was created outside this script.
    CHILD_DB_PASSWORDS["$db_name"]="EXISTING_DB_PASSWORD_UNKNOWN"
    continue
  fi

  # Generate a strong random password for this child DB
  local_pw=$(LC_ALL=C tr -dc 'A-Za-z0-9!@#$%^&*()_+-=' </dev/urandom | head -c 48 2>/dev/null \
    || openssl rand -base64 36 | tr -d '=\n' | head -c 48)
  CHILD_DB_PASSWORDS["$db_name"]="$local_pw"

  printf '  Creating %s...' "$db_path"
  if echo "$local_pw" | keepassxc-cli db-create \
      --decryption-time 100 \
      "$db_path" \
      >/dev/null 2>&1; then
    echo " ✓"
  else
    echo " ✗"
    die "Failed to create $db_path — check keepassxc-cli version and permissions"
  fi

  unset local_pw
done

# ---------------------------------------------------------------------------
# Step 2: Store child DB passwords in master KeePass
# ---------------------------------------------------------------------------

echo ""
echo "── Storing child DB passwords in master KeePass ─────────────────"
echo "   Entry path: Broodforge/child-dbs/<db-name>"
echo ""

_STORE_FAILURES=0

for db_name in "${CHILD_DBS[@]}"; do
  entry_path="Broodforge/child-dbs/${db_name}"
  child_pw="${CHILD_DB_PASSWORDS[$db_name]}"

  if [[ "$child_pw" == "EXISTING_DB_PASSWORD_UNKNOWN" ]]; then
    echo "  ⚠ ${db_name}: database pre-existed — password unknown."
    echo "    Manually add the entry '${entry_path}' to your master KeePass."
    _STORE_FAILURES=$(( _STORE_FAILURES + 1 ))
    continue
  fi

  # Try keepassxc-cli add with --password flag (KeePassXC >= 2.7)
  printf '  Storing %s...' "$entry_path"
  if printf '%s\n' "$KEEPASS_MASTER_PASSWORD" | keepassxc-cli add \
      --quiet \
      --username "broodforge-child-db" \
      --password "$child_pw" \
      "$FORGE_KDBX_PATH" \
      "$entry_path" \
      >/dev/null 2>&1; then
    echo " ✓"
  else
    echo " ✗ (CLI add failed — see manual step below)"
    echo ""
    echo "  ┌──────────────────────────────────────────────────────────────"
    echo "  │  MANUAL ACTION REQUIRED: Add this entry to your master KeePass"
    echo "  │  Entry path   : $entry_path"
    # Print password to tty only — not to stdout/log
    printf '  │  Password     : %s\n' "$child_pw" >/dev/tty
    echo "  │  Username     : broodforge-child-db"
    echo "  └──────────────────────────────────────────────────────────────"
    echo ""
    _STORE_FAILURES=$(( _STORE_FAILURES + 1 ))
  fi

  # Clear from local scope
  unset child_pw
done

if (( _STORE_FAILURES > 0 )); then
  echo "  ⚠ ${_STORE_FAILURES} password(s) could not be stored automatically."
  echo "  Complete the manual steps above before proceeding."
fi

# ---------------------------------------------------------------------------
# Step 3: Write credential-hierarchy.json
# ---------------------------------------------------------------------------

echo ""
echo "── Writing credential-hierarchy.json ───────────────────────────"

if [[ -f "$HIER_CONFIG" ]]; then
  echo "  ○ $HIER_CONFIG already exists — skipping (delete it to regenerate)"
else
  python3 - <<PYEOF
import json, sys
from pathlib import Path

state_dir = "${STATE_DIR}"
master_path = "${FORGE_KDBX_PATH}"

scopes = {
  "forge-autonomous": "Autonomous operation credentials: restic repo password, k8s service account tokens, monitoring API keys, Headscale API key",
  "forge-spawn":      "Spawn-phase credentials: Cloud-Init keypairs, spawn-phase node credentials, Headscale pre-auth keys",
  "forge-migrate":    "Migration-phase credentials: temporary elevated access (mostly empty; populated during migration ceremony only)",
}

child_databases = [
  {
    "name":              name,
    "path":              f"{state_dir}/{name}.kdbx",
    "master_entry":      f"Broodforge/child-dbs/{name}",
    "scope_description": scopes[name],
  }
  for name in ("forge-autonomous", "forge-spawn", "forge-migrate")
]

config = {
  "hierarchy_version": "1",
  "master_db_path":    master_path,
  "child_databases":   child_databases,
}

out = Path("${HIER_CONFIG}")
out.parent.mkdir(parents=True, exist_ok=True)
tmp = out.with_suffix(".json.tmp")
try:
    with open(tmp, "w") as fh:
        json.dump(config, fh, indent=2)
        fh.write("\n")
    tmp.replace(out)
    print(f"  ✓ Wrote: {out}")
except Exception as exc:
    tmp.unlink(missing_ok=True)
    print(f"  ✗ Failed: {exc}", file=sys.stderr)
    sys.exit(1)
PYEOF
fi

# ---------------------------------------------------------------------------
# Step 4: KeeShare setup instructions (GUI — CLI does not support KeeShare)
# ---------------------------------------------------------------------------

echo ""
echo "┌────────────────────────────────────────────────────────────────────"
echo "│  Manual step required: KeeShare one-way sync setup"
echo "│"
echo "│  KeePassXC CLI does not support KeeShare configuration."
echo "│  Perform this setup ONCE in the KeePassXC GUI:"
echo "│"
echo "│  For each child database (forge-autonomous, forge-spawn, forge-migrate):"
echo "│"
echo "│  1. Open the MASTER database in KeePassXC."
echo "│     Database → Database Settings → KeeShare → Export"
echo "│     Click 'Export to …' and enable sharing for the group:"
echo "│       'Broodforge/child-dbs'   (or the relevant group)"
echo "│     Set type: 'Export to / one-way (master authoritative)'"
echo "│     Save the .keeshare export file alongside the child .kdbx."
echo "│"
echo "│  2. Open each CHILD database in a separate KeePassXC window."
echo "│     Database → Database Settings → KeeShare → Import"
echo "│     Click 'Receive from …' and point it at the .keeshare file"
echo "│     from step 1."
echo "│     Set type: 'Import from / one-way (accept changes from master)'"
echo "│"
echo "│  3. Click 'OK' and let KeeShare synchronise."
echo "│     The child database now mirrors the exported group from master."
echo "│"
echo "│  After GUI setup, credential rotations are propagated automatically"
echo "│  by forge-rotate-credential.sh (step 5 calls forge-sync-credentials.sh"
echo "│  which triggers the KeeShare merge — no operator GUI action needed"
echo "│  for subsequent rotations once the initial sync is configured)."
echo "│"
echo "└────────────────────────────────────────────────────────────────────"
echo ""

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

echo "forge-init-credential-hierarchy.sh complete."
echo ""
echo "Next steps:"
echo "  1. Complete the KeeShare GUI setup described above (one-time)."
echo "  2. Run: python3 proxmox-bootstrap/credential_hierarchy.py --list"
echo "     to verify the hierarchy config."
echo "  3. Use forge-rotate-credential.sh to perform key rotations."
echo "     Syncs to child DBs will happen automatically."
echo ""
