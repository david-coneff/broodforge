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
    generated = generation_meta.get("generated_at", "unknown")
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

    rb.h2("Physical Access")
    rb.checkbox(f"Physical access to host '{hostname}' confirmed")
    rb.checkbox("IPMI / out-of-band management accessible (if required)")
    rb.spacer()

    rb.h2("Credentials")
    rb.field("Root password", "[HUMAN] Retrieve from KeePass", "HUMAN",
             "Retrieve root password before starting")
    rb.checkbox("Root password retrieved from KeePass")
    rb.checkbox("KeePass database accessible on recovery device")
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
                rb.code(f"qm status {vmid}")
                rb.body("Expected: status running")
                rb.code(f"ssh ubuntu@[VM_IP]  # replace with {node.metadata.get('name','vm')} IP")
                rb.body("Expected: login succeeds")
                rb.checkbox(f"VM {vmid} running")
                rb.checkbox(f"SSH to {node.metadata.get('name','vm')} confirmed")
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
    for edge in graph.edges:
        from_node = node_map.get(edge.from_id)
        to_node   = node_map.get(edge.to_id)
        fl = from_node.label if from_node else edge.from_id
        tl = to_node.label   if to_node   else edge.to_id
        rb.body(f"  {fl}  →[{edge.type}]→  {tl}  ({edge.label or ''})")

    rb.spacer()

    rb.h1("Appendix B — Readiness Gaps")
    all_gaps = [g for cr in readiness.components for g in cr.gaps]
    if all_gaps:
        for gap in all_gaps:
            node = node_map.get(gap.component_id)
            rb.h2(f"{node.label if node else gap.component_id} — {gap.gap_type}")
            rb.field("Severity",   SCORE_SYMBOLS.get(gap.severity, gap.severity), gap.severity, "")
            rb.body(f"Issue: {gap.description}")
            if gap.remediation:
                rb.body(f"Fix: {gap.remediation}")
            if gap.readiness_impact:
                rb.body(f"Impact: {gap.readiness_impact}")
    else:
        rb.body("No gaps detected.")

    return rb.build_odt()
