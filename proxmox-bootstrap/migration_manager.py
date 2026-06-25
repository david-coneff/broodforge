#!/usr/bin/env python3
"""
migration_manager.py — Schema versioning and migration runner (Phase 1.N).

Reads the current schema_version from bootstrap-state.json, discovers migration
scripts in the migrations/ directory, and runs them in version order using
importlib. Each migration script must expose:

    def run(state_dir: str) -> None

which modifies state files in place (including updating schema_version).

Schema version format
---------------------
Version strings use the format ``YYYY-MM-DD_HH-MM-SS_<7-char-hash>``, e.g.
``"2026-06-09_14-30-22_a3b4c5d"``.  The special sentinel ``"initial"``
represents state that pre-dates the versioning system (equivalent to the old
``"0.0"`` baseline).

Migration script naming
-----------------------
Because version strings themselves contain underscores, the filename separator
between from-version and to-version uses a double-underscore:

    migrate_<from>__to__<to>.py

Examples::

    migrate_initial__to__2026-06-09_00-00-00_0000000.py
    migrate_2026-06-09_00-00-00_0000000__to__2026-07-01_08-00-00_abc1234.py

Provides:
  CURRENT_SCHEMA_VERSION — the schema version this code was written against
  SchemaVersion          — comparable version wrapper
  MigrationRecord        — log entry written to migration-history.jsonl
  discover_migrations()  — find pending migration scripts in order
  load_migration()       — import a migration module by path
  read_schema_version()  — read schema_version from bootstrap-state.json
  run_migrations()       — apply all pending migrations
  append_migration_log() — write a MigrationRecord to migration-history.jsonl

CLI:
  python3 migration_manager.py --state-dir /var/lib/broodforge/
                               [--migrations-dir ./migrations/]
                               [--dry-run]

Exit codes:
  0 — nothing to do, or all migrations applied successfully
  1 — one or more migrations failed
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import sys
import warnings
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema version constant (loaded from version.py at import time)
# ---------------------------------------------------------------------------

def _load_schema_version() -> str:
    """Load SCHEMA_VERSION from version.py by reading the module attribute directly.

    On FileNotFoundError (version.py absent) returns the baseline fallback silently —
    the file may not exist yet on a fresh checkout.  On any other failure a
    warnings.warn() is emitted so corruption is visible rather than silently ignored.

    Accesses ``mod.SCHEMA_VERSION`` directly — version.py is a pure constants file
    updated by ``scripts/forge-stamp-version.sh`` and exposes no functions.
    """
    version_file = Path(__file__).parent / "version.py"
    _DEFAULT = "2026-06-09_00-00-00_0000000"  # noqa: N806
    try:
        spec = importlib.util.spec_from_file_location("_broodforge_version", version_file)
        if spec is not None and spec.loader is not None:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            return str(mod.SCHEMA_VERSION)
    except FileNotFoundError:
        pass  # version.py absent — return baseline silently
    except Exception as exc:
        warnings.warn(
            f"Cannot load SCHEMA_VERSION from version.py ({exc}) — using baseline fallback",
            stacklevel=2,
        )
    return _DEFAULT


CURRENT_SCHEMA_VERSION: str = _load_schema_version()
STATE_FILENAME: str = "bootstrap-state.json"
HISTORY_FILENAME: str = "migration-history.jsonl"


# ---------------------------------------------------------------------------
# SchemaVersion — comparable version wrapper
# ---------------------------------------------------------------------------

class SchemaVersion:
    """
    Comparable wrapper for timestamp+hash schema version strings.

    The canonical format is ``YYYY-MM-DD_HH-MM-SS_<7-char-hash>``, e.g.
    ``"2026-06-09_14-30-22_a3b4c5d"``.

    The special sentinel ``"initial"`` represents state that pre-dates the
    versioning system and sorts before all real versions.

    Ordering is by the timestamp prefix (``YYYY-MM-DD_HH-MM-SS``). The hash
    suffix is not used for ordering — two versions from the same second but
    different commits compare as equal.

    Examples
    --------
    >>> SchemaVersion.parse("initial") < SchemaVersion.parse("2026-06-09_00-00-00_0000000")
    True
    >>> SchemaVersion.parse("2026-06-01_00-00-00_aaaaaaa") < SchemaVersion.parse("2026-06-09_00-00-00_bbbbbbb")
    True
    >>> SchemaVersion.parse("2026-06-09_00-00-00_0000000") == SchemaVersion.parse("2026-06-09_00-00-00_0000000")
    True
    """

    __slots__ = ("raw",)

    def __init__(self, raw: str) -> None:
        self.raw = raw

    @classmethod
    def parse(cls, version_str: str) -> "SchemaVersion":
        """
        Parse a schema version string.

        Accepts ``"initial"`` or ``"YYYY-MM-DD_HH-MM-SS_<7-char-hash>"``.

        Raises
        ------
        ValueError
            If the format is invalid.
        """
        s = str(version_str).strip()
        if s == "initial":
            return cls(s)
        parts = s.split("_")
        if len(parts) != 3:
            raise ValueError(
                f"Invalid schema version {version_str!r}: expected "
                f"'YYYY-MM-DD_HH-MM-SS_<7-char-hash>' or 'initial' "
                f"(got {len(parts)} underscore-separated parts)"
            )
        date_str, time_str, hash_str = parts
        if len(date_str) != 10 or len(time_str) != 8 or len(hash_str) != 7:
            raise ValueError(
                f"Invalid schema version {version_str!r}: "
                f"expected date(10)_time(8)_hash(7), "
                f"got {len(date_str)}_{len(time_str)}_{len(hash_str)}"
            )
        try:
            y, m, d = date_str.split("-")
            int(y); int(m); int(d)
            h, mn, sec = time_str.split("-")
            int(h); int(mn); int(sec)
        except (ValueError, AttributeError) as exc:
            raise ValueError(
                f"Invalid schema version {version_str!r}: "
                f"date and time components must be numeric ({exc})"
            ) from exc
        return cls(s)

    def _sort_key(self) -> str:
        """Timestamp prefix used for ordering: '' for initial, 'YYYY-MM-DD_HH-MM-SS' otherwise."""
        if self.raw == "initial":
            return ""
        return self.raw[:19]  # "YYYY-MM-DD_HH-MM-SS" = 19 chars

    def __str__(self) -> str:
        return self.raw

    def __repr__(self) -> str:
        return f"SchemaVersion({self.raw!r})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, SchemaVersion):
            return self.raw == other.raw
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.raw)

    def __lt__(self, other: "SchemaVersion") -> bool:
        return self._sort_key() < other._sort_key()

    def __le__(self, other: "SchemaVersion") -> bool:
        return self._sort_key() <= other._sort_key()

    def __gt__(self, other: "SchemaVersion") -> bool:
        return self._sort_key() > other._sort_key()

    def __ge__(self, other: "SchemaVersion") -> bool:
        return self._sort_key() >= other._sort_key()


# ---------------------------------------------------------------------------
# MigrationRecord — written to migration-history.jsonl
# ---------------------------------------------------------------------------

@dataclass
class MigrationRecord:
    """One entry in the migration history log."""

    from_version: str
    to_version: str
    script: str
    ran_at: str
    success: bool
    dry_run: bool
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover_migrations(
    migrations_dir: Path,
    current_version: SchemaVersion,
) -> list[tuple[SchemaVersion, SchemaVersion, Path]]:
    """
    Find all migration scripts in *migrations_dir* that should run given the
    current schema version.

    A migration script is named ``migrate_<from>__to__<to>.py``.  The double
    underscore (``__to__``) separator disambiguates the boundary between the
    from-version and to-version, both of which may contain underscores.

    Returns the matching (from_version, to_version, path) tuples **sorted in
    version order** (ascending by from_version timestamp), filtered to those
    with from_version >= current_version.

    Parameters
    ----------
    migrations_dir:
        Directory containing ``migrate_*__to__*.py`` scripts.
    current_version:
        The schema version currently recorded in state.

    Returns
    -------
    list of (from_version, to_version, script_path) tuples in run order.
    """
    if not migrations_dir.exists():
        logger.warning("Migrations directory not found: %s", migrations_dir)
        return []

    pending: list[tuple[SchemaVersion, SchemaVersion, Path]] = []

    for script in sorted(migrations_dir.glob("migrate_*__to__*.py")):
        name = script.stem  # e.g. "migrate_initial__to__2026-06-09_00-00-00_0000000"
        without_prefix = name[len("migrate_"):]  # "initial__to__2026-06-09_00-00-00_0000000"
        try:
            from_str, to_str = without_prefix.split("__to__", 1)
            from_ver = SchemaVersion.parse(from_str)
            to_ver = SchemaVersion.parse(to_str)
        except (ValueError, AttributeError) as exc:
            logger.warning(
                "Skipping %s: cannot parse version from filename (%s)", script.name, exc
            )
            continue

        if from_ver >= current_version:
            pending.append((from_ver, to_ver, script))

    # Sort by from_version timestamp so migrations run in correct order
    pending.sort(key=lambda t: t[0])
    return pending


# ---------------------------------------------------------------------------
# State file I/O
# ---------------------------------------------------------------------------

def read_schema_version(state_dir: Path) -> SchemaVersion:
    """
    Read schema_version from bootstrap-state.json.

    Returns ``SchemaVersion("initial")`` if the file is missing or the field
    is absent, consistent with pre-migration state.
    """
    state_file = state_dir / STATE_FILENAME
    if not state_file.exists():
        logger.info(
            "bootstrap-state.json not found in %s — assuming version 'initial'", state_dir
        )
        return SchemaVersion.parse("initial")

    try:
        with open(state_file, encoding="utf-8") as fh:
            state: dict[str, Any] = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"Cannot read {state_file}: {exc}") from exc

    raw = state.get("schema_version", "initial")
    try:
        return SchemaVersion.parse(str(raw))
    except ValueError as exc:
        raise RuntimeError(
            f"Invalid schema_version {raw!r} in {state_file}: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Migration loader
# ---------------------------------------------------------------------------

def load_migration(script_path: Path) -> Any:
    """
    Import a migration script as a module using importlib.

    The module must expose ``def run(state_dir: str) -> None``.

    Returns the loaded module object.
    """
    spec = importlib.util.spec_from_file_location(
        f"_migration_{script_path.stem}", script_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot create module spec for {script_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    if not callable(getattr(mod, "run", None)):
        raise AttributeError(
            f"Migration {script_path.name} must expose a callable 'run(state_dir: str) -> None'"
        )
    return mod


# ---------------------------------------------------------------------------
# Log writer
# ---------------------------------------------------------------------------

def append_migration_log(
    state_dir: Path,
    record: MigrationRecord,
) -> None:
    """Append a MigrationRecord as a JSON line to migration-history.jsonl."""
    log_path = state_dir / HISTORY_FILENAME
    line = json.dumps(record.to_dict(), ensure_ascii=False)
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_migrations(
    state_dir: Path,
    migrations_dir: Path,
    *,
    dry_run: bool = False,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> bool:
    """
    Discover and apply all pending migrations.

    Parameters
    ----------
    state_dir:
        Path to the directory containing bootstrap-state.json.
    migrations_dir:
        Path to the directory containing migrate_*__to__*.py scripts.
    dry_run:
        If True, print what would run but do not execute.
    clock:
        Callable returning the current UTC datetime (injected for testing).

    Returns
    -------
    True if all migrations applied successfully (or nothing to do), False on error.
    """
    current_version = read_schema_version(state_dir)
    pending = discover_migrations(migrations_dir, current_version)

    if not pending:
        print("State at current schema version — nothing to do")
        return True

    print(f"Current schema version: {current_version}")
    print(f"Found {len(pending)} pending migration(s):")
    for from_ver, to_ver, script in pending:
        print(f"  {from_ver} → {to_ver}  ({script.name})")

    if dry_run:
        print("[dry-run] No migrations were executed.")
        return True

    all_ok = True
    for from_ver, to_ver, script in pending:
        ran_at = clock().strftime("%Y-%m-%dT%H:%M:%SZ")
        print(f"\n[migrate] Running {script.name} ({from_ver} → {to_ver}) ...")
        try:
            mod = load_migration(script)
            mod.run(str(state_dir))
            record = MigrationRecord(
                from_version=str(from_ver),
                to_version=str(to_ver),
                script=script.name,
                ran_at=ran_at,
                success=True,
                dry_run=False,
            )
            append_migration_log(state_dir, record)
            print(f"[migrate] {script.name} succeeded.")
        except Exception as exc:  # noqa: BLE001
            logger.error("Migration %s failed: %s", script.name, exc)
            record = MigrationRecord(
                from_version=str(from_ver),
                to_version=str(to_ver),
                script=script.name,
                ran_at=ran_at,
                success=False,
                dry_run=False,
                error=str(exc),
            )
            append_migration_log(state_dir, record)
            print(f"[migrate] ERROR: {script.name} failed: {exc}", file=sys.stderr)
            all_ok = False
            break  # stop on first failure

    return all_ok


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI arguments with argparse.

    Using argparse eliminates the IndexError that the previous manual argv-indexing
    implementation raised when ``--state-dir`` or ``--migrations-dir`` was the
    final token (missing the required path value).  argparse handles missing values,
    unknown arguments, and ``--help`` correctly.
    """
    parser = argparse.ArgumentParser(
        prog="migration_manager.py",
        description="Apply schema migrations to broodforge bootstrap state.",
    )
    parser.add_argument(
        "--state-dir",
        dest="state_dir",
        default=None,
        metavar="PATH",
        help="Path to the directory containing bootstrap-state.json (required).",
    )
    parser.add_argument(
        "--migrations-dir",
        dest="migrations_dir",
        default=None,
        metavar="PATH",
        help="Path to the migrations directory (default: <repo>/migrations).",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Print pending migrations but do not execute them.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="[%(levelname)s] %(message)s")

    raw = argv if argv is not None else sys.argv[1:]
    args = _parse_args(raw)

    if args.state_dir is None:
        print("Usage: migration_manager.py --state-dir <path> [--migrations-dir <path>] [--dry-run]",
              file=sys.stderr)
        return 1

    state_dir = Path(args.state_dir)
    if not state_dir.exists():
        print(f"ERROR: state-dir does not exist: {state_dir}", file=sys.stderr)
        return 1

    # ---------------------------------------------------------------------------
    # AD-065: Migration requires operator presence.
    # forge-quiesce.sh creates migration.lock and calls forge_keepass_gate()
    # before any migration action.  migration_manager.py must not run without
    # that lock — direct invocation bypasses the KeePass operator-presence gate.
    # ---------------------------------------------------------------------------
    lock_file = state_dir / "migration.lock"
    if not lock_file.exists():
        print(
            f"ERROR: migration.lock not found at {lock_file}\n"
            "AD-065: Migration requires operator presence (KeePass gate in forge-quiesce.sh).\n"
            "Run 'sudo bash scripts/forge-quiesce.sh' before invoking migration_manager.py,\n"
            "or use 'sudo bash scripts/forge-migrate.sh' which handles quiesce automatically.",
            file=sys.stderr,
        )
        return 1

    # Default migrations dir: <repo_root>/migrations/ relative to this script
    if args.migrations_dir is not None:
        migrations_dir = Path(args.migrations_dir)
    else:
        migrations_dir = Path(__file__).parent.parent / "migrations"

    ok = run_migrations(
        state_dir,
        migrations_dir,
        dry_run=args.dry_run,
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
