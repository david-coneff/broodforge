#!/usr/bin/env bash
# forge-build-node-iso.sh — Phase 1.Q: Zero-touch node ISO builder
#
# Generates answer.toml and a bootstrap script for a planned broodling node,
# then prints operator instructions to run proxmox-auto-install-assistant on
# the Proxmox host. The assistant itself must run ON THE PROXMOX HOST (not the
# hatchery VM) because it manipulates ISOs in a way that requires Proxmox
# tooling.
#
# What this script produces (in the output directory):
#   <codename>/
#     answer.toml              — Proxmox auto-install answer file
#     broodling-bootstrap.sh   — Post-install bootstrap (embedded in ISO)
#     README-operator.txt      — Instructions for running proxmox-auto-install-assistant
#
# The bootstrap script:
#   - Generates the broodling RSA key pair on first boot
#   - Posts its public key + join PIN to the hatchery /api/node-register endpoint
#   - Installs Headscale client using the embedded pre-auth key
#   - Waits for operator approval before doing anything further
#
# Usage:
#   ./scripts/forge-build-node-iso.sh --codename swift-falcon [OPTIONS]
#
# Exit codes:
#   0 — success
#   1 — fatal error
#   2 — NOT_IMPLEMENTED

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# shellcheck source=lib/forge-lib.sh
source "${REPO_ROOT}/lib/forge-lib.sh"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

CODENAME=""
OUTPUT_DIR="${BROODFORGE_ISO_OUTPUT_DIR:-/var/lib/broodforge/iso-staging}"
STATE_DIR="${BROODFORGE_STATE_DIR:-/var/lib/broodforge}"
HATCHERY_URL="${BROODFORGE_HATCHERY_URL:-}"
HATCHERY_PUBKEY_PATH="${BROODFORGE_HATCHERY_PUBKEY:-/etc/broodforge/hatchery-public.pem}"
PROXMOX_ISO="${BROODFORGE_PVE_ISO:-}"  # base Proxmox ISO path
# shellcheck disable=SC2034  # PVE_ROOT_USER passed to child scripts via environment
PVE_ROOT_USER="${BROODFORGE_PVE_ROOT_USER:-root}"
PVE_NET_IFACE="${BROODFORGE_PVE_NET_IFACE:-}"
PVE_TIMEZONE="${BROODFORGE_PVE_TIMEZONE:-UTC}"
PYTHON="${BROODFORGE_PYTHON:-python3}"
NODE_PLANNER="${REPO_ROOT}/proxmox-bootstrap/node_planner.py"

# ---------------------------------------------------------------------------
# Arg parsing
# ---------------------------------------------------------------------------

usage() {
    cat <<EOF
Usage: $(basename "$0") --codename CODENAME [OPTIONS]

Build ISO artifacts for a planned broodling node.

OPTIONS:
  -c, --codename NAME       Node codename (required, must exist in planned state)
  -o, --output-dir DIR      Directory for generated artifacts (default: ${OUTPUT_DIR})
      --pve-iso PATH        Path to base Proxmox VE ISO
      --hatchery-url URL    Hatchery registration URL (default: from env/KeePass)
      --iface NAME          Network interface for Proxmox install (e.g. eth0)
      --timezone TZ         Timezone for installed Proxmox (default: UTC)
  -h, --help                Show this help

ENVIRONMENT:
  BROODFORGE_STATE_DIR          State directory (default: /var/lib/broodforge)
  BROODFORGE_ISO_OUTPUT_DIR     ISO staging directory
  BROODFORGE_HATCHERY_URL       Hatchery base URL (e.g. https://hatchery.example.com)
  BROODFORGE_HATCHERY_PUBKEY    Path to hatchery RSA public key PEM
  BROODFORGE_PVE_ISO            Base Proxmox VE ISO path
  BROODFORGE_PVE_NET_IFACE      Network interface for PVE install
  BROODFORGE_PVE_TIMEZONE       Timezone for PVE install (default: UTC)
  BROODFORGE_PYTHON             Python interpreter (default: python3)
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -c|--codename)    CODENAME="$2";          shift 2 ;;
        -o|--output-dir)  OUTPUT_DIR="$2";        shift 2 ;;
        --pve-iso)        PROXMOX_ISO="$2";       shift 2 ;;
        --hatchery-url)   HATCHERY_URL="$2";      shift 2 ;;
        --iface)          PVE_NET_IFACE="$2";     shift 2 ;;
        --timezone)       PVE_TIMEZONE="$2";      shift 2 ;;
        -h|--help)        usage; exit 0            ;;
        *)
            echo "[forge-build-node-iso] ERROR: Unknown argument: $1" >&2
            usage
            exit 1
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------

