#!/usr/bin/env python3
"""
failure_domain.py — Failure Domain Modeling (Phase 21).

Models how failures propagate through the infrastructure and identifies
single points of failure and circular recovery dependencies.

21.1  FailureDomainTaxonomy  — hierarchical failure domain types
21.2  PropagationEngine      — storage → VMs → services propagation rules
21.3  blast_radius()         — enumerate components affected by a failure
21.4  detect_spofs()         — components with no recovery alternative
21.5  detect_circular_deps() — circular recovery dependencies
21.6  FailureDomainReport    — for embedding in readiness reports

Provides:
  FailureDomainLevel   — enum-like constants (physical/cluster/vm/service)
  FailureDomainNode    — node in the failure domain graph
  PropagationRule      — how a failure propagates
  PropagationEngine    — apply propagation rules to a failure set
  blast_radius()       — enumerate all affected nodes given an initial failure
  detect_spofs()       — find components with no recovery alternative
  detect_circular_deps() — find circular dependency chains
  FailureDomainReport  — structured report for readiness integration
  build_failure_domain_graph() — construct graph from manifest

Stdlib only.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# Failure domain taxonomy (21.1)
# ---------------------------------------------------------------------------

LEVEL_PHYSICAL  = "physical"    # Host hardware, disk, NIC
LEVEL_CLUSTER   = "cluster"     # Proxmox cluster, ZFS pool, network bridge
LEVEL_VM        = "vm"          # Individual VM
LEVEL_SERVICE   = "service"     # Service running inside a VM
LEVEL_K3S       = "k3s"         # k3s node or cluster
LEVEL_STORAGE   = "storage"     # Storage backend
LEVEL_NETWORK   = "network"     # Network segment
LEVEL_EXTERNAL  = "external"    # External dependency

ALL_LEVELS = (
    LEVEL_PHYSICAL, LEVEL_CLUSTER, LEVEL_VM, LEVEL_SERVICE,
    LEVEL_K3S, LEVEL_STORAGE, LEVEL_NETWORK, LEVEL_EXTERNAL,
)


@dataclass
class FailureDomainNode:
    """A component that can fail and whose failure may propagate."""
    node_id:      str
    level:        str           # one of ALL_LEVELS
    label:        str
    cell_id:      str
    redundancy:   int   = 1     # number of equivalent instances (1 = SPOF)
    depends_on:   list[str] = field(default_factory=list)   # node_ids this depends on
    recovers_via: list[str] = field(default_factory=list)   # node_ids that can recover this
    metadata:     dict   = field(default_factory=dict)

    @property
    def is_spof(self) -> bool:
        return self.redundancy <= 1 and not self.recovers_via


@dataclass
class PropagationRule:
    """A rule describing how a failure at a source propagates to a target."""
    source_level: str    # failure at this level…
    target_level: str    # …propagates to this level
    condition:    str    # "direct_dependency" | "shared_resource" | "network"
    probability:  float  = 1.0    # 0.0–1.0 (1.0 = always propagates)
    description:  str    = ""


# Default propagation rules (21.2)
DEFAULT_PROPAGATION_RULES: list[PropagationRule] = [
    PropagationRule(LEVEL_PHYSICAL,  LEVEL_CLUSTER,  "direct_dependency", 1.0,
                    "Physical host failure takes down Proxmox cluster node"),
    PropagationRule(LEVEL_PHYSICAL,  LEVEL_STORAGE,  "shared_resource",   1.0,
                    "Physical host failure takes down ZFS pool on that host"),
    PropagationRule(LEVEL_STORAGE,   LEVEL_VM,       "direct_dependency", 1.0,
                    "ZFS pool failure causes VMs using that pool to fail"),
    PropagationRule(LEVEL_CLUSTER,   LEVEL_VM,       "direct_dependency", 1.0,
                    "Proxmox node failure causes VMs on that node to fail"),
    PropagationRule(LEVEL_VM,        LEVEL_SERVICE,  "direct_dependency", 1.0,
                    "VM failure causes all services in that VM to fail"),
    PropagationRule(LEVEL_VM,        LEVEL_K3S,      "direct_dependency", 1.0,
                    "VM with k3s node fails → k3s node goes NotReady"),
    PropagationRule(LEVEL_K3S,       LEVEL_SERVICE,  "direct_dependency", 0.8,
                    "k3s node failure may impact services scheduled there"),
    PropagationRule(LEVEL_NETWORK,   LEVEL_EXTERNAL, "network",           0.9,
                    "Network segment failure may block external dependency access"),
    PropagationRule(LEVEL_NETWORK,   LEVEL_SERVICE,  "network",           0.7,
                    "Network segment failure may make services unreachable"),
]


# ---------------------------------------------------------------------------
# Propagation engine (21.2)
# ---------------------------------------------------------------------------

class PropagationEngine:
    """
    Apply failure propagation rules to an initial failure set.

    Given a set of initially-failed node IDs, uses dependency edges and
    propagation rules to determine the full set of affected nodes.
    """

    def __init__(
        self,
        nodes: list[FailureDomainNode],
        rules: list[PropagationRule] | None = None,
    ):
        self._nodes: dict[str, FailureDomainNode] = {n.node_id: n for n in nodes}
        self._rules: list[PropagationRule] = rules or DEFAULT_PROPAGATION_RULES
        # Build dependency graph: depended_on_by[node_id] = [dependent_ids]
        self._dependents: dict[str, list[str]] = {n: [] for n in self._nodes}
        for node in nodes:
            for dep_id in node.depends_on:
                if dep_id in self._dependents:
                    self._dependents[dep_id].append(node.node_id)

    def propagate(
        self,
        initial_failures: set[str],
        *,
        probability_threshold: float = 0.5,
    ) -> set[str]:
        """
        Return the set of all node_ids affected by initial_failures.

        Uses BFS: failed node → its dependents → their dependents, etc.
        Only follows edges where the applicable propagation rule's probability
        meets the threshold.
        """
        affected: set[str] = set(initial_failures)
        queue    = list(initial_failures)

        while queue:
            src_id = queue.pop(0)
            src    = self._nodes.get(src_id)
            if src is None:
                continue

            # Find nodes that depend on src_id
            for dep_id in self._dependents.get(src_id, []):
                if dep_id in affected:
                    continue
                dep = self._nodes.get(dep_id)
                if dep is None:
                    continue

                # Check if any rule applies
                rule = self._applicable_rule(src.level, dep.level)
                if rule and rule.probability >= probability_threshold:
                    affected.add(dep_id)
                    queue.append(dep_id)

        return affected

    def _applicable_rule(
        self,
        src_level: str,
        tgt_level: str,
    ) -> PropagationRule | None:
        for rule in self._rules:
            if rule.source_level == src_level and rule.target_level == tgt_level:
                return rule
        return None


# ---------------------------------------------------------------------------
# Blast radius (21.3)
# ---------------------------------------------------------------------------

@dataclass
class BlastRadiusResult:
    initial_failures:  set[str]
    all_affected:      set[str]
    by_level:          dict[str, set[str]]  # level → {node_ids}
    total_affected:    int
    critical_services: set[str]             # affected SERVICE-level nodes


def blast_radius(
    failed_node_ids: set[str] | list[str],
    nodes:           list[FailureDomainNode],
    rules:           list[PropagationRule] | None = None,
    *,
    probability_threshold: float = 0.5,
) -> BlastRadiusResult:
    """
    Given a set of initially-failed nodes, enumerate all affected nodes.

    Returns a BlastRadiusResult with affected nodes grouped by level.
    """
    engine   = PropagationEngine(nodes, rules)
    initial  = set(failed_node_ids)
    affected = engine.propagate(initial, probability_threshold=probability_threshold)

    node_map = {n.node_id: n for n in nodes}
    by_level: dict[str, set[str]] = {level: set() for level in ALL_LEVELS}
    critical: set[str] = set()

    for nid in affected:
        node = node_map.get(nid)
        if node:
            by_level[node.level].add(nid)
            if node.level == LEVEL_SERVICE:
                critical.add(nid)

    return BlastRadiusResult(
        initial_failures=initial,
        all_affected=affected,
        by_level=by_level,
        total_affected=len(affected),
        critical_services=critical,
    )


# ---------------------------------------------------------------------------
# SPOF detection (21.4)
# ---------------------------------------------------------------------------

@dataclass
class SpofFinding:
    node_id:    str
    level:      str
    label:      str
    cell_id:    str
    reason:     str


def detect_spofs(nodes: list[FailureDomainNode]) -> list[SpofFinding]:
    """
    Identify nodes that are single points of failure.

    A node is a SPOF if:
      - redundancy ≤ 1 (only one instance)
      - AND no recovers_via alternatives declared
      - AND at least one other node depends on it
    """
    node_map = {n.node_id: n for n in nodes}
    # Which nodes are depended upon?
    depended_on: set[str] = set()
    for node in nodes:
        depended_on.update(node.depends_on)

    findings: list[SpofFinding] = []
    for node in nodes:
        if node.node_id not in depended_on:
            continue     # nobody depends on this node → not a SPOF for others
        if not node.is_spof:
            continue     # has redundancy or recovery alternative
        findings.append(SpofFinding(
            node_id=node.node_id,
            level=node.level,
            label=node.label,
            cell_id=node.cell_id,
            reason=(
                f"Redundancy={node.redundancy}, no recovers_via declared. "
                f"Depended on by: {_find_dependents(node.node_id, nodes)}"
            ),
        ))
    return findings


def _find_dependents(node_id: str, nodes: list[FailureDomainNode]) -> str:
    deps = [n.label for n in nodes if node_id in n.depends_on]
    return ", ".join(deps[:5]) + ("…" if len(deps) > 5 else "")


# ---------------------------------------------------------------------------
# Circular dependency detection (21.5)
# ---------------------------------------------------------------------------

@dataclass
class CircularDependencyFinding:
    cycle:      list[str]   # node_ids forming the cycle
    labels:     list[str]   # human-readable labels


def detect_circular_deps(nodes: list[FailureDomainNode]) -> list[CircularDependencyFinding]:
    """
    Detect circular dependencies in the recovers_via graph.

    A circular dependency means: cell A recovers via cell B, which recovers
    via cell A — both would need to be up to recover the other.
    Uses DFS cycle detection.
    """
    node_map = {n.node_id: n for n in nodes}
    visited: set[str]    = set()
    in_stack: set[str]   = set()
    findings: list[CircularDependencyFinding] = []

    def dfs(node_id: str, path: list[str]) -> None:
        if node_id in in_stack:
            cycle_start = path.index(node_id)
            cycle = path[cycle_start:]
            labels = [node_map[n].label if n in node_map else n for n in cycle]
            findings.append(CircularDependencyFinding(cycle=cycle, labels=labels))
            return
        if node_id in visited:
            return
        visited.add(node_id)
        in_stack.add(node_id)
        path.append(node_id)
        node = node_map.get(node_id)
        if node:
            for recovery_id in node.recovers_via:
                dfs(recovery_id, list(path))
        in_stack.discard(node_id)

    for node in nodes:
        if node.node_id not in visited:
            dfs(node.node_id, [])

    return findings


# ---------------------------------------------------------------------------
# Graph builder from manifest (21.6)
# ---------------------------------------------------------------------------

def build_failure_domain_graph(manifest: dict) -> list[FailureDomainNode]:
    """
    Build a FailureDomainNode list from a bootstrap-state.json manifest.

    This is a best-effort construction from known manifest fields.
    Operators can extend by adding dependency declarations to their manifest.
    """
    cell_id = manifest.get("cell_id") or "unknown"
    nodes:  list[FailureDomainNode] = []

    hi = manifest.get("host_identity") or {}
    sc = manifest.get("storage_config") or {}
    zfs = sc.get("zfs_pool") or {}

    # Physical host
    hostname = hi.get("hostname") or "host"
    host_id  = f"{cell_id}:host:{hostname}"
    nodes.append(FailureDomainNode(
        node_id=host_id, level=LEVEL_PHYSICAL,
        label=f"Host: {hostname}", cell_id=cell_id,
        redundancy=1,
    ))

    # ZFS pool / storage
    pool_name = zfs.get("pool_name") or "zfs-pool"
    pool_id   = f"{cell_id}:storage:{pool_name}"
    nodes.append(FailureDomainNode(
        node_id=pool_id, level=LEVEL_STORAGE,
        label=f"ZFS: {pool_name}", cell_id=cell_id,
        redundancy=1,
        depends_on=[host_id],
    ))

    # Network bridges
    nt_decl   = manifest.get("network_topology_declared") or {}
    bridges   = nt_decl.get("bridges") or []
    bridge_ids = []
    for bridge in bridges:
        b_name = bridge.get("name") or "vmbr0"
        b_id   = f"{cell_id}:network:{b_name}"
        nodes.append(FailureDomainNode(
            node_id=b_id, level=LEVEL_NETWORK,
            label=f"Bridge: {b_name}", cell_id=cell_id,
            redundancy=1,
            depends_on=[host_id],
        ))
        bridge_ids.append(b_id)

    # VMs
    vms = manifest.get("vms") or []
    vm_ids = {}
    for vm in vms:
        vmid   = str(vm.get("vmid") or "?")
        vname  = vm.get("name") or f"vm-{vmid}"
        vm_id  = f"{cell_id}:vm:{vmid}"
        vm_ids[vname] = vm_id
        nodes.append(FailureDomainNode(
            node_id=vm_id, level=LEVEL_VM,
            label=f"VM: {vname} ({vmid})", cell_id=cell_id,
            redundancy=1,
            depends_on=[host_id, pool_id] + (bridge_ids[:1] if bridge_ids else []),
        ))

    # Services from service contracts
    for sc_ in (manifest.get("service_contracts") or []):
        svc_name = sc_.get("service") or sc_.get("service_name") or "?"
        vm_name  = sc_.get("vm_name") or "?"
        svc_id   = f"{cell_id}:service:{svc_name}"
        vm_dep   = [vm_ids[vm_name]] if vm_name in vm_ids else []
        req_if   = sc_.get("required_interfaces") or []
        for ri in req_if:
            dep_svc = ri.get("service")
            if dep_svc:
                dep_id = f"{cell_id}:service:{dep_svc}"
                if dep_id not in vm_dep:
                    vm_dep.append(dep_id)
        nodes.append(FailureDomainNode(
            node_id=svc_id, level=LEVEL_SERVICE,
            label=f"Service: {svc_name}", cell_id=cell_id,
            redundancy=1,
            depends_on=vm_dep,
        ))

    # k3s nodes (from cluster config)
    k3s = manifest.get("k3s_cluster") or {}
    for server in (k3s.get("server_nodes") or []):
        s_name = server.get("hostname") or "k3s-server"
        k_id   = f"{cell_id}:k3s:{s_name}"
        vm_dep = [vm_ids[s_name]] if s_name in vm_ids else [host_id]
        nodes.append(FailureDomainNode(
            node_id=k_id, level=LEVEL_K3S,
            label=f"k3s server: {s_name}", cell_id=cell_id,
            redundancy=len(k3s.get("server_nodes") or []),
            depends_on=vm_dep,
        ))

    return nodes


# ---------------------------------------------------------------------------
# Failure domain report (21.6)
# ---------------------------------------------------------------------------

@dataclass
class FailureDomainReport:
    cell_id:       str
    total_nodes:   int
    spofs:         list[SpofFinding]
    circular_deps: list[CircularDependencyFinding]
    score:         str    # GREEN/YELLOW/ORANGE/RED
    reason:        str

    def to_findings(self) -> list[dict]:
        findings = []
        for s in self.spofs:
            findings.append({
                "severity": "YELLOW",
                "category": "spof",
                "node_id":  s.node_id,
                "message":  f"SPOF: {s.label} ({s.level}) — {s.reason}",
            })
        for c in self.circular_deps:
            findings.append({
                "severity": "ORANGE",
                "category": "circular_dependency",
                "cycle":    c.cycle,
                "message":  f"Circular dependency: {' → '.join(c.labels)}",
            })
        return findings


def analyze_failure_domain(manifest: dict, cell_id: str | None = None) -> FailureDomainReport:
    """
    Build failure domain graph from manifest and run full analysis.

    Returns a FailureDomainReport suitable for embedding in readiness reports.
    """
    cid   = cell_id or manifest.get("cell_id") or "unknown"
    nodes = build_failure_domain_graph(manifest)
    spofs = detect_spofs(nodes)
    circ  = detect_circular_deps(nodes)

    if circ:
        score  = "ORANGE"
        reason = f"{len(circ)} circular recovery dependency/ies detected."
    elif spofs:
        score  = "YELLOW"
        reason = f"{len(spofs)} single point(s) of failure identified."
    else:
        score  = "GREEN"
        reason = "No SPOFs or circular dependencies detected."

    return FailureDomainReport(
        cell_id=cid,
        total_nodes=len(nodes),
        spofs=spofs,
        circular_deps=circ,
        score=score,
        reason=reason,
    )
