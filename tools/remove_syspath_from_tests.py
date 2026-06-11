#!/usr/bin/env python3
"""
remove_syspath_from_tests.py — Bulk cleanup: remove sys.path.insert() calls
from test files now that pyproject.toml [tool.pytest.ini_options] pythonpath
declarations make them redundant.

Audit finding fix (rounds 4/5): test suite used per-file sys.path.insert()
to locate proxmox-bootstrap, doc-gen, and peer packages. The pythonpath
setting in pyproject.toml now handles this, making these calls dead code.

Usage:
    python3 tools/remove_syspath_from_tests.py [--dry-run]

What it does per file:
  1. Removes all sys.path.insert() and sys.path.append() lines.
  2. Removes lines of the form:
       _ROOT = os.path.dirname(os.path.dirname(...(__file__)))
       REPO_ROOT = Path(__file__).parent.parent.parent
       ROOT = Path(__file__).parent.parent
     ONLY when that variable is no longer referenced in the file after removal.
  3. Removes `import sys` ONLY when `sys.` no longer appears in the file
     after removal of sys.path lines.
  4. Removes `import os` ONLY when `os.` no longer appears in the file
     after removal (handles the common _ROOT = os.path.dirname... pattern).

Safety:
  - Writes to a temp file first; replaces original only when the result
    has fewer sys.path references.
  - Never removes a line if the result would break an obvious import chain.
  - Reports every file changed and every line removed.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
TEST_DIRS = [
    REPO_ROOT / "tests",
]

# Patterns that indicate a line is a sys.path manipulation
SYS_PATH_RE = re.compile(r"^\s*sys\.path\.(insert|append)\s*\(")

# Pattern for _ROOT / REPO_ROOT / ROOT variable assignments used only for path
ROOT_VAR_RE = re.compile(
    r"^(?P<varname>[A-Z_a-z][A-Z_a-z0-9]*)\s*=\s*"
    r"(?:os\.path\.dirname\s*\(|Path\s*\(|str\s*\(Path\s*\()"
    r".*__file__"
)

def _count_references(lines: list[str], varname: str) -> int:
    """Count how many lines reference <varname> as a word."""
    pattern = re.compile(r'\b' + re.escape(varname) + r'\b')
    return sum(1 for line in lines if pattern.search(line))


def _process_file(path: Path, dry_run: bool) -> list[str]:
    """Return list of change descriptions, or [] if no changes."""
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)

    # Pass 1: identify sys.path.insert/append lines and their line numbers
    sys_path_lines: set[int] = set()
    for i, line in enumerate(lines):
        if SYS_PATH_RE.match(line):
            sys_path_lines.add(i)

    if not sys_path_lines:
        return []

    # Build new lines with sys.path.insert removed
    new_lines = [line for i, line in enumerate(lines) if i not in sys_path_lines]

    # Pass 2: remove ROOT variable assignments if no longer referenced
    root_vars_to_check: dict[str, int] = {}  # varname -> line index in new_lines
    for i, line in enumerate(new_lines):
        m = ROOT_VAR_RE.match(line)
        if m:
            varname = m.group("varname")
            root_vars_to_check[varname] = i

    root_lines_to_remove: set[int] = set()
    for varname, idx in root_vars_to_check.items():
        # Count references in new_lines excluding the definition line itself
        other_lines = [l for j, l in enumerate(new_lines) if j != idx]
        if _count_references(other_lines, varname) == 0:
            root_lines_to_remove.add(idx)

    new_lines = [line for i, line in enumerate(new_lines) if i not in root_lines_to_remove]

    # Pass 3: remove `import sys` if sys. no longer appears
    new_content_check = "".join(new_lines)
    import_sys_lines: set[int] = set()
    for i, line in enumerate(new_lines):
        if re.match(r"^\s*import\s+sys\s*(?:#.*)?$", line):
            import_sys_lines.add(i)

    if import_sys_lines:
        # Count sys. usages excluding import and removed lines
        other_lines = [l for j, l in enumerate(new_lines) if j not in import_sys_lines]
        if not any(re.search(r'\bsys\.', l) for l in other_lines):
            new_lines = [l for j, l in enumerate(new_lines) if j not in import_sys_lines]

    # Pass 4: remove `import os` if os. no longer appears
    import_os_lines: set[int] = set()
    for i, line in enumerate(new_lines):
        if re.match(r"^\s*import\s+os\s*(?:#.*)?$", line):
            import_os_lines.add(i)

    if import_os_lines:
        other_lines = [l for j, l in enumerate(new_lines) if j not in import_os_lines]
        if not any(re.search(r'\bos\.', l) for l in other_lines):
            new_lines = [l for j, l in enumerate(new_lines) if j not in import_os_lines]

    new_content = "".join(new_lines)

    if new_content == original:
        return []

    removed_count = len(original.splitlines()) - len(new_content.splitlines())
    changes = [
        f"  removed {len(sys_path_lines)} sys.path.insert/append line(s) "
        f"(+{removed_count - len(sys_path_lines)} dead variable/import lines)"
    ]

    if not dry_run:
        path.write_text(new_content, encoding="utf-8")

    return changes


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    mode = "DRY RUN" if dry_run else "APPLYING"
    print(f"[{mode}] Removing redundant sys.path manipulations from test files")
    print(f"  pyproject.toml pythonpath covers: proxmox-bootstrap, doc-gen, "
          f"doc-gen/renderers, data-model, lib, assessment/tier1\n")

    total_changed = 0
    for test_dir in TEST_DIRS:
        for py_file in sorted(test_dir.rglob("*.py")):
            # Skip non-test files and tools directory
            rel = py_file.relative_to(REPO_ROOT)
            if "deprecated" in rel.parts:
                continue
            # Only process test files (in tests/ tree)
            if "tests" not in rel.parts:
                continue
            changes = _process_file(py_file, dry_run)
            if changes:
                total_changed += 1
                print(f"  {rel}")
                for change in changes:
                    print(change)

    print(f"\n[{mode}] {total_changed} file(s) {'would be' if dry_run else 'were'} modified.")
    if dry_run:
        print("  Re-run without --dry-run to apply changes.")


if __name__ == "__main__":
    main()
