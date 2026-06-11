#!/usr/bin/env python3
"""
html_recovery_workbook.py — HTML recovery workbook renderer.

Produces a self-contained HTML document that replaces the ODS recovery workbook.
Organises the same five content areas as the spreadsheet version into collapsible
sections using the setup-guide style defined in html_base.py.

Sections (parallel to the former ODS sheets):
  1. Infrastructure Overview  — host, CPU, RAM, storage, network, VMs, overall score
  2. Restore Sequence         — wave-by-wave restore plan with estimated times
  3. Component Details        — per-component backup / restore / gap information
  4. Recovery Readiness       — scores, gaps, blockers, SPOFs, interactive pre-flight
  5. Generation Report        — metadata and graph statistics

Interactive behavior:
  - Recovery Readiness section contains checkbox items (saved in localStorage).
  - All five sections are collapsible; sections 1 and 4 are open by default.

Public API:
  build_recovery_workbook_html(manifest, graph, readiness, generation_meta) → str

Checkbox behavior: checked → " done" italic, NO strikethrough.
Stdlib only.
"""

import sys
from html import escape as _e
from pathlib import Path

# Audit finding (rounds 4/5): Priority 4 — legitimate standalone-script path manipulation.
# doc-gen/renderers/ has no __init__.py; html_base, timestamps, etc. are co-located
# modules, not a package.  Relative imports require __init__.py.
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from html_base import (
    html_page, h, p, pre, code, dl, table, divider,
    callout, section, score_badge,
    checkbox_item, checkbox_list, reset_checkbox_counter,
)
from timestamps import format_doc_timestamp_from_iso


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get(manifest: dict, path: str, default=None):
    obj = manifest
    for part in path.split("."):
        if not isinstance(obj, dict):
            return default
        obj = obj.get(part, default)
    return obj


def _str(v, fallback: str = "—") -> str:
    if v is None:
        return fallback
    if isinstance(v, list):
        return ", ".join(str(x) for x in v) if v else "(none)"
    return str(v)


def _score_cls(score: str) -> str:
    return {
        "GREEN":   "score-green",
        "YELLOW":  "score-yellow",
        "ORANGE":  "score-orange",
        "RED":     "score-red",
        "BLOCKED": "score-blocked",
    }.get(score.upper(), "score-blocked")


def _badge(score: str) -> str:
    label = {
        "GREEN":   "✓ GREEN",
        "YELLOW":  "⚠ YELLOW",
        "ORANGE":  "⚠ ORANGE",
        "RED":     "✗ RED",
        "BLOCKED": "⛔ BLOCKED",
        "UNKNOWN": "? UNKNOWN",
    }.get(score.upper(), score)
    cls = _score_cls(score)
    return f'<span class="score {_e(cls)}">{_e(label)}</span>'


# ---------------------------------------------------------------------------
# Section 1 — Infrastructure Overview
# ---------------------------------------------------------------------------

