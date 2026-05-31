# Assessment Engine — Roadmap

Version: 5.0
Last updated: 2026-05-31
Architecture: v5.0 (see ARCHITECTURE.md and docs/ARCHITECTURE-REVIEW-v5.md)

---

## Completed

- [x] Phase 1: Core assessment engine (Tier 2 foundation)
- [x] Phase 2: Assessment history store
- [x] Phase 3: Forgejo integration and repository export
- [x] Phase 4: Bootstrap assessment package (proxmox-audit-package-v1)
- [x] Milestone 5.1: Data Model Formalization (five schemas)
- [x] Milestone 5.2: Tier 1 Bootstrap Assessment Rebuild
- [x] Milestone 5.3: Bootstrap Documentation Generator
- [x] Milestone 5.4: Recovery Documentation Generator
- [x] Milestone 5.5: Recovery Readiness Scoring (with backup inventory)
- [x] Milestone 5.6: Historical State Integration (drift detection, snapshot index, reproducibility)

---

## Roadmap Overview

Phases are organized into three tracks that must be completed in order.

**Track 1 — Cell-Scoped Foundation (Phases 6–12)**
Complete the single-cell documentation and reconstruction capability.
All schemas in this track are updated to carry `cell_id` (federation-readiness gate).

**Track 2 — Expanded State Model (Phases 13–18)**
Add the new state categories required by v5.0: Hardware, Platform, Cluster, Storage,
External Dependencies, Data Protection, Observability, Capability, Federation State.

**Track 3 — Digital Twin and Federation (Phases 19–25)**
Build the Digital Twin platform, federation architecture, federated reconstruction,
and continuous assessment capability.

Track 2 begins after Phase 12 validates single-cell reconstruction.
Track 3 begins after Phase 18 completes the expanded state model.

---

## Track 1 — Cell-Scoped Foundation

### Phase 6 — Bootstrap State

**6.1 — Bootstrap State Schema and Repository Structure**
- [ ] `data-model/bootstrap-state-schema.json` (Cloud-Init, image registry, templates,
      provenance, secret registry, DNS registry, service contracts, hardware requirements)
- [ ] `data-model/service-state-schema.json`
- [ ] `cell_id` field in both schemas
- [ ] `proxmox-bootstrap/` repository structure
- [ ] Schema validation tests

**6.2 — Cloud-Init Template Library**
- [ ] Cloud-Init user-data per VM role
- [ ] Cloud-Init network-config per VM
- [ ] Proxmox vendor-data snippet
- [ ] Snippet upload procedure documentation

**6.3 — Secret Registry**
- [ ] `secret-registry.yaml` schema with `owning_cell` field (federation-readiness)
- [ ] Initial registry entries for all known secrets
- [ ] Secret registry reader in doc-gen
- [ ] Wire into recovery documentation (pre-populate secret retrieval steps)
- [ ] Secret registry completeness in readiness scorer (ORANGE if missing)

**6.4 — DNS Registry**
- [ ] `dns-registry.yaml` schema
- [ ] Initial registry entries for all VMs
- [ ] DNS registry reader in doc-gen
- [ ] Wire into recovery runbook (replace `[VM_IP]` placeholders)
- [ ] DNS registry completeness in readiness scorer (YELLOW if missing)

**6.5 — Deployment Provenance**
- [ ] Provenance record schema
- [ ] Provenance recorder (captures tofu workspace, ansible commit, cloud-init hash)
- [ ] Provenance collector in Tier 2 assessment
- [ ] Provenance completeness in readiness scorer (YELLOW if missing)
- [ ] Wire into recovery documentation

**6.6 — Template Registry and Base Image Tracking**
- [ ] Template registry schema
- [ ] Initial registry entries
- [ ] Template registry reader in doc-gen
- [ ] Template registry completeness in readiness scorer (ORANGE if missing)
- [ ] Template rebuild playbook format

**6.7 — Tier 2 Bootstrap State Collector**
- [ ] `assessment/tier2/collectors/bootstrap_state.py`
- [ ] Cloud-Init snippet comparison (deployed vs. repository)
- [ ] Integration into Tier 2 manifest
- [ ] Tests

