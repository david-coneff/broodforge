#!/usr/bin/env python3
"""
assemble-forge-package.py — CLI entry point for the forge package assembler.

Usage:
    python3 assemble-forge-package.py \\
        --manifest forge-manifest.json \\
        [--output-dir /opt/broodforge/forge-packages] \\
        [--repo /path/to/broodforge] \\
        [--kdbx /path/to/cell.kdbx]

Produces:
    forge-package-{cell_id}-{timestamp}.tar.gz
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))

from assemble_forge_package import assemble_forge_package


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Assemble a forge package for bare-metal Proxmox provisioning",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--manifest", required=True,
        help="Path to forge-manifest.json",
    )
    parser.add_argument(
        "--output-dir", default=".",
        help="Directory to write the package into (default: current directory)",
    )
    parser.add_argument(
        "--repo", default=None,
        help="Path to broodforge repo to bundle library code "
             "(default: inferred from this script's location)",
    )
    parser.add_argument(
        "--kdbx", default=None,
        help="Path to KeePass .kdbx to embed in the package (optional)",
    )
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print(f"[error] Manifest not found: {manifest_path}", file=sys.stderr)
        sys.exit(1)

    with open(manifest_path) as f:
        manifest = json.load(f)

    kdbx_path = Path(args.kdbx) if args.kdbx else None
    if kdbx_path and not kdbx_path.exists():
        print(f"[error] KeePass database not found: {kdbx_path}", file=sys.stderr)
        sys.exit(1)

    # The forge phase scripts invoke python3 "$SCRIPT_DIR/proxmox-bootstrap/*.py"
    # at runtime, so the package MUST bundle the library code. When --repo is not
    # given, infer the repo root from this script's location (it lives in
    # proxmox-bootstrap/) so the documented happy path produces a self-contained
    # package rather than one that fails at phase-00.
    if args.repo:
        repo_dir = Path(args.repo)
    else:
        inferred = _HERE.parent
        repo_dir = inferred if (inferred / "proxmox-bootstrap").is_dir() else None
        if repo_dir is None:
            print("[warn] Could not infer repo root; package will NOT bundle "
                  "library code. Pass --repo to bundle proxmox-bootstrap/, "
                  "data-model/, and doc-gen/.", file=sys.stderr)

    pkg = assemble_forge_package(
        manifest=manifest,
        output_dir=Path(args.output_dir),
        repo_dir=repo_dir,
        kdbx_path=kdbx_path,
    )

    cell_id  = manifest.get("cell_id", "unknown")
    hostname = (manifest.get("host_identity") or {}).get("hostname", "unknown")
    profile  = (manifest.get("network_topology") or {}).get("profile", "unknown")

    print(f"\n{'=' * 64}")
    print(f"  Forge Package Assembled")
    print(f"{'=' * 64}")
    print(f"  Package:  {pkg}")
    print(f"  SHA-256:  {hashlib.sha256(pkg.read_bytes()).hexdigest()}")
    print(f"  Cell:     {cell_id}")
    print(f"  Host:     {hostname}")
    print(f"  Profile:  {profile}")
    print(f"\n  Next steps:")
    print(f"    1. Copy {pkg.name} to the bare-metal Proxmox host")
    print(f"    2. Extract: tar -xzf {pkg.name}")
    print(f"    3. Run:     bash forge.sh")
    print()


if __name__ == "__main__":
    main()
