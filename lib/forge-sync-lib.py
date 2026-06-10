#!/usr/bin/env python3
"""
lib/forge-sync-lib.py — KeePass one-way sync using pykeepass (Phase 1.P addendum).

Master-authoritative: entries copied from master always overwrite matching entries
in child. Child-only entries are left intact unless --delete-orphans is passed.

Security properties:
  - Passwords read from stdin ONLY (line 1 = master password, line 2 = child password)
  - Never accepted as CLI arguments or environment variables
  - Local password variables unset after use
  - No password is ever written to stdout, stderr, or disk

Sync modes:
  --entry GROUP/TITLE   Copy a single entry from master to child (add or update)
  --group GROUP/PATH    Recursively copy all entries under a master group to child

Entry/group path format: slash-separated from root
  e.g.  "Broodforge/services/restic/repo-password"   (entry)
        "Broodforge/services"                          (group)

Exit codes:
  0 — sync complete
  1 — error (bad path, wrong password, file not found, etc.)
  2 — pykeepass not installed (pip install pykeepass); caller should fall back

Usage (from shell):
  printf '%s\\n%s\\n' "$MASTER_PW" "$CHILD_PW" | \\
      python3 lib/forge-sync-lib.py \\
          --master /var/lib/broodforge/master.kdbx \\
          --child  /var/lib/broodforge/forge-autonomous.kdbx \\
          --entry  "Broodforge/services/restic/repo-password"
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# pykeepass import — exit 2 if not installed so callers can fall back
# ---------------------------------------------------------------------------

try:
    from pykeepass import PyKeePass                    # type: ignore
    from pykeepass.exceptions import CredentialsError  # type: ignore
    _PYKEEPASS_AVAILABLE = True
except ImportError:
    _PYKEEPASS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Path helpers (no pykeepass dependency)
# ---------------------------------------------------------------------------

def split_entry_path(path: str) -> tuple[list[str], str]:
    """Split "Group/Sub/Title" into (["Group", "Sub"], "Title").

    Strips leading/trailing slashes. Single component returns ([], component).
    Raises ValueError on empty input.
    """
    parts = [p for p in path.strip("/").split("/") if p]
    if not parts:
        raise ValueError(f"Empty entry path: {path!r}")
    return parts[:-1], parts[-1]


def split_group_path(path: str) -> list[str]:
    """Split "Group/Sub" into ["Group", "Sub"]. Raises ValueError if empty."""
    parts = [p for p in path.strip("/").split("/") if p]
    if not parts:
        raise ValueError(f"Empty group path: {path!r}")
    return parts


# ---------------------------------------------------------------------------
# pykeepass traversal helpers
# ---------------------------------------------------------------------------

def _find_group_by_path(kp: "PyKeePass", path_parts: list[str]) -> Optional[object]:
    """Navigate from root to the group at path_parts. Returns group or None."""
    current = kp.root_group
    for part in path_parts:
        found = None
        for subgroup in current.subgroups:
            if subgroup.name == part:
                found = subgroup
                break
        if found is None:
            return None
        current = found
    return current


def _find_entry_in_group(group, title: str) -> Optional[object]:
    """Find a direct-child entry by title. Returns entry or None."""
    for entry in group.entries:
        if entry.title == title:
            return entry
    return None


def _ensure_group_path(kp: "PyKeePass", path_parts: list[str]) -> object:
    """Return the group at path_parts, creating missing intermediate groups."""
    current = kp.root_group
    for part in path_parts:
        found = None
        for subgroup in current.subgroups:
            if subgroup.name == part:
                found = subgroup
                break
        if found is None:
            found = kp.add_group(current, part)
        current = found
    return current


# ---------------------------------------------------------------------------
# Core copy primitive
# ---------------------------------------------------------------------------

def _copy_entry(src_entry, dst_kp: "PyKeePass", dst_group_parts: list[str],
                dry_run: bool) -> str:
    """Copy src_entry into dst_kp under dst_group_parts.

    Returns "added", "updated", or "dry-run".
    src_entry must have .title, .username, .password, .url, .notes attributes.
    """
    title = src_entry.title or ""
    dst_group = _ensure_group_path(dst_kp, dst_group_parts)
    existing = _find_entry_in_group(dst_group, title)
    path_str = "/".join(dst_group_parts + [title])

    if dry_run:
        verb = "would-add" if existing is None else "would-update"
        print(f"[sync-lib] {verb}: {path_str}")
        return "dry-run"

    if existing is None:
        dst_kp.add_entry(
            dst_group,
            title=title,
            username=src_entry.username or "",
            password=src_entry.password or "",
            url=src_entry.url or "",
            notes=src_entry.notes or "",
        )
        print(f"[sync-lib] added: {path_str}")
        return "added"
    else:
        existing.username = src_entry.username or ""
        existing.password = src_entry.password or ""
        existing.url      = src_entry.url or ""
        existing.notes    = src_entry.notes or ""
        print(f"[sync-lib] updated: {path_str}")
        return "updated"


# ---------------------------------------------------------------------------
# Recursive group sync
# ---------------------------------------------------------------------------

def _sync_group_recursive(
    src_group,
    dst_kp: "PyKeePass",
    dst_path_parts: list[str],
    dry_run: bool,
    stats: dict,
    delete_orphans: bool = False,
) -> None:
    """Recursively sync all entries from src_group into dst_kp."""
    # Add / update entries from source
    for entry in src_group.entries:
        action = _copy_entry(entry, dst_kp, dst_path_parts, dry_run)
        if action == "added":
            stats["added"] += 1
        elif action == "updated":
            stats["updated"] += 1

    # Remove orphaned entries in dst that are absent from src
    if delete_orphans:
        src_titles = {(e.title or "") for e in src_group.entries}
        dst_group = _find_group_by_path(dst_kp, dst_path_parts)
        if dst_group is not None:
            for dst_entry in list(dst_group.entries):
                title = dst_entry.title or ""
                if title not in src_titles:
                    path_str = "/".join(dst_path_parts + [title])
                    if dry_run:
                        print(f"[sync-lib] would-delete: {path_str}")
                    else:
                        dst_kp.delete_entry(dst_entry)
                        print(f"[sync-lib] deleted: {path_str}")
                    stats["deleted"] = stats.get("deleted", 0) + 1

    for subgroup in src_group.subgroups:
        _sync_group_recursive(
            subgroup,
            dst_kp,
            dst_path_parts + [subgroup.name],
            dry_run,
            stats,
            delete_orphans,
        )


# ---------------------------------------------------------------------------
# Public sync functions
# ---------------------------------------------------------------------------

def sync_entry(
    master_kdbx: str,
    master_pw: str,
    child_kdbx: str,
    child_pw: str,
    entry_path: str,
    dry_run: bool = False,
) -> int:
    """Copy one entry from master to child (add or update). Returns 0 or 1."""
    try:
        group_parts, title = split_entry_path(entry_path)
    except ValueError as exc:
        print(f"[sync-lib] {exc}", file=sys.stderr)
        return 1

    try:
        master = PyKeePass(master_kdbx, password=master_pw)
    except CredentialsError:
        print(f"[sync-lib] master: wrong password: {master_kdbx}", file=sys.stderr)
        return 1
    except FileNotFoundError:
        print(f"[sync-lib] master: file not found: {master_kdbx}", file=sys.stderr)
        return 1

    try:
        child = PyKeePass(child_kdbx, password=child_pw)
    except CredentialsError:
        print(f"[sync-lib] child: wrong password: {child_kdbx}", file=sys.stderr)
        return 1
    except FileNotFoundError:
        print(f"[sync-lib] child: file not found: {child_kdbx}", file=sys.stderr)
        return 1

    # Locate entry in master — try exact group path first, then title-only
    src_group = _find_group_by_path(master, group_parts) if group_parts else master.root_group
    src_entry = None
    if src_group is not None:
        src_entry = _find_entry_in_group(src_group, title)
    if src_entry is None:
        # Fallback: search by title across entire master DB
        results = master.find_entries(title=title, first=True)
        src_entry = results

    if src_entry is None:
        print(f"[sync-lib] entry not found in master: {entry_path!r}", file=sys.stderr)
        return 1

    _copy_entry(src_entry, child, group_parts, dry_run)
    if not dry_run:
        child.save()
    return 0


def sync_group(
    master_kdbx: str,
    master_pw: str,
    child_kdbx: str,
    child_pw: str,
    group_path: str,
    dry_run: bool = False,
    delete_orphans: bool = False,
) -> int:
    """Recursively copy all entries under a master group into child. Returns 0 or 1."""
    try:
        group_parts = split_group_path(group_path)
    except ValueError as exc:
        print(f"[sync-lib] {exc}", file=sys.stderr)
        return 1

    try:
        master = PyKeePass(master_kdbx, password=master_pw)
    except (CredentialsError, FileNotFoundError) as exc:
        print(f"[sync-lib] master open failed: {exc}", file=sys.stderr)
        return 1

    try:
        child = PyKeePass(child_kdbx, password=child_pw)
    except (CredentialsError, FileNotFoundError) as exc:
        print(f"[sync-lib] child open failed: {exc}", file=sys.stderr)
        return 1

    src_group = _find_group_by_path(master, group_parts)
    if src_group is None:
        print(f"[sync-lib] group not found in master: {group_path!r}", file=sys.stderr)
        return 1

    stats = {"added": 0, "updated": 0}
    _sync_group_recursive(src_group, child, group_parts, dry_run, stats, delete_orphans)

    if not dry_run:
        child.save()

    print(f"[sync-lib] group sync complete: {group_path}")
    deleted = stats.get("deleted", 0)
    print(f"[sync-lib]   added={stats['added']}  updated={stats['updated']}  deleted={deleted}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    if not _PYKEEPASS_AVAILABLE:
        print(
            "[sync-lib] pykeepass is not installed.\n"
            "  Install: pip install pykeepass\n"
            "  forge-sync-credentials.sh will fall back to keepassxc-cli.",
            file=sys.stderr,
        )
        return 2

    parser = argparse.ArgumentParser(
        description="forge-sync-lib: KeePass one-way sync (master → child)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Passwords are read from stdin (line 1 = master password, line 2 = child password).
Never passed as CLI arguments.

Examples:
  printf '%s\\n%s\\n' "$MASTER_PW" "$CHILD_PW" | \\
      python3 lib/forge-sync-lib.py \\
          --master /var/lib/broodforge/master.kdbx \\
          --child  /var/lib/broodforge/forge-autonomous.kdbx \\
          --entry  "Broodforge/services/restic/repo-password"

  printf '%s\\n%s\\n' "$MASTER_PW" "$CHILD_PW" | \\
      python3 lib/forge-sync-lib.py \\
          --master /var/lib/broodforge/master.kdbx \\
          --child  /var/lib/broodforge/forge-autonomous.kdbx \\
          --group  "Broodforge/services" --dry-run
""",
    )
    parser.add_argument("--master", required=True, help="Path to master .kdbx")
    parser.add_argument("--child",  required=True, help="Path to child .kdbx")

    mode_grp = parser.add_mutually_exclusive_group(required=True)
    mode_grp.add_argument("--entry", metavar="PATH",
                          help="Sync one entry: Group/SubGroup/Title")
    mode_grp.add_argument("--group", metavar="PATH",
                          help="Sync all entries under a group: Group/SubGroup")

    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be synced; make no changes")
    parser.add_argument("--delete-orphans", action="store_true",
                        help="Remove child entries absent from master (group sync only)")

    args = parser.parse_args(argv)

    # Read passwords from stdin — two lines
    raw = sys.stdin.read()
    lines = raw.splitlines()
    if len(lines) < 2:
        print(
            "[sync-lib] stdin must have 2 lines: master password then child password",
            file=sys.stderr,
        )
        return 1

    master_pw = lines[0]
    child_pw  = lines[1]

    try:
        if args.entry:
            rc = sync_entry(
                args.master, master_pw,
                args.child,  child_pw,
                args.entry,
                dry_run=args.dry_run,
            )
        else:
            rc = sync_group(
                args.master, master_pw,
                args.child,  child_pw,
                args.group,
                dry_run=args.dry_run,
                delete_orphans=args.delete_orphans,
            )
    finally:
        # Clear passwords from local scope
        master_pw = child_pw = ""  # noqa: F841

    return rc


if __name__ == "__main__":
    sys.exit(main())