**6.8 — Bootstrap Documentation Update**
- [ ] Bootstrap Workbook Stage 02: template creation from registry
- [ ] Bootstrap Workbook Stage 03–N: Cloud-Init pre-populated from Bootstrap State
- [ ] Replace `[CLOUD_INIT_PATH]` and `[VM_IP]` with registry data
- [ ] End-to-end test

### Phase 7 — Service State

**7.1 — Service Contract Implementation**
- [ ] Service Contract YAML spec format
- [ ] Initial contracts for all known VMs
- [ ] Service contract reader in Tier 2 collector
- [ ] Service contract validator (observed vs. declared)
- [ ] Dependency graph builder updated to use contracts as primary source

**7.2 — Service State Schema and Collection**
- [ ] Finalise `service-state-schema.json` with `cell_id`
- [ ] Service state collector
- [ ] Service state in Tier 2 manifest
- [ ] Service contract completeness in readiness scorer

**7.3 — External Dependency State (Phase 7 addition from v5.0)**
- [ ] `data-model/external-dependency-state-schema.json`
- [ ] External dependency declaration format (DNS provider, SMTP, cert authority)
- [ ] Certificate expiry monitoring (ORANGE if ≤ 30 days)
- [ ] External dependency section in Recovery Runbook

**7.4 — Recovery Documentation Update (Service Layer)**
- [ ] Service contract validation steps in recovery runbook
- [ ] Service health check commands (from contract `health_check` field)
- [ ] Service restart/verification commands
- [ ] Dependency graph: Service Contract edges shown distinctly

### Phase 8 — Network Topology as Code

- [ ] 8.1: Network topology OpenTofu resources (bridges, VLANs, firewall rules)
- [ ] 8.2: Network topology collector (compare observed vs. declared)
- [ ] 8.3: Network topology drift detection
- [ ] 8.4: Recovery documentation Wave 0: network reconstruction from code
- [ ] 8.5: Network topology completeness in readiness scorer

### Phase 9 — Reconstruction Playbooks

- [ ] 9.1: Reconstruction playbook format and schema
- [ ] 9.2: Playbook generator (from state model) — organized under `reconstruction/<cell_id>/`
- [ ] 9.3: Wave 0 (host restore) playbook
- [ ] 9.4: Wave 0.5 (template rebuild) playbook
- [ ] 9.5: Per-VM reconstruction playbook
- [ ] 9.6: Orchestrated `run-all.sh` generator
- [ ] 9.7: Playbook validator (syntax check + dependency check)
- [ ] 9.8: Playbook existence in readiness scorer

### Phase 10 — Operational Documentation

- [ ] 10.1: Operational documentation class design
- [ ] 10.2: Drift summary renderer
- [ ] 10.3: Capacity trend renderer
- [ ] 10.4: Service health summary renderer
- [ ] 10.5: Secret registry completeness renderer
- [ ] 10.6: Wire into engine.py (`--mode operational`)
- [ ] 10.7: Scheduled refresh

### Phase 11 — Capacity Model

- [ ] 11.1: Capacity model schema
- [ ] 11.2: Capacity tracking in Tier 2 assessment
- [ ] 11.3: Capacity validation in readiness scorer
- [ ] 11.4: Capacity trend analysis and projection
- [ ] 11.5: ORANGE if target host cannot accommodate restored workload

### Phase 12 — Full Single-Cell Reconstruction Test

- [ ] 12.1: End-to-end reconstruction drill (full destroy + reconstruct from repos)
- [ ] 12.2: Reconstruction time measurement vs. estimate
- [ ] 12.3: Gap identification and remediation
- [ ] 12.4: Reconstruction drill procedure as a scheduled activity

**Gate:** Phase 12 completion validates the single-cell foundation.
Track 2 begins after Phase 12.

---

## Track 2 — Expanded State Model

### Phase 13 — Hardware and Platform State

