#!/usr/bin/env python3
"""
assemble_forge_package.py — Forge package assembler (Phase 1.F.1).

Bundles all forge artifacts into a self-contained tar.gz archive that an
operator downloads and runs on bare Proxmox hardware to forge the first
broodforge hatchery.

Package layout:
  forge-package-{cell_id}-{YYYY-MM-DD_HH_MM_SS}.tar.gz
  ├── forge-manifest.json         cell identity snapshot
  ├── forge.sh                    orchestrated entry point
  ├── phase-00-discover.sh
  ├── phase-01-plan.sh
  ├── phase-02-validate.sh
  ├── phase-03-host.sh
  ├── phase-04-vms.sh
  ├── phase-05-k3s.sh
  ├── phase-06-gitops.sh
  ├── phase-07-intelligence.sh
  ├── phase-08-verify.sh
  ├── lib/
  │   ├── checkpoint.sh
  │   ├── forge-keepass-gate.sh
  │   └── pve-suppress-nag.sh
  ├── forge-workbook.html         HTML workbook for forge tracking
  ├── proxmox-bootstrap/          library code (planners, validators, setup scripts)
  ├── data-model/                 JSON schemas
  ├── doc-gen/                    documentation engine
  └── [kdbx/{cell_id}-*.kdbx]    optional — embedded KeePass database

Security: the package NEVER contains secret values. Only KeePass paths (references)
are included. The KeePass database is optional and only embedded if the operator
chose to at planning time.

Stdlib only.
"""

import io
import json
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    from html_forge_workbook import build_forge_workbook_html as _build_forge_workbook_html
    _HAS_WORKBOOK = True
except ImportError:
    _build_forge_workbook_html = None  # type: ignore
    _HAS_WORKBOOK = False

try:
    from html_package_manifest import build_forge_manifest_html as _build_forge_manifest_html
    _HAS_PKG_MANIFEST = True
except ImportError:
    _build_forge_manifest_html = None  # type: ignore
    _HAS_PKG_MANIFEST = False

try:
    from forge_scripts import (
        FORGE_CHECKPOINT_SH, FORGE_KEEPASS_GATE_SH,
        generate_forge_sh,
        generate_phase_00_sh, generate_phase_01_sh, generate_phase_02_sh,
        generate_phase_03_sh, generate_phase_04_sh, generate_phase_05_sh,
        generate_phase_06_sh, generate_phase_07_sh, generate_phase_08_sh,
    )
    _HAS_SCRIPTS = True
except ImportError:
    _HAS_SCRIPTS = False


# ---------------------------------------------------------------------------
# pve-suppress-nag.sh (embedded literal — avoids reading from lib/ at build time)
# ---------------------------------------------------------------------------

_PVE_NAG_SH = """\
#!/usr/bin/env bash
# pve-suppress-nag.sh — Remove Proxmox subscription popup (AD-046).
# See lib/pve-suppress-nag.sh for full version with dpkg hook install.
set -euo pipefail
PROXMOX_LIB="/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js"
MARKER="# broodforge-nag-suppressed"
[ ! -f "$PROXMOX_LIB" ] && { echo "[nag] $PROXMOX_LIB not found."; exit 0; }
grep -q "$MARKER" "$PROXMOX_LIB" && { echo "[nag] Already patched."; exit 0; }
sed -i 's/if\\s*(data\\.status\\s*!==\\s*\\'Active\\')/if (false) \\/\\/ nag-suppressed/g' "$PROXMOX_LIB"
echo "$MARKER" >> "$PROXMOX_LIB"
systemctl restart pveproxy 2>/dev/null || true
echo "[nag] Patched."
"""


# ---------------------------------------------------------------------------
# Package naming
# ---------------------------------------------------------------------------

def package_name(manifest: dict, now: Optional[datetime] = None) -> str:
    """Build the forge package filename."""
    cell_id = manifest.get("cell_id") or "unknown-cell"
    ts      = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d_%H_%M_%S")
    return f"forge-package-{cell_id}-{ts}.tar.gz"


# ---------------------------------------------------------------------------
# Content listing (for inspection / testing)
# ---------------------------------------------------------------------------

def package_contents(
    manifest:          dict,
    hardware_profile:  Optional[dict] = None,
    embed_kdbx:        bool = False,
    repo_dir:          Optional[Path] = None,
) -> list[str]:
    """
    Return the list of archive member paths that will be in the package.

    repo_dir: path to the broodforge repo (for enumerating library code).
    If None, only the generated script/manifest names are listed.
    """
    items = [
        "forge-manifest.json",
        "forge.sh",
        "phase-00-discover.sh",
        "phase-01-plan.sh",
        "phase-02-validate.sh",
        "phase-03-host.sh",
        "phase-04-vms.sh",
        "phase-05-k3s.sh",
        "phase-06-gitops.sh",
        "phase-07-intelligence.sh",
        "phase-08-verify.sh",
        "lib/checkpoint.sh",
        "lib/forge-keepass-gate.sh",
        "lib/pve-suppress-nag.sh",
        "forge-workbook.html",
        "forge-manifest.html",
    ]
    if embed_kdbx:
        cell_id = manifest.get("cell_id") or "cell"
        items.append(f"kdbx/{cell_id}.kdbx")
    return items


# ---------------------------------------------------------------------------
# Assembler
# ---------------------------------------------------------------------------

