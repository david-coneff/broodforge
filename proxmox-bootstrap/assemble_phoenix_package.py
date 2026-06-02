#!/usr/bin/env python3
"""
assemble_phoenix_package.py — Phoenix package assembler (Phase 9.T).

Bundles all phoenix artifacts into a self-contained tar.gz archive that an
operator runs on replacement hardware to restore a failed node.

Package layout:
  phoenix-package-{cell_id}-{hostname}-{YYYY-MM-DD_HH_MM_SS}.tar.gz
  ├── phoenix-playbook.json        machine-readable reconstruction plan
  ├── run-all.sh                   orchestrating entry point
  ├── phase-{N}-{name}.sh          one script per restoration wave
  ├── lib/
  │   └── checkpoint.sh            resumable checkpoint library
  ├── phoenix-workbook.html        optional phase-tracking workbook
  └── phoenix-manifest.html        human-readable manifest (mandatory)

Security: the package NEVER contains secret values. Only KeePass paths
(references) are included. The KeePass database is optional and only
embedded if the operator chooses at planning time.

Stdlib only.
"""

import io
import json
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    from phoenix_scripts import (
        generate_wave_script, generate_run_all_sh,
        PHOENIX_KEEPASS_GATE_SH as _PHOENIX_KEEPASS_GATE_SH,
    )
    _HAS_SCRIPTS = True
    _HAS_KEEPASS_GATE = True
except ImportError:
    _HAS_SCRIPTS = False
    _HAS_KEEPASS_GATE = False
    _PHOENIX_KEEPASS_GATE_SH = None  # type: ignore

try:
    from html_package_manifest import build_phoenix_manifest_html as _build_phoenix_manifest_html
    _HAS_PKG_MANIFEST = True
except ImportError:
    _build_phoenix_manifest_html = None  # type: ignore
    _HAS_PKG_MANIFEST = False

try:
    from html_phoenix_workbook import build_phoenix_workbook_html as _build_phoenix_workbook_html
    _HAS_WORKBOOK = True
except ImportError:
    _build_phoenix_workbook_html = None  # type: ignore
    _HAS_WORKBOOK = False


# ---------------------------------------------------------------------------
# Checkpoint library (embedded literal — avoids filesystem read at build time)
# ---------------------------------------------------------------------------

_CHECKPOINT_SH = """\
#!/usr/bin/env bash
# checkpoint.sh — Resumable checkpoint library for phoenix scripts
CHECKPOINT_DIR="${SCRIPT_DIR}/.checkpoints"
mkdir -p "$CHECKPOINT_DIR"

checkpoint_start()  { echo "[$(date +%H:%M:%S)] START: $1"; }
checkpoint_done()   { touch "$CHECKPOINT_DIR/$1.done"; echo "[$(date +%H:%M:%S)] DONE:  $1"; }
checkpoint_skip()   { echo "[$(date +%H:%M:%S)] SKIP:  $1 (already completed)"; }
checkpoint_failed() { echo "[$(date +%H:%M:%S)] FAIL:  $1"; exit 1; }
is_done() { [ -f "$CHECKPOINT_DIR/$1.done" ]; }
checkpoint_reset() { rm -rf "$CHECKPOINT_DIR"; mkdir -p "$CHECKPOINT_DIR"; }
"""


# ---------------------------------------------------------------------------
# Package naming
# ---------------------------------------------------------------------------

def package_name(playbook: dict, now: Optional[datetime] = None) -> str:
    """Build the phoenix package filename."""
    cell_id  = playbook.get("cell_id") or "unknown-cell"
    node     = playbook.get("target_node") or {}
    hostname = node.get("hostname") or "unknown"
    ts       = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d_%H_%M_%S")
    return f"phoenix-package-{cell_id}-{hostname}-{ts}.tar.gz"


# ---------------------------------------------------------------------------
# Assembler
# ---------------------------------------------------------------------------

def assemble_phoenix_package(
    playbook:    dict,
    output_dir:  Path,
    kdbx_path:   Optional[Path] = None,
    now:         Optional[datetime] = None,
) -> Path:
    """
    Bundle all phoenix artifacts into a self-contained tar.gz.

    Args:
        playbook:    phoenix-playbook.json dict
        output_dir:  where to write the package
        kdbx_path:   optional path to KeePass .kdbx to embed
        now:         injectable datetime for deterministic naming in tests

    Returns:
        Path to the generated .tar.gz file.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    pkg_path = output_dir / package_name(playbook, now)

    with tarfile.open(pkg_path, "w:gz") as tar:

        def _add_str(arcname: str, content: str, mode: int = 0o644):
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name=arcname)
            info.size = len(data)
            info.mode = mode
            tar.addfile(info, io.BytesIO(data))

        def _add_file(arcname: str, src: Path):
            if src.exists():
                tar.add(str(src), arcname=arcname)

        # Core playbook JSON
        _add_str("phoenix-playbook.json", json.dumps(playbook, indent=2))

        # Wave scripts + orchestrator
        if _HAS_SCRIPTS:
            waves = playbook.get("waves") or []
            for wave in sorted(waves, key=lambda w: w.get("wave", 0)):
                wave_num  = wave.get("wave", "?")
                wave_name = (wave.get("name") or "").lower().replace(" ", "-")
                script_name = f"phase-{str(wave_num).replace('.', '-')}-{wave_name}.sh"
                _add_str(script_name, generate_wave_script(wave, playbook), mode=0o755)
            _add_str("run-all.sh", generate_run_all_sh(playbook), mode=0o755)
        else:
            _add_str("run-all.sh", "#!/bin/bash\necho 'Placeholder'\n", mode=0o755)

        # Checkpoint library
        _add_str("lib/checkpoint.sh", _CHECKPOINT_SH)

        # KeePass gate
        if _HAS_KEEPASS_GATE and _PHOENIX_KEEPASS_GATE_SH:
            _add_str("lib/phoenix-keepass-gate.sh", _PHOENIX_KEEPASS_GATE_SH)

        # Human-readable manifest (mandatory per architecture)
        if _HAS_PKG_MANIFEST and _build_phoenix_manifest_html is not None:
            manifest_html = _build_phoenix_manifest_html(
                playbook,
                now_fn=lambda: (now or datetime.now(timezone.utc)).isoformat(),
            )
            _add_str("phoenix-manifest.html", manifest_html)

        # Optional phase-tracking workbook
        if _HAS_WORKBOOK and _build_phoenix_workbook_html is not None:
            wb_html = _build_phoenix_workbook_html(playbook)
            _add_str("phoenix-workbook.html", wb_html)

        # Optional KeePass database
        if kdbx_path and Path(kdbx_path).exists():
            cell_id = playbook.get("cell_id") or "cell"
            _add_file(f"kdbx/{Path(kdbx_path).name}", Path(kdbx_path))

    return pkg_path


def package_contents(pkg_path: Path) -> list[str]:
    """Return list of member names in the tar.gz package."""
    with tarfile.open(pkg_path, "r:gz") as tar:
        return [m.name for m in tar.getmembers()]
