#!/usr/bin/env python3
"""
forge_scripts.py — Forge phase script generator (Phase 1.F.2).

Generates the bash scripts that constitute forge.sh (orchestrator) and the
8 individual phase scripts embedded in the forge package. The scripts use
the same checkpoint/resumable library pattern as spawn scripts.

Forge phases:
  phase-00: discover    — hardware discovery + forge_validator check
  phase-01: plan        — forge-planner.py (identity, network, mode)
  phase-02: validate    — hardware validation (RED findings block)
  phase-03: host        — host config (hostname, ZFS, bridges, nag, dnsmasq, Headscale, TLS)
  phase-04: vms         — VM provisioning (tofu apply — min viable stack)
  phase-05: k3s         — k3s cluster init (ansible k3s-server role)
  phase-06: gitops      — Flux CD bootstrap → Forgejo
  phase-07: intelligence — assessment + doc engine setup
  phase-08: verify      — cluster health, bootstrap-state.json commit

Provides:
  FORGE_CHECKPOINT_SH     — checkpoint library (reused from spawn)
  FORGE_KEEPASS_GATE_SH   — KeePass gate adapted for forge flow
  generate_forge_sh()     — forge.sh orchestrator
  generate_phase_00_sh()  — discover
  generate_phase_01_sh()  — plan
  generate_phase_02_sh()  — validate
  generate_phase_03_sh()  — host config
  generate_phase_04_sh()  — VMs
  generate_phase_05_sh()  — k3s
  generate_phase_06_sh()  — Flux/GitOps
  generate_phase_07_sh()  — intelligence layer
  generate_phase_08_sh()  — verify + commit
  write_all_forge_scripts() — write everything to an output directory

Stdlib only.
"""

import os
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Shared library content (embedded in the package)
# ---------------------------------------------------------------------------

FORGE_CHECKPOINT_SH = """\
#!/usr/bin/env bash
# checkpoint.sh — Resumable checkpoint library for forge scripts
# Source this file before using checkpoint_start/checkpoint_done.
# Re-running forge.sh skips already-completed steps automatically.

CHECKPOINT_DIR="${SCRIPT_DIR}/.checkpoints"
mkdir -p "$CHECKPOINT_DIR"

checkpoint_start()  { echo "[$(date +%H:%M:%S)] START: $1"; }

checkpoint_done()   {
  touch "$CHECKPOINT_DIR/$1.done"
  echo "[$(date +%H:%M:%S)] DONE:  $1"
}

checkpoint_skip()   { echo "[$(date +%H:%M:%S)] SKIP:  $1 (already completed)"; }

checkpoint_failed() {
  echo "[$(date +%H:%M:%S)] FAIL:  $1" >&2
  echo "Check $FORGE_LOG for details." >&2
  exit 1
}

is_done() { [ -f "$CHECKPOINT_DIR/$1.done" ]; }

checkpoint_reset() {
  echo "[checkpoint] Resetting all checkpoints — fresh run"
  rm -rf "$CHECKPOINT_DIR"
  mkdir -p "$CHECKPOINT_DIR"
}
"""

