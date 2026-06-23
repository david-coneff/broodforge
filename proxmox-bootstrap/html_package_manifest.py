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
  build_bootstrap_image_manifest_html(manifest, image_manifest) → str
  build_recovery_readiness_certificate_html(certificate) → str
  build_scoped_vault_plan_html(plan_dict) → str
  build_recovery_account_plan_html(plan) → str

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
                body += "<h3>Deferred Services (will not be restored in this run)</h3>"
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


# ---------------------------------------------------------------------------
# Bootstrap image staging bundle HTML manifest (Phase 1.H, AD-057)
# ---------------------------------------------------------------------------

def build_bootstrap_image_manifest_html(
    manifest: dict,
    image_manifest: dict,
    now_fn=None,
) -> str:
    """
    Build a human-readable HTML manifest for a bootstrap image staging bundle.

    manifest:       forge-manifest.json (cell identity snapshot)
    image_manifest: bootstrap-image-manifest.json content (see _image_builder.
                    build_image_manifest) — bundle contents + embedded forge
                    package hash.

    Explains: what the bundle is (and is NOT — a staging bundle, not a
    bootable ISO), what's inside, the embedded forge package's verification
    hash, and what the operator must do to turn it into bootable media.
    """
    gen_at = (now_fn() if now_fn else datetime.now(timezone.utc).isoformat())
    cell_id = manifest.get("cell_id") or image_manifest.get("cell_id") or "unknown-cell"
    hi = manifest.get("host_identity") or image_manifest.get("host_identity") or {}
    hostname = hi.get("hostname") or hi.get("fqdn") or "unknown"
    fqdn = hi.get("fqdn") or ""
    nt = manifest.get("network_topology") or image_manifest.get("network_topology") or {}
    mgmt_cidr = nt.get("management_cidr") or nt.get("cidr") or ""
    gateway = nt.get("gateway") or ""

    pkg = image_manifest.get("embedded_forge_package") or {}
    pkg_name = pkg.get("name") or ""
    pkg_sha = pkg.get("sha256") or ""
    pkg_size = pkg.get("size_bytes") or 0
    answer_sha = image_manifest.get("answer_toml_sha256") or ""
    unit_name = image_manifest.get("first_boot_unit") or ""

    body = ""

    # Identity overview
    body += "<h2>Bundle Identity</h2>"
    body += '<div class="section-wrap">'
    body += '<div class="warn">This is a <b>staging bundle</b>, not a bootable ISO. ' \
            'It contains everything cell-specific that an operator combines with the ' \
            'official Proxmox VE ISO via their own remastering process. See README.md ' \
            'inside the bundle for the exact steps.</div>'
    body += _kv([
        ("Cell ID",          cell_id),
        ("Target hostname",  hostname),
        ("FQDN",             fqdn),
        ("Management CIDR",  mgmt_cidr),
        ("Gateway",          gateway),
        ("First-boot unit",  unit_name),
        ("Generated",        gen_at[:19]),
    ])
    body += "</div>"

    # What's in this bundle
    body += "<h2>Bundle Contents</h2>"
    body += '<div class="section-wrap">'
    body += '<div class="tip">Extract the bundle to get an <code>iso-staging/</code> ' \
            'directory ready to overlay onto the official Proxmox VE ISO.</div>'
    files = [
        ("answer.toml",                       "Proxmox 8+ automated-installer answer file — derived from forge-manifest.json (network, hostname, disk layout, timezone)"),
        ("forge-package.tar.gz",              "Embedded forge package — same artifact FORGING.md Step 2 produces; runs automatically on first boot"),
        (f"first-boot/{unit_name}",           "Systemd oneshot unit — runs the embedded forge package's forge.sh on first boot"),
        ("first-boot/install-first-boot-hook.sh", "Installer script invoked by answer.toml's post-install hook — stages the forge package and enables the first-boot unit"),
        ("bootstrap-image-manifest.json",     "This bundle's machine-readable hash/contents manifest"),
        ("bootstrap-image-manifest.html",     "This document — human-readable twin (AD-051)"),
        ("README.md",                         "Remastering instructions — how to combine this bundle with the official Proxmox VE ISO"),
    ]
    rows = [[f"<code>{_e(f)}</code>", _e(d)] for f, d in files]
    body += "<table><tr><th>File</th><th>Purpose</th></tr>" + \
            "".join(f"<tr><td>{r[0]}</td><td>{r[1]}</td></tr>" for r in rows) + "</table>"
    body += "</div>"

    # Verification (AD-042/AD-051 supply-chain pattern)
    body += "<h2>Artifact Verification</h2>"
    body += '<div class="section-wrap">'
    body += '<div class="tip">Verify the embedded forge package before relying on this bundle — ' \
            'the same SHA-256 pattern used for forge/spawn/phoenix packages.</div>'
    body += _kv([
        ("Embedded package",   pkg_name),
        ("Package SHA-256",    pkg_sha),
        ("Package size",       f"{pkg_size:,} bytes" if pkg_size else ""),
        ("answer.toml SHA-256", answer_sha),
    ])
    body += f'<pre>sha256sum {_e(pkg_name)}\n# compare against: {_e(pkg_sha)}</pre>'
    body += "</div>"

    # Security note — single-use install passphrase
    body += "<h2>Security Notes</h2>"
    body += '<div class="section-wrap">'
    body += '<div class="danger">The <code>root-password</code> in <code>answer.toml</code> is a ' \
            '<b>freshly-generated, single-use discovery passphrase</b> (AD-039/AD-043 pattern) — ' \
            'NOT a permanent credential and NOT stored in KeePass. The embedded forge package ' \
            'replaces it with a KeePass-managed credential during phase-03. Note it down before ' \
            'burning this bundle to media; rotate or discard it once forging completes.</div>'
    body += '<p style="color:var(--muted);font-size:.88em">As with every broodforge package, this ' \
            'bundle never embeds permanent secret values — only KeePass references (and this one ' \
            'time-boxed install passphrase, which is not a permanent secret by design).</p>'
    body += "</div>"

    # What the operator must do
    body += "<h2>Operator Checklist</h2>"
    body += '<div class="section-wrap">'
    tasks = [
        "Extract this bundle to obtain the iso-staging/ directory",
        "Download the official Proxmox VE ISO for your target version (operator-performed — broodforge does not redistribute it)",
        "Use proxmox-auto-install-assistant (or the documented USB overlay method) to combine answer.toml from this bundle with that ISO",
        "Burn/write the resulting media and boot the target host from it",
        "Note down the answer.toml root-password (single-use discovery passphrase) before first boot — you cannot recover it from this bundle afterward",
        "After the automated install completes: install-first-boot-hook.sh stages the forge package and enables the first-boot unit",
        f"On first real boot, {unit_name} runs forge.sh unattended — turning bare metal into an operational hatchery",
        "At the KeePass gate (forge phase-03): set your master password — the only manual input required",
    ]
    body += "".join(f'<div class="operator-task">{_e(t)}</div>' for t in tasks)
    body += "</div>"

    return _page(
        title=f"Bootstrap Image — {cell_id}",
        cell_id=cell_id,
        subtitle=f"Bootstrap Image Staging Bundle · {cell_id} · {hostname}",
        body=body,
        gen_at=gen_at,
    )


