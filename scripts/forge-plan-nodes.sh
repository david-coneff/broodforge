#!/usr/bin/env bash
# forge-plan-nodes.sh — Phase 1.Q: Interactive batch node planner
#
# KeePass-gated interactive script for planning new broodling bare-metal nodes.
# Generates codenames, Headscale pre-auth keys, and join PINs; persists to
# provisioning-state.json; and prints a summary the operator keeps for ISO builds.
#
# Usage:
#   ./scripts/forge-plan-nodes.sh [--count N] [--role ROLE] [--yes]
#
# Exit codes:
#   0 — success
#   1 — fatal error
#   2 — NOT_IMPLEMENTED
#
# Dependencies:
#   - lib/forge-lib.sh (forge_keepass_gate, kdbx_get)
#   - proxmox-bootstrap/node_planner.py
#   - python3 (3.11+)
#   - BROODFORGE_HEADSCALE_URL in environment or .env
#   - KeePass vault with Headscale credentials entry

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# shellcheck source=lib/forge-lib.sh
source "${REPO_ROOT}/lib/forge-lib.sh"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

COUNT=1
ROLE="worker"
AUTO_CONFIRM=0
STATE_DIR="${BROODFORGE_STATE_DIR:-/var/lib/broodforge}"
PYTHON="${BROODFORGE_PYTHON:-python3}"
NODE_PLANNER="${REPO_ROOT}/proxmox-bootstrap/node_planner.py"

# ---------------------------------------------------------------------------
# Arg parsing
# ---------------------------------------------------------------------------

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Plan bare-metal Proxmox nodes for zero-touch provisioning (Phase 1.Q).

OPTIONS:
  -n, --count N       Number of nodes to plan (default: 1)
  -r, --role ROLE     Node role: worker|control-plane|storage|general (default: worker)
  -y, --yes           Skip confirmation prompt
  -h, --help          Show this help

ENVIRONMENT:
  BROODFORGE_HEADSCALE_URL    Headscale server URL (required for real keys)
  BROODFORGE_STATE_DIR        Override state directory (default: /var/lib/broodforge)
  BROODFORGE_PYTHON           Python interpreter (default: python3)

EXAMPLES:
  forge-plan-nodes.sh --count 3 --role worker
  forge-plan-nodes.sh --count 1 --role control-plane --yes
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -n|--count)    COUNT="$2";       shift 2 ;;
        -r|--role)     ROLE="$2";        shift 2 ;;
        -y|--yes)      AUTO_CONFIRM=1;   shift   ;;
        -h|--help)     usage; exit 0            ;;
        *)
            echo "[forge-plan-nodes] ERROR: Unknown argument: $1" >&2
            usage
            exit 1
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Validate inputs
# ---------------------------------------------------------------------------

if ! [[ "${COUNT}" =~ ^[1-9][0-9]*$ ]]; then
    echo "[forge-plan-nodes] ERROR: --count must be a positive integer, got: ${COUNT}" >&2
    exit 1
fi

valid_roles="worker control-plane storage general"
if ! echo "${valid_roles}" | grep -qw "${ROLE}"; then
    echo "[forge-plan-nodes] ERROR: --role must be one of: ${valid_roles}" >&2
    exit 1
fi

if [[ ! -f "${NODE_PLANNER}" ]]; then
    echo "[forge-plan-nodes] ERROR: node_planner.py not found at: ${NODE_PLANNER}" >&2
    exit 1
fi

if ! command -v "${PYTHON}" &>/dev/null; then
    echo "[forge-plan-nodes] ERROR: Python not found at: ${PYTHON}" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Operator gate
# ---------------------------------------------------------------------------

echo ""
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║      broodforge — Node Provisioning Planner (Phase 1.Q)         ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""
echo "  Count : ${COUNT}"
echo "  Role  : ${ROLE}"
echo ""

forge_keepass_gate "forge-plan-nodes: plan ${COUNT} node(s) with role=${ROLE}"

# ---------------------------------------------------------------------------
# Fetch Headscale URL from KeePass (if not already in env)
# ---------------------------------------------------------------------------