if [[ -z "${CODENAME}" ]]; then
    echo "[forge-build-node-iso] ERROR: --codename is required." >&2
    usage
    exit 1
fi

# Validate codename: lowercase alphanumeric and hyphens only, no leading/trailing hyphens.
# This prevents shell injection when CODENAME is interpolated into Python -c commands below.
if ! [[ "${CODENAME}" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ]]; then
    echo "[forge-build-node-iso] ERROR: Invalid codename '${CODENAME}'." >&2
    echo "  Codenames must be lowercase alphanumeric with hyphens (e.g. swift-falcon)." >&2
    exit 1
fi

if ! command -v "${PYTHON}" &>/dev/null; then
    echo "[forge-build-node-iso] ERROR: Python not found: ${PYTHON}" >&2
    exit 1
fi

if [[ ! -f "${NODE_PLANNER}" ]]; then
    echo "[forge-build-node-iso] ERROR: node_planner.py not found at: ${NODE_PLANNER}" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# KeePass gate
# ---------------------------------------------------------------------------

echo ""
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║        broodforge — Node ISO Builder (Phase 1.Q)                ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""
echo "  Codename : ${CODENAME}"
echo ""

forge_keepass_gate "forge-build-node-iso: build ISO for node ${CODENAME}"

# ---------------------------------------------------------------------------
# Fetch credentials from KeePass if not in environment
# ---------------------------------------------------------------------------

if [[ -z "${HATCHERY_URL}" ]]; then
    HATCHERY_URL="$(kdbx_get "Infrastructure/Hatchery" "url" 2>/dev/null || true)"
fi

if [[ -z "${HATCHERY_URL}" ]]; then
    echo "[forge-build-node-iso] ERROR: Hatchery URL not set." >&2
    echo "  Set BROODFORGE_HATCHERY_URL or add 'url' to KeePass 'Infrastructure/Hatchery'." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Read node from provisioning state
# ---------------------------------------------------------------------------

echo "[forge-build-node-iso] Reading node state for '${CODENAME}'..."

NODE_JSON=$(
    "${PYTHON}" "${NODE_PLANNER}" \
        --list \
        --json \
        --state-dir "${STATE_DIR}" \
    | "${PYTHON}" -c "
import json, sys
nodes = json.load(sys.stdin)
for n in nodes:
    if n.get('codename') == '${CODENAME}':
        print(json.dumps(n))
        sys.exit(0)
sys.exit(1)
" 2>&1
) || {
    echo "[forge-build-node-iso] ERROR: Codename '${CODENAME}' not found in provisioning state." >&2
    echo "  Run forge-plan-nodes.sh first to plan and commit the node." >&2
    exit 1
}

# Extract fields using Python
read -r HEADSCALE_KEY JOIN_PIN NODE_ROLE < <(
    echo "${NODE_JSON}" | "${PYTHON}" -c "
import json, sys
n = json.load(sys.stdin)
print(n.get('headscale_key_id','') + ' ' + n.get('join_pin','') + ' ' + n.get('role','worker'))
" 2>&1
)

# headscale_key_id is not the actual key string — we need the actual key
# The key string is generated by plan_batch but NOT stored in state (only key_id is).
# For ISO build we re-create a fresh key. This is safe — single-use keys.
echo "[forge-build-node-iso] Generating fresh Headscale pre-auth key for '${CODENAME}'..."

