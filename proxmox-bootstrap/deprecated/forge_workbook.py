#!/usr/bin/env python3
"""
forge_workbook.py — Forge workbook ODS generator (Phase 1.F.3).

Generates a LibreOffice Calc (.ods) workbook embedded in every forge package.
Tracks each forge phase with the same checkpoint/status/timestamp pattern
as the spawn and phoenix workbooks.

Sheets:
  1. Overview     — forge plan summary (cell, hostname, mode, network profile)
  2. Hardware     — hardware profile discovered during phase-00 + validation result
  3. Storage      — ZFS pool plan (topology, disk IDs, datastore names)
  4. Network      — bridge config, DNS, Headscale URL, TLS provider
  5. Identity     — KeePass config, cell_id, domain, timezone, cell_id
  6. Services     — minimum viable stack and GitOps service list
  7. Validation   — phase-by-phase checklist with status/timestamp columns

Provides:
  build_forge_workbook(manifest, hardware_profile=None, validation_findings=None) -> bytes
  generate_forge_workbook_file(manifest, output_path, hardware_profile=None, ...)

Stdlib only.
"""

import io
import zipfile
from pathlib import Path
from typing import Any, Optional
from xml.sax.saxutils import escape as xml_escape

# ---------------------------------------------------------------------------
# ODS XML constants (minimal standalone copy — matches spawn_workbook pattern)
# ---------------------------------------------------------------------------

_MIMETYPE = b"application/vnd.oasis.opendocument.spreadsheet"

_MANIFEST_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"
                   manifest:version="1.2">
  <manifest:file-entry manifest:full-path="/"
      manifest:media-type="application/vnd.oasis.opendocument.spreadsheet"/>
  <manifest:file-entry manifest:full-path="content.xml"
      manifest:media-type="text/xml"/>
  <manifest:file-entry manifest:full-path="styles.xml"
      manifest:media-type="text/xml"/>
  <manifest:file-entry manifest:full-path="meta.xml"
      manifest:media-type="text/xml"/>
</manifest:manifest>
"""

_META_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<office:document-meta
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0"
  office:version="1.2">
  <office:meta>
    <meta:generator>Broodforge forge_workbook v1.0</meta:generator>
  </office:meta>
</office:document-meta>
"""

_STYLES_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<office:document-styles
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
  xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
  office:version="1.2">
  <office:styles>
    <style:style style:name="Default" style:family="table-cell">
      <style:text-properties fo:font-size="10pt"/>
    </style:style>
  </office:styles>
  <office:automatic-styles/>
</office:document-styles>"""

_CELL_STYLES = """\
    <style:style style:name="ce_title" style:family="table-cell">
      <style:text-properties fo:font-weight="bold" fo:font-size="13pt" fo:color="#1F3864"/>
    </style:style>
    <style:style style:name="ce_section" style:family="table-cell">
      <style:text-properties fo:font-weight="bold" fo:font-size="10pt" fo:color="#1F3864"/>
      <style:table-cell-properties fo:background-color="#D6E4F0" fo:padding="2pt"/>
    </style:style>
    <style:style style:name="ce_label" style:family="table-cell">
      <style:text-properties fo:font-weight="bold" fo:font-size="10pt"/>
    </style:style>
    <style:style style:name="ce_value" style:family="table-cell">
      <style:text-properties fo:font-size="10pt" fo:color="#1A5276"/>
      <style:table-cell-properties fo:background-color="#EBF5FB"/>
    </style:style>
    <style:style style:name="ce_pending" style:family="table-cell">
      <style:text-properties fo:font-size="10pt" fo:color="#7D6608"/>
      <style:table-cell-properties fo:background-color="#FEFDE7"/>
    </style:style>
    <style:style style:name="ce_pass" style:family="table-cell">
      <style:text-properties fo:font-size="10pt" fo:color="#145A32"/>
      <style:table-cell-properties fo:background-color="#EAFAF1"/>
    </style:style>
    <style:style style:name="ce_fail" style:family="table-cell">
      <style:text-properties fo:font-size="10pt" fo:color="#78281F"/>
      <style:table-cell-properties fo:background-color="#FDEDEC"/>
    </style:style>
    <style:style style:name="ce_warn" style:family="table-cell">
      <style:text-properties fo:font-size="10pt" fo:color="#7E5109"/>
      <style:table-cell-properties fo:background-color="#FEF9E7"/>
    </style:style>
    <style:style style:name="ce_note" style:family="table-cell">
      <style:text-properties fo:font-size="9pt" fo:color="#555555" fo:font-style="italic"/>
    </style:style>
    <style:style style:name="co_label" style:family="table-column">
      <style:table-column-properties style:column-width="6cm"/>
    </style:style>
    <style:style style:name="co_value" style:family="table-column">
      <style:table-column-properties style:column-width="10cm"/>
    </style:style>
    <style:style style:name="co_status" style:family="table-column">
      <style:table-column-properties style:column-width="3cm"/>
    </style:style>
    <style:style style:name="co_ts" style:family="table-column">
      <style:table-column-properties style:column-width="5.5cm"/>
    </style:style>
    <style:style style:name="ro_section" style:family="table-row">
      <style:table-row-properties style:row-height="0.7cm" fo:background-color="#D6E4F0"/>
    </style:style>
    <style:style style:name="ro_normal" style:family="table-row">
      <style:table-row-properties style:row-height="0.55cm"/>
    </style:style>
