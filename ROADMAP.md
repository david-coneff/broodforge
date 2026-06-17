# Broodforge — Roadmap

Codebase stamp: `2026-06-13_20-05-27_UTC_c0831145`
Last updated: 2026-06-13 (phases 1.L–2.J implemented since 2026-06-08;
Phase 3.A–3.K proposed 2026-06-13.
**Phase 1.L** — Static Analysis Self-Audit Integration (AD-062, commit f7446be);
**Phase 1.M** — Dynamic Analysis Self-Audit Integration (2026-06-09);
**Phase 1.N** — Migration Infrastructure (AD-065, 2026-06-09);
**Phase 1.O** — Coordinated Quiesce + Backup / CQB (2026-06-10, commit 5e31aff);
**Phase 1.P** — Credential Hierarchy and Key Rotation (2026-06-09);
**Phase 1.Q** — Zero-Touch Node Provisioning (2026-06-10, commit 5dfa573);
**Phase 1.U** — Kubernetes User Registry (2026-06-10);
**Phases 2.A–2.J** — Cluster Services: SSO/Authentik, cert-manager, Prometheus/Grafana,
Loki/Promtail, Longhorn, nginx-ingress, Flux CD, Velero, Linkerd, Kyverno (2026-06-10/13);
**Phase 2.K** — External Secrets Operator: proposed, not yet implemented)
Architecture stamp: `2026-06-13_20-05-27_UTC_c0831145` (see ARCHITECTURE.md; design evolution in docs/DESIGN-HISTORY.md)
Stamp format: `YYYY-MM-DD_HH-MM-SS_<tz>_<shorthash>` where shorthash = SHA-256[:8] of all codebase files
(Python, shell, YAML, TOML, tests — documentation excluded). Reproduce: `python3 proxmox-bootstrap/version_stamp.py`

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
- [x] Milestones 6.0–6.8: Bootstrap State schema, Cloud-Init templates, Secret/DNS registries,
      provenance tracking, template registry, Tier 2 SSH state collector,
      Bootstrap Workbook registry wiring
- [x] Milestones 7.1–7.4: Service contract implementation, service state schema and collection,
      external dependency state (cert expiry + recovery Appendix G),
      recovery documentation service layer (contract block, health checks, restart commands,
      Appendix A edge legend)
- [x] Phase 6.B: Backup infrastructure — restic + rclone engine, BackupNaming, SpaceProbe,
      ResticRunner, RcloneRunner, BackupEngine, RestoreEngine, run-backup.py,
      restore-from-backup.py, setup-backup.py, backup readiness scoring, Appendix H
- [x] Phase 8: Network topology as code — schema, collector, compare, merge, drift detection, Wave 0 runbook
- [x] Phase 9: Phoenix playbooks — schema, generator, wave scripts, validator, readiness scoring, phoenix-planner.py CLI
- [x] Phases 10–12: Operational report, capacity model, reconstruction drill framework
- [x] Phase 1.G: Guided setup framework — four modes, group selector, suggestion revision, conflict detection
- [x] Phase 1.F: Forge package assembly — forge.sh (8 phases), forge-pack.sh, forge-manifest.json,
      forge validator, passphrase generator, KeePass init, dnsmasq, Headscale, DDNS, TLS, FORGING.md
- [x] Phase 12.E: Node spawn bootstrap — hatchery state, conflict validator, spawn planner,
      hardware discovery, IaC generator, phase scripts, package assembler, KeePass gate,
      HTML workbook, disposition scoring, spawn scenarios, NODE-SPAWNING.md
- [x] Phases 13–18: Hardware, Platform, Cluster, Storage, Data Protection, Observability,
      Digital Twin foundation, Capability State, Secret Reference State
- [x] Phases 19–25: Federation State and Trust, Federation Documentation, Failure Domain Modeling,
      Multi-Level Readiness, Federated Reconstruction Planning, Continuous Assessment,
      Reconstruction Validation

**Tests at completion of Phases 1–25: 3302 (3298 passed, 4 skipped). See "Remaining / Future Work" below for per-phase counts; round 12 recorded 3932 passed, 37 skipped; phases 1.M–2.K added further tests.**

### Remaining / Future Work

- [x] **Phase 26 — Autonomous Remediation** (Track 4): Detect → Propose → Approve → Execute → Reassess loop.
      All phases 26.1–26.7 implemented. remediation_planner.py, remediation_queue.py,
      remediation_executor.py, remediation_policy.py, remediation-cli.py. Dashboard
      integration, operational report Section 8, schema additions. 94 tests.
- [x] **Full-stack audit findings** — all HIGH, MEDIUM, LOW items resolved:
      Phoenix assembler + CLI, security→state loop, AD dedup, StrictHostKeyChecking fixes,
      watch() continuous mode, recursive shell script scan, stale docs, dashboard WAN warning,
      phoenix KeePass gate + workbook, service-catalog disambiguation; forge manifest schema
      validation, receiver X-Broodforge-Token auth, flaky passphrase test fixed, dead code
      removed, deprecated/CONTAINER-COMPATIBILITY-PLAN.md, .ai/context.md updated.
      Tests: 3577 passed, 37 skipped, 3 pre-existing jsonschema env failures.
- [x] 9.T (foundation): Talos Linux alternative support — foundation tier complete.
      `build-talos-template.sh`, `generate-talos-config.py` (library + CLI),
      `os_variant` added to base_image/vm_template/provenance_record schemas,
      talos-1x-base fixture entries, `_score_talos_config_completeness()` readiness scorer,
      Talos-specific Wave 2.5 template rebuild + Wave 3 VM reconstruction steps.
      57 tests. See `docs/TALOS-ALTERNATIVE.md` for design and prerequisites.
- [x] 9.T (migration): Ubuntu↔Talos migration tier implemented (9.T.9–9.T.17, all complete).
      `migrate_k3s_lib.py` (shared library: preflight, snapshot, drain, rollback, history),
      `migrate-k3s-to-talos.py` (Ubuntu→Talos 9-step wizard with auto-rollback),
      `migrate-k3s-to-ubuntu.py` (Talos→Ubuntu reverse wizard),
      `migration_history` array in bootstrap-state-schema.json,
      YAML parser fix in generate_talos_config.py, forge_validator.py field name fix.
      48 tests. TALOS-ALTERNATIVE.md usage examples updated.
- [x] 9.T.12: Recovery runbook "OS Variant Migration" Appendix I — migration history table
      with per-record detail and manual rollback commands. ODT + HTML. 25 tests.
      Tests: 3757 passed, 37 skipped, 3 pre-existing jsonschema env failures.
- [x] **Full-stack audit findings (round 4)** — all 13 findings resolved:
      S1: setup-secrets.py private key redirected to /dev/tty (not stdout/log);
      S2: RESTIC_PASSWORD env pattern documented as intentional (correct approach);
      S3: headscale auth key no longer partially printed to stdout;
      D1/I4: reconstruction-drill.py CLI wrapper created (start/complete/last/report);
      D2: update_state_after_spawn.py docstring corrected;
      I1: hatchery_receiver.py /api/spawn-complete endpoint; spawn verify script
          POSTs to hatchery on success; hatchery_url embedded in spawn manifest;
      I2: migration scripts commit bootstrap-state.json to git after migration;
      I3: readiness.py _score_migration_health() ORANGE(failed)/YELLOW(rolled_back);
      I5: migrate_k3s_lib.py imports from collector_utils (consistent with round 3 fix);
      A2: 5 state collector import aliases removed (local_runner not _local_runner);
      A3: same as S1. A1 (sys.path coupling) deferred — requires package restructure.
      35 new tests. Tests: 3792 passed, 37 skipped, 3 pre-existing.
- [x] **ODT/ODS renderer deprecation** — all ODT/ODS renderers (recovery_runbook.py,
      runbook.py, operational_report.py, workbook.py) moved to renderers/deprecated/.
      HTML renderers improved during migration: Appendix C (DNS Registry) added to
      html_recovery_runbook.py; service contract blocks now wire correctly in restore
      waves; _health_check_cmds()/_service_restart_cmds() unified; html_operational_report
      gains backup failure actions + inline cert expiry computation. 9 test files migrated.
      Tests: 3745 passed, 37 skipped, 3 pre-existing.
- [x] **Full-stack audit findings (round 5)** — 10 findings, all resolved:
      A1/I2: recovery_workbook.py (missed in ODT sweep) → moved to deprecated/;
      I1: TestHtmlRecoveryWorkbook (8 tests) added — html_recovery_workbook had no coverage;
      D1–D4: stale .ods/.odt refs in README, ROADMAP, NODE-SPAWNING.md updated to HTML.
      A2 (sys.path coupling) and A3 (deprecated ODS import in test) deferred.
      Tests: 3647 passed, 37 skipped, 3 pre-existing.
- [x] **Security fix: /api/spawn-complete path traversal** — hatchery_receiver.py was
      accepting state_path from POST body, allowing any filesystem path to be
      read+written. Fixed: body state_path now ignored; only server-configured --state
      path is used. 1 new test. Tests: 3648 passed.
- [x] **Full-stack audit findings (round 6)** — 7 findings fixed:
      HIGH: forge_scripts.py heredoc __file__ bug (NameError in stdin mode) → SCRIPT_DIR env;
      A2: sys.path inserts in 5 proxmox-bootstrap/ workbook modules made idempotent;
      A3: test_bootstrap_workbook.py migrated to html_bootstrap.py; registry helpers extracted;
      D1–D4: stale ODS refs in ROADMAP, ARCHITECTURE-REVIEW-v7.md deprecation note, AD-055 added.
      Tests: 3646 passed, 37 skipped.
- [x] **Full-stack audit findings (round 7)** — 2 findings:
      I1: html_forge_workbook.py + html_phoenix_workbook.py had zero test coverage;
          TestHtmlForgeWorkbook + TestHtmlPhoenixWorkbook added (8 tests total).
      Tests: 3654 passed, 37 skipped.
- [x] **Full-stack audit findings (round 8)** — comprehensive scan, all findings fixed:
      D: spawn_workbook.py + forge_workbook.py moved to proxmox-bootstrap/deprecated/;
         tests migrated to HTML (56 tests); html_forge_workbook.py findings rendering bug
         fixed (RED/YELLOW severity handling for ForgeValidationFinding dataclasses);
         setup_warnings now rendered in Overview section.
      Tests: 3720 passed, 37 skipped.
