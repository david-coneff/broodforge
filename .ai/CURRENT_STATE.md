# Current State

Last updated: 2026-05-31 20:00:00 UTC (2026-05-31 14:00:00 MDT)

## Active Architecture: v7.0

Self-Documenting, Self-Assessing, Self-Recovering Infrastructure Platform.
  k3s + Flux CD + Proxmox + four intelligence layers.
  See ARCHITECTURE.md and docs/ARCHITECTURE-REVIEW-v7.md for full detail.
Seventeen-state model. Six-layer lifecycle. Three assessment tiers. Five dependency graphs.


## Next Action

**Implement Milestone 7.4 — Recovery Documentation Update (Service Layer).**
Add service contract validation steps, service health check commands (from
contract `health_check` field), service restart/verification commands, and
distinct rendering of Service Contract dependency edges in the recovery runbook.
See ROADMAP.md Milestone 7.4 for the full spec.

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
| Architecture Review | v6.0 — k3s, Flux CD, four intelligence phases | Complete |
| Architecture Review | v7.0 — Assessment Engine, 5 scores (ACS/RRS/DCS/CRS/OSS), 12-phase roadmap | Complete |
| Architecture Review | v7.1 — Hatchery/Stargate process, broodling/phoenix terminology, Phase 12.E Node Spawn Bootstrap | Complete |
| Phase 0 | Metadata Model — 10 authoritative YAML files + validator | Complete |
| Phase 1 | Bootstrap Intelligence — discovery, 4 planners, 2 validators | Complete |
| 6.0 | External backup (GitHub/encrypted-archive), recovery runbook Step 0, init wizard prompt | Complete |
| 6.1 | Bootstrap State and Service State schemas (cell_id, network_topology, external_backup, containers) | Complete |
| 6.2 | Cloud-Init Template Library — generated snippets, generate-network-configs.py, generate-user-data.py | Complete |
| 6.3 | Secret Registry — secret-registry.yaml, SecretRegistry, recovery runbook Appendix D | Complete |
| 6.4 | DNS Registry — dns-registry.yaml, DnsRegistry, [VM_IP] resolution in recovery runbook | Complete |
| 6.5 | Deployment Provenance — ProvenanceRegistry, per-VM recovery blocks, Appendix E | Complete |
| 6.6 | Template Registry — TemplateRegistry, base image tracking, recovery runbook Appendix F | Complete |
| 6.7 | Tier 2 Bootstrap State Collector — SSH collector library + CLI + runbook (54 tests) | Complete |
| 6.8 | Bootstrap Documentation Update — DNS + template registry wiring into Bootstrap Workbook (28 tests) | Complete |
| 7.1 | Service Contract Implementation — YAML spec, ServiceContractRegistry, validator, graph edges, Tier 2 reader (39 tests) | Complete |
| 7.2 | Service State Schema and Collection — collector, readiness scorer, engine injection, Tier 2 write (49 tests) | Complete |
| 7.3 | External Dependency State — schema, ExternalDependencyRegistry, cert expiry scorer, Appendix G in recovery runbook, engine injection (71 tests) | Complete |
| 7.4 | Recovery Documentation Update (Service Layer) — per-VM service contract block, health check commands, restart commands, required interfaces, Appendix A edge legend + ★ marker (44 tests) | Complete |
| 6.B | Backup Infrastructure — restic+rclone engine, BackupNaming, SpaceProbe, ResticRunner, RcloneRunner, BackupEngine, RestoreEngine, run-backup.py, restore-from-backup.py, setup-backup.py, readiness scoring, Appendix H, schema additions (82 tests) | Complete |
| 8 | Network Topology as Code — network-topology-schema.json, network_topology_declared in bootstrap-state-schema.json, network_topology_collector.py (parser + SSH collector + compare + merge), _score_network_topology_completeness(), Wave 0 in recovery runbook, engine injection (58 tests) | Complete |
| 9 | Phoenix Playbooks — schema, PhoenixPlaybookGenerator (waves 0, 0.5, 1, 2, 3, 4), RECREATE vs RESTORE decision (_vm_is_stateless), _wave_05_template_rebuild(), phoenix_scripts.py (generate_wave_script + generate_run_all_sh), phoenix_validator.py (validate_playbook + is_valid + summarise_findings), readiness scorer (95 tests) | Complete |

| 10 | Operational Documentation — operational_report.py (7 sections: readiness, drift, capacity, service health, secret completeness, external deps, actions), run_operational() in engine.py (--mode operational), setup-operational-schedule.sh (36 tests) | Complete |

| 11 | Capacity Model — capacity_model schema in bootstrap-state, capacity_collector.py (snapshot extraction, trend analysis, restoration headroom), _score_capacity_model() readiness scorer, engine injection (34 tests) | Complete |

| 12 | Full Single-Cell Reconstruction Test — DrillRecord, start_drill, generate_drill_report, save/get drill, _score_reconstruction_drill(), schema additions, docs/RECONSTRUCTION-DRILL.md, schedule-reconstruction-drill.sh (36 tests) | Complete |

| 1.G | Guided Setup Framework — SETTING_GROUPS, GuidedSetupSession (4 modes), suggest() with revision cascades, check_conflicts() (CIDR overlap, gateway subnet, VMID collision, hostname format, RAM headroom), set_value(), group_selector_rows(), run_ip_selective_suggestions(), session_to_overrides() (60 tests) | Complete |

| 1.G (network) | Network profiles — LanNetworkConfig/WanNetworkConfig, suggest_lan/wan (with field revision), validate, migration plan generation (7-step LAN→WAN/4-step WAN→LAN), state serialization, dnsmasq config generator, schema additions, SETUP-GUIDE.html updated (66 tests) | Complete |

**Tests: 1739 total (1735 passed, 4 skipped)**

## Next Milestones

| Milestone | Description |
|---|---|
| **Phase 12.E** | **Node Spawn Bootstrap (Hatchery Process) — START HERE** |
| Phase 1.G.4-6 | Wire guided setup into forge, spawn, phoenix |
| Phase 1.F | Forge Package Assembly (capstone of forging process) |

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
