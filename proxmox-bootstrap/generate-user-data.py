#!/usr/bin/env python3
"""
User-data snippet generator.

Reads bootstrap-state.json and generates a Cloud-Init user-data snippet
for each VM. All values that were previously hard-coded in snippets are
now derived from the single source of truth:

  bootstrap-state.json
    vm_defaults.timezone          -> timezone: field
    vm_defaults.initial_user      -> users[].name
    vm_defaults.workspace_base_path -> runcmd mkdir/chown
    network_topology.search_domain -> fqdn: field
    host_identity.hostname        -> cell context in comments
    keepass_config.root_path      -> SSH key placeholder comment
    vm.name                       -> hostname: field
    vm.initial_ip                 -> comment header
    vm.initial_user               -> overrides vm_defaults.initial_user
    vm.extra_packages             -> appended to base packages
    vm.workspace_path             -> overrides vm_defaults workspace path
    vm.ssh_key_reference          -> links to secret registry entry
    cell_id                       -> final_message

Base packages (applied to every VM):
  python3, python3-pip, qemu-guest-agent, openssh-server, git, curl

SSH public key is the only value that CANNOT be generated — it still requires
a POPULATE placeholder. Retrieve the public key from the corresponding
SSH private key in KeePass before uploading snippets to Proxmox.

Usage (from proxmox-bootstrap/ directory):
    python3 generate-user-data.py
    python3 generate-user-data.py --bootstrap path/to/bootstrap-state.json
    python3 generate-user-data.py --dry-run

Re-run whenever any of the following change:
    - vm_defaults (timezone, initial_user, workspace_base_path)
    - network_topology.search_domain
    - keepass_config.root_path
    - vm.name, vm.initial_ip, vm.extra_packages, vm.workspace_path
    - vm.ssh_key_reference (changes the placeholder comment)
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Packages installed on every VM regardless of role
BASE_PACKAGES = [
    "python3",
    "python3-pip",
    "qemu-guest-agent",
    "openssh-server",
    "git",
    "curl",
]


_PUBKEY_DIR = Path(__file__).parent / "ssh" / "public-keys"


def _resolve_ssh_public_key(vm: dict, secrets: list, keepass_root: str) -> str:
    """
    Resolve the SSH authorized_keys line for a VM.

    Resolution order:
      1. ssh/public-keys/{vmname}.pub — actual key file (populated by setup-secrets.py)
      2. POPULATE placeholder with KeePass reference (for manual setup)
    """
    pub_key_file = _PUBKEY_DIR / f"{vm['name']}.pub"
    if pub_key_file.exists():
        content = pub_key_file.read_text(encoding="utf-8").strip()
        if content:
            return content  # actual ed25519 public key

    # Fall back to placeholder
    ref_id = vm.get("ssh_key_reference")
    if not ref_id:
        return "POPULATE: SSH public key for this VM"
    secret = next((s for s in secrets if s["id"] == ref_id), None)
    if secret:
        return f"POPULATE: SSH public key — KeePass: {secret['keepass_path']}"
    return f"POPULATE: SSH public key — KeePass: {keepass_root}/ssh/deploy-keys/{vm['name']}"


def _workspace_runcmd(vm: dict, vm_defaults: dict) -> list[str]:
    """Return runcmd lines for workspace directory creation, or empty list."""
    workspace = vm.get("workspace_path")
    if workspace is None:
        base = vm_defaults.get("workspace_base_path")
        if not base:
            return []
        workspace = f"{base}/{vm['name']}"

    user = vm.get("initial_user") or vm_defaults.get("initial_user", "ubuntu")
    return [
        f"- mkdir -p {workspace}",
        f"- chown {user}:{user} {workspace}",
    ]


def generate_user_data(
    vm: dict,
    vm_defaults: dict,
    network_topology: dict,
    host_identity: dict,
    keepass_config: dict,
    secrets: list,
    cell_id: str,
    generated_at: str,
) -> str:
    name = vm["name"]
    vmid = vm["vmid"]
    ip = vm["initial_ip"]
    role = vm.get("role", name)
    user = vm.get("initial_user") or vm_defaults.get("initial_user", "ubuntu")
    timezone = vm_defaults.get("timezone", "UTC")
    search_domain = network_topology.get("search_domain") or "local"
    keepass_root = keepass_config.get("root_path", "Infrastructure")
    fqdn = f"{name}.{search_domain}"

    # Find the password KeePass path for the comment header
    pw_ref = vm.get("password_reference")
    pw_secret = next((s for s in secrets if s["id"] == pw_ref), None) if pw_ref else None
    pw_keepass = pw_secret["keepass_path"] if pw_secret else f"{keepass_root}/vms/{name}-password"

    ssh_placeholder = _resolve_ssh_public_key(vm, secrets, keepass_root)

    # Packages: base + role-specific extras
    packages = list(BASE_PACKAGES)
    for pkg in vm.get("extra_packages", []):
        if pkg not in packages:
            packages.append(pkg)
    pkg_lines = "\n".join(f"  - {p}" for p in packages)

    # runcmd: always enable guest-agent and disable password auth
    runcmd_lines = [
        "  - systemctl enable qemu-guest-agent",
        "  - systemctl start qemu-guest-agent",
        "  - sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config",
        "  - systemctl restart sshd",
    ]
    for line in _workspace_runcmd(vm, vm_defaults):
        runcmd_lines.append(f"  {line}")

    runcmd_block = "\n".join(runcmd_lines)

    using_placeholder = ssh_placeholder.startswith("POPULATE:")
    populate_note = (
        "#\n"
        "# BEFORE UPLOADING: replace the POPULATE placeholder in ssh_authorized_keys\n"
        "# with the actual SSH public key for this VM."
        if using_placeholder else
        "# SSH public key embedded from ssh/public-keys/{}.pub".format(name)
    )

    return f"""\