FORGE_KEEPASS_GATE_SH = """\
#!/usr/bin/env bash
# forge-keepass-gate.sh — KeePass master password gate for forge.sh
# Source this and call forge_keepass_gate() in phase-03 before any secrets.

FORGE_KDBX_PATH=""
FORGE_KDBX_UNLOCKED=0

forge_keepass_find_db() {
  local embedded
  embedded="$(ls "$SCRIPT_DIR"/kdbx/*.kdbx 2>/dev/null | head -1)"
  if [ -n "$embedded" ]; then
    FORGE_KDBX_PATH="$embedded"
    echo "[kdbx] Using embedded database: $FORGE_KDBX_PATH"
    return 0
  fi
  read -rp "[kdbx] Path to KeePass database (.kdbx): " FORGE_KDBX_PATH
  [ -f "$FORGE_KDBX_PATH" ] || { echo "[kdbx] Not found: $FORGE_KDBX_PATH" >&2; return 1; }
}

forge_keepass_gate() {
  [ "$FORGE_KDBX_UNLOCKED" -eq 1 ] && return 0
  # Write prompts to /dev/tty so they reach the operator regardless of log redirects
  echo "" >/dev/tty
  echo "=================================================================" >/dev/tty
  echo " KeePass Unlock Gate — forge.sh" >/dev/tty
  echo " The master password is required once. All subsequent secret" >/dev/tty
  echo " lookups during forging are automatic." >/dev/tty
  echo "=================================================================" >/dev/tty
  forge_keepass_find_db || { echo "[kdbx] Cannot locate database." >&2; exit 1; }
  # Read password from /dev/tty to guarantee it is not captured in forge.log
  read -rsp "[kdbx] Master password: " KEEPASS_MASTER_PASSWORD </dev/tty >/dev/tty
  echo "" >/dev/tty
  # Export only the database path; keep the password as a shell-local variable
  # so child processes do not inherit it via their environment
  export FORGE_KDBX_PATH
  FORGE_KDBX_UNLOCKED=1
  echo "[kdbx] Unlocked. Secrets broker active." >/dev/tty
  echo "" >/dev/tty
}

kdbx_get() {
  local path="$1"
  if command -v keepassxc-cli &>/dev/null; then
    # Pipe password via stdin — never passed as a command-line argument
    printf '%s\\n' "$KEEPASS_MASTER_PASSWORD" | \\
      keepassxc-cli show -q -a Password "$FORGE_KDBX_PATH" "$path" 2>/dev/null
  else
    echo "[kdbx] keepassxc-cli not found — retrieve '$path' manually" >&2
    echo "MANUAL_ENTRY_REQUIRED"
  fi
}
"""


# ---------------------------------------------------------------------------
# Shared header for all phase scripts
# ---------------------------------------------------------------------------

def _phase_header(phase_name: str, description: str) -> str:
    return f"""\
#!/usr/bin/env bash
# {phase_name} — {description}
# Part of broodforge forge package (Phase 1.F).
# Idempotent: re-run to resume after failure.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
FORGE_LOG="${{SCRIPT_DIR}}/forge.log"
source "$SCRIPT_DIR/lib/checkpoint.sh"
source "$SCRIPT_DIR/lib/forge-keepass-gate.sh"

exec >> "$FORGE_LOG" 2>&1
echo "[{phase_name}] Starting at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
"""


# ---------------------------------------------------------------------------
# forge.sh — orchestrator
# ---------------------------------------------------------------------------

def generate_forge_sh(manifest: dict) -> str:
    """Generate forge.sh — the top-level forge orchestrator."""
    hostname = (manifest.get("host_identity") or {}).get("hostname") or "pve01"
    cell_id  = manifest.get("cell_id") or f"{hostname}-cell"
    return f"""\
#!/usr/bin/env bash
# forge.sh — Broodforge hatchery forge orchestrator (Phase 1.F.2)
# Forges bare Proxmox hardware into an operational broodforge hatchery.
#
# Usage:
#   bash forge.sh           Run all phases in order (skips completed)
#   bash forge.sh --reset   Reset all checkpoints and start fresh
#   bash forge.sh --from N  Resume from phase N (0-8)
#
# Cell: {cell_id}  Hostname: {hostname}
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
FORGE_LOG="${{SCRIPT_DIR}}/forge.log"

source "$SCRIPT_DIR/lib/checkpoint.sh"

RESET=0
FROM_PHASE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --reset)  RESET=1; shift ;;
    --from)   FROM_PHASE="$2"; shift 2 ;;
    *)        echo "Unknown flag: $1" >&2; exit 1 ;;
  esac
done

[ "$RESET" -eq 1 ] && checkpoint_reset

PHASES=(
  "phase-00-discover.sh"
  "phase-01-plan.sh"
  "phase-02-validate.sh"
  "phase-03-host.sh"
  "phase-04-vms.sh"
  "phase-05-k3s.sh"
  "phase-06-gitops.sh"
  "phase-07-intelligence.sh"
  "phase-08-verify.sh"
)

echo "================================================================="
echo ' Broodforge Forge — {cell_id}'
echo " $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "================================================================="
echo ""

for i in "${{!PHASES[@]}}"; do
  phase_num=$((i))
  script="${{PHASES[$i]}}"
  if [ "$phase_num" -lt "$FROM_PHASE" ]; then
    echo "[forge] Skipping $script (--from $FROM_PHASE)"
    continue
  fi
  if is_done "forge_phase_${{phase_num}}_complete"; then
    echo "[forge] SKIP  $script (checkpoint exists)"
    continue
  fi
  echo "[forge] >>>  $script"
  bash "$SCRIPT_DIR/$script" || {{
    echo "[forge] FAIL $script — aborting." >&2
    echo "[forge] Re-run: bash forge.sh --from ${{phase_num}}" >&2
    exit 1
  }}
  checkpoint_done "forge_phase_${{phase_num}}_complete"
done

echo ""
echo "================================================================="
echo " Forge complete. Your hatchery is operational."
echo ""
echo ' Hostname:  {hostname}'
echo ' Cell ID:   {cell_id}'
echo ""
echo " Next steps:"
echo "   1. Push your GitOps repository to Forgejo"
echo "   2. Flux CD will deploy application workloads"
echo "   3. Run: python3 doc-gen/engine.py --mode bootstrap"
echo "================================================================="
"""


