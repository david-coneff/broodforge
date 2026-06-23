#!/usr/bin/env python3
"""
forge_validator.py — Minimum viable forge validation (Phase 1.F.5).

Validates that a host's hardware profile meets the minimum requirements for
forging a broodforge hatchery. Used in phase-02 (validate) of forge.sh —
RED findings block the forge, YELLOW findings warn but allow proceeding.

The minimum viable broodforge stack requires:
  - At least 16 GiB RAM (8 GiB recommended per VM × 2 minimum VMs)
  - At least 2 disks suitable for ZFS (≥ 32 GiB each)
  - At least 1 NIC (in addition to any loopback/virtual)
  - Proxmox VE installed (presence of qm + pvecm commands inferred from context)

User applications are NOT validated here — they are added via GitOps after forging.
Only the minimum viable broodforge stack is checked.

Provides:
  ForgeHardwareRequirements  — named constant set
  ForgeValidationFinding     — {severity, field, message}
  validate_forge_hardware()  — entry point
  is_forge_valid()           — True if no RED findings
  summarise_forge_findings() — human-readable string

Stdlib only.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

# ---------------------------------------------------------------------------
# Severity constants
# ---------------------------------------------------------------------------

SEVERITY_RED    = "RED"
SEVERITY_YELLOW = "YELLOW"


# ---------------------------------------------------------------------------
# Minimum requirements (constants — easy to find and update)
# ---------------------------------------------------------------------------

class ForgeHardwareRequirements:
    """Minimum hardware for a viable broodforge hatchery."""

    # Minimum RAM for the host itself (GiB)
    # Assessment Engine + doc-gen + Proxmox overhead alone need ~4 GiB
    MIN_HOST_RAM_GIB      = 16

    # Recommended host RAM (enables more comfortable VM sizing)
    RECOMMENDED_RAM_GIB   = 32

    # Minimum disk count for ZFS (mirror requires 2; stripe is possible with 1
    # but strongly discouraged — RED if only 1 usable disk)
    MIN_DISK_COUNT        = 2

    # Minimum per-disk size in GiB for a ZFS member disk
    MIN_DISK_SIZE_GIB     = 32

    # Minimum usable NIC count (physical NICs, excluding lo / vmbr* / veth* etc.)
    MIN_NIC_COUNT         = 1

    # Minimum CPU cores recommended (Proxmox + VMs)
    RECOMMENDED_CPU_CORES = 4

    # Minimum storage headroom after ZFS pool (GiB) — free space expected
    # for Proxmox ISOs, templates, and VM disks
    MIN_FREE_STORAGE_GIB  = 50


# ---------------------------------------------------------------------------
# Finding dataclass
# ---------------------------------------------------------------------------

@dataclass
class ForgeValidationFinding:
    """A single validation result from validate_forge_hardware()."""
    severity: str   # RED | YELLOW
    field:    str   # what was checked
    message:  str   # human-readable description
    observed: Any   # what was found
    required: Any   # what is needed


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

def validate_forge_hardware(hardware_profile: dict) -> list[ForgeValidationFinding]:
    """
    Validate hardware_profile dict against minimum forge requirements.

    hardware_profile format mirrors spawn_hardware_discovery.HardwareProfile.to_dict():
      ram_gb: int
      cpu_model: str
      cpu_cores: int
      hostname: str
      disks: [{name, size_gb, model, rotational, removable}]
      nics: [{name, mac, speed_mbps}]
      derived: {disk_count, usable_disks, ssd_count, hdd_count}

    Returns list of ForgeValidationFinding (empty = all checks passed).
    """
    findings: list[ForgeValidationFinding] = []
    req = ForgeHardwareRequirements

    ram_gb    = hardware_profile.get("ram_gb") or 0
    cpu_cores = hardware_profile.get("cpu_cores") or 0
    disks     = hardware_profile.get("disks") or []
    nics      = hardware_profile.get("nics") or []
    hardware_profile.get("derived") or {}

    # ------------------------------------------------------------------
    # RAM
    # ------------------------------------------------------------------
    if ram_gb < req.MIN_HOST_RAM_GIB:
        findings.append(ForgeValidationFinding(
            severity=SEVERITY_RED,
            field="ram_gb",
            message=(
                f"Host has {ram_gb} GiB RAM; minimum required is {req.MIN_HOST_RAM_GIB} GiB. "
                "The broodforge stack (Assessment Engine, doc-gen, k3s VMs) requires at least "
                f"{req.MIN_HOST_RAM_GIB} GiB to operate reliably."
            ),
            observed=ram_gb,
            required=req.MIN_HOST_RAM_GIB,
        ))
    elif ram_gb < req.RECOMMENDED_RAM_GIB:
        findings.append(ForgeValidationFinding(
            severity=SEVERITY_YELLOW,
            field="ram_gb",
            message=(
                f"Host has {ram_gb} GiB RAM; {req.RECOMMENDED_RAM_GIB} GiB recommended for "
                "comfortable operation with multiple VMs. Forge can proceed but VM sizing will "
                "be constrained."
            ),
            observed=ram_gb,
            required=req.RECOMMENDED_RAM_GIB,
        ))

    # ------------------------------------------------------------------
    # Disks — count and size
    # ------------------------------------------------------------------
    usable = _usable_disks(disks, req.MIN_DISK_SIZE_GIB)
    usable_count = len(usable)

    if usable_count == 0:
        findings.append(ForgeValidationFinding(
            severity=SEVERITY_RED,
            field="disks",
            message=(
                f"No usable disks found (minimum size {req.MIN_DISK_SIZE_GIB} GiB). "
                "At least 2 disks are required for a ZFS mirror pool. "
                f"Total disks detected: {len(disks)}."
            ),
            observed=usable_count,
            required=req.MIN_DISK_COUNT,
        ))
    elif usable_count < req.MIN_DISK_COUNT:
        findings.append(ForgeValidationFinding(
            severity=SEVERITY_RED,
            field="disks",
            message=(
                f"Only {usable_count} usable disk(s) ≥{req.MIN_DISK_SIZE_GIB} GiB found; "
                f"{req.MIN_DISK_COUNT} required for ZFS mirror. "
                "A single-disk stripe is possible but provides no data redundancy — forge is "
                "blocked until a second disk is available."
            ),
            observed=usable_count,
            required=req.MIN_DISK_COUNT,
        ))

    # Check for small disks that might be OS disks (usable as ZFS members but borderline)
    small_usable = [d for d in usable if d.get("size_gb", 0) < 100]
    if small_usable and usable_count >= req.MIN_DISK_COUNT:
        sizes = [d.get("size_gb", 0) for d in small_usable]
        findings.append(ForgeValidationFinding(
            severity=SEVERITY_YELLOW,
            field="disks",
            message=(
                f"{len(small_usable)} disk(s) are small (<100 GiB): "
                f"{', '.join(str(s)+' GiB' for s in sizes)}. "
                "These will be usable as ZFS members but will limit VM disk sizing. "
                "Consider larger disks for production use."
            ),
            observed=sizes,
            required="≥100 GiB per disk recommended",
        ))

    # ------------------------------------------------------------------
    # NICs
    # ------------------------------------------------------------------
    nic_count = len(nics)
    if nic_count < req.MIN_NIC_COUNT:
        findings.append(ForgeValidationFinding(
            severity=SEVERITY_RED,
            field="nics",
            message=(
                f"No physical NICs detected. At least {req.MIN_NIC_COUNT} NIC is required "
                "for the Proxmox management bridge (vmbr0). "
                "Virtual/loopback interfaces are excluded."
            ),
            observed=nic_count,
            required=req.MIN_NIC_COUNT,
        ))
    elif nic_count == 1:
        findings.append(ForgeValidationFinding(
            severity=SEVERITY_YELLOW,
            field="nics",
            message=(
                "Only 1 physical NIC detected. The hatchery will operate on a single bridge "
                "(vmbr0 on eth0/eno1). A second NIC enables dedicated storage or VM traffic "
                "separation — recommended for production use."
            ),
            observed=nic_count,
            required="≥2 recommended for traffic separation",
        ))

    # ------------------------------------------------------------------
    # CPU cores
    # ------------------------------------------------------------------
    if cpu_cores > 0 and cpu_cores < req.RECOMMENDED_CPU_CORES:
        findings.append(ForgeValidationFinding(
            severity=SEVERITY_YELLOW,
            field="cpu_cores",
            message=(
                f"Host has {cpu_cores} CPU core(s); {req.RECOMMENDED_CPU_CORES} recommended "
                "for comfortable multi-VM operation. Forge can proceed but VM vCPU allocation "
                "will be constrained."
            ),
            observed=cpu_cores,
            required=req.RECOMMENDED_CPU_CORES,
        ))

    return findings


def _usable_disks(disks: list, min_size_gib: int) -> list:
    """Return disks that meet the minimum size requirement and are not removable."""
    result = []
    for d in disks:
        size_gb  = d.get("size_gb") or 0
        removable = d.get("removable") or False
        if size_gb >= min_size_gib and not removable:
            result.append(d)
    return result


# ---------------------------------------------------------------------------
# Helper: is_forge_valid / summarise
# ---------------------------------------------------------------------------

def is_forge_valid(findings: list[ForgeValidationFinding]) -> bool:
    """Return True if no RED findings exist (forge may proceed)."""
    return not any(f.severity == SEVERITY_RED for f in findings)


def summarise_forge_findings(findings: list[ForgeValidationFinding]) -> str:
    """Return a human-readable summary of forge validation findings."""
    if not findings:
        return "All forge hardware checks passed."
    reds    = [f for f in findings if f.severity == SEVERITY_RED]
    yellows = [f for f in findings if f.severity == SEVERITY_YELLOW]
    lines = []
    if reds:
        lines.append(f"BLOCKED ({len(reds)} RED finding(s)):")
        for f in reds:
            lines.append(f"  [RED]    {f.field}: {f.message}")
    if yellows:
        lines.append(f"Warnings ({len(yellows)} YELLOW finding(s)):")
        for f in yellows:
            lines.append(f"  [YELLOW] {f.field}: {f.message}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Minimum viable stack declaration
# ---------------------------------------------------------------------------

MINIMUM_VIABLE_STACK = [
    "proxmox-ve",           # Proxmox hypervisor
    "k3s-server",           # k3s control plane (SQLite embedded etcd — single node)
    "assessment-engine",    # Broodforge assessment + doc generation
    "forgejo",              # Git server (GitOps source of truth)
]

def describe_minimum_stack() -> str:
    """Return a human-readable description of the minimum forge stack."""
    return (
        "Minimum viable broodforge hatchery stack:\n"
        + "\n".join(f"  - {s}" for s in MINIMUM_VIABLE_STACK)
        + "\n\nUser applications are added via GitOps (Flux CD) after forging."
    )


# ---------------------------------------------------------------------------
# Forge manifest schema validation
# ---------------------------------------------------------------------------

_SCHEMA_PATH = Path(__file__).parent.parent / "data-model" / "forge-manifest-schema.json"


def validate_forge_manifest(manifest: dict, schema_path: Optional[str] = None) -> List["ForgeValidationFinding"]:
    """
    Validate a forge-manifest.json dict against the JSON schema.

    Uses jsonschema if available; falls back to structural checks (required
    fields only) if jsonschema is not installed.

    Returns a list of ForgeValidationFinding — empty list means valid.
    """
    findings: List[ForgeValidationFinding] = []
    path = Path(schema_path) if schema_path else _SCHEMA_PATH

    if not path.exists():
        return [ForgeValidationFinding(
            severity=SEVERITY_YELLOW,
            field="schema",
            message=f"forge-manifest-schema.json not found at {path} — schema validation skipped",
            observed=None,
            required=None,
        )]

    with open(path) as fh:
        schema = json.load(fh)

    try:
        import jsonschema  # type: ignore
        try:
            jsonschema.validate(manifest, schema)
        except jsonschema.ValidationError as exc:
            path_str = ".".join(str(p) for p in exc.absolute_path)
            if not path_str and exc.validator == "required":
                # Root-level required field: extract name from message
                import re as _re
                m = _re.search(r"'(\w+)' is a required property", exc.message)
                path_str = m.group(1) if m else "root"
            elif not path_str:
                path_str = "root"
            findings.append(ForgeValidationFinding(
                severity=SEVERITY_RED,
                field=path_str,
                message=exc.message,
                observed=None,
                required=None,
            ))
        except jsonschema.SchemaError as exc:
            findings.append(ForgeValidationFinding(
                severity=SEVERITY_YELLOW,
                field="schema",
                message=f"Schema itself is invalid: {exc.message}",
                observed=None,
                required=None,
            ))
    except ImportError:
        # jsonschema not available — fall back to checking required fields only
        required = schema.get("required") or []
        for field in required:
            if field not in manifest:
                findings.append(ForgeValidationFinding(
                    severity=SEVERITY_RED,
                    field=field,
                    message=f"Required field '{field}' missing from forge manifest",
                    observed=None,
                    required=field,
                ))

    return findings
