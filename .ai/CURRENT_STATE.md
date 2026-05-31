# Current State

Last updated: 2026-05-31 13:34:57 UTC

## Active Architecture: v5.0

Federated Infrastructure Digital Twin Platform.
Seventeen-state model. Six-layer lifecycle. Three assessment tiers. Five dependency graphs.
See ARCHITECTURE.md and docs/ARCHITECTURE-REVIEW-v5.md for full detail.

## Next Action

**Implement Milestone 6.3 — Secret Registry reader in doc-gen.**
Reads `proxmox-bootstrap/secret-registry.yaml`, pre-populates KeePass paths in
recovery runbook (replaces `[KEEPASS_PATH]` placeholders with actual paths).
After 6.3: 6.4 DNS Registry reader, then 6.5, 6.6, 6.7, 6.8.
See docs/SESSION-HANDOFF.md for full context and file locations.

## Completed Milestones

| Phase | Description | Status |
|---|---|---|
| Legacy pae CLI (Phases 1–6) | Assessment engine, SQLite history, OpenTofu ingestion, report generation | Complete — see CURRENT_STATE_LEGACY.md |
| 5.1 | Data Model Formalization (5 JSON schemas + validator) | Complete |
| 5.2 | Tier 1 Bootstrap Assessment Rebuild | Complete |
| 5.3 | Bootstrap Documentation Generator | Complete |
| 5.4 | Recovery Documentation Generator | Complete |
| 5.5 | Recovery Readiness Scoring | Complete |
| 5.6 | Historical State Integration — drift detection, snapshot index, reproducibility | Complete |
| Architecture Review | v4.0 — 7-state model, 6-layer lifecycle, Cloud-Init as first-class | Complete |
| Architecture Review | v5.0 — 17-state model, federation, digital twin, 5 dependency graphs | Complete |
| 6.0 | External backup (GitHub/encrypted-archive), recovery runbook Step 0, init wizard prompt | Complete |
| 6.1 | Bootstrap State and Service State schemas (cell_id, network_topology, external_backup, containers) | Complete |
| 6.2 | Cloud-Init Template Library — generated snippets, generate-network-configs.py, generate-user-data.py | Complete |

## Next Milestones

| Milestone | Description |
|---|---|
| **6.1** | **Bootstrap State Schema — START HERE** |
| 6.2 | Cloud-Init Template Library |
| 6.3 | Secret Registry |
| 6.4 | DNS Registry |
| 6.5 | Deployment Provenance |

## Architecture Gaps (v4.0 items not yet implemented)

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

## New Codebase Layout (doc-gen architecture)

```
assessment/tier1/       Tier 1 bootstrap assessment package
data-model/             7 JSON schemas + stdlib validator (90 tests passing)
doc-gen/                Documentation generation engine
  engine.py             CLI: --mode bootstrap | recovery (+ drift integration)
  analyzers.py          10 DERIVED field analyzers
  dependencies.py       Dependency graph + topological sort
  drift.py              Field-level manifest diff and drift detector
  readiness.py          GREEN/YELLOW/ORANGE/RED/BLOCKED scorer
  readiness_report.py   Standalone Readiness-Report.md + .json
  renderers/            ODS and ODT generators (stdlib only)
history/                Snapshot store
  index.py              Snapshot index builder CLI
  index.json            Snapshot index (auto-generated)
  snapshots/            Historical manifest snapshots (2 entries)
docs/                   Architecture docs and session handoff
reports/                Generated documentation output
tests/unit/             110 tests (schema, analyze, readiness, drift, reproducibility)
tests/fixtures/         Sample manifests for tier1 and tier2
```

## Legacy Codebase Layout (pae CLI — do not delete)

```
engine/         Original assessment engine and CLI
collector/      Original collector framework
schemas/        Original JSON schemas (assessment.schema.json etc.)
tests/          Original 286 tests for legacy codebase
pyproject.toml  Package definition for pae CLI
```

## Key Design Constraints

- analyze.py and validate.py: Python 3 stdlib only (no pip)
- ODS/ODT renderers: zipfile + XML only (no odfpy)
- doc-gen: runs without network access (all data from manifest)
- UNRESOLVED fields: never silently omitted
- Historical snapshots: reproducible (same manifest → same docs)
