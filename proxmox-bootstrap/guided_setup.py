#!/usr/bin/env python3
"""
guided_setup.py — Guided Setup Framework core engine (Phase 1.G).

Provides the suggestion-revision and conflict-detection machinery used by
all three deployment packages (forge, spawn, phoenix).

Four configuration modes:
  autonomous    All settings auto-calculated (default).
  ip-selective  Autonomous except operator chooses IP addressing.
  group-manual  Operator selects which setting groups to configure manually.
  full-manual   Operator walks through all settings with auto-suggestions.

Key types:
  SETTING_GROUPS   — dict defining the seven setting groups and their field paths
  GuidedSetupSession — session state: mode, selected groups, choices, warnings
  suggest()        — returns an auto-suggestion, revised from current choices
  set_value()      — records a choice and returns conflict warnings
  check_conflicts()— checks a proposed value against current session state

Stdlib only. No terminal I/O in this module — I/O is handled by callers
(forge-planner.py, spawn-planner.py) so the engine is fully testable.
"""

import ipaddress
import re
from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Setting groups
# ---------------------------------------------------------------------------

# Each group maps to a list of field paths that belong to it.
# Field paths use dot-notation (e.g., "network.management_cidr").
SETTING_GROUPS: dict[str, dict] = {
    "network": {
        "label": "Network",
        "description": "Management CIDR, gateway, bridge names, VLANs, DNS, Headscale",
        "fields": [
            "network.management_cidr",
            "network.gateway",
            "network.nameservers",
            "network.search_domain",
            "network.bridge_name",
            "network.vlan_aware",
            "network.headscale_url",
        ],
        "representative_field": "network.management_cidr",
    },
    "storage": {
        "label": "Storage",
        "description": "ZFS pool topology, pool name, datastore names, disk assignment",
        "fields": [
            "storage.pool_name",
            "storage.topology",
            "storage.disks",
            "storage.datastore_name",
        ],
        "representative_field": "storage.topology",
    },
    "vm_sizing": {
        "label": "VM Sizing",
        "description": "VMID block, per-VM RAM/CPU/disk, placement",
        "fields": [
            "vms.vmid_start",
            "vms.default_ram_gb",
            "vms.default_cores",
            "vms.default_disk_gb",
        ],
        "representative_field": "vms.vmid_start",
    },
    "identity": {
        "label": "Identity",
        "description": "Hostname, domain, FQDN, cell_id, naming convention",
        "fields": [
            "host_identity.hostname",
            "host_identity.domain",
            "host_identity.fqdn",
            "host_identity.cell_id",
        ],
        "representative_field": "host_identity.hostname",
    },
    "security": {
        "label": "Security",
        "description": "KeePass location, password format, SSH key references",
        "fields": [
            "security.kdbx_path",
            "security.password_format",
            "security.ssh_key_path",
        ],
        "representative_field": "security.kdbx_path",
    },
    "k3s": {
        "label": "k3s",
        "description": "Pod/service CIDR, CNI plugin, initial cluster role",
        "fields": [
            "k3s.pod_cidr",
            "k3s.service_cidr",
            "k3s.cni",
            "k3s.initial_role",
        ],
        "representative_field": "k3s.pod_cidr",
    },
    "backup": {
        "label": "Backup",
        "description": "Restic destinations, retention policy, DDNS provider",
        "fields": [
            "backup.secrets_destinations",
            "backup.config_destinations",
            "backup.retention_count",
            "backup.ddns_provider",
        ],
        "representative_field": "backup.config_destinations",
    },
}

MODES = ("autonomous", "ip-selective", "group-manual", "full-manual")

# IP-selective mode only prompts for these fields
IP_SELECTIVE_FIELDS = {
    "network.management_cidr",
    "network.gateway",
    "network.nameservers",
}


# ---------------------------------------------------------------------------
# Choice record
# ---------------------------------------------------------------------------

@dataclass
class Choice:
    field_path: str
    value: Any
    source: str   # 'auto' | 'manual'


# ---------------------------------------------------------------------------
# GuidedSetupSession
# ---------------------------------------------------------------------------