def assemble_forge_package(
    manifest:          dict,
    output_dir:        Path,
    repo_dir:          Optional[Path] = None,
    kdbx_path:         Optional[Path] = None,
    hardware_profile:  Optional[dict] = None,
    validation_findings: Optional[list] = None,
    now:               Optional[datetime] = None,
) -> Path:
    """
    Bundle all forge artifacts into a self-contained tar.gz.

    Args:
        manifest:             forge-manifest.json dict
        output_dir:           where to write the package
        repo_dir:             path to broodforge repo (to include library code)
        kdbx_path:            optional path to KeePass .kdbx to embed
        hardware_profile:     hardware profile dict (for workbook)
        validation_findings:  forge validator findings (for workbook)
        now:                  injectable datetime (for tests)

    Returns:
        Path to the generated .tar.gz file.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    pkg_path = output_dir / package_name(manifest, now)

    with tarfile.open(pkg_path, "w:gz") as tar:

        def _add_str(arcname: str, content: str, mode: int = 0o644):
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name=arcname)
            info.size = len(data)
            info.mode = mode
            tar.addfile(info, io.BytesIO(data))

        def _add_bytes(arcname: str, data: bytes, mode: int = 0o644):
            info = tarfile.TarInfo(name=arcname)
            info.size = len(data)
            info.mode = mode
            tar.addfile(info, io.BytesIO(data))

        def _add_file(arcname: str, src: Path, mode: int = 0o644):
            if src.exists():
                tar.add(str(src), arcname=arcname)

        def _add_dir(src_dir: Path, arc_prefix: str):
            if not src_dir.exists():
                return
            for f in sorted(src_dir.rglob("*")):
                if f.is_file() and not any(
                    part.startswith(".") for part in f.parts
                ):
                    rel = f.relative_to(src_dir)
                    tar.add(str(f), arcname=f"{arc_prefix}/{rel}")

        # Core manifest
        _add_str("forge-manifest.json", json.dumps(manifest, indent=2))

        # Generated scripts
        if _HAS_SCRIPTS:
            _add_str("forge.sh",                 generate_forge_sh(manifest),         mode=0o755)
            _add_str("phase-00-discover.sh",     generate_phase_00_sh(manifest),      mode=0o755)
            _add_str("phase-01-plan.sh",         generate_phase_01_sh(manifest),      mode=0o755)
            _add_str("phase-02-validate.sh",     generate_phase_02_sh(manifest),      mode=0o755)
            _add_str("phase-03-host.sh",         generate_phase_03_sh(manifest),      mode=0o755)
            _add_str("phase-04-vms.sh",          generate_phase_04_sh(manifest),      mode=0o755)
            _add_str("phase-05-k3s.sh",          generate_phase_05_sh(manifest),      mode=0o755)
            _add_str("phase-06-gitops.sh",       generate_phase_06_sh(manifest),      mode=0o755)
            _add_str("phase-07-intelligence.sh", generate_phase_07_sh(manifest),      mode=0o755)
            _add_str("phase-08-verify.sh",       generate_phase_08_sh(manifest),      mode=0o755)
            _add_str("lib/checkpoint.sh",        FORGE_CHECKPOINT_SH)
            _add_str("lib/forge-keepass-gate.sh", FORGE_KEEPASS_GATE_SH)
        else:
            _add_str("forge.sh", "#!/bin/bash\necho 'Placeholder'\n", mode=0o755)

        # pve-suppress-nag.sh
        _add_str("lib/pve-suppress-nag.sh", _PVE_NAG_SH, mode=0o755)

        # Forge workbook (HTML)
        if _HAS_WORKBOOK:
            wb_html = _build_forge_workbook_html(manifest, hardware_profile, validation_findings)
            _add_str("forge-workbook.html", wb_html)

        # Human-readable package manifest (architecture requirement)
        if _HAS_PKG_MANIFEST:
            manifest_html = _build_forge_manifest_html(manifest, now_fn=lambda: (now or datetime.now(timezone.utc)).isoformat())
            _add_str("forge-manifest.html", manifest_html)

        # Optional KeePass database
        if kdbx_path and Path(kdbx_path).exists():
            cell_id = manifest.get("cell_id") or "cell"
            _add_file(f"kdbx/{cell_id}.kdbx", Path(kdbx_path))

        # Include library code from repo (if repo_dir provided)
        if repo_dir:
            repo_dir = Path(repo_dir)
            # proxmox-bootstrap Python modules
            pb_dir = repo_dir / "proxmox-bootstrap"
            if pb_dir.exists():
                for pyf in sorted(pb_dir.glob("*.py")):
                    tar.add(str(pyf), arcname=f"proxmox-bootstrap/{pyf.name}")
                for yamlf in sorted(pb_dir.glob("*.yaml")):
                    tar.add(str(yamlf), arcname=f"proxmox-bootstrap/{yamlf.name}")
            # data-model schemas
            dm_dir = repo_dir / "data-model"
            if dm_dir.exists():
                _add_dir(dm_dir, "data-model")
            # doc-gen engine
            dg_dir = repo_dir / "doc-gen"
            if dg_dir.exists():
                _add_dir(dg_dir, "doc-gen")
            # Ansible roles + playbooks (forge VM + k3s configuration). phase-05
            # references ansible/playbooks/04-k3s.yaml and ansible/inventory/.
            ans_dir = repo_dir / "ansible"
            if ans_dir.exists():
                _add_dir(ans_dir, "ansible")
            # IaC generators (produce opentofu tfvars + ansible inventory from
            # plans). proxmox-bootstrap/*.py is bundled non-recursively above, so
            # the generators/ subpackage must be added explicitly.
            gen_dir = repo_dir / "proxmox-bootstrap" / "generators"
            if gen_dir.exists():
                _add_dir(gen_dir, "proxmox-bootstrap/generators")

    return pkg_path
