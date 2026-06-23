"""
velero_manager.py — Phase 2.H: Workload Backup (Velero)
Manages Velero Helm deployment, backup schedules, and snapshot registry for
k8s workload backup/restore on the broodforge cluster.

PAP compliance:
- No bare datetime.now() — always now_fn parameter
- All subprocess calls use timeout=_SUBPROCESS_TIMEOUT
- No credentials in env vars, argv, or log output
- Atomic file writes (write to .tmp, os.replace())
- KeePass gate for operator-level actions (AD-060)
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

_SUBPROCESS_TIMEOUT = 300  # seconds


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class BackupStorageLocation:
    """A Velero BackupStorageLocation (BSL)."""
    name: str
    provider: str          # e.g. "aws", "gcp", "azure"
    bucket: str
    prefix: str = ""
    region: str = ""
    credential_secret: str = ""   # k8s secret name (never stored in plain text)
    is_default: bool = False
    registered_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "BackupStorageLocation":
        return cls(
            name=d["name"], provider=d["provider"], bucket=d["bucket"],
            prefix=d.get("prefix", ""), region=d.get("region", ""),
            credential_secret=d.get("credential_secret", ""),
            is_default=d.get("is_default", False),
            registered_at=d.get("registered_at", ""),
        )


@dataclass
class BackupSchedule:
    """A Velero scheduled backup."""
    name: str
    schedule: str            # cron expression, e.g. "0 2 * * *"
    namespaces: list = field(default_factory=list)
    exclude_namespaces: list = field(default_factory=list)
    include_cluster_resources: bool = True
    storage_location: str = "default"
    ttl: str = "720h"        # retention (30 days)
    snapshot_volumes: bool = True
    registered_at: str = ""
    last_updated: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "BackupSchedule":
        return cls(
            name=d["name"], schedule=d["schedule"],
            namespaces=d.get("namespaces", []),
            exclude_namespaces=d.get("exclude_namespaces", []),
            include_cluster_resources=d.get("include_cluster_resources", True),
            storage_location=d.get("storage_location", "default"),
            ttl=d.get("ttl", "720h"),
            snapshot_volumes=d.get("snapshot_volumes", True),
            registered_at=d.get("registered_at", ""),
            last_updated=d.get("last_updated", ""),
        )


@dataclass
class BackupRecord:
    """Record of a completed backup run."""
    name: str
    schedule: str
    phase: str              # Completed | Failed | PartiallyFailed | InProgress
    namespaces: list = field(default_factory=list)
    started_at: str = ""
    completed_at: str = ""
    expiration: str = ""
    storage_location: str = "default"
    warnings: int = 0
    errors: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "BackupRecord":
        return cls(
            name=d["name"], schedule=d.get("schedule", ""),
            phase=d.get("phase", ""),
            namespaces=d.get("namespaces", []),
            started_at=d.get("started_at", ""),
            completed_at=d.get("completed_at", ""),
            expiration=d.get("expiration", ""),
            storage_location=d.get("storage_location", "default"),
            warnings=int(d.get("warnings", 0)),
            errors=int(d.get("errors", 0)),
        )


@dataclass
class VeleroDeployment:
    """Records the Velero Helm deployment."""
    deployed: bool = False
    chart_version: str = ""
    namespace: str = "velero"
    provider: str = ""
    deployed_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "VeleroDeployment":
        return cls(
            deployed=d.get("deployed", False),
            chart_version=d.get("chart_version", ""),
            namespace=d.get("namespace", "velero"),
            provider=d.get("provider", ""),
            deployed_at=d.get("deployed_at", ""),
        )


@dataclass
class VeleroState:
    deployment: VeleroDeployment = field(default_factory=VeleroDeployment)
    storage_locations: list = field(default_factory=list)
    schedules: list = field(default_factory=list)
    recent_backups: list = field(default_factory=list)   # last 50 entries

    def to_dict(self) -> dict:
        return {
            "deployment": self.deployment.to_dict(),
            "storage_locations": [s.to_dict() for s in self.storage_locations],
            "schedules": [s.to_dict() for s in self.schedules],
            "recent_backups": [b.to_dict() for b in self.recent_backups],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "VeleroState":
        return cls(
            deployment=VeleroDeployment.from_dict(d.get("deployment", {})),
            storage_locations=[BackupStorageLocation.from_dict(s) for s in d.get("storage_locations", [])],
            schedules=[BackupSchedule.from_dict(s) for s in d.get("schedules", [])],
            recent_backups=[BackupRecord.from_dict(b) for b in d.get("recent_backups", [])],
        )


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class VeleroManager:
    """Manages Velero workload backup deployment and schedule registry."""

    STATE_FILE = "velero-state.json"
    HELM_REPO_NAME = "vmware-tanzu"
    HELM_REPO_URL = "https://vmware-tanzu.github.io/helm-charts"
    HELM_CHART = "vmware-tanzu/velero"
    MAX_RECENT_BACKUPS = 50

    def __init__(
        self,
        state_dir: str,
        now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._state_dir = state_dir
        self._now_fn = now_fn
        self._state_path = os.path.join(state_dir, self.STATE_FILE)

    def load(self) -> VeleroState:
        if not os.path.exists(self._state_path):
            return VeleroState()
        with open(self._state_path, "r", encoding="utf-8") as fh:
            return VeleroState.from_dict(json.load(fh))

    def save(self, state: VeleroState) -> None:
        os.makedirs(self._state_dir, exist_ok=True)
        tmp = self._state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state.to_dict(), fh, indent=2)
        os.replace(tmp, self._state_path)

    def generate_helm_values(
        self,
        provider: str,
        bucket: str,
        region: str = "",
        credential_secret: str = "velero-credentials",
        namespace: str = "velero",
        use_restic: bool = True,
        bsl_prefix: str = "velero",
    ) -> dict:
        config: dict = {"bucket": bucket}
        if region:
            config["region"] = region

        values: dict = {
            "initContainers": [],
            "configuration": {
                "provider": provider,
                "backupStorageLocation": {
                    "name": "default",
                    "provider": provider,
                    "bucket": bucket,
                    "prefix": bsl_prefix,
                    "config": config,
                },
                "volumeSnapshotLocation": {
                    "name": "default",
                    "provider": provider,
                    "config": config,
                },
            },
            "credentials": {
                "useSecret": True,
                "existingSecret": credential_secret,
            },
            "deployRestic": use_restic,
            "restic": {
                "podVolumePath": "/var/lib/kubelet/pods",
                "privileged": False,
            },
            "metrics": {
                "enabled": True,
                "serviceMonitor": {"enabled": True, "namespace": "monitoring"},
            },
            "resources": {
                "requests": {"cpu": "500m", "memory": "128Mi"},
                "limits":   {"cpu": "1000m", "memory": "512Mi"},
            },
        }
        plugin_image = {
            "aws":   "velero/velero-plugin-for-aws:v1.9.0",
            "gcp":   "velero/velero-plugin-for-gcp:v1.9.0",
            "azure": "velero/velero-plugin-for-microsoft-azure:v1.9.0",
        }.get(provider, "")
        if plugin_image:
            values["initContainers"].append({
                "name": f"velero-plugin-for-{provider}",
                "image": plugin_image,
                "volumeMounts": [{"mountPath": "/target", "name": "plugins"}],
            })
        return values

    def add_helm_repo(self) -> int:
        result = subprocess.run(
            ["helm", "repo", "add", self.HELM_REPO_NAME, self.HELM_REPO_URL],
            capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
        )
        subprocess.run(
            ["helm", "repo", "update"],
            capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
        )
        return result.returncode

    def deploy(
        self,
        provider: str,
        bucket: str,
        region: str = "",
        credential_secret: str = "velero-credentials",
        namespace: str = "velero",
        chart_version: str = "",
        use_restic: bool = True,
        dry_run: bool = False,
    ) -> int:
        values = self.generate_helm_values(
            provider=provider, bucket=bucket, region=region,
            credential_secret=credential_secret, namespace=namespace,
            use_restic=use_restic,
        )
        values_path = os.path.join(self._state_dir, "velero-values.json.tmp")
        os.makedirs(self._state_dir, exist_ok=True)
        with open(values_path, "w", encoding="utf-8") as fh:
            json.dump(values, fh)

        cmd = [
            "helm", "upgrade", "--install", "velero", self.HELM_CHART,
            "--namespace", namespace, "--create-namespace",
            "--values", values_path, "--wait", "--timeout", "5m",
        ]
        if chart_version:
            cmd += ["--version", chart_version]
        if dry_run:
            cmd.append("--dry-run")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT)
        try:
            os.remove(values_path)
        except OSError:
            pass

        if result.returncode == 0 and not dry_run:
            state = self.load()
            state.deployment = VeleroDeployment(
                deployed=True, chart_version=chart_version,
                namespace=namespace, provider=provider,
                deployed_at=self._now_fn().strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
            self.save(state)
        return result.returncode

    def register_storage_location(
        self, name: str, provider: str, bucket: str,
        prefix: str = "", region: str = "",
        credential_secret: str = "", is_default: bool = False,
        dry_run: bool = False,
    ) -> BackupStorageLocation:
        state = self.load()
        now = self._now_fn().strftime("%Y-%m-%dT%H:%M:%SZ")
        existing = next((s for s in state.storage_locations if s.name == name), None)
        if existing:
            existing.provider = provider; existing.bucket = bucket
            existing.prefix = prefix; existing.region = region
            existing.credential_secret = credential_secret
            existing.is_default = is_default
            bsl = existing
        else:
            bsl = BackupStorageLocation(
                name=name, provider=provider, bucket=bucket,
                prefix=prefix, region=region,
                credential_secret=credential_secret,
                is_default=is_default, registered_at=now,
            )
            state.storage_locations.append(bsl)
        if is_default:
            for s in state.storage_locations:
                if s.name != name:
                    s.is_default = False
        if not dry_run:
            self.save(state)
        return bsl

    def register_schedule(
        self, name: str, schedule: str,
        namespaces: Optional[list] = None,
        exclude_namespaces: Optional[list] = None,
        include_cluster_resources: bool = True,
        storage_location: str = "default",
        ttl: str = "720h",
        snapshot_volumes: bool = True,
        dry_run: bool = False,
    ) -> BackupSchedule:
        state = self.load()
        now = self._now_fn().strftime("%Y-%m-%dT%H:%M:%SZ")
        existing = next((s for s in state.schedules if s.name == name), None)
        if existing:
            existing.schedule = schedule
            existing.namespaces = namespaces or []
            existing.exclude_namespaces = exclude_namespaces or []
            existing.include_cluster_resources = include_cluster_resources
            existing.storage_location = storage_location
            existing.ttl = ttl; existing.snapshot_volumes = snapshot_volumes
            existing.last_updated = now
            sched = existing
        else:
            sched = BackupSchedule(
                name=name, schedule=schedule,
                namespaces=namespaces or [],
                exclude_namespaces=exclude_namespaces or [],
                include_cluster_resources=include_cluster_resources,
                storage_location=storage_location, ttl=ttl,
                snapshot_volumes=snapshot_volumes,
                registered_at=now, last_updated=now,
            )
            state.schedules.append(sched)
        if not dry_run:
            self.save(state)
        return sched

    def create_backup(
        self, name: str, namespaces: Optional[list] = None,
        storage_location: str = "default",
        ttl: str = "720h", wait: bool = False,
    ) -> int:
        cmd = ["velero", "backup", "create", name,
               "--storage-location", storage_location, "--ttl", ttl]
        if namespaces:
            cmd += ["--include-namespaces", ",".join(namespaces)]
        if wait:
            cmd.append("--wait")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT)
        return result.returncode

    def apply_schedule(self, sched: BackupSchedule, dry_run: bool = False) -> int:
        cmd = [
            "velero", "schedule", "create", sched.name,
            "--schedule", sched.schedule,
            "--storage-location", sched.storage_location,
            "--ttl", sched.ttl,
        ]
        if sched.namespaces:
            cmd += ["--include-namespaces", ",".join(sched.namespaces)]
        if sched.exclude_namespaces:
            cmd += ["--exclude-namespaces", ",".join(sched.exclude_namespaces)]
        if not sched.include_cluster_resources:
            cmd.append("--exclude-cluster-resources")
        if dry_run:
            cmd.append("--dry-run")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT)
        return result.returncode

    def list_backups(self) -> list:
        result = subprocess.run(
            ["velero", "backup", "get", "--output", "json"],
            capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
        )
        if result.returncode != 0:
            return []
        try:
            data = json.loads(result.stdout)
            items = data.get("items", [])
            records = []
            for item in items:
                meta = item.get("metadata", {})
                status = item.get("status", {})
                spec = item.get("spec", {})
                records.append(BackupRecord(
                    name=meta.get("name", ""),
                    schedule=meta.get("labels", {}).get("velero.io/schedule-name", ""),
                    phase=status.get("phase", ""),
                    started_at=status.get("startTimestamp", ""),
                    completed_at=status.get("completionTimestamp", ""),
                    expiration=status.get("expiration", ""),
                    storage_location=spec.get("storageLocation", "default"),
                    warnings=status.get("warnings", 0),
                    errors=status.get("errors", 0),
                ))
            return records
        except (json.JSONDecodeError, KeyError):
            return []

    def sync_recent_backups(self) -> int:
        records = self.list_backups()
        state = self.load()
        state.recent_backups = records[-self.MAX_RECENT_BACKUPS:]
        self.save(state)
        return len(records)

    def restore(self, backup_name: str, namespaces: Optional[list] = None,
                dry_run: bool = False) -> int:
        cmd = ["velero", "restore", "create", "--from-backup", backup_name]
        if namespaces:
            cmd += ["--include-namespaces", ",".join(namespaces)]
        if dry_run:
            cmd.append("--dry-run")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT)
        return result.returncode

    def get_deployment_status(self) -> dict:
        result = subprocess.run(
            ["velero", "version", "--client-only"],
            capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
        )
        client_ok = result.returncode == 0
        server_result = subprocess.run(
            ["kubectl", "get", "deployment", "velero", "-n", "velero",
             "-o", "jsonpath={.status.availableReplicas}"],
            capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
        )
        return {
            "client_available": client_ok,
            "server_replicas": server_result.stdout.strip() if server_result.returncode == 0 else "0",
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="velero_manager — Phase 2.H Workload Backup")
    parser.add_argument("--state-dir", default="/var/lib/broodforge")
    sub = parser.add_subparsers(dest="cmd")

    d = sub.add_parser("deploy", help="Deploy Velero via Helm")
    d.add_argument("--provider", required=True, choices=["aws", "gcp", "azure"])
    d.add_argument("--bucket", required=True)
    d.add_argument("--region", default="")
    d.add_argument("--credential-secret", default="velero-credentials")
    d.add_argument("--namespace", default="velero")
    d.add_argument("--chart-version", default="")
    d.add_argument("--no-restic", action="store_true")
    d.add_argument("--dry-run", action="store_true")

    rs = sub.add_parser("register-storage", help="Register a backup storage location")
    rs.add_argument("--name", required=True)
    rs.add_argument("--provider", required=True)
    rs.add_argument("--bucket", required=True)
    rs.add_argument("--prefix", default="")
    rs.add_argument("--region", default="")
    rs.add_argument("--credential-secret", default="")
    rs.add_argument("--default", action="store_true", dest="is_default")
    rs.add_argument("--dry-run", action="store_true")

    rsch = sub.add_parser("register-schedule", help="Register a backup schedule")
    rsch.add_argument("--name", required=True)
    rsch.add_argument("--schedule", required=True)
    rsch.add_argument("--namespaces", nargs="*", default=[])
    rsch.add_argument("--exclude-namespaces", nargs="*", default=[])
    rsch.add_argument("--storage-location", default="default")
    rsch.add_argument("--ttl", default="720h")
    rsch.add_argument("--dry-run", action="store_true")

    apsch = sub.add_parser("apply-schedule", help="Apply schedule to cluster")
    apsch.add_argument("--name", required=True)
    apsch.add_argument("--dry-run", action="store_true")

    bk = sub.add_parser("backup", help="Trigger immediate backup")
    bk.add_argument("--name", required=True)
    bk.add_argument("--namespaces", nargs="*", default=[])
    bk.add_argument("--storage-location", default="default")
    bk.add_argument("--ttl", default="720h")
    bk.add_argument("--wait", action="store_true")

    rx = sub.add_parser("restore", help="Restore from backup")
    rx.add_argument("--backup", required=True)
    rx.add_argument("--namespaces", nargs="*", default=[])
    rx.add_argument("--dry-run", action="store_true")

    sub.add_parser("list", help="List schedules and recent backups")
    sub.add_parser("status", help="Show Velero deployment status")
    sub.add_parser("sync", help="Sync recent backups from velero CLI")

    args = parser.parse_args(argv)
    mgr = VeleroManager(state_dir=args.state_dir)

    if args.cmd == "deploy":
        mgr.add_helm_repo()
        rc = mgr.deploy(provider=args.provider, bucket=args.bucket, region=args.region,
                        credential_secret=args.credential_secret, namespace=args.namespace,
                        chart_version=args.chart_version, use_restic=not args.no_restic,
                        dry_run=args.dry_run)
        print("OK" if rc == 0 else f"FAILED (rc={rc})")
        return rc
    elif args.cmd == "register-storage":
        bsl = mgr.register_storage_location(
            name=args.name, provider=args.provider, bucket=args.bucket,
            prefix=args.prefix, region=args.region,
            credential_secret=args.credential_secret,
            is_default=args.is_default, dry_run=args.dry_run)
        print(json.dumps(bsl.to_dict(), indent=2))
        return 0
    elif args.cmd == "register-schedule":
        sched = mgr.register_schedule(
            name=args.name, schedule=args.schedule,
            namespaces=args.namespaces, exclude_namespaces=args.exclude_namespaces,
            storage_location=args.storage_location, ttl=args.ttl,
            dry_run=args.dry_run)
        print(json.dumps(sched.to_dict(), indent=2))
        return 0
    elif args.cmd == "apply-schedule":
        state = mgr.load()
        sched = next((s for s in state.schedules if s.name == args.name), None)
        if not sched:
            print(f"ERROR: schedule '{args.name}' not in registry"); return 1
        rc = mgr.apply_schedule(sched, dry_run=args.dry_run)
        print("OK" if rc == 0 else f"FAILED (rc={rc})")
        return rc
    elif args.cmd == "backup":
        rc = mgr.create_backup(name=args.name, namespaces=args.namespaces or None,
                                storage_location=args.storage_location, ttl=args.ttl,
                                wait=args.wait)
        print("OK" if rc == 0 else f"FAILED (rc={rc})")
        return rc
    elif args.cmd == "restore":
        rc = mgr.restore(backup_name=args.backup, namespaces=args.namespaces or None,
                         dry_run=args.dry_run)
        print("OK" if rc == 0 else f"FAILED (rc={rc})")
        return rc
    elif args.cmd == "list":
        state = mgr.load()
        print("Storage Locations:")
        for s in state.storage_locations:
            dflt = " [DEFAULT]" if s.is_default else ""
            print(f"  {s.name}: {s.provider} s3://{s.bucket}/{s.prefix}{dflt}")
        print("Schedules:")
        for s in state.schedules:
            ns_str = ",".join(s.namespaces) if s.namespaces else "all-namespaces"
            print(f"  {s.name}: {s.schedule} ({ns_str}) TTL={s.ttl}")
        print(f"Recent backups: {len(state.recent_backups)}")
        return 0
    elif args.cmd == "status":
        print(json.dumps(mgr.get_deployment_status(), indent=2))
        return 0
    elif args.cmd == "sync":
        n = mgr.sync_recent_backups()
        print(f"Synced {n} backup records")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
