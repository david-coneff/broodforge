#!/usr/bin/env python3
"""
Cluster planner — Phase A, Layer A.

Reads hardware discovery output and k3s-cluster.yaml metadata to produce
a cluster-plan.json that specifies how many k3s nodes to create and what
resources to allocate to each.

Usage:
    python3 planners/cluster_planner.py
    python3 planners/cluster_planner.py --hardware discovery/hardware-report.json
                                         --metadata metadata/k3s-cluster.yaml
                                         --out plans/cluster-plan.json

Outputs: plans/cluster-plan.json
"""

import json
import os
import re
import sys
from pathlib import Path

BOOTSTRAP_DIR = Path(__file__).parent.parent


def load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def load_yaml_minimal(path: Path) -> dict:
    """
    Minimal YAML loader sufficient for k3s-cluster.yaml.
    Handles simple key: value and nested structures.
    Does NOT handle lists, anchors, or multi-line strings.
    Use PyYAML for production; this is a stdlib fallback.
    """
    try:
        import yaml
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        pass

    # Fallback: parse key: value pairs, ignoring comments and indentation
    result = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.split("#")[0].strip()
            if ":" in line and not line.startswith("-"):
                key, _, val = line.partition(":")
                key = key.strip()
                val = val.strip()
                if val and not val.startswith("{") and not val.startswith("["):
                    # Coerce booleans and integers
                    if val.lower() == "true":
                        result[key] = True
                    elif val.lower() == "false":
                        result[key] = False
                    else:
                        try:
                            result[key] = int(val)
                        except ValueError:
                            result[key] = val.strip('"').strip("'")
    return result


# ---------------------------------------------------------------------------
# Planning logic
# ---------------------------------------------------------------------------

# System overhead reserved per VM — not available for workloads
SYSTEM_OVERHEAD_MB = 512

# Minimum resources per role
MIN_FORGEJO_RAM_MB = 1536
MIN_OPERATIONS_RAM_MB = 1536
MIN_K3S_SERVER_RAM_MB = 3072   # 2GB for control plane + 1GB workload headroom
MIN_K3S_WORKER_RAM_MB = 2048

# Minimum disk sizes
MIN_FORGEJO_DISK_GB = 40
MIN_OPERATIONS_DISK_GB = 20
MIN_K3S_SERVER_DISK_GB = 60


