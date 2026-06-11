"""
migrate_initial__to__2026-06-09_00-00-00_0000000.py

Stamps ``schema_version`` into bootstrap-state.json for state files that
pre-date the versioning system.

This is the first real migration: it adds
``schema_version: "2026-06-09_00-00-00_0000000"`` to bootstrap-state.json
if the field is absent or still set to the ``"initial"`` sentinel.

Idempotent: safe to re-run. If schema_version is already
``"2026-06-09_00-00-00_0000000"``, this migration exits immediately without
modifying any file.

Contract: run(state_dir) -> None
  - state_dir: path to the directory containing bootstrap-state.json
  - Updates schema_version in bootstrap-state.json to the target version
  - Raises RuntimeError if bootstrap-state.json cannot be read or written
"""

import json
from pathlib import Path

_TARGET_VERSION = "2026-06-09_00-00-00_0000000"
_STATE_FILENAME = "bootstrap-state.json"


def run(state_dir: str) -> None:
    """
    Stamp schema_version = "2026-06-09_00-00-00_0000000" into
    bootstrap-state.json (idempotent).

    Parameters
    ----------
    state_dir:
        Directory containing bootstrap-state.json.

    Raises
    ------
    RuntimeError
        If bootstrap-state.json cannot be read or written.
    """
    state_file = Path(state_dir) / _STATE_FILENAME

    if not state_file.exists():
        raise RuntimeError(
            f"bootstrap-state.json not found in {state_dir}. "
            f"Cannot apply migration initial → {_TARGET_VERSION}."
        )

    try:
        with open(state_file, encoding="utf-8") as fh:
            state: dict = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"Cannot read {state_file}: {exc}") from exc

    # Idempotency check — already at target version
    if state.get("schema_version") == _TARGET_VERSION:
        return

    state["schema_version"] = _TARGET_VERSION

    try:
        with open(state_file, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
    except OSError as exc:
        raise RuntimeError(f"Cannot write {state_file}: {exc}") from exc
