#!/usr/bin/env python3
"""
doc-gen/engine.py — Documentation Generation Engine

Usage:
    python3 doc-gen/engine.py --mode bootstrap --archive <bootstrap_*.tar.gz>
    python3 doc-gen/engine.py --mode bootstrap --manifest <manifest.json>

Outputs (bootstrap mode):
    reports/<id>/Bootstrap-Workbook.ods
    reports/<id>/Bootstrap-Runbook.odt
    reports/<id>/generation-report.md
"""

import argparse
import json
import os
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "doc-gen"))
sys.path.insert(0, str(REPO_ROOT / "doc-gen" / "renderers"))
sys.path.insert(0, str(REPO_ROOT / "data-model"))

from drift import compute_drift
from timestamps import format_doc_timestamp, format_doc_timestamp_from_iso, now_utc_iso


def _load_history_snapshot(tier: int) -> tuple[dict | None, str | None]:
    """
    Load the latest historical manifest for the given tier from history/index.json.
    Returns (manifest_dict, snapshot_id) or (None, None) if unavailable.
    """
    index_path = REPO_ROOT / "history" / "index.json"
    if not index_path.exists():
        return None, None
    try:
        index = json.loads(index_path.read_text())
    except Exception:
        return None, None

    key = "latest_tier1_id" if tier == 1 else "latest_tier2_id"
    snap_id = index.get(key)
    if not snap_id:
        return None, None

    snap_entry = next((s for s in index.get("snapshots", []) if s["id"] == snap_id), None)
    if not snap_entry:
        return None, None

    manifest_path = REPO_ROOT / snap_entry["manifest_path"]
    if not manifest_path.exists():
        return None, None

    try:
        return json.loads(manifest_path.read_text()), snap_id
    except Exception:
        return None, None


def _load_manifest(args) -> tuple[dict, str]:
    """Load manifest from archive or direct file. Returns (manifest, assessment_id)."""
    if args.manifest:
        path = Path(args.manifest)
        manifest = json.loads(path.read_text())
        assessment_id = path.parent.name or path.stem
        return manifest, assessment_id

    archive_path = Path(args.archive)
    if not archive_path.exists():
        print(f"Error: archive not found: {archive_path}", file=sys.stderr)
        sys.exit(1)

    assessment_id = archive_path.stem  # bootstrap_2026-05-30_15_00_00
    tmpdir = Path(tempfile.mkdtemp())

    with tarfile.open(archive_path, "r:gz") as tf:
        tf.extractall(tmpdir)

    # Find manifest.json inside extracted dir
    candidates = list(tmpdir.rglob("manifest.json"))
    if not candidates:
        print("Error: manifest.json not found in archive", file=sys.stderr)
        sys.exit(1)

    manifest = json.loads(candidates[0].read_text())
    return manifest, assessment_id