- [ ] 13.1: `data-model/hardware-state-schema.json` (BIOS, firmware, disks, NICs, UPS)
- [ ] 13.2: Hardware State Tier 1 collector (extend bootstrap assessment)
- [ ] 13.3: `data-model/platform-state-schema.json` (Proxmox config, certs, packages)
- [ ] 13.4: Platform State Tier 2 collector
- [ ] 13.5: Hardware requirements declaration in Bootstrap State
- [ ] 13.6: Pre-reconstruction hardware verification playbook
- [ ] 13.7: Hardware and Platform readiness scoring

### Phase 14 — Cluster and Storage State

- [ ] 14.1: `data-model/cluster-state-schema.json` (identity, topology, membership, history)
- [ ] 14.2: Cluster State collector (Proxmox cluster API, Corosync, HA manager)
- [ ] 14.3: `data-model/storage-state-schema.json` (ZFS, Ceph, CephFS, RBD, datastores)
- [ ] 14.4: Storage State collector (ZFS CLI, Ceph status API)
- [ ] 14.5: Ceph FSID in readiness scorer (RED if missing)
- [ ] 14.6: Cluster and Storage waves in Reconstruction Playbook generator

### Phase 15 — Data Protection State

- [ ] 15.1: `data-model/data-protection-state-schema.json` (PBS, jobs, retention, RTO/RPO)
- [ ] 15.2: Data Protection collector (PBS API, backup job inventory, verification status)
- [ ] 15.3: RTO/RPO declaration format and compliance scoring
- [ ] 15.4: Backup encryption key recoverability check (RED if not recoverable)
- [ ] 15.5: PBS self-recovery plan check (ORANGE if absent)
- [ ] 15.6: Data Protection readiness scoring additions

### Phase 16 — Observability State

- [ ] 16.1: `data-model/observability-state-schema.json` (monitoring stack, alerts, dashboards)
- [ ] 16.2: Observability State collector
- [ ] 16.3: Observability reconstruction in playbook generator
- [ ] 16.4: Alert rule restoration in Recovery Runbook

### Phase 17 — Digital Twin Foundation

- [ ] 17.1: Cell Identity schema and registry (`twin/federation/cells/`)
- [ ] 17.2: Twin storage layout (full `twin/` directory structure)
- [ ] 17.3: Twin state writer (all collectors write to twin, not only history/)
- [ ] 17.4: Staleness manifest (per-field confidence and last-updated tracking)
- [ ] 17.5: Twin consistency checker (stale, missing, conflicting state detection)
- [ ] **17.6: `cell_id` migration — all existing schemas updated (federation gate)**

### Phase 18 — Capability and Secret Reference State

- [ ] 18.1: `data-model/capability-state-schema.json` (all capability categories)
- [ ] 18.2: Capability declaration format and initial declaration
- [ ] 18.3: Capability verification in Tier 2 assessment
- [ ] 18.4: Capability index builder (aggregation across all cells)
- [ ] 18.5: `data-model/secret-reference-state-schema.json` (standalone, with `owning_cell`)
- [ ] 18.6: Secret Reference State migration (extract from Bootstrap State)
- [ ] 18.7: Capability-based readiness scoring additions

**Gate:** Phase 18 completion validates the expanded state model.
Track 3 begins after Phase 18.

---

## Track 3 — Digital Twin and Federation

### Phase 19 — Federation State and Trust Model

- [ ] 19.1: `data-model/federation-state-schema.json` (cell registry, relationships, trust)
- [ ] 19.2: Cell identity and federation registry
- [ ] 19.3: Trust relationship schema and declaration format (all relationship types)
- [ ] 19.4: Trust relationship verification procedure (CLI + automated check)
- [ ] 19.5: Recovery relationship schema and declaration format
- [ ] 19.6: Recovery relationship verification (backup reachable, history readable)
- [ ] 19.7: Tier 3 assessment engine (cross-cell, federation-scope)
- [ ] 19.8: Federation State tests

### Phase 20 — Federation Documentation Generation

- [ ] 20.1: Federation Workbook renderer (all cells, all relationships, federation readiness)
- [ ] 20.2: Federation Runbook renderer (coordination procedures)
- [ ] 20.3: Cell Workbook (full 17-state view per cell)
- [ ] 20.4: Cell Runbook (full cell reconstruction)
- [ ] 20.5: Cluster Workbook and Runbook
- [ ] 20.6: Node Workbook and Runbook
- [ ] 20.7: Dependency Workbook (all five graph types, multi-cell scope)
- [ ] 20.8: Command Reference Sheets (pre-populated for all known values)
- [ ] 20.9: Validation Sheets (post-recovery checklists)

