#!/usr/bin/env python3
"""
failure_package_analyzer.py — Phase-aware failure package analyzer.

When a spawn script phase fails on the broodling, a failure package is
created containing:
  failure-report.json   — structured failure data (phase, error, diagnostics)
  spawn-plan.json       — original spawn plan
  spawn-manifest.json   — hatchery reservation manifest
  hardware-profile.json — detected hardware (if available)
  logs/spawn-*.log      — captured log output
  checkpoints/          — checkpoint state (which phases completed)

The failure package is exported via USB or network (if the broodling
established connectivity to the hatchery), received by the hatchery
receiver, and analyzed here.

The analyzer:
  1. Identifies which phase failed and the root error category
  2. Generates a human-readable diagnosis
  3. Suggests specific, actionable fixes
  4. Determines whether broodforge can auto-regenerate a corrected package

Provides:
  FailureReport          — parsed failure report
  FailureDiagnosis       — analysis result with fixes + regeneration guidance
  analyze_failure_report() — analyze from parsed failure-report.json dict
  analyze_failure_package() — analyze from a tar.gz bundle path
  export_to_usb()        — copy package to USB mount point
  export_to_hatchery()   — POST package to hatchery receiver
  FAILURE_SHELL_FUNCTIONS — bash library: generate_failure_package()
  PHASE_DIAGNOSTICS      — phase-to-error-category mapping

Stdlib only.
"""

import io
import json
import os
import tarfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Phase catalogue — what each phase does and what failure means
# ---------------------------------------------------------------------------

PHASE_CATALOGUE: dict[str, dict] = {
    "phase-00-preflight": {
        "description": "Hardware pre-flight (read-only scan)",
        "error_categories": {
            "disk_missing":        "One or more planned disk IDs not found on this host.",
            "nic_renamed":         "NIC names changed since hardware discovery (kernel update or hardware change).",
            "ram_insufficient":    "Available RAM is less than planned VMs require.",
            "zfs_pool_conflict":   "An existing ZFS pool name conflicts with the planned pool.",
            "bridge_conflict":     "An existing network bridge name conflicts with the planned bridge.",
            "stale_manifest":      "Spawn manifest is stale — hatchery reserved additional resources since package was built.",
            "vmid_conflict":       "One or more planned VMIDs are now in use on the hatchery.",
            "ip_conflict":         "One or more planned IPs are now in use.",
        },
    },
    "phase-00-host": {
        "description": "Host configuration (bridge/ZFS/hostname)",
        "error_categories": {
            "bridge_failed":       "Failed to create network bridge (ifreload -a error).",
            "zfs_pool_failed":     "Failed to create ZFS pool (disk error or topology mismatch).",
            "hostname_failed":     "Failed to set hostname or /etc/hosts.",
            "pvesm_failed":        "Failed to register ZFS pool as Proxmox datastore.",
        },
    },
    "phase-01-proxmox": {
        "description": "Proxmox cluster join",
        "error_categories": {
            "join_fingerprint":    "Cluster fingerprint mismatch — hatchery cluster identity changed.",
            "join_unreachable":    "Hatchery Proxmox cluster address unreachable from broodling.",
            "join_auth":           "Proxmox cluster join authentication failed.",
            "join_timeout":        "pvecm add timed out — network congestion or cluster overloaded.",
        },
    },
    "phase-02-vms": {
        "description": "VM provisioning (tofu apply)",
        "error_categories": {
            "vmid_taken":          "VMID(s) were claimed by another spawn between package generation and execution.",
            "disk_full":           "Insufficient storage space on ZFS pool for VM disks.",
            "tofu_api_error":      "Proxmox API error during OpenTofu apply.",
            "template_missing":    "VM template (base image) not found on this host.",
            "tofu_timeout":        "tofu apply timed out — cluster congested or API unresponsive.",
        },
    },
    "phase-03-cloudinit": {
        "description": "Cloud-Init snippets + VM startup",
        "error_categories": {
            "snippet_upload":      "Failed to upload Cloud-Init snippet to Proxmox snippet store.",
            "vm_boot_timeout":     "VM did not reach SSH-ready state within the wait window.",
            "cloud_init_error":    "Cloud-Init reported an error during first boot.",
            "network_config":      "VM network configuration incorrect — SSH unreachable.",
        },
    },
    "phase-04-k3s": {
        "description": "k3s cluster join (Ansible)",
        "error_categories": {
            "token_expired":       "k3s join token has expired — tokens rotate after a node joins.",
            "ansible_unreachable": "Ansible cannot reach VM via SSH — check VM IP and network config.",
            "k3s_join_failed":     "k3s join failed — cluster may be unhealthy or token invalid.",
            "tls_cert_error":      "k3s TLS certificate error — check cluster time sync.",
        },
    },
    "phase-05-ha": {
        "description": "SQLite → etcd HA promotion (3rd control-plane only)",
        "error_categories": {
            "etcd_migration":      "etcd migration failed — cluster quiescing issue.",
            "not_third_server":    "HA phase ran but this is not the 3rd k3s server node.",
            "etcd_timeout":        "etcd promotion timed out — check cluster connectivity.",
        },
    },
    "phase-06-verify": {
        "description": "Post-spawn cluster health check",
        "error_categories": {
            "nodes_not_ready":     "k3s nodes not all in Ready state after spawn.",
            "vms_not_running":     "One or more VMs did not reach running state.",
            "flux_not_reconciled": "Flux CD did not reconcile within the wait window.",
        },
    },
}


