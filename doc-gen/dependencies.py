#!/usr/bin/env python3
"""
dependencies.py — Dependency graph builder and restore sequence generator.

Builds a typed directed graph from a Tier 2 manifest.
Performs topological sort to produce restore waves.

Node types:  host, vm, container, storage, service, network, repository
Edge types:  DEPENDS_ON, STORAGE, NETWORK, SERVICE, BACKUP
"""

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Node:
    id: str
    type: str          # host, vm, container, storage, service, network, repository
    label: str
    readiness: str = "UNKNOWN"
    metadata: dict = field(default_factory=dict)


@dataclass
class Edge:
    from_id: str
    to_id: str
    type: str          # DEPENDS_ON, STORAGE, NETWORK, SERVICE, BACKUP
    label: Optional[str] = None


@dataclass
class RestoreWave:
    wave: int
    component_ids: list
    note: str = ""
    estimated_minutes: Optional[int] = None


@dataclass
class DependencyGraph:
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    restore_waves: list[RestoreWave] = field(default_factory=list)

    def node_map(self) -> dict[str, Node]:
        return {n.id: n for n in self.nodes}

    def to_dict(self) -> dict:
        return {
            "nodes": [
                {"id": n.id, "type": n.type, "label": n.label,
                 "readiness": n.readiness, "metadata": n.metadata}
                for n in self.nodes
            ],
            "edges": [
                {"from": e.from_id, "to": e.to_id, "type": e.type, "label": e.label}
                for e in self.edges
            ],
            "restore_waves": [
                {"wave": w.wave, "components": w.component_ids,
                 "note": w.note, "estimated_minutes": w.estimated_minutes}
                for w in self.restore_waves
            ],
        }


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_graph(manifest: dict) -> DependencyGraph:
    """
    Build a dependency graph from a Tier 2 observed-state manifest.

    Sources used:
      - Host node (always present)
      - ZFS pools → storage nodes
      - PVE storage → storage nodes (deduplicated with ZFS pools)
      - VMs → vm nodes (depend on host + storage)
      - Containers → container nodes (depend on host + storage)
      - Network bridges → network nodes
      - Running services (heuristic service relationships)
    """
    g = DependencyGraph()
    added_node_ids: set = set()
    added_edge_keys: set = set()

    def add_node(node: Node) -> None:
        if node.id not in added_node_ids:
            g.nodes.append(node)
            added_node_ids.add(node.id)

    def add_edge(edge: Edge) -> None:
        key = (edge.from_id, edge.to_id, edge.type)
        if key not in added_edge_keys:
            g.edges.append(edge)
            added_edge_keys.add(key)

    host = manifest.get("host", {})
    hostname = host.get("hostname", "pve-host")
    host_id = f"host:{hostname}"

    # ---- Host node ----
    add_node(Node(
        id=host_id,
        type="host",
        label=f"{hostname} (Proxmox {host.get('proxmox_version', 'unknown')})",
        metadata={
            "proxmox_version": host.get("proxmox_version"),
            "kernel": host.get("kernel_version"),
            "hostname": hostname,
        }
    ))

    # ---- Storage nodes ----
    # ZFS pools first (authoritative source for topology)
    zfs_pool_ids: dict[str, str] = {}  # pool_name → node_id
    for pool in manifest.get("storage", {}).get("zfs_pools", []):
        pool_id = f"zfs:{pool['name']}"
        zfs_pool_ids[pool["name"]] = pool_id
        add_node(Node(
            id=pool_id,
            type="storage",
            label=f"{pool['name']} (ZFS {pool.get('topology') or 'pool'}, "
                  f"{pool.get('free_gb', '?')} GB free)",
            metadata={
                "pool_name": pool["name"],
                "topology": pool.get("topology"),
                "total_gb": pool.get("total_gb"),
                "free_gb": pool.get("free_gb"),
                "state": pool.get("state"),
                "devices": pool.get("devices", []),
                "storage_type": "zfspool",
            }
        ))
        # Storage depends on host (host must be up for ZFS to be available)
        add_edge(Edge(pool_id, host_id, "DEPENDS_ON", "runs on host"))

    # PVE storage entries not already covered by ZFS pools
    pve_storage_ids: dict[str, str] = {}  # name → node_id
    for store in manifest.get("storage", {}).get("pve_storage", []):
        name = store["name"]
        # If this storage maps to a ZFS pool we already added, link it but don't duplicate
        if name in zfs_pool_ids:
            pve_storage_ids[name] = zfs_pool_ids[name]
            continue
        # Check if it's a zfspool type that matches a zpool by convention
        mapped = False
        for pool_name, pool_id in zfs_pool_ids.items():
            if name == pool_name or name == f"local-{pool_name}":
                pve_storage_ids[name] = pool_id
                mapped = True
                break
        if not mapped:
            stor_id = f"storage:{name}"
            pve_storage_ids[name] = stor_id
            add_node(Node(
                id=stor_id,
                type="storage",
                label=f"{name} ({store.get('type', 'storage')}, "
                      f"{store.get('free_gb', '?')} GB free)",
                metadata={
                    "storage_name": name,
                    "storage_type": store.get("type"),
                    "total_gb": store.get("total_gb"),
                    "free_gb": store.get("free_gb"),
                    "active": store.get("active"),
                }
            ))
            add_edge(Edge(stor_id, host_id, "DEPENDS_ON", "runs on host"))

    # Pick the "primary" storage node for VM placement
    # (largest free ZFS pool, then largest free PVE store)
    primary_storage_id: Optional[str] = None
    best_free = -1.0
    for pool in manifest.get("storage", {}).get("zfs_pools", []):
        free = pool.get("free_gb") or 0
        if free > best_free:
            best_free = free
            primary_storage_id = zfs_pool_ids[pool["name"]]
    if primary_storage_id is None:
        for name, sid in pve_storage_ids.items():
            add_edge(Edge(sid, host_id, "DEPENDS_ON", "runs on host"))
            primary_storage_id = sid
            break

    # ---- Network nodes ----
    net_bridge_ids: dict[str, str] = {}
    for bridge in manifest.get("network", {}).get("bridges", []):
        bname = bridge["name"]
        bid = f"net:{bname}"
        net_bridge_ids[bname] = bid
        add_node(Node(
            id=bid,
            type="network",
            label=f"{bname} (bridge, {', '.join(bridge.get('addresses', [])) or 'no IP'})",
            metadata={
                "bridge_name": bname,
                "ports": bridge.get("ports", []),
                "addresses": bridge.get("addresses", []),
                "vlan_aware": bridge.get("vlan_aware"),
            }
        ))
        add_edge(Edge(bid, host_id, "DEPENDS_ON", "network infrastructure on host"))

    # ---- VM nodes ----
    vm_ids_in_manifest: set = set()
    for vm in manifest.get("vms", []):
        vmid = vm["vmid"]
        name = vm.get("name", f"vm-{vmid}")
        vm_node_id = f"vm:{name}"
        vm_ids_in_manifest.add(vmid)

        add_node(Node(
            id=vm_node_id,
            type="vm",
            label=f"{name} (VM {vmid})",
            metadata={
                "vmid": vmid,
                "name": name,
                "status": vm.get("status"),
                "cores": vm.get("cores"),
                "memory_mb": vm.get("memory_mb"),
                "disk_gb": vm.get("disk_gb"),
            }
        ))

        # All VMs depend on host
        add_edge(Edge(vm_node_id, host_id, "DEPENDS_ON", "runs on host"))

        # All VMs depend on primary storage
        if primary_storage_id:
            add_edge(Edge(vm_node_id, primary_storage_id, "STORAGE", "primary storage"))

        # All VMs depend on primary network bridge
        if net_bridge_ids:
            primary_bridge = next(iter(net_bridge_ids.values()))
            add_edge(Edge(vm_node_id, primary_bridge, "NETWORK", "network access"))

    # ---- Container nodes ----
    for ct in manifest.get("containers", []):
        ctid = ct["ctid"]
        name = ct.get("name", f"ct-{ctid}")
        ct_node_id = f"ct:{name}"

        add_node(Node(
            id=ct_node_id,
            type="container",
            label=f"{name} (CT {ctid})",
            metadata={
                "ctid": ctid,
                "name": name,
                "status": ct.get("status"),
            }
        ))
        add_edge(Edge(ct_node_id, host_id, "DEPENDS_ON", "runs on host"))
        if primary_storage_id:
            add_edge(Edge(ct_node_id, primary_storage_id, "STORAGE", "primary storage"))

    # ---- Service relationship heuristics ----
    # Known service dependency patterns based on VM names
    _add_service_heuristics(g, added_edge_keys, manifest)

    # ---- Topological sort → restore waves ----
    g.restore_waves = _topological_waves(g)

    return g