#cloud-config
# user-data - {name}
# GENERATED by generate-user-data.py - DO NOT EDIT MANUALLY
# Re-run the generator if vm_defaults, network_topology, or VM config changes.
#
# Source: bootstrap-state.json -> vm_defaults + vm[{vmid}]
# Cell:   {cell_id}
# VM ID:  {vmid}
# Role:   {role}
# IP:     {ip}
# Host:   {host_identity.get('hostname', 'unknown')}
# KeePass (initial password): {pw_keepass}
# Generated: {generated_at}
{populate_note}

hostname: {name}
fqdn: {fqdn}

users:
  - name: {user}
    gecos: Ubuntu
    groups: [sudo, adm]
    shell: /bin/bash
    sudo: ALL=(ALL) NOPASSWD:ALL
    lock_passwd: true
    ssh_authorized_keys:
      - "{ssh_placeholder}"

timezone: {timezone}

package_update: true
package_upgrade: false

packages:
{pkg_lines}

runcmd:
{runcmd_block}

final_message: |
  Cloud-Init first-boot complete on {name} ({ip}).
  Connect via SSH as {user}@{ip} using the deploy key.
  Cell: {cell_id}
"""


def run(bootstrap_path: Path, output_dir: Path, dry_run: bool = False) -> list[str]:
    with open(bootstrap_path) as f:
        state = json.load(f)

    cell_id = state["cell_id"]
    vm_defaults = state["vm_defaults"]
    network_topology = state["network_topology"]
    host_identity = state["host_identity"]
    keepass_config = state["keepass_config"]
    secrets = state.get("secrets", [])
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    written = []
    for vm in state["vms"]:
        content = generate_user_data(
            vm=vm,
            vm_defaults=vm_defaults,
            network_topology=network_topology,
            host_identity=host_identity,
            keepass_config=keepass_config,
            secrets=secrets,
            cell_id=cell_id,
            generated_at=generated_at,
        )

        out_path = output_dir / f"{vm['name']}.yaml"
        if dry_run:
            print(f"[dry-run] Would write {out_path}")
            sys.stdout.buffer.write(content.encode("utf-8"))
            print("\n---")
        else:
            out_path.write_text(content, encoding="utf-8")
            print(f"  wrote  {out_path}")

        written.append(str(out_path))

    return written


def main() -> None:
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]

    if "--bootstrap" in args:
        idx = args.index("--bootstrap")
        bootstrap_path = Path(args[idx + 1]).resolve()
    else:
        bootstrap_path = Path(__file__).parent / "bootstrap-state.json"
        if not bootstrap_path.exists():
            bootstrap_path = (
                Path(__file__).parent.parent
                / "tests" / "fixtures" / "bootstrap" / "bootstrap-state.json"
            )

    if not bootstrap_path.exists():
        print(f"Error: bootstrap-state.json not found at {bootstrap_path}", file=sys.stderr)
        print("Use --bootstrap <path> to specify the manifest location.", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(__file__).parent / "snippets" / "user-data"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Bootstrap state: {bootstrap_path}")
    print(f"Output dir:      {output_dir}")
    if dry_run:
        print("Mode:            dry-run (no files written)")
    print()

    written = run(bootstrap_path, output_dir, dry_run=dry_run)

    if not dry_run:
        print(f"\nGenerated {len(written)} user-data snippet(s).")
        print("After generation, populate SSH public keys before uploading.")
        print("See SNIPPET-UPLOAD.md for instructions.")


if __name__ == "__main__":
    main()
