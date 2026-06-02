#!/usr/bin/env python3
"""
hatchery_state.py — Hatchery state reader (Phase 12.E.1).

Reads bootstrap-state.json and any available k3s/Proxmox configuration
to produce a point-in-time reservation snapshot: everything the hatchery
has reserved (VMIDs, IPs, hostnames, cluster join address, k3s tokens).

This snapshot is the authoritative "what is already taken" data embedded
in every spawn package. The broodling uses it without querying the live
hatchery API.

Provides:
  read_hatchery_state(bootstrap_state, k3s_tokens, options) → dict (spawn manifest)
  SpawnManifest                 — typed wrapper around the manifest dict
  next_vmid_block(manifest, n)  — allocate n non-conflicting VMIDs
  next_ip_block(manifest, cidr, n) — allocate n non-conflicting IPs from CIDR
  suggest_hostname(manifest, role, convention) — next hostname following convention

Stdlib only.
"""

import ipaddress
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Spawn manifest schema version
# ---------------------------------------------------------------------------

SPAWN_MANIFEST_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get(obj, *keys, default=None):
    for k in keys:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(k, default)
    return obj


# ---------------------------------------------------------------------------
# SpawnManifest — typed wrapper
# ---------------------------------------------------------------------------

@dataclass
class SpawnManifest:
    """
    Typed wrapper around the spawn manifest dict.
    Use read_hatchery_state() to construct from bootstrap-state.json.
    """
    raw: dict

    @property
    def schema_version(self) -> str:
        return self.raw.get("schema_version", SPAWN_MANIFEST_VERSION)

    @property
    def cell_id(self) -> str:
        return self.raw.get("cell_id", "")

    @property
    def reserved_vmids(self) -> set:
        return set(self.raw.get("reserved", {}).get("vmids") or [])

    @property
    def reserved_ips(self) -> set:
        return set(self.raw.get("reserved", {}).get("ips") or [])

    @property
    def reserved_hostnames(self) -> set:
        return set(self.raw.get("reserved", {}).get("hostnames") or [])

    @property
    def proxmox_cluster_address(self) -> Optional[str]:
        return _get(self.raw, "hatchery", "proxmox_cluster_address")

    @property
    def headscale_url(self) -> Optional[str]:
        return _get(self.raw, "hatchery", "headscale_url")

    @property
    def k3s_server_count(self) -> int:
        return _get(self.raw, "reserved", "k3s_server_count") or 0

    @property
    def k3s_worker_count(self) -> int:
        return _get(self.raw, "reserved", "k3s_worker_count") or 0

    @property
    def worker_join_token(self) -> Optional[str]:
        return _get(self.raw, "k3s", "worker_join_token")

    @property
    def server_join_token(self) -> Optional[str]:
        return _get(self.raw, "k3s", "server_join_token")

    def to_dict(self) -> dict:
        return self.raw


# ---------------------------------------------------------------------------
# Main reader
# ---------------------------------------------------------------------------

