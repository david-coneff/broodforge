#!/usr/bin/env python3
"""
twin_state_writer.py — Digital Twin state writer (Phase 17.3 + 17.4).

All state collectors write their output to the digital twin directory tree
(`twin/`) in addition to / instead of `history/`. The twin is the single
source of truth for all state categories.

Twin directory layout (17.2):
  twin/
    cells/
      {cell_id}/
        identity.json                  Cell Identity (17.1)
        state/
          bootstrap.json               Bootstrap state (from proxmox-bootstrap/)
          hardware.json                Hardware state (Phase 13)
          platform.json                Platform state (Phase 13)
          cluster.json                 Cluster state (Phase 14)
          storage.json                 Storage state (Phase 14)
          data-protection.json         Data Protection state (Phase 15)
          observability.json           Observability state (Phase 16)
        staleness.json                 Per-field staleness manifest (Phase 17.4)

Provides:
  TwinPaths          — canonical path builder for any cell
  TwinStateWriter    — writes any state dict to its twin location
  StalenessEntry     — per-field staleness record
  StalenessManifest  — collection of StalenessEntry for one cell
  read_staleness()   — read existing staleness manifest
  update_staleness() — update staleness after a write
  write_cell_identity() — write or update cell identity record

Stdlib only.
"""

import json
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# State category constants
# ---------------------------------------------------------------------------

STATE_BOOTSTRAP       = "bootstrap"
STATE_HARDWARE        = "hardware"
STATE_PLATFORM        = "platform"
STATE_CLUSTER         = "cluster"
STATE_STORAGE         = "storage"
STATE_DATA_PROTECTION = "data-protection"
STATE_OBSERVABILITY   = "observability"

ALL_STATE_CATEGORIES = [
    STATE_BOOTSTRAP,
    STATE_HARDWARE,
    STATE_PLATFORM,
    STATE_CLUSTER,
    STATE_STORAGE,
    STATE_DATA_PROTECTION,
    STATE_OBSERVABILITY,
]

# Staleness thresholds (seconds) — how long until a state category is stale
STALENESS_THRESHOLDS = {
    STATE_BOOTSTRAP:       7 * 24 * 3600,   # 7 days
    STATE_HARDWARE:       30 * 24 * 3600,   # 30 days
    STATE_PLATFORM:        1 * 24 * 3600,   # 1 day
    STATE_CLUSTER:         1 * 24 * 3600,   # 1 day
    STATE_STORAGE:         1 * 24 * 3600,   # 1 day
    STATE_DATA_PROTECTION: 1 * 24 * 3600,   # 1 day
    STATE_OBSERVABILITY:   1 * 3600,        # 1 hour
}


# ---------------------------------------------------------------------------
# TwinPaths — canonical path builder
# ---------------------------------------------------------------------------

class TwinPaths:
    """Resolve canonical twin filesystem paths for a given cell."""

    def __init__(self, twin_root: str, cell_id: str):
        self.root    = Path(twin_root)
        self.cell_id = cell_id

    @property
    def cell_dir(self) -> Path:
        return self.root / "cells" / self.cell_id

    @property
    def state_dir(self) -> Path:
        return self.cell_dir / "state"

    @property
    def identity_path(self) -> Path:
        return self.cell_dir / "identity.json"

    @property
    def staleness_path(self) -> Path:
        return self.cell_dir / "staleness.json"

    def state_path(self, category: str) -> Path:
        return self.state_dir / f"{category}.json"

    def all_state_paths(self) -> dict[str, Path]:
        return {cat: self.state_path(cat) for cat in ALL_STATE_CATEGORIES}


# ---------------------------------------------------------------------------
# StalenessEntry + StalenessManifest (Phase 17.4)
# ---------------------------------------------------------------------------

@dataclass
class StalenessEntry:
    """Per-category staleness record in the digital twin."""
    category:          str
    last_written_at:   Optional[str]   = None   # ISO timestamp
    last_collected_at: Optional[str]   = None   # from the state document
    sha256:            Optional[str]   = None   # SHA-256 of last written content
    is_stale:          bool            = False
    stale_since:       Optional[str]   = None
    staleness_age_sec: Optional[int]   = None
    threshold_sec:     int             = 86400


