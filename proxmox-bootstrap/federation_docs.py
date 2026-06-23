#!/usr/bin/env python3
"""
federation_docs.py — Federation Documentation Generation (Phase 20).

Generates HTML documentation for the federation: multi-cell workbooks,
cell runbooks, dependency workbooks, command reference sheets, and
validation sheets.

All outputs are self-contained HTML using the broodforge checkbox behavior:
  checked → show " done" in italics; no strikethrough.

Provides:
  build_federation_workbook_html()  — federation overview + all cells + readiness
  build_cell_workbook_html()        — full 17-state view for a single cell
  build_dependency_workbook_html()  — cross-cell dependency graph overview
  build_validation_sheet_html()     — post-recovery checklists
  build_command_reference_html()    — pre-populated command reference

20.1  build_federation_workbook_html()
20.2  build_federation_runbook_html() (coordination procedures)
20.3  build_cell_workbook_html()
20.7  build_dependency_workbook_html()
20.8  build_command_reference_html()
20.9  build_validation_sheet_html()

Stdlib only.
"""

from federation_state import (
    FederationReadinessReport,
    FederationState,
    score_federation_readiness,
)
from html_base import (
    callout,
    checkbox_list,
    divider,
    dl,
    html_page,
    p,
    pre,
    reset_checkbox_counter,
    score_badge,
    section,
    table,
)


def _e(text: str) -> str:
    from html import escape
    return escape(str(text))


# ---------------------------------------------------------------------------
# 20.1 — Federation Workbook
# ---------------------------------------------------------------------------

def _section_cell_registry(federation: FederationState) -> str:
    rows = []
    for cell in federation.cells:
        rows.append([
            _e(cell.cell_id),
            _e(cell.hostname or "?"),
            _e(cell.fqdn or cell.endpoint or "—"),
            score_badge("GREEN" if cell.is_active else "RED"),
            _e(", ".join(cell.capabilities[:3]) + ("…" if len(cell.capabilities) > 3 else "")),
        ])
    body = table(["Cell ID", "Host", "Endpoint", "Status", "Capabilities (top 3)"], rows)
    return section("Cell Registry", body, open_=True)


def _section_trust_relationships(federation: FederationState) -> str:
    if not federation.trust_relationships:
        return section("Trust Relationships", callout("warn", "No trust relationships declared."), open_=True)

    rows = []
    for t in federation.trust_relationships:
        days_label = ""
        days = t.days_until_expiry
        if days is not None:
            if days <= 7:
                days_label = f"⚠ {days}d"
            elif days <= 30:
                days_label = f"▲ {days}d"
            else:
                days_label = f"{days}d"
        rows.append([
            _e(t.from_cell),
            _e(f"→[{t.relationship_type}]→"),
            _e(t.to_cell),
            score_badge("GREEN" if t.status == "active" else
                        ("RED" if t.status == "revoked" else "YELLOW")),
            _e(days_label or (t.expires_at or "never")),
        ])
    body = table(["From Cell", "Type", "To Cell", "Status", "Expires"], rows)
    return section("Trust Relationships", body, open_=True)


def _section_recovery_relationships(federation: FederationState) -> str:
    if not federation.recovery_relationships:
        return section("Recovery Relationships",
                       callout("warn", "No recovery relationships declared."), open_=True)

    rows = []
    for r in federation.recovery_relationships:
        rto = f"{r.rto_minutes}m" if r.rto_minutes else "—"
        rpo = f"{r.rpo_hours}h" if r.rpo_hours else "—"
        rows.append([
            _e(r.subject_cell),
            _e(f"→ {r.coordinator_cell}"),
            _e(str(len(r.backup_locations))),
            score_badge("GREEN" if r.status == "active" else
                        ("YELLOW" if r.status == "unverified" else "RED")),
            _e(rto), _e(rpo),
        ])
    body = table(["Subject Cell", "Coordinator", "Backup Locs", "Status", "RTO", "RPO"], rows)
    return section("Recovery Relationships", body, open_=True)