def _section_overview(manifest: dict, readiness) -> str:
    host = manifest.get("host") or {}
    cpu  = manifest.get("cpu") or {}
    mem  = manifest.get("memory") or {}
    collected = manifest.get("collected_at", "—")

    pairs: list[tuple] = [
        ("Hostname",           host.get("hostname") or "—"),
        ("FQDN",               host.get("fqdn") or "—"),
        ("Proxmox version",    host.get("proxmox_version") or "—"),
        ("Kernel",             host.get("kernel_version") or "—"),
        ("Timezone",           host.get("timezone") or "—"),
        ("Assessment date",    collected),
        ("Overall score",      ""),   # replaced below
    ]

    overall = getattr(readiness, "overall_score", "?")
    reason  = getattr(readiness, "overall_score_reason", "")
    body = dl(pairs[:-1])
    body += (
        f'<dl style="margin:.4em 0">'
        f'<dt>Overall score</dt>'
        f'<dd>{_badge(overall)} <span style="color:#555;font-size:.9em">{_e(reason)}</span></dd>'
        f'</dl>'
    )

    body += h(3, "CPU")
    body += dl([
        ("Model",        cpu.get("model") or "—"),
        ("Logical CPUs", _str(cpu.get("total_threads"))),
        ("Sockets",      _str(cpu.get("sockets"))),
        ("Architecture", cpu.get("architecture") or "—"),
    ])

    body += h(3, "Memory")
    body += dl([
        ("Total RAM",   f"{mem.get('total_gb', '—')} GB"),
        ("Available",   f"{mem.get('available_gb', '—')} GB"),
        ("Swap",        f"{mem.get('swap_total_gb', '—')} GB"),
    ])

    body += h(3, "Storage")
    pools = (_get(manifest, "storage.zfs_pools") or [])
    if pools:
        pool_rows = [
            [_e(pool.get("name", "?")), _e(pool.get("state", "?")),
             _e(pool.get("topology", "?")), _e(f"{pool.get('free_gb', '?')} GB")]
            for pool in pools
        ]
        body += table(["Pool", "State", "Topology", "Free"], pool_rows)
    else:
        pve_storage = (_get(manifest, "storage.pve_storage") or [])
        if pve_storage:
            rows = [
                [_e(s.get("name","?")), _e(s.get("type","?")),
                 _e(f"{s.get('total_gb','?')} GB"), _e(f"{s.get('free_gb','?')} GB")]
                for s in pve_storage
            ]
            body += table(["Name", "Type", "Total", "Free"], rows)
        else:
            body += p("No storage data collected.")

    body += h(3, "Network")
    bridges = _get(manifest, "network.bridges") or []
    body += dl([
        ("Default gateway", _get(manifest, "network.default_gateway") or "—"),
        ("DNS servers",     ", ".join(_get(manifest, "network.dns_servers") or []) or "—"),
    ])
    if bridges:
        bridge_rows = [
            [_e(b.get("name","?")), _e(b.get("addresses") or b.get("address") or "—"),
             _e(", ".join(b.get("ports") or []) or "—")]
            for b in bridges
        ]
        body += table(["Bridge", "Address", "Ports"], bridge_rows)

    body += h(3, "Virtual Machines")
    vms = _get(manifest, "vms") or []
    if vms:
        vm_rows = [
            [_e(str(vm.get("vmid","?"))), _e(vm.get("name","?")),
             _e(vm.get("status","?")), _e(str(vm.get("cores","?"))),
             _e(f"{vm.get('memory_mb','?')} MB")]
            for vm in vms
        ]
        body += table(["VMID", "Name", "Status", "Cores", "RAM"], vm_rows)
    else:
        body += p("No VM data collected.")

    spof_ids  = getattr(readiness, "single_points_of_failure", [])
    blocker_ids = getattr(readiness, "recovery_blockers", [])
    if spof_ids or blocker_ids:
        body += h(3, "Recovery Risk Summary")
        body += dl([
            ("SPOFs",    str(len(spof_ids))),
            ("Blockers", str(len(blocker_ids))),
        ])

    return section("Infrastructure Overview", body, open_=True, id_="s1")


# ---------------------------------------------------------------------------
# Section 2 — Restore Sequence
# ---------------------------------------------------------------------------

