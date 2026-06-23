#!/usr/bin/env python3
"""
html_forge_workbook.py — HTML forge workbook renderer.

Produces a self-contained HTML workbook for forge execution tracking.
Checkbox behavior: checked → " done" italic, no strikethrough.

Public API:
  build_forge_workbook_html(manifest, hardware_profile=None,
                            validation_findings=None) → str
  generate_forge_workbook_html_file(manifest, output_path, ...)

Stdlib only.
"""

from html_base import (
    callout,
    checkbox_list,
    divider,
    dl,
    html_page,
    p,
    reset_checkbox_counter,
    section,
    table,
)


def _e(text: str) -> str:
    from html import escape
    return escape(str(text))


def _str(v) -> str:
    if v is None:
        return "[UNRESOLVED]"
    if isinstance(v, list):
        return ", ".join(str(x) for x in v) if v else "(none)"
    return str(v)


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _section_overview(manifest: dict) -> str:
    hi = manifest.get("host_identity") or {}
    nt = manifest.get("network_topology") or {}
    pairs = [
        ("Cell ID",      manifest.get("cell_id") or "[UNRESOLVED]"),
        ("Hostname",     hi.get("hostname") or "[UNRESOLVED]"),
        ("Domain",       hi.get("domain") or "—"),
        ("FQDN",         hi.get("fqdn") or "—"),
        ("Setup Mode",   manifest.get("setup_mode") or "autonomous"),
        ("Net Profile",  nt.get("profile") or "lan"),
        ("Generated",    manifest.get("generated_at") or "?"),
    ]
    body = dl(pairs)
    warnings = manifest.get("setup_warnings") or []
    if warnings:
        msgs = "<br>".join(_e(str(w)) for w in warnings)
        body += callout("warn", f"<strong>Setup warnings:</strong><br>{msgs}")
    return section("Overview", body, open_=True)


def _section_hardware(hw: dict) -> str:
    if not hw:
        return section("Hardware", p("Hardware profile not yet collected."), open_=False)

    pairs = [
        ("Hostname",  hw.get("hostname") or "?"),
        ("CPU",       hw.get("cpu_model") or "?"),
        ("RAM",       _str(hw.get("ram_gb")) + " GB"),
        ("Disk count", str(len(hw.get("disks") or []))),
        ("NIC count",  str(len(hw.get("nics") or []))),
    ]
    disks = hw.get("disks") or []
    body = dl(pairs)
    if disks:
        rows = [[_e(d.get("id") or d.get("name") or "?"),
                 _e(str(d.get("size_gb") or "?")),
                 "SSD" if d.get("rotational") is False else "HDD"]
                for d in disks]
        body += table(["Device", "Size (GB)", "Type"], rows)

    items = [
        "CPU meets minimum requirements (x86-64, VT-x)",
        "RAM ≥ 16 GB",
        "Storage ≥ 500 GB",
    ]
    body += checkbox_list(items, id_prefix="hw")
    return section("Hardware", body, open_=True)


def _section_storage(manifest: dict) -> str:
    sc  = manifest.get("storage_config") or {}
    zfs = sc.get("zfs_pool") or {}
    pairs = [
        ("Pool Name",   zfs.get("pool_name") or "—"),
        ("Topology",    zfs.get("topology") or "—"),
        ("Datastore",   zfs.get("datastore_name") or "—"),
    ]
    items = [
        "ZFS pool created: zpool list",
        "Proxmox datastore registered: pvesm status",
    ]
    body = dl(pairs) + checkbox_list(items, id_prefix="storage")
    return section("Storage", body, open_=True)


def _section_network(manifest: dict) -> str:
    nt  = manifest.get("network_topology") or {}
    wan = nt.get("wan_config") or {}
    pairs = [
        ("Management CIDR",  _str(nt.get("management_cidr"))),
        ("Gateway",          _str(nt.get("gateway"))),
        ("DNS Servers",      _str(nt.get("dns_servers") or nt.get("nameservers"))),
        ("Profile",          nt.get("profile") or "lan"),
    ]
    if wan:
        pairs += [
            ("Headscale URL",  wan.get("headscale_url") or nt.get("headscale_url") or "—"),
            ("DDNS Provider",  wan.get("dns_provider") or nt.get("ddns_provider") or "—"),
            ("TLS Provider",   wan.get("tls_provider") or nt.get("ssl_provider") or "—"),
        ]
    items = [
        "Bridges active: ip link show",
        "dnsmasq running: systemctl status dnsmasq",
    ]
    if wan.get("headscale_url") or nt.get("headscale_url"):
        items.append("Headscale running: systemctl status headscale")
        items.append("Hatchery registered with its own Headscale")
    body = dl(pairs) + checkbox_list(items, id_prefix="net")
    return section("Network", body, open_=True)