- [x] **Full-stack audit findings (round 9)** — 7 fixes (Round 1 + Round 2):
      Round 1 — A1: html_base.py copied to proxmox-bootstrap/; sys.path.insert removed from 4
          workbook modules; I1: test_hatchery_receiver_wiring.py (16 tests); I3:
          TestScoreMigrationHealth (6 tests) to test_readiness.py; D2: docstring corrected.
      Round 2 (full-stack audit) — 3 HIGH subprocess timeout fixes:
          collect_tier2.py SSH timeout=30, remediation_executor.py timeout=300,
          setup_ddns.py lexicon timeout=30.
      Tests: 3781 passed, 4 skipped.
- [x] **Full-stack audit findings (round 10)** — 8 fixes (Cycles 1–4):
      Cycle 1 — S1: 5 subprocess timeouts (backup.py git remote, forge_keepass_init.py bash
          loop, init-bootstrap-state.py wizard spawn); D1: NODE-SPAWNING.md stale ODS ref fixed.
      Cycle 2 — I1: bootstrap-state-schema.json security_scan property added; S1: silent
          exception in analyze_all_unanalyzed() now prints warning; D1/D2: RECONSTRUCTION-DRILL.md
          CLI examples replaced (removed fake --mode/--record-manual flags); readiness.py
          docstring corrected (removed false "last scan overdue" claim).
      Cycle 3 — I1: reconstruction-drill.py complete gains --gaps argument; RECONSTRUCTION-DRILL.md
          updated with --gaps example.
      Cycle 4 — B1: _score_reconstruction_drill() handles in_progress drills (YELLOW);
          B2: reconstruction-drill.py complete outcome choices fixed (success/partial/failed/aborted);
          B3: partial outcome now correctly scored as ORANGE.
      Tests: 3780 passed, 6 skipped.
- [x] **Full-stack audit findings (round 11)** — 9 fixes (Cycles 1–5):
      Cycle 1 — D1: FORGING.md forge-pack.sh→assemble-forge-package.py (wrong script ref);
          S1: forge_scripts.py heredoc subprocess timeout=300/30; D2: ROADMAP/CURRENT_STATE sync.
      Cycle 2 — I1: spawn package self-assembly (no pre-generated artifacts required);
          D1: assemble-spawn-package.py --artifacts optional, --state alias added;
          D2: spawn-planner.py next-steps complete command; D3: NODE-SPAWNING.md wrong flags;
          I2: update_state_after_spawn.py gains __main__ CLI block.
      Cycle 3 — S1: assemble_spawn_package is_ha logic bug (used non-existent promote_ha);
          D1: FORGING.md engine.py --state→--manifest; I1: bootstrap-state→spawn-manifest
          conversion in CLI (ensures hatchery_url in package).
      Cycle 4 — S1: WAN mode spawn scripts missing (include_wan_phase not passed).
      Cycle 5 — AD-056 added to ARCHITECTURE.md; docs synced.
      Tests: 3925 passed, 37 skipped (+16 new tests).
- [x] **Full-stack audit findings (round 12)** — 7 fixes (Cycles 1–3):
      Cycle 1 — schema_version check bug in assemble-spawn-package.py CLI fixed;
          phase-06-verify.sh error fallback message improved.
      Cycle 2 — hatchery_receiver target_hostname→hostname; html_package_manifest stale
          field names fixed (target_hostname→hostname, vmid_block dict→vms[] list,
          top-level execution_mode/network_mode→disposition.*).
      Cycle 3 — html_spawn_workbook network_mode from disposition; update_state_after_spawn
          vmid_block fallback to vms[].vmid (spawn history was empty).
      Tests: 3932 passed, 37 skipped (+7 new tests).
- [x] **Full-stack audit findings (round 3)** — all MEDIUM and LOW items resolved:
      S1: secrets.compare_digest in hatchery_receiver; I1: security scan wired into operational;
      I2: 9.T migration tier (above); S2: no-token startup warning in dashboard;
      S3: WAN exposure warning in receiver; S4+I4: HTTP request logging + --verbose flag;
      S5: _local_runner() extracted to collector_utils.py (5 collector modules updated);
      I3: DASHBOARD_VERSION synced to 7.1.
      Tests: 3732 passed, 4 skipped.
- [x] **Phase 1.M — Dynamic Analysis Self-Audit Integration** (2026-06-09):
      DynamicHealthScore, assess_dynamic_health(), hypothesis/mutmut/bats/atheris infrastructure,
      run_continuous_assessment() production loop, systemd service+timer, deal contracts,
      beartype in conftest.py. 51 new tests.
- [x] **Phase 1.N — Migration Infrastructure** (AD-065, 2026-06-09):
      migration_manager.py, bootstrap_state.py, package_verifier.py, version.py;
      forge-quiesce/resume/migrate/stamp-version/verify-package.sh; migrations/ directory.
      Operator-gated schema migration with KeePass gate; no autonomous migration pathway.
- [x] **Phase 1.O — Coordinated Quiesce + Backup (CQB)** (2026-06-10, commit 5e31aff):
      backup_manager.py (BackupScope, BackupManifest, BackupScopeInferrer, BackupManager);
      forge-backup/restore/list-backups/backup-scheduled.sh; dashboard CQB Backup & Restore panel. 21 tests.
- [x] **Phase 1.P — Credential Hierarchy and Key Rotation** (2026-06-09):
      credential_hierarchy.py; forge-init-credential-hierarchy/sync-credentials/rotate-credential.sh;
      kdbx_get_child broker; child DB domains (forge-autonomous/spawn/migrate.kdbx);
      vault-of-vaults recordkeeping. 11 tests.
- [x] **Phase 1.Q — Zero-Touch Node Provisioning** (2026-06-10, commit 5dfa573):
      node_planner.py (full lifecycle: planned → joining → pending-approval → active);
      forge-plan-nodes/build-node-iso.sh; dashboard Nodes panel with pending-approval queue
      and PIN verification; /api/node-register + /api/provisioning-nodes endpoints. 16 tests.
- [x] **Phase 1.U — Kubernetes User Registry** (2026-06-10):
      user_registry.py (UserRecord, UserRegistry, disposition model, key throw-away);
      forge-onboard-user/provision-users.sh; dashboard Users panel.
      Centrally tracked users auto-provisioned on cluster rebuild.
- [x] **Phases 2.A–2.J — Cluster Services** (2026-06-10/13):
      Ten k8s-layer services, each with a KeePass-gated init script, Python manager module,
      dashboard panel, and unit tests:
      **2.A** authentik_manager.py + forge-init-authentik.sh (OIDC SSO, AD-060/061 compliant);
      **2.B** cert_manager.py + forge-init-cert-manager/rotate-tls-cert.sh (cert-manager, ClusterIssuers, 34 tests);
      **2.C** monitoring_manager.py + forge-init-monitoring/add-alert-rule.sh (kube-prometheus-stack, 21 tests);
      **2.D** log_aggregation_manager.py + forge-init-log-aggregation.sh (Loki+Promtail, 23 tests);
      **2.E** storage_manager.py + forge-init-longhorn/add-longhorn-disk.sh (Longhorn, 32 tests);
      **2.F** ingress_manager.py + forge-init-ingress/register-ingress.sh (nginx-ingress, ~40 tests);
      **2.G** flux_manager.py + forge-init-flux/flux-reconcile.sh (Flux CD GitOps, ~35 tests);
      **2.H** velero_manager.py + forge-init-velero/velero-backup.sh (Velero workload backup, ~45 tests);
      **2.I** linkerd_manager.py + forge-init-linkerd/enroll-linkerd-ns.sh (Linkerd mTLS, default-deny);
      **2.J** kyverno_manager.py + forge-init-kyverno/forge-kyverno-policy.sh (Kyverno policy enforcement, AD-073, 25 tests).
- [ ] **Phase 2.K — External Secrets Operator** *(proposed, not yet implemented)*:
      external_secrets_manager.py + forge-init-eso/register-secret-store.sh;
      ESO syncs secrets from Vault/AWS SM/etc. into k8s Secrets via ExternalSecret CRDs.
      Proposed scope: Helm install, SecretStore/ClusterSecretStore registry, ExternalSecret lifecycle tracking, ~20 tests.

---

## Proposed Phase 3 — Intelligence, Governance & Experience Layer

Phase 3 introduces the advisory, integrity, and operator/user experience systems
synthesized from the ChatGPT architecture corpus (2026-06-11 session).  All phases
are **proposed, not yet implemented**.  Phases 3.A–3.H form the core intelligence
stack; 3.I–3.K address cluster integrity, operator dashboarding, and user self-service.

Phases are designed to be implemented sequentially (each builds on the prior)
though 3.A–3.C may proceed in parallel with 3.I.

---

### Phase 3.A — Event Platform *(proposed)*

**Purpose:** Introduce a lightweight internal event bus that all broodforge components
publish to and consume from.  Replaces the current pattern of direct inter-module
function calls with a structured event log that other phases (especially 3.D, 3.F,
3.G, 3.I) can inspect and react to.

**Scope:**
- `event_platform.py` — EventBus, EventRecord, subscription registry
- `EventRecord` fields: `event_id`, `source_component`, `event_type`, `timestamp`,
  `payload` (typed dict), `correlation_id`
- In-process publish/subscribe; optional append-only disk journal (one file per day)
- CLI: `publish`, `tail`, `replay` subcommands
- ~20 unit tests

**Design constraints:** no external message broker required; single-node first.
Federation routing deferred to Phase 4.

---

### Phase 3.B — Capability & Policy Engine *(proposed)*

**Purpose:** Centralise what each operator role/service account is allowed to do and
under what conditions.  Currently each manager module enforces its own KeePass gate
(AD-061); Phase 3.B replaces ad-hoc checks with a unified policy layer that other
components query.

**Scope:**
- `capability_engine.py` — CapabilityPolicy, RoleBinding, CapabilityEngine
- Policy schema: `{ role, resource_type, action, conditions: [...] }`
- Conditions: time-of-day windows, quorum requirement (N-of-M approvers), label selectors
- Decision log written to EventBus (3.A) for integrity chain (3.I)
- Policy files stored as versioned YAML under `proxmox-bootstrap/policies/`
- CLI: `check`, `explain`, `list-roles`, `apply-policy` subcommands
- ~25 unit tests

**Design constraints:** stateless evaluation (policy files are source of truth); no
runtime database.  KeePass gate (AD-061) remains the authentication source.

---

### Phase 3.C — Execution Broker *(proposed)*