def _add_service_heuristics(
    g: DependencyGraph,
    added_edge_keys: set,
    manifest: dict,
) -> None:
    """
    Add inferred NETWORK dependencies between VMs based on known service patterns.
    These are best-effort; Tier 2 full assessment would replace with API-sourced edges.
    """
    node_map = g.node_map()
    vm_nodes = {n.id: n for n in g.nodes if n.type == "vm"}

    # Known patterns: services that others depend on
    DEPENDENCY_PATTERNS = [
        # (provider_name_fragment, consumer_name_fragment, label)
        ("forgejo",    "assessment",  "git remote (assessment repos)"),
        ("forgejo",    "inventory",   "git remote (inventory repo)"),
        ("forgejo",    "ansible",     "git remote (ansible repo)"),
        ("forgejo",    "tofu",        "git remote (tofu repo)"),
        ("inventory",  "assessment",  "inventory data"),
        ("dns",        None,          "DNS service"),  # everything depends on DNS
        ("nfs",        None,          "NFS storage"),
        ("postgres",   None,          "database"),
        ("database",   None,          "database"),
        ("db",         None,          "database"),
    ]

    def _find_vm_node(fragment: str) -> Optional[str]:
        for nid, node in vm_nodes.items():
            if fragment.lower() in node.metadata.get("name", "").lower():
                return nid
        return None

    for provider_frag, consumer_frag, label in DEPENDENCY_PATTERNS:
        provider_id = _find_vm_node(provider_frag)
        if provider_id is None:
            continue
        if consumer_frag is None:
            # Provider is a dependency for all other VMs
            for nid in vm_nodes:
                if nid == provider_id:
                    continue
                key = (nid, provider_id, "NETWORK")
                if key not in added_edge_keys:
                    g.edges.append(Edge(nid, provider_id, "NETWORK", label))
                    added_edge_keys.add(key)
        else:
            consumer_id = _find_vm_node(consumer_frag)
            if consumer_id and consumer_id != provider_id:
                key = (consumer_id, provider_id, "NETWORK")
                if key not in added_edge_keys:
                    g.edges.append(Edge(consumer_id, provider_id, "NETWORK", label))
                    added_edge_keys.add(key)


