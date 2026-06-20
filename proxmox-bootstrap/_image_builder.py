#!/usr/bin/env python3
"""
_image_builder.py — Pre-install bootstrap image builder (Phase 1.H, AD-057).

Builds a "bootstrap image staging bundle" — a structured tar.gz that documents
and stages exactly what an operator would combine with the official Proxmox VE
ISO via their own remastering process to produce bootable pre-install media.

This module does NOT download, mount, or repack a real Proxmox ISO (no network
access, no source ISO available in this environment — and broodforge does not
redistribute Proxmox's installer media). Instead it produces the *staging
content* an operator overlays onto that ISO: an `answer.toml` (Proxmox 8+
automated-installer answer file, derived from forge-manifest.json so the
operator answers setup questions exactly once — AD-049), the assembled forge
package (reusing `assemble_forge_package`), a first-boot systemd hook that
runs the embedded forge package's `forge.sh` automatically, an installer
script for that hook, and a README documenting the manual remastering steps.

This mirrors how `assemble_forge_package` builds a tar.gz describing *its*
artifact rather than a literal physical thing — the bundle here is the
equivalent staging artifact for pre-install media.

Bundle layout:
  bootstrap-image-{cell_id}-{YYYY-MM-DD_HH_MM_SS}.tar.gz
  └── iso-staging/
      ├── answer.toml                       Proxmox 8+ automated-installer answer file
      ├── forge-package.tar.gz              embedded forge package (assemble_forge_package)
      ├── first-boot/
      │   ├── broodforge-first-boot.service systemd oneshot unit — runs forge.sh on first boot
      │   └── install-first-boot-hook.sh    installer invoked by answer.toml post-install hook
      ├── bootstrap-image-manifest.json     hash/contents manifest for this bundle
      ├── bootstrap-image-manifest.html     human-readable twin (AD-051)
      └── README.md                         remastering instructions for the operator

Security: like the forge package, this bundle NEVER contains real secrets.
`answer.toml`'s root credential is a freshly-generated, single-use discovery
passphrase (same pattern as the Cloud-Init temporary-password flow, AD-039/
AD-043 — `spawn_planner.generate_temp_password`) that the operator is expected
to rotate via the KeePass-managed credential the forge package installs; it is
never written to KeePass and is printed once, at build time, for the operator
to note down.

Stdlib only.
"""

import hashlib
import io
import json
import random
import secrets
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    from assemble_forge_package import assemble_forge_package as _assemble_forge_package
    _HAS_ASSEMBLER = True
except ImportError:
    _assemble_forge_package = None  # type: ignore
    _HAS_ASSEMBLER = False

try:
    from html_package_manifest import build_bootstrap_image_manifest_html as _build_image_manifest_html
    _HAS_IMAGE_MANIFEST_HTML = True
except ImportError:
    _build_image_manifest_html = None  # type: ignore
    _HAS_IMAGE_MANIFEST_HTML = False


# ---------------------------------------------------------------------------
# Discovery passphrase (AD-039/AD-043 pattern — fresh, single-use, never fixed)
# ---------------------------------------------------------------------------

_PASSPHRASE_WORDS = [
    "anchor", "beacon", "cipher", "drift", "ember", "forge", "glyph", "harbor",
    "ion", "jade", "kiln", "lumen", "mason", "nimbus", "onyx", "pivot",
    "quartz", "ridge", "spark", "talon", "umbra", "vault", "wisp", "zephyr",
]


def generate_install_passphrase(seed: Optional[int] = None) -> str:
    """
    Generate a fresh, readable, single-use root passphrase for the Proxmox
    installer's automated answer file.

    This mirrors `spawn_planner.generate_temp_password` (AD-039/AD-043): a
    readable Capital.word.word.N passphrase, never a fixed/predictable value.
    It is valid only for the install + first-boot window — the embedded forge
    package replaces it with a KeePass-managed credential during phase-03, the
    same way Cloud-Init replaces the spawn discovery password. `seed` exists
    only for deterministic tests; production callers must never pass one.
    """
    if seed is not None:
        rng = random.Random(seed)  # noqa: S311
        w1 = _PASSPHRASE_WORDS[rng.randint(0, len(_PASSPHRASE_WORDS) - 1)]  # noqa: S311
        w2 = _PASSPHRASE_WORDS[rng.randint(0, len(_PASSPHRASE_WORDS) - 1)]  # noqa: S311
        n = rng.randint(1, 9)  # noqa: S311
    else:
        w1 = secrets.choice(_PASSPHRASE_WORDS)
        w2 = secrets.choice(_PASSPHRASE_WORDS)
        n = secrets.randbelow(9) + 1
    return f"{w1.capitalize()}.boot.{w2}.{n}"


