#!/usr/bin/env python3
"""
phoenix_guided_setup.py — Guided setup framework for phoenix package generation (Phase 1.G.6).

Offers the operator two customisation points before a phoenix playbook is finalized:

  1. Restoration scope — full (all waves) or partial (operator selects which waves).
     Partial scope is useful when only specific components failed and the operator
     knows certain waves can be skipped (e.g., storage survived, skip Wave 1).

  2. Identity overrides — operator can override hostname, FQDN, cell_id, or other
     identity fields. This is useful when rebuilding on different hardware that
     must be registered under the same logical identity, or when a hostname change
     is required.

Key types:
  PhoenixGuidedSetupSession — session state: scope, selected waves, identity overrides
  step0_set_restoration_scope()   — set full/partial scope; for partial, set selected waves
  step1_run_identity_overrides()  — optionally override identity fields via guided setup
  apply_overrides_to_playbook()   — merge session choices into existing playbook dict
  restoration_wave_options()      — list of wave options for display

Stdlib only. No terminal I/O in this module — I/O is handled by phoenix-planner.py.
"""

from dataclasses import dataclass, field
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RESTORATION_SCOPE_FULL    = "full"
RESTORATION_SCOPE_PARTIAL = "partial"

RESTORATION_SCOPES = (RESTORATION_SCOPE_FULL, RESTORATION_SCOPE_PARTIAL)

# Identity fields that are meaningful to override in a phoenix context
PHOENIX_IDENTITY_FIELDS = [
    "host_identity.hostname",
    "host_identity.domain",
    "host_identity.fqdn",
    "host_identity.cell_id",
]


# ---------------------------------------------------------------------------
# PhoenixGuidedSetupSession
# ---------------------------------------------------------------------------

@dataclass
class PhoenixGuidedSetupSession:
    """
    Tracks operator choices during phoenix guided setup.

    Populated in order:
      step0: restoration_scope + selected_waves (for partial)
      step1: identity_overrides (optional)

    After all steps, apply_overrides_to_playbook() merges choices into
    the playbook dict.
    """
    restoration_scope:  str = RESTORATION_SCOPE_FULL
    selected_waves:     list = field(default_factory=list)   # wave numbers (int)
    identity_overrides: dict = field(default_factory=dict)   # field_path → value
    guided_session:     Optional[Any] = None                 # GuidedSetupSession
    setup_mode:         str = "autonomous"

    # Conflict/advisory warnings
    warnings:           list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helper: list wave options from a playbook dict
# ---------------------------------------------------------------------------

def restoration_wave_options(playbook: dict) -> list[dict]:
    """
    Return a list of wave display records from a phoenix playbook dict.

    Each record: {wave, name, estimated_minutes, step_count}
    Sorted by wave number ascending.
    """
    waves = playbook.get("waves") or []
    options = []
    for w in waves:
        wave_num = w.get("wave")
        if wave_num is None:
            continue
        options.append({
            "wave":              wave_num,
            "name":              w.get("name", f"Wave {wave_num}"),
            "estimated_minutes": w.get("estimated_minutes", 0),
            "step_count":        len(w.get("steps") or []),
        })
    options.sort(key=lambda x: x["wave"])
    return options


# ---------------------------------------------------------------------------
# Step 0 — Restoration scope
# ---------------------------------------------------------------------------

def step0_set_restoration_scope(
    session:        PhoenixGuidedSetupSession,
    scope:          str,
    selected_waves: Optional[list] = None,
) -> PhoenixGuidedSetupSession:
    """
    Set the restoration scope.

    scope: "full" — all waves are included.
           "partial" — only waves in selected_waves are included.

    selected_waves: list of wave numbers (int or float) to include.
                    Required for "partial" scope; ignored for "full".
    """
    if scope not in RESTORATION_SCOPES:
        raise ValueError(
            f"Unknown restoration scope {scope!r}. Valid: {RESTORATION_SCOPES}"
        )
    session.restoration_scope = scope

    if scope == RESTORATION_SCOPE_PARTIAL:
        if not selected_waves:
            session.warnings.append(
                "Partial scope selected but no waves specified — defaulting to full scope."
            )
            session.restoration_scope = RESTORATION_SCOPE_FULL
        else:
            session.selected_waves = [int(w) for w in selected_waves]

    return session