def _section_restore_sequence(graph, readiness) -> str:
    node_map   = graph.node_map() if hasattr(graph, "node_map") else {}
    waves      = getattr(graph, "restore_waves", [])
    components = getattr(readiness, "components", [])

    total_min = sum(getattr(w, "estimated_minutes", 0) or 0 for w in waves)

    body = dl([
        ("Total waves",          str(len(waves))),
        ("Estimated total time", f"{total_min} minutes"),
    ])

    for wave in waves:
        wave_num  = getattr(wave, "wave", "?")
        wave_note = getattr(wave, "note", "")
        wave_min  = getattr(wave, "estimated_minutes", None)
        wave_cids = getattr(wave, "component_ids", [])

        wave_title = f"Wave {wave_num}"
        if wave_note:
            wave_title += f" — {wave_note}"
        if wave_min:
            wave_title += f" (~{wave_min} min)"

        rows = []
        for cid in wave_cids:
            node = node_map.get(cid)
            if not node:
                continue
            cr = next((c for c in components if c.component_id == cid), None)
            score = cr.score if cr else "UNKNOWN"
            deps  = [e.to_id for e in graph.edges if e.from_id == cid]
            dep_labels = [node_map[d].label for d in deps if d in node_map]
            dep_str = ", ".join(dep_labels) if dep_labels else "—"
            rows.append([
                _e(getattr(node, "label", cid)),
                _badge(score),
                _e(dep_str),
            ])

        wave_body = table(["Component", "Readiness", "Depends on"], rows) if rows else p("(no components)")
        body += section(wave_title, wave_body, open_=False)

    return section("Restore Sequence", body, open_=False, id_="s2")


# ---------------------------------------------------------------------------
# Section 3 — Component Details
# ---------------------------------------------------------------------------

def _section_component_details(graph, readiness) -> str:
    node_map   = graph.node_map() if hasattr(graph, "node_map") else {}
    components = getattr(readiness, "components", [])

    body = ""
    for node in graph.nodes:
        cr = next((c for c in components if c.component_id == node.id), None)
        if not cr:
            continue

        score = cr.score if cr else "UNKNOWN"
        label = getattr(node, "label", node.id)

        comp_pairs: list[tuple] = [
            ("Readiness",  ""),
            ("Type",       getattr(node, "type", "—")),
        ]

        comp_body = (
            f'<dl style="margin:.4em 0">'
            f'<dt>Readiness</dt>'
            f'<dd>{_badge(score)} <span style="color:#555;font-size:.9em">{_e(cr.score_reason or "")}</span></dd>'
            f'</dl>'
        )

        extra_pairs = [("Type", getattr(node, "type", "—"))]
        for k, v in (getattr(node, "metadata", None) or {}).items():
            if v is not None:
                extra_pairs.append((k.replace("_", " ").title(), str(v)))
        comp_body += dl(extra_pairs)

        # Backup info
        bp = getattr(cr, "backup_present", None)
        if bp is True:
            age = getattr(cr, "backup_age_days", None)
            age_str = f"{age:.0f} days" if age is not None else "unknown age"
            tested  = "Yes" if getattr(cr, "restore_tested", False) else "No"
            comp_body += dl([("Backup", f"Present ({age_str})"), ("Restore tested", tested)])
        elif bp is False:
            comp_body += callout("danger", "Backup not found — no backup job detected for this component.")
        else:
            comp_body += callout("warn", "Backup status unknown — run Tier 2 assessment to collect backup inventory.")

        # Gaps
        gaps = getattr(cr, "gaps", [])
        if gaps:
            gap_rows = [
                [_e(g.gap_type), _e(g.description), _e(g.severity),
                 _e(g.remediation or "—"), _e(g.readiness_impact or "—")]
                for g in gaps
            ]
            comp_body += h(4, "Gaps")
            comp_body += table(["Type", "Description", "Severity", "Remediation", "Impact"], gap_rows)

        # Human field
        comp_body += h(4, "Recovery Notes")
        reset_checkbox_counter()
        comp_body += checkbox_list([
            f"Restore notes / passphrase recorded for {_e(label)}",
        ], id_prefix=f"comp-{_e(node.id)}")

        body += section(label, comp_body, open_=False)

    return section("Component Details", body, open_=False, id_="s3")


# ---------------------------------------------------------------------------
# Section 4 — Recovery Readiness
# ---------------------------------------------------------------------------

