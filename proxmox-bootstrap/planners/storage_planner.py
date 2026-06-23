#!/usr/bin/env python3
"""
Storage planner — Phase A, Layer A.

Reads storage discovery output and hardware-profile.yaml to recommend
a ZFS pool topology for the Proxmox host.

ZFS topology decision tree:
  0 disks:   ERROR — cannot proceed
  1 disk:    stripe (single disk, no redundancy — WARN)
  2 disks:   mirror (RAID-1 equivalent)
  3-5 disks: raidz  (RAID-5 equivalent, 1 parity disk)
  6-8 disks: raidz2 (RAID-6 equivalent, 2 parity disks)
  9+ disks:  raidz3 or nested raidz2 mirror

Mixed SSD/HDD: recommend separate pools.
  Fast pool (SSD/NVMe): system, VMs, high-IOPS workloads
  Bulk pool (HDD):      backups, large capacity workloads

Usage:
    python3 planners/storage_planner.py
    python3 planners/storage_planner.py --storage discovery/storage-report.json
                                         --hardware discovery/hardware-report.json
                                         --out plans/storage-plan.json

Outputs: plans/storage-plan.json
"""

import json
import os
import re
import sys
from pathlib import Path

BOOTSTRAP_DIR = Path(__file__).parent.parent

# ZFS pool naming convention: proxmox-cell-a → pool0 (primary), pool1 (secondary)
DEFAULT_PRIMARY_POOL = "rpool"
DEFAULT_SECONDARY_POOL = "data"


def _load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Topology decision logic
# ---------------------------------------------------------------------------

def recommend_topology(disk_count: int, disk_types: list[str]) -> tuple[str, str]:
    """
    Recommend a ZFS topology given disk count and types.

    Returns (topology_name, rationale)
    topology_name: "mirror", "raidz", "raidz2", "raidz3", "stripe", "error"
    """
    if disk_count == 0:
        return "error", "No disks detected — cannot create ZFS pool"
    if disk_count == 1:
        return "stripe", (
            "Single disk — no redundancy. Data loss on disk failure. "
            "Acceptable for test/development only."
        )
    if disk_count == 2:
        return "mirror", (
            "2 disks — mirror (RAID-1). Survives one disk failure. "
            "50% usable capacity (1 disk)."
        )
    if disk_count <= 5:
        return "raidz", (
            f"{disk_count} disks — RAIDZ (RAID-5 equivalent). "
            f"Survives one disk failure. "
            f"{disk_count - 1} disks usable capacity."
        )
    if disk_count <= 8:
        return "raidz2", (
            f"{disk_count} disks — RAIDZ2 (RAID-6 equivalent). "
            f"Survives two simultaneous disk failures. "
            f"{disk_count - 2} disks usable capacity."
        )
    # 9+ disks: raidz3 or nested raidz2 mirror
    return "raidz3", (
        f"{disk_count} disks — RAIDZ3 (3 parity disks). "
        f"Survives three simultaneous failures. "
        f"{disk_count - 3} disks usable capacity. "
        f"Consider nested raidz2 mirror for better write performance."
    )


def classify_disks(disks: list[dict]) -> dict[str, list[dict]]:
    """
    Classify disks by type: nvme, ssd, hdd.
    Returns dict with keys "nvme", "ssd", "hdd", each a list of disk dicts.
    """
    groups: dict[str, list] = {"nvme": [], "ssd": [], "hdd": []}
    for disk in disks:
        dtype = (disk.get("type") or "").upper()
        iface = (disk.get("interface") or "").upper()
        if dtype == "NVME" or iface == "NVME":
            groups["nvme"].append(disk)
        elif dtype == "SSD":
            groups["ssd"].append(disk)
        else:
            groups["hdd"].append(disk)
    return groups


