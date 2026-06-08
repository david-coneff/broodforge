# Current State

Last updated: 2026-06-08 UTC (operator directed full implementation of all four scoped phases in order — MILESTONE CLOSED, all five items done: datetime.now()/utcnow() clock-injection sweep DONE (commit c1aef50), Phase 1.H/AD-057 Pre-Install Forge Package and Image Builder DONE (commit 072112e, 62 new tests), Phase 1.I/AD-059 Recovery-Readiness Conformance Certificate DONE (commit 3b32137, `_recovery_readiness_certificate.py` + `generate-recovery-readiness-certificate.py` + `replay-snapshot.py`, 56 new tests — also closed an AD-059-premise gap: RRS/ACS/DCS/CRS/OSS scores don't actually exist in readiness.py, certificate composes the real `overall_score` signal instead), Phase 1.K/AD-061 Scoped Vault Hierarchy + User Provisioning DONE (commit c750ed6, `_vault_hierarchy.py` + `derive-scoped-vault.py` + `role-scope-registry.yaml`, 40 new tests — derived-vault plans + keepassxc-cli/pveum command sequences, no live KDBX manipulation, god-mode tier refused by design), and Phase 1.J/AD-060 Hypervisor Recovery: Constrained Accounts + Pre-Generated Spawn Media DONE (`_recovery_accounts.py` + `setup_recovery_account.py` + `authorize-spawn-media-join.py` + `_image_builder.py`/`phoenix_playbook.py` extensions, 96 new tests — forced-command recovery accounts structurally incapable of an arbitrary-shell escape, break-glass root as a passive YAML annotation never autonomously read, pre-generated spawn-media credentials gated by a human-operated authorization CLI, phoenix session credentials with rotation requirements recorded in generated output; constraint-honored confirmed by grep + structural guard tests — no code path reads a permanent hypervisor root credential). Full suite at close: 4388 passed/1 skipped/4 deselected (pre-existing unrelated test_opentofu.py failures, unchanged from clean main).)

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

**Three draft sketches → promoted to scoped phases (2026-06-07 drafted,
2026-06-08 operator-confirmed and scoped):** all three sketches named below
were written 2026-06-07 as "draft for discussion / awaiting operator
reaction." On 2026-06-08 the operator returned with itemized, exact
decisions on all three at once ("The operator has made decisions on all
three roadmap sketches. Incorporate them into ROADMAP.md, ARCHITECTURE.md,
and PAP-state") — closing that thread completely. `ROADMAP.md` "Proposed
Future Work" now contains **zero** items in draft/awaiting-reaction status;
all three are scoped, numbered, proposed-but-not-started phases with their
own ADs, the same tier as Phase 1.H:

- **Phase 1.I — Recovery-Readiness Conformance** (AD-059). Reframes the
  formal axiomatic-kernel/proof-system slice of the `new/` corpus deferral —
  not "implement the formal apparatus" but its two real underlying concerns
  (provable recovery readiness; observed-state ↔ intent-manifest
  conformance) — into **one** new generated artifact:
  `recovery-readiness-certificate.json`/HTML, composing the existing
  RRS/ACS/DCS/CRS/OSS scores (`readiness.py`), drift summary (`drift.py`),
  dependency-graph hashes (`dependencies.py`), a canonical-serialization +
  SHA-256 manifest hash (snapshot/provenance store), and the latest
  `DrillRecord` (Phase 12) into one timestamped record — additive
  extensions only, no cryptographic root-of-trust apparatus or formal
  certification levels (the translation table mapping all 13 formal-proof
  PDFs to existing broodforge mechanisms is preserved in `ROADMAP.md` as
  supporting analysis).
- **Phase 1.J — Hypervisor Recovery: Constrained Accounts and Pre-Generated
  Spawn Media** (AD-060). Operating inside a **firm architectural
  constraint** the operator stated explicitly and which AD-060 records as
  binding on *all* future development, not just this phase: **no autonomous
  pathway may read and wield full root credentials against live
  hypervisors** — because root has no boundary by definition, and an
  autonomous pathway wielding it would convert any compromise of that one
  pathway into root on every hypervisor in the cell at once. Two narrow
  exceptions are explicitly named (both bounded to a single node's
  *temporary*, soon-discarded credential, never the permanent keystore):
  node spawning (already in place via Cloud-Init) and — newly, by direct
  operator instruction — **phoenix recovery packages** (a temporary root
  credential scoped to the setup session only, with a hard requirement,
  recorded in the generated runbook, that the operator rotates it
  afterward). The three-part middle path is **accepted as stated** and
  scoped as this phase's implementation targets: forced-command recovery
  accounts (autonomous-safe by construction), break-glass root as an
  annotation on existing `secret-registry.yaml` entries (behind the
  existing AD-042 human-unlock gate, no new pathway), and pre-generated,
  human-authorization-gated spawn-media credentials (extends AD-043/AD-041).
- **Phase 1.K — Granular Secret Access Silos: Vault Hierarchy and User
  Provisioning** (AD-061). Keeps the "multiple derived vaults" design (the
  only approach compatible with KeePass/KDBX's single-master-password
  model and broodforge's offline-first constraints) and expands it per two
  operator-added requirements: (1) **vault-of-vaults recordkeeping** —
  higher-tier vaults must record lower-tier scoped vaults' credentials, so
  a god-mode operator can always recover any scoped vault's passphrase from
  their own (generalizing the AD-044 per-backup unique-secret bookkeeping
  pattern); (2) **VM/Proxmox-level user-provisioning templates** —
  default account templates per scope tier (service operator / node
  sysadmin / god mode), each provisioned with access to exactly its
  corresponding scoped vault. "God mode" remains the homelab default; no
  new dependency; no change to the trust-model foundations.

See `ROADMAP.md` "Proposed Future Work" for the full scope of all three
(each carries a "Proposed scope" checklist plus the original analysis,
preserved as supporting material), `ARCHITECTURE.md` AD-059/AD-060/AD-061,
and `.ai/decisions.md`'s combined entry for the rationale and consequences.

A new **`tests/unit/test_meta_doc_sync.py`** was also added this session —
it asserts ROADMAP/ARCHITECTURE `.md` files and their `.html` companions
carry matching version/date stamps, catching exactly the kind of doc-vs-doc
drift the operator spotted (ROADMAP.html and docs/ARCHITECTURE.html were
both several days stale relative to their `.md` sources). It failed on first
run (as intended), the drift was fixed, and it now passes — broodforge's own
internal trigger for keeping its self-documentation honest, mirroring
`doc-gen/drift.py`'s role for the infrastructure it manages.

**AD-058 follow-up closed (2026-06-08 UTC, later same-day session):** the gap
named in the previous cycle — MFA method "inherited silently, not seen and
confirmed" — is now closed end-to-end. `security.mfa_method` is a guided-setup
field (`guided_setup.py`: suggest → `"totp"`, `check_conflicts` validates
`{none, totp, yubikey}` and rejects SMS/email-style values); `forge_planner.py`
`build_forge_manifest()` writes the operator's choice (or the `"totp"` default)
into `keepass_config.mfa_method`; `forge_keepass_init.py`
`generate_keepass_init_config()` reads it and threads it into
`KeePassInitConfig`. (Resumed mid-flight: a prior session had left this wiring
partially started — the manifest plumbing existed but `forge_keepass_init.py`
computed `mfa_method` without passing it to the returned config; completed and
tested.) Also fixed a latent clock bug surfaced by the calendar: `verify_trust()`
in `federation_state.py` compared `relationship.is_expired` (real
`datetime.now()`) against an injected `now_fn`, which flipped
`test_phase19_federation.py::test_expiring_soon_still_valid` red the moment
real UTC passed the fixture's fixed expiry date — now computes expiry from the
injected `now` consistently. Full suite: **3844 passed**. See
`docs/FEATURE-HISTORY.md` cycle `2026-06-08_12_36_41 UTC`.

**Two more direct operator instructions landed the same session (2026-06-08
UTC), both now fully implemented and tested — see `docs/FEATURE-HISTORY.md`'s
newest cycle (`2026-06-08_04_54_51 UTC`) and `pap/state/SESSION_HANDOFF.md`'s
`last_completed_step` for the full record:**

- **AD-058 — second-factor auth is now the *default*, not opt-in, for the
  KeePass unlock gate.** Operator instruction: "for high level functions of
  any kind, we should be requiring 2nd factor authentication as a default,
  not just a password — the 2nd factor method should be limited to
  TOTP-authenticator or yubikey, not SMS based TOTP or email-based TOTP
  since this have greater vulnerability to being hacked." broodforge
  *already had* a complete, tested MFA mechanism matching this exactly
  (`proxmox-bootstrap/keepass_mfa.py` — RFC 6238 TOTP + YubiKey
  HMAC-SHA1, 49 tests) — it just defaulted to off. Flipped
  `KeePassInitConfig.mfa_method` / `--mfa` default `"none"` → `"totp"`,
  updated the pinned test, and added **AD-058** to `ARCHITECTURE.md`
  recording the policy (and explicitly, permanently, ruling out SMS/email
  OTP — never to be added as a choice). **Gap named, not yet closed**:
  `guided_setup.py`/`forge_planner.py` still don't prompt for MFA
  interactively — the new default is inherited silently, not seen and
  confirmed. That's a scoped follow-up candidate for a future session.
- **`ROADMAP.html` (and `docs/FEATURE-HISTORY.html`) regenerated with
  collapsible sections.** Operator instruction: "broodforge's roadmap
  should be revised to use collapsible sections, it's quite lengthy at this
  point" (2459 lines). Used the existing, already-proven
  `proxmox-bootstrap/md_to_html.py --collapsible` (the same generator
  behind `FEATURE-HISTORY.html`) rather than hand-editing — which also
  surfaced and fixed a *worse* doc-drift problem than the stamp-only
  `test_meta_doc_sync.py` can detect: the hand-synced `ROADMAP.html` was
  missing entire `<h3>` sections present in `ROADMAP.md` (the three draft
  sketches above existed in the `.md` but not its HTML twin). True
  regeneration guarantees full content sync, not just stamp sync.
  `docs/ARCHITECTURE.html` was checked and confirmed to be a *different*,
  hand-authored doc (no generator marker) — left untouched.

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
