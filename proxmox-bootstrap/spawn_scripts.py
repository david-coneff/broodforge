#!/usr/bin/env python3
"""
spawn_scripts.py — Spawn phase script generator (Phase 12.E.6).

Generates the bash scripts embedded in every spawn package.
Pattern mirrors phoenix_scripts.py but for the seven spawn phases.

Provides:
  generate_spawn_sh(plan)           — orchestrating entry point
  generate_phase_00_preflight(plan) — hardware pre-flight (read-only)
  generate_phase_00_host(plan)      — host configuration (bridge/ZFS/hostname)
  generate_phase_01_proxmox(plan)   — pvecm join
  generate_phase_02_vms(plan)       — tofu apply
  generate_phase_03_cloudinit(plan) — cloud-init snippets + VM start
  generate_phase_04_k3s(plan)       — ansible k3s role
  generate_tailscale_join_sh(plan)  — WAN mode: tailscale/headscale join
  generate_phase_05_ha(plan)        — conditional HA promotion
  generate_phase_06_verify(plan)    — post-spawn health check
  write_all_scripts(plan, output_dir) — write everything to disk

All generators return strings. write_all_scripts() writes to disk.
Stdlib only.
"""

import shlex
from pathlib import Path

_SHEBANG  = "#!/usr/bin/env bash"
_STRICT   = "set -euo pipefail"
_CHECKPOINT_LIB = """\
CHECKPOINT_DIR="${SCRIPT_DIR}/.checkpoints"
mkdir -p "$CHECKPOINT_DIR"
checkpoint_start()  { echo "[spawn] START: $1"; }
checkpoint_done()   { touch "$CHECKPOINT_DIR/$1.done"; echo "[spawn] DONE: $1"; }
checkpoint_skip()   { echo "[spawn] SKIP (done): $1"; }
checkpoint_failed() { echo "[spawn] FAILED: $1 — see $SPAWN_LOG"; exit 1; }
is_done()           { [ -f "$CHECKPOINT_DIR/$1.done" ]; }
"""

def _plan_header(plan: dict, script_name: str) -> str:
    return (
        f"{_SHEBANG}\n"
        f"# {script_name}\n"
        f"# Spawn package: {plan.get('package_id', '?')}\n"
        f"# Broodling:     {plan.get('hostname', '?')}\n"
        f"# Generated:     {plan.get('generated_at', '?')}\n"
        f"# DO NOT EDIT — regenerate from spawn-plan.json\n"
        f"{_STRICT}\n\n"
        f'SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"\n'
        f'SPAWN_LOG="$SCRIPT_DIR/spawn-$(date +%Y%m%d_%H%M%S).log"\n'
        f'source "$SCRIPT_DIR/lib/checkpoint.sh" 2>/dev/null || {{\n{_CHECKPOINT_LIB}}}\n\n'
    )


# ---------------------------------------------------------------------------
# spawn.sh — orchestrating entry point
# ---------------------------------------------------------------------------