def estimate_usable_gb(disk_count: int, topology: str, disk_size_gb: float) -> float:
    """Estimate usable capacity in GB given topology and disk count/size."""
    if topology == "mirror":
        return disk_size_gb * (disk_count // 2)
    if topology == "raidz":
        return disk_size_gb * (disk_count - 1)
    if topology == "raidz2":
        return disk_size_gb * (disk_count - 2)
    if topology == "raidz3":
        return disk_size_gb * (disk_count - 3)
    return disk_size_gb * disk_count  # stripe


def _disk_size_gb(disk: dict) -> float:
    raw = disk.get("size_raw") or disk.get("size_bytes")
    if isinstance(raw, (int, float)):
        return raw / (1024 ** 3)
    if isinstance(raw, str):
        m = re.match(r"([\d.]+)([TGMK]?)B?$", raw.strip().upper())
        if m:
            v = float(m.group(1))
            u = m.group(2)
            return v * {"T": 1024, "G": 1, "M": 1 / 1024, "K": 1 / 1048576, "": 1}.get(u, 1)
    return 0.0


# ---------------------------------------------------------------------------
# Plan generation
# ---------------------------------------------------------------------------

def plan_storage(storage: dict, hardware: dict | None = None) -> dict:
    """
    Produce a storage plan from discovery output.

    Parameters
    ----------
    storage : dict   Output of collect_storage() — storage-report.json
    hardware : dict  Output of collect_hardware() — for disk type info (optional)

    Returns
    -------
    dict — storage-plan.json structure
    """
    warnings = []
    recommendations = []
    errors = []

    # ── Existing ZFS pools ────────────────────────────────────────────────────
    existing_pools = storage.get("zfs_pools", [])
    if existing_pools:
        recommendations.append(
            f"Found {len(existing_pools)} existing ZFS pool(s): "
            f"{', '.join(p['name'] for p in existing_pools)}. "
            f"Import during Proxmox reinstall with: zpool import <pool_name>"
        )

    # ── Disk inventory from hardware report ───────────────────────────────────
    # storage-report has pool info; hardware-report has raw disk inventory
    raw_disks = []
    if hardware:
        raw_disks = hardware.get("disks", [])
    elif storage.get("collection_errors"):
        errors.extend(storage["collection_errors"])

    disk_groups = classify_disks(raw_disks)
    fast_disks = disk_groups["nvme"] + disk_groups["ssd"]
    slow_disks = disk_groups["hdd"]

    # ── Pool topology planning ─────────────────────────────────────────────────
    pools = []

    if fast_disks and slow_disks:
        # Mixed: recommend separate pools
        recommendations.append(
            "Mixed SSD and HDD detected. Recommend two ZFS pools: "
            "fast pool (SSD/NVMe) for VMs and system, "
            "data pool (HDD) for backups and large storage."
        )
        fast_topo, fast_rationale = recommend_topology(
            len(fast_disks), [d.get("type", "") for d in fast_disks]
        )
        slow_topo, slow_rationale = recommend_topology(
            len(slow_disks), [d.get("type", "") for d in slow_disks]
        )
        fast_avg_gb = (
            sum(_disk_size_gb(d) for d in fast_disks) / len(fast_disks)
            if fast_disks else 0
        )
        slow_avg_gb = (
            sum(_disk_size_gb(d) for d in slow_disks) / len(slow_disks)
            if slow_disks else 0
        )
        pools.append({
            "name": DEFAULT_PRIMARY_POOL,
            "purpose": "primary",
            "topology": fast_topo,
            "disk_count": len(fast_disks),
            "disk_types": list({d.get("type", "unknown") for d in fast_disks}),
            "estimated_usable_gb": round(
                estimate_usable_gb(len(fast_disks), fast_topo, fast_avg_gb), 0
            ),
            "rationale": fast_rationale,
            "proxmox_content_types": ["images", "rootdir", "snippets", "iso"],
            "disks": [d.get("name") for d in fast_disks],
        })
        if slow_topo != "error":
            pools.append({
                "name": DEFAULT_SECONDARY_POOL,
                "purpose": "secondary",
                "topology": slow_topo,
                "disk_count": len(slow_disks),
                "disk_types": list({d.get("type", "unknown") for d in slow_disks}),
                "estimated_usable_gb": round(
                    estimate_usable_gb(len(slow_disks), slow_topo, slow_avg_gb), 0
                ),
                "rationale": slow_rationale,
                "proxmox_content_types": ["backup"],
                "disks": [d.get("name") for d in slow_disks],
            })
    else:
        # Homogeneous disks — single pool
        all_disks = fast_disks or slow_disks or raw_disks
        disk_count = len(all_disks)
        disk_types = list({d.get("type", "unknown") for d in all_disks})
        topo, rationale = recommend_topology(disk_count, disk_types)

        if topo == "error":
            errors.append(rationale)
        else:
            if topo == "stripe":
                warnings.append(
                    "Single disk — no redundancy. Data loss on disk failure. "
                    "Add a second disk to enable mirror before production use."
                )
            avg_gb = (
                sum(_disk_size_gb(d) for d in all_disks) / len(all_disks)
                if all_disks else 0
            )
            pools.append({
                "name": DEFAULT_PRIMARY_POOL,
                "purpose": "primary",
                "topology": topo,
                "disk_count": disk_count,
                "disk_types": disk_types,
                "estimated_usable_gb": round(
                    estimate_usable_gb(disk_count, topo, avg_gb), 0
                ),
                "rationale": rationale,
                "proxmox_content_types": ["images", "rootdir", "snippets", "iso", "backup"],
                "disks": [d.get("name") for d in all_disks],
            })

    # ── Proxmox datastores ────────────────────────────────────────────────────
    storage.get("proxmox_datastores", [])
    recommended_datastores = []
    for pool in pools:
        recommended_datastores.append({
            "name": f"{pool['name']}-zfs" if pool["purpose"] == "primary" else pool["name"],
            "type": "zfspool",
            "pool": pool["name"],
            "content_types": pool["proxmox_content_types"],
            "note": (
                f"Create in Proxmox: Datacenter -> Storage -> Add -> ZFS -> "
                f"Pool: {pool['name']}"
            ),
        })
    # Always ensure local storage exists for ISO/snippets
    recommended_datastores.append({
        "name": "local",
        "type": "dir",
        "path": "/var/lib/vz",
        "content_types": ["iso", "snippets", "vztmpl"],
        "note": "Default Proxmox local storage — required for Cloud-Init snippets",
    })

    # ── ashift recommendation ─────────────────────────────────────────────────
    all_types = {d.get("type", "").upper() for d in raw_disks}
    if "NVME" in all_types or "SSD" in all_types:
        ashift = 12
        ashift_reason = "ashift=12 recommended for SSD/NVMe (4K native sectors)"
    else:
        ashift = 12
        ashift_reason = "ashift=12 recommended for modern HDDs (4K Advanced Format)"

    recommendations.append(
        f"ZFS ashift: {ashift} — {ashift_reason}. "
        f"Set at pool creation: zpool create -o ashift={ashift} ..."
    )

    return {
        "generated_at": _now_utc(),
        "disk_inventory": {
            "total_disks": len(raw_disks),
            "nvme_count": len(disk_groups["nvme"]),
            "ssd_count": len(disk_groups["ssd"]),
            "hdd_count": len(disk_groups["hdd"]),
            "mixed": bool(fast_disks and slow_disks),
        },
        "pools": pools,
        "recommended_datastores": recommended_datastores,
        "existing_pools": [p["name"] for p in existing_pools],
        "ashift": ashift,
        "warnings": warnings,
        "errors": errors,
        "recommendations": recommendations,
    }


def _now_utc() -> str:
    from datetime import datetime, timedelta, timezone
    utc = datetime.now(timezone.utc)
    local = utc + timedelta(hours=int(os.environ.get("LOCAL_TZ_OFFSET", "0")))
    tz_name = os.environ.get("LOCAL_TZ_NAME", "UTC")
    if tz_name == "UTC":
        return utc.strftime("%Y-%m-%d %H:%M:%S UTC")
    return (f"{utc.strftime('%Y-%m-%d %H:%M:%S')} UTC "
            f"({local.strftime('%Y-%m-%d %H:%M:%S')} {tz_name})")


def main() -> None:
    args = sys.argv[1:]
    storage_path = BOOTSTRAP_DIR / "discovery" / "storage-report.json"
    hardware_path = BOOTSTRAP_DIR / "discovery" / "hardware-report.json"
    out_path = BOOTSTRAP_DIR / "plans" / "storage-plan.json"

    i = 0
    while i < len(args):
        if args[i] == "--storage" and i + 1 < len(args):
            storage_path = Path(args[i + 1]); i += 2
        elif args[i] == "--hardware" and i + 1 < len(args):
            hardware_path = Path(args[i + 1]); i += 2
        elif args[i] == "--out" and i + 1 < len(args):
            out_path = Path(args[i + 1]); i += 2
        else:
            i += 1

    if not storage_path.exists():
        print(f"Storage report not found: {storage_path}")
        print("Run: python3 discovery/discover.py --collector storage")
        sys.exit(1)

    storage = _load_json(storage_path)
    hardware = _load_json(hardware_path) if hardware_path.exists() else None
    plan = plan_storage(storage, hardware)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    print(f"Storage plan written: {out_path}")
    for pool in plan["pools"]:
        print(f"  Pool '{pool['name']}': {pool['topology']} "
              f"({pool['disk_count']} disks, ~{pool['estimated_usable_gb']:.0f}GB usable)")
    for w in plan["warnings"]:
        print(f"  WARNING: {w}")
    for e in plan["errors"]:
        print(f"  ERROR: {e}")


if __name__ == "__main__":
    main()
