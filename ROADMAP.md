# Assessment Engine — Roadmap

Version: 4.0
Last updated: 2026-05-30
Architecture: v4.0 (see ARCHITECTURE.md and docs/ARCHITECTURE-REVIEW-v4.md)

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

---

## Phase 5 — Documentation Generation Foundation (In Progress)

### Milestone 5.6 — Historical State Integration
- [ ] Implement snapshot index builder (history/index.json)
- [ ] Implement drift detector (field-level manifest diff)
- [ ] Implement documentation drift detection (which doc fields became stale)
- [ ] Wire historical state into doc-gen (populate "as of last assessment" fields)
- [ ] Verify snapshot reproducibility (regenerate docs from historical snapshot, compare)
- [ ] Write drift detection tests

---

## Phase 6 — Bootstrap State  *(v4.0)*

### Milestone 6.1 — Bootstrap State Schema and Repository Structure
- [ ] Define `data-model/bootstrap-state-schema.json`
  - Cloud-Init snippet manifests
  - Base image registry
  - Template registry
  - Deployment provenance records
  - Secret Registry
  - DNS Registry
  - Service Contract format
- [ ] Define `data-model/service-state-schema.json`
- [ ] Create `proxmox-bootstrap/` repository structure
- [ ] Write schema validation tests

### Milestone 6.2 — Cloud-Init Template Library
- [ ] Write Cloud-Init user-data templates for each VM role
  - base-ubuntu.yaml (shared base)
  - infra-bootstrap.yaml
  - forgejo.yaml
  - inventory.yaml
  - assessment-engine.yaml
- [ ] Write Cloud-Init network-config templates per VM
- [ ] Write Proxmox vendor-data snippet
- [ ] Document snippet upload procedure for Proxmox storage

### Milestone 6.3 — Secret Registry
- [ ] Define secret-registry.yaml schema
- [ ] Populate initial registry entries (all known secrets referenced in docs)
- [ ] Build secret registry reader in doc-gen
- [ ] Wire into recovery documentation (pre-populate secret retrieval steps)
- [ ] Add Secret Registry completeness to readiness scorer (ORANGE if missing)

### Milestone 6.4 — DNS Registry
- [ ] Define dns-registry.yaml schema
- [ ] Populate initial registry entries for all VMs
- [ ] Build DNS registry reader in doc-gen
- [ ] Wire into recovery runbook (replace `[VM_IP]` placeholders)
- [ ] Add DNS Registry completeness to readiness scorer (YELLOW if missing)

### Milestone 6.5 — Deployment Provenance
- [ ] Define provenance record schema
- [ ] Build provenance recorder (captures tofu workspace, ansible commit, cloud-init hash)
- [ ] Add provenance collector to Tier 2 assessment
- [ ] Add provenance completeness to readiness scorer (YELLOW if missing)
- [ ] Wire into recovery documentation

### Milestone 6.6 — Template Registry and Base Image Tracking
- [ ] Define template registry schema
- [ ] Populate initial registry entries
- [ ] Build template registry reader in doc-gen
- [ ] Add template registry completeness to readiness scorer (ORANGE if missing)
- [ ] Write template rebuild playbook format

### Milestone 6.7 — Tier 2 Bootstrap State Collector
- [ ] Build `assessment/tier2/collectors/bootstrap_state.py`
  - Reads Cloud-Init snippets from Proxmox storage (pvesm + API)
  - Reads snippet registry from proxmox-bootstrap/ via Forgejo
  - Compares deployed snippets to repository versions
  - Flags divergence as drift
- [ ] Integrate into Tier 2 assessment manifest
- [ ] Write tests

### Milestone 6.8 — Bootstrap Documentation Update
- [ ] Update Bootstrap Workbook Stage 02 (template creation from registry)
- [ ] Update Bootstrap Workbook Stage 03–N (Cloud-Init pre-populated from Bootstrap State)
- [ ] Replace `[CLOUD_INIT_PATH]` and `[VM_IP]` placeholders with registry data
- [ ] End-to-end test: Bootstrap State → pre-populated workbook

---

## Phase 7 — Service State  *(v4.0)*

### Milestone 7.1 — Service Contract Implementation
- [ ] Write Service Contract spec format (YAML)
- [ ] Create initial service contracts for all known VMs
  - forgejo.yaml
  - inventory.yaml
  - assessment-engine.yaml
