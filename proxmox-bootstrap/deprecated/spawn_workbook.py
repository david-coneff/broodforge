#!/usr/bin/env python3
"""
spawn_workbook.py — Spawn workbook ODS generator (Phase 12.E.8).

Generates a LibreOffice Calc (.ods) workbook embedded in every spawn package.
Tracks each spawn phase with the same checkpoint/status/timestamp pattern
as the recovery workbook.

Sheets:
  1. Overview       — spawn plan summary (cell, hostname, mode, disposition)
  2. Discovery      — hardware profile (CPU, RAM, disks, NICs)
  3. Storage        — ZFS pool plan (topology, disk IDs, datastore)
  4. Network        — bridge config (gateway, nameservers)
  5. Proxmox-Join   — cluster join info (address, fingerprint)
  6. VMs            — VM plan (VMIDs, IPs, roles, sizing)
  7. k3s-Join       — k3s cluster join (role, server URL, token reference)
  8. Validation     — phase-by-phase checklist with status/timestamp columns

Provides:
  build_spawn_workbook(plan, hardware_profile=None) -> bytes
  generate_spawn_workbook_file(plan, output_path, hardware_profile=None)

Stdlib only.
"""

import io
import zipfile
from pathlib import Path
from typing import Any, Optional
from xml.sax.saxutils import escape as xml_escape