if [[ -n "${BROODFORGE_HEADSCALE_URL:-}" ]]; then
    HEADSCALE_KEY=$(
        headscale preauthkeys create \
            --one-time \
            --expiration 0 \
            --tags "tag:broodling" \
            --output json 2>/dev/null \
        | "${PYTHON}" -c "import json,sys; d=json.load(sys.stdin); print(d.get('key') or d.get('authKey',''))"
    ) || {
        echo "[forge-build-node-iso] WARNING: Could not generate fresh Headscale key. Using stub." >&2
        HEADSCALE_KEY="STUB_HEADSCALE_KEY_${CODENAME}"
    }
else
    echo "[forge-build-node-iso] WARNING: BROODFORGE_HEADSCALE_URL not set. Using stub key." >&2
    HEADSCALE_KEY="STUB_HEADSCALE_KEY_${CODENAME}"
fi

if [[ -z "${JOIN_PIN}" ]]; then
    echo "[forge-build-node-iso] ERROR: join_pin is missing from provisioning state for '${CODENAME}'." >&2
    echo "  Re-plan the node: forge-plan-nodes.sh --count 1 --role ${NODE_ROLE}" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Read hatchery public key
# ---------------------------------------------------------------------------

HATCHERY_PUBKEY_PEM=""
if [[ -f "${HATCHERY_PUBKEY_PATH}" ]]; then
    HATCHERY_PUBKEY_PEM="$(cat "${HATCHERY_PUBKEY_PATH}")"
else
    echo "[forge-build-node-iso] WARNING: Hatchery public key not found at ${HATCHERY_PUBKEY_PATH}." >&2
    echo "  The bootstrap script will not be able to encrypt its registration payload." >&2
fi

# ---------------------------------------------------------------------------
# Create output directory
# ---------------------------------------------------------------------------

NODE_OUT="${OUTPUT_DIR}/${CODENAME}"
mkdir -p "${NODE_OUT}"

# ---------------------------------------------------------------------------
# Generate answer.toml (Proxmox auto-install answer file)
# ---------------------------------------------------------------------------

ANSWER_TOML="${NODE_OUT}/answer.toml"

cat > "${ANSWER_TOML}" <<TOML
# Proxmox VE auto-install answer file — generated by forge-build-node-iso.sh
# Node: ${CODENAME}  Role: ${NODE_ROLE}
# DO NOT COMMIT this file to version control — it contains the Headscale pre-auth key.

[global]
keyboard = "en-us"
country = "us"
fqdn = "${CODENAME}.broodling.internal"
mailto = "root@localhost"
timezone = "${PVE_TIMEZONE}"
root_password = "$(openssl rand -base64 24 | tr -d '/')"

[network]
source = "from-dhcp"
$([ -n "${PVE_NET_IFACE}" ] && echo "default_route_interface = \"${PVE_NET_IFACE}\"" || true)

[disk-setup]
filesystem = "ext4"
disk_list = ["sda"]
swapsize = 4
hdsize = 0

[first-boot]
source = "from-iso"
ordering = ["broodling-bootstrap"]

[first-boot.scripts.broodling-bootstrap]
path = "/broodling-bootstrap.sh"
TOML

echo "[forge-build-node-iso] answer.toml written: ${ANSWER_TOML}"

# ---------------------------------------------------------------------------
# Generate broodling-bootstrap.sh (post-install first-boot script)
# ---------------------------------------------------------------------------

BOOTSTRAP_SCRIPT="${NODE_OUT}/broodling-bootstrap.sh"

cat > "${BOOTSTRAP_SCRIPT}" <<'BOOTSTRAP_EOF'
#!/usr/bin/env bash
# broodling-bootstrap.sh — Phase 1.Q first-boot script
# Embedded in the Proxmox auto-install ISO.
# Runs once on first boot after Proxmox VE is installed.
#
# Steps:
#   1. Generate RSA key pair
#   2. Encrypt registration payload with hatchery public key
#   3. POST to hatchery /api/node-register
#   4. Install Tailscale/Headscale client using embedded pre-auth key
#   5. Signal readiness; wait for operator approval

