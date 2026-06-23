#!/usr/bin/env python3
"""
validate_spawn.py — Spawn conflict validator (Phase 12.E.2).

Run before spawn package generation on the hatchery AND again on the
broodling before any deployment action. Uses only the embedded
spawn-manifest.json — no live API access required on the broodling.

Provides:
  SpawnFinding          — a single validation finding (severity + message)
  SpawnProposal         — proposed allocations for a new broodling
  validate_spawn(manifest, proposal) → list[SpawnFinding]
  is_valid(findings)    — True if no RED findings
  summarise(findings)   → human-readable string

Severity levels:
  RED    — collision or violation that blocks spawn package generation.
           Must be resolved before the package can be built.
  YELLOW — advisory warning; spawn can proceed but operator should review.
"""

import ipaddress
import re
from dataclasses import dataclass, field
from typing import Optional

from hatchery_state import SpawnManifest

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

SEVERITY_RED    = "RED"
SEVERITY_YELLOW = "YELLOW"


@dataclass
class SpawnFinding:
    severity:    str              # RED | YELLOW
    field:       str              # dot-path to the problematic field
    message:     str
    proposed:    Optional[str] = None   # the value that caused the finding
    conflicting: Optional[str] = None   # the existing value it conflicts with


@dataclass
class SpawnProposal:
    """
    Proposed allocations for a new broodling.

    All fields are optional — only the ones present will be validated.
    The spawn planner populates this from the planned allocations.
    """
    vmids:           list = field(default_factory=list)   # proposed VMID integers
    ips:             list = field(default_factory=list)   # proposed IP strings
    hostnames:       list = field(default_factory=list)   # proposed FQDN/short strings
    hostname:        Optional[str] = None                  # primary broodling hostname
    roles:           list = field(default_factory=list)   # service roles to deploy
    ram_gb:          Optional[float] = None               # total VM RAM required
    host_ram_gb:     Optional[float] = None               # replacement hardware RAM
    placement_policy: Optional[dict] = None               # from metadata/placement-policy.yaml


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

def validate_spawn(
    manifest: SpawnManifest,
    proposal: SpawnProposal,
) -> list[SpawnFinding]:
    """
    Validate a spawn proposal against the hatchery's reservation manifest.

    Returns a list of SpawnFinding. An empty list means no issues found.
    RED findings block package generation; YELLOW findings are advisory.
    """
    findings: list[SpawnFinding] = []

    findings += _check_vmids(manifest, proposal)
    findings += _check_ips(manifest, proposal)
    findings += _check_hostnames(manifest, proposal)
    findings += _check_capacity(manifest, proposal)
    findings += _check_placement(manifest, proposal)

    return findings


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_vmids(manifest: SpawnManifest, proposal: SpawnProposal) -> list[SpawnFinding]:
    findings = []
    reserved = manifest.reserved_vmids

    # Intra-proposal duplicates
    seen: set = set()
    for vmid in proposal.vmids:
        try:
            vid = int(vmid)
        except (TypeError, ValueError):
            findings.append(SpawnFinding(
                severity=SEVERITY_RED,
                field="vmids",
                message=f"VMID '{vmid}' is not a valid integer",
                proposed=str(vmid),
            ))
            continue

        if vid in seen:
            findings.append(SpawnFinding(
                severity=SEVERITY_RED,
                field="vmids",
                message=f"Duplicate VMID {vid} in proposal",
                proposed=str(vid),
            ))
        seen.add(vid)

        # Reserved range checks
        if vid < 100:
            findings.append(SpawnFinding(
                severity=SEVERITY_RED,
                field="vmids",
                message=f"VMID {vid} is below 100 (reserved by Proxmox)",
                proposed=str(vid),
            ))
        elif vid >= 9000:
            findings.append(SpawnFinding(
                severity=SEVERITY_RED,
                field="vmids",
                message=f"VMID {vid} is in template range (9000+)",
                proposed=str(vid),
            ))
        elif vid in reserved:
            conflicting = next((str(v) for v in reserved if v == vid), None)
            findings.append(SpawnFinding(
                severity=SEVERITY_RED,
                field="vmids",
                message=f"VMID {vid} is already allocated in the hatchery",
                proposed=str(vid),
                conflicting=conflicting,
            ))

    return findings


def _check_ips(manifest: SpawnManifest, proposal: SpawnProposal) -> list[SpawnFinding]:
    findings  = []
    reserved  = manifest.reserved_ips
    mgmt_cidr = manifest.raw.get("reserved", {}).get("management_cidr", "")

    # Parse management CIDR for subnet check
    mgmt_net = None
    if mgmt_cidr:
        try:
            mgmt_net = ipaddress.ip_network(mgmt_cidr, strict=False)
        except ValueError:
            pass

    seen: set = set()
    for ip in proposal.ips:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            findings.append(SpawnFinding(
                severity=SEVERITY_RED,
                field="ips",
                message=f"'{ip}' is not a valid IP address",
                proposed=ip,
            ))
            continue

        if ip in seen:
            findings.append(SpawnFinding(
                severity=SEVERITY_RED,
                field="ips",
                message=f"Duplicate IP {ip} in proposal",
                proposed=ip,
            ))
        seen.add(ip)

        if ip in reserved:
            findings.append(SpawnFinding(
                severity=SEVERITY_RED,
                field="ips",
                message=f"IP {ip} is already allocated in the hatchery",
                proposed=ip,
                conflicting=ip,
            ))

        if mgmt_net and addr not in mgmt_net:
            findings.append(SpawnFinding(
                severity=SEVERITY_YELLOW,
                field="ips",
                message=(
                    f"IP {ip} is not in management CIDR {mgmt_cidr} — "
                    "ensure it is reachable from the hatchery"
                ),
                proposed=ip,
            ))

    return findings