# ---------------------------------------------------------------------------
# ODS XML constants (minimal standalone copy — no doc-gen dependency)
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
    <meta:generator>Broodforge spawn_workbook v1.0</meta:generator>
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
</office:document-styles>
"""

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
        self._rows.append(_row([_cell(l, "ce_label") for l in labels]))
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


def _list_str(items: list, fmt: str, empty: str = "(none)") -> str:
    if not items:
        return empty
    lines = []
    for item in items:
        try:
            lines.append(fmt.format(**{k: (str(v) if v is not None else "N/A") for k, v in item.items()}))
        except (KeyError, TypeError):
            lines.append(str(item))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Sheet builders
# ---------------------------------------------------------------------------

def _sheet_overview(plan: dict) -> _SheetBuilder:
    s = _SheetBuilder("Overview")
    hostname   = _g(plan, "hostname")
    cell_id    = _g(plan, "cell_id")
    pkg_id     = _g(plan, "package_id")
    gen_at     = _g(plan, "generated_at")
    exec_mode  = _g(plan, "disposition", "execution_mode") or "autonomous"
    net_mode   = _g(plan, "disposition", "network_mode") or "lan"
    k3s_role   = _g(plan, "k3s", "role") or _g(plan, "k3s_role")
    services   = _g(plan, "disposition", "services")
    excluded   = _g(plan, "disposition", "excluded")

    s.title(f"Spawn Package — {hostname}")
    s.headers("Field", "Value", "Status", "Note")
    s.section("Identity")
    s.field("Hostname",        hostname)
    s.field("Cell ID",         cell_id)
    s.field("Package ID",      pkg_id)
    s.field("Generated At",    gen_at)

    s.section("Disposition")
    s.field("Execution Mode",  exec_mode)
    s.field("Network Mode",    net_mode)
    s.field("k3s Role",        str(k3s_role))
    if isinstance(services, list):
        s.field("Selected Services", "\n".join(str(x) for x in services) or "(baseline only)")
    elif services:
        s.field("Selected Services", str(services))
    else:
        s.field("Selected Services", "(interactive — selected at runtime)")
    if isinstance(excluded, list) and excluded:
        s.field("Excluded Services", "\n".join(str(x) for x in excluded))

    s.section("Phase Status")
    for phase, desc in [
        ("phase-00-preflight", "Hardware pre-flight verification"),
        ("phase-00-host",      "Host bootstrap (hostname, bridges, ZFS)"),
        ("phase-01-proxmox",   "Proxmox cluster join"),
        ("phase-02-vms",       "VM provisioning via OpenTofu"),
        ("phase-03-cloudinit", "Cloud-Init snippet install + VM start"),
        ("phase-04-k3s",       "k3s cluster join via Ansible"),
        ("phase-05-ha",        "HA promotion (3rd server only — conditional)"),
        ("phase-06-verify",    "Post-spawn health verification"),
    ]:
        s.phase_row(phase, desc)

    return s


def _sheet_discovery(plan: dict, hardware_profile: Optional[dict]) -> _SheetBuilder:
    s = _SheetBuilder("Discovery")
    s.title("Hardware Discovery")
    s.headers("Field", "Value", "", "Note")
    s.section("Host")
    hostname = _g(plan, "hostname") or "(unknown)"
    s.field("Hostname",  hostname)

    if hardware_profile:
        s.field("CPU Model",   _g(hardware_profile, "cpu_model"))
        s.field("CPU Cores",   str(_g(hardware_profile, "cpu_cores")))
        s.field("RAM (GB)",    str(_g(hardware_profile, "ram_gb")))

        s.section("Disks")
        disks = hardware_profile.get("disks") or []
        s.field("Disk Count",  str(len(disks)))
        for d in disks:
            name    = d.get("name", "?")
            size_gb = d.get("size_gb", "?")
            kind    = "SSD" if not d.get("rotational", True) else "HDD"
            s.field(name, f"{size_gb} GB  [{kind}]")

        s.section("NICs")
        nics = hardware_profile.get("nics") or []
        s.field("NIC Count", str(len(nics)))
        for n in nics:
            s.field(n.get("name", "?"), f"MAC={n.get('mac', 'N/A')}  speed={n.get('speed_mbps', '?')} Mbps")

        derived = hardware_profile.get("derived") or {}
        s.section("Derived")
        s.field("Usable Disks",   str(derived.get("usable_disks", "?")))
        s.field("SSD Count",      str(derived.get("ssd_count", "?")))
        s.field("HDD Count",      str(derived.get("hdd_count", "?")))
        s.field("ZFS Topology",   str(derived.get("zfs_topology", "?")),
                note="Derived from usable disk count")
    else:
        s.section("Hardware Profile")
        s.field("Status", "(not available — interactive mode or discovery skipped)",
                note="Hardware discovered at runtime on the broodling")

    return s


def _sheet_storage(plan: dict) -> _SheetBuilder:
    s = _SheetBuilder("Storage")
    storage = _g(plan, "storage") or {}
    s.title("ZFS Storage Plan")
    s.headers("Field", "Value", "", "Note")
    s.section("ZFS Pool")
    s.field("Pool Name",      _g(storage, "pool_name"))
    s.field("Topology",       _g(storage, "topology"),
            note="stripe/mirror/raidz1/raidz2/raidz3 from disk count")
    s.field("Disk IDs",
            "\n".join(str(d) for d in (storage.get("disk_ids") or [])) or "(none)",
            note="Confirmed during phase-00-preflight")
    s.field("Datastore Name", _g(storage, "datastore_name"),
            note="pvesm register name")
    return s


def _sheet_network(plan: dict) -> _SheetBuilder:
    s = _SheetBuilder("Network")
    network = _g(plan, "network") or {}
    s.title("Network Configuration Plan")
    s.headers("Field", "Value", "", "Note")
    s.section("Bridges")
    s.field("Primary Bridge", _g(network, "bridge"),
            note="Created in phase-00-host from NIC layout")
    s.field("Gateway",        _g(network, "gateway"))
    ns = network.get("nameservers") or []
    s.field("Nameservers",
            ", ".join(str(n) for n in ns) or "(none)",
            note="Hatchery IP for LAN DNS; upstream for WAN")
    s.section("Spawn Mode")
    net_mode = _g(plan, "disposition", "network_mode") or "lan"
    s.field("Network Mode", net_mode)
    headscale_url = _g(plan, "hatchery", "headscale_url")
    if headscale_url:
        s.field("Headscale URL", headscale_url,
                note="Used in WAN mode for tailnet join")
    return s


def _sheet_proxmox(plan: dict) -> _SheetBuilder:
    s = _SheetBuilder("Proxmox-Join")
    hatchery = _g(plan, "hatchery") or {}
    s.title("Proxmox Cluster Join")
    s.headers("Field", "Value", "", "Note")
    s.section("Cluster Join")
    s.field("Cluster Address",    _g(hatchery, "proxmox_cluster_address"),
            note="pvecm add target")
    s.field("Fingerprint",        _g(hatchery, "proxmox_fingerprint") or "(from live cluster)")
    s.field("Broodling LAN IP",   _g(plan, "lan_ip"))
    s.field("Broodling Domain",   _g(plan, "domain"))
    s.section("Phase-01 Status")
    s.phase_row("phase-01-proxmox", "pvecm add — idempotent if already a member")
    return s


def _sheet_vms(plan: dict) -> _SheetBuilder:
    s = _SheetBuilder("VMs")
    vms = plan.get("vms") or []
    s.title("VM Provisioning Plan")
    s.headers("Field", "Value", "", "Note")
    s.section("VM Set")
    s.field("VM Count", str(len(vms)))
    for vm in vms:
        vmid = vm.get("vmid", "?")
        name = vm.get("name", "?")
        ip   = vm.get("ip", "?")
        mem  = vm.get("memory_mb", "?")
        s.section(f"VM {vmid} — {name}")
        s.field("VMID",      str(vmid))
        s.field("IP",        str(ip))
        s.field("RAM (MB)",  str(mem))
        s.field("User",      str(vm.get("initial_user", "ubuntu")))
    if not vms:
        s.field("VMs", "(none declared in plan)")
    s.section("Phase-02 Status")
    s.phase_row("phase-02-vms",       "tofu apply — creates VM set")
    s.phase_row("phase-03-cloudinit", "Cloud-Init snippets install + VM start")
    return s


def _sheet_k3s(plan: dict) -> _SheetBuilder:
    s = _SheetBuilder("k3s-Join")
    k3s = _g(plan, "k3s") or {}
    s.title("k3s Cluster Join")
    s.headers("Field", "Value", "", "Note")
    s.section("k3s Configuration")
    s.field("k3s Role",      str(k3s.get("role", "worker")))
    s.field("Server URL",    str(k3s.get("server_url", "")))
    s.field("Token KeePass Path",
            str(k3s.get("worker_token_path") or k3s.get("server_token_path") or "(in spawn-plan.json)"),
            note="Retrieved via KeePass gate — not stored in plain text")
    s.field("Node Labels",
            "\n".join(str(l) for l in (k3s.get("node_labels") or [])) or "(none)",
            note="Applied during k3s join")
    s.section("Phase-04 Status")
    s.phase_row("phase-04-k3s", "Ansible k3s role — applies join token and labels")
    if k3s.get("role") == "server":
        s.section("Phase-05 Status (HA Promotion)")
        s.phase_row("phase-05-ha", "SQLite → etcd migration (3rd server node only)")
    return s


def _sheet_validation(plan: dict) -> _SheetBuilder:
    s = _SheetBuilder("Validation")
    hostname = _g(plan, "hostname") or "broodling"
    s.title(f"Spawn Validation Checklist — {hostname}")
    s.headers("Check", "Description", "Status", "Timestamp")
    s.section("Pre-flight")
    checks = [
        ("Disks verified",           "All disk IDs in plan present and sized correctly"),
        ("NIC layout matches",        "NIC names and MACs match embedded hardware profile"),
        ("RAM sufficient",            "Available RAM ≥ sum of VM RAM + 10% overhead"),
        ("No ZFS pool conflict",      "No existing pool name matching planned pool"),
        ("No bridge conflict",        "No existing bridge matching planned bridge name"),
        ("Spawn manifest current",    "No VMID/IP/hostname conflicts against live hatchery"),
    ]
    for label, desc in checks:
        s.phase_row(label, desc)
    s.section("Phase Completion")
    phases = [
        ("phase-00-preflight",  "Hardware pre-flight — PASS gate before any writes"),
        ("phase-00-host",       "Hostname + bridges + ZFS pool + datastore registered"),
        ("phase-01-proxmox",    "Proxmox cluster member — visible in Datacenter"),
        ("phase-02-vms",        "VMs provisioned via tofu apply"),
        ("phase-03-cloudinit",  "Cloud-Init snippets installed; VMs started and SSH ready"),
        ("phase-04-k3s",        "k3s nodes joined; all nodes Ready"),
        ("phase-05-ha",         "HA promotion complete (conditional)"),
        ("phase-06-verify",     "Final health check — cluster healthy, all VMs running"),
    ]
    for phase, desc in phases:
        s.phase_row(phase, desc)
    s.section("Post-Spawn")
    post_checks = [
        ("bootstrap-state updated",    "Hatchery bootstrap-state.json updated with broodling"),
        ("DNS entries added",          "Broodling and VM entries in dns-registry.yaml"),
        ("Provenance recorded",        "Provenance records written for all new VMs"),
        ("Flux CD detected broodling", "Flux scheduler running on new k3s nodes"),
        ("Assessment re-run",          "Readiness scores updated after spawn"),
    ]
    for label, desc in post_checks:
        s.phase_row(label, desc)
    return s


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_spawn_workbook(
    plan: dict,
    hardware_profile: Optional[dict] = None,
) -> bytes:
    """
    Build the spawn workbook ODS from a spawn plan dict.

    Args:
        plan:             spawn-plan.json dict
        hardware_profile: optional hardware-profile.json dict (from 12.E.4)

    Returns:
        Raw bytes of the .ods file.
    """
    sheets = [
        _sheet_overview(plan),
        _sheet_discovery(plan, hardware_profile),
        _sheet_storage(plan),
        _sheet_network(plan),
        _sheet_proxmox(plan),
        _sheet_vms(plan),
        _sheet_k3s(plan),
        _sheet_validation(plan),
    ]

    sheets_xml = "".join(s.build_xml() for s in sheets)
    content_xml = (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<office:document-content {_CONTENT_NS}>'
        f'<office:automatic-styles>{_CELL_STYLES}</office:automatic-styles>'
        f'<office:body><office:spreadsheet>'
        f'{sheets_xml}'
        f'</office:spreadsheet></office:body>'
        f'</office:document-content>'
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), _MIMETYPE, compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/manifest.xml", _MANIFEST_XML)
        zf.writestr("content.xml",           content_xml)
        zf.writestr("styles.xml",            _STYLES_XML)
        zf.writestr("meta.xml",              _META_XML)

    return buf.getvalue()


def generate_spawn_workbook_file(
    plan: dict,
    output_path,
    hardware_profile: Optional[dict] = None,
) -> Path:
    """Write the spawn workbook to disk. Returns the output path."""
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(build_spawn_workbook(plan, hardware_profile))
    return p
