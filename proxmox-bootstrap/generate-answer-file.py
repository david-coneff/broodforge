#!/usr/bin/env python3
"""
generate-answer-file.py — CLI entry point for Proxmox VE answer-file generation
(Phase 1.H, AD-057 — Pre-Install Forge Package and Image Builder).

Derives a Proxmox VE 8+ automated-installer `answer.toml` directly from a
`forge-manifest.json` so the operator answers setup questions exactly once
(hostname, network, timezone, disk layout) and gets a ready-to-use answer file
without building the full bootstrap image staging bundle.

This is useful for:
  - Reviewing / editing answer.toml before committing to a full image build
  - Re-generating answer.toml after tweaking forge-manifest.json fields
  - Operators who use their own tooling to package or deploy the answer file

For a full bootstrap image staging bundle (answer.toml + embedded forge package
+ first-boot hook), see generate-bootstrap-image.py instead.

Usage:
    python3 generate-answer-file.py \\
        --manifest forge-manifest.json \\
        [--output answer.toml] \\
        [--keyboard en-us] [--country us] [--filesystem zfs] \\
        [--disk /dev/sda --disk /dev/sdb] \\
        [--interface enp3s0]

Produces:
    answer.toml (or stdout if --output is omitted)
"""

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))

from _image_builder import generate_answer_toml, generate_install_passphrase


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a Proxmox VE 8+ automated-installer answer.toml "
                    "from forge-manifest.json (Phase 1.H, AD-057)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--manifest", required=True,
        help="Path to forge-manifest.json",
    )
    parser.add_argument(
        "--output", default=None,
        help="Where to write answer.toml (default: print to stdout)",
    )
    parser.add_argument(
        "--keyboard", default="en-us",
        help="Keyboard layout for [global] (default: en-us)",
    )
    parser.add_argument(
        "--country", default="us",
        help="ISO country code for [global] (default: us)",
    )
    parser.add_argument(
        "--filesystem", default="zfs", choices=["zfs", "ext4", "xfs", "btrfs"],
        help="Root filesystem for [disk-setup] (default: zfs)",
    )
    parser.add_argument(
        "--disk", action="append", default=None, dest="disks",
        help="Disk device for [disk-setup] disk-list "
             "(repeatable; default: a placeholder the operator must populate). "
             "Discover with: lsblk  (on target hardware)",
    )
    parser.add_argument(
        "--interface", default=None,
        help="Network interface name for [network] filter.ID_NET_NAME "
             "(e.g. enp3s0, eth0). REQUIRED for automated installer — discover "
             "with 'ip link show' on the target hardware before building.",
    )
    args = parser.parse_args()

    # Warn about mandatory placeholder values that will need filling before use.
    _placeholders = []
    if not args.interface:
        _placeholders.append(
            "  --interface <name>  (e.g. --interface enp3s0)\n"
            "                      Discover with: ip link show  (on target hardware)"
        )
    if not args.disks:
        _placeholders.append(
            "  --disk <device>     (e.g. --disk /dev/sda)\n"
            "                      Discover with: lsblk  (on target hardware)"
        )
    if _placeholders:
        print(
            "[warn] answer.toml will contain placeholder values for the following "
            "hardware-specific fields. Populate them before using the file:\n" +
            "\n".join(_placeholders),
            file=sys.stderr,
        )

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print(f"[error] Manifest not found: {manifest_path}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(manifest_path) as f:
            manifest = json.load(f)
    except json.JSONDecodeError as exc:
        print(f"[error] Manifest is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(1)

    passphrase = generate_install_passphrase()
    answer_toml = generate_answer_toml(
        manifest,
        root_passphrase=passphrase,
        keyboard=args.keyboard,
        country=args.country,
        filesystem=args.filesystem,
        disk_list=args.disks,
        interface_name=args.interface,
    )

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(answer_toml, encoding="utf-8")
        print(f"[ok] answer.toml written to: {output_path}")
    else:
        print(answer_toml, end="")
        # When writing to stdout, surface the passphrase warning on stderr so it
        # is visible regardless of whether stdout is redirected to a file.
        print("", file=sys.stderr)

    cell_id = manifest.get("cell_id", "unknown")
    hostname = (manifest.get("host_identity") or {}).get("hostname", "unknown")

    print(f"{'!' * 64}", file=sys.stderr)
    print(f"  !! SINGLE-USE INSTALL PASSPHRASE — RECORD THIS NOW !!", file=sys.stderr)
    print(f"{'!' * 64}", file=sys.stderr)
    print(f"", file=sys.stderr)
    print(f"    {passphrase}", file=sys.stderr)
    print(f"", file=sys.stderr)
    print(f"  Cell:    {cell_id}  |  Host: {hostname}", file=sys.stderr)
    print(f"  This passphrase is the answer.toml root-password. It will NOT be", file=sys.stderr)
    print(f"  stored anywhere by broodforge. Write it down before using the file.", file=sys.stderr)
    print(f"  It is replaced by a KeePass-managed credential during forge phase-03.", file=sys.stderr)
    print(f"{'!' * 64}", file=sys.stderr)
    print(f"", file=sys.stderr)


if __name__ == "__main__":
    main()