"""

_CONTENT_NS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
    'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
    'office:version="1.2"'
)


# ---------------------------------------------------------------------------
# XML cell/row helpers
# ---------------------------------------------------------------------------

def _cell(value: Any, style: str = "Default", wrap: bool = False) -> str:
    v = xml_escape(str(value) if value is not None else "")
    wrap_attr = ' fo:wrap-option="wrap"' if wrap else ""
    return (
        f'<table:table-cell table:style-name="{style}" '
        f'office:value-type="string"{wrap_attr}>'
        f'<text:p>{v}</text:p>'
        f'</table:table-cell>'
    )


def _empty(n: int = 1) -> str:
    if n == 1:
        return '<table:table-cell/>'
    return f'<table:table-cell table:number-columns-repeated="{n}"/>'


def _row(cells: list, style: str = "ro_normal") -> str:
    return f'<table:table-row table:style-name="{style}">{"".join(cells)}</table:table-row>'


def _section(title: str) -> str:
    cells = [_cell(f"  {title}", "ce_section")] + [_cell("", "ce_section")] * 3
    return _row(cells, "ro_section")


# ---------------------------------------------------------------------------
# SheetBuilder
# ---------------------------------------------------------------------------

class _SheetBuilder:
    def __init__(self, name: str):
        self.name = name
        self._rows: list[str] = []

    def title(self, text: str) -> "_SheetBuilder":
        self._rows.append(_row([_cell(text, "ce_title"), _empty(3)]))
        self._rows.append(_row([_empty(4)]))
        return self

    def headers(self, *labels: str) -> "_SheetBuilder":
        self._rows.append(_row([_cell(lbl, "ce_label") for lbl in labels]))
        return self

    def section(self, title: str) -> "_SheetBuilder":
        self._rows.append(_row([_empty(4)]))
        self._rows.append(_section(title))
        return self

    def field(self, label: str, value: Any, note: str = "") -> "_SheetBuilder":
        self._rows.append(_row([
            _cell(label, "ce_label"),
            _cell(value if value is not None else "", "ce_value", wrap=True),
            _empty(),
            _cell(note, "ce_note", wrap=True),
        ]))
        return self

    def finding_row(self, severity: str, field: str, message: str) -> "_SheetBuilder":
        style = "ce_fail" if severity == "RED" else "ce_warn"
        self._rows.append(_row([
            _cell(f"[{severity}]", style),
            _cell(field, "ce_label"),
            _cell(message, "ce_note", wrap=True),
            _empty(),
        ]))
        return self

    def phase_row(self, phase: str, description: str) -> "_SheetBuilder":
        self._rows.append(_row([
            _cell(phase, "ce_label"),
            _cell(description, "ce_note", wrap=True),
            _cell("PENDING", "ce_pending"),
            _cell("", "Default"),
        ]))
        return self

    def spacer(self) -> "_SheetBuilder":
        self._rows.append(_row([_empty(4)]))
        return self

    def build_xml(self) -> str:
        safe_name = xml_escape(self.name)
        col_defs = (
            '<table:table-column table:style-name="co_label"/>'
            '<table:table-column table:style-name="co_value"/>'
            '<table:table-column table:style-name="co_status"/>'
            '<table:table-column table:style-name="co_ts"/>'
        )
        return (
            f'<table:table table:name="{safe_name}">'
            f'{col_defs}{"".join(self._rows)}'
            f'</table:table>'
        )


# ---------------------------------------------------------------------------
# Plan accessors
# ---------------------------------------------------------------------------

def _g(d: dict, *keys, default="") -> Any:
    obj = d
    for k in keys:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(k, default)
    return obj if obj is not None else default


# ---------------------------------------------------------------------------
# Sheet builders
# ---------------------------------------------------------------------------

def _sheet_overview(manifest: dict) -> _SheetBuilder:
    s = _SheetBuilder("Overview")
    hostname     = _g(manifest, "host_identity", "hostname")
    cell_id      = _g(manifest, "cell_id")
    generated_at = _g(manifest, "generated_at")
    setup_mode   = _g(manifest, "setup_mode") or "autonomous"
    profile      = _g(manifest, "network_topology", "profile") or "lan"
    domain       = _g(manifest, "host_identity", "domain")
    fqdn         = _g(manifest, "host_identity", "fqdn")
    timezone_val = _g(manifest, "host_identity", "timezone")

    s.title(f"Forge Package — {hostname}")
    s.headers("Field", "Value", "Status", "Note")

    s.section("Identity")
    s.field("Hostname",     hostname)
    s.field("Domain",       domain)
    s.field("FQDN",         fqdn)
    s.field("Cell ID",      cell_id)
    s.field("Generated At", generated_at)
    if timezone_val:
        s.field("Timezone", timezone_val)

    s.section("Configuration")
    s.field("Setup Mode",       setup_mode)
    s.field("Network Profile",  profile)

    # WAN config summary
    wan = manifest.get("network_topology", {}).get("wan_config") or {}
    if wan:
        s.section("WAN Configuration")
        if wan.get("dns_provider"):
            s.field("DNS Provider",  wan["dns_provider"])
        if wan.get("ddns_provider"):
            s.field("DDNS Provider", wan["ddns_provider"])
        if wan.get("headscale_url"):
            s.field("Headscale URL", wan["headscale_url"])
        if wan.get("tls_provider"):
            s.field("TLS Provider",  wan["tls_provider"])

    # Warnings
    warnings = manifest.get("setup_warnings") or []
    if warnings:
        s.section(f"Setup Warnings ({len(warnings)})")
        for w in warnings:
            s.field("Warning", w)

    return s


def _sheet_hardware(hardware_profile: Optional[dict], findings: Optional[list]) -> _SheetBuilder:
    s = _SheetBuilder("Hardware")
    s.title("Hardware Profile")
    s.headers("Field", "Value", "Status", "Note")

    if not hardware_profile:
        s.section("No hardware profile available")
        s.field("Status", "Hardware profile not yet collected")
        s.field("Action", "Run phase-00 (discover) to populate this sheet")
        return s

    s.section("Host")
    s.field("Hostname",   _g(hardware_profile, "hostname"))
    s.field("RAM (GiB)",  str(_g(hardware_profile, "ram_gb")))
    s.field("CPU Model",  _g(hardware_profile, "cpu_model"))
    s.field("CPU Cores",  str(_g(hardware_profile, "cpu_cores")))

    disks = hardware_profile.get("disks") or []
    s.section(f"Disks ({len(disks)} detected)")
    for d in disks:
        removable = " [REMOVABLE]" if d.get("removable") else ""
        disk_type = "SSD" if not d.get("rotational") else "HDD"
        s.field(
            d.get("name", "?"),
            f"{d.get('size_gb', '?')} GiB  {disk_type}{removable}",
            d.get("model", ""),
        )

    nics = hardware_profile.get("nics") or []
    s.section(f"NICs ({len(nics)} detected)")
    for n in nics:
        s.field(
            n.get("name", "?"),
            n.get("mac", ""),
            f"{n.get('speed_mbps', '?')} Mbps",
        )

    # Validation findings
    if findings:
        reds    = [f for f in findings if getattr(f, "severity", None) == "RED"
                   or (isinstance(f, dict) and f.get("severity") == "RED")]
        yellows = [f for f in findings if getattr(f, "severity", None) == "YELLOW"
                   or (isinstance(f, dict) and f.get("severity") == "YELLOW")]
        valid   = not reds
        s.section(f"Validation {'PASS' if valid else 'BLOCKED'}")
        for f in reds:
            sev  = getattr(f, "severity", f.get("severity", "RED") if isinstance(f, dict) else "RED")
            fld  = getattr(f, "field",    f.get("field", "")   if isinstance(f, dict) else "")
            msg  = getattr(f, "message",  f.get("message", "") if isinstance(f, dict) else "")
            s.finding_row(sev, fld, msg)
        for f in yellows:
            sev  = getattr(f, "severity", f.get("severity", "YELLOW") if isinstance(f, dict) else "YELLOW")
            fld  = getattr(f, "field",    f.get("field", "")    if isinstance(f, dict) else "")
            msg  = getattr(f, "message",  f.get("message", "")  if isinstance(f, dict) else "")
            s.finding_row(sev, fld, msg)
    else:
        s.section("Validation")
        s.field("Status", "Not yet validated (run phase-02)")

    return s


def _sheet_storage(manifest: dict, hardware_profile: Optional[dict]) -> _SheetBuilder:
    s = _SheetBuilder("Storage")
    s.title("Storage Plan")
    s.headers("Field", "Value", "Status", "Note")

    # Derive ZFS topology from disk count
    disks = (hardware_profile or {}).get("disks") or []
    usable = [d for d in disks if not d.get("removable") and (d.get("size_gb") or 0) >= 32]
    n = len(usable)
    topology = _zfs_topology(n)

    manifest.get("network_topology") or {}

    s.section("ZFS Pool")
    s.field("Usable Disk Count", str(n))
    s.field("ZFS Topology",      topology)
    s.field("Pool Name",         "rpool")

    if usable:
        s.section("Disk Assignment")
        for i, d in enumerate(usable):
            s.field(f"Disk {i+1}", d.get("name", "?"), f"{d.get('size_gb', '?')} GiB")

    s.section("Proxmox Datastores")
    s.field("VM storage datastore", "local-zfs  (rpool/data)")
    s.field("ISO/template store",   "local  (/var/lib/vz)")

    return s


def _zfs_topology(n: int) -> str:
    """Return ZFS pool topology name for n usable disks."""
    if n == 0:
        return "UNAVAILABLE (no usable disks)"
    if n == 1:
        return "stripe (no redundancy — not recommended)"
    if n == 2:
        return "mirror"
    if n <= 5:
        return "raidz1"
    if n <= 8:
        return "raidz2"
    return "raidz3"


def _sheet_network(manifest: dict) -> _SheetBuilder:
    s = _SheetBuilder("Network")
    s.title("Network Configuration")
    s.headers("Field", "Value", "Status", "Note")

    nt = manifest.get("network_topology") or {}

    s.section("Management Network")
    s.field("Profile",         nt.get("profile") or "lan")
    s.field("Management CIDR", nt.get("management_cidr") or "")
    s.field("Gateway",         nt.get("gateway") or "")

    s.section("Proxmox Bridges")
    s.field("vmbr0", "Management bridge (eth0/eno1 → VMs)")
    s.field("Note",  "Additional bridges generated from NIC inventory by phase-03")

    wan = nt.get("wan_config") or {}
    if manifest.get("network_topology", {}).get("profile") == "wan":
        s.section("WAN / Headscale")
        s.field("Headscale URL",  wan.get("headscale_url") or "")
        s.field("DDNS Provider",  wan.get("ddns_provider") or "(none)")
        s.field("TLS Provider",   wan.get("tls_provider")  or "")
        s.field("Note",           "Router port forward: 8080 → hatchery LAN IP required")

    s.section("DNS")
    s.field("dnsmasq",         "Deployed in phase-03; serves split-horizon DNS")
    s.field("Upstream DNS 1",  "8.8.8.8")
    s.field("Upstream DNS 2",  "1.1.1.1")
    domain = manifest.get("host_identity", {}).get("domain") or ""
    if domain:
        s.field("Local domain",  domain)

    return s


def _sheet_identity(manifest: dict) -> _SheetBuilder:
    s = _SheetBuilder("Identity")
    s.title("Identity and Security")
    s.headers("Field", "Value", "Status", "Note")

    hi = manifest.get("host_identity") or {}

    s.section("Host Identity")
    s.field("Hostname",  hi.get("hostname") or "")
    s.field("Domain",    hi.get("domain")   or "")
    s.field("FQDN",      hi.get("fqdn")     or "")
    s.field("Cell ID",   hi.get("cell_id")  or "")
    s.field("Timezone",  hi.get("timezone") or "(not set — defaults to UTC)")

    kp = manifest.get("keepass_config") or {}
    s.section("KeePass")
    s.field("Embed in packages", str(kp.get("embed_in_packages", "not configured")))
    s.field("Database path hint", kp.get("database_path_hint") or "(prompt at gate)")
    s.field("Master password",   "[entered at KeePass unlock gate — never stored]")

    overrides = manifest.get("setup_overrides") or {}
    if overrides:
        s.section(f"Setup Overrides ({len(overrides)} manual choices)")
        for fp, v in list(overrides.items())[:20]:
            val = v.get("value", "") if isinstance(v, dict) else str(v)
            s.field(fp, str(val))

    return s


def _sheet_services(manifest: dict) -> _SheetBuilder:
    s = _SheetBuilder("Services")
    s.title("Service Stack")
    s.headers("Field", "Value", "Status", "Note")

    stack = manifest.get("minimum_vm_stack") or [
        "proxmox-ve",
        "k3s-server",
        "assessment-engine",
        "forgejo",
    ]

    s.section("Minimum Viable Stack (forged directly)")
    for svc in stack:
        s.field(svc, "Included in forge")

    s.section("GitOps Services (added after forging via Flux CD)")
    s.field("Note", "User applications are NOT included in the forge package.")
    s.field("",     "After forging, push your Flux GitOps repository to Forgejo.")
    s.field("",     "Flux CD will deploy application workloads automatically.")

    return s


def _sheet_validation(manifest: dict) -> _SheetBuilder:
    s = _SheetBuilder("Validation")
    s.title("Forge Phase Validation")
    s.headers("Phase", "Description", "Status", "Timestamp")

    phases = [
        ("phase-00", "Hardware discovery (lsblk, ip link, /proc/meminfo)"),
        ("phase-01", "Forge planning (forge-planner.py — identity, network, mode)"),
        ("phase-02", "Hardware validation (forge_validator.py — RED blocks forge)"),
        ("phase-03", "Host configuration (hostname, bridges, ZFS, nag suppress, dnsmasq)"),
        ("phase-04", "VM provisioning (tofu apply — minimum stack VMs)"),
        ("phase-05", "k3s cluster init (ansible k3s-server role)"),
        ("phase-06", "Flux CD bootstrap (flux bootstrap → Forgejo)"),
        ("phase-07", "Intelligence layer (assessment engine, doc engine, first report)"),
        ("phase-08", "Verify and commit (cluster health, bootstrap-state.json update)"),
    ]

    for phase, desc in phases:
        s.phase_row(phase, desc)

    s.section("Post-Forge Verification")
    s.field("k3s node ready",          "kubectl get nodes — all nodes Ready")
    s.field("Flux reconciled",         "flux get kustomizations — all synced")
    s.field("Assessment report green", "engine.py --mode bootstrap — no RED findings")
    s.field("Forgejo accessible",      "https://forgejo.{domain} — web UI loads")

    s.section("WAN Verification (if profile=wan)")
    s.field("External DNS resolves",   "dig hatchery.{domain} from external resolver")
    s.field("Headscale reachable",     "curl -k https://hatchery.{domain}:8080/health")
    s.field("TLS certificate valid",   "openssl s_client -connect hatchery.{domain}:443")

    return s


# ---------------------------------------------------------------------------
# ODS assembler
# ---------------------------------------------------------------------------

def _build_content_xml(sheets: list[_SheetBuilder]) -> str:
    tables_xml = "".join(sh.build_xml() for sh in sheets)
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<office:document-content {_CONTENT_NS}>'
        f'<office:automatic-styles>{_CELL_STYLES}</office:automatic-styles>'
        f'<office:body><office:spreadsheet>'
        f'{tables_xml}'
        f'</office:spreadsheet></office:body>'
        f'</office:document-content>'
    )


def build_forge_workbook(
    manifest:             dict,
    hardware_profile:     Optional[dict] = None,
    validation_findings:  Optional[list] = None,
) -> bytes:
    """
    Build the forge workbook ODS and return as bytes.

    manifest: forge-manifest.json dict (from build_forge_manifest() or file load)
    hardware_profile: HardwareProfile.to_dict() output (from phase-00 discovery)
    validation_findings: list of ForgeValidationFinding (from forge_validator)
    """
    sheets = [
        _sheet_overview(manifest),
        _sheet_hardware(hardware_profile, validation_findings),
        _sheet_storage(manifest, hardware_profile),
        _sheet_network(manifest),
        _sheet_identity(manifest),
        _sheet_services(manifest),
        _sheet_validation(manifest),
    ]
    content_xml = _build_content_xml(sheets)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", _MIMETYPE, compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/manifest.xml", _MANIFEST_XML)
        zf.writestr("meta.xml", _META_XML)
        zf.writestr("styles.xml", _STYLES_XML)
        zf.writestr("content.xml", content_xml)
    return buf.getvalue()


def generate_forge_workbook_file(
    manifest:             dict,
    output_path:          str,
    hardware_profile:     Optional[dict] = None,
    validation_findings:  Optional[list] = None,
) -> None:
    """Write the forge workbook ODS to output_path."""
    data = build_forge_workbook(manifest, hardware_profile, validation_findings)
    Path(output_path).write_bytes(data)