@dataclass
class GuidedSetupSession:
    """
    Tracks the operator's configuration choices during guided setup.

    mode:            autonomous | ip-selective | group-manual | full-manual
    manifest:        base manifest dict from discovery (read-only reference)
    selected_groups: groups the operator has chosen to configure manually
    choices:         field_path → Choice (current value + source)
    warnings:        list of conflict/warning strings from set_value() calls
    """
    mode:             str
    manifest:         dict
    selected_groups:  set = field(default_factory=set)
    choices:          dict = field(default_factory=dict)   # field_path → Choice
    warnings:         list = field(default_factory=list)

    def is_manual_field(self, field_path: str) -> bool:
        """Return True if this field should be prompted manually in current mode."""
        if self.mode == "autonomous":
            return False
        if self.mode == "ip-selective":
            return field_path in IP_SELECTIVE_FIELDS
        if self.mode == "group-manual":
            for gname, gdef in SETTING_GROUPS.items():
                if gname in self.selected_groups and field_path in gdef["fields"]:
                    return True
            return False
        # full-manual: everything is manual
        return True

    def get_value(self, field_path: str) -> Optional[Any]:
        """Return the current value for a field (manual or auto)."""
        choice = self.choices.get(field_path)
        return choice.value if choice else None

    def is_manually_set(self, field_path: str) -> bool:
        choice = self.choices.get(field_path)
        return bool(choice and choice.source == "manual")


# ---------------------------------------------------------------------------
# Suggestion engine — revised from current choices
# ---------------------------------------------------------------------------

def _get_manifest_val(manifest: dict, path: str, default=None):
    parts = path.split(".")
    obj = manifest
    for p in parts:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(p, default)
    return obj


