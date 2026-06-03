#!/usr/bin/env python3
"""
assemble_spawn_package.py — Spawn package assembler (Phase 12.E.7 + 12.E.7a).

Bundles all generated spawn artifacts into a self-contained tar.gz archive
that the operator copies to the broodling and executes with `bash spawn.sh`.

Package layout:
  spawn-package-{cell_id}-{hostname}-{YYYY-MM-DD_HH_MM_SS}.tar.gz
  ├── spawn-manifest.json        reservation snapshot (what the hatchery has allocated)
  ├── spawn-plan.json            broodling-specific plan (VMIDs, IPs, disposition)
  ├── spawn.sh                   orchestrated entry point
  ├── phase-00-preflight.sh
  ├── phase-00-host.sh
  ├── phase-01-proxmox.sh
  ├── phase-02-vms.sh
  ├── phase-03-cloudinit.sh
  ├── phase-04-k3s.sh
  ├── [phase-05-ha.sh]           conditional — only when 3rd server node
  ├── phase-06-verify.sh
  ├── opentofu/
  │   └── spawn-{hostname}.auto.tfvars
  ├── cloud-init/snippets/
  │   ├── user-data/{vm}.yaml
  │   └── network-config/{vm}.yaml
  ├── ansible/
  │   ├── spawn-{hostname}.ini
  │   └── group_vars/k3s_all.yml
  ├── lib/
  │   ├── checkpoint.sh          resumable checkpoint library
  │   └── keepass-gate.sh        KeePass master password gate (12.E.7a)
  └── [kdbx/{cell_id}-*.kdbx]   optional KeePass database (if operator chose to embed)

Security: the package NEVER contains secret values. Only KeePass paths (references)
are included. The KeePass database itself is optional and only embedded if the
operator explicitly chose to include it at package generation time.

Stdlib only.
"""

import json
import tarfile
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    from html_spawn_workbook import build_spawn_workbook_html as _build_spawn_workbook_html
except ImportError:
    _build_spawn_workbook_html = None  # type: ignore

try:
    from html_package_manifest import build_spawn_manifest_html as _build_spawn_manifest_html
    _HAS_PKG_MANIFEST = True
except ImportError:
    _build_spawn_manifest_html = None  # type: ignore
    _HAS_PKG_MANIFEST = False

try:
    from spawn_scripts import (
        generate_spawn_sh,
        generate_tailscale_join_sh,
        generate_phase_00_preflight,
        generate_phase_00_host,
        generate_phase_01_proxmox,
        generate_phase_02_vms,
        generate_phase_03_cloudinit,
        generate_phase_04_k3s,
        generate_phase_05_ha,
        generate_phase_06_verify,
    )
    from spawn_iac_generator import (
        generate_tfvars,
        generate_cloudinit_user_data,
        generate_cloudinit_network_config,
        generate_ansible_inventory,
        generate_ansible_k3s_vars,
    )
    _HAS_SPAWN_GEN = True
except ImportError:
    _HAS_SPAWN_GEN = False


# ---------------------------------------------------------------------------
# KeePass unlock gate — 12.E.7a
# ---------------------------------------------------------------------------

KEEPASS_GATE_SH = """\
#!/usr/bin/env bash
# keepass-gate.sh — KeePass master password unlock gate (Phase 12.E.7a)
# Source this file and call keepass_unlock_gate() before any secrets are accessed.
# The gate runs ONCE per spawn session. After unlocking, the secrets broker
# handles all subsequent lookups without further operator input.

KDBX_PATH=""
KDBX_UNLOCKED=0

keepass_find_db() {
  # Check for embedded KeePass database first, then fall back to path
  local embedded
  embedded="$(ls "$SCRIPT_DIR"/kdbx/*.kdbx 2>/dev/null | head -1)"
  if [ -n "$embedded" ]; then
    KDBX_PATH="$embedded"
    echo "[kdbx] Using embedded database: $KDBX_PATH"
    return 0
  fi
  # Prompt for path
  read -rp "[kdbx] Enter path to KeePass database (.kdbx): " KDBX_PATH
  if [ ! -f "$KDBX_PATH" ]; then
    echo "[kdbx] File not found: $KDBX_PATH" && return 1
  fi
}

keepass_unlock_gate() {
  [ "$KDBX_UNLOCKED" -eq 1 ] && return 0   # already unlocked this session
  echo ""
  echo "================================================================="
  echo " KeePass Unlock Gate"
  echo " The master password is required once before any secrets are"
  echo " accessed. All subsequent lookups are automatic."
  echo "================================================================="
  keepass_find_db || { echo "[kdbx] Cannot locate database — aborting"; exit 1; }
  read -rsp "[kdbx] Master password: " KDBX_MASTER_PASSWORD
  echo ""
  # Export only the database path; keep the password as a shell-local variable
  # so child processes do not inherit it via their environment
  export KDBX_PATH
  KDBX_UNLOCKED=1
  echo "[kdbx] Database unlocked. Secrets broker active."
  echo ""
}

# Retrieve a secret value by KeePass path (requires keepassxc-cli)
kdbx_get() {
  local path="$1"
  if command -v keepassxc-cli &>/dev/null; then
    echo "$KDBX_MASTER_PASSWORD" | \\
      keepassxc-cli show -q -a Password "$KDBX_PATH" "$path" 2>/dev/null
  else
    echo "[kdbx] keepassxc-cli not found — retrieve '$path' manually" >&2
    echo "MANUAL_ENTRY_REQUIRED"
  fi
}
"""

