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

import shlex
from dataclasses import dataclass, field
from typing import Optional

try:
    from keepass_mfa import (
        MfaConfig,
        print_totp_setup_to_tty,
        provision_totp,
        render_mfa_provision_commands,
    )
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

    # MFA configuration (TOTP or YubiKey — provisioned during forge).
    # Defaults to "totp" (app-based, no extra hardware to source) per operator
    # decision: high-level functions require a second factor by default — a
    # password-only KeePass unlock gate is no longer the baseline. SMS- and
    # email-based OTP are deliberately not offered as choices anywhere in this
    # module; both are weaker factors (SIM-swap / mailbox-compromise exposure)
    # than an authenticator app or a hardware key. "none" remains selectable
    # for operators who explicitly choose to opt out.
    mfa_method:             str = "totp"     # "none" | "totp" | "yubikey"


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

    Generates a master password suggestion using lib/passphrase.generate_master_password_suggestion(),
    which tries keepassxc-cli first (KeePass's own CSPRNG) then falls back to the
    secrets-module generator. If suggested_passphrase is provided explicitly, it is used
    as-is (useful for testing and when the caller has already generated a suggestion).
    """
    if not suggested_passphrase:
        try:
            import os as _os
            import sys as _sys
            _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))
            from passphrase import generate_master_password_suggestion
            suggested_passphrase, _ = generate_master_password_suggestion()
        except Exception:
            pass
    db_path = "/etc/broodforge/keepass.kdbx"

    # MFA method: honour an explicit guided-setup choice carried in the
    # manifest's keepass_config.mfa_method (AD-058 — "seen and confirmed,"
    # not silently inherited); fall back to the "totp" default otherwise.
    mfa_method = (forge_manifest.get("keepass_config") or {}).get("mfa_method") or "totp"

    extra: list[KeePassEntry] = []
    # include_wan is intentionally a no-op: all WAN-specific entries
    # (Cloudflare/DuckDNS/Headscale) are already in KEEPASS_INITIAL_ENTRIES
    # as required=False. The parameter is kept for CLI symmetry.

    return KeePassInitConfig(
        master_password_mode="generated",
        suggested_passphrase=suggested_passphrase,
        embed_in_packages=embed_in_packages,
        db_path=db_path,
        entries=list(KEEPASS_INITIAL_ENTRIES),
        extra_entries=extra,
        include_wan_entries=include_wan,
        mfa_method=mfa_method,
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
    ]

    if config.suggested_passphrase:
        lines += [
            "",
            "Suggested master password (generated by KeePass or Python secrets module):",
            f"  {config.suggested_passphrase}",
            "",
            "  You may use this suggestion, enter your own, or invoke KeePass's",
            "  built-in generator at the prompt. This suggestion is shown once only",
            "  and is NOT stored by broodforge.",
        ]

    lines += [
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
    The master password is piped via stdin — never passed as a command-line argument
    to avoid exposure in process listings (ps aux) and shell history.
    KEEPASS_MASTER_PASSWORD must be set in the calling shell's environment.
    """
    db = config.db_path
    db_q = shlex.quote(db)  # shell-quote for safe use in bash -c commands
    cmds = [
        "# Phase 1.F.6 — KeePass database initialisation",
        "apt-get install -y keepassxc 2>/dev/null || true",
        "install -d -m 700 /etc/broodforge",
        # Pipe master password via stdin; --set-password reads '-' as stdin in keepassxc-cli ≥2.6
        f"printf '%s\\n' \"$KEEPASS_MASTER_PASSWORD\" | keepassxc-cli db-create --set-password - {db_q}",
        "",
    ]

    for entry in config.entries + config.extra_entries:
        group = "/".join(entry.path.split("/")[:-1])
        cmds.append(
            f"printf '%s\\n' \"$KEEPASS_MASTER_PASSWORD\" | "
            f"keepassxc-cli mkdir --password - {db_q} "
            f"'/{group}' 2>/dev/null || true"
        )
        cmds.append(
            f"printf '%s\\n' \"$KEEPASS_MASTER_PASSWORD\" | "
            f"keepassxc-cli add --password - {db_q} "
            f"--no-password '/{entry.path}' "
            f"--notes '{entry.description} [PLACEHOLDER — set during service deploy]'"
        )

    cmds.append("")
    cmds.append(f"echo '[keepass] Database initialised at {db_q}'")
    if config.embed_in_packages:
        cmds.append("echo '[keepass] Database will be embedded in spawn/phoenix packages.'")
    else:
        cmds.append("echo '[keepass] Database NOT embedded — path-based access only.'")

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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import json
    import os
    import subprocess
    import sys

    ap = argparse.ArgumentParser(description="Broodforge KeePass initialisation (phase-03)")
    ap.add_argument("--manifest",    required=True, help="Path to forge-manifest.json")
    ap.add_argument("--run",         action="store_true", help="Execute init commands (requires KEEPASS_MASTER_PASSWORD in env)")
    ap.add_argument("--plan",        action="store_true", help="Print init plan without executing")
    ap.add_argument("--include-wan", action="store_true", help="Include WAN-specific KeePass entries")
    ap.add_argument("--embed",       action="store_true", help="Mark database as embedded in packages")
    ap.add_argument("--mfa",         default="totp", choices=["none", "totp", "yubikey"],
                    help="Second factor for the KeePass unlock gate (default: totp — "
                         "an authenticator app; 'yubikey' for a hardware key; 'none' "
                         "to explicitly opt out of the default. SMS/email OTP are not "
                         "offered — both are weaker factors than an app or hardware key.")
    args = ap.parse_args()

    with open(args.manifest) as f:
        manifest = json.load(f)

    cfg = generate_keepass_init_config(
        manifest,
        include_wan=args.include_wan,
        embed_in_packages=args.embed,
    )
    cfg.mfa_method = args.mfa

    if args.plan:
        print(describe_init_plan(cfg))
        sys.exit(0)

    if not args.run:
        ap.print_help()
        sys.exit(0)

    master_pw = os.environ.get("KEEPASS_MASTER_PASSWORD", "")
    if not master_pw:
        print("[keepass-init] KEEPASS_MASTER_PASSWORD not set — aborting.", file=sys.stderr)
        sys.exit(1)

    # Show the init plan (including passphrase suggestion) to /dev/tty
    # so the operator can confirm before execution. Suggestion already
    # displayed by forge_scripts.py generate_phase_03_sh() before the gate;
    # this is a reminder for --run invocations not via the phase script.
    try:
        with open("/dev/tty", "w") as _tty:
            _tty.write(describe_init_plan(cfg) + "\n")
    except OSError:
        pass

    cmds = render_init_commands(cfg)
    errors = 0
    for cmd in cmds:
        if not cmd or cmd.startswith("#"):
            continue
        # Commands that use printf…| piping must run via bash to preserve the pipe
        result = subprocess.run(
            ["bash", "-c", cmd],
            capture_output=False,
            env={**os.environ, "KEEPASS_MASTER_PASSWORD": master_pw},
            timeout=30,
        )
        if result.returncode != 0:
            print(f"[keepass-init] Command failed (exit {result.returncode}): {cmd[:80]}", file=sys.stderr)
            errors += 1

    if errors:
        print(f"[keepass-init] {errors} command(s) failed.", file=sys.stderr)
        sys.exit(1)

    # Provision TOTP AFTER the KeePass DB is confirmed created — the DB must
    # exist before provision_totp can write the secret entry. stdout may be
    # redirected to forge.log; TOTP secrets go to /dev/tty only.
    if cfg.mfa_method == "totp" and _HAS_MFA:
        totp_cfg = provision_totp(manifest.get("cell_id", "broodforge"))
        print_totp_setup_to_tty(totp_cfg.totp_secret or "", totp_cfg.totp_account or "broodforge")

    print(f"[keepass-init] Initialisation complete: {cfg.db_path}")
