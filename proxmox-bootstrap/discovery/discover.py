#!/usr/bin/env python3
"""
Bootstrap discovery engine — Phase A, Layer A.

Collects hardware, network, storage, and Proxmox environment information
from the current host. Produces structured JSON reports consumed by planners.

Usage:
    python3 discover.py                          run all collectors, write to discovery/
    python3 discover.py --out /path/to/dir       write reports to specified directory
    python3 discover.py --collector hardware      run only the hardware collector
    python3 discover.py --dry-run                print what would be collected

Design constraints:
    stdlib only — runs on a fresh Proxmox host with no pip-installed packages.
    Gracefully degrades when tools are absent (not all hosts have lshw, dmidecode).
    Every collector returns a dict with a 'collection_errors' list — partial
    results are acceptable; errors are surfaced, not silently dropped.

Output files:
    discovery/hardware-report.json
    discovery/network-report.json
    discovery/storage-report.json
    discovery/proxmox-report.json
    discovery/discovery-summary.json   aggregated summary + collection errors
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path


# ---------------------------------------------------------------------------
# Subprocess helper
# ---------------------------------------------------------------------------

def _run(cmd: list[str], timeout: int = 10) -> tuple[str, str, int]:
    """Run a command, return (stdout, stderr, returncode). Never raises."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            errors="replace",
        )
        return result.stdout, result.stderr, result.returncode
    except FileNotFoundError:
        return "", f"command not found: {cmd[0]}", 127
    except subprocess.TimeoutExpired:
        return "", f"timeout after {timeout}s", -1
    except Exception as e:
        return "", str(e), -1


def _run_json(cmd: list[str], timeout: int = 10) -> tuple[dict | list | None, str]:
    """Run a command and parse its JSON output. Returns (data, error_str)."""
    stdout, stderr, rc = _run(cmd, timeout)
    if rc != 0:
        return None, f"{' '.join(cmd)}: exit {rc}: {stderr.strip()}"
    try:
        return json.loads(stdout), ""
    except json.JSONDecodeError as e:
        return None, f"JSON parse error: {e}"


# ---------------------------------------------------------------------------
# Hardware collector
# ---------------------------------------------------------------------------

def collect_hardware() -> dict:
    """
    Collect CPU, RAM, disk, and NIC hardware inventory.

    Sources: /proc/cpuinfo, /proc/meminfo, lshw -json, lsblk -J,
             dmidecode, ip -j link, smartctl
    """
    errors = []

    # ── CPU ──────────────────────────────────────────────────────────────────
    cpu = {"model": None, "sockets": None, "cores_per_socket": None,
           "threads_per_core": None, "total_threads": None,
           "architecture": None, "virtualization": None}

    cpuinfo, _, _ = _run(["cat", "/proc/cpuinfo"])
    if cpuinfo:
        models = re.findall(r"^model name\s*:\s*(.+)$", cpuinfo, re.MULTILINE)
        if models:
            cpu["model"] = models[0].strip()
        physical_ids = set(re.findall(r"^physical id\s*:\s*(\d+)$", cpuinfo, re.MULTILINE))
        cpu["sockets"] = len(physical_ids) or 1
        cores = re.findall(r"^cpu cores\s*:\s*(\d+)$", cpuinfo, re.MULTILINE)
        cpu["cores_per_socket"] = int(cores[0]) if cores else None
        siblings = re.findall(r"^siblings\s*:\s*(\d+)$", cpuinfo, re.MULTILINE)
        total_threads = len(re.findall(r"^processor\s*:\s*\d+$", cpuinfo, re.MULTILINE))
        cpu["total_threads"] = total_threads
        if cpu["cores_per_socket"] and total_threads and cpu["sockets"]:
            cpu["threads_per_core"] = total_threads // (cpu["sockets"] * cpu["cores_per_socket"])
        flags = re.findall(r"^flags\s*:\s*(.+)$", cpuinfo, re.MULTILINE)
        if flags:
            flag_list = flags[0].split()
            if "vmx" in flag_list:
                cpu["virtualization"] = "VT-x (Intel)"
            elif "svm" in flag_list:
                cpu["virtualization"] = "AMD-V"

    arch_out, _, _ = _run(["uname", "-m"])
    cpu["architecture"] = arch_out.strip() or "unknown"

    # ── RAM ──────────────────────────────────────────────────────────────────
    memory = {"total_gb": None, "ecc": None}
    meminfo, _, _ = _run(["cat", "/proc/meminfo"])
    if meminfo:
        m = re.search(r"^MemTotal:\s+(\d+)\s+kB$", meminfo, re.MULTILINE)
        if m:
            memory["total_gb"] = round(int(m.group(1)) / 1024 / 1024, 1)

    # ECC: try dmidecode
    dmi_mem, _, dmi_rc = _run(["dmidecode", "-t", "memory"])
    if dmi_rc == 0:
        memory["ecc"] = "ECC" in dmi_mem

    # ── Storage ──────────────────────────────────────────────────────────────
    disks = []
    lsblk_data, lsblk_err = _run_json(["lsblk", "-J", "-o",
                                        "NAME,SIZE,TYPE,ROTA,TRAN,MODEL,SERIAL,MOUNTPOINTS"])
    if lsblk_data:
        for dev in lsblk_data.get("blockdevices", []):
            if dev.get("type") != "disk":
                continue
            rota = dev.get("rota")
            tran = (dev.get("tran") or "").lower()
            disk_type = "NVMe" if tran == "nvme" else ("HDD" if rota else "SSD")
            disks.append({
                "name": dev.get("name"),
                "model": (dev.get("model") or "").strip() or None,
                "serial": (dev.get("serial") or "").strip() or None,
                "size_raw": dev.get("size"),
                "type": disk_type,
                "interface": tran.upper() if tran else None,
                "rotational": rota,
            })
    else:
        errors.append(f"lsblk: {lsblk_err}")

    # ── NICs ─────────────────────────────────────────────────────────────────
    nics = []
    ip_data, ip_err = _run_json(["ip", "-j", "link"])
    if ip_data:
        for iface in ip_data:
            if iface.get("link_type") != "ether":
                continue
            if iface.get("ifname", "").startswith("vmbr"):
                continue  # skip Proxmox bridges at hardware level
            nics.append({
                "name": iface.get("ifname"),
                "mac": iface.get("address"),
                "mtu": iface.get("mtu"),
                "state": iface.get("operstate"),
            })
    else:
        errors.append(f"ip link: {ip_err}")

    return {
        "collected_at": _now_utc(),
        "cpu": cpu,
        "memory": memory,
        "disks": disks,
        "nics": nics,
        "collection_errors": errors,
    }