# ---------------------------------------------------------------------------
# Phase scripts
# ---------------------------------------------------------------------------

def generate_phase_00_sh(manifest: dict) -> str:
    """Phase 00 — Hardware discovery."""
    return _phase_header("phase-00-discover", "Hardware discovery") + """\

step="phase00_discover"
if is_done "$step"; then checkpoint_skip "$step"; else
  checkpoint_start "$step"
  python3 "$SCRIPT_DIR/proxmox-bootstrap/spawn_hardware_discovery.py" \\
    --local --output "$SCRIPT_DIR/hardware-profile.json"
  python3 "$SCRIPT_DIR/proxmox-bootstrap/forge_validator.py" \\
    --profile "$SCRIPT_DIR/hardware-profile.json" || {
    echo "[phase-00] WARNING: Validator reported issues. Check hardware-profile.json." >&2
  }
  checkpoint_done "$step"
fi
echo "[phase-00] Hardware discovery complete."
"""


def generate_phase_01_sh(manifest: dict) -> str:
    """Phase 01 — Forge planning."""
    return _phase_header("phase-01-plan", "Forge planning (identity, network, mode)") + """\

step="phase01_plan"
if is_done "$step"; then checkpoint_skip "$step"; else
  checkpoint_start "$step"
  echo "[phase-01] Running forge planner..."
  python3 "$SCRIPT_DIR/proxmox-bootstrap/forge-planner.py" \\
    --manifest "$SCRIPT_DIR/forge-manifest.json"
  echo "[phase-01] forge-manifest.json written."
  checkpoint_done "$step"
fi
echo "[phase-01] Forge planning complete."
"""


def generate_phase_02_sh(manifest: dict) -> str:
    """Phase 02 — Hardware validation (RED findings block)."""
    return _phase_header("phase-02-validate", "Hardware validation (RED findings block forge)") + """\

step="phase02_validate"
if is_done "$step"; then checkpoint_skip "$step"; else
  checkpoint_start "$step"
  python3 - <<'PYEOF'
import json, sys, os
# __file__ is undefined in heredoc stdin mode; use $SCRIPT_DIR (set by the calling shell).
sys.path.insert(0, os.path.join(os.environ.get("SCRIPT_DIR", "."), "proxmox-bootstrap"))
from forge_validator import validate_forge_hardware, is_forge_valid, summarise_forge_findings

try:
    hw = json.load(open("hardware-profile.json"))
except FileNotFoundError:
    print("[phase-02] hardware-profile.json not found. Run phase-00 first.", file=sys.stderr)
    sys.exit(1)

findings = validate_forge_hardware(hw)
print(summarise_forge_findings(findings))
if not is_forge_valid(findings):
    print("[phase-02] RED findings present — forge blocked.", file=sys.stderr)
    print("[phase-02] Resolve hardware issues and re-run forge.sh --from 2", file=sys.stderr)
    sys.exit(1)
print("[phase-02] Validation passed.")
PYEOF
  checkpoint_done "$step"
fi
echo "[phase-02] Validation complete."
"""


