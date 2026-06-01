#!/usr/bin/env python3
"""
federation_state.py — Federation State and Trust Model (Phase 19).

A federation is a set of broodforge cells that can recover each other.
Each cell is independently operational but participates in the federation
for resilience: cells hold each other's backups, trust each other's
authentication, and coordinate reconstruction when a cell fails.

This module implements:
  19.1  FederationState schema + federation-state-schema.json
  19.2  CellRegistryEntry — registered cell in the federation
  19.3  TrustRelationship — declared trust between cells (all relationship types)
  19.4  verify_trust()    — check trust validity (expiry, verification age)
  19.5  RecoveryRelationship — which cell can recover which
  19.6  verify_recovery()    — check if recovery resources are accessible
  19.7  Tier3AssessmentEngine — cross-cell, federation-scope readiness scoring
  19.8  Tests in test_phase19_federation.py

Trust relationship types:
  peer            — mutual: share resources, coordinate workloads
  recovery        — coordinator can reconstruct subject after failure
  backup-provider — coordinator holds backups for subject
  read-only       — coordinator can read subject's state (assessment, twin)

Provides:
  CellRegistryEntry         — single cell in the federation registry
  TrustRelationship         — declared inter-cell trust
  RecoveryRelationship      — recovery coordination declaration
  FederationState           — complete federation state document
  register_cell()           — add/update cell in federation
  declare_trust()           — declare a trust relationship
  declare_recovery()        — declare a recovery relationship
  verify_trust()            — check trust validity
  verify_recovery()         — check recovery resource reachability
  score_federation_readiness() — RED/ORANGE/YELLOW/GREEN per cell + overall
  FederationReadinessReport — per-cell and overall readiness summary
  Tier3AssessmentEngine     — cross-cell assessment driver
  federation_state_to_dict() — JSON-serialisable dict

Stdlib only.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# Trust relationship type constants
# ---------------------------------------------------------------------------

TRUST_PEER              = "peer"
TRUST_RECOVERY          = "recovery"
TRUST_BACKUP_PROVIDER   = "backup-provider"
TRUST_READ_ONLY         = "read-only"

ALL_TRUST_TYPES = (TRUST_PEER, TRUST_RECOVERY, TRUST_BACKUP_PROVIDER, TRUST_READ_ONLY)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CellRegistryEntry:
    """A cell registered in the federation."""
    cell_id:          str
    registered_at:    str
    hostname:         Optional[str]  = None
    domain:           Optional[str]  = None
    fqdn:             Optional[str]  = None
    endpoint:         Optional[str]  = None   # e.g. https://hatchery.home.example.com:8080
    status:           str            = "active"  # active|degraded|unreachable|decommissioned
    last_seen_at:     Optional[str]  = None
    capabilities:     list[str]      = field(default_factory=list)   # from CapabilityState
    notes:            Optional[str]  = None

    @property
    def is_active(self) -> bool:
        return self.status == "active"


@dataclass
class TrustRelationship:
    """
    Declared trust between two cells.

    Trust is directional: from_cell trusts to_cell to perform relationship_type
    operations on its behalf. "peer" is mutual by convention but still requires
    both sides to declare (or a single peer declaration is treated as mutual).
    """
    relationship_id:  str
    from_cell:        str           # cell granting trust
    to_cell:          str           # cell being trusted
    relationship_type: str          # TRUST_* constant
    declared_at:      str
    expires_at:       Optional[str] = None    # None = never expires
    verified_at:      Optional[str] = None    # last time this was verified operational
    status:           str           = "active"  # active|expired|unverified|revoked
    notes:            Optional[str] = None
    # How often this must be re-verified (days); None = no requirement
    reverify_days:    Optional[int] = 90

    @property
    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        try:
            exp = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
            return datetime.now(timezone.utc) > exp
        except (ValueError, AttributeError):
            return False

    @property
    def days_until_expiry(self) -> Optional[int]:
        if not self.expires_at:
            return None
        try:
            exp = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
            delta = exp - datetime.now(timezone.utc)
            return max(0, delta.days)
        except (ValueError, AttributeError):
            return None


@dataclass
class RecoveryRelationship:
    """
    Recovery coordination declaration.

    subject_cell:     the cell that may need to be recovered
    coordinator_cell: the cell that holds resources and can coordinate recovery
    """
    relationship_id:    str
    subject_cell:       str
    coordinator_cell:   str
    declared_at:        str
    backup_locations:   list[dict]   = field(default_factory=list)
    # Backup locations: [{type: "restic"|"rclone", remote: "...", path: "...", layer: "..."}]
    verified_at:        Optional[str] = None
    status:             str           = "active"  # active|unverified|degraded|unavailable
    last_backup_at:     Optional[str] = None
    rto_minutes:        Optional[int] = None      # declared RTO in minutes
    rpo_hours:          Optional[int] = None      # declared RPO in hours
    notes:              Optional[str] = None

    @property
    def is_active(self) -> bool:
        return self.status == "active"


@dataclass
class FederationState:
    """Complete federation state document."""
    federation_id:         str
    declared_at:           str
    cells:                 list[CellRegistryEntry]    = field(default_factory=list)
    trust_relationships:   list[TrustRelationship]   = field(default_factory=list)
    recovery_relationships: list[RecoveryRelationship] = field(default_factory=list)
    federation_name:       Optional[str]              = None
    notes:                 Optional[str]              = None

    def get_cell(self, cell_id: str) -> Optional[CellRegistryEntry]:
        return next((c for c in self.cells if c.cell_id == cell_id), None)

    def get_trust(self, from_cell: str, to_cell: str) -> list[TrustRelationship]:
        return [t for t in self.trust_relationships
                if t.from_cell == from_cell and t.to_cell == to_cell]

    def get_recovery(self, subject_cell: str) -> list[RecoveryRelationship]:
        return [r for r in self.recovery_relationships
                if r.subject_cell == subject_cell]

    def peers_of(self, cell_id: str) -> list[str]:
        peers = set()
        for t in self.trust_relationships:
            if t.relationship_type == TRUST_PEER and t.status == "active":
                if t.from_cell == cell_id:
                    peers.add(t.to_cell)
                elif t.to_cell == cell_id:
                    peers.add(t.from_cell)
        return sorted(peers)

    def coordinators_for(self, cell_id: str) -> list[str]:
        return sorted({
            r.coordinator_cell
            for r in self.recovery_relationships
            if r.subject_cell == cell_id and r.status == "active"
        })


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------

def _gen_id(*parts: str) -> str:
    """Generate a deterministic short ID from constituent parts."""
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def _now_iso(now_fn: Optional[Callable[[], str]] = None) -> str:
    if now_fn:
        return now_fn()
    return datetime.now(timezone.utc).isoformat()


def register_cell(
    federation:  FederationState,
    cell_id:     str,
    *,
    hostname:    Optional[str] = None,
    domain:      Optional[str] = None,
    fqdn:        Optional[str] = None,
    endpoint:    Optional[str] = None,
    capabilities: Optional[list[str]] = None,
    status:      str = "active",
    now_fn:      Optional[Callable[[], str]] = None,
) -> CellRegistryEntry:
    """
    Add or update a cell in the federation registry.

    If the cell is already registered, updates its fields.
    Returns the CellRegistryEntry.
    """
    now = _now_iso(now_fn)
    existing = federation.get_cell(cell_id)
    if existing:
        existing.hostname     = hostname     or existing.hostname
        existing.domain       = domain       or existing.domain
        existing.fqdn         = fqdn         or existing.fqdn
        existing.endpoint     = endpoint     or existing.endpoint
        existing.capabilities = capabilities or existing.capabilities
        existing.status       = status
        existing.last_seen_at = now
        return existing

    entry = CellRegistryEntry(
        cell_id=cell_id,
        registered_at=now,
        hostname=hostname,
        domain=domain,
        fqdn=fqdn,
        endpoint=endpoint,
        status=status,
        last_seen_at=now,
        capabilities=capabilities or [],
    )
    federation.cells.append(entry)
    return entry


def declare_trust(
    federation:        FederationState,
    from_cell:         str,
    to_cell:           str,
    relationship_type: str,
    *,
    expires_at:        Optional[str] = None,
    reverify_days:     Optional[int] = 90,
    notes:             Optional[str] = None,
    now_fn:            Optional[Callable[[], str]] = None,
) -> TrustRelationship:
    """
    Declare a trust relationship between two cells.

    Idempotent: if a relationship of the same type between the same cells
    already exists, updates it rather than creating a duplicate.
    """
    now  = _now_iso(now_fn)
    rel_id = _gen_id(from_cell, to_cell, relationship_type)

    existing = next(
        (t for t in federation.trust_relationships
         if t.relationship_id == rel_id or
         (t.from_cell == from_cell and t.to_cell == to_cell
          and t.relationship_type == relationship_type)),
        None,
    )
    if existing:
        existing.expires_at    = expires_at    or existing.expires_at
        existing.reverify_days = reverify_days if reverify_days is not None else existing.reverify_days
        existing.notes         = notes         or existing.notes
        existing.status        = "active"
        return existing

    rel = TrustRelationship(
        relationship_id=rel_id,
        from_cell=from_cell,
        to_cell=to_cell,
        relationship_type=relationship_type,
        declared_at=now,
        expires_at=expires_at,
        reverify_days=reverify_days,
        notes=notes,
    )
    federation.trust_relationships.append(rel)
    return rel


def declare_recovery(
    federation:       FederationState,
    subject_cell:     str,
    coordinator_cell: str,
    *,
    backup_locations: Optional[list[dict]] = None,
    rto_minutes:      Optional[int]        = None,
    rpo_hours:        Optional[int]        = None,
    notes:            Optional[str]        = None,
    now_fn:           Optional[Callable[[], str]] = None,
) -> RecoveryRelationship:
    """
    Declare that coordinator_cell holds recovery resources for subject_cell.

    Idempotent: updates existing relationship if already declared.
    """
    now    = _now_iso(now_fn)
    rel_id = _gen_id(subject_cell, coordinator_cell, "recovery")

    existing = next(
        (r for r in federation.recovery_relationships
         if r.relationship_id == rel_id or
         (r.subject_cell == subject_cell and r.coordinator_cell == coordinator_cell)),
        None,
    )
    if existing:
        if backup_locations is not None:
            existing.backup_locations = backup_locations
        existing.rto_minutes = rto_minutes or existing.rto_minutes
        existing.rpo_hours   = rpo_hours   or existing.rpo_hours
        existing.notes       = notes       or existing.notes
        return existing

    rel = RecoveryRelationship(
        relationship_id=rel_id,
        subject_cell=subject_cell,
        coordinator_cell=coordinator_cell,
        declared_at=now,
        backup_locations=backup_locations or [],
        rto_minutes=rto_minutes,
        rpo_hours=rpo_hours,
        notes=notes,
    )
    federation.recovery_relationships.append(rel)
    return rel


# ---------------------------------------------------------------------------
# Trust verification (19.4)
# ---------------------------------------------------------------------------

@dataclass
class TrustVerificationResult:
    relationship_id: str
    valid:           bool
    reason:          str
    verified_at:     str


def verify_trust(
    relationship: TrustRelationship,
    *,
    now_fn: Optional[Callable[[], str]] = None,
    max_reverify_age_days: Optional[int] = None,
) -> TrustVerificationResult:
    """
    Verify that a trust relationship is currently valid.

    Checks:
      1. Status is "active" (not revoked)
      2. Not expired (expires_at in the future, or None)
      3. Not overdue for re-verification (if reverify_days set)

    Returns a TrustVerificationResult with valid=True/False and reason.
    """
    now_str = _now_iso(now_fn)
    now     = datetime.fromisoformat(now_str.replace("Z", "+00:00"))

    if relationship.status == "revoked":
        return TrustVerificationResult(
            relationship_id=relationship.relationship_id,
            valid=False, reason="Trust relationship has been revoked.",
            verified_at=now_str,
        )

    if relationship.is_expired:
        return TrustVerificationResult(
            relationship_id=relationship.relationship_id,
            valid=False,
            reason=f"Trust relationship expired at {relationship.expires_at}.",
            verified_at=now_str,
        )

    # Check re-verification age
    rev_days = max_reverify_age_days or relationship.reverify_days
    if rev_days and relationship.verified_at:
        try:
            last = datetime.fromisoformat(relationship.verified_at.replace("Z", "+00:00"))
            age  = (now - last).days
            if age > rev_days:
                return TrustVerificationResult(
                    relationship_id=relationship.relationship_id,
                    valid=False,
                    reason=f"Trust not re-verified in {age} days (limit: {rev_days}).",
                    verified_at=now_str,
                )
        except (ValueError, AttributeError):
            pass

    days_left = relationship.days_until_expiry
    if days_left is not None and days_left <= 14:
        return TrustVerificationResult(
            relationship_id=relationship.relationship_id,
            valid=True,
            reason=f"Trust valid but expires soon ({days_left}d).",
            verified_at=now_str,
        )

    return TrustVerificationResult(
        relationship_id=relationship.relationship_id,
        valid=True, reason="Trust relationship active and current.",
        verified_at=now_str,
    )


# ---------------------------------------------------------------------------
# Recovery relationship verification (19.6)
# ---------------------------------------------------------------------------

@dataclass
class RecoveryVerificationResult:
    relationship_id:  str
    reachable:        bool
    reason:           str
    verified_at:      str


def verify_recovery(
    relationship: RecoveryRelationship,
    *,
    probe_fn: Optional[Callable[[str], bool]] = None,
    now_fn:   Optional[Callable[[], str]] = None,
) -> RecoveryVerificationResult:
    """
    Verify that recovery resources declared in the relationship are accessible.

    probe_fn(location_path) → bool: test whether a backup location is reachable.
    Without probe_fn, performs structural validation only (cannot test real access).

    Returns RecoveryVerificationResult with reachable=True/False and reason.
    """
    now_str = _now_iso(now_fn)

    if relationship.status == "unavailable":
        return RecoveryVerificationResult(
            relationship_id=relationship.relationship_id,
            reachable=False, reason="Recovery relationship marked unavailable.",
            verified_at=now_str,
        )

    if not relationship.backup_locations:
        return RecoveryVerificationResult(
            relationship_id=relationship.relationship_id,
            reachable=False,
            reason="No backup locations declared in recovery relationship.",
            verified_at=now_str,
        )

    if probe_fn is None:
        # Structural check only — assume accessible unless marked unavailable
        return RecoveryVerificationResult(
            relationship_id=relationship.relationship_id,
            reachable=True,
            reason=f"{len(relationship.backup_locations)} backup location(s) declared (structural check only — no live probe).",
            verified_at=now_str,
        )

    # Live probe: test each location
    failed = []
    for loc in relationship.backup_locations:
        path = loc.get("path") or loc.get("remote") or ""
        if not probe_fn(path):
            failed.append(path or "(unnamed)")

    if failed:
        return RecoveryVerificationResult(
            relationship_id=relationship.relationship_id,
            reachable=False,
            reason=f"Backup location(s) unreachable: {', '.join(failed)}",
            verified_at=now_str,
        )

    return RecoveryVerificationResult(
        relationship_id=relationship.relationship_id,
        reachable=True,
        reason=f"All {len(relationship.backup_locations)} backup location(s) reachable.",
        verified_at=now_str,
    )


# ---------------------------------------------------------------------------
# Federation readiness scoring (19.7 input)
# ---------------------------------------------------------------------------

@dataclass
class CellFederationScore:
    cell_id:                  str
    score:                    str    # GREEN/YELLOW/ORANGE/RED
    reason:                   str
    trust_issues:             list[str] = field(default_factory=list)
    recovery_issues:          list[str] = field(default_factory=list)
    has_recovery_coordinator: bool = False
    coordinator_cells:        list[str] = field(default_factory=list)


@dataclass
class FederationReadinessReport:
    overall_score:    str
    overall_reason:   str
    cell_scores:      list[CellFederationScore] = field(default_factory=list)
    total_cells:      int = 0
    active_cells:     int = 0
    trust_warnings:   list[str] = field(default_factory=list)
    recovery_gaps:    list[str] = field(default_factory=list)


def score_federation_readiness(
    federation: FederationState,
    *,
    now_fn: Optional[Callable[[], str]] = None,
) -> FederationReadinessReport:
    """
    Score federation-level readiness for each cell and overall.

    Per-cell scoring:
      GREEN:  has ≥1 active coordinator; all trust relationships valid
      YELLOW: no coordinator declared; or trust approaching expiry
      ORANGE: trust expired; or coordinator declared but unverified
      RED:    no cells in federation; or critical trust revoked

    Overall: worst cell score propagates.
    """
    now_str = _now_iso(now_fn)
    report  = FederationReadinessReport(
        overall_score="GREEN",
        overall_reason="All cells have valid trust and recovery coordinators.",
        total_cells=len(federation.cells),
        active_cells=sum(1 for c in federation.cells if c.is_active),
    )

    if not federation.cells:
        report.overall_score  = "RED"
        report.overall_reason = "No cells registered in federation."
        return report

    _score_order = {"GREEN": 0, "YELLOW": 1, "ORANGE": 2, "RED": 3}
    worst = "GREEN"

    for cell in federation.cells:
        score, reason = _score_cell(cell, federation, now_str)
        cs = CellFederationScore(
            cell_id=cell.cell_id,
            score=score,
            reason=reason,
            has_recovery_coordinator=bool(federation.coordinators_for(cell.cell_id)),
            coordinator_cells=federation.coordinators_for(cell.cell_id),
        )
        report.cell_scores.append(cs)
        if _score_order.get(score, 0) > _score_order.get(worst, 0):
            worst = score

    report.overall_score = worst
    if worst == "GREEN":
        report.overall_reason = "All cells have valid trust and recovery coordinators."
    elif worst == "YELLOW":
        report.overall_reason = "Some cells missing recovery coordinators or trust approaching expiry."
    elif worst == "ORANGE":
        report.overall_reason = "Trust expired or recovery unverified for one or more cells."
    else:
        report.overall_reason = "Critical federation readiness issue — some cells have no recovery path."

    return report


def _score_cell(
    cell: CellRegistryEntry,
    federation: FederationState,
    now_str: str,
) -> tuple[str, str]:
    coordinators = federation.coordinators_for(cell.cell_id)
    trusts       = federation.trust_relationships

    # Check trust validity
    trust_issues = []
    for t in trusts:
        if t.from_cell != cell.cell_id and t.to_cell != cell.cell_id:
            continue
        result = verify_trust(t)
        if not result.valid:
            trust_issues.append(result.reason)

    # No recovery coordinator
    if not coordinators:
        return "YELLOW", "No recovery coordinator declared for this cell."

    # Recovery relationships not verified
    rec_rels = federation.get_recovery(cell.cell_id)
    unverified = [r for r in rec_rels if r.status == "unverified"]
    if unverified:
        return "ORANGE", f"Recovery relationship(s) unverified for {cell.cell_id}."

    if trust_issues:
        severity = "ORANGE" if any("expired" in i.lower() or "revoked" in i.lower()
                                   for i in trust_issues) else "YELLOW"
        return severity, "; ".join(trust_issues[:2])

    return "GREEN", f"Trust valid; coordinator(s): {', '.join(coordinators)}."


# ---------------------------------------------------------------------------
# Tier 3 Assessment Engine (19.7)
# ---------------------------------------------------------------------------

@dataclass
class Tier3AssessmentResult:
    """Cross-cell assessment result."""
    assessed_at:      str
    federation_score: str
    per_cell:         list[CellFederationScore] = field(default_factory=list)
    total_cells:      int = 0
    findings:         list[dict] = field(default_factory=list)


class Tier3AssessmentEngine:
    """
    Tier 3 assessment engine — cross-cell, federation-scope.

    Reads all cell states from the twin (or provided directly) and produces
    a federation-level readiness assessment.
    """

    def __init__(
        self,
        federation:      FederationState,
        cell_cap_states: Optional[dict] = None,   # {cell_id: capability_state_dict}
        now_fn:          Optional[Callable[[], str]] = None,
    ):
        self.federation      = federation
        self.cell_cap_states = cell_cap_states or {}
        self.now_fn          = now_fn

    def assess(self) -> Tier3AssessmentResult:
        """Run cross-cell assessment. Returns Tier3AssessmentResult."""
        now = _now_iso(self.now_fn)
        fed_report = score_federation_readiness(self.federation, now_fn=self.now_fn)

        findings: list[dict] = []

        # Check trust expiry warnings
        for t in self.federation.trust_relationships:
            days = t.days_until_expiry
            if days is not None:
                if days <= 0:
                    findings.append({
                        "severity": "RED",
                        "category": "trust_expiry",
                        "message":  f"Trust {t.relationship_id} ({t.from_cell}→{t.to_cell}) EXPIRED",
                    })
                elif days <= 14:
                    findings.append({
                        "severity": "ORANGE",
                        "category": "trust_expiry",
                        "message":  f"Trust {t.relationship_id} expires in {days}d",
                    })
                elif days <= 30:
                    findings.append({
                        "severity": "YELLOW",
                        "category": "trust_expiry",
                        "message":  f"Trust {t.relationship_id} expires in {days}d",
                    })

        # Check cells with no coordinator
        for cell in self.federation.cells:
            if cell.is_active and not self.federation.coordinators_for(cell.cell_id):
                findings.append({
                    "severity": "YELLOW",
                    "category": "no_coordinator",
                    "message":  f"Cell {cell.cell_id} has no recovery coordinator",
                })

        # Check cross-capability coverage (if capability states provided)
        if len(self.cell_cap_states) > 1:
            cap_coverage = {}
            for cell_id, cap_state in self.cell_cap_states.items():
                for cap in (cap_state.get("capabilities") or []):
                    cap_id = cap.get("id")
                    if cap_id and cap.get("status") == "active":
                        if cap_id not in cap_coverage:
                            cap_coverage[cap_id] = []
                        cap_coverage[cap_id].append(cell_id)
            # Capabilities only on one cell (SPOF)
            for cap_id, cells in cap_coverage.items():
                if len(cells) == 1:
                    findings.append({
                        "severity": "YELLOW",
                        "category": "capability_spof",
                        "message":  f"Capability '{cap_id}' on only 1 cell ({cells[0]}) — single point of failure",
                    })

        return Tier3AssessmentResult(
            assessed_at=now,
            federation_score=fed_report.overall_score,
            per_cell=fed_report.cell_scores,
            total_cells=fed_report.total_cells,
            findings=findings,
        )


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def federation_state_to_dict(state: FederationState) -> dict:
    """Convert FederationState to a JSON-serialisable dict."""
    return {
        "schema_version":   "1.0",
        "federation_id":    state.federation_id,
        "federation_name":  state.federation_name,
        "declared_at":      state.declared_at,
        "notes":            state.notes,
        "cells": [
            {
                "cell_id":       c.cell_id,
                "registered_at": c.registered_at,
                "hostname":      c.hostname,
                "domain":        c.domain,
                "fqdn":          c.fqdn,
                "endpoint":      c.endpoint,
                "status":        c.status,
                "last_seen_at":  c.last_seen_at,
                "capabilities":  c.capabilities,
                "notes":         c.notes,
            }
            for c in state.cells
        ],
        "trust_relationships": [
            {
                "relationship_id":  t.relationship_id,
                "from_cell":        t.from_cell,
                "to_cell":          t.to_cell,
                "relationship_type": t.relationship_type,
                "declared_at":      t.declared_at,
                "expires_at":       t.expires_at,
                "verified_at":      t.verified_at,
                "status":           t.status,
                "reverify_days":    t.reverify_days,
                "notes":            t.notes,
            }
            for t in state.trust_relationships
        ],
        "recovery_relationships": [
            {
                "relationship_id":  r.relationship_id,
                "subject_cell":     r.subject_cell,
                "coordinator_cell": r.coordinator_cell,
                "declared_at":      r.declared_at,
                "backup_locations": r.backup_locations,
                "verified_at":      r.verified_at,
                "status":           r.status,
                "last_backup_at":   r.last_backup_at,
                "rto_minutes":      r.rto_minutes,
                "rpo_hours":        r.rpo_hours,
                "notes":            r.notes,
            }
            for r in state.recovery_relationships
        ],
    }


def build_federation_state(
    federation_id:   str,
    *,
    federation_name: Optional[str] = None,
    now_fn:          Optional[Callable[[], str]] = None,
) -> FederationState:
    """Create a new empty FederationState."""
    now = _now_iso(now_fn)
    return FederationState(
        federation_id=federation_id,
        declared_at=now,
        federation_name=federation_name,
    )
