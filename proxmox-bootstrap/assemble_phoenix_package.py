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
        PHOENIX_KEEPASS_GATE_SH as _PHOENIX_KEEPASS_GATE_SH,
    )
    from phoenix_scripts import (
        generate_run_all_sh,
        generate_wave_script,
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
            playbook.get("cell_id") or "cell"
            _add_file(f"kdbx/{Path(kdbx_path).name}", Path(kdbx_path))

    return pkg_path


def package_contents(pkg_path: Path) -> list[str]:
    """Return list of member names in the tar.gz package."""
    with tarfile.open(pkg_path, "r:gz") as tar:
        return [m.name for m in tar.getmembers()]


# ---------------------------------------------------------------------------
# Pack-from-state helpers
# ---------------------------------------------------------------------------

def _load_version_from(version_py: Path) -> str:
    """Load SCHEMA_VERSION from version.py; return a zeroed fallback if absent."""
    import importlib.util
    import warnings as _warnings

    _DEFAULT = "0000-00-00_00-00-00_0000000"  # noqa: N806
    try:
        spec = importlib.util.spec_from_file_location("_broodforge_ver", version_py)
        if spec is not None and spec.loader is not None:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            return str(mod.SCHEMA_VERSION)
    except FileNotFoundError:
        pass
    except Exception as exc:
        _warnings.warn(f"Cannot load SCHEMA_VERSION from {version_py}: {exc}", stacklevel=2)
    return _DEFAULT


def _tar_add_str(tar: tarfile.TarFile, arcname: str, content: str, mode: int = 0o644) -> None:
    """Add a UTF-8 string as a file inside *tar*."""
    data = content.encode("utf-8")
    info = tarfile.TarInfo(name=arcname)
    info.size = len(data)
    info.mode = mode
    tar.addfile(info, io.BytesIO(data))


def pack_state(
    state_dir: Path,
    output: Path,
    repo_root: Path,
    *,
    now: Optional[datetime] = None,
) -> Path:
    """
    Assemble a phoenix recovery package from the current deployment state.

    This is the "pack from current state" path — no pre-generated playbook
    required. The resulting archive contains everything an operator needs to
    rebuild the deployment from scratch after catastrophic failure.

    Package layout::

        <timestamp>.tar.gz
        ├── phoenix-manifest.json        (packed_at, schema_version, hostname, …)
        ├── manifest.toml                (deployment configuration)
        ├── bootstrap-state.json         (current forge state)
        ├── package-descriptor.json      (package integrity descriptor)
        ├── state-descriptor.json        (state integrity descriptor)
        ├── proxmox-bootstrap/
        │   └── version.py               (current schema version file)
        └── migrations/                  (migration history — all files)

    Missing source files are skipped with a stderr warning; the pack is
    never aborted due to a missing optional file.

    Parameters
    ----------
    state_dir   : directory containing manifest.toml / bootstrap-state.json
    output      : full path for the .tar.gz (parent dir is created if needed)
    repo_root   : repo root (parent of proxmox-bootstrap/, migrations/, …)
    now         : injectable datetime for deterministic timestamps in tests

    Returns
    -------
    Path to the generated archive (same as *output*).
    """
    import socket
    import sys as _sys

    if now is None:
        now = datetime.now(timezone.utc)

    version_py = repo_root / "proxmox-bootstrap" / "version.py"
    schema_version = _load_version_from(version_py)

    manifest: dict = {
        "packed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "schema_version": schema_version,
        "hostname": socket.gethostname(),
        "broodforge_version": schema_version,
    }

    output.parent.mkdir(parents=True, exist_ok=True)

    with tarfile.open(output, "w:gz") as tar:

        def _add_file_opt(arcname: str, src: Path) -> None:
            """Add *src* as *arcname*; warn and skip if the file is missing."""
            if src.exists():
                tar.add(str(src), arcname=arcname)
            else:
                print(
                    f"[pack] WARNING: {src} not found — skipping {arcname}",
                    file=_sys.stderr,
                )

        # phoenix-manifest.json — always first so --list can read it quickly
        _tar_add_str(tar, "phoenix-manifest.json",
                     json.dumps(manifest, indent=2) + "\n")

        # State files (optional — skip with warning if absent)
        _add_file_opt("manifest.toml",       state_dir / "manifest.toml")
        _add_file_opt("bootstrap-state.json", state_dir / "bootstrap-state.json")

        # Integrity descriptors from proxmox-bootstrap/
        pb_dir = repo_root / "proxmox-bootstrap"
        _add_file_opt("package-descriptor.json", pb_dir / "package-descriptor.json")
        _add_file_opt("state-descriptor.json",   pb_dir / "state-descriptor.json")

        # Schema-version file
        _add_file_opt("proxmox-bootstrap/version.py", version_py)

        # migrations/ directory — full copy preserves migration history
        migrations_dir = repo_root / "migrations"
        if migrations_dir.exists():
            for p in sorted(migrations_dir.rglob("*")):
                if p.is_file():
                    arcname = "migrations/" + str(p.relative_to(migrations_dir))
                    tar.add(str(p), arcname=arcname)
        else:
            print(
                "[pack] WARNING: migrations/ directory not found — skipping",
                file=_sys.stderr,
            )

    return output


def read_phoenix_manifest(pkg_path: Path) -> dict:
    """
    Read and return the phoenix-manifest.json from a packed archive.

    Raises
    ------
    KeyError  : if phoenix-manifest.json is absent from the archive
    ValueError: if the JSON cannot be parsed
    """
    with tarfile.open(pkg_path, "r:gz") as tar:
        member = tar.getmember("phoenix-manifest.json")
        f = tar.extractfile(member)
        if f is None:
            raise ValueError("Cannot extract phoenix-manifest.json from archive")
        return json.loads(f.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# CLI — standalone "pack current state" and "list package" entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys

    ap = argparse.ArgumentParser(
        description="Phoenix package assembler — current-state pack / inspect",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  # Pack current state to the default output directory:\n"
            "  python3 assemble_phoenix_package.py --pack\n\n"
            "  # Pack with custom directories:\n"
            "  python3 assemble_phoenix_package.py --pack \\\n"
            "      --state-dir /var/lib/broodforge \\\n"
            "      --output /mnt/usb/phoenix-2026-06-09.tar.gz\n\n"
            "  # Inspect a previously packed archive:\n"
            "  python3 assemble_phoenix_package.py --list /var/lib/broodforge/phoenix/2026-06-09.tar.gz\n"
        ),
    )
    mode_group = ap.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--pack", action="store_true",
        help="Assemble a phoenix recovery package from the current deployment state",
    )
    mode_group.add_argument(
        "--list", metavar="PACKAGE",
        help="Print the phoenix-manifest.json contents of a packed archive",
    )
    ap.add_argument(
        "--state-dir", default="/var/lib/broodforge",
        help="Directory containing manifest.toml / bootstrap-state.json "
             "(default: /var/lib/broodforge)",
    )
    ap.add_argument(
        "--output", default=None,
        help="Output path for the .tar.gz "
             "(default: <state-dir>/phoenix/<timestamp>.tar.gz)",
    )
    ap.add_argument(
        "--repo-root", default=None,
        help="Repository root (default: parent of this script's directory)",
    )
    args = ap.parse_args()

    _repo_root = (
        Path(args.repo_root)
        if args.repo_root is not None
        else Path(__file__).parent.parent
    )

    if args.pack:
        _state_dir = Path(args.state_dir)
        _now = datetime.now(timezone.utc)
        _ts = _now.strftime("%Y-%m-%d_%H-%M-%S")

        if args.output is not None:
            _output = Path(args.output)
        else:
            _output = _state_dir / "phoenix" / f"{_ts}.tar.gz"

        print("[pack] Assembling phoenix recovery package ...", file=sys.stderr)
        print(f"[pack]   state-dir : {_state_dir}", file=sys.stderr)
        print(f"[pack]   output    : {_output}", file=sys.stderr)

        _pkg = pack_state(
            state_dir=_state_dir,
            output=_output,
            repo_root=_repo_root,
            now=_now,
        )
        # Print only the path on stdout so forge-phoenix-pack.sh can capture it
        print(_pkg)
        sys.exit(0)

    if args.list:
        _pkg_path = Path(args.list)
        if not _pkg_path.exists():
            print(f"[list] ERROR: package not found: {_pkg_path}", file=sys.stderr)
            sys.exit(1)
        try:
            _manifest = read_phoenix_manifest(_pkg_path)
        except (KeyError, ValueError, OSError) as _exc:
            print(f"[list] ERROR: cannot read manifest: {_exc}", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(_manifest, indent=2))
        sys.exit(0)