def _section_recovery_readiness(graph, readiness) -> str:
    node_map   = graph.node_map() if hasattr(graph, "node_map") else {}
    components = getattr(readiness, "components", [])
    overall    = getattr(readiness, "overall_score", "?")
    reason     = getattr(readiness, "overall_score_reason", "")
    spof_ids   = getattr(readiness, "single_points_of_failure", [])
    blockers   = getattr(readiness, "recovery_blockers", [])

    body = (
        f'<p style="margin:.6em 0">'
        f'<strong>Overall score:</strong> {_badge(overall)}'
        + (f' <span style="color:#555;font-size:.9em">— {_e(reason)}</span>' if reason else "")
        + "</p>"
    )

    # Per-component scores
    if components:
        score_rows = []
        for cr in components:
            node = node_map.get(cr.component_id)
            label = node.label if node else cr.component_id
            score_rows.append([_e(label), _badge(cr.score), _e(cr.score_reason or "")])
        body += h(3, "Component Scores")
        body += table(["Component", "Score", "Reason"], score_rows)

    # Gaps
    all_gaps = [g for cr in components for g in getattr(cr, "gaps", [])]
    if all_gaps:
        body += h(3, f"Gaps Requiring Attention ({len(all_gaps)})")
        gap_rows = []
        for gap in all_gaps:
            node  = node_map.get(gap.component_id)
            label = node.label if node else gap.component_id
            gap_rows.append([
                _e(label),
                _e(gap.gap_type),
                _badge(gap.severity),
                _e(gap.description),
                _e(gap.remediation or "—"),
            ])
        body += table(["Component", "Gap type", "Severity", "Description", "Remediation"], gap_rows)

    # SPOFs
    if spof_ids:
        body += h(3, "Single Points of Failure")
        spof_rows = []
        for sid in spof_ids:
            node = node_map.get(sid)
            if node:
                dep_count = sum(1 for e in graph.edges if e.to_id == sid)
                spof_rows.append([_e(node.label), _e(f"{dep_count} component(s) depend on this")])
        body += table(["Component", "Risk"], spof_rows)

    # Blockers
    if blockers:
        body += h(3, "Recovery Blockers")
        body += callout("danger", "Resolve all blockers before attempting recovery — their downstream dependencies cannot be restored until these are fixed.")
        blocker_rows = []
        for bid in blockers:
            node = node_map.get(bid)
            if node:
                blocked = [node_map[e.from_id].label for e in graph.edges if e.to_id == bid and e.from_id in node_map]
                blocker_rows.append([_e(node.label), _e(", ".join(blocked) or "—")])
        body += table(["Blocker", "Blocks"], blocker_rows)

    # Interactive pre-flight checklist
    body += h(3, "Pre-Flight Checklist (fill in during recovery)")
    reset_checkbox_counter()
    body += checkbox_list([
        "KeePass database retrieved from backup and accessible",
        "KeePass master password available (in head or secure location)",
        "Physical access to recovery hardware confirmed",
        "Incident start time recorded",
        "Recovery decision-maker identified and notified",
        "Affected components confirmed as failed (not just unreachable)",
        "Network connectivity to replacement hardware verified",
    ], id_prefix="preflight")

    # Human input fields (text)
    body += h(3, "Human Input Required")
    body += (
        '<table style="width:100%;border-collapse:collapse;font-size:.9em;margin:.6em 0">'
        '<thead><tr>'
        '<th style="background:#1f3864;color:#fff;padding:7px 10px">Field</th>'
        '<th style="background:#1f3864;color:#fff;padding:7px 10px">Value (fill during recovery)</th>'
        '</tr></thead><tbody>'
        + "".join(
            f'<tr><td style="padding:6px 10px;border-bottom:1px solid #dee2e6;font-weight:600">{_e(label)}</td>'
            f'<td style="padding:4px 6px;border-bottom:1px solid #dee2e6">'
            f'<input type="text" placeholder="Enter value..." '
            f'style="width:100%;border:1px solid #dee2e6;border-radius:3px;padding:4px 8px;font-size:.9em">'
            f'</td></tr>'
            for label in [
                "Incident start time (UTC)",
                "Affected components (confirmed failed)",
                "Recovery decision-maker name",
                "Recovery hardware hostname / VMID",
                "Estimated recovery completion time",
                "Post-recovery verification notes",
            ]
        )
        + "</tbody></table>"
    )

    return section("Recovery Readiness", body, open_=True, id_="s4")


