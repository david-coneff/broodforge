#!/usr/bin/env python3
"""
forge_keepass_init.py — KeePass initialisation at forge time (Phase 1.F.6).

Generates the setup commands and KeePass entry plan for phase-03 (host config).
The operator:
  1. Accepts or customises a generated passphrase as the master password
  2. The passphrase generator suggests a readable phrase (Capital.word.phrase.N format)
  3. KeePass database is initialised with the chosen password
  4. Service credential paths are established (values filled later during service deploy)
  5. Operator chooses whether to embed the database in future packages

Provides:
  KeePassInitConfig       — structured config
  KeePassEntry            — single KeePass entry (path + description)
  KEEPASS_INITIAL_ENTRIES — canonical list of entries for a fresh hatchery
  generate_keepass_init_config() — build from forge manifest
  keepass_entry_paths()   — list all paths to pre-create
  describe_init_plan()    — human-readable setup plan description
  render_init_commands()  — ordered setup commands for phase-03
  config_to_dict()        — serialise for testing

Stdlib only.
"""

from dataclasses import dataclass, field
from typing import Optional

try:
    from keepass_mfa import MfaConfig, provision_totp, render_mfa_provision_commands
    _HAS_MFA = True
except ImportError:
    _HAS_MFA = False


# ---------------------------------------------------------------------------
# KeePass entry spec
# ---------------------------------------------------------------------------

@dataclass
class KeePassEntry:
    """A single KeePass entry to create during forge initialisation."""
    path:        str        # KeePass path (e.g. "Infrastructure/headscale/api-key")
    description: str        # Human-readable description of what this entry holds
    required:    bool = True # If False: entry is optional / only created for certain configs


# ---------------------------------------------------------------------------
# Canonical initial entry list
# ---------------------------------------------------------------------------

#
# These entries are created at forge time with placeholder values.
# Actual values are populated automatically during service deployment.
#
KEEPASS_INITIAL_ENTRIES: list[KeePassEntry] = [
    # Infrastructure — core platform credentials
    KeePassEntry("Infrastructure/headscale/api-key",
                 "Headscale server API key for spawn-planner.py", required=True),
    KeePassEntry("Infrastructure/forgejo/admin-password",
                 "Forgejo admin user password", required=True),
    KeePassEntry("Infrastructure/forgejo/runner-token",
                 "Forgejo Actions runner registration token", required=False),
    KeePassEntry("Infrastructure/proxmox/api-token",
                 "Proxmox API token for OpenTofu provider", required=True),

    # k3s cluster
    KeePassEntry("k3s/join-token-server",
                 "k3s server-mode join token (rotated after broodling joins)", required=True),
    KeePassEntry("k3s/join-token-worker",
                 "k3s worker-mode join token (rotated after broodling joins)", required=True),

    # Assessment engine
    KeePassEntry("AssessmentEngine/api-key",
                 "Assessment Engine API key for doc-gen engine.py", required=True),

    # Backup — transport credentials (NOT subject to KeePass gate — embedded in packages)
    KeePassEntry("Backup/transport/credentials",
                 "rclone backup transport credentials (embedded in forge manifest)", required=False),

    # Backup — restic repo passwords (auto-created by run-backup.py)
    KeePassEntry("Backup/config-state/current",
                 "Pointer to latest restic repo password for config-state layer", required=False),
    KeePassEntry("Backup/secrets/current",
                 "Pointer to latest restic repo password for secrets layer", required=False),

    # MFA — second factor for KeePass unlock gate
    KeePassEntry("MFA/method",
                 "KeePass unlock gate MFA method: none | totp | yubikey", required=False),
    KeePassEntry("MFA/totp-secret",
                 "TOTP base32 secret (auto-provisioned at forge time)", required=False),

    # External services — populated if configured at forge time
    KeePassEntry("External/cloudflare/api-token",
                 "Cloudflare API token for DNS-01 cert automation", required=False),
    KeePassEntry("External/duckdns/token",
                 "DuckDNS token for DDNS updates and acme.sh DNS-01", required=False),
    KeePassEntry("External/smtp/credentials",
                 "SMTP relay credentials for outbound email", required=False),
]


# ---------------------------------------------------------------------------
# KeePassInitConfig
# ---------------------------------------------------------------------------

@dataclass
class KeePassInitConfig:
    """Structured KeePass initialisation configuration."""

    # How the master password is sourced
    master_password_mode:   str = "generated"   # "generated" | "operator-chosen"

    # Generated passphrase suggestion (shown to operator; not stored by broodforge)
    suggested_passphrase:   Optional[str] = None

    # Embed database in subsequent packages?
    embed_in_packages:      bool = False

    # Filesystem path for the database
    db_path:                str = "/etc/broodforge/keepass.kdbx"

    # Entries to pre-create during initialisation
    entries:                list[KeePassEntry] = field(default_factory=lambda: list(KEEPASS_INITIAL_ENTRIES))

    # Optional: extra entries (WAN-specific, etc.)
    extra_entries:          list[KeePassEntry] = field(default_factory=list)

    # Whether to include WAN-specific entries (Cloudflare, DuckDNS, Headscale)
    include_wan_entries:    bool = False

    # MFA configuration (TOTP or YubiKey — provisioned during forge)
    mfa_method:             str = "none"     # "none" | "totp" | "yubikey"


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