def _section_federation_readiness(report: FederationReadinessReport) -> str:
    rows = []
    for cs in report.cell_scores:
        rows.append([
            _e(cs.cell_id),
            score_badge(cs.score),
            _e(cs.reason),
            _e(", ".join(cs.coordinator_cells) or "none"),
        ])

    body = (
        p(f"Overall: {score_badge(report.overall_score)} — {_e(report.overall_reason)}") +
        p(f"Cells: {report.total_cells} total, {report.active_cells} active") +
        table(["Cell", "Score", "Reason", "Coordinators"], rows)
    )
    return section("Federation Readiness", body, open_=True)


def build_federation_workbook_html(
    federation: FederationState,
    readiness:  FederationReadinessReport | None = None,
    generation_meta: dict | None = None,
) -> str:
    """20.1 — Self-contained HTML federation overview workbook."""
    reset_checkbox_counter()
    if readiness is None:
        readiness = score_federation_readiness(federation)

    gen_at = (generation_meta or {}).get("generated_at_display") or "?"
    title  = f"Federation Workbook — {federation.federation_id}"
    meta   = f"{federation.federation_name or ''}  |  Generated: {gen_at}".strip(" |")

    body = ""
    body += p(f"Federation ID: {_e(federation.federation_id)}")
    body += p("This workbook tracks federation readiness: cell registry, trust, and recovery relationships.")
    body += divider()
    body += _section_federation_readiness(readiness)
    body += _section_cell_registry(federation)
    body += _section_trust_relationships(federation)
    body += _section_recovery_relationships(federation)

    return html_page(title, body, doc_id=f"fed-{federation.federation_id}", meta=meta)


# ---------------------------------------------------------------------------
# 20.2 — Federation Runbook
# ---------------------------------------------------------------------------

def build_federation_runbook_html(
    federation: FederationState,
    readiness:  FederationReadinessReport | None = None,
    generation_meta: dict | None = None,
) -> str:
    """20.2 — Self-contained HTML federation coordination runbook."""
    reset_checkbox_counter()
    if readiness is None:
        readiness = score_federation_readiness(federation)

    gen_at = (generation_meta or {}).get("generated_at_display") or "?"
    title  = f"Federation Runbook — {federation.federation_id}"
    meta   = f"Generated: {gen_at}"

    body = ""
    body += p(f"Overall: {score_badge(readiness.overall_score)} — {_e(readiness.overall_reason)}")
    body += divider()

    # Pre-recovery coordination
    coord_items = [
        "Confirm which cell has failed",
        "Identify recovery coordinator(s) from Recovery Relationships table",
        "Contact coordinator cell operator if different operator",
        "Confirm backup last-backup-at is within RPO window",
        "Confirm coordinator cell has sufficient capacity for workload migration",
    ]
    body += section("Step 1 — Pre-Recovery Coordination",
                    checkbox_list(coord_items, id_prefix="fed-coord"), open_=True)

    # Per-coordinator recovery steps
    for cell in federation.cells:
        coordinators = federation.coordinators_for(cell.cell_id)
        if not coordinators:
            continue
        items = [
            f"Coordinator {_e(c)} confirms backup availability" for c in coordinators
        ] + [
            f"Trust relationship {_e(cell.cell_id)} ↔ {_e(c)} valid" for c in coordinators
        ] + [
            f"Restore {_e(cell.cell_id)} at coordinator site",
            f"Verify all services on {_e(cell.cell_id)} healthy",
            f"Update federation state: {_e(cell.cell_id)} status → active",
        ]
        body += section(f"Cell Recovery: {cell.cell_id}",
                        checkbox_list(items, id_prefix=f"rec-{cell.cell_id}"), open_=False)

    # Post-recovery
    post_items = [
        "Update federation-state.json with recovery outcome",
        "Rotate trust relationship keys (if applicable)",
        "Run Tier 3 assessment to confirm GREEN",
        "Document RTO and RPO achieved",
        "Schedule post-recovery review",
    ]
    body += section("Step N — Post-Recovery", checkbox_list(post_items, id_prefix="post-rec"), open_=False)

    return html_page(title, body, doc_id=f"fed-runbook-{federation.federation_id}", meta=meta)


# ---------------------------------------------------------------------------
# 20.3 — Cell Workbook (17-state view)
# ---------------------------------------------------------------------------