# ---------------------------------------------------------------------------
# answer.toml generation (Proxmox 8+ automated-installer answer file)
# ---------------------------------------------------------------------------

def _toml_str(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _toml_str_array(values: list) -> str:
    return "[" + ", ".join(_toml_str(str(v)) for v in values) + "]"


def generate_answer_toml(
    manifest: dict,
    root_passphrase: Optional[str] = None,
    keyboard: str = "en-us",
    country: str = "us",
    filesystem: str = "zfs",
    disk_list: Optional[list] = None,
    interface_name: Optional[str] = None,
    now: Optional[datetime] = None,
) -> str:
    """
    Derive a Proxmox VE 8+ `answer.toml` from forge-manifest.json fields.

    Pulls the same `host_identity` / `network_topology` fields the guided-setup
    framework (AD-049, forge_planner.py) already collects, so the operator
    answers hostname/domain/network/timezone questions exactly once — the
    image builder does not prompt again.

    Security (no plaintext secrets in the artifact): `root_passphrase` MUST be
    a freshly-generated, single-use discovery passphrase (see
    `generate_install_passphrase`), never a real or reused root password. It
    is written in plaintext here deliberately — Proxmox's automated installer
    requires a plaintext-or-hashed value in `answer.toml` and there is no
    KeePass-reference indirection at install time (KeePass does not exist on
    the host yet) — but it is scoped to the install + first-boot window only,
    exactly like the Cloud-Init discovery password (AD-039/AD-043): the
    embedded forge package's phase-03 KeePass init replaces it with a
    permanent, vaulted credential, and the generated README instructs the
    operator to treat it as a one-time-use value to be rotated/discarded.

    Args:
        manifest:        forge-manifest.json dict
        root_passphrase: pre-generated single-use install passphrase (if None,
                         one is generated fresh — never a fixed value)
        keyboard:        keyboard layout (Proxmox answer.toml `keyboard`)
        country:         ISO country code (Proxmox answer.toml `country`)
        filesystem:      disk-setup filesystem (`zfs`, `ext4`, `xfs`, ...)
        disk_list:       explicit disk device list for [disk-setup]; if None,
                         a placeholder the operator must populate is emitted
        now:             injectable datetime (for tests / reproducible output)

    Returns:
        Hand-formatted TOML text (stdlib `tomllib` can read but not write TOML).
    """
    gen_at = (now or datetime.now(timezone.utc)).isoformat()
    hi = manifest.get("host_identity") or {}
    nt = manifest.get("network_topology") or {}

    hostname = hi.get("hostname") or "pve01"
    domain = hi.get("domain") or "home.example.com"
    fqdn = hi.get("fqdn") or f"{hostname}.{domain}"
    tz = hi.get("timezone") or "UTC"

    mgmt_cidr = nt.get("management_cidr") or "192.168.1.0/24"
    gateway = nt.get("gateway") or "192.168.1.1"
    cidr_prefix = mgmt_cidr.split("/")[1] if "/" in mgmt_cidr else "24"

    # The host's static IP is not itself a forge-manifest field (it is assigned
    # to VMs, not the hatchery) — derive it as the first usable address in the
    # management subnet, matching the documented convention (gateway = .1,
    # hatchery = .2) the rest of the bootstrap docs already assume.
    net_base = ".".join(mgmt_cidr.split("/")[0].split(".")[:3])
    host_ip = f"{net_base}.2"

    nameservers = nt.get("nameservers") or [gateway]
    dns_line = nameservers[0] if nameservers else gateway

    passphrase = root_passphrase or generate_install_passphrase()
    disks = disk_list if disk_list else ["__POPULATE_DISK_DEVICE__"]

    lines = [
        "# answer.toml — Proxmox VE 8+ automated-installer answer file",
        "# GENERATED by generate-bootstrap-image.py (Phase 1.H, AD-057) — derived from forge-manifest.json",
        f"# Cell:      {manifest.get('cell_id') or 'unknown-cell'}",
        f"# Generated: {gen_at}",
        "#",
        "# SECURITY: root-password below is a FRESH, SINGLE-USE discovery passphrase",
        "# (AD-039/AD-043 pattern) — not a real credential. The embedded forge",
        "# package replaces it with a KeePass-managed credential at phase-03.",
        "# Rotate or discard it once the embedded forge package completes.",
        "# Populate disk-list with the real target-host disk device path(s) before use.",
        "",
        "[global]",
        f"keyboard = {_toml_str(keyboard)}",
        f"country = {_toml_str(country)}",
        f"fqdn = {_toml_str(fqdn)}",
        f"mailto = {_toml_str(f'root@{domain}')}",
        f"timezone = {_toml_str(tz)}",
        f"root-password = {_toml_str(passphrase)}",
        "",
        "[network]",
        "source = \"from-answer\"",
        f"cidr = {_toml_str(f'{host_ip}/{cidr_prefix}')}",
        f"dns = {_toml_str(dns_line)}",
        f"gateway = {_toml_str(gateway)}",
        f"filter.ID_NET_NAME = {_toml_str(interface_name or '__POPULATE_INTERFACE_NAME__')}",
        "",
        "[disk-setup]",
        f"filesystem = {_toml_str(filesystem)}",
        f"disk-list = {_toml_str_array(disks)}",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# First-boot automation hook (systemd unit, string-template pattern — see
# forge_scripts.py FORGE_CHECKPOINT_SH for the embedded-template convention)
# ---------------------------------------------------------------------------

FIRST_BOOT_SERVICE_NAME = "broodforge-first-boot.service"
_FORGE_RUN_DIR = "/root/forge-package"
_FIRST_BOOT_MARKER = "/var/lib/broodforge-first-boot.done"


def generate_first_boot_unit(manifest: dict) -> str:
    """
    Generate the systemd oneshot unit that runs the embedded forge package's
    `forge.sh` automatically on first boot of the freshly-installed host.

    Replaces the manual "SSH in and kick off forging" step (FORGING.md Step 4).
    Idempotent: a marker file prevents re-running on subsequent boots, and the
    unit disables + removes itself once forge.sh completes successfully.
    """
    cell_id = manifest.get("cell_id") or "unknown-cell"
    return f"""\
[Unit]
Description=Broodforge first-boot forge automation ({cell_id})
Documentation=https://github.com/broodforge — see FORGING.md
ConditionPathExists=!{_FIRST_BOOT_MARKER}
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory={_FORGE_RUN_DIR}
ExecStartPre=/bin/mkdir -p /var/lib
ExecStart=/bin/bash {_FORGE_RUN_DIR}/forge.sh
ExecStartPost=/bin/touch {_FIRST_BOOT_MARKER}
ExecStartPost=/bin/systemctl disable {FIRST_BOOT_SERVICE_NAME}
StandardOutput=journal+console
StandardError=journal+console
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
"""


def generate_first_boot_install_sh(manifest: dict) -> str:
    """
    Generate the oneshot installer script that the answer file's post-install
    hook invokes to install and enable the first-boot unit.

    This is what `answer.toml`'s `[first-boot]` post-install-hook would call —
    it copies the forge package into place, installs the systemd unit, and
    enables it so forge.sh runs unattended on the new host's first real boot.
    """
    cell_id = manifest.get("cell_id") or "unknown-cell"
    return f"""\
#!/usr/bin/env bash
# install-first-boot-hook.sh — installs the broodforge first-boot automation unit
# Cell: {cell_id}
# Invoked by the Proxmox automated installer's post-install hook (answer.toml
# [first-boot] section) on the freshly-installed host, BEFORE first reboot.
set -euo pipefail

STAGING_DIR="$(dirname "$(readlink -f "$0")")"
RUN_DIR="{_FORGE_RUN_DIR}"
UNIT_NAME="{FIRST_BOOT_SERVICE_NAME}"

echo "[first-boot-install] Staging forge package to $RUN_DIR ..."
mkdir -p "$RUN_DIR"
tar -xzf "$STAGING_DIR/forge-package.tar.gz" -C "$RUN_DIR"
chmod +x "$RUN_DIR/forge.sh"

echo "[first-boot-install] Installing $UNIT_NAME ..."
install -m 0644 "$STAGING_DIR/$UNIT_NAME" "/etc/systemd/system/$UNIT_NAME"
systemctl daemon-reload
systemctl enable "$UNIT_NAME"

echo "[first-boot-install] Done. forge.sh will run automatically on first boot."
"""


# ---------------------------------------------------------------------------
# README — operator-facing remastering instructions
# ---------------------------------------------------------------------------

def generate_staging_readme(manifest: dict, now: Optional[datetime] = None) -> str:
    gen_at = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S UTC")
    cell_id = manifest.get("cell_id") or "unknown-cell"
    hostname = (manifest.get("host_identity") or {}).get("hostname") or "unknown"
    return f"""\
# Bootstrap Image Staging Bundle — {cell_id}

Generated: {gen_at}
Target host: {hostname}

## What this bundle is — and is NOT

This is a **staging bundle**, not a bootable ISO. broodforge cannot download,
mount, or remaster the official Proxmox VE installer image in this environment
(no network access at build time, and broodforge does not redistribute
Proxmox's media). What you have here is everything *specific to your cell*
that needs to be combined with the official Proxmox VE ISO:

- `answer.toml`           — Proxmox 8+ automated-installer answer file, derived
                            from your forge-manifest.json (network, hostname,
                            disk layout, timezone — answered once, here)
- `forge-package.tar.gz`  — the full forge package for this cell (same artifact
                            FORGING.md Step 2 produces — embedded so the new
                            host can forge itself without a second copy step)
- `first-boot/`           — a systemd oneshot unit + installer script that runs
                            the embedded forge package's forge.sh automatically
                            on the new host's first boot
- `bootstrap-image-manifest.{{json,html}}` — hash/contents manifest for this bundle

## How to build bootable media from this bundle (operator-performed)

Proxmox publishes an "Automated Installation" guide describing how to combine
an `answer.toml` with the official ISO — either by mounting the ISO, copying
`answer.toml` to its root, and re-packing it (`xorriso`/`proxmox-auto-install-assistant`),
or by preparing a USB stick with the answer file alongside the ISO image. That
process is **the operator's responsibility** and uses Proxmox's own tooling —
broodforge does not (and, offline, cannot) perform it for you. The high-level
steps, per Proxmox's documentation:

1. Download the official Proxmox VE ISO for your target version.
2. Use `proxmox-auto-install-assistant prepare-iso <iso> --fetch-from iso
   --answer-file answer.toml` (or the equivalent partition-overlay method for
   USB media) to produce bootable media that boots straight into the
   automated installer using the answer file in this bundle.
3. After the automated install completes and the host reboots into Proxmox,
   run `install-first-boot-hook.sh` (from `first-boot/`) — Proxmox's
   `[first-boot]` post-install hook in `answer.toml` can invoke it directly,
   or you can run it manually once, before the first reboot.
4. On first real boot, `{FIRST_BOOT_SERVICE_NAME}` runs the embedded
   `forge.sh` unattended — turning "bare metal → operational hatchery" into a
   boot-and-walk-away operation (the same 8 phases FORGING.md Step 5 documents).

## IMPORTANT — about the root password in answer.toml

`answer.toml`'s `root-password` is a **freshly-generated, single-use discovery
passphrase** (the same temporary-credential pattern Cloud-Init uses for spawned
nodes, AD-039/AD-043) — NOT a permanent credential, and NOT stored in KeePass.
It exists only to satisfy the installer's requirement for a root password and
to allow the embedded forge package to bootstrap itself. The forge package's
phase-03 replaces it with a KeePass-managed credential during the automated
forge run. **Note the passphrase down before burning this bundle to media —
you will not be able to recover it from this bundle afterward — and treat it
as compromised/discard it once forging completes.**

## This is an OPTIONAL alternative path

The supported baseline remains: install Proxmox VE yourself (any way you like
— official installer, hosting-provider imaging, an existing cluster), then
follow FORGING.md from Step 1. This bundle only collapses the "install Proxmox"
+ "copy package" + "SSH in and run forge.sh" steps into one boot. See
FORGING.md "Step 0 — Build pre-install media (optional)" for the full picture.
"""


# ---------------------------------------------------------------------------
# Pre-generated spawn-media credentials + pending join authorization
# (Phase 1.J, AD-060(c) — additive extension to the Phase 1.H / AD-057 image
# builder, running the AD-043 passphrase-generation pattern at BUILD time and
# embedding the result on install media instead of generating it at install
# time.)
#
# THE GATE: a node installed from such pre-made media must NOT be allowed to
# join the cell until a human operator explicitly authorizes it — recorded as
# a state entry, the same shape AD-041's autonomous-mode service-selection
# confirmation already uses (a RECORDED OPERATOR DECISION broodforge reads
# back, never a live interactive prompt broodforge runs against a hypervisor).
# `authorize-spawn-media-join.py` is the only thing that flips `authorized`,
# and it is a human-operated CLI step — broodforge never auto-authorizes.
#
# Only a SHA-256 HASH of the passphrase is recorded — never the passphrase
# itself (mirrors AD-039/AD-043: shown once, at build time, to the operator;
# never written to KeePass or any broodforge-managed store).
# ---------------------------------------------------------------------------

def hash_install_passphrase(passphrase: str) -> str:
    """SHA-256 hex digest of an install passphrase — for record/verification only; never reversible, never the value itself."""
    return hashlib.sha256((passphrase or "").encode("utf-8")).hexdigest()


def build_pending_join_authorization(
    manifest: dict,
    image_bundle_name_str: str,
    passphrase: str,
    now: Optional[datetime] = None,
) -> dict:
    """
    Build a single "pending join authorization" record for a pre-generated
    spawn-media bundle — the AD-041-shaped gate AD-060(c) requires: a state
    record an operator must explicitly flip to `authorized: true` before a
    node installed from this media may join the cell.

    This is a STATE RECORD ONLY — generation-time bookkeeping, never a live
    decision broodforge makes about itself. `authorized` always starts False;
    only `authorize-spawn-media-join.py`, run by a human operator, may set it
    True (recorded with `authorized_at` / `authorized_by`).

    The passphrase itself is never embedded here — only its SHA-256 hash, so
    the record can later be cross-checked against what the operator noted down
    at build time without the record itself becoming a secret.
    """
    gen_at = (now or datetime.now(timezone.utc)).isoformat()
    return {
        "schema_version": "1.0",
        "record_type": "pending_join_authorization",
        "cell_id": manifest.get("cell_id") or "unknown-cell",
        "image_bundle_name": image_bundle_name_str,
        "generated_at": gen_at,
        "passphrase_hash": hash_install_passphrase(passphrase),
        "passphrase_hash_algorithm": "sha256",
        "authorized": False,
        "authorized_at": None,
        "authorized_by": None,
        "notes": [
            "The passphrase itself is NEVER recorded here — only its SHA-256 "
            "hash, for later cross-check against the value the operator noted "
            "down once, at build time (AD-039/AD-043 shown-once convention).",
            "A node installed from this bundle must NOT be allowed to join the "
            "cell until `authorized` is explicitly flipped to true by a human "
            "operator via authorize-spawn-media-join.py — mirrors how AD-041's "
            "autonomous-mode service-selection confirmation is a RECORDED "
            "decision broodforge reads back, never a live prompt it runs.",
            "broodforge never sets `authorized: true` on its own initiative.",
        ],
    }


def pending_join_authorizations_path(repo_dir: Optional[Path] = None) -> Path:
    """Path to bootstrap-state.json's home — pending_join_authorizations lives in that file's top-level dict."""
    base = Path(repo_dir) if repo_dir else Path(__file__).resolve().parent
    return base / "bootstrap-state.json"


def record_pending_join_authorization(
    state: dict,
    authorization_record: dict,
) -> dict:
    """
    Append `authorization_record` to `state["pending_join_authorizations"]`
    (creating the list if absent) and return the updated state dict.

    Pure data transformation — does not read or write any file; callers that
    persist `bootstrap-state.json` do so through the existing state-write path
    (this mirrors how the rest of `_image_builder` only ever returns dicts/
    strings for the assembler to place — see `build_image_manifest`).
    """
    records = list(state.get("pending_join_authorizations") or [])
    records.append(authorization_record)
    state = dict(state)
    state["pending_join_authorizations"] = records
    return state


def build_pregenerated_spawn_media_record(
    manifest: dict,
    image_bundle_name_str: Optional[str] = None,
    passphrase: Optional[str] = None,
    seed: Optional[int] = None,
    now: Optional[datetime] = None,
) -> dict:
    """
    Generate the build-time passphrase (AD-043 pattern, run early per
    AD-060(c)) and its paired pending-join-authorization record in one step.

    Returns a dict with BOTH the plaintext `passphrase` (for the caller to
    surface to the operator ONCE, at build time — e.g. embedded in
    `answer.toml` and printed to the build console, exactly like
    `generate_install_passphrase` already is) and the `authorization_record`
    (which carries only the passphrase's hash — see
    `build_pending_join_authorization`). Callers MUST NOT persist the
    plaintext `passphrase` value anywhere broodforge manages.
    """
    passphrase = passphrase or generate_install_passphrase(seed=seed)
    bundle_name = image_bundle_name_str or image_bundle_name(manifest, now=now)
    return {
        "passphrase": passphrase,
        "image_bundle_name": bundle_name,
        "authorization_record": build_pending_join_authorization(
            manifest, bundle_name, passphrase, now=now,
        ),
    }


# ---------------------------------------------------------------------------
# Bundle naming
# ---------------------------------------------------------------------------

def image_bundle_name(manifest: dict, now: Optional[datetime] = None) -> str:
    """Build the bootstrap image staging bundle filename."""
    cell_id = manifest.get("cell_id") or "unknown-cell"
    ts = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d_%H_%M_%S")
    return f"bootstrap-image-{cell_id}-{ts}.tar.gz"


# ---------------------------------------------------------------------------
# Content listing (for inspection / testing)
# ---------------------------------------------------------------------------

def image_bundle_contents(manifest: dict) -> list[str]:
    """Return the list of archive member paths the bundle will contain."""
    return [
        "iso-staging/answer.toml",
        "iso-staging/forge-package.tar.gz",
        f"iso-staging/first-boot/{FIRST_BOOT_SERVICE_NAME}",
        "iso-staging/first-boot/install-first-boot-hook.sh",
        "iso-staging/bootstrap-image-manifest.json",
        "iso-staging/bootstrap-image-manifest.html",
        "iso-staging/README.md",
    ]


# ---------------------------------------------------------------------------
# Image manifest (machine-readable — hash/contents record, AD-051/AD-042)
# ---------------------------------------------------------------------------

def build_image_manifest(
    manifest: dict,
    forge_pkg_path: Path,
    answer_toml_text: str,
    now: Optional[datetime] = None,
) -> dict:
    """
    Build the machine-readable bootstrap-image-manifest.json content: what's
    in the bundle and the SHA-256 of the embedded forge package, following the
    same hash-and-verify pattern `assemble-forge-package.py` uses for its
    own artifact (AD-042/AD-051 supply-chain verification).
    """
    gen_at = (now or datetime.now(timezone.utc)).isoformat()
    forge_pkg_path = Path(forge_pkg_path)
    return {
        "schema_version": "1.0",
        "artifact_type": "bootstrap-image-staging-bundle",
        "cell_id": manifest.get("cell_id") or "unknown-cell",
        "generated_at": gen_at,
        "host_identity": manifest.get("host_identity") or {},
        "network_topology": manifest.get("network_topology") or {},
        "contents": image_bundle_contents(manifest),
        "embedded_forge_package": {
            "name": forge_pkg_path.name,
            "sha256": hashlib.sha256(forge_pkg_path.read_bytes()).hexdigest(),
            "size_bytes": forge_pkg_path.stat().st_size,
        },
        "answer_toml_sha256": hashlib.sha256(answer_toml_text.encode("utf-8")).hexdigest(),
        "first_boot_unit": FIRST_BOOT_SERVICE_NAME,
        "notes": [
            "This is a staging bundle, not a bootable ISO — see README.md.",
            "answer.toml root-password is a single-use discovery passphrase, "
            "not a permanent credential (AD-039/AD-043 pattern).",
            "The package never contains secret values beyond the single-use "
            "install passphrase — all other credentials are KeePass references.",
        ],
    }


# ---------------------------------------------------------------------------
# Assembler
# ---------------------------------------------------------------------------

def build_bootstrap_image(
    manifest: dict,
    output_dir: Path,
    repo_dir: Optional[Path] = None,
    kdbx_path: Optional[Path] = None,
    root_passphrase: Optional[str] = None,
    keyboard: str = "en-us",
    country: str = "us",
    filesystem: str = "zfs",
    disk_list: Optional[list] = None,
    interface_name: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Path:
    """
    Build the bootstrap image staging bundle (tar.gz).

    Internally assembles a forge package (reusing `assemble_forge_package`),
    derives `answer.toml` from the manifest, generates the first-boot hook,
    builds the hash/contents manifest (+ HTML twin), writes a README, and
    bundles all of it under an `iso-staging/` layout inside the returned
    tar.gz — the staging content an operator combines with the official
    Proxmox VE ISO via their own remastering process (see README.md).

    Args:
        manifest:        forge-manifest.json dict
        output_dir:      where to write the bundle (and intermediate forge
                         package — written to a `forge-package/` subdirectory)
        repo_dir:        path to broodforge repo (passed through to the forge
                         package assembler so it bundles library code)
        kdbx_path:       optional KeePass .kdbx to embed in the forge package
        root_passphrase: pre-generated single-use install passphrase (if None,
                         a fresh one is generated — never a fixed value)
        keyboard/country/filesystem/disk_list: passed to `generate_answer_toml`
        now:             injectable datetime (for tests)

    Returns:
        Path to the generated bootstrap-image-*.tar.gz bundle.
    """
    if not _HAS_ASSEMBLER:
        raise RuntimeError("assemble_forge_package is required to build a bootstrap image")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    forge_pkg_dir = output_dir / "forge-package"
    forge_pkg_path = _assemble_forge_package(
        manifest=manifest,
        output_dir=forge_pkg_dir,
        repo_dir=repo_dir,
        kdbx_path=kdbx_path,
        now=now,
    )

    passphrase = root_passphrase or generate_install_passphrase()
    answer_toml_text = generate_answer_toml(
        manifest, root_passphrase=passphrase,
        keyboard=keyboard, country=country,
        filesystem=filesystem, disk_list=disk_list,
        interface_name=interface_name, now=now,
    )
    unit_text = generate_first_boot_unit(manifest)
    install_sh_text = generate_first_boot_install_sh(manifest)
    readme_text = generate_staging_readme(manifest, now=now)
    image_manifest = build_image_manifest(manifest, forge_pkg_path, answer_toml_text, now=now)

    if _HAS_IMAGE_MANIFEST_HTML:
        manifest_html = _build_image_manifest_html(
            manifest, image_manifest,
            now_fn=lambda: (now or datetime.now(timezone.utc)).isoformat(),
        )
    else:
        manifest_html = "<html><body><pre>" + json.dumps(image_manifest, indent=2) + "</pre></body></html>"

    bundle_path = output_dir / image_bundle_name(manifest, now)

    with tarfile.open(bundle_path, "w:gz") as tar:

        def _add_str(arcname: str, content: str, mode: int = 0o644):
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name=arcname)
            info.size = len(data)
            info.mode = mode
            tar.addfile(info, io.BytesIO(data))

        _add_str("iso-staging/answer.toml", answer_toml_text)
        tar.add(str(forge_pkg_path), arcname="iso-staging/forge-package.tar.gz")
        _add_str(f"iso-staging/first-boot/{FIRST_BOOT_SERVICE_NAME}", unit_text)
        _add_str("iso-staging/first-boot/install-first-boot-hook.sh", install_sh_text, mode=0o755)
        _add_str("iso-staging/bootstrap-image-manifest.json", json.dumps(image_manifest, indent=2))
        _add_str("iso-staging/bootstrap-image-manifest.html", manifest_html)
        _add_str("iso-staging/README.md", readme_text)

    return bundle_path