def _resolve_fields(manifest: dict) -> tuple[dict, dict]:
    """
    Resolve all fields from the manifest and analyzers.

    Returns:
        resolved  — {field_id: {"value": ..., "class": ..., "note": ...}}
        meta      — generation metadata for the report
    """
    import analyzers as az

    resolved: dict = {}
    unresolved_list: list = []
    human_list: list = []

    def _get_nested(path: str, default=None):
        parts = path.split(".")
        obj = manifest
        for p in parts:
            if not isinstance(obj, dict):
                return default
            obj = obj.get(p, default)
        return obj

    def _format_value(val, fmt: str = None):
        if val is None:
            return None
        if fmt and fmt != "list" and fmt != "join" and fmt != "kv":
            try:
                return fmt.replace("{value}", str(val))
            except Exception:
                return str(val)
        return val

    # -----------------------------------------------------------------------
    # AUTO fields — direct manifest lookups
    # -----------------------------------------------------------------------
    AUTO_FIELDS = {
        "host.hostname":         "host.hostname",
        "host.fqdn":             "host.fqdn",
        "host.proxmox_version":  "host.proxmox_version",
        "host.kernel_version":   "host.kernel_version",
        "host.timezone":         "host.timezone",
        "cpu.model":             "cpu.model",
        "cpu.total_threads":     "cpu.total_threads",
        "cpu.sockets":           "cpu.sockets",
        "cpu.cores_per_socket":  "cpu.cores_per_socket",
        "cpu.threads_per_core":  "cpu.threads_per_core",
        "cpu.architecture":      "cpu.architecture",
        "cpu.virtualization":    "cpu.virtualization",
        "memory.total_gb":       "memory.total_gb",
        "memory.available_gb":   "memory.available_gb",
        "memory.swap_total_gb":  "memory.swap_total_gb",
        "memory.numa_nodes":     "memory.numa_nodes",
        "network.default_gateway": "network.default_gateway",
        "network.dns_servers":   "network.dns_servers",
    }

    for field_id, path in AUTO_FIELDS.items():
        val = _get_nested(path)
        if val is not None:
            resolved[field_id] = {
                "value": str(val) if not isinstance(val, (list, dict)) else val,
                "class": "AUTO",
                "note":  f"From manifest: {path}",
            }
        else:
            resolved[field_id] = {
                "value": "(not detected)",
                "class": "UNRESOLVED",
                "note":  f"Field '{path}' was not populated during assessment",
            }
            unresolved_list.append({
                "id": field_id,
                "reason": f"Not populated during assessment ({path})",
                "impact": "LOW",
                "guidance": "Re-run bootstrap assessment as root for full data",
            })

    # Format list fields for display
    dns = _get_nested("network.dns_servers") or []
    resolved["network.dns_servers"]["value"] = ", ".join(dns) if dns else "(none)"

    # -----------------------------------------------------------------------
    # DERIVED fields — analyzer results
    # -----------------------------------------------------------------------
    DERIVED_FIELDS = {
        "derived.zfs_topology":       "storage.zfs_topology",
        "derived.storage_pool_name":  "storage.pool_name",
        "derived.vm_id":              "vm_ids.next_available",
        "derived.vm_id_sequence":     "vm_ids.sequence_4",
        "derived.vm_ram":             "vm_sizing.infra_bootstrap_ram",
        "derived.vm_cores":           "vm_sizing.infra_bootstrap_cores",
        "derived.vm_disk":            "vm_sizing.infra_bootstrap_disk",
        "derived.vm_bridge":          "network.recommend_bridge",
        "derived.vm_ip_plan":         "network.recommend_ip_plan",
        "derived.vm_storage_pool":    "storage.pool_name",
        "derived.automation_summary": "software.automation_readiness",
    }

    for field_id, analyzer_id in DERIVED_FIELDS.items():
        result = az.run(analyzer_id, manifest)
        if result.value == "UNRESOLVED":
            resolved[field_id] = {
                "value": "UNRESOLVED",
                "class": "UNRESOLVED",
                "note":  result.rationale,
                "warnings": result.warnings,
            }
            unresolved_list.append({
                "id": field_id,
                "reason": result.rationale,
                "impact": "MEDIUM" if result.confidence == "LOW" else "LOW",
                "guidance": "Review analyzer logic or provide missing manifest data",
            })
        else:
            resolved[field_id] = {
                "value": result.value,
                "class": "DERIVED",
                "note":  result.rationale
                         + (f"  ⚠ {'; '.join(result.warnings)}" if result.warnings else ""),
                "warnings": result.warnings,
                "confidence": result.confidence,
            }

    # -----------------------------------------------------------------------
    # HUMAN fields — placeholders with prompts
    # -----------------------------------------------------------------------
    HUMAN_FIELDS = [
        ("human.root_password_location",
         "Enter KeePass path for root password, e.g. Infrastructure/proxmox/pve01-root"),
        ("human.recovery_passphrase",
         "Enter KeePass path for disk encryption passphrase (if applicable)"),
        ("human.vm_ip_address",
         f"Enter static IP for infra-bootstrap VM. Suggested: {resolved.get('derived.vm_ip_plan', {}).get('value', 'see Stage 01')}"),
        ("human.vm_name",          "Enter VM name (recommended: infra-bootstrap)"),
        ("human.vm_username",      "Enter OS username (recommended: ubuntu)"),
        ("human.vm_password_location", "Enter KeePass path for VM password"),
        ("human.iso_location",
         "Enter ISO path in Proxmox, e.g. local:iso/ubuntu-22.04-live-server-amd64.iso"),
    ]

    for field_id, prompt in HUMAN_FIELDS:
        resolved[field_id] = {
            "value": None,
            "class": "HUMAN",
            "note":  prompt,
        }
        human_list.append({"id": field_id, "prompt": prompt})

    # -----------------------------------------------------------------------
    # Count by class
    # -----------------------------------------------------------------------
    counts: dict = {"AUTO": 0, "DERIVED": 0, "HUMAN": 0, "UNRESOLVED": 0}
    for entry in resolved.values():
        c = entry.get("class", "UNRESOLVED")
        counts[c] = counts.get(c, 0) + 1

    collected_at = manifest.get("collected_at", "unknown")
    meta = {
        "generated_at":         now_utc_iso(),
        "generated_at_display": format_doc_timestamp(),
        "collected_at":    collected_at,
        "tier":            manifest.get("assessment_tier", 1),
        "template_version": "bootstrap-v1.0",
        "field_counts":    counts,
        "unresolved_fields": unresolved_list,
        "human_fields":    human_list,
    }

    return resolved, meta