_STATE_CATEGORIES = [
    ("Hardware State",       "hardware_state"),
    ("Platform State",       "platform_state"),
    ("Cluster State",        "cluster_state"),
    ("Storage State",        "storage_state"),
    ("Data Protection State","data_protection_state"),
    ("Observability State",  "observability_state"),
    ("Service State",        "service_state"),
    ("Bootstrap State",      "bootstrap_state"),
    ("Network Topology",     "network_topology"),
    ("Capability State",     "capability_state"),
    ("Secret References",    "secret_reference_state"),
    ("External Dependencies","external_dependencies"),
    ("Backup Config",        "backup_config"),
    ("Digital Twin",         "twin_state"),
    ("Federation State",     "federation_state"),
    ("Reconstruction Drills","reconstruction_drills"),
    ("Capacity Model",       "capacity_model"),
]


def build_cell_workbook_html(
    cell_id:         str,
    state_docs:      dict | None = None,   # {state_category_key: dict}
    generation_meta: dict | None = None,
) -> str:
    """20.3 — Full 17-state view for a single cell."""
    reset_checkbox_counter()

    state_docs  = state_docs or {}
    gen_at      = (generation_meta or {}).get("generated_at_display") or "?"
    title       = f"Cell Workbook — {cell_id}"
    meta        = f"Generated: {gen_at}"

    body = ""
    body += p(f"Full 17-category state view for cell {_e(cell_id)}.")
    body += divider()

    rows = []
    for label, key in _STATE_CATEGORIES:
        doc      = state_docs.get(key)
        status   = "Present" if doc else "Missing"
        badge    = score_badge("GREEN" if doc else "YELLOW")
        last_col = _e(str(doc.get("collected_at") or doc.get("declared_at") or "?")[:19]
                      if doc else "—")
        rows.append([badge, _e(label), _e(status), last_col])

    body += section("State Coverage",
                    table(["Status", "State Category", "Present?", "Last Updated"], rows),
                    open_=True)

    # Per-category sections
    for label, key in _STATE_CATEGORIES:
        doc = state_docs.get(key)
        if doc:
            pairs = [(k, str(v)[:100]) for k, v in doc.items()
                     if k not in ("schema_version", "cell_id")
                     and isinstance(v, (str, int, float, bool))
                     and v is not None][:10]
            content = dl(pairs) if pairs else p("(no displayable fields)")
        else:
            content = callout("warn", f"No {label} data available.")
        body += section(label, content, open_=False)

    return html_page(title, body, doc_id=f"cell-workbook-{cell_id}", meta=meta)


# ---------------------------------------------------------------------------
# 20.7 — Dependency Workbook
# ---------------------------------------------------------------------------

def build_dependency_workbook_html(
    federation:     FederationState,
    cell_graphs:    dict | None = None,   # {cell_id: graph_description_str}
    generation_meta: dict | None = None,
) -> str:
    """20.7 — Cross-cell dependency graph overview."""
    reset_checkbox_counter()

    cell_graphs = cell_graphs or {}
    gen_at      = (generation_meta or {}).get("generated_at_display") or "?"
    title       = f"Dependency Workbook — {federation.federation_id}"

    body = ""
    body += p(f"Cross-cell dependency graph for federation {_e(federation.federation_id)}.")
    body += divider()

    # Recovery dependencies
    rows = []
    for r in federation.recovery_relationships:
        for loc in r.backup_locations:
            rows.append([
                _e(r.subject_cell),
                _e(r.coordinator_cell),
                _e(loc.get("type") or "?"),
                _e(loc.get("remote") or loc.get("path") or "—"),
            ])
    if rows:
        body += section("Recovery Dependencies",
                        table(["Subject Cell", "Coordinator", "Backup Type", "Location"], rows),
                        open_=True)

    # Per-cell dependency graphs
    for cell in federation.cells:
        graph_str = cell_graphs.get(cell.cell_id)
        if graph_str:
            body += section(f"Dependency Graph: {cell.cell_id}", pre(graph_str), open_=False)
        else:
            body += section(f"Dependency Graph: {cell.cell_id}",
                            p(f"No dependency graph available for {cell.cell_id}."),
                            open_=False)

    return html_page(title, body, doc_id=f"dep-workbook-{federation.federation_id}", meta=gen_at)


