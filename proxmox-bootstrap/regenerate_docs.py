#!/usr/bin/env python3
"""
regenerate_docs.py — Rebuild all broodforge HTML documentation from source Markdown.

Reads proxmox-bootstrap/doc-manifest.json and regenerates every registered
HTML file. Prefers the Tessel compiler (tessel-cli.js via Node.js) when
available; falls back to md_to_html.py (Python reference implementation).

Compiler selection order:
  1. $TESSEL_CLI env var — absolute path to tessel-cli.js
  2. Auto-discover: ../tessel/tools/tessel-cli.js relative to this repo
  3. Fallback: md_to_html.py (Python, stdlib only)

Usage (from repo root):
    python3 proxmox-bootstrap/regenerate_docs.py            # regenerate all
    python3 proxmox-bootstrap/regenerate_docs.py --check    # report stale files only
    python3 proxmox-bootstrap/regenerate_docs.py --id phoenix  # single doc by id
    python3 proxmox-bootstrap/regenerate_docs.py --type runbook  # filter by type
    python3 proxmox-bootstrap/regenerate_docs.py --python   # force Python compiler

Stdlib only — no pip dependencies.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.resolve()
MANIFEST_PATH = Path(__file__).parent / "doc-manifest.json"
GENERATOR = Path(__file__).parent / "md_to_html.py"

# ---- Tessel compiler discovery ----

def _find_tessel_cli() -> Path | None:
    """Return path to tessel-cli.js, or None if unavailable."""
    # 1. Explicit env override
    env_path = os.environ.get("TESSEL_CLI")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p
        sys.stderr.write(f"[regen] TESSEL_CLI set to {env_path} but file not found — ignoring.\n")

    # 2. Sibling repo: ../tessel/tools/tessel-cli.js
    candidate = REPO_ROOT.parent / "tessel" / "tools" / "tessel-cli.js"
    if candidate.exists():
        return candidate

    return None


def _node_available() -> bool:
    return shutil.which("node") is not None


def _resolve_compiler(force_python: bool):
    """
    Return (compiler_type, path_or_None).
    compiler_type is 'tessel' or 'python'.
    """
    if not force_python:
        cli = _find_tessel_cli()
        if cli and _node_available():
            return ("tessel", cli)
    return ("python", GENERATOR)


def load_manifest() -> dict:
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        return json.load(f)


def is_stale(source: Path, output: Path, generator: Path) -> bool:
    """Return True if output doesn't exist or is older than source or generator."""
    if not output.exists():
        return True
    out_mtime = output.stat().st_mtime
    if source.exists() and source.stat().st_mtime > out_mtime:
        return True
    if generator.exists() and generator.stat().st_mtime > out_mtime:
        return True
    return False


def regenerate(
    doc: dict,
    compiler_type: str,
    compiler_path: Path,
    force: bool = False,
    check_only: bool = False,
) -> tuple[bool, str]:
    """
    Regenerate a single doc entry.
    Returns (success, message).
    """
    # Skip hand-authored HTML files — they have no source Markdown
    if doc.get("handAuthored") or "source" not in doc:
        return True, "hand-authored (skipped)"

    src = REPO_ROOT / doc["source"]
    out = REPO_ROOT / doc["output"]

    if not src.exists():
        return False, f"MISSING SOURCE: {doc['source']}"

    stale = force or is_stale(src, out, compiler_path)
    if not stale:
        return True, "up-to-date"

    if check_only:
        return False, "STALE"

    out.parent.mkdir(parents=True, exist_ok=True)

    if compiler_type == "tessel":
        # node tessel-cli.js --title "..." [--collapsible] [--playbook] src.md out.html
        flags = doc.get("flags", [])
        cmd = [
            "node",
            str(compiler_path),
            "--title", doc.get("title", ""),
        ] + flags + [str(src), str(out)]
    else:
        # python md_to_html.py --title "..." --manifest path [flags] src.md out.html
        cmd = [
            sys.executable,
            str(compiler_path),
            "--title", doc.get("title", ""),
            "--manifest", str(MANIFEST_PATH),
        ] + doc.get("flags", []) + [str(src), str(out)]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        size = out.stat().st_size if out.exists() else 0
        tag = f"[{compiler_type}]"
        return True, f"regenerated {tag} ({size:,} bytes)"
    else:
        return False, f"FAILED: {result.stderr.strip()[:300]}"


def main():
    ap = argparse.ArgumentParser(
        description="Regenerate all broodforge HTML docs from their Markdown sources."
    )
    ap.add_argument(
        "--check", action="store_true",
        help="Report which docs are stale without regenerating."
    )
    ap.add_argument(
        "--force", action="store_true",
        help="Regenerate all docs even if they appear up-to-date."
    )
    ap.add_argument(
        "--id", metavar="ID",
        help="Regenerate a single doc by its manifest id."
    )
    ap.add_argument(
        "--type", metavar="TYPE",
        help="Regenerate only docs of a given type (runbook, guide, reference, index)."
    )
    ap.add_argument(
        "--python", action="store_true",
        help="Force the Python compiler (md_to_html.py) even when Tessel is available."
    )
    args = ap.parse_args()

    compiler_type, compiler_path = _resolve_compiler(force_python=args.python)

    manifest = load_manifest()
    docs = manifest["docs"]

    # Apply filters
    if args.id:
        docs = [d for d in docs if d["id"] == args.id]
        if not docs:
            print(f"ERROR: No doc with id {args.id!r} in manifest.", file=sys.stderr)
            sys.exit(1)
    if args.type:
        docs = [d for d in docs if d.get("type") == args.type]
        if not docs:
            print(f"ERROR: No docs of type {args.type!r} in manifest.", file=sys.stderr)
            sys.exit(1)

    width = max(len(d["id"]) for d in docs) if docs else 20
    ok = stale = missing = failed = 0

    compiler_label = f"tessel ({compiler_path})" if compiler_type == "tessel" else f"python ({compiler_path.name})"
    print(f"Broodforge doc regeneration — {len(docs)} doc(s)")
    print(f"Compiler: {compiler_label}")
    print(f"Mode: {'check-only' if args.check else 'force-all' if args.force else 'incremental'}")
    print()

    for doc in docs:
        success, msg = regenerate(
            doc,
            compiler_type=compiler_type,
            compiler_path=compiler_path,
            force=args.force,
            check_only=args.check,
        )
        doc_id = doc["id"].ljust(width)
        if "MISSING" in msg:
            print(f"  ⚠  {doc_id}  {msg}")
            missing += 1
        elif "STALE" in msg:
            print(f"  ↺  {doc_id}  needs regeneration  ({doc.get('source','')} → {doc['output']})")
            stale += 1
        elif "FAILED" in msg:
            print(f"  ✗  {doc_id}  {msg}")
            failed += 1
        elif msg == "up-to-date":
            print(f"  ✓  {doc_id}  up-to-date")
            ok += 1
        elif "hand-authored" in msg:
            print(f"  ⊙  {doc_id}  {msg}")
            ok += 1
        else:
            print(f"  ✓  {doc_id}  {msg}")
            ok += 1

    print()
    if args.check:
        if stale or missing:
            print(f"  {stale} stale, {missing} missing source, {ok} up-to-date")
            print("  Run without --check to regenerate.")
            sys.exit(1)
        else:
            print(f"  All {ok} docs up-to-date.")
    else:
        if failed or missing:
            print(f"  {ok} regenerated, {failed} failed, {missing} missing source")
            sys.exit(1)
        else:
            print(f"  {ok} docs regenerated successfully.")


if __name__ == "__main__":
    main()
