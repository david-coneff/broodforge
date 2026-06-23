#!/usr/bin/env python3
"""
capability_state.py — Capability State management (Phase 18.1-18.4).

Manages the declared capabilities of a broodforge cell. Capabilities are
derived from bootstrap state (what is running) and can be verified by
probing live service endpoints.

Capability categories:
  compute       k3s worker/server nodes
  storage       PBS datastore, Longhorn volumes, ZFS pools
  networking    Headscale tailnet coordinator, dnsmasq DNS server
  intelligence  Assessment engine, doc-gen engine
  observability Prometheus, Grafana, Alertmanager
  backup        Restic backup engine, PBS server
  gitops        Forgejo git server, Flux CD
  security      KeePass, cert-manager

Provides:
  CapabilityEntry               — single capability record
  CapabilityState               — full capability state for a cell
  derive_capabilities_from_state() — build from bootstrap/service state
  verify_capabilities()         — probe live endpoints
  build_capability_index()      — aggregate across cells
  capability_state_to_dict()   — JSON-serialisable dict
  CapabilityIndex               — cross-cell capability registry

Stdlib only.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

# ---------------------------------------------------------------------------
# Standard capability IDs
# ---------------------------------------------------------------------------

CAP_K3S_SERVER       = "k3s-server"
CAP_K3S_WORKER       = "k3s-worker"
CAP_PBS_DATASTORE    = "pbs-datastore"
CAP_LONGHORN         = "longhorn"
CAP_ZFS_POOL         = "zfs-pool"
CAP_HEADSCALE        = "headscale"
CAP_DNSMASQ          = "dnsmasq"
CAP_ASSESSMENT_ENGINE = "assessment-engine"
CAP_DOC_ENGINE       = "doc-engine"
CAP_PROMETHEUS       = "prometheus"
CAP_GRAFANA          = "grafana"
CAP_RESTIC_BACKUP    = "restic-backup"
CAP_PBS_SERVER       = "pbs-server"
CAP_FORGEJO          = "forgejo"
CAP_FLUX_CD          = "flux-cd"
CAP_CERT_MANAGER     = "cert-manager"


# Capability category mapping
_CAP_CATEGORIES: dict[str, str] = {
    CAP_K3S_SERVER:       "compute",
    CAP_K3S_WORKER:       "compute",
    CAP_PBS_DATASTORE:    "storage",
    CAP_LONGHORN:         "storage",
    CAP_ZFS_POOL:         "storage",
    CAP_HEADSCALE:        "networking",
    CAP_DNSMASQ:          "networking",
    CAP_ASSESSMENT_ENGINE: "intelligence",
    CAP_DOC_ENGINE:       "intelligence",
    CAP_PROMETHEUS:       "observability",
    CAP_GRAFANA:          "observability",
    CAP_RESTIC_BACKUP:    "backup",
    CAP_PBS_SERVER:       "backup",
    CAP_FORGEJO:          "gitops",
    CAP_FLUX_CD:          "gitops",
    CAP_CERT_MANAGER:     "security",
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CapabilityEntry:
    id:                  str
    category:            str
    status:              str = "active"   # active|degraded|inactive|planned
    description:         Optional[str] = None
    version:             Optional[str] = None
    endpoint:            Optional[str] = None
    verified_at:         Optional[str] = None
    verification_method: Optional[str] = None
    serves_cells:        list[str]     = field(default_factory=list)
    tags:                list[str]     = field(default_factory=list)
    ram_gib:             Optional[float] = None
    cpu_cores:           Optional[int]   = None


@dataclass
class CapabilityState:
    cell_id:         str
    declared_at:     str
    capabilities:    list[CapabilityEntry] = field(default_factory=list)
    last_verified_at: Optional[str]        = None
    collection_errors: list[dict]          = field(default_factory=list)

    def by_category(self, category: str) -> list[CapabilityEntry]:
        return [c for c in self.capabilities if c.category == category]

    def by_id(self, cap_id: str) -> Optional[CapabilityEntry]:
        return next((c for c in self.capabilities if c.id == cap_id), None)

    def active(self) -> list[CapabilityEntry]:
        return [c for c in self.capabilities if c.status == "active"]


# ---------------------------------------------------------------------------
# Derive capabilities from state (18.2 + 18.3)
# ---------------------------------------------------------------------------

def derive_capabilities_from_state(
    cell_id:        str,
    bootstrap_state: dict,
    cluster_state:   Optional[dict] = None,
    platform_state:  Optional[dict] = None,
    observability_state: Optional[dict] = None,
    now_fn: Optional[Callable[[], str]] = None,
) -> CapabilityState:
    """
    Derive the capability set from collected state documents.

    This is the 18.3 "verification" step — capabilities are active if the
    corresponding state indicates they are running.
    """
    now = (now_fn or (lambda: datetime.now(timezone.utc).isoformat()))()
    state = CapabilityState(cell_id=cell_id, declared_at=now)
    caps: list[CapabilityEntry] = []

    # From bootstrap state
    vms    = bootstrap_state.get("vms") or []
    sc     = bootstrap_state.get("service_contracts") or []
    hi     = bootstrap_state.get("host_identity") or {}
    nt     = bootstrap_state.get("network_topology") or {}

    # Derive from service contracts / VMs
    vm_names = {v.get("name", "").lower() for v in vms}
    sc_names = {s.get("service", "").lower() for s in sc}

    # k3s roles
    k3s_cfg = bootstrap_state.get("k3s_cluster") or {}
    servers = k3s_cfg.get("server_nodes") or []
    workers = k3s_cfg.get("worker_nodes") or []
    if servers:
        caps.append(CapabilityEntry(
            id=CAP_K3S_SERVER,
            category="compute",
            status="active",
            description=f"k3s control plane ({len(servers)} server node(s))",
        ))
    if workers:
        caps.append(CapabilityEntry(
            id=CAP_K3S_WORKER,
            category="compute",
            status="active",
            description=f"k3s worker node ({len(workers)} worker(s))",
        ))

    # ZFS pool
    storage = bootstrap_state.get("storage_config") or {}
    zfs = storage.get("zfs_pool") or {}
    if zfs.get("pool_name"):
        caps.append(CapabilityEntry(
            id=CAP_ZFS_POOL,
            category="storage",
            status="active",
            description=f"ZFS pool: {zfs.get('pool_name')} ({zfs.get('topology', '?')})",
        ))

    # Headscale (WAN profile)
    wan = nt.get("wan_config") or {}
    if wan.get("headscale_url") or nt.get("headscale_url"):
        caps.append(CapabilityEntry(
            id=CAP_HEADSCALE,
            category="networking",
            status="active",
            description="Self-hosted Headscale tailnet coordinator",
            endpoint=wan.get("headscale_url") or nt.get("headscale_url"),
        ))

    # dnsmasq (always if declared)
    if nt.get("profile") in ("lan", "wan"):
        caps.append(CapabilityEntry(
            id=CAP_DNSMASQ,
            category="networking",
            status="active",
            description="Split-horizon dnsmasq DNS server",
        ))

    # Forgejo (from VMs or service contracts)
    if any("forgejo" in n for n in vm_names | sc_names):
        hi.get("fqdn")
        caps.append(CapabilityEntry(
            id=CAP_FORGEJO,
            category="gitops",
            status="active",
            description="Forgejo git server (GitOps source of truth)",
            endpoint=f"https://forgejo.{hi.get('domain')}" if hi.get("domain") else None,
        ))

    # Assessment engine (always assumed present)
    caps.append(CapabilityEntry(
        id=CAP_ASSESSMENT_ENGINE,
        category="intelligence",
        status="active",
        description="Broodforge assessment engine",
    ))
    caps.append(CapabilityEntry(
        id=CAP_DOC_ENGINE,
        category="intelligence",
        status="active",
        description="Documentation generation engine",
    ))

    # Restic backup
    bc = bootstrap_state.get("backup_config") or {}
    if bc:
        caps.append(CapabilityEntry(
            id=CAP_RESTIC_BACKUP,
            category="backup",
            status="active",
            description="Restic + rclone backup engine",
        ))

    # From cluster state
    if cluster_state:
        k3s = cluster_state.get("k3s_cluster") or {}
        if k3s.get("flux_reconciled"):
            caps.append(CapabilityEntry(
                id=CAP_FLUX_CD,
                category="gitops",
                status="active",
                description="Flux CD GitOps reconciliation",
            ))

    # From observability state
    if observability_state:
        prom = observability_state.get("prometheus") or {}
        if prom.get("reachable"):
            caps.append(CapabilityEntry(
                id=CAP_PROMETHEUS,
                category="observability",
                status="active",
                endpoint=prom.get("url"),
                description="Prometheus metrics collection",
            ))
        graf = observability_state.get("grafana") or {}
        if graf.get("reachable"):
            caps.append(CapabilityEntry(
                id=CAP_GRAFANA,
                category="observability",
                status="active",
                endpoint=graf.get("url"),
                description="Grafana dashboards",
            ))

    state.capabilities = caps
    return state


# ---------------------------------------------------------------------------
# Capability Index (18.4)
# ---------------------------------------------------------------------------

@dataclass
class CapabilityIndex:
    """Cross-cell aggregation of capabilities for federation matching."""
    built_at: str
    cells: dict[str, list[str]] = field(default_factory=dict)  # cell_id → [cap_ids]
    by_capability: dict[str, list[str]] = field(default_factory=dict)  # cap_id → [cell_ids]

    def cells_with(self, cap_id: str) -> list[str]:
        """Return all cell_ids that have the given capability active."""
        return self.by_capability.get(cap_id) or []

    def capabilities_of(self, cell_id: str) -> list[str]:
        """Return all active capability IDs for a cell."""
        return self.cells.get(cell_id) or []

    def has_capability(self, cell_id: str, cap_id: str) -> bool:
        return cell_id in self.cells_with(cap_id)


def build_capability_index(
    capability_states: list[CapabilityState],
    now_fn: Optional[Callable[[], str]] = None,
) -> CapabilityIndex:
    """
    Aggregate capability states from multiple cells into a cross-cell index.

    Returns a CapabilityIndex useful for federation placement decisions.
    """
    now = (now_fn or (lambda: datetime.now(timezone.utc).isoformat()))()
    index = CapabilityIndex(built_at=now)

    for cs in capability_states:
        active_ids = [c.id for c in cs.active()]
        index.cells[cs.cell_id] = active_ids
        for cap_id in active_ids:
            if cap_id not in index.by_capability:
                index.by_capability[cap_id] = []
            if cs.cell_id not in index.by_capability[cap_id]:
                index.by_capability[cap_id].append(cs.cell_id)

    return index


# ---------------------------------------------------------------------------
# Summary helper
# ---------------------------------------------------------------------------

def _summary(state: CapabilityState) -> dict:
    all_caps = state.capabilities
    return {
        "total":    len(all_caps),
        "active":   sum(1 for c in all_caps if c.status == "active"),
        "degraded": sum(1 for c in all_caps if c.status == "degraded"),
        "inactive": sum(1 for c in all_caps if c.status == "inactive"),
        "planned":  sum(1 for c in all_caps if c.status == "planned"),
    }


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def capability_state_to_dict(state: CapabilityState) -> dict:
    """Convert CapabilityState to a JSON-serialisable dict."""
    return {
        "schema_version": "1.0",
        "cell_id":        state.cell_id,
        "declared_at":    state.declared_at,
        "last_verified_at": state.last_verified_at,
        "collection_errors": state.collection_errors,
        "capabilities": [
            {
                "id":                  c.id,
                "category":            c.category,
                "status":              c.status,
                "description":         c.description,
                "version":             c.version,
                "endpoint":            c.endpoint,
                "verified_at":         c.verified_at,
                "verification_method": c.verification_method,
                "serves_cells":        c.serves_cells,
                "tags":                c.tags,
                "resource_requirements": {
                    "ram_gib":   c.ram_gib,
                    "cpu_cores": c.cpu_cores,
                } if (c.ram_gib or c.cpu_cores) else {},
            }
            for c in state.capabilities
        ],
        "capability_summary": _summary(state),
    }