if [[ -z "${BROODFORGE_HEADSCALE_URL:-}" ]]; then
    echo "[forge-plan-nodes] Fetching Headscale URL from KeePass vault..."
    BROODFORGE_HEADSCALE_URL="$(kdbx_get "Infrastructure/Headscale" "url" 2>/dev/null || true)"
    if [[ -z "${BROODFORGE_HEADSCALE_URL}" ]]; then
        echo "[forge-plan-nodes] WARNING: BROODFORGE_HEADSCALE_URL not set and not found in KeePass." >&2
        echo "[forge-plan-nodes] WARNING: Stub Headscale keys will be generated. Set the URL before ISO build." >&2
    else
        export BROODFORGE_HEADSCALE_URL
    fi
fi

# ---------------------------------------------------------------------------
# Plan phase: dry-run with --json to see proposed batch
# ---------------------------------------------------------------------------

echo ""
echo "[forge-plan-nodes] Generating plan for ${COUNT} ${ROLE} node(s)..."
echo ""

PLAN_JSON=$(
    "${PYTHON}" "${NODE_PLANNER}" \
        --plan \
        --count "${COUNT}" \
        --role  "${ROLE}"  \
        --json  \
        --state-dir "${STATE_DIR}"
)

if [[ -z "${PLAN_JSON}" ]]; then
    echo "[forge-plan-nodes] ERROR: node_planner.py returned empty plan." >&2
    exit 1
fi

# Display plan to operator
echo "Proposed batch:"
echo ""
echo "${PLAN_JSON}" | "${PYTHON}" -c "
import json, sys
plans = json.load(sys.stdin)
hdr = f\"{'#':<4} {'Codename':<22} {'Role':<14} {'JOIN PIN':<16} {'Headscale Key (preview)'}\"
print(hdr)
print('-' * 90)
for i, p in enumerate(plans, 1):
    key = p.get('headscale_key','')
    key_preview = key[:16]+'...' if len(key) > 16 else key
    print(f\"{i:<4} {p['codename']:<22} {p['role']:<14} {p['join_pin']:<16} {key_preview}\")
print()
print(f'Total: {len(plans)} node(s)')
print()
print('NOTE: Store join PINs securely. They are embedded in the ISO and identify')
print('      each specific node when it joins (###-###-###-### format).')
print()
"

# ---------------------------------------------------------------------------
# Confirmation
# ---------------------------------------------------------------------------

if [[ "${AUTO_CONFIRM}" -eq 0 ]]; then
    read -r -p "Commit this plan to provisioning state? [y/N] " confirm
    case "${confirm}" in
        [yY]|[yY][eE][sS]) : ;;
        *)
            echo "[forge-plan-nodes] Aborted — nothing was committed."
            exit 0
            ;;
    esac
fi

# ---------------------------------------------------------------------------
# Write temp plan file and commit
# ---------------------------------------------------------------------------

PLAN_TMP="$(mktemp /tmp/broodforge-plan-XXXXXX.json)"
trap 'rm -f "${PLAN_TMP}"' EXIT

echo "${PLAN_JSON}" > "${PLAN_TMP}"

echo ""
echo "[forge-plan-nodes] Committing plan to provisioning state..."

"${PYTHON}" "${NODE_PLANNER}" \
    --commit \
    --plan-file "${PLAN_TMP}" \
    --state-dir "${STATE_DIR}"

# ---------------------------------------------------------------------------
# Summary output
# ---------------------------------------------------------------------------

echo ""
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║                    Plan committed successfully                    ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""
echo "Next steps:"
echo ""
echo "  1. For each node, build an ISO:"
echo "     ./scripts/forge-build-node-iso.sh --codename <codename>"
echo ""
echo "  2. Burn the ISO to a USB drive:"
echo "     dd if=<iso_path> of=/dev/sdX bs=4M status=progress"
echo ""
echo "  3. Boot the bare-metal server from the USB. Proxmox installs"
echo "     automatically. When done the node calls home to the hatchery."
echo ""
echo "  4. Approve the join from the sidecar dashboard:"
echo "     http://localhost:9322  → Nodes panel → pending-approval queue"
echo ""
echo "  Verify codenames and PINs match what is shown in the dashboard"
echo "  before approving. Each node sends its PIN with the join request."
echo ""

"${PYTHON}" "${NODE_PLANNER}" \
    --list \
    --state planned \
    --state-dir "${STATE_DIR}" \
    2>/dev/null || true

echo ""