**Purpose:** All side-effectful operations (Helm install, kubectl apply, node
provisioning, backup trigger) are routed through a single broker that enforces
capability checks (3.B), records execution state, and provides a clean retry/timeout
surface.

**Scope:**
- `execution_broker.py` — ExecutionRequest, ExecutionRecord, ExecutionBroker
- `ExecutionRecord` fields: `request_id`, `operation_type`, `args`, `approved_by`,
  `status` (queued/running/succeeded/failed/timed-out), `started_at`, `ended_at`,
  `stdout_digest`, `stderr_digest`
- Broker enforces capability check before running; publishes lifecycle events to 3.A
- Atomic state file per request; full request journal
- CLI: `submit`, `status`, `cancel`, `history` subcommands
- ~25 unit tests

**Design constraints:** synchronous execution only (no async worker pool) in Phase 3;
parallel execution queue deferred to Phase 4.  Broker never stores raw credential
material.

---

### Phase 3.D — Operational Intelligence & Expectations Engine *(proposed)*

**Purpose:** Provide operators with data-driven time estimates before any long-running
operation executes.  Strictly advisory — the engine never blocks or triggers execution.

**Scope:**
- `operational_intelligence.py` — DurationSample, DurationModel, HistoricalRollup,
  Expectation, Prediction, OperationalIntelligence
- `DurationSample` fields: `operation_type`, `args_hash`, `duration_seconds`, `outcome`,
  `recorded_at`
- `HistoricalRollup` granularities: `MINUTE / HOUR / DAY / WEEK / MONTH / QUARTER / YEAR`
- `Prediction` fields: `operation_type`, `p50_seconds`, `p90_seconds`, `p99_seconds`,
  `confidence` (0.0–1.0), `sample_count`, `generated_at`
- `Expectation`: operator-defined threshold (warn if p50 > X seconds); raises advisory
  event via 3.A if actual duration deviates significantly
- CLI: `predict <operation>`, `record <operation> <duration>`, `rollup <granularity>`,
  `expectations list/set/clear`
- ~20 unit tests

**Design constraints:** purely read/advisory; never calls subprocess.  No ML model —
percentile statistics over raw samples only.

---

### Phase 3.E — Countdown / ETA Display *(proposed)*

**Purpose:** Surface Phase 3.D predictions in the Control Nexus dashboard (3.J) and
CLI before any Execution Broker (3.C) operation is dispatched, so the operator sees
an estimated completion time and confidence band.

**Scope:**
- Dashboard panel: "Predicted duration" card shown in operation confirmation dialogs
- CLI flag `--predict` on any `execution_broker submit` call prints the prediction
  before prompting to confirm
- Live progress timer shown for running operations (time elapsed vs. p50 estimate)
- No new Python module — thin integration layer between 3.C, 3.D, and 3.J

**Design constraints:** display only; confirmation/approval flow is unchanged.

---

### Phase 3.F — Incident System & Internal Ticketing *(proposed)*

**Purpose:** Provide a lightweight, self-hosted incident and task-tracking system
scoped to the broodforge cluster.  Not a replacement for external project management;
intended for operational incidents, remediation tracking, and change requests that
affect cluster state.

**Scope:**
- `incident_manager.py` — IncidentRecord, IncidentStatus, RemediationStep, IncidentManager
- `IncidentRecord` fields: `incident_id`, `title`, `severity` (P1–P4), `source_event_id`
  (link to 3.A EventRecord), `affected_components`, `opened_at`, `resolved_at`,
  `resolution_summary`, `steps: list[RemediationStep]`
- Auto-opened by anomaly correlation (3.G) or manually via CLI
- Published to EventBus (3.A); visible in Control Nexus (3.J)
- CLI: `open`, `update`, `close`, `list`, `show` subcommands
- ~20 unit tests

**Design constraints:** local-only store (JSON file per incident); no external ITSM
integration in Phase 3.

---

### Phase 3.G — Advisories & Anomaly Correlation *(proposed)*

**Purpose:** Correlate events from the EventBus (3.A) and metrics from Prometheus (Phase
2.C) to surface actionable advisories.  Strictly read-only; never takes automated
remediation actions.

**Scope:**
- `advisory_engine.py` — AdvisoryRule, AdvisoryRecord, CorrelationEngine
- Built-in rules: duration deviation (actual vs. 3.D p90), repeated failure of same
  operation type, secret expiry horizon (from vault_manager if present), policy audit
  violations (from 3.B decision log)
- `AdvisoryRecord` fields: `advisory_id`, `rule_name`, `severity`, `message`,
  `source_events`, `created_at`, `acknowledged_at`, `acknowledged_by`
- Advisory triggers incident auto-open in 3.F when severity ≥ P2
- Dashboard panel: advisory feed with acknowledge action
- ~20 unit tests

**Design constraints:** advisory rules are evaluated on-demand (not a streaming engine);
no ML anomaly detection — rule-based only.

---

### Phase 3.H — Secrets & Trust Brokerage *(proposed)*

**Purpose:** Extend the credential gate (AD-061) with a structured secrets broker that
mediates all runtime secret delivery to components.  Phase 3.H is the Phase 3 version
of what Phase 2.K (ESO) does for Kubernetes — it covers the broader credential surface
including operator-level secrets, cluster CA material, and inter-service tokens.

**Scope:**
- `secrets_broker.py` — SecretDescriptor, SecretLease, SecretsBroker
- `SecretDescriptor` fields: `secret_id`, `kind` (tls-cert / api-token / ssh-key /
  arbitrary), `scope` (node / cluster / federation), `rotation_interval_days`,
  `last_rotated_at`, `holder_components`
- `SecretLease`: time-bounded delivery record; published to EventBus (3.A) and
  included in integrity chain coverage (3.I)
- Audit trail: every secret access creates an EventRecord; lease expiry creates an
  advisory (3.G)
- CLI: `register`, `deliver`, `rotate`, `revoke`, `list`, `audit` subcommands
- ~25 unit tests

**Design constraints:** broker never stores plaintext secrets; stores metadata and
leases only.  KeePass remains the root credential store (AD-061).

---

### Phase 3.I — Governance Integrity Chain *(proposed)*

**Purpose:** Bake a compact, hash-linked audit record into the core operation of every
node, cluster, and federation tier.  Provides tamper-evidence for governance events,
policy changes, secret lease events, and execution records without requiring an
external blockchain or consensus engine.

**Location:** `integrity/` (top-level directory, peer to `proxmox-bootstrap/` — bootstrap
is scoped to initial node setup; the integrity chain spans all tiers and is an
independent, foundational oversight function)

**Schema — checkpoint record (JSON, append-only chain file):**

```json
{
  "checkpoint_id":    "string (UUID)",
  "seq":              "integer (monotonic, per-scope)",
  "scope":            "node | cluster | federation",
  "scope_id":         "string (node hostname / cluster name / federation name)",
  "prev_chain_hash":  "string (SHA-256 of previous checkpoint JSON, hex)",
  "state_merkle_root":"string (SHA-256 of covered entries, hex)",
  "covered_entries":  ["event_id_1", "event_id_2", "..."],
  "timestamp":        "ISO-8601 UTC",
  "chain_hash":       "string (SHA-256 of: prev_chain_hash + state_merkle_root + timestamp)"
}
```

**Migration approval record** (embedded in `covered_entries` before any schema migration):

```json
{
  "entry_type":          "migration_approval",
  "migration_id":        "string (UUID)",
  "from_schema_hash":    "string (SHA-256 of current governance/policy/execution schema)",
  "to_schema_hash":      "string (SHA-256 of proposed replacement schema)",
  "approved_by":         ["role_or_principal_1", "..."],
  "approved_at":         "ISO-8601 UTC",
  "approval_chain_hash": "string (chain_hash of the checkpoint that sealed this approval)"
}
```

**Migration event record** (appended immediately after migration executes):

```json
{
  "entry_type":        "migration_event",
  "migration_id":      "string (same UUID as approval above)",
  "adopted_schema_hash":"string (SHA-256 of the schema actually deployed)",
  "approval_ref":      "checkpoint_id of the approval record",
  "migrated_at":       "ISO-8601 UTC"
}
```

The audit tool compares `adopted_schema_hash` to `to_schema_hash` from the approval
record.  A mismatch (or a migration event with no corresponding approval record in
the chain) is flagged as an **unapproved migration**, pinpointing exactly which
checkpoint to use as the rollback target.

**Scope:**
- `integrity/chain_manager.py` — ChainEntry, MigrationApproval, MigrationEvent,
  IntegrityChain, ChainManager
- `integrity/audit_tool.py` — CLI: `verify`, `show`, `migrations`, `check-migration <id>`
- Per-scope chain files: `integrity/chains/<scope>/<scope_id>.jsonl`
  (e.g. `integrity/chains/node/homelab-01.jsonl`, `integrity/chains/cluster/main.jsonl`)
- ChainManager appends checkpoint on every significant state transition (execution
  completed, policy changed, secret rotated, migration approved/executed)
- `audit_tool verify` walks the entire chain recomputing `chain_hash` at each step;
  first hash mismatch identifies the exact corrupted checkpoint
- `audit_tool check-migration <id>` confirms that a given migration's
  `adopted_schema_hash == to_schema_hash` from its approval record
- ~25 unit tests

**Design constraints:** no consensus algorithm, no gas, no token.  Chain files are
append-only (never in-place edited).  Schema is deliberately minimal: hashes +
entry references, not full state snapshots.  A node can verify its own chain
offline without contacting any peer.

---

### Phase 3.J — Control Nexus: Tiered Operator Dashboard *(proposed)*

**Purpose:** Replace the current single-tier `broodforge_dashboard.py` with a
three-tier operator console that presents the right view at the right scope.
Renamed from "sidecar GUI" to Control Nexus to reflect its broader function.

**Tiers:**

- **Node tier** — physical host + Proxmox view (hardware stats, VM inventory,
  storage pools, Proxmox cluster membership).  Runs on the node itself.
- **Cluster tier** — k3s cluster view (current dashboard.py scope extended with
  Phase 3 panels: incidents, advisories, integrity chain status, ETA display).
  Runs on any cluster node.
- **Federation tier** — multi-cluster aggregate view (Phase 4 stub; included as
  empty placeholder panel in Phase 3 so the routing logic is designed now).

**Scope:**
- Extend `broodforge_dashboard.py`: tier selector in header (Node / Cluster /
  Federation), dynamic panel routing
- New panels: Incident Feed (3.F), Advisory Feed (3.G), Integrity Chain Status
  (3.I — last checkpoint + any failed verifications), ETA card (3.D/3.E),
  Secrets Lease Expiry (3.H)