# ---------------------------------------------------------------------------
# Section 5 — Generation Report
# ---------------------------------------------------------------------------

def _section_generation_report(graph, readiness, generation_meta: dict) -> str:
    components = getattr(readiness, "components", [])
    waves      = getattr(graph, "restore_waves", [])

    total_min = sum(getattr(w, "estimated_minutes", 0) or 0 for w in waves)

    gen_at   = format_doc_timestamp_from_iso(generation_meta.get("generated_at", ""))
    coll_at  = generation_meta.get("collected_at", "—")

    body = h(3, "Generation Metadata")
    body += dl([
        ("Generated at",    gen_at),
        ("Assessment date", coll_at),
        ("Assessment tier", str(generation_meta.get("tier", "—"))),
        ("Template",        generation_meta.get("template_version", "recovery-v1.0")),
    ])

    body += h(3, "Dependency Graph")
    body += dl([
        ("Nodes",          str(len(graph.nodes))),
        ("Edges",          str(len(graph.edges))),
        ("Restore waves",  str(len(waves))),
        ("Estimated time", f"{total_min} minutes"),
    ])

    body += h(3, "Readiness Summary")
    score_counts: dict = {}
    for cr in components:
        sc = cr.score
        score_counts[sc] = score_counts.get(sc, 0) + 1

    counts_rows = [
        [_badge(sc), _e(str(score_counts.get(sc, 0)))]
        for sc in ("GREEN", "YELLOW", "ORANGE", "RED", "BLOCKED", "UNKNOWN")
        if score_counts.get(sc, 0) > 0
    ]
    if counts_rows:
        body += table(["Score", "Components"], counts_rows)
    else:
        body += p("No components scored.")

    drift = generation_meta.get("drift")
    if drift and drift.get("diffs"):
        body += h(3, "Drift Since Last Assessment")
        body += dl([
            ("Severity",   drift.get("drift_severity", "—")),
            ("Fields changed", str(len(drift["diffs"]))),
            ("Compared",   f'{drift.get("from_snapshot","?")} → {drift.get("to_snapshot","?")}'),
        ])
        drift_rows = [
            [_e(d["path"]), _e(str(d.get("from_value",""))), _e(str(d.get("to_value",""))), _e(d.get("severity",""))]
            for d in drift["diffs"][:25]
        ]
        body += table(["Field", "Was", "Now", "Severity"], drift_rows)
        if len(drift["diffs"]) > 25:
            body += p(f"… and {len(drift['diffs']) - 25} more change(s).")

    return section("Generation Report", body, open_=False, id_="s5")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_recovery_workbook_html(
    manifest:         dict,
    graph,
    readiness,
    generation_meta:  dict,
) -> str:
    """
    Build the complete recovery workbook as a self-contained HTML page.

    Returns the HTML string. Write to a .html file; no binary wrapper needed.
    """
    host     = manifest.get("host") or {}
    hostname = host.get("hostname") or "unknown"
    coll_at  = manifest.get("collected_at", "")
    overall  = getattr(readiness, "overall_score", "?")

    body = (
        _section_overview(manifest, readiness)
        + _section_restore_sequence(graph, readiness)
        + _section_component_details(graph, readiness)
        + _section_recovery_readiness(graph, readiness)
        + _section_generation_report(graph, readiness, generation_meta)
    )

    return html_page(
        title=f"Recovery Workbook — {hostname}",
        body=body,
        doc_id=f"recovery-workbook-{hostname}",
        meta=f"Assessment: {coll_at}  ·  Overall: {overall}",
    )