def generate_phase_03_sh(manifest: dict) -> str:
    """Phase 03 — Host configuration."""
    hostname   = (manifest.get("host_identity") or {}).get("hostname") or "pve01"
    domain     = (manifest.get("host_identity") or {}).get("domain")   or "home.example.com"
    fqdn       = (manifest.get("host_identity") or {}).get("fqdn")     or f"{hostname}.{domain}"
    profile    = (manifest.get("network_topology") or {}).get("profile") or "lan"

    return _phase_header("phase-03-host", "Host configuration") + f"""\

HOSTNAME='{hostname}'
DOMAIN='{domain}'
FQDN='{fqdn}'
NETWORK_PROFILE='{profile}'

# ---- Master password suggestion (shown to operator before the gate) -------
# Display is sent to /dev/tty so it reaches the operator regardless of log
# redirects. The suggestion is generated by keepassxc-cli (KeePass's own
# CSPRNG) if available; otherwise by Python's secrets module (os.urandom).
# The suggestion is shown ONCE and is never stored by broodforge.
python3 - >/dev/tty 2>/dev/null <<'SUGGEST_EOF'
import sys, os
# __file__ is undefined in heredoc stdin mode; use $SCRIPT_DIR (set by the calling shell).
sys.path.insert(0, os.path.join(os.environ.get("SCRIPT_DIR", "."), "lib"))
try:
    from passphrase import generate_master_password_suggestion
    suggestion, source = generate_master_password_suggestion()
    bar = "=" * 68
    print("")
    print(bar)
    print(" KeePass Master Password Suggestion")
    print(bar)
    print("")
    print(" Suggested password (" + source + "):")
    print("    " + suggestion)
    print("")
    print(" You may use this suggestion, enter your own, or use KeePass's")
    print(" built-in generator. This is shown ONCE and not stored by broodforge.")
    print(" Write it down BEFORE entering it at the prompt below.")
    print(bar)
    print("")
except Exception:
    pass
SUGGEST_EOF

# KeePass gate — required before any secrets are accessed
forge_keepass_gate

# ---- Hostname -----------------------------------------------------------
step="phase03_hostname"
if is_done "$step"; then checkpoint_skip "$step"; else
  checkpoint_start "$step"
  hostnamectl set-hostname "$HOSTNAME"
  sed -i "s/^127\\.0\\.1\\.1.*/127.0.1.1 $FQDN $HOSTNAME/" /etc/hosts
  echo "[phase-03] Hostname set to $HOSTNAME ($FQDN)"
  checkpoint_done "$step"
fi

# ---- Proxmox nag suppression -------------------------------------------
step="phase03_nag_suppress"
if is_done "$step"; then checkpoint_skip "$step"; else
  checkpoint_start "$step"
  bash "$SCRIPT_DIR/lib/pve-suppress-nag.sh" && checkpoint_done "$step" || \\
    echo "[phase-03] WARNING: nag suppression failed (non-critical)" >&2
fi

# ---- ZFS pool ----------------------------------------------------------
step="phase03_zfs"
if is_done "$step"; then checkpoint_skip "$step"; else
  checkpoint_start "$step"
  python3 "$SCRIPT_DIR/proxmox-bootstrap/spawn_hardware_discovery.py" \\
    --local --output "$SCRIPT_DIR/hardware-profile.json" --quiet 2>/dev/null || true
  python3 - <<'PYEOF'
import json, subprocess, sys
hw = json.load(open("hardware-profile.json"))
disks = [d for d in hw.get("disks", [])
         if not d.get("removable") and (d.get("size_gb") or 0) >= 32]
n = len(disks)
if n == 0:
    print("[phase-03] No usable disks found for ZFS.", file=sys.stderr); sys.exit(1)
disk_devs = ["/dev/" + d["name"] for d in disks[:min(n, 8)]]
topo = "mirror" if n == 2 else ("raidz1" if n <= 5 else ("raidz2" if n <= 8 else "raidz3"))
if n == 1: topo = ""  # stripe
cmd = ["zpool", "create", "-f", "rpool"] + ([topo] if topo else []) + disk_devs
print(f"[phase-03] Creating ZFS pool: " + " ".join(cmd))
subprocess.run(cmd, check=True, timeout=300)
subprocess.run(["pvesm", "add", "zfspool", "local-zfs",
                "--pool", "rpool/data", "--sparse", "1"], check=False, timeout=30)
PYEOF
  checkpoint_done "$step"
fi

# ---- Network bridges (defer to Proxmox ifreload) ----------------------
step="phase03_network"
if is_done "$step"; then checkpoint_skip "$step"; else
  checkpoint_start "$step"
  echo "[phase-03] Network bridges managed by Proxmox (vmbr0 pre-exists)."
  echo "[phase-03] Additional bridge config derived from hardware-profile.json at VM creation."
  ifreload -a 2>/dev/null || true
  checkpoint_done "$step"
fi

# ---- dnsmasq -----------------------------------------------------------
step="phase03_dnsmasq"
if is_done "$step"; then checkpoint_skip "$step"; else
  checkpoint_start "$step"
  apt-get install -y dnsmasq
  python3 "$SCRIPT_DIR/proxmox-bootstrap/setup_dnsmasq.py" \\
    --manifest "$SCRIPT_DIR/forge-manifest.json" \\
    --dns-registry "$SCRIPT_DIR/proxmox-bootstrap/dns-registry.yaml" \\
    --output /etc/dnsmasq.d/broodforge.conf
  systemctl enable --now dnsmasq
  echo "[phase-03] dnsmasq configured and running."
  checkpoint_done "$step"
fi

# ---- KeePass database initialisation -----------------------------------
step="phase03_keepass"
if is_done "$step"; then checkpoint_skip "$step"; else
  checkpoint_start "$step"
  # TOTP secret display and keepass prompts are redirected to /dev/tty so they
  # reach the operator terminal but are NOT captured in forge.log
  KEEPASS_MASTER_PASSWORD="$KEEPASS_MASTER_PASSWORD" \\
    python3 "$SCRIPT_DIR/proxmox-bootstrap/forge_keepass_init.py" \\
      --manifest "$SCRIPT_DIR/forge-manifest.json" \\
      --run >/dev/tty
  checkpoint_done "$step"
fi

# ---- Headscale (WAN profile only) -------------------------------------
if [ "$NETWORK_PROFILE" = "wan" ]; then
  step="phase03_headscale"
  if is_done "$step"; then checkpoint_skip "$step"; else
    checkpoint_start "$step"
    python3 "$SCRIPT_DIR/proxmox-bootstrap/setup_headscale.py" \\
      --manifest "$SCRIPT_DIR/forge-manifest.json" \\
      --run
    checkpoint_done "$step"
  fi

  # ---- TLS certificates -----------------------------------------------
  step="phase03_tls"
  if is_done "$step"; then checkpoint_skip "$step"; else
    checkpoint_start "$step"
    python3 "$SCRIPT_DIR/proxmox-bootstrap/setup_tls.py" \\
      --manifest "$SCRIPT_DIR/forge-manifest.json" \\
      --run
    checkpoint_done "$step"
  fi

  # ---- DDNS -----------------------------------------------------------
  step="phase03_ddns"
  if is_done "$step"; then checkpoint_skip "$step"; else
    checkpoint_start "$step"
    python3 "$SCRIPT_DIR/proxmox-bootstrap/setup_ddns.py" \\
      --manifest "$SCRIPT_DIR/forge-manifest.json" \\
      --run
    checkpoint_done "$step"
  fi
fi

echo "[phase-03] Host configuration complete."
"""