- Node-tier panels: Proxmox summary, VM states, disk health (reads local API)
- Federation-tier panel: placeholder "Not yet implemented — Phase 4"
- ~15 unit tests (panel routing, tier detection)

**Design constraints:** single-process Flask server; no added JS framework beyond
what is already used.  Federation panel is intentionally minimal in Phase 3.

---

### Phase 3.K — Portal: User Self-Service Hub *(proposed)*

**Purpose:** Provide a unified web interface for end-users (not operators) of the
services running in the k3s cluster.  Users log in once via Authentik SSO (Phase 2.A)
and see all the services they have access to, can manage their account centrally, and
can request access to additional services without operator intervention.

**Scope:**
- `portal/` — self-contained Flask (or static + OIDC-proxy) application
- OIDC login via Authentik; session scoped to authenticated user
- **Service registry panel:** list of all k8s-layer services the user is enrolled in
  (Nextcloud, Gitea, etc.) with per-service account status and direct links
- **Account management:** change display name, upload SSH public key, view active
  sessions, revoke sessions
- **Access request:** user submits request for a new service; request creates an
  IncidentRecord (3.F) routed to operator queue
- **SSO chain view:** shows which upstream identity provider (e.g., Google → Authentik)
  is backing the user's session
- Operator-visible queue in Control Nexus (3.J) Cluster tier for approving access
  requests
- ~15 unit tests (route auth, service registry rendering, access request flow)

**Context indicator:** A small, inconspicuous chip in the bottom-right corner of
every Portal page displays the current federation name and cluster identity (e.g.,
`homelab-fed / hatchery`).  This gives users unambiguous context when accessing
multiple broodforge environments.  The chip is populated from Authentik OIDC token
claims or a `/api/v1/context` endpoint backed by `bootstrap-state.json`; it is
read-only and styled to be visible but not distracting (muted colour, small font,
similar to a browser status bar indicator).

**Design constraints:** Portal is user-facing only — no cluster admin functions.
Operators use Control Nexus (3.J).  Portal does not expose raw k8s or Proxmox APIs.

---

## Phases from `new/` corpus analysis *(all proposed phases implemented; deferred items remain out of scope)*

The `new/` directory holds a large proposed-revision corpus (~25 chapters, ~115
specifications/RFCs, plus a separate "axiomatic kernel" formal-methods series).
It was deferred at intake (PAP-AUDIT finding F3 — see
`pap/state/SESSION_HANDOFF.md`) and has now been triaged per direct operator
instruction: items with a realistic implementation path in broodforge or its
documentation tooling are integrated below; the remainder — multi-generational
federation, "knowledge civilization" / cross-civilization exchange, century-scale
succession planning, and the formal axiomatic-kernel/category-theoretic proof
series (`broodforge_*_v1_*.pdf`) — is **explicitly deferred** as out of scope for
broodforge's actual product (a Proxmox/k3s infrastructure platform), not as a
quality judgment on the material itself. See "What was deferred and why" at the
end of this section.

### Phase 1.H — Pre-Install Forge Package and Image Builder *(implemented — commit 072112e; GUI wizard added)*

**Source:** `new/BroodForge_Chapter_16_Bootstrap_and_First_Node_Architecture.docx`,
`new/BroodForge_Specification_70_Bootstrap_Forge_Package_and_First_Node_Deployment.docx`,
`new/BroodForge_Specification_148_Canonical_Bootstrap_and_First_Node_Genesis_Framework.docx`.

**The gap this names:** `FORGING.md` currently lists "Proxmox VE installed on
the target host" as a software prerequisite — forge-manifest.json is generated
entirely on the operator's workstation (Step 1), but the forge package itself
still has to be copied onto an *already-installed* Proxmox host (Step 2+). The
corpus's Chapter 16 names the gap directly: *"The first BroodForge node exists
before infrastructure memory, assessment systems, and regeneration systems are
operational... A BroodForge environment should be creatable without requiring
an existing BroodForge deployment,"* and calls out "Image Builder Architecture"
— generating "ISO images, USB installation media, appliance images... derived
from infrastructure knowledge" — and "Bootstrap Bundle Deployment" as the
concrete mechanism.

**Proposed scope (additive — does not replace the existing path):**

- [x] `generate-bootstrap-image.py` — Image Builder CLI. Consumes
      `forge-manifest.json` plus a Proxmox VE unattended-installer answer file
      (`answer.toml`, Proxmox 8+ automated installer format) and produces a
      single bootable ISO/USB image bundling: (a) the automated Proxmox VE
      installer, (b) the assembled forge package, (c) a first-boot hook.
- [x] Answer-file template generator — `generate-answer-file.py` CLI and
      `generate_answer_toml()` in `_image_builder.py`. Derives `answer.toml`
      (disk layout, network, root credentials, timezone) from the same
      `forge-manifest.json` fields the guided-setup framework (AD-049) already
      collects, so the operator answers setup questions exactly once.
      `generate-answer-file.py` generates answer.toml standalone (for review or
      re-generation without building a full image bundle);
      `generate-bootstrap-image.py` calls the same library function as part of
      the full staging bundle build.
- [x] First-boot automation hook — a systemd unit installed by the answer
      file's post-install script that runs the embedded forge package's
      `forge.sh` automatically on the freshly-installed host's first boot,
      replacing the manual "SSH in and kick off forging" step.
- [x] Image artifact verification — hash/signature manifest for the generated
      image, following the same supply-chain verification pattern already
      established for forge/spawn/phoenix packages (AD-042 KeePass gating,
      AD-051 HTML manifest alongside every machine-readable manifest).
- [x] `FORGING.md` gains an alternative "Step 0 — Build pre-install media
      (optional)" path; the existing "Proxmox already installed" path remains
      the supported baseline for operators who provision hosts another way
      (existing Proxmox cluster, hosting-provider-imaged hardware, etc.).
- [x] `forge-image-builder.html` — cross-platform GUI wizard for the Image
      Builder CLI: self-contained HTML, offline-first, dark/light theme toggle,
      live command preview, clipboard copy. No server required.

**Why this is additive, not a redesign:** the forge manifest is *already*
generated entirely on the operator's workstation before any contact with the
target host (FORGING.md Step 1). This phase only extends what that planning
step can *output* — from "a package you copy onto an already-installed host"
to "a bootable image that installs the host and then runs the package" —
closing exactly the gap the corpus names as "creating the first node without
requiring an existing deployment," using artifacts broodforge already builds.

**Explicitly out of scope (do not expand into):** generic multi-hypervisor
image builders, or "appliance images" for arbitrary target platforms. Chapter
16 itself frames these as "future implementations" and Specification 70 is
explicit that *"the initial implementation shall target the validated
reference stack rather than attempting universal platform support"* — i.e.
the corpus's own text agrees this stays Proxmox-VE-and-reference-hardware
scoped, consistent with broodforge's existing AD-040.

See AD-057 in `ARCHITECTURE.md` for the architecture-level decision record.

### What was reviewed and found already covered

- **Documentation Engine / Infrastructure Memory publication**
  (`new/BroodForge_Specification_60...docx`) and **Runbook Generation /
  Operational Workbook** (`new/BroodForge_Specification_82...docx`) describe,
  at a conceptual level, almost exactly what `doc-gen/` + the Phoenix
  playbook system (Phase 9) + Operational Documentation (Phase 10) already
  do: generate runbooks, workbooks, and recovery documentation from
  infrastructure state rather than hand-authoring them. No gap found.
- **Reference UI and Knowledge Visualization**
  (`new/BroodForge_Specification_88...docx`) names "capability maps,"
  "dependency maps," "trust maps," and "regeneration maps" as desirable
  dashboard features. `doc-gen/dependencies.py`, `capability_state.py`,
  `failure_domain.py`, and the HTML recovery runbook/workbook renderers
  already implement dependency-graph and capability-relationship
  visualization in the generated documentation and dashboard. No gap found
  worth a dedicated phase; incremental visualization improvements should
  continue to ride along with the renderer work that already owns this area.
- **Reference API/CLI** (`new/BroodForge_Specification_87...docx`) — "the
  CLI is authoritative; APIs are built on the same capability model" matches
  broodforge's existing pattern (every planner/assembler is CLI-first;
  `hatchery_receiver.py` exposes the only HTTP API surface, deliberately
  thin). No gap found.

### What was deferred and why

