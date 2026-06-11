#!/usr/bin/env python3
"""
package_verifier.py — Deterministic content-hash verifier for the broodforge package.

Implements a **dual-descriptor** integrity model:

  package-descriptor.json  — SHA-256 over static source files (this module's
                             original function); updated at release time by
                             forge-stamp-version.sh.

  state-descriptor.json    — SHA-256 over operational state files (manifest.toml,
                             bootstrap-state.json, active migration scripts, etc.);
                             updated after any state-mutating operation (spawn,
                             phoenix restore, migration) by forge-stamp-state.sh.

MUTUAL EXCLUSION (critical — prevents self-reference loops):
  Package hash excludes: state-descriptor.json, package-descriptor.json,
                         all .json/.jsonl/.toml files.
  State hash excludes:   package-descriptor.json, state-descriptor.json,
                         all .py/.sh/.md source files.
  Neither descriptor is ever included in the other's content set.

Package hash scope
------------------
Only **static source files** are hashed — files that are identical on every
deployment of a given package version and never modified after install.  This
means that even a running deployed instance can verify its own integrity at any
time without false positives from runtime state changes.

INCLUDED in package hash (static source, shipped with the package):
  - All ``.py`` files under ``proxmox-bootstrap/``, ``engine/``, ``tests/``,
    ``migrations/`` (migration scripts only — not *.jsonl history logs)
  - All ``.sh`` files under ``scripts/``, ``lib/``, ``assessment/``, ``tools/``
  - ``migrations/README.md`` and other ``*.md`` docs shipped with the package

EXCLUDED from package hash (runtime state or operator-configured files):
  - ``*.json``           — state files (bootstrap-state.json, etc.) change at runtime
  - ``*.jsonl``          — migration history logs (migration-history.jsonl)
  - ``*.log``            — log output
  - ``*.toml``           — operator-configured files (manifest.toml, answer.toml)
  - ``*.lock``           — lock files (migration.lock)
  - ``.secrets.baseline``— updated by automated security scans
  - ``__pycache__/``     — compiled bytecode (Python)
  - ``*.pyc``, ``*.pyo`` — compiled bytecode
  - ``.audit/``          — generated audit reports
  - ``backups/``         — pre-migration backup copies of state
  - ``package-descriptor.json``  — CRITICAL: the descriptor records the hash of
    everything else; including it would be circular (you cannot know the hash
    before writing it, but writing it changes the hash).
  - ``state-descriptor.json``    — MUTUAL EXCLUSION: state descriptor must not
    appear in the package hash (separate concern, separate descriptor).

State hash scope
----------------
Covers operational/stateful content that defines "what this deployment is running":

INCLUDED in state hash:
  - ``*.json`` files directly in state_dir (manifest.toml, bootstrap-state.json, etc.)
  - ``*.toml`` files directly in state_dir
  - ``migrations/migrate_initial__to__*.py`` — the active migration script

EXCLUDED from state hash:
  - ``package-descriptor.json`` — MUTUAL EXCLUSION: base package descriptor
  - ``state-descriptor.json``   — MUTUAL EXCLUSION: self-reference loop
  - ``migration-history.jsonl`` — append-only run log, not current state
  - ``*.lock``                  — transient lock files
  - Files under ``backups/``    — snapshots, not current state
  - All ``.py``/``.sh``/``.md`` — source files (those are in the package hash)

The file list is sorted lexicographically before hashing so the digest is
deterministic regardless of filesystem enumeration order.

CLI:
  python3 package_verifier.py --stamp                       write / update package-descriptor.json
  python3 package_verifier.py --verify                      check package hash vs descriptor
  python3 package_verifier.py --stamp-state [--state-dir P] write / update state-descriptor.json
  python3 package_verifier.py --verify-state [--state-dir P] check state hash vs descriptor

Exit codes (--verify / --verify-state):
  0 — hash matches descriptor
  1 — hash mismatch
  2 — descriptor not found (run --stamp / --stamp-state first)

Stdlib only.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent
THIS_DIR = Path(__file__).parent

# The descriptor file — EXCLUDED from the hash computation (see module docstring).
DESCRIPTOR_PATH = THIS_DIR / "package-descriptor.json"

# ---------------------------------------------------------------------------
# Hash scope: include and exclude sets (see module docstring for rationale)
# ---------------------------------------------------------------------------

# Glob specs: (base_directory, glob_pattern)
# Only patterns for static source files are listed here.  Runtime state files
# (.json, .jsonl, .log, .toml, .lock) cannot match these patterns, but they
# are also checked explicitly in _collect_files() so the boundary is clear even
# if glob patterns are ever extended.
_CONTENT_GLOBS: list[tuple[Path, str]] = [
    # Python source — shipped code and migration scripts (*.jsonl logs excluded by glob)
    (REPO_ROOT / "proxmox-bootstrap", "**/*.py"),
    (REPO_ROOT / "engine",            "**/*.py"),
    (REPO_ROOT / "tests",             "**/*.py"),
    (REPO_ROOT / "migrations",        "*.py"),
    # Shell scripts
    (REPO_ROOT / "scripts",           "*.sh"),
    (REPO_ROOT / "lib",               "*.sh"),
    (REPO_ROOT / "assessment",        "**/*.sh"),
    (REPO_ROOT / "tools",             "**/*.sh"),
    # Documentation shipped with the package
    (REPO_ROOT / "migrations",        "*.md"),   # migrations/README.md
]

# Directories whose contents are never static source — skip any file whose
# path includes one of these directory names.
_EXCLUDED_DIR_COMPONENTS: frozenset[str] = frozenset({
    "__pycache__",  # compiled Python bytecode
    ".audit",       # generated audit reports
    "backups",      # pre-migration backup copies of runtime state
})

# File suffixes that indicate runtime-generated or operator-configured content.
# Kept explicit even though current globs don't produce these extensions, so
# the boundary remains unambiguous if globs are ever extended.
_EXCLUDED_SUFFIXES: frozenset[str] = frozenset({
    ".pyc",    # compiled Python bytecode
    ".pyo",    # optimised compiled Python bytecode
    ".json",   # runtime state files (bootstrap-state.json, etc.)
    ".jsonl",  # migration history logs (migration-history.jsonl)
    ".log",    # log output
    ".lock",   # lock files (migration.lock)
    ".toml",   # operator-configured files (manifest.toml, answer.toml)
})

# Specific filenames to exclude regardless of location.
_EXCLUDED_NAMES: frozenset[str] = frozenset({
    ".secrets.baseline",   # updated by automated security scans — not static
    # MUTUAL EXCLUSION: the state descriptor must never appear in the package hash.
    # The two descriptors cover separate concerns (source vs. state); mixing them
    # would create a cross-contamination between the two integrity boundaries.
    "state-descriptor.json",
})


# ---------------------------------------------------------------------------
# Version loading
# ---------------------------------------------------------------------------

def _load_schema_version() -> str:
    """Load SCHEMA_VERSION from version.py by reading the module attribute directly.

    On FileNotFoundError (version.py absent) returns the baseline fallback silently —
    the file may not exist yet on a fresh checkout.  On any other failure a
    warnings.warn() is emitted so corruption is visible rather than silently ignored.

    Accesses ``mod.SCHEMA_VERSION`` directly — version.py is a pure constants file
    updated by ``scripts/forge-stamp-version.sh`` and exposes no functions.
    """
    version_file = THIS_DIR / "version.py"
    _DEFAULT = "2026-06-09_00-00-00_0000000"
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


# ---------------------------------------------------------------------------
# File collection
# ---------------------------------------------------------------------------

def _collect_files() -> list[Path]:
    """
    Return a sorted list of absolute paths for all static source files to hash.

    Only static source files are hashed so integrity can be verified on a
    deployed instance without false positives from runtime state changes.
    See module docstring for the full include/exclude boundary.

    Exclusions enforced:
    - Directories in _EXCLUDED_DIR_COMPONENTS (__pycache__, .audit, backups)
    - File suffixes in _EXCLUDED_SUFFIXES (.pyc, .json, .jsonl, .log, .lock, .toml)
    - Specific filenames in _EXCLUDED_NAMES (.secrets.baseline, state-descriptor.json)
    - ``package-descriptor.json`` itself (circular — records our own hash)
    - ``state-descriptor.json`` excluded by _EXCLUDED_NAMES (MUTUAL EXCLUSION)
    """
    descriptor_resolved = DESCRIPTOR_PATH.resolve()
    files: set[Path] = set()

    for base, pattern in _CONTENT_GLOBS:
        if not base.exists():
            continue
        for p in base.glob(pattern):
            if not p.is_file():
                continue
            # Skip runtime-state or generated-content directories.
            if any(part in _EXCLUDED_DIR_COMPONENTS for part in p.parts):
                continue
            # Skip runtime-state file types (explicit even when globs don't
            # produce these extensions, so the boundary is unambiguous).
            if p.suffix in _EXCLUDED_SUFFIXES:
                continue
            # Skip specific files that change at runtime (e.g. .secrets.baseline).
            if p.name in _EXCLUDED_NAMES:
                continue
            # CRITICAL: exclude the descriptor file itself to avoid circular
            # dependency.  The descriptor records the hash of all other files;
            # including it would make writing the descriptor invalidate the hash
            # it records.
            if p.resolve() == descriptor_resolved:
                continue
            files.add(p.resolve())

    return sorted(files)


def _relative(path: Path) -> str:
    """Return path relative to REPO_ROOT, or the absolute path as fallback."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# Hash computation
