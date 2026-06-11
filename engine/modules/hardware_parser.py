"""
Hardware parser – maps HardwareCollector raw output to normalized schema fields.

Raw shape (from collector/hardware.py):
{
  "cpu": { model, vendor, sockets, cores_per_socket, threads_per_core,
           total_cores, total_threads, architecture, flags },
  "memory": { total_bytes, dimms:[...], ecc_enabled },
  "system": { Manufacturer, Product Name, Serial Number, UUID, SKU Number, ... },
  "baseboard": { Manufacturer, Product Name, Serial Number, Version, ... },
}

Also handles firmware data emitted by the hardware collector's dmidecode type-0 block
if the collector is extended in future; for now firmware comes from the same collector
via a separate "firmware" key that may be present.
"""

from __future__ import annotations

import subprocess
import shutil

from engine.parser import register_parser


@register_parser("hardware")
def parse_hardware(raw: dict) -> dict:
    fragment: dict = {}

    cpu_raw = raw.get("cpu") or {}
    mem_raw = raw.get("memory") or {}
    sys_raw = raw.get("system") or {}
    bb_raw = raw.get("baseboard") or {}
    fw_raw = raw.get("firmware") or {}

    # ---- hardware.cpu ----
    if cpu_raw:
        cpu: dict = {}
        _copy_if(cpu_raw, cpu, {
            "model": "model",
            "vendor": "vendor",
            "sockets": "sockets",
            "cores_per_socket": "cores_per_socket",
            "threads_per_core": "threads_per_core",
            "total_cores": "total_cores",
            "total_threads": "total_threads",
            "architecture": "architecture",
            "flags": "flags",
        })
        _set_nested(fragment, ["hardware", "cpu"], cpu)

    # ---- hardware.memory ----
    if mem_raw:
        mem: dict = {}
        _copy_if(mem_raw, mem, {
            "total_bytes": "total_bytes",
            "dimms": "dimms",
            "ecc_enabled": "ecc_enabled",
        })
        _set_nested(fragment, ["hardware", "memory"], mem)

    # ---- hardware.system ----
    if sys_raw:
        system = {
            "manufacturer": sys_raw.get("Manufacturer", ""),
            "product_name": sys_raw.get("Product Name", ""),
            "serial_number": sys_raw.get("Serial Number", ""),
            "uuid": sys_raw.get("UUID", ""),
            "sku": sys_raw.get("SKU Number", ""),
        }
        system = {k: v for k, v in system.items() if v}
        if system:
            _set_nested(fragment, ["hardware", "system"], system)

    # ---- hardware.baseboard ----
    if bb_raw:
        baseboard = {
            "manufacturer": bb_raw.get("Manufacturer", ""),
            "product_name": bb_raw.get("Product Name", ""),
            "serial_number": bb_raw.get("Serial Number", ""),
            "version": bb_raw.get("Version", ""),
        }
        baseboard = {k: v for k, v in baseboard.items() if v}
        if baseboard:
            _set_nested(fragment, ["hardware", "baseboard"], baseboard)

    # ---- firmware (BIOS) ----
    # Collector may include a "bios" sub-key from dmidecode type 0,
    # or it may be passed as the top-level "firmware" key.
    bios_raw = raw.get("bios") or fw_raw.get("bios") or {}
    if not bios_raw and sys_raw:
        # Try to parse from a separate dmidecode type-0 block if stored in sys_raw
        pass

    if bios_raw:
        bios = {
            "vendor": bios_raw.get("Vendor", ""),
            "version": bios_raw.get("Version", ""),
            "release_date": bios_raw.get("Release Date", ""),
            "revision": bios_raw.get("BIOS Revision", ""),
        }
        bios = {k: v for k, v in bios.items() if v}
        if bios:
            _set_nested(fragment, ["firmware", "bios"], bios)

    # ---- os ----
    os_raw = raw.get("os") or {}
    if os_raw:
        _set_nested(fragment, ["os"], os_raw)
    elif raw:
        # Best-effort OS facts from the runtime environment (only when input is non-empty)
        os_facts = _collect_os_facts()
        if os_facts:
            _set_nested(fragment, ["os"], os_facts)

    return fragment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _copy_if(src: dict, dst: dict, mapping: dict[str, str]) -> None:
    """Copy keys from src → dst using mapping {src_key: dst_key}, skip missing/None."""
    for src_key, dst_key in mapping.items():
        val = src.get(src_key)
        if val is not None:
            dst[dst_key] = val


def _set_nested(d: dict, path: list[str], value: dict) -> None:
    """Set d[path[0]][path[1]]... = value, creating intermediate dicts."""
    for key in path[:-1]:
        d = d.setdefault(key, {})
    d[path[-1]] = value


def _collect_os_facts() -> dict:
    """Collect basic OS facts from the live system."""
    facts: dict = {}
    try:
        import platform
        facts["name"] = _read_os_release().get("NAME", platform.system())
        facts["version"] = _read_os_release().get("VERSION", platform.version())
        facts["kernel_version"] = platform.release()
        facts["architecture"] = platform.machine()
    except Exception:
        pass
    try:
        import time
        with open("/proc/uptime") as f:
            facts["uptime_seconds"] = int(float(f.read().split()[0]))
    except Exception:
        pass
    return facts


def _read_os_release() -> dict:
    result: dict = {}
    try:
        with open("/etc/os-release") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    result[k] = v.strip('"')
    except OSError:
        pass
    return result
