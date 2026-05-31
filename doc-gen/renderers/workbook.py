#!/usr/bin/env python3
"""
workbook.py — ODS workbook renderer (stdlib only, no odfpy).

Generates a LibreOffice Calc (.ods) file from resolved field data.
ODS is a ZIP archive containing XML files per the OASIS ODF standard.
"""

import io
import zipfile
from typing import Any
from xml.sax.saxutils import escape as xml_escape


# ---------------------------------------------------------------------------
# ODS XML constants
# ---------------------------------------------------------------------------

MIMETYPE = b"application/vnd.oasis.opendocument.spreadsheet"

MANIFEST_XML = """\
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

META_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<office:document-meta
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0"
  office:version="1.2">
  <office:meta>
    <meta:generator>Assessment Engine doc-gen v1.0</meta:generator>
  </office:meta>
</office:document-meta>
"""

STYLES_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<office:document-styles
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
  xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
  xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"
  office:version="1.2">
  <office:styles>
    <style:style style:name="Default" style:family="table-cell">
      <style:text-properties fo:font-size="10pt"/>
    </style:style>
  </office:styles>
  <office:automatic-styles/>
</office:document-styles>
"""


# ---------------------------------------------------------------------------
# Cell style definitions (embedded in content.xml automatic-styles)
# ---------------------------------------------------------------------------

CELL_STYLES = """\
    <!-- Section header -->
    <style:style style:name="ce_section" style:family="table-cell">
      <style:text-properties fo:font-weight="bold" fo:font-size="10pt"
          fo:color="#1F3864" fo:background-color="#D6E4F0"/>
      <style:table-cell-properties fo:background-color="#D6E4F0"
          fo:padding="2pt"/>
    </style:style>
    <!-- Sheet title -->
    <style:style style:name="ce_title" style:family="table-cell">
      <style:text-properties fo:font-weight="bold" fo:font-size="12pt"
          fo:color="#1F3864"/>
    </style:style>
    <!-- Label column -->
    <style:style style:name="ce_label" style:family="table-cell">
      <style:text-properties fo:font-weight="bold" fo:font-size="10pt"/>
    </style:style>
    <!-- AUTO field value -->
    <style:style style:name="ce_auto" style:family="table-cell">
      <style:text-properties fo:font-size="10pt" fo:color="#1A5276"/>
      <style:table-cell-properties fo:background-color="#EBF5FB"/>
    </style:style>
    <!-- DERIVED field value -->
    <style:style style:name="ce_derived" style:family="table-cell">
      <style:text-properties fo:font-size="10pt" fo:color="#145A32"/>
      <style:table-cell-properties fo:background-color="#EAFAF1"/>
    </style:style>
    <!-- HUMAN field value (blank, highlighted for input) -->
    <style:style style:name="ce_human" style:family="table-cell">
      <style:text-properties fo:font-size="10pt" fo:color="#7D6608"/>
      <style:table-cell-properties fo:background-color="#FEFDE7"
          style:cell-protect="formula-hidden"/>
    </style:style>
    <!-- UNRESOLVED field value -->
    <style:style style:name="ce_unresolved" style:family="table-cell">
      <style:text-properties fo:font-size="10pt" fo:color="#78281F"/>
      <style:table-cell-properties fo:background-color="#FDEDEC"/>
    </style:style>
    <!-- Rationale / note text -->
    <style:style style:name="ce_note" style:family="table-cell">
      <style:text-properties fo:font-size="9pt" fo:color="#555555" fo:font-style="italic"/>
    </style:style>
    <!-- Checkbox placeholder -->
    <style:style style:name="ce_checkbox" style:family="table-cell">
      <style:text-properties fo:font-size="10pt"/>
      <style:table-cell-properties fo:background-color="#FFF9C4"/>
    </style:style>
    <!-- Column width styles -->
    <style:style style:name="co_label" style:family="table-column">
      <style:table-column-properties style:column-width="5.5cm"/>
    </style:style>
    <style:style style:name="co_value" style:family="table-column">
      <style:table-column-properties style:column-width="9cm"/>
    </style:style>
    <style:style style:name="co_note" style:family="table-column">
      <style:table-column-properties style:column-width="10cm"/>
    </style:style>
    <style:style style:name="co_class" style:family="table-column">
      <style:table-column-properties style:column-width="2.5cm"/>
    </style:style>
    <!-- Row height for section headers -->
    <style:style style:name="ro_section" style:family="table-row">
      <style:table-row-properties style:row-height="0.7cm" fo:background-color="#D6E4F0"/>
    </style:style>
    <style:style style:name="ro_normal" style:family="table-row">
      <style:table-row-properties style:row-height="0.55cm"/>
    </style:style>