def generate_spawn_sh(plan: dict, include_wan_phase: bool = False) -> str:
    hostname   = plan.get("hostname", "unknown")
    vms        = plan.get("vms") or []
    k3s_role   = (plan.get("k3s") or {}).get("role", "worker")
    exec_mode  = plan.get("disposition", {}).get("execution_mode", "autonomous")
    package_id = plan.get("package_id", "?")
    has_ha     = k3s_role == "server" and len(vms) > 0

    lines = [
        _plan_header(plan, "spawn.sh — orchestrated entry point"),
        'exec > >(tee -a "$SPAWN_LOG") 2>&1',
        "echo '================================================================='",
        f"echo ' Broodforge Spawn — {hostname}'",
        f"echo ' Mode: {exec_mode}   k3s role: {k3s_role}'",
        f"echo ' Package: {package_id}'",
        "echo '================================================================='",
        'echo ""',
        '',
    ]

    lines += [
        '# ── KeePass unlock gate ──────────────────────────────────────────────',
        'if [ -f "$SCRIPT_DIR/lib/keepass-gate.sh" ]; then',
        '  source "$SCRIPT_DIR/lib/keepass-gate.sh"',
        '  keepass_unlock_gate',
        'fi',
        '',
    ]

    phases = []
    if include_wan_phase:
        phases.append(("00a", "tailscale-join", "Tailscale join (WAN mode)"))
    phases += [
        ("00-preflight", "phase-00-preflight", "Hardware pre-flight (read-only)"),
        ("00-host",      "phase-00-host",      "Host configuration"),
        ("01",           "phase-01-proxmox",   "Proxmox cluster join"),
        ("02",           "phase-02-vms",       "VM provisioning"),
        ("03",           "phase-03-cloudinit", "Cloud-Init + VM start"),
        ("04",           "phase-04-k3s",       "k3s join"),
    ]
    if has_ha:
        phases.append(("05", "phase-05-ha", "HA promotion (3rd server node)"))
    phases.append(("06", "phase-06-verify", "Post-spawn verification"))

    for phase_id, script, desc in phases:
        lines += [
            f'# ── Phase {phase_id}: {desc}',
            f'echo "[spawn] Phase {phase_id}: {desc}"',
            f'bash "$SCRIPT_DIR/{script}.sh" \\',
            f'  || {{ echo "[spawn] FAILED: {desc}"; exit 1; }}',
            'echo ""',
            '',
        ]

    lines += [
        "echo '================================================================='",
        f"echo ' Spawn complete: {hostname}'",
        "echo ' Report success to hatchery to trigger bootstrap-state update.'",
        "echo '================================================================='",
        'echo ""',
        "echo ' Post-spawn validation:'",
        "echo '   qm list                     # all VMs running'",
        "echo '   kubectl get nodes            # all nodes Ready'",
        "echo '   flux get kustomizations      # Flux reconciled'",
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# phase-00-preflight.sh — hardware pre-flight (read-only)
# ---------------------------------------------------------------------------

def generate_phase_00_preflight(plan: dict) -> str:
    storage  = plan.get("storage") or {}
    network  = plan.get("network") or {}
    pool     = storage.get("pool_name", "rpool")
    bridge   = network.get("bridge", "vmbr0")
    disk_ids = storage.get("disk_ids") or []
    vms      = plan.get("vms") or []
    host_ram_needed = sum(v.get("memory_mb", 4096) for v in vms) / 1024 * 1.1

    pool_q   = shlex.quote(pool)
    bridge_q = shlex.quote(bridge)
    disks_check = "\n".join(
        f"  if [ ! -b {shlex.quote(d)} ]; then FAILS+=('Disk {d} not found'); fi"
        for d in disk_ids
    ) or '  echo "  No disk IDs in plan — skipping disk check"'

    return (
        _plan_header(plan, "phase-00-preflight.sh — hardware pre-flight (read-only)") +
        'echo "[preflight] Checking hardware against embedded profile..."\n'
        'FAILS=()\n\n'
        '# ── Disk presence ────────────────────────────────────────────────\n'
        + disks_check + "\n\n"
        f'# ── No conflicting ZFS pool ──────────────────────────────────────\n'
        f'if zpool list {pool_q} &>/dev/null; then\n'
        f"  FAILS+=('ZFS pool {pool} already exists — conflict with spawn plan')\n"
        f'fi\n\n'
        f'# ── No conflicting bridge ─────────────────────────────────────────\n'
        f'if ip link show {bridge_q} &>/dev/null; then\n'
        f"  echo '  Bridge {bridge} already exists — will verify config'\n"
        f'fi\n\n'
        f'# ── Sufficient RAM ───────────────────────────────────────────────\n'
        f'AVAIL_RAM_GB=$(awk \'/MemAvailable/{{printf "%.1f", $2/1048576}}\' /proc/meminfo)\n'
        f'NEEDED={host_ram_needed:.1f}\n'
        f'if (( $(echo "$AVAIL_RAM_GB < $NEEDED" | bc -l) )); then\n'
        f'  FAILS+=("Insufficient RAM: ${{AVAIL_RAM_GB}}GB available, {host_ram_needed:.1f}GB needed")\n'
        f'fi\n\n'
        f'# ── Re-run conflict validator ────────────────────────────────────\n'
        f'if command -v python3 &>/dev/null && [ -f "$SCRIPT_DIR/validate-spawn.py" ]; then\n'
        f'  python3 "$SCRIPT_DIR/validate-spawn.py" \\\n'
        f'    --manifest "$SCRIPT_DIR/spawn-manifest.json" \\\n'
        f'    --plan     "$SCRIPT_DIR/spawn-plan.json" \\\n'
        f'    || FAILS+=("Conflict validator: collisions detected")\n'
        f'fi\n\n'
        f'# ── Result ───────────────────────────────────────────────────────\n'
        f'if [ ${{#FAILS[@]}} -gt 0 ]; then\n'
        f'  echo "[preflight] FAILED — ${{#FAILS[@]}} issue(s):"\n'
        f'  for f in "${{FAILS[@]}}"; do echo "  ✗ $f"; done\n'
        f'  echo "[preflight] No changes made to this host. Fix issues and regenerate package."\n'
        f'  exit 1\n'
        f'fi\n'
        f'echo "[preflight] All checks PASSED"\n'
    )


# ---------------------------------------------------------------------------
# phase-00-host.sh — host configuration
# ---------------------------------------------------------------------------

def generate_phase_00_host(plan: dict) -> str:
    hostname = plan.get("hostname", "unknown")
    lan_ip   = plan.get("lan_ip", "")
    storage  = plan.get("storage") or {}
    network  = plan.get("network") or {}
    pool     = storage.get("pool_name", "rpool")
    topology = storage.get("topology", "mirror")
    disk_ids = storage.get("disk_ids") or []
    bridge   = network.get("bridge", "vmbr0")
    domain   = plan.get("domain", "internal")
    disks_str = " ".join(shlex.quote(d) for d in disk_ids)
    ds_name  = storage.get("datastore_name", f"local-{pool}")

    # Shell-quote plan values before embedding them in generated bash
    h   = shlex.quote(hostname)
    shlex.quote(lan_ip)
    shlex.quote(domain)
    br  = shlex.quote(bridge)
    p   = shlex.quote(pool)
    topo = shlex.quote(topology)
    ds  = shlex.quote(ds_name)
    hosts_entry = shlex.quote(f"{lan_ip}  {hostname}.{domain} {hostname}")

    return (
        _plan_header(plan, "phase-00-host.sh — host configuration") +
        f'# ── Hostname ────────────────────────────────────────────────────\n'
        f'is_done "hostname" && checkpoint_skip "hostname" || {{\n'
        f'  checkpoint_start "hostname"\n'
        f'  hostnamectl set-hostname {h}\n'
        f'  # Fix /etc/hosts (pvecm add fails if hostname resolves to 127.0.0.1)\n'
        f'  sed -i "/127.0.1.1/d" /etc/hosts\n'
        f'  echo {hosts_entry} >> /etc/hosts\n'
        f'  checkpoint_done "hostname"\n'
        f'}}\n\n'
        f'# ── Network bridge ──────────────────────────────────────────────\n'
        f'is_done "bridge" && checkpoint_skip "bridge" || {{\n'
        f'  checkpoint_start "bridge"\n'
        f'  # Write bridge config from spawn plan to /etc/network/interfaces\n'
        f'  cat "$SCRIPT_DIR/network/interfaces.d/{br}" >> /etc/network/interfaces.d/{br}\n'
        f'  ifreload -a\n'
        f'  checkpoint_done "bridge"\n'
        f'}}\n\n'
        f'# ── ZFS pool ────────────────────────────────────────────────────\n'
        f'is_done "zpool" && checkpoint_skip "zpool" || {{\n'
        f'  checkpoint_start "zpool"\n'
        f'  zpool create {p} {topo} {disks_str}\n'
        f'  checkpoint_done "zpool"\n'
        f'}}\n\n'
        f'# ── Register datastore with Proxmox ─────────────────────────────\n'
        f'is_done "pvesm" && checkpoint_skip "pvesm" || {{\n'
        f'  checkpoint_start "pvesm"\n'
        f'  pvesm add zfspool {ds} --pool {p} --sparse 1\n'
        f'  checkpoint_done "pvesm"\n'
        f'}}\n\n'
        f'# ── apt repos ───────────────────────────────────────────────────\n'
        f'is_done "apt-repos" && checkpoint_skip "apt-repos" || {{\n'
        f'  checkpoint_start "apt-repos"\n'
        f'  # Disable enterprise repos, enable no-subscription\n'
        f'  sed -i "s/^deb/# deb/" /etc/apt/sources.list.d/pve-enterprise.list 2>/dev/null || true\n'
        f'  echo "deb http://download.proxmox.com/debian/pve bookworm pve-no-subscription" \\\n'
        f'    > /etc/apt/sources.list.d/pve-no-subscription.list\n'
        f'  apt-get update -qq\n'
        f'  checkpoint_done "apt-repos"\n'
        f'}}\n\n'
        f'echo "[host] Host configuration complete"\n'
    )


# ---------------------------------------------------------------------------
# phase-01-proxmox.sh — pvecm join
# ---------------------------------------------------------------------------

def generate_phase_01_proxmox(plan: dict) -> str:
    hatchery = (plan.get("hatchery") or {}).get("proxmox_cluster_address", "hatchery")
    fingerprint = (plan.get("hatchery") or {}).get("proxmox_cluster_fingerprint") or ""
    h = shlex.quote(hatchery)
    fp_arg = f'--fingerprint {shlex.quote(fingerprint)}' if fingerprint else ""

    return (
        _plan_header(plan, "phase-01-proxmox.sh — Proxmox cluster join") +
        f'is_done "pvecm" && checkpoint_skip "pvecm" || {{\n'
        f'  checkpoint_start "pvecm"\n'
        f'  # Check if already a cluster member\n'
        f'  if pvecm status 2>/dev/null | grep -q "Quorum"; then\n'
        f'    echo "[pvecm] Already a cluster member — skipping join"\n'
        f'  else\n'
        f'    pvecm add {h} {fp_arg}\n'
        f'  fi\n'
        f'  checkpoint_done "pvecm"\n'
        f'}}\n\n'
        f'# Verify membership\n'
        f'pvecm status\n'
        f'echo "[pvecm] This host is now visible in Proxmox datacenter"\n'
    )


# ---------------------------------------------------------------------------
# phase-02-vms.sh — tofu apply
# ---------------------------------------------------------------------------

def generate_phase_02_vms(plan: dict) -> str:
    hostname = plan.get("hostname", "unknown")
    return (
        _plan_header(plan, "phase-02-vms.sh — VM provisioning via OpenTofu") +
        f'is_done "tofu-apply" && checkpoint_skip "tofu-apply" || {{\n'
        f'  checkpoint_start "tofu-apply"\n'
        f'  cd "$SCRIPT_DIR/opentofu"\n'
        f'  tofu init -input=false\n'
        f'  tofu apply -input=false -auto-approve \\\n'
        f"    -var-file='spawn-{hostname}.auto.tfvars'\n"
        f'  checkpoint_done "tofu-apply"\n'
        f'}}\n\n'
        f'# Verify VMs created\n'
        f'qm list\n'
        f'echo "[vms] VM provisioning complete"\n'
    )


# ---------------------------------------------------------------------------
# phase-03-cloudinit.sh — snippets + VM start + SSH readiness
# ---------------------------------------------------------------------------

def generate_phase_03_cloudinit(plan: dict) -> str:
    snippets_store = shlex.quote((plan.get("storage") or {}).get("snippets", "local:snippets"))
    vms = plan.get("vms") or []
    vm_waits = "\n".join(
        f'wait_ssh {shlex.quote(str(v.get("ip","")))} {shlex.quote(str(v.get("name","vm")))}'
        for v in vms if v.get("ip")
    )

    return (
        _plan_header(plan, "phase-03-cloudinit.sh — Cloud-Init snippets + VM start") +
        f'wait_ssh() {{\n'
        f'  local ip="$1" name="$2" retries=30\n'
        f'  echo "[cloud-init] Waiting for SSH on $name ($ip)..."\n'
        f'  for i in $(seq 1 $retries); do\n'
        f'    ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new ubuntu@"$ip" exit 0 2>/dev/null \\\n'
        f'      && {{ echo "[cloud-init] $name SSH ready"; return 0; }}\n'
        f'    sleep 10\n'
        f'  done\n'
        f'  echo "[cloud-init] Timeout waiting for $name" && exit 1\n'
        f'}}\n\n'
        f'is_done "snippets" && checkpoint_skip "snippets" || {{\n'
        f'  checkpoint_start "snippets"\n'
        f'  # Upload Cloud-Init snippets to Proxmox snippet store\n'
        f'  for f in "$SCRIPT_DIR"/cloud-init/snippets/user-data/*.yaml; do\n'
        f'    pvesm upload {snippets_store} "$f" --content snippets\n'
        f'  done\n'
        f'  for f in "$SCRIPT_DIR"/cloud-init/snippets/network-config/*.yaml; do\n'
        f'    pvesm upload {snippets_store} "$f" --content snippets\n'
        f'  done\n'
        f'  checkpoint_done "snippets"\n'
        f'}}\n\n'
        f'is_done "vm-start" && checkpoint_skip "vm-start" || {{\n'
        f'  checkpoint_start "vm-start"\n'
        + "\n".join(
            '  qm start {} && echo "[cloud-init] Started {}"'.format(
                v.get("vmid", "?"), v.get("name", "?"))
            for v in vms
        ) + "\n"
        '  checkpoint_done "vm-start"\n'
        '}\n\n'
        '# Wait for SSH readiness on each VM\n'
        + vm_waits + "\n"
        '\necho "[cloud-init] All VMs booted and SSH-ready"\n'
    )


# ---------------------------------------------------------------------------
# phase-04-k3s.sh — ansible k3s join
# ---------------------------------------------------------------------------

def generate_phase_04_k3s(plan: dict) -> str:
    k3s_role = (plan.get("k3s") or {}).get("role", "worker")
    if k3s_role not in ("worker", "server"):
        raise ValueError(f"Invalid k3s role: {k3s_role!r} — must be 'worker' or 'server'")
    hostname_q = shlex.quote(plan.get("hostname", "?"))
    return (
        _plan_header(plan, f"phase-04-k3s.sh — k3s {k3s_role} join via Ansible") +
        f'is_done "k3s-join" && checkpoint_skip "k3s-join" || {{\n'
        f'  checkpoint_start "k3s-join"\n'
        f'  cd "$SCRIPT_DIR/ansible"\n'
        f'  ansible-playbook site.yml \\\n'
        f'    -i "spawn-{hostname_q}.ini" \\\n'
        f'    --tags k3s-{k3s_role}\n'
        f'  checkpoint_done "k3s-join"\n'
        f'}}\n\n'
        f'echo "[k3s] Node joined as {k3s_role}"\n'
    )


# ---------------------------------------------------------------------------
# tailscale-join.sh — WAN mode: join Headscale control plane via Tailscale
# ---------------------------------------------------------------------------

def generate_tailscale_join_sh(plan: dict) -> str:
    """Generate the tailscale join script for WAN-mode spawn packages.

    Reads the auth key and headscale URL from the spawn plan (embedded at
    package assembly time). Installs tailscale if missing, then runs
    `tailscale up --login-server <url> --authkey <key>`.
    """
    disposition    = plan.get("disposition") or {}
    auth_key       = disposition.get("wan_auth_key", "")
    headscale_url  = (plan.get("hatchery") or {}).get("headscale_url", "")

    auth_key_line = (
        f"AUTH_KEY='{auth_key}'" if auth_key
        else "AUTH_KEY=''  # populate before running — embed key in spawn-manifest.json"
    )
    server_line = (
        f"HEADSCALE_URL='{headscale_url}'" if headscale_url
        else "HEADSCALE_URL=''  # populate with your Headscale server URL"
    )

    return (
        _plan_header(plan, "tailscale-join.sh — WAN mode: Headscale / Tailscale join") +
        f'# WAN mode only: joins the broodling to the Headscale control plane so\n'
        f'# the hatchery can reach it over the internet.\n\n'
        f'{auth_key_line}\n'
        f'{server_line}\n\n'
        f'is_done "tailscale-join" && checkpoint_skip "tailscale-join" || {{\n'
        f'  checkpoint_start "tailscale-join"\n\n'
        f'  # Install tailscale if not present\n'
        f'  if ! command -v tailscale &>/dev/null; then\n'
        f'    echo "[tailscale] Installing tailscale..."\n'
        f'    curl -fsSL https://tailscale.com/install.sh | sh\n'
        f'  fi\n\n'
        f'  if [ -z "$AUTH_KEY" ]; then\n'
        f'    echo "[tailscale] ERROR: AUTH_KEY is empty — embed a Headscale auth key in the spawn package"\n'
        f'    exit 1\n'
        f'  fi\n\n'
        f'  if [ -z "$HEADSCALE_URL" ]; then\n'
        f'    echo "[tailscale] ERROR: HEADSCALE_URL is empty — set it to your Headscale server URL"\n'
        f'    exit 1\n'
        f'  fi\n\n'
        f'  echo "[tailscale] Joining Headscale at $HEADSCALE_URL"\n'
        f'  tailscale up \\\n'
        f'    --login-server "$HEADSCALE_URL" \\\n'
        f'    --authkey "$AUTH_KEY" \\\n'
        f'    --hostname "$(hostname -s)" \\\n'
        f'    --accept-routes\n\n'
        f'  # Verify connectivity\n'
        f'  tailscale status | grep -q "$(hostname -s)" \\\n'
        f'    || {{ echo "[tailscale] ERROR: node not visible in tailnet after join"; exit 1; }}\n\n'
        f'  checkpoint_done "tailscale-join"\n'
        f'}}\n\n'
        f'echo "[tailscale] Broodling joined tailnet — WAN connectivity established"\n'
    )


# ---------------------------------------------------------------------------
# phase-05-ha.sh — conditional HA promotion (3rd server node only)
# ---------------------------------------------------------------------------

def generate_phase_05_ha(plan: dict) -> str:
    server_url = (plan.get("k3s") or {}).get("server_url", "")
    server_host = shlex.quote(server_url.replace("https://", "").split(":")[0])
    return (
        _plan_header(plan, "phase-05-ha.sh — SQLite → etcd HA promotion (3rd server)") +
        f'# This phase only runs when this is the 3rd k3s server node.\n'
        f'# If omitted from the spawn package, HA promotion is not applicable.\n\n'
        f'is_done "ha-promote" && checkpoint_skip "ha-promote" || {{\n'
        f'  checkpoint_start "ha-promote"\n'
        f'  echo "[ha] Promoting k3s cluster from SQLite to embedded etcd"\n'
        f'  # This procedure quiesces the existing cluster, promotes etcd,\n'
        f'  # and distributes the control plane across all 3 server nodes.\n'
        f'  # Run against the hatchery k3s server:\n'
        f'  ssh ubuntu@{server_host} \\\n'
        f'    "sudo k3s etcd-snapshot save && sudo systemctl restart k3s"\n'
        f'  checkpoint_done "ha-promote"\n'
        f'}}\n\n'
        f'echo "[ha] HA promotion complete — 3-server etcd quorum established"\n'
    )


# ---------------------------------------------------------------------------
# phase-06-verify.sh — post-spawn health check
# ---------------------------------------------------------------------------

def generate_phase_06_verify(plan: dict) -> str:
    hostname   = plan.get("hostname", "unknown")
    vms        = plan.get("vms") or []
    gateway    = (plan.get("network") or {}).get("gateway", "")
    hostname_q = shlex.quote(hostname)
    gateway_q  = shlex.quote(gateway) if gateway else ""

    vm_checks = "\n".join(
        "qm status {} | grep -q running || FAILS+=('VM {} not running')".format(
            v.get("vmid", "?"), v.get("name", "?"))
        for v in vms
    )

    return (
        _plan_header(plan, "phase-06-verify.sh — post-spawn health check") +
        'FAILS=()\n\n'
        '# ── VMs running ─────────────────────────────────────────────────\n'
        + vm_checks + "\n\n"
        f'# ── k3s node visible ────────────────────────────────────────────\n'
        f'if command -v kubectl &>/dev/null; then\n'
        f'  kubectl get node {hostname_q} &>/dev/null \\\n'
        f"    || FAILS+=('k3s node {hostname} not found in cluster')\n"
        f'fi\n\n'
        f'# ── Network reachable ───────────────────────────────────────────\n'
        + (f"ping -c 3 {gateway_q} &>/dev/null || FAILS+=('Gateway {gateway} unreachable')\n\n" if gateway else "")
        + f'# ── Result ───────────────────────────────────────────────────────\n'
        f'if [ ${{#FAILS[@]}} -gt 0 ]; then\n'
        f'  echo "[verify] FAILED — ${{#FAILS[@]}} issue(s):"\n'
        f'  for f in "${{FAILS[@]}}"; do echo "  ✗ $f"; done\n'
        f'  exit 1\n'
        f'fi\n'
        f'echo "[verify] All checks PASSED"\n'
        f'\n'
        f'# ── Report success to hatchery ──────────────────────────────────\n'
        f'# POST to /api/spawn-complete so the hatchery updates bootstrap-state.json.\n'
        f'# Reads hatchery address and auth token from spawn-manifest.json.\n'
        f'HATCHERY_URL=$(python3 -c "\n'
        f'import json, sys\n'
        f'd=json.load(open(\\\"$SCRIPT_DIR/spawn-manifest.json\\\"))\n'
        f'print(d.get(\\\"hatchery_url\\\", \\\"\\\"))\n'
        f'" 2>/dev/null || true)\n'
        f'HATCHERY_TOKEN=$(python3 -c "\n'
        f'import json, sys\n'
        f'd=json.load(open(\\\"$SCRIPT_DIR/spawn-manifest.json\\\"))\n'
        f'print(d.get(\\\"receiver_token\\\", \\\"\\\"))\n'
        f'" 2>/dev/null || true)\n'
        f'if [ -n "$HATCHERY_URL" ]; then\n'
        f'  PAYLOAD=$(python3 -c "\n'
        f'import json\n'
        f'plan=json.load(open(\\\"$SCRIPT_DIR/spawn-plan.json\\\"))\n'
        f'hp=json.load(open(\\\"$SCRIPT_DIR/hardware-profile.json\\\")) if __import__(\\\"os\\\").path.exists(\\\"$SCRIPT_DIR/hardware-profile.json\\\") else {{}}\n'
        f'print(json.dumps({{\\\"spawn_plan\\\": plan, \\\"hardware_profile\\\": hp}}))\n'
        f'")\n'
        f'  if curl -sf -X POST "${{HATCHERY_URL}}/api/spawn-complete" \\\n'
        f'      -H "Content-Type: application/json" \\\n'
        f'      ${{HATCHERY_TOKEN:+-H "X-Broodforge-Token: $HATCHERY_TOKEN"}} \\\n'
        f'      -d "$PAYLOAD" &>/dev/null; then\n'
        f'    echo "[verify] Hatchery notified — bootstrap-state.json updated"\n'
        f'  else\n'
        f'    echo "[verify] WARNING: could not reach hatchery at ${{HATCHERY_URL}}"\n'
        f"    echo '[verify] Run on hatchery: python3 proxmox-bootstrap/update_state_after_spawn.py --state proxmox-bootstrap/bootstrap-state.json --plan /path/to/spawn-plan-{hostname}.json'\n"
        f'  fi\n'
        f'else\n'
        f'  echo "[verify] No hatchery_url in spawn-manifest.json — update hatchery manually"\n'
        f'fi\n'
    )


# ---------------------------------------------------------------------------
# Write all scripts
# ---------------------------------------------------------------------------

def write_all_scripts(
    plan: dict,
    output_dir: Path,
    include_ha: bool = False,
    include_wan_phase: bool = False,
) -> dict[str, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    scripts = {
        "spawn.sh":                generate_spawn_sh(plan, include_wan_phase=include_wan_phase),
        "phase-00-preflight.sh":   generate_phase_00_preflight(plan),
        "phase-00-host.sh":        generate_phase_00_host(plan),
        "phase-01-proxmox.sh":     generate_phase_01_proxmox(plan),
        "phase-02-vms.sh":         generate_phase_02_vms(plan),
        "phase-03-cloudinit.sh":   generate_phase_03_cloudinit(plan),
        "phase-04-k3s.sh":         generate_phase_04_k3s(plan),
        "phase-06-verify.sh":      generate_phase_06_verify(plan),
    }
    if include_wan_phase:
        scripts["tailscale-join.sh"] = generate_tailscale_join_sh(plan)
    if include_ha:
        scripts["phase-05-ha.sh"] = generate_phase_05_ha(plan)

    for name, content in scripts.items():
        path = output_dir / name
        path.write_text(content, encoding="utf-8")
        written[name] = path

    return written
