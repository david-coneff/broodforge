#!/usr/bin/env python3
"""
analyze.py — Tier 1 Bootstrap Manifest Builder

Reads raw collector outputs from OUTDIR and produces a schema-validated manifest.json.
Uses Python 3 stdlib only.

Usage:
    python3 analyze.py <collector_output_dir>
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def read(path: Path, default: str = "") -> str:
    try:
        return path.read_text(errors="replace").strip()
    except (OSError, IOError):
        return default


def read_json(path: Path) -> Optional[dict | list]:
    try:
        return json.loads(path.read_text(errors="replace"))
    except Exception:
        return None


def warn(errors: list, collector: str, message: str, field: Optional[str] = None) -> None:
    entry: dict = {"collector": collector, "message": message}
    if field:
        entry["field"] = field
    errors.append(entry)


# ---------------------------------------------------------------------------
# CPU parser
# ---------------------------------------------------------------------------

def parse_cpu(outdir: Path, collection_errors: list) -> dict:
    cpu: dict[str, Any] = {
        "model": None, "architecture": None, "sockets": None,
        "cores_per_socket": None, "threads_per_core": None,
        "total_threads": 0, "virtualization": None,
    }

    # Try lscpu JSON first
    lscpu_json = read_json(outdir / "lscpu_json.json")
    if lscpu_json and "lscpu" in lscpu_json:
        fields = {item["field"].rstrip(":"): item["data"]
                  for item in lscpu_json["lscpu"] if "field" in item and "data" in item}
        cpu["model"] = fields.get("Model name") or fields.get("Model Name")
        cpu["architecture"] = fields.get("Architecture")
        cpu["virtualization"] = fields.get("Virtualization") or fields.get("Virtualization type")
        try:
            cpu["sockets"] = int(fields.get("Socket(s)", 0) or 0)
            cpu["cores_per_socket"] = int(fields.get("Core(s) per socket", 0) or 0)
            cpu["threads_per_core"] = int(fields.get("Thread(s) per core", 0) or 0)
            cpu["total_threads"] = int(fields.get("CPU(s)", 0) or 0)
        except (ValueError, TypeError):
            pass
        return cpu

    # Fall back to text lscpu
    lscpu_text = read(outdir / "lscpu.txt")
    if lscpu_text:
        for line in lscpu_text.splitlines():
            if ":" not in line:
                continue
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            if key in ("Model name", "Model Name"):
                cpu["model"] = val
            elif key == "Architecture":
                cpu["architecture"] = val
            elif key == "Socket(s)":
                try: cpu["sockets"] = int(val)
                except ValueError: pass
            elif key == "Core(s) per socket":
                try: cpu["cores_per_socket"] = int(val)
                except ValueError: pass
            elif key == "Thread(s) per core":
                try: cpu["threads_per_core"] = int(val)
                except ValueError: pass
            elif key == "CPU(s)":
                try: cpu["total_threads"] = int(val)
                except ValueError: pass
            elif key in ("Virtualization", "Virtualization type"):
                cpu["virtualization"] = val

    # Fall back to /proc/cpuinfo
    if cpu["total_threads"] == 0:
        cpuinfo = read(outdir / "cpuinfo.txt")
        cpu["total_threads"] = cpuinfo.count("processor\t:")
        if not cpu["model"]:
            for line in cpuinfo.splitlines():
                if line.startswith("model name"):
                    cpu["model"] = line.split(":", 1)[1].strip()
                    break

    if cpu["total_threads"] == 0:
        warn(collection_errors, "cpu", "Could not determine CPU thread count", "cpu.total_threads")
        cpu["total_threads"] = 1  # schema requires integer; 1 is safe minimum

    return cpu


# ---------------------------------------------------------------------------
# Memory parser
# ---------------------------------------------------------------------------

def parse_memory(outdir: Path, collection_errors: list) -> dict:
    mem: dict[str, Any] = {"total_gb": 0.0, "available_gb": None, "swap_total_gb": None, "numa_nodes": None}

    raw = read(outdir / "memory.txt")
    for line in raw.splitlines():
        parts = line.split()
        if not parts:
            continue
        label = parts[0].lower()
        if label == "mem:" and len(parts) >= 2:
            try:
                mem["total_gb"] = round(int(parts[1]) / 1073741824, 1)
                if len(parts) >= 7:
                    mem["available_gb"] = round(int(parts[6]) / 1073741824, 1)
            except (ValueError, IndexError):
                pass
        elif label == "swap:" and len(parts) >= 2:
            try:
                mem["swap_total_gb"] = round(int(parts[1]) / 1073741824, 1)
            except (ValueError, IndexError):
                pass

    # Fall back to /proc/meminfo
    if mem["total_gb"] == 0:
        meminfo = read(outdir / "meminfo.txt")
        for line in meminfo.splitlines():
            if line.startswith("MemTotal:"):
                try:
                    kb = int(line.split()[1])
                    mem["total_gb"] = round(kb / 1048576, 1)
                except (ValueError, IndexError):
                    pass
            elif line.startswith("MemAvailable:"):
                try:
                    kb = int(line.split()[1])
                    mem["available_gb"] = round(kb / 1048576, 1)
                except (ValueError, IndexError):
                    pass
            elif line.startswith("SwapTotal:"):
                try:
                    kb = int(line.split()[1])
                    mem["swap_total_gb"] = round(kb / 1048576, 1)
                except (ValueError, IndexError):
                    pass

    if mem["total_gb"] == 0:
        warn(collection_errors, "memory", "Could not determine total RAM", "memory.total_gb")

    # NUMA nodes from lscpu
    lscpu_text = read(outdir / "lscpu.txt")
    for line in lscpu_text.splitlines():
        if line.startswith("NUMA node(s)"):
            try:
                mem["numa_nodes"] = int(line.split(":")[1].strip())
            except (ValueError, IndexError):
                pass

    return mem


# ---------------------------------------------------------------------------
# Storage parser
# ---------------------------------------------------------------------------

def _bytes_to_gb(b: Any) -> Optional[float]:
    try:
        return round(int(b) / 1073741824, 1)
    except (TypeError, ValueError):
        return None


def parse_storage(outdir: Path, collection_errors: list) -> dict:
    storage: dict[str, Any] = {"block_devices": [], "zfs_pools": [], "pve_storage": []}

    # Block devices — prefer lsblk JSON
    lsblk_data = read_json(outdir / "lsblk_json.json")
    if lsblk_data and "blockdevices" in lsblk_data:
        def flatten_devices(devices, acc):
            for dev in devices:
                if dev.get("type") in ("disk", "part", "rom", "loop", "lvm"):
                    size_gb = _bytes_to_gb(dev.get("size"))
                    if size_gb is None:
                        continue
                    acc.append({
                        "name": dev.get("name", "unknown"),
                        "type": dev.get("type", "disk"),
                        "size_gb": size_gb,
                        "rotational": bool(int(dev["rota"])) if dev.get("rota") is not None else None,
                        "model": (dev.get("model") or "").strip() or None,
                        "transport": (dev.get("tran") or "").strip() or None,
                        "wwn": (dev.get("wwn") or "").strip() or None,
                    })
                if dev.get("children"):
                    flatten_devices(dev["children"], acc)
        flatten_devices(lsblk_data["blockdevices"], storage["block_devices"])
    else:
        # Text lsblk fallback — header: NAME SIZE TYPE ROTA MODEL TRAN
        lsblk_text = read(outdir / "lsblk.txt")
        lines = lsblk_text.splitlines()
        if lines:
            for line in lines[1:]:  # skip header
                parts = line.split()
                if len(parts) < 3:
                    continue
                dev_type = parts[2] if len(parts) > 2 else "disk"
                if dev_type not in ("disk", "part", "rom", "loop", "lvm"):
                    continue
                size_gb = _bytes_to_gb(parts[1]) if len(parts) > 1 else None
                if size_gb is None:
                    continue
                storage["block_devices"].append({
                    "name": parts[0].lstrip("├─└─"),
                    "type": dev_type,
                    "size_gb": size_gb,
                    "rotational": (parts[3] == "1") if len(parts) > 3 else None,
                    "model": parts[4] if len(parts) > 4 else None,
                    "transport": parts[5] if len(parts) > 5 else None,
                    "wwn": None,
                })

    if not storage["block_devices"]:
        warn(collection_errors, "storage", "No block devices detected", "storage.block_devices")

    # ZFS pools
    zpool_list = read(outdir / "zpool_list.txt")
    if zpool_list:
        for line in zpool_list.splitlines():
            if not line.strip() or line.startswith("NAME"):
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            # columns: name size free health [altroot]
            pool: dict[str, Any] = {
                "name": parts[0],
                "state": parts[3] if len(parts) > 3 else "UNKNOWN",
                "topology": None,
                "total_gb": _bytes_to_gb(parts[1]) if len(parts) > 1 else None,
                "free_gb": _bytes_to_gb(parts[2]) if len(parts) > 2 else None,
                "devices": [],
            }
            storage["zfs_pools"].append(pool)

        # Enrich with topology and devices from zpool_status
        _enrich_zpool_topology(outdir, storage["zfs_pools"])

    # Proxmox storage
    pvesm = read(outdir / "pvesm_status.txt")
    if pvesm:
        for line in pvesm.splitlines():
            if not line.strip() or line.startswith("Name"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            # columns: Name Type Status Total Used Available %
            stor: dict[str, Any] = {
                "name": parts[0],
                "type": parts[1],
                "path": None,
                "total_gb": _bytes_to_gb(parts[3]) if len(parts) > 3 else None,
                "free_gb": _bytes_to_gb(parts[5]) if len(parts) > 5 else None,
                "content": [],
                "active": (parts[2].lower() == "active") if len(parts) > 2 else None,
            }
            storage["pve_storage"].append(stor)

    return storage


def _enrich_zpool_topology(outdir: Path, pools: list) -> None:
    """Parse zpool_status.txt to add topology and device list to each pool."""
    status_text = read(outdir / "zpool_status.txt")
    if not status_text:
        return

    pool_map = {p["name"]: p for p in pools}
    current_pool = None
    in_config = False
    topology_word = None

    for line in status_text.splitlines():
        # Pool header: "  pool: rpool"
        m = re.match(r"^\s*pool:\s+(\S+)", line)
        if m:
            current_pool = pool_map.get(m.group(1))
            in_config = False
            topology_word = None
            continue

        if current_pool is None:
            continue

        if re.match(r"^\s*config:", line):
            in_config = True
            continue

        if in_config:
            # First non-header line after config: usually pool name or topology keyword
            stripped = line.strip()
            if not stripped or stripped.startswith("NAME"):
                continue
            # Topology keywords appear as the vdev type line
            topo_m = re.match(r"^(mirror|raidz[123]?|stripe)\b", stripped)
            if topo_m:
                current_pool["topology"] = topo_m.group(1)
                continue
            # Lines starting with a device name (sdX, nvmeXnY, etc.)
            dev_match = re.match(r"^\s+(sd[a-z]+|nvme\w+|vd[a-z]+|hd[a-z]+)\s+", line)
            if dev_match:
                dev_name = dev_match.group(1)
                if dev_name not in current_pool["devices"]:
                    current_pool["devices"].append(dev_name)
            # Stop at errors/status section
            if re.match(r"^\s*(errors|status|action|see):", line):
                in_config = False


# ---------------------------------------------------------------------------
# Network parser
# ---------------------------------------------------------------------------

def parse_network(outdir: Path, collection_errors: list) -> dict:
    network: dict[str, Any] = {
        "interfaces": [], "bridges": [], "vlans": [],
        "default_gateway": None, "dns_servers": [], "dns_search": [],
    }

    # Interfaces — prefer ip addr JSON
    ip_json = read_json(outdir / "ip_addr_json.json")
    if ip_json and isinstance(ip_json, list):
        for iface in ip_json:
            name = iface.get("ifname", "")
            addrs = [
                f"{a['local']}/{a['prefixlen']}"
                for a in iface.get("addr_info", [])
                if "local" in a and "prefixlen" in a
            ]
            network["interfaces"].append({
                "name": name,
                "mac": iface.get("address"),
                "state": iface.get("operstate"),
                "addresses": addrs,
                "mtu": iface.get("mtu"),
            })
    else:
        # Text fallback — parse ip addr output
        _parse_ip_addr_text(read(outdir / "ip_addr.txt"), network["interfaces"])

    # Default gateway
    route_json = read_json(outdir / "ip_route_json.json")
    if route_json and isinstance(route_json, list):
        for route in route_json:
            if route.get("dst") == "default":
                network["default_gateway"] = route.get("gateway")
                break
    else:
        for line in read(outdir / "ip_route.txt").splitlines():
            if line.startswith("default via"):
                parts = line.split()
                if len(parts) >= 3:
                    network["default_gateway"] = parts[2]
                break

    # Bridges and VLANs from /etc/network/interfaces
    _parse_network_interfaces(
        read(outdir / "network_interfaces.txt"),
        network["interfaces"],
        network["bridges"],
        network["vlans"],
    )

    # DNS
    for line in read(outdir / "resolv_conf.txt").splitlines():
        line = line.strip()
        if line.startswith("nameserver"):
            parts = line.split()
            if len(parts) >= 2:
                network["dns_servers"].append(parts[1])
        elif line.startswith("search") or line.startswith("domain"):
            network["dns_search"].extend(line.split()[1:])

    return network


def _parse_ip_addr_text(text: str, interfaces: list) -> None:
    current: Optional[dict] = None
    for line in text.splitlines():
        m = re.match(r"^\d+:\s+(\S+):.*", line)
        if m:
            current = {
                "name": m.group(1).rstrip(":@"),
                "mac": None, "state": None, "addresses": [], "mtu": None,
            }
            interfaces.append(current)
            mtu_m = re.search(r"mtu (\d+)", line)
            if mtu_m:
                current["mtu"] = int(mtu_m.group(1))
            state_m = re.search(r"state (\w+)", line)
            if state_m:
                current["state"] = state_m.group(1)
            continue
        if current is None:
            continue
        line = line.strip()
        if line.startswith("link/ether"):
            parts = line.split()
            if len(parts) >= 2:
                current["mac"] = parts[1]
        elif line.startswith("inet ") or line.startswith("inet6 "):
            parts = line.split()
            if len(parts) >= 2:
                current["addresses"].append(parts[1])


def _parse_network_interfaces(text: str, interfaces: list, bridges: list, vlans: list) -> None:
    """Parse Debian-style /etc/network/interfaces for bridge and VLAN definitions."""
    iface_name = None
    current_block: dict = {}
    iface_map = {i["name"]: i for i in interfaces}

    def flush_block():
        if not iface_name or not current_block:
            return
        if current_block.get("bridge-ports") is not None or current_block.get("bridge_ports") is not None:
            # This is a bridge definition
            bridge = {
                "name": iface_name,
                "ports": (current_block.get("bridge-ports") or current_block.get("bridge_ports", "")).split(),
                "addresses": [],
                "vlan_aware": current_block.get("bridge-vlan-aware") == "yes" or current_block.get("bridge_vlan_aware") == "yes",
                "comment": None,
            }
            if "address" in current_block:
                prefix = current_block.get("netmask", "24")
                bridge["addresses"].append(f"{current_block['address']}/{prefix}")
            # Also sync to interfaces list if present
            if iface_name in iface_map and current_block.get("address"):
                prefix = current_block.get("netmask", "24")
                addr = f"{current_block['address']}/{prefix}"
                if addr not in iface_map[iface_name]["addresses"]:
                    iface_map[iface_name]["addresses"].append(addr)
            bridges.append(bridge)
        elif "vlan-raw-device" in current_block:
            vlan_id_m = re.search(r"\.(\d+)$", iface_name)
            if vlan_id_m:
                vlans.append({
                    "name": iface_name,
                    "vlan_id": int(vlan_id_m.group(1)),
                    "parent": current_block.get("vlan-raw-device"),
                })

    for line in text.splitlines():
        line_stripped = line.strip()
        if not line_stripped or line_stripped.startswith("#"):
            continue
        if line_stripped.startswith("iface ") or line_stripped.startswith("auto ") or line_stripped.startswith("allow-"):
            flush_block()
            current_block = {}
            if line_stripped.startswith("iface "):
                parts = line_stripped.split()
                iface_name = parts[1] if len(parts) > 1 else None
        else:
            parts = line_stripped.split(None, 1)
            if len(parts) == 2:
                current_block[parts[0]] = parts[1]
    flush_block()


# ---------------------------------------------------------------------------
# VM / Container parser
# ---------------------------------------------------------------------------

def parse_vms(outdir: Path, collection_errors: list) -> list:
    vms = []
    text = read(outdir / "qm_list.txt")
    for line in text.splitlines():
        # Header line
        if re.match(r"^\s*VMID", line, re.IGNORECASE):
            continue
        parts = line.split()
        if not parts:
            continue
        try:
            vmid = int(parts[0])
        except ValueError:
            continue
        vms.append({
            "vmid": vmid,
            "name": parts[1] if len(parts) > 1 else f"vm-{vmid}",
            "status": parts[2] if len(parts) > 2 else "unknown",
            "cores": None,
            "memory_mb": None,
            "disk_gb": None,
        })
    return vms


def parse_containers(outdir: Path, collection_errors: list) -> list:
    containers = []
    text = read(outdir / "pct_list.txt")
    for line in text.splitlines():
        if re.match(r"^\s*VMID|^\s*CT", line, re.IGNORECASE):
            continue
        parts = line.split()
        if not parts:
            continue
        try:
            ctid = int(parts[0])
        except ValueError:
            continue
        containers.append({
            "ctid": ctid,
            "name": parts[2] if len(parts) > 2 else f"ct-{ctid}",
            "status": parts[1] if len(parts) > 1 else "unknown",
            "cores": None,
            "memory_mb": None,
            "disk_gb": None,
        })
    return containers


# ---------------------------------------------------------------------------
# Software parser
# ---------------------------------------------------------------------------

AUTOMATION_TOOLS = ["git", "python3", "ansible", "ansible-playbook", "terraform", "tofu", "curl", "wget"]

def parse_software(outdir: Path, collection_errors: list) -> dict:
    packages = []
    dpkg_text = read(outdir / "dpkg_list.txt")
    for line in dpkg_text.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        # Only include installed packages
        status = parts[2].strip() if len(parts) > 2 else ""
        if "installed" not in status and status:
            continue
        packages.append({"name": parts[0].strip(), "version": parts[1].strip() or None})

    services = []
    svc_text = read(outdir / "systemctl_list.txt")
    for line in svc_text.splitlines():
        # Format: unit.service loaded active running Description
        parts = line.split()
        if parts and parts[0].endswith(".service"):
            services.append(parts[0])

    # Automation readiness from tool_versions.txt
    tool_text = read(outdir / "tool_versions.txt")
    found_tools = set()
    for line in tool_text.splitlines():
        for tool in AUTOMATION_TOOLS:
            if line.startswith(tool + " "):
                found_tools.add(tool)

    readiness = {
        "git": "git" in found_tools,
        "python3": "python3" in found_tools,
        "ansible": "ansible" in found_tools or "ansible-playbook" in found_tools,
        "terraform": "terraform" in found_tools,
        "curl": "curl" in found_tools,
        "wget": "wget" in found_tools,
    }

    # If tool_versions.txt is empty (e.g., non-root), try spotchecking packages
    if not found_tools:
        pkg_names = {p["name"] for p in packages}
        readiness["git"] = "git" in pkg_names
        readiness["python3"] = any(p.startswith("python3") for p in pkg_names)
        readiness["ansible"] = "ansible" in pkg_names
        readiness["curl"] = "curl" in pkg_names
        readiness["wget"] = "wget" in pkg_names

    return {
        "installed_packages": packages,
        "running_services": services,
        "automation_readiness": readiness,
    }


# ---------------------------------------------------------------------------
# Host metadata parser
# ---------------------------------------------------------------------------

def parse_host(outdir: Path, collection_errors: list) -> dict:
    hostname_raw = read(outdir / "hostname.txt")
    # hostname -f may return FQDN; split on first dot for short name
    fqdn = hostname_raw if "." in hostname_raw else None
    hostname = hostname_raw.split(".")[0] if hostname_raw else "unknown"

    # Proxmox version
    pve_version = None
    pve_text = read(outdir / "pveversion.txt")
    for line in pve_text.splitlines():
        if line.startswith("proxmox-ve:") or line.startswith("pve-manager:"):
            parts = line.split(":")
            if len(parts) >= 2:
                pve_version = parts[1].strip().split()[0]
                break
    if not pve_version and pve_text:
        # Single-line format: "pve-manager/8.2.1 ..."
        m = re.search(r"pve-manager/(\S+)", pve_text)
        if m:
            pve_version = m.group(1)
    if not pve_version:
        warn(collection_errors, "proxmox", "pveversion not available — may not be a Proxmox host", "host.proxmox_version")
        pve_version = "unknown"

    # Uptime
    uptime_seconds = None
    uptime_text = read(outdir / "uptime.txt")
    if uptime_text:
        try:
            uptime_seconds = int(float(uptime_text.split()[0]))
        except (ValueError, IndexError):
            pass

    # Kernel
    uname_text = read(outdir / "uname.txt")
    kernel_version = uname_text.split()[2] if uname_text else None

    # Timezone
    tz_text = read(outdir / "timezone.txt")
    timezone_str = tz_text.strip() or None

    return {
        "hostname": hostname,
        "fqdn": fqdn,
        "proxmox_version": pve_version,
        "uptime_seconds": uptime_seconds,
        "kernel_version": kernel_version,
        "timezone": timezone_str,
    }


# ---------------------------------------------------------------------------
# collected_at
# ---------------------------------------------------------------------------

def parse_collected_at(outdir: Path) -> str:
    ts_file = read(outdir / "collected_at.txt")
    if ts_file and re.match(r"^\d{4}-\d{2}-\d{2}T", ts_file):
        return ts_file
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Collection warnings/errors files
# ---------------------------------------------------------------------------

def parse_collection_log(path: Path, collector_name: str) -> list:
    entries = []
    text = read(path)
    for line in text.splitlines():
        line = line.strip()
        if line:
            entries.append({"collector": collector_name, "message": line, "field": None})
    return entries


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_manifest(outdir: Path) -> dict:
    collection_errors: list = []
    collection_warnings: list = []

    # Read log files produced by bootstrap.sh
    for line in read(outdir / "collection_errors.log").splitlines():
        if line.strip():
            collection_errors.append({"collector": "bootstrap", "message": line.strip(), "field": None})
    for line in read(outdir / "collection_warnings.log").splitlines():
        if line.strip():
            collection_warnings.append({"collector": "bootstrap", "message": line.strip()})

    manifest = {
        "schema_version": "1.0",
        "assessment_tier": 1,
        "collected_at": parse_collected_at(outdir),
        "host": parse_host(outdir, collection_errors),
        "cpu": parse_cpu(outdir, collection_errors),
        "memory": parse_memory(outdir, collection_errors),
        "storage": parse_storage(outdir, collection_errors),
        "network": parse_network(outdir, collection_errors),
        "vms": parse_vms(outdir, collection_errors),
        "containers": parse_containers(outdir, collection_errors),
        "software": parse_software(outdir, collection_errors),
        "collection_errors": collection_errors,
        "collection_warnings": collection_warnings,
    }

    return manifest


def main():
    if len(sys.argv) < 2:
        print(f"Usage: python3 {sys.argv[0]} <collector_output_dir>", file=sys.stderr)
        sys.exit(1)

    outdir = Path(sys.argv[1])
    if not outdir.is_dir():
        print(f"Error: {outdir} is not a directory", file=sys.stderr)
        sys.exit(1)

    manifest = build_manifest(outdir)

    out_path = outdir / "manifest.json"
    out_path.write_text(json.dumps(manifest, indent=2))
    print(f"manifest.json written: {out_path}")

    # Validate against schema if validator is available
    schema_path = Path(__file__).parent.parent.parent / "data-model" / "observed-state-schema.json"
    if schema_path.exists():
        sys.path.insert(0, str(schema_path.parent))
        try:
            from validate import validate_file
            ok, errors = validate_file(out_path, schema_path)
            if ok:
                print("Schema validation: PASS")
            else:
                print(f"Schema validation: FAIL ({len(errors)} errors)", file=sys.stderr)
                for e in errors:
                    print(f"  {e.path}: {e.message}", file=sys.stderr)
                sys.exit(1)
        except ImportError:
            pass  # Validator not available — skip silently

    return 0


if __name__ == "__main__":
    sys.exit(main())