# ---------------------------------------------------------------------------
# Network collector
# ---------------------------------------------------------------------------

def collect_network() -> dict:
    """
    Collect network topology: interfaces, bridges, bonds, routes, DNS.

    Sources: ip -j link, ip -j addr, ip -j route, brctl show,
             /etc/network/interfaces, /etc/resolv.conf
    """
    errors = []
    bridges = []
    physical_nics = []
    routes = []
    dns_servers = []
    search_domains = []

    # ── Interfaces ────────────────────────────────────────────────────────────
    ip_link, link_err = _run_json(["ip", "-j", "link"])
    ip_addr, addr_err = _run_json(["ip", "-j", "addr"])
    if link_err:
        errors.append(f"ip link: {link_err}")
    if addr_err:
        errors.append(f"ip addr: {addr_err}")

    addr_map = {}
    if ip_addr:
        for iface in ip_addr:
            addr_map[iface["ifname"]] = [
                ai["local"] + "/" + str(ai["prefixlen"])
                for ai in iface.get("addr_info", [])
                if ai.get("family") in ("inet", "inet6")
            ]

    if ip_link:
        for iface in ip_link:
            name = iface.get("ifname", "")
            link_type = iface.get("link_type", "")
            addrs = addr_map.get(name, [])
            if name.startswith("vmbr") or "BRIDGE" in str(iface.get("flags", [])):
                bridges.append({
                    "name": name,
                    "addresses": addrs,
                    "state": iface.get("operstate"),
                    "mac": iface.get("address"),
                    "ports": [],  # populated below
                })
            elif link_type == "ether" and not name.startswith("lo"):
                physical_nics.append({
                    "name": name,
                    "mac": iface.get("address"),
                    "state": iface.get("operstate"),
                    "addresses": addrs,
                    "mtu": iface.get("mtu"),
                })

    # ── Bridge ports ─────────────────────────────────────────────────────────
    brctl_out, _, brctl_rc = _run(["brctl", "show"])
    if brctl_rc == 0:
        current_bridge = None
        for line in brctl_out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 4:
                current_bridge = parts[0]
                port = parts[3] if len(parts) > 3 else None
            elif parts and current_bridge:
                port = parts[0]
            else:
                continue
            if port and current_bridge:
                for br in bridges:
                    if br["name"] == current_bridge and port not in br["ports"]:
                        br["ports"].append(port)

    # ── Routes ───────────────────────────────────────────────────────────────
    ip_route, route_err = _run_json(["ip", "-j", "route"])
    if ip_route:
        for route in ip_route:
            routes.append({
                "dst": route.get("dst"),
                "gateway": route.get("gateway"),
                "dev": route.get("dev"),
                "type": route.get("type"),
            })
    elif route_err:
        errors.append(f"ip route: {route_err}")

    default_gateway = next(
        (r["gateway"] for r in routes if r.get("dst") == "default" and r.get("gateway")),
        None
    )

    # ── DNS ──────────────────────────────────────────────────────────────────
    resolv, _, _ = _run(["cat", "/etc/resolv.conf"])
    for line in resolv.splitlines():
        line = line.strip()
        if line.startswith("nameserver"):
            parts = line.split()
            if len(parts) >= 2:
                dns_servers.append(parts[1])
        elif line.startswith("search") or line.startswith("domain"):
            search_domains.extend(line.split()[1:])

    return {
        "collected_at": _now_utc(),
        "physical_nics": physical_nics,
        "bridges": bridges,
        "default_gateway": default_gateway,
        "routes": routes,
        "dns_servers": dns_servers,
        "search_domains": search_domains,
        "collection_errors": errors,
    }