"""

CLASS_STYLE = {
    "AUTO":       "ce_auto",
    "DERIVED":    "ce_derived",
    "HUMAN":      "ce_human",
    "UNRESOLVED": "ce_unresolved",
}


# ---------------------------------------------------------------------------
# XML helpers
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


def _empty_cell(n: int = 1) -> str:
    if n == 1:
        return '<table:table-cell/>'
    return f'<table:table-cell table:number-columns-repeated="{n}"/>'


def _row(cells: list[str], style: str = "ro_normal") -> str:
    return f'<table:table-row table:style-name="{style}">{"".join(cells)}</table:table-row>'


def _section_header_row(title: str) -> str:
    return _row([
        _cell(f"  {title}", style="ce_section"),
        _cell("", style="ce_section"),
        _cell("", style="ce_section"),
        _cell("", style="ce_section"),
    ], style="ro_section")


def _legend_row() -> str:
    return _row([
        _cell("CLASS LEGEND:", style="ce_label"),
        _cell("[AUTO] From assessment  [DERIVED] Computed  [HUMAN] Operator input  "
              "[UNRESOLVED] Missing — see note", style="ce_note"),
        _cell("", style="Default"),
        _cell("", style="Default"),
    ])


# ---------------------------------------------------------------------------
# Sheet builder
# ---------------------------------------------------------------------------

class SheetBuilder:
    def __init__(self, name: str):
        self.name = name
        self._rows: list[str] = []

    def title(self, text: str) -> "SheetBuilder":
        self._rows.append(_row([
            _cell(text, style="ce_title"),
            _empty_cell(3),
        ]))
        self._rows.append(_row([_empty_cell(4)]))
        return self

    def column_headers(self) -> "SheetBuilder":
        self._rows.append(_row([
            _cell("Field", style="ce_label"),
            _cell("Value", style="ce_label"),
            _cell("Class", style="ce_label"),
            _cell("Note / Rationale", style="ce_label"),
        ]))
        return self

    def section(self, title: str) -> "SheetBuilder":
        self._rows.append(_row([_empty_cell(4)]))
        self._rows.append(_section_header_row(title))
        return self

    def field(self, label: str, value: Any, cls: str, note: str = "") -> "SheetBuilder":
        v_style = CLASS_STYLE.get(cls, "Default")
        self._rows.append(_row([
            _cell(label, style="ce_label"),
            _cell(value if value is not None else "", style=v_style, wrap=True),
            _cell(f"[{cls}]", style="ce_label"),
            _cell(note, style="ce_note", wrap=True),
        ]))
        return self

    def human_field(self, label: str, prompt: str,
                    is_checkbox: bool = False) -> "SheetBuilder":
        value = "☐  (enter value)" if not is_checkbox else "☐  (check when complete)"
        self._rows.append(_row([
            _cell(label, style="ce_label"),
            _cell(value, style="ce_human"),
            _cell("[HUMAN]", style="ce_label"),
            _cell(prompt, style="ce_note", wrap=True),
        ]))
        return self

    def spacer(self) -> "SheetBuilder":
        self._rows.append(_row([_empty_cell(4)]))
        return self

    def legend(self) -> "SheetBuilder":
        self._rows.append(_row([_empty_cell(4)]))
        self._rows.append(_legend_row())
        return self

    def build_xml(self) -> str:
        safe_name = xml_escape(self.name)
        col_defs = (
            '<table:table-column table:style-name="co_label"/>'
            '<table:table-column table:style-name="co_value"/>'
            '<table:table-column table:style-name="co_class"/>'
            '<table:table-column table:style-name="co_note"/>'
        )
        rows_xml = "".join(self._rows)
        return (
            f'<table:table table:name="{safe_name}">'
            f'{col_defs}{rows_xml}'
            f'</table:table>'
        )


# ---------------------------------------------------------------------------
# ODS file assembly
# ---------------------------------------------------------------------------

CONTENT_NS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
    'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
    'xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0" '
    'office:version="1.2"'
)


def build_ods(sheets: list[SheetBuilder]) -> bytes:
    """Assemble an ODS byte stream from a list of SheetBuilder objects."""
    sheets_xml = "".join(s.build_xml() for s in sheets)

    content_xml = (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<office:document-content {CONTENT_NS}>'
        f'<office:automatic-styles>{CELL_STYLES}</office:automatic-styles>'
        f'<office:body>'
        f'<office:spreadsheet>'
        f'{sheets_xml}'
        f'</office:spreadsheet>'
        f'</office:body>'
        f'</office:document-content>'
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # mimetype must be first entry and uncompressed
        zf.writestr(
            zipfile.ZipInfo("mimetype"),
            MIMETYPE,
            compress_type=zipfile.ZIP_STORED,
        )
        zf.writestr("META-INF/manifest.xml", MANIFEST_XML)
        zf.writestr("content.xml", content_xml)
        zf.writestr("styles.xml", STYLES_XML)
        zf.writestr("meta.xml", META_XML)

    return buf.getvalue()


# ---------------------------------------------------------------------------
# Bootstrap workbook builder
# ---------------------------------------------------------------------------

def _fmt_list(items: list, template: str, empty: str = "(none)") -> str:
    """Format a list of dicts using a template string."""
    if not items:
        return empty
    lines = []
    for item in items:
        try:
            # Simple {key} substitution; missing keys → "N/A"
            keys = {k: (str(v) if v is not None else "N/A") for k, v in item.items()}
            lines.append(template.format(**keys))
        except (KeyError, TypeError):
            lines.append(str(item))
    return "\n".join(lines)


def _fmt_kv(d: dict) -> str:
    if not d:
        return "(none)"
    return "\n".join(f"{k}: {'YES' if v else 'no'}" for k, v in d.items())


def _get(manifest: dict, path: str, default: Any = None) -> Any:
    """Dot-notation path lookup in manifest."""
    parts = path.split(".")
    obj = manifest
    for p in parts:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(p, default)
        if obj is None:
            return default
    return obj


def build_bootstrap_workbook(
    manifest: dict,
    resolved_fields: dict,
    generation_meta: dict,
) -> bytes:
    """
    Build the full bootstrap workbook ODS from a resolved field dict.

    resolved_fields: {field_id: {"value": ..., "class": ..., "note": ...}}
    """

    def r(field_id: str) -> dict:
        return resolved_fields.get(field_id, {"value": None, "class": "UNRESOLVED", "note": ""})

    def v(field_id: str) -> str:
        return str(r(field_id)["value"] or "")

    def note(field_id: str) -> str:
        return r(field_id).get("note", "")

    def cls(field_id: str) -> str:
        return r(field_id).get("class", "UNRESOLVED")

    # ---- Sheet 1: Stage 01 — Host Preparation ----
    s01 = SheetBuilder("Stage 01 — Host Preparation")
    s01.title("Stage 01 — Proxmox Host Preparation")
    s01.column_headers()

    s01.section("Host Identification")
    s01.field("Hostname",            v("host.hostname"),       cls("host.hostname"),       note("host.hostname"))
    s01.field("FQDN",                v("host.fqdn"),           cls("host.fqdn"),           note("host.fqdn"))
    s01.field("Proxmox Version",     v("host.proxmox_version"),cls("host.proxmox_version"),note("host.proxmox_version"))
    s01.field("Kernel Version",      v("host.kernel_version"), cls("host.kernel_version"), note("host.kernel_version"))
    s01.field("Timezone",            v("host.timezone"),       cls("host.timezone"),       note("host.timezone"))

    s01.section("Hardware Summary")
    s01.field("CPU Model",           v("cpu.model"),           cls("cpu.model"),           note("cpu.model"))
    s01.field("Logical CPU Count",   v("cpu.total_threads"),   cls("cpu.total_threads"),   note("cpu.total_threads"))
    s01.field("Total RAM",           v("memory.total_gb"),     cls("memory.total_gb"),     note("memory.total_gb"))
    s01.field("Available RAM",       v("memory.available_gb"), cls("memory.available_gb"), note("memory.available_gb"))
    s01.field("Virtualization",      v("cpu.virtualization"),  cls("cpu.virtualization"),  note("cpu.virtualization"))

    s01.section("Storage Inventory")
    s01.field("Block Devices",
              _fmt_list(_get(manifest, "storage.block_devices", []),
                        "{name}: {size_gb} GB  model={model}  rotational={rotational}"),
              "AUTO", "Detected from lsblk")
    s01.field("Existing ZFS Pools",
              _fmt_list(_get(manifest, "storage.zfs_pools", []),
                        "{name}: topology={topology}  free={free_gb} GB"),
              "AUTO", "From zpool list")

    s01.section("ZFS Configuration Recommendation")
    s01.field("Recommended Topology",v("derived.zfs_topology"), cls("derived.zfs_topology"), note("derived.zfs_topology"))
    s01.field("Recommended Pool Name",v("derived.storage_pool_name"),cls("derived.storage_pool_name"),note("derived.storage_pool_name"))
    s01.human_field("ZFS config approved by operator", "Review topology above. Check when confirmed.", is_checkbox=True)

    s01.section("Network Inventory")
    s01.field("Default Gateway",     v("network.default_gateway"), cls("network.default_gateway"), note("network.default_gateway"))
    s01.field("DNS Servers",         v("network.dns_servers"),     cls("network.dns_servers"),     note("network.dns_servers"))
    s01.field("Network Interfaces",
              _fmt_list(_get(manifest, "network.interfaces", []),
                        "{name}: {state}  {addresses}"),
              "AUTO", "From ip addr")
    s01.field("Bridges",
              _fmt_list(_get(manifest, "network.bridges", []),
                        "{name}: ports={ports}  {addresses}"),
              "AUTO", "From /etc/network/interfaces")
    s01.field("Recommended VM Bridge", v("derived.bridge_recommendation"), cls("derived.bridge_recommendation"), note("derived.bridge_recommendation"))
    s01.field("Suggested VM IP Range", v("derived.vm_ip_plan"),            cls("derived.vm_ip_plan"),            note("derived.vm_ip_plan"))

    s01.section("Credential Locations (Operator Input)")
    s01.human_field("Root password — KeePass path",
                    "Enter KeePass path, e.g. Infrastructure/proxmox/pve01-root")
    s01.human_field("Encryption passphrase — KeePass path",
                    "If using disk encryption. Leave blank if not applicable.")

    s01.section("Validation Checkpoints")
    s01.human_field("SSH access confirmed",  f"ssh root@{v('host.hostname')} — verify login",  is_checkbox=True)
    s01.human_field("Web UI accessible",     f"https://{v('host.hostname')}:8006 — verify login", is_checkbox=True)
    s01.human_field("ZFS pool healthy",      "Run: zpool status — verify ONLINE",             is_checkbox=True)

    s01.legend()

    # ---- Sheet 2: Stage 02 — Host Assessment ----
    s02 = SheetBuilder("Stage 02 — Host Assessment")
    s02.title("Stage 02 — Host Assessment (Observed State)")
    s02.column_headers()

    s02.section("CPU")
    cpu = _get(manifest, "cpu", {})
    s02.field("Model",        str(cpu.get("model") or "N/A"),           "AUTO", "")
    s02.field("Architecture", str(cpu.get("architecture") or "N/A"),    "AUTO", "")
    s02.field("Sockets",      str(cpu.get("sockets") or "N/A"),         "AUTO", "")
    s02.field("Cores/Socket", str(cpu.get("cores_per_socket") or "N/A"),"AUTO", "")
    s02.field("Threads/Core", str(cpu.get("threads_per_core") or "N/A"),"AUTO", "")
    s02.field("Total Logical CPUs", str(cpu.get("total_threads", "N/A")),"AUTO", "")
    s02.field("Virtualization",    str(cpu.get("virtualization") or "N/A"),"AUTO", "")

    s02.section("Memory")
    mem = _get(manifest, "memory", {})
    s02.field("Total RAM",     f"{mem.get('total_gb', 'N/A')} GB",     "AUTO", "")
    s02.field("Available RAM", f"{mem.get('available_gb', 'N/A')} GB", "AUTO", "")
    s02.field("Swap",          f"{mem.get('swap_total_gb', 'N/A')} GB","AUTO", "")
    s02.field("NUMA Nodes",    str(mem.get("numa_nodes") or "N/A"),    "AUTO", "")

    s02.section("Storage")
    block_devs = _get(manifest, "storage.block_devices", [])
    s02.field("Block Devices",
              _fmt_list(block_devs,
                        "{name}: {size_gb} GB  type={type}  rotational={rotational}  model={model}  transport={transport}"),
              "AUTO", f"{len(block_devs)} device(s) detected")
    s02.field("ZFS Pools",
              _fmt_list(_get(manifest, "storage.zfs_pools", []),
                        "{name}: state={state}  topology={topology}  total={total_gb} GB  free={free_gb} GB  devices={devices}"),
              "AUTO", "")
    s02.field("PVE Storage",
              _fmt_list(_get(manifest, "storage.pve_storage", []),
                        "{name} ({type}): total={total_gb} GB  free={free_gb} GB  active={active}"),
              "AUTO", "")

    s02.section("Network")
    s02.field("Interfaces",
              _fmt_list(_get(manifest, "network.interfaces", []),
                        "{name}: state={state}  mac={mac}  addresses={addresses}  mtu={mtu}"),
              "AUTO", "")
    s02.field("Bridges",
              _fmt_list(_get(manifest, "network.bridges", []),
                        "{name}: ports={ports}  addresses={addresses}  vlan_aware={vlan_aware}"),
              "AUTO", "")
    s02.field("VLANs",
              _fmt_list(_get(manifest, "network.vlans", []),
                        "{name}: vlan_id={vlan_id}  parent={parent}", "(none)"),
              "AUTO", "")
    s02.field("Default Gateway", str(_get(manifest, "network.default_gateway") or "N/A"), "AUTO", "")
    s02.field("DNS Servers",
              ", ".join(_get(manifest, "network.dns_servers", [])) or "N/A",
              "AUTO", "")

    s02.section("Virtual Machines")
    vms = _get(manifest, "vms", [])
    s02.field("VMs",
              _fmt_list(vms,
                        "VM {vmid} ({name}): {status}  cores={cores}  mem={memory_mb} MB",
                        "(no existing VMs)"),
              "AUTO", f"{len(vms)} VM(s)")
    cts = _get(manifest, "containers", [])
    s02.field("Containers",
              _fmt_list(cts,
                        "CT {ctid} ({name}): {status}", "(no existing containers)"),
              "AUTO", f"{len(cts)} container(s)")

    s02.section("Software")
    s02.field("Automation Tools",
              _fmt_kv(_get(manifest, "software.automation_readiness", {})),
              "AUTO", "")
    s02.field("Automation Readiness", v("derived.automation_summary"),
              cls("derived.automation_summary"), note("derived.automation_summary"))
    s02.field("Running Services",
              ", ".join(_get(manifest, "software.running_services", [])) or "(none)",
              "AUTO", "")

    s02.section("Assessment Gaps")
    errs = _get(manifest, "collection_errors", [])
    s02.field("Collection Errors",
              _fmt_list(errs, "[{collector}] {message}", "(none)"),
              "AUTO" if not errs else "UNRESOLVED",
              f"{len(errs)} error(s)" if errs else "")
    warns = _get(manifest, "collection_warnings", [])
    s02.field("Collection Warnings",
              _fmt_list(warns, "[{collector}] {message}", "(none)"),
              "AUTO", f"{len(warns)} warning(s)" if warns else "")

    s02.legend()

    # ---- Sheet 3: Stage 03 — Infra Bootstrap VM ----
    s03 = SheetBuilder("Stage 03 — Infra Bootstrap VM")
    s03.title("Stage 03 — Infra Bootstrap VM Configuration")
    s03.column_headers()

    s03.section("VM Configuration")
    s03.field("VM ID",          v("derived.vm_id"),           cls("derived.vm_id"),           note("derived.vm_id"))
    s03.field("RAM Allocation", v("derived.vm_ram"),          cls("derived.vm_ram"),          note("derived.vm_ram"))
    s03.field("vCPU Count",     v("derived.vm_cores"),        cls("derived.vm_cores"),        note("derived.vm_cores"))
    s03.field("Boot Disk Size", v("derived.vm_disk"),         cls("derived.vm_disk"),         note("derived.vm_disk"))
    s03.field("Storage Pool",   v("derived.vm_storage_pool"), cls("derived.vm_storage_pool"), note("derived.vm_storage_pool"))
    s03.field("Network Bridge", v("derived.vm_bridge"),       cls("derived.vm_bridge"),       note("derived.vm_bridge"))
    s03.human_field("VM IP Address", "Enter static IP. Suggested range: " + v("derived.vm_ip_plan"))
    s03.human_field("VM Name",       "Enter VM name (default: infra-bootstrap)")

    s03.section("OS Configuration")
    s03.human_field("Ubuntu ISO path", "Path to ISO in Proxmox storage, e.g. local:iso/ubuntu-22.04-live-server-amd64.iso")
    s03.human_field("OS username",     "Initial OS username (e.g. ubuntu)")
    s03.human_field("VM password — KeePass path", "Enter KeePass path for VM password")

    s03.section("Bootstrap VM ID Sequence")
    s03.field("VM IDs for Stages 03–12",
              v("derived.vm_id_sequence"),
              cls("derived.vm_id_sequence"),
              note("derived.vm_id_sequence"))

    s03.section("Create VM Command (Auto-generated)")
    vm_id   = v("derived.vm_id")
    ram_mb  = _ram_gb_to_mb(v("derived.vm_ram"))
    cores   = v("derived.vm_cores")
    pool    = v("derived.vm_storage_pool")
    bridge  = v("derived.vm_bridge")
    disk_gb = _disk_str_to_gb(v("derived.vm_disk"))
    cmd = (
        f"qm create {vm_id} \\\n"
        f"  --name infra-bootstrap \\\n"
        f"  --memory {ram_mb} \\\n"
        f"  --cores {cores} \\\n"
        f"  --net0 virtio,bridge={bridge} \\\n"
        f"  --scsi0 {pool}:{disk_gb} \\\n"
        f"  --ostype l26 --serial0 socket --vga serial0"
    )
    s03.field("qm create command", cmd, "DERIVED",
              "Parameters derived from assessment. Replace [VM_IP] in cloud-init after creation.")

    s03.section("Validation Checkpoints")
    s03.human_field("VM created in Proxmox web UI", "Verify VM appears with correct ID and name", is_checkbox=True)
    s03.human_field("VM boots to OS", "Start VM and confirm OS boot completes", is_checkbox=True)
    s03.human_field("SSH access confirmed", "ssh ubuntu@[VM_IP] — verify login", is_checkbox=True)
    s03.human_field("Internet access from VM", "From VM: ping 1.1.1.1 — verify response", is_checkbox=True)

    s03.legend()

    # ---- Sheet 4: Generation Report ----
    rpt = SheetBuilder("Generation Report")
    rpt.title("Documentation Generation Report")
    rpt.column_headers()

    meta = generation_meta
    rpt.section("Generation Metadata")
    rpt.field("Generated At",    meta.get("generated_at", "N/A"),  "AUTO", "")
    rpt.field("Assessment Tier", str(meta.get("tier", "N/A")),     "AUTO", "")
    rpt.field("Assessment Date", meta.get("collected_at", "N/A"),  "AUTO", "")
    rpt.field("Template Version",meta.get("template_version", "bootstrap-v1.0"), "AUTO", "")

    rpt.section("Field Summary")
    counts = meta.get("field_counts", {})
    total  = sum(counts.values())
    for cls_name in ("AUTO", "DERIVED", "HUMAN", "UNRESOLVED"):
        n = counts.get(cls_name, 0)
        pct = f"{100*n//total}%" if total else "0%"
        rpt.field(cls_name, f"{n} fields ({pct})", CLASS_STYLE.get(cls_name, "Default"), "")

    unresolved = meta.get("unresolved_fields", [])
    if unresolved:
        rpt.section("Unresolved Fields")
        for uf in unresolved:
            rpt.field(uf["id"], uf.get("reason", "N/A"), "UNRESOLVED",
                      f"Impact: {uf.get('impact', 'unknown')}")

    human_fields = meta.get("human_fields", [])
    if human_fields:
        rpt.section("Human Input Required")
        for hf in human_fields:
            rpt.field(hf["id"], "(blank)", "HUMAN", hf.get("prompt", ""))

    return build_ods([s01, s02, s03, rpt])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ram_gb_to_mb(val: str) -> str:
    """Convert '8 GB' → '8192'."""
    try:
        n = int(val.replace("GB", "").replace("gb", "").strip())
        return str(n * 1024)
    except (ValueError, AttributeError):
        return "4096"  # safe default


def _disk_str_to_gb(val: str) -> str:
    """Convert '64 GB' → '64'."""
    try:
        return str(int(val.replace("GB", "").replace("gb", "").strip()))
    except (ValueError, AttributeError):
        return "32"