def suggest(field_path: str, session: GuidedSetupSession) -> Any:
    """
    Return the auto-suggestion for a field, revised to be logically
    consistent with choices already made in the session.

    If the operator has already set a value manually, returns that value.
    """
    if field_path in session.choices:
        return session.choices[field_path].value

    m = session.manifest
    chosen_cidr = session.get_value("network.management_cidr")
    chosen_hostname = session.get_value("host_identity.hostname")
    chosen_domain = session.get_value("host_identity.domain")
    chosen_pool = session.get_value("storage.pool_name")
    chosen_vmid_start = session.get_value("vms.vmid_start")

    # ── Network ─────────────────────────────────────────────────────────────

    if field_path == "network.management_cidr":
        # Prefer discovered network topology CIDR
        cidr = _get_manifest_val(m, "network_topology.management_cidr")
        if cidr:
            return cidr
        # Infer from gateway
        gw = _get_manifest_val(m, "network.default_gateway")
        if gw:
            try:
                net = ipaddress.ip_interface(f"{gw}/24").network
                return str(net)
            except ValueError:
                pass
        return "192.168.1.0/24"

    if field_path == "network.gateway":
        if chosen_cidr:
            try:
                net = ipaddress.ip_network(chosen_cidr, strict=False)
                return str(next(net.hosts()))
            except ValueError:
                pass
        return _get_manifest_val(m, "network.default_gateway") or "192.168.1.1"

    if field_path == "network.nameservers":
        discovered = _get_manifest_val(m, "network.dns_servers") or []
        if discovered:
            return discovered
        gw = suggest("network.gateway", session)
        return [gw, "8.8.8.8"]

    if field_path == "network.search_domain":
        return _get_manifest_val(m, "network_topology.search_domain") or "internal"

    if field_path == "network.bridge_name":
        return _get_manifest_val(m, "network_topology.interface_name") and "vmbr0" or "vmbr0"

    if field_path == "network.vlan_aware":
        return True

    if field_path == "network.headscale_url":
        fqdn = suggest("host_identity.fqdn", session)
        return f"https://{fqdn}:8080"

    # ── Storage ──────────────────────────────────────────────────────────────

    if field_path == "storage.topology":
        pools = _get_manifest_val(m, "storage.zfs_pools") or []
        if pools:
            return pools[0].get("topology", "mirror")
        block_devs = _get_manifest_val(m, "storage.block_devices") or []
        from network_topology_collector import _zfs_topology_from_disk_count  # reuse
        return _zfs_topology_from_disk_count(len(block_devs))

    if field_path == "storage.pool_name":
        pools = _get_manifest_val(m, "storage.zfs_pools") or []
        if pools:
            return pools[0].get("name", "rpool")
        return "rpool"

    if field_path == "storage.datastore_name":
        pool = chosen_pool or suggest("storage.pool_name", session)
        return f"local-{pool}"

    if field_path == "storage.disks":
        block_devs = _get_manifest_val(m, "storage.block_devices") or []
        return [d.get("name") for d in block_devs if d.get("name")]

    # ── VM Sizing ─────────────────────────────────────────────────────────────

    if field_path == "vms.vmid_start":
        # Default to 100 unless existing VMs show a higher base
        vms = _get_manifest_val(m, "vms") or []
        existing_ids = [int(v["vmid"]) for v in vms if v.get("vmid")]
        return max(existing_ids, default=99) + 1

    if field_path == "vms.default_ram_gb":
        mem_total = _get_manifest_val(m, "memory.total_gb") or 32
        n_vms = max(len(_get_manifest_val(m, "vms") or []), 3)
        # Suggest ~25% of host RAM per VM, floor at 2 GB
        per_vm = max(int(mem_total * 0.25), 2)
        return per_vm

    if field_path == "vms.default_cores":
        threads = _get_manifest_val(m, "cpu.total_threads") or 4
        return max(threads // 4, 1)

    if field_path == "vms.default_disk_gb":
        return 32

    # ── Identity ─────────────────────────────────────────────────────────────

    if field_path == "host_identity.hostname":
        return _get_manifest_val(m, "host.hostname") or "pve01"

    if field_path == "host_identity.domain":
        return _get_manifest_val(m, "host_identity.domain") or "home.example.com"

    if field_path == "host_identity.fqdn":
        hostname = chosen_hostname or suggest("host_identity.hostname", session)
        domain   = chosen_domain   or suggest("host_identity.domain", session)
        return f"{hostname}.{domain}"

    if field_path == "host_identity.cell_id":
        hostname = chosen_hostname or suggest("host_identity.hostname", session)
        return _get_manifest_val(m, "cell_id") or f"{hostname}-cell"

    # ── Security ─────────────────────────────────────────────────────────────

    if field_path == "security.kdbx_path":
        return "/opt/broodforge/cluster.kdbx"

    if field_path == "security.password_format":
        return "passphrase"   # Capital.word.phrase.N

    if field_path == "security.ssh_key_path":
        return "~/.ssh/id_rsa"

    # ── k3s ──────────────────────────────────────────────────────────────────

    if field_path == "k3s.pod_cidr":
        cidr = chosen_cidr or suggest("network.management_cidr", session)
        # Avoid overlap: if management is 10.42.x, shift pod CIDR
        try:
            mgmt_net = ipaddress.ip_network(cidr, strict=False)
            k3s_default = ipaddress.ip_network("10.42.0.0/16")
            if mgmt_net.overlaps(k3s_default):
                return "172.20.0.0/16"
        except ValueError:
            pass
        return "10.42.0.0/16"

    if field_path == "k3s.service_cidr":
        pod = suggest("k3s.pod_cidr", session)
        # Service CIDR should be adjacent but not overlapping
        if pod.startswith("10.42"):
            return "10.43.0.0/16"
        if pod.startswith("172.20"):
            return "172.21.0.0/16"
        return "10.43.0.0/16"

    if field_path == "k3s.cni":
        return "flannel"

    if field_path == "k3s.initial_role":
        return "server"

    # ── Backup ───────────────────────────────────────────────────────────────

    if field_path == "backup.retention_count":
        return 5

    if field_path == "backup.ddns_provider":
        return None   # operator must configure

    if field_path == "backup.config_destinations":
        return ["(not configured — run setup-backup.py)"]

    # Unknown field
    return None


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------

def check_conflicts(field_path: str, value: Any, session: GuidedSetupSession) -> list[str]:
    """
    Check a proposed value for conflicts with current session state.
    Returns a list of warning strings (empty = no conflicts).
    """
    warnings = []

    if field_path == "network.management_cidr":
        try:
            proposed = ipaddress.ip_network(value, strict=False)
        except ValueError:
            return [f"'{value}' is not a valid CIDR notation (e.g. 192.168.1.0/24)"]

        # Check k3s CIDR overlap
        pod_cidr = session.get_value("k3s.pod_cidr")
        svc_cidr = session.get_value("k3s.service_cidr")
        for name, cidr in (("k3s.pod_cidr", pod_cidr), ("k3s.service_cidr", svc_cidr)):
            if cidr:
                try:
                    other = ipaddress.ip_network(cidr, strict=False)
                    if proposed.overlaps(other):
                        warnings.append(
                            f"Management CIDR {value} overlaps with {name} ({cidr})"
                        )
                except ValueError:
                    pass

    elif field_path == "network.gateway":
        cidr = session.get_value("network.management_cidr")
        if cidr:
            try:
                net = ipaddress.ip_network(cidr, strict=False)
                gw  = ipaddress.ip_address(value)
                if gw not in net:
                    warnings.append(
                        f"Gateway {value} is not within management CIDR {cidr}"
                    )
            except ValueError:
                pass

    elif field_path == "vms.vmid_start":
        try:
            start = int(value)
        except (TypeError, ValueError):
            return [f"VMID must be an integer, got {value!r}"]
        if start < 100:
            warnings.append(f"VMIDs below 100 are reserved by Proxmox (suggested ≥ 100)")
        if start >= 9000:
            warnings.append(f"VMIDs 9000+ are reserved for templates")
        # Check against existing declared VMs
        vms = session.manifest.get("vms") or []
        existing_ids = {int(v["vmid"]) for v in vms if v.get("vmid")}
        if start in existing_ids:
            warnings.append(f"VMID {start} is already allocated to an existing VM")

    elif field_path == "host_identity.hostname":
        if not re.match(r"^[a-z][a-z0-9-]{0,61}[a-z0-9]$", str(value)):
            warnings.append(
                f"Hostname '{value}' should be lowercase letters, digits, hyphens; "
                f"start with a letter; max 63 chars"
            )

    elif field_path == "host_identity.domain":
        if not re.match(r"^[a-z0-9][a-z0-9.-]+\.[a-z]{2,}$", str(value)):
            warnings.append(
                f"Domain '{value}' should look like 'home.example.com'"
            )

    elif field_path == "k3s.pod_cidr":
        try:
            proposed = ipaddress.ip_network(value, strict=False)
        except ValueError:
            return [f"'{value}' is not a valid CIDR (e.g. 10.42.0.0/16)"]
        mgmt_cidr = session.get_value("network.management_cidr")
        if mgmt_cidr:
            try:
                mgmt = ipaddress.ip_network(mgmt_cidr, strict=False)
                if proposed.overlaps(mgmt):
                    warnings.append(
                        f"k3s pod CIDR {value} overlaps with management network {mgmt_cidr}"
                    )
            except ValueError:
                pass

    elif field_path == "vms.default_ram_gb":
        try:
            ram = float(value)
        except (TypeError, ValueError):
            return [f"RAM must be a number (GB), got {value!r}"]
        host_ram = session.manifest.get("memory", {}).get("total_gb")
        if host_ram and ram > host_ram * 0.9:
            warnings.append(
                f"Allocating {ram} GB RAM per VM may exhaust host RAM "
                f"({host_ram} GB total)"
            )

    return warnings


# ---------------------------------------------------------------------------
# Value setter — records choice and returns conflicts
# ---------------------------------------------------------------------------

def set_value(
    field_path: str,
    value: Any,
    session: GuidedSetupSession,
    source: str = "manual",
) -> list[str]:
    """
    Record a value in the session. Returns list of conflict warning strings.
    Warnings are also appended to session.warnings.

    source: 'manual' (operator choice) | 'auto' (programmatically set)
    """
    conflicts = check_conflicts(field_path, value, session)
    session.warnings.extend(conflicts)
    session.choices[field_path] = Choice(
        field_path=field_path,
        value=value,
        source=source,
    )
    return conflicts


# ---------------------------------------------------------------------------
# IP-selective mode helper
# ---------------------------------------------------------------------------

def run_ip_selective_suggestions(session: GuidedSetupSession) -> dict:
    """
    Pre-populate the session with auto-suggestions for IP-selective mode.
    Returns dict of field_path → suggested_value for the IP fields that
    need operator input.
    """
    ip_fields = {
        f: suggest(f, session) for f in sorted(IP_SELECTIVE_FIELDS)
    }
    # Auto-populate all non-IP fields
    for group_fields in (g["fields"] for g in SETTING_GROUPS.values()):
        for fp in group_fields:
            if fp not in IP_SELECTIVE_FIELDS and fp not in session.choices:
                val = suggest(fp, session)
                if val is not None:
                    set_value(fp, val, session, source="auto")
    return ip_fields


# ---------------------------------------------------------------------------
# Group selector helper (returns display rows — I/O by caller)
# ---------------------------------------------------------------------------

def group_selector_rows(session: GuidedSetupSession) -> list[dict]:
    """
    Build the display rows for the group selector interface.
    Returns list of dicts:
      {group_id, label, description, representative_field, auto_suggestion, selected}
    Callers render these and update session.selected_groups.
    """
    rows = []
    for gid, gdef in SETTING_GROUPS.items():
        rep_field = gdef["representative_field"]
        auto_val  = suggest(rep_field, session)
        rows.append({
            "group_id":          gid,
            "label":             gdef["label"],
            "description":       gdef["description"],
            "representative_field": rep_field,
            "auto_suggestion":   auto_val,
            "selected":          gid in session.selected_groups,
        })
    return rows


# ---------------------------------------------------------------------------
# Session serialization — what gets embedded in spawn/forge/phoenix package
# ---------------------------------------------------------------------------

def session_to_overrides(session: GuidedSetupSession) -> dict:
    """
    Serialize only the manually-set choices to a compact overrides dict.
    This is embedded in spawn-plan.json / forge-manifest.json so the
    package knows which values were intentionally chosen vs. auto-calculated.

    Format: {field_path: {value, source}} for all manual choices.
    """
    return {
        fp: {"value": c.value, "source": c.source}
        for fp, c in session.choices.items()
        if c.source == "manual"
    }
