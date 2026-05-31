#!/usr/bin/env python3
"""
analyzers.py — DERIVED field analyzers for bootstrap documentation generation.

Each analyzer receives the full manifest dict and returns a Result with:
  value      — the recommended value (string)
  rationale  — explanation of how the recommendation was derived
  confidence — HIGH / MEDIUM / LOW
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Result:
    value: str
    rationale: str
    confidence: str = "HIGH"  # HIGH / MEDIUM / LOW
    warnings: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# VM sizing
# ---------------------------------------------------------------------------

def infra_bootstrap_vm_ram(manifest: dict) -> Result:
    """Recommend RAM allocation for the infra-bootstrap VM."""
    total_gb = manifest.get("memory", {}).get("total_gb", 0) or 0

    if total_gb >= 128:
        rec, rationale = 16, f"Host has {total_gb:.0f} GB RAM. 16 GB allocated (12.5% of total)."
    elif total_gb >= 64:
        rec, rationale = 8, f"Host has {total_gb:.0f} GB RAM. 8 GB allocated (standard allocation)."
    elif total_gb >= 32:
        rec, rationale = 4, f"Host has {total_gb:.0f} GB RAM. 4 GB allocated (host RAM is moderate)."
    elif total_gb >= 16:
        rec, rationale = 2, f"Host has {total_gb:.0f} GB RAM. 2 GB allocated (host RAM is low; consider additional RAM)."
        return Result(value=f"{rec} GB", rationale=rationale, confidence="MEDIUM",
                      warnings=["Host RAM is low. 2 GB may limit future VM expansion."])
    else:
        return Result(
            value="2 GB",
            rationale=f"Host has {total_gb:.0f} GB RAM. Minimum allocation; RAM is critically low.",
            confidence="LOW",
            warnings=[
                f"Host has only {total_gb:.0f} GB RAM total.",
                "Strongly recommend adding RAM before proceeding with full bootstrap.",
            ]
        )
    return Result(value=f"{rec} GB", rationale=rationale)


def infra_bootstrap_vm_cores(manifest: dict) -> Result:
    """Recommend vCPU count for the infra-bootstrap VM."""
    total_threads = manifest.get("cpu", {}).get("total_threads", 0) or 0

    if total_threads >= 32:
        rec = 4
    elif total_threads >= 16:
        rec = 4
    elif total_threads >= 8:
        rec = 2
    else:
        rec = 2

    rationale = (
        f"Host has {total_threads} logical CPUs. "
        f"{rec} vCPUs allocated for infra-bootstrap VM."
    )
    return Result(value=str(rec), rationale=rationale)


def infra_bootstrap_vm_disk(manifest: dict) -> Result:
    """Recommend boot disk size for infra-bootstrap VM based on available storage."""
    pools = manifest.get("storage", {}).get("zfs_pools", [])
    pve_stores = manifest.get("storage", {}).get("pve_storage", [])

    best_free = 0
    best_name = None

    for pool in pools:
        free = pool.get("free_gb") or 0
        if free > best_free:
            best_free = free
            best_name = pool["name"]

    for store in pve_stores:
        if store.get("type") == "zfspool":
            free = store.get("free_gb") or 0
            if free > best_free:
                best_free = free
                best_name = store["name"]

    if best_free >= 500:
        rec, confidence = 64, "HIGH"
    elif best_free >= 200:
        rec, confidence = 64, "HIGH"
    elif best_free >= 100:
        rec, confidence = 32, "MEDIUM"
    elif best_free >= 50:
        rec, confidence = 32, "MEDIUM"
    else:
        rec, confidence = 20, "LOW"

    store_note = f" (pool: {best_name}, {best_free:.0f} GB free)" if best_name else ""
    rationale = f"{rec} GB disk recommended{store_note}."
    warnings = []
    if best_free < 100:
        warnings.append(f"Available storage is low ({best_free:.0f} GB free). Consider adding storage.")

    return Result(value=f"{rec} GB", rationale=rationale, confidence=confidence, warnings=warnings)


# ---------------------------------------------------------------------------
# Storage recommendations
# ---------------------------------------------------------------------------

def zfs_topology_recommendation(manifest: dict) -> Result:
    """Recommend ZFS pool topology based on detected block devices."""
    devices = manifest.get("storage", {}).get("block_devices", [])
    disks = [d for d in devices if d.get("type") == "disk"]
    ssds  = [d for d in disks if d.get("rotational") is False]
    hdds  = [d for d in disks if d.get("rotational") is True]
    unk   = [d for d in disks if d.get("rotational") is None]

    # Prefer SSDs; fall back to all disks if no rotational data
    primary = ssds if ssds else (disks if not hdds else hdds)
    n = len(primary)
    dev_names = [d["name"] for d in primary]
    dev_type = "SSD" if ssds else ("HDD" if hdds else "disk")

    warnings = []

    if n == 0:
        return Result(
            value="UNRESOLVED",
            rationale="No block devices detected. Cannot recommend ZFS topology.",
            confidence="LOW",
            warnings=["No disks found. Check lsblk output."]
        )
    elif n == 1:
        topology = "single (no redundancy)"
        rationale = (
            f"One {dev_type} detected ({dev_names[0]}). "
            "ZFS single-device pool possible but provides no redundancy."
        )
        warnings.append("Single disk — no redundancy. Strongly recommend adding a second disk for mirror.")
        confidence = "MEDIUM"
    elif n == 2:
        topology = "mirror"
        rationale = (
            f"Two {dev_type}s detected ({', '.join(dev_names)}). "
            "ZFS mirror recommended: full redundancy, no write penalty vs. single device."
        )
        confidence = "HIGH"
    elif n == 3:
        topology = "raidz1"
        rationale = (
            f"Three {dev_type}s detected ({', '.join(dev_names)}). "
            "RAIDZ1 recommended: 1-disk fault tolerance, ~67% usable capacity."
        )
        confidence = "HIGH"
    elif n == 4:
        topology = "raidz1 (4-wide) or mirror×2"
        rationale = (
            f"Four {dev_type}s detected ({', '.join(dev_names)}). "
            "Options: RAIDZ1 (1 parity, ~75% usable) or two-way mirror ×2 (faster IOPS, 50% usable)."
        )
        confidence = "MEDIUM"
    else:
        topology = f"raidz2 ({n}-wide)"
        rationale = (
            f"{n} {dev_type}s detected ({', '.join(dev_names[:4])}{'...' if n > 4 else ''}). "
            "RAIDZ2 recommended: 2-disk fault tolerance."
        )
        confidence = "HIGH"

    # Mixed media warning
    if ssds and hdds:
        warnings.append(
            f"Mixed media detected: {len(ssds)} SSD(s) and {len(hdds)} HDD(s). "
            "Recommend using matched media in the same pool."
        )

    # Existing pools
    existing = manifest.get("storage", {}).get("zfs_pools", [])
    if existing:
        existing_names = [p["name"] for p in existing]
        warnings.append(
            f"Existing ZFS pool(s) detected: {', '.join(existing_names)}. "
            "Verify topology matches recommendation before proceeding."
        )

    return Result(value=topology, rationale=rationale, confidence=confidence, warnings=warnings)


def storage_pool_name(manifest: dict) -> Result:
    """Identify the primary storage pool for VM placement."""
    pools = manifest.get("storage", {}).get("zfs_pools", [])
    if not pools:
        return Result(
            value="local-zfs",
            rationale="No ZFS pools detected. Defaulting to 'local-zfs' (standard Proxmox name).",
            confidence="LOW",
        )
    # Pick largest free pool
    best = max(pools, key=lambda p: p.get("free_gb") or 0)
    return Result(
        value=best["name"],
        rationale=(
            f"Pool '{best['name']}' has the most free space "
            f"({best.get('free_gb', 0):.0f} GB free, topology: {best.get('topology') or 'unknown'})."
        ),
    )


# ---------------------------------------------------------------------------
# VM ID recommendations
# ---------------------------------------------------------------------------

def next_available_vmid(manifest: dict) -> Result:
    """Return the next available VM ID starting from 100."""
    used = set()
    for vm in manifest.get("vms", []):
        used.add(vm.get("vmid"))
    for ct in manifest.get("containers", []):
        used.add(ct.get("ctid"))

    candidate = 100
    while candidate in used:
        candidate += 1

    if not used:
        rationale = "No existing VMs or containers. Starting at VM ID 100 (Proxmox convention)."
    else:
        rationale = (
            f"Existing IDs in use: {sorted(used)}. "
            f"Next available ID: {candidate}."
        )
    return Result(value=str(candidate), rationale=rationale)


def vm_id_sequence(manifest: dict, count: int = 4) -> Result:
    """Return the next N available VM IDs for the full bootstrap sequence."""
    used = set()
    for vm in manifest.get("vms", []):
        used.add(vm.get("vmid"))
    for ct in manifest.get("containers", []):
        used.add(ct.get("ctid"))

    ids = []
    candidate = 100
    while len(ids) < count:
        if candidate not in used:
            ids.append(candidate)
        candidate += 1

    rationale = (
        f"Next {count} available VM IDs: {ids}. "
        + (f"Skipped existing IDs: {sorted(used)}." if used else "No existing IDs in use.")
    )
    return Result(value=", ".join(str(i) for i in ids), rationale=rationale)


# ---------------------------------------------------------------------------
# Network recommendations
# ---------------------------------------------------------------------------

def recommend_bridge(manifest: dict) -> Result:
    """Recommend a bridge name for new VMs."""
    existing_bridges = {b["name"] for b in manifest.get("network", {}).get("bridges", [])}
    existing_ifaces  = {i["name"] for i in manifest.get("network", {}).get("interfaces", [])}

    if "vmbr0" not in existing_bridges and "vmbr0" not in existing_ifaces:
        return Result(
            value="vmbr0",
            rationale="vmbr0 is the Proxmox default bridge name and is not yet in use.",
        )

    # Find next available
    for n in range(1, 10):
        candidate = f"vmbr{n}"
        if candidate not in existing_bridges and candidate not in existing_ifaces:
            return Result(
                value=candidate,
                rationale=(
                    f"vmbr0 is already in use. "
                    f"Recommend {candidate} as the next available bridge name."
                ),
            )

    return Result(
        value="vmbr1",
        rationale="Could not determine next available bridge. Defaulting to vmbr1.",
        confidence="LOW",
    )


def recommend_ip_plan(manifest: dict) -> Result:
    """Suggest a VM IP addressing plan based on the host's existing network."""
    bridges = manifest.get("network", {}).get("bridges", [])
    interfaces = manifest.get("network", {}).get("interfaces", [])

    host_cidr = None
    host_ip = None

    # Find the first non-loopback address
    for bridge in bridges:
        for addr in bridge.get("addresses", []):
            if not addr.startswith("127."):
                host_cidr = addr
                host_ip = addr.split("/")[0]
                break
        if host_cidr:
            break

    if not host_cidr:
        for iface in interfaces:
            for addr in iface.get("addresses", []):
                if not addr.startswith("127.") and not addr.startswith("::"):
                    host_cidr = addr
                    host_ip = addr.split("/")[0]
                    break
            if host_cidr:
                break

    if not host_ip:
        return Result(
            value="HUMAN INPUT REQUIRED",
            rationale="Could not detect host IP address. Operator must specify VM IP plan.",
            confidence="LOW",
        )

    # Suggest .x range in same subnet
    parts = host_ip.split(".")
    if len(parts) == 4:
        prefix = ".".join(parts[:3])
        prefix_len = host_cidr.split("/")[1] if "/" in host_cidr else "24"
        suggestion = f"{prefix}.20–{prefix}.30/{prefix_len}"
        rationale = (
            f"Host IP is {host_ip}/{prefix_len}. "
            f"Suggested VM range: {suggestion} (same subnet, avoids host address)."
        )
        return Result(value=suggestion, rationale=rationale, confidence="MEDIUM")

    return Result(
        value="HUMAN INPUT REQUIRED",
        rationale="Could not parse host IP for VM subnet suggestion.",
        confidence="LOW",
    )


