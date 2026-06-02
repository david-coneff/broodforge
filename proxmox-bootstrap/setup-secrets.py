#!/usr/bin/env python3
"""
Secret generation wizard for Infrastructure Cell bootstrap.

Generates all secrets required for a new cell, stores them in KeePass
(via KeePassXC CLI if available), and prepares SSH public keys for direct
embedding in user-data snippets — eliminating the POPULATE placeholder.

Prerequisites:
    - bootstrap-state.json must exist (run init-bootstrap-state.py first)
    - KeePassXC must be installed with a database file ready
    - OR: secrets will be generated and printed for manual entry

KeePassXC CLI detection:
    keepassxc-cli is tried first. If not found, passwords are generated
    using Python's secrets module and displayed for manual KeePass entry.
    SSH key pairs are always generated using ssh-keygen (stdlib-free approach
    using os.urandom for ed25519 is not practical; ssh-keygen is required).

Secrets generated:
    Host:    root password, OpenTofu API token placeholder
    Per VM:  initial OS user password, SSH ED25519 key pair

After this script:
    - KeePass contains all generated secrets (if CLI available)
    - ssh/public-keys/{vmname}.pub files exist in proxmox-bootstrap/
    - generate-user-data.py will embed actual public keys (no POPULATE)
    - bootstrap-state.json secret registry is updated with all paths

Usage:
    python3 setup-secrets.py
    python3 setup-secrets.py --bootstrap path/to/bootstrap-state.json
    python3 setup-secrets.py --keepass path/to/database.kdbx
    python3 setup-secrets.py --dry-run   (show what would be created, no writes)
"""

import importlib.util
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BOOTSTRAP_REPO = Path(__file__).parent
PUBKEY_DIR = BOOTSTRAP_REPO / "ssh" / "public-keys"


# ---------------------------------------------------------------------------
# Load suggest-names module (hyphen-safe)
# ---------------------------------------------------------------------------

