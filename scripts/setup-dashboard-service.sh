#!/usr/bin/env bash
# setup-dashboard-service.sh — Install broodforge sidecar dashboard as a
# non-root systemd service (F-4 fix).
#
# Creates a dedicated `broodforge` system user, assigns ownership of the
# state directory, writes the service unit with User=broodforge, and enables
# + starts the service.
#
# Usage:
#   sudo bash scripts/setup-dashboard-service.sh [options]
#
# Options:
#   --state-dir DIR      State directory (default: /var/lib/broodforge)
#   --port PORT          Dashboard port (default: 7070)
#   --repo-root DIR      Broodforge repo root (default: parent of this script)
#   --uninstall          Stop + disable service and remove unit file only
#                        (does not delete the broodforge user or state dir)
#
# The service unit is written to /etc/systemd/system/broodforge-dashboard.service.
# Re-running this script is idempotent.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

STATE_DIR="/var/lib/broodforge"
PORT=7070
UNINSTALL=0
SERVICE_NAME="broodforge-dashboard"
UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
BROODFORGE_USER="broodforge"

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

while [[ $# -gt 0 ]]; do
  case "$1" in
    --state-dir) STATE_DIR="$2"; shift 2 ;;
    --port)      PORT="$2"; shift 2 ;;
    --repo-root) REPO_ROOT="$2"; shift 2 ;;
    --uninstall) UNINSTALL=1; shift ;;
    --help|-h)
      sed -n '3,25p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "[dashboard-svc] ERROR: unknown argument: $1" >&2; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

info()  { echo "[dashboard-svc] $*"; }
die()   { echo "[dashboard-svc] ERROR: $*" >&2; exit 1; }

require_root() {
  if [[ "$(id -u)" -ne 0 ]]; then
    die "This script must be run as root (use sudo)."
  fi
}

# ---------------------------------------------------------------------------
# Uninstall path
# ---------------------------------------------------------------------------

if [[ "$UNINSTALL" -eq 1 ]]; then
  require_root
  info "Uninstalling ${SERVICE_NAME} ..."
  systemctl stop  "${SERVICE_NAME}.service" 2>/dev/null || true
  systemctl disable "${SERVICE_NAME}.service" 2>/dev/null || true
  rm -f "$UNIT_FILE"
  systemctl daemon-reload
  info "Service removed. State directory and broodforge user are preserved."
  info "To remove the user: userdel broodforge"
  info "To remove state:    rm -rf ${STATE_DIR}"
  exit 0
fi

# ---------------------------------------------------------------------------
# Install path
# ---------------------------------------------------------------------------

require_root

DASHBOARD_SCRIPT="${REPO_ROOT}/proxmox-bootstrap/broodforge_dashboard.py"
if [[ ! -f "$DASHBOARD_SCRIPT" ]]; then
  die "broodforge_dashboard.py not found at ${DASHBOARD_SCRIPT}. Check --repo-root."
fi

# --- 1. Create system user (no login shell, home at state dir) -------------

if id "$BROODFORGE_USER" &>/dev/null; then
  info "System user '${BROODFORGE_USER}' already exists — skipping creation."
else
  info "Creating system user '${BROODFORGE_USER}' ..."
  useradd \
    --system \
    --no-create-home \
    --home-dir "$STATE_DIR" \
    --shell /usr/sbin/nologin \
    --comment "broodforge service account" \
    "$BROODFORGE_USER"
  info "User '${BROODFORGE_USER}' created."
fi

# --- 2. Create and chown the state directory -------------------------------

if [[ ! -d "$STATE_DIR" ]]; then
  info "Creating state directory ${STATE_DIR} ..."
  mkdir -p "$STATE_DIR"
fi

info "Setting ownership: ${STATE_DIR} → ${BROODFORGE_USER}:${BROODFORGE_USER}"
chown -R "${BROODFORGE_USER}:${BROODFORGE_USER}" "$STATE_DIR"
chmod 750 "$STATE_DIR"

# Subdirectories that may exist already
for subdir in backups reports failures; do
  if [[ -d "${STATE_DIR}/${subdir}" ]]; then
    chown -R "${BROODFORGE_USER}:${BROODFORGE_USER}" "${STATE_DIR}/${subdir}"
    chmod 750 "${STATE_DIR}/${subdir}"
  fi
done

# --- 3. Write systemd unit --------------------------------------------------

info "Writing ${UNIT_FILE} ..."
cat > "$UNIT_FILE" << EOF
[Unit]
Description=broodforge sidecar dashboard
Documentation=https://github.com/broodforge/broodforge
After=network.target
Wants=network.target

[Service]
Type=simple
User=${BROODFORGE_USER}
Group=${BROODFORGE_USER}
WorkingDirectory=${REPO_ROOT}/proxmox-bootstrap
ExecStart=/usr/bin/python3 ${DASHBOARD_SCRIPT} --port ${PORT} --state ${STATE_DIR}
Restart=on-failure
RestartSec=5s

# Hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=${STATE_DIR}
ReadOnlyPaths=${REPO_ROOT}
CapabilityBoundingSet=
AmbientCapabilities=

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=broodforge-dashboard

[Install]
WantedBy=multi-user.target
EOF

chmod 644 "$UNIT_FILE"

# --- 4. Enable and (re)start ------------------------------------------------

info "Reloading systemd daemon ..."
systemctl daemon-reload

if systemctl is-active --quiet "${SERVICE_NAME}.service"; then
  info "Service already running — restarting to pick up changes ..."
  systemctl restart "${SERVICE_NAME}.service"
else
  info "Enabling and starting ${SERVICE_NAME}.service ..."
  systemctl enable "${SERVICE_NAME}.service"
  systemctl start  "${SERVICE_NAME}.service"
fi

# --- 5. Verify -------------------------------------------------------------

sleep 1
if systemctl is-active --quiet "${SERVICE_NAME}.service"; then
  info "Dashboard service is running as User=${BROODFORGE_USER} on port ${PORT}."
  info "Unit: ${UNIT_FILE}"
  info "State dir: ${STATE_DIR} (owned by ${BROODFORGE_USER})"
  info "To view logs: journalctl -u ${SERVICE_NAME} -f"
else
  echo ""
  echo "[dashboard-svc] WARNING: service did not start cleanly. Check:"
  echo "  journalctl -u ${SERVICE_NAME} --no-pager -n 30"
  exit 1
fi