def generate_phase_04_sh(manifest: dict) -> str:
    """Phase 04 — VM provisioning."""
    return _phase_header("phase-04-vms", "VM provisioning (tofu apply — minimum viable stack)") + """\

step="phase04_vms"
if is_done "$step"; then checkpoint_skip "$step"; else
  checkpoint_start "$step"
  if [ -d "$SCRIPT_DIR/opentofu" ]; then
    cd "$SCRIPT_DIR/opentofu"
    tofu init -input=false
    tofu plan -input=false -out=forge.tfplan
    tofu apply -input=false forge.tfplan
    cd "$SCRIPT_DIR"
  else
    echo "[phase-04] No opentofu/ modules in package — VM provisioning skipped." >&2
    echo "[phase-04] The forge VM-provisioning IaC is the active deploy-to-hardware" >&2
    echo "[phase-04] work; see FORGING.md 'Forge provisioning status (opentofu/ansible)'." >&2
    echo "[phase-04] Provision the Forgejo + operations VMs manually, then re-run --from 5." >&2
  fi
  checkpoint_done "$step"
fi
echo "[phase-04] VM provisioning complete."
"""


def generate_phase_05_sh(manifest: dict) -> str:
    """Phase 05 — k3s cluster initialisation."""
    return _phase_header("phase-05-k3s", "k3s cluster init (ansible k3s-server role)") + """\

step="phase05_k3s"
if is_done "$step"; then checkpoint_skip "$step"; else
  checkpoint_start "$step"
  _ans="$SCRIPT_DIR/ansible"
  _inv="$_ans/inventory/hosts.yaml"
  _play="$_ans/playbooks/04-k3s.yaml"
  if [ -f "$_inv" ] && [ -f "$_play" ]; then
    # Write k3s token to a temp vars file so it never appears on the ansible command line
    # (command-line -e values are visible in ps aux and may appear in logs)
    _k3s_vars=$(mktemp)
    chmod 600 "$_k3s_vars"
    trap 'rm -f "$_k3s_vars"' EXIT INT TERM
    printf 'k3s_token: "%s"\\n' "$(kdbx_get 'k3s/join-token-server')" > "$_k3s_vars"
    ansible-playbook -i "$_inv" "$_play" -e "@$_k3s_vars"
    rm -f "$_k3s_vars"
    trap - EXIT INT TERM
  else
    echo "[phase-05] ansible inventory ($_inv) not generated — k3s setup is manual for now." >&2
    echo "[phase-05] See FORGING.md 'Forge provisioning status (opentofu/ansible)'." >&2
  fi
  checkpoint_done "$step"
fi
echo "[phase-05] k3s cluster init complete."
"""


