#!/usr/bin/env python3
"""
backup_engine.py — Backup infrastructure library for broodforge.

Provides:
  BackupNaming     — naming convention helpers (pure, no I/O)
  SpaceProbe       — available-space querying via rclone / statvfs
  ResticRunner     — thin subprocess wrapper around restic (injectable for tests)
  RcloneRunner     — thin subprocess wrapper around rclone (injectable for tests)
  BackupEngine     — orchestrates per-layer backup runs
  RestoreEngine    — orchestrates restore from backup_history

Design constraints:
  - stdlib only (subprocess, os, json, hashlib, uuid, datetime, pathlib)
  - External dependencies: restic binary, rclone binary (called via subprocess)
  - ResticRunner and RcloneRunner accept an injectable runner_fn so tests can mock
    all subprocess calls without needing restic/rclone installed
"""

import hashlib
import json
import logging
import os
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Timestamp utilities
# ---------------------------------------------------------------------------

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _ts(dt: Optional[datetime] = None) -> str:
    """Format a datetime as YYYY-MM-DD_HH_MM_SS (UTC, underscores)."""
    if dt is None:
        dt = _now_utc()
    return dt.strftime("%Y-%m-%d_%H_%M_%S")


def _hash8(data: bytes) -> str:
    """Return first 8 hex characters of the SHA-256 hash of data."""
    return hashlib.sha256(data).hexdigest()[:8]


def _uuid8() -> str:
    """Return first 8 hex characters of a new UUID4."""
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# BackupNaming — enforced naming convention (pure, no I/O)
# ---------------------------------------------------------------------------

class BackupNaming:
    """
    Naming convention for all backup artifacts.

    Component prefixes:
      kdbx            KeePass database
      cell-config     Cell-wide configuration state
      node-{hostname} Proxmox host
      vm-{name}-{id}  Virtual machine
      ct-{name}-{id}  LXC container
      vol-{vm}-{vol}  Data volume within a VM
      svc-{name}      Application service

    Timestamp format: YYYY-MM-DD_HH_MM_SS (UTC, underscores)
    Hash: 8 hex chars — SHA-256 of content (files) or first 8 of UUID (run IDs)
    """

    # ── Component prefix builders ──────────────────────────────────────────

    @staticmethod
    def kdbx_prefix() -> str:
        return "kdbx"

    @staticmethod
    def cell_config_prefix() -> str:
        return "cell-config"

    @staticmethod
    def node_prefix(hostname: str) -> str:
        return f"node-{hostname}"

    @staticmethod
    def vm_prefix(name: str, vmid) -> str:
        return f"vm-{name}-{vmid}"

    @staticmethod
    def ct_prefix(name: str, ctid) -> str:
        return f"ct-{name}-{ctid}"

    @staticmethod
    def vol_prefix(vm_name: str, vol_name: str) -> str:
        return f"vol-{vm_name}-{vol_name}"

    @staticmethod
    def svc_prefix(service_name: str) -> str:
        return f"svc-{service_name}"

    # ── Restic repo path ───────────────────────────────────────────────────

    @staticmethod
    def repo_path(repo_root: str, cell_id: str, layer: str, component: str) -> str:
        """
        Full restic repo path at a destination:
          {repo_root}/{cell_id}/{layer}/{component}
        e.g. b2:cell-backup/proxmox-cell-a/config/vm-forgejo-101
        """
        root = repo_root.rstrip("/")
        return f"{root}/{cell_id}/{layer}/{component}"

    # ── KeePass DB filename ────────────────────────────────────────────────

    @staticmethod
    def kdbx_filename(cell_id: str, timestamp: str, content_hash8: str) -> str:
        """
        KeePass DB backup filename:
          kdbx_{cell_id}_{timestamp}_{hash8}.kdbx
        e.g. kdbx_proxmox-cell-a_2026-06-01_03_00_00_a3f2b891.kdbx
        """
        return f"kdbx_{cell_id}_{timestamp}_{content_hash8}.kdbx"

    # ── Snapshot set ID ────────────────────────────────────────────────────

    @staticmethod
    def snapshot_set_id(cell_id: str, timestamp: str, run_hash8: str) -> str:
        """
        Human-readable snapshot set ID that links all component snapshots of one run:
          {cell_id}_{timestamp}_{run_hash8}
        e.g. proxmox-cell-a_2026-06-01_03_00_00_f7c1d3a2
        """
        return f"{cell_id}_{timestamp}_{run_hash8}"

    # ── KeePass key paths ──────────────────────────────────────────────────

    @staticmethod
    def keepass_key_path(prefix: str, component: str, timestamp: str) -> str:
        """
        Per-backup KeePass path for a restic repo password:
          {prefix}/{component}/{timestamp}/repo-password
        e.g. Backup/config/vm-forgejo-101/2026-06-01_03_00_00/repo-password
        """
        return f"{prefix}/{component}/{timestamp}/repo-password"

    @staticmethod
    def keepass_current_path(prefix: str, component: str) -> str:
        """
        KeePass alias pointing to the latest backup's key path:
          {prefix}/{component}/current
        """
        return f"{prefix}/{component}/current"

    # ── Restic snapshot tags ───────────────────────────────────────────────

    @staticmethod
    def snapshot_tags(
        cell_id: str,
        snapshot_set_id: str,
        component: str,
        layer: str,
        timestamp: str,
    ) -> list[str]:
        """
        Tags applied to every restic snapshot at creation.
        Queryable with: restic snapshots --tag component:vm-forgejo-101
        """
        return [
            f"cell:{cell_id}",
            f"set:{snapshot_set_id}",
            f"component:{component}",
            f"layer:{layer}",
            f"run:{timestamp}",
        ]