def _write_generation_report(out_dir: Path, manifest: dict,
                              resolved: dict, meta: dict) -> None:
    counts = meta["field_counts"]
    total  = sum(counts.values())

    def pct(n):
        return f"{100*n//total}%" if total else "0%"

    lines = [
        "# Documentation Generation Report",
        "",
        f"Generated:        {meta.get('generated_at_display', meta['generated_at'])}",
        f"Mode:             bootstrap",
        f"Assessment tier:  {meta['tier']}",
        f"Assessment date:  {meta['collected_at']}",
        f"Template version: {meta['template_version']}",
        f"Host:             {manifest.get('host', {}).get('hostname', 'unknown')}",
        "",
        "## Field Summary",
        "",
        f"Total fields: {total}",
    ]
    for cls_name in ("AUTO", "DERIVED", "HUMAN", "UNRESOLVED"):
        n = counts.get(cls_name, 0)
        lines.append(f"  {cls_name:<12} {n:3d}  ({pct(n)})")

    unresolved = meta.get("unresolved_fields", [])
    if unresolved:
        lines += ["", f"## Unresolved Fields ({len(unresolved)})", ""]
        for uf in unresolved:
            lines += [
                f"### {uf['id']}",
                f"Reason:   {uf.get('reason', 'N/A')}",
                f"Impact:   {uf.get('impact', 'unknown')}",
                f"Guidance: {uf.get('guidance', 'N/A')}",
                "",
            ]

    human_fields = meta.get("human_fields", [])
    if human_fields:
        lines += [f"## Human Input Required ({len(human_fields)})", ""]
        for hf in human_fields:
            lines += [f"- {hf['id']}: {hf.get('prompt', '')}"]

    drift = meta.get("drift")
    if drift and drift["diffs"]:
        lines += [
            "",
            f"## Drift Since Last Assessment (severity: {drift['drift_severity']})",
            f"Compared: {drift['from_snapshot']} → {drift['to_snapshot']}",
            "",
        ]
        for d in drift["diffs"][:20]:  # cap at 20 for readability
            lines.append(
                f"- [{d['severity']}] {d['path']}: "
                f"{d['from_value']!r} → {d['to_value']!r}"
            )
        if len(drift["diffs"]) > 20:
            lines.append(f"  ... and {len(drift['diffs']) - 20} more field(s)")
    elif drift:
        lines += ["", "## Drift Since Last Assessment", "No field changes detected."]

    lines += [
        "",
        "## Derived Recommendations",
        "",
    ]
    for fid in ("derived.zfs_topology", "derived.vm_id", "derived.vm_ram",
                "derived.vm_cores", "derived.vm_disk", "derived.vm_bridge",
                "derived.vm_ip_plan"):
        entry = resolved.get(fid, {})
        lines.append(f"- {fid}: {entry.get('value', 'N/A')}")
        if entry.get("note"):
            lines.append(f"  Rationale: {entry['note']}")
        for w in entry.get("warnings", []):
            lines.append(f"  ⚠ {w}")

    (out_dir / "generation-report.md").write_text("\n".join(lines), encoding="utf-8")


