#!/usr/bin/env python3
"""
External backup utilities for Infrastructure Cell bootstrap state.

Handles two backup providers:
  github            Mirror config repos to private GitHub repositories via SSH deploy key.
  encrypted-archive Produce timestamped GPG-encrypted tar.gz archives, transferred
                    to a destination via rclone, scp, or local copy.

Archive filename format
-----------------------
  {cell_id}_{YYYY-MM-DD_HH_MM_SS}_{6-char-hash}.tar.gz.gpg

  Timestamp: UTC, 24-hour time, underscores as separators (filesystem-safe).
  Short hash: first 6 hex characters of sha256(cell_id + timestamp_string).
              Deterministic — regenerating the same cell_id + timestamp always
              produces the same hash, so archives can be identified from logs.

  Example: proxmox-cell-a_2026-05-31_14_30_00_a3f7b2.tar.gz.gpg

Archive contents
----------------
  The external backup covers configuration state and self-description data:
    bootstrap-state.json        — how to rebuild the cell
    snippets/                   — Cloud-Init templates
    registries (dns, secret)    — naming and secret path declarations
    assessment history/         — what the cell looked like over time
    generated docs/             — documentation output

  NOT included: VM disk images, personal user data, application databases.
  Those are PBS territory (VM-level backup → offsite via rclone separately).

Importable by setup-external-backup.py and run-backup.py.
"""

import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Archive filename generation
# ---------------------------------------------------------------------------

TIMESTAMP_FORMAT = "%Y-%m-%d_%H_%M_%S"


