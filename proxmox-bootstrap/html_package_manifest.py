#!/usr/bin/env python3
"""
html_package_manifest.py — Human-readable HTML manifests for package exports.

Architecture requirement (see ARCHITECTURE.md):
  Every machine-readable manifest (forge-manifest.json, spawn-manifest.json,
  phoenix-playbook.json) MUST have a corresponding human-readable HTML equivalent
  embedded in its package. This module generates those HTML equivalents.

Provides:
  build_forge_manifest_html(manifest) → str
  build_spawn_manifest_html(manifest, plan) → str
  build_phoenix_manifest_html(playbook) → str

All outputs are self-contained HTML files using broodforge's standard dark theme.
They include: what's inside the package, what each component does, key settings,
and what the operator must do.

Stdlib only.
"""

from datetime import datetime, timezone
from html import escape as _e
from typing import Optional


# ---------------------------------------------------------------------------
# Shared CSS (same dark theme as dashboard and setup guide)
# ---------------------------------------------------------------------------

_CSS = """\
  :root{--bg:#1a1d23;--bg2:#22262e;--bg3:#2a2f3a;--border:#3a3f4d;--text:#cdd6f4;
    --muted:#7f8498;--accent:#89b4fa;--green:#a6e3a1;--yellow:#f9e2af;
    --orange:#fab387;--red:#f38ba8;--code-bg:#181b21;--radius:6px}
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--text);font-family:'Segoe UI',system-ui,sans-serif;
    font-size:14px;line-height:1.6;padding:0}
  .topbar{background:#0e1117;border-bottom:1px solid var(--border);padding:10px 24px;
    display:flex;align-items:center;gap:16px;position:sticky;top:0;z-index:100}
  .topbar-title{color:var(--accent);font-size:1.1em;font-weight:700}
  .topbar-sub{color:var(--muted);font-size:.88em}
  .topbar-ts{color:var(--muted);font-size:.78em;margin-left:auto}
  .content{padding:20px 24px;max-width:1100px;margin:0 auto}
  h2{color:var(--accent);font-size:.95em;text-transform:uppercase;letter-spacing:.06em;
    margin:20px 0 8px;padding-bottom:4px;border-bottom:1px solid var(--border)}
  h3{color:var(--text);font-size:.95em;font-weight:600;margin:14px 0 6px}
  .section-wrap{background:var(--bg2);border:1px solid var(--border);
    border-radius:var(--radius);padding:14px 16px;margin-bottom:16px}
  .stat-row{display:flex;gap:14px;flex-wrap:wrap;margin:8px 0}
  .stat{background:var(--bg3);border:1px solid var(--border);border-radius:var(--radius);
    padding:8px 14px;min-width:100px}
  .stat-val{font-size:1.3em;font-weight:700;color:var(--accent)}
  .stat-label{font-size:.75em;color:var(--muted)}
  table{width:100%;border-collapse:collapse;font-size:.88em;margin:8px 0}
  th{background:var(--bg3);color:var(--muted);text-align:left;padding:6px 8px;
    font-size:.78em;text-transform:uppercase;letter-spacing:.05em;
    border-bottom:1px solid var(--border)}
  td{padding:5px 8px;border-bottom:1px solid var(--bg3);vertical-align:top}
  tr:last-child td{border-bottom:none}
  code{background:var(--code-bg);color:var(--green);padding:1px 5px;border-radius:3px;
    font-family:'Cascadia Code',Consolas,monospace;font-size:.86em}
  pre{background:var(--code-bg);border-left:3px solid var(--accent);
    padding:10px 14px;overflow-x:auto;border-radius:0 var(--radius) var(--radius) 0;
    font-family:'Cascadia Code',Consolas,monospace;font-size:.83em;margin:8px 0}
  details{border:1px solid var(--border);border-radius:var(--radius);margin:6px 0}
  details>summary{cursor:pointer;padding:8px 12px;background:var(--bg3);
    font-weight:600;list-style:none;border-radius:var(--radius);user-select:none}
  details[open]>summary{border-radius:var(--radius) var(--radius) 0 0}
  details>.det-body{padding:10px 14px}
  .tip{background:#1e2d3a;border-left:3px solid var(--accent);padding:8px 12px;
    border-radius:0 var(--radius) var(--radius) 0;margin:8px 0;font-size:.88em}
  .warn{background:#3a2e1a;border-left:3px solid var(--orange);padding:8px 12px;
    border-radius:0 var(--radius) var(--radius) 0;margin:8px 0;font-size:.88em}
  .danger{background:#3a1e1e;border-left:3px solid var(--red);padding:8px 12px;
    border-radius:0 var(--radius) var(--radius) 0;margin:8px 0;font-size:.88em}
  .kv{display:grid;grid-template-columns:180px 1fr;gap:3px 12px;
    margin:6px 0;font-size:.88em}
  .kv dt{font-weight:600;color:var(--muted);padding:3px 0;white-space:nowrap}
  .kv dd{margin:0;padding:3px 0;border-bottom:1px dotted var(--border)}
  .pkg-file{font-size:.82em;padding:2px 4px;margin:2px;display:inline-block;
    background:var(--bg3);border-radius:3px;font-family:monospace}
  .operator-task{background:var(--bg3);border:1px solid var(--orange);
    border-radius:var(--radius);padding:10px 14px;margin:6px 0}
  .operator-task::before{content:"📋 ";font-size:1.1em}
  @media print{.topbar{display:none}body{padding:12px}}
"""