# ---------------------------------------------------------------------------
# Topological sort → restore waves
# ---------------------------------------------------------------------------

def _topological_waves(g: DependencyGraph) -> list[RestoreWave]:
    """
    Kahn's algorithm topological sort, grouped into parallel restore waves.

    A "wave" contains all nodes whose dependencies are satisfied by previous waves.
    Nodes within a wave have no mutual dependencies and can be restored in parallel.

    Restore order is: what you depend ON must be restored BEFORE you.
    So edges point FROM dependent TO dependency (consumer → provider).
    """
    node_ids = [n.id for n in g.nodes]
    node_map = g.node_map()

    # Build adjacency: prerequisite_id → [nodes that depend on it]
    # and in-degree: how many unresolved prerequisites each node has
    in_degree: dict[str, int] = {nid: 0 for nid in node_ids}
    dependents: dict[str, list] = defaultdict(list)  # prereq → consumers

    for edge in g.edges:
        # edge.from_id depends on edge.to_id
        # so edge.to_id must be restored first
        in_degree[edge.from_id] = in_degree.get(edge.from_id, 0) + 1
        dependents[edge.to_id].append(edge.from_id)

    # Wave 0: nodes with no prerequisites
    ready = deque(nid for nid in node_ids if in_degree[nid] == 0)
    waves: list[RestoreWave] = []
    wave_num = 1
    processed = 0

    while ready:
        wave_nodes = list(ready)
        ready.clear()

        # Sort within wave for stable output: host first, then storage, then network, then VMs
        TYPE_ORDER = {"host": 0, "storage": 1, "network": 2,
                      "vm": 3, "container": 3, "service": 4, "repository": 5}
        wave_nodes.sort(key=lambda nid: (
            TYPE_ORDER.get(node_map.get(nid, Node("","unknown","")).type, 9),
            nid
        ))

        # Generate wave note
        types_in_wave = [node_map[nid].type for nid in wave_nodes if nid in node_map]
        note = _wave_note(wave_num, types_in_wave, wave_nodes, node_map)
        est = _estimate_minutes(types_in_wave)

        waves.append(RestoreWave(
            wave=wave_num,
            component_ids=wave_nodes,
            note=note,
            estimated_minutes=est,
        ))
        wave_num += 1
        processed += len(wave_nodes)

        for nid in wave_nodes:
            for dep in dependents.get(nid, []):
                in_degree[dep] -= 1
                if in_degree[dep] == 0:
                    ready.append(dep)

    # Cycle detection
    if processed < len(node_ids):
        remaining = [nid for nid in node_ids if in_degree.get(nid, 0) > 0]
        waves.append(RestoreWave(
            wave=wave_num,
            component_ids=remaining,
            note=f"WARNING: Possible dependency cycle detected — {len(remaining)} node(s) not placed",
        ))

    return waves