set -euo pipefail

BOOTSTRAP_EOF

# Embed secrets and config as shell variables (not in heredoc, to allow variable expansion)
cat >> "${BOOTSTRAP_SCRIPT}" <<SECRETS_EOF
# ---- EMBEDDED AT BUILD TIME (do not edit) ----
BROODLING_CODENAME="${CODENAME}"
BROODLING_JOIN_PIN="${JOIN_PIN}"
HEADSCALE_AUTHKEY="${HEADSCALE_KEY}"
HATCHERY_URL="${HATCHERY_URL}"
HATCHERY_PUBKEY_PEM="$(echo "${HATCHERY_PUBKEY_PEM}" | base64 -w0)"
# ---- END EMBEDDED ----

SECRETS_EOF

cat >> "${BOOTSTRAP_SCRIPT}" <<'MAIN_EOF'
LOG="/var/log/broodling-bootstrap.log"
exec >> "${LOG}" 2>&1
echo "[broodling-bootstrap] $(date -Iseconds) Starting bootstrap for node: ${BROODLING_CODENAME}"

KEY_DIR="/etc/broodling"
PRIV_KEY="${KEY_DIR}/broodling-private.pem"
PUB_KEY="${KEY_DIR}/broodling-public.pem"
HATCHERY_PUBKEY_FILE="${KEY_DIR}/hatchery-public.pem"
PAYLOAD_ENC="${KEY_DIR}/registration-payload.enc"
PAYLOAD_JSON="${KEY_DIR}/registration-payload.json"

mkdir -p "${KEY_DIR}"
chmod 700 "${KEY_DIR}"

# ---------------------------------------------------------------------------
# 1. Generate RSA key pair (if not already present — idempotent)
# ---------------------------------------------------------------------------

if [[ ! -f "${PRIV_KEY}" ]]; then
    echo "[broodling-bootstrap] Generating RSA-4096 key pair..."
    openssl genrsa -out "${PRIV_KEY}" 4096
    openssl rsa -in "${PRIV_KEY}" -pubout -out "${PUB_KEY}"
    chmod 600 "${PRIV_KEY}"
    echo "[broodling-bootstrap] Key pair generated."
else
    echo "[broodling-bootstrap] Key pair already exists, reusing."
fi

PUB_KEY_PEM="$(cat "${PUB_KEY}")"
PUB_KEY_B64="$(base64 -w0 "${PUB_KEY}")"

# ---------------------------------------------------------------------------
# 2. Build registration payload JSON
# ---------------------------------------------------------------------------

cat > "${PAYLOAD_JSON}" <<PAYLOAD_EOF
{
  "codename": "${BROODLING_CODENAME}",
  "join_pin": "${BROODLING_JOIN_PIN}",
  "public_key_pem": "${PUB_KEY_B64}"
}
PAYLOAD_EOF

# ---------------------------------------------------------------------------
# 3. Encrypt payload with hatchery public key (if available)
# ---------------------------------------------------------------------------