@dataclass
class StalenessManifest:
    """Per-cell staleness manifest for all state categories."""
    cell_id:    str
    updated_at: str
    entries:    list[StalenessEntry] = field(default_factory=list)

    def get_entry(self, category: str) -> Optional[StalenessEntry]:
        return next((e for e in self.entries if e.category == category), None)

    def stale_categories(self) -> list[str]:
        return [e.category for e in self.entries if e.is_stale]

    def missing_categories(self) -> list[str]:
        present = {e.category for e in self.entries}
        return [c for c in ALL_STATE_CATEGORIES if c not in present]


# ---------------------------------------------------------------------------
# TwinStateWriter (Phase 17.3)
# ---------------------------------------------------------------------------

class TwinStateWriter:
    """
    Writes any state dict to its canonical twin location and updates staleness.
    """

    def __init__(self, twin_root: str, cell_id: str):
        self.paths = TwinPaths(twin_root, cell_id)

    def write_state(self, category: str, state_dict: dict) -> Path:
        """
        Write state_dict to twin/cells/{cell_id}/state/{category}.json.
        Creates directories as needed. Returns the path written.
        """
        self.paths.state_dir.mkdir(parents=True, exist_ok=True)
        path = self.paths.state_path(category)
        content = json.dumps(state_dict, indent=2, ensure_ascii=False)
        path.write_text(content, encoding="utf-8")
        return path

    def read_state(self, category: str) -> Optional[dict]:
        """Read a state category from the twin. Returns None if not present."""
        path = self.paths.state_path(category)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def write_all(self, state_map: dict[str, dict]) -> dict[str, Path]:
        """
        Write multiple state categories at once.
        state_map: {category: state_dict}
        Returns {category: path_written}.
        """
        return {cat: self.write_state(cat, state) for cat, state in state_map.items()}

    def update_staleness(self, now_fn: Optional[Any] = None) -> StalenessManifest:
        """
        Scan written state files, compute staleness, and write staleness.json.
        Returns the updated StalenessManifest.
        """
        now_str = (now_fn or (lambda: datetime.now(timezone.utc).isoformat()))()
        now_ts  = datetime.fromisoformat(now_str.replace("Z", "+00:00"))
        manifest = update_staleness(self.paths, now_ts)
        _write_staleness(self.paths, manifest)
        return manifest

    def write_cell_identity(self, identity_dict: dict) -> Path:
        """Write or update the cell identity record."""
        self.paths.cell_dir.mkdir(parents=True, exist_ok=True)
        path = self.paths.identity_path
        content = json.dumps(identity_dict, indent=2, ensure_ascii=False)
        path.write_text(content, encoding="utf-8")
        return path

    def read_cell_identity(self) -> Optional[dict]:
        """Read the cell identity record. Returns None if not present."""
        path = self.paths.identity_path
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None


# ---------------------------------------------------------------------------
# Staleness computation (Phase 17.4)
# ---------------------------------------------------------------------------

def update_staleness(
    paths:  TwinPaths,
    now_ts: Optional[datetime] = None,
) -> StalenessManifest:
    """
    Compute the staleness manifest from the current twin state files.

    Returns an updated StalenessManifest without writing it.
    """
    if now_ts is None:
        now_ts = datetime.now(timezone.utc)
    now_str = now_ts.isoformat()

    entries: list[StalenessEntry] = []
    for category in ALL_STATE_CATEGORIES:
        threshold = STALENESS_THRESHOLDS.get(category, 86400)
        path      = paths.state_path(category)

        if not path.exists():
            continue

        try:
            raw     = path.read_text(encoding="utf-8")
            sha256  = "sha256:" + hashlib.sha256(raw.encode()).hexdigest()
            state   = json.loads(raw)
            written = path.stat().st_mtime
            written_ts = datetime.fromtimestamp(written, tz=timezone.utc)

            # collected_at from inside the state doc
            collected_at = state.get("collected_at") or state.get("generated_at")

            # Compute age from file mtime (most reliable)
            age_sec = int((now_ts - written_ts).total_seconds())
            is_stale = age_sec > threshold

            entries.append(StalenessEntry(
                category=category,
                last_written_at=written_ts.isoformat(),
                last_collected_at=collected_at,
                sha256=sha256,
                is_stale=is_stale,
                stale_since=(
                    (written_ts + timedelta(seconds=threshold)).isoformat()
                    if is_stale else None
                ),
                staleness_age_sec=age_sec if is_stale else None,
                threshold_sec=threshold,
            ))
        except (OSError, json.JSONDecodeError, Exception):
            continue

    return StalenessManifest(cell_id=paths.cell_id, updated_at=now_str, entries=entries)


