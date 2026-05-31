"""
Guest assessment report generator.

Produces a Markdown report answering:
  - What guests exist?
  - What software / services exist?
  - What containers exist?
  - How are systems managed?
  - How were systems observed?

No recommendations are generated.  All content is factual.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone


def generate_guest_report(assessment: dict) -> str:
    """Generate a guest-assessment.md Markdown report from a normalized assessment."""
    guests: list[dict] = assessment.get("guests") or []
    state_sources: dict = assessment.get("state_sources") or {}
    hostname = assessment.get("hostname", "unknown")
    timestamp = assessment.get("timestamp", "unknown")

    sections = [
        _header(hostname, timestamp),
        _guest_summary(guests),
        _operating_systems(guests),
        _services(guests),
        _containers(guests),
        _inventory_groups(guests),
        _collection_coverage(guests),
        _provisioning_metadata(guests),
        _configuration_metadata(guests),
        _state_sources(state_sources),
    ]

    return "\n\n".join(s for s in sections if s)


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def _header(hostname: str, timestamp: str) -> str:
    return f"# Guest Assessment Report\n\n**Node:** {hostname}  \n**Assessment timestamp:** {timestamp}"


def _guest_summary(guests: list[dict]) -> str:
    if not guests:
        return "## Guest Summary\n\nNo guests collected."

    reachable = [g for g in guests if g.get("collection_method") == "ansible-facts"]
    unreachable = [g for g in guests if g.get("collection_method") == "unreachable"]
    failed = [g for g in guests if g.get("collection_method") not in ("ansible-facts", "unreachable")]

    lines = [
        "## Guest Summary",
        "",
        f"| Metric | Count |",
        f"|--------|-------|",
        f"| Total guests in inventory | {len(guests)} |",
        f"| Successfully assessed | {len(reachable)} |",
        f"| Unreachable | {len(unreachable)} |",
        f"| Collection failed | {len(failed)} |",
    ]
    return "\n".join(lines)


def _operating_systems(guests: list[dict]) -> str:
    reachable = [g for g in guests if g.get("operating_system")]
    if not reachable:
        return ""

    dist_counter: Counter = Counter()
    for g in reachable:
        os = g.get("operating_system") or {}
        dist = os.get("distribution", "Unknown")
        ver = os.get("distribution_version", "")
        dist_counter[f"{dist} {ver}".strip()] += 1

    lines = [
        "## Operating Systems",
        "",
        "| Distribution | Count |",
        "|-------------|-------|",
    ]
    for dist, count in dist_counter.most_common():
        lines.append(f"| {dist} | {count} |")

    return "\n".join(lines)


def _services(guests: list[dict]) -> str:
    all_running: Counter = Counter()
    all_enabled: Counter = Counter()

    for g in guests:
        for svc in g.get("running_services") or []:
            all_running[svc] += 1
        for svc in g.get("enabled_services") or []:
            all_enabled[svc] += 1

    if not all_running and not all_enabled:
        return ""

    lines = ["## Services", ""]

    if all_running:
        lines += [
            "### Running Services",
            "",
            "| Service | Hosts |",
            "|---------|-------|",
        ]
        for svc, count in sorted(all_running.items()):
            lines.append(f"| `{svc}` | {count} |")
        lines.append("")

    if all_enabled:
        lines += [
            "### Enabled Services",
            "",
            "| Service | Hosts |",
            "|---------|-------|",
        ]
        for svc, count in sorted(all_enabled.items()):
            lines.append(f"| `{svc}` | {count} |")

    return "\n".join(lines)


def _containers(guests: list[dict]) -> str:
    docker_hosts: list[tuple[str, dict]] = []
    podman_hosts: list[tuple[str, dict]] = []

    for g in guests:
        host = g.get("hostname", "?")
        for c in g.get("docker_containers") or []:
            docker_hosts.append((host, c))
        for c in g.get("podman_containers") or []:
            podman_hosts.append((host, c))

    if not docker_hosts and not podman_hosts:
        return ""

    lines = ["## Containers", ""]

    if docker_hosts:
        lines += [
            "### Docker",
            "",
            "| Host | Container | Image | Status |",
            "|------|-----------|-------|--------|",
        ]
        for host, c in docker_hosts:
            lines.append(
                f"| {host} | {c.get('name','')} | {c.get('image','')} | {c.get('status','')} |"
            )
        lines.append("")

    if podman_hosts:
        lines += [
            "### Podman",
            "",
            "| Host | Container | Image | Status |",
            "|------|-----------|-------|--------|",
        ]
        for host, c in podman_hosts:
            lines.append(
                f"| {host} | {c.get('name','')} | {c.get('image','')} | {c.get('status','')} |"
            )

    return "\n".join(lines)


def _inventory_groups(guests: list[dict]) -> str:
    group_counter: Counter = Counter()
    for g in guests:
        for grp in g.get("groups") or []:
            group_counter[grp] += 1

    if not group_counter:
        return ""

    lines = [
        "## Inventory Groups",
        "",
        "| Group | Host Count |",
        "|-------|------------|",
    ]
    for grp, count in sorted(group_counter.items()):
        lines.append(f"| {grp} | {count} |")

    return "\n".join(lines)


def _collection_coverage(guests: list[dict]) -> str:
    method_counter: Counter = Counter()
    for g in guests:
        method_counter[g.get("collection_method", "unknown")] += 1

    lines = [
        "## Assessment Coverage",
        "",
        "| Collection Method | Count |",
        "|-------------------|-------|",
    ]
    for method, count in sorted(method_counter.items()):
        lines.append(f"| {method} | {count} |")

    return "\n".join(lines)


def _provisioning_metadata(guests: list[dict]) -> str:
    prov_counter: Counter = Counter()
    for g in guests:
        prov = g.get("provisioning_method") or "unknown"
        prov_counter[prov] += 1

    lines = [
        "## Provisioning Metadata",
        "",
        "| Provisioning Method | Count |",
        "|---------------------|-------|",
    ]
    for method, count in sorted(prov_counter.items()):
        lines.append(f"| {method} | {count} |")

    return "\n".join(lines)


def _configuration_metadata(guests: list[dict]) -> str:
    conf_counter: Counter = Counter()
    for g in guests:
        conf = g.get("configuration_method") or "unknown"
        conf_counter[conf] += 1

    lines = [
        "## Configuration Metadata",
        "",
        "| Configuration Method | Count |",
        "|----------------------|-------|",
    ]
    for method, count in sorted(conf_counter.items()):
        lines.append(f"| {method} | {count} |")

    return "\n".join(lines)


def _state_sources(state_sources: dict) -> str:
    if not state_sources:
        return ""

    lines = ["## State Sources", ""]

    declared = state_sources.get("declared") or {}
    configured = state_sources.get("configured") or {}
    observed = state_sources.get("observed") or {}

    lines += [
        "| Layer | Tool | Collected |",
        "|-------|------|-----------|",
        f"| Declared (OpenTofu) | {declared.get('tool') or 'not configured'} | {_yn(declared.get('collected', False))} |",
        f"| Configured (Ansible) | {configured.get('tool') or 'not configured'} | {_yn(configured.get('collected', False))} |",
        f"| Observed (this engine) | {observed.get('tool') or 'broodforge'} | {_yn(observed.get('collected', True))} |",
    ]

    inv_path = configured.get("inventory_path")
    if inv_path:
        lines += ["", f"**Inventory path:** `{inv_path}`"]

    return "\n".join(lines)


def _yn(val: bool) -> str:
    return "yes" if val else "no"
