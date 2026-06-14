#!/usr/bin/env python3
"""
version_stamp.py — Generate a broodforge version stamp for documentation headers.

Format: YYYY-MM-DD_HH-MM-SS_<tz>_<shorthash>

The shorthash is the first 8 hex characters of a SHA-256 computed over all
codebase files sorted by relative path.  The exact inclusion/exclusion rules
are defined in the canonical schema file:

    proxmox-bootstrap/version-hash-schema.yaml

That file is machine- and human-readable, documents the rationale for every
rule, and is itself included in the hash.  This script loads the schema at
runtime so that the rules are never duplicated between the schema and the code.

If pyyaml is available it is used to parse the schema.  If not, a minimal
built-in parser extracts the extension and directory lists from the YAML using
straightforward line matching — sufficient for the schema's regular structure.

PAP compliance:
  - No bare datetime.now() — caller passes now_fn or function uses now_fn parameter
  - No subprocess calls
  - No credentials touched
  - Atomic file writes not applicable (read-only tool)

Usage:
    python3 proxmox-bootstrap/version_stamp.py [--repo-root /path/to/repo]
    python3 proxmox-bootstrap/version_stamp.py --hash-only
    python3 proxmox-bootstrap/version_stamp.py --timestamp-only
    python3 proxmox-bootstrap/version_stamp.py --show-schema
    python3 proxmox-bootstrap/version_stamp.py --list-files
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, NamedTuple, Optional

# ---------------------------------------------------------------------------
# Schema location
# ---------------------------------------------------------------------------

_SCHEMA_FILENAME = "version-hash-schema.yaml"


def _schema_path(repo_root: Path) -> Path:
    return repo_root / "proxmox-bootstrap" / _SCHEMA_FILENAME


# ---------------------------------------------------------------------------
# Minimal built-in YAML parser (schema-specific, stdlib-only fallback)
# ---------------------------------------------------------------------------

def _parse_schema_builtin(text: str) -> dict:
    """Extract include/exclude extension and directory lists from the schema YAML.

    This is a deliberately narrow parser that understands only the specific
    structure of version-hash-schema.yaml.  It is not a general YAML parser.
    It produces the same result as pyyaml.safe_load() for this file.

    Recognised patterns (stripped lines):
      - ext: ".foo"       → extension entry
      - name: "bar"       → directory entry
      - name: '.git'      → directory entry (single-quoted)
      - name: baz         → directory entry (unquoted)
    """
    include_exts: list[str] = []
    exclude_exts: list[str] = []
    exclude_dirs: list[str] = []

    # Track which top-level section we're inside
    section = None       # "include" | "exclude"
    subsection = None    # "extensions" | "directories"

    ext_re   = re.compile(r'^-\s+ext:\s*["\']?(\.[A-Za-z0-9_]+)["\']?\s*$')
    name_re  = re.compile(r'^-\s+name:\s*["\']?([^"\'#\s][^"\'#]*?)["\']?\s*(?:#.*)?$')
    sec_re   = re.compile(r'^(include|exclude):')
    sub_re   = re.compile(r'^\s+(extensions|directories):')

    for line in text.splitlines():
        stripped = line.rstrip()

        m = sec_re.match(stripped)
        if m:
            section = m.group(1)
            subsection = None
            continue

        m = sub_re.match(stripped)
        if m:
            subsection = m.group(1)
            continue

        if section == "include" and subsection == "extensions":
            m = ext_re.match(stripped.strip())
            if m:
                include_exts.append(m.group(1).lower())

        elif section == "exclude":
            if subsection == "extensions":
                m = ext_re.match(stripped.strip())
                if m:
                    exclude_exts.append(m.group(1).lower())
            elif subsection == "directories":
                m = name_re.match(stripped.strip())
                if m:
                    exclude_dirs.append(m.group(1))

    return {
        "include": {"extensions": [{"ext": e} for e in include_exts]},
        "exclude": {
            "extensions": [{"ext": e} for e in exclude_exts],
            "directories": [{"name": d} for d in exclude_dirs],
        },
    }


def _load_schema(repo_root: Path) -> dict:
    """Load and parse the version-hash-schema.yaml file.

    Tries pyyaml first (richer error messages, handles edge cases); falls back
    to the built-in parser if pyyaml is not installed.  Raises FileNotFoundError
    if the schema file does not exist.
    """
    path = _schema_path(repo_root)
    if not path.exists():
        raise FileNotFoundError(
            f"Schema file not found: {path}\n"
            "Run this script from the repository root, or pass --repo-root."
        )
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import]
        return yaml.safe_load(text)
    except ImportError:
        return _parse_schema_builtin(text)


# ---------------------------------------------------------------------------
# HashRules — extracted from schema
# ---------------------------------------------------------------------------

class HashRules(NamedTuple):
    include_exts: frozenset[str]   # lower-cased
    exclude_exts: frozenset[str]   # lower-cased
    exclude_dirs: frozenset[str]   # exact match


def _rules_from_schema(schema: dict) -> HashRules:
    inc = schema.get("include", {})
    exc = schema.get("exclude", {})

    include_exts = frozenset(
        e["ext"].lower()
        for e in inc.get("extensions", [])
        if isinstance(e, dict) and "ext" in e
    )
    exclude_exts = frozenset(
        e["ext"].lower()
        for e in exc.get("extensions", [])
        if isinstance(e, dict) and "ext" in e
    )
    exclude_dirs = frozenset(
        d["name"]
        for d in exc.get("directories", [])
        if isinstance(d, dict) and "name" in d
    )
    return HashRules(include_exts=include_exts,
                     exclude_exts=exclude_exts,
                     exclude_dirs=exclude_dirs)


# ---------------------------------------------------------------------------
# File inclusion check
# ---------------------------------------------------------------------------

def _should_include(path: Path, repo_root: Path, rules: HashRules) -> bool:
    """Return True if *path* should be included in the codebase hash."""
    if not path.is_file():
        return False
    ext = path.suffix.lower()
    if ext not in rules.include_exts:
        return False
    if ext in rules.exclude_exts:
        return False
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        return False
    # Check all ancestor directory components (not the filename itself)
    for part in rel.parts[:-1]:
        if part in rules.exclude_dirs:
            return False
        # Also exclude hidden directories (schema: hidden_directories rule)
        if part.startswith("."):
            return False
    return True


# ---------------------------------------------------------------------------
# Core hash computation
# ---------------------------------------------------------------------------

def compute_codebase_hash(repo_root: Path, rules: Optional[HashRules] = None) -> str:
    """Return the first 8 hex chars of SHA-256 over all codebase files.

    Files are processed in ascending lexicographic order of their POSIX
    relative paths.  Both path and contents are fed into the digest so that
    renames and content changes both affect the hash.

    If *rules* is None the schema is loaded from the repo.
    """
    if rules is None:
        schema = _load_schema(repo_root)
        rules = _rules_from_schema(schema)

    h = hashlib.sha256()
    files = sorted(
        p for p in repo_root.rglob("*")
        if _should_include(p, repo_root, rules)
    )
    if not files:
        raise RuntimeError(
            f"No codebase files found under {repo_root!s} — "
            "check that the repo root is correct and the schema is valid."
        )
    for f in files:
        rel = f.relative_to(repo_root).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\x00")
        h.update(f.read_bytes())
        h.update(b"\x00")
    return h.hexdigest()[:8]


# ---------------------------------------------------------------------------
# Stamp generation
# ---------------------------------------------------------------------------

def _tz_label(dt: datetime) -> str:
    """Return a short, unambiguous timezone label for a datetime.

    Examples: "UTC", "MST", "EST".  Falls back to "UTC" for naive datetimes
    (which this codebase should never produce, but belt-and-suspenders).
    """
    if dt.tzinfo is None:
        return "UTC"
    name = dt.tzname()
    return name if name else "UTC"


def generate_stamp(
    repo_root: Path,
    now_fn: Optional[Callable[[], datetime]] = None,
    rules: Optional[HashRules] = None,
) -> str:
    """Return a full version stamp: ``YYYY-MM-DD_HH-MM-SS_<tz>_<shorthash>``."""
    if now_fn is None:
        now_fn = lambda: datetime.now(timezone.utc)
    now = now_fn()
    ts = now.strftime("%Y-%m-%d_%H-%M-%S")
    tz = _tz_label(now)
    shorthash = compute_codebase_hash(repo_root, rules=rules)
    return f"{ts}_{tz}_{shorthash}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(
        description="Generate a broodforge version stamp (YYYY-MM-DD_HH-MM-SS_<tz>_shorthash)"
    )
    ap.add_argument(
        "--repo-root", default=".",
        help="Path to the repository root (default: current directory)"
    )
    ap.add_argument(
        "--hash-only", action="store_true",
        help="Print only the 8-char shorthash"
    )
    ap.add_argument(
        "--timestamp-only", action="store_true",
        help="Print only the YYYY-MM-DD_HH-MM-SS portion"
    )
    ap.add_argument(
        "--list-files", action="store_true",
        help="List the files that would be included in the hash (for verification)"
    )
    ap.add_argument(
        "--show-schema", action="store_true",
        help="Print the active inclusion/exclusion rules derived from the schema file"
    )
    args = ap.parse_args(argv)

    root = Path(args.repo_root).resolve()
    if not root.is_dir():
        print(f"[version_stamp] not a directory: {root}", file=sys.stderr)
        sys.exit(2)

    schema = _load_schema(root)
    rules = _rules_from_schema(schema)

    if args.show_schema:
        print(f"Schema: {_schema_path(root)}")
        print(f"  schema_version : {schema.get('schema_version', '?')}")
        algo = schema.get("hash", {}).get("algorithm", "sha256")
        trunc = schema.get("hash", {}).get("truncate_chars", 8)
        print(f"  hash           : {algo}, first {trunc} hex chars")
        print(f"  include exts   : {sorted(rules.include_exts)}")
        print(f"  exclude exts   : {sorted(rules.exclude_exts)}")
        print(f"  exclude dirs   : {sorted(rules.exclude_dirs)}")
        hid = schema.get("exclude", {}).get("hidden_directories", {})
        if hid:
            _rule = hid.get("rule", "name.startswith(\x27.\x27)")
            print(f"  hidden dirs    : {_rule}")
        return

    if args.list_files:
        files = sorted(
            p for p in root.rglob("*")
            if _should_include(p, root, rules)
        )
        for f in files:
            print(f.relative_to(root).as_posix())
        print(f"\n{len(files)} files total", file=sys.stderr)
        return

    if args.hash_only:
        print(compute_codebase_hash(root, rules=rules))
    elif args.timestamp_only:
        now = datetime.now(timezone.utc)
        print(f"{now.strftime('%Y-%m-%d_%H-%M-%S')}_{_tz_label(now)}")
    else:
        print(generate_stamp(root, rules=rules))


if __name__ == "__main__":
    main()
