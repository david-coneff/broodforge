#!/usr/bin/env python3
"""
storage_state_collector.py — Storage State collector (Phase 14.4).

Collects ZFS pool health, Proxmox datastore usage, and PBS backup job status.
Produces a storage-state.json conforming to data-model/storage-state-schema.json.

Provides:
  ZfsPool, ProxmoxDatastore, PbsJob  — typed entries
  StorageStateDocument                — typed result
  collect_storage_state()             — main collection entry point
  compute_storage_health()            — aggregate health
  storage_state_to_dict()            — JSON-serialisable dict

Stdlib only.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from collector_utils import local_runner, RunnerFn  # noqa: F401


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ZfsVdev:
    name:   str
    type:   str = "stripe"
    state:  Optional[str] = None
    disks:  list[str] = field(default_factory=list)


@dataclass
class ZfsPool:
    name:          str
    state:         Optional[str]   = None   # ONLINE, DEGRADED, FAULTED, etc.
    size_gb:       Optional[float] = None
    allocated_gb:  Optional[float] = None
    free_gb:       Optional[float] = None
    capacity_pct:  Optional[int]   = None
    dedup_ratio:   Optional[float] = None
    health:        Optional[str]   = None
    scan_status:   Optional[str]   = None
    last_scrub_at: Optional[str]   = None
    vdevs:         list[ZfsVdev]   = field(default_factory=list)


@dataclass
class ProxmoxDatastore:
    id:        str
    type:      Optional[str]   = None
    content:   list[str]       = field(default_factory=list)
    enabled:   Optional[bool]  = None
    size_gb:   Optional[float] = None
    used_gb:   Optional[float] = None
    avail_gb:  Optional[float] = None
    shared:    Optional[bool]  = None
    path:      Optional[str]   = None


@dataclass
class PbsJob:
    id:             str
    store:          Optional[str]   = None
    vm_id:          Optional[int]   = None
    last_run:       Optional[str]   = None
    last_status:    Optional[str]   = None
    next_run:       Optional[str]   = None
    snapshot_count: Optional[int]   = None
    size_gb:        Optional[float] = None


@dataclass
class StorageStateDocument:
    cell_id:             str
    collected_at:        str
    zfs_pools:           list[ZfsPool]          = field(default_factory=list)
    proxmox_datastores:  list[ProxmoxDatastore] = field(default_factory=list)
    pbs_jobs:            list[PbsJob]            = field(default_factory=list)
    pbs_datastore_id:    Optional[str]           = None
    collection_errors:   list[dict]              = field(default_factory=list)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _parse_zpool_list_json(output: str) -> list[ZfsPool]:
    """Parse 'zpool list -j' (ZFS JSON output, available on OpenZFS 2.1+)."""
    pools = []
    try:
        data = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return pools

    for pool_name, pool_data in (data.get("pools") or {}).items():
        props = pool_data.get("properties") or {}

        def _prop(key: str) -> Optional[str]:
            v = (props.get(key) or {}).get("value")
            return str(v) if v is not None and str(v) != "-" else None

        state     = _prop("state")
        size_raw  = _prop("size")
        alloc_raw = _prop("allocated")
        free_raw  = _prop("free")
        cap       = _prop("capacity")
        dedup     = _prop("dedupratio")
        health    = _prop("health")

        size_gb  = _bytes_to_gb(size_raw)
        alloc_gb = _bytes_to_gb(alloc_raw)
        free_gb  = _bytes_to_gb(free_raw)
        cap_pct  = _int(cap.rstrip("%")) if cap else None
        dedup_f  = _safe_float(dedup.rstrip("x")) if dedup else None

        pools.append(ZfsPool(
            name=pool_name,
            state=state,
            size_gb=size_gb,
            allocated_gb=alloc_gb,
            free_gb=free_gb,
            capacity_pct=cap_pct,
            dedup_ratio=dedup_f,
            health=health,
        ))
    return pools


def _parse_zpool_status(output: str) -> list[ZfsPool]:
    """
    Parse 'zpool status' text output (fallback when JSON not available).
    Returns minimal pool objects with name and state.
    """
    pools = []
    current = None
    for line in output.splitlines():
        if line.startswith("  pool:"):
            if current:
                pools.append(current)
            name = line.split(":", 1)[1].strip()
            current = ZfsPool(name=name)
        elif line.startswith(" state:") and current:
            current.state = line.split(":", 1)[1].strip()
        elif line.startswith("status:") and current:
            current.health = line.split(":", 1)[1].strip()
        elif line.startswith("  scan:") and current:
            current.scan_status = line.split(":", 1)[1].strip()
    if current:
        pools.append(current)
    return pools


def _parse_pvesm_status(output: str) -> list[ProxmoxDatastore]:
    """Parse 'pvesm status' text output."""
    stores = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 2 or parts[0] == "Name":
            continue
        store_id   = parts[0]
        store_type = parts[1] if len(parts) > 1 else None
        status     = parts[2] if len(parts) > 2 else None
        total_b    = _int(parts[3]) if len(parts) > 3 else None
        used_b     = _int(parts[4]) if len(parts) > 4 else None
        avail_b    = _int(parts[5]) if len(parts) > 5 else None

        stores.append(ProxmoxDatastore(
            id=store_id,
            type=store_type,
            enabled=status == "active",
            size_gb=_bytes_to_gb_int(total_b),
            used_gb=_bytes_to_gb_int(used_b),
            avail_gb=_bytes_to_gb_int(avail_b),
        ))
    return stores


def _bytes_to_gb(val: Optional[str]) -> Optional[float]:
    """Convert a bytes string (possibly with K/M/G/T suffix) to GiB."""
    if not val:
        return None
    val = val.strip()
    try:
        if val.endswith("T"):
            return float(val[:-1]) * 1024
        if val.endswith("G"):
            return float(val[:-1])
        if val.endswith("M"):
            return float(val[:-1]) / 1024
        if val.endswith("K"):
            return float(val[:-1]) / (1024 ** 2)
        return round(int(val) / (1024 ** 3), 2)
    except (ValueError, TypeError):
        return None


def _bytes_to_gb_int(val: Optional[int]) -> Optional[float]:
    if val is None:
        return None
    try:
        return round(val / (1024 ** 3), 2)
    except (TypeError, ValueError):
        return None


def _int(v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _safe_float(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Storage health aggregation (Phase 14.5 / 14.6)
# ---------------------------------------------------------------------------

def compute_storage_health(doc: StorageStateDocument) -> dict:
    """Derive storage_health dict from StorageStateDocument."""
    issues = []

    # ZFS pool health
    pool_states = [p.state for p in doc.zfs_pools if p.state]
    if not pool_states:
        pool_summary = "UNKNOWN"
    elif any(s in ("FAULTED", "UNAVAIL", "REMOVED") for s in pool_states):
        pool_summary = "FAULTED"
        issues.append("ZFS pool(s) in FAULTED/UNAVAIL state")
    elif any(s == "DEGRADED" for s in pool_states):
        pool_summary = "DEGRADED"
        issues.append("ZFS pool(s) DEGRADED — reduced redundancy")
    else:
        pool_summary = "ALL_ONLINE"

    # High capacity pools (>80%)
    high_cap = [p.name for p in doc.zfs_pools if (p.capacity_pct or 0) > 80]
    if high_cap:
        issues.append(f"High capacity pools (>80%): {', '.join(high_cap)}")

    # PBS job failures
    pbs_failures = [j.id for j in doc.pbs_jobs if j.last_status == "error"]
    if pbs_failures:
        issues.append(f"PBS backup failures: {', '.join(pbs_failures)}")

    # Overall status
    if pool_summary in ("FAULTED",):
        overall = "CRITICAL"
    elif pool_summary == "DEGRADED" or high_cap or pbs_failures:
        overall = "DEGRADED"
    elif pool_summary == "UNKNOWN" and not doc.zfs_pools:
        overall = "UNKNOWN"
    else:
        overall = "HEALTHY"

    return {
        "overall_status":        overall,
        "pool_health_summary":   pool_summary,
        "high_capacity_pools":   high_cap,
        "pbs_job_failures":      pbs_failures,
        "issues":                issues,
    }


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------

def collect_storage_state(
    cell_id:   str,
    runner_fn: Optional[RunnerFn] = None,
    now_fn:    Optional[Callable[[], str]] = None,
) -> StorageStateDocument:
    """Collect storage state from the local Proxmox host."""
    runner = runner_fn or local_runner
    now    = (now_fn or (lambda: datetime.now(timezone.utc).isoformat()))()

    doc = StorageStateDocument(cell_id=cell_id, collected_at=now)
    errors = []

    # ZFS pools — try JSON first, fall back to text
    try:
        out = runner("zpool list -j 2>/dev/null || true")
        if out.strip() and out.strip().startswith("{"):
            doc.zfs_pools = _parse_zpool_list_json(out)
        else:
            out2 = runner("zpool status 2>/dev/null || true")
            doc.zfs_pools = _parse_zpool_status(out2)
    except Exception as e:
        errors.append({"component": "zfs_pools", "error": str(e)})

    # Proxmox datastores
    try:
        out = runner("pvesm status 2>/dev/null || true")
        if out.strip():
            doc.proxmox_datastores = _parse_pvesm_status(out)
    except Exception as e:
        errors.append({"component": "proxmox_datastores", "error": str(e)})

    doc.collection_errors = errors
    return doc


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def storage_state_to_dict(doc: StorageStateDocument) -> dict:
    """Convert StorageStateDocument to a JSON-serialisable dict."""
    health = compute_storage_health(doc)
    return {
        "schema_version": "1.0",
        "cell_id":        doc.cell_id,
        "collected_at":   doc.collected_at,
        "collection_errors": doc.collection_errors,
        "zfs_pools": [
            {
                "name":         p.name,
                "state":        p.state,
                "size_gb":      p.size_gb,
                "allocated_gb": p.allocated_gb,
                "free_gb":      p.free_gb,
                "capacity_pct": p.capacity_pct,
                "dedup_ratio":  p.dedup_ratio,
                "health":       p.health,
                "scan_status":  p.scan_status,
            }
            for p in doc.zfs_pools
        ],
        "proxmox_datastores": [
            {
                "id":       s.id,
                "type":     s.type,
                "enabled":  s.enabled,
                "size_gb":  s.size_gb,
                "used_gb":  s.used_gb,
                "avail_gb": s.avail_gb,
            }
            for s in doc.proxmox_datastores
        ],
        "pbs_jobs": [
            {
                "id":          j.id,
                "store":       j.store,
                "vm_id":       j.vm_id,
                "last_run":    j.last_run,
                "last_status": j.last_status,
            }
            for j in doc.pbs_jobs
        ],
        "pbs_datastore_id": doc.pbs_datastore_id,
        "storage_health":   health,
    }
