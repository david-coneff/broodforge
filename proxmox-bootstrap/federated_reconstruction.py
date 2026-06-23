#!/usr/bin/env python3
"""
federated_reconstruction.py — Federated Reconstruction Planning (Phase 23).

Plans cross-cell coordinated reconstruction: when a cell fails, this module
identifies the best coordinator, matches capabilities, generates a multi-phase
reconstruction playbook, and plans temporary workload migration.

23.1  RecoveryCoordinator    — select best coordinator from capability index
23.2  PhoenixPackageManifest — what a federated phoenix package contains
23.3  match_capabilities()   — find cells that can fulfill each recovery need
23.4  FederatedPlaybook      — multi-phase cross-cell reconstruction plan
23.5  plan_trust_establishment() — steps to establish cross-cell trust
23.6  plan_workload_migration()  — temporary migration plan
23.7  Tests in test_phase23_federated_reconstruction.py

Provides:
  CoordinatorScore          — scored candidate coordinator
  select_coordinator()      — pick best coordinator for a subject cell
  PhoenixPackageManifest    — federated phoenix package contents declaration
  CapabilityMatchResult     — which cells can fulfill a need
  match_capabilities()      — find available cells per capability
  FederatedReconstructionPlan — complete federated reconstruction plan
  plan_trust_establishment()  — steps to establish/verify cross-cell trust
  WorkloadMigrationPlan     — temporary migration steps
  plan_workload_migration()  — generate migration plan
  build_federated_plan()    — assemble full plan

Stdlib only.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# ---------------------------------------------------------------------------
# 23.1 — Recovery Coordinator Selection
# ---------------------------------------------------------------------------

@dataclass
class CoordinatorScore:
    """A candidate coordinator cell with its suitability score."""
    cell_id:           str
    score:             float    # 0.0 (worst) – 1.0 (best)
    reasons:           list[str] = field(default_factory=list)
    capabilities:      list[str] = field(default_factory=list)
    has_backups:       bool = False
    trust_valid:       bool = False
    capacity_ok:       bool = False
    availability:      str  = "unknown"   # available|busy|unknown


def select_coordinator(
    subject_cell_id:   str,
    federation_state:  Any,           # FederationState from federation_state.py
    capability_index:  Any = None,    # CapabilityIndex from capability_state.py
) -> list[CoordinatorScore]:
    """
    Select and rank candidate coordinator cells for a subject cell.

    Scoring factors:
      +0.4  Has declared recovery relationship with subject
      +0.3  All declared backup locations present
      +0.2  Trust relationship valid (not expired)
      +0.1  Has capability overlap with subject

    Returns list of CoordinatorScore sorted by score descending.
    """
    candidates: list[CoordinatorScore] = []

    for cell in federation_state.cells:
        if cell.cell_id == subject_cell_id:
            continue
        if not cell.is_active:
            continue

        score  = 0.0
        reasons: list[str] = []

        # Has recovery relationship?
        rec_rels = [r for r in federation_state.recovery_relationships
                    if r.subject_cell == subject_cell_id
                    and r.coordinator_cell == cell.cell_id]
        has_backups = bool(rec_rels and any(r.backup_locations for r in rec_rels))
        if rec_rels:
            score += 0.4
            reasons.append("Declared recovery relationship")
        if has_backups:
            score += 0.3
            reasons.append("Backup locations declared")

        # Trust valid?
        trusts = federation_state.get_trust(subject_cell_id, cell.cell_id) + \
                 federation_state.get_trust(cell.cell_id, subject_cell_id)
        trust_valid = any(t.status == "active" and not t.is_expired for t in trusts)
        if trust_valid:
            score += 0.2
            reasons.append("Trust relationship active")

        # Capability overlap?
        subject_caps = _get_cell_caps(subject_cell_id, capability_index)
        coord_caps   = _get_cell_caps(cell.cell_id, capability_index)
        overlap      = set(subject_caps) & set(coord_caps)
        if overlap:
            score += 0.1
            reasons.append(f"Capability overlap: {', '.join(list(overlap)[:3])}")

        candidates.append(CoordinatorScore(
            cell_id=cell.cell_id,
            score=score,
            reasons=reasons,
            capabilities=coord_caps,
            has_backups=has_backups,
            trust_valid=trust_valid,
        ))

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates


def _get_cell_caps(cell_id: str, cap_index: Any) -> list[str]:
    if cap_index is None:
        return []
    if hasattr(cap_index, "capabilities_of"):
        return cap_index.capabilities_of(cell_id)
    return []


# ---------------------------------------------------------------------------
# 23.2 — Phoenix Package Manifest
# ---------------------------------------------------------------------------

@dataclass
class PhoenixPackageManifest:
    """
    Declares the contents of a federated phoenix package.

    A federated phoenix package is assembled by the coordinator cell and
    contains everything the subject cell needs to reconstruct itself.
    """
    package_id:         str
    subject_cell:       str
    coordinator_cell:   str
    generated_at:       str
    contents:           list[dict]  = field(default_factory=list)
    # Each content entry: {type, description, source_path, included: bool}
    backup_snapshot_ids: list[str]  = field(default_factory=list)
    trust_tokens:       list[dict]  = field(default_factory=list)
    # trust_tokens: [{cell_id, token_type, expires_at}]
    estimated_size_mb:  Optional[float] = None
    notes:              Optional[str]   = None


def build_phoenix_package_manifest(
    subject_cell:     str,
    coordinator_cell: str,
    recovery_rel:     Any,    # RecoveryRelationship
    *,
    bootstrap_state:  dict | None  = None,
    now_fn:           Callable[[], str] | None = None,
) -> PhoenixPackageManifest:
    """Build a PhoenixPackageManifest from a recovery relationship."""
    import hashlib
    from datetime import datetime, timezone
    now  = (now_fn or (lambda: datetime.now(timezone.utc).isoformat()))()
    pid  = hashlib.sha256(f"{subject_cell}:{coordinator_cell}:{now}".encode()).hexdigest()[:12]

    contents = [
        {"type": "backup_snapshots",   "description": "PBS or restic snapshot sets",
         "included": bool(getattr(recovery_rel, "backup_locations", []))},
        {"type": "bootstrap_state",    "description": "bootstrap-state.json for subject cell",
         "included": bool(bootstrap_state)},
        {"type": "gitops_history",     "description": "Forgejo repository history",
         "included": False},
        {"type": "secret_references",  "description": "KeePass path references (no values)",
         "included": True},
        {"type": "phoenix_playbook",   "description": "Generated phoenix playbook",
         "included": True},
        {"type": "trust_tokens",       "description": "Temporary cross-cell trust tokens",
         "included": True},
    ]

    return PhoenixPackageManifest(
        package_id=pid,
        subject_cell=subject_cell,
        coordinator_cell=coordinator_cell,
        generated_at=now,
        contents=contents,
    )


# ---------------------------------------------------------------------------
# 23.3 — Capability Matching
# ---------------------------------------------------------------------------

@dataclass
class CapabilityMatchResult:
    """Result of matching a capability need to available cells."""
    capability_id:   str
    needed_by:       str      # subject_cell that needs this
    available_cells: list[str] = field(default_factory=list)
    matched:         bool      = False
    gap_reason:      Optional[str] = None


def match_capabilities(
    subject_cell_id:  str,
    needed_caps:      list[str],
    capability_index: Any,     # CapabilityIndex
    exclude_cells:    list[str] | None = None,
) -> list[CapabilityMatchResult]:
    """
    For each needed capability, find available cells that have it.

    Returns one CapabilityMatchResult per capability_id.
    """
    excluded = set(exclude_cells or []) | {subject_cell_id}
    results  = []

    for cap_id in needed_caps:
        available = [
            c for c in (capability_index.cells_with(cap_id) if capability_index else [])
            if c not in excluded
        ]
        results.append(CapabilityMatchResult(
            capability_id=cap_id,
            needed_by=subject_cell_id,
            available_cells=available,
            matched=bool(available),
            gap_reason=None if available else f"No other cell provides {cap_id}",
        ))

    return results


# ---------------------------------------------------------------------------
# 23.4 — Federated Reconstruction Plan
# ---------------------------------------------------------------------------

@dataclass
class FederatedPhase:
    """One phase in a federated reconstruction plan."""
    phase_number:    int
    name:            str
    responsible:     str        # which cell executes this phase
    description:     str
    steps:           list[str]  = field(default_factory=list)
    prerequisites:   list[str]  = field(default_factory=list)
    estimated_minutes: Optional[int] = None


@dataclass
class FederatedReconstructionPlan:
    """Multi-phase cross-cell reconstruction plan."""
    plan_id:          str
    subject_cell:     str
    coordinator_cell: str
    generated_at:     str
    phases:           list[FederatedPhase] = field(default_factory=list)
    trust_steps:      list[str]            = field(default_factory=list)
    migration_plan:   Any                  = None   # WorkloadMigrationPlan
    notes:            Optional[str]        = None

    @property
    def total_estimated_minutes(self) -> int:
        return sum(p.estimated_minutes or 0 for p in self.phases)


def build_federated_plan(
    subject_cell:    str,
    coordinator:     CoordinatorScore,
    federation_state: Any,
    *,
    bootstrap_state: dict | None = None,
    capability_index: Any        = None,
    now_fn:          Callable[[], str] | None = None,
) -> FederatedReconstructionPlan:
    """
    Build a complete federated reconstruction plan.

    Phase sequence:
      0. Trust establishment (coordinator → subject)
      1. Bootstrap state retrieval from coordinator
      2. Hardware provisioning (human-driven)
      3. Proxmox installation and configuration
      4. Backup restore (coordinator-provided)
      5. Service verification
      6. Trust re-registration (subject re-enters federation)
    """
    import hashlib
    from datetime import datetime, timezone
    now  = (now_fn or (lambda: datetime.now(timezone.utc).isoformat()))()
    pid  = hashlib.sha256(f"fed:{subject_cell}:{coordinator.cell_id}:{now}".encode()).hexdigest()[:12]

    coord = coordinator.cell_id
    subj  = subject_cell

    phases = [
        FederatedPhase(0, "Trust Establishment", coord,
                       f"Coordinator {coord} generates temporary trust tokens for {subj}",
                       steps=[
                           f"On {coord}: generate temporary headscale auth key for {subj}",
                           f"On {coord}: generate temporary KeePass gate token",
                           "Verify federation-state.json shows trust active",
                       ],
                       estimated_minutes=5),
        FederatedPhase(1, "Bootstrap State Retrieval", coord,
                       f"Retrieve {subj} bootstrap state from coordinator",
                       steps=[
                           f"On {coord}: locate latest bootstrap-state.json for {subj}",
                           f"On {coord}: decrypt and verify backup integrity",
                           "Transfer bootstrap-state.json to reconstruction host",
                       ],
                       prerequisites=["Trust Establishment"],
                       estimated_minutes=10),
        FederatedPhase(2, "Hardware Provisioning", "[HUMAN]",
                       "Provision replacement hardware (operator-driven)",
                       steps=[
                           "Install Proxmox on replacement hardware",
                           "Verify hardware meets minimum requirements",
                           "Connect to management network",
                       ],
                       prerequisites=["Bootstrap State Retrieval"],
                       estimated_minutes=30),
        FederatedPhase(3, "Proxmox Configuration", subj,
                       f"Configure Proxmox host to match {subj} bootstrap state",
                       steps=[
                           "Run forge.sh phase-03 from bootstrap state",
                           "Recreate network bridges",
                           "Recreate ZFS pool",
                           f"Rejoin Proxmox cluster (pvecm add {coord})",
                       ],
                       prerequisites=["Hardware Provisioning"],
                       estimated_minutes=20),
        FederatedPhase(4, "Backup Restore", coord,
                       f"Restore VMs and data from {coord} backup locations",
                       steps=[
                           f"On {coord}: unlock KeePass gate",
                           f"On {coord}: python3 restore-from-backup.py --latest --target {subj}",
                           "Verify VM disk integrity after restore",
                           "Start restored VMs",
                       ],
                       prerequisites=["Proxmox Configuration"],
                       estimated_minutes=45),
        FederatedPhase(5, "Service Verification", subj,
                       "Verify all services healthy after restore",
                       steps=[
                           "Run assessment engine: python3 engine.py --mode recovery",
                           "Check k3s node status: kubectl get nodes",
                           "Run per-service health checks from recovery runbook",
                           "Confirm readiness score GREEN",
                       ],
                       prerequisites=["Backup Restore"],
                       estimated_minutes=15),
        FederatedPhase(6, "Federation Re-registration", subj,
                       f"Re-register {subj} in federation and restore trust",
                       steps=[
                           "Update federation-state.json: cell status → active",
                           "Re-declare trust relationships",
                           "Verify cross-cell connectivity",
                           "Run Tier 3 assessment",
                       ],
                       prerequisites=["Service Verification"],
                       estimated_minutes=10),
    ]

    return FederatedReconstructionPlan(
        plan_id=pid,
        subject_cell=subject_cell,
        coordinator_cell=coord,
        generated_at=now,
        phases=phases,
    )


# ---------------------------------------------------------------------------
# 23.5 — Trust Establishment Steps
# ---------------------------------------------------------------------------

def plan_trust_establishment(
    subject_cell:     str,
    coordinator_cell: str,
    federation_state: Any,
) -> list[str]:
    """
    Generate ordered steps to establish or verify cross-cell trust.

    Used when initiating a federated reconstruction where trust is
    currently unverified or expired.
    """
    steps = [
        f"1. Verify {coordinator_cell} is reachable: ping/curl {coordinator_cell} endpoint",
        f"2. On {coordinator_cell}: confirm trust relationship for {subject_cell} is active",
        f"3. On {coordinator_cell}: headscale preauthkeys create --expiration 1h --user broodforge",
        f"4. On {coordinator_cell}: generate temporary KeePass read-only token",
        "5. Securely transfer tokens to reconstruction host",
        "6. Update federation-state.json: trust verified_at = now",
        "7. Run Tier 3 assessment to confirm trust score GREEN",
    ]
    return steps


# ---------------------------------------------------------------------------
# 23.6 — Workload Migration Plan
# ---------------------------------------------------------------------------

@dataclass
class MigrationStep:
    step_number: int
    action:      str
    responsible: str
    description: str
    reversible:  bool  = True
    commands:    list[str] = field(default_factory=list)


@dataclass
class WorkloadMigrationPlan:
    """Temporary workload migration from failing cell to coordinator."""
    plan_id:             str
    source_cell:         str
    destination_cell:    str
    workloads:           list[str]    # k3s workloads / service names to migrate
    steps:               list[MigrationStep] = field(default_factory=list)
    estimated_minutes:   Optional[int]       = None
    notes:               Optional[str]       = None


def plan_workload_migration(
    source_cell:      str,
    destination_cell: str,
    workloads:        list[str],
    *,
    now_fn: Callable[[], str] | None = None,
) -> WorkloadMigrationPlan:
    """
    Generate a temporary workload migration plan.

    Steps: drain source → migrate → verify on destination → update DNS
    """
    import hashlib
    from datetime import datetime, timezone
    now = (now_fn or (lambda: datetime.now(timezone.utc).isoformat()))()
    pid = hashlib.sha256(f"mig:{source_cell}:{destination_cell}:{now}".encode()).hexdigest()[:12]

    steps = [
        MigrationStep(1, "Cordon source node", source_cell,
                      "Prevent new workloads scheduling on failing cell",
                      commands=["kubectl cordon <node-name>"]),
        MigrationStep(2, "Drain source node", source_cell,
                      "Evict existing pods gracefully",
                      commands=["kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data"]),
        MigrationStep(3, "Verify workloads on destination", destination_cell,
                      "Confirm all workloads rescheduled successfully",
                      commands=["kubectl get pods -A -o wide | grep <destination-node>"]),
        MigrationStep(4, "Update DNS if needed", "[HUMAN]",
                      "Update split-horizon DNS if services have node-specific IPs",
                      reversible=False,
                      commands=["python3 generate-dnsmasq-config.py && systemctl reload dnsmasq"]),
        MigrationStep(5, "Verify service health", destination_cell,
                      "Run health checks for all migrated services",
                      commands=["python3 engine.py --mode operational"]),
    ]

    return WorkloadMigrationPlan(
        plan_id=pid,
        source_cell=source_cell,
        destination_cell=destination_cell,
        workloads=workloads,
        steps=steps,
        estimated_minutes=25,
        notes=f"Temporary migration until {source_cell} is restored.",
    )