# ---------------------------------------------------------------------------
# Step 1 — Identity overrides
# ---------------------------------------------------------------------------

def step1_run_identity_overrides(
    session:   PhoenixGuidedSetupSession,
    manifest:  dict,
    mode:      str = "autonomous",
    overrides: Optional[dict] = None,
) -> PhoenixGuidedSetupSession:
    """
    Optionally override identity fields for the phoenix playbook.

    mode: "autonomous" — no overrides; "full-manual" — use overrides dict.
    overrides: dict of field_path → value for identity fields to override.
               Keys should be from PHOENIX_IDENTITY_FIELDS.

    For manual modes, records overrides in a GuidedSetupSession for
    conflict detection (e.g., format validation on hostname).
    """
    session.setup_mode = mode

    if mode == "autonomous" or not overrides:
        return session

    from guided_setup import GuidedSetupSession, set_value

    gs = GuidedSetupSession(mode=mode, manifest=manifest)
    session.guided_session = gs

    for fp, val in (overrides or {}).items():
        if fp in PHOENIX_IDENTITY_FIELDS:
            conflicts = set_value(fp, val, gs, source="manual")
            session.identity_overrides[fp] = val
            session.warnings.extend(conflicts)
        else:
            # Non-identity fields: store as-is without conflict check
            session.identity_overrides[fp] = val

    return session


# ---------------------------------------------------------------------------
# Apply overrides to playbook
# ---------------------------------------------------------------------------

def apply_overrides_to_playbook(
    session:  PhoenixGuidedSetupSession,
    playbook: dict,
) -> dict:
    """
    Merge guided setup choices into an existing phoenix playbook dict.

    Modifications:
      1. Restoration scope: if partial, filter playbook["waves"] to only
         the selected wave numbers.
      2. Identity overrides: update target_node identity fields and inject
         setup_overrides / restoration_scope into the playbook top level.

    Returns a modified copy of the playbook (original is not mutated).
    """
    import copy
    result = copy.deepcopy(playbook)

    # --- Restoration scope ---
    result["restoration_scope"] = session.restoration_scope

    if session.restoration_scope == RESTORATION_SCOPE_PARTIAL and session.selected_waves:
        selected_set = set(session.selected_waves)
        original_waves = result.get("waves") or []
        result["waves"] = [
            w for w in original_waves
            if int(w.get("wave", -1)) in selected_set
        ]
        result["partial_waves_selected"] = sorted(session.selected_waves)

    # --- Identity overrides ---
    if session.identity_overrides:
        target_node = result.get("target_node") or {}

        # Map field_path → target_node key
        field_to_key = {
            "host_identity.hostname": "hostname",
            "host_identity.domain":   "domain",
            "host_identity.fqdn":     "fqdn",
            "host_identity.cell_id":  "cell_id",
        }

        for fp, val in session.identity_overrides.items():
            node_key = field_to_key.get(fp)
            if node_key:
                target_node[node_key] = val

        if target_node:
            result["target_node"] = target_node

        # Record overrides for audit trail
        result["setup_overrides"] = {
            fp: {"value": val, "source": "manual"}
            for fp, val in session.identity_overrides.items()
        }

    # Embed warnings for operator review
    if session.warnings:
        result["setup_warnings"] = list(session.warnings)

    return result


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

def build_phoenix_guided_session(
    restoration_scope:  str = RESTORATION_SCOPE_FULL,
    selected_waves:     Optional[list] = None,
    identity_overrides: Optional[dict] = None,
    manifest:           Optional[dict] = None,
) -> PhoenixGuidedSetupSession:
    """
    Factory that constructs a fully-populated PhoenixGuidedSetupSession
    in one call. Useful for programmatic/test usage.
    """
    session = PhoenixGuidedSetupSession()
    step0_set_restoration_scope(session, restoration_scope, selected_waves)
    if identity_overrides:
        step1_run_identity_overrides(
            session,
            manifest=manifest or {},
            mode="full-manual",
            overrides=identity_overrides,
        )
    return session