def _section_identity(manifest: dict) -> str:
    hi   = manifest.get("host_identity") or {}
    vmd  = manifest.get("vm_defaults") or {}
    pairs = [
        ("Cell ID",   manifest.get("cell_id") or "—"),
        ("Hostname",  hi.get("hostname") or "—"),
        ("Domain",    hi.get("domain") or "—"),
        ("Timezone",  vmd.get("timezone") or "UTC"),
        ("KeePass DB",  "/etc/broodforge/keepass.kdbx"),
    ]
    items = [
        "KeePass database initialised",
        "Master password confirmed (not stored by broodforge)",
        "TOTP second factor provisioned (if configured)",
        "Service credential paths pre-created in KeePass",
    ]
    body = dl(pairs) + checkbox_list(items, id_prefix="ident")
    return section("Identity & Security", body, open_=True)


def _section_validation(findings: list | None) -> str:
    phases = [
        ("phase-00", "Hardware discovery and pre-flight"),
        ("phase-01", "Planning and forge-manifest.json"),
        ("phase-02", "Validation (RED = blocked)"),
        ("phase-03", "Host configuration"),
        ("phase-04", "VM provisioning"),
        ("phase-05", "k3s cluster bootstrap"),
        ("phase-06", "Flux GitOps bootstrap"),
        ("phase-07", "Intelligence layer"),
        ("phase-08", "Final verification and commit"),
    ]

    items = [f"{_e(pname)} — {_e(desc)}" for pname, desc in phases]
    body = p("Check each phase as it completes.")

    if findings:
        def _sev(f):
            # Support both dict findings and ForgeValidationFinding dataclasses
            return getattr(f, "severity", None) or (f.get("severity") if isinstance(f, dict) else None) or ""
        def _msg(f):
            return getattr(f, "message", None) or (f.get("message", "?") if isinstance(f, dict) else "?")
        crit = [f for f in findings if _sev(f) in ("ERROR", "RED")]
        warn = [f for f in findings if _sev(f) in ("WARNING", "YELLOW")]
        if crit:
            msgs = "<br>".join(_e(_msg(f)) for f in crit)
            body += callout("danger", f"<strong>{len(crit)} error(s):</strong><br>{msgs}")
        if warn:
            msgs = "<br>".join(_e(_msg(f)) for f in warn)
            body += callout("warn", f"<strong>{len(warn)} warning(s):</strong><br>{msgs}")

    body += checkbox_list(items, id_prefix="phases")
    return section("Phase Validation", body, open_=True)


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_forge_workbook_html(
    manifest:            dict,
    hardware_profile:    dict | None  = None,
    validation_findings: list | None  = None,
) -> str:
    """Build a self-contained HTML forge workbook."""
    reset_checkbox_counter()

    cell_id  = manifest.get("cell_id") or "unknown"
    hostname = (manifest.get("host_identity") or {}).get("hostname") or "unknown"
    gen_at   = manifest.get("generated_at") or "?"

    title = f"Forge Workbook — {cell_id}"
    meta  = f"Host: {hostname}  |  Generated: {gen_at}"

    body = ""
    body += p("This workbook tracks forge execution progress. "
              "Check each phase as it completes. State saved in browser (localStorage).")
    body += divider()
    body += _section_overview(manifest)
    body += _section_hardware(hardware_profile or {})
    body += _section_storage(manifest)
    body += _section_network(manifest)
    body += _section_identity(manifest)
    body += _section_validation(validation_findings)

    return html_page(title, body, doc_id=f"forge-workbook-{cell_id}", meta=meta)


def generate_forge_workbook_html_file(
    manifest:            dict,
    output_path:         str,
    hardware_profile:    dict | None = None,
    validation_findings: list | None = None,
) -> None:
    """Write the HTML forge workbook to a file."""
    html = build_forge_workbook_html(manifest, hardware_profile, validation_findings)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