def run_bootstrap(args):
    print("[doc-gen] Loading manifest...")
    manifest, assessment_id = _load_manifest(args)

    out_dir = REPO_ROOT / "reports" / f"bootstrap_{assessment_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Drift detection — compare against previous tier 1 snapshot if available
    drift_record = None
    prior_manifest, prior_snap_id = _load_history_snapshot(tier=1)
    if prior_manifest is not None and prior_snap_id != assessment_id:
        print(f"[doc-gen] Computing drift against snapshot: {prior_snap_id}")
        drift_record = compute_drift(prior_manifest, manifest, prior_snap_id, assessment_id)
        print(f"[doc-gen]   Drift: {len(drift_record['diffs'])} field(s) changed  "
              f"severity={drift_record['drift_severity']}")
    else:
        print("[doc-gen] No prior bootstrap snapshot — drift detection skipped")

    print("[doc-gen] Resolving fields...")
    resolved, meta = _resolve_fields(manifest)
    meta["drift"] = drift_record

    counts = meta["field_counts"]
    total  = sum(counts.values())
    print(f"[doc-gen] Fields: {total} total  "
          f"AUTO={counts['AUTO']}  DERIVED={counts['DERIVED']}  "
          f"HUMAN={counts['HUMAN']}  UNRESOLVED={counts['UNRESOLVED']}")

    print("[doc-gen] Rendering workbook...")
    from workbook import build_bootstrap_workbook
    ods_bytes = build_bootstrap_workbook(manifest, resolved, meta)
    ods_path = out_dir / "Bootstrap-Workbook.ods"
    ods_path.write_bytes(ods_bytes)
    print(f"[doc-gen]   → {ods_path}  ({len(ods_bytes):,} bytes)")

    print("[doc-gen] Rendering runbook...")
    from runbook import build_bootstrap_runbook
    odt_bytes = build_bootstrap_runbook(manifest, resolved, meta)
    odt_path = out_dir / "Bootstrap-Runbook.odt"
    odt_path.write_bytes(odt_bytes)
    print(f"[doc-gen]   → {odt_path}  ({len(odt_bytes):,} bytes)")

    print("[doc-gen] Writing generation report...")
    _write_generation_report(out_dir, manifest, resolved, meta)
    rpt_path = out_dir / "generation-report.md"
    print(f"[doc-gen]   → {rpt_path}")

    unresolved_count = counts["UNRESOLVED"]
    human_count      = counts["HUMAN"]

    print("")
    print("=" * 60)
    print(f"  Bootstrap documentation generated: {out_dir}")
    print(f"  AUTO fields populated:   {counts['AUTO']} / {total}")
    print(f"  DERIVED recommendations: {counts['DERIVED']}")
    print(f"  HUMAN input required:    {human_count} field(s)")
    if unresolved_count:
        print(f"  UNRESOLVED fields:       {unresolved_count} — see generation-report.md")
    print("=" * 60)
    print("")
    print("  Open Bootstrap-Workbook.ods to review and complete HUMAN fields.")
    print("  Open Bootstrap-Runbook.odt  to follow the step-by-step procedure.")


def _load_bootstrap_state(repo_root: Path) -> dict:
    """
    Load bootstrap-state.json from the proxmox-bootstrap directory if present.
    Returns an empty dict if not found — callers treat missing keys as unset.
    """
    candidates = [
        repo_root / "proxmox-bootstrap" / "bootstrap-state.json",
        repo_root / "tests" / "fixtures" / "bootstrap" / "bootstrap-state.json",
    ]
    for path in candidates:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
    return {}