def archive_timestamp(dt: datetime | None = None) -> str:
    """
    Return a filesystem-safe UTC timestamp string.
    Format: YYYY-MM-DD_HH_MM_SS (24-hour, underscore-separated).
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    return dt.strftime(TIMESTAMP_FORMAT)


def archive_hash(cell_id: str, timestamp_str: str) -> str:
    """
    Return a 6-character hex hash for a given cell_id + timestamp.
    Deterministic: same inputs always produce the same hash.
    """
    payload = f"{cell_id}{timestamp_str}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:6]


def archive_filename(
    cell_id: str,
    dt: datetime | None = None,
    encrypted: bool = True,
    prefix: str | None = None,
) -> str:
    """
    Generate the archive filename for a given cell and timestamp.

    Parameters
    ----------
    cell_id : str
        Infrastructure Cell identifier, e.g. 'proxmox-cell-a'
    dt : datetime, optional
        Timestamp to embed. Defaults to now (UTC).
    encrypted : bool
        If True, filename ends in .tar.gz.gpg. If False, .tar.gz.
    prefix : str, optional
        Optional prefix prepended before cell_id.

    Returns
    -------
    str
        e.g. 'proxmox-cell-a_2026-05-31_14_30_00_a3f7b2.tar.gz.gpg'
    """
    ts = archive_timestamp(dt)
    short_hash = archive_hash(cell_id, ts)
    base = f"{cell_id}_{ts}_{short_hash}"
    if prefix:
        base = f"{prefix}_{base}"
    ext = ".tar.gz.gpg" if encrypted else ".tar.gz"
    return base + ext


def parse_archive_filename(filename: str) -> dict | None:
    """
    Parse a previously generated archive filename back into its components.

    Filename structure: {cell_id}_{YYYY-MM-DD}_{HH}_{MM}_{SS}_{hash}[.tar.gz[.gpg]]

    From the right, the fixed components are (5 underscores from right):
      hash (6 hex chars), SS, MM, HH, YYYY-MM-DD

    Everything before those 5 components is the cell_id.
    cell_ids should use hyphens not underscores (kebab-case convention).

    Returns dict with keys: cell_id, timestamp_str, short_hash, encrypted
    Returns None if the filename doesn't match the expected pattern.
    """
    stem = filename
    encrypted = False

    if stem.endswith(".tar.gz.gpg"):
        stem = stem[:-len(".tar.gz.gpg")]
        encrypted = True
    elif stem.endswith(".tar.gz"):
        stem = stem[:-len(".tar.gz")]
    else:
        return None

    # Split from right: we need exactly 5 splits to isolate
    # hash, SS, MM, HH, date — leaving cell_id as the remainder
    parts = stem.rsplit("_", 5)
    if len(parts) < 6:
        return None

    short_hash = parts[-1]    # 6-char hex
    ss = parts[-2]            # SS
    mm_time = parts[-3]       # MM
    hh = parts[-4]            # HH
    date_str = parts[-5]      # YYYY-MM-DD
    cell_id = "_".join(parts[:-5])  # everything before (usually has hyphens)

    # Validate: short hash must be 6 hex chars
    if len(short_hash) != 6 or not all(c in "0123456789abcdef" for c in short_hash):
        return None

    # Validate timestamp fields
    try:
        timestamp_str = f"{date_str}_{hh}_{mm_time}_{ss}"
        datetime.strptime(timestamp_str, TIMESTAMP_FORMAT)
    except ValueError:
        return None

    return {
        "cell_id": cell_id,
        "timestamp_str": timestamp_str,
        "short_hash": short_hash,
        "encrypted": encrypted,
    }


# ---------------------------------------------------------------------------
# Archive creation
# ---------------------------------------------------------------------------

# What is included in an external backup archive.
# Keys are labels; values are relative-to-bootstrap-repo paths.
BACKUP_CONTENTS = {
    "bootstrap_state":   "bootstrap-state.json",
    "snippets":          "snippets/",
    "secret_registry":   "secret-registry.yaml",
    "dns_registry":      "dns-registry.yaml",
    "image_registry":    "images/registry.yaml",
    "service_contracts": "service-contracts/",
    "ssh_public_keys":   "ssh/public-keys/",
}

BACKUP_CONTENTS_DESCRIPTION = (
    "bootstrap-state.json, Cloud-Init snippets, secret-registry.yaml, "
    "dns-registry.yaml, images/registry.yaml, service-contracts/, "
    "ssh/public-keys/"
)


def create_tar_archive(
    source_paths: list[tuple[str, Path]],  # (archive_name, source_path)
    output_path: Path,
) -> Path:
    """
    Create a .tar.gz archive from a list of (name, source_path) pairs.

    Parameters
    ----------
    source_paths : list of (archive_name, source_path)
        Files or directories to include. archive_name is the path inside
        the archive; source_path is the filesystem path to read from.
    output_path : Path
        Destination .tar.gz file path.

    Returns
    -------
    Path to the created archive.
    """
    with tarfile.open(output_path, "w:gz") as tar:
        for arcname, src in source_paths:
            if Path(src).exists():
                tar.add(src, arcname=arcname)
    return output_path


def encrypt_archive(
    archive_path: Path,
    output_path: Path,
    passphrase: str,
) -> Path:
    """
    GPG-encrypt a file using symmetric AES-256 encryption.

    Parameters
    ----------
    archive_path : Path
        Input file to encrypt.
    output_path : Path
        Destination encrypted file path (.gpg).
    passphrase : str
        Encryption passphrase (retrieved from KeePass by the caller).

    Returns
    -------
    Path to the encrypted file.

    Raises
    ------
    RuntimeError if gpg is not available or encryption fails.
    """
    gpg = shutil.which("gpg") or shutil.which("gpg2")
    if not gpg:
        raise RuntimeError(
            "gpg not found. Install GnuPG: "
            "apt install gnupg  (Debian/Ubuntu) or brew install gnupg  (macOS)"
        )

    cmd = [
        gpg, "--batch", "--yes",
        "--symmetric",
        "--cipher-algo", "AES256",
        "--compress-algo", "none",   # already compressed (tar.gz)
        "--passphrase-fd", "0",      # read passphrase from stdin
        "--output", str(output_path),
        str(archive_path),
    ]

    result = subprocess.run(
        cmd,
        input=passphrase,
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        raise RuntimeError(f"GPG encryption failed: {result.stderr.strip()}")

    return output_path


def decrypt_archive(
    encrypted_path: Path,
    output_path: Path,
    passphrase: str,
) -> Path:
    """Decrypt a GPG-encrypted archive. Inverse of encrypt_archive."""
    gpg = shutil.which("gpg") or shutil.which("gpg2")
    if not gpg:
        raise RuntimeError("gpg not found. Install GnuPG.")

    cmd = [
        gpg, "--batch", "--yes",
        "--decrypt",
        "--passphrase-fd", "0",
        "--output", str(output_path),
        str(encrypted_path),
    ]

    result = subprocess.run(
        cmd, input=passphrase, capture_output=True, text=True, timeout=120,
    )

    if result.returncode != 0:
        raise RuntimeError(f"GPG decryption failed: {result.stderr.strip()}")

    return output_path


def create_cell_backup(
    bootstrap_repo: Path,
    cell_id: str,
    passphrase: str,
    output_dir: Path,
    dt: datetime | None = None,
    extra_paths: list[tuple[str, Path]] | None = None,
) -> Path:
    """
    Create a complete encrypted backup archive for a cell.

    Collects all BACKUP_CONTENTS from the bootstrap repo, packages them
    into a tar.gz, encrypts with GPG, and writes to output_dir.

    Parameters
    ----------
    bootstrap_repo : Path
        Root of the proxmox-bootstrap/ directory.
    cell_id : str
        Cell identifier used in the filename.
    passphrase : str
        GPG encryption passphrase (caller retrieves from KeePass).
    output_dir : Path
        Directory where the final archive is written.
    dt : datetime, optional
        Timestamp to embed. Defaults to now (UTC).
    extra_paths : list of (archive_name, source_path), optional
        Additional paths to include (e.g. assessment history directory).

    Returns
    -------
    Path to the final encrypted archive.
    """
    if dt is None:
        dt = datetime.now(timezone.utc)

    filename = archive_filename(cell_id, dt, encrypted=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Collect source paths
    sources: list[tuple[str, Path]] = []
    for label, rel_path in BACKUP_CONTENTS.items():
        src = bootstrap_repo / rel_path
        if src.exists():
            sources.append((rel_path, src))

    if extra_paths:
        sources.extend(extra_paths)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_tar = Path(tmpdir) / "archive.tar.gz"
        create_tar_archive(sources, tmp_tar)
        final_path = output_dir / filename
        encrypt_archive(tmp_tar, final_path, passphrase)

    return final_path


# ---------------------------------------------------------------------------
# Archive transfer
# ---------------------------------------------------------------------------

def transfer_rclone(local_path: Path, remote_dest: str) -> bool:
    """
    Copy a local file to a rclone remote destination.

    Parameters
    ----------
    local_path : Path
        Local file to copy.
    remote_dest : str
        rclone destination, e.g. 'gdrive:/backups/cell-id'.

    Returns
    -------
    bool: True on success.
    """
    rclone = shutil.which("rclone")
    if not rclone:
        raise RuntimeError(
            "rclone not found. Install from https://rclone.org/install/"
        )
    result = subprocess.run(
        [rclone, "copy", str(local_path), remote_dest, "--progress"],
        capture_output=False,
        timeout=300,
    )
    return result.returncode == 0


def transfer_scp(local_path: Path, scp_dest: str) -> bool:
    """Copy a local file to an scp destination, e.g. user@host:/path/."""
    scp = shutil.which("scp")
    if not scp:
        raise RuntimeError("scp not found.")
    result = subprocess.run(
        [scp, str(local_path), scp_dest],
        capture_output=False,
        timeout=300,
    )
    return result.returncode == 0


def transfer_local(local_path: Path, dest_dir: str) -> bool:
    """Copy archive to a local or mounted path."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(local_path, dest / local_path.name)
    return True