# ---------------------------------------------------------------------------
# Recovery-Readiness Conformance Certificate HTML twin (Phase 1.I, AD-059/AD-051)
# ---------------------------------------------------------------------------

_SCORE_BADGE_CLASS = {
    "GREEN": "tip", "YELLOW": "warn", "ORANGE": "warn",
    "RED": "danger", "BLOCKED": "danger", "UNKNOWN": "warn",
}


def build_recovery_readiness_certificate_html(certificate: dict, now_fn=None) -> str:
    """
    Build a human-readable HTML twin for recovery-readiness-certificate.json
    (Phase 1.I, AD-059 — AD-051 manifest/HTML-twin pattern).

    certificate: dict produced by
                 _recovery_readiness_certificate.build_recovery_readiness_certificate

    Explains: what this certificate is (a read-only composition of existing
    evidence, not a new trust apparatus), the manifest/graph hashes and how to
    independently verify them (replay-snapshot.py), the real readiness signal
    (with the AD-059 correction note — see _recovery_readiness_certificate's
    module docstring), the drift summary, and the latest reconstruction drill.
    """
    gen_at = (now_fn() if now_fn else certificate.get("generated_at")
              or datetime.now(timezone.utc).isoformat())
    cell_id = certificate.get("cell_id") or "unknown-cell"
    cert_id = certificate.get("certificate_id") or ""

    readiness = certificate.get("readiness") or {}
    drift = certificate.get("drift") or {}
    drill = certificate.get("latest_drill") or {}

    overall = readiness.get("overall_score") or "UNKNOWN"
    badge_class = _SCORE_BADGE_CLASS.get(overall, "warn")

    body = ""

    # Identity / hashes
    body += "<h2>Certificate Identity</h2>"
    body += '<div class="section-wrap">'
    body += '<div class="tip">This certificate is a <b>read-only composition</b> of evidence ' \
            'broodforge already produces — readiness scoring, drift detection, dependency-graph ' \
            'hashing, and reconstruction drills. It introduces no new scoring system, signing ' \
            'scheme, or trust apparatus (explicitly out of scope per AD-059). Trust anchors ' \
            'remain git + KeePass + restic, exactly as AD-040 scopes them.</div>'
    body += _kv([
        ("Certificate ID", cert_id),
        ("Cell ID",        cell_id),
        ("Generated",      gen_at[:19]),
        ("Schema version", certificate.get("schema_version")),
        ("Manifest hash (SHA-256)", certificate.get("manifest_hash")),
        ("Graph hash (SHA-256)",    certificate.get("graph_hash")),
    ])
    body += '<p style="color:var(--muted);font-size:.88em">Both hashes are SHA-256 over the ' \
            'canonical (sorted-keys JSON) serialization of the manifest and dependency graph ' \
            'respectively — independently recomputable at any later time via ' \
            '<code>replay-snapshot.py</code>, which re-derives both and asserts they match what ' \
            'was recorded in <code>history/index.json</code> at snapshot time.</p>'
    body += "</div>"

    # Readiness signal (with AD-059 correction note)
    body += "<h2>Recovery Readiness Signal</h2>"
    body += '<div class="section-wrap">'
    body += f'<div class="{badge_class}"><b>Overall score: {_e(overall)}</b> — ' \
            f'{_e(readiness.get("overall_score_reason") or "no reason recorded")}</div>'
    body += _kv([
        ("Components scored",        readiness.get("component_count")),
        ("Single points of failure", readiness.get("single_points_of_failure_count")),
        ("Recovery blockers",        readiness.get("recovery_blockers_count")),
        ("Registry gaps",            readiness.get("registry_gaps_count")),
    ])
    counts = readiness.get("component_score_counts") or {}
    if counts:
        rows = [[score, str(n)] for score, n in sorted(counts.items())]
        body += _table(["Component score", "Count"], rows)
    body += '<div class="warn"><b>Note on terminology:</b> ' + _e(readiness.get("note") or "") + '</div>'
    body += "</div>"

    # Drift summary
    body += "<h2>Drift Summary</h2>"
    body += '<div class="section-wrap">'
    if drift.get("available"):
        body += _kv([
            ("From snapshot",   drift.get("from_snapshot")),
            ("To snapshot",     drift.get("to_snapshot")),
            ("Generated",       (drift.get("generated_at") or "")[:19]),
            ("Drift severity",  drift.get("drift_severity")),
            ("Diff count",      drift.get("diff_count")),
        ])
        sev_counts = drift.get("diff_severity_counts") or {}
        if sev_counts:
            rows = [[sev, str(n)] for sev, n in sorted(sev_counts.items())]
            body += _table(["Diff severity", "Count"], rows)
        body += '<p style="color:var(--muted);font-size:.88em">This is a summary — see the full ' \
                'drift record (doc-gen/drift.py output) for the field-level diff list.</p>'
    else:
        body += '<div class="tip">No drift summary available — fewer than two snapshots exist ' \
                'in the history store, or no prior snapshot was found to compare against.</div>'
    body += "</div>"

    # Latest reconstruction drill
    body += "<h2>Latest Reconstruction Drill</h2>"
    body += '<div class="section-wrap">'
    if drill.get("available"):
        body += _kv([
            ("Drill ID",          drill.get("drill_id")),
            ("Outcome",           drill.get("outcome")),
            ("Completed",         (drill.get("completed_at") or "")[:19]),
            ("Waves completed",   f"{drill.get('completed_waves')} / {drill.get('total_waves')}"),
            ("Timing accuracy",   f"{drill.get('accuracy_pct')}%" if drill.get("accuracy_pct") is not None else "n/a"),
            ("Gaps found",        drill.get("gaps_found_count")),
            ("Gaps remediated",   drill.get("gaps_remediated_count")),
        ])
        body += '<div class="operator-task">Reconstruction drills are operator-run exercises — ' \
                'see "Human Intervention Boundary" documentation for which steps in this ' \
                'pipeline are autonomous vs. require an operator to act.</div>'
    else:
        body += '<div class="warn">No reconstruction drill has been recorded for this cell yet. ' \
                'A certificate composed without drill evidence documents readiness scoring and ' \
                'drift posture, but not a demonstrated reconstruction.</div>'
    body += "</div>"

    return _page(
        title=f"Recovery-Readiness Certificate — {cell_id}",
        cell_id=cell_id,
        subtitle=f"Recovery-Readiness Conformance Certificate · {cell_id} · {overall}",
        body=body,
        gen_at=gen_at,
    )


