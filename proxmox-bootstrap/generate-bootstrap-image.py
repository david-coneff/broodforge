#!/usr/bin/env python3
"""
generate-bootstrap-image.py — CLI entry point for the bootstrap image builder
(Phase 1.H, AD-057 — Pre-Install Forge Package and Image Builder).

Consumes forge-manifest.json and produces a "bootstrap image staging bundle":
a structured tar.gz that documents and stages everything an operator combines
with the official Proxmox VE ISO to produce bootable pre-install media —
answer.toml (derived from the manifest), the assembled forge package, and a
first-boot hook that runs forge.sh automatically once the new host comes up.

This is NOT a literal bootable ISO — see the bundle's README.md (and
_image_builder.py's docstring) for why, and what the operator does with it.

Usage:
    python3 generate-bootstrap-image.py \\
        --manifest forge-manifest.json \\
        [--output-dir /opt/broodforge/bootstrap-images] \\
        [--repo /path/to/broodforge] \\
        [--kdbx /path/to/cell.kdbx] \\
        [--keyboard en-us] [--country us] [--filesystem zfs] \\
        [--disk /dev/sda --disk /dev/sdb]

Produces:
    bootstrap-image-{cell_id}-{timestamp}.tar.gz
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))

from _image_builder import (
    build_bootstrap_image,
    build_pregenerated_spawn_media_record,
    record_pending_join_authorization,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a pre-install bootstrap image staging bundle (Phase 1.H/1.J, AD-057/AD-060)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--manifest", required=True,
        help="Path to forge-manifest.json",
    )
    parser.add_argument(
        "--output-dir", default=".",
        help="Directory to write the bundle into (default: current directory)",
    )
    parser.add_argument(
        "--repo", default=None,
        help="Path to broodforge repo to bundle library code into the embedded "
             "forge package (default: inferred from this script's location)",
    )
    parser.add_argument(
        "--kdbx", default=None,
        help="Path to KeePass .kdbx to embed in the embedded forge package (optional)",
    )
    parser.add_argument(
        "--keyboard", default="en-us",
        help="Keyboard layout for answer.toml [global] (default: en-us)",
    )
    parser.add_argument(
        "--country", default="us",
        help="ISO country code for answer.toml [global] (default: us)",
    )
    parser.add_argument(
        "--filesystem", default="zfs", choices=["zfs", "ext4", "xfs", "btrfs"],
        help="Root filesystem for answer.toml [disk-setup] (default: zfs)",
    )
    parser.add_argument(
        "--disk", action="append", default=None, dest="disks",
        help="Disk device for answer.toml [disk-setup] disk-list "
             "(repeatable; default: a placeholder the operator must populate)",
    )
    parser.add_argument(
        "--interface", default=None,
        help="Network interface name for answer.toml [network] filter.ID_NET_NAME "
             "(e.g. enp3s0, eth0). REQUIRED for automated installer — discover with "
             "'ip link show' on the target hardware before building.",
    )
    parser.add_argument(
        "--state", default=None,
        help="Path to bootstrap-state.json. When provided, a pending-join-authorization "
             "record is appended so authorize-spawn-media-join.py can gate the resulting "
             "node before it joins the cell (Phase 1.J, AD-060(c)). Required for "
             "pre-generated spawn media; optional for plain bootstrap images.",
    )
    args = parser.parse_args()

    # Validate mandatory answer.toml fields at build time (F-018):
    # These placeholders in the generated answer.toml will cause the Proxmox
    # installer to fail at network or disk setup with cryptic errors.
    _missing = []
    if not args.interface:
        _missing.append(
            "  --interface <name>  (e.g. --interface enp3s0)\n"
            "                      Discover with: ip link show  (on target hardware)"
        )
    if not args.disks:
        _missing.append(
            "  --disk <device>     (e.g. --disk /dev/sda)\n"
            "                      Discover with: lsblk  (on target hardware)"
        )
    if _missing:
        print(
            "[error] answer.toml cannot be built with mandatory placeholder values.\n"
            "[error] Provide the following before building the image:\n" +
            "\n".join(_missing) + "\n"
            "[error] These values are specific to the target hardware and cannot be\n"
            "[error] auto-detected at build time. Boot a live OS on the target to\n"
            "[error] discover them, then re-run this command.",
            file=sys.stderr,
        )
        sys.exit(1)

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

    if args.repo:
        repo_dir = Path(args.repo)
    else:
        inferred = _HERE.parent
        repo_dir = inferred if (inferred / "proxmox-bootstrap").is_dir() else None
        if repo_dir is None:
            print("[warn] Could not infer repo root; embedded forge package will NOT "
                  "bundle library code. Pass --repo to bundle it.", file=sys.stderr)

    # Build passphrase + authorization record together (N-004 fix: Phase 1.J wiring).
    # build_pregenerated_spawn_media_record() returns both the plaintext passphrase
    # (shown once to the operator, never persisted) and the authorization_record
    # (only the hash — safe to persist in bootstrap-state.json).
    spawn_media = build_pregenerated_spawn_media_record(manifest)
    passphrase = spawn_media["passphrase"]
    authorization_record = spawn_media["authorization_record"]
    bundle_name = spawn_media["image_bundle_name"]

    bundle = build_bootstrap_image(
        manifest=manifest,
        output_dir=Path(args.output_dir),
        repo_dir=repo_dir,
        kdbx_path=kdbx_path,
        root_passphrase=passphrase,
        keyboard=args.keyboard,
        country=args.country,
        filesystem=args.filesystem,
        disk_list=args.disks,
        interface_name=args.interface,
    )

    cell_id = manifest.get("cell_id", "unknown")
    hostname = (manifest.get("host_identity") or {}).get("hostname", "unknown")

    print(f"\n{'=' * 64}")
    print(f"  Bootstrap Image Staging Bundle Built")
    print(f"{'=' * 64}")
    print(f"  Bundle:   {bundle}")
    print(f"  SHA-256:  {hashlib.sha256(bundle.read_bytes()).hexdigest()}")
    print(f"  Cell:     {cell_id}")
    print(f"  Host:     {hostname}")
    print(f"\n{'!' * 64}")
    print(f"  !! SINGLE-USE INSTALL PASSPHRASE — RECORD THIS NOW !!")
    print(f"{'!' * 64}")
    print(f"")
    print(f"    {passphrase}")
    print(f"")
    print(f"  This passphrase is the answer.toml root-password for the automated")
    print(f"  Proxmox installer. It will NOT be stored anywhere by broodforge.")
    print(f"  Write it down or store it in a secure location BEFORE using the media.")
    print(f"  It is replaced by a KeePass-managed credential during forge phase-03.")
    print(f"{'!' * 64}")
    print(f"\n  This is a STAGING BUNDLE, not a bootable ISO.")
    print(f"  Extract it and read iso-staging/README.md for how to combine it with")
    print(f"  the official Proxmox VE ISO to produce bootable media.")
    print()

    # Write pending-join-authorization record to bootstrap-state.json so
    # authorize-spawn-media-join.py can gate the node before it joins (N-004).
    state_path = Path(args.state) if args.state else None
    if state_path is not None:
        if not state_path.exists():
            print(f"[error] State file not found: {state_path}", file=sys.stderr)
            sys.exit(1)
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"[error] Could not parse {state_path}: {exc}", file=sys.stderr)
            sys.exit(1)
        state = record_pending_join_authorization(state, authorization_record)
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        print(f"  Authorization record written to: {state_path}")
        print(f"  Bundle name:  {bundle_name}")
        print(f"  Passph. hash: {authorization_record['passphrase_hash']}  (cross-check only)")
        print(f"\n  A node installed from this media must be authorized before it")
        print(f"  may join the cell. Run:")
        print(f"    python3 authorize-spawn-media-join.py \\")
        print(f"        --state {state_path} \\")
        print(f"        --bundle {bundle_name} \\")
        print(f"        --operator <your-name>")
        print()


if __name__ == "__main__":
    main()
