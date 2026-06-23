#!/usr/bin/env python3
"""
credential_hierarchy.py — KeePass child database hierarchy manager (Phase 1.P).

Manages the credential hierarchy configuration that maps child KeePass databases
to their scope, file paths, and master entry locations.

Config file: $BROODFORGE_STATE_DIR/credential-hierarchy.json

Reference format: child://<db-name>/<group>/<entry-title>
  Examples:
    child://forge-autonomous/restic/repo-password
    child://forge-autonomous/k8s/service-account-token
    child://forge-spawn/cloud-init/node-keypair

CLI:
  python3 credential_hierarchy.py --list
  python3 credential_hierarchy.py --validate-ref "child://forge-autonomous/restic/repo-password"
  python3 credential_hierarchy.py --init
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ChildDatabase:
    name: str              # e.g. "forge-autonomous"
    path: Path             # /path/to/forge-autonomous.kdbx
    master_entry: str      # KeePass entry path in master: "Broodforge/child-dbs/forge-autonomous"
    scope_description: str # human-readable description of what credentials this DB holds


@dataclass
class CredentialHierarchy:
    master_db_path: Path
    child_databases: list[ChildDatabase] = field(default_factory=list)
    hierarchy_version: str = "1"


# ---------------------------------------------------------------------------
# Default child DB definitions (used by --init)
# ---------------------------------------------------------------------------

_DEFAULT_CHILD_DBS = [
    {
        "name": "forge-autonomous",
        "path": "/var/lib/broodforge/forge-autonomous.kdbx",
        "master_entry": "Broodforge/child-dbs/forge-autonomous",
        "scope_description": (
            "Autonomous operation credentials: restic repo password, "
            "k8s service account tokens, monitoring API keys, Headscale API key"
        ),
    },
    {
        "name": "forge-spawn",
        "path": "/var/lib/broodforge/forge-spawn.kdbx",
        "master_entry": "Broodforge/child-dbs/forge-spawn",
        "scope_description": (
            "Spawn-phase credentials: Cloud-Init keypairs, "
            "spawn-phase node credentials, Headscale pre-auth keys"
        ),
    },
    {
        "name": "forge-migrate",
        "path": "/var/lib/broodforge/forge-migrate.kdbx",
        "master_entry": "Broodforge/child-dbs/forge-migrate",
        "scope_description": (
            "Migration-phase credentials: temporary elevated access; "
            "mostly empty, populated during migration ceremony only"
        ),
    },
]


# ---------------------------------------------------------------------------
# HierarchyManager
# ---------------------------------------------------------------------------

class HierarchyManager:
    """Loads and saves the credential hierarchy config and validates references."""

    def __init__(
        self,
        config_path: Optional[Path] = None,
        now_fn=None,
    ) -> None:
        if config_path is None:
            state_dir = os.environ.get("BROODFORGE_STATE_DIR", "/var/lib/broodforge")
            config_path = Path(state_dir) / "credential-hierarchy.json"
        self.config_path = Path(config_path)
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    # ── Load / save ─────────────────────────────────────────────────────────

    def load(self) -> CredentialHierarchy:
        """Load hierarchy config from JSON. Raises FileNotFoundError if absent."""
        with open(self.config_path) as fh:
            data = json.load(fh)
        return self._from_dict(data)

    def save(self, hierarchy: CredentialHierarchy) -> None:
        """Atomically write hierarchy config to JSON."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.config_path.with_suffix(".json.tmp")
        try:
            with open(tmp, "w") as fh:
                json.dump(self._to_dict(hierarchy), fh, indent=2)
                fh.write("\n")
            tmp.replace(self.config_path)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

    # ── Query helpers ────────────────────────────────────────────────────────

    def list_child_dbs(self) -> list[ChildDatabase]:
        """Return all child databases from the loaded config."""
        return self.load().child_databases

    def get_child_db(self, name: str) -> Optional[ChildDatabase]:
        """Return the named child database, or None if not found."""
        for child in self.list_child_dbs():
            if child.name == name:
                return child
        return None

    def validate_reference(self, ref: str) -> tuple[str, str, str]:
        """Parse a child:// reference into (db_name, group, entry_title).

        Raises ValueError if:
        - the format is invalid (not child://db/group/entry)
        - the db-name is not present in the hierarchy config

        Returns (db_name, group, entry_title) on success.
        """
        if not ref.startswith("child://"):
            raise ValueError(
                f"Invalid reference format (must start with 'child://'): {ref!r}"
            )
        without_scheme = ref[len("child://"):]
        parts = without_scheme.split("/")
        if len(parts) < 3 or any(p == "" for p in parts):
            raise ValueError(
                f"Invalid reference format (need child://db/group/entry): {ref!r}"
            )
        db_name = parts[0]
        group = parts[1]
        entry_title = "/".join(parts[2:])

        # Verify the DB is declared in the hierarchy
        child = self.get_child_db(db_name)
        if child is None:
            known = [c.name for c in self.list_child_dbs()]
            raise ValueError(
                f"Unknown child DB {db_name!r} in reference {ref!r}. "
                f"Known databases: {known}"
            )
        return db_name, group, entry_title

    # ── Serialisation ────────────────────────────────────────────────────────

    @staticmethod
    def _to_dict(h: CredentialHierarchy) -> dict:
        return {
            "hierarchy_version": h.hierarchy_version,
            "master_db_path": str(h.master_db_path),
            "child_databases": [
                {
                    "name": c.name,
                    "path": str(c.path),
                    "master_entry": c.master_entry,
                    "scope_description": c.scope_description,
                }
                for c in h.child_databases
            ],
        }

    @staticmethod
    def _from_dict(data: dict) -> CredentialHierarchy:
        children = [
            ChildDatabase(
                name=c["name"],
                path=Path(c["path"]),
                master_entry=c["master_entry"],
                scope_description=c.get("scope_description", ""),
            )
            for c in data.get("child_databases", [])
        ]
        return CredentialHierarchy(
            hierarchy_version=data.get("hierarchy_version", "1"),
            master_db_path=Path(data.get("master_db_path", "")),
            child_databases=children,
        )

    # ── Init / skeleton ──────────────────────────────────────────────────────

    def init_skeleton(self, master_db_path: Optional[str] = None) -> CredentialHierarchy:
        """Create and save a skeleton hierarchy config with placeholder paths.

        Does not overwrite an existing config without --force.
        """
        if self.config_path.exists():
            raise FileExistsError(
                f"Config already exists: {self.config_path}. "
                "Remove it or use --force to overwrite."
            )
        state_dir = str(self.config_path.parent)
        resolved_master = master_db_path or f"{state_dir}/master.kdbx"

        children = [
            ChildDatabase(
                name=d["name"],
                path=Path(d["path"]),
                master_entry=d["master_entry"],
                scope_description=d["scope_description"],
            )
            for d in _DEFAULT_CHILD_DBS
        ]
        hierarchy = CredentialHierarchy(
            master_db_path=Path(resolved_master),
            child_databases=children,
        )
        self.save(hierarchy)
        return hierarchy


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cmd_list(manager: HierarchyManager) -> int:
    try:
        hierarchy = manager.load()
    except FileNotFoundError:
        print(
            f"No hierarchy config found at {manager.config_path}\n"
            "Run --init to create a skeleton config.",
            file=sys.stderr,
        )
        return 1

    print(f"Hierarchy version : {hierarchy.hierarchy_version}")
    print(f"Master DB         : {hierarchy.master_db_path}")
    print(f"Child databases   : {len(hierarchy.child_databases)}")
    print()
    for child in hierarchy.child_databases:
        exists_marker = "✓" if child.path.exists() else "✗ (not found)"
        print(f"  {child.name}")
        print(f"    path         : {child.path}  {exists_marker}")
        print(f"    master entry : {child.master_entry}")
        print(f"    scope        : {child.scope_description}")
        print()
    return 0


