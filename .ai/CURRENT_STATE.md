# Current State

Last updated: 2026-06-02 UTC

## Active Architecture: v7.1

Self-Documenting, Self-Assessing, Self-Recovering Infrastructure Platform.
  k3s + Flux CD + Proxmox + four intelligence layers.
  See ARCHITECTURE.md and docs/ARCHITECTURE-REVIEW-v7.md for full detail.
Seventeen-state model. Six-layer lifecycle. Three assessment tiers. Five dependency graphs.
Four tracks complete: Forging Foundation, Cell-Scoped Foundation, Expanded State Model,
Digital Twin + Federation, and Autonomous Operations (Phase 26 — all sub-phases).


## Next Action

**All audit findings resolved** (2026-06-02 round 3). MEDIUM and LOW findings fixed:
S1 (timing-safe token), I1 (security scan operational wiring), I2 (9.T migration tier),
S2/S3 (WAN/token warnings), S4/I4 (--verbose + logging), S5 (collector_utils shared runner),
I3 (DASHBOARD_VERSION 7.1). Tests: 3732 passed, 4 skipped.

**9.T migration tier (9.T.9–9.T.11) implemented**: migrate_k3s_lib.py, migrate-k3s-to-talos.py,
migrate-k3s-to-ubuntu.py, migration_history schema, 48 tests.

Next: **Deploy to hardware** — run `python3 proxmox-bootstrap/forge-planner.py`
on a Proxmox host to forge the first cell. See FORGING.md for operator runbook.

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

| SETUP-GUIDE + manifest | Interactive checklist/notes HTML guide with localStorage persistence, export, import; generate-setup-manifest.py with Markdown and JSON output (37 tests) | Complete |

| 12.E.1 | Hatchery state reader — SpawnManifest, read_hatchery_state, next_vmid_block, next_ip_block, suggest_hostname (37 tests) | Complete |
| 12.E.2 | Spawn conflict validator — SpawnProposal, SpawnFinding, validate_spawn, is_valid, summarise (31 tests) | Complete |
| 12.E.4 | Spawn hardware discovery — HardwareProfile, DiskInfo, NicInfo, parsers, SSH collector, zfs_topology, round-trip serialization (34 tests) | Complete |
| 12.E.9 | Bootstrap-state updater after spawn — SpawnResult, update_state_after_spawn, build_spawn_result, no-duplicate guards (21 tests) | Complete |
| 12.E.10 | Disposition-aware assessment scoring — _score_disposition_compliance() RED if declared service VM not on broodling (9 tests) | Complete |
| 12.E.5  | Spawn IaC and config generator — generate_tfvars, generate_cloudinit_user_data, generate_ansible_inventory, write_all_artifacts (33 tests) | Complete |
| 12.E.6  | Spawn scripts generator — generate_spawn_sh, 7 phase scripts, write_all_scripts (43 tests) | Complete |
| 12.E.7+7a | Spawn package assembler + KeePass unlock gate — assemble_spawn_package, package_contents, KEEPASS_GATE_SH, CHECKPOINT_SH (44 tests) | Complete |
| 12.E.8  | Spawn workbook ODS — 8 sheets (Overview, Discovery, Storage, Network, Proxmox-Join, VMs, k3s-Join, Validation), embedded in package (56 tests) | Complete |
| 12.E.11 | Spawn scenarios — 9 scenarios (baseline, compute, storage, control-plane, mixed, insufficient, full-peer, WAN, interactive), conflict detection (52 tests) | Complete |
| 12.E.12 | NODE-SPAWNING.md — operator runbook (7 steps, pre-flight, troubleshooting, capacity guide) | Complete |
| 12.E.3  | Spawn planner — ServiceCatalog (YAML parser), ServiceFitAssessor, SpawnPlannerSession (3 steps), build_spawn_plan, interactive CLI spawn-planner.py, service-catalog.yaml (70 tests) | Complete |
| 1.G.4   | Forge planner — ForgePlannerSession, step0_set_setup_mode, step1_run_guided_setup (all 4 modes), step2_set_identity, step3_set_network_profile, record_manual_field, build_forge_manifest, forge-planner.py CLI (64 tests) | Complete |
| 1.G.5   | Spawn guided setup wiring — SpawnPlannerSession extended (guided_session + setup_overrides), step_guided_setup() (all 4 modes), Step 0.5 in spawn-planner.py CLI, setup_overrides embedded in spawn-plan.json | Complete |
| 1.G.6   | Phoenix guided setup — PhoenixGuidedSetupSession, restoration_wave_options, step0_set_restoration_scope (full/partial), step1_run_identity_overrides, apply_overrides_to_playbook, build_phoenix_guided_session, phoenix-planner.py CLI (63 tests) | Complete |

| Phase 26 | Autonomous Remediation — remediation_planner.py, remediation_queue.py, remediation_executor.py, remediation_policy.py, remediation-cli.py; dashboard integration (remediations section, autonomous mode badge, approve/reject API); operational report Section 8; bootstrap-state-schema.json additions (remediation_proposal, remediation_policy, autonomous_mode); 94 tests | Complete |
| Security Analyzer | security_analyzer.py — log/script/manifest scanning (15 rules), HTML report, security_posture_score(), _score_security_posture() in readiness.py, Security section in dashboard (/api/security), 56 tests | Complete |
| Setup Guide explainer | SETUP-GUIDE.html manifest-import-explainer section: how-to-import (drag-drop/paste/CLI), what auto-fills, what requires manual entry, CLI usage with generate-setup-manifest.py | Complete |
| EFF passphrase | lib/passphrase_eff.py — 1128-word EFF-derived list, generate_eff_passphrase() (44+ bits entropy), passphrase_eff.py; generate_master_password_suggestion() updated to default to EFF style; keepassxc-cli diceware gap documented; 29 tests | Complete |
| HTML package manifests | html_package_manifest.py — build_forge/spawn/phoenix_manifest_html(); forge and spawn assemblers updated to embed *.html alongside *.json; ARCHITECTURE.md AD-047 documents as mandatory pattern; 38 tests | Complete |
| 9.T foundation | Talos Linux alternative — build-talos-template.sh, generate_talos_config.py (library + CLI), os_variant enum in base_image/vm_template/provenance_record schemas, talos-1x-base fixture entries, _score_talos_config_completeness() in readiness.py, Talos Wave 2.5 rebuild + Wave 3 reconstruction steps in phoenix_playbook.py; 57 tests | Complete |

**Tests: 3634 (3634 passed, 37 skipped, 3 pre-existing env failures) — 9.T foundation complete**

## Next Milestones

| Milestone | Description |
|---|---|
| **Deploy to hardware** | **Run forge-planner.py on a real Proxmox host — forge the first cell** |

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