# ---------------------------------------------------------------------------
# Scoped vault plan HTML (Phase 1.K, AD-061)
# ---------------------------------------------------------------------------

def build_scoped_vault_plan_html(plan_dict: dict, now_fn=None) -> str:
    """
    Build a human-readable HTML twin for scoped-vault-plan-{role}-{timestamp}.json
    (Phase 1.K, AD-061 — AD-051 manifest/HTML-twin pattern).

    plan_dict: dict produced by _vault_hierarchy.plan_to_dict(plan, include_passphrase=False)
               — the passphrase is NEVER embedded in this artifact (shown-once,
               operator-recorded-only, mirroring _image_builder.py's install
               passphrase handling).

    Explains: what a derived vault is and is not (a smaller .kdbx with its own
    passphrase, NOT a broker/ACL system — see AD-061), which canonical entries
    are in scope and why (the role's glob-pattern scope), the vault-of-vaults
    recordkeeping path where the (never-embedded) passphrase belongs, and the
    authorization-model / revocation-is-rotate-and-reissue design statements
    AD-061 frames as properties documented by construction, not enforced by
    new machinery.
    """
    gen_at = (now_fn() if now_fn else plan_dict.get("generated_at")
              or datetime.now(timezone.utc).isoformat())
    role = plan_dict.get("role") or "unknown-role"
    tier = plan_dict.get("tier") or "unknown-tier"

    body = ""

    body += "<h2>Derived Vault Identity</h2>"
    body += '<div class="section-wrap">'
    body += '<div class="tip">A <b>derived vault</b> is a smaller, independent .kdbx file ' \
            'containing only an in-scope subset of the canonical vault\'s secrets, with its ' \
            'own freshly-generated passphrase — "more vaults derived from the one vault," ' \
            'not a broker or per-user ACL layer bolted onto KeePass (which would require a ' \
            'network-dependent identity service broodforge deliberately avoids — AD-061, ' \
            'AD-042). broodforge does not open or write live .kdbx files: this plan is data ' \
            'plus the keepassxc-cli command sequence an operator runs to build it.</div>'
    body += _kv([
        ("Role",              role),
        ("Tier",              tier),
        ("Description",       plan_dict.get("description")),
        ("Generated",         (gen_at or "")[:19]),
        ("Schema version",    plan_dict.get("schema_version")),
        ("Derived vault path", plan_dict.get("db_path")),
        ("Parent vault path", plan_dict.get("parent_db_path")),
        ("Holders",           ", ".join(plan_dict.get("holders") or []) or "(none declared)"),
    ])
    body += "</div>"

    body += "<h2>Scope Match</h2>"
    body += '<div class="section-wrap">'
    body += _kv([
        ("Canonical entries considered", plan_dict.get("total_registry_count")),
        ("In-scope entries",             plan_dict.get("entry_count")),
        ("Excluded by scope/excludes",   plan_dict.get("excluded_count")),
    ])
    entries = plan_dict.get("entries") or []
    if entries:
        rows = [[e.get("id"), e.get("keepass_path"), e.get("secret_type"), e.get("description")]
                for e in entries]
        body += _table(["ID", "KeePass path", "Type", "Description"], rows)
    body += "</div>"

    body += "<h2>Vault-of-Vaults Recordkeeping</h2>"
    body += '<div class="section-wrap">'
    body += '<div class="warn"><b>The generated passphrase is shown ONCE, at plan-generation ' \
            'time, and is never written to this artifact or to disk by broodforge.</b> ' \
            'Record it in the <i>parent</i> (next tier up — ultimately the canonical god-mode) ' \
            'vault at the path below, generalising the AD-044 per-backup unique-secret ' \
            'bookkeeping convention (<code>Backup/{layer}/{component}/{timestamp}/repo-password</code> ' \
            '→ <code>Vaults/{role}/{timestamp}/passphrase</code>). This is what makes it a ' \
            '"vault of vaults": a higher-tier holder can always recover any scoped vault\'s ' \
            'passphrase from their own vault.</div>'
    body += _kv([
        ("Parent-vault record path", plan_dict.get("parent_record_path")),
        ("Passphrase source",        plan_dict.get("passphrase_source")),
    ])
    body += "</div>"

    body += "<h2>Authorization Model (documented by construction)</h2>"
    body += '<div class="section-wrap">'
    body += '<div class="tip">Only someone who can already read <code>secret-registry.yaml</code> ' \
            'and open the canonical vault in full could produce this plan — the same trust ' \
            'boundary as running <code>forge-planner.py</code>/<code>spawn-planner.py</code> today. ' \
            '<b>"You can only derive a scope you can already see in its entirety"</b> is true by ' \
            'construction; AD-061 deliberately does not introduce a separate permission-check ' \
            'system, because there is nothing left to check.</div>'
    body += "</div>"

    body += "<h2>Revocation = Rotate + Reissue (an honest non-guarantee)</h2>"
    body += '<div class="section-wrap">'
    body += '<div class="warn">A derived vault has no live link back to the canonical vault and ' \
            '<b>cannot be remotely revoked.</b> A lost, stale, or compromised scoped vault is ' \
            'neutralized by rotating every secret it contains (per each entry\'s ' \
            '<code>rotation_schedule</code>, generalising AD-044) and reissuing a fresh ' \
            'derivative with a fresh passphrase — not by an in-database access-list edit. ' \
            'Static derived vaults cannot support instant kick-out; that is a property of the ' \
            'offline-first model, not a flaw specific to this design — and arguably a ' \
            '<i>stronger</i> property than a layered ACL: a derived vault literally cannot leak ' \
            'ciphertext it never received.</div>'
    body += "</div>"

    body += "<h2>User-Provisioning Templates</h2>"
    body += '<div class="section-wrap">'
    body += '<div class="operator-task">VM-level accounts: an additive Cloud-Init account block ' \
            f'(<code>{_e(role)}</code>, tier <code>{_e(tier)}</code>) referencing this scoped ' \
            'vault for SSH-key lookup — generated alongside the existing <code>initial_user</code> ' \
            'account in <code>spawn_iac_generator.py::generate_cloudinit_user_data()</code>, not ' \
            'as a parallel system. Proxmox-level accounts: templated ' \
            '<code>pveum user add</code>/<code>pveum aclmod</code>/<code>pveum user token add</code> ' \
            'command sequences for an operator to run — broodforge has no live-Proxmox-API-' \
            'mutation code path, and does not add one here.</div>'
    body += "</div>"

    return _page(
        title=f"Derived Vault Plan — {role}",
        cell_id=role,
        subtitle=f"Scoped Vault Plan · role: {role} · tier: {tier}",
        body=body,
        gen_at=gen_at,
    )


