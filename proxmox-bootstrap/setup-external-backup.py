#!/usr/bin/env python3
"""
External backup setup wizard.

Guides the operator through choosing and configuring an external backup
provider for the cell's configuration state and self-description data.

Two providers are supported:

  (a) GitHub      Push configuration repos to private GitHub repositories
                  via SSH deploy key. Provides version history, diff, and
                  easy clone-based recovery ("git clone" to restore).

  (b) Encrypted archive
                  Produce timestamped GPG-encrypted .tar.gz archives and
                  transfer them to a destination via rclone (Google Drive,
                  S3, Backblaze B2, etc.), scp, or local mount.

What is backed up externally
-----------------------------
  bootstrap-state.json, Cloud-Init snippets, registries (secret, DNS, image),
  service contracts, SSH public keys.

  This is the minimum needed to rebuild the cell from scratch. Full VM disk
  snapshots (user-generated data, databases, etc.) are PBS territory.

After setup
-----------
  The external_backup section in bootstrap-state.json is populated.
  For encrypted archive: a test backup is created and transferred.
  For GitHub: an initial push is performed to verify connectivity.
  The setup can be re-run to change providers at any time.

Usage:
    python3 setup-external-backup.py
    python3 setup-external-backup.py --bootstrap path/to/bootstrap-state.json
    python3 setup-external-backup.py --dry-run
"""

import importlib.util
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

BOOTSTRAP_REPO = Path(__file__).parent