# ---------------------------------------------------------------------------
# SpaceProbe — available space checking
# ---------------------------------------------------------------------------

@dataclass
class SpaceInfo:
    available_bytes: int
    total_bytes: Optional[int] = None
    used_bytes: Optional[int] = None

    @property
    def available_gb(self) -> float:
        return self.available_bytes / (1024 ** 3)


class SpaceProbe:
    """
    Checks available storage space at backup destinations.
    Uses rclone `about` for remotes; os.statvfs for local paths.
    """

    def __init__(self, rclone_fn: Optional[Callable] = None):
        """
        rclone_fn: injectable function (path: str) -> (returncode, stdout, stderr)
        Used for rclone about calls; defaults to subprocess.
        """
        self._rclone_fn = rclone_fn or self._default_rclone

    @staticmethod
    def _default_rclone(remote_path: str) -> tuple[int, str, str]:
        result = subprocess.run(
            ["rclone", "about", remote_path, "--json"],
            capture_output=True, text=True, timeout=30,
        )
        return result.returncode, result.stdout, result.stderr

    def check(self, destination_type: str, path: str) -> Optional[SpaceInfo]:
        """
        Return SpaceInfo for the given destination, or None on failure.
        destination_type: "local" or any rclone-backed type
        path: local filesystem path, or rclone remote path like "b2:bucket/dir"
        """
        if destination_type == "local":
            return self._check_local(path)
        return self._check_rclone(path)

    def _check_local(self, path: str) -> Optional[SpaceInfo]:
        try:
            p = Path(path)
            p.mkdir(parents=True, exist_ok=True)
            st = os.statvfs(str(p))
            return SpaceInfo(
                available_bytes=st.f_bavail * st.f_frsize,
                total_bytes=st.f_blocks * st.f_frsize,
                used_bytes=(st.f_blocks - st.f_bfree) * st.f_frsize,
            )
        except Exception as exc:
            log.warning("Local space probe failed for %s: %s", path, exc)
            return None

    def _check_rclone(self, remote_path: str) -> Optional[SpaceInfo]:
        # rclone about needs the remote root, not a subdirectory
        # Extract remote prefix: "b2:bucket" from "b2:bucket/cell/layer/component"
        if ":" in remote_path:
            proto, rest = remote_path.split(":", 1)
            top = rest.split("/")[0]
            probe_target = f"{proto}:{top}"
        else:
            probe_target = remote_path

        rc, stdout, stderr = self._rclone_fn(probe_target)
        if rc != 0:
            log.warning("rclone about failed for %s: %s", probe_target, stderr.strip())
            return None
        try:
            data = json.loads(stdout)
            return SpaceInfo(
                available_bytes=data.get("free", 0),
                total_bytes=data.get("total"),
                used_bytes=data.get("used"),
            )
        except (json.JSONDecodeError, KeyError) as exc:
            log.warning("rclone about parse failed for %s: %s", probe_target, exc)
            return None


