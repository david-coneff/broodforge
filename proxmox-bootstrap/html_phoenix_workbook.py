#!/usr/bin/env python3
"""
html_phoenix_workbook.py — HTML phoenix workbook renderer.

Produces a self-contained HTML workbook for phoenix restoration tracking.
One section per restoration wave with progress checkboxes.

Public API:
  build_phoenix_workbook_html(playbook) → str

Stdlib only.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'doc-gen', 'renderers'))

from html_base import (
    html_page, h, p, pre, code, dl, table, divider,
    callout, section, score_badge,
    checkbox_list, reset_checkbox_counter,
)


def _str(v) -> str:
    if v is None:
        return "[UNRESOLVED]"
    if isinstance(v, list):
        return ", ".join(str(x) for x in v) if v else "(none)"
    return str(v)


def _e(text) -> str:
    from html import escape
    return escape(str(text))


def _section_overview(playbook: dict) -> str:
    node     = playbook.get("target_node") or {}
    identity = playbook.get("identity") or {}
    scope    = playbook.get("restoration_scope") or "full"
    waves    = playbook.get("waves") or []
    est_min  = playbook.get("estimated_total_minutes") or 0

    pairs = [
        ("Cell ID",             playbook.get("cell_id") or "?"),
        ("Node hostname",       node.get("hostname") or "?"),
        ("Node role",           node.get("role") or "?"),
        ("Restoration scope",   scope),
        ("Waves",               str(len(waves))),
        ("Estimated runtime",   f"{est_min} minutes"),
        ("LAN IP",              identity.get("lan_ip") or "?"),
        ("ZFS pool",            identity.get("zfs_pool_name") or "?"),
        ("VMIDs",               _str(identity.get("vmids") or [])),
        ("Generated",           playbook.get("generated_at") or "?"),
    ]
    return section("Overview", dl(pairs), open_=True)


def _section_preflight(playbook: dict) -> str:
    hostname = (playbook.get("target_node") or {}).get("hostname") or "node"
    items = [
        "Phoenix package extracted on replacement hardware",
        f"Target hostname confirmed as: {hostname}",
        "KeePass database accessible (embedded or at path)",
        "Backup server (PBS) reachable from this host",
        "All wave scripts present: ls *.sh",
        "lib/checkpoint.sh present",
    ]
    body = p("Complete all preflight checks before running run-all.sh.")
    body += checkbox_list(items, id_prefix="preflight")
    return section("Pre-flight Checks", body, open_=True)


def _section_wave(wave: dict) -> str:
    wave_num  = wave.get("wave", "?")
    wave_name = wave.get("name") or ""
    est_min   = wave.get("estimated_minutes")
    steps     = wave.get("steps") or []
    prereqs   = wave.get("prerequisites") or []
    desc      = wave.get("description") or ""

    script_name = f"phase-{str(wave_num).replace('.', '-')}-{wave_name.lower().replace(' ', '-')}.sh"

    header_pairs = [("Script", script_name)]
    if est_min:
        header_pairs.append(("Estimated", f"{est_min} minutes"))
    if prereqs:
        header_pairs.append(("Prerequisites", _str(prereqs)))

    body = ""
    if desc:
        body += p(_e(desc))
    body += dl(header_pairs)
    body += pre(f"bash {script_name}")

    step_items = [
        f"Step {s.get('id', '?')}: {s.get('action', '')}"
        for s in steps
    ]
    if step_items:
        body += checkbox_list(step_items, id_prefix=f"wave-{wave_num}")
    else:
        body += checkbox_list([f"Wave {wave_num} complete"], id_prefix=f"wave-{wave_num}")

    body += checkbox_list([f"Wave {wave_num} — {wave_name} complete"], id_prefix=f"wave-{wave_num}-done")

    title = f"Wave {wave_num} — {wave_name}"
    if est_min:
        title += f" (~{est_min}m)"
    return section(title, body, open_=True)


def _section_final_validation(playbook: dict) -> str:
    hostname  = (playbook.get("target_node") or {}).get("hostname") or "node"
    checklist = playbook.get("validation_checklist") or [
        "All VMs running: qm list",
        f"Node {hostname} in k3s cluster: kubectl get nodes",
        "Flux reconciled: flux get all",
        "bootstrap-state.json updated and committed to Forgejo",
        "Phoenix workbook committed to Forgejo",
        "Hatchery assessment run: python3 proxmox-bootstrap/continuous_assessment.py",
    ]
    body = p("Final validation confirms the node is fully restored and reintegrated.")
    body += checkbox_list(list(checklist), id_prefix="final-valid")
    return section("Final Validation", body, open_=True)


def build_phoenix_workbook_html(playbook: dict) -> str:
    """Build a self-contained HTML phoenix restoration workbook."""
    reset_checkbox_counter()

    node     = playbook.get("target_node") or {}
    cell_id  = playbook.get("cell_id") or "unknown"
    hostname = node.get("hostname") or "unknown"
    gen_at   = playbook.get("generated_at") or "?"
    scope    = playbook.get("restoration_scope") or "full"
    waves    = playbook.get("waves") or []

    title = f"Phoenix Workbook — {hostname}"
    meta  = f"Cell: {cell_id}  |  Scope: {scope}  |  Generated: {gen_at}"

    body = ""
    body += p(
        "This workbook tracks phoenix restoration progress. "
        "Check each item as it completes. State is saved in the browser (localStorage)."
    )
    body += callout(
        "danger",
        "WARNING: This package reconstitutes a failed node. "
        "All existing data on the target host will be destroyed. "
        "Confirm this is the correct package before running.",
    )
    body += divider()
    body += _section_overview(playbook)
    body += _section_preflight(playbook)

    for wave in sorted(waves, key=lambda w: w.get("wave", 0)):
        body += _section_wave(wave)

    body += _section_final_validation(playbook)

    return html_page(title, body, doc_id=f"phoenix-workbook-{cell_id}-{hostname}", meta=meta)
