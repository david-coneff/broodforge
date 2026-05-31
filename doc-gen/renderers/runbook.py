#!/usr/bin/env python3
"""
runbook.py — ODT runbook renderer (stdlib only).

Generates a LibreOffice Writer (.odt) file from resolved field data.
ODT is a ZIP archive per OASIS ODF standard.
"""

import io
import zipfile
from typing import Any
from xml.sax.saxutils import escape as xml_escape


# ---------------------------------------------------------------------------
# ODT static files
# ---------------------------------------------------------------------------

MIMETYPE = b"application/vnd.oasis.opendocument.text"

MANIFEST_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"
                   manifest:version="1.2">
  <manifest:file-entry manifest:full-path="/"
      manifest:media-type="application/vnd.oasis.opendocument.text"/>
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
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
  office:version="1.2">
  <office:styles>
    <style:style style:name="Standard" style:family="paragraph" style:class="text">
      <style:paragraph-properties fo:margin-bottom="0.2cm"/>
      <style:text-properties fo:font-size="10pt" fo:font-family="Liberation Sans"/>
    </style:style>
    <style:style style:name="Heading1" style:family="paragraph" style:parent-style-name="Standard">
      <style:paragraph-properties fo:margin-top="0.5cm" fo:margin-bottom="0.3cm"
          fo:keep-with-next="always"/>
      <style:text-properties fo:font-size="16pt" fo:font-weight="bold" fo:color="#1F3864"/>
    </style:style>
    <style:style style:name="Heading2" style:family="paragraph" style:parent-style-name="Standard">
      <style:paragraph-properties fo:margin-top="0.4cm" fo:margin-bottom="0.2cm"
          fo:keep-with-next="always" fo:background-color="#D6E4F0"/>
      <style:text-properties fo:font-size="13pt" fo:font-weight="bold" fo:color="#1F3864"/>
    </style:style>
    <style:style style:name="Heading3" style:family="paragraph" style:parent-style-name="Standard">
      <style:paragraph-properties fo:margin-top="0.3cm" fo:margin-bottom="0.1cm"/>
      <style:text-properties fo:font-size="11pt" fo:font-weight="bold" fo:color="#1A5276"/>
    </style:style>
    <style:style style:name="BodyText" style:family="paragraph" style:parent-style-name="Standard">
      <style:paragraph-properties fo:margin-bottom="0.15cm"/>
      <style:text-properties fo:font-size="10pt"/>
    </style:style>
    <style:style style:name="Code" style:family="paragraph" style:parent-style-name="Standard">
      <style:paragraph-properties fo:margin-left="0.5cm" fo:margin-bottom="0.1cm"
          fo:background-color="#F2F3F4" fo:padding="0.1cm"/>
      <style:text-properties fo:font-size="9pt" fo:font-family="Liberation Mono"
          style:font-family-generic="modern"/>
    </style:style>
    <style:style style:name="FieldAuto" style:family="paragraph" style:parent-style-name="Standard">
      <style:paragraph-properties fo:margin-left="0.3cm" fo:background-color="#EBF5FB"
          fo:padding="0.05cm"/>
      <style:text-properties fo:font-size="10pt" fo:color="#1A5276"/>
    </style:style>
    <style:style style:name="FieldDerived" style:family="paragraph" style:parent-style-name="Standard">
      <style:paragraph-properties fo:margin-left="0.3cm" fo:background-color="#EAFAF1"
          fo:padding="0.05cm"/>
      <style:text-properties fo:font-size="10pt" fo:color="#145A32"/>
    </style:style>
    <style:style style:name="FieldHuman" style:family="paragraph" style:parent-style-name="Standard">
      <style:paragraph-properties fo:margin-left="0.3cm" fo:background-color="#FEFDE7"
          fo:padding="0.05cm"/>
      <style:text-properties fo:font-size="10pt" fo:color="#7D6608"/>
    </style:style>
    <style:style style:name="FieldUnresolved" style:family="paragraph" style:parent-style-name="Standard">
      <style:paragraph-properties fo:margin-left="0.3cm" fo:background-color="#FDEDEC"
          fo:padding="0.05cm"/>
      <style:text-properties fo:font-size="10pt" fo:color="#78281F"/>
    </style:style>
    <style:style style:name="Note" style:family="paragraph" style:parent-style-name="Standard">
      <style:paragraph-properties fo:margin-left="0.5cm"/>
      <style:text-properties fo:font-size="9pt" fo:color="#555555" fo:font-style="italic"/>
    </style:style>
    <style:style style:name="Checkbox" style:family="paragraph" style:parent-style-name="Standard">
      <style:paragraph-properties fo:margin-left="0.5cm" fo:background-color="#FFF9C4"/>
      <style:text-properties fo:font-size="10pt"/>
    </style:style>
  </office:styles>
  <office:automatic-styles/>