- [ ] Build service contract reader in Tier 2 collector
- [ ] Build service contract validator (observed vs. declared)
- [ ] Update dependency graph builder to use Service Contracts as primary source
- [ ] Fall back to heuristics only when contracts not present

### Milestone 7.2 — Service State Schema and Collection
- [ ] Finalise service-state-schema.json
- [ ] Build service state collector (reads contracts + observed service state)
- [ ] Add service state to Tier 2 manifest
- [ ] Add service contract completeness to readiness scorer (YELLOW if missing)

### Milestone 7.3 — Recovery Documentation Update (Service Layer)
- [ ] Add service contract validation steps to recovery runbook
- [ ] Add service health check commands (from contract health_check field)
- [ ] Add service restart/verification commands
- [ ] Update dependency graph: Service Contract edges shown distinctly from heuristic edges

---

## Phase 8 — Network Topology as Code

- [ ] 8.1: Network topology OpenTofu resources (bridges, VLANs, firewall rules)
- [ ] 8.2: Network topology collector (compare observed vs. declared)
- [ ] 8.3: Network topology drift detection
- [ ] 8.4: Recovery documentation Wave 0: network reconstruction from code
- [ ] 8.5: Add network topology completeness to readiness scorer

---

## Phase 9 — Reconstruction Playbooks

- [ ] 9.1: Define reconstruction playbook format and schema
- [ ] 9.2: Build reconstruction playbook generator (from state model)
- [ ] 9.3: Build Wave 0 (host restore) playbook template
- [ ] 9.4: Build Wave 0.5 (template rebuild) playbook template
- [ ] 9.5: Build per-VM reconstruction playbook template
- [ ] 9.6: Build orchestrated run-all.sh generator
- [ ] 9.7: Reconstruction playbook validator (syntax check + dependency check)
- [ ] 9.8: Add reconstruction playbook existence to readiness scorer (YELLOW if missing)

---

## Phase 10 — Operational Documentation  *(v4.0)*

- [ ] 10.1: Operational documentation class design
- [ ] 10.2: Drift summary renderer (what changed since last assessment)
- [ ] 10.3: Capacity trend renderer (RAM, disk, CPU over time)
- [ ] 10.4: Service health summary renderer
- [ ] 10.5: Secret Registry completeness renderer
- [ ] 10.6: Wire into engine.py (--mode operational)
- [ ] 10.7: Scheduled refresh (daily or on-assessment trigger)

---

## Phase 11 — Capacity Model

- [ ] 11.1: Capacity model schema
- [ ] 11.2: Capacity tracking in Tier 2 assessment
- [ ] 11.3: Capacity validation in recovery readiness scorer
- [ ] 11.4: Capacity trend analysis and projection
- [ ] 11.5: Recovery readiness: ORANGE if target host cannot accommodate workload

---

## Phase 12 — Full Reconstruction Test

- [ ] 12.1: End-to-end reconstruction drill from repository state
- [ ] 12.2: Measure actual vs. estimated reconstruction time
- [ ] 12.3: Identify and remediate gaps found during drill
- [ ] 12.4: Document reconstruction drill procedure as a scheduled activity

---

## Design Principles (v4.0)

1. **Reconstruction is the objective.** Every state category, metadata field, and
   documentation artifact is evaluated against: "Does this enable reconstruction
   from repository state after complete infrastructure loss?"

2. **Documentation is generated, not authored.** Technical infrastructure information
   is collected automatically. Operators provide only what cannot be discovered.

3. **The provisioning layer is first-class.** Cloud-Init templates, base images,
   and first-boot configuration are managed assets, not ephemeral artifacts.

4. **Service Contracts replace heuristics.** Declared dependency contracts are more
   reliable than name-pattern matching. Heuristics are a fallback, not a foundation.

5. **Secret references are tracked, never values.** The Secret Registry enables
   automated gap detection and pre-populated recovery steps without storing secrets.

6. **Missing information is surfaced, never silently omitted.** UNRESOLVED fields
   include reason, collection guidance, and readiness impact.

7. **Historical snapshots are reproducible.** Any snapshot must regenerate the
   documentation current at that time.

8. **Readiness scoring is honest.** RED means recovery will likely fail. ORANGE means
   it will be difficult. YELLOW means it will be slower than it should be.
