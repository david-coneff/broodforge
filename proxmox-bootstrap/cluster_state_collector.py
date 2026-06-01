#!/usr/bin/env python3
"""
cluster_state_collector.py — Cluster State collector (Phase 14.2).

Collects Proxmox cluster state (Corosync quorum, HA manager) and k3s cluster
state (node readiness, Flux CD reconciliation) from a Proxmox host.

Produces a cluster-state.json conforming to data-model/cluster-state-schema.json.

Provides:
  ProxmoxNode, K3sNode, HaResource   — typed entries
  ClusterStateDocument                — typed result
  collect_cluster_state()             — main collection entry point
  compute_cluster_health()            — aggregate health
  cluster_state_to_dict()            — JSON-serialisable dict

Stdlib only.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ProxmoxNode:
    name:         str
    id:           Optional[int]   = None
    ip:           Optional[str]   = None
    online:       Optional[bool]  = None
    role:         Optional[str]   = None
    cpu_usage:    Optional[float] = None
    mem_usage:    Optional[float] = None
    uptime_sec:   Optional[int]   = None
    pve_version:  Optional[str]   = None


@dataclass
class K3sNode:
    name:          str
    status:        Optional[str]   = None
    roles:         list[str]       = field(default_factory=list)
    version:       Optional[str]   = None
    internal_ip:   Optional[str]   = None
    os_image:      Optional[str]   = None
    kernel_version: Optional[str]  = None
    age_seconds:   Optional[int]   = None
    taint_no_schedule: Optional[bool] = None


@dataclass
class HaResource:
    sid:    str
    state:  Optional[str] = None
    node:   Optional[str] = None
    group:  Optional[str] = None


@dataclass
class ClusterStateDocument:
    cell_id:         str
    collected_at:    str
    # Proxmox cluster
    cluster_name:    Optional[str]         = None
    quorum_votes:    Optional[int]         = None
    quorum_ok:       Optional[bool]        = None
    proxmox_nodes:   list[ProxmoxNode]     = field(default_factory=list)
    ha_resources:    list[HaResource]      = field(default_factory=list)
    ha_enabled:      Optional[bool]        = None
    corosync_ring_ok: Optional[bool]       = None
    # k3s cluster
    k3s_version:     Optional[str]         = None
    k3s_server_url:  Optional[str]         = None
    k3s_is_ha:       Optional[bool]        = None
    k3s_nodes:       list[K3sNode]         = field(default_factory=list)
    flux_reconciled: Optional[bool]        = None
    etcd_healthy:    Optional[bool]        = None
    collection_errors: list[dict]          = field(default_factory=list)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

RunnerFn = Callable[[str], str]


def _local_runner(cmd: str) -> str:
    import subprocess
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
    return result.stdout


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _parse_pvecm_status(output: str) -> dict:
    """Parse 'pvecm status' text output."""
    result: dict = {}
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("Name:"):
            result["name"] = stripped.split(":", 1)[1].strip()
        elif "Quorum OK" in stripped and "not" not in stripped.lower():
            result["quorum_ok"] = True
        elif "Quorum not OK" in stripped or ("not OK" in stripped and "Quorum" in stripped):
            result["quorum_ok"] = False
        elif stripped.startswith("Votes:"):
            try:
                result["votes"] = int(stripped.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif "Ring Status" in stripped:
            result["ring_ok"] = "ok" in stripped.lower()
    return result


def _parse_pvecm_nodes(output: str) -> list[ProxmoxNode]:
    """Parse 'pvecm nodes' text output.
    Format: Nodeid  Votes  Name  (columns separated by whitespace)
    """
    nodes = []
    for line in output.splitlines():
        parts = line.split()
        # Line must have at least 3 columns and first must be a numeric node ID
        if len(parts) >= 3 and parts[0].isdigit():
            node_id   = int(parts[0])
            node_name = parts[2]  # column index 2 is the node name
            nodes.append(ProxmoxNode(name=node_name, id=node_id))
    return nodes


def _parse_kubectl_nodes_json(output: str) -> list[K3sNode]:
    """Parse 'kubectl get nodes -o json' output."""
    nodes = []
    try:
        data = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return nodes

    for item in (data.get("items") or []):
        meta    = item.get("metadata") or {}
        status  = item.get("status") or {}
        spec    = item.get("spec") or {}
        labels  = meta.get("labels") or {}

        name = meta.get("name") or "unknown"

        # Determine roles from labels
        roles = [
            lk.split("/")[-1]
            for lk in labels
            if lk.startswith("node-role.kubernetes.io/")
        ]

        # Status conditions
        conditions = status.get("conditions") or []
        ready_cond = next(
            (c for c in conditions if c.get("type") == "Ready"),
            None
        )
        ready = ready_cond.get("status") == "True" if ready_cond else None

        # Node info
        node_info = status.get("nodeInfo") or {}
        addresses = status.get("addresses") or []
        internal_ip = next(
            (a["address"] for a in addresses if a.get("type") == "InternalIP"),
            None
        )

        # Taint no-schedule
        taints = spec.get("taints") or []
        no_sched = any(t.get("effect") == "NoSchedule" for t in taints)

        nodes.append(K3sNode(
            name=name,
            status="Ready" if ready else ("NotReady" if ready is not None else None),
            roles=roles,
            version=node_info.get("kubeletVersion"),
            internal_ip=internal_ip,
            os_image=node_info.get("osImage"),
            kernel_version=node_info.get("kernelVersion"),
            taint_no_schedule=no_sched if taints else None,
        ))
    return nodes


def _int(v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Cluster health
# ---------------------------------------------------------------------------

def compute_cluster_health(doc: ClusterStateDocument) -> dict:
    """Derive cluster_health dict from ClusterStateDocument."""
    issues = []

    # Proxmox quorum
    quorum_ok = doc.quorum_ok
    if quorum_ok is False:
        issues.append("Proxmox cluster quorum not OK")

    # Proxmox nodes
    offline_nodes = [n.name for n in doc.proxmox_nodes if n.online is False]
    all_proxmox_up = not offline_nodes
    if offline_nodes:
        issues.append(f"Proxmox nodes offline: {', '.join(offline_nodes)}")

    # k3s nodes
    not_ready = [n.name for n in doc.k3s_nodes if n.status == "NotReady"]
    all_k3s_ready = not not_ready
    if not_ready:
        issues.append(f"k3s nodes not ready: {', '.join(not_ready)}")

    # HA resources
    failed_ha = [r.sid for r in doc.ha_resources if r.state in ("error", "fence")]
    ha_ok = not failed_ha
    if failed_ha:
        issues.append(f"HA resources failed: {', '.join(failed_ha)}")

    # Overall
    if quorum_ok is False or not_ready or failed_ha:
        overall = "CRITICAL"
    elif offline_nodes or (not all_k3s_ready and doc.k3s_nodes):
        overall = "DEGRADED"
    elif not doc.proxmox_nodes and not doc.k3s_nodes:
        overall = "UNKNOWN"
    else:
        overall = "HEALTHY"

    return {
        "overall_status":          overall,
        "quorum_ok":               quorum_ok,
        "all_proxmox_nodes_up":    all_proxmox_up,
        "all_k3s_nodes_ready":     all_k3s_ready,
        "ha_resources_healthy":    ha_ok,
        "issues":                  issues,
    }


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------

def collect_cluster_state(
    cell_id:   str,
    runner_fn: Optional[RunnerFn] = None,
    now_fn:    Optional[Callable[[], str]] = None,
) -> ClusterStateDocument:
    """
    Collect cluster state from the local Proxmox host.
    """
    runner = runner_fn or _local_runner
    now    = (now_fn or (lambda: datetime.now(timezone.utc).isoformat()))()

    doc = ClusterStateDocument(cell_id=cell_id, collected_at=now)
    errors = []

    # Proxmox cluster quorum
    try:
        out = runner("pvecm status 2>/dev/null || true")
        pvecm = _parse_pvecm_status(out)
        doc.cluster_name  = pvecm.get("name")
        doc.quorum_ok     = pvecm.get("quorum_ok")
        doc.quorum_votes  = pvecm.get("votes")
        doc.corosync_ring_ok = pvecm.get("ring_ok")
    except Exception as e:
        errors.append({"component": "pvecm_status", "error": str(e)})

    # Proxmox nodes
    try:
        out = runner("pvecm nodes 2>/dev/null || true")
        doc.proxmox_nodes = _parse_pvecm_nodes(out)
    except Exception as e:
        errors.append({"component": "pvecm_nodes", "error": str(e)})

    # k3s nodes
    try:
        kubeconfig = "/etc/rancher/k3s/k3s.yaml"
        out = runner(
            f"KUBECONFIG={kubeconfig} kubectl get nodes -o json 2>/dev/null || true"
        )
        if out.strip():
            doc.k3s_nodes = _parse_kubectl_nodes_json(out)
            doc.k3s_is_ha = any(
                "etcd" in (n.os_image or "").lower() or n.taint_no_schedule
                for n in doc.k3s_nodes
            )
    except Exception as e:
        errors.append({"component": "k3s_nodes", "error": str(e)})

    # k3s server version
    try:
        out = runner("k3s --version 2>/dev/null || true").strip()
        if out:
            parts = out.split()
            if len(parts) >= 2:
                doc.k3s_version = parts[1]
    except Exception as e:
        errors.append({"component": "k3s_version", "error": str(e)})

    # Flux CD reconciliation
    try:
        kubeconfig = "/etc/rancher/k3s/k3s.yaml"
        out = runner(
            f"KUBECONFIG={kubeconfig} flux get kustomizations 2>/dev/null || true"
        )
        if out.strip():
            # "Applied revision" in all lines = reconciled
            doc.flux_reconciled = "False" not in out and out.strip() != ""
    except Exception as e:
        errors.append({"component": "flux", "error": str(e)})

    doc.collection_errors = errors
    return doc


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def cluster_state_to_dict(doc: ClusterStateDocument) -> dict:
    """Convert ClusterStateDocument to a JSON-serialisable dict."""
    health = compute_cluster_health(doc)
    k3s_nodes = doc.k3s_nodes
    servers = sum(1 for n in k3s_nodes if "control-plane" in n.roles or "master" in n.roles)
    workers = sum(1 for n in k3s_nodes if not n.roles or "worker" in n.roles)
    return {
        "schema_version": "1.0",
        "cell_id":        doc.cell_id,
        "collected_at":   doc.collected_at,
        "collection_errors": doc.collection_errors,
        "proxmox_cluster": {
            "name":         doc.cluster_name,
            "quorum_ok":    doc.quorum_ok,
            "quorum_votes": doc.quorum_votes,
            "node_count":   len(doc.proxmox_nodes),
            "nodes": [
                {
                    "name":    n.name,
                    "id":      n.id,
                    "online":  n.online,
                    "role":    n.role,
                }
                for n in doc.proxmox_nodes
            ],
            "ha_enabled":   doc.ha_enabled,
            "ha_resources": [
                {"sid": r.sid, "state": r.state, "node": r.node}
                for r in doc.ha_resources
            ],
            "corosync_ring_status": "ok" if doc.corosync_ring_ok else ("degraded" if doc.corosync_ring_ok is False else None),
        },
        "k3s_cluster": {
            "version":         doc.k3s_version,
            "is_ha":           doc.k3s_is_ha,
            "node_count":      len(k3s_nodes),
            "server_count":    servers,
            "worker_count":    workers,
            "all_nodes_ready": all(n.status == "Ready" for n in k3s_nodes) if k3s_nodes else None,
            "flux_reconciled": doc.flux_reconciled,
            "etcd_healthy":    doc.etcd_healthy,
            "nodes": [
                {
                    "name":        n.name,
                    "status":      n.status,
                    "roles":       n.roles,
                    "version":     n.version,
                    "internal_ip": n.internal_ip,
                }
                for n in k3s_nodes
            ],
        },
        "cluster_health": health,
    }