def read_staleness(paths: TwinPaths) -> Optional[StalenessManifest]:
    """Read the persisted staleness manifest. Returns None if not present."""
    path = paths.staleness_path
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = [
            StalenessEntry(**{k: v for k, v in e.items() if k in StalenessEntry.__dataclass_fields__})
            for e in (data.get("entries") or [])
        ]
        return StalenessManifest(
            cell_id=data.get("cell_id", paths.cell_id),
            updated_at=data.get("updated_at", ""),
            entries=entries,
        )
    except (json.JSONDecodeError, OSError, TypeError):
        return None


def _write_staleness(paths: TwinPaths, manifest: StalenessManifest) -> Path:
    """Persist the staleness manifest to twin/cells/{cell_id}/staleness.json."""
    paths.cell_dir.mkdir(parents=True, exist_ok=True)
    path = paths.staleness_path
    data = {
        "cell_id":    manifest.cell_id,
        "updated_at": manifest.updated_at,
        "entries": [
            {
                "category":          e.category,
                "last_written_at":   e.last_written_at,
                "last_collected_at": e.last_collected_at,
                "sha256":            e.sha256,
                "is_stale":          e.is_stale,
                "stale_since":       e.stale_since,
                "staleness_age_sec": e.staleness_age_sec,
                "threshold_sec":     e.threshold_sec,
            }
            for e in manifest.entries
        ],
    }
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Cell identity builder (Phase 17.1)
# ---------------------------------------------------------------------------

def build_cell_identity(
    forge_manifest: dict,
    now_fn: Optional[Any] = None,
) -> dict:
    """
    Build a cell identity dict from a forge manifest.

    This is the initial cell identity record — it will be updated as the
    twin state grows (node_count, capabilities, etc.).
    """
    now = (now_fn or (lambda: datetime.now(timezone.utc).isoformat()))()
    hi  = forge_manifest.get("host_identity") or {}
    nt  = forge_manifest.get("network_topology") or {}
    wan = nt.get("wan_config") or {}

    cell_id  = forge_manifest.get("cell_id") or hi.get("cell_id") or "unknown-cell"
    hostname = hi.get("hostname") or "unknown"
    fqdn     = hi.get("fqdn") or f"{hostname}.home.example.com"

    return {
        "schema_version": "1.0",
        "cell_id":        cell_id,
        "registered_at":  now,
        "last_updated_at": now,
        "host_identity": {
            "hostname":  hostname,
            "domain":    hi.get("domain"),
            "fqdn":      fqdn,
            "lan_ip":    None,
            "wan_ip":    None,
            "tailnet_ip": None,
            "timezone":  hi.get("timezone"),
        },
        "network_profile":       nt.get("profile"),
        "headscale_url":         wan.get("headscale_url"),
        "forgejo_url":           None,
        "assessment_engine_url": None,
        "node_count":            None,
        "k3s_server_count":      None,
        "k3s_worker_count":      None,
        "capabilities":          [],
        "federation_trust":      {},
        "twin_state_paths": {
            cat: f"twin/cells/{cell_id}/state/{cat}.json"
            for cat in ALL_STATE_CATEGORIES
        },
        "forge_manifest_sha256": None,
    }