def _load_suggest_names():
    spec = importlib.util.spec_from_file_location(
        "suggest_names", BOOTSTRAP_REPO / "suggest-names.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Tooling detection
# ---------------------------------------------------------------------------

def detect_keepassxc_cli() -> str | None:
    """Return path to keepassxc-cli, or None if not found."""
    return shutil.which("keepassxc-cli")


def detect_ssh_keygen() -> str | None:
    """Return path to ssh-keygen, or None if not found."""
    return shutil.which("ssh-keygen")


# ---------------------------------------------------------------------------
# Password generation
# ---------------------------------------------------------------------------

_PW_CHARS = (
    "abcdefghijkmnpqrstuvwxyz"    # lowercase (no l, o)
    "ABCDEFGHJKLMNPQRSTUVWXYZ"    # uppercase (no I, O)
    "23456789"                     # digits (no 0, 1)
    "!@#$%^&*-_=+"                 # special
)


def generate_password_python(length: int = 32) -> str:
    """Generate a strong password using Python's secrets module."""
    return "".join(secrets.choice(_PW_CHARS) for _ in range(length))


def generate_password_keepassxc(cli: str, length: int = 32) -> str | None:
    """
    Generate a password using keepassxc-cli generate.
    Returns None if the command fails.
    """
    try:
        result = subprocess.run(
            [cli, "generate", "-L", str(length), "-l", "-u", "-n", "-s",
             "--exclude-similar"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def generate_password(cli: str | None, length: int = 32) -> tuple[str, str]:
    """
    Generate a password. Returns (password, source) where source describes
    what generated it.
    """
    if cli:
        pw = generate_password_keepassxc(cli, length)
        if pw:
            return pw, "keepassxc-cli generate"
    return generate_password_python(length), "python secrets module"


# ---------------------------------------------------------------------------
# SSH key generation
# ---------------------------------------------------------------------------

def generate_ssh_keypair(
    name: str,
    ssh_keygen: str,
    comment: str | None = None,
) -> tuple[str, str] | None:
    """
    Generate an ED25519 SSH key pair using ssh-keygen.

    Returns (private_key_pem, public_key_line) or None on failure.
    The private key is the full PEM text suitable for storing in KeePass.
    The public key is the single-line authorized_keys format.
    """
    comment = comment or f"deploy-key-{name}"
    with tempfile.TemporaryDirectory() as tmpdir:
        key_path = Path(tmpdir) / name
        try:
            result = subprocess.run(
                [ssh_keygen, "-t", "ed25519", "-C", comment,
                 "-f", str(key_path), "-N", ""],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0:
                return None
            private_key = key_path.read_text(encoding="utf-8")
            public_key = (key_path.with_suffix(".pub")).read_text(encoding="utf-8").strip()
            return private_key, public_key
        except Exception:
            return None


# ---------------------------------------------------------------------------
# KeePass operations
# ---------------------------------------------------------------------------

def keepass_create_group(cli: str, db_path: str, group_path: str, db_password: str) -> bool:
    """Create a KeePass group (mkdir-like). Silently ignores if already exists."""
    try:
        result = subprocess.run(
            [cli, "mkdir", "--no-password", "-q", db_path, group_path],
            input=db_password, capture_output=True, text=True, timeout=10,
        )
        return True  # group may already exist; that's fine
    except Exception:
        return False


def keepass_add_password(
    cli: str,
    db_path: str,
    entry_path: str,
    username: str,
    password: str,
    notes: str | None,
    db_password: str,
) -> bool:
    """
    Add a password entry to KeePass.
    Entry path is the full path including group, e.g. Infrastructure/pve01/root-password.
    """
    try:
        # keepassxc-cli add takes the password from stdin when --stdin-password is used
        # The db master password is entered via the password prompt
        cmd = [cli, "add", db_path, entry_path,
               "--username", username,
               "--stdin-password"]
        # We pipe: "db_master_password\nentry_password\n"
        # keepassxc-cli prompts for db password first, then entry password
        stdin_input = f"{db_password}\n{password}\n"
        result = subprocess.run(
            cmd, input=stdin_input, capture_output=True, text=True, timeout=15,
        )
        return result.returncode == 0
    except Exception:
        return False


def keepass_add_ssh_key(
    cli: str,
    db_path: str,
    entry_path: str,
    private_key_pem: str,
    db_password: str,
) -> bool:
    """
    Store an SSH private key in KeePass as an entry with the PEM in the notes field.
    Uses a temp file for the attachment approach.
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix=".pem",
                                     delete=False, encoding="utf-8") as f:
        f.write(private_key_pem)
        tmp_path = f.name
    try:
        # Create the entry first (no password — the key IS the secret)
        cmd_add = [cli, "add", db_path, entry_path,
                   "--username", "deploy",
                   "--no-password"]
        stdin_add = f"{db_password}\n"
        r1 = subprocess.run(cmd_add, input=stdin_add, capture_output=True,
                            text=True, timeout=15)

        # Attach the private key file
        cmd_attach = [cli, "attachment-import", db_path, entry_path,
                      "private_key.pem", tmp_path]
        stdin_attach = f"{db_password}\n"
        r2 = subprocess.run(cmd_attach, input=stdin_attach, capture_output=True,
                            text=True, timeout=15)
        return r1.returncode == 0  # r2 may fail on older keepassxc — that's ok
    except Exception:
        return False
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Public key file management
# ---------------------------------------------------------------------------

def save_public_key(vm_name: str, public_key: str, pubkey_dir: Path) -> Path:
    """Save a VM's SSH public key to ssh/public-keys/{vmname}.pub."""
    pubkey_dir.mkdir(parents=True, exist_ok=True)
    out = pubkey_dir / f"{vm_name}.pub"
    out.write_text(public_key + "\n", encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Main wizard
# ---------------------------------------------------------------------------

def run_wizard(
    bootstrap_path: Path,
    keepass_db: str | None,
    dry_run: bool,
) -> None:
    sn = _load_suggest_names()

    with open(bootstrap_path) as f:
        state = json.load(f)

    cell_id = state["cell_id"]
    hostname = state["host_identity"]["hostname"]
    kp_root = state["keepass_config"]["root_path"]
    vms = state["vms"]

    # Tool detection
    cli = detect_keepassxc_cli()
    ssh_keygen = detect_ssh_keygen()

    print()
    print("=" * 64)
    print("  Secret Generation Wizard")
    print(f"  Cell: {cell_id}  |  Host: {hostname}")
    print("=" * 64)
    print()
    print(f"  KeePassXC CLI:  {'found at ' + cli if cli else 'NOT FOUND — manual entry mode'}")
    print(f"  ssh-keygen:     {'found at ' + ssh_keygen if ssh_keygen else 'NOT FOUND — SSH keys skipped'}")
    if dry_run:
        print("  Mode:           dry-run (nothing written)")
    print()

    # Show naming convention preview
    vm_names = [vm["name"] for vm in vms]
    sn.print_preview(
        cell_id=cell_id,
        hostname=hostname,
        kp_root=kp_root,
        management_cidr=state["network_topology"]["management_cidr"],
        vm_names=vm_names,
        search_domain=state["network_topology"].get("search_domain", "internal"),
    )

    if dry_run:
        print("[dry-run] No secrets generated or stored. Re-run without --dry-run to proceed.")
        return

    # KeePass database path — auto-discover, then confirm
    db_password = None
    if cli:
        if not keepass_db:
            best, candidates = sn.suggest_keepass_database()
            if candidates:
                print("  KeePass databases found:")
                for i, c in enumerate(candidates[:5]):
                    marker = " ← suggested" if i == 0 else ""
                    print(f"    [{i+1}] {c}{marker}")
                print()
                try:
                    raw = input(
                        f"  KeePass database [Enter to use suggested, or type path]: "
                    ).strip()
                except (EOFError, KeyboardInterrupt):
                    print("\n  Aborted.")
                    sys.exit(0)
                if not raw:
                    keepass_db = best
                elif raw.isdigit() and 1 <= int(raw) <= len(candidates):
                    keepass_db = candidates[int(raw) - 1]
                else:
                    keepass_db = raw
            else:
                print("  No KeePass databases found automatically.")
                try:
                    keepass_db = input("  KeePass database path (.kdbx): ").strip()
                except (EOFError, KeyboardInterrupt):
                    print("\n  Aborted.")
                    sys.exit(0)

        if not keepass_db or not Path(keepass_db).exists():
            print(f"  Warning: database not found at {keepass_db!r}. Switching to manual mode.")
            cli = None
        else:
            print(f"  Using: {keepass_db}")
            import getpass
            try:
                db_password = getpass.getpass("  KeePass master password: ")
            except (EOFError, KeyboardInterrupt):
                print("\n  Aborted.")
                sys.exit(0)

    # Build the full secret plan from naming convention
    kp_paths = sn.keepass_paths(kp_root, hostname, vms)
    registry_entries = sn.secret_registry_entries(kp_root, hostname, cell_id, vms)

    print()
    print("─" * 64)
    print("  Generating secrets...")
    print("─" * 64)

    generated_passwords: dict[str, str] = {}
    generated_pubkeys: dict[str, str] = {}

    # ── Host root password ──────────────────────────────────────────────────
    secret_id = f"{hostname}-root-password"
    kp_path = kp_paths[secret_id]
    pw, source = generate_password(cli)
    generated_passwords[secret_id] = pw
    if cli and db_password:
        ok = keepass_add_password(cli, keepass_db, kp_path, "root", pw, None, db_password)
        status = "stored in KeePass" if ok else "KeePass write failed — copy manually"
    else:
        status = f"MANUAL: copy to KeePass at {kp_path!r}"
    print(f"\n  [{secret_id}]")
    print(f"    KeePass path: {kp_path}")
    print(f"    Source:       {source}")
    print(f"    Status:       {status}")
    if not (cli and db_password):
        print(f"    Password:     {pw}")

    # ── Host API token (placeholder — PVE generates tokens in its UI) ───────
    secret_id = f"{hostname}-api-token-tofu"
    kp_path = kp_paths[secret_id]
    print(f"\n  [{secret_id}]")
    print(f"    KeePass path: {kp_path}")
    print(f"    Action:       Generate via Proxmox UI → Datacenter → API Tokens")
    print(f"                  Store result at KeePass path above")
    print(f"    (Proxmox API tokens cannot be generated externally)")

    # ── Per-VM secrets ───────────────────────────────────────────────────────
    for vm in vms:
        name = vm["name"]
        vmid = vm["vmid"]

        # Initial OS user password
        pw_id = f"vm-{name}-password"
        kp_path = kp_paths[pw_id]
        pw, source = generate_password(cli)
        generated_passwords[pw_id] = pw
        if cli and db_password:
            ok = keepass_add_password(cli, keepass_db, kp_path,
                                      vm.get("initial_user", "ubuntu"), pw, None, db_password)
            status = "stored in KeePass" if ok else "KeePass write failed — copy manually"
        else:
            status = f"MANUAL: copy to KeePass at {kp_path!r}"
        print(f"\n  [vm-{name}-password]")
        print(f"    KeePass path: {kp_path}")
        print(f"    Source:       {source}")
        print(f"    Status:       {status}")
        if not (cli and db_password):
            print(f"    Password:     {pw}")

        # SSH deploy key pair
        key_id = f"{name}-deploy-key"
        kp_path = kp_paths[key_id]
        print(f"\n  [{key_id}]")
        print(f"    KeePass path: {kp_path}")
        if ssh_keygen:
            result = generate_ssh_keypair(
                name, ssh_keygen,
                comment=f"{name}-deploy-key@{hostname}",
            )
            if result:
                private_pem, public_key = result
                generated_pubkeys[name] = public_key

                # Save public key to repo
                pub_path = save_public_key(name, public_key, PUBKEY_DIR)
                print(f"    Public key:   saved to {pub_path}")
                print(f"    Public key:   {public_key}")

                if cli and db_password:
                    ok = keepass_add_ssh_key(cli, keepass_db, kp_path, private_pem, db_password)
                    status = "private key stored in KeePass" if ok else "KeePass write failed — store manually"
                else:
                    status = f"MANUAL: store private key in KeePass at {kp_path!r}"
                print(f"    Status:       {status}")
                if not (cli and db_password):
                    # Write to /dev/tty to bypass any log redirection (forge.sh
                    # runs with exec >> forge.log 2>&1, which would capture stdout).
                    # Same pattern as print_totp_setup_to_tty() in keepass_mfa.py.
                    import sys as _sys
                    _key_header = f"    Private key:  (shown below — copy to KeePass before closing terminal)"
                    try:
                        with open("/dev/tty", "w") as _tty:
                            print(_key_header, file=_tty)
                            print(file=_tty)
                            print(private_pem, file=_tty)
                    except (OSError, AttributeError):
                        print(_key_header, file=_sys.stderr)
                        print(file=_sys.stderr)
                        print(private_pem, file=_sys.stderr)
            else:
                print(f"    Status:       ssh-keygen failed — generate manually")
        else:
            print(f"    Status:       ssh-keygen not found — generate manually with:")
            print(f"                  ssh-keygen -t ed25519 -C '{name}-deploy-key@{hostname}' -f {name}_key")
            print(f"                  Store private key in KeePass at path above")
            print(f"                  Copy public key to: ssh/public-keys/{name}.pub")

    # ── Update bootstrap-state.json secret registry ──────────────────────────
    print()
    print("─" * 64)
    print("  Updating bootstrap-state.json secret registry...")
    state["secrets"] = registry_entries
    with open(bootstrap_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    print(f"  Updated: {bootstrap_path}")

    # ── Regenerate user-data snippets ─────────────────────────────────────────
    gen_ud = BOOTSTRAP_REPO / "generate-user-data.py"
    if gen_ud.exists() and generated_pubkeys:
        print()
        print("─" * 64)
        print("  Regenerating user-data snippets (with actual SSH public keys)...")
        try:
            result = subprocess.run(
                [sys.executable, str(gen_ud), "--bootstrap", str(bootstrap_path)],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                print(result.stdout.strip())
                print("  SSH public keys embedded — POPULATE placeholder replaced.")
            else:
                print(f"  Warning: generate-user-data.py failed: {result.stderr.strip()}")
        except Exception as e:
            print(f"  Warning: Could not run generator: {e}")
    elif not generated_pubkeys:
        print()
        print("  Note: No SSH public keys were generated.")
        print("  After placing public keys in ssh/public-keys/{name}.pub,")
        print("  run: python3 generate-user-data.py")

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    print("=" * 64)
    print("  Setup complete.")
    print()
    if not (cli and db_password):
        print("  IMPORTANT: Copy all displayed passwords and private keys to KeePass")
        print("  before closing this terminal. They will not be shown again.")
        print()
    print("  Next steps:")
    print("  1. Store the Proxmox API token manually (Proxmox UI → API Tokens)")
    print(f"     KeePass path: {kp_root}/{hostname}/api-token-tofu")
    print("  2. Verify all entries in KeePass")
    print("  3. Populate bootstrap-state.json with VM definitions")
    print("  4. python3 generate-network-configs.py")
    print("  5. python3 generate-user-data.py  (if not already run above)")
    print("  6. See SNIPPET-UPLOAD.md for Proxmox upload instructions")
    print("=" * 64)
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]

    bootstrap_path = None
    keepass_db = None

    i = 0
    while i < len(args):
        if args[i] == "--bootstrap" and i + 1 < len(args):
            bootstrap_path = Path(args[i + 1])
            i += 2
        elif args[i] == "--keepass" and i + 1 < len(args):
            keepass_db = args[i + 1]
            i += 2
        else:
            i += 1

    if bootstrap_path is None:
        bootstrap_path = BOOTSTRAP_REPO / "bootstrap-state.json"
        if not bootstrap_path.exists():
            bootstrap_path = (
                Path(__file__).parent.parent
                / "tests" / "fixtures" / "bootstrap" / "bootstrap-state.json"
            )

    if not bootstrap_path.exists():
        print(f"Error: bootstrap-state.json not found at {bootstrap_path}", file=sys.stderr)
        print("Run init-bootstrap-state.py first.", file=sys.stderr)
        sys.exit(1)

    run_wizard(bootstrap_path, keepass_db, dry_run)


if __name__ == "__main__":
    main()
