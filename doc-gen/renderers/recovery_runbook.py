#!/usr/bin/env python3
"""
recovery_runbook.py — Recovery runbook ODT renderer.

Generates a structured recovery runbook with:
- Pre-Recovery Checklist
- One section per restore wave with pre-populated commands
- Validation checkpoints per component
- Gap/blocker callouts inline
- Appendix with full dependency graph and readiness gaps
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from runbook import RunbookBuilder
from timestamps import format_doc_timestamp_from_iso

SCORE_SYMBOLS = {
    "GREEN":   "✓ GREEN",
    "YELLOW":  "⚠ YELLOW",
    "ORANGE":  "⚠ ORANGE",
    "RED":     "✗ RED",
    "BLOCKED": "⛔ BLOCKED",
    "UNKNOWN": "? UNKNOWN",
}


def _get(manifest: dict, path: str, default=None):
    parts = path.split(".")
    obj = manifest
    for p in parts:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(p, default)
    return obj


def _fmt_list(items, template, empty="(none)"):
    if not items:
        return empty
    lines = []
    for item in items:
        try:
            keys = {k: (str(v) if v is not None else "N/A") for k, v in item.items()}
            lines.append(template.format(**keys))
        except Exception:
            lines.append(str(item))
    return "\n".join(lines)


def _resolve_vm_ip(vmid, manifest: dict) -> str:
    """Return IP for a VM from the DNS registry, or '[VM_IP]' if not found."""
    if vmid is None:
        return "[VM_IP]"
    dns_reg = manifest.get("dns_registry") or []
    for entry in dns_reg:
        try:
            if int(entry.get("vmid", -1)) == int(vmid):
                return entry.get("ip", "[VM_IP]")
        except (TypeError, ValueError):
            pass
    return "[VM_IP]"


def _get_contract(vm_name: str, manifest: dict) -> dict | None:
    """Return the service contract for the given VM name, or None."""
    for c in (manifest.get("service_contracts") or []):
        if c.get("vm") == vm_name:
            return c
    return None


def _health_check_cmds(iface: dict, vm_ip: str) -> list[str]:
    """
    Generate executable health-check commands from a provided_interface entry.

    Returns a list of command strings (empty if no meaningful check can be derived).
    SSH interfaces are skipped — SSH reachability is validated in the standard block.
    """
    protocol     = (iface.get("protocol") or "").lower()
    port         = iface.get("port")
    health_check = iface.get("health_check")
    url_pattern  = iface.get("url_pattern")
    host         = vm_ip if vm_ip != "[VM_IP]" else "HOST"

    if protocol == "ssh":
        return []   # covered by standard validation block

    if protocol == "postgresql":
        return [
            f"pg_isready -h {host} -p {port or 5432}",
            "# Expected: accepting connections",
        ]

    if protocol in ("smtp", "smtps"):
        return [
            f"nc -z -w 5 {host} {port or 25}",
            "# Expected: connection established (exit 0)",
        ]

    # HTTP/HTTPS — parse "GET /path" health_check string
    if health_check and health_check.upper().startswith("GET "):
        path = health_check[4:].strip()
        if url_pattern:
            url = url_pattern.rstrip("/") + path
        else:
            scheme = "https" if protocol == "https" else "http"
            url = f"{scheme}://{host}:{port}{path}"
        return [
            f"curl -sf --max-time 10 '{url}'",
            "# Expected: HTTP 2xx (exit 0)",
        ]

    # Generic port connectivity
    if port and vm_ip != "[VM_IP]":
        return [
            f"nc -z -w 5 {vm_ip} {port}",
            f"# Expected: {protocol}:{port} reachable (exit 0)",
        ]

    return []


def _service_restart_cmds(contract: dict, vm_ip: str) -> list[str]:
    """
    Generate service restart and status commands for a declared service.
    Commands assume Ubuntu VM with systemd; issued via SSH from the operator machine.
    """
    svc = contract.get("service", "unknown")
    if vm_ip == "[VM_IP]":
        prefix = f"ssh ubuntu@[VM_IP_{svc.upper().replace('-','_')}]"
    else:
        prefix = f"ssh ubuntu@{vm_ip}"
    return [
        f"# Restart and verify service: {svc}",
        f"{prefix} 'sudo systemctl restart {svc}'",
        f"{prefix} 'sudo systemctl status --no-pager {svc}'",
        "# Expected: Active: active (running)",
    ]


def _restore_cmd(node, manifest: dict) -> list[str]:
    """Generate restore commands for a given node based on its type and metadata."""
    cmds = []
    meta = node.metadata

    if node.type == "host":
        hostname = meta.get("hostname", "pve-host")
        pve_ver  = meta.get("proxmox_version", "unknown")
        cmds = [
            f"# Restore Proxmox host: {hostname}",
            f"# Target version: Proxmox VE {pve_ver}",
            "# 1. Boot from Proxmox ISO",
            "# 2. Install to same disk layout",
            "# 3. Restore ZFS pool from backup",
            "# 4. Restore /etc from backup or reconfigure",
            f"# 5. Verify: ssh root@{hostname}",
        ]

    elif node.type == "storage":
        pool_name = meta.get("pool_name") or meta.get("storage_name", "rpool")
        topology  = meta.get("topology", "mirror")
        devices   = meta.get("devices", [])
        cmds = [
            f"# Restore ZFS pool: {pool_name}",
            f"# Topology: {topology}  Devices: {', '.join(devices) or '(check lsblk)'}",
            f"zpool import {pool_name}",
            f"# Or if pool needs recreation:",
            f"# zpool create {pool_name} {topology} {' '.join(devices)}",
            f"zpool status {pool_name}",
            "# Expected: pool state ONLINE",
        ]

    elif node.type in ("vm", "container"):
        vmid  = meta.get("vmid") or meta.get("ctid", "ID")
        name  = meta.get("name", node.id)
        cmd   = "qmrestore" if node.type == "vm" else "pct restore"
        cmds = [
            f"# Restore {node.type}: {name} (ID {vmid})",
            f"# Find backup: ls /path/to/backups/ | grep {vmid}",
            f"{cmd} /path/to/backup/{vmid}-latest.vma.zst {vmid} --storage local-zfs",
            f"qm start {vmid}" if node.type == "vm" else f"pct start {vmid}",
            f"# Verify: qm status {vmid}" if node.type == "vm" else f"# Verify: pct status {vmid}",
        ]

    elif node.type == "network":
        bname = meta.get("bridge_name", node.id)
        addrs = meta.get("addresses", [])
        cmds = [
            f"# Verify bridge: {bname}",
            f"ip link show {bname}",
            f"ip addr show {bname}",
            f"# Expected address: {', '.join(addrs) or '(check /etc/network/interfaces)'}",
        ]

    else:
        cmds = [f"# Restore: {node.label}", "# No automatic command available for this component type"]

    return cmds


def build_recovery_runbook(
    manifest: dict,
    graph,
    readiness,
    generation_meta: dict,
) -> bytes:
    node_map = graph.node_map()
    hostname = _get(manifest, "host.hostname") or "unknown"
    pve_ver  = _get(manifest, "host.proxmox_version") or "unknown"
    collected = manifest.get("collected_at", "unknown")
    _gen_iso  = generation_meta.get("generated_at", "")
    generated = format_doc_timestamp_from_iso(_gen_iso) if _gen_iso else generation_meta.get("generated_at_display", "unknown")
    gateway   = _get(manifest, "network.default_gateway") or "unknown"
    dns_list  = ", ".join(_get(manifest, "network.dns_servers") or []) or "unknown"

    rb = RunbookBuilder()

    # ------------------------------------------------------------------
    # Cover
    # ------------------------------------------------------------------
    rb.h1("Recovery Runbook")
    rb.body(f"Host: {hostname}  |  Proxmox {pve_ver}  |  Assessment: {collected}")
    rb.body(f"Generated: {generated}")
    rb.body(
        f"Overall Readiness: {SCORE_SYMBOLS.get(readiness.overall_score, '?')}  "
        f"— {readiness.overall_score_reason}"
    )
    rb.spacer()
    rb.body(
        "This runbook is generated from observed infrastructure state. "
        "Commands are pre-populated from the assessment. "
        "Fields marked [HUMAN] require operator input at recovery time."
    )
    rb.body("Methodology: Observe → Decide → Act → Record → Validate")
    rb.spacer()

    total_waves = len(graph.restore_waves)
    total_mins  = sum(w.estimated_minutes or 0 for w in graph.restore_waves)
    rb.body(f"Restore sequence: {total_waves} wave(s), estimated {total_mins} minutes total.")
    rb.spacer()

    # ------------------------------------------------------------------
    # Readiness summary callouts
    # ------------------------------------------------------------------
    red_comps = [c for c in readiness.components if c.score == "RED"]
    blocked   = [c for c in readiness.components if c.score == "BLOCKED"]
    if red_comps or blocked:
        rb.h2("⚠ Pre-Recovery Warnings")
        for c in red_comps:
            node = node_map.get(c.component_id)
            rb.warning(f"RED: {node.label if node else c.component_id} — {c.score_reason}")
        for c in blocked:
            node = node_map.get(c.component_id)
            blocker_node = node_map.get(c.blocked_by or "")
            rb.warning(
                f"BLOCKED: {node.label if node else c.component_id} "
                f"— blocked by {blocker_node.label if blocker_node else c.blocked_by}"
            )
        rb.spacer()

    # ------------------------------------------------------------------
    # Pre-Recovery Checklist
    # ------------------------------------------------------------------
    rb.h1("Pre-Recovery Checklist")
    rb.body("Complete all items before beginning restore operations.")
    rb.spacer()

    # ── Step 0: Obtain bootstrap state ─────────────────────────────────
    rb.h2("Step 0 — Obtain Bootstrap State")
    rb.body(
        "Bootstrap state (bootstrap-state.json, Cloud-Init snippets, registries) "
        "is required before any VM can be provisioned. Retrieve it now, before "
        "touching the Proxmox host."
    )
    rb.spacer()

    ext_backup = manifest.get("external_backup") or {}
    provider = ext_backup.get("provider")

    if provider == "github":
        gh = ext_backup.get("github") or {}
        repos = gh.get("repos") or {}
        bootstrap_url = repos.get("bootstrap") or repos.get("infrastructure")
        deploy_key_ref = gh.get("deploy_key_reference") or "[HUMAN: deploy key ID]"
        if bootstrap_url:
            rb.field("Bootstrap repo", bootstrap_url, "AUTO", "")
            rb.field("Deploy key", deploy_key_ref, "AUTO", "KeePass secret reference")
            rb.code(f"# On recovery machine — requires SSH key for {deploy_key_ref}")
            rb.code(f"git clone {bootstrap_url} proxmox-bootstrap")
            rb.code(f"cd proxmox-bootstrap")
        else:
            rb.field("Bootstrap repo", "[HUMAN: GitHub URL not recorded]", "HUMAN",
                     "Check GitHub account for bootstrap repo")
        rb.checkbox("Bootstrap repo cloned successfully")
        rb.checkbox("bootstrap-state.json present and readable")

    elif provider == "encrypted-archive":
        arch = ext_backup.get("encrypted_archive") or {}
        dest = arch.get("destination") or "[HUMAN: archive destination not recorded]"
        dest_type = arch.get("destination_type") or "unknown"
        passphrase_ref = arch.get("passphrase_reference") or "[HUMAN: passphrase secret ID]"
        retention = arch.get("retention_count")

        rb.field("Archive destination", dest, "AUTO", "")
        rb.field("Passphrase", passphrase_ref, "AUTO", "KeePass secret reference")
        rb.body(
            f"Archives are named: {{cell_id}}_{{YYYY-MM-DD_HH_MM_SS}}_{{hash}}.tar.gz.gpg  "
            f"(most recent = newest timestamp). "
            + (f"Up to {retention} archives are retained." if retention else "")
        )
        rb.spacer()

        if dest_type == "rclone":
            rb.code(f"# List available archives:")
            rb.code(f"rclone ls {dest}/")
            rb.code(f"# Download the most recent archive:")
            rb.code(f"rclone copy {dest}/<latest-archive>.tar.gz.gpg .")
        elif dest_type == "scp":
            rb.code(f"# Download the most recent archive:")
            rb.code(f"scp '{dest}/<latest-archive>.tar.gz.gpg' .")
        else:
            rb.field("Archive location", dest, "AUTO", "")
            rb.body("Copy the most recent archive from the declared destination.")

        rb.code("# Decrypt (passphrase from KeePass at path: " + passphrase_ref + "):")
        rb.code("gpg --decrypt <archive>.tar.gz.gpg > archive.tar.gz")
        rb.code("tar xzf archive.tar.gz")
        rb.checkbox("Archive downloaded and decrypted successfully")
        rb.checkbox("bootstrap-state.json present and readable")

    else:
        # No external backup configured
        rb.field("External backup", "NOT CONFIGURED", "UNRESOLVED",
                 "No external backup was set up for this cell. "
                 "bootstrap-state.json must be obtained from another source.")
        rb.body(
            "Possible sources: operator's local copy, another cell that held a "
            "documentation mirror, or manual reconstruction using known values."
        )
        rb.checkbox("[HUMAN] bootstrap-state.json obtained from alternative source")

    rb.spacer()

    # ── Credentials ─────────────────────────────────────────────────────
    rb.h2("Physical Access and Credentials")
    rb.checkbox(f"Physical access to host '{hostname}' confirmed")
    rb.checkbox("IPMI / out-of-band management accessible (if required)")
    rb.field("Root password", "[HUMAN] Retrieve from KeePass", "HUMAN",
             "Retrieve root password before starting")
    rb.checkbox("Root password retrieved from KeePass")
    rb.checkbox("KeePass database accessible on recovery device")
    rb.spacer()

    # ── Secrets required for recovery ───────────────────────────────────
    secret_reg = manifest.get("secret_registry") or []
    rb.h2("Secrets Required for Recovery")
    if secret_reg:
        rb.body(
            "The following secrets are required during recovery. "
            "Retrieve them from KeePass before beginning restore operations. "
            f"({len(secret_reg)} entries from secret registry)"
        )
        rb.spacer()
        for s in secret_reg:
            sid   = s.get("id", "unknown")
            desc  = s.get("description", "")
            kpath = s.get("keepass_path") or "[KEEPASS_PATH not recorded]"
            stype = s.get("secret_type", "")
            req   = ", ".join(s.get("required_by") or [])
            rb.field(
                f"{sid}  ({stype})",
                kpath,
                "AUTO" if s.get("keepass_path") else "UNRESOLVED",
                f"{desc}  |  Required by: {req}" if req else desc,
            )
            rb.checkbox(f"Retrieved: {sid}")
    else:
        rb.field(
            "Secret registry", "NOT AVAILABLE", "UNRESOLVED",
            "secret-registry.yaml was not found in bootstrap-state. "
            "Retrieve secrets manually — check KeePass under 'Infrastructure/'."
        )
        rb.checkbox("[HUMAN] All required secrets retrieved from KeePass")
    rb.spacer()

    rb.h2("Backup Media")
    rb.field("Backup source", "[HUMAN] Confirm backup location", "HUMAN",
             "PBS server address, NFS share, or physical media location")
    rb.checkbox("Backup storage accessible and mounts successfully")
    rb.checkbox("Target backup verified present (check timestamps)")
    rb.spacer()

    rb.h2("Network")
    rb.field("Expected gateway", gateway, "AUTO", "")
    rb.field("Expected DNS",     dns_list, "AUTO", "")
    rb.checkbox("Network access from recovery environment confirmed")
    rb.spacer()

    rb.h2("Recovery Decision")
    rb.field("Incident start time",     "[HUMAN]", "HUMAN", "Record when recovery was initiated")
    rb.field("Decision maker",          "[HUMAN]", "HUMAN", "Name of person authorising recovery")
    rb.field("Affected components",     "[HUMAN]", "HUMAN", "List confirmed failed components")
    rb.field("Target recovery point",   "[HUMAN]", "HUMAN", "Which backup date/time to restore to")
    rb.spacer()

    # ------------------------------------------------------------------
    # Wave 0 — Network Reconstruction (from declared topology)
    # ------------------------------------------------------------------
    rb.h1("Wave 0 — Network Reconstruction")
    rb.body(
        "Wave 0 rebuilds the Proxmox host's network configuration before "
        "any VM is restored. Bridges must exist before VMs can be started; "
        "routing must be correct before SSH or backup storage is reachable."
    )
    rb.spacer()

    ntd = manifest.get("network_topology_declared")
    declared_bridges = (ntd.get("bridges") or []) if ntd else []

    if declared_bridges:
        drift = ntd.get("drift_detected", False)
        if drift:
            rb.warning(
                f"Network topology drift was detected at last collection: "
                f"{ntd.get('drift_details') or 'details unavailable'}"
            )
            rb.warning(
                "Verify bridges match declared configuration before proceeding"
            )
        rb.body(f"Declared bridges: {len(declared_bridges)}")
        rb.spacer()

        for bridge in declared_bridges:
            bname = bridge.get("name", "?")
            bip   = bridge.get("ip")
            bgw   = bridge.get("gateway")
            bports = bridge.get("ports") or []
            bvlan  = bridge.get("vlan_aware", False)
            bpurpose = bridge.get("purpose")

            rb.h2(f"Bridge: {bname}")
            if bpurpose:
                rb.body(f"Purpose: {bpurpose.strip()}")
            rb.field("IP",           bip or "(no host IP — VM-only bridge)", "AUTO", "")
            rb.field("Gateway",      bgw or "(no gateway)",                  "AUTO", "")
            rb.field("Ports",        ", ".join(bports) or "(no physical ports — internal)", "AUTO", "")
            rb.field("VLAN-aware",   "yes" if bvlan else "no",              "AUTO", "")

            rb.h3(f"Verify: {bname}")
            rb.code(f"ip link show {bname}")
            rb.body("Expected: bridge visible and state UP")
            if bip:
                rb.code(f"ip addr show {bname}")
                rb.body(f"Expected: inet {bip} assigned")
            rb.checkbox(f"Bridge {bname} UP")
            if bip:
                rb.checkbox(f"Bridge {bname} has correct IP {bip}")
            rb.spacer()

            rb.h3(f"Reconstruct {bname} (if missing)")
            rb.body("If the bridge is missing, reconstruct from /etc/network/interfaces:")
            rb.code("# Verify /etc/network/interfaces contains the bridge declaration:")
            rb.code(f"grep -A 10 'iface {bname}' /etc/network/interfaces")
            rb.body("Expected: bridge stanza present with correct address and bridge-ports.")
            rb.body("If the stanza is missing, restore from the forge/phoenix package's")
            rb.body("  proxmox-bootstrap/metadata/network-topology.yaml")
            rb.body("  and write it to /etc/network/interfaces, then run:")
            rb.code("ifreload -a")
            rb.body("Expected: bridge comes up without a full reboot.")
            rb.checkbox(f"Bridge {bname} reconstructed and verified")
            rb.spacer()

        if bgw:
            rb.h2("Verify Routing")
            rb.code(f"ping -c 3 {bgw}")
            rb.body(f"Expected: 3 packets received — gateway {bgw} reachable")
            rb.code("ip route show")
            rb.body("Expected: default route via gateway visible")
            rb.checkbox("Default route confirmed")
            rb.checkbox("External network reachable from host")
            rb.spacer()
    else:
        rb.field(
            "Network topology",
            "NOT DECLARED — manual bridge verification required",
            "UNRESOLVED",
            "Populate network_topology_declared in bootstrap-state.json to "
            "enable pre-populated Wave 0 reconstruction commands",
        )
        rb.body("Without declared topology, verify bridges manually:")
        rb.code("ip link show type bridge")
        rb.code("cat /etc/network/interfaces")
        rb.checkbox("[HUMAN] All bridges present and correctly configured")
        rb.spacer()

    # ------------------------------------------------------------------
    # Restore waves
    # ------------------------------------------------------------------
    rb.h1("Restore Sequence")
    rb.body(
        f"Restore waves are ordered by dependency. "
        f"Each wave's prerequisites must be complete before the wave begins."
    )
    rb.spacer()

    for wave in graph.restore_waves:
        rb.h2(f"Wave {wave.wave} — {wave.note}")
        if wave.estimated_minutes:
            rb.body(f"Estimated time: {wave.estimated_minutes} minutes")
        rb.spacer()

        for cid in wave.component_ids:
            node = node_map.get(cid)
            if not node:
                continue

            cr = next((c for c in readiness.components if c.component_id == cid), None)
            score = cr.score if cr else "UNKNOWN"
            score_sym = SCORE_SYMBOLS.get(score, "?")

            rb.h3(f"{node.label}  [{score_sym}]")

            # Readiness callout
            if cr and cr.score in ("RED", "BLOCKED", "ORANGE"):
                rb.warning(f"{score_sym}: {cr.score_reason}")
                for gap in (cr.gaps or []):
                    if gap.severity in ("RED", "ORANGE"):
                        rb.warning(f"  Gap: {gap.description}")
                        if gap.remediation:
                            rb.note(f"  Fix: {gap.remediation}")

            # Dependencies
            prereq_ids = [e.to_id for e in graph.edges if e.from_id == cid]
            if prereq_ids:
                prereq_labels = [
                    node_map[p].label for p in prereq_ids if p in node_map
                ]
                rb.note(f"Prerequisites: {', '.join(prereq_labels)}")
            rb.checkbox(f"Prerequisites for {node.label} confirmed complete")
            rb.spacer()

            # Restore commands
            cmds = _restore_cmd(node, manifest)
            for cmd in cmds:
                rb.code(cmd)
            rb.spacer()

            # Backup info
            if cr:
                if cr.backup_present is True:
                    age = f"{cr.backup_age_days:.0f}d" if cr.backup_age_days is not None else "unknown age"
                    rb.field("Backup", f"Present ({age})", "AUTO", "")
                    rb.field("Restore tested", "Yes" if cr.restore_tested else "No — unvalidated",
                             "AUTO" if cr.restore_tested else "UNRESOLVED", "")
                elif cr.backup_present is False:
                    rb.field("Backup", "NOT FOUND — recovery may fail", "UNRESOLVED",
                             "No backup detected for this component")
                else:
                    rb.field("Backup", "Unknown — Tier 2 assessment required", "UNRESOLVED", "")

            # Deployment provenance (VM nodes only)
            if node.type == "vm":
                prov_reg = manifest.get("provenance_registry") or []
                node_vmid = node.metadata.get("vmid")
                prov = None
                if node_vmid is not None:
                    for r in prov_reg:
                        try:
                            if int(r.get("vmid", -1)) == int(node_vmid):
                                prov = r
                                break
                        except (TypeError, ValueError):
                            pass

                if prov:
                    tofu_commit   = (prov.get("tofu_commit") or "unknown")
                    ans_commit    = (prov.get("ansible_commit") or "unknown")
                    ci_hash       = (prov.get("cloudinit_user_data_hash") or "unknown")
                    tofu_short    = tofu_commit[:12] + "..." if len(tofu_commit) > 12 else tofu_commit
                    ans_short     = ans_commit[:12] + "..."  if len(ans_commit) > 12  else ans_commit
                    ci_short      = ci_hash[:20] + "..."     if len(ci_hash) > 20     else ci_hash
                    rb.field("Provenance: deployed at",      prov.get("deployed_at", "unknown"), "AUTO", "")
                    rb.field("Provenance: OpenTofu workspace", prov.get("tofu_workspace", "unknown"), "AUTO", "")
                    rb.field("Provenance: OpenTofu commit",  tofu_short, "AUTO", "")
                    rb.field("Provenance: Ansible commit",   ans_short,  "AUTO", "")
                    rb.field("Provenance: template",         prov.get("template_name", "unknown"), "AUTO", "")
                    rb.field("Provenance: Cloud-Init hash",  ci_short, "AUTO",
                             "Compare against current snippets/user-data/ to verify parity")
                    rb.note(
                        "Verify reconstruction matches this provenance record before closing the incident."
                    )
                else:
                    rb.field("Deployment provenance", "NOT RECORDED", "UNRESOLVED",
                             f"No provenance record found for {node.label} — "
                             f"cannot verify reconstruction matches original deployment")

            # Service Contract block (VM nodes only)
            if node.type == "vm":
                vm_name  = node.metadata.get("name", "")
                vmid     = node.metadata.get("vmid", "?")
                vm_ip    = _resolve_vm_ip(vmid, manifest)
                contract = _get_contract(vm_name, manifest)

                if contract:
                    svc = contract.get("service", vm_name)
                    rb.h3(f"Service Contract: {svc}")

                    # -- Provided interfaces & health checks --------------------
                    provided = contract.get("provided_interfaces") or []
                    if provided:
                        rb.body("Provided interfaces:")
                        for iface in provided:
                            proto = iface.get("protocol", "?")
                            port  = iface.get("port", "?")
                            hc    = iface.get("health_check")
                            hc_str = f"  health_check: {hc}" if hc else "  no health check"
                            rb.field(
                                f"  {proto}:{port}",
                                hc_str,
                                "AUTO",
                            )
                            for cmd in _health_check_cmds(iface, vm_ip):
                                rb.code(cmd)
                        rb.spacer()

                    # -- Required interfaces ------------------------------------
                    required = contract.get("required_interfaces") or []
                    if required:
                        rb.body("Required interfaces (must be healthy before this service starts):")
                        for req in required:
                            req_svc      = req.get("service", "?")
                            req_proto    = req.get("protocol", "?")
                            req_port     = req.get("port", "?")
                            req_critical = req.get("critical", False)
                            severity_str = "CRITICAL" if req_critical else "optional"
                            rb.field(
                                f"  {req_svc}  ({req_proto}:{req_port})",
                                severity_str,
                                "UNRESOLVED" if req_critical else "AUTO",
                                f"Verify {req_svc} is reachable before starting {svc}",
                            )
                        rb.spacer()

                    # -- Startup ordering --------------------------------------
                    after = contract.get("startup_after") or []
                    if after:
                        rb.note(f"Start after: {', '.join(after)}")
                        rb.spacer()

                    # -- Restart commands --------------------------------------
                    rb.body("Service restart commands (run from operator machine):")
                    for cmd in _service_restart_cmds(contract, vm_ip):
                        rb.code(cmd)
                    rb.spacer()

                    # -- Secrets required by this service ----------------------
                    secret_refs = contract.get("secret_references") or []
                    if secret_refs:
                        rb.body(f"Secrets required by {svc}:")
                        for ref in secret_refs:
                            rb.field(f"  {ref}", "[retrieve from KeePass]", "HUMAN", "")

                    # -- Contract-level checkboxes ----------------------------
                    rb.checkbox(f"All required interfaces for {svc} verified reachable")
                    for iface in provided:
                        hc_cmds = _health_check_cmds(iface, vm_ip)
                        if hc_cmds:
                            proto = iface.get("protocol", "?")
                            port  = iface.get("port", "")
                            rb.checkbox(f"Health check passed: {svc} {proto}:{port}")
                    rb.checkbox(f"Service {svc} running and healthy")
                    rb.spacer()

            rb.field("Restore notes", "[HUMAN] Record any component-specific recovery notes", "HUMAN",
                     f"Notes for: {node.label}")
            rb.spacer()

            # Validation
            rb.h3(f"Validate: {node.label}")
            if node.type == "host":
                rb.code(f"ssh root@{hostname}")
                rb.body("Expected: login succeeds, Proxmox banner displayed")
                rb.code("pveversion -v")
                rb.body("Expected: version string matches pre-failure version")
                rb.checkbox("Host accessible via SSH")
                rb.checkbox("Proxmox web UI accessible")
            elif node.type == "storage":
                pool = node.metadata.get("pool_name", "rpool")
                rb.code(f"zpool status {pool}")
                rb.body("Expected: state ONLINE, no errors")
                rb.checkbox(f"Pool {pool} ONLINE")
            elif node.type == "vm":
                vmid = node.metadata.get("vmid", "?")
                vm_ip = _resolve_vm_ip(vmid, manifest)
                vm_name = node.metadata.get("name", "vm")
                rb.code(f"qm status {vmid}")
                rb.body("Expected: status running")
                rb.code(f"ssh ubuntu@{vm_ip}")
                if vm_ip == "[VM_IP]":
                    rb.note(f"Replace [VM_IP] with the IP address of {vm_name} — "
                            f"check /etc/pve/qemu-server/{vmid}.conf or DNS registry")
                rb.body("Expected: login succeeds")
                rb.checkbox(f"VM {vmid} running")
                rb.checkbox(f"SSH to {vm_name} confirmed")
            elif node.type == "container":
                ctid = node.metadata.get("ctid", "?")
                rb.code(f"pct status {ctid}")
                rb.checkbox(f"Container {ctid} running")
            elif node.type == "network":
                bname = node.metadata.get("bridge_name", "vmbr0")
                rb.code(f"ip link show {bname}")
                rb.checkbox(f"Bridge {bname} UP")
            rb.spacer()

    # ------------------------------------------------------------------
    # Post-Recovery Validation
    # ------------------------------------------------------------------
    rb.h1("Post-Recovery Validation")
    rb.body("After all waves complete, perform end-to-end validation.")
    rb.spacer()

    rb.h2("Infrastructure Check")
    rb.code("qm list")
    rb.body("Expected: all expected VMs listed with status running")
    rb.code("zpool status")
    rb.body("Expected: all pools ONLINE")
    rb.code(f"ping -c 3 {gateway}")
    rb.body("Expected: 3 packets received")
    rb.checkbox("All VMs running")
    rb.checkbox("All ZFS pools healthy")
    rb.checkbox("Network connectivity confirmed")
    rb.spacer()

    rb.h2("Re-run Assessment")
    rb.body("Run Tier 2 assessment to capture post-recovery state:")
    rb.code("python3 assessment/tier2/assess.py")
    rb.body("Compare output to pre-failure assessment to confirm full recovery.")
    rb.field("Post-recovery assessment ID", "[HUMAN] Record assessment ID", "HUMAN",
             "Record the ID of the post-recovery assessment for audit trail")
    rb.checkbox("Post-recovery assessment complete and state verified")
    rb.spacer()

    # ------------------------------------------------------------------
    # Appendix
    # ------------------------------------------------------------------
    rb.h1("Appendix A — Dependency Graph")
    rb.body(f"Nodes: {len(graph.nodes)}  |  Edges: {len(graph.edges)}")
    rb.spacer()

    rb.h2("All Nodes")
    for node in graph.nodes:
        cr = next((c for c in readiness.components if c.component_id == node.id), None)
        score = cr.score if cr else "UNKNOWN"
        rb.body(f"  {SCORE_SYMBOLS.get(score,'?')}  {node.label}  [{node.type}]  id={node.id}")

    rb.h2("All Dependencies (consumer → provider)")
    rb.body("Edge type legend:")
    rb.body("  [SERVICE★]   — declared required_interface in service-contracts.yaml")
    rb.body("  [DEPENDS_ON] — startup ordering (startup_after) or structural dependency")
    rb.body("  [STORAGE]    — storage pool dependency")
    rb.body("  [NETWORK]    — network infrastructure dependency")
    rb.body("  [BACKUP]     — backup relationship")
    rb.body("  ★ = sourced from declared service contract")
    rb.spacer()
    for edge in graph.edges:
        from_node = node_map.get(edge.from_id)
        to_node   = node_map.get(edge.to_id)
        fl = from_node.label if from_node else edge.from_id
        tl = to_node.label   if to_node   else edge.to_id
        origin = " ★" if edge.type == "SERVICE" else ""
        rb.body(f"  {fl}  →[{edge.type}{origin}]→  {tl}  ({edge.label or ''})")

    rb.spacer()

    rb.h1("Appendix B — Readiness Gaps")
    all_gaps = [g for cr in readiness.components for g in cr.gaps]
    registry_gaps = getattr(readiness, "registry_gaps", [])
    all_gaps_combined = all_gaps + list(registry_gaps)
    if all_gaps_combined:
        for gap in all_gaps_combined:
            node = node_map.get(gap.component_id)
            label = node.label if node else gap.component_id
            rb.h2(f"{label} — {gap.gap_type}")
            rb.field("Severity", SCORE_SYMBOLS.get(gap.severity, gap.severity), gap.severity, "")
            rb.body(f"Issue: {gap.description}")
            if gap.remediation:
                rb.body(f"Fix: {gap.remediation}")
            if gap.readiness_impact:
                rb.body(f"Impact: {gap.readiness_impact}")
    else:
        rb.body("No gaps detected.")

    # ------------------------------------------------------------------
    # Appendix C — DNS Registry
    # ------------------------------------------------------------------
    rb.h1("Appendix C — DNS Registry")
    dns_reg = manifest.get("dns_registry") or []
    if dns_reg:
        rb.body(f"All managed hostnames and IP addresses for cell: {hostname}")
        rb.spacer()
        for entry in dns_reg:
            hn    = entry.get("hostname", "unknown")
            ip    = entry.get("ip", "unknown")
            vmid  = entry.get("vmid")
            role  = entry.get("role", "")
            vmid_str = f"  VM {vmid}" if vmid is not None else "  (host)"
            rb.body(f"  {hn:<35} {ip:<18} {vmid_str:<10} {role}")
    else:
        rb.body(
            "DNS registry not available. "
            "VM IPs were not pre-populated — recovery commands use [VM_IP] placeholders."
        )

    rb.spacer()

    # ------------------------------------------------------------------
    # Appendix D — Secret Registry
    # ------------------------------------------------------------------
    rb.h1("Appendix D — Secret Registry")
    secret_reg_all = manifest.get("secret_registry") or []
    if secret_reg_all:
        rb.body(
            f"All managed secrets for cell. "
            f"KeePass paths reference the operator's KeePass database."
        )
        rb.spacer()
        for s in secret_reg_all:
            sid   = s.get("id", "unknown")
            kpath = s.get("keepass_path") or "[KEEPASS_PATH not recorded]"
            stype = s.get("secret_type", "")
            req   = ", ".join(s.get("required_by") or [])
            ops   = ", ".join(s.get("required_for") or [])
            rb.h2(f"{sid}  ({stype})")
            rb.field("KeePass path", kpath, "AUTO" if s.get("keepass_path") else "UNRESOLVED", "")
            if req:
                rb.body(f"Required by:  {req}")
            if ops:
                rb.body(f"Required for: {ops}")
            rotation = s.get("rotation_schedule")
            if rotation:
                rb.body(f"Rotation: {rotation}")
    else:
        rb.body(
            "Secret registry not available. "
            "Run setup-secrets.py or populate secret-registry.yaml and "
            "include it in bootstrap-state.json."
        )

    # ------------------------------------------------------------------
    # Appendix E — Deployment Provenance
    # ------------------------------------------------------------------
    rb.h1("Appendix E — Deployment Provenance")
    prov_reg_all = manifest.get("provenance_registry") or []
    if prov_reg_all:
        rb.body(
            f"Provenance records capture the exact OpenTofu workspace, Ansible commit, "
            f"and Cloud-Init hashes used to deploy each VM. "
            f"Use these to verify that reconstruction reproduces the original deployment."
        )
        rb.spacer()
        for r in prov_reg_all:
            vmid      = r.get("vmid", "?")
            name      = r.get("name", "unknown")
            dep_at    = r.get("deployed_at", "unknown")
            tofu_ws   = r.get("tofu_workspace", "unknown")
            tofu_c    = r.get("tofu_commit") or "unknown"
            ans_c     = r.get("ansible_commit") or "unknown"
            tmpl      = r.get("template_name", "unknown")
            ci_ud     = r.get("cloudinit_user_data_hash") or "unknown"
            ci_nc     = r.get("cloudinit_network_config_hash") or "unknown"
            dep_by    = r.get("deployed_by", "unknown")

            rb.h2(f"{name}  (vmid={vmid})")
            rb.field("Deployed at",          dep_at,                "AUTO", "")
            rb.field("Deployed by",          dep_by,                "AUTO", "")
            rb.field("OpenTofu workspace",   tofu_ws,               "AUTO", "")
            rb.field("OpenTofu commit",      tofu_c[:40],           "AUTO", "")
            rb.field("Ansible commit",       ans_c[:40],            "AUTO", "")
            rb.field("Template",             tmpl,                  "AUTO", "")
            rb.field("Cloud-Init user-data hash",    ci_ud[:64],    "AUTO", "")
            rb.field("Cloud-Init network-config hash", ci_nc[:64],  "AUTO", "")
            notes = r.get("notes")
            if notes:
                rb.body(f"Notes: {notes}")
    else:
        rb.body(
            "Provenance registry not available. "
            "Record deployment details in bootstrap-state.json provenance_records "
            "after each VM is provisioned."
        )

    # ------------------------------------------------------------------
    # Appendix F — Template Registry
    # ------------------------------------------------------------------
    rb.h1("Appendix F — Template Registry")
    base_images = manifest.get("base_images") or []
    templates   = manifest.get("templates") or []
    if templates or base_images:
        rb.body(
            "Templates are Proxmox VM templates (VMID 9000+) built from base ISO images. "
            "During reconstruction, clone the appropriate template rather than reinstalling "
            "from ISO to ensure package parity with the original deployment."
        )
        rb.spacer()

        if templates:
            rb.h2("VM Templates")
            for t in templates:
                name     = t.get("name", "unknown")
                base     = t.get("base_image", "unknown")
                tmpl_id  = t.get("proxmox_template_id", "unknown")
                created  = t.get("created_at", "unknown")
                pkgs     = t.get("additional_packages") or []
                notes    = t.get("build_notes") or ""
                rb.h3(name)
                rb.field("Proxmox template ID", str(tmpl_id), "AUTO", "")
                rb.field("Base image",          base,         "AUTO", "")
                rb.field("Created at",          created,      "AUTO", "")
                if pkgs:
                    rb.field("Additional packages", ", ".join(pkgs), "AUTO", "")
                if notes:
                    rb.body(f"Build notes: {notes}")

        if base_images:
            rb.spacer()
            rb.h2("Base Images")
            for bi in base_images:
                name     = bi.get("name", "unknown")
                iso      = bi.get("source_iso", "unknown")
                checksum = bi.get("checksum", "unknown")
                created  = bi.get("created_at", "unknown")
                pkgs     = bi.get("included_packages") or []
                notes    = bi.get("notes") or ""
                rb.h3(name)
                rb.field("Source ISO",  iso,      "AUTO", "")
                rb.field("Checksum",    checksum, "AUTO", "")
                rb.field("Created at",  created,  "AUTO", "")
                if pkgs:
                    rb.field("Included packages", ", ".join(pkgs), "AUTO", "")
                if notes:
                    rb.body(f"Notes: {notes}")
    else:
        rb.body(
            "Template registry not available. "
            "Populate base_images and templates in bootstrap-state.json "
            "to enable pre-populated reconstruction steps."
        )

    # ------------------------------------------------------------------
    # Appendix G — External Dependencies
    # ------------------------------------------------------------------
    rb.h1("Appendix G — External Dependencies")
    ext_deps = manifest.get("external_dependencies") or []
    if ext_deps:
        rb.body(
            f"External dependencies are services outside the cell boundary that "
            f"internal services rely on. ({len(ext_deps)} declared)"
        )
        rb.spacer()

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)

        for dep in ext_deps:
            dep_id    = dep.get("id", "unknown")
            dep_name  = dep.get("name", dep_id)
            dep_type  = dep.get("type", "other")
            endpoint  = dep.get("endpoint", "(not set)")
            status    = dep.get("status", "unknown")
            req_by    = ", ".join(dep.get("required_by") or []) or "(none declared)"
            desc      = dep.get("description") or ""
            failover  = dep.get("failover")
            notes     = dep.get("notes")

            rb.h2(f"{dep_name}  ({dep_type})")
            rb.field("ID",          dep_id,   "AUTO", "")
            rb.field("Endpoint",    endpoint, "AUTO", "")
            rb.field("Status",      status,   "AUTO" if status != "unknown" else "UNRESOLVED", "")
            rb.field("Required by", req_by,   "AUTO", "")
            if desc:
                rb.body(f"Description: {desc}")
            if failover:
                rb.field("Failover",  failover, "AUTO", "fallback if primary endpoint unreachable")
            if notes:
                rb.body(f"Notes: {notes}")

            cert = dep.get("certificate")
            if cert:
                rb.h3("TLS Certificate")
                expires_at    = cert.get("expires_at", "(unknown)")
                issuer        = cert.get("issuer") or "(not recorded)"
                subject       = cert.get("subject") or "(not recorded)"
                auto_renew    = cert.get("auto_renew")
                last_checked  = cert.get("last_checked_at") or dep.get("last_checked_at")

                days_remaining = None
                try:
                    exp_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                    days_remaining = (exp_dt - now).days
                except (ValueError, TypeError, AttributeError):
                    pass

                if days_remaining is not None:
                    if days_remaining <= 7:
                        sev_str = f"⚠ EXPIRES IN {days_remaining} DAYS — RENEW IMMEDIATELY"
                        rb.field("Expires at", f"{expires_at}  ({sev_str})", "UNRESOLVED", "")
                    elif days_remaining <= 30:
                        sev_str = f"⚠ {days_remaining} days remaining — renewal required"
                        rb.field("Expires at", f"{expires_at}  ({sev_str})", "HUMAN", "")
                    elif days_remaining <= 60:
                        sev_str = f"{days_remaining} days remaining — plan renewal"
                        rb.field("Expires at", f"{expires_at}  ({sev_str})", "DERIVED", "")
                    else:
                        rb.field("Expires at", f"{expires_at}  ({days_remaining} days remaining)", "AUTO", "")
                else:
                    rb.field("Expires at", expires_at, "AUTO", "")

                rb.field("Issuer",  issuer,  "AUTO", "")
                rb.field("Subject", subject, "AUTO", "")
                if auto_renew is not None:
                    rb.field("Auto-renew", "Yes" if auto_renew else "No", "AUTO", "")
                if last_checked:
                    rb.field("Last checked", last_checked, "AUTO", "")

                sans = cert.get("sans") or []
                if sans:
                    rb.body(f"SANs: {', '.join(sans)}")

            rb.spacer()

    else:
        rb.body(
            "No external dependencies declared. "
            "To track certificate expiry and reachability, add external_dependencies "
            "to bootstrap-state.json."
        )

    # ------------------------------------------------------------------
    # Appendix H — Backup Configuration
    # ------------------------------------------------------------------
    rb.h1("Appendix H — Backup Configuration")
    bc = manifest.get("backup_config")
    if bc:
        layers_cfg  = bc.get("layers") or {}
        history     = bc.get("backup_history") or []
        checkpoint_tag = bc.get("checkpoint_tag", "checkpoint")

        rb.body(
            "Backup is managed by restic (config/appdata layers) and rclone "
            "(secrets / KeePass layer). All restic repos use per-backup unique "
            "encryption keys stored in KeePass."
        )
        rb.spacer()

        LAYER_LABELS = {
            "secrets": "Secrets (KeePass database) — rclone copy, no restic",
            "config":  "Configuration state — restic, encrypted",
            "appdata": "Application data volumes — restic, encrypted (opt-in)",
        }

        for layer_name, layer_label in LAYER_LABELS.items():
            layer = layers_cfg.get(layer_name) or {}
            if not layer.get("enabled"):
                rb.h2(f"{layer_label} [DISABLED]")
                continue

            rb.h2(layer_label)
            dests   = layer.get("destinations") or []
            last_ok = layer.get("last_backup_at")
            consec  = layer.get("consecutive_all_fail_count", 0)

            if consec >= 2:
                rb.warning(f"ALL DESTINATIONS FAILED on {consec} consecutive runs — backup chain broken")
            elif consec == 1:
                rb.warning("All destinations failed on last run — investigate before next run")

            rb.field("Last successful backup",
                     last_ok or "NEVER",
                     "AUTO" if last_ok else "UNRESOLVED", "")
            rb.field("Consecutive all-fail count", str(consec),
                     "AUTO" if consec == 0 else ("ORANGE" if consec == 1 else "UNRESOLVED"), "")

            if dests:
                rb.body(f"Destination chain ({len(dests)} configured):")
                for i, dest in enumerate(dests, 1):
                    dest_type = dest.get("type", "?")
                    dest_id   = dest.get("id", "?")
                    if layer_name == "secrets":
                        root = dest.get("kdbx_destination_root", "(not set)")
                    else:
                        root = dest.get("restic_repo_root", "(not set)")
                    rb.body(f"  {i}. [{dest_type}] {dest_id}  —  {root}")
            else:
                rb.field("Destinations", "NONE CONFIGURED", "UNRESOLVED",
                         "Add destinations with setup-backup.py")

            # Recent history for this layer
            layer_history = [r for r in history if r.get("layer") == layer_name][:3]
            if layer_history:
                rb.body("Recent backup runs:")
                for r in layer_history:
                    run_at   = r.get("run_at", "?")
                    set_id   = (r.get("snapshot_set_id") or "?")[:40]
                    succeeded = len(r.get("destinations_succeeded") or [])
                    attempted = len(r.get("destinations_attempted") or [])
                    status = "✓" if succeeded == attempted else f"⚠ {succeeded}/{attempted}"
                    rb.body(f"  {run_at[:19]}  {status}  {set_id}")
            rb.spacer()

        # Restore instructions
        rb.h2("Restore Commands")
        rb.body("To restore from the most recent backup:")
        rb.code("# List available snapshot sets:")
        rb.code("python3 proxmox-bootstrap/restore-from-backup.py \\")
        rb.code("  --state proxmox-bootstrap/bootstrap-state.json --list")
        rb.code("")
        rb.code("# Restore config state (latest):")
        rb.code("python3 proxmox-bootstrap/restore-from-backup.py \\")
        rb.code("  --state proxmox-bootstrap/bootstrap-state.json \\")
        rb.code("  --layer config --latest --target /tmp/restore")
        rb.code("")
        rb.code("# Restore a permanent checkpoint:")
        rb.code("python3 proxmox-bootstrap/restore-from-backup.py \\")
        rb.code("  --state proxmox-bootstrap/bootstrap-state.json \\")
        rb.code(f"  --layer config --checkpoint --target /tmp/restore")
        rb.body("After restore: verify files at /tmp/restore and copy to their "
                "operational locations.")
        rb.spacer()

        # KeePass backup note
        rb.h2("KeePass Database Backup")
        secrets_cfg  = layers_cfg.get("secrets") or {}
        secrets_dests = secrets_cfg.get("destinations") or []
        rb.body(
            "The KeePass database is backed up as a plain rclone file copy "
            f"(already AES-256 encrypted — no restic layer). "
            f"{len(secrets_dests)} destination(s) configured."
        )
        rb.body(
            "To retrieve the KeePass backup: use the rclone credentials from "
            "forge-manifest.json (stored in the spawn/phoenix package, not in KeePass)."
        )
        rb.body(
            "After retrieving the .kdbx file, open it with the KeePass master password "
            "to access all restic repo passwords and service credentials."
        )

    else:
        rb.body(
            "Backup not configured. Run proxmox-bootstrap/setup-backup.py to configure "
            "backup destinations for KeePass DB, configuration state, and application data."
        )
        rb.warning(
            "No backup configured — KeePass database and infrastructure state are "
            "not protected by external backup. Run setup-backup.py immediately."
        )

    return rb.build_odt()
