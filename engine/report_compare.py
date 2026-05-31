"""
Declared vs Configured vs Observed comparison report generator.

Produces a Markdown report answering:
  - What resources are declared in OpenTofu / Terraform?
  - What hosts are configured in Ansible inventory?
  - What guests were actually observed?
  - Where do the three layers agree?
  - Where do they diverge?

All content is factual.  No recommendations are generated.
"""

from __future__ import annotations

from engine.compare import compare, ComparisonResult


def generate_comparison_report(assessment: dict) -> str:
    """Generate the Declared vs Configured vs Observed Markdown report."""
    result = compare(assessment)
    hostname = assessment.get("hostname", "unknown")
    timestamp = assessment.get("timestamp", "unknown")

    sections = [
        _header(hostname, timestamp),
        _state_layers(assessment),
        _summary_table(result),
        _matches(result),
        _declared_only(result),
        _observed_only(result),
        _configured_only(result),
        _declared_resources_table(result),
    ]
    return "\n\n".join(s for s in sections if s)


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def _header(hostname: str, timestamp: str) -> str:
    return (
        "# Declared vs Configured vs Observed Report\n\n"
        f"**Node:** {hostname}  \n"
        f"**Assessment timestamp:** {timestamp}"
    )


def _state_layers(assessment: dict) -> str:
    ss = assessment.get("state_sources") or {}
    declared = ss.get("declared") or {}
    configured = ss.get("configured") or {}
    observed = ss.get("observed") or {}

    lines = [
        "## State Layer Sources", "",
        "| Layer | Tool | Collected | Detail |",
        "|-------|------|-----------|--------|",
        f"| Declared | {declared.get('tool') or '—'} "
        f"| {'yes' if declared.get('collected') else 'no'} "
        f"| {declared.get('state_path') or '—'} |",
        f"| Configured | {configured.get('tool') or '—'} "
        f"| {'yes' if configured.get('collected') else 'no'} "
        f"| {configured.get('inventory_path') or '—'} |",
        f"| Observed | {observed.get('tool') or 'broodforge'} "
        f"| {'yes' if observed.get('collected', True) else 'no'} | — |",
    ]
    return "\n".join(lines)


def _summary_table(result: ComparisonResult) -> str:
    s = result.summary()
    lines = [
        "## Summary", "",
        "| Metric | Count |",
        "|--------|-------|",
        f"| Declared resources | {s['declared_count']} |",
        f"| Configured hosts | {s['configured_count']} |",
        f"| Observed guests | {s['observed_count']} |",
        f"| Matched across layers | {s['matched_count']} |",
        f"| Declared only (not observed) | {s['declared_only_count']} |",
        f"| Observed only (not declared) | {s['observed_only_count']} |",
        f"| Configured only | {s['configured_only_count']} |",
    ]
    return "\n".join(lines)


def _matches(result: ComparisonResult) -> str:
    if not result.matches:
        return ""

    lines = [
        "## Matched Resources", "",
        "Resources present in two or more layers.", "",
        "| Name | Layers | Resource Type | Observed OS | Collection Method |",
        "|------|--------|---------------|-------------|-------------------|",
    ]
    for m in sorted(result.matches, key=lambda x: x.name):
        rtype = ""
        if m.declared:
            rtype = m.declared.get("resource_type", "")
        obs_os = ""
        coll = ""
        if m.observed:
            os_facts = m.observed.get("operating_system") or {}
            obs_os = f"{os_facts.get('distribution', '')} {os_facts.get('distribution_version', '')}".strip()
            coll = m.observed.get("collection_method", "")
        lines.append(
            f"| {m.name} | {m.layer_string()} | {rtype} | {obs_os} | {coll} |"
        )
    return "\n".join(lines)


def _declared_only(result: ComparisonResult) -> str:
    if not result.declared_only:
        return ""

    lines = [
        "## Declared but Not Observed", "",
        "Resources present in the OpenTofu / Terraform state but not found among observed guests.", "",
        "| Name | Resource Type | Target Node | VMID |",
        "|------|---------------|-------------|------|",
    ]
    for r in sorted(result.declared_only, key=lambda x: _resource_display_name(x)):
        attrs = r.get("attributes") or {}
        lines.append(
            f"| {_resource_display_name(r)} "
            f"| {r.get('resource_type', '')} "
            f"| {attrs.get('target_node', '')} "
            f"| {attrs.get('vmid', '')} |"
        )
    return "\n".join(lines)


def _observed_only(result: ComparisonResult) -> str:
    if not result.observed_only:
        return ""

    lines = [
        "## Observed but Not Declared", "",
        "Guests found by the assessment engine but absent from the OpenTofu / Terraform state.", "",
        "| Hostname | Groups | OS | Collection Method |",
        "|----------|--------|----|-------------------|",
    ]
    for g in sorted(result.observed_only, key=lambda x: x.get("hostname", "")):
        os_facts = g.get("operating_system") or {}
        os_str = f"{os_facts.get('distribution', '')} {os_facts.get('distribution_version', '')}".strip()
        groups = ", ".join(g.get("groups") or [])
        lines.append(
            f"| {g.get('hostname', '')} "
            f"| {groups} "
            f"| {os_str} "
            f"| {g.get('collection_method', '')} |"
        )
    return "\n".join(lines)


def _configured_only(result: ComparisonResult) -> str:
    if not result.configured_only:
        return ""

    lines = [
        "## Configured but Not Observed or Declared", "",
        "Hosts present in the Ansible inventory but neither declared in OpenTofu nor observed by the engine.", "",
        "| Hostname |",
        "|----------|",
    ]
    for h in sorted(result.configured_only):
        lines.append(f"| {h} |")
    return "\n".join(lines)


def _declared_resources_table(result: ComparisonResult) -> str:
    if not result.declared_resources:
        return ""

    lines = [
        "## All Declared Resources", "",
        "| Name | Resource Type | Module | Status | Target Node | VMID | Cores | Memory (MB) |",
        "|------|---------------|--------|--------|-------------|------|-------|-------------|",
    ]
    for r in sorted(result.declared_resources, key=lambda x: _resource_display_name(x)):
        attrs = r.get("attributes") or {}
        module = r.get("module") or "root"
        lines.append(
            f"| {_resource_display_name(r)} "
            f"| {r.get('resource_type', '')} "
            f"| {module} "
            f"| {r.get('status', '')} "
            f"| {attrs.get('target_node', '')} "
            f"| {attrs.get('vmid', '')} "
            f"| {attrs.get('cores', '')} "
            f"| {attrs.get('memory', '')} |"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resource_display_name(r: dict) -> str:
    attrs = r.get("attributes") or {}
    return attrs.get("name") or r.get("resource_name", "")