def read_hatchery_state(
    bootstrap_state: dict,
    k3s_tokens: Optional[dict] = None,
    proxmox_cluster_fingerprint: Optional[str] = None,
    now_fn=None,
) -> SpawnManifest:
    """
    Build a spawn manifest from the hatchery's bootstrap-state.json.

    Args:
        bootstrap_state:              parsed bootstrap-state.json dict
        k3s_tokens:                   {"worker": "...", "server": "..."} (optional)
        proxmox_cluster_fingerprint:  Proxmox cluster TLS fingerprint (optional)
        now_fn:                       injectable datetime function for tests

    Returns:
        SpawnManifest wrapping the complete reservation snapshot dict.
    """
    ts     = (now_fn or _now_utc)()
    cell_id = bootstrap_state.get("cell_id", "unknown-cell")
    hi      = bootstrap_state.get("host_identity") or {}
    nt      = bootstrap_state.get("network_topology") or {}
    vms     = bootstrap_state.get("vms") or []
    dns_reg = bootstrap_state.get("dns_registry") or []
    prov    = bootstrap_state.get("provenance_records") or []
    k3s_cfg = bootstrap_state.get("k3s_cluster") or {}   # from metadata k3s-cluster.yaml mirror

    # ── Reserved VMIDs ───────────────────────────────────────────────────────
    vmids: set[int] = set()
    for vm in vms:
        if vm.get("vmid") is not None:
            try:
                vmids.add(int(vm["vmid"]))
            except (TypeError, ValueError):
                pass
    # Always reserve template VMID range 9000-9099
    vmids.update(range(9000, 9010))

    # ── Reserved IPs ─────────────────────────────────────────────────────────
    ips: set[str] = set()
    for entry in dns_reg:
        ip = entry.get("ip")
        if ip:
            ips.add(ip)
    # Also collect IPs from provenance records (deployed VM IPs)
    for r in prov:
        for vm in vms:
            if vm.get("vmid") == r.get("vmid"):
                ip_val = vm.get("initial_ip")
                if ip_val:
                    ips.add(ip_val)

    # ── Reserved hostnames ────────────────────────────────────────────────────
    hostnames: set[str] = set()
    for entry in dns_reg:
        hn = entry.get("hostname") or entry.get("fqdn")
        if hn:
            hostnames.add(hn)
    # Also add short names
    for entry in dns_reg:
        hn = entry.get("hostname", "")
        short = hn.split(".")[0]
        if short:
            hostnames.add(short)

    # ── k3s cluster state ─────────────────────────────────────────────────────
    server_nodes = k3s_cfg.get("server_nodes") or []
    worker_nodes = k3s_cfg.get("worker_nodes") or []
    k3s_server_count = len(server_nodes)
    k3s_worker_count = len(worker_nodes)

    pod_cidr     = k3s_cfg.get("pod_cidr")     or nt.get("k3s", {}).get("pod_cidr")     or "10.42.0.0/16"
    service_cidr = k3s_cfg.get("service_cidr") or nt.get("k3s", {}).get("service_cidr") or "10.43.0.0/16"

    # ── Proxmox cluster join address ──────────────────────────────────────────
    # Use management IP of the host (from DNS registry, proxmox-host role)
    proxmox_ip = None
    for entry in dns_reg:
        if entry.get("role") == "proxmox-host" and entry.get("vmid") is None:
            proxmox_ip = entry.get("ip")
            break
    if not proxmox_ip:
        proxmox_ip = hi.get("fqdn") or hi.get("hostname")

    # Receiver URL for /api/spawn-complete (broodling POSTs here after verify)
    _fqdn = hi.get("fqdn") or hi.get("hostname") or ""
    _receiver_port = 9321
    _hatchery_receiver_url = f"http://{_fqdn}:{_receiver_port}" if _fqdn else ""

    manifest = {
        "schema_version": SPAWN_MANIFEST_VERSION,
        "cell_id":        cell_id,
        "generated_at":   ts,
        "hatchery_url":   _hatchery_receiver_url,
        "receiver_token": "",  # populated by spawn planner if --token was set
        "hatchery": {
            "hostname":                 hi.get("hostname"),
            "fqdn":                     _fqdn,
            "proxmox_cluster_address":  proxmox_ip,
            "proxmox_cluster_fingerprint": proxmox_cluster_fingerprint,
            "headscale_url":            nt.get("headscale_url"),
            "network_profile":          nt.get("profile", "lan"),
        },
        "reserved": {
            "vmids":             sorted(vmids),
            "ips":               sorted(ips),
            "hostnames":         sorted(hostnames),
            "k3s_server_count":  k3s_server_count,
            "k3s_worker_count":  k3s_worker_count,
            "management_cidr":   nt.get("management_cidr", "192.168.1.0/24"),
        },
        "k3s": {
            "pod_cidr":           pod_cidr,
            "service_cidr":       service_cidr,
            "worker_join_token":  (k3s_tokens or {}).get("worker"),
            "server_join_token":  (k3s_tokens or {}).get("server"),
        },
    }

    return SpawnManifest(raw=manifest)


# ---------------------------------------------------------------------------
# Allocation helpers — used by spawn planner to assign resources
# ---------------------------------------------------------------------------

def next_vmid_block(manifest: SpawnManifest, count: int, start_hint: int = 200) -> list[int]:
    """
    Allocate `count` consecutive VMIDs not in the manifest's reserved set.
    Returns list of `count` VMIDs starting from start_hint or higher.
    """
    reserved = manifest.reserved_vmids
    result   = []
    candidate = max(start_hint, 100)
    while len(result) < count:
        if candidate not in reserved and candidate < 9000:
            result.append(candidate)
        candidate += 1
        if candidate > 8999:
            raise ValueError(f"Cannot allocate {count} VMIDs below 9000 (all taken)")
    return result


def next_ip_block(
    manifest: SpawnManifest,
    cidr: Optional[str] = None,
    count: int = 1,
    skip_first: int = 10,
) -> list[str]:
    """
    Allocate `count` IPs from the management CIDR not in the reserved set.
    Skips the first `skip_first` host addresses (gateway, host IP, etc.).
    Returns list of IP strings.
    """
    cidr = cidr or manifest.raw.get("reserved", {}).get("management_cidr", "192.168.1.0/24")
    try:
        net = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        raise ValueError(f"Invalid CIDR: {cidr}")

    reserved = manifest.reserved_ips
    result   = []
    hosts    = list(net.hosts())

    for ip in hosts[skip_first:]:
        if str(ip) not in reserved:
            result.append(str(ip))
        if len(result) == count:
            break

    if len(result) < count:
        raise ValueError(f"Cannot allocate {count} IPs from {cidr} (insufficient free addresses)")
    return result


def suggest_hostname(
    manifest: SpawnManifest,
    role: str = "pve",
    domain: Optional[str] = None,
) -> str:
    """
    Suggest the next available hostname for a given role, following the
    pattern {role}{index:02d} (e.g. pve02, pve03).
    """
    reserved_short = {hn.split(".")[0] for hn in manifest.reserved_hostnames}
    for i in range(2, 100):
        candidate = f"{role}{i:02d}"
        if candidate not in reserved_short:
            if domain:
                return f"{candidate}.{domain}"
            return candidate
    raise ValueError(f"Cannot find unused hostname with role '{role}' (checked 02–99)")
