#!/usr/bin/env python3
"""
assemble-phoenix-package.py — CLI entry point for the phoenix package assembler.

Usage:
    python3 assemble-phoenix-package.py \\
        --playbook phoenix-playbook.json \\
        [--output-dir /opt/broodforge/phoenix-packages] \\
        [--kdbx /path/to/cell.kdbx]

Produces:
    phoenix-package-{cell_id}-{hostname}-{timestamp}.tar.gz
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))

from assemble_phoenix_package import assemble_phoenix_package


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Assemble a phoenix restoration package",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--playbook", required=True,
        help="Path to phoenix-playbook.json",
    )
    parser.add_argument(
        "--output-dir", default=".",
        help="Directory to write the package into (default: current directory)",
    )
    parser.add_argument(
        "--kdbx", default=None,
        help="Path to KeePass .kdbx to embed in the package (optional)",
    )
    args = parser.parse_args()

    playbook_path = Path(args.playbook)
    if not playbook_path.exists():
        print(f"[error] Playbook not found: {playbook_path}", file=sys.stderr)
        sys.exit(1)

    with open(playbook_path) as f:
        playbook = json.load(f)

    kdbx_path = Path(args.kdbx) if args.kdbx else None
    if kdbx_path and not kdbx_path.exists():
        print(f"[error] KeePass database not found: {kdbx_path}", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir)
    pkg = assemble_phoenix_package(
        playbook=playbook,
        output_dir=output_dir,
        kdbx_path=kdbx_path,
    )

    node = (playbook.get("target_node") or {}).get("hostname", "unknown")
    cell_id = playbook.get("cell_id", "unknown")
    scope = playbook.get("restoration_scope", "full")
    waves = playbook.get("waves") or []

    print(f"\n{'=' * 64}")
    print(f"  Phoenix Package Assembled")
    print(f"{'=' * 64}")
    print(f"  Package:  {pkg}")
    print(f"  SHA-256:  {hashlib.sha256(pkg.read_bytes()).hexdigest()}")
    print(f"  Cell:     {cell_id}")
    print(f"  Node:     {node}")
    print(f"  Scope:    {scope}")
    print(f"  Waves:    {len(waves)}")
    print(f"\n  Next steps:")
    print(f"    1. Copy {pkg.name} to the replacement hardware")
    print(f"    2. Extract: tar -xzf {pkg.name}")
    print(f"    3. Run:     bash run-all.sh")
    print()


if __name__ == "__main__":
    main()
