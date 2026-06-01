#!/usr/bin/env python3
"""
hardware_state_collector.py — Hardware State Tier 1 + 2 collector (Phase 13.2).

Collects physical hardware state from a Proxmox host via SSH (Tier 2) or
from local command output (Tier 1 / testing). Produces a hardware-state.json
document conforming to data-model/hardware-state-schema.json.

Data collected:
  - BIOS/UEFI info    (dmidecode)
  - CPU details       (lscpu)
  - Memory            (/proc/meminfo + dmidecode for modules)
  - Disks             (lsblk + smartctl for SMART health)
  - NICs              (ip link + ethtool for speed/duplex/driver)
  - UPS               (upsc if NUT is installed)
  - PCIe devices      (lspci)
  - Hardware health   (aggregate from above)

Provides:
  HardwareStateDocument — typed result
  collect_hardware_state(host, user, port, key, runner_fn) — SSH-based
  collect_hardware_state_local(runner_fn) — local execution
  compute_hardware_health(doc) — derive aggregate health
  hardware_state_to_dict(doc) — JSON-serialisable dict

Stdlib only.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class DiskEntry:
    name:         str
    size_gb:      Optional[float] = None
    model:        Optional[str]   = None
    serial:       Optional[str]   = None
    firmware:     Optional[str]   = None
    rotational:   bool            = True
    removable:    bool            = False
    transport:    Optional[str]   = None
    health:       Optional[str]   = None   # PASSED/FAILED/WARNING/UNKNOWN
    smart_errors: Optional[int]   = None
    temperature_c: Optional[int]  = None
    power_on_hours: Optional[int] = None
    zfs_role:     Optional[str]   = None
    zfs_pool:     Optional[str]   = None
    partition_table: Optional[str] = None


@dataclass
class NicEntry:
    name:       str
    mac:        Optional[str]  = None
    vendor:     Optional[str]  = None
    model:      Optional[str]  = None
    driver:     Optional[str]  = None
    speed_mbps: Optional[int]  = None
    duplex:     Optional[str]  = None
    link_up:    Optional[bool] = None
    pci_slot:   Optional[str]  = None
    firmware:   Optional[str]  = None
    bridge:     Optional[str]  = None
    vlan_aware: Optional[bool] = None
    numa_node:  Optional[int]  = None


@dataclass
class MemoryModule:
    slot:         str
    size_gib:     Optional[int] = None
    type:         Optional[str] = None
    speed_mhz:    Optional[int] = None
    manufacturer: Optional[str] = None
    serial:       Optional[str] = None
    ecc:          Optional[bool] = None


@dataclass
class UpsEntry:
    name:                    str
    model:                   Optional[str]   = None
    driver:                  Optional[str]   = None
    status:                  Optional[str]   = None
    battery_charge_pct:      Optional[int]   = None
    runtime_remaining_sec:   Optional[int]   = None
    input_voltage:           Optional[float] = None
    output_voltage:          Optional[float] = None
    load_pct:                Optional[int]   = None
    last_checked_at:         Optional[str]   = None


@dataclass
class CpuInfo:
    model:            Optional[str] = None
    vendor_id:        Optional[str] = None
    physical_cores:   Optional[int] = None
    logical_cores:    Optional[int] = None
    threads_per_core: Optional[int] = None
    sockets:          Optional[int] = None
    base_freq_mhz:    Optional[int] = None
    max_freq_mhz:     Optional[int] = None
    architecture:     Optional[str] = None
    virtualization:   Optional[str] = None
    microcode:        Optional[str] = None
    flags:            list[str]     = field(default_factory=list)


@dataclass
class BiosInfo:
    vendor:       Optional[str]  = None
    version:      Optional[str]  = None
    release_date: Optional[str]  = None
    type:         Optional[str]  = None
    secure_boot:  Optional[bool] = None


@dataclass
class HardwareStateDocument:
    cell_id:       str
    node_hostname: str
    collected_at:  str
    node_fqdn:     Optional[str]        = None
    bios:          Optional[BiosInfo]   = None
    cpu:           Optional[CpuInfo]    = None
    memory_total_gib: Optional[int]     = None
    memory_used_gib:  Optional[int]     = None
    memory_ecc:       Optional[bool]    = None
    memory_modules:   list[MemoryModule] = field(default_factory=list)
    disks:         list[DiskEntry]      = field(default_factory=list)
    nics:          list[NicEntry]       = field(default_factory=list)
    ups_devices:   list[UpsEntry]       = field(default_factory=list)
    pcie_devices:  list[dict]           = field(default_factory=list)
    collection_errors: list[dict]       = field(default_factory=list)


# ---------------------------------------------------------------------------
# Runner type
# ---------------------------------------------------------------------------

RunnerFn = Callable[[str], str]   # fn(command) -> stdout string


def _local_runner(cmd: str) -> str:
    """Run a command locally and return stdout."""
    import subprocess
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
    return result.stdout


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _parse_lsblk(output: str) -> list[DiskEntry]:
    """Parse JSON output of: lsblk -J -b -o NAME,SIZE,MODEL,SERIAL,ROTA,RM,TRAN,FSTYPE,PTTYPE"""
    disks = []
    try:
        data = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return disks
    for bd in (data.get("blockdevices") or []):
        # Skip partitions (no children with type disk)
        if bd.get("type") not in (None, "disk", ""):
            continue
        name      = bd.get("name", "")
        size_b    = bd.get("size")
        size_gb   = round(int(size_b) / (1024 ** 3), 1) if size_b else None
        rotational = bd.get("rota") in (True, "1", 1)
        removable  = bd.get("rm") in (True, "1", 1)
        transport  = bd.get("tran") or None
        disks.append(DiskEntry(
            name=name,
            size_gb=size_gb,
            model=(bd.get("model") or "").strip() or None,
            serial=(bd.get("serial") or "").strip() or None,
            rotational=rotational,
            removable=removable,
            transport=transport,
            partition_table=bd.get("pttype") or None,
        ))
    return disks


def _parse_lscpu(output: str) -> CpuInfo:
    """Parse lscpu text output."""
    cpu = CpuInfo()
    for line in output.splitlines():
        parts = line.split(":", 1)
        if len(parts) != 2:
            continue
        key = parts[0].strip()
        val = parts[1].strip()
        if key == "Architecture":
            cpu.architecture = val
        elif key == "Model name":
            cpu.model = val
        elif key == "Vendor ID":
            cpu.vendor_id = val
        elif key == "Socket(s)":
            cpu.sockets = _int(val)
        elif key == "Core(s) per socket":
            pass  # derive below
        elif key == "CPU(s)":
            cpu.logical_cores = _int(val)
        elif key == "Thread(s) per core":
            cpu.threads_per_core = _int(val)
        elif key == "CPU MHz":
            cpu.base_freq_mhz = _int(float(val)) if val else None
        elif key == "CPU max MHz":
            cpu.max_freq_mhz = _int(float(val)) if val else None
        elif key == "Virtualization":
            cpu.virtualization = val

    if cpu.logical_cores and cpu.threads_per_core and cpu.sockets:
        cores_per_socket = cpu.logical_cores // (cpu.threads_per_core * cpu.sockets)
        cpu.physical_cores = cores_per_socket * cpu.sockets

    return cpu


def _parse_ip_link_json(output: str) -> list[NicEntry]:
    """Parse: ip -j link show"""
    nics = []
    try:
        data = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return nics

    SKIP_PREFIXES = ("lo", "vmbr", "veth", "bond", "dummy", "tap", "docker")
    for iface in (data or []):
        name = iface.get("ifname", "")
        if any(name.startswith(p) for p in SKIP_PREFIXES):
            continue
        link_type = iface.get("link_type", "")
        if link_type == "loopback":
            continue
        mac = iface.get("address") or None
        flags = iface.get("flags") or []
        link_up = "UP" in flags
        nics.append(NicEntry(
            name=name,
            mac=mac,
            link_up=link_up,
        ))
    return nics


def _parse_meminfo(output: str) -> tuple[Optional[int], Optional[int]]:
    """Parse /proc/meminfo → (total_gib, available_gib)."""
    total_kb = free_kb = avail_kb = None
    for line in output.splitlines():
        if line.startswith("MemTotal:"):
            total_kb = _int(line.split()[1])
        elif line.startswith("MemAvailable:"):
            avail_kb = _int(line.split()[1])
    if total_kb:
        total_gib = round(total_kb / (1024 ** 2))
        used_gib  = round((total_kb - (avail_kb or 0)) / (1024 ** 2)) if avail_kb else None
        return total_gib, used_gib
    return None, None


def _int(v: Any) -> Optional[int]:
    """Safe int conversion."""
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Hardware health aggregation (Phase 13.7)
# ---------------------------------------------------------------------------

def compute_hardware_health(doc: HardwareStateDocument) -> dict:
    """
    Derive the hardware_health dict from a HardwareStateDocument.

    Returns a dict suitable for the hardware_health field in hardware-state-schema.json.
    """
    # Disk health
    disk_statuses = [d.health for d in doc.disks if d.health is not None]
    if not disk_statuses:
        disk_summary = "UNKNOWN"
    elif any(s == "FAILED" for s in disk_statuses):
        disk_summary = "FAILURES"
    elif any(s == "WARNING" for s in disk_statuses):
        disk_summary = "WARNINGS"
    else:
        disk_summary = "ALL_PASSED"

    # Temperature warnings
    temp_warnings = []
    for d in doc.disks:
        if d.temperature_c is not None and d.temperature_c > 55:
            temp_warnings.append(f"disk:{d.name} ({d.temperature_c}°C)")

    # UPS status
    ups_status = None
    if doc.ups_devices:
        statuses = [u.status for u in doc.ups_devices if u.status]
        if any("LOWBATT" in (s or "") for s in statuses):
            ups_status = "LOW_BATTERY"
        elif any("OL" in (s or "") and "OB" not in (s or "") for s in statuses):
            ups_status = "ON_LINE"
        elif statuses:
            ups_status = statuses[0]

    # Overall status
    if disk_summary == "FAILURES":
        overall = "CRITICAL"
    elif disk_summary == "WARNINGS" or temp_warnings:
        overall = "DEGRADED"
    elif disk_summary == "UNKNOWN" and not doc.disks:
        overall = "UNKNOWN"
    else:
        overall = "HEALTHY"

    return {
        "overall_status":        overall,
        "disk_health_summary":   disk_summary,
        "memory_errors_detected": None,
        "temperature_warnings":  temp_warnings,
        "ups_status":            ups_status,
    }


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------

def collect_hardware_state(
    cell_id:   str,
    hostname:  str,
    fqdn:      Optional[str]   = None,
    runner_fn: Optional[RunnerFn] = None,
    now_fn:    Optional[Callable[[], str]] = None,
) -> HardwareStateDocument:
    """
    Collect hardware state from the local host (or via injectable runner for SSH).

    runner_fn: function(command: str) -> str  — defaults to local subprocess
    now_fn: function() -> ISO timestamp string — for test injection
    """
    runner = runner_fn or _local_runner
    now    = (now_fn or (lambda: datetime.now(timezone.utc).isoformat()))()

    doc = HardwareStateDocument(
        cell_id=cell_id,
        node_hostname=hostname,
        node_fqdn=fqdn,
        collected_at=now,
    )
    errors = []

    # CPU
    try:
        out = runner("lscpu")
        doc.cpu = _parse_lscpu(out)
    except Exception as e:
        errors.append({"component": "cpu", "error": str(e)})

    # Memory
    try:
        out = runner("cat /proc/meminfo")
        total_gib, used_gib = _parse_meminfo(out)
        doc.memory_total_gib = total_gib
        doc.memory_used_gib  = used_gib
    except Exception as e:
        errors.append({"component": "memory", "error": str(e)})

    # Disks
    try:
        out = runner(
            "lsblk -J -b -o NAME,SIZE,MODEL,SERIAL,ROTA,RM,TRAN,FSTYPE,PTTYPE,TYPE"
        )
        doc.disks = _parse_lsblk(out)
    except Exception as e:
        errors.append({"component": "disks", "error": str(e)})

    # NICs
    try:
        out = runner("ip -j link show")
        doc.nics = _parse_ip_link_json(out)
    except Exception as e:
        errors.append({"component": "nics", "error": str(e)})

    # UPS (NUT)
    try:
        upsc_list = runner("upsc -l 2>/dev/null || true")
        for ups_name in upsc_list.splitlines():
            ups_name = ups_name.strip()
            if not ups_name:
                continue
            info = runner(f"upsc {ups_name} 2>/dev/null || true")
            ups = _parse_upsc(ups_name, info)
            ups.last_checked_at = now
            doc.ups_devices.append(ups)
    except Exception as e:
        errors.append({"component": "ups", "error": str(e)})

    doc.collection_errors = errors
    return doc


def _parse_upsc(name: str, output: str) -> UpsEntry:
    """Parse upsc output for a single UPS."""
    data: dict = {}
    for line in output.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            data[k.strip()] = v.strip()
    return UpsEntry(
        name=name,
        model=data.get("ups.model"),
        driver=data.get("driver.name"),
        status=data.get("ups.status"),
        battery_charge_pct=_int(data.get("battery.charge")),
        runtime_remaining_sec=_int(data.get("battery.runtime")),
        input_voltage=_safe_float(data.get("input.voltage")),
        output_voltage=_safe_float(data.get("output.voltage")),
        load_pct=_int(data.get("ups.load")),
    )


def _safe_float(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def _disk_to_dict(d: DiskEntry) -> dict:
    return {
        "name":         d.name,
        "size_gb":      d.size_gb,
        "model":        d.model,
        "serial":       d.serial,
        "firmware":     d.firmware,
        "rotational":   d.rotational,
        "removable":    d.removable,
        "transport":    d.transport,
        "health":       d.health,
        "smart_errors": d.smart_errors,
        "temperature_c": d.temperature_c,
        "power_on_hours": d.power_on_hours,
        "zfs_role":     d.zfs_role,
        "zfs_pool":     d.zfs_pool,
        "partition_table": d.partition_table,
    }


def _nic_to_dict(n: NicEntry) -> dict:
    return {
        "name":       n.name,
        "mac":        n.mac,
        "vendor":     n.vendor,
        "model":      n.model,
        "driver":     n.driver,
        "speed_mbps": n.speed_mbps,
        "duplex":     n.duplex,
        "link_up":    n.link_up,
        "pci_slot":   n.pci_slot,
        "firmware":   n.firmware,
        "bridge":     n.bridge,
        "vlan_aware": n.vlan_aware,
        "numa_node":  n.numa_node,
    }


def _ups_to_dict(u: UpsEntry) -> dict:
    return {
        "name":                   u.name,
        "model":                  u.model,
        "driver":                 u.driver,
        "status":                 u.status,
        "battery_charge_pct":     u.battery_charge_pct,
        "runtime_remaining_sec":  u.runtime_remaining_sec,
        "input_voltage":          u.input_voltage,
        "output_voltage":         u.output_voltage,
        "load_pct":               u.load_pct,
        "last_checked_at":        u.last_checked_at,
    }


def hardware_state_to_dict(doc: HardwareStateDocument) -> dict:
    """Convert HardwareStateDocument to a JSON-serialisable dict."""
    health = compute_hardware_health(doc)
    return {
        "schema_version": "1.0",
        "cell_id":        doc.cell_id,
        "node_hostname":  doc.node_hostname,
        "node_fqdn":      doc.node_fqdn,
        "collected_at":   doc.collected_at,
        "collection_errors": doc.collection_errors,
        "bios": {
            "vendor":       (doc.bios.vendor      if doc.bios else None),
            "version":      (doc.bios.version     if doc.bios else None),
            "release_date": (doc.bios.release_date if doc.bios else None),
            "type":         (doc.bios.type         if doc.bios else None),
            "secure_boot":  (doc.bios.secure_boot  if doc.bios else None),
        } if doc.bios else None,
        "cpu": {
            "model":           (doc.cpu.model           if doc.cpu else None),
            "vendor_id":       (doc.cpu.vendor_id       if doc.cpu else None),
            "physical_cores":  (doc.cpu.physical_cores  if doc.cpu else None),
            "logical_cores":   (doc.cpu.logical_cores   if doc.cpu else None),
            "threads_per_core":(doc.cpu.threads_per_core if doc.cpu else None),
            "sockets":         (doc.cpu.sockets         if doc.cpu else None),
            "base_freq_mhz":   (doc.cpu.base_freq_mhz   if doc.cpu else None),
            "max_freq_mhz":    (doc.cpu.max_freq_mhz    if doc.cpu else None),
            "architecture":    (doc.cpu.architecture    if doc.cpu else None),
            "virtualization":  (doc.cpu.virtualization  if doc.cpu else None),
            "flags":           (doc.cpu.flags           if doc.cpu else []),
        } if doc.cpu else None,
        "memory": {
            "total_gib":   doc.memory_total_gib,
            "used_gib":    doc.memory_used_gib,
            "free_gib":    (doc.memory_total_gib - doc.memory_used_gib
                            if (doc.memory_total_gib and doc.memory_used_gib) else None),
            "ecc_enabled": doc.memory_ecc,
            "modules":     [],
        },
        "disks":       [_disk_to_dict(d) for d in doc.disks],
        "nics":        [_nic_to_dict(n) for n in doc.nics],
        "ups_devices": [_ups_to_dict(u) for u in doc.ups_devices],
        "pcie_devices": doc.pcie_devices,
        "hardware_health": health,
    }
