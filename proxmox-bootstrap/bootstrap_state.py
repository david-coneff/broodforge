#!/usr/bin/env python3
"""
bootstrap_state.py — bootstrap-state.json loader with schema_version validation.

Provides a single entry point for loading and validating the broodforge
bootstrap-state.json file. Handles the schema_version field introduced in
Phase 1.N: if the state file is from a newer broodforge version than the
current code was written against, a warning is logged so operators know
that some fields may not be understood by this version.

Schema version format
---------------------
Version strings use the format ``YYYY-MM-DD_HH-MM-SS_<7-char-hash>``, e.g.
``"2026-06-09_14-30-22_a3b4c5d"``.  The special sentinel ``"initial"``
represents state that pre-dates the versioning system.  CURRENT_SCHEMA_VERSION
is loaded from ``proxmox-bootstrap/version.py`` at import time; that file is
updated by ``scripts/forge-stamp-version.sh`` at release time.

Provides:
  CURRENT_SCHEMA_VERSION  — the schema version this module was written against
  BootstrapState          — loaded, validated state dataclass
  load_bootstrap_state()  — load from a file path, warn on future schema
  _warn_schema_version()  — (internal) emit a schema-mismatch warning

Stdlib only.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema version constant (loaded from version.py at import time)
# ---------------------------------------------------------------------------

def _load_schema_version() -> str:
    """Load SCHEMA_VERSION from version.py by reading the module attribute directly.

    On FileNotFoundError (version.py absent) returns the baseline fallback silently —
    the file may not exist yet on a fresh checkout.  On any other failure a
    warnings.warn() is emitted so corruption is visible rather than silently ignored.

    Accesses ``mod.SCHEMA_VERSION`` directly — version.py is a pure constants file
    updated by ``scripts/forge-stamp-version.sh`` and exposes no functions.
    """
    version_file = Path(__file__).parent / "version.py"
    _DEFAULT = "2026-06-09_00-00-00_0000000"
    try:
        spec = importlib.util.spec_from_file_location("_broodforge_version", version_file)
        if spec is not None and spec.loader is not None:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            return str(mod.SCHEMA_VERSION)
    except FileNotFoundError:
        pass  # version.py absent — return baseline silently
    except Exception as exc:
        warnings.warn(
            f"Cannot load SCHEMA_VERSION from version.py ({exc}) — using baseline fallback",
            stacklevel=2,
        )
    return _DEFAULT


CURRENT_SCHEMA_VERSION: str = _load_schema_version()
"""The schema version this module was written against.

Loaded from ``proxmox-bootstrap/version.py`` at import time.  If
bootstrap-state.json contains a schema_version newer than this string,
:func:`load_bootstrap_state` will emit a warning.  Migration infrastructure
(Phase 1.N) is responsible for keeping the state file at a compatible version.

