#!/usr/bin/env python3
"""
storage_manager.py — Persistent Storage (Longhorn) Management (Phase 2.E).

Manages Longhorn distributed block storage for broodforge's Kubernetes cluster:
  - Longhorn Helm values.yaml generation
  - Node disk configuration registry (which disks/paths are exposed per node)
  - Volume registry (PVC name → Longhorn volume → replica count / health)
  - StorageClass generation (default + bulk storage classes)
  - Backup target configuration (NFS / S3-compatible via existing restic backend)
  - Replica and data locality policy per storage class

PAP constraints:
  - No bare datetime.now() — now_fn injected throughout
  - All subprocess calls: timeout=_SUBPROCESS_TIMEOUT
  - No credentials in env, argv, or logs
  - KeePass gate at shell layer; this module never opens a kdbx

State file: {STATE_DIR}/storage-state.json

CLI:
  python3 storage_manager.py generate-values [--output <f>]
      [--default-replica-count <n>] [--storage-class <sc>]
  python3 storage_manager.py generate-storage-class --name <n>
      [--replica-count <n>] [--reclaim-policy <Delete|Retain>]
      [--data-locality <disabled|best-effort|strict-local>]
      [--output <f>]
  python3 storage_manager.py register-node-disk --node <hostname>
      --path <path> [--disk-type <filesystem|block>] [--tags <t,...>]
      [--allow-scheduling] [--storage-reserved <Mi>]
  python3 storage_manager.py list-disks [--node <hostname>] [--json]
  python3 storage_manager.py register-volume --name <n> --namespace <ns>
      [--replica-count <n>] [--size <Gi>] [--storage-class <sc>]
  python3 storage_manager.py list-volumes [--namespace <ns>] [--json]
  python3 storage_manager.py mark-deployed [--version <v>]
  python3 storage_manager.py status [--json]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

_SUBPROCESS_TIMEOUT = 300

STATE_FILENAME = "storage-state.json"
DEFAULT_STATE_DIR = os.environ.get("BROODFORGE_STATE_DIR", "/var/lib/broodforge")
DEFAULT_NAMESPACE = "longhorn-system"
DEFAULT_RELEASE = "longhorn"
DEFAULT_CHART = "longhorn/longhorn"
DEFAULT_VERSION = "1.6.2"
DEFAULT_REPLICA_COUNT = 2
DEFAULT_STORAGE_RESERVED_MB = 2048  # 2 GiB reserved on each disk for OS

VALID_DISK_TYPES = ("filesystem", "block")
VALID_RECLAIM_POLICIES = ("Delete", "Retain")
VALID_DATA_LOCALITY = ("disabled", "best-effort", "strict-local")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class NodeDisk:
    """A disk/path registered with Longhorn on a specific node."""
    node: str
    path: str                  # e.g. /var/lib/longhorn or /dev/sdb
    disk_type: str             # filesystem | block
    tags: List[str]            # e.g. ["fast", "ssd"]
    allow_scheduling: bool
    storage_reserved_mb: int
    registered_at: str
    last_updated_at: str

    @classmethod
    def new(
        cls,
        node: str,
        path: str,
        disk_type: str = "filesystem",
        tags: Optional[List[str]] = None,
        allow_scheduling: bool = True,
        storage_reserved_mb: int = DEFAULT_STORAGE_RESERVED_MB,
        now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> "NodeDisk":
        ts = now_fn().isoformat()
        return cls(
            node=node,
            path=path,
            disk_type=disk_type,
            tags=tags or [],
            allow_scheduling=allow_scheduling,
            storage_reserved_mb=storage_reserved_mb,
            registered_at=ts,
            last_updated_at=ts,
        )


@dataclass
class VolumeRecord:
    """A tracked Longhorn-backed PVC / volume."""
    name: str               # PVC name
    namespace: str
    replica_count: int
    size_gi: int            # requested size in GiB
    storage_class: str
    registered_at: str
    last_updated_at: str
    healthy: Optional[bool] = None  # None = unknown; True/False from kubectl check

    @classmethod
    def new(
        cls,
        name: str,
        namespace: str,
        replica_count: int = DEFAULT_REPLICA_COUNT,
        size_gi: int = 10,
        storage_class: str = "longhorn",
        now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> "VolumeRecord":
        ts = now_fn().isoformat()
        return cls(
            name=name,
            namespace=namespace,
            replica_count=replica_count,
            size_gi=size_gi,
            storage_class=storage_class,
            registered_at=ts,
            last_updated_at=ts,
        )


@dataclass
class StorageState:
    schema_version: str = "1.0"
    release: str = DEFAULT_RELEASE
    helm_namespace: str = DEFAULT_NAMESPACE
    chart_version: str = DEFAULT_VERSION
    deployed_at: Optional[str] = None
    default_replica_count: int = DEFAULT_REPLICA_COUNT
    default_storage_class: str = "longhorn"
    backup_target: str = ""         # e.g. s3://bucket@us-east-1/path or nfs://host/path
    backup_target_type: str = ""    # s3 | nfs | ""
    node_disks: List[NodeDisk] = field(default_factory=list)
    volumes: List[VolumeRecord] = field(default_factory=list)

    def find_disk(self, node: str, path: str) -> Optional[NodeDisk]:
        for d in self.node_disks:
            if d.node == node and d.path == path:
                return d
        return None

    def find_volume(self, name: str, namespace: str) -> Optional[VolumeRecord]:
        for v in self.volumes:
            if v.name == name and v.namespace == namespace:
                return v
        return None


# ---------------------------------------------------------------------------
# State I/O
# ---------------------------------------------------------------------------

def _state_path(state_dir: str) -> Path:
    return Path(state_dir) / STATE_FILENAME


def load_state(state_dir: str) -> StorageState:
    p = _state_path(state_dir)
    if not p.exists():
        return StorageState()
    with open(p) as fh:
        raw = json.load(fh)
    node_disks = [NodeDisk(**d) for d in raw.get("node_disks", [])]
    volumes = [VolumeRecord(**v) for v in raw.get("volumes", [])]
    return StorageState(
        schema_version=raw.get("schema_version", "1.0"),
        release=raw.get("release", DEFAULT_RELEASE),
        helm_namespace=raw.get("helm_namespace", DEFAULT_NAMESPACE),
        chart_version=raw.get("chart_version", DEFAULT_VERSION),
        deployed_at=raw.get("deployed_at"),
        default_replica_count=raw.get("default_replica_count", DEFAULT_REPLICA_COUNT),
        default_storage_class=raw.get("default_storage_class", "longhorn"),
        backup_target=raw.get("backup_target", ""),
        backup_target_type=raw.get("backup_target_type", ""),
        node_disks=node_disks,
        volumes=volumes,
    )


def save_state(state: StorageState, state_dir: str) -> None:
    p = _state_path(state_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w") as fh:
        json.dump({
            "schema_version": state.schema_version,
            "release": state.release,
            "helm_namespace": state.helm_namespace,
            "chart_version": state.chart_version,
            "deployed_at": state.deployed_at,
            "default_replica_count": state.default_replica_count,
            "default_storage_class": state.default_storage_class,
            "backup_target": state.backup_target,
            "backup_target_type": state.backup_target_type,
            "node_disks": [asdict(d) for d in state.node_disks],
            "volumes": [asdict(v) for v in state.volumes],
        }, fh, indent=2)
    tmp.replace(p)


# ---------------------------------------------------------------------------
# Helm values generation
# ---------------------------------------------------------------------------

def generate_longhorn_values_yaml(
    namespace: str = DEFAULT_NAMESPACE,
    default_replica_count: int = DEFAULT_REPLICA_COUNT,
    default_storage_class: str = "longhorn",
    backup_target: str = "",
    backup_target_credential_secret: str = "",
    storage_over_provisioning_pct: int = 200,
    storage_minimal_available_pct: int = 25,
) -> str:
    """Generate Longhorn Helm values.yaml for broodforge deployment."""
    lines = [
        "# Longhorn Helm values — generated by broodforge storage_manager.py",
        "# Longhorn distributed block storage for Kubernetes",
        "",
        "defaultSettings:",
        f"  defaultReplicaCount: {default_replica_count}",
        f"  storageOverProvisioningPercentage: {storage_over_provisioning_pct}",
        f"  storageMinimalAvailablePercentage: {storage_minimal_available_pct}",
        "  autoSalvage: true",
        "  autoDeletePodWhenVolumeDetachedUnexpectedly: true",
        "  nodeDownPodDeletionPolicy: delete-both-statefulset-and-deployment-pod",
        "  guaranteedInstanceManagerCPU: 12",
        "  replicaAutoBalance: best-effort",
    ]
    if backup_target:
        lines += [
            f"  backupTarget: {backup_target}",
        ]
        if backup_target_credential_secret:
            lines += [
                f"  backupTargetCredentialSecret: {backup_target_credential_secret}",
            ]
    lines += [
        "",
        "persistence:",
        f"  defaultClass: true",
        f"  defaultClassReplicaCount: {default_replica_count}",
        f"  defaultDataLocality: best-effort",
        f"  reclaimPolicy: Delete",
        "",
        "ingress:",
        "  enabled: false",
        "  # To expose the Longhorn UI, configure ingress after deployment.",
        "  # The UI is sensitive — keep it internal to the cluster.",
        "",
        "service:",
        "  ui:",
        "    type: ClusterIP",
        "  manager:",
        "    type: ClusterIP",
        "",
        "longhornManager:",
        "  tolerations: []",
        "  priorityClass:",
        "    name: ''",
        "",
        "longhornDriver:",
        "  tolerations: []",
        "",
        "longhornUI:",
        "  replicas: 1",
        "  tolerations: []",
        "",
        "resources:",
        "  limits:",
        "    cpu: 300m",
        "    memory: 300Mi",
        "  requests:",
        "    cpu: 50m",
        "    memory: 100Mi",
    ]
    return "\n".join(lines) + "\n"


def generate_storage_class_yaml(
    name: str = "longhorn",
    replica_count: int = DEFAULT_REPLICA_COUNT,
    reclaim_policy: str = "Delete",
    data_locality: str = "best-effort",
    is_default: bool = True,
    fs_type: str = "ext4",
) -> str:
    """Generate a Kubernetes StorageClass manifest for Longhorn."""
    default_annotation = (
        '"storageclass.kubernetes.io/is-default-class": "true"'
        if is_default
        else '"storageclass.kubernetes.io/is-default-class": "false"'
    )
    return (
        "# StorageClass generated by broodforge storage_manager.py\n"
        "kind: StorageClass\n"
        "apiVersion: storage.k8s.io/v1\n"
        "metadata:\n"
        f"  name: {name}\n"
        "  annotations:\n"
        f"    {default_annotation}\n"
        "provisioner: driver.longhorn.io\n"
        f"allowVolumeExpansion: true\n"
        f"reclaimPolicy: {reclaim_policy}\n"
        "volumeBindingMode: Immediate\n"
        "parameters:\n"
        f'  numberOfReplicas: "{replica_count}"\n'
        f'  dataLocality: "{data_locality}"\n'
        f'  fsType: "{fs_type}"\n'
        '  staleReplicaTimeout: "2880"\n'
        '  fromBackup: ""\n'
    )


# ---------------------------------------------------------------------------
# StorageManager
# ---------------------------------------------------------------------------

class StorageError(Exception):
    pass


class StorageManager:

    def __init__(
        self,
        state_dir: str = DEFAULT_STATE_DIR,
        now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.state_dir = state_dir
        self.now_fn = now_fn
        self._state: Optional[StorageState] = None

    @property
    def state(self) -> StorageState:
        if self._state is None:
            self._state = load_state(self.state_dir)
        return self._state

    def _save(self) -> None:
        save_state(self.state, self.state_dir)

    def mark_deployed(
        self,
        version: str = DEFAULT_VERSION,
        default_replica_count: int = DEFAULT_REPLICA_COUNT,
        default_storage_class: str = "longhorn",
    ) -> None:
        self.state.deployed_at = self.now_fn().isoformat()
        self.state.chart_version = version
        self.state.default_replica_count = default_replica_count
        self.state.default_storage_class = default_storage_class
        self._save()

    def set_backup_target(
        self,
        backup_target: str,
        backup_target_type: str,
    ) -> None:
        if backup_target_type not in ("s3", "nfs", ""):
            raise StorageError(f"Unknown backup target type: {backup_target_type!r}")
        self.state.backup_target = backup_target
        self.state.backup_target_type = backup_target_type
        self._save()

    def register_node_disk(
        self,
        node: str,
        path: str,
        disk_type: str = "filesystem",
        tags: Optional[List[str]] = None,
        allow_scheduling: bool = True,
        storage_reserved_mb: int = DEFAULT_STORAGE_RESERVED_MB,
    ) -> NodeDisk:
        if disk_type not in VALID_DISK_TYPES:
            raise StorageError(f"Invalid disk_type {disk_type!r}. Use: {VALID_DISK_TYPES}")
        existing = self.state.find_disk(node, path)
        if existing:
            existing.disk_type = disk_type
            existing.tags = tags or existing.tags
            existing.allow_scheduling = allow_scheduling
            existing.storage_reserved_mb = storage_reserved_mb
            existing.last_updated_at = self.now_fn().isoformat()
            self._save()
            return existing
        disk = NodeDisk.new(
            node=node, path=path, disk_type=disk_type,
            tags=tags, allow_scheduling=allow_scheduling,
            storage_reserved_mb=storage_reserved_mb,
            now_fn=self.now_fn,
        )
        self.state.node_disks.append(disk)
        self._save()
        return disk

    def list_disks(self, node_filter: Optional[str] = None) -> List[NodeDisk]:
        disks = list(self.state.node_disks)
        if node_filter:
            disks = [d for d in disks if d.node == node_filter]
        return disks

    def register_volume(
        self,
        name: str,
        namespace: str,
        replica_count: int = DEFAULT_REPLICA_COUNT,
        size_gi: int = 10,
        storage_class: str = "longhorn",
    ) -> VolumeRecord:
        existing = self.state.find_volume(name, namespace)
        if existing:
            existing.replica_count = replica_count
            existing.size_gi = size_gi
            existing.storage_class = storage_class
            existing.last_updated_at = self.now_fn().isoformat()
            self._save()
            return existing
        vol = VolumeRecord.new(
            name=name, namespace=namespace, replica_count=replica_count,
            size_gi=size_gi, storage_class=storage_class, now_fn=self.now_fn,
        )
        self.state.volumes.append(vol)
        self._save()
        return vol

    def list_volumes(self, namespace_filter: Optional[str] = None) -> List[VolumeRecord]:
        vols = list(self.state.volumes)
        if namespace_filter:
            vols = [v for v in vols if v.namespace == namespace_filter]
        return vols

    def check_longhorn_health(self) -> dict:
        """
        Run kubectl get nodes.longhorn.io to check node readiness.
        Returns {"healthy": bool, "output": str, "error": str}.
        Requires kubectl in PATH and a valid kubeconfig.
        """
        try:
            result = subprocess.run(
                ["kubectl", "get", "nodes.longhorn.io",
                 "-n", self.state.helm_namespace, "--no-headers"],
                capture_output=True, text=True,
                timeout=_SUBPROCESS_TIMEOUT,
            )
            if result.returncode == 0:
                return {"healthy": True, "output": result.stdout.strip(), "error": ""}
            return {"healthy": False, "output": "", "error": result.stderr.strip()}
        except FileNotFoundError:
            return {"healthy": False, "output": "", "error": "kubectl not found"}
        except subprocess.TimeoutExpired:
            return {"healthy": False, "output": "", "error": "kubectl timed out"}

    def summary(self) -> dict:
        return {
            "deployed": self.state.deployed_at is not None,
            "version": self.state.chart_version,
            "default_replica_count": self.state.default_replica_count,
            "default_storage_class": self.state.default_storage_class,
            "backup_target": self.state.backup_target,
            "backup_target_type": self.state.backup_target_type,
            "node_disk_count": len(self.state.node_disks),
            "volume_count": len(self.state.volumes),
            "nodes": sorted({d.node for d in self.state.node_disks}),
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="storage_manager.py — Persistent Storage (Longhorn) (Phase 2.E)"
    )
    parser.add_argument("--state", default=DEFAULT_STATE_DIR)
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("generate-values")
    p.add_argument("--output", default="-")
    p.add_argument("--default-replica-count", type=int, default=DEFAULT_REPLICA_COUNT)
    p.add_argument("--storage-class", default="longhorn")
    p.add_argument("--backup-target", default="")
    p.add_argument("--backup-target-credential-secret", default="")

    p = sub.add_parser("generate-storage-class")
    p.add_argument("--name", required=True)
    p.add_argument("--replica-count", type=int, default=DEFAULT_REPLICA_COUNT)
    p.add_argument("--reclaim-policy", default="Delete",
                   choices=list(VALID_RECLAIM_POLICIES))
    p.add_argument("--data-locality", default="best-effort",
                   choices=list(VALID_DATA_LOCALITY))
    p.add_argument("--output", default="-")
    p.add_argument("--not-default", action="store_true")

    p = sub.add_parser("register-node-disk")
    p.add_argument("--node", required=True)
    p.add_argument("--path", required=True)
    p.add_argument("--disk-type", default="filesystem",
                   choices=list(VALID_DISK_TYPES))
    p.add_argument("--tags", default="")
    p.add_argument("--allow-scheduling", action="store_true", default=True)
    p.add_argument("--no-scheduling", dest="allow_scheduling", action="store_false")
    p.add_argument("--storage-reserved", type=int,
                   default=DEFAULT_STORAGE_RESERVED_MB,
                   metavar="MB")

    p = sub.add_parser("list-disks")
    p.add_argument("--node", default="")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("register-volume")
    p.add_argument("--name", required=True)
    p.add_argument("--namespace", required=True)
    p.add_argument("--replica-count", type=int, default=DEFAULT_REPLICA_COUNT)
    p.add_argument("--size", type=int, default=10, metavar="GI")
    p.add_argument("--storage-class", default="longhorn")

    p = sub.add_parser("list-volumes")
    p.add_argument("--namespace", default="")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("set-backup-target")
    p.add_argument("--target", required=True)
    p.add_argument("--type", required=True, choices=["s3", "nfs"],
                   dest="target_type")

    p = sub.add_parser("mark-deployed")
    p.add_argument("--version", default=DEFAULT_VERSION)
    p.add_argument("--default-replica-count", type=int, default=DEFAULT_REPLICA_COUNT)
    p.add_argument("--storage-class", default="longhorn")

    p = sub.add_parser("health")

    p = sub.add_parser("status")
    p.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    def _write_out(text: str, path: str) -> None:
        if path == "-":
            print(text, end="")
        else:
            p2 = Path(path)
            tmp = p2.with_suffix(".tmp")
            tmp.write_text(text)
            tmp.replace(p2)

    if args.cmd == "generate-values":
        _write_out(generate_longhorn_values_yaml(
            default_replica_count=args.default_replica_count,
            default_storage_class=args.storage_class,
            backup_target=args.backup_target,
            backup_target_credential_secret=args.backup_target_credential_secret,
        ), args.output)
        return 0

    if args.cmd == "generate-storage-class":
        _write_out(generate_storage_class_yaml(
            name=args.name,
            replica_count=args.replica_count,
            reclaim_policy=args.reclaim_policy,
            data_locality=args.data_locality,
            is_default=not args.not_default,
        ), args.output)
        return 0

    if args.cmd == "register-node-disk":
        mgr = StorageManager(state_dir=args.state)
        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        try:
            disk = mgr.register_node_disk(
                node=args.node, path=args.path, disk_type=args.disk_type,
                tags=tags, allow_scheduling=args.allow_scheduling,
                storage_reserved_mb=args.storage_reserved,
            )
            print(f"Registered disk: {disk.node}:{disk.path} ({disk.disk_type})")
            return 0
        except StorageError as exc:
            print(f"Error: {exc}", file=sys.stderr); return 1

    if args.cmd == "list-disks":
        mgr = StorageManager(state_dir=args.state)
        disks = mgr.list_disks(node_filter=args.node or None)
        if args.json:
            print(json.dumps([asdict(d) for d in disks], indent=2)); return 0
        if not disks:
            print("No disks registered."); return 0
        print(f"{'NODE':<20} {'PATH':<30} {'TYPE':<12} {'SCHED':<7} TAGS")
        for d in disks:
            print(f"{d.node:<20} {d.path:<30} {d.disk_type:<12} "
                  f"{'yes' if d.allow_scheduling else 'no':<7} "
                  f"{','.join(d.tags) or '-'}")
        return 0

    if args.cmd == "register-volume":
        mgr = StorageManager(state_dir=args.state)
        vol = mgr.register_volume(
            name=args.name, namespace=args.namespace,
            replica_count=args.replica_count,
            size_gi=args.size,
            storage_class=args.storage_class,
        )
        print(f"Registered volume: {vol.namespace}/{vol.name} "
              f"({vol.size_gi}Gi x{vol.replica_count})")
        return 0

    if args.cmd == "list-volumes":
        mgr = StorageManager(state_dir=args.state)
        vols = mgr.list_volumes(namespace_filter=args.namespace or None)
        if args.json:
            print(json.dumps([asdict(v) for v in vols], indent=2)); return 0
        if not vols:
            print("No volumes registered."); return 0
        print(f"{'NAMESPACE':<20} {'NAME':<30} {'SIZE':<8} {'REPLICAS':<10} SC")
        for v in vols:
            print(f"{v.namespace:<20} {v.name:<30} {v.size_gi}Gi    "
                  f"{v.replica_count:<10} {v.storage_class}")
        return 0

    if args.cmd == "set-backup-target":
        mgr = StorageManager(state_dir=args.state)
        try:
            mgr.set_backup_target(args.target, args.target_type)
            print(f"Backup target set: {args.target} ({args.target_type})")
            return 0
        except StorageError as exc:
            print(f"Error: {exc}", file=sys.stderr); return 1

    if args.cmd == "mark-deployed":
        mgr = StorageManager(state_dir=args.state)
        mgr.mark_deployed(
            version=args.version,
            default_replica_count=args.default_replica_count,
            default_storage_class=args.storage_class,
        )
        print(f"Recorded: longhorn={args.version}")
        return 0

    if args.cmd == "health":
        mgr = StorageManager(state_dir=args.state)
        result = mgr.check_longhorn_health()
        if result["healthy"]:
            print("Longhorn nodes: healthy")
            if result["output"]:
                print(result["output"])
            return 0
        print(f"Longhorn health check failed: {result['error']}", file=sys.stderr)
        return 1

    if args.cmd == "status":
        mgr = StorageManager(state_dir=args.state)
        s = mgr.summary()
        if args.json:
            print(json.dumps(s, indent=2)); return 0
        print(f"deployed:          {s['deployed']}")
        print(f"version:           {s['version']}")
        print(f"default replicas:  {s['default_replica_count']}")
        print(f"default sc:        {s['default_storage_class']}")
        print(f"backup target:     {s['backup_target'] or '(none)'}")
        print(f"node disks:        {s['node_disk_count']}")
        print(f"volumes tracked:   {s['volume_count']}")
        print(f"nodes:             {', '.join(s['nodes']) or '(none)'}")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