</office:document-styles>
"""

# ---------------------------------------------------------------------------
# ODT content builder
# ---------------------------------------------------------------------------

CONTENT_NS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
    'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
    'office:version="1.2"'
)


class RunbookBuilder:
    def __init__(self):
        self._paras: list[str] = []

    def _p(self, text: str, style: str = "BodyText") -> str:
        # Handle multi-line text — split on newlines
        lines = str(text).split("\n") if text else [""]
        parts = []
        for i, line in enumerate(lines):
            if i == 0:
                parts.append(f'<text:p text:style-name="{style}">{xml_escape(line)}</text:p>')
            else:
                parts.append(f'<text:p text:style-name="{style}">{xml_escape(line)}</text:p>')
        return "".join(parts)

    def h1(self, text: str) -> "RunbookBuilder":
        self._paras.append(self._p(text, "Heading1"))
        return self

    def h2(self, text: str) -> "RunbookBuilder":
        self._paras.append(self._p(text, "Heading2"))
        return self

    def h3(self, text: str) -> "RunbookBuilder":
        self._paras.append(self._p(text, "Heading3"))
        return self

    def body(self, text: str) -> "RunbookBuilder":
        self._paras.append(self._p(text, "BodyText"))
        return self

    def code(self, text: str) -> "RunbookBuilder":
        for line in str(text).split("\n"):
            self._paras.append(self._p(line or " ", "Code"))
        return self

    def field(self, label: str, value: Any, cls: str, note: str = "") -> "RunbookBuilder":
        style_map = {
            "AUTO":       "FieldAuto",
            "DERIVED":    "FieldDerived",
            "HUMAN":      "FieldHuman",
            "UNRESOLVED": "FieldUnresolved",
        }
        style = style_map.get(cls, "BodyText")
        tag = f"[{cls}]"
        v = str(value) if value is not None else "(not available)"
        self._paras.append(self._p(f"{tag}  {label}: {v}", style))
        if note:
            self._paras.append(self._p(f"       ↳ {note}", "Note"))
        return self

    def checkbox(self, text: str) -> "RunbookBuilder":
        self._paras.append(self._p(f"☐  {text}", "Checkbox"))
        return self

    def spacer(self) -> "RunbookBuilder":
        self._paras.append(self._p("", "BodyText"))
        return self

    def note(self, text: str) -> "RunbookBuilder":
        self._paras.append(self._p(f"ℹ  {text}", "Note"))
        return self

    def warning(self, text: str) -> "RunbookBuilder":
        self._paras.append(self._p(f"⚠  {text}", "FieldUnresolved"))
        return self

    def build_content_xml(self) -> str:
        body = "".join(self._paras)
        return (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<office:document-content {CONTENT_NS}>'
            f'<office:automatic-styles/>'
            f'<office:body>'
            f'<office:text>'
            f'{body}'
            f'</office:text>'
            f'</office:body>'
            f'</office:document-content>'
        )

    def build_odt(self) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(zipfile.ZipInfo("mimetype"), MIMETYPE,
                        compress_type=zipfile.ZIP_STORED)
            zf.writestr("META-INF/manifest.xml", MANIFEST_XML)
            zf.writestr("content.xml", self.build_content_xml())
            zf.writestr("styles.xml", STYLES_XML)
            zf.writestr("meta.xml", META_XML)
        return buf.getvalue()


# ---------------------------------------------------------------------------
# Bootstrap runbook builder
# ---------------------------------------------------------------------------

def _get(manifest: dict, path: str, default: Any = None) -> Any:
    parts = path.split(".")
    obj = manifest
    for p in parts:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(p, default)
        if obj is None:
            return default
    return obj


def _fmt_list(items: list, template: str, empty: str = "(none)") -> str:
    if not items:
        return empty
    lines = []
    for item in items:
        try:
            keys = {k: (str(v) if v is not None else "N/A") for k, v in item.items()}
            lines.append(template.format(**keys))
        except (KeyError, TypeError):
            lines.append(str(item))
    return "\n".join(lines)


def build_bootstrap_runbook(
    manifest: dict,
    resolved_fields: dict,
    generation_meta: dict,
) -> bytes:
    def r(field_id: str) -> dict:
        return resolved_fields.get(field_id, {"value": None, "class": "UNRESOLVED", "note": ""})

    def v(field_id: str) -> str:
        val = r(field_id)["value"]
        return str(val) if val is not None else "(not available)"

    def note(field_id: str) -> str:
        return r(field_id).get("note", "")

    def cls(field_id: str) -> str:
        return r(field_id).get("class", "UNRESOLVED")

    def warn_list(field_id: str) -> list:
        return r(field_id).get("warnings", [])

    rb = RunbookBuilder()

    hostname = v("host.hostname")
    pve_ver  = v("host.proxmox_version")
    collected = generation_meta.get("collected_at", "unknown")

    # -----------------------------------------------------------------------
    # Cover
    # -----------------------------------------------------------------------
    rb.h1("Bootstrap Runbook")
    rb.body(f"Host: {hostname}  |  Proxmox {pve_ver}  |  Assessment: {collected}")
    rb.body("Generated by Assessment Engine doc-gen. "
            "Fields are classified: [AUTO] from assessment  [DERIVED] computed  "
            "[HUMAN] operator input required  [UNRESOLVED] data unavailable.")
    rb.spacer()
    rb.body("Methodology: Observe → Decide → Act → Record → Validate")
    rb.spacer()

    # -----------------------------------------------------------------------
    # Stage 01 — Host Preparation
    # -----------------------------------------------------------------------
    rb.h1("Stage 01 — Proxmox Host Preparation")
    rb.body("Purpose: Configure the freshly installed Proxmox host — storage, networking, "
            "and base system settings — to a known-good state ready for VM deployment.")
    rb.spacer()

    rb.h2("Observed State")
    rb.field("Hostname",        v("host.hostname"),        cls("host.hostname"))
    rb.field("Proxmox Version", v("host.proxmox_version"), cls("host.proxmox_version"))
    rb.field("Kernel",          v("host.kernel_version"),  cls("host.kernel_version"))
    rb.field("CPU",
             f"{v('cpu.model')}  ({v('cpu.total_threads')} logical CPUs)",
             cls("cpu.model"))
    rb.field("RAM", f"{v('memory.total_gb')} GB total", cls("memory.total_gb"))
    rb.field("Block Devices",
             _fmt_list(_get(manifest, "storage.block_devices", []),
                       "{name}: {size_gb} GB  {model}  rotational={rotational}"),
             "AUTO")
    rb.field("Network",
             f"Gateway: {v('network.default_gateway')}  DNS: " +
             ", ".join(_get(manifest, "network.dns_servers", [])),
             "AUTO")
    rb.spacer()

    rb.h2("Decisions")
    rb.field("ZFS Topology",    v("derived.zfs_topology"),       cls("derived.zfs_topology"),       note("derived.zfs_topology"))
    rb.field("Pool Name",       v("derived.storage_pool_name"),  cls("derived.storage_pool_name"),  note("derived.storage_pool_name"))
    rb.field("VM Bridge",       v("derived.bridge_recommendation"), cls("derived.bridge_recommendation"), note("derived.bridge_recommendation"))
    rb.field("VM IP Range",     v("derived.vm_ip_plan"),         cls("derived.vm_ip_plan"),         note("derived.vm_ip_plan"))
    for w in warn_list("derived.zfs_topology"):
        rb.warning(w)
    rb.spacer()

    rb.h2("Step 1.1 — Verify SSH Access")
    rb.code(f"ssh root@{hostname}")
    rb.body("Expected: login succeeds, Proxmox welcome banner displayed.")
    rb.checkbox("SSH access confirmed")
    rb.spacer()

    rb.h2("Step 1.2 — Verify ZFS Pool")
    rb.code("zpool status")
    rb.field("Expected pool name",     v("derived.storage_pool_name"), cls("derived.storage_pool_name"))
    rb.field("Expected topology",      v("derived.zfs_topology"),      cls("derived.zfs_topology"))
    rb.body("Expected: pool state ONLINE, no errors.")
    rb.checkbox("ZFS pool healthy and ONLINE")
    rb.spacer()

    rb.h2("Step 1.3 — Verify Network Configuration")
    rb.code("ip addr show")
    rb.code("ip route show")
    rb.field("Expected bridge",  v("derived.bridge_recommendation"), cls("derived.bridge_recommendation"))
    rb.field("Expected gateway", v("network.default_gateway"),       cls("network.default_gateway"))
    rb.checkbox("Network configuration matches expected state")
    rb.spacer()

    rb.h2("Step 1.4 — Record Credentials")
    rb.field("Root password — KeePass path",
             "[HUMAN INPUT REQUIRED]", "HUMAN",
             "Record root password in KeePass before proceeding")
    rb.checkbox("Root password recorded in KeePass")
    rb.spacer()

    rb.h2("Step 1.5 — Verify Proxmox Web UI")
    rb.code(f"https://{hostname}:8006")
    rb.body("Expected: login page loads, authentication succeeds.")
    rb.checkbox("Proxmox web UI accessible and login confirmed")
    rb.spacer()

    rb.h2("Recovery: Stage 01 Failures")
    rb.body("SSH not accessible: verify host IP, check /etc/network/interfaces, restart networking.")
    rb.body("ZFS pool degraded: run 'zpool status' for detail, do not proceed until ONLINE.")
    rb.body("Web UI not accessible: check pveproxy service — 'systemctl status pveproxy'.")
    rb.spacer()

    # -----------------------------------------------------------------------
    # Stage 02 — Host Assessment
    # -----------------------------------------------------------------------
    rb.h1("Stage 02 — Host Assessment")
    rb.body("Purpose: Capture complete observed state of the host into the assessment record. "
            "This is the baseline from which all documentation is generated.")
    rb.spacer()

    rb.h2("Observed State — Complete Inventory")
    rb.h3("CPU")
    cpu = _get(manifest, "cpu", {})
    rb.field("Model",        str(cpu.get("model") or "N/A"),            "AUTO")
    rb.field("Architecture", str(cpu.get("architecture") or "N/A"),     "AUTO")
    rb.field("Logical CPUs", str(cpu.get("total_threads", "N/A")),      "AUTO")
    rb.field("Virtualization", str(cpu.get("virtualization") or "N/A"), "AUTO")

    rb.h3("Memory")
    mem = _get(manifest, "memory", {})
    rb.field("Total",     f"{mem.get('total_gb', 'N/A')} GB",     "AUTO")
    rb.field("Available", f"{mem.get('available_gb', 'N/A')} GB", "AUTO")

    rb.h3("Storage")
    block_devs = _get(manifest, "storage.block_devices", [])
    rb.field("Block Devices",
             _fmt_list(block_devs, "{name}: {size_gb} GB  {model}  rotational={rotational}",
                       "(none detected)"),
             "AUTO", f"{len(block_devs)} device(s)")
    rb.field("ZFS Pools",
             _fmt_list(_get(manifest, "storage.zfs_pools", []),
                       "{name}: {state}  topology={topology}  free={free_gb} GB"),
             "AUTO")

    rb.h3("Network")
    rb.field("Interfaces",
             _fmt_list(_get(manifest, "network.interfaces", []),
                       "{name}: {state}  {addresses}"),
             "AUTO")
    rb.field("Bridges",
             _fmt_list(_get(manifest, "network.bridges", []),
                       "{name}: ports={ports}  {addresses}"),
             "AUTO")

    rb.h3("Existing VMs and Containers")
    vms = _get(manifest, "vms", [])
    cts = _get(manifest, "containers", [])
    rb.field("VMs",
             _fmt_list(vms, "VM {vmid} ({name}): {status}", "(none)"),
             "AUTO", f"{len(vms)} VM(s)")
    rb.field("Containers",
             _fmt_list(cts, "CT {ctid} ({name}): {status}", "(none)"),
             "AUTO", f"{len(cts)} container(s)")

    rb.h3("Software")
    r_obj = _get(manifest, "software.automation_readiness", {})
    rb.field("Automation Tools",
             "  ".join(f"{k}={'✓' if v else '✗'}" for k, v in r_obj.items()),
             "AUTO")

    rb.h2("Step 2.1 — Run Bootstrap Assessment")
    rb.body("If not already done, run the Tier 1 assessment to capture fresh state:")
    rb.code("./bootstrap.sh")
    rb.body("Transfer the resulting archive to your management workstation.")
    rb.checkbox("Assessment archive transferred to workstation")

    rb.h2("Step 2.2 — Verify Assessment Completeness")
    errs = _get(manifest, "collection_errors", [])
    if errs:
        rb.warning(f"{len(errs)} collection error(s) detected:")
        for e in errs:
            rb.body(f"  [{e.get('collector')}] {e.get('message')}")
    else:
        rb.body("No collection errors detected.")
    rb.checkbox("Assessment gaps reviewed and understood")
    rb.spacer()

    # -----------------------------------------------------------------------
    # Stage 03 — Infra Bootstrap VM
    # -----------------------------------------------------------------------
    rb.h1("Stage 03 — Infra Bootstrap VM")
    rb.body("Purpose: Create the infra-bootstrap VM. This VM is the control node from which "
            "Ansible, OpenTofu, and the full automation platform will be deployed in later stages.")
    rb.spacer()

    vm_id   = v("derived.vm_id")
    ram_mb  = _ram_gb_to_mb(v("derived.vm_ram"))
    cores   = v("derived.vm_cores")
    pool    = v("derived.vm_storage_pool")
    bridge  = v("derived.vm_bridge")
    disk_gb = _disk_str_to_gb(v("derived.vm_disk"))

    rb.h2("Decisions")
    rb.field("VM ID",          vm_id,                         cls("derived.vm_id"),           note("derived.vm_id"))
    rb.field("RAM",            v("derived.vm_ram"),           cls("derived.vm_ram"),           note("derived.vm_ram"))
    rb.field("vCPUs",          cores,                         cls("derived.vm_cores"),         note("derived.vm_cores"))
    rb.field("Disk",           v("derived.vm_disk"),          cls("derived.vm_disk"),          note("derived.vm_disk"))
    rb.field("Storage Pool",   pool,                          cls("derived.vm_storage_pool"),  note("derived.vm_storage_pool"))
    rb.field("Network Bridge", bridge,                        cls("derived.vm_bridge"),        note("derived.vm_bridge"))
    rb.field("VM IP Address",  "[HUMAN INPUT REQUIRED]",      "HUMAN",
             f"Suggested range: {v('derived.vm_ip_plan')}")
    rb.field("VM ID Sequence", v("derived.vm_id_sequence"),   cls("derived.vm_id_sequence"),  note("derived.vm_id_sequence"))
    for w in warn_list("derived.vm_ram"):
        rb.warning(w)
    rb.spacer()

    rb.h2("Step 3.1 — Download Ubuntu ISO (if not present)")
    rb.code("# On the Proxmox host:")
    rb.code("wget -P /var/lib/vz/template/iso/ \\")
    rb.code("  https://releases.ubuntu.com/22.04/ubuntu-22.04.4-live-server-amd64.iso")
    rb.checkbox("Ubuntu ISO available in Proxmox local storage")
    rb.spacer()

    rb.h2("Step 3.2 — Create VM")
    rb.body("Run the following on the Proxmox host. "
            "Replace [VM_IP] and [CIDR_PREFIX] with values from the Decisions section above.")
    rb.code(
        f"qm create {vm_id} \\\n"
        f"  --name infra-bootstrap \\\n"
        f"  --memory {ram_mb} \\\n"
        f"  --cores {cores} \\\n"
        f"  --net0 virtio,bridge={bridge} \\\n"
        f"  --scsi0 {pool}:{disk_gb} \\\n"
        f"  --ide2 local:iso/ubuntu-22.04.4-live-server-amd64.iso,media=cdrom \\\n"
        f"  --boot order=ide2 \\\n"
        f"  --ostype l26 --serial0 socket --vga serial0"
    )
    rb.checkbox(f"VM {vm_id} (infra-bootstrap) created")
    rb.spacer()

    rb.h2("Step 3.3 — Configure Cloud-Init (Optional)")
    rb.body("If using cloud-init for automated Ubuntu setup:")
    rb.code(f"qm set {vm_id} --ciuser ubuntu --cipassword $(openssl passwd -6 'REPLACE_ME')")
    rb.code(f"qm set {vm_id} --ipconfig0 ip=[VM_IP]/24,gw={v('network.default_gateway')}")
    rb.code(f"qm set {vm_id} --nameserver {', '.join(_get(manifest, 'network.dns_servers', ['1.1.1.1']))}")
    rb.code(f"qm set {vm_id} --sshkeys ~/.ssh/authorized_keys")
    rb.checkbox("Cloud-init configured (or manual install selected)")
    rb.spacer()

    rb.h2("Step 3.4 — Start VM and Install OS")
    rb.code(f"qm start {vm_id}")
    rb.body(f"Monitor installation via Proxmox web UI → VM {vm_id} → Console.")
    rb.body("Complete Ubuntu installation. Set hostname, username, SSH key.")
    rb.field("Recommended username", "ubuntu", "HUMAN", "Or enter your preferred username above")
    rb.checkbox("Ubuntu installation complete")
    rb.spacer()

    rb.h2("Step 3.5 — Verify VM")
    rb.code("ssh ubuntu@[VM_IP]")
    rb.body("Expected: login succeeds.")
    rb.code("ping -c 3 1.1.1.1")
    rb.body("Expected: 3 packets transmitted, 3 received.")
    rb.code("sudo apt update")
    rb.body("Expected: package lists updated without errors.")
    rb.checkbox("SSH access to VM confirmed")
    rb.checkbox("Internet access from VM confirmed")
    rb.checkbox("Package manager works (apt update succeeds)")
    rb.spacer()

    rb.h2("Recovery: Stage 03 Failures")
    rb.body(f"VM won't start: check 'qm status {vm_id}', review Proxmox task log.")
    rb.body("Network not reachable: verify bridge configuration, check IP assignment.")
    rb.body("ISO not found: verify ISO path — 'ls /var/lib/vz/template/iso/'.")
    rb.spacer()

    # -----------------------------------------------------------------------
    # Appendix
    # -----------------------------------------------------------------------
    rb.h1("Appendix — Assessment Data")
    rb.body(f"Assessment collected: {collected}")
    rb.body(f"Host: {hostname} ({v('host.fqdn')})")
    rb.body(f"Proxmox: {pve_ver}")
    rb.spacer()
    rb.body("Field classification legend:")
    rb.body("  [AUTO]       — Populated directly from assessment data")
    rb.body("  [DERIVED]    — Computed by analysis module from assessment data")
    rb.body("  [HUMAN]      — Operator must provide; cannot be discovered automatically")
    rb.body("  [UNRESOLVED] — Expected data was unavailable during collection")
    rb.spacer()
    unresolved = generation_meta.get("unresolved_fields", [])
    if unresolved:
        rb.h2("Unresolved Fields")
        for uf in unresolved:
            rb.field(uf["id"], f"UNRESOLVED: {uf.get('reason', 'N/A')}", "UNRESOLVED",
                     f"Impact: {uf.get('impact', 'unknown')} | "
                     f"How to collect: {uf.get('guidance', 'see collection_errors in manifest')}")
    else:
        rb.body("No unresolved fields.")

    return rb.build_odt()


def _ram_gb_to_mb(val: str) -> str:
    try:
        n = int(val.replace("GB", "").replace("gb", "").strip())
        return str(n * 1024)
    except (ValueError, AttributeError):
        return "4096"


def _disk_str_to_gb(val: str) -> str:
    try:
        return str(int(val.replace("GB", "").replace("gb", "").strip()))
    except (ValueError, AttributeError):
        return "32"