# ---------------------------------------------------------------------------
# Summary / readiness indicators
# ---------------------------------------------------------------------------

def automation_readiness_summary(manifest: dict) -> Result:
    """Summarise automation tool availability."""
    r = manifest.get("software", {}).get("automation_readiness", {})
    present  = [k for k, v in r.items() if v]
    missing  = [k for k, v in r.items() if not v]

    value = "Ready" if not missing else f"Partial ({len(missing)} tools missing)"
    rationale = (
        f"Present: {', '.join(present) or 'none'}. "
        f"Missing: {', '.join(missing) or 'none'}."
    )
    confidence = "HIGH" if not missing else "MEDIUM"
    warnings = [f"'{t}' not detected — will need to be installed during bootstrap." for t in missing]
    return Result(value=value, rationale=rationale, confidence=confidence, warnings=warnings)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

ANALYZERS = {
    "vm_sizing.infra_bootstrap_ram":    infra_bootstrap_vm_ram,
    "vm_sizing.infra_bootstrap_cores":  infra_bootstrap_vm_cores,
    "vm_sizing.infra_bootstrap_disk":   infra_bootstrap_vm_disk,
    "storage.zfs_topology":             zfs_topology_recommendation,
    "storage.pool_name":                storage_pool_name,
    "vm_ids.next_available":            next_available_vmid,
    "vm_ids.sequence_4":                vm_id_sequence,
    "network.recommend_bridge":         recommend_bridge,
    "network.recommend_ip_plan":        recommend_ip_plan,
    "software.automation_readiness":    automation_readiness_summary,
}


def run(analyzer_id: str, manifest: dict) -> Result:
    fn = ANALYZERS.get(analyzer_id)
    if fn is None:
        return Result(
            value="UNRESOLVED",
            rationale=f"Unknown analyzer: {analyzer_id}",
            confidence="LOW",
        )
    try:
        return fn(manifest)
    except Exception as exc:
        return Result(
            value="UNRESOLVED",
            rationale=f"Analyzer '{analyzer_id}' raised an exception: {exc}",
            confidence="LOW",
        )
