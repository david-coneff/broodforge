#!/usr/bin/env python3
"""
recovery_workbook.py — Recovery workbook ODS renderer.

Sheets:
  1. Infrastructure Overview  — full observed state summary
  2. Restore Sequence         — wave-by-wave restore plan
  3. Component Details        — per-component backup/restore info
  4. Recovery Readiness       — scores, gaps, blockers, SPOFs
  5. Generation Report        — metadata and field counts
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from workbook import SheetBuilder, build_ods, _fmt_list, _fmt_kv, _get, CLASS_STYLE, _cell, _row, _empty_cell, _section_header_row

SCORE_STYLE = {
    "GREEN":   ("✓ GREEN",   "ce_derived"),
    "YELLOW":  ("⚠ YELLOW",  "ce_auto"),
    "ORANGE":  ("⚠ ORANGE",  "ce_human"),
    "RED":     ("✗ RED",     "ce_unresolved"),
    "BLOCKED": ("⛔ BLOCKED", "ce_unresolved"),
    "UNKNOWN": ("? UNKNOWN", "ce_note"),
}


def _score_cell(score: str) -> str:
    label, style = SCORE_STYLE.get(score, ("? UNKNOWN", "ce_note"))
    from xml.sax.saxutils import escape as xml_escape
    return (
        f'<table:table-cell table:style-name="{style}" office:value-type="string">'
        f'<text:p>{xml_escape(label)}</text:p>'
        f'</table:table-cell>'
    )


def _score_row(label: str, score: str, reason: str) -> str:
    return (
        '<table:table-row table:style-name="ro_normal">'
        + _cell(label, style="ce_label")
        + _score_cell(score)
        + _cell(reason, style="ce_note", wrap=True)
        + _empty_cell()
        + '</table:table-row>'
    )


def build_recovery_workbook(
    manifest: dict,
    graph,           # DependencyGraph
    readiness,       # ReadinessReport
    generation_meta: dict,
) -> bytes:
    node_map = graph.node_map()
    hostname = _get(manifest, "host.hostname") or "unknown"
    collected = manifest.get("collected_at", "unknown")

    # =========================================================
    # Sheet 1: Infrastructure Overview
    # =========================================================
    s1 = SheetBuilder("Infrastructure Overview")
    s1.title(f"Recovery Documentation — {hostname}")
    s1.field("Host", hostname, "AUTO", f"Assessment: {collected}")
    s1.field("Proxmox Version", _get(manifest, "host.proxmox_version") or "N/A", "AUTO", "")
    s1.field("Kernel", _get(manifest, "host.kernel_version") or "N/A", "AUTO", "")
    s1.field("Assessment Date", collected, "AUTO", "")
    s1.field("Generated", generation_meta.get("generated_at", ""), "AUTO", "")
    s1.spacer()

    s1.section("CPU")
    cpu = _get(manifest, "cpu") or {}
    s1.field("Model",        str(cpu.get("model") or "N/A"),            "AUTO", "")
    s1.field("Logical CPUs", str(cpu.get("total_threads", "N/A")),      "AUTO", "")
    s1.field("Sockets",      str(cpu.get("sockets") or "N/A"),          "AUTO", "")

    s1.section("Memory")
    mem = _get(manifest, "memory") or {}
    s1.field("Total RAM",  f"{mem.get('total_gb', 'N/A')} GB", "AUTO", "")
    s1.field("Available",  f"{mem.get('available_gb', 'N/A')} GB", "AUTO", "")

    s1.section("Storage")
    s1.field("ZFS Pools",
             _fmt_list(_get(manifest, "storage.zfs_pools") or [],
                       "{name}: state={state}  topology={topology}  free={free_gb} GB"),
             "AUTO", "")
    s1.field("PVE Storage",
             _fmt_list(_get(manifest, "storage.pve_storage") or [],
                       "{name} ({type}): total={total_gb} GB  free={free_gb} GB"),
             "AUTO", "")

    s1.section("Network")
    s1.field("Bridges",
             _fmt_list(_get(manifest, "network.bridges") or [],
                       "{name}: ports={ports}  {addresses}"),
             "AUTO", "")
    s1.field("Default Gateway", str(_get(manifest, "network.default_gateway") or "N/A"), "AUTO", "")
    s1.field("DNS Servers",
             ", ".join(_get(manifest, "network.dns_servers") or []) or "N/A",
             "AUTO", "")

    s1.section("Virtual Machines")
    vms = _get(manifest, "vms") or []
    s1.field("VMs",
             _fmt_list(vms, "VM {vmid} ({name}): {status}  cores={cores}  mem={memory_mb} MB",
                       "(none)"),
             "AUTO", f"{len(vms)} VM(s)")

    s1.section("Overall Readiness")
    overall_label, overall_style = SCORE_STYLE.get(readiness.overall_score, ("?", "ce_note"))

    # Manually add a score row inline
    from xml.sax.saxutils import escape as xml_escape
    s1._rows.append(
        '<table:table-row table:style-name="ro_normal">'
        + _cell("Overall Score", style="ce_label")
        + f'<table:table-cell table:style-name="{overall_style}" office:value-type="string">'
        + f'<text:p>{xml_escape(overall_label)}</text:p></table:table-cell>'
        + _cell(readiness.overall_score_reason, style="ce_note", wrap=True)
        + _empty_cell()
        + '</table:table-row>'
    )

    spof_labels = [node_map[nid].label for nid in readiness.single_points_of_failure if nid in node_map]
    s1.field("Single Points of Failure",
             "\n".join(spof_labels) or "(none identified)",
             "DERIVED" if spof_labels else "AUTO", "")
    blocker_labels = [node_map[nid].label for nid in readiness.recovery_blockers if nid in node_map]
    s1.field("Recovery Blockers",
             "\n".join(blocker_labels) or "(none)",
             "RED" if blocker_labels else "AUTO", "")
    s1.legend()

    # =========================================================
    # Sheet 2: Restore Sequence
    # =========================================================
    s2 = SheetBuilder("Restore Sequence")
    s2.title("Restore Sequence (Generated from Dependency Graph)")
    s2.column_headers()

    total_minutes = sum(w.estimated_minutes or 0 for w in graph.restore_waves)
    s2.field("Total Estimated Time", f"{total_minutes} minutes", "DERIVED",
             "Sum of per-wave estimates — actual time varies")
    s2.field("Total Waves", str(len(graph.restore_waves)), "DERIVED", "")
    s2.spacer()

    for wave in graph.restore_waves:
        s2.section(f"Wave {wave.wave} — {wave.note}")
        if wave.estimated_minutes:
            s2.field("Estimated Time", f"{wave.estimated_minutes} minutes", "DERIVED", "")

        for cid in wave.component_ids:
            node = node_map.get(cid)
            if not node:
                continue
            cr = next((c for c in readiness.components if c.component_id == cid), None)
            score_label = SCORE_STYLE.get(cr.score if cr else "UNKNOWN", ("?","ce_note"))[0]

            # Dependencies
            deps = [e.to_id for e in graph.edges if e.from_id == cid]
            dep_labels = [node_map[d].label for d in deps if d in node_map]

            s2.field(
                node.label,
                score_label,
                cr.score if cr else "UNKNOWN",
                f"Depends on: {', '.join(dep_labels)}" if dep_labels else "No prerequisites",
            )

    s2.legend()

    # =========================================================
    # Sheet 3: Component Details
    # =========================================================
    s3 = SheetBuilder("Component Details")
    s3.title("Component Recovery Details")
    s3.column_headers()

    for node in graph.nodes:
        cr = next((c for c in readiness.components if c.component_id == node.id), None)
        if not cr:
            continue

        s3.section(node.label)
        score_label = SCORE_STYLE.get(cr.score, ("?", "ce_note"))[0]
        s3.field("Readiness Score", score_label, cr.score, cr.score_reason)
        s3.field("Type",   node.type,  "AUTO", "")

        # Metadata fields
        for k, v in node.metadata.items():
            if v is not None:
                s3.field(k.replace("_", " ").title(), str(v), "AUTO", "")

        # Backup info
        if cr.backup_present is True:
            age = f"{cr.backup_age_days:.0f} days" if cr.backup_age_days is not None else "unknown age"
            s3.field("Backup", f"Present ({age})", "AUTO", "")
            s3.field("Restore Tested", "Yes" if cr.restore_tested else "No", "AUTO", "")
        elif cr.backup_present is False:
            s3.field("Backup", "NOT FOUND", "UNRESOLVED", "No backup job detected")
        else:
            s3.field("Backup", "Unknown (Tier 1 assessment)", "UNRESOLVED",
                     "Run Tier 2 assessment to collect backup inventory")

        # Gaps
        if cr.gaps:
            for gap in cr.gaps:
                s3.field(f"GAP: {gap.gap_type}", gap.description, gap.severity,
                         f"Remediation: {gap.remediation or 'N/A'}")

        # Human fields
        s3.human_field("Restore notes / passphrase location",
                       f"Record any recovery-specific notes for {node.label}")

    s3.legend()

    # =========================================================
    # Sheet 4: Recovery Readiness
    # =========================================================
    s4 = SheetBuilder("Recovery Readiness")
    s4.title("Recovery Readiness Report")

    # Overall
    s4._rows.append(
        '<table:table-row table:style-name="ro_section">'
        + _cell("Overall Score", style="ce_section")
        + _score_cell(readiness.overall_score)
        + _cell(readiness.overall_score_reason, style="ce_note", wrap=True)
        + _empty_cell()
        + '</table:table-row>'
    )
    s4.spacer()

    s4.section("Component Scores")
    for cr in readiness.components:
        node = node_map.get(cr.component_id)
        label = node.label if node else cr.component_id
        s4._rows.append(_score_row(label, cr.score, cr.score_reason))

    # Gaps
    all_gaps = [g for cr in readiness.components for g in cr.gaps]
    if all_gaps:
        s4.section(f"Gaps Requiring Attention ({len(all_gaps)})")
        for gap in all_gaps:
            node = node_map.get(gap.component_id)
            comp_label = node.label if node else gap.component_id
            s4.field(
                f"{comp_label} — {gap.gap_type}",
                gap.description,
                gap.severity,
                f"Fix: {gap.remediation or 'N/A'}  |  Impact: {gap.readiness_impact or 'N/A'}",
            )

    # SPOFs
    if readiness.single_points_of_failure:
        s4.section("Single Points of Failure")
        for spof_id in readiness.single_points_of_failure:
            node = node_map.get(spof_id)
            if node:
                dep_count = sum(1 for e in graph.edges if e.to_id == spof_id)
                s4.field(node.label, f"{dep_count} component(s) depend on this",
                         "ORANGE", "Consider adding redundancy or offsite backup")

    # Blockers
    if readiness.recovery_blockers:
        s4.section("Recovery Blockers")
        for bid in readiness.recovery_blockers:
            node = node_map.get(bid)
            if node:
                blocked = [node_map[e.from_id].label for e in graph.edges
                           if e.to_id == bid and e.from_id in node_map]
                s4.field(node.label, f"Blocks: {', '.join(blocked)}",
                         "RED", "Resolve backup/restore issues before attempting recovery")

    # Unresolved HUMAN fields reminder
    s4.section("Human Input Required During Recovery")
    s4.human_field("Incident start time",        "Record when recovery was initiated")
    s4.human_field("Affected components",         "List components confirmed as failed")
    s4.human_field("Recovery decision maker",     "Name of person authorising recovery")
    s4.human_field("KeePass database available",  "Confirm KeePass database is accessible", is_checkbox=True)
    s4.human_field("Physical access confirmed",   "Confirm physical host access", is_checkbox=True)

    s4.legend()

    # =========================================================
    # Sheet 5: Generation Report
    # =========================================================
    s5 = SheetBuilder("Generation Report")
    s5.title("Recovery Documentation Generation Report")
    s5.column_headers()

    s5.section("Generation Metadata")
    s5.field("Generated At",    generation_meta.get("generated_at", "N/A"), "AUTO", "")
    s5.field("Mode",            "recovery", "AUTO", "")
    s5.field("Assessment Tier", str(generation_meta.get("tier", "N/A")), "AUTO", "")
    s5.field("Assessment Date", generation_meta.get("collected_at", "N/A"), "AUTO", "")

    s5.section("Graph Summary")
    s5.field("Nodes", str(len(graph.nodes)), "DERIVED", "")
    s5.field("Edges", str(len(graph.edges)), "DERIVED", "")
    s5.field("Restore Waves", str(len(graph.restore_waves)), "DERIVED", "")
    s5.field("Estimated Total Time", f"{total_minutes} minutes", "DERIVED", "")

    s5.section("Readiness Summary")
    score_counts: dict = {}
    for cr in readiness.components:
        score_counts[cr.score] = score_counts.get(cr.score, 0) + 1
    for sc in ("GREEN", "YELLOW", "ORANGE", "RED", "BLOCKED", "UNKNOWN"):
        n = score_counts.get(sc, 0)
        if n:
            s5.field(sc, str(n), sc, "")

    return build_ods([s1, s2, s3, s4, s5])
