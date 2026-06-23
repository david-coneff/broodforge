#!/usr/bin/env python3
"""
capacity_collector.py — Capacity tracking for Tier 2 assessment (Phase 11).

Provides:
  collect_capacity_snapshot(manifest)   — extract utilization from manifest data
  compute_trend(snapshots)              — derive trend direction + projection from history
  merge_capacity_model(state, manifest, snapshots) — update bootstrap-state.json

Stdlib only. No SSH required — reads from manifest data already collected
by collect_tier2.py (cpu, memory, storage, vms sections).
"""

from datetime import datetime, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# Default thresholds
# ---------------------------------------------------------------------------

DEFAULT_THRESHOLDS = {
    "cpu_warn_pct":              75,
    "cpu_crit_pct":              90,
    "ram_warn_pct":              75,
    "ram_crit_pct":              90,
    "storage_warn_pct":          80,
    "storage_crit_pct":          90,
    "restoration_headroom_pct":  10,
}


# ---------------------------------------------------------------------------
# Snapshot collector (from manifest)
# ---------------------------------------------------------------------------

def collect_capacity_snapshot(manifest: dict, now: Optional[datetime] = None) -> dict:
    """
    Extract a capacity utilization snapshot from a Tier 1/2 manifest.

    Returns a dict matching the capacity_model.observed schema:
      observed_at, cpu_usage_pct, ram_total_gb, ram_used_gb, ram_usage_pct,
      storage_total_gb, storage_used_gb, storage_usage_pct, vm_ram_total_gb
    """
    if now is None:
        now = datetime.now(timezone.utc)

    def _get(path: str, default=None):
        parts = path.split(".")
        obj = manifest
        for p in parts:
            if not isinstance(obj, dict):
                return default
            obj = obj.get(p, default)
        return obj

    # RAM
    ram_total = _get("memory.total_gb")
    ram_avail = _get("memory.available_gb")
    ram_used  = None
    ram_pct   = None
    if ram_total is not None and ram_avail is not None:
        ram_used = round(ram_total - ram_avail, 2)
        ram_pct  = round(ram_used / ram_total * 100, 1) if ram_total > 0 else None

    # Storage — sum across ZFS pools
    pools = _get("storage.zfs_pools") or []
    storage_total = None
    storage_used  = None
    storage_pct   = None
    if pools:
        total = sum(p.get("size_gb", 0) or 0 for p in pools)
        free  = sum(p.get("free_gb", 0) or 0 for p in pools)
        if total > 0:
            storage_total = round(total, 1)
            storage_used  = round(total - free, 1)
            storage_pct   = round(storage_used / total * 100, 1)

    # CPU — if available (usually from Tier 2 live data)
    cpu_pct = _get("cpu.usage_pct")  # may be None in Tier 1

    # VM RAM allocation
    vms = manifest.get("vms") or []
    vm_ram_total = None
    if vms:
        vm_rams = [v.get("maxmem_gb") or v.get("ram_gb") or 0 for v in vms]
        vm_ram_total = round(sum(vm_rams), 2) if any(vm_rams) else None

    return {
        "observed_at":       now.isoformat(),
        "cpu_usage_pct":     cpu_pct,
        "ram_total_gb":      ram_total,
        "ram_used_gb":       ram_used,
        "ram_usage_pct":     ram_pct,
        "storage_total_gb":  storage_total,
        "storage_used_gb":   storage_used,
        "storage_usage_pct": storage_pct,
        "vm_ram_total_gb":   vm_ram_total,
    }


# ---------------------------------------------------------------------------
# Trend analysis (11.4)
# ---------------------------------------------------------------------------