# ---------------------------------------------------------------------------
# GitHub push
# ---------------------------------------------------------------------------

def git_push_to_remote(
    repo_path: Path,
    remote_url: str,
    deploy_key_path: Path | None = None,
    branch: str = "main",
) -> bool:
    """
    Push a local git repository to a remote URL using an SSH deploy key.

    Parameters
    ----------
    repo_path : Path
        Local git repository root.
    remote_url : str
        Remote URL, e.g. 'git@github.com:username/repo.git'
    deploy_key_path : Path, optional
        Path to the SSH private key file. If None, uses the default SSH agent.
    branch : str
        Branch to push. Defaults to 'main'.

    Returns
    -------
    bool: True on success.
    """
    env = dict(os.environ)
    if deploy_key_path and deploy_key_path.exists():
        env["GIT_SSH_COMMAND"] = (
            f"ssh -i {deploy_key_path} -o StrictHostKeyChecking=accept-new"
        )

    # Set remote if not already set
    remotes_result = subprocess.run(
        ["git", "remote"], capture_output=True, text=True, cwd=repo_path
    )
    if "external-backup" not in remotes_result.stdout:
        subprocess.run(
            ["git", "remote", "add", "external-backup", remote_url],
            cwd=repo_path, check=True,
        )
    else:
        subprocess.run(
            ["git", "remote", "set-url", "external-backup", remote_url],
            cwd=repo_path, check=True,
        )

    result = subprocess.run(
        ["git", "push", "external-backup", f"HEAD:{branch}", "--force"],
        cwd=repo_path, env=env, capture_output=True, text=True, timeout=120,
    )
    return result.returncode == 0


# ---------------------------------------------------------------------------
# Archive listing and retention
# ---------------------------------------------------------------------------

def list_archives(directory: Path, cell_id: str) -> list[dict]:
    """
    List all archives in a directory that belong to cell_id.

    Returns list of dicts with keys: filename, path, timestamp_str, short_hash.
    Sorted by timestamp, newest first.
    """
    archives = []
    for path in directory.glob(f"{cell_id}_*.tar.gz.gpg"):
        parsed = parse_archive_filename(path.name)
        if parsed and parsed["cell_id"] == cell_id:
            archives.append({
                "filename": path.name,
                "path": path,
                "timestamp_str": parsed["timestamp_str"],
                "short_hash": parsed["short_hash"],
            })
    archives.sort(key=lambda a: a["timestamp_str"], reverse=True)
    return archives


def prune_archives(directory: Path, cell_id: str, keep_count: int) -> list[Path]:
    """
    Remove old archives, keeping only the most recent keep_count.

    Returns list of deleted paths.
    """
    archives = list_archives(directory, cell_id)
    to_delete = archives[keep_count:]
    deleted = []
    for archive in to_delete:
        archive["path"].unlink()
        deleted.append(archive["path"])
    return deleted


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

def gpg_available() -> bool:
    return bool(shutil.which("gpg") or shutil.which("gpg2"))


def rclone_available() -> bool:
    return bool(shutil.which("rclone"))