def _check_hostnames(manifest: SpawnManifest, proposal: SpawnProposal) -> list[SpawnFinding]:
    findings = []
    reserved = manifest.reserved_hostnames

    # Collect all proposed hostnames; normalise to short names for dedup.
    # hostname (bare) and hostnames (FQDNs) may refer to the same machine —
    # deduplicate by short name so e.g. "pve02" + "pve02.internal" is not a conflict.
    all_proposed = list(proposal.hostnames)
    if proposal.hostname:
        short_of_hostname = proposal.hostname.split(".")[0]
        if not any(h.split(".")[0] == short_of_hostname for h in all_proposed):
            all_proposed.append(proposal.hostname)

    seen_short: set = set()
    for hostname in all_proposed:
        short = hostname.split(".")[0]

        if short in seen_short:
            findings.append(SpawnFinding(
                severity=SEVERITY_RED,
                field="hostnames",
                message=f"Duplicate hostname '{hostname}' in proposal",
                proposed=hostname,
            ))
        seen_short.add(short)

        if hostname in reserved or short in reserved:
            findings.append(SpawnFinding(
                severity=SEVERITY_RED,
                field="hostnames",
                message=f"Hostname '{hostname}' is already in use in the hatchery",
                proposed=hostname,
                conflicting=hostname,
            ))

        # Format check (only on non-trivially formatted names)
        check = hostname.lower()
        if not re.match(r"^[a-z][a-z0-9-]{0,61}([a-z0-9])?(\.[a-z0-9-]+)*$", check):
            findings.append(SpawnFinding(
                severity=SEVERITY_YELLOW,
                field="hostnames",
                message=(
                    f"Hostname '{hostname}' does not follow standard naming convention "
                    "(lowercase, letters/digits/hyphens, max 63 chars per label)"
                ),
                proposed=hostname,
            ))

    return findings


def _check_capacity(manifest: SpawnManifest, proposal: SpawnProposal) -> list[SpawnFinding]:
    findings = []
    if proposal.ram_gb is None or proposal.host_ram_gb is None:
        return findings  # cannot assess without data

    headroom = proposal.host_ram_gb * 0.10
    available = proposal.host_ram_gb - headroom

    if proposal.ram_gb > available:
        shortfall = proposal.ram_gb - available
        findings.append(SpawnFinding(
            severity=SEVERITY_RED,
            field="capacity.ram_gb",
            message=(
                f"Proposed VM RAM ({proposal.ram_gb} GB) exceeds available capacity "
                f"({available:.1f} GB = {proposal.host_ram_gb} GB host − 10% headroom). "
                f"Shortfall: {shortfall:.1f} GB."
            ),
            proposed=str(proposal.ram_gb),
            conflicting=str(available),
        ))
    elif proposal.ram_gb > available * 0.85:
        findings.append(SpawnFinding(
            severity=SEVERITY_YELLOW,
            field="capacity.ram_gb",
            message=(
                f"Proposed VM RAM ({proposal.ram_gb} GB) uses "
                f"{proposal.ram_gb / proposal.host_ram_gb * 100:.0f}% of host RAM "
                f"— limited headroom for future growth"
            ),
            proposed=str(proposal.ram_gb),
        ))

    return findings


def _check_placement(manifest: SpawnManifest, proposal: SpawnProposal) -> list[SpawnFinding]:
    """Advisory: check proposed roles against placement policy if provided."""
    findings = []
    if not proposal.placement_policy or not proposal.roles:
        return findings

    allowed_roles = set(proposal.placement_policy.get("allowed_roles") or [])
    if allowed_roles:
        for role in proposal.roles:
            if role not in allowed_roles:
                findings.append(SpawnFinding(
                    severity=SEVERITY_YELLOW,
                    field="roles",
                    message=(
                        f"Role '{role}' is not in the declared placement policy "
                        f"allowed_roles: {sorted(allowed_roles)}"
                    ),
                    proposed=role,
                ))

    return findings


# ---------------------------------------------------------------------------
# Summary helpers
# ---------------------------------------------------------------------------

def is_valid(findings: list[SpawnFinding]) -> bool:
    """Return True if there are no RED findings."""
    return not any(f.severity == SEVERITY_RED for f in findings)


def summarise(findings: list[SpawnFinding]) -> str:
    """Return a human-readable summary of findings."""
    reds    = [f for f in findings if f.severity == SEVERITY_RED]
    yellows = [f for f in findings if f.severity == SEVERITY_YELLOW]

    if not findings:
        return "✓ No conflicts detected — spawn proposal is valid"

    lines = [f"Spawn validation: {len(reds)} error(s), {len(yellows)} warning(s)"]
    for f in reds:
        lines.append(f"  [RED]    {f.field}: {f.message}")
    for f in yellows:
        lines.append(f"  [YELLOW] {f.field}: {f.message}")
    if reds:
        lines.append("Spawn package generation is BLOCKED until RED findings are resolved.")
    return "\n".join(lines)