def plan_cluster(hardware: dict, k3s_meta: dict, current_physical_hosts: int = 1) -> dict:
    """
    Produce a cluster plan from hardware discovery and k3s metadata.

    Parameters
    ----------
    hardware : dict
        Output of collect_hardware() — hardware-report.json
    k3s_meta : dict
        Parsed k3s-cluster.yaml metadata
    current_physical_hosts : int
        Number of physical Proxmox hosts available

    Returns
    -------
    dict  — cluster-plan.json structure
    """
    warnings = []
    recommendations = []

    total_ram_mb = round((hardware.get("memory", {}).get("total_gb") or 0) * 1024)
    total_threads = hardware.get("cpu", {}).get("total_threads") or 0
    disks = hardware.get("disks", [])

    ha_threshold = int((k3s_meta.get("ha_policy") or {}).get(
        "control_plane_ha_threshold", 3
    ) if isinstance(k3s_meta.get("ha_policy"), dict) else 3)

    ha_enabled = current_physical_hosts >= ha_threshold

    if ha_enabled:
        server_count = 3
        recommendations.append(
            f"HA enabled: {current_physical_hosts} hosts >= threshold {ha_threshold}. "
            f"Recommend 3 k3s server nodes distributed across physical hosts."
        )
    else:
        server_count = 1
        recommendations.append(
            f"Single-node mode: {current_physical_hosts} host(s) < HA threshold {ha_threshold}. "
            f"Single k3s server node. Upgrade to 3-server HA when third host is added."
        )

    # ── RAM allocation ────────────────────────────────────────────────────────
    # Fixed VM allocations (required pre-k3s VMs)
    fixed_ram_mb = MIN_FORGEJO_RAM_MB + MIN_OPERATIONS_RAM_MB
    k3s_server_ram_mb = MIN_K3S_SERVER_RAM_MB

    remaining_for_k3s = total_ram_mb - fixed_ram_mb - (k3s_server_ram_mb * server_count)

    if remaining_for_k3s < 0:
        warnings.append(
            f"INSUFFICIENT RAM: {total_ram_mb}MB total; "
            f"fixed pre-k3s VMs require {fixed_ram_mb}MB + "
            f"k3s-server requires {k3s_server_ram_mb * server_count}MB. "
            f"Consider reducing VM count or adding RAM."
        )
        # Proceed with minimum viable allocation anyway
        remaining_for_k3s = 0
    elif remaining_for_k3s < 2048:
        warnings.append(
            f"LOW HEADROOM: Only {remaining_for_k3s}MB RAM available after VM allocation. "
            f"Intelligence layer workloads may experience memory pressure."
        )

    # ── vCPU allocation ───────────────────────────────────────────────────────
    # Simple: 2 vCPUs per VM minimum; k3s-server gets more
    forgejo_vcpus = max(2, total_threads // 8)
    operations_vcpus = 2
    k3s_server_vcpus = max(4, total_threads // 4)

    # ── Disk sizing ───────────────────────────────────────────────────────────
    total_disk_gb = sum(_parse_disk_size_gb(d) for d in disks)
    k3s_server_disk_gb = max(MIN_K3S_SERVER_DISK_GB, total_disk_gb // 4)

    # ── Storage class recommendation ──────────────────────────────────────────
    initial_storage_class = "local-path"
    phase11_storage_class = "longhorn"
    recommendations.append(
        "Phase 3: use local-path provisioner (k3s built-in, no additional setup). "
        "Phase 11: migrate to Longhorn for distributed storage across multiple nodes."
    )

    # ── Summary ───────────────────────────────────────────────────────────────
    plan = {
        "generated_at": _now_utc(),
        "hardware_summary": {
            "total_ram_mb": total_ram_mb,
            "total_threads": total_threads,
            "total_disk_gb": round(total_disk_gb, 1),
            "disk_count": len(disks),
        },
        "ha": {
            "enabled": ha_enabled,
            "threshold": ha_threshold,
            "current_physical_hosts": current_physical_hosts,
        },
        "server_nodes": {
            "count": server_count,
            "ram_mb_each": k3s_server_ram_mb,
            "vcpus_each": k3s_server_vcpus,
            "disk_gb_each": k3s_server_disk_gb,
            "embedded_etcd": ha_enabled,
            "also_worker": not ha_enabled,  # single-node runs workloads on server
        },
        "worker_nodes": {
            "count": 0,  # workers added in Phase 9
            "ram_mb_each": MIN_K3S_WORKER_RAM_MB,
            "note": "Add dedicated workers in Phase 9 when additional RAM or hosts available",
        },
        "pre_k3s_vms": {
            "forgejo": {
                "ram_mb": MIN_FORGEJO_RAM_MB,
                "vcpus": forgejo_vcpus,
                "disk_gb": MIN_FORGEJO_DISK_GB,
            },
            "operations": {
                "ram_mb": MIN_OPERATIONS_RAM_MB,
                "vcpus": operations_vcpus,
                "disk_gb": MIN_OPERATIONS_DISK_GB,
            },
        },
        "storage": {
            "initial_class": initial_storage_class,
            "phase11_class": phase11_storage_class,
        },
        "total_vm_ram_mb": fixed_ram_mb + (k3s_server_ram_mb * server_count),
        "available_workload_ram_mb": remaining_for_k3s,
        "warnings": warnings,
        "recommendations": recommendations,
    }

    return plan


def _parse_disk_size_gb(disk: dict) -> float:
    """Parse disk size from lsblk output (e.g. '4T', '500G', '256M')."""
    raw = disk.get("size_raw") or disk.get("size_bytes")
    if isinstance(raw, (int, float)):
        return raw / (1024 ** 3)
    if isinstance(raw, str):
        raw = raw.strip().upper()
        m = re.match(r"([\d.]+)([TGMK]?)B?$", raw)
        if m:
            value = float(m.group(1))
            unit = m.group(2)
            multipliers = {"T": 1024, "G": 1, "M": 1/1024, "K": 1/1048576, "": 1}
            return value * multipliers.get(unit, 1)
    return 0.0


def _now_utc() -> str:
    from datetime import datetime, timedelta, timezone
    utc = datetime.now(timezone.utc)
    local = utc + timedelta(hours=int(os.environ.get("LOCAL_TZ_OFFSET", "0")))
    tz_name = os.environ.get("LOCAL_TZ_NAME", "UTC")
    if tz_name == "UTC":
        return utc.strftime("%Y-%m-%d %H:%M:%S UTC")
    return (f"{utc.strftime('%Y-%m-%d %H:%M:%S')} UTC "
            f"({local.strftime('%Y-%m-%d %H:%M:%S')} {tz_name})")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    args = sys.argv[1:]

    hw_path = BOOTSTRAP_DIR / "discovery" / "hardware-report.json"
    meta_path = BOOTSTRAP_DIR / "metadata" / "k3s-cluster.yaml"
    out_path = BOOTSTRAP_DIR / "plans" / "cluster-plan.json"
    physical_hosts = 1

    i = 0
    while i < len(args):
        if args[i] == "--hardware" and i + 1 < len(args):
            hw_path = Path(args[i + 1]); i += 2
        elif args[i] == "--metadata" and i + 1 < len(args):
            meta_path = Path(args[i + 1]); i += 2
        elif args[i] == "--out" and i + 1 < len(args):
            out_path = Path(args[i + 1]); i += 2
        elif args[i] == "--hosts" and i + 1 < len(args):
            physical_hosts = int(args[i + 1]); i += 2
        else:
            i += 1

    if not hw_path.exists():
        print(f"Hardware report not found: {hw_path}")
        print("Run: python3 discovery/discover.py --collector hardware")
        sys.exit(1)

    hardware = load_json(hw_path)
    k3s_meta = load_yaml_minimal(meta_path) if meta_path.exists() else {}

    plan = plan_cluster(hardware, k3s_meta, physical_hosts)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")

    print(f"Cluster plan written: {out_path}")
    print(f"  k3s server nodes: {plan['server_nodes']['count']}")
    print(f"  HA enabled: {plan['ha']['enabled']}")
    print(f"  Available workload RAM: {plan['available_workload_ram_mb']}MB")
    for w in plan["warnings"]:
        print(f"  WARNING: {w}")


if __name__ == "__main__":
    main()