# ---------------------------------------------------------------------------
# Recovery account provisioning plan HTML twin (Phase 1.J, AD-060)
# ---------------------------------------------------------------------------

def build_recovery_account_plan_html(plan: dict, now_fn=None) -> str:
    """
    Build a human-readable HTML twin for a recovery-account-provisioning-plan
    (Phase 1.J, AD-060 — AD-051 manifest/HTML-twin pattern, mirrors
    build_scoped_vault_plan_html).

    plan: dict produced by _recovery_accounts.build_recovery_account_plan().

    Explains: what a constrained, forced-command recovery account is and why
    its blast radius is bounded by construction (the `authorized_keys`
    restricted-command line and its standard OpenSSH restriction flags), the
    fixed read-only/bounded diagnostic menu and its structural command-
    injection-safety invariant, and — critically — the break-glass root
    pointer table that displays ONLY KeePass paths (never values), annotated
    AD-060(b)/AD-042 human-unlock-gated. broodforge generates these strings;
    it never installs, runs, or connects with them — see _recovery_accounts.py.
    """
    gen_at = (now_fn() if now_fn else plan.get("generated_at")
              or datetime.now(timezone.utc).isoformat())
    cell_id = plan.get("cell_id") or "unknown-cell"
    node = plan.get("node_hostname") or "unknown-node"
    account = plan.get("account") or {}
    menu = plan.get("menu_script") or {}

    body = ""
    body += "<h2>Constrained Recovery Account</h2>"
    body += '<div class="section-wrap">'
    body += '<div class="tip">A dedicated, narrowly-scoped account per hypervisor, ' \
            'forced through a fixed read-only/bounded diagnostic menu via ' \
            '<code>command=</code> in <code>authorized_keys</code> — never an arbitrary ' \
            'shell. Because its blast radius is bounded <b>by construction</b>, AD-060 ' \
            'names this as the one piece of the recovery surface safe to query ' \
            'autonomously. broodforge generates these strings; it does not install, run, ' \
            'or connect with them — see README/phase-03 for the provisioning step.</div>'
    body += _kv([
        ("Cell",              cell_id),
        ("Node",              node),
        ("Generated",         (gen_at or "")[:19]),
        ("Account name",      account.get("name")),
        ("Login shell",       account.get("shell_restriction")),
        ("Menu script path",  account.get("menu_script_path")),
        ("authorized_keys restrictions", ", ".join(account.get("authorized_keys_restrictions") or [])),
    ])
    body += "</div>"

    body += "<h2>authorized_keys Restricted-Command Line</h2>"
    body += '<div class="section-wrap">'
    body += '<div class="warn">Install this single line into the account\'s ' \
            '<code>~/.ssh/authorized_keys</code>. The <code>command=</code> clause forces ' \
            'every session through the fixed-menu script regardless of what the client ' \
            'requests; the remaining flags disable port/X11/agent forwarding and pty ' \
            'allocation — there is no path back to an interactive shell.</div>'
    body += (f'<pre style="white-space:pre-wrap;word-break:break-all">'
             f'{_e(account.get("authorized_keys_line") or "")}</pre>')
    body += "</div>"

    body += "<h2>Fixed Diagnostic Menu</h2>"
    body += '<div class="section-wrap">'
    body += _kv([("VMID validation pattern", menu.get("vmid_validation_pattern"))])
    rows = [[c] for c in (menu.get("menu_commands") or [])]
    if rows:
        body += _table(["Menu command"], rows)
    body += '<div class="tip">The script never evaluates client input as shell — see its ' \
            'STRUCTURAL SAFETY INVARIANT header comment in the generated script. ' \
            'Numeric-only vmid validation is the entire guarantee against ' \
            'command-injection via vmstart/vmstop.</div>'
    body += "</div>"

    bg = plan.get("break_glass_pointers") or []
    body += "<h2>Break-Glass Root — Pointer Only (never read by broodforge)</h2>"
    body += '<div class="section-wrap">'
    if bg:
        rows = [[p.get("id"), p.get("keepass_path"), p.get("description")] for p in bg]
        body += _table(["ID", "KeePass path (lookup only)", "Description"], rows)
    body += '<div class="warn"><b>broodforge never reads these entries\' VALUES, here or ' \
            'anywhere else.</b> They are human-unlock-gated break-glass root (AD-042 gate, ' \
            'AD-060(b) annotation in secret-registry.yaml) — this table exists only so the ' \
            'operator knows where to look in KeePass. They open it and type the password ' \
            'themselves.</div>'
    body += "</div>"

    constraint = plan.get("constraint") or {}
    body += "<h2>AD-060 Constraint</h2>"
    body += '<div class="section-wrap">'
    body += f'<div class="tip">{_e(constraint.get("statement") or "")}</div>'
    body += "</div>"

    return _page(
        title=f"Recovery Account Plan — {node}",
        cell_id=cell_id,
        subtitle=f"Constrained recovery account · generated {((gen_at or '')[:19])} UTC",
        body=body,
        gen_at=gen_at,
    )