# ---------------------------------------------------------------------------
# Fix suggestions for each error category
# ---------------------------------------------------------------------------

_FIX_SUGGESTIONS: dict[str, list[str]] = {
    "disk_missing": [
        "Verify all planned disks are physically attached to the broodling.",
        "Check disk IDs with: lsblk -do NAME,SERIAL,SIZE,TYPE",
        "Re-run hardware discovery on the hatchery and regenerate the spawn package.",
    ],
    "nic_renamed": [
        "Verify NIC names with: ip -br link",
        "If NICs were renumbered by a kernel update, run hardware discovery again.",
        "Re-run hardware discovery on the hatchery and regenerate the spawn package.",
    ],
    "ram_insufficient": [
        "Check available RAM: free -h",
        "Reduce VM RAM allocations in the spawn plan and regenerate the package.",
        "Or accept reduced service set (fewer VMs on this broodling).",
    ],
    "stale_manifest": [
        "The spawn manifest is outdated — the hatchery has reserved more resources since it was built.",
        "Re-run spawn-planner.py on the hatchery and regenerate the spawn package.",
    ],
    "vmid_conflict": [
        "A VMID conflict was detected — another spawn occurred since this package was built.",
        "Re-run spawn-planner.py on the hatchery to get a fresh non-conflicting VMID block.",
        "Regenerate the spawn package with the new VMID allocation.",
    ],
    "ip_conflict": [
        "An IP address conflict was detected — re-run spawn-planner.py to allocate fresh IPs.",
        "Regenerate Cloud-Init snippets with the corrected IPs.",
    ],
    "bridge_failed": [
        "Check /etc/network/interfaces for syntax errors.",
        "Verify NIC names match plan: ip -br link",
        "Try: ifreload -a && ip link show",
    ],
    "zfs_pool_failed": [
        "Check disk availability: lsblk -do NAME,SIZE",
        "Ensure no existing pool with same name: zpool list",
        "Check for disk errors: dmesg | tail -20",
    ],
    "join_fingerprint": [
        "The hatchery Proxmox cluster fingerprint changed — regenerate the spawn package.",
        "Get current fingerprint: pvecm status | grep fingerprint",
    ],
    "join_unreachable": [
        "Check network connectivity: ping <hatchery-ip>",
        "Verify Proxmox port 8006 and 2222 are reachable.",
        "Check firewall rules on both hatchery and broodling.",
    ],
    "vmid_taken": [
        "VMIDs were claimed by another spawn — this is a race condition.",
        "Re-run spawn-planner.py on the hatchery and regenerate with a fresh VMID block.",
    ],
    "disk_full": [
        "Check ZFS pool usage: zpool list && zfs list",
        "Free space on the pool or provision a larger disk.",
        "Reduce VM disk sizes in the spawn plan and regenerate.",
    ],
    "template_missing": [
        "Download and install the required VM template on this host.",
        "Check template availability: qm list | grep template",
        "Run the template rebuild phase from a phoenix playbook.",
    ],
    "snippet_upload": [
        "Verify Proxmox snippet store is configured: pvesm status",
        "Check that /var/lib/vz/snippets/ is writable.",
    ],
    "vm_boot_timeout": [
        "Check VM console: qm terminal <vmid>",
        "Check Cloud-Init log: journalctl -b -u cloud-init",
        "Verify network-config snippet has correct IPs.",
    ],
    "token_expired": [
        "k3s join tokens expire after use or timeout.",
        "Regenerate join tokens on the hatchery: k3s token create",
        "Update bootstrap-state.json with new tokens and regenerate the spawn package.",
    ],
    "ansible_unreachable": [
        "Confirm VM SSH is reachable: ssh ubuntu@<vm-ip> 'echo ok'",
        "Check Cloud-Init completed: qm guest exec <vmid> -- cloud-init status",
        "Verify the correct SSH key is available.",
    ],
    "nodes_not_ready": [
        "Check k3s node status: kubectl get nodes",
        "Check k3s service: systemctl status k3s",
        "Review k3s logs: journalctl -u k3s --since '10 minutes ago'",
    ],
    "vms_not_running": [
        "Check VM status: qm list",
        "Check VM console for errors: qm terminal <vmid>",
        "Check Proxmox task log: pvesh get /nodes/<node>/tasks",
    ],
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class FailureReport:
    """Parsed failure-report.json from inside a failure package."""
    package_id:       str
    broodling_host:   str
    failed_phase:     str
    error_message:    str
    error_type:       str = "unknown"
    cell_id:          Optional[str] = None
    failed_at:        Optional[str] = None
    spawn_plan_id:    Optional[str] = None
    diagnostics:      dict = field(default_factory=dict)
    completed_phases: list[str] = field(default_factory=list)
    log_excerpt:      Optional[str] = None


@dataclass
class FailureDiagnosis:
    """Complete analysis result from the failure package analyzer."""
    package_id:          str
    broodling_host:      str
    failed_phase:        str
    phase_description:   str
    error_type:          str
    diagnosis:           str
    suggested_fixes:     list[str] = field(default_factory=list)
    completed_phases:    list[str] = field(default_factory=list)
    can_regenerate:      bool = False
    regeneration_steps:  list[str] = field(default_factory=list)
    analyzed_at:         Optional[str] = None

    def summary_lines(self) -> list[str]:
        lines = [
            f"Failure Package Analysis — {self.package_id}",
            f"Broodling: {self.broodling_host}",
            f"Failed phase: {self.failed_phase} — {self.phase_description}",
            f"Error type: {self.error_type}",
            f"Diagnosis: {self.diagnosis}",
            "",
            "Completed before failure: " + (
                ", ".join(self.completed_phases) if self.completed_phases else "(none)"
            ),
            "",
            "Suggested fixes:",
        ]
        for i, fix in enumerate(self.suggested_fixes, 1):
            lines.append(f"  {i}. {fix}")
        if self.can_regenerate:
            lines.append("")
            lines.append("Regeneration: broodforge can regenerate a corrected package.")
            for step in self.regeneration_steps:
                lines.append(f"  → {step}")
        return lines

    def to_markdown(self) -> str:
        return "\n".join(self.summary_lines())


# ---------------------------------------------------------------------------
# Regeneration steps for each error category
# ---------------------------------------------------------------------------

_REGEN_STEPS: dict[str, tuple[bool, list[str]]] = {
    # (can_regenerate, steps)
    "disk_missing":      (False, ["Re-discover hardware and regenerate spawn package."]),
    "nic_renamed":       (False, ["Re-discover hardware and regenerate spawn package."]),
    "ram_insufficient":  (True,  [
        "spawn-planner.py --reduce-vms: remove VMs until RAM fits",
        "Regenerate spawn package with reduced VM set",
    ]),
    "stale_manifest":    (True,  [
        "spawn-planner.py: re-read hatchery state (new reservation snapshot)",
        "Regenerate spawn package with fresh manifest",
    ]),
    "vmid_conflict":     (True,  [
        "spawn-planner.py: allocate next available VMID block",
        "Regenerate spawn package with new VMID assignments",
        "Update Cloud-Init snippets with new VMIDs",
    ]),
    "ip_conflict":       (True,  [
        "spawn-planner.py: allocate next available IPs",
        "Regenerate Cloud-Init snippets with new IPs",
        "Regenerate spawn package",
    ]),
    "join_fingerprint":  (True,  [
        "Retrieve current cluster fingerprint from hatchery",
        "Regenerate spawn package with updated fingerprint",
    ]),
    "token_expired":     (True,  [
        "Rotate k3s join tokens on the hatchery",
        "Update bootstrap-state.json with new tokens",
        "Regenerate spawn package with fresh tokens",
    ]),
    "vmid_taken":        (True,  [
        "spawn-planner.py: allocate next available VMID block",
        "Regenerate spawn package with new VMIDs",
    ]),
    "template_missing":  (False, ["Install base template on broodling, then retry from phase-02."]),
}


# ---------------------------------------------------------------------------
# Core analyzer
# ---------------------------------------------------------------------------

def _phase_description(phase: str) -> str:
    info = PHASE_CATALOGUE.get(phase)
    if info:
        return info["description"]
    return f"Unknown phase ({phase})"


def _error_diagnosis(phase: str, error_type: str) -> str:
    info = PHASE_CATALOGUE.get(phase, {})
    categories = info.get("error_categories", {})
    return categories.get(error_type, f"Unknown error in {phase}: {error_type}")


def analyze_failure_report(report: FailureReport) -> FailureDiagnosis:
    """
    Analyze a parsed FailureReport and return a FailureDiagnosis.

    Phase-aware: uses PHASE_CATALOGUE to interpret the failure in context.
    """
    now = datetime.now(timezone.utc).isoformat()
    phase = report.failed_phase
    etype = report.error_type

    diagnosis   = _error_diagnosis(phase, etype)
    fixes       = _FIX_SUGGESTIONS.get(etype, [
        f"Review spawn log for details about {etype}.",
        f"Check phase script: {phase}.sh",
    ])
    can_regen, regen_steps = _REGEN_STEPS.get(etype, (False, []))

    return FailureDiagnosis(
        package_id=report.package_id,
        broodling_host=report.broodling_host,
        failed_phase=phase,
        phase_description=_phase_description(phase),
        error_type=etype,
        diagnosis=diagnosis,
        suggested_fixes=fixes,
        completed_phases=report.completed_phases,
        can_regenerate=can_regen,
        regeneration_steps=regen_steps,
        analyzed_at=now,
    )


def parse_failure_report(d: dict) -> FailureReport:
    """Parse a failure-report.json dict into a FailureReport."""
    return FailureReport(
        package_id=d.get("package_id") or d.get("spawn_package_id") or "unknown",
        broodling_host=d.get("broodling_host") or d.get("hostname") or "unknown",
        failed_phase=d.get("failed_phase") or "unknown",
        error_message=d.get("error_message") or d.get("error") or "",
        error_type=d.get("error_type") or _infer_error_type(d),
        cell_id=d.get("cell_id"),
        failed_at=d.get("failed_at"),
        spawn_plan_id=d.get("spawn_plan_id"),
        diagnostics=d.get("diagnostics") or {},
        completed_phases=d.get("completed_phases") or [],
        log_excerpt=d.get("log_excerpt"),
    )


def _infer_error_type(d: dict) -> str:
    """Heuristically infer error_type from error_message if not explicit."""
    msg = (d.get("error_message") or d.get("error") or "").lower()
    if "disk" in msg and "not found" in msg:
        return "disk_missing"
    if "nic" in msg or "interface" in msg and "renamed" in msg:
        return "nic_renamed"
    if "ram" in msg or "memory" in msg and "insufficient" in msg:
        return "ram_insufficient"
    if "vmid" in msg and "conflict" in msg:
        return "vmid_conflict"
    if "fingerprint" in msg:
        return "join_fingerprint"
    if "token" in msg and "expir" in msg:
        return "token_expired"
    if "unreachable" in msg:
        if "ansible" in msg:
            return "ansible_unreachable"
        return "join_unreachable"
    if "disk full" in msg or "no space" in msg:
        return "disk_full"
    return "unknown"


def analyze_failure_package(package_path: str) -> FailureDiagnosis:
    """
    Analyze a failure package tar.gz bundle.

    Extracts failure-report.json from the archive and analyzes it.
    """
    if not os.path.exists(package_path):
        raise FileNotFoundError(f"Failure package not found: {package_path}")

    with tarfile.open(package_path, "r:gz") as tar:
        # Find failure-report.json
        names = tar.getnames()
        report_name = next(
            (n for n in names if n.endswith("failure-report.json")),
            None,
        )
        if report_name is None:
            raise ValueError(f"No failure-report.json found in {package_path}")

        member = tar.getmember(report_name)
        fobj = tar.extractfile(member)
        if fobj is None:
            raise ValueError("Cannot read failure-report.json from archive")
        data = json.loads(fobj.read().decode())

    return analyze_failure_report(parse_failure_report(data))


# ---------------------------------------------------------------------------
# Package assembly helper (called from spawn.sh on failure)
# ---------------------------------------------------------------------------

def assemble_failure_package(
    failure_report: dict,
    spawn_plan_path: Optional[str] = None,
    manifest_path:   Optional[str] = None,
    hardware_profile_path: Optional[str] = None,
    log_paths:       Optional[list[str]] = None,
    checkpoint_dir:  Optional[str] = None,
    output_dir:      str = "/tmp",  # nosec B108 — caller-supplied output dir, not insecure temp file creation
) -> str:
    """
    Assemble a failure package tar.gz in memory and write to output_dir.

    Returns the path to the created package.
    Used by the Python-side (for tests and hatchery tooling);
    the shell-side uses FAILURE_SHELL_FUNCTIONS.
    """
    pkg_id = failure_report.get("package_id") or "failure-unknown"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H_%M_%S")
    fname = f"failure-{pkg_id}-{ts}.tar.gz"
    out_path = os.path.join(output_dir, fname)

    with tarfile.open(out_path, "w:gz") as tar:
        def _add_json(name: str, data: dict) -> None:
            raw = json.dumps(data, indent=2).encode()
            info = tarfile.TarInfo(name=name)
            info.size = len(raw)
            tar.addfile(info, io.BytesIO(raw))

        def _add_file(archive_name: str, fs_path: str) -> None:
            if fs_path and os.path.exists(fs_path):
                tar.add(fs_path, arcname=archive_name)

        _add_json("failure-report.json", failure_report)
        _add_file("spawn-plan.json",       spawn_plan_path or "")
        _add_file("spawn-manifest.json",   manifest_path or "")
        _add_file("hardware-profile.json", hardware_profile_path or "")

        for lp in (log_paths or []):
            _add_file(f"logs/{os.path.basename(lp)}", lp)

        if checkpoint_dir and os.path.isdir(checkpoint_dir):
            for f in os.listdir(checkpoint_dir):
                _add_file(f"checkpoints/{f}", os.path.join(checkpoint_dir, f))

    return out_path


# ---------------------------------------------------------------------------
# Export functions
# ---------------------------------------------------------------------------

def export_to_usb(package_path: str, mount_point: str) -> str:
    """
    Copy a failure package to a USB drive mount point.

    Returns the destination path on success.
    Raises OSError on failure.
    """
    import shutil
    if not os.path.isdir(mount_point):
        raise OSError(f"USB mount point not found: {mount_point}")
    dest = os.path.join(mount_point, os.path.basename(package_path))
    shutil.copy2(package_path, dest)
    return dest


def export_to_hatchery(
    package_path: str,
    hatchery_url:  str,
    timeout:       int = 30,
) -> dict:
    """
    POST a failure package to the hatchery receiver endpoint.

    Returns the JSON response from the hatchery ({"status": "received", ...}).
    Raises urllib.error.URLError on network failure.

    Uses urllib (stdlib). The broodling calls this when hatchery connectivity
    was established during the spawn (phase-01 succeeded or WAN mode was used).
    """
    if urllib.parse.urlparse(hatchery_url).scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme for hatchery endpoint: {hatchery_url!r}")
    endpoint = hatchery_url.rstrip("/") + "/api/failure-packages"
    with open(package_path, "rb") as f:
        body = f.read()

    req = urllib.request.Request(  # noqa: S310  # nosec B310
        endpoint,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/octet-stream",
            "X-Package-Name": os.path.basename(package_path),
            "X-Package-Size": str(len(body)),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310  # nosec B310
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise urllib.error.URLError(f"Hatchery returned {e.code}: {e.reason}")


# ---------------------------------------------------------------------------
# Shell library for spawn scripts (embedded in spawn.sh / phoenix run-all.sh)
# ---------------------------------------------------------------------------

FAILURE_SHELL_FUNCTIONS = r"""\
# ---------------------------------------------------------------------------
# Failure package generation — sourced by spawn.sh and run-all.sh
# ---------------------------------------------------------------------------

FAILURE_PACKAGE_DIR="${SCRIPT_DIR}/failure-packages"
mkdir -p "$FAILURE_PACKAGE_DIR"

_write_failure_report() {
  local phase="$1" error_type="$2" error_msg="$3"
  local ts; ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  local hostname; hostname="$(hostname -s 2>/dev/null || echo unknown)"
  cat > "$FAILURE_PACKAGE_DIR/failure-report.json" <<REPORT_EOF
{
  "package_id":      "${SPAWN_PACKAGE_ID:-unknown}",
  "broodling_host":  "${hostname}",
  "cell_id":         "${CELL_ID:-unknown}",
  "failed_phase":    "${phase}",
  "error_type":      "${error_type}",
  "error_message":   "${error_msg}",
  "failed_at":       "${ts}",
  "spawn_plan_id":   "${SPAWN_PLAN_ID:-unknown}",
  "completed_phases": [$(
    if ls "$CHECKPOINT_DIR"/*.done &>/dev/null; then
      ls "$CHECKPOINT_DIR"/*.done | sed 's|.*/||;s|\.done$||' | \
        awk '{printf "\\"%s\\"", $0}' | sed 's/"/,"/g' | sed 's/^,//'
    fi
  )],
  "log_excerpt": "$(tail -20 "$SPAWN_LOG" 2>/dev/null | tr '\\n' '|' | sed 's/"/\\\\"/g')"
}
REPORT_EOF
}

generate_failure_package() {
  local phase="$1" error_type="${2:-unknown}" error_msg="${3:-}"
  local ts; ts="$(date -u +%Y%m%d_%H%M%S)"
  local pkg_name="failure-${SPAWN_PACKAGE_ID:-unknown}-${ts}.tar.gz"
  local pkg_path="$FAILURE_PACKAGE_DIR/$pkg_name"

  echo "[fail] Generating failure package: $pkg_name"
  _write_failure_report "$phase" "$error_type" "$error_msg"

  tar -czf "$pkg_path" \\
    -C "$FAILURE_PACKAGE_DIR" failure-report.json \\
    -C "$SCRIPT_DIR" \\
    $([ -f spawn-plan.json ]       && echo spawn-plan.json) \\
    $([ -f spawn-manifest.json ]   && echo spawn-manifest.json) \\
    $([ -f hardware-profile.json ] && echo hardware-profile.json) \\
    $([ -f "$SPAWN_LOG" ]          && echo "$(basename "$SPAWN_LOG")") \\
    $([ -d "$CHECKPOINT_DIR" ]     && echo "$(basename "$CHECKPOINT_DIR")") \\
    2>/dev/null || true

  echo "[fail] Failure package ready: $pkg_path"

  # Try network export first (if hatchery connectivity was established)
  if [ -n "${HATCHERY_RECEIVER_URL:-}" ]; then
    echo "[fail] Exporting to hatchery: $HATCHERY_RECEIVER_URL"
    if curl -sf --max-time 30 \\
        -X POST "$HATCHERY_RECEIVER_URL/api/failure-packages" \\
        --data-binary "@$pkg_path" \\
        -H "Content-Type: application/octet-stream" \\
        -H "X-Package-Name: $pkg_name" >/dev/null 2>&1; then
      echo "[fail] Failure package sent to hatchery."
    else
      echo "[fail] Network export failed — package saved locally for USB export."
    fi
  fi

  # USB export instructions
  echo ""
  echo "================================================================="
  echo " Failure Package: $pkg_path"
  echo " To export via USB: cp '$pkg_path' /media/<usb-mount>/"
  echo " Then on hatchery: python3 failure_package_analyzer.py <path>"
  echo "================================================================="
}
"""