# ---------------------------------------------------------------------------

def compute_hash(files: Optional[list[Path]] = None) -> tuple[str, list[str]]:
    """
    Compute a deterministic SHA-256 digest over *files*.

    If *files* is None, ``_collect_files()`` is called automatically.

    The algorithm feeds each file's relative path (as a UTF-8 string + newline)
    followed by the file's raw bytes + newline into the hasher, in sorted order.
    This makes the digest sensitive to both file content and relative path.

    Returns
    -------
    (hexdigest, sorted_relative_paths)
    """
    if files is None:
        files = _collect_files()

    # Sort by relative path for determinism
    sorted_files = sorted(files, key=_relative)

    h = hashlib.sha256()
    rel_paths: list[str] = []

    for f in sorted_files:
        rel = _relative(f)
        rel_paths.append(rel)
        # Feed path label so renaming a file changes the hash
        h.update(rel.encode("utf-8"))
        h.update(b"\n")
        # Feed file contents
        h.update(f.read_bytes())
        h.update(b"\n")

    return h.hexdigest(), rel_paths


# ---------------------------------------------------------------------------
# Descriptor I/O
# ---------------------------------------------------------------------------

def load_descriptor() -> Optional[dict[str, Any]]:
    """Load and parse the descriptor JSON, returning None if absent or invalid."""
    if not DESCRIPTOR_PATH.exists():
        return None
    try:
        return json.loads(DESCRIPTOR_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def stamp() -> None:
    """Compute the current hash and write (or update) package-descriptor.json."""
    schema_version = _load_schema_version()
    files = _collect_files()
    digest, rel_paths = compute_hash(files)

    descriptor: dict[str, Any] = {
        "schema_version": schema_version,
        "package_hash": digest,
        "stamped_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        # NOTE: package-descriptor.json is NOT listed here — it is excluded from
        # the hash computation to avoid the circular-dependency problem.
        "files_hashed": rel_paths,
    }

    DESCRIPTOR_PATH.write_text(
        json.dumps(descriptor, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"[stamp] Package descriptor written: {DESCRIPTOR_PATH.name}")
    print(f"[stamp]   schema_version : {schema_version}")
    print(f"[stamp]   package_hash   : {digest[:16]}...  ({len(rel_paths)} files hashed)")
    print(f"[stamp]   Note: {DESCRIPTOR_PATH.name} itself is excluded from the hash.")


def verify() -> int:
    """
    Verify that the current content hash matches the stored descriptor.

    Returns
    -------
    0   — hash matches
    1   — hash mismatch
    2   — descriptor not found
    """
    descriptor = load_descriptor()
    if descriptor is None:
        print(
            f"[verify] ERROR: descriptor not found at {DESCRIPTOR_PATH}\n"
            "[verify]   Run: python3 package_verifier.py --stamp",
            file=sys.stderr,
        )
        return 2

    files = _collect_files()
    digest, rel_paths = compute_hash(files)
    expected = descriptor.get("package_hash", "")

    if digest == expected:
        print(f"[verify] OK — package hash matches descriptor ({digest[:16]}...)")
        return 0

    # Compute a diff for the operator
    expected_files: set[str] = set(descriptor.get("files_hashed", []))
    current_files: set[str] = set(rel_paths)
    added = sorted(current_files - expected_files)
    removed = sorted(expected_files - current_files)

    print("[verify] MISMATCH — package hash does not match descriptor", file=sys.stderr)
    print(f"[verify]   Expected : {expected[:16]}...", file=sys.stderr)
    print(f"[verify]   Current  : {digest[:16]}...", file=sys.stderr)
    if added:
        print(f"[verify]   Added    : {added}", file=sys.stderr)
    if removed:
        print(f"[verify]   Removed  : {removed}", file=sys.stderr)
    if not added and not removed:
        print(
            "[verify]   File set is unchanged — one or more existing files were modified.",
            file=sys.stderr,
        )
    print("[verify]   Run 'bash scripts/forge-stamp-version.sh' if changes are intentional.",
          file=sys.stderr)
    return 1


# ---------------------------------------------------------------------------
# State descriptor: paths and exclusion sets
# ---------------------------------------------------------------------------

# Default location for the state descriptor — alongside package-descriptor.json
# in proxmox-bootstrap/.  Both descriptors live here so they can be shipped with
# the package and verified together.
_DEFAULT_STATE_DESCRIPTOR_PATH: Path = THIS_DIR / "state-descriptor.json"

# Default state directory for development use.  At runtime, override with
# --state-dir /var/lib/broodforge (or equivalent deployed path).
_DEFAULT_STATE_DIR: Path = REPO_ROOT

# Glob patterns for files collected *directly* in state_dir (non-recursive).
# Only .json and .toml files represent operational state/configuration.
# Source files (.py, .sh, .md) are intentionally absent — those belong in the
# package hash, not the state hash (mutual exclusion rule).
_STATE_GLOBS_IN_STATE_DIR: list[str] = ["*.json", "*.toml"]

# MUTUAL EXCLUSION (critical — prevents self-reference loops):
# Neither descriptor is ever included in the other's content set.
#
#   package-descriptor.json — records static source integrity.  Including it in
#     the state hash would cross the source/state boundary and could mask a source
#     change by appearing to be a state change.
#
#   state-descriptor.json — records the hash of all other state files.  Including
#     it is a self-referential loop: the hash cannot be known before writing, but
#     writing it changes the hash — stable convergence is impossible.
#
# Both exclusions are enforced in code (not just documented) so that future
# additions to the state content globs cannot accidentally re-introduce either
# file into the hashed set.
_STATE_EXCLUDED_NAMES: frozenset[str] = frozenset({
    "package-descriptor.json",   # MUTUAL EXCLUSION: base package descriptor — not state
    "state-descriptor.json",     # MUTUAL EXCLUSION: self-reference loop
    "migration-history.jsonl",   # append-only run log — not current deployment state
})

# File suffixes excluded from the state content set.
_STATE_EXCLUDED_SUFFIXES: frozenset[str] = frozenset({
    ".lock",   # transient lock files (migration.lock, etc.)
    ".jsonl",  # append-only logs (migration-history.jsonl, etc.) — explicit even though
               # .jsonl does not match the *.json glob; listed for documentary clarity
})

# Directory components whose contents are excluded from state (non-recursive glob
# already excludes subdirectories, but this guard defends against future glob changes).
_STATE_EXCLUDED_DIR_COMPONENTS: frozenset[str] = frozenset({
    "backups",  # pre-migration snapshots — historical, not current state
})


# ---------------------------------------------------------------------------
# State file collection
# ---------------------------------------------------------------------------

def collect_state_files(state_dir: Path, descriptor_path: Path) -> list[Path]:
    """
    Return a sorted list of absolute paths for all state files to hash.

    Collects two categories:

    1. ``*.json`` and ``*.toml`` files *directly* in *state_dir* (non-recursive).
       At runtime, state_dir = /var/lib/broodforge/.  For development, the
       --state-dir argument defaults to the repo root.

    2. ``migrations/migrate_initial__to__*.py`` from the repo root — the active
       migration script that defines the version the state was migrated to.

    Exclusions enforced (see _STATE_EXCLUDED_NAMES, _STATE_EXCLUDED_SUFFIXES,
    _STATE_EXCLUDED_DIR_COMPONENTS and the inline MUTUAL EXCLUSION guards):

    - ``package-descriptor.json``   MUTUAL EXCLUSION: base package descriptor
    - ``state-descriptor.json``     MUTUAL EXCLUSION: self-reference loop
    - ``migration-history.jsonl``   append-only log, not current state
    - ``*.lock``                    transient lock files
    - Files under ``backups/``      snapshots, not current state
    - ``.py``/``.sh``/``.md``       source files — those belong in the package hash
    """
    descriptor_resolved = descriptor_path.resolve()
    # MUTUAL EXCLUSION: always resolve and exclude package-descriptor.json
    # regardless of whether it currently exists on disk.
    package_descriptor_resolved = (THIS_DIR / "package-descriptor.json").resolve()

    files: set[Path] = set()

    # --- Category 1: operational state files in state_dir ---
    if state_dir.exists():
        for pattern in _STATE_GLOBS_IN_STATE_DIR:
            for p in state_dir.glob(pattern):  # non-recursive: only top-level files
                if not p.is_file():
                    continue
                # Exclude files nested under excluded directory components.
                # (Non-recursive glob already prevents this, but the guard is
                # kept so future glob extensions cannot accidentally re-introduce
                # subdirectory content without triggering an explicit exclusion.)
                rel_parts = p.relative_to(state_dir).parts
                if len(rel_parts) > 1 and any(
                    part in _STATE_EXCLUDED_DIR_COMPONENTS for part in rel_parts[:-1]
                ):
                    continue
                # Exclude transient/log suffixes
                if p.suffix in _STATE_EXCLUDED_SUFFIXES:
                    continue
                # Exclude specific named files (mutual exclusion + append-only logs)
                if p.name in _STATE_EXCLUDED_NAMES:
                    continue
                # MUTUAL EXCLUSION guard: never include the state descriptor
                # (resolving handles symlinks and relative paths)
                if p.resolve() == descriptor_resolved:
                    continue
                # MUTUAL EXCLUSION guard: never include the package descriptor
                if p.resolve() == package_descriptor_resolved:
                    continue
                files.add(p.resolve())

    # --- Category 2: active migration script from the repo's migrations/ dir ---
    # The migration script defines the schema version the state was migrated to;
    # it is part of "what this deployment is running."
    migrations_dir = REPO_ROOT / "migrations"
    if migrations_dir.exists():
        for p in migrations_dir.glob("migrate_initial__to__*.py"):
            if p.is_file():
                files.add(p.resolve())

    return sorted(files)


# ---------------------------------------------------------------------------
# State stamp and verify
# ---------------------------------------------------------------------------

def stamp_state_descriptor(
    state_dir: Path,
    descriptor_path: Path,
    now_fn=None,  # clock injection for testing: () -> datetime
) -> dict:
    """
    Compute the state hash and write (or update) *descriptor_path*.

    Parameters
    ----------
    state_dir       : directory whose top-level .json/.toml files are hashed
    descriptor_path : path to write state-descriptor.json (created or overwritten)
    now_fn          : optional clock injection — callable returning a ``datetime``
                      (used in tests to produce deterministic timestamps)

    Returns the written descriptor dict.

    The state-descriptor.json format is::

        {
          "state_hash":    "<sha256hex>",
          "stamped_at":    "<ISO UTC>",
          "state_dir":     "<absolute path at stamp time>",
          "files_hashed":  ["<relative paths sorted>"]
        }

    Note: no ``schema_version`` field — schema version belongs to the package
    descriptor only.  Neither descriptor file is included in the hashed set
    (mutual exclusion rule — see module docstring).
    """
    if now_fn is None:
        now_fn = lambda: datetime.now(timezone.utc)  # noqa: E731

    files = collect_state_files(state_dir, descriptor_path)
    # Reuse the public compute_hash function for consistency of algorithm
    digest, rel_paths = compute_hash(files)

    descriptor: dict[str, Any] = {
        "state_hash": digest,
        "stamped_at": now_fn().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "state_dir": str(state_dir.resolve()),
        # NOTE: state-descriptor.json is NOT listed here — excluded from the
        # hash to avoid a self-referential loop (MUTUAL EXCLUSION rule).
        # NOTE: package-descriptor.json is NOT listed here — excluded from the
        # state hash because it records source integrity, not operational state
        # (MUTUAL EXCLUSION rule).
        "files_hashed": rel_paths,
    }

    descriptor_path.write_text(
        json.dumps(descriptor, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return descriptor


def verify_state_descriptor(
    state_dir: Path,
    descriptor_path: Path,
) -> tuple[bool, list[str]]:
    """
    Verify that the current state files match the stored descriptor.

    Returns
    -------
    (ok, errors)
        ok=True and errors=[] when the hash matches.
        ok=False and errors contains at least one message on mismatch or missing
        descriptor.

    Callers can map the error list to exit codes:
        descriptor missing  → errors[0] contains "not found"  → exit 2
        hash mismatch       → errors[0] contains "mismatch"   → exit 1
    """
    if not descriptor_path.exists():
        return False, [f"State descriptor not found at {descriptor_path} — run forge-stamp-state.sh first"]

    try:
        stored = json.loads(descriptor_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return False, [f"Cannot read state descriptor: {exc}"]

    expected_hash = stored.get("state_hash", "")
    files = collect_state_files(state_dir, descriptor_path)
    digest, rel_paths = compute_hash(files)

    if digest == expected_hash:
        return True, []

    # Build a diff for the operator
    expected_files: set[str] = set(stored.get("files_hashed", []))
    current_files: set[str] = set(rel_paths)
    added = sorted(current_files - expected_files)
    removed = sorted(expected_files - current_files)

    errors: list[str] = [
        f"state_hash mismatch — expected {expected_hash[:16]}... got {digest[:16]}..."
    ]
    if added:
        errors.append(f"Added files: {added}")
    if removed:
        errors.append(f"Removed files: {removed}")
    if not added and not removed:
        errors.append("File set unchanged — one or more existing state files were modified")
    return False, errors


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        print(
            "Usage: package_verifier.py --stamp | --verify\n"
            "       package_verifier.py --stamp-state [--state-dir <path>]\n"
            "       package_verifier.py --verify-state [--state-dir <path>]",
            file=sys.stderr,
        )
        return 1

    # Parse --state-dir (shared between --stamp-state and --verify-state).
    # Defaults to repo root for development; override with /var/lib/broodforge at runtime.
    state_dir: Path = _DEFAULT_STATE_DIR
    i = 0
    while i < len(args):
        if args[i] == "--state-dir" and i + 1 < len(args):
            state_dir = Path(args[i + 1])
            del args[i:i + 2]
        else:
            i += 1

    mode = args[0] if args else ""

    if mode == "--stamp":
        stamp()
        return 0

    if mode == "--verify":
        return verify()

    if mode == "--stamp-state":
        descriptor_path = _DEFAULT_STATE_DESCRIPTOR_PATH
        result = stamp_state_descriptor(state_dir, descriptor_path)
        digest = result["state_hash"]
        n = len(result["files_hashed"])
        print(f"[stamp-state] State descriptor written: {descriptor_path.name}")
        print(f"[stamp-state]   state_hash   : {digest[:16]}...  ({n} files hashed)")
        print(f"[stamp-state]   state_dir    : {state_dir.resolve()}")
        print(
            f"[stamp-state]   Note: {descriptor_path.name} and package-descriptor.json "
            "are excluded (mutual exclusion rule)."
        )
        return 0

    if mode == "--verify-state":
        descriptor_path = _DEFAULT_STATE_DESCRIPTOR_PATH
        ok, errors = verify_state_descriptor(state_dir, descriptor_path)
        if ok:
            print("[verify-state] OK — state hash matches descriptor")
            return 0
        for err in errors:
            print(f"[verify-state] {err}", file=sys.stderr)
        # Exit 2 if descriptor not found; exit 1 for hash mismatch or read error
        if errors and "not found" in errors[0]:
            return 2
        return 1

    print(f"Unknown argument: {args[0] if args else '(none)'}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