def run_recovery(args):
    print("[doc-gen] Loading manifest...")
    manifest, assessment_id = _load_manifest(args)

    tier = manifest.get("assessment_tier", 1)
    if tier == 1:
        print("WARNING: Tier 1 manifest detected. Recovery mode works best with Tier 2 assessment.",
              file=sys.stderr)
        print("         Continuing with available data — backup inventory will be unavailable.")

    out_dir = REPO_ROOT / "reports" / f"recovery_{assessment_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load external_backup config from bootstrap-state (if available) and
    # merge into manifest so the runbook renderer can emit a pre-populated
    # Step 0 (how to obtain bootstrap state on a fresh recovery host).
    bootstrap_state = _load_bootstrap_state(REPO_ROOT)
    if bootstrap_state.get("external_backup"):
        manifest["external_backup"] = bootstrap_state["external_backup"]
        print(f"[doc-gen] External backup provider: "
              f"{bootstrap_state['external_backup'].get('provider') or 'none'}")

    # Load secret and DNS registries from bootstrap-state
    # (secrets field in bootstrap-state.json, dns_registry field)
    _secrets = bootstrap_state.get("secrets") or bootstrap_state.get("secret_registry") or []
    if _secrets:
        manifest["secret_registry"] = _secrets
        print(f"[doc-gen] Secret registry: {len(_secrets)} entries")
    else:
        print("[doc-gen] Secret registry: not found in bootstrap-state (runbook will use placeholders)")

    _dns = bootstrap_state.get("dns_registry") or []
    if _dns:
        manifest["dns_registry"] = _dns
        print(f"[doc-gen] DNS registry: {len(_dns)} entries")
    else:
        print("[doc-gen] DNS registry: not found in bootstrap-state (runbook will use [VM_IP] placeholders)")

    print("[doc-gen] Building dependency graph...")
    sys.path.insert(0, str(REPO_ROOT / "doc-gen"))
    import dependencies as dep_mod
    import readiness as rdns_mod

    graph = dep_mod.build_graph(manifest)
    print(f"[doc-gen]   Nodes: {len(graph.nodes)}  Edges: {len(graph.edges)}  "
          f"Waves: {len(graph.restore_waves)}")

    print("[doc-gen] Scoring readiness...")
    readiness = rdns_mod.score_graph(graph, manifest)
    print(f"[doc-gen]   Overall: {readiness.overall_score}  "
          f"— {readiness.overall_score_reason}")

    # Component score summary
    from collections import Counter
    score_counts = Counter(c.score for c in readiness.components)
    for sc in ("GREEN", "YELLOW", "ORANGE", "RED", "BLOCKED"):
        n = score_counts.get(sc, 0)
        if n:
            print(f"[doc-gen]   {sc}: {n}")

    # Drift detection — compare against previous tier 2 snapshot if available
    drift_record = None
    prior_manifest, prior_snap_id = _load_history_snapshot(tier=2)
    if prior_manifest is not None and prior_snap_id != assessment_id:
        print(f"[doc-gen] Computing drift against snapshot: {prior_snap_id}")
        drift_record = compute_drift(prior_manifest, manifest, prior_snap_id, assessment_id)
        print(f"[doc-gen]   Drift: {len(drift_record['diffs'])} field(s) changed  "
              f"severity={drift_record['drift_severity']}")
    else:
        print("[doc-gen] No prior tier 2 snapshot — drift detection skipped")

    collected_at = manifest.get("collected_at", "unknown")
    generation_meta = {
        "generated_at":         now_utc_iso(),
        "generated_at_display": format_doc_timestamp(),
        "collected_at":    collected_at,
        "tier":            tier,
        "template_version": "recovery-v1.0",
        "drift":           drift_record,
    }

    print("[doc-gen] Rendering recovery workbook...")
    from renderers.recovery_workbook import build_recovery_workbook
    ods_bytes = build_recovery_workbook(manifest, graph, readiness, generation_meta)
    ods_path = out_dir / "Recovery-Workbook.ods"
    ods_path.write_bytes(ods_bytes)
    print(f"[doc-gen]   → {ods_path}  ({len(ods_bytes):,} bytes)")

    print("[doc-gen] Rendering recovery runbook...")
    from renderers.recovery_runbook import build_recovery_runbook
    odt_bytes = build_recovery_runbook(manifest, graph, readiness, generation_meta)
    odt_path = out_dir / "Recovery-Runbook.odt"
    odt_path.write_bytes(odt_bytes)
    print(f"[doc-gen]   → {odt_path}  ({len(odt_bytes):,} bytes)")

    print("[doc-gen] Writing restore sequence...")
    seq_text = dep_mod.restore_sequence_text(graph, manifest)
    seq_path = out_dir / "Restore-Sequence.md"
    seq_path.write_text(seq_text, encoding="utf-8")
    print(f"[doc-gen]   → {seq_path}")

    print("[doc-gen] Writing readiness report...")
    import readiness_report as rr_mod
    rpt_json = rr_mod.build_readiness_report_json(manifest, graph, readiness, generation_meta)
    rpt_json_path = out_dir / "Readiness-Report.json"
    rpt_json_path.write_text(json.dumps(rpt_json, indent=2), encoding="utf-8")
    print(f"[doc-gen]   → {rpt_json_path}  ({rpt_json_path.stat().st_size:,} bytes)")

    rpt_md = rr_mod.build_readiness_report_md(manifest, graph, readiness, generation_meta)
    rpt_md_path = out_dir / "Readiness-Report.md"
    rpt_md_path.write_text(rpt_md, encoding="utf-8")
    print(f"[doc-gen]   → {rpt_md_path}")

    print("[doc-gen] Writing generation report...")
    _write_recovery_report(out_dir, manifest, graph, readiness, generation_meta)
    print(f"[doc-gen]   → {out_dir / 'generation-report.md'}")

    spof_count    = len(readiness.single_points_of_failure)
    blocker_count = len(readiness.recovery_blockers)
    all_gaps      = [g for c in readiness.components for g in c.gaps]

    print("")
    print("=" * 60)
    print(f"  Recovery documentation generated: {out_dir}")
    print(f"  Overall readiness: {readiness.overall_score}")
    print(f"  Components: {len(readiness.components)}  "
          f"Gaps: {len(all_gaps)}  Blockers: {blocker_count}  SPOFs: {spof_count}")
    print("=" * 60)
    print("")
    print("  Open Recovery-Workbook.ods  for the full infrastructure and readiness overview.")
    print("  Open Recovery-Runbook.odt   for step-by-step restore procedures.")
    print("  Open Restore-Sequence.md    for the dependency-ordered restore plan.")
    print("  Open Readiness-Report.md    for the prioritised readiness summary.")