### Phase 21 — Failure Domain Modeling

- [ ] 21.1: Failure domain taxonomy schema
- [ ] 21.2: Failure propagation rules engine (storage → VMs → services propagation)
- [ ] 21.3: Blast radius calculator (given failure at level X, enumerate affected)
- [ ] 21.4: SPOF detection (components with no recovery alternative)
- [ ] 21.5: Circular recovery dependency detection
- [ ] 21.6: Failure domain analysis in readiness reports

### Phase 22 — Multi-Level Readiness Assessment

- [ ] 22.1: Hardware-level readiness scoring (new inputs from Phase 13)
- [ ] 22.2: Cluster-level readiness scoring (new inputs from Phase 14)
- [ ] 22.3: Cell-level readiness (aggregation across all 17 state categories)
- [ ] 22.4: Federation-level readiness (aggregation across all cells)
- [ ] 22.5: Federation Readiness Report
- [ ] 22.6: Tier 3 assessment integration with multi-level readiness

### Phase 23 — Federated Reconstruction Planning

- [ ] 23.1: Recovery coordinator model (coordinator selection from capability index)
- [ ] 23.2: Recovery package assembly (history, docs, repos, secrets, backup locations)
- [ ] 23.3: Capability matching (find available cells for each recovery need)
- [ ] 23.4: Multi-phase reconstruction playbook generator (all 7 phases)
- [ ] 23.5: Cross-cell trust establishment automation
- [ ] 23.6: Temporary workload migration planning
- [ ] 23.7: Federated reconstruction tests

### Phase 24 — Continuous Assessment and Twin Maintenance

- [ ] 24.1: Scheduled assessment framework (cron-driven, cell-scoped)
- [ ] 24.2: Repository ingestion hooks (git webhook → twin update on push)
- [ ] 24.3: Deployment event hooks (tofu apply / ansible run → twin update)
- [ ] 24.4: Staleness alerting (notify when state categories exceed threshold)
- [ ] 24.5: Twin diff reporting (what changed in the twin since last report)
- [ ] 24.6: PBS API integration for continuous Data Protection State updates
- [ ] 24.7: Certificate expiry monitoring (continuous External Dependency State)

### Phase 25 — Reconstruction Validation

- [ ] 25.1: Reconstruction drill framework (scheduled full-destroy + reconstruct)
- [ ] 25.2: Reconstruction time measurement and RTO validation
- [ ] 25.3: Automated post-reconstruction assessment and comparison
- [ ] 25.4: Gap identification and remediation tracking
- [ ] 25.5: Federation reconstruction drill (multi-cell coordinated scenario)

---

## Design Principles

1. **Reconstruction is the objective.** Every state category, metadata field, and
   documentation artifact is evaluated against: "Does this enable reconstruction
   from repository state after complete infrastructure loss?"

2. **Documentation is generated, not authored.** Technical infrastructure information
   is collected automatically. Operators provide only what cannot be discovered.

3. **Cell scope is universal.** `cell_id` is mandatory on every state document.
   No single-environment assumptions anywhere in the data model.

4. **The Digital Twin is the source of truth.** All outputs derive from the twin.

5. **Recovery relationships are explicit.** Which cell holds what for whom is
   declared and verified, not assumed.

6. **Missing information is surfaced, never silently omitted.** UNRESOLVED and
   STALE fields are always visible with reason, impact, and remediation guidance.

7. **Trust is declared and verified.** Inter-cell trust has expiry, is verified at
   Tier 3 assessment, and expired trust degrades federation readiness scores.

8. **Historical snapshots are reproducible.** Same twin state always produces same outputs.

9. **Readiness scoring is honest.** RED means recovery will likely fail.

10. **Single-cell work must be federation-ready from the start.** `cell_id` in all
    schemas. Recovery playbooks organized by cell. Documentation scoped by cell.
    The federation layer is added above, not retrofitted below.