if [[ -n "${HATCHERY_PUBKEY_PEM}" ]]; then
    echo "${HATCHERY_PUBKEY_PEM}" | base64 -d > "${HATCHERY_PUBKEY_FILE}"
    # Generate random AES-256 key for hybrid encryption
    AES_KEY="$(openssl rand -hex 32)"
    AES_IV="$(openssl rand -hex 16)"
    # Encrypt payload with AES-256-CBC
    openssl enc -aes-256-cbc -K "${AES_KEY}" -iv "${AES_IV}" \
        -in "${PAYLOAD_JSON}" -out "${KEY_DIR}/payload.enc.bin"
    # Encrypt AES key with RSA public key (OAEP)
    echo "${AES_KEY}:${AES_IV}" | \
        openssl pkeyutl -encrypt -pubin -inkey "${HATCHERY_PUBKEY_FILE}" \
            -pkeyopt rsa_padding_mode:oaep \
            -out "${KEY_DIR}/aes-key.enc"
    # Bundle: base64(enc_aes_key) + "." + base64(enc_payload)
    ENC_AES_KEY="$(base64 -w0 "${KEY_DIR}/aes-key.enc")"
    ENC_PAYLOAD="$(base64 -w0 "${KEY_DIR}/payload.enc.bin")"
    ENCRYPTED_BODY="{\"encrypted\":true,\"key\":\"${ENC_AES_KEY}\",\"payload\":\"${ENC_PAYLOAD}\"}"
    echo "[broodling-bootstrap] Payload encrypted with hatchery public key."
else
    # No encryption available — send unencrypted (hatchery will warn)
    ENCRYPTED_BODY="$(cat "${PAYLOAD_JSON}")"
    echo "[broodling-bootstrap] WARNING: Hatchery public key not embedded. Sending unencrypted." >&2
fi

# ---------------------------------------------------------------------------
# 4. POST registration to hatchery (retry up to 30 times, 60s apart)
# ---------------------------------------------------------------------------

REGISTER_URL="${HATCHERY_URL}/api/node-register"
MAX_ATTEMPTS=30
ATTEMPT=0

echo "[broodling-bootstrap] Registering with hatchery at ${REGISTER_URL}..."

until [[ ${ATTEMPT} -ge ${MAX_ATTEMPTS} ]]; do
    ATTEMPT=$(( ATTEMPT + 1 ))
    HTTP_STATUS=$(
        curl -s -o /dev/null -w "%{http_code}" \
            -X POST "${REGISTER_URL}" \
            -H "Content-Type: application/json" \
            --max-time 30 \
            --data "${ENCRYPTED_BODY}" \
        2>/dev/null || echo "000"
    )
    if [[ "${HTTP_STATUS}" == "200" || "${HTTP_STATUS}" == "204" ]]; then
        echo "[broodling-bootstrap] Registration accepted (HTTP ${HTTP_STATUS})."
        break
    fi
    echo "[broodling-bootstrap] Registration attempt ${ATTEMPT}/${MAX_ATTEMPTS} failed (HTTP ${HTTP_STATUS}). Retrying in 60s..."
    sleep 60
done

if [[ ${ATTEMPT} -ge ${MAX_ATTEMPTS} ]]; then
    echo "[broodling-bootstrap] ERROR: Failed to register with hatchery after ${MAX_ATTEMPTS} attempts." >&2
    echo "[broodling-bootstrap] Manual intervention required. Check HATCHERY_URL and network." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# 5. Install Tailscale/Headscale client and join network
# ---------------------------------------------------------------------------

echo "[broodling-bootstrap] Installing Tailscale..."

# Use official Tailscale install script (adjust for air-gapped envs as needed)
if ! command -v tailscale &>/dev/null; then
    curl -fsSL https://tailscale.com/install.sh | sh
fi

systemctl enable --now tailscaled

echo "[broodling-bootstrap] Joining Headscale network..."
tailscale up \
    --login-server "$(echo "${HATCHERY_URL}" | sed 's|/api.*||')" \
    --authkey "${HEADSCALE_AUTHKEY}" \
    --hostname "${BROODLING_CODENAME}" \
    --tags "tag:broodling" \
    --accept-routes

echo "[broodling-bootstrap] Tailscale joined. Waiting for operator approval..."

# ---------------------------------------------------------------------------
# 6. Cleanup sensitive files
# ---------------------------------------------------------------------------

# Remove key material that is no longer needed
rm -f "${KEY_DIR}/aes-key.enc" "${KEY_DIR}/payload.enc.bin" "${PAYLOAD_JSON}"
# Note: keep PRIV_KEY — the node will need it for mutual TLS / future ops

