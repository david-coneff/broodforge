#!/usr/bin/env python3
"""
forge_planner.py — Forge planner logic (Phase 1.G.4).

Separates the forge planning logic from interactive I/O so that the planner
can be tested without stdin/stdout and composed into different UIs.

The forge planner produces a forge-manifest.json that captures all operator
choices made during the guided setup, plus auto-calculated values for fields
that were not manually configured.

Four configuration modes (AD-049):
  autonomous   All settings auto-calculated from discovery (default).
  ip-selective Autonomous except operator chooses IP addressing.
  group-manual Operator selects which setting groups to configure manually.
  full-manual  Operator walks through all settings with auto-suggestions.

Interactive CLI entry point: forge-planner.py (separate script).

Stdlib only.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Mode constants
# ---------------------------------------------------------------------------

FORGE_MODE_AUTONOMOUS  = "autonomous"
FORGE_MODE_IP_SELECTIVE = "ip-selective"
FORGE_MODE_GROUP_MANUAL = "group-manual"
FORGE_MODE_FULL_MANUAL  = "full-manual"

FORGE_MODES = (
    FORGE_MODE_AUTONOMOUS,
    FORGE_MODE_IP_SELECTIVE,
    FORGE_MODE_GROUP_MANUAL,
    FORGE_MODE_FULL_MANUAL,
)

# Network profiles
PROFILE_LAN = "lan"
PROFILE_WAN = "wan"


# ---------------------------------------------------------------------------
# ForgePlannerSession
# ---------------------------------------------------------------------------

@dataclass
class ForgePlannerSession:
    """
    Tracks operator choices made during forge planning.

    Populated in order:
      step0: setup_mode selected
      step1: guided_setup session run (if non-autonomous)
      step2: identity configured (hostname, domain, cell_id)
      step3: network profile configured (lan / wan)
      step4: timezone set (optional — defaults to UTC)
      step5: backup destinations configured (optional)

    After all steps, build_forge_manifest() produces forge-manifest.json.
    """
    setup_mode:       str = FORGE_MODE_AUTONOMOUS

    # Base manifest from discovery (empty dict for bare-metal first run)
    manifest:         dict = field(default_factory=dict)

    # Guided setup session (populated for non-autonomous modes)
    guided_session:   Optional[Any] = None  # GuidedSetupSession

    # Identity fields (set by step2 or by guided session)
    hostname:         Optional[str] = None
    domain:           Optional[str] = None
    cell_id:          Optional[str] = None

    # Network profile (set by step3)
    network_profile:  str = PROFILE_LAN
    wan_config:       dict = field(default_factory=dict)

    # Timezone (set by step4; stored in host_identity.timezone)
    timezone:         Optional[str] = None

    # Backup configuration (set by step5; minimal for forge — full config in 6.B)
    backup_destinations: list = field(default_factory=list)
    keepass_embed_in_packages: bool = False

    # Serialized manual overrides (populated after guided session)
    setup_overrides:  dict = field(default_factory=dict)

    # Conflict warnings collected during guided setup
    warnings:         list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Step 0 — Set setup mode
# ---------------------------------------------------------------------------

def step0_set_setup_mode(
    session: ForgePlannerSession,
    mode:    str,
) -> ForgePlannerSession:
    """
    Set the configuration mode for this forge session.

    For autonomous mode, no guided_setup session is created — all values
    will be auto-calculated from the base manifest at manifest-build time.
    """
    if mode not in FORGE_MODES:
        raise ValueError(f"Unknown forge mode {mode!r}. Valid: {FORGE_MODES}")
    session.setup_mode = mode
    return session


# ---------------------------------------------------------------------------
# Step 1 — Run guided setup (non-autonomous modes)
# ---------------------------------------------------------------------------

def step1_run_guided_setup(
    session:         ForgePlannerSession,
    selected_groups: Optional[list[str]] = None,
    ip_values:       Optional[dict] = None,
) -> ForgePlannerSession:
    """
    Launch a GuidedSetupSession for the chosen mode.

    For autonomous: no-op (returns session unchanged).
    For ip-selective: pre-populates non-IP fields auto; returns IP suggestion dict.
    For group-manual: uses selected_groups to scope the manual fields.
    For full-manual: creates session with all fields eligible for manual entry.

    ip_values: dict of field_path → value for explicit IP field overrides
               (used by ip-selective and full-manual modes).
    selected_groups: list of group IDs to configure manually (group-manual mode).
    """
    if session.setup_mode == FORGE_MODE_AUTONOMOUS:
        return session

    from guided_setup import (
        GuidedSetupSession,
        run_ip_selective_suggestions,
        session_to_overrides,
        set_value,
    )

    gs = GuidedSetupSession(
        mode=session.setup_mode,
        manifest=session.manifest,
        selected_groups=set(selected_groups or []),
    )
    session.guided_session = gs

    if session.setup_mode == FORGE_MODE_IP_SELECTIVE:
        run_ip_selective_suggestions(gs)
        if ip_values:
            for fp, val in ip_values.items():
                conflicts = set_value(fp, val, gs, source="manual")
                session.warnings.extend(conflicts)

    elif session.setup_mode == FORGE_MODE_GROUP_MANUAL:
        if selected_groups:
            gs.selected_groups = set(selected_groups)

    # For full-manual: caller will drive set_value() calls; session is ready

    # Serialize current overrides
    session.setup_overrides = session_to_overrides(gs)
    return session


# ---------------------------------------------------------------------------
# Step 2 — Set identity fields
# ---------------------------------------------------------------------------

def step2_set_identity(
    session:  ForgePlannerSession,
    hostname: Optional[str] = None,
    domain:   Optional[str] = None,
    cell_id:  Optional[str] = None,
) -> ForgePlannerSession:
    """
    Set identity fields for the forge session.

    If a guided session is active, records these as manual choices in it so
    that dependent suggestions (FQDN, headscale_url, cell_id) are revised.
    Updates session.setup_overrides after recording.
    """
    from guided_setup import session_to_overrides, set_value, suggest

    gs = session.guided_session

    if hostname is not None:
        session.hostname = hostname
        if gs is not None:
            conflicts = set_value("host_identity.hostname", hostname, gs, source="manual")
            session.warnings.extend(conflicts)

    if domain is not None:
        session.domain = domain
        if gs is not None:
            conflicts = set_value("host_identity.domain", domain, gs, source="manual")
            session.warnings.extend(conflicts)

    if cell_id is not None:
        session.cell_id = cell_id
        if gs is not None:
            conflicts = set_value("host_identity.cell_id", cell_id, gs, source="manual")
            session.warnings.extend(conflicts)

    # For autonomous, derive sensible defaults from manifest
    if gs is None:
        if session.hostname is None:
            session.hostname = session.manifest.get("host", {}).get("hostname") or "pve01"
        if session.domain is None:
            hi = session.manifest.get("host_identity") or {}
            session.domain = hi.get("domain") or "home.example.com"
        if session.cell_id is None:
            session.cell_id = session.manifest.get("cell_id") or f"{session.hostname}-cell"
    else:
        # Pull auto-suggestions for any fields not yet set
        if session.hostname is None:
            session.hostname = suggest("host_identity.hostname", gs)
        if session.domain is None:
            session.domain = suggest("host_identity.domain", gs)
        if session.cell_id is None:
            session.cell_id = suggest("host_identity.cell_id", gs)
        # Refresh overrides
        session.setup_overrides = session_to_overrides(gs)

    return session


# ---------------------------------------------------------------------------
# Step 3 — Set network profile
# ---------------------------------------------------------------------------

def step3_set_network_profile(
    session:    ForgePlannerSession,
    profile:    str,
    wan_config: Optional[dict] = None,
) -> ForgePlannerSession:
    """
    Set the network profile for the forged hatchery.

    profile: "lan" | "wan"
    wan_config: optional WAN config dict (domain, dns_provider, headscale_url, etc.)
    """
    if profile not in (PROFILE_LAN, PROFILE_WAN):
        raise ValueError(f"Unknown network profile {profile!r}. Valid: lan, wan")
    session.network_profile = profile
    if wan_config:
        session.wan_config = dict(wan_config)

    # If guided session active, record network-related choices
    if session.guided_session is not None:
        from guided_setup import session_to_overrides, set_value
        gs = session.guided_session

        # Record headscale URL for WAN profile
        if profile == PROFILE_WAN and wan_config and wan_config.get("headscale_url"):
            conflicts = set_value(
                "network.headscale_url",
                wan_config["headscale_url"],
                gs,
                source="manual",
            )
            session.warnings.extend(conflicts)

        session.setup_overrides = session_to_overrides(gs)

    return session


# ---------------------------------------------------------------------------
# Manual field entry helper (for group-manual and full-manual modes)
# ---------------------------------------------------------------------------

def record_manual_field(
    session:    ForgePlannerSession,
    field_path: str,
    value:      Any,
) -> list[str]:
    """
    Record a manual field value in the guided session.
    Returns list of conflict warning strings (also appended to session.warnings).

    Refreshes session.setup_overrides after recording.
    """
    if session.guided_session is None:
        return []

    from guided_setup import session_to_overrides, set_value
    conflicts = set_value(field_path, value, session.guided_session, source="manual")
    session.warnings.extend(conflicts)
    session.setup_overrides = session_to_overrides(session.guided_session)
    return conflicts


# ---------------------------------------------------------------------------
# Step 4 — Set timezone (Phase 1.F.9)
# ---------------------------------------------------------------------------

def step4_set_timezone(
    session:  ForgePlannerSession,
    timezone: Optional[str] = None,
) -> ForgePlannerSession:
    """
    Set the operator's timezone preference for the forged hatchery.

    timezone: IANA timezone string (e.g. "America/Denver", "Europe/London").
    If None, the timezone will default to UTC at runtime.

    Stored in host_identity.timezone in the forge manifest. All documentation
    engine timestamps display both UTC and local time.
    """
    if timezone:
        # Minimal validation: must contain "/" for IANA format, or be "UTC"
        if timezone != "UTC" and "/" not in timezone:
            session.warnings.append(
                f"Timezone {timezone!r} does not look like an IANA timezone "
                "(expected format: Continent/City, e.g. America/Denver). "
                "Using it anyway — verify it is valid."
            )
        session.timezone = timezone
    return session


# ---------------------------------------------------------------------------
# Step 5 — Configure backup destinations (Phase 1.F.10)
# ---------------------------------------------------------------------------

def step5_set_backup_config(
    session:                   ForgePlannerSession,
    destinations:              Optional[list] = None,
    keepass_embed_in_packages: bool = False,
) -> ForgePlannerSession:
    """
    Set backup destination configuration for the hatchery.

    At forge time, the operator configures at least one backup destination for:
      (a) Secrets / KeePass database
      (b) Configuration state

    Application data volumes are opt-in and configured per-service after forging.

    destinations: list of destination dicts:
      [{type, rclone_remote, rclone_path}]   — cloud/remote destinations
      [{type, local_path}]                    — local filesystem / USB mount

    keepass_embed_in_packages: whether to embed the KeePass database in
      subsequent spawn/phoenix packages (convenient but adds security consideration).
    """
    if destinations is not None:
        session.backup_destinations = list(destinations)
    session.keepass_embed_in_packages = keepass_embed_in_packages
    return session


# ---------------------------------------------------------------------------
# Build forge manifest
# ---------------------------------------------------------------------------

def build_forge_manifest(
    session: ForgePlannerSession,
    now_fn:  Optional[Any] = None,
) -> dict:
    """
    Assemble the forge-manifest.json dict from a completed planner session.

    For autonomous mode, all values are auto-calculated.
    For guided modes, manual overrides from the guided session are embedded
    under the top-level "setup_overrides" key (field_path → {value, source}).

    Returns:
        forge-manifest dict ready for JSON serialization.
    """
    now = (now_fn or (lambda: datetime.now(timezone.utc).isoformat()))()

    hostname = session.hostname or "pve01"
    domain   = session.domain   or "home.example.com"
    cell_id  = session.cell_id  or f"{hostname}-cell"
    fqdn     = f"{hostname}.{domain}"

    # Gather network topology from manifest or defaults
    m  = session.manifest
    nt = m.get("network_topology") or {}
    m.get("host_identity") or {}

    mgmt_cidr = nt.get("management_cidr") or "192.168.1.0/24"
    gateway   = nt.get("gateway") or "192.168.1.1"

    # If guided session has IP choices, use them
    if session.guided_session is not None:
        gs = session.guided_session
        gs_cidr = gs.get_value("network.management_cidr")
        gs_gw   = gs.get_value("network.gateway")
        if gs_cidr:
            mgmt_cidr = gs_cidr
        if gs_gw:
            gateway = gs_gw

    # Network profile
    profile = session.network_profile

    # host_identity block (include timezone if set)
    host_identity: dict = {
        "hostname": hostname,
        "domain":   domain,
        "fqdn":     fqdn,
        "cell_id":  cell_id,
    }
    if session.timezone:
        host_identity["timezone"] = session.timezone

    manifest: dict = {
        "schema_version": "1.0",
        "cell_id":        cell_id,
        "generated_at":   now,
        "setup_mode":     session.setup_mode,
        "host_identity":  host_identity,
        "network_topology": {
            "profile":          profile,
            "management_cidr":  mgmt_cidr,
            "gateway":          gateway,
        },
    }

    # WAN config
    if profile == PROFILE_WAN and session.wan_config:
        manifest["network_topology"]["wan_config"] = dict(session.wan_config)

    # MFA method for the KeePass unlock gate (AD-058 default: "totp").
    # Guided sessions may have recorded an explicit operator choice under
    # "security.mfa_method" — honour it; otherwise fall back to the default.
    mfa_method = "totp"
    if session.guided_session is not None:
        gs_mfa = session.guided_session.get_value("security.mfa_method")
        if gs_mfa:
            mfa_method = gs_mfa

    # KeePass configuration (from step5)
    manifest["keepass_config"] = {
        "embed_in_packages":  session.keepass_embed_in_packages,
        "database_path_hint": None,
        "mfa_method":         mfa_method,
    }

    # Backup destinations (from step5 — minimal at forge time)
    if session.backup_destinations:
        manifest["backup_config_ref"] = {
            "destinations": list(session.backup_destinations),
        }

    # Embed setup overrides so downstream tools know which fields were manual
    if session.setup_overrides:
        manifest["setup_overrides"] = session.setup_overrides

    # Embed warnings so the operator can review them
    if session.warnings:
        manifest["setup_warnings"] = list(session.warnings)

    return manifest


# ---------------------------------------------------------------------------
# Suggestion helper — exposes guided suggestions without a running session
# ---------------------------------------------------------------------------

def auto_suggest_field(field_path: str, manifest: dict) -> Any:
    """
    Return the auto-suggestion for a field given a base manifest dict.
    Useful for displaying defaults before an operator makes choices.
    """
    from guided_setup import GuidedSetupSession, suggest
    session = GuidedSetupSession(mode=FORGE_MODE_AUTONOMOUS, manifest=manifest)
    return suggest(field_path, session)