CHECKPOINT_SH = """\
#!/usr/bin/env bash
# checkpoint.sh — Resumable checkpoint library for spawn scripts
# Each step calls checkpoint_start/checkpoint_done.
# If spawn.sh is re-run, completed steps are skipped automatically.

CHECKPOINT_DIR="${SCRIPT_DIR}/.checkpoints"
mkdir -p "$CHECKPOINT_DIR"

checkpoint_start()  {
  echo "[$(date +%H:%M:%S)] START: $1"
}

checkpoint_done()   {
  touch "$CHECKPOINT_DIR/$1.done"
  echo "[$(date +%H:%M:%S)] DONE:  $1"
}

checkpoint_skip()   {
  echo "[$(date +%H:%M:%S)] SKIP:  $1 (already completed)"
}

checkpoint_failed() {
  echo "[$(date +%H:%M:%S)] FAIL:  $1"
  echo "Check $SPAWN_LOG for details."
  exit 1
}

is_done() {
  [ -f "$CHECKPOINT_DIR/$1.done" ]
}

checkpoint_reset() {
  echo "[checkpoint] Resetting all checkpoints (fresh run)"
  rm -rf "$CHECKPOINT_DIR"
  mkdir -p "$CHECKPOINT_DIR"
}
"""


# ---------------------------------------------------------------------------
# Package naming
# ---------------------------------------------------------------------------

def _package_name(plan: dict, now: Optional[datetime] = None) -> str:
    cell_id  = plan.get("cell_id", "unknown-cell")
    hostname = plan.get("hostname", "unknown")
    ts       = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d_%H_%M_%S")
    return f"spawn-package-{cell_id}-{hostname}-{ts}.tar.gz"


# ---------------------------------------------------------------------------
# Assembler
# ---------------------------------------------------------------------------