Update by running ``bash scripts/forge-stamp-version.sh`` after any change to
the package.
"""

_STATE_FILENAME: str = "bootstrap-state.json"


# ---------------------------------------------------------------------------
# Schema version comparison helpers
# ---------------------------------------------------------------------------

def _parse_version(version_str: str) -> tuple:
    """
    Parse a schema version string to a sort key for comparison.

    Returns a tuple that sorts correctly:
    - ``"initial"``                         → ``("",)``
    - ``"YYYY-MM-DD_HH-MM-SS_<hash>"``     → ``("YYYYMMDD_HH-MM-SS",)``

    Raises ValueError for any other format.
    """
    s = str(version_str).strip()
    if s == "initial":
        return ("",)
    parts = s.split("_")
    if len(parts) != 3:
        raise ValueError(
            f"Invalid schema version {version_str!r}: expected "
            f"'YYYY-MM-DD_HH-MM-SS_<7-char-hash>' or 'initial'"
        )
    date_str, time_str, hash_str = parts
    if len(date_str) != 10 or len(time_str) != 8:
        raise ValueError(
            f"Invalid schema version {version_str!r}: "
            f"date must be 10 chars (YYYY-MM-DD), time must be 8 chars (HH-MM-SS)"
        )
    try:
        y, m, d = date_str.split("-")
        int(y); int(m); int(d)
        h, mn, sec = time_str.split("-")
        int(h); int(mn); int(sec)
    except (ValueError, AttributeError) as exc:
        raise ValueError(
            f"Invalid schema version {version_str!r}: "
            f"date and time components must be numeric ({exc})"
        ) from exc
    # Sort key is the timestamp prefix (YYYY-MM-DD_HH-MM-SS)
    return (f"{date_str}_{time_str}",)


def _is_newer(version_str: str, reference: str) -> bool:
    """Return True if version_str is strictly newer than reference."""
    return _parse_version(version_str) > _parse_version(reference)


# ---------------------------------------------------------------------------
# BootstrapState — thin wrapper around the raw state dict
# ---------------------------------------------------------------------------

@dataclass
class BootstrapState:
    """
    Loaded bootstrap-state.json content.

    Attributes
    ----------
    raw:
        The complete parsed JSON dict. Callers that need specific fields
        not captured as named attributes should access ``raw`` directly.
    schema_version:
        The schema_version recorded in the file, or ``"initial"`` if absent.
    source_path:
        The filesystem path from which this state was loaded.
    """

    raw: dict[str, Any]
    schema_version: str
    source_path: Optional[Path] = field(default=None)

    def get(self, key: str, default: Any = None) -> Any:
        """Convenience pass-through to the underlying dict."""
        return self.raw.get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self.raw[key]

    def __contains__(self, key: str) -> bool:
        return key in self.raw


# ---------------------------------------------------------------------------
# Schema version warning
# ---------------------------------------------------------------------------

def _warn_schema_version(
    file_schema: str,
    current: str,
    source_path: Optional[Path] = None,
) -> None:
    """
    Emit a warning when bootstrap-state.json is from a newer schema version.

    This is a warning (not an error) because older code can often still read
    newer state files — unknown fields are simply ignored. Operators should
    upgrade broodforge or run migration_manager.py to align versions.
    """
    loc = f" in {source_path}" if source_path else ""
    msg = (
        f"bootstrap-state.json{loc} has schema_version={file_schema!r}, "
        f"but this broodforge code was written against version {current!r}. "
        "Some fields introduced in the newer schema may not be understood. "
        "Run 'python3 proxmox-bootstrap/migration_manager.py' to align versions, "
        "or upgrade broodforge."
    )
    logger.warning(msg)
    warnings.warn(msg, category=UserWarning, stacklevel=3)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_bootstrap_state(
    path: str | Path,
    *,
    allow_missing: bool = False,
) -> BootstrapState:
    """
    Load bootstrap-state.json from *path*.

    If *path* is a directory, looks for ``bootstrap-state.json`` inside it.

    Parameters
    ----------
    path:
        Path to the state file, or its containing directory.
    allow_missing:
        If True and the file does not exist, return an empty BootstrapState
        with schema_version ``"initial"`` rather than raising FileNotFoundError.

    Returns
    -------
    BootstrapState
        The loaded state. Emits a warning (via :mod:`warnings`) if the file's
        schema_version is newer than CURRENT_SCHEMA_VERSION.

    Raises
    ------
    FileNotFoundError
        If the state file does not exist and allow_missing is False.
    ValueError
        If the JSON cannot be parsed or schema_version has an invalid format.
    """
    state_path = Path(path)
    if state_path.is_dir():
        state_path = state_path / _STATE_FILENAME

    if not state_path.exists():
        if allow_missing:
            logger.info(
                "bootstrap-state.json not found at %s — returning empty state", state_path
            )
            return BootstrapState(raw={}, schema_version="initial", source_path=state_path)
        raise FileNotFoundError(
            f"bootstrap-state.json not found: {state_path}. "
            "Run 'python3 proxmox-bootstrap/init-bootstrap-state.py' to create it."
        )

    try:
        with open(state_path, encoding="utf-8") as fh:
            raw: dict[str, Any] = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Cannot parse {state_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError(f"{state_path} must contain a JSON object at the top level")

    # Read and validate schema_version
    raw_version = raw.get("schema_version", "initial")
    try:
        _parse_version(str(raw_version))
    except ValueError as exc:
        raise ValueError(
            f"Invalid schema_version {raw_version!r} in {state_path}: {exc}"
        ) from exc

    schema_version = str(raw_version)

    # Warn if the state file is from a newer broodforge version
    if _is_newer(schema_version, CURRENT_SCHEMA_VERSION):
        _warn_schema_version(schema_version, CURRENT_SCHEMA_VERSION, state_path)

    return BootstrapState(raw=raw, schema_version=schema_version, source_path=state_path)