def _wave_note(wave: int, types: list, node_ids: list, node_map: dict) -> str:
    type_counts = defaultdict(int)
    for t in types:
        type_counts[t] += 1

    if "host" in type_counts:
        return "Physical host — must be restored first"
    if "storage" in type_counts and "vm" not in type_counts:
        return "Storage layer — must be available before VMs can start"
    if "network" in type_counts and "vm" not in type_counts:
        return "Network infrastructure — bridges and routing"
    if "vm" in type_counts or "container" in type_counts:
        labels = [node_map[nid].label for nid in node_ids if nid in node_map]
        if len(labels) == 1:
            return f"Restore: {labels[0]}"
        return f"Restore {len(labels)} component(s) — no mutual dependencies"
    return f"Wave {wave}"


def _estimate_minutes(types: list) -> int:
    estimates = {"host": 90, "storage": 15, "network": 5,
                 "vm": 20, "container": 10, "service": 5, "repository": 10}
    return sum(estimates.get(t, 10) for t in types)


# ---------------------------------------------------------------------------
# Restore sequence text generator
# ---------------------------------------------------------------------------

def restore_sequence_text(g: DependencyGraph, manifest: dict) -> str:
    """Generate a human-readable restore sequence from the dependency graph."""
    node_map = g.node_map()
    lines = [
        "# Restore Sequence",
        f"Host: {manifest.get('host', {}).get('hostname', 'unknown')}",
        f"Assessment: {manifest.get('collected_at', 'unknown')}",
        f"Total waves: {len(g.restore_waves)}",
        f"Estimated total time: {sum(w.estimated_minutes or 0 for w in g.restore_waves)} minutes",
        "",
    ]

    for wave in g.restore_waves:
        lines.append(f"## Wave {wave.wave} — {wave.note}")
        if wave.estimated_minutes:
            lines.append(f"Estimated time: {wave.estimated_minutes} minutes")
        for cid in wave.component_ids:
            node = node_map.get(cid)
            if node:
                deps = [e.to_id for e in g.edges if e.from_id == cid]
                dep_labels = [node_map[d].label for d in deps if d in node_map]
                lines.append(f"  - {node.label}")
                if dep_labels:
                    lines.append(f"    Dependencies: {', '.join(dep_labels)}")
        lines.append("")

    return "\n".join(lines)