def generate_keepass_init_config(
    forge_manifest:   dict,
    include_wan:      bool = False,
    embed_in_packages: bool = False,
    suggested_passphrase: Optional[str] = None,
) -> KeePassInitConfig:
    """
    Build KeePassInitConfig from forge manifest.

    If suggested_passphrase is None, the CLI will generate one and display it
    to the operator. This function does not generate passphrases to avoid
    importing lib/passphrase.py (kept as a soft dependency for testing).
    """
    db_path = "/etc/broodforge/keepass.kdbx"

    extra: list[KeePassEntry] = []
    if include_wan:
        # Add WAN-specific entries if not already in the base list
        wan_paths = {e.path for e in KEEPASS_INITIAL_ENTRIES}
        # These are already required=False in KEEPASS_INITIAL_ENTRIES
        pass  # Base list already has Cloudflare/DuckDNS entries

    return KeePassInitConfig(
        master_password_mode="generated",
        suggested_passphrase=suggested_passphrase,
        embed_in_packages=embed_in_packages,
        db_path=db_path,
        entries=list(KEEPASS_INITIAL_ENTRIES),
        extra_entries=extra,
        include_wan_entries=include_wan,
    )


# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------

def keepass_entry_paths(config: KeePassInitConfig, required_only: bool = False) -> list[str]:
    """
    Return all KeePass entry paths to pre-create.

    required_only=True: only return entries marked required=True.
    """
    all_entries = config.entries + config.extra_entries
    if required_only:
        return [e.path for e in all_entries if e.required]
    return [e.path for e in all_entries]


def describe_init_plan(config: KeePassInitConfig) -> str:
    """Return a human-readable description of the KeePass initialisation plan."""
    all_entries = config.entries + config.extra_entries
    required    = [e for e in all_entries if e.required]
    optional    = [e for e in all_entries if not e.required]

    lines = [
        "KeePass Initialisation Plan",
        "===========================",
        f"Database path:    {config.db_path}",
        f"Embed in packages: {'Yes' if config.embed_in_packages else 'No'}",
        f"Master password:  {config.master_password_mode}",
        "",
        f"Required entries ({len(required)}):",
    ]
    for e in required:
        lines.append(f"  {e.path}")
        lines.append(f"    → {e.description}")

    if optional:
        lines.append("")
        lines.append(f"Optional entries ({len(optional)}) — created with placeholder if applicable:")
        for e in optional:
            lines.append(f"  {e.path}")

    return "\n".join(lines)


def render_init_commands(config: KeePassInitConfig) -> list[str]:
    """
    Return ordered shell commands to initialise the KeePass database in phase-03.

    These commands use keepassxc-cli (available in Debian/Ubuntu repos).
    The master password is read from the KEEPASS_MASTER_PASSWORD environment
    variable (set by forge.sh from the operator's input — never stored on disk).
    """
    db = config.db_path
    cmds = [
        "# Phase 1.F.6 — KeePass database initialisation",
        "apt-get install -y keepassxc 2>/dev/null || true",
        f"install -d -m 700 /etc/broodforge",
        f"keepassxc-cli db-create --set-password '$KEEPASS_MASTER_PASSWORD' {db}",
        "",
    ]

    for entry in config.entries + config.extra_entries:
        group = "/".join(entry.path.split("/")[:-1])
        name  = entry.path.split("/")[-1]
        cmds.append(
            f"keepassxc-cli mkdir {db} --password '$KEEPASS_MASTER_PASSWORD' "
            f"'/{group}' 2>/dev/null || true"
        )
        cmds.append(
            f"keepassxc-cli add {db} --password '$KEEPASS_MASTER_PASSWORD' "
            f"--no-password '/{entry.path}' "
            f"--notes '{entry.description} [PLACEHOLDER — set during service deploy]'"
        )

    cmds.append("")
    cmds.append(f"echo '[keepass] Database initialised at {db}'")
    if config.embed_in_packages:
        cmds.append(f"echo '[keepass] Database will be embedded in spawn/phoenix packages.'")
    else:
        cmds.append(f"echo '[keepass] Database NOT embedded — path-based access only.'")

    # MFA provisioning (if configured)
    if config.mfa_method != "none" and _HAS_MFA:
        if config.mfa_method == "totp":
            # Cell ID derived from db path (best effort)
            cell_id = "broodforge"
            mfa_cfg = provision_totp(cell_id)
        else:
            mfa_cfg = MfaConfig(method=config.mfa_method)
        cmds += render_mfa_provision_commands(mfa_cfg, db)

    return cmds


# ---------------------------------------------------------------------------
# Serialisation helper
# ---------------------------------------------------------------------------

def config_to_dict(config: KeePassInitConfig) -> dict:
    """Serialise KeePassInitConfig to a plain dict."""
    all_entries = config.entries + config.extra_entries
    return {
        "master_password_mode": config.master_password_mode,
        "embed_in_packages":    config.embed_in_packages,
        "db_path":              config.db_path,
        "include_wan_entries":  config.include_wan_entries,
        "mfa_method":           config.mfa_method,
        "entry_count":          len(all_entries),
        "required_entry_count": sum(1 for e in all_entries if e.required),
        "entry_paths":          [e.path for e in all_entries],
    }