# ---------------------------------------------------------------------------
# Storage collector
# ---------------------------------------------------------------------------

def collect_storage() -> dict:
    """
    Collect ZFS pool topology and Proxmox datastore inventory.

    Sources: zpool list -j, zpool status, pvesm status
    """
    errors = []
    zfs_pools = []
    proxmox_datastores = []

    # ── ZFS pools ────────────────────────────────────────────────────────────
    zpool_list, zpool_err = _run_json(["zpool", "list", "-j"])
    if zpool_list:
        for pool in zpool_list.get("pools", []):
            zfs_pools.append({
                "name": pool.get("name"),
                "state": pool.get("state"),
                "size_bytes": pool.get("size", {}).get("value"),
                "alloc_bytes": pool.get("alloc", {}).get("value"),
                "free_bytes": pool.get("free", {}).get("value"),
                "capacity_percent": pool.get("capacity", {}).get("value"),
                "health": pool.get("health"),
            })
    else:
        # Fall back to text parsing
        zpool_text, _, zpool_rc = _run(["zpool", "list", "-H", "-o",
                                         "name,size,alloc,free,cap,health"])
        if zpool_rc == 0:
            for line in zpool_text.splitlines():
                parts = line.split("\t")
                if len(parts) >= 6:
                    zfs_pools.append({
                        "name": parts[0],
                        "size_raw": parts[1],
                        "alloc_raw": parts[2],
                        "free_raw": parts[3],
                        "capacity_percent": parts[4],
                        "health": parts[5],
                    })
        elif zpool_rc == 127:
            errors.append("zpool not found — ZFS may not be installed")
        else:
            errors.append(f"zpool: {zpool_err}")

    # ── ZFS pool topology (vdev structure) ───────────────────────────────────
    for pool in zfs_pools:
        status_out, _, rc = _run(["zpool", "status", pool["name"]])
        if rc == 0:
            topology = _parse_zpool_topology(status_out)
            pool["topology"] = topology
        else:
            pool["topology"] = None

    # ── Proxmox datastores ───────────────────────────────────────────────────
    pvesm_out, _, pvesm_rc = _run(["pvesm", "status"])
    if pvesm_rc == 0:
        for line in pvesm_out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 5:
                proxmox_datastores.append({
                    "name": parts[0],
                    "type": parts[1],
                    "status": parts[2],
                    "total_raw": parts[3] if len(parts) > 3 else None,
                    "used_raw": parts[4] if len(parts) > 4 else None,
                    "available_raw": parts[5] if len(parts) > 5 else None,
                })
    elif pvesm_rc == 127:
        errors.append("pvesm not found — is this a Proxmox host?")
    else:
        errors.append(f"pvesm: {pvesm_rc}")

    return {
        "collected_at": _now_utc(),
        "zfs_pools": zfs_pools,
        "proxmox_datastores": proxmox_datastores,
        "collection_errors": errors,
    }


def _parse_zpool_topology(status_text: str) -> str:
    """
    Extract a simplified topology description from 'zpool status' output.
    Returns one of: mirror, raidz, raidz2, raidz3, stripe, unknown
    """
    lower = status_text.lower()
    if "mirror" in lower:
        return "mirror"
    elif "raidz3" in lower:
        return "raidz3"
    elif "raidz2" in lower:
        return "raidz2"
    elif "raidz" in lower:
        return "raidz"
    elif "stripe" in lower:
        return "stripe"
    return "unknown"


# ---------------------------------------------------------------------------
# Proxmox collector
# ---------------------------------------------------------------------------