# ---------------------------------------------------------------------------
# ResticRunner — subprocess wrapper
# ---------------------------------------------------------------------------

class ResticRunner:
    """
    Thin wrapper around restic subprocess calls.
    Password is passed via RESTIC_PASSWORD env var (never in args).
    Accepts an injectable runner_fn for testing without restic installed.
    """

    def __init__(
        self,
        repo: str,
        password: str,
        runner_fn: Optional[Callable] = None,
        extra_env: Optional[dict] = None,
    ):
        self._repo = repo
        self._password = password
        # RESTIC_PASSWORD is the recommended restic authentication mechanism —
        # safer than --password-command or a file because it avoids disk writes
        # and CLI history exposure. Visible in /proc/[pid]/environ during the
        # subprocess's lifetime but only to processes running as the same user.
        self._env = {**os.environ, "RESTIC_PASSWORD": password, **(extra_env or {})}
        self._run = runner_fn or self._default_run

    @staticmethod
    def _default_run(cmd: list, env: dict, input_text: Optional[str] = None) -> tuple[int, str, str]:
        result = subprocess.run(
            cmd, env=env, capture_output=True, text=True,
            input=input_text, timeout=600,
        )
        return result.returncode, result.stdout, result.stderr

    def _exec(self, args: list, input_text: Optional[str] = None) -> tuple[int, str, str]:
        cmd = ["restic", "--repo", self._repo, "--no-lock"] + args
        return self._run(cmd, self._env, input_text)

    def init(self) -> tuple[bool, str]:
        """Initialise a new restic repository. Returns (ok, message)."""
        rc, out, err = self._exec(["init"])
        return rc == 0, (out + err).strip()

    def exists(self) -> bool:
        """Return True if the repository already exists."""
        rc, _, _ = self._exec(["cat", "config"])
        return rc == 0

    def backup(
        self,
        paths: list[str],
        tags: list[str],
        hostname: Optional[str] = None,
    ) -> tuple[bool, Optional[str], str]:
        """
        Run restic backup.
        Returns (ok, snapshot_id_or_None, message).
        """
        args = ["backup", "--json"] + paths
        for tag in tags:
            args += ["--tag", tag]
        if hostname:
            args += ["--hostname", hostname]
        rc, out, err = self._exec(args)
        if rc != 0:
            return False, None, (out + err).strip()
        # Extract snapshot ID from JSON output
        snapshot_id = None
        for line in out.splitlines():
            try:
                data = json.loads(line)
                if data.get("message_type") == "summary":
                    snapshot_id = data.get("snapshot_id")
            except json.JSONDecodeError:
                pass
        return True, snapshot_id, out.strip()

    def key_list(self) -> tuple[bool, list]:
        """Return (ok, list_of_key_dicts) — each dict has 'id' and 'current' fields."""
        rc, out, err = self._exec(["key", "list", "--json"])
        if rc != 0:
            return False, []
        try:
            return True, json.loads(out)
        except json.JSONDecodeError:
            return False, []

    def key_add(self, new_password: str) -> tuple[bool, str]:
        """Add a new password key to the repo. Returns (ok, message)."""
        rc, out, err = self._exec(["key", "add", "--new-password-command", "cat"],
                                   input_text=new_password + "\n")
        return rc == 0, (out + err).strip()

    def key_remove(self, key_id: str) -> tuple[bool, str]:
        """Remove a key from the repo by ID. Returns (ok, message)."""
        rc, out, err = self._exec(["key", "remove", key_id])
        return rc == 0, (out + err).strip()

    def stats(self) -> tuple[bool, dict]:
        """Return (ok, stats_dict) with total_size, total_file_count, etc."""
        rc, out, err = self._exec(["stats", "--json"])
        if rc != 0:
            return False, {}
        try:
            return True, json.loads(out)
        except json.JSONDecodeError:
            return False, {}

    def snapshots(self, tags: Optional[list[str]] = None) -> tuple[bool, list]:
        """List snapshots, optionally filtered by tags. Returns (ok, list_of_dicts)."""
        args = ["snapshots", "--json"]
        for tag in (tags or []):
            args += ["--tag", tag]
        rc, out, err = self._exec(args)
        if rc != 0:
            return False, []
        try:
            return True, json.loads(out)
        except json.JSONDecodeError:
            return False, []

    def forget(
        self,
        keep_last: int,
        checkpoint_tag: str = "checkpoint",
        prune: bool = True,
    ) -> tuple[bool, str]:
        """Apply retention policy, preserving checkpoint-tagged snapshots."""
        args = ["forget", f"--keep-last={keep_last}",
                f"--keep-tag={checkpoint_tag}"]
        if prune:
            args.append("--prune")
        rc, out, err = self._exec(args)
        return rc == 0, (out + err).strip()

    def restore(self, snapshot_id: str, target_path: str) -> tuple[bool, str]:
        """Restore a snapshot to target_path. Returns (ok, message)."""
        rc, out, err = self._exec(["restore", snapshot_id, "--target", target_path])
        return rc == 0, (out + err).strip()

    def check(self) -> tuple[bool, str]:
        """Run integrity check. Returns (ok, message)."""
        rc, out, err = self._exec(["check"])
        return rc == 0, (out + err).strip()