echo "[broodling-bootstrap] Bootstrap complete for ${BROODLING_CODENAME}."
echo "[broodling-bootstrap] Node is in pending-approval state. Waiting for operator."
MAIN_EOF

chmod +x "${BOOTSTRAP_SCRIPT}"
echo "[forge-build-node-iso] Bootstrap script written: ${BOOTSTRAP_SCRIPT}"

# ---------------------------------------------------------------------------
# Update provisioning state: iso-built
# ---------------------------------------------------------------------------

"${PYTHON}" "${NODE_PLANNER}" \
    --update "${CODENAME}" \
    --set "state=iso-built" "iso_path=${NODE_OUT}" \
    --state-dir "${STATE_DIR}"

echo "[forge-build-node-iso] Node '${CODENAME}' state updated to iso-built."

# ---------------------------------------------------------------------------
# Generate operator README
# ---------------------------------------------------------------------------

README="${NODE_OUT}/README-operator.txt"

cat > "${README}" <<README_EOF
Node ISO Build Artifacts — ${CODENAME}
Generated: $(date -Iseconds)
Role: ${NODE_ROLE}
Join PIN: ${JOIN_PIN}
================================================================================

OPERATOR INSTRUCTIONS
=====================

These artifacts must be assembled into a bootable ISO using the
proxmox-auto-install-assistant tool. This tool MUST RUN ON THE PROXMOX HOST
(not the hatchery VM) because it requires Proxmox-specific tooling.

STEP 1: Copy artifacts to your Proxmox host
--------------------------------------------
  scp -r ${NODE_OUT} root@<proxmox-host>:/tmp/broodling-iso-staging/

STEP 2: Run proxmox-auto-install-assistant on the Proxmox host
--------------------------------------------------------------
  ssh root@<proxmox-host>
  cd /tmp/broodling-iso-staging/${CODENAME}

  proxmox-auto-install-assistant prepare-iso \\
      ${PROXMOX_ISO:-/path/to/proxmox-ve_*.iso} \\
      --answer-file ./answer.toml \\
      --on-first-boot ./broodling-bootstrap.sh \\
      --output ./${CODENAME}-autoinstall.iso

  # Verify:
  proxmox-auto-install-assistant validate-answer ./answer.toml

STEP 3: Transfer ISO to USB
----------------------------
  dd if=./${CODENAME}-autoinstall.iso of=/dev/sdX bs=4M status=progress

STEP 4: Boot the bare-metal server
-------------------------------------
  - Insert USB, power on server
  - Proxmox installs automatically (~10 min depending on disk speed)
  - On first boot the node will:
    a. Generate its RSA key pair
    b. POST a registration request to: ${HATCHERY_URL}/api/node-register
    c. Join Headscale network (pending approval)

STEP 5: Approve in the sidecar dashboard
-----------------------------------------
  Open: http://localhost:9322  (or your hatchery URL)
  → Nodes panel → Pending Approval queue
  → Verify codename: ${CODENAME}
  → Verify PIN:      ${JOIN_PIN}
  → Click Approve

SECURITY NOTES
==============
- The join PIN (${JOIN_PIN}) ties this ISO to this specific node slot.
  If the PIN doesn't match, the hatchery rejects the registration.
- Do NOT share this file or the ISO publicly.
- Store this README in your secure vault (KeePass) after ISO build.
- Shred this directory after burning: rm -rf ${NODE_OUT}

================================================================================
README_EOF

echo "[forge-build-node-iso] Operator README written: ${README}"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

echo ""
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║               ISO Artifacts Generated Successfully               ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""
echo "  Codename  : ${CODENAME}"
echo "  Join PIN  : ${JOIN_PIN}"
echo "  Artifacts : ${NODE_OUT}/"
echo ""
echo "  Read ${README}"
echo "  for full operator instructions."
echo ""
echo "  IMPORTANT: These artifacts contain the Headscale pre-auth key."
echo "  Treat them as secrets. Shred the staging directory after ISO burn."
echo ""