def _page(title: str, cell_id: str, subtitle: str, body: str, gen_at: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="topbar">
  <span class="topbar-title">📦 Broodforge Package</span>
  <span class="topbar-sub">{_e(subtitle)}</span>
  <span class="topbar-ts">Generated: {_e(gen_at[:19])}</span>
</div>
<div class="content">
  {body}
  <p style="color:var(--muted);font-size:.75em;margin-top:20px;text-align:center">
    Broodforge Package Manifest · Cell: {_e(cell_id)} · Generated: {_e(gen_at[:19])}
  </p>
</div>
</body>
</html>"""


def _kv(pairs: list[tuple]) -> str:
    rows = "".join(
        f"<dt>{_e(str(k))}</dt><dd><code>{_e(str(v))}</code></dd>"
        for k, v in pairs if v is not None and v != ""
    )
    return f'<dl class="kv">{rows}</dl>'


def _table(headers: list[str], rows: list[list]) -> str:
    ths = "".join(f"<th>{_e(h)}</th>" for h in headers)
    trs = "".join(
        "<tr>" + "".join(f"<td>{_e(str(c))}</td>" for c in row) + "</tr>"
        for row in rows
    )
    return f"<table><tr>{ths}</tr>{trs}</table>"


# ---------------------------------------------------------------------------
# Forge package HTML manifest
# ---------------------------------------------------------------------------

def build_forge_manifest_html(
    manifest: dict,
    now_fn=None,
) -> str:
    """
    Build a human-readable HTML manifest for a forge package.

    Explains: what's inside, key settings, what each phase does,
    and what the operator must do.
    """
    gen_at = (now_fn() if now_fn else datetime.now(timezone.utc).isoformat())
    cell_id  = manifest.get("cell_id") or "unknown-cell"
    hi       = manifest.get("host_identity") or {}
    hostname = hi.get("hostname") or hi.get("fqdn") or "unknown"
    domain   = hi.get("domain") or hi.get("fqdn") or ""
    fqdn     = hi.get("fqdn") or ""
    nt       = manifest.get("network_topology") or {}
    mgmt_cidr = nt.get("management_cidr") or nt.get("cidr") or ""
    gateway   = nt.get("gateway") or ""
    vms      = manifest.get("vms") or []
    sm       = manifest.get("setup_mode") or "autonomous"

    # Storage
    sc = manifest.get("storage_config") or {}
    pool_name    = sc.get("zfs_pool_name") or sc.get("pool_name") or ""
    datastore    = sc.get("local_lvm") or sc.get("datastore") or ""

    # Backup
    bc = manifest.get("backup_config") or {}
    backup_configured = bool(bc) or bool(manifest.get("external_backup"))

    body = ""

    # Identity overview
    body += "<h2>Package Identity</h2>"
    body += '<div class="section-wrap">'
    body += _kv([
        ("Cell ID",          cell_id),
        ("Hostname",         hostname),
        ("FQDN",             fqdn),
        ("Domain",           domain),
        ("Management CIDR",  mgmt_cidr),
        ("Gateway",          gateway),
        ("ZFS pool",         pool_name),
        ("Datastore",        datastore),
        ("Setup mode",       sm),
        ("Generated",        gen_at[:19]),
    ])
    body += "</div>"

    # What's in this package
    body += "<h2>Package Contents</h2>"
    body += '<div class="section-wrap">'
    body += '<div class="tip">This package takes a bare Proxmox installation to a fully operational broodforge hatchery via 8 automated phases. Run: <code>bash forge.sh</code></div>'
    files = [
        ("forge-manifest.json", "Cell identity snapshot — auto-generated"),
        ("forge.sh",            "Orchestrated entry point — runs all 8 phases in order"),
        ("phase-00-discover.sh","Discover host hardware (CPU, RAM, disks, NICs)"),
        ("phase-01-plan.sh",    "Interactive planning — domain, IPs, ZFS topology"),
        ("phase-02-validate.sh","Validate hardware meets minimum requirements (blocks on RED)"),
        ("phase-03-host.sh",    "Configure Proxmox host — ZFS pool, networking, KeePass init, dnsmasq, Headscale, nag suppression"),
        ("phase-04-vms.sh",     "Provision VMs via OpenTofu"),
        ("phase-05-k3s.sh",     "Bootstrap k3s cluster (server role)"),
        ("phase-06-gitops.sh",  "Bootstrap Flux CD GitOps"),
        ("phase-07-intelligence.sh","Install broodforge assessment engine + documentation engine"),
        ("phase-08-verify.sh",  "Verify cluster health; commit forge state to Forgejo"),
        ("forge-workbook.html", "Interactive HTML workbook — track forge progress with checkboxes"),
        ("lib/checkpoint.sh",   "Checkpoint/resumption library (shared by all phase scripts)"),
        ("lib/forge-keepass-gate.sh","KeePass master password gate (phase-03 onwards)"),
        ("lib/pve-suppress-nag.sh","Remove Proxmox subscription popup (idempotent)"),
        ("proxmox-bootstrap/",  "All Python modules — planners, validators, assessment engine"),
        ("data-model/",         "JSON schemas for bootstrap state and service state"),
        ("doc-gen/",            "Documentation generation engine (runbooks, workbooks, reports)"),
    ]
    rows = [[f"<code>{_e(f)}</code>", _e(d)] for f, d in files]
    body += "<table><tr><th>File</th><th>Purpose</th></tr>" + \
            "".join(f"<tr><td>{r[0]}</td><td>{r[1]}</td></tr>" for r in rows) + "</table>"
    body += "</div>"

    # VM inventory
    if vms:
        body += "<h2>VM Inventory</h2>"
        body += '<div class="section-wrap">'
        vm_rows = []
        for vm in vms:
            vmid  = vm.get("vmid") or ""
            role  = vm.get("role") or ""
            ram   = vm.get("memory_mb") or vm.get("ram_mb") or ""
            cpu   = vm.get("cores") or vm.get("cpu") or ""
            ip    = vm.get("initial_ip") or vm.get("management_ip") or ""
            name  = vm.get("name") or vm.get("hostname") or ""
            vm_rows.append([name, str(vmid), role, f"{ram}MB" if ram else "", str(cpu), ip])
        body += _table(["Name", "VMID", "Role", "RAM", "vCPU", "IP"], vm_rows)
        body += f'<div class="stat-row"><div class="stat"><div class="stat-val">{len(vms)}</div><div class="stat-label">Total VMs</div></div></div>'
        body += "</div>"

    # Key settings
    body += "<h2>Key Settings</h2>"
    body += '<div class="section-wrap">'
    ssl = nt.get("ssl_provider") or "not configured"
    ddns = nt.get("ddns_provider") or "not configured"
    hs_url = nt.get("headscale_url") or ""
    body += _kv([
        ("SSL provider",    ssl),
        ("DDNS provider",   ddns),
        ("Headscale URL",   hs_url),
        ("Backup",          "Configured" if backup_configured else "NOT configured — set up before first backup"),
    ])
    body += "</div>"

    # What the operator must do
    body += "<h2>Operator Checklist</h2>"
    body += '<div class="section-wrap">'
    tasks = [
        "Install Proxmox VE on target hardware (community edition is fine)",
        "Copy this package to the Proxmox host",
        "Run: bash forge.sh (takes 20-40 minutes)",
        "At the KeePass gate (phase-03): set your master password — this is the only manual input required in autonomous mode",
        "After forge completes: verify the hatchery is accessible at " + (fqdn or "your configured FQDN"),
        "Configure router: forward port 8080 → hatchery LAN IP (for Headscale/WAN access)",
        "Configure DNS: add A record for hatchery FQDN → your WAN IP",
    ]
    if not backup_configured:
        tasks.insert(3, "⚠ Configure backup destinations before forge proceeds past phase-01 (required)")
    body += "".join(f'<div class="operator-task">{_e(t)}</div>' for t in tasks)
    body += "</div>"

    return _page(
        title=f"Forge Package — {cell_id}",
        cell_id=cell_id,
        subtitle=f"Forge Package · {cell_id} · {hostname}",
        body=body,
        gen_at=gen_at,
    )


# ---------------------------------------------------------------------------
# Spawn package HTML manifest
# ---------------------------------------------------------------------------

def build_spawn_manifest_html(
    manifest: dict,
    plan: Optional[dict] = None,
    now_fn=None,
) -> str:
    """
    Build a human-readable HTML manifest for a spawn package.

    manifest: spawn-manifest.json (hatchery reservation snapshot)
    plan:     spawn-plan.json (broodling-specific plan, optional)
    """
    gen_at  = (now_fn() if now_fn else datetime.now(timezone.utc).isoformat())
    cell_id = manifest.get("cell_id") or "unknown-cell"
    plan    = plan or {}

    # Support both current spawn plan format (hostname, disposition.*)
    # and legacy test format (target_hostname, top-level execution_mode/network_mode)
    disposition  = plan.get("disposition") or {}
    hostname     = plan.get("hostname") or plan.get("target_hostname") or "unknown"
    exec_mode    = disposition.get("execution_mode") or plan.get("execution_mode") or "autonomous"
    network_mode = disposition.get("network_mode") or plan.get("network_mode") or "lan"
    services     = disposition.get("services") or []
    excluded     = disposition.get("excluded") or []

    # Allocated resources — current plan uses vms[] list; legacy used vmid_block dict
    vms       = plan.get("vms") or []
    vmid_list = [str(v.get("vmid", "?")) for v in vms if v.get("vmid")]
    vmid_str  = ", ".join(vmid_list) if vmid_list else ""
    if not vmid_str:
        # Fallback: legacy vmid_block dict format
        vmid_block = plan.get("vmid_block") or {}
        if isinstance(vmid_block, dict):
            vm_start = vmid_block.get("start") or ""
            vm_end   = vmid_block.get("end") or ""
            vmid_str = f"{vm_start}–{vm_end}" if vm_start else ""
        elif isinstance(vmid_block, list):
            vmid_str = ", ".join(str(v) for v in vmid_block)
    ip_block     = plan.get("ip_block") or []
    zfs_topo     = (plan.get("storage") or {}).get("topology") or plan.get("zfs_topology") or ""

    # k3s — current plan uses k3s.role; legacy used top-level k3s_role
    k3s_mode     = (plan.get("k3s") or {}).get("role") or plan.get("k3s_role") or "worker"
    k3s_server   = (plan.get("k3s") or {}).get("server_url") or manifest.get("k3s_server_address") or ""
    prox_addr    = (plan.get("hatchery") or {}).get("proxmox_cluster_address") or manifest.get("proxmox_join_address") or ""

    body = ""

    # Identity overview
    body += "<h2>Package Identity</h2>"
    body += '<div class="section-wrap">'
    body += _kv([
        ("Cell ID",          cell_id),
        ("Target hostname",  hostname),
        ("Execution mode",   exec_mode),
        ("Network mode",     network_mode),
        ("VMID block",       vmid_str if vmid_str else "auto-assigned"),
        ("ZFS topology",     zfs_topo),
        ("k3s role",         k3s_mode),
        ("Proxmox join",     prox_addr),
        ("k3s server",       k3s_server),
        ("Generated",        gen_at[:19]),
    ])
    body += "</div>"

    # What's in this package
    body += "<h2>Package Contents</h2>"
    body += '<div class="section-wrap">'
    body += '<div class="tip">This package takes a bare Proxmox installation and joins it to the hatchery as a broodling. Run: <code>bash spawn.sh</code></div>'
    files = [
        ("spawn-manifest.json", "Hatchery reservation snapshot — all allocated VMIDs, IPs, hostnames"),
        ("spawn-plan.json",     "Broodling-specific plan — VMID block, IPs, ZFS topology, service disposition"),
        ("spawn.sh",            "Orchestrated entry point — runs all phases; prompts once for KeePass password"),
        ("phase-00-preflight.sh","Hardware pre-flight — verifies disk IDs, NIC layout, RAM vs plan (read-only)"),
        ("phase-00-host.sh",    "Host configuration — ZFS pool, network bridges, hostname, apt repos"),
        ("phase-01-proxmox.sh", "Join Proxmox cluster: pvecm add <hatchery>"),
        ("phase-02-vms.sh",     "Provision VMs via OpenTofu (uses tfvars from this package)"),
        ("phase-03-cloudinit.sh","Apply Cloud-Init snippets; start VMs; poll SSH readiness"),
        ("phase-04-k3s.sh",     "Join k3s cluster as worker (or server if 3rd control plane)"),
        ("phase-05-ha.sh",      "HA promotion (SQLite→etcd) — only present if this is the 3rd server node"),
        ("phase-06-verify.sh",  "Cluster health check; conflict re-validation"),
        ("spawn-workbook.html", "Interactive HTML workbook — track spawn progress"),
        ("opentofu/",           "Terraform/OpenTofu variables for this broodling's VM set"),
        ("cloud-init/",         "Per-VM Cloud-Init user-data and network-config snippets"),
        ("ansible/",            "Ansible inventory and group variables for k3s join"),
        ("lib/checkpoint.sh",   "Checkpoint/resumption library"),
        ("lib/keepass-gate.sh", "KeePass master password gate"),
    ]
    rows = [[f"<code>{_e(f)}</code>", _e(d)] for f, d in files]
    body += "<table><tr><th>File</th><th>Purpose</th></tr>" + \
            "".join(f"<tr><td>{r[0]}</td><td>{r[1]}</td></tr>" for r in rows) + "</table>"
    body += "</div>"

    # Service disposition
    body += "<h2>Service Disposition</h2>"
    body += '<div class="section-wrap">'
    if exec_mode == "interactive":
        body += '<div class="tip">Interactive mode: service selection happens on the broodling at runtime. The package includes all available service scripts.</div>'
    elif services:
        body += f'<div class="tip">{len(services)} services selected for autonomous deployment.</div>'
        svc_rows = [[_e(s)] for s in services]
        body += _table(["Selected Service"], svc_rows)
    else:
        body += '<p style="color:var(--muted)">No services selected (intelligence baseline only).</p>'

    if excluded:
        body += "<h3>Excluded (hardware fit)</h3>"
        body += _table(["Excluded Service", "Reason"],
                       [[_e(str(e.get("service", e))), _e(str(e.get("reason", "")))]
                        for e in excluded])
    body += "</div>"

    # Allocated resources
    if ip_block:
        body += "<h2>Allocated Resources</h2>"
        body += '<div class="section-wrap">'
        body += "<h3>IP Addresses</h3>"
        ip_rows = [[_e(str(ip))] for ip in ip_block[:20]]
        body += _table(["Allocated IP"], ip_rows)
        body += "</div>"

    # What the operator must do
    body += "<h2>Operator Checklist</h2>"
    body += '<div class="section-wrap">'
    tasks = [
        "Install Proxmox VE on target hardware (community edition)",
        f"{'Connect broodling to hatchery LAN' if network_mode == 'lan' else 'Ensure Headscale auth key is still valid (1h expiry) — regenerate spawn package if expired'}",
        "Copy this package to the Proxmox host",
        "Run: bash spawn.sh",
        "At the KeePass gate: enter master password — this is the only prompt in autonomous mode",
        "After spawn completes: verify broodling appears in Proxmox datacenter and k3s node list",
    ]
    if exec_mode == "interactive":
        tasks.insert(4, "At the service selection prompt: choose which services to deploy based on hardware fit")
    body += "".join(f'<div class="operator-task">{_e(t)}</div>' for t in tasks)
    body += "</div>"

    return _page(
        title=f"Spawn Package — {hostname} ({cell_id})",
        cell_id=cell_id,
        subtitle=f"Spawn Package · {hostname} · {cell_id}",
        body=body,
        gen_at=gen_at,
    )


# ---------------------------------------------------------------------------
# Phoenix package HTML manifest
# ---------------------------------------------------------------------------

def build_phoenix_manifest_html(
    playbook: dict,
    now_fn=None,
) -> str:
    """
    Build a human-readable HTML manifest for a phoenix package.

    playbook: phoenix-playbook.json dict.
    """
    gen_at  = (now_fn() if now_fn else datetime.now(timezone.utc).isoformat())
    cell_id = playbook.get("cell_id") or "unknown-cell"
    node    = playbook.get("target_node") or {}
    hn      = node.get("hostname") or "unknown"
    role    = node.get("role") or ""
    scope   = playbook.get("restoration_scope") or "full"
    waves   = playbook.get("waves") or []
    identity= playbook.get("identity") or {}
    lan_ip  = identity.get("lan_ip") or ""
    vmids   = identity.get("vmids") or []
    bridges = identity.get("bridge_names") or []
    pool    = identity.get("zfs_pool_name") or ""
    est_min = playbook.get("estimated_total_minutes") or 0

    body = ""

    # Identity overview
    body += "<h2>Package Identity</h2>"
    body += '<div class="section-wrap">'
    body += '<div class="danger">This package reconstitutes a failed node on new hardware. All existing data on the target host will be destroyed. Confirm this is the correct package before running.</div>'
    body += _kv([
        ("Cell ID",              cell_id),
        ("Node hostname",        hn),
        ("Node role",            role),
        ("Restoration scope",    scope),
        ("LAN IP",               lan_ip),
        ("VMIDs to restore",     ", ".join(str(v) for v in vmids)),
        ("Bridge names",         ", ".join(bridges)),
        ("ZFS pool",             pool),
        ("Estimated runtime",    f"{est_min} minutes"),
        ("Generated",            gen_at[:19]),
    ])
    body += "</div>"

    # What's in this package
    body += "<h2>Package Contents</h2>"
    body += '<div class="section-wrap">'
    body += f'<div class="tip">This package reconstitutes <code>{_e(hn)}</code> on new hardware via {len(waves)} restoration waves. Run: <code>bash run-all.sh</code></div>'
    files = [
        ("phoenix-playbook.json",  "Machine-readable playbook — full reconstruction plan"),
        ("run-all.sh",             "Orchestrated entry point — calls each wave script in order"),
        ("wave-0-network.sh",      "Wave 0: Reconstruct network topology (bridges, VLANs)"),
        ("wave-0.5-templates.sh",  "Wave 0.5: Rebuild VM templates from ISO (if needed)"),
        ("wave-1-storage.sh",      "Wave 1: Reconstruct ZFS pool"),
        ("wave-2-host.sh",         "Wave 2: Host configuration (hostname, repos, services)"),
        ("wave-3-vms.sh",          "Wave 3: Restore VMs from PBS backup (identity-preserving)"),
        ("wave-4-k3s.sh",          "Wave 4: Rejoin k3s cluster + Flux reconciliation"),
        ("lib/checkpoint.sh",      "Checkpoint library — resume from last completed step on failure"),
    ]
    rows = [[f"<code>{_e(f)}</code>", _e(d)] for f, d in files]
    body += "<table><tr><th>File</th><th>Purpose</th></tr>" + \
            "".join(f"<tr><td>{r[0]}</td><td>{r[1]}</td></tr>" for r in rows) + "</table>"
    body += "</div>"

    # Waves summary
    if waves:
        body += "<h2>Restoration Waves</h2>"
        body += '<div class="section-wrap">'
        wave_rows = []
        for wave in waves:
            wave_id = wave.get("wave") or ""
            wave_name = wave.get("name") or ""
            steps = wave.get("steps") or []
            step_count = len(steps)
            actions = ", ".join(s.get("action", "") for s in steps[:4])
            if len(steps) > 4:
                actions += f"… +{len(steps)-4} more"
            wave_rows.append([str(wave_id), wave_name, str(step_count), actions])
        body += _table(["Wave", "Name", "Steps", "Actions"], wave_rows)
        body += "</div>"

    # VM disposition
    if vmids:
        body += "<h2>VM Restoration</h2>"
        body += '<div class="section-wrap">'
        body += _kv([("VMIDs to restore", ", ".join(str(v) for v in vmids))])
        if scope == "partial":
            deferred = playbook.get("deferred_services") or []
            if deferred:
                body += f"<h3>Deferred Services (will not be restored in this run)</h3>"
                body += _table(["Service"], [[_e(s)] for s in deferred])
        body += "</div>"

    # What the operator must do
    body += "<h2>Operator Checklist</h2>"
    body += '<div class="section-wrap">'
    tasks = [
        f"Confirm this package is for node: {hn} (cell: {cell_id})",
        "Install Proxmox VE on the REPLACEMENT hardware",
        "Ensure PBS backup server is reachable and contains snapshots for the VMIDs above",
        "Copy this package to the replacement Proxmox host",
        "Run: bash run-all.sh",
        "Wave 0: verify network is up before proceeding (check output of ifreload -a)",
        "Wave 3: verify each VM started successfully and SSH is reachable",
        f"Estimated total time: {est_min} minutes",
        "After completion: run assessment engine on hatchery to confirm node is healthy",
    ]
    body += "".join(f'<div class="operator-task">{_e(t)}</div>' for t in tasks)
    body += "</div>"

    return _page(
        title=f"Phoenix Package — {hn} ({cell_id})",
        cell_id=cell_id,
        subtitle=f"Phoenix Package · {hn} · {cell_id} · {scope} restore",
        body=body,
        gen_at=gen_at,
    )
