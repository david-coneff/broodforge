# Current State

Last updated: 2026-05-30

## Architecture

**Current version:** 4.0 (see ARCHITECTURE.md and docs/ARCHITECTURE-REVIEW-v4.md)

**Key changes from v3.0:**
- Seven-state model (added Bootstrap State and Service State)
- Six-layer lifecycle (Infrastructure Definition → Provisioning → Configuration → Service → Assessment → Documentation)
- Cloud-Init elevated to first-class Bootstrap State
- Eight additional architectural elements identified
- Three documentation classes (Bootstrap, Operational, Recovery)

## Completed Phases

| Phase | Description | Status |
|---|---|---|
| 1–4 | Core engine, history, Forgejo, bootstrap package | Complete |
| 5.1 | Data Model Formalization (5 schemas) | Complete |
| 5.2 | Tier 1 Bootstrap Assessment Rebuild | Complete |
| 5.3 | Bootstrap Documentation Generator | Complete |
| 5.4 | Recovery Documentation Generator | Complete |
| 5.5 | Recovery Readiness Scoring | Complete |
| Architecture Review | v4.0 — 7-state model, 6-layer lifecycle | **Complete** |

## Next Milestone

**5.6 — Historical State Integration** (Phase 5 completion)

Then: **Phase 6 — Bootstrap State** (Cloud-Init, Secret Registry, DNS Registry,
Template Registry, Deployment Provenance)

## What Exists

### Schemas (data-model/)
- `observed-state-schema.json` — Tier 1/2 manifest (hardware, network, VMs, backup inventory)
- `historical-state-schema.json` — snapshot index, drift records
- `recovery-state-schema.json` — dependency graph, readiness report
- `declared-state-schema.json` — OpenTofu workspace/resource state
- `configured-state-schema.json` — Ansible inventory, role assignments
- `validate.py` — stdlib-only schema validator

*Schemas for Bootstrap State (v4.0) and Service State (v4.0) are pending Phase 6/7.*

### Assessment Package
- `assessment/tier1/` — bootstrap.sh + modular collectors + analyze.py
- Produces schema-validated manifest.json

### Documentation Generator
- `doc-gen/engine.py` — bootstrap and recovery modes
- `doc-gen/analyzers.py` — 10 DERIVED analyzers
- `doc-gen/dependencies.py` — dependency graph builder + topological sort
- `doc-gen/readiness.py` — scoring (GREEN/YELLOW/ORANGE/RED/BLOCKED + cascade)
- `doc-gen/readiness_report.py` — standalone Readiness-Report.md + .json
- `doc-gen/renderers/` — ODS and ODT generators (stdlib only)

### Generated Artifacts (reports/)
- `bootstrap_tier1/` — Bootstrap-Workbook.ods, Bootstrap-Runbook.odt
- `recovery_tier2/` — Recovery-Workbook.ods, Recovery-Runbook.odt,
  Restore-Sequence.md, Readiness-Report.md, Readiness-Report.json

### Tests
- `tests/unit/test_schema_validation.py` — 32 tests
- `tests/unit/test_analyze.py` — 32 tests
- `tests/unit/test_readiness.py` — 26 tests
- All 90 tests passing

## Architecture Gaps (v4.0 roadmap items not yet implemented)

| Gap | Phase | Impact on Reconstruction |
|---|---|---|
| Bootstrap State schema | 6.1 | Cannot track Cloud-Init, templates, provenance |
| Cloud-Init templates | 6.2 | First-boot provisioning not replayable |
| Secret Registry | 6.3 | Recovery commands have `[KEEPASS_PATH]` placeholders |
| DNS Registry | 6.4 | Recovery commands have `[VM_IP]` placeholders |
| Deployment Provenance | 6.5 | Cannot verify reconstruction matches original |
| Template Registry | 6.6 | Base images not tracked, template rebuild not automated |
| Service Contracts | 7.1 | Dependencies use heuristics, not declared contracts |
| Service State schema | 7.2 | Service layer not modeled in recovery documentation |
| Network topology as code | 8.x | Wave 0 network reconstruction requires manual steps |
| Reconstruction Playbooks | 9.x | No executable reconstruction scripts |
| Operational Documentation | 10.x | No drift/capacity/health documentation class |
| Capacity Model | 11.x | Recovery readiness does not validate resource headroom |
