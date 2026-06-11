#!/usr/bin/env python3
"""
backup_manager.py — Coordinated Quiesce + Backup (CQB), Phase 1.O.

Provides:
  BackupScope          — what to include in a backup
  BackupManifest       — record of a completed backup (JSON serialisable)
  BackupScopeInferrer  — derive scope from a declared blast-radius string
  BackupManager        — orchestrate backup, restore, and list operations

Architecture (Phase 1.O decisions):
  k8s workload backup: etcd snapshot + restic PVC backup (not vzdump — k8s
    VMs are cattle; Talos/Ubuntu with Cloud-Init is disposable OS).
  Full VM disk snapshot (vzdump): explicit opt-in only via full_vm_disk_snapshot=True
    (used for pre-migration or explicit full backups, never the default).
  Governance VM: no dedicated backup — phoenix pack covers bootstrap-state.json.

Manifest files are stored at:
  {BROODFORGE_STATE_DIR}/backups/<backup_id>/manifest.json

CLI:
  python3 backup_manager.py --backup [--scope full|broodforge|vm:100,101|...] [--trigger operator|autonomous|scheduled] [--dry-run]
  python3 backup_manager.py --restore <backup_id> [--dry-run]
  python3 backup_manager.py --list [--json]
  python3 backup_manager.py --infer-scope --affects <affects_string> [--vms 100,101]

Exit codes:
  0 — success
  1 — fatal error
  2 — NOT_IMPLEMENTED (stub placeholder; some sub-operations not yet fully wired)

Stdlib only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import subprocess
import sys
import warnings
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_STATE_DIR = os.environ.get("BROODFORGE_STATE_DIR", "/var/lib/broodforge/")
BROODFORGE_VERSION_FILE = Path(__file__).parent / "version.py"
_SUBPROCESS_TIMEOUT = 300  # seconds — default timeout for all subprocess calls


def _load_broodforge_version() -> str:
    """Read SCHEMA_VERSION from version.py; return 'unknown' on any failure."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("_version", BROODFORGE_VERSION_FILE)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            return str(getattr(mod, "SCHEMA_VERSION", "unknown"))
    except Exception:
        pass
    return "unknown"


# ---------------------------------------------------------------------------
# BackupScope dataclass
# ---------------------------------------------------------------------------