def generate_phase_06_sh(manifest: dict) -> str:
    """Phase 06 — Flux CD bootstrap."""
    return _phase_header("phase-06-gitops", "Flux CD bootstrap → Forgejo") + """\

step="phase06_flux"
if is_done "$step"; then checkpoint_skip "$step"; else
  checkpoint_start "$step"
  # Export kubeconfig from k3s
  export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

  # Install Flux CLI if not present
  command -v flux &>/dev/null || curl -s https://fluxcd.io/install.sh | FLUX_VERSION=latest bash

  FORGEJO_TOKEN="$(kdbx_get 'Infrastructure/forgejo/admin-password')"
  FORGEJO_HOST="$(python3 -c "import json; m=json.load(open('forge-manifest.json')); print(m.get('host_identity',{}).get('fqdn','localhost'))")"

  flux bootstrap gitea \\
    --hostname "$FORGEJO_HOST" \\
    --owner broodforge \\
    --repository gitops \\
    --path ./clusters/hatchery \\
    --token-auth \\
    --personal

  checkpoint_done "$step"
fi
echo "[phase-06] Flux CD bootstrap complete."
"""


def generate_phase_07_sh(manifest: dict) -> str:
    """Phase 07 — Intelligence layer setup."""
    return _phase_header("phase-07-intelligence", "Intelligence layer (assessment + doc engine)") + """\

step="phase07_assessment_engine"
if is_done "$step"; then checkpoint_skip "$step"; else
  checkpoint_start "$step"
  # Initialise bootstrap-state.json from forge manifest
  python3 "$SCRIPT_DIR/proxmox-bootstrap/init-bootstrap-state.py" \\
    --manifest "$SCRIPT_DIR/forge-manifest.json" \\
    --output "$SCRIPT_DIR/proxmox-bootstrap/bootstrap-state.json"

  # Generate first documentation set
  python3 "$SCRIPT_DIR/doc-gen/engine.py" \\
    --mode bootstrap \\
    --state "$SCRIPT_DIR/proxmox-bootstrap/bootstrap-state.json" \\
    --output "$SCRIPT_DIR/reports/" || \\
    echo "[phase-07] WARNING: doc engine failed — check bootstrap-state.json" >&2

  checkpoint_done "$step"
fi
echo "[phase-07] Intelligence layer initialised."
"""


