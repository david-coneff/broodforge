# Current State

Last updated: 2026-06-03 UTC (audit round 15: shell injection in pvecm, XSS in onclick, k3s_role validation)

## Active Architecture: v7.1

Self-Documenting, Self-Assessing, Self-Recovering Infrastructure Platform.
  k3s + Flux CD + Proxmox + four intelligence layers.
  See ARCHITECTURE.md and docs/DESIGN-HISTORY.md for full detail.
Seventeen-state model. Six-layer lifecycle. Three assessment tiers. Five dependency graphs.
Four tracks complete: Forging Foundation, Cell-Scoped Foundation, Expanded State Model,
Digital Twin + Federation, and Autonomous Operations (Phase 26 — all sub-phases).


## Next Action

**All audit findings resolved through round 15** (2026-06-03).
Audit rounds 3–14 complete. Round 14 fixes:
- S-01: spawn KEEPASS_GATE_SH no longer exports KDBX_MASTER_PASSWORD; path only
- S-02: hatchery_receiver warns to stderr at startup when no auth token configured
- S-03: _remediation_history_row() escapes action_type/target/outcome via _e()
- S-04: backup provider/path escaped via _e() in dashboard
- S-05: _score_badge() escapes abbr and level via _e()
- S-06: hatchery_receiver 500 errors return generic message; full exception logged to stderr
- S-07: spawn_scripts.py uses shlex.quote() for lan_ip/hostname/domain/bridge/pool/ds_name/snippets_store/server_url
- D-01: NODE-SPAWNING.md spawn_history schema now includes all 5 previously missing fields
- I-01: sync-cert-to-k8s.sh stub created (registered action type now has a real script)
- I-02: spawn_scripts.py unified to use k3s.role nested path (was k3s_role top-level)
- A-01: sys.path.insert moved to module level in broodforge_dashboard.py and hatchery_receiver.py
- A-03: assert set(ALLOWED_ACTION_TYPES)==set(_HANDLERS.keys()) added at module load
- A-04: confusing `and` idiom replaced with explicit if in continuous_assessment.py
- A-05: html_base.py sync comment strengthened; test_html_base_sync.py added

Round 15 fixes:
- S-15.1 (HIGH): spawn_scripts.py generate_phase_01_proxmox — hatchery address and fingerprint shell-quoted
- S-15.2 (HIGH): spawn_scripts.py generate_phase_04_k3s — k3s_role validated against allowed set; hostname shell-quoted
- S-15.3 (MEDIUM): spawn_scripts.py generate_phase_03_cloudinit — VM ip/name shell-quoted in wait_ssh calls
- S-15.4 (MEDIUM): broodforge_dashboard.py _remediation_card — onclick pid now uses json.dumps() for JS context (not HTML escaping)
Tests: 3958 passed, 37 skipped.

All roadmap items complete. Next: **Deploy to hardware** — run `python3 proxmox-bootstrap/forge-planner.py`
on a Proxmox host to forge the first cell. See FORGING.md for operator runbook.

**`new/` corpus analysis complete** (2026-06-07): the previously-untracked
`new/` directory (~165 proposed-revision documents, PAP-AUDIT finding F3) has
been analyzed and triaged per direct operator instruction. One concrete,
additive roadmap item was integrated — **Phase 1.H (proposed, not started):
Pre-Install Forge Package and Image Builder** — closing the gap between
today's only supported path (Proxmox VE already installed on the target) and
true bare-metal bootstrapping (a single bootable image bundling the Proxmox
installer + forge package + first-boot automation). See `ROADMAP.md`
"Proposed Future Work — from `new/` corpus analysis", `ARCHITECTURE.md`
AD-057, `.ai/NEXT_STEPS.md`, and `pap/state/SESSION_HANDOFF.md` for the full
record of what was integrated, what was found already covered, and what was
explicitly deferred (and why).

**DRAFT — Recovery-Readiness Conformance (2026-06-07, awaiting operator
reaction):** the operator partially reconsidered the formal axiomatic-kernel/
proof-system slice of the deferral above — not asking to implement it, but
observing it names two real concerns (provable recovery readiness; observed-
state vs. intent-manifest conformance) and asking for a draft of "what to do
with these." `ROADMAP.md` "Proposed Future Work" now contains a **DRAFT
SKETCH** translating each formal construct (Root Manifest, System Graph,
Reconciliation Engine, drift classification, benchmark scores, Deployment
Certificate, hash-chained replay, idempotent-action invariants, trust
boundaries) into the broodforge mechanism that already plays that role
(`bootstrap-state.json`, `dependencies.py`, Phase 26 remediation, `drift.py`,
existing RRS/ACS/DCS/CRS/OSS scores, readiness + drift + `DrillRecord`,
`history/snapshots/`, idempotent remediation actions, KeePass/restic/git
trust model) — and names **one** genuinely new artifact worth scoping
further: a `recovery-readiness-certificate.json`/HTML composing existing
scores, hashes, and drill results into one timestamped record. Marked
explicitly draft / not a phase / not an AD — offered for operator reaction,
not yet promoted.

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
| 9.T migration + 9.T.12 | migrate_k3s_lib.py, migrate-k3s-to-talos.py, migrate-k3s-to-ubuntu.py, migration_history schema; recovery runbook Appendix I (OS Variant Migration History) in ODT + HTML renderers; 48+25 tests | Complete |
| Round 4 audit fixes | 13 findings: S1 (key→/dev/tty), S3 (auth key), D1/I4 (reconstruction-drill.py CLI), D2 (docstring), I1 (/api/spawn-complete endpoint + spawn verify POST), I2 (migration git commit), I3 (_score_migration_health), I5 (collector_utils), A2 (import aliases); 35 tests | Complete |

**Tests: 3780 passed, 6 skipped — audit round 10 cycles 1–4: timeouts, schema, CLI bugs, drill scorer**

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
  renderers/            HTML document generators (stdlib only)
  renderers/deprecated/ ODS/ODT renderers — preserved but not used
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
- HTML renderers: stdlib html.escape + html_base.py (no external deps)
- ODS/ODT renderers: deprecated — preserved in renderers/deprecated/ but not called by engine.py
- doc-gen: runs without network access (all data from manifest)
- UNRESOLVED fields: never silently omitted
- Historical snapshots: reproducible (same manifest → same docs)