def _write_recovery_report(out_dir, manifest, graph, readiness, meta):
    node_map = graph.node_map()
    all_gaps = [g for c in readiness.components for g in c.gaps]
    lines = [
        "# Recovery Documentation Generation Report",
        "",
        f"Generated:        {meta.get('generated_at_display', meta['generated_at'])}",
        f"Mode:             recovery",
        f"Assessment tier:  {meta['tier']}",
        f"Assessment date:  {meta['collected_at']}",
        f"Host:             {manifest.get('host', {}).get('hostname', 'unknown')}",
        "",
        "## Dependency Graph",
        f"  Nodes:          {len(graph.nodes)}",
        f"  Edges:          {len(graph.edges)}",
        f"  Restore waves:  {len(graph.restore_waves)}",
        f"  Estimated time: {sum(w.estimated_minutes or 0 for w in graph.restore_waves)} minutes",
        "",
        "## Restore Waves",
    ]
    for wave in graph.restore_waves:
        labels = [node_map[c].label for c in wave.component_ids if c in node_map]
        lines.append(f"  Wave {wave.wave}: {wave.note}")
        for l in labels:
            lines.append(f"    - {l}")

    lines += [
        "",
        "## Readiness",
        f"  Overall: {readiness.overall_score} — {readiness.overall_score_reason}",
    ]
    for c in readiness.components:
        node = node_map.get(c.component_id)
        label = node.label if node else c.component_id
        lines.append(f"  {c.score:<8} {label}")

    if readiness.single_points_of_failure:
        lines += ["", "## Single Points of Failure"]
        for sid in readiness.single_points_of_failure:
            node = node_map.get(sid)
            lines.append(f"  - {node.label if node else sid}")

    if all_gaps:
        lines += ["", f"## Gaps ({len(all_gaps)})"]
        for g in all_gaps:
            node = node_map.get(g.component_id)
            lines.append(
                f"  [{g.severity}] {node.label if node else g.component_id}: {g.description}"
            )

    drift = meta.get("drift")
    if drift and drift["diffs"]:
        lines += [
            "",
            f"## Drift Since Last Assessment (severity: {drift['drift_severity']})",
            f"Compared: {drift['from_snapshot']} → {drift['to_snapshot']}",
            "",
        ]
        for d in drift["diffs"][:20]:
            lines.append(
                f"  [{d['severity']}] {d['path']}: "
                f"{d['from_value']!r} → {d['to_value']!r}"
            )
        if len(drift["diffs"]) > 20:
            lines.append(f"  ... and {len(drift['diffs']) - 20} more field(s)")
    elif drift:
        lines += ["", "## Drift Since Last Assessment", "  No field changes detected."]

    (out_dir / "generation-report.md").write_text("\n".join(lines), encoding="utf-8")

def main():
    parser = argparse.ArgumentParser(
        description="Assessment Engine Documentation Generator"
    )
    parser.add_argument("--mode", required=True, choices=["bootstrap", "recovery"],
                        help="Documentation mode")
    parser.add_argument("--archive", help="Path to assessment .tar.gz archive")
    parser.add_argument("--manifest", help="Path to manifest.json directly")

    args = parser.parse_args()

    if not args.archive and not args.manifest:
        parser.error("Provide --archive or --manifest")

    if args.mode == "bootstrap":
        run_bootstrap(args)
    else:
        run_recovery(args)


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Recovery mode
# ---------------------------------------------------------------------------