def generate_phase_08_sh(manifest: dict) -> str:
    """Phase 08 — Verify and commit."""
    cell_id = manifest.get("cell_id") or "pve01-cell"
    return _phase_header("phase-08-verify", "Verify cluster health and commit state") + f"""\

CELL_ID='{cell_id}'

step="phase08_k3s_health"
if is_done "$step"; then checkpoint_skip "$step"; else
  checkpoint_start "$step"
  export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
  kubectl wait node --all --for=condition=Ready --timeout=120s || {{
    echo "[phase-08] k3s nodes not ready after 120s." >&2
    checkpoint_failed "$step"
  }}
  checkpoint_done "$step"
fi

step="phase08_flux_health"
if is_done "$step"; then checkpoint_skip "$step"; else
  checkpoint_start "$step"
  export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
  flux check 2>/dev/null || echo "[phase-08] WARNING: flux not yet reconciled (may still be bootstrapping)"
  checkpoint_done "$step"
fi

step="phase08_commit"
if is_done "$step"; then checkpoint_skip "$step"; else
  checkpoint_start "$step"
  cd "$SCRIPT_DIR"
  if [ -d .git ]; then
    git add proxmox-bootstrap/bootstrap-state.json forge-manifest.json || true
    git commit -m "forge: $CELL_ID — initial hatchery bootstrap $(date -u +%Y-%m-%dT%H:%M:%SZ)" \\
      --allow-empty || true
    git push 2>/dev/null || echo "[phase-08] WARNING: git push failed — commit exists locally."
  fi
  checkpoint_done "$step"
fi

echo "[phase-08] Verification and commit complete."
echo "================================================================="
echo " Hatchery operational: $CELL_ID"
echo "================================================================="
"""


# ---------------------------------------------------------------------------
# Write all scripts to output directory
# ---------------------------------------------------------------------------

def write_all_forge_scripts(manifest: dict, output_dir: str) -> list[str]:
    """
    Write all forge scripts to output_dir and return list of filenames written.
    """
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    lib_dir = output / "lib"
    lib_dir.mkdir(exist_ok=True)

    scripts = {
        "forge.sh":                 generate_forge_sh(manifest),
        "phase-00-discover.sh":     generate_phase_00_sh(manifest),
        "phase-01-plan.sh":         generate_phase_01_sh(manifest),
        "phase-02-validate.sh":     generate_phase_02_sh(manifest),
        "phase-03-host.sh":         generate_phase_03_sh(manifest),
        "phase-04-vms.sh":          generate_phase_04_sh(manifest),
        "phase-05-k3s.sh":          generate_phase_05_sh(manifest),
        "phase-06-gitops.sh":       generate_phase_06_sh(manifest),
        "phase-07-intelligence.sh": generate_phase_07_sh(manifest),
        "phase-08-verify.sh":       generate_phase_08_sh(manifest),
    }
    lib_scripts = {
        "lib/checkpoint.sh":        FORGE_CHECKPOINT_SH,
        "lib/forge-keepass-gate.sh": FORGE_KEEPASS_GATE_SH,
    }

    written = []
    for name, content in {**scripts, **lib_scripts}.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(name)

    return written