def compute_trend(snapshots: list[dict]) -> dict:
    """
    Derive utilization trend direction and projection from a list of observed
    capacity snapshots, ordered oldest → newest.

    Each snapshot is a capacity_model.observed dict (from collect_capacity_snapshot).

    Returns a capacity_model.trend dict.
    """
    now = datetime.now(timezone.utc)
    valid = [s for s in snapshots if s.get("observed_at")]

    if len(valid) < 2:
        return {
            "ram_trend":           None,
            "storage_trend":       None,
            "days_to_ram_full":    None,
            "days_to_storage_full": None,
            "trend_computed_at":   now.isoformat(),
            "snapshots_used":      len(valid),
        }

    def _trend_and_days(key_pct: str) -> tuple:
        """Return (trend_str, days_to_full) for a utilization metric."""
        readings = []
        for s in valid:
            pct = s.get(key_pct)
            if pct is not None:
                try:
                    ts = datetime.fromisoformat(s["observed_at"].replace("Z", "+00:00"))
                    readings.append((ts, float(pct)))
                except (ValueError, TypeError):
                    pass

        if len(readings) < 2:
            return None, None

        oldest_ts, oldest_pct = readings[0]
        newest_ts, newest_pct = readings[-1]
        delta_days = max((newest_ts - oldest_ts).total_seconds() / 86400, 0.01)
        delta_pct  = newest_pct - oldest_pct
        rate_per_day = delta_pct / delta_days  # % points per day

        if abs(rate_per_day) < 0.1:
            trend = "stable"
        elif rate_per_day > 0:
            trend = "increasing"
        else:
            trend = "decreasing"

        days_to_full: Optional[float] = None
        if rate_per_day > 0 and newest_pct < 100:
            days_to_full = round((100 - newest_pct) / rate_per_day, 1)

        return trend, days_to_full

    ram_trend, days_ram       = _trend_and_days("ram_usage_pct")
    stor_trend, days_stor     = _trend_and_days("storage_usage_pct")

    return {
        "ram_trend":            ram_trend,
        "storage_trend":        stor_trend,
        "days_to_ram_full":     days_ram,
        "days_to_storage_full": days_stor,
        "trend_computed_at":    now.isoformat(),
        "snapshots_used":       len(valid),
    }


# ---------------------------------------------------------------------------
# Restoration headroom check (11.5)
# ---------------------------------------------------------------------------

def check_restoration_headroom(manifest: dict, capacity_model: dict) -> Optional[dict]:
    """
    Verify the host has sufficient RAM to restore all declared VMs after recovery.

    Returns a findings dict if insufficient headroom, or None if OK.
    Format: {ok: bool, required_gb: float, available_gb: float, gap_gb: float}
    """
    observed = (capacity_model.get("observed") or {})
    thresholds = {**DEFAULT_THRESHOLDS, **(capacity_model.get("thresholds") or {})}

    ram_total = observed.get("ram_total_gb")
    if ram_total is None:
        return None  # cannot assess without RAM data

    headroom_pct = thresholds["restoration_headroom_pct"]
    available_for_vms = ram_total * (1 - headroom_pct / 100)

    # Sum declared VM RAM from bootstrap-state vms[]
    vms = manifest.get("vms") or []
    vm_rams = []
    for vm in vms:
        r = vm.get("ram_gb") or vm.get("maxmem_gb")
        if r:
            try:
                vm_rams.append(float(r))
            except (TypeError, ValueError):
                pass

    if not vm_rams:
        return None  # no VM RAM data

    required_gb = sum(vm_rams)
    gap_gb      = available_for_vms - required_gb

    return {
        "ok":           gap_gb >= 0,
        "required_gb":  round(required_gb, 1),
        "available_gb": round(available_for_vms, 1),
        "gap_gb":       round(gap_gb, 1),
    }


# ---------------------------------------------------------------------------
# Merge into bootstrap-state.json (11.2)
# ---------------------------------------------------------------------------

def merge_capacity_model(
    state: dict,
    manifest: dict,
    history_snapshots: Optional[list[dict]] = None,
) -> dict:
    """
    Update the capacity_model section of bootstrap-state.json with:
    - Current observed utilization (from manifest)
    - Trend analysis (from historical snapshots if provided)

    Returns the modified state dict.
    """
    existing = state.get("capacity_model") or {}
    thresholds = existing.get("thresholds") or DEFAULT_THRESHOLDS

    observed = collect_capacity_snapshot(manifest)
    trend    = compute_trend(history_snapshots or [])

    state["capacity_model"] = {
        "thresholds": thresholds,
        "observed":   observed,
        "trend":      trend,
    }
    return state