# ---------------------------------------------------------------------------
# 20.8 — Command Reference Sheet
# ---------------------------------------------------------------------------

def build_command_reference_html(
    cell_id:    str,
    manifest:   dict | None = None,
    generation_meta: dict | None = None,
) -> str:
    """20.8 — Pre-populated command reference for a cell."""
    reset_checkbox_counter()

    manifest = manifest or {}
    gen_at   = (generation_meta or {}).get("generated_at_display") or "?"
    title    = f"Command Reference — {cell_id}"
    hi       = manifest.get("host_identity") or {}
    dns_reg  = manifest.get("dns_registry") or []
    hostname = hi.get("hostname") or "HATCHERY"

    def _vm_ip(name: str) -> str:
        for e in dns_reg:
            if e.get("hostname", "").startswith(name):
                return e.get("ip") or "VM_IP"
        return "VM_IP"

    body = ""
    body += p("Pre-populated commands derived from bootstrap-state.json. Verify before use.")
    body += divider()

    # Proxmox commands
    pve_cmds = [
        "# Proxmox cluster status",
        "pvecm status",
        "qm list",
        f"pvesh get /nodes/{hostname}/tasks --limit 20",
        "zpool list && zfs list",
    ]
    body += section("Proxmox Host Commands", pre("\n".join(pve_cmds)), open_=True)

    # k3s commands
    k3s_cmds = [
        "kubectl get nodes -o wide",
        "kubectl get pods -A",
        "flux get all",
        "k3s kubectl get events -A --sort-by='.lastTimestamp' | tail -20",
    ]
    body += section("k3s / Kubernetes Commands", pre("\n".join(k3s_cmds)), open_=True)

    # Assessment engine
    assess_cmds = [
        "python3 engine.py --mode bootstrap",
        "python3 engine.py --mode recovery",
        "python3 engine.py --mode operational",
    ]
    body += section("Assessment Engine Commands", pre("\n".join(assess_cmds)), open_=False)

    # KeePass
    kp_cmds = [
        "keepassxc-cli open /etc/broodforge/keepass.kdbx",
        "keepassxc-cli show /etc/broodforge/keepass.kdbx Infrastructure/headscale/api-key",
        "keepassxc-cli show /etc/broodforge/keepass.kdbx k3s/join-token-server",
    ]
    body += section("KeePass Commands", pre("\n".join(kp_cmds)), open_=False)

    # Backup commands
    backup_cmds = [
        "python3 run-backup.py --layer secrets",
        "python3 run-backup.py --layer config",
        "python3 run-backup.py --dry-run",
        "python3 restore-from-backup.py --list",
        "python3 restore-from-backup.py --latest",
    ]
    body += section("Backup Commands", pre("\n".join(backup_cmds)), open_=False)

    return html_page(title, body, doc_id=f"cmd-ref-{cell_id}", meta=f"Cell: {cell_id}  |  {gen_at}")


# ---------------------------------------------------------------------------
# 20.9 — Validation Sheet
# ---------------------------------------------------------------------------

def build_validation_sheet_html(
    title_suffix: str,
    checklist:    list[str | tuple],
    manifest:     dict | None     = None,
    generation_meta: dict | None  = None,
) -> str:
    """
    20.9 — Post-recovery validation checklist.

    title_suffix: e.g. "Post-Recovery — pve01-cell" or "Spawn — broodling01"
    checklist:    list of items (str or (label, item_id) tuples)
    """
    reset_checkbox_counter()

    manifest = manifest or {}
    gen_at   = (generation_meta or {}).get("generated_at_display") or "?"
    cell_id  = manifest.get("cell_id") or "unknown"
    title    = f"Validation Sheet — {title_suffix}"

    body = ""
    body += p("Post-operation validation checklist. Check each item as confirmed.")
    body += divider()
    body += checkbox_list(checklist, id_prefix="valid")

    return html_page(title, body,
                     doc_id=f"validation-{title_suffix.replace(' ', '-').lower()}",
                     meta=f"Cell: {cell_id}  |  {gen_at}")