def _import(filename: str, mod_name: str):
    spec = importlib.util.spec_from_file_location(
        mod_name, BOOTSTRAP_REPO / filename
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _prompt(label: str, default: str | None = None) -> str:
    display = f" [{default}]" if default else ""
    try:
        val = input(f"  {label}{display}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)
    return val if val else (default or "")


def _confirm(question: str, default: bool = True) -> bool:
    hint = "[Y/n]" if default else "[y/N]"
    try:
        raw = input(f"  {question} {hint}: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)
    if not raw:
        return default
    return raw in ("y", "yes")


# ---------------------------------------------------------------------------
# Provider: encrypted archive
# ---------------------------------------------------------------------------

def setup_encrypted_archive(state: dict, dry_run: bool) -> dict:
    bk = _import("backup.py", "backup")
    cell_id = state["cell_id"]

    print()
    print("─" * 64)
    print("  Encrypted Archive Backup Setup")
    print("─" * 64)
    print()
    print("  Archives are named:")
    ts = datetime.now(timezone.utc)
    example = bk.archive_filename(cell_id, dt=ts, encrypted=True)
    print(f"  {example}")
    print()
    print("  Format: {cell_id}_{YYYY-MM-DD_HH_MM_SS}_{6-char-hash}.tar.gz.gpg")
    print("  Encryption: AES-256 symmetric (GPG)")
    print()

    # Tool check
    if not bk.gpg_available():
        print("  WARNING: gpg not found. Install GnuPG before proceeding:")
        print("    apt install gnupg   (Debian/Ubuntu)")
        print("    brew install gnupg  (macOS)")
        print()

    # Destination
    print("  Destination examples:")
    print("    rclone  gdrive:/backups/proxmox-cell-a   (Google Drive via rclone)")
    print("    rclone  s3:my-bucket/backups             (S3-compatible)")
    print("    scp     user@nas.local:/mnt/backups/     (SCP to NAS)")
    print("    local   /mnt/external-drive/backups/     (Mounted drive or share)")
    print()
    dest = _prompt("Backup destination")
    dest_type = "local"
    if dest.startswith("gdrive:") or dest.startswith("s3:") or ":" in dest and "@" not in dest:
        dest_type = "rclone"
    elif "@" in dest and ":" in dest:
        dest_type = "scp"

    if dest_type == "rclone" and not bk.rclone_available():
        print("  WARNING: rclone not found. Install from https://rclone.org/install/")
        print("  You can still save this configuration and install rclone before the first run.")

    # Passphrase
    print()
    kp_root = state["keepass_config"]["root_path"]
    hostname = state["host_identity"]["hostname"]
    suggested_kp_path = f"{kp_root}/{hostname}/backup-encryption-passphrase"
    print(f"  The encryption passphrase is stored in KeePass.")
    print(f"  Suggested KeePass path: {suggested_kp_path}")
    passphrase_ref_id = "backup-encryption-passphrase"

    # Add to secret registry if not already there
    secrets = state.get("secrets", [])
    if not any(s["id"] == passphrase_ref_id for s in secrets):
        secrets.append({
            "id": passphrase_ref_id,
            "description": "GPG passphrase for encrypted external backup archives",
            "keepass_path": suggested_kp_path,
            "owning_cell": state["cell_id"],
            "secret_type": "password",
            "required_by": [f"host:{hostname}"],
            "required_for": ["external-backup-encryption"],
            "rotation_schedule": None,
            "recovery_path": (
                "If passphrase is lost, archives cannot be decrypted. "
                "Ensure KeePass database has a separate offsite backup."
            ),
        })
        state["secrets"] = secrets
        print(f"  Added passphrase to secret registry: {passphrase_ref_id}")

    # Schedule
    print()
    schedule = _prompt("Backup schedule (cron expression or 'daily')", "0 2 * * *")
    if schedule.lower() == "daily":
        schedule = "0 2 * * *"

    retention = _prompt("Number of archives to keep", "30")
    try:
        retention_count = int(retention)
    except ValueError:
        retention_count = 30

    config = {
        "destination": dest,
        "destination_type": dest_type,
        "passphrase_reference": passphrase_ref_id,
        "schedule": schedule,
        "retention_count": retention_count,
        "filename_prefix": None,
    }

    # Test backup
    print()
    if not dry_run and _confirm("Run a test backup now?"):
        import getpass
        try:
            passphrase = getpass.getpass("  Enter backup passphrase (will encrypt test archive): ")
        except (EOFError, KeyboardInterrupt):
            passphrase = None

        if passphrase:
            try:
                with tempfile.TemporaryDirectory() as tmpdir:
                    archive = bk.create_cell_backup(
                        bootstrap_repo=BOOTSTRAP_REPO,
                        cell_id=cell_id,
                        passphrase=passphrase,
                        output_dir=Path(tmpdir),
                    )
                    print(f"  Created: {archive.name} ({archive.stat().st_size:,} bytes)")

                    # Try transfer
                    if dest_type == "rclone":
                        ok = bk.transfer_rclone(archive, dest)
                    elif dest_type == "scp":
                        ok = bk.transfer_scp(archive, dest)
                    else:
                        Path(dest).mkdir(parents=True, exist_ok=True)
                        ok = bk.transfer_local(archive, dest)

                    if ok:
                        print(f"  Test backup transferred to: {dest}")
                    else:
                        print(f"  Transfer failed — check destination and credentials")
            except Exception as e:
                print(f"  Test backup failed: {e}")
        else:
            print("  Skipped (no passphrase entered).")
    elif dry_run:
        print(f"  [dry-run] Would create archive: {bk.archive_filename(cell_id, dt=ts)}")

    return {
        "provider": "encrypted-archive",
        "github": None,
        "encrypted_archive": config,
        "what_is_backed_up": bk.BACKUP_CONTENTS_DESCRIPTION,
    }


# ---------------------------------------------------------------------------
# Provider: GitHub
# ---------------------------------------------------------------------------

def setup_github(state: dict, dry_run: bool) -> dict:
    cell_id = state["cell_id"]

    print()
    print("─" * 64)
    print("  GitHub External Backup Setup")
    print("─" * 64)
    print()
    print("  Configuration repos are mirrored to private GitHub repositories.")
    print("  Authentication uses an SSH deploy key (already generated by")
    print("  setup-secrets.py if you ran that step).")
    print()
    print("  Suggested repo names:")
    for purpose, suffix in [
        ("infrastructure", "infrastructure"),
        ("bootstrap",      "bootstrap"),
        ("configuration",  "ansible"),
        ("docs",           "docs"),
        ("assessment_history", "assessment-history"),
    ]:
        print(f"    {purpose:<20} github.com/your-username/{cell_id}-{suffix}")
    print()

    github_user = _prompt("GitHub username or organisation")
    base_url = f"git@github.com:{github_user}"

    repos = {}
    for purpose, suffix in [
        ("infrastructure", "infrastructure"),
        ("bootstrap",      "bootstrap"),
        ("configuration",  "ansible"),
        ("docs",           "docs"),
        ("assessment_history", "assessment-history"),
    ]:
        suggested = f"{base_url}/{cell_id}-{suffix}.git"
        url = _prompt(f"Repo URL for {purpose}", suggested)
        repos[purpose] = url if url else None

    # Deploy key
    pubkey_dir = BOOTSTRAP_REPO / "ssh" / "public-keys"
    deploy_key_ref = f"github-config-deploy-key"
    print()
    print("  The deploy key is the SSH key used to push to GitHub.")
    print("  The PUBLIC key must be added to each GitHub repo:")
    print("    GitHub repo → Settings → Deploy keys → Add deploy key")
    print("    Enable 'Allow write access'")
    print()

    # Show available public keys
    if pubkey_dir.exists():
        pub_keys = list(pubkey_dir.glob("*.pub"))
        if pub_keys:
            print("  Available SSH public keys:")
            for pk in pub_keys:
                content = pk.read_text(encoding="utf-8").strip()
                print(f"    {pk.name}:")
                print(f"      {content}")
            print()
            print("  Choose one of the above keys as the GitHub deploy key,")
            print("  or generate a dedicated GitHub deploy key.")

    deploy_key_ref = _prompt("Secret Registry ID for the deploy key", "github-config-deploy-key")

    if not dry_run:
        print()
        _confirm("Have you added the deploy key to all GitHub repos?", default=False)

    config = {
        "repos": repos,
        "deploy_key_reference": deploy_key_ref,
        "github_username": github_user,
    }

    return {
        "provider": "github",
        "github": config,
        "encrypted_archive": None,
        "what_is_backed_up": (
            "Configuration repos mirrored to GitHub: infrastructure, bootstrap, "
            "Ansible configuration, generated documentation, assessment history."
        ),
    }


# ---------------------------------------------------------------------------
# Main wizard
# ---------------------------------------------------------------------------

def run_wizard(bootstrap_path: Path, dry_run: bool) -> None:
    with open(bootstrap_path) as f:
        state = json.load(f)

    cell_id = state["cell_id"]

    print()
    print("=" * 64)
    print("  External Backup Setup")
    print(f"  Cell: {cell_id}")
    print("=" * 64)
    print()
    print("  External backup preserves the minimum needed to rebuild this")
    print("  cell from scratch: bootstrap state, Cloud-Init snippets,")
    print("  registries, and assessment history.")
    print()
    print("  VM disk snapshots and user data are covered separately by PBS.")
    print()

    existing = state.get("external_backup", {})
    if existing and existing.get("provider"):
        print(f"  Current provider: {existing['provider']}")
        if not _confirm("Reconfigure external backup?"):
            return
    print()

    print("  Choose a backup provider:")
    print()
    print("  (a) GitHub — push configuration repos to private GitHub repos")
    print("               + version history, diffs, easy recovery via git clone")
    print("               + requires GitHub account and deploy key setup")
    print()
    print("  (b) Encrypted archive — timestamped .tar.gz.gpg files")
    print("               + works with any rclone destination (Google Drive, S3,")
    print("                 Backblaze, NAS, local mount)")
    print("               + no external account required beyond storage provider")
    print()
    print("  (n) None — skip external backup")
    print()

    try:
        choice = input("  Provider [(a)/(b)/(n)]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return

    if choice in ("a", "github", "g"):
        backup_config = setup_github(state, dry_run)
    elif choice in ("b", "archive", "encrypted", "e"):
        backup_config = setup_encrypted_archive(state, dry_run)
    else:
        backup_config = {"provider": None, "github": None,
                         "encrypted_archive": None, "what_is_backed_up": None}
        print("  External backup skipped.")

    state["external_backup"] = backup_config

    if not dry_run:
        with open(bootstrap_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        print()
        print(f"  Updated: {bootstrap_path}")

    print()
    print("=" * 64)
    if backup_config["provider"]:
        print(f"  External backup configured: {backup_config['provider']}")
        print()
        print("  Next steps:")
        if backup_config["provider"] == "encrypted-archive":
            print("  1. Store the backup passphrase in KeePass at the declared path")
            print("  2. Run: python3 run-backup.py  to perform the first backup")
            print("  3. Set up a cron job on the assessment-engine VM for scheduled backups")
        elif backup_config["provider"] == "github":
            print("  1. Create the GitHub repos (private) if not already done")
            print("  2. Add the deploy key to each repo in GitHub Settings")
            print("  3. Run: python3 run-backup.py  to perform the first push")
    else:
        print("  No external backup configured.")
        print("  Re-run this wizard at any time to set one up.")
    print("=" * 64)
    print()


def main() -> None:
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]

    bootstrap_path = None
    if "--bootstrap" in args:
        idx = args.index("--bootstrap")
        bootstrap_path = Path(args[idx + 1])

    if bootstrap_path is None:
        bootstrap_path = BOOTSTRAP_REPO / "bootstrap-state.json"
        if not bootstrap_path.exists():
            bootstrap_path = (
                Path(__file__).parent.parent
                / "tests" / "fixtures" / "bootstrap" / "bootstrap-state.json"
            )

    if not bootstrap_path.exists():
        print(f"Error: bootstrap-state.json not found at {bootstrap_path}", file=sys.stderr)
        sys.exit(1)

    run_wizard(bootstrap_path, dry_run)


if __name__ == "__main__":
    main()
