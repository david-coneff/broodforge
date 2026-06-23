#!/usr/bin/env python3
"""
setup-backup.py — Backup configuration wizard for broodforge.

Usage:
  python3 setup-backup.py --state bootstrap-state.json [--simple | --detailed]

Walks the operator through configuring backup destinations for all three layers:
  secrets  — KeePass database (rclone copy, no restic)
  config   — Bootstrap state + assessment history (restic, encrypted)
  appdata  — VM data volumes (restic, encrypted, opt-in)

Writes backup_config section to bootstrap-state.json.
"""

import argparse
import json
import sys
from pathlib import Path


def _load_state(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        print(f"Error: {path} not found", file=sys.stderr)
        sys.exit(1)
    return json.loads(p.read_text(encoding="utf-8"))


def _save_state(path: str, state: dict):
    Path(path).write_text(json.dumps(state, indent=2), encoding="utf-8")


def _prompt(message: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    val = input(f"{message}{suffix}: ").strip()
    return val or default


def _prompt_bool(message: str, default: bool = True) -> bool:
    default_str = "Y/n" if default else "y/N"
    val = input(f"{message} [{default_str}]: ").strip().lower()
    if not val:
        return default
    return val in ("y", "yes")


def _collect_destination_secrets() -> dict:
    print("\n  Destination type:")
    print("    1. local  — filesystem path or USB mount point")
    print("    2. rclone — any rclone-supported remote (Google Drive, B2, S3, etc.)")
    dtype_choice = _prompt("  Choice", "1")

    dest_id = _prompt("  Destination label (e.g. local-usb, gdrive-backup)", "local-secrets")

    if dtype_choice == "2":
        rclone_remote = _prompt("  rclone remote name (configured in ~/.config/rclone/rclone.conf)")
        root = _prompt("  Destination root path on remote (e.g. broodforge/secrets)")
        return {
            "id": dest_id,
            "type": "rclone",
            "rclone_remote": rclone_remote,
            "kdbx_destination_root": f"{rclone_remote}:{root}",
        }
    else:
        root = _prompt("  Local path (e.g. /mnt/usb/broodforge/secrets)", "/mnt/backup/secrets")
        return {
            "id": dest_id,
            "type": "local",
            "rclone_remote": None,
            "kdbx_destination_root": root,
        }


def _collect_destination_restic(layer: str) -> dict:
    print(f"\n  Destination type for {layer}:")
    print("    1. local  — filesystem path")
    print("    2. b2     — Backblaze B2 (see docs/CLOUD-STORAGE-SETUP.md)")
    print("    3. s3     — AWS S3 / Cloudflare R2 / MinIO")
    print("    4. rclone — any rclone remote (Google Drive, etc.)")
    dtype_choice = _prompt("  Choice", "1")

    dest_id = _prompt("  Destination label (e.g. local-drive, b2-cloud)", f"local-{layer}")
    retention = int(_prompt("  Snapshots to keep", "5"))
    kp_prefix = _prompt(
        "  KeePass path prefix for repo passwords",
        f"Backup/{layer}",
    )

    type_map = {"1": "local", "2": "b2", "3": "s3", "4": "rclone"}
    dest_type = type_map.get(dtype_choice, "local")

    dest: dict = {
        "id": dest_id,
        "type": dest_type,
        "rclone_remote": None,
        "restic_repo_password_keepass_prefix": kp_prefix,
        "retention_count": retention,
    }

    if dest_type == "local":
        root = _prompt("  Local path", f"/mnt/backup/{layer}")
        dest["restic_repo_root"] = root
    elif dest_type == "b2":
        bucket = _prompt("  B2 bucket name")
        dest["b2_bucket"] = bucket
        dest["restic_repo_root"] = f"b2:{bucket}"
    elif dest_type == "s3":
        endpoint = _prompt("  S3 endpoint (leave blank for AWS)", "")
        bucket   = _prompt("  S3 bucket name")
        dest["s3_bucket"]   = bucket
        dest["s3_endpoint"] = endpoint or None
        prefix = f"{endpoint.rstrip('/')}/{bucket}" if endpoint else f"s3:{bucket}"
        dest["restic_repo_root"] = prefix
    elif dest_type == "rclone":
        remote = _prompt("  rclone remote name")
        path   = _prompt(f"  Path on remote (e.g. broodforge/{layer})", f"broodforge/{layer}")
        dest["rclone_remote"]    = remote
        dest["restic_repo_root"] = f"{remote}:{path}"

    return dest


def _simple_wizard(state: dict) -> dict:
    cell_id = state.get("cell_id", "cell")
    print(f"\n=== Simple Backup Setup for cell: {cell_id} ===")
    print("Configure backup destinations. Add as many as you like.")
    print("Secrets (KeePass DB), config, and appdata layers can share destinations.")
    print()

    # Secrets layer
    print("─── Secrets Layer (KeePass database) ───────────────────────────────")
    print("The KeePass database is backed up as a plain rclone copy.")
    print("Transport credentials are stored in forge-manifest.json, not KeePass.")
    secrets_dests = []
    while True:
        d = _collect_destination_secrets()
        secrets_dests.append(d)
        if not _prompt_bool("  Add another secrets destination?", False):
            break

    # Config layer
    print("\n─── Config Layer (bootstrap-state, assessment history) ──────────────")
    print("Uses restic with per-backup unique encryption keys stored in KeePass.")
    config_dests = []
    while True:
        d = _collect_destination_restic("config")
        config_dests.append(d)
        if not _prompt_bool("  Add another config destination?", False):
            break

    # Appdata layer
    enable_appdata = _prompt_bool(
        "\nEnable application data backup? (VM data volumes — opt-in)", False
    )
    appdata_dests = []
    if enable_appdata:
        print("─── Appdata Layer (VM data volumes) ─────────────────────────────────")
        while True:
            d = _collect_destination_restic("appdata")
            appdata_dests.append(d)
            if not _prompt_bool("  Add another appdata destination?", False):
                break

    checkpoint_tag = _prompt("Checkpoint tag name", "checkpoint")
    policy_alert   = _prompt_bool("Alert on all-destinations-fail?", True)
    policy_block   = _prompt_bool("Block assessment on all-destinations-fail?", True)
    policy = []
    if policy_alert:
        policy.append("alert")
    if policy_block:
        policy.append("block_assessment")

    return {
        "layers": {
            "secrets": {
                "enabled": True,
                "destinations": secrets_dests,
                "last_backup_at": None,
                "last_successful_destination_id": None,
                "consecutive_all_fail_count": 0,
            },
            "config": {
                "enabled": True,
                "destinations": config_dests,
                "last_backup_at": None,
                "last_successful_destination_id": None,
                "consecutive_all_fail_count": 0,
            },
            "appdata": {
                "enabled": enable_appdata,
                "destinations": appdata_dests,
                "last_backup_at": None,
                "last_successful_destination_id": None,
                "consecutive_all_fail_count": 0,
            },
        },
        "checkpoint_tag": checkpoint_tag,
        "all_failed_policy": policy,
        "backup_history": [],
    }


def main():
    parser = argparse.ArgumentParser(description="broodforge backup setup wizard")
    parser.add_argument("--state",    required=True, help="Path to bootstrap-state.json")
    parser.add_argument("--simple",   action="store_true", help="Simple mode (default)")
    parser.add_argument("--detailed", action="store_true", help="Detailed per-component mode")
    args = parser.parse_args()

    state = _load_state(args.state)

    if args.detailed:
        print("Detailed mode: per-component backup configuration.")
        print("NOTE: detailed mode scaffold — full component-tree configuration coming in Phase 6.B.5.")
        print("Starting with simple mode as foundation...")

    backup_config = _simple_wizard(state)
    state["backup_config"] = backup_config
    _save_state(args.state, state)

    print(f"\n[setup-backup] Configuration written to {args.state}")
    print("[setup-backup] Run run-backup.py to execute the first backup.")


if __name__ == "__main__":
    main()