The remainder of the `new/` corpus describes a substantially different,
larger architecture vision than broodforge's actual product line — most of
it framed around governing *the specification corpus itself* (a "Global
Coherence Ledger," "Coherence Certification Authority," "RFC Index,"
"Master Control Plane," "Unified System Orchestration Kernel," "Bootstrap
Order Generator" for reconstructing *the RFC graph*, federated "knowledge
civilization" exchange, century-scale "knowledge commons" and succession
planning, and a separate fully-formal "axiomatic kernel" series
(`broodforge_*_v1_*.pdf` — category-theoretic abstraction, terminal
synthesis theorems, metatheoretic irreducibility, etc.) — rather than
managing Proxmox/k3s infrastructure, which is what broodforge actually does.
`new/broodforge.json` itself frames this material as a `fidelity_translation_only`
handoff that forbids "architecture_simplification… spec_rewrite… semantic_
reinterpretation" — i.e. it is asking to be implemented verbatim as a
parallel system, not mined for ideas. Per the operator's explicit
instruction (and consistent with PAP-AUDIT finding F3's original framing —
"highly speculative, philosophical territory"), none of this is integrated:
- Federation/economic/marketplace/trust-scoring specifications (138–145)
- Knowledge-preservation/civilization/century-scale specifications (116–132)
- The RFC-graph self-governance series (Coherence Dashboard, Master Control
  Plane, Orchestration Kernel, Coherence Ledger, Bootstrap Order Generator,
  Post-Bootstrap Verification Framework) — these govern *the spec corpus as
  a system*, which is a different problem than the one broodforge solves
- The formal axiomatic-kernel / proof-system PDF series (v1.5–v1.27)

If a future operator wants any of this revisited, the entry points are
`new/claude prompt.txt` (the original analysis brief) and
`new/BroodForge_Synthesis_Entry_For_Claude_Analysis_v1.docx` (the corpus's
own "how to analyze me" document) — both still present, untouched.

### Phase 1.I — Recovery-Readiness Conformance *(implemented — commit 3b32137)*

**Status: implemented — commit 3b32137.** Proposed from the
draft sketch below by direct operator decision: *"Recovery-Readiness
Conformance → Scope as Phase 1.I... Build as additive extensions to existing
`readiness.py`, `drift.py`, `dependencies.py`, snapshot/provenance store, and
Phase 12 drills. Write an AD for it."* See **AD-059** in `ARCHITECTURE.md`
for the architecture-level decision record.

**Proposed scope (additive — extensions to existing modules, no new
subsystem):**

- [x] `recovery-readiness-certificate.json` (+ HTML, AD-051 pattern) —
      generator that composes, into one timestamped record: the manifest hash
      (canonical serialization + SHA-256 over `bootstrap-state.json` + the 10
      metadata YAMLs), the graph hash (SHA-256 over each of the five
      `dependencies.py` dependency graphs' canonical form), the current
      readiness score (RRS/ACS/DCS/CRS/OSS from `readiness.py`), the latest
      drift summary (`drift.py`), and the latest `DrillRecord` (Phase 12).
- [x] Hash recording wired into snapshot generation — each
      `history/snapshots/` entry gains `manifest_hash`/`graph_hash` fields, so
      "the graph that produced this readiness score" is independently
      checkable after the fact, not just at generation time.
- [x] `replay-snapshot.py` — re-derives a manifest's readiness score and
      drift report from a stored snapshot and asserts it matches what was
      recorded at the time, turning "snapshots are reproducible" (an existing
      design constraint — `.ai/CURRENT_STATE.md` "Key Design Constraints")
      from an assumption into a checked, reportable fact.
- [x] Documentation pass — write down, in plain language, what broodforge
      does *not* promise to recover automatically (the "Human Intervention
      Boundary," e.g., "if the KeePass database itself is lost, no amount of
      manifest replay restores secrets").

#### Human Intervention Boundary — what's autonomous vs. operator-required

The recovery-readiness conformance pipeline mixes autonomous, read-only
composition with steps that genuinely require a human. Naming the line
between them precisely is the documentation deliverable above; the line is:

**Autonomous (no operator action required):**
- *Certificate generation* (`generate-recovery-readiness-certificate.py`) —
  pure read-only composition of evidence already on disk: hashes the manifest
  and dependency graph, reads the current `ReadinessReport`, the latest drift
  summary, and the latest recorded `DrillRecord`. Produces no side effects
  beyond writing the certificate JSON/HTML.
- *Hash recording* (`history/index.py::build_index`) — regenerates
  `manifest_hash`/`graph_hash` for every snapshot already captured in
  `history/snapshots/`; reads raw snapshot manifests, writes only the
  derived index.
- *Replay / conformance check* (`replay-snapshot.py`) — re-derives a stored
  snapshot's hashes and readiness signal and asserts they match what was
  recorded; a verification pass over existing data — nothing is mutated.
- *Readiness scoring and drift detection* (`readiness.py`/`drift.py`,
  already existing) — both already run unattended as part of `doc-gen`'s
  bootstrap/recovery/operational report generation.

**Requires an operator (broodforge will not do this for you, by design):**
- *Running a reconstruction drill* — `reconstruction_drill.py`'s `DrillRecord`
  only exists because a human deliberately executed a drill (followed the
  generated phoenix playbook, timed the waves, recorded gaps). The certificate
  *reports* the latest drill's outcome; it cannot conjure a drill that wasn't
  run, and a certificate generated for a cell with no drill history says so
  plainly rather than implying readiness it hasn't demonstrated.
- *KeePass master-password entry* — every credential broodforge manages is a
  KeePass reference, not a plaintext value (AD-021/AD-040). If the KeePass
  database itself is lost or its master password forgotten, no amount of
  manifest replay, certificate verification, or graph-hash matching restores
  the secrets it held — this is the canonical "Human Intervention Boundary"
  example named in the operator's original framing of this phase.
- *restic/rclone restore execution* — broodforge documents and plans backups;
  an operator (or their break-glass procedure) actually runs the restore.
  The readiness score can say a backup is present and recent; it cannot
  perform the restore itself.
- *Acting on certificate findings* — if a certificate reports RED/BLOCKED
  components, single points of failure, or HIGH-severity drift, a human
  decides what to do about it (broodforge's remediation queue can *propose*
  actions per Phase 26, but operator approval gates anything destructive or
  credential-touching).

This boundary is not a gap to be closed — it is the deliberate trust-model
line AD-040 draws (git + KeePass + restic as the actual trust anchors, no
autonomous full-root pathways). The certificate's job is to make today's
*position relative to that boundary* visible and checkable, not to erase it.

**Explicitly out of scope (do not expand into):** the cryptographic apparatus
named in the formal-proof-series corpus — Ed25519 root-of-trust chains,
category-theoretic compositional proof objects, formal certification
"levels" with externally-audited conformance. That apparatus is heavier than
broodforge's actual threat model (a home-lab / small-cell operator using
git + KeePass + restic as the trust anchors, per AD-040's SHALL-NOT scope);
building it would be exactly the "implement the spec corpus verbatim" outcome
the `new/` corpus deferral correctly avoided. This phase is additive scoring
fields, one new generated artifact, and a documentation pass — not a rewrite.

The analysis that produced this scope — including the full formal-concept →
broodforge-mechanism translation table — follows below for reference.

**Source of this analysis:** operator follow-up, 2026-06-07. After the `new/`
corpus deferral was recorded, the operator reconsidered one slice of it and
asked for a draft of "what to do with these":

> "the formal-proof series does in theory require software implementation of
> how broodforge documents itself to accommodate the proof process... It's
> about making sure that systems can prove their readiness to recover and/or
> that the state observed matches the intent manifest on record."

That is a narrower and more concrete claim than "implement the axiomatic
kernel" — it says the ~13-document formal-proof/axiomatic-kernel series
(`broodforge_formal_state_transition_proofs_v1_8`,
`broodforge_compositional_proof_system_v1_11`,
`broodforge_completeness_boundary_conditions_v1_7`,
`broodforge_operational_validation_benchmarking_v1_23`,
`broodforge_deployment_certification_conformance_v1_24`,
`broodforge_root_manifest_crypto_spec_v0_4`,
`broodforge_system_graph_schema_v0_5`,
`broodforge_reconciliation_engine_spec_v0_6`,
`broodforge_reconciliation_semantics_v0_2`,
`broodforge_observability_audit_replay_v1_1`,
`broodforge_security_proof_invariant_guarantees_v1_5`,
`broodforge_failure_threat_model_hardening_v1_0`,
`broodforge_action_runtime_idempotent_layer_v0_7`) names two real, narrow
concerns underneath its category-theoretic dress:

1. **Provable recovery readiness** — not just "we scored GREEN," but a
   reproducible demonstration that reconstruction would succeed.
2. **Observed-state ↔ intent-manifest conformance** — a defensible answer to
   "does what's actually running match what we declared it should be?", with
   evidence, not just a diff.

broodforge already has *informal* versions of every formal construct in that
series. None of this needs a from-scratch "axiomatic kernel" — it needs the
existing mechanisms drawn into one place and given a verifiable, replayable
output. Translation table (formal concept → broodforge today → possible
extension):

| Formal concept (PDF series) | broodforge today | Possible additive extension |
|---|---|---|
| Root Manifest (hashed, Ed25519-signed, chained) | `bootstrap-state.json` + 10 metadata YAMLs (plain JSON/YAML, git-tracked, KeePass-gated) | Add a canonical-serialization + SHA-256 content hash for the manifest set, recorded alongside each snapshot in `history/` — tamper-evidence without changing the trust model (git + KeePass + restic remain the actual trust anchors) |
| System Graph (content-addressed nodes/edges, `graph_hash`) | Five dependency graphs in `doc-gen/dependencies.py` | Hash each graph's canonical form at generation time; store the hash next to the graph in the snapshot index so "the graph that produced this readiness score" is independently checkable |
| Reconciliation engine `R(actual, spec) → next`, fixed-point convergence | `remediation_planner.py` / `remediation_queue.py` / `remediation_executor.py` (Phase 26) | Record, per remediation cycle, the pre-/post-state deviation vector and whether it shrank monotonically — turns "did remediation help?" into a measured, logged claim instead of an assumption |
| Drift classification + deviation vector δ, threshold δ_threshold | `doc-gen/drift.py` field-level diff | Bucket existing drift findings into structural/behavioral/performance/security classes and attach a magnitude, so drift reports gain a comparable severity axis (this is a reclassification of existing output, not a new detector) |
| Benchmark scores (GFS/RCS/ADS/PCS) | RRS/ACS/DCS/CRS/OSS scores already in `readiness.py` / assessment engine | No new scores needed — the formal series is naming the same idea (composite, comparable health metrics) with different letters |
| Deployment Certificate (manifest hash + graph hash + conformance level) | Readiness scoring (GREEN…BLOCKED) + drift report + Phase 12 `DrillRecord`, generated separately | **The one genuinely new artifact worth drafting further**: a single generated `recovery-readiness-certificate.json` (+ HTML) that bundles the manifest hash, graph hash, current readiness score, latest drift summary, and latest drill result into one timestamped, signed-by-reference object — "as of this run, here is the evidence that this cell could recover, and here is what it was declared to be" |
| Hash-chained event log + deterministic replay (Strict/Evaluated/Debug modes) | `history/snapshots/` + provenance registry + audit logging already present | Add a `replay-snapshot.py` that re-derives a manifest's readiness score and drift report from a stored snapshot and asserts it matches what was recorded at the time — turns "snapshots are reproducible" (an existing design constraint, see `.ai/CURRENT_STATE.md` "Key Design Constraints") from an assumption into a checked, reportable fact |
| Idempotent action runtime, global invariants I1–I5 | Remediation actions are already required to be idempotent (Phase 26 design); `ALLOWED_ACTION_TYPES`/`_HANDLERS` assertion in `continuous_assessment.py` | Document the existing idempotency guarantees and the handler-set invariant explicitly as "invariants broodforge already enforces," rather than inventing new ones — most of I1–I5 already hold informally |
| Trusted/Controlled/Untrusted boundary, "Human Intervention Boundary," explicit non-guarantees | Implicit in KeePass-gated secrets, restic/rclone backup trust model, and the reconstruction-drill model (a human runs the drill) | Write down, in plain language, what broodforge does *not* promise to recover automatically (e.g., "if the KeePass database itself is lost, no amount of manifest replay restores secrets — that is the documented Human Intervention Boundary") — this is a documentation task, not a code task |

**What this draft is *not* proposing:** the cryptographic apparatus
(Ed25519 root-of-trust chains, category-theoretic compositional proof
objects, formal certification "levels" with externally-audited conformance)
is heavier than broodforge's actual threat model (a home-lab / small-cell
operator using git + KeePass + restic as the trust anchors, per AD-040's
SHALL-NOT scope). Building a parallel formal-verification subsystem would be
exactly the kind of "implement the spec corpus verbatim" outcome the
deferral above correctly avoided. The translation table above is deliberately
phrased as *extensions to existing modules* (`readiness.py`, `drift.py`,
`dependencies.py`, the snapshot/provenance store, Phase 12 drills) — additive
scoring fields, one new generated artifact, and a documentation pass — not a
rewrite.

**This scope was confirmed by direct operator decision on 2026-06-08** — see
the status block at the top of this section and AD-059.

### Phase 1.J — Hypervisor Recovery: Constrained Accounts and Pre-Generated Spawn Media *(implemented — commit f883540)*

**Status: implemented — commit f883540.** Promoted from the
draft recommendation below by direct operator decision, which also recorded a
**firm architectural constraint** ruling out any autonomous pathway that can
read and wield full root credentials against live hypervisors — see **AD-060**
in `ARCHITECTURE.md`, which records that constraint and its two narrow,
explicitly-bounded exceptions (temporary credentials for node spawning and for
phoenix recovery sessions, both already-established patterns extended, never
the permanent keystore). The three-part middle path below is **accepted as
stated** and forms this phase's implementation targets.

**Proposed scope (additive — no autonomous full-root pathway, per AD-060):**

- [x] **Constrained recovery account per hypervisor** — a dedicated,
      narrowly-scoped account provisioned during forge phase-03 (host config),
      gated by a forced command (`ForceCommand`/`command=` in
      `authorized_keys`) limited to a fixed menu of read-only diagnostics and
      safe operations (status, logs, VM start/stop) — never an arbitrary
      shell. Because its blast radius is bounded *by construction*, this is
      the one piece of the recovery surface safe to query autonomously.
- [x] **Break-glass root — storage annotation, not a new mechanism.**
      `secret-registry.yaml` already tracks `pve0X-root-password` entries per
      `host:X`; this item documents/annotates those entries as
      human-unlock-gated break-glass root, behind the *same* gate that already
      protects every other secret (AD-042), with **no new autonomous
      pathway** — functionally "the recovery runbook tells the operator where
      to find it and they type it themselves."
- [x] **Pre-generated spawn-media credentials.** Run the existing AD-043
      passphrase-generation pattern earlier — at image-build time (Phase 1.H)
      — and embed the result on install media instead of generating it at
      install time. Requires human authorization before a node installed from
      such pre-made media is allowed to join the cell — the operator's own
      proposed safeguard, which slots into the same place the existing
      autonomous-mode service-selection confirmation already lives (AD-041).
- [x] **Phoenix package temporary-credential extension.** Per the operator's
      explicit direction, extend the node-spawning temporary-credential
      pattern (Cloud-Init: a generated pre-install root passphrase, used only
      for discovery, discarded the instant the KeePass-managed replacement is
      installed — already in place) to phoenix recovery packages: a temporary
      root credential scoped to the phoenix setup session only, with a hard
      requirement — recorded directly in the generated phoenix runbook — that
      the operator rotates the credential once the recovery session completes.
      Scoped as part of the Phase 9 phoenix-package design.

The analysis that produced this scope follows below for reference.

**Source of this analysis:** operator follow-up, 2026-06-07. The operator
asked for a thorough evaluation of whether broodforge should start
*permanently* storing each Proxmox host's root password in KeePass —
reasoning that the hatchery already handles a *temporary* root passphrase
during spawn discovery (`ARCHITECTURE.md` lines ~159–169: generated
pre-install, used for SSH-based hardware discovery, discarded the moment
Cloud-Init installs a KeePass-managed credential), and a permanent version
would (a) close the gap where a node that boots to Proxmox but fails to bring
up its VM/k3s layer is currently a dead end requiring physical console access,
and (b) give broodforge "a genuinely complete keystore of all node root
passwords," including the ability to autonomously pre-generate credentials for
future spawns and embed them in install media (gated by human authorization
before the resulting node is allowed to join — the operator's own proposed
safeguard).

**The benefit is real; so is the risk, and the risk dominates.** Today, even a
total compromise of the hatchery or KeePass yields, at worst, operational
credentials for nodes mid-spawn — a narrow, time-boxed set, because the
temporary passphrase dies the instant Cloud-Init replaces it. A permanent
"complete keystore of all node root passwords" converts that same compromise
into root on *every hypervisor in the cell — the substrate everything else
runs on*. That is not a difference of degree; it is the difference between
"compromise the secrets layer" and "own the entire infrastructure,
permanently, with no expiry to bound the damage." The sharpest form of the
danger is the one the operator named directly: an *autonomous* execution-
broker pathway that can read and wield a permanent root password turns any
bug, misconfiguration, or compromise of *that one pathway* into root on every
hypervisor at once — a far larger escalation surface than anything that exists
in broodforge today, and exactly the kind of unbounded autonomous action the
newly-amended AD-034/AD-040 ("autonomous action is acceptable when bounded by
safeguards and recoverability," per the F2 resolution recorded earlier today)
was never meant to license, because root has no boundary by definition.

**Recommended middle path — gets the recovery benefit without the liability:**

1. **Constrained recovery accounts, not root, for the "diagnose a
   partially-failed node" case.** Provision a dedicated, narrowly-scoped
   account per hypervisor with a forced command (`ForceCommand` /
   `command=` in `authorized_keys`) limited to a fixed menu of read-only
   diagnostics and safe operations (status, logs, VM start/stop) — never an
   arbitrary shell. Even total compromise of that credential store yields
   only the fixed command surface, never root. Because its blast radius is
   bounded *by construction*, this is the one piece that could safely be
   queried autonomously.
2. **Full root as break-glass, governed by the gate that already exists.**
   Where genuine root is unavoidable (e.g., filesystem repair), store it —
   but behind the *same human-unlock gate* that already protects every other
   secret in the system (AD-042), with **no new autonomous pathway**. This is
   functionally "the recovery runbook tells the operator where to find it and
   they type it themselves" — a storage change, not a privilege change. It
   delivers the "complete keystore, nothing orphaned" property on a trust
   boundary that is already trusted, at zero new attack-surface cost.
3. **Pre-generated spawn-media credentials — adopt as described.** This part
   of the proposal is sound as stated and cheap to build: it is the existing
   `AD-043` passphrase-generation pattern, just run earlier and shipped on
   media instead of typed by an operator at install time. The operator's own
   proposed safeguard — human authorization required before a node installed
   from such pre-made media is allowed to join — costs nothing architecturally;
   it slots into the same place the existing autonomous-mode service-selection
   confirmation already lives (AD-041).

**The line this sketch recommended broodforge not cross — and which the
operator has now confirmed as a firm architectural constraint (AD-060):** an
autonomous pathway that can read and wield full root credentials against live
hypervisors. Everything else the operator described — the complete keystore,
pre-generated spawn media, human-gated joining — is reachable through the
human-unlock gate (for break-glass root) and a constrained-command account
(for routine diagnostics) without ever building that pathway. **This direction
was confirmed by direct operator decision on 2026-06-08** — see the status
block at the top of this section, AD-060, and Phase 1.J's scope, which scopes
items 1 and 3 above as implementation targets and item 2 as the
`secret-registry.yaml` / `SecretRegistry` annotation described.

**Enforcement points (AD-060):**
- `lib/forge-lib.sh`, `forge_keepass_gate()` (line 46): operator-presence gate
  that must be called in every process/subprocess chain before any `kdbx_get`
  invocation; persists the session to a 0600 tmpfs file so later sub-phases
  resume without re-prompting while still requiring the initial human unlock
- `lib/forge-lib.sh`, `kdbx_get()` (line 94): the only function that reads a
  secret from KeePass; defined exclusively in operator-initiated package scripts
  (forge, spawn, phoenix phases) — not present in any autonomous or scheduled path
- `proxmox-bootstrap/forge_scripts.py`, generated phase-05 and phase-06 scripts:
  `forge_keepass_gate` called before any `kdbx_get` invocation; k3s join tokens
  and service passwords only — no hypervisor root credentials are read via
  `kdbx_get` in any generated script
- `proxmox-bootstrap/assemble_spawn_package.py` and `proxmox-bootstrap/phoenix_scripts.py`:
  `forge_keepass_gate` embedded in generated package scripts; credentials accessed
  are scoped to the spawn/phoenix session (temporary, per AD-060 exceptions)
- `tests/unit/test_forge_assembler.py`, `test_phase_05_calls_keepass_gate_before_kdbx_get`
  and `test_phase_06_calls_keepass_gate_before_kdbx_get`: assert gate precedes
  any `kdbx_get` call in generated phase scripts (text-position enforcement)
- No `kdbx_get`, `keepassxc-cli`, or KeePass credential access appears in


---

### Phase 3.L — OpenBao Secrets Broker *(proposed)*

**Purpose:** Introduce OpenBao as a machine-facing secrets API layer sitting between
runtime components and the KeePass credential store.  KeePass remains the
operator-facing encrypted vault (root of trust, AD-061); OpenBao becomes the
programmatic API that enforces RBAC, TTL leases, and produces an audit log — all
the things a CLI call to `keepassxc-cli` cannot provide.  The `child://` reference
scheme continues to work; only the implementation behind `kdbx_get_child()` changes.

**Topology (AD-074):** OpenBao runs as a systemd service on the Proxmox host (not
inside k3s).  Rationale: it must be reachable during bootstrap before k3s is up,
and it governs hypervisor-level secrets that must not depend on a cluster that may
be down during a recovery.  A single-node OpenBao instance is sufficient; HA is
deferred until Phase 3.P+ multi-node federation.  Listen address: loopback only
(`127.0.0.1:8200`); external access proxied through the governance VM's nginx.

**Bootstrap ceremony:** `lib/forge-lib.sh` `forge_openbao_seed()` — a one-time
seeding function called at the end of the Forging runbook (Phase 1.F).  It reads
each credential from the KeePass child DBs using the existing `kdbx_get_child()`
path, then writes each secret into the appropriate OpenBao path using `bao kv put`.
After seeding, `kdbx_get_child()` is switched to call the OpenBao API; the KeePass
side becomes read-only backup.  The seeding ceremony must be run under operator
presence (KeePass gate, AD-065 pattern).

**Auto-unseal (AD-075):** OpenBao sealed state blocks all secret reads.  On
Proxmox-host restart, a systemd `ExecStartPost` script calls
`lib/forge-lib.sh` `forge_openbao_unseal()`, which reads the unseal key shard from
a hardware-bound file (`/etc/broodforge/unseal-shard.enc`) decrypted by the
Proxmox-host's own SSH host key (using `openssl rsautl`).  The unseal shard itself
is generated at bootstrap and recorded in the forge-autonomous KeePass DB.
Threat model: physical access to the host already grants full compromise; the
unseal-at-boot mechanism adds no new attack surface over the current keepassxc-cli
approach.  TOTP-based manual unseal remains available as a fallback.

**Policy mapping:**
- `forge-autonomous` KeePass DB → OpenBao path `secret/autonomous/`; policy
  `autonomous-policy` allows `read` on `secret/autonomous/*`, `deny` on `write`.
- `forge-spawn` → `secret/spawn/`; policy `spawn-policy` allows `read/write`
  for session-scoped spawn credentials only; `deny` on `secret/autonomous/*`.
- `forge-migrate` → `secret/migrate/`; policy `migrate-policy` allows `read`
  on `secret/migrate/*` during a migration session; denies everything else.
  Each policy enforces TTL ≤ 24 h; spawn/migrate leases expire at session end.

**`lib/forge-lib.sh` change:** `kdbx_get_child()` gains a `--via-openbao` flag
(default once seeded).  Internally it calls `curl -s -H "X-Vault-Token: $BFVAULT_TOKEN"
http://127.0.0.1:8200/v1/secret/data/<path>` and extracts `.data.data.value`.
The token is read from `/run/broodforge/openbao-token` (tmpfs, mode 0600),
written by `forge_openbao_login()` at session start using the AppRole credentials
stored in `/etc/broodforge/approle-<role>.env`.  Fallback: if OpenBao is
unreachable, `kdbx_get_child()` falls through to the original `keepassxc-cli` path
and logs a `WARN_OPENBAO_FALLBACK` event.

**Key rotation:** `forge_rotate_secret()` in `lib/forge-lib.sh` writes a new value
to the OpenBao KV path, increments the KV version, and records the rotation as a
`SecretRotationRecord` published to the EventBus (Phase 3.A) and covered by the
Governance Integrity Chain (Phase 3.I).  The old KeePass DB entry is updated
simultaneously using `keepassxc-cli edit` to keep both stores in sync.

**Files to create/modify:**
- `lib/forge-lib.sh` — `kdbx_get_child()` + `forge_openbao_seed()` + `forge_openbao_unseal()` + `forge_openbao_login()` + `forge_openbao_totp()`
- `proxmox-bootstrap/openbao/install-openbao.sh` — download, verify, install systemd unit
- `proxmox-bootstrap/openbao/openbao-policies/` — `autonomous-policy.hcl`, `spawn-policy.hcl`, `migrate-policy.hcl`
- `proxmox-bootstrap/openbao/openbao-unseal.sh` — boot-time unseal helper
- `docs/OPENBAO-SETUP.md` + `docs/OPENBAO-SETUP.html` — operator walkthrough (add to doc-manifest.json)
- Tests: `tests/test_openbao_broker.py` (~20 unit tests covering seed, login, get, rotate, fallback)

**Dependencies:** Phase 3.H (Secrets & Trust Brokerage) — 3.L is the concrete
OpenBao backend for the abstract `SecretsBroker` defined in 3.H.  Integrates with
Phase 3.I (Governance Integrity Chain) for rotation audit records.

**Operator decisions required:**
- Confirm that loopback-only OpenBao on the Proxmox host is the right topology
  (alternative: run in a dedicated governance LXC).
- Choose unseal-shard encryption: SSH host key (current plan) vs. a TPM-backed
  sealing (more secure but requires TPM 2.0 hardware confirmation).
- Confirm whether forge-autonomous credentials should be seeded into OpenBao at all,
  or whether autonomous-mode scripts should continue to call KeePass directly.

---

### Phase 3.M — Markdown Source Editor (Standalone Tool) *(proposed)*

**Purpose:** Provide a standalone HTML editor tool (`docs/bf-editor.html`) that
operators launch when they want to edit a doc's markdown source and regenerate it.
This keeps individual doc pages lightweight — no editor machinery embedded in each
generated HTML file.

**Design (standalone tool approach):** A dedicated `docs/bf-editor.html` file,
not generated by `md_to_html.py`, contains the full editor UI.  It is opened via
an "✎ Edit" badge in the left-side nav of every generated doc page (alongside the
existing Light/Dark mode badge).  The badge passes the current doc's manifest id
as a URL parameter: `bf-editor.html?id=forging`.  The editor page then:
- Fetches the doc's markdown source via `GET /api/docs/source?id=<id>` from
  `broodforge_dashboard.py`, displaying it in a full-page CodeMirror-style textarea
  (using only inline JS — no CDN; a ~12 KB minimal syntax-highlight shim is inlined).
- Provides a lint pass: scans for unknown `@directive` syntax and malformed
  `@credential[...]` refs; highlights offending lines in a gutter.
- "Save & Regenerate" POSTs `{id, source}` to `POST /api/docs/edit`; dashboard
  writes the `.md` file and runs `regenerate_docs.py --id=<id>`.  On success,
  the editor offers a link to reload the regenerated doc page.
- Fallback when dashboard is not running: "⬇ Download .md" button only (uses a
  pre-fetched source stored in sessionStorage from the originating doc page).

**How the originating doc page passes context:** `md_to_html.py` embeds the doc
manifest id as `<meta name="bf-doc-id" content="{id}">` in the `<head>`.  The
"✎ Edit" nav badge reads this meta tag and opens
`bf-editor.html?id={id}` in a new tab.  No markdown source is embedded in the
generated HTML (keeps file sizes down and avoids self-referential editing).

**Files to create/modify:**
- `docs/bf-editor.html` — standalone editor (hand-authored, not in doc-manifest.json).
- `proxmox-bootstrap/md_to_html.py` — add `<meta name="bf-doc-id">` to `<head>`;
  add "✎ Edit" badge to the left-side nav toolbar.
- `proxmox-bootstrap/broodforge_dashboard.py` — add `GET /api/docs/source?id=<id>`
  and `POST /api/docs/edit` endpoints.
- `proxmox-bootstrap/regenerate_docs.py` — add `--id=<id>` single-doc rebuild flag.

---

### Phase 3.N — TOTP QR Code in HTML Pages *(proposed)*

**Purpose:** Walkthrough docs that set up TOTP-protected services need a scannable
QR code so the operator can scan-to-add in an authenticator app without typing a
base32 secret manually.

**New directive:** `@totp-qr[Service Name|TOTP_VAR|account@example.com]`
- Renders a `<canvas>` QR element linked to an `@credential` field variable.
- QR generation: inline compact pure-JS QR encoder (~6 KB minified, MIT licensed).
- Canvas starts blank; rendered when the linked credential field is non-empty.
- `otpauth://` URI: `otpauth://totp/<issuer>%3A<account>?secret=<BASE32>&issuer=<issuer>&algorithm=SHA1&digits=6&period=30`.
- Print safety: canvas `background:#fff` unconditionally; `page-break-inside:avoid`.

**Files to create/modify:**
- `proxmox-bootstrap/md_to_html.py` — add `@totp-qr` directive, inline QR library JS.
- Tests: `tests/test_md_to_html.py` — verify canvas element and `otpauth://` URI.

---

### Phase 3.O — TOC Tiered Numbering *(proposed)*

**Purpose:** Replace the current flat h2-only Table of Contents with a full-hierarchy
numbered TOC (h2/h3/h4) with active-section IntersectionObserver highlighting and
numeric section badges in `<summary>` elements.

**Current state:** TOC is h2-only, flat; no active-link highlighting.

**Design:**
- `_render_blocks()`: capture h2, h3, h4 into `toc` list (remove `if level == 2:` guard).
- `render_html()`: build nested `<ul>` with hierarchical counter; JS `bf_assign_toc_numbers()`
  prepends `<span class="bf-toc-num">1.2.3</span>` per entry.
- `IntersectionObserver` with `rootMargin: "-10% 0px -80% 0px"` adds `bf-toc-active`
  class to the visible section's TOC entry.
- Section number badges: `details[data-sec-num] > summary::before { content: attr(data-sec-num) " "; }`.

**Files to create/modify:**
- `proxmox-bootstrap/md_to_html.py` — TOC generation rewrite, IntersectionObserver JS, CSS.
- Tests: h3/h4 in TOC, nested `<ul>` structure.

---

### Phase 3.P — Setup Guide Markdown Migration *(proposed)*

**Purpose:** Migrate `docs/SETUP-GUIDE.html` (hand-authored, ~150KB, no `.md` source)
to markdown-generated via `md_to_html.py`.

**Steps:**
1. Audit `SETUP-GUIDE.html` for schema element opportunities: `@field`, `@credential`,
   `@check`, `@radio`, `@dir`, `@parse`, `@totp-qr`.
2. Author `docs/SETUP-GUIDE.md` using broodforge schema.
3. Update `proxmox-bootstrap/doc-manifest.json`: remove `"handAuthored": true`, add
   `"source": "docs/SETUP-GUIDE.md"`.
4. Regenerate via `regenerate_docs.py --id=setup-guide`.
5. Visual equivalence check.

**Dependencies:** Phase 3.N (TOTP QR) should land first if setup guide includes TOTP
setup steps.

---

### Phase 3.Q — OpenTofu Lifecycle Manager *(proposed)*

**Goal:** Complete the IaC story. `spawn_iac_generator.py` generates OpenTofu configs
from spawn plans; there is no manager that runs them (plan/apply/drift/destroy).

**Design:**
- `proxmox-bootstrap/opentofu_manager.py` — lifecycle runner: `plan()`, `apply()`,
  `show()`, `drift_check()`, `destroy()`
- State backend: local state in forge working directory OR Forgejo-hosted HTTP backend
- Phoenix gate: `apply()` requires a BackupManifest snapshot before proceeding
- Drift detection: scheduled `drift_check()` run; findings surfaced in dashboard
- Credentials: all secrets via OpenBao provider (after Phase 3.L)
- `scripts/forge-tofu-plan.sh` and `forge-tofu-apply.sh` wrappers with KeePass gate

**Files to create:** `proxmox-bootstrap/opentofu_manager.py`, `scripts/forge-tofu-plan.sh`,
`scripts/forge-tofu-apply.sh`

**Dependencies:** Phase 3.L (OpenBao).

---

### Phase 3.R — Ansible Configuration Manager *(proposed)*

**Goal:** Fill the post-boot configuration gap (Packer replacement alongside Cloud-Init + OpenTofu).

**Design:**
- `proxmox-bootstrap/ansible_manager.py` — playbook registry, dynamic inventory from
  Headscale peer list + broodforge node state, run execution with subprocess + timeout
- Integrated into node lifecycle: after `node_planner.py` marks node `active`, Ansible
  phase triggers automatically
- Vault/OpenBao integration: Ansible vault passwords retrieved via OpenBao (Phase 3.L)
- Run logs in broodforge state directory; failures surface in dashboard

**Files to create:** `proxmox-bootstrap/ansible_manager.py`,
`config/ansible/` (inventory template, site.yml, role definitions),
`scripts/forge-ansible-run.sh`

**Dependencies:** Phase 3.L (OpenBao), Phase 1.Q (node lifecycle).

---

### Phase 3.S — Forgejo Source Control Integration *(proposed)*

**Goal:** Self-host source of truth on Forgejo instead of GitHub. FluxCD currently
sources from GitHub — a public dependency for a private-by-default stack.

**Design:**
- `proxmox-bootstrap/forgejo_manager.py` — provision Forgejo on governance VM or k8s;
  org/repo/webhook creation; mirror setup for upstream dependencies
- FluxCD `GitRepository` objects updated to point to Forgejo over Headscale
- Webhook: Forgejo fires `forge-render-docs.sh` on `.md` push for automatic HTML regen
- Authentication: OIDC federated through Authentik (Phase 2.A)
- Robot accounts for FluxCD and CI stored in OpenBao (Phase 3.L)
- Migration: mirror GitHub → Forgejo; update FluxCD sources; GitHub becomes read-only mirror

**Files to create:** `proxmox-bootstrap/forgejo_manager.py`,
`config/forgejo/` (Helm values, webhook config), `scripts/forge-init-forgejo.sh`

**Dependencies:** Phase 3.L (OpenBao), Phase 2.A (Authentik).

---

### Phase 3.T — Teleport Access Management *(proposed)*

**Goal:** Privileged access management and session recording (Boundary replacement).
Headscale handles WireGuard overlay; Teleport handles certificate-based SSH, k8s API
access, session recording, and privileged access workflows.

**Design:**
- `proxmox-bootstrap/teleport_manager.py` — Auth/Proxy cluster init; node enrollment;
  k8s cluster registration; user provisioning via Authentik OIDC
- Teleport Auth on governance VM; Node agent on each spawned node
- Session recording: all SSH and k8s `exec` sessions recorded; stored in Restic-backed archive
- Relationship to Headscale: Headscale = WireGuard overlay (layer 3); Teleport = access
  control and recording layer on top. Both coexist.

**Files to create:** `proxmox-bootstrap/teleport_manager.py`,
`scripts/forge-init-teleport.sh`, `config/teleport/`

**Dependencies:** Phase 2.A (Authentik), Phase 1.P (credential hierarchy).

---

### Phase 3.U — OPA/Conftest IaC Policy Validation *(proposed)*

**Goal:** Pre-apply policy validation (Sentinel replacement). Kyverno handles k8s
admission at runtime; OPA/Conftest validates OpenTofu plans, Helm values, and k8s
manifests before they are applied.

**Why both:** Kyverno = runtime admission (k8s); OPA/Conftest = pre-apply policy
(blocks bad OpenTofu plans before they reach the cluster). Complementary layers.

**Design:**
- `proxmox-bootstrap/opa_manager.py` — Conftest policy bundle management; Rego policy
  registry; validation against OpenTofu plan JSON output
- PAP pattern integration: broodforge audit patterns translated to Rego rules
- Gate: `opentofu_manager.apply()` calls Conftest validation before proceeding
- Policy sources: stored in Forgejo (Phase 3.S); FluxCD syncs to governance VM

**Files to create:** `proxmox-bootstrap/opa_manager.py`,
`config/opa/policies/` (Rego files), `scripts/forge-conftest-validate.sh`

**Dependencies:** Phase 3.Q (OpenTofu), Phase 3.S (Forgejo).

---

### Phase 3.V — CoreDNS Configuration Manager *(proposed)*

**Goal:** Custom CoreDNS configuration for split-horizon DNS, Headscale MagicDNS
integration, and service discovery across the overlay network.

**Current state:** CoreDNS runs as default k8s cluster DNS; no custom config managed
by broodforge.

**Design:**
- `proxmox-bootstrap/coredns_manager.py` — manage Corefile patches via ConfigMap;
  register custom zones; configure forwarding
- Split-horizon: internal zone (`.broodforge.local`) resolves inside Headscale overlay
- Headscale MagicDNS: CoreDNS forwards `.ts.net` / Headscale zone queries to Headscale DNS
- Wildcard ingress: `*.apps.<cluster>` pointing to ingress controller
- `setup_dnsmasq.py` (governance VM, pre-k8s bootstrap) and `coredns_manager.py`
  (cluster DNS, runtime) complement each other

**Files to create:** `proxmox-bootstrap/coredns_manager.py`

---

### Phase 3.W — Control Nexus *(Future Epic)*

**Goal:** Federation controller providing multi-cell resource advertisement, allocation,
cluster discovery, and trust management. Extends `federation_manager.py` into a full
coordination layer.

**What `federation_manager.py` already does:**
- PeerCell registration/deregistration, trust bundle sync, probe/health check

**What Control Nexus adds:**
- Resource advertisement: each cell publishes available compute/storage/capability
- Resource allocation: workloads scheduled across cells based on advertisements
- Cluster discovery: new cells auto-discover via Headscale + Forgejo-hosted manifest
- Infrastructure memory: cell state in distributed log; reconstruction drills target any cell
- API: REST served by nexus; consumed by `broodforge_dashboard.py` federation panel

**Implementation milestones:**
1. Resource advertisement protocol
2. Cluster discovery (Forgejo-hosted manifest)
3. Resource allocation scheduler
4. Dashboard federation panel

**Dependencies:** Phase 3.S (Forgejo), Phase 3.L (OpenBao), Phases 3.Q/3.R (OpenTofu/Ansible).

---

## HashiCorp Replacement Coverage Map

| HashiCorp Capability | Replacement | Status | File(s) |
|---|---|---|---|
| Terraform | OpenTofu | ⚠ Partial | `spawn_iac_generator.py`; no lifecycle runner → Phase 3.Q |
| Vault | OpenBao | 🔲 Planned | Phase 3.L |
| Consul Service Discovery | CoreDNS | ⚠ Partial | `setup_dnsmasq.py`; no custom CoreDNS manager → Phase 3.V |
| Consul Connect | Linkerd | ✅ Done | `linkerd_manager.py` |
| Nomad | Kubernetes | ✅ Done | Kubernetes throughout |
| Packer | Proxmox + Cloud-Init + OpenTofu + Ansible | ⚠ Partial | Image builder exists; Ansible missing → Phase 3.R |
| Boundary | Headscale + Teleport | ⚠ Partial | `setup_headscale.py` done; Teleport missing → Phase 3.T |
| Waypoint | FluxCD | ✅ Done | `flux_manager.py` |
| Sentinel | OPA | ⚠ Partial | `kyverno_manager.py` (k8s); OPA/Conftest for IaC missing → Phase 3.U |

## Canonical Stack Coverage

| Component | Role | Status | Notes |
|---|---|---|---|
| Proxmox | Hypervisor | ✅ Core | |
| OpenTofu | IaC provisioning | ⚠ Partial | Generator exists; lifecycle runner → Phase 3.Q |
| Ansible | Config management | 🔲 Missing | → Phase 3.R |
| Cloud-Init | Node initialization | ✅ Done | `generate-user-data.py`, `forge-build-node-iso.sh` |
| Forgejo | Source control (GitOps) | 🔲 Missing | → Phase 3.S |
| OpenBao | Secrets broker | 🔲 Planned | → Phase 3.L |
| KeePassXC | Human root store | ✅ Done | `credential_hierarchy.py`, `forge-lib.sh` |
| Kubernetes | Orchestration | ✅ Done | Throughout |
| FluxCD | GitOps | ✅ Done | `flux_manager.py` |
| Authentik | Identity/SSO | ✅ Done | Phase 2.A |
| Headscale | Overlay network | ✅ Done | `setup_headscale.py` |
| Teleport | Privileged access | 🔲 Missing | → Phase 3.T |
| CoreDNS | Service discovery | ⚠ Partial | Default k8s; no custom config manager → Phase 3.V |
| Linkerd | Service mesh | ✅ Done | `linkerd_manager.py` |
| Ceph/Longhorn | Storage | ⚠ Unclear | `storage_manager.py` needs audit (see note below) |
| Restic | Backup | ✅ Done | `backup_manager.py`, `backup_engine.py` |
| Prometheus | Metrics | ✅ Done | Phase 2.C |
| Grafana | Dashboards | ✅ Done | Phase 2.C |
| OPA | Policy engine | ⚠ Partial | Kyverno for k8s; OPA/Conftest for IaC → Phase 3.U |
| Control Nexus | Federation controller | 🔲 Future epic | → Phase 3.W |

**Ceph vs Longhorn:** `storage_manager.py` needs audit. Recommended: both coexist at
different layers — Longhorn for k8s-native PVC storage; Ceph for VM-level block storage
on Proxmox. If needed, split into `longhorn_manager.py` and `ceph_manager.py`.

## Recommended Phase Sequencing (3.L onward)

```
3.L OpenBao          ← unlock secrets management first; everything depends on it
3.M Source Editor    ← doc tooling; independent
3.N TOTP QR          ← doc tooling; independent
3.O TOC Numbering    ← doc tooling; independent
3.P Setup Guide      ← doc migration; after 3.N
3.Q OpenTofu         ← depends on 3.L for secret injection
3.R Ansible          ← depends on 3.L for vault passwords
3.S Forgejo          ← depends on 3.L, 2.A; needed before OPA policy hosting
3.T Teleport         ← depends on 2.A, 1.P
3.U OPA/Conftest     ← depends on 3.Q, 3.S
3.V CoreDNS          ← relatively independent; after basic cluster is stable
3.W Control Nexus    ← future epic; depends on 3.S, 3.L, 3.Q, 3.R
```