def collect_proxmox() -> dict:
    """
    Collect Proxmox version, node info, existing VMs/CTs, and cluster status.

    Sources: pveversion, pvesh, qm list, pct list
    """
    errors = []

    # ── Proxmox version ───────────────────────────────────────────────────────
    pve_version = None
    pve_out, _, pve_rc = _run(["pveversion"])
    if pve_rc == 0:
        m = re.search(r"pve-manager/([\d.]+)", pve_out)
        pve_version = m.group(1) if m else pve_out.strip()
    else:
        errors.append("pveversion: not found — may not be a Proxmox host")

    # ── Hostname ─────────────────────────────────────────────────────────────
    hostname_out, _, _ = _run(["hostname", "-s"])
    hostname = hostname_out.strip()

    # ── VMs ──────────────────────────────────────────────────────────────────
    vms = []
    qm_out, _, qm_rc = _run(["qm", "list"])
    if qm_rc == 0:
        for line in qm_out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 3:
                vms.append({
                    "vmid": int(parts[0]),
                    "name": parts[1],
                    "status": parts[2],
                    "mem_mb": int(parts[3]) if len(parts) > 3 else None,
                    "bootdisk": parts[4] if len(parts) > 4 else None,
                    "pid": parts[5] if len(parts) > 5 else None,
                })
    elif qm_rc == 127:
        errors.append("qm not found — may not be a Proxmox host")

    # ── Containers ───────────────────────────────────────────────────────────
    containers = []
    pct_out, _, pct_rc = _run(["pct", "list"])
    if pct_rc == 0:
        for line in pct_out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 3:
                containers.append({
                    "ctid": int(parts[0]),
                    "status": parts[1],
                    "name": parts[2] if len(parts) > 2 else None,
                })

    # ── Cluster ───────────────────────────────────────────────────────────────
    cluster = {"name": None, "nodes": [], "quorum": None}
    pvecm_out, _, pvecm_rc = _run(["pvecm", "status"])
    if pvecm_rc == 0:
        for line in pvecm_out.splitlines():
            if "Name:" in line:
                cluster["name"] = line.split(":", 1)[1].strip()
            elif "Quorum" in line and ":" in line:
                cluster["quorum"] = line.split(":", 1)[1].strip()

    return {
        "collected_at": _now_utc(),
        "proxmox_version": pve_version,
        "hostname": hostname,
        "vms": vms,
        "containers": containers,
        "cluster": cluster,
        "collection_errors": errors,
    }


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _now_utc() -> str:
    utc = datetime.now(timezone.utc)
    local = utc + timedelta(hours=int(os.environ.get("LOCAL_TZ_OFFSET", "0")))
    tz_name = os.environ.get("LOCAL_TZ_NAME", "UTC")
    if tz_name == "UTC":
        return utc.strftime("%Y-%m-%d %H:%M:%S UTC")
    return (f"{utc.strftime('%Y-%m-%d %H:%M:%S')} UTC "
            f"({local.strftime('%Y-%m-%d %H:%M:%S')} {tz_name})")


COLLECTORS = {
    "hardware": collect_hardware,
    "network": collect_network,
    "storage": collect_storage,
    "proxmox": collect_proxmox,
}

OUTPUT_FILENAMES = {
    "hardware": "hardware-report.json",
    "network":  "network-report.json",
    "storage":  "storage-report.json",
    "proxmox":  "proxmox-report.json",
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]

    out_dir = Path(__file__).parent
    if "--out" in args:
        idx = args.index("--out")
        out_dir = Path(args[idx + 1])
        args = args[:idx] + args[idx + 2:]

    collector_name = None
    if "--collector" in args:
        idx = args.index("--collector")
        collector_name = args[idx + 1]
        args = args[:idx] + args[idx + 2:]

    to_run = {collector_name: COLLECTORS[collector_name]} if collector_name else COLLECTORS

    if collector_name and collector_name not in COLLECTORS:
        print(f"Unknown collector: {collector_name!r}. Choose from: {list(COLLECTORS)}")
        sys.exit(1)

    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {"run_at": _now_utc(), "reports": {}, "all_errors": []}

    for name, fn in to_run.items():
        print(f"  Collecting {name}...", end=" ", flush=True)
        data = fn()
        errs = data.get("collection_errors", [])
        filename = OUTPUT_FILENAMES[name]
        if not dry_run:
            (out_dir / filename).write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"{'[dry-run] ' if dry_run else ''}{filename} "
              f"({'OK' if not errs else f'{len(errs)} error(s)'})")
        summary["reports"][name] = {"file": filename, "errors": errs}
        summary["all_errors"].extend(errs)

    if not dry_run:
        (out_dir / "discovery-summary.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )
    print(f"\n  {'[dry-run] ' if dry_run else ''}Done. "
          f"{len(summary['all_errors'])} total collection error(s).")


if __name__ == "__main__":
    main()