def _cmd_validate_ref(manager: HierarchyManager, ref: str) -> int:
    try:
        db_name, group, entry_title = manager.validate_reference(ref)
    except ValueError as exc:
        print(f"Invalid reference: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError:
        print(
            f"Hierarchy config not found: {manager.config_path}",
            file=sys.stderr,
        )
        return 1

    print(f"Reference : {ref}")
    print(f"  db_name     : {db_name}")
    print(f"  group       : {group}")
    print(f"  entry_title : {entry_title}")
    return 0


def _cmd_init(manager: HierarchyManager, master_db: Optional[str], force: bool) -> int:
    if force and manager.config_path.exists():
        manager.config_path.unlink()

    try:
        hierarchy = manager.init_skeleton(master_db_path=master_db)
    except FileExistsError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Created: {manager.config_path}")
    print()
    print("Skeleton credential hierarchy config written.")
    print("Edit the paths to match your actual .kdbx file locations, then run:")
    print("  python3 credential_hierarchy.py --list")
    print()
    print("Child databases to create:")
    for child in hierarchy.child_databases:
        print(f"  {child.name}  →  {child.path}")
    print()
    print("Run scripts/forge-init-credential-hierarchy.sh to create the .kdbx files.")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Broodforge credential hierarchy manager (Phase 1.P)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 credential_hierarchy.py --list
  python3 credential_hierarchy.py --validate-ref "child://forge-autonomous/restic/repo-password"
  python3 credential_hierarchy.py --init
  python3 credential_hierarchy.py --init --master-db /path/to/master.kdbx
""",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to credential-hierarchy.json (default: $BROODFORGE_STATE_DIR/credential-hierarchy.json)",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="List all child databases")
    group.add_argument(
        "--validate-ref",
        metavar="REF",
        help="Validate a child:// reference path",
    )
    group.add_argument(
        "--init",
        action="store_true",
        help="Create skeleton credential-hierarchy.json with placeholder paths",
    )
    parser.add_argument(
        "--master-db",
        default=None,
        help="Path to master KeePass database (used with --init)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing config (used with --init)",
    )

    args = parser.parse_args(argv)
    config_path = Path(args.config) if args.config else None
    manager = HierarchyManager(config_path=config_path)

    if args.list:
        return _cmd_list(manager)
    if args.validate_ref:
        return _cmd_validate_ref(manager, args.validate_ref)
    if args.init:
        return _cmd_init(manager, master_db=args.master_db, force=args.force)
    return 1  # unreachable


if __name__ == "__main__":
    sys.exit(main())