def assemble_spawn_package(
    plan: dict,
    manifest: dict,
    artifacts_dir: Optional[Path] = None,
    output_dir: Path = Path("."),
    kdbx_path: Optional[Path] = None,
    hardware_profile: Optional[dict] = None,
    now: Optional[datetime] = None,
) -> Path:
    """
    Bundle all spawn artifacts into a self-contained tar.gz.

    Args:
        plan:             spawn-plan.json dict
        manifest:         spawn-manifest.json dict (hatchery state / bootstrap-state.json)
        artifacts_dir:    optional directory with pre-generated artifacts
                          (opentofu/, cloud-init/, ansible/, phase-*.sh, spawn.sh).
                          If None, all scripts are generated internally from plan.
        output_dir:       where to write the package (default: current directory)
        kdbx_path:        optional path to KeePass .kdbx to embed in package
        hardware_profile: optional hardware-profile dict to embed in workbook
        now:              injectable datetime for deterministic naming in tests

    Returns:
        Path to the generated .tar.gz file.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    pkg_name = _package_name(plan, now)
    pkg_path = output_dir / pkg_name

    with tarfile.open(pkg_path, "w:gz") as tar:

        def _add_str(arcname: str, content: str, mode: int = 0o644):
            """Add a string as a file in the archive."""
            data  = content.encode("utf-8")
            info  = tarfile.TarInfo(name=arcname)
            info.size = len(data)
            info.mode = mode
            tar.addfile(info, io.BytesIO(data))

        def _add_file(arcname: str, src: Path):
            """Add an existing file to the archive."""
            if src.exists():
                tar.add(src, arcname=arcname)

        def _add_dir(src_dir: Path, arc_prefix: str):
            """Recursively add all files from src_dir to arc_prefix/."""
            if not src_dir.exists():
                return
            for f in sorted(src_dir.rglob("*")):
                if f.is_file():
                    rel = f.relative_to(src_dir)
                    tar.add(f, arcname=f"{arc_prefix}/{rel}")

        # Core JSON manifests
        _add_str("spawn-manifest.json", json.dumps(manifest, indent=2))
        _add_str("spawn-plan.json",     json.dumps(plan, indent=2))

        # Library scripts (checkpoint + KeePass gate)
        _add_str("lib/checkpoint.sh",    CHECKPOINT_SH)
        _add_str("lib/keepass-gate.sh",  KEEPASS_GATE_SH)

        if artifacts_dir is not None:
            # Use pre-generated artifacts from disk
            artifacts_dir = Path(artifacts_dir)
            for script in sorted(artifacts_dir.glob("*.sh")):
                tar.add(script, arcname=script.name)
            _add_dir(artifacts_dir / "opentofu",   "opentofu")
            _add_dir(artifacts_dir / "cloud-init", "cloud-init")
            _add_dir(artifacts_dir / "ansible",    "ansible")
        elif _HAS_SPAWN_GEN:
            # Generate all scripts and IaC internally from plan (preferred path)
            k3s_role  = (plan.get("k3s") or {}).get("role", "worker")
            is_ha     = k3s_role == "server" and bool(plan.get("vms"))
            is_wan    = (plan.get("disposition") or {}).get("network_mode") == "wan"
            _add_str("spawn.sh",              generate_spawn_sh(plan, include_wan_phase=is_wan), mode=0o755)
            if is_wan:
                _add_str("tailscale-join.sh", generate_tailscale_join_sh(plan),    mode=0o755)
            _add_str("phase-00-preflight.sh", generate_phase_00_preflight(plan),   mode=0o755)
            _add_str("phase-00-host.sh",      generate_phase_00_host(plan),        mode=0o755)
            _add_str("phase-01-proxmox.sh",   generate_phase_01_proxmox(plan),     mode=0o755)
            _add_str("phase-02-vms.sh",       generate_phase_02_vms(plan),         mode=0o755)
            _add_str("phase-03-cloudinit.sh", generate_phase_03_cloudinit(plan),   mode=0o755)
            _add_str("phase-04-k3s.sh",       generate_phase_04_k3s(plan),         mode=0o755)
            if is_ha:
                _add_str("phase-05-ha.sh",    generate_phase_05_ha(plan),          mode=0o755)
            _add_str("phase-06-verify.sh",    generate_phase_06_verify(plan),      mode=0o755)
            # IaC artifacts
            hostname = plan.get("hostname", "unknown")
            _add_str(f"opentofu/spawn-{hostname}.auto.tfvars", generate_tfvars(plan))
            for vm in (plan.get("vms") or []):
                vm_name = vm.get("name", "vm")
                _add_str(f"cloud-init/snippets/user-data/{vm_name}.yaml",
                         generate_cloudinit_user_data(vm, plan))
                _add_str(f"cloud-init/snippets/network-config/{vm_name}.yaml",
                         generate_cloudinit_network_config(vm, plan))
            _add_str(f"ansible/spawn-{hostname}.ini", generate_ansible_inventory(plan))
            _add_str("ansible/group_vars/k3s_all.yml", generate_ansible_k3s_vars(plan))

        # Human-readable package manifest (architecture requirement)
        if _HAS_PKG_MANIFEST and _build_spawn_manifest_html is not None:
            pkg_html = _build_spawn_manifest_html(
                manifest, plan,
                now_fn=lambda: (now or datetime.now(timezone.utc)).isoformat(),
            )
            _add_str("spawn-manifest.html", pkg_html)

        # Spawn workbook (HTML)
        if _build_spawn_workbook_html is not None:
            wb_html  = _build_spawn_workbook_html(plan, manifest, hardware_profile)
            wb_bytes = wb_html.encode("utf-8")
            hostname = plan.get("hostname", "broodling")
            ts       = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d_%H_%M_%S")
            wb_name  = f"spawn-workbook-{hostname}-{ts}.html"
            wb_info  = tarfile.TarInfo(name=wb_name)
            wb_info.size = len(wb_bytes)
            tar.addfile(wb_info, io.BytesIO(wb_bytes))

        # Optional KeePass database
        if kdbx_path and Path(kdbx_path).exists():
            hostname = plan.get("hostname", "broodling")
            _add_file(f"kdbx/{Path(kdbx_path).name}", Path(kdbx_path))

    return pkg_path


def package_contents(pkg_path: Path) -> list[str]:
    """Return list of member names in the tar.gz package."""
    with tarfile.open(pkg_path, "r:gz") as tar:
        return [m.name for m in tar.getmembers()]