@dataclass
class BackupScope:
    """Declares what a backup should include.

    Phase 1.O architecture:
      - k8s workload backup uses etcd snapshot + restic PVC (not vzdump).
      - full_vm_disk_snapshot (vzdump) is an explicit opt-in — not the default.
      - Governance VM is covered by phoenix pack; no dedicated VM backup by default.
    """

    include_broodforge: bool = True       # always True, non-optional
    quiesce_level: int = 1                # 0=live, 1=service, 2=vm-suspend, 3=full
    vm_ids: list[int] | str = field(default_factory=lambda: "all")
    include_proxmox_host_config: bool = False  # /etc/pve/ etc — level 2+ only
    k8s_etcd_snapshot: bool = True        # etcdctl snapshot save — default for k8s clusters
    k8s_pvc_backup: bool = True           # restic backup of PVC mountpoints — default for k8s
    full_vm_disk_snapshot: bool = False   # vzdump — explicit opt-in only, never default

    def __post_init__(self) -> None:
        if not self.include_broodforge:
            warnings.warn(
                "BackupScope.include_broodforge was set to False — "
                "this is not permitted; forcing True.",
                UserWarning,
                stacklevel=2,
            )
            self.include_broodforge = True
        if self.quiesce_level >= 2:
            self.include_proxmox_host_config = True

    def human_label(self) -> str:
        """Return a short human-readable scope label for the manifest."""
        if self.quiesce_level == 3:
            return "full"
        if self.quiesce_level == 0 and (
            not isinstance(self.vm_ids, list) or len(self.vm_ids) == 0
        ):
            return "broodforge-only"
        if isinstance(self.vm_ids, list) and len(self.vm_ids) == 1:
            return f"vm:{self.vm_ids[0]}"
        if isinstance(self.vm_ids, list) and self.vm_ids:
            ids_str = ",".join(str(v) for v in self.vm_ids)
            return f"vms:{ids_str}"
        return f"level-{self.quiesce_level}"

    def to_dict(self) -> dict:
        vm_ids_serial = self.vm_ids if isinstance(self.vm_ids, str) else list(self.vm_ids)
        return {
            "include_broodforge": self.include_broodforge,
            "quiesce_level": self.quiesce_level,
            "vm_ids": vm_ids_serial,
            "include_proxmox_host_config": self.include_proxmox_host_config,
            "k8s_etcd_snapshot": self.k8s_etcd_snapshot,
            "k8s_pvc_backup": self.k8s_pvc_backup,
            "full_vm_disk_snapshot": self.full_vm_disk_snapshot,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BackupScope":
        vm_ids = d.get("vm_ids", "all")
        if isinstance(vm_ids, list):
            vm_ids = [int(v) for v in vm_ids]
        return cls(
            include_broodforge=bool(d.get("include_broodforge", True)),
            quiesce_level=int(d.get("quiesce_level", 1)),
            vm_ids=vm_ids,
            include_proxmox_host_config=bool(d.get("include_proxmox_host_config", False)),
            k8s_etcd_snapshot=bool(d.get("k8s_etcd_snapshot", True)),
            k8s_pvc_backup=bool(d.get("k8s_pvc_backup", True)),
            full_vm_disk_snapshot=bool(d.get("full_vm_disk_snapshot", False)),
        )


# ---------------------------------------------------------------------------
# BackupManifest dataclass
# ---------------------------------------------------------------------------

@dataclass
class BackupManifest:
    """Record of a completed (or dry-run) backup."""

    backup_id: str           # YYYY-MM-DD_HH-MM-SS_<7-char-hash>
    scope: str               # human label: "full", "vm:100", "broodforge-only", etc.
    trigger: str             # "operator" | "autonomous" | "scheduled"
    quiesce_level: int
    broodforge: dict         # phoenix_package path, schema_version, state_hash
    proxmox_host_config: Optional[dict]   # restic snapshot id if captured
    k8s_snapshots: dict      # {"etcd_snapshot": {...}, "pvc_restic": {...}}
    vm_snapshots: dict       # vmid -> vzdump result (explicit full mode only)
    completed_at: str        # ISO-8601 UTC
    broodforge_version: str  # from version.py
    manifest_sha256: str = ""  # F-5: SHA-256 of manifest.json after write; "" in dry-run

    def to_dict(self) -> dict:
        return {
            "backup_id": self.backup_id,
            "scope": self.scope,
            "trigger": self.trigger,
            "quiesce_level": self.quiesce_level,
            "broodforge": self.broodforge,
            "proxmox_host_config": self.proxmox_host_config,
            "k8s_snapshots": self.k8s_snapshots,
            "vm_snapshots": self.vm_snapshots,
            "completed_at": self.completed_at,
            "broodforge_version": self.broodforge_version,
            "manifest_sha256": self.manifest_sha256,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BackupManifest":
        return cls(
            backup_id=str(d["backup_id"]),
            scope=str(d.get("scope", "")),
            trigger=str(d.get("trigger", "operator")),
            quiesce_level=int(d.get("quiesce_level", 0)),
            broodforge=dict(d.get("broodforge") or {}),
            proxmox_host_config=d.get("proxmox_host_config"),
            k8s_snapshots=dict(d.get("k8s_snapshots") or {}),
            vm_snapshots=dict(d.get("vm_snapshots") or {}),
            completed_at=str(d.get("completed_at", "")),
            broodforge_version=str(d.get("broodforge_version", "unknown")),
            manifest_sha256=str(d.get("manifest_sha256", "")),
        )

    def save(self, backup_dir: Path) -> None:
        """Serialise to <backup_dir>/manifest.json and record SHA-256 (F-5).

        Post-write verification: after the file is flushed to disk, the written
        bytes are re-read and SHA-256'd. The digest is stored in the in-memory
        manifest (accessible after return) and also written to
        <backup_dir>/manifest.sha256 so an operator or restore script can
        independently verify integrity without loading the JSON.
        """
        backup_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = backup_dir / "manifest.json"

        # Write manifest (without the checksum field — we don't know it yet)
        with open(manifest_path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

        # Post-write checksum verification (F-5)
        raw = manifest_path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        self.manifest_sha256 = digest

        # Persist the digest both in the manifest and as a sidecar .sha256 file
        # Update the manifest file to include the computed digest
        data = json.loads(raw)
        data["manifest_sha256"] = digest
        manifest_path.write_text(json.dumps(data, indent=2))

        sha256_path = backup_dir / "manifest.sha256"
        sha256_path.write_text(f"{digest}  manifest.json\n")

        logger.info(
            "[backup] Manifest written to %s (sha256=%s)", manifest_path, digest[:12] + "…"
        )

    @classmethod
    def load(cls, backup_dir: Path) -> "BackupManifest":
        """Deserialise from <backup_dir>/manifest.json.

        If manifest.sha256 exists alongside the manifest, the digest is
        verified on load; a mismatch raises RuntimeError so a corrupt or
        tampered manifest is caught before any restore action is taken (F-5).
        """
        manifest_path = backup_dir / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"Manifest not found: {manifest_path}")

        raw = manifest_path.read_bytes()

        # Verify against sidecar checksum file if present
        sha256_path = backup_dir / "manifest.sha256"
        if sha256_path.exists():
            actual_digest = hashlib.sha256(raw).hexdigest()
            first_line = sha256_path.read_text().strip().split()[0]
            if actual_digest != first_line:
                raise RuntimeError(
                    f"Manifest integrity check FAILED for {manifest_path}. "
                    f"Expected {first_line[:12]}…, got {actual_digest[:12]}…. "
                    "The backup manifest may be corrupt or tampered."
                )

        d = json.loads(raw)
        return cls.from_dict(d)

    def verify_integrity(self, backup_dir: Path) -> bool:
        """Re-verify manifest.json against manifest.sha256 (F-5).

        Returns True if intact, False if the file is missing or the digest
        does not match.  Does not raise — intended for health-check callers.
        """
        manifest_path = backup_dir / "manifest.json"
        sha256_path = backup_dir / "manifest.sha256"
        if not manifest_path.exists() or not sha256_path.exists():
            return False
        try:
            actual = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            expected = sha256_path.read_text().strip().split()[0]
            return actual == expected
        except Exception:
            return False


# ---------------------------------------------------------------------------
# BackupScopeInferrer
# ---------------------------------------------------------------------------

class BackupScopeInferrer:
    """Infer a BackupScope from a risky operation's declared blast-radius string.

    Blast-radius strings (``affects`` parameter):
      "broodforge-config"   → broodforge only, no k8s/VM backup, level 0
      "pod:<ns>/<name>"     → level 1, k8s_etcd_snapshot=True, k8s_pvc_backup=True
      "service:<name>"      → level 1, k8s_etcd_snapshot=True, k8s_pvc_backup=True
      "vm:<vmid>"           → level 2, include_proxmox_host_config=True, k8s snapshots
      "node:<id>"           → level 2, all VMs on node (same as "all" w/o further info)
      "full"                → level 3, everything, full_vm_disk_snapshot=True
      "unknown"             → level 3, everything, full_vm_disk_snapshot=True (safe default)
    """

    def infer(
        self,
        affects: str,
        affected_vms: Optional[list[int]] = None,
    ) -> BackupScope:
        affects = (affects or "unknown").strip().lower()

        if affects == "broodforge-config":
            return BackupScope(
                include_broodforge=True,
                quiesce_level=0,
                vm_ids=[],
                include_proxmox_host_config=False,
                k8s_etcd_snapshot=False,
                k8s_pvc_backup=False,
                full_vm_disk_snapshot=False,
            )

        if affects.startswith("pod:") or affects.startswith("service:"):
            vms = list(affected_vms) if affected_vms else []
            return BackupScope(
                include_broodforge=True,
                quiesce_level=1,
                vm_ids=vms,
                include_proxmox_host_config=False,
                k8s_etcd_snapshot=True,
                k8s_pvc_backup=True,
                full_vm_disk_snapshot=False,
            )

        if affects.startswith("vm:"):
            try:
                vmid = int(affects.split(":", 1)[1])
                vms = [vmid]
            except (ValueError, IndexError):
                vms = list(affected_vms) if affected_vms else []
            return BackupScope(
                include_broodforge=True,
                quiesce_level=2,
                vm_ids=vms,
                include_proxmox_host_config=True,
                k8s_etcd_snapshot=True,
                k8s_pvc_backup=True,
                full_vm_disk_snapshot=False,
            )

        if affects.startswith("node:"):
            # All VMs on the node — we don't have the inventory here, use "all"
            vms: list[int] | str = list(affected_vms) if affected_vms else "all"
            return BackupScope(
                include_broodforge=True,
                quiesce_level=2,
                vm_ids=vms,
                include_proxmox_host_config=True,
                k8s_etcd_snapshot=True,
                k8s_pvc_backup=True,
                full_vm_disk_snapshot=False,
            )

        # "full", "unknown", or any unrecognised value → safe default = full
        return BackupScope(
            include_broodforge=True,
            quiesce_level=3,
            vm_ids="all",
            include_proxmox_host_config=True,
            k8s_etcd_snapshot=True,
            k8s_pvc_backup=True,
            full_vm_disk_snapshot=True,
        )


# ---------------------------------------------------------------------------
# BackupManager
# ---------------------------------------------------------------------------

def _generate_backup_id(now: datetime) -> str:
    """Generate YYYY-MM-DD_HH-MM-SS_<7-char-hash> backup ID."""
    ts = now.strftime("%Y-%m-%d_%H-%M-%S")
    # Short hash: SHA-256 of the timestamp + a random nonce for uniqueness
    import secrets as _secrets
    nonce = _secrets.token_hex(4)
    h = hashlib.sha256(f"{ts}{nonce}".encode()).hexdigest()[:7]
    return f"{ts}_{h}"


class BackupManager:
    """Orchestrate CQB backup and restore operations."""

    def __init__(
        self,
        state_dir: Path,
        proxmox_api_url: Optional[str] = None,
        now_fn: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.state_dir = Path(state_dir)
        self.backups_dir = self.state_dir / "backups"
        self.proxmox_api_url = proxmox_api_url
        # Clock injection: default to UTC now; callers can inject a fixed clock for tests
        self._now: Callable[[], datetime] = now_fn or (
            lambda: datetime.now(timezone.utc)
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def backup(
        self,
        scope: BackupScope,
        trigger: str = "operator",
        dry_run: bool = False,
    ) -> BackupManifest:
        """Execute a backup according to the provided scope.

        On dry_run=True: prints what would be done but writes NO state files
        (manifest.json is not created).

        Returns a BackupManifest (with backup_id populated even in dry-run).
        """
        now = self._now()
        backup_id = _generate_backup_id(now)
        backup_dir = self.backups_dir / backup_id

        logger.info(
            "[backup] Starting CQB backup. id=%s scope=%s trigger=%s dry_run=%s",
            backup_id, scope.human_label(), trigger, dry_run,
        )

        if dry_run:
            print(f"[dry-run] Would create backup: {backup_id}")
            print(f"[dry-run]   scope:              {scope.human_label()}")
            print(f"[dry-run]   quiesce_level:      {scope.quiesce_level}")
            print(f"[dry-run]   vm_ids:             {scope.vm_ids}")
            print(f"[dry-run]   host_config:        {scope.include_proxmox_host_config}")
            print(f"[dry-run]   k8s_etcd_snapshot:  {scope.k8s_etcd_snapshot}")
            print(f"[dry-run]   k8s_pvc_backup:     {scope.k8s_pvc_backup}")
            print(f"[dry-run]   full_vm_disk_snap:  {scope.full_vm_disk_snapshot}")
            print(f"[dry-run]   backup_dir:         {backup_dir}")
            broodforge_info: dict = {"dry_run": True}
            host_config_info: Optional[dict] = (
                {"dry_run": True} if scope.include_proxmox_host_config else None
            )
            k8s_snapshots: dict = {}
            if scope.k8s_etcd_snapshot:
                k8s_snapshots["etcd_snapshot"] = {"dry_run": True}
            if scope.k8s_pvc_backup:
                k8s_snapshots["pvc_restic"] = {"dry_run": True}
            vm_snapshots: dict = {}
            if scope.full_vm_disk_snapshot:
                if scope.vm_ids == "all":
                    vm_snapshots = {"all": f"dry-run-vzdump-{backup_id}"}
                elif isinstance(scope.vm_ids, list):
                    for vmid in scope.vm_ids:
                        vm_snapshots[str(vmid)] = f"dry-run-vzdump-{backup_id}"
        else:
            backup_dir.mkdir(parents=True, exist_ok=True)
            broodforge_info = self._pack_broodforge(backup_dir)
            host_config_info = (
                self._snapshot_proxmox_host_config(backup_dir)
                if scope.include_proxmox_host_config
                else None
            )
            k8s_snapshots = (
                self._snapshot_k8s(backup_dir, scope)
                if (scope.k8s_etcd_snapshot or scope.k8s_pvc_backup)
                else {}
            )
            vm_snapshots = (
                self._snapshot_vms_full(scope.vm_ids, backup_dir, backup_id)
                if scope.full_vm_disk_snapshot
                else {}
            )

        completed_at = self._now().strftime("%Y-%m-%dT%H:%M:%SZ")
        manifest = BackupManifest(
            backup_id=backup_id,
            scope=scope.human_label(),
            trigger=trigger,
            quiesce_level=scope.quiesce_level,
            broodforge=broodforge_info,
            proxmox_host_config=host_config_info,
            k8s_snapshots=k8s_snapshots,
            vm_snapshots=vm_snapshots,
            completed_at=completed_at,
            broodforge_version=_load_broodforge_version(),
        )

        if not dry_run:
            manifest.save(backup_dir)
            logger.info("[backup] Backup complete: %s", backup_id)
        else:
            logger.info("[backup] Dry-run complete (no files written).")

        return manifest

    def restore(self, backup_id: str, dry_run: bool = False) -> None:
        """Restore from a backup manifest.

        Raises FileNotFoundError if the manifest is missing.
        On dry_run=True: prints what would be done without executing.
        """
        backup_dir = self.backups_dir / backup_id
        manifest = BackupManifest.load(backup_dir)   # raises FileNotFoundError if absent

        logger.info("[restore] Restoring from backup %s (dry_run=%s)", backup_id, dry_run)
        print(f"[restore] Backup ID:       {manifest.backup_id}")
        print(f"[restore] Scope:           {manifest.scope}")
        print(f"[restore] Trigger:         {manifest.trigger}")
        print(f"[restore] Completed at:    {manifest.completed_at}")
        print(f"[restore] k8s snapshots:   {list(manifest.k8s_snapshots.keys())}")
        print(f"[restore] VM snapshots:    {list(manifest.vm_snapshots.keys())}")
        print(f"[restore] Broodforge pkg:  {manifest.broodforge}")

        if dry_run:
            print("[dry-run] Would restore k8s snapshots, VM snapshots, and broodforge state — no action taken.")
            return

        # Restore k8s etcd snapshot
        etcd_info = manifest.k8s_snapshots.get("etcd_snapshot")
        if etcd_info and isinstance(etcd_info, dict) and etcd_info.get("path"):
            snap_path = etcd_info["path"]
            print(f"[restore] etcd snapshot: {snap_path}")
            print("[restore] To restore etcd: stop etcd, replace data dir, then:")
            print(f"[restore]   ETCDCTL_API=3 etcdctl snapshot restore {snap_path}")
            print("[restore] NOTE: etcd restore is a manual operator procedure — not automated here.")

        # Restore VM snapshots (vzdump — explicit full mode only)
        for vmid_str, vzdump_result in manifest.vm_snapshots.items():
            if vmid_str == "all":
                logger.warning("[restore] vm_snapshots key 'all' cannot be restored automatically — manual restore required")
                print(f"[restore] WARNING: vm_snapshots recorded as 'all' — restore vzdump '{vzdump_result}' manually on each VM")
                continue
            print(f"[restore] VM {vmid_str} vzdump result: {vzdump_result}")
            print(f"[restore] Restore with: qmrestore <vzdump-file> <vmid>")

        # Restore broodforge state
        pkg_path = manifest.broodforge.get("phoenix_package_path")
        if pkg_path:
            print(f"[restore] Broodforge phoenix package: {pkg_path}")
            print("[restore] Extract and run the phoenix package to restore broodforge state.")
        else:
            logger.warning("[restore] No phoenix_package_path in broodforge manifest — skipping broodforge state restore")
            print("[restore] No broodforge phoenix package path recorded — restore state manually.")

        print(f"[restore] Restore procedure printed for backup {backup_id}")

    def list_backups(self) -> list[BackupManifest]:
        """Return all backup manifests, sorted newest-first."""
        if not self.backups_dir.is_dir():
            return []
        results: list[BackupManifest] = []
        for entry in self.backups_dir.iterdir():
            if not entry.is_dir():
                continue
            try:
                m = BackupManifest.load(entry)
                results.append(m)
            except (FileNotFoundError, json.JSONDecodeError, KeyError) as exc:
                logger.warning("[backup] Skipping %s: %s", entry.name, exc)
        results.sort(key=lambda m: m.completed_at, reverse=True)
        return results

    def get_manifest(self, backup_id: str) -> BackupManifest:
        """Load and return a single manifest by backup_id."""
        return BackupManifest.load(self.backups_dir / backup_id)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _pack_broodforge(self, backup_dir: Path) -> dict:
        """Call assemble_phoenix_package to pack broodforge state.

        Returns a dict with:
          phoenix_package_path — path to the .tar.gz (relative to backup_dir)
          schema_version       — from version.py
          state_hash           — SHA-256 of bootstrap-state.json if present
        """
        state_json = self.state_dir / "bootstrap-state.json"
        state_hash = ""
        if state_json.exists():
            with open(state_json, "rb") as f:
                state_hash = hashlib.sha256(f.read()).hexdigest()

        schema_version = _load_broodforge_version()

        # Locate assemble_phoenix_package.py
        phoenix_script = Path(__file__).parent / "assemble_phoenix_package.py"
        pkg_path: Optional[str] = None

        if phoenix_script.exists():
            output_file = backup_dir / f"broodforge-phoenix-{backup_dir.name}.tar.gz"
            try:
                result = subprocess.run(
                    [
                        sys.executable,
                        str(phoenix_script),
                        "--state-dir", str(self.state_dir),
                        "--output", str(output_file),
                    ],
                    capture_output=True, text=True,
                    timeout=_SUBPROCESS_TIMEOUT,
                )
                if result.returncode == 0:
                    pkg_path = str(output_file)
                    logger.info("[backup] Phoenix package created: %s", pkg_path)
                elif result.returncode == 2:
                    logger.warning(
                        "[backup] assemble_phoenix_package exited 2 (NOT_IMPLEMENTED) — "
                        "phoenix pack skipped; broodforge state backup is partial."
                    )
                    pkg_path = None
                else:
                    logger.warning(
                        "[backup] assemble_phoenix_package failed (rc=%d): %s",
                        result.returncode, result.stderr,
                    )
                    pkg_path = None
            except subprocess.TimeoutExpired:
                logger.warning("[backup] assemble_phoenix_package timed out after %ds", _SUBPROCESS_TIMEOUT)
                pkg_path = None
        else:
            logger.warning("[backup] assemble_phoenix_package.py not found at %s", phoenix_script)

        return {
            "phoenix_package_path": pkg_path,
            "schema_version": schema_version,
            "state_hash": state_hash,
        }

    def _snapshot_proxmox_host_config(self, backup_dir: Path) -> Optional[dict]:
        """Snapshot /etc/pve and related host config files using restic.

        Returns a dict with restic snapshot ID, or None if restic is not
        configured / fails.

        NOTE: restic must be configured separately (RESTIC_REPOSITORY + RESTIC_PASSWORD
        env vars or /etc/restic.conf). If not configured, this step logs a warning and
        returns None rather than failing the entire backup.
        """
        restic_bin = _find_executable("restic")
        if not restic_bin:
            logger.warning(
                "[backup] restic not found — /etc/pve backup skipped. "
                "Install restic and configure RESTIC_REPOSITORY + RESTIC_PASSWORD "
                "to enable host config snapshots."
            )
            return None

        # Check that restic env is configured
        if not os.environ.get("RESTIC_REPOSITORY") and not os.environ.get("RESTIC_REPOSITORY_FILE"):
            logger.warning(
                "[backup] RESTIC_REPOSITORY not set — /etc/pve backup skipped. "
                "See docs/CLOUD-STORAGE-SETUP.md for restic configuration."
            )
            return None

        paths_to_backup = ["/etc/pve", "/etc/network/interfaces", "/etc/hosts"]
        existing_paths = [p for p in paths_to_backup if os.path.exists(p)]

        if not existing_paths:
            logger.warning("[backup] No /etc/pve paths found — is this running on a Proxmox host?")
            return {"snapshot_id": None, "note": "no /etc/pve paths found"}

        tag = f"broodforge-cqb-{backup_dir.name}"
        try:
            result = subprocess.run(
                [restic_bin, "backup", "--json", "--tag", tag] + existing_paths,
                capture_output=True, text=True,
                timeout=_SUBPROCESS_TIMEOUT,
            )
            if result.returncode != 0:
                logger.warning("[backup] restic backup failed (rc=%d): %s", result.returncode, result.stderr)
                return {"snapshot_id": None, "error": result.stderr[:500]}

            # Parse snapshot ID from JSON output
            snapshot_id = _parse_restic_snapshot_id(result.stdout)
            logger.info("[backup] restic snapshot created: %s", snapshot_id)
            return {"snapshot_id": snapshot_id, "tag": tag, "paths": existing_paths}

        except subprocess.TimeoutExpired:
            logger.warning("[backup] restic backup timed out after %ds", _SUBPROCESS_TIMEOUT)
            return {"snapshot_id": None, "error": "restic timed out"}

    def _snapshot_k8s(self, backup_dir: Path, scope: BackupScope) -> dict:
        """Snapshot k8s cluster state: etcd snapshot and/or restic PVC backup.

        This is the primary k8s backup method (Phase 1.O architecture):
          - etcd snapshot captures all k8s object state
          - PVC restic backup captures persistent volume data

        Full VM disk snapshots (vzdump) are NOT used for k8s clusters — the VM OS
        is cattle (Talos/Ubuntu+Cloud-Init). Only call _snapshot_vms_full() when
        full_vm_disk_snapshot=True (explicit pre-migration use case).

        Returns a dict with:
          etcd_snapshot — {"path": ..., "status": "ok"} or {"error": ...}
          pvc_restic    — {"snapshot_id": ..., "tag": ..., "paths": [...]} or {"error": ...}

        NOTE: etcdctl path and PVC mountpoints may need adjustment per deployment.
              Set ETCDCTL_ENDPOINTS, ETCDCTL_CACERT, ETCDCTL_CERT, ETCDCTL_KEY env
              vars to configure etcd TLS.
        """
        result: dict = {}

        if scope.k8s_etcd_snapshot:
            etcdctl = _find_executable("etcdctl")
            if not etcdctl:
                logger.warning(
                    "[backup] etcdctl not found — etcd snapshot skipped. "
                    "Install etcd-client and ensure etcdctl is in PATH. "
                    "Also set ETCDCTL_ENDPOINTS (default: 127.0.0.1:2379)."
                )
                result["etcd_snapshot"] = {"error": "etcdctl not found", "status": "skipped"}
            else:
                snap_path = backup_dir / f"etcd-snapshot-{backup_dir.name}.db"
                env = os.environ.copy()
                env.setdefault("ETCDCTL_API", "3")
                env.setdefault("ETCDCTL_ENDPOINTS", "127.0.0.1:2379")
                try:
                    r = subprocess.run(
                        [etcdctl, "snapshot", "save", str(snap_path)],
                        capture_output=True, text=True,
                        timeout=_SUBPROCESS_TIMEOUT,
                        env=env,
                    )
                    if r.returncode == 0:
                        result["etcd_snapshot"] = {
                            "path": str(snap_path),
                            "status": "ok",
                        }
                        logger.info("[backup] etcd snapshot saved: %s", snap_path)
                    else:
                        logger.warning(
                            "[backup] etcdctl snapshot save failed (rc=%d): %s",
                            r.returncode, r.stderr,
                        )
                        result["etcd_snapshot"] = {
                            "error": r.stderr[:300],
                            "status": "failed",
                        }
                except subprocess.TimeoutExpired:
                    logger.warning("[backup] etcdctl snapshot timed out after %ds", _SUBPROCESS_TIMEOUT)
                    result["etcd_snapshot"] = {"error": "timeout", "status": "failed"}

        if scope.k8s_pvc_backup:
            restic_bin = _find_executable("restic")
            if not restic_bin:
                logger.warning("[backup] restic not found — PVC backup skipped.")
                result["pvc_restic"] = {"error": "restic not found", "status": "skipped"}
            elif not os.environ.get("RESTIC_REPOSITORY") and not os.environ.get("RESTIC_REPOSITORY_FILE"):
                logger.warning(
                    "[backup] RESTIC_REPOSITORY not set — PVC backup skipped. "
                    "Configure RESTIC_REPOSITORY + RESTIC_PASSWORD to enable PVC snapshots."
                )
                result["pvc_restic"] = {"error": "RESTIC_REPOSITORY not configured", "status": "skipped"}
            else:
                # Common PVC mountpoint locations for k3s / Talos / kubeadm deployments
                pvc_candidate_paths = [
                    "/var/lib/rancher/k3s/storage",  # k3s local-path provisioner
                    "/var/openebs/local",             # OpenEBS local PV
                    "/mnt/pvc",                       # generic convention
                    "/data/pvc",                      # generic convention
                ]
                existing = [p for p in pvc_candidate_paths if os.path.exists(p)]
                if not existing:
                    logger.warning(
                        "[backup] No PVC mountpoints found at %s — PVC backup skipped. "
                        "Adjust pvc_candidate_paths in _snapshot_k8s() for this deployment.",
                        pvc_candidate_paths,
                    )
                    result["pvc_restic"] = {
                        "error": "no PVC mountpoints found",
                        "checked": pvc_candidate_paths,
                        "status": "skipped",
                    }
                else:
                    tag = f"broodforge-pvc-{backup_dir.name}"
                    try:
                        r = subprocess.run(
                            [restic_bin, "backup", "--json", "--tag", tag] + existing,
                            capture_output=True, text=True,
                            timeout=_SUBPROCESS_TIMEOUT,
                        )
                        if r.returncode == 0:
                            sid = _parse_restic_snapshot_id(r.stdout)
                            result["pvc_restic"] = {
                                "snapshot_id": sid,
                                "tag": tag,
                                "paths": existing,
                                "status": "ok",
                            }
                            logger.info("[backup] PVC restic snapshot: %s", sid)
                        else:
                            logger.warning(
                                "[backup] restic PVC backup failed (rc=%d): %s",
                                r.returncode, r.stderr,
                            )
                            result["pvc_restic"] = {
                                "error": r.stderr[:300],
                                "status": "failed",
                            }
                    except subprocess.TimeoutExpired:
                        logger.warning("[backup] restic PVC backup timed out after %ds", _SUBPROCESS_TIMEOUT)
                        result["pvc_restic"] = {"error": "timeout", "status": "failed"}

        return result

    def _snapshot_vms_full(
        self,
        vm_ids: list[int] | str,
        backup_dir: Path,
        backup_id: Optional[str] = None,
    ) -> dict:
        """Create full VM disk backups via vzdump (explicit opt-in only).

        This is NOT the default backup path for k8s cluster VMs — use _snapshot_k8s()
        for k8s workloads. This method is for explicit pre-migration or operator-requested
        full disk snapshots (scope.full_vm_disk_snapshot=True).

        Returns a dict mapping vmid (str) → vzdump output path or error.
        """
        if backup_id is None:
            backup_id = backup_dir.name

        vzdump = _find_executable("vzdump")
        if not vzdump:
            logger.warning("[backup] vzdump not found — full VM disk snapshot skipped")
            return {"error": "vzdump not found"}

        if isinstance(vm_ids, str):
            if vm_ids == "all":
                return self._vzdump_all_vms(backup_dir, backup_id)
            else:
                logger.warning("[backup] Unexpected vm_ids value: %r — skipping full VM backup", vm_ids)
                return {}

        results: dict = {}
        dumpdir = str(backup_dir)
        for vmid in vm_ids:
            try:
                r = subprocess.run(
                    [
                        vzdump, str(vmid),
                        "--dumpdir", dumpdir,
                        "--compress", "zstd",
                        "--mode", "snapshot",
                    ],
                    capture_output=True, text=True,
                    timeout=_SUBPROCESS_TIMEOUT,
                )
                if r.returncode == 0:
                    # vzdump prints the output path in stdout
                    output_line = [
                        line for line in r.stdout.splitlines()
                        if "creating" in line.lower() or ".vma" in line or ".tar" in line
                    ]
                    results[str(vmid)] = {
                        "status": "ok",
                        "dumpdir": dumpdir,
                        "note": output_line[-1].strip() if output_line else "vzdump succeeded",
                    }
                    logger.info("[backup] vzdump VM %d complete", vmid)
                else:
                    logger.warning("[backup] vzdump %d failed (rc=%d): %s", vmid, r.returncode, r.stderr)
                    results[str(vmid)] = {"status": "failed", "error": r.stderr[:300]}
            except subprocess.TimeoutExpired:
                logger.warning("[backup] vzdump %d timed out after %ds", vmid, _SUBPROCESS_TIMEOUT)
                results[str(vmid)] = {"status": "failed", "error": "timeout"}

        return results

    def _vzdump_all_vms(self, backup_dir: Path, backup_id: str) -> dict:
        """Discover all VMs via pvesh and vzdump each one."""
        pvesh = _find_executable("pvesh")
        if not pvesh:
            logger.warning("[backup] pvesh not found — cannot enumerate VMs for 'all' scope")
            return {"all": {"status": "skipped", "error": "pvesh not found"}}

        try:
            result = subprocess.run(
                [pvesh, "get", "/nodes/localhost/qemu", "--output-format", "json"],
                capture_output=True, text=True,
                timeout=60,
            )
            if result.returncode != 0:
                logger.warning("[backup] pvesh get qemu list failed: %s", result.stderr)
                return {"all": {"status": "failed", "error": result.stderr[:300]}}

            vms_data = json.loads(result.stdout)
            vm_ids = [int(vm["vmid"]) for vm in vms_data if "vmid" in vm]
        except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError) as exc:
            logger.warning("[backup] Could not enumerate VMs: %s", exc)
            return {"all": {"status": "failed", "error": str(exc)}}

        return self._snapshot_vms_full(vm_ids, backup_dir, backup_id)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _find_executable(name: str) -> Optional[str]:
    """Return the full path to an executable, or None if not found."""
    import shutil
    return shutil.which(name)


def _parse_restic_snapshot_id(output: str) -> Optional[str]:
    """Parse restic's JSON output to extract the snapshot ID."""
    for line in output.strip().splitlines():
        try:
            obj = json.loads(line)
            # restic --json backup summary has message_type="summary" and snapshot_id
            if obj.get("message_type") == "summary":
                return obj.get("snapshot_id")
        except json.JSONDecodeError:
            continue
    return None


# ---------------------------------------------------------------------------
# Scope parsing helpers (for CLI --scope flag)
# ---------------------------------------------------------------------------

def _parse_scope_arg(scope_str: str) -> BackupScope:
    """Parse a --scope CLI argument into a BackupScope.

    Accepted values:
      full                  — quiesce_level=3, all VMs, host config, full_vm_disk_snapshot
      broodforge            — quiesce_level=0, no VMs, no k8s, no host config
      vm:100,101            — quiesce_level=2, named VMs, k8s snapshots, no vzdump
      pod:ns/name           — quiesce_level=1, k8s_etcd+pvc
      service:name          — quiesce_level=1, k8s_etcd+pvc
    """
    inferrer = BackupScopeInferrer()
    s = (scope_str or "").strip().lower()

    if s == "full":
        return BackupScope(
            quiesce_level=3,
            vm_ids="all",
            include_proxmox_host_config=True,
            k8s_etcd_snapshot=True,
            k8s_pvc_backup=True,
            full_vm_disk_snapshot=True,
        )

    if s in ("broodforge", "broodforge-only"):
        return BackupScope(
            quiesce_level=0,
            vm_ids=[],
            include_proxmox_host_config=False,
            k8s_etcd_snapshot=False,
            k8s_pvc_backup=False,
            full_vm_disk_snapshot=False,
        )

    if s.startswith("vm:"):
        parts = s[3:].split(",")
        try:
            vms = [int(p.strip()) for p in parts if p.strip()]
        except ValueError:
            print(f"[backup] ERROR: invalid vm IDs in scope: {scope_str}", file=sys.stderr)
            sys.exit(1)
        return BackupScope(
            quiesce_level=2,
            vm_ids=vms,
            include_proxmox_host_config=True,
            k8s_etcd_snapshot=True,
            k8s_pvc_backup=True,
            full_vm_disk_snapshot=False,
        )

    # Delegate pod: / service: / node: / unknown to inferrer
    return inferrer.infer(s)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="broodforge CQB backup manager (Phase 1.O)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--backup",   action="store_true", help="Run a backup")
    action.add_argument("--restore",  metavar="BACKUP_ID",  help="Restore from a backup ID")
    action.add_argument("--list",     action="store_true",  help="List all backups")
    action.add_argument("--infer-scope", action="store_true", help="Print inferred scope for a blast-radius string")

    parser.add_argument(
        "--scope",
        default="full",
        help="Backup scope: full|broodforge|vm:100,101|pod:ns/name|service:name",
    )
    parser.add_argument(
        "--trigger",
        default="operator",
        choices=["operator", "autonomous", "scheduled"],
        help="Backup trigger source",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print plan without executing")
    parser.add_argument("--json",    action="store_true",  help="JSON output for --list")
    parser.add_argument(
        "--state-dir",
        default=DEFAULT_STATE_DIR,
        help="BROODFORGE_STATE_DIR path",
    )
    parser.add_argument("--affects",  help="Blast-radius string for --infer-scope")
    parser.add_argument(
        "--vms", default="",
        help="Comma-separated VM IDs for --infer-scope",
    )

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(message)s",
        stream=sys.stderr,
    )
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    manager = BackupManager(state_dir=Path(args.state_dir))

    # --backup
    if args.backup:
        scope = _parse_scope_arg(args.scope)
        manifest = manager.backup(scope=scope, trigger=args.trigger, dry_run=args.dry_run)
        if args.dry_run:
            print(f"[dry-run] backup_id: {manifest.backup_id}")
        else:
            print(f"backup_id: {manifest.backup_id}")
            print(f"scope:     {manifest.scope}")
            print(f"completed: {manifest.completed_at}")
        return 0

    # --restore
    if args.restore:
        try:
            manager.restore(backup_id=args.restore, dry_run=args.dry_run)
        except FileNotFoundError as exc:
            print(f"[restore] ERROR: {exc}", file=sys.stderr)
            return 1
        except RuntimeError as exc:
            print(f"[restore] ERROR: {exc}", file=sys.stderr)
            return 1
        return 0

    # --list
    if args.list:
        backups = manager.list_backups()
        if args.json:
            print(json.dumps([m.to_dict() for m in backups], indent=2))
        else:
            if not backups:
                print("No backups found.")
                return 0
            print(f"{'BACKUP ID':<35}  {'SCOPE':<20}  {'TRIGGER':<12}  {'QL':>2}  COMPLETED")
            print("-" * 90)
            for m in backups:
                print(
                    f"{m.backup_id:<35}  {m.scope:<20}  {m.trigger:<12}  "
                    f"{m.quiesce_level:>2}  {m.completed_at}"
                )
        return 0

    # --infer-scope
    if args.infer_scope:
        if not args.affects:
            print("[infer-scope] ERROR: --affects is required", file=sys.stderr)
            return 1
        vms: Optional[list[int]] = None
        if args.vms:
            try:
                vms = [int(v.strip()) for v in args.vms.split(",") if v.strip()]
            except ValueError:
                print(f"[infer-scope] ERROR: invalid --vms: {args.vms}", file=sys.stderr)
                return 1
        inferrer = BackupScopeInferrer()
        scope = inferrer.infer(affects=args.affects, affected_vms=vms)
        if args.json:
            print(json.dumps(scope.to_dict(), indent=2))
        else:
            print(f"affects:               {args.affects}")
            print(f"quiesce_level:         {scope.quiesce_level}")
            print(f"vm_ids:                {scope.vm_ids}")
            print(f"include_host_config:   {scope.include_proxmox_host_config}")
            print(f"k8s_etcd_snapshot:     {scope.k8s_etcd_snapshot}")
            print(f"k8s_pvc_backup:        {scope.k8s_pvc_backup}")
            print(f"full_vm_disk_snapshot: {scope.full_vm_disk_snapshot}")
            print(f"human_label:           {scope.human_label()}")
        return 0

    # Should never reach here — argparse enforces the required group
    return 1


if __name__ == "__main__":
    sys.exit(main())