# ---------------------------------------------------------------------------
# RcloneRunner — subprocess wrapper
# ---------------------------------------------------------------------------

class RcloneRunner:
    """
    Thin wrapper around rclone subprocess calls.
    Accepts an injectable runner_fn for testing without rclone installed.
    """

    def __init__(self, runner_fn: Optional[Callable] = None):
        self._run = runner_fn or self._default_run

    @staticmethod
    def _default_run(cmd: list, env: Optional[dict] = None) -> tuple[int, str, str]:
        result = subprocess.run(
            cmd, env=env or os.environ,
            capture_output=True, text=True, timeout=300,
        )
        return result.returncode, result.stdout, result.stderr

    def copy(self, src: str, dst_dir: str, dst_filename: str) -> tuple[bool, str]:
        """
        Copy src file to dst_dir/dst_filename.
        Uses rclone copyto for precise destination naming.
        """
        dst = f"{dst_dir.rstrip('/')}/{dst_filename}"
        rc, out, err = self._run(["rclone", "copyto", src, dst])
        return rc == 0, (out + err).strip()

    def ls(self, path: str) -> tuple[bool, list]:
        """List files at a remote path. Returns (ok, list_of_filenames)."""
        rc, out, err = self._run(["rclone", "lsf", path])
        if rc != 0:
            return False, []
        return True, [line.strip() for line in out.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Passphrase generator for backup repo passwords
# ---------------------------------------------------------------------------

_WORDS = [
    "atlas", "beacon", "cipher", "delta", "ember", "forge", "graph", "helix",
    "index", "joule", "kernel", "layer", "matrix", "nexus", "orbit", "pivot",
    "quorum", "relay", "sigma", "token", "vault", "warden", "xenon", "yield",
    "zero", "amber", "bridge", "cedar", "drift", "epoch", "flare", "grove",
    "harbor", "inlet", "jasper", "karma", "ledge", "manor", "north", "ocean",
    "phase", "quartz", "ridge", "shore", "tidal", "ultra", "vista", "winter",
]

import random as _random


def generate_backup_passphrase() -> str:
    """
    Generate a readable passphrase for a restic repo password.
    Format: Capital.word.word.N  (20-30 chars, period separators, trailing digit)
    """
    rng = _random.SystemRandom()
    while True:
        words = rng.sample(_WORDS, 3)
        digit = rng.randint(1, 9)
        phrase = f"{words[0].capitalize()}.{words[1]}.{words[2]}.{digit}"
        if 20 <= len(phrase) <= 30:
            return phrase


# ---------------------------------------------------------------------------
# BackupResult — per-destination outcome
# ---------------------------------------------------------------------------

@dataclass
class DestinationResult:
    destination_id: str
    success: bool
    verified: bool = False
    error_message: str = ""
    snapshot_id: Optional[str] = None
    size_bytes: Optional[int] = None
    routed_reason: str = "primary"
    keepass_key_path: Optional[str] = None
    component_prefix: Optional[str] = None


@dataclass
class LayerRunResult:
    layer: str
    run_at: str
    snapshot_set_id: str
    destination_results: list[DestinationResult] = field(default_factory=list)

    @property
    def any_succeeded(self) -> bool:
        return any(r.success and r.verified for r in self.destination_results)

    @property
    def all_failed(self) -> bool:
        return not self.any_succeeded

    @property
    def succeeded_ids(self) -> list[str]:
        return [r.destination_id for r in self.destination_results if r.success and r.verified]

    @property
    def failed_ids(self) -> list[str]:
        return [r.destination_id for r in self.destination_results if not (r.success and r.verified)]

    def to_history_record(self) -> dict:
        return {
            "run_at":               self.run_at,
            "snapshot_set_id":      self.snapshot_set_id,
            "layer":                self.layer,
            "destinations_attempted": [r.destination_id for r in self.destination_results],
            "destinations_succeeded": self.succeeded_ids,
            "consecutive_all_fail_count": 0,  # updated by caller
            "components": [
                {
                    "component_id":       r.component_prefix or r.destination_id,
                    "component_prefix":   r.component_prefix or "",
                    "destination_id":     r.destination_id,
                    "restic_snapshot_id": r.snapshot_id,
                    "keepass_key_path":   r.keepass_key_path,
                    "size_bytes":         r.size_bytes,
                    "verified":           r.verified,
                    "routed_reason":      r.routed_reason,
                }
                for r in self.destination_results
            ],
        }


# ---------------------------------------------------------------------------
# BackupEngine
# ---------------------------------------------------------------------------

class BackupEngine:
    """
    Orchestrates backup runs for all configured layers.

    Relies on injectable ResticRunner/RcloneRunner factories and a SecretsProvider
    for KeePass integration. Tests inject mocks for all three.
    """

    def __init__(
        self,
        cell_id: str,
        backup_config: dict,
        restic_factory: Optional[Callable] = None,
        rclone_runner: Optional[RcloneRunner] = None,
        space_probe: Optional[SpaceProbe] = None,
        secrets_provider=None,
        now_fn: Optional[Callable] = None,
    ):
        """
        cell_id:          cell identity string
        backup_config:    the backup_config section from bootstrap-state.json
        restic_factory:   fn(repo, password, runner_fn) -> ResticRunner  (for injection)
        rclone_runner:    RcloneRunner instance (injectable)
        space_probe:      SpaceProbe instance (injectable)
        secrets_provider: object with get(path)->str and set(path, value)->None
        now_fn:           fn()->datetime (injectable for deterministic tests)
        """
        self._cell_id     = cell_id
        self._config      = backup_config
        self._restic_fac  = restic_factory or (lambda repo, pwd, rfn=None: ResticRunner(repo, pwd, rfn))
        self._rclone      = rclone_runner or RcloneRunner()
        self._space       = space_probe or SpaceProbe()
        self._secrets     = secrets_provider  # may be None (KeePass not yet integrated)
        self._now         = now_fn or _now_utc
        self._checkpoint_tag = backup_config.get("checkpoint_tag", "checkpoint")

    def _layer_config(self, layer: str) -> Optional[dict]:
        return (self._config.get("layers") or {}).get(layer)

    def _destinations(self, layer: str) -> list[dict]:
        lc = self._layer_config(layer)
        if not lc or not lc.get("enabled"):
            return []
        return lc.get("destinations") or []

    # ── Secrets layer (KeePass DB — rclone copy) ───────────────────────────

    def run_secrets_backup(self, kdbx_path: str) -> LayerRunResult:
        """
        Back up the KeePass database as a plain rclone copy to each destination.
        No restic layer (KeePass is already AES-256 encrypted).
        """
        now = self._now()
        ts  = _ts(now)
        run_hash = _uuid8()
        set_id = BackupNaming.snapshot_set_id(self._cell_id, ts, run_hash)
        result = LayerRunResult(layer="secrets", run_at=now.isoformat(), snapshot_set_id=set_id)

        destinations = self._destinations("secrets")
        if not destinations:
            log.warning("Secrets backup: no destinations configured")
            return result

        # Compute content hash for filename
        try:
            content = Path(kdbx_path).read_bytes()
            content_hash = _hash8(content)
        except OSError as exc:
            log.error("Cannot read KeePass DB at %s: %s", kdbx_path, exc)
            return result

        filename = BackupNaming.kdbx_filename(self._cell_id, ts, content_hash)

        for dest in destinations:
            dest_id   = dest["id"]
            dest_root = dest["kdbx_destination_root"]
            ok, msg   = self._rclone.copy(kdbx_path, dest_root, filename)
            dr = DestinationResult(
                destination_id=dest_id,
                success=ok,
                verified=ok,      # for rclone copy, success = verified
                error_message="" if ok else msg,
                component_prefix=BackupNaming.kdbx_prefix(),
                routed_reason="primary",
            )
            if not ok:
                log.warning("Secrets backup to '%s' FAILED: %s", dest_id, msg)
            else:
                log.info("Secrets backup to '%s' ✓ (%s)", dest_id, filename)
            result.destination_results.append(dr)

        if result.all_failed:
            log.error(
                "Secrets backup ALL DESTINATIONS FAILED — "
                "KeePass DB may be unprotected by external backup"
            )
        return result

    # ── Config / appdata layer (restic) ────────────────────────────────────

    def run_restic_backup(
        self,
        layer: str,
        component_prefix: str,
        source_paths: list[str],
        restic_runner_fn: Optional[Callable] = None,
    ) -> LayerRunResult:
        """
        Back up source_paths via restic to each configured destination for this layer.
        Per-backup unique key rotation: generate new password → key add → backup →
        verify → key remove old → store new password in KeePass (if available).
        """
        now    = self._now()
        ts     = _ts(now)
        run_hash = _uuid8()
        set_id = BackupNaming.snapshot_set_id(self._cell_id, ts, run_hash)
        result = LayerRunResult(layer=layer, run_at=now.isoformat(), snapshot_set_id=set_id)

        destinations = self._destinations(layer)
        if not destinations:
            log.warning("%s backup: no destinations configured", layer)
            return result

        tags = BackupNaming.snapshot_tags(self._cell_id, set_id, component_prefix, layer, ts)

        for dest in destinations:
            dest_id         = dest["id"]
            repo_root       = dest["restic_repo_root"]
            kp_prefix       = dest.get("restic_repo_password_keepass_prefix", f"Backup/{layer}")
            retention_count = dest.get("retention_count", 5)

            repo_path = BackupNaming.repo_path(repo_root, self._cell_id, layer, component_prefix)
            kp_path   = BackupNaming.keepass_key_path(kp_prefix, component_prefix, ts)

            # Generate a new unique password for this backup run
            new_password = generate_backup_passphrase()

            # Retrieve the current (previous) password if available
            old_password = None
            if self._secrets:
                current_path = BackupNaming.keepass_current_path(kp_prefix, component_prefix)
                try:
                    old_kp_path  = self._secrets.get(current_path)
                    if old_kp_path:
                        old_password = self._secrets.get(old_kp_path)
                except Exception:
                    pass

            # Use old_password if available to open repo; fall back to new_password for init
            repo_password = old_password or new_password
            runner = self._restic_fac(repo_path, repo_password, restic_runner_fn)

            # Ensure repo exists
            if not runner.exists():
                ok_init, msg_init = runner.init()
                if not ok_init:
                    log.error("restic init failed for '%s' at %s: %s", dest_id, repo_path, msg_init)
                    result.destination_results.append(DestinationResult(
                        destination_id=dest_id, success=False,
                        error_message=f"init failed: {msg_init}",
                        component_prefix=component_prefix,
                    ))
                    continue

            # Add the new key
            ok_add, msg_add = runner.key_add(new_password)
            if not ok_add:
                log.warning("key add failed for '%s': %s — using existing key", dest_id, msg_add)

            # Run the backup using the old password (repo still unlockable with it)
            ok_bkp, snap_id, msg_bkp = runner.backup(source_paths, tags)

            # Verify: repo stats must be readable
            verified = False
            size_bytes = None
            if ok_bkp:
                ok_stats, stats = runner.stats()
                verified   = ok_stats
                size_bytes = stats.get("total_size")

            if not ok_bkp or not verified:
                log.warning("restic backup to '%s' FAILED or unverified: %s", dest_id, msg_bkp)
                result.destination_results.append(DestinationResult(
                    destination_id=dest_id,
                    success=ok_bkp,
                    verified=verified,
                    error_message=msg_bkp if not ok_bkp else "stats verification failed",
                    snapshot_id=snap_id,
                    component_prefix=component_prefix,
                ))
                continue

            # Remove the old key (key rotation)
            if old_password and ok_add:
                # Switch runner to new password now that backup succeeded
                new_runner = self._restic_fac(repo_path, new_password, restic_runner_fn)
                ok_keys, keys = new_runner.key_list()
                if ok_keys:
                    # Remove all keys except the one marked current (new password)
                    for k in keys:
                        if not k.get("current"):
                            new_runner.key_remove(k["id"])

            # Store new password in KeePass
            if self._secrets:
                try:
                    self._secrets.set(kp_path, new_password)
                    current_path = BackupNaming.keepass_current_path(kp_prefix, component_prefix)
                    self._secrets.set(current_path, kp_path)
                except Exception as exc:
                    log.warning("KeePass write failed for %s: %s", kp_path, exc)

            # Apply retention policy
            runner2 = self._restic_fac(repo_path, new_password, restic_runner_fn)
            runner2.forget(keep_last=retention_count, checkpoint_tag=self._checkpoint_tag)

            log.info("restic backup to '%s' ✓ snapshot=%s size=%.1fMB",
                     dest_id, (snap_id or "?")[:12], (size_bytes or 0) / (1024 ** 2))

            result.destination_results.append(DestinationResult(
                destination_id=dest_id,
                success=True,
                verified=True,
                snapshot_id=snap_id,
                size_bytes=size_bytes,
                keepass_key_path=kp_path,
                component_prefix=component_prefix,
                routed_reason="primary",
            ))

        if result.all_failed:
            log.error(
                "%s backup ALL DESTINATIONS FAILED for component '%s' — "
                "this will surface as a RED readiness gap",
                layer, component_prefix,
            )
        return result


# ---------------------------------------------------------------------------
# RestoreEngine
# ---------------------------------------------------------------------------

class RestoreEngine:
    """
    Orchestrates restore from backup_history metadata.
    Resolves per-snapshot KeePass keys automatically (if secrets_provider available).
    """

    def __init__(
        self,
        cell_id: str,
        backup_config: dict,
        restic_factory: Optional[Callable] = None,
        rclone_runner: Optional[RcloneRunner] = None,
        secrets_provider=None,
    ):
        self._cell_id    = cell_id
        self._config     = backup_config
        self._restic_fac = restic_factory or (lambda repo, pwd, rfn=None: ResticRunner(repo, pwd, rfn))
        self._rclone     = rclone_runner or RcloneRunner()
        self._secrets    = secrets_provider

    def list_snapshot_sets(self) -> list[dict]:
        """
        Return a deduplicated list of snapshot set IDs from backup_history,
        most recent first.
        """
        history = self._config.get("backup_history") or []
        seen = set()
        sets = []
        for record in sorted(history, key=lambda r: r.get("run_at", ""), reverse=True):
            sid = record.get("snapshot_set_id")
            if sid and sid not in seen:
                seen.add(sid)
                sets.append({
                    "snapshot_set_id": sid,
                    "run_at":          record.get("run_at"),
                    "layer":           record.get("layer"),
                    "all_succeeded":   len(record.get("destinations_succeeded", [])) ==
                                       len(record.get("destinations_attempted", [])),
                })
        return sets

    def find_record_for_set(self, snapshot_set_id: str, layer: str) -> Optional[dict]:
        """Return the backup_history record for a given snapshot_set_id and layer."""
        for record in (self._config.get("backup_history") or []):
            if (record.get("snapshot_set_id") == snapshot_set_id and
                    record.get("layer") == layer):
                return record
        return None

    def restore_snapshot_set(
        self,
        snapshot_set_id: str,
        layer: str,
        target_dir: str,
        restic_runner_fn: Optional[Callable] = None,
        dry_run: bool = False,
    ) -> list[dict]:
        """
        Restore all components of a snapshot set.
        Returns a list of per-component result dicts.
        """
        record = self.find_record_for_set(snapshot_set_id, layer)
        if not record:
            log.error("No backup record found for set=%s layer=%s", snapshot_set_id, layer)
            return [{"error": f"No record for set={snapshot_set_id} layer={layer}"}]

        results = []
        destinations = {d["id"]: d for d in
                        ((self._config.get("layers") or {}).get(layer) or {}).get("destinations") or []}

        for comp in (record.get("components") or []):
            dest_id      = comp.get("destination_id")
            snap_id      = comp.get("restic_snapshot_id")
            kp_path      = comp.get("keepass_key_path")
            comp_prefix  = comp.get("component_prefix", "unknown")
            dest_config  = destinations.get(dest_id, {})

            repo_root    = dest_config.get("restic_repo_root", "")
            repo_path    = BackupNaming.repo_path(repo_root, self._cell_id, layer, comp_prefix)

            # Resolve password from KeePass
            password = None
            if self._secrets and kp_path:
                try:
                    password = self._secrets.get(kp_path)
                except Exception as exc:
                    log.warning("KeePass lookup failed for %s: %s", kp_path, exc)

            if not password:
                log.warning("No password available for %s — restore may fail", comp_prefix)
                password = "UNKNOWN"

            comp_target = str(Path(target_dir) / comp_prefix)

            if dry_run:
                log.info("[DRY RUN] Would restore %s from %s snapshot=%s → %s",
                         comp_prefix, dest_id, (snap_id or "latest")[:12], comp_target)
                results.append({"component": comp_prefix, "dry_run": True,
                                 "destination": dest_id, "snapshot_id": snap_id})
                continue

            runner = self._restic_fac(repo_path, password, restic_runner_fn)
            ok, msg = runner.restore(snap_id or "latest", comp_target)
            if ok:
                ok_check, check_msg = runner.check()
                log.info("Restore %s ✓ integrity=%s", comp_prefix, "ok" if ok_check else "warn")
            else:
                log.error("Restore %s FAILED from %s: %s", comp_prefix, dest_id, msg)

            results.append({
                "component":    comp_prefix,
                "destination":  dest_id,
                "snapshot_id":  snap_id,
                "target_dir":   comp_target,
                "success":      ok,
                "integrity_ok": ok if not ok else ok_check,
                "message":      msg,
            })

        return results
