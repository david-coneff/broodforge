#!/usr/bin/env python3
"""
secret_reference_state.py — Secret Reference State (Phase 18.5-18.6).

Manages the standalone secret reference registry. Secret references are
KeePass paths — never secret values. This module extracts references from
bootstrap-state.json (migration step 18.6) and provides the authoritative
secret reference state document.

Provides:
  SecretRefEntry              — single secret reference
  SecretReferenceState        — complete secret reference state for a cell
  migrate_from_bootstrap()    — extract references from bootstrap-state.json
  build_recovery_critical()   — identify secrets required for reconstruction
  secret_ref_state_to_dict()  — JSON-serialisable dict

Stdlib only.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SecretRefEntry:
    id:                   str
    keepass_path:         str
    owning_cell:          str
    name:                 Optional[str]   = None
    category:             Optional[str]   = None   # infrastructure/backup/k3s/service/external
    used_by:              list[str]       = field(default_factory=list)
    rotation_policy:      Optional[str]   = None   # manual/auto-90d/auto-30d/never
    last_rotated_at:      Optional[str]   = None
    expires_at:           Optional[str]   = None
    notes:                Optional[str]   = None
    required_for_recovery: bool           = False


@dataclass
class SecretReferenceState:
    cell_id:     str
    owning_cell: str
    declared_at: str
    secrets:     list[SecretRefEntry] = field(default_factory=list)
    last_updated_at: Optional[str]   = None
    collection_errors: list[dict]    = field(default_factory=list)

    def recovery_critical(self) -> list[SecretRefEntry]:
        return [s for s in self.secrets if s.required_for_recovery]

    def by_category(self, cat: str) -> list[SecretRefEntry]:
        return [s for s in self.secrets if s.category == cat]

    def recovery_critical_paths(self) -> list[str]:
        return [s.keepass_path for s in self.recovery_critical()]


# ---------------------------------------------------------------------------
# Migration from bootstrap-state.json (18.6)
# ---------------------------------------------------------------------------

def migrate_from_bootstrap(
    cell_id:         str,
    bootstrap_state: dict,
    now_fn: Optional[Callable[[], str]] = None,
) -> SecretReferenceState:
    """
    Extract secret references from bootstrap-state.json to produce a standalone
    SecretReferenceState document (Phase 18.6 migration).

    Sources:
      - secret_registry[]       → each entry becomes a SecretRefEntry
      - backup_config           → backup transport credentials
      - k3s_cluster join tokens → k3s join token paths
    """
    now = (now_fn or (lambda: datetime.now(timezone.utc).isoformat()))()
    state = SecretReferenceState(
        cell_id=cell_id,
        owning_cell=cell_id,
        declared_at=now,
    )
    refs: list[SecretRefEntry] = []
    seen_paths: set[str] = set()

    # From secret_registry (existing registry — already has KeePass paths)
    for entry in (bootstrap_state.get("secret_registry") or []):
        kp_path = entry.get("keepass_path") or entry.get("path")
        if not kp_path or kp_path in seen_paths:
            continue
        seen_paths.add(kp_path)
        refs.append(SecretRefEntry(
            id=entry.get("id") or kp_path.replace("/", "-"),
            keepass_path=kp_path,
            owning_cell=entry.get("owning_cell") or cell_id,
            name=entry.get("name"),
            category=_categorise_path(kp_path),
            used_by=_list(entry.get("used_by") or entry.get("services")),
            rotation_policy=entry.get("rotation_policy"),
            required_for_recovery=bool(entry.get("required_for_recovery", True)),
        ))

    # From forge_keepass_init defaults — add standard paths if not already present
    for std_path, name, cat, required in _STANDARD_SECRET_PATHS:
        if std_path not in seen_paths:
            seen_paths.add(std_path)
            refs.append(SecretRefEntry(
                id=std_path.replace("/", "-").lower(),
                keepass_path=std_path,
                owning_cell=cell_id,
                name=name,
                category=cat,
                required_for_recovery=required,
            ))

    state.secrets = refs
    return state


# Standard secret paths known to broodforge (from forge_keepass_init.py)
_STANDARD_SECRET_PATHS: list[tuple[str, str, str, bool]] = [
    ("Infrastructure/headscale/api-key",   "Headscale API key",          "infrastructure", True),
    ("Infrastructure/forgejo/admin-password", "Forgejo admin password",  "infrastructure", True),
    ("Infrastructure/proxmox/api-token",   "Proxmox API token",          "infrastructure", True),
    ("k3s/join-token-server",              "k3s server join token",      "k3s",            True),
    ("k3s/join-token-worker",              "k3s worker join token",      "k3s",            True),
    ("AssessmentEngine/api-key",           "Assessment Engine API key",  "infrastructure", False),
    ("Backup/config-state/current",        "Restic config-state key",    "backup",         False),
    ("Backup/secrets/current",             "Restic secrets layer key",   "backup",         False),
]


def _categorise_path(path: str) -> str:
    """Heuristically categorise a KeePass path."""
    lower = path.lower()
    if "k3s" in lower:
        return "k3s"
    if "backup" in lower or "restic" in lower:
        return "backup"
    if "external" in lower or "cloudflare" in lower or "duckdns" in lower:
        return "external"
    if any(k in lower for k in ("forgejo", "proxmox", "headscale", "assessment")):
        return "infrastructure"
    return "service"


def _list(v: Any) -> list[str]:
    if isinstance(v, list):
        return [str(x) for x in v]
    if isinstance(v, str):
        return [v]
    return []


# ---------------------------------------------------------------------------
# Recovery critical identification
# ---------------------------------------------------------------------------

def build_recovery_critical(state: SecretReferenceState) -> list[str]:
    """
    Return the list of KeePass paths required for cell reconstruction.

    These are the secrets that must be available at the KeePass gate before
    any recovery operation can proceed.
    """
    return state.recovery_critical_paths()


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def secret_ref_state_to_dict(state: SecretReferenceState) -> dict:
    """Convert SecretReferenceState to a JSON-serialisable dict."""
    return {
        "schema_version":   "1.0",
        "cell_id":          state.cell_id,
        "owning_cell":      state.owning_cell,
        "declared_at":      state.declared_at,
        "last_updated_at":  state.last_updated_at,
        "collection_errors": state.collection_errors,
        "secrets": [
            {
                "id":                   s.id,
                "name":                 s.name,
                "keepass_path":         s.keepass_path,
                "owning_cell":          s.owning_cell,
                "category":             s.category,
                "used_by":              s.used_by,
                "rotation_policy":      s.rotation_policy,
                "last_rotated_at":      s.last_rotated_at,
                "expires_at":           s.expires_at,
                "notes":                s.notes,
                "required_for_recovery": s.required_for_recovery,
            }
            for s in state.secrets
        ],
        "recovery_critical_paths": state.recovery_critical_paths(),
    }
