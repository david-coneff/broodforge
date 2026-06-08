# Broodforge — Roadmap

Version: 7.1
Last updated: 2026-06-07 (`new/` corpus analysis: Phase 1.H proposed — Pre-Install
Forge Package and Image Builder; plus a draft sketch reframing the formal-proof
series as "Recovery-Readiness Conformance" — see "Proposed Future Work" below)
Architecture: v7.1 (see ARCHITECTURE.md; design evolution in docs/DESIGN-HISTORY.md)

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

**Tests at completion: 3302 (3298 passed, 4 skipped)**

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

---

## Proposed Future Work — from `new/` corpus analysis (PROPOSED — NOT STARTED)

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

### Phase 1.H — Pre-Install Forge Package and Image Builder *(proposed)*

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

- [ ] `generate-bootstrap-image.py` — Image Builder CLI. Consumes
      `forge-manifest.json` plus a Proxmox VE unattended-installer answer file
      (`answer.toml`, Proxmox 8+ automated installer format) and produces a
      single bootable ISO/USB image bundling: (a) the automated Proxmox VE
      installer, (b) the assembled forge package, (c) a first-boot hook.
- [ ] Answer-file template generator — derive `answer.toml` (disk layout,
      network, root credentials, timezone) from the same `forge-manifest.json`
      fields the guided-setup framework (AD-049) already collects, so the
      operator answers setup questions exactly once.
- [ ] First-boot automation hook — a systemd unit installed by the answer
      file's post-install script that runs the embedded forge package's
      `forge.sh` automatically on the freshly-installed host's first boot,
      replacing the manual "SSH in and kick off forging" step.
- [ ] Image artifact verification — hash/signature manifest for the generated
      image, following the same supply-chain verification pattern already
      established for forge/spawn/phoenix packages (AD-042 KeePass gating,
      AD-051 HTML manifest alongside every machine-readable manifest).
- [ ] `FORGING.md` gains an alternative "Step 0 — Build pre-install media
      (optional)" path; the existing "Proxmox already installed" path remains
      the supported baseline for operators who provision hosts another way
      (existing Proxmox cluster, hosting-provider-imaged hardware, etc.).

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

### DRAFT SKETCH — Recovery-Readiness Conformance (operator follow-up, 2026-06-07)

**Status: draft for discussion — NOT a scoped phase, NOT started, NOT yet an
AD.** After the deferral above was recorded, the operator reconsidered one
slice of it and asked for a draft of "what to do with these":

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

**If the operator wants to proceed**, the natural next step is to scope the
single new artifact — a `recovery-readiness-certificate.json`/HTML generator
that composes existing scores, hashes, and the latest drill result into one
timestamped record — as a numbered phase (tentatively "Phase 1.I"), the same
way Phase 1.H was scoped from Chapter 16/Spec 70/Spec 148. This sketch
deliberately stops short of that: it is the "what to do with these" the
operator asked for, offered for reaction before being written into
`ARCHITECTURE.md` as an AD or split into roadmap deliverables.

---

## Roadmap Overview

### Three Processes — Three Package Types

| Process | Package | Phases | What it does |
|---|---|---|---|
| **Forging** | Forge package | Phase 0–3 + Phase 1.F | Bare hardware → first operational hatchery |
| **Hatchery Process** | Spawn package | Phase 12.E | Hatchery → broodling joins without conflict |
| **Stargate Process** | Phoenix package | Phase 9 + Phase C/D | Failed node → identity resurrected |

### Four Tracks

**Forging Foundation (Phases 0–3, Phase 1.F)**
Establish the metadata model and all Phase A tooling. Culminates in the forge
package — a self-contained archive that takes bare hardware to an operational
broodforge hatchery via eight automated phases.

**Track 1 — Cell-Scoped Foundation (Phases 6–12.E)**
Complete the single-cell documentation, reconstruction, and spawn capability.
Includes:
- Phase 9 (Stargate Process) — phoenix playbooks that reconstitute a failed node's
  identity on new hardware
- Phase 12.E (Hatchery Process) — spawn package that a broodling runs after bare
  Proxmox install to join the hatchery without VMID, IP, or hostname conflicts
All schemas in this track carry `cell_id` (federation-readiness gate).

**Track 2 — Expanded State Model (Phases 13–18)**
Add the new state categories: Hardware, Platform, Cluster, Storage,
External Dependencies, Data Protection, Observability, Capability, Federation State.

**Track 3 — Digital Twin and Federation (Phases 19–25)**
Build the Digital Twin platform, federation architecture, federated reconstruction,
and continuous assessment capability.

**Track 4 — Autonomous Operations (Phase 26)**
Close the detect → propose → approve → execute → reassess loop. The assessment
engine has always found and scored gaps; Track 4 adds the ability to act on them,
always gated by explicit human approval. No autonomous action without a recorded
operator decision.

Track 2 begins after Phase 12.E completes the single-cell + expansion foundation.
Track 3 begins after Phase 18 completes the expanded state model.
Track 4 begins after Track 3 and requires Phase 24 (continuous assessment) running.

---

## Forging Foundation — Phase 0 through Phase 3

Phases 0–3 constitute the **forging process**: building the Phase A toolchain that
can take bare hardware to an operational broodforge hatchery. These phases are
complete. Phase 1.F (Forge Package Assembly) is the planned capstone.

### Phase 1.F — Forge Package Assembly *(Forging Process capstone)*

*Assembles all Phase A tooling into a single self-contained forge package — the
artifact an operator downloads and runs on bare Proxmox to forge the first hatchery.*

- [x] 1.F.1: `forge-pack.sh` — assembles forge package from current repo state:
      discovery scripts, planners, generators, opentofu/, ansible/, forge.sh + phases,
      forge-workbook.html template, lib/ (checkpoint, validation, failure-package)
- [x] 1.F.2: `forge.sh` — orchestrated entry point with 8 phases:
      phase-00 (discover) → phase-01 (plan) → phase-02 (validate, RED blocks) →
      phase-03 (host config) → phase-04 (VMs) → phase-05 (k3s) →
      phase-06 (Flux GitOps) → phase-07 (intelligence layer) → phase-08 (verify + commit)
- [x] 1.F.3: Forge workbook (HTML) — tracks forge execution with same checkpoint/status
      pattern as spawn and phoenix workbooks; committed to Forgejo on completion
- [x] 1.F.4: `forge-manifest.json` — cell identity snapshot embedded in package:
      declares cell_id, naming convention, hardware requirements, storage config,
      secret registry paths, target VM set (minimum viable broodforge stack only)
- [x] 1.F.5: Minimum viable forge validation — phase-02 checks that hardware meets
      minimum requirements for the broodforge stack (doc engine + assessment engine);
      user applications are not included in the forge package (added via GitOps after)
- [x] 1.F.5a: **Proxmox subscription nag suppression** — `lib/pve-suppress-nag.sh`:
      Patches the Proxmox web UI JavaScript to remove the non-enterprise subscription
      popup. Applied during phase-03 (host config) as part of standard host hardening.

      Implementation: patches `/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js`
      to neutralise the `Ext.Msg.show` call that renders the subscription dialog.
      Idempotent — detects if already applied and exits cleanly.

      Persistence: installs a dpkg post-invoke hook at
      `/etc/apt/apt.conf.d/85pve-nag-suppress` that re-applies the patch whenever
      `proxmox-widget-toolkit` or `pve-manager` packages are updated, so the
      suppression survives Proxmox upgrades without operator intervention.

      Note: Proxmox Community Edition (VE without subscription) is fully functional
      and free to use. The subscription nag is a commercial reminder, not a licence
      restriction. This script removes the UI interruption for homelab operators who
      do not hold an enterprise subscription.

- [x] 1.F.6: **KeePass initialisation at forge time** — phase-03 (host config) prompts
      the operator to set the KeePass master password before any secrets are generated:
      - Broodforge offers a generated readable passphrase as the default suggestion
        (format: `Capital.word.phrase.9` — 20-30 chars, leading capital, lowercase,
        period separators, trailing digit; see AD-043)
      - Operator may accept the suggestion, enter their own, or open the KeePass
        built-in generator for an alternative format
      - Password confirmed by re-entry; never stored by broodforge
      - KeePass database initialised and populated with generated service credential
        entries (paths only established here; values filled during service deployment)
      - Operator selects whether to embed the database in subsequent spawn/phoenix
        packages (embedded = convenient but requires master password at gate;
        path-based = database stays off the package entirely)
- [x] 1.F.7: **Readable passphrase generator** (`lib/passphrase.py`) — stdlib only:
      Generates passwords in the `Capital.word.phrase.9` format from a curated word list.
      Used for master password suggestion, initial service credentials, and any
      operator-facing password output. Character set: A-Z (leading only), a-z, 0-9, `.`
- [x] 1.F.8: **Service password compatibility detector** — if a service deployment phase
      fails with an authentication or credential-related error, the detector:
      - Matches the failure pattern against known incompatibility signatures
        (common patterns: service rejects `.` or `_` in passwords)
      - Offers to regenerate the affected credential as a plain alphanumeric password
        (letters + digits only, same length range — KeePass default format)
      - Retries the failed deployment phase with the new credential
      - Records the service name and character restriction in service-catalog metadata
        so the restriction is applied automatically in future deployments
      - The service-specific format override is stored in service-catalog.yaml as
        `password_format: alphanumeric` for any service known to require it
- [x] 1.F.8a: **Headscale auto-configuration** — installed and configured during phase-03
      (host config) so the hatchery is the tailnet coordinator from the moment it is forged:

      **Installation:**
        Download headscale binary (or apt install headscale if available in repos)
        Generate headscale config: server_url, listen_addr, db_path, log_level
        server_url derived from the hatchery's discovered WAN/LAN address + port 8080
        TLS: configured with self-signed cert for initial operation; operator can
        supply a proper cert or configure ACME after forging
        systemd service created and enabled: `headscale serve`

      **Initial setup:**
        Create a broodforge user/namespace in Headscale:
          `headscale users create broodforge`
        Register the hatchery's own Tailscale client with its own Headscale:
          `tailscale up --login-server https://{hatchery-address}:8080`
          (the hatchery is the first node on its own tailnet)
        Record the Headscale server URL in bootstrap-state.json as
          `network_topology.headscale_url`
        Store the Headscale API key in KeePass:
          `headscale apikeys create` → stored at
          `Infrastructure/headscale/api-key`
        The hatchery's tailnet IP (100.64.0.1 or similar) is also recorded in
          bootstrap-state.json alongside its LAN IP

      **Auth key generation for spawn packages:**
        When spawn-planner.py runs in WAN mode, it calls:
          `headscale authkeys generate --expiration 1h --user broodforge`
        The resulting key (a short string, typeable or pasteable) is embedded in
        the spawn package. It is single-use and expires — not stored in KeePass.

      **LAN vs WAN detection:**
        spawn-planner.py tries a direct connection to the broodling's reported IP.
        If unreachable within 5 seconds, prompts the operator:
          "Broodling appears unreachable on LAN. Use WAN mode (Headscale)?"
        Operator can also set --wan or --lan explicitly.

- [x] 1.F.8b: **Split-horizon DNS server (dnsmasq)** — deployed in phase-03 (host config),
      before any VMs exist, so DNS is available from the moment the hatchery can serve LAN:

      **Installation and configuration:**
        apt install dnsmasq
        Generate /etc/dnsmasq.conf from dns-registry.yaml:
          - One `address=/{fqdn}/{lan-ip}` line per dns-registry.yaml entry
          - `server=8.8.8.8` and `server=1.1.1.1` for upstream forwarding
          - `domain={operator-domain}` to make unqualified names resolvable
          - `listen-address={hatchery-lan-ip}` to bind to the LAN interface
        Generate via `proxmox-bootstrap/generate-dnsmasq-config.py`:
          reads dns-registry.yaml → writes /etc/dnsmasq.d/broodforge.conf
          Idempotent: re-run after any dns-registry.yaml update to reload config
        systemctl enable --now dnsmasq
        Update Proxmox host /etc/resolv.conf to point at itself (127.0.0.1)

      **The operator provides their domain during phase-01 (plan):**
        forge-planner.py asks:
          "Your domain name (e.g. home.example.com): _"
        Stored in bootstrap-state.json as `host_identity.domain`.
        All node hostnames in the deployment use this domain suffix:
          hatchery.home.example.com, forgejo.home.example.com, etc.
        FQDN stored as `host_identity.fqdn` — the canonical address for all
        inbound connections (Headscale, Forgejo, and any WAN-reachable service).

      **Split-horizon behaviour:**
        LAN clients with hatchery as DNS:   `hatchery.home.example.com` → LAN IP
        WAN clients using public DNS:        `hatchery.home.example.com` → WAN IP
        Same FQDN, same spawn package, same Headscale URL — works from everywhere.

      **Router/firewall requirements (operator-configured, not automated):**
        Port forwarding: 8080 (Headscale) → hatchery LAN IP
        External DNS A record: `hatchery.{domain}` → operator's WAN IP
        The forge wizard reminds the operator of these requirements but cannot
        configure the upstream router automatically (out of scope for forge).

- [x] 1.F.8c: **External DNS auto-update** — for operators with dynamic WAN IPs:

      **Tool selection:**
        Primary: **dns-lexicon** (pip install dns-lexicon) — 90+ providers, actively
          maintained, unified CLI/API. Providers: Cloudflare, GoDaddy, Namecheap,
          Route53, Porkbun, Gandi, OVH, DigitalOcean, Linode, Vultr, and 80+ more.
        Special case: **DuckDNS** — handled via a single HTTPS GET (no lexicon needed),
          suitable for operators who want a free subdomain rather than their own domain.
        DO NOT USE: inadyn — archived Oct 2025, no longer maintained.

      **Squarespace registrar note:**
        Squarespace exposes no DNS API. Operators with Squarespace-registered domains
        must delegate DNS management to Cloudflare (change nameservers in Squarespace
        dashboard → "Use Custom Nameservers" → enter Cloudflare NS records). After
        delegation, all DNS is managed via Cloudflare API — broodforge treats it as
        a standard Cloudflare provider. See docs/CLOUDFLARE-SETUP.md.

      **forge-planner.py asks:**
        "Is your WAN IP static or dynamic?"
        If dynamic: presents provider selection menu:
          1. Cloudflare (recommended — works for any registrar, including Squarespace)
          2. DuckDNS (free subdomain — no own domain needed)
          3. Other provider (Namecheap, GoDaddy, Route53, Porkbun, etc.) via dns-lexicon
          4. Skip — I will manage DNS records manually

      **Implementation:**
        `proxmox-bootstrap/setup_ddns.py` — interactive configuration wizard:
          Walks operator through provider selection, credential entry, and
          writes config to /etc/broodforge/ddns.conf.
          Credentials stored in KeePass; references stored in bootstrap-state.json.
          Tests the update before saving (makes a real DNS call to verify credentials).
        `proxmox-bootstrap/update-dns.py` — update script (called by systemd timer):
          Detects current WAN IP (curl ifconfig.me / ipinfo.io, with fallback)
          Compares to cached last-known IP (/var/lib/broodforge/last-wan-ip)
          If changed: calls dns-lexicon or DuckDNS GET to update A record
          Logs outcome to systemd journal
          On failure: logs and retries on next timer tick (does not crash)
        systemd timer: broodforge-ddns.timer — runs every 5 minutes
          OnBootSec=60 (initial delay to let network settle)
          OnUnitActiveSec=5min

      **Configuration stored in bootstrap-state.json:**
        `network_topology.ddns_provider` — "cloudflare" | "duckdns" | "lexicon:{name}" | null
        `network_topology.ddns_zone` — the DNS zone/domain being managed
        `network_topology.ddns_record` — the specific A record being updated (e.g. "hatchery")
        `network_topology.ddns_credential_reference` — KeePass path for API token/key

      **Documentation:** docs/CLOUDFLARE-SETUP.md and docs/DUCKDNS-SETUP.md —
        step-by-step guides for each provider including Squarespace → Cloudflare
        delegation walkthrough.

- [x] 1.F.8d: **Let's Encrypt TLS certificate automation** — runs after DNS is configured
      (1.F.8b + 1.F.8c); tool and method depend on which DNS provider was selected:

      **Cloudflare path:**
        Install certbot + python3-certbot-dns-cloudflare (apt)
        Write /etc/broodforge/cloudflare.ini using API token from KeePass
          (chmod 600 — certbot refuses to read world-readable credentials files)
        Issue wildcard cert:
          certbot certonly --dns-cloudflare
            --dns-cloudflare-credentials /etc/broodforge/cloudflare.ini
            --dns-cloudflare-propagation-seconds 30
            -d {fqdn} -d "*.{domain}"
            --email {operator-email} --agree-tos --non-interactive
        Certs land at /etc/letsencrypt/live/{fqdn}/fullchain.pem + privkey.pem
        certbot.timer (installed by certbot) handles auto-renewal
        Deploy hook written to /etc/letsencrypt/renewal-hooks/deploy/:
          Reloads headscale and nginx after each successful renewal

      **DuckDNS path:**
        Install acme.sh (curl https://get.acme.sh | sh)
        Issue wildcard cert:
          DuckDNS_Token={token from KeePass}
          acme.sh --issue --dns dns_duckdns
            -d {subdomain}.duckdns.org -d "*.{subdomain}.duckdns.org"
            --server letsencrypt --dnssleep 60
        Install cert to stable path /etc/broodforge/ssl/ with --install-cert
        acme.sh cron entry handles auto-renewal (added during install)
        Reload command: systemctl reload headscale + sync-cert-to-k8s.sh

      **Both paths — Headscale TLS config:**
        forge.sh writes the cert paths into /etc/headscale/config.yaml after
        cert issuance; Headscale is (re)started with TLS enabled

      **k3s ClusterIssuer (deployed in phase-06 Flux bootstrap):**
        Cloudflare: ClusterIssuer with dns01.cloudflare solver + k8s secret from
          Cloudflare API token (written from KeePass during phase-06)
        DuckDNS: No native cert-manager DNS-01 support; forge generates
          sync-cert-to-k8s.sh which copies the acme.sh wildcard cert into k8s TLS
          secrets in each namespace; script is wired into acme.sh --reloadcmd and
          also runs as a weekly k8s CronJob to catch any drift

      **SSL config stored in bootstrap-state.json:**
        network_topology.ssl_provider: "certbot" | "acme.sh"
        network_topology.ssl_method:   "dns-01-cloudflare" | "dns-01-duckdns"
        network_topology.ssl_cert_path: path to fullchain.pem
        network_topology.ssl_key_path:  path to privkey.pem

      **Documentation:** docs/CLOUDFLARE-SETUP.md Part 3 and docs/DUCKDNS-SETUP.md Part 2

- [x] 1.F.9: **Timezone preference at forge time** — phase-01 (plan) prompts the
      operator to confirm or set their local timezone:
      - Auto-detected from the host OS if available
      - Stored in `bootstrap-state.json` as `vm_defaults.timezone`
      - Used by all documentation engine output (all timestamps show both UTC and local)
      - Updatable after forging via `engine.py --set-timezone` without requiring a rebuild
- [x] 1.F.10: **Backup destination setup at forge time** — phase-01 (plan) walks the
      operator through configuring restic + rclone backup destinations:
      - At least one destination required before forge proceeds (secrets must be backed up)
      - Local destinations (filesystem path, USB mount point) need no credentials
      - Cloud destinations require an API key, Application Key, or OAuth token — not
        username/password; operator directed to docs/CLOUD-STORAGE-SETUP.md for setup
      - Destinations defined as an **ordered chain** per layer; no limit on chain depth
      - Each destination attempted in sequence; each upload independently verified
      - If a destination fails, the next in the chain is attempted automatically;
        the failure is reported to the operator but does not halt the process
      - If every destination in the chain fails for a layer: RED alarm surfaced
        to operator via log, workbook, and next assessment run — never silent
      - All backups encrypted by default with restic (encryption is mandatory, not optional);
        encryption password per restic repo stored in KeePass and retrieved by secrets
        broker at backup time — operator never manually handles backup decryption keys
      - Separate choices for: (a) secrets / KeePass DB, (b) configuration state,
        (c) application data volumes (opt-in; not configured by default)
      - Retention policy: number of versions to keep (default: 5); permanent checkpoint option
      - All backup config stored in bootstrap-state.json as first-class readiness metadata
- [x] 1.F.11: Documentation: `FORGING.md` — operator runbook covering prerequisites,
      running forge-pack.sh on the repo, copying forge package to target host,
      executing forge.sh, verifying hatchery is operational

### Phase 1.G — Guided Setup Framework *(cross-cutting: forge, spawn, phoenix)*

*A shared configuration guidance engine used by all three deployment packages.
At every manual prompt the auto-suggestion is displayed and revised as the operator
makes choices. Conflicts are detected and surfaced before commitment.*

**Four configuration modes:**

| Mode | Operator interaction | When to use |
|---|---|---|
| **Autonomous** (default) | None — all settings calculated automatically | Standard deployment |
| **IP-Selective** | Choose IP addressing only; everything else is automatic | Operator has a specific IP plan |
| **Group-Manual** | Group selector → configure chosen groups manually, rest is automatic | Operator wants control over specific areas |
| **Full Manual** | Walk through all settings with auto-suggestions | Complete control |

**Setting groups (available in Group-Manual and Full Manual modes):**

| Group | Settings covered |
|---|---|
| Network | Management CIDR, gateway, bridge names, VLAN IDs, DNS, Headscale URL |
| Storage | ZFS pool topology, pool name, datastore names, disk assignment |
| VM Sizing | VMID block, per-VM RAM/CPU/disk, placement constraints |
| Identity | Hostname, domain, FQDN, cell_id, naming convention |
| Security | KeePass location, password format, SSH key references |
| k3s | Pod/service CIDR, CNI plugin, initial role (server/worker) |
| Backup | Restic destinations, retention policy, DDNS provider |

**Suggestion revision:** when the operator overrides a setting, all downstream
auto-suggestions are revised to remain logically consistent. Example: choosing
`192.168.50.0/24` as the management CIDR causes all subsequent VM IP suggestions
to come from that range; choosing a custom pool name causes all datastore references
to use that name.

**Conflict detection:** before accepting each override, the engine checks:
- VMID collisions with existing or other declared VMs
- IP address collisions with DNS registry or other declared VMs
- Subnet overlaps with k3s pod/service CIDR or other networks
- RAM allocation exceeding host total RAM
- ZFS pool or bridge names that already exist on the host
Warnings are shown with specific conflict details. The operator may still proceed.

- [x] 1.G.1: `proxmox-bootstrap/guided_setup.py` — core engine:
      `SETTING_GROUPS` — dict defining the seven groups and their constituent field paths
      `GuidedSetupSession` — session class that tracks:
        mode (autonomous|ip-selective|group-manual|full-manual)
        selected_groups (set of group names for group-manual mode)
        choices (field_path → {value, source: 'auto'|'manual'})
        warnings (accumulated conflict messages)
      `suggest(field_path, session)` — returns auto-suggestion revised from current choices;
        subnet changes cascade to IP suggestions; hostname changes cascade to FQDN; etc.
      `set_value(field_path, value, session)` → list[str] conflict warnings;
        records choice; triggers suggestion revision for dependent fields
      `check_conflicts(field_path, value, session)` → list[str] warning messages

- [x] 1.G.2: Group selector interface:
      `select_groups(session)` — displays group table with current auto-suggestions for
        a representative field in each group; operator toggles groups on/off;
        returns the set of groups to configure manually
      `prompt_field(field_path, label, session, choices=None)` → value;
        shows auto-suggestion, optional discrete choices, accepts free-text or selection;
        calls set_value() and surfaces any conflicts before returning

- [x] 1.G.3: IP-Selective mode specialization:
      Runs autonomously except for the Network group;
      `run_ip_selective(session)` — prompts only for CIDR, gateway, and VM IP assignments;
        all other settings auto-calculated; subsequent IP suggestions revised from choices

- [x] 1.G.3b: Network profiles (setup_network.py):
      LanNetworkConfig / WanNetworkConfig dataclasses; suggest_lan/wan() with field
      revision (cidr→gateway, domain→fqdn, dns_provider→tls_provider);
      validate_lan/wan_config() with errors/warnings; plan_migration_to_wan()
      (7-step plan, router step non-autonomous); plan_migration_to_lan() with
      preserve_headscale option; lan/wan_config_to_state() serialization;
      apply_network_config_to_state(); generate_dnsmasq_config() for both profiles.
      Schema: network_topology.profile + wan_config + lan_config + ssl_provider enum updated.
- [x] 1.G.4: Wire into forge (Phase 1.F):
      forge_planner.py (library) + forge-planner.py (CLI): ForgePlannerSession,
      step0_set_setup_mode, step1_run_guided_setup (autonomous/ip-selective/
      group-manual/full-manual), step2_set_identity, step3_set_network_profile,
      record_manual_field, build_forge_manifest. Produces forge-manifest.json
      with setup_overrides embedded for manual choices. (64 tests)

- [x] 1.G.5: Wire into spawn (Phase 12.E):
      SpawnPlannerSession extended with guided_session + setup_overrides fields.
      step_guided_setup() helper (autonomous no-op; ip-selective pre-populates;
      group-manual + full-manual record field_values). Step 0.5 in spawn-planner.py
      CLI offers guided setup between network mode and execution mode.
      build_spawn_plan() embeds setup_overrides in spawn-plan.json.

- [x] 1.G.6: Wire into phoenix (Phase 9):
      phoenix_guided_setup.py: PhoenixGuidedSetupSession, restoration_wave_options,
      step0_set_restoration_scope (full/partial with wave selection),
      step1_run_identity_overrides (hostname/domain/fqdn/cell_id overrides with
      conflict detection), apply_overrides_to_playbook (scope filter + identity
      update + setup_overrides audit trail), build_phoenix_guided_session factory.
      phoenix-planner.py CLI. (63 tests)

---

## Track 1 — Cell-Scoped Foundation

### Phase 6 — Bootstrap State

**6.0 — External Backup Setup and Recovery Runbook Integration**
- [x] `external_backup` section in bootstrap-state-schema.json
- [x] `backup.py` — archive naming, GPG encryption, transfer, listing, pruning
- [x] `setup-external-backup.py` — GitHub or encrypted-archive interactive wizard
- [x] `init-bootstrap-state.py` — prompts for external backup as part of init flow
- [x] Recovery runbook Step 0 — pre-populated bootstrap state retrieval commands
      derived from declared external_backup provider (git clone / rclone + gpg / UNRESOLVED)

**6.1 — Bootstrap State Schema and Repository Structure**
- [x] `data-model/bootstrap-state-schema.json` (Cloud-Init, image registry, templates,
      provenance, secret registry, DNS registry, service contracts, hardware requirements)
- [x] `data-model/service-state-schema.json`
- [x] `cell_id` field in both schemas
- [x] `proxmox-bootstrap/` repository structure
- [x] Schema validation tests (90 tests in test_bootstrap_service_schemas.py)

**6.2 — Cloud-Init Template Library**
- [x] Cloud-Init user-data per VM role
- [x] Cloud-Init network-config per VM
- [x] Proxmox vendor-data snippet
- [x] Snippet upload procedure documentation (SNIPPET-UPLOAD.md)

**6.3 — Secret Registry**
- [x] `secret-registry.yaml` schema with `owning_cell` field (federation-readiness)
- [x] Initial registry entries for all known secrets
- [x] Secret registry reader in doc-gen (`doc-gen/registries.py` — `SecretRegistry`)
- [x] Wire into recovery documentation (pre-populated "Secrets Required for Recovery" section + Appendix D)
- [x] Secret registry completeness in readiness scorer (ORANGE if missing)

**6.4 — DNS Registry**
- [x] `dns-registry.yaml` schema
- [x] Initial registry entries for all VMs
- [x] DNS registry reader in doc-gen (`doc-gen/registries.py` — `DnsRegistry`)
- [x] Wire into recovery runbook (replace `[VM_IP]` placeholders with actual IPs + Appendix C)
- [x] DNS registry completeness in readiness scorer (YELLOW if missing)

**6.5 — Deployment Provenance**
- [x] Provenance record schema (provenance_records in bootstrap-state-schema.json)
- [x] Provenance recorder (bootstrap-state.json provenance_records array)
- [x] Provenance collector in Tier 2 assessment
- [x] Provenance completeness in readiness scorer (YELLOW if missing, per VM)
- [x] Wire into recovery documentation (per-VM block + Appendix E)

**6.6 — Template Registry and Base Image Tracking**
- [x] Template registry schema (base_images + templates arrays in bootstrap-state-schema.json)
- [x] Initial registry entries (ubuntu-2204-base ISO + template in bootstrap-state.json)
- [x] Template registry reader in doc-gen (doc-gen/template_registry.py — TemplateRegistry)
- [x] Template registry completeness in readiness scorer (ORANGE if missing)
- [x] Appendix F — Template Registry in recovery runbook
- [x] Template rebuild playbook format (Phase 9)

**6.7 — Tier 2 Bootstrap State Collector**
- [x] `proxmox-bootstrap/collect_tier2.py` — SSH collector library (parse_qm_list,
      parse_qm_config, collect_templates, collect_provenance_records, merge_into_state)
- [x] `proxmox-bootstrap/collect-tier2.py` — CLI entry point (--host, --user, --port,
      --key, --state, --dry-run, --verbose)
- [x] `proxmox-bootstrap/TIER2-COLLECTION.md` — runbook: prerequisites, usage, merge
      behaviour, ISO name inference, post-collection steps, troubleshooting
- [x] `--dry-run` flag; merge-only logic (never overwrites existing manual entries)
- [x] Tests — 54 tests in test_tier2_collector.py
- [x] Cloud-Init snippet comparison (deployed vs. repository) — deferred to 6.8
- [x] Integration into Tier 2 manifest — deferred to 6.8

**6.8 — Bootstrap Documentation Update**
- [x] Bootstrap Workbook Stage 03: VM IP from DNS registry; ISO path from template registry
- [x] Stage 03 validation checkpoint and qm create note pre-populated from registries
- [x] End-to-end test (28 tests)

**6.B — Backup Infrastructure** *(restic + rclone; KeePass, config state, app data)*

- [x] 6.B.1: `proxmox-bootstrap/setup-backup.py` — interactive backup configuration wizard:
      - Installs restic and rclone on the host if not present
      - Configures one or more backup layers:
          (a) Secrets / KeePass DB — always enabled when any destination configured
          (b) Configuration state — enabled by default
          (c) Application data volumes — opt-in per volume at service setup
      - For each layer, builds an **ordered destination chain** (no limit on length):
          → Enter destinations one at a time; add as many as desired
          → Each destination attempted in sequence when the previous one fails
          → All attempted; failures reported but chain continues; all-fail = RED
      - Local destinations: filesystem path or USB mount point (no credentials)
      - Cloud destinations: provider selection → API credential entry → rclone config
          written to `~/.config/rclone/rclone.conf`; restic repo initialised at destination
          Cloud destinations require API key / OAuth / Application Key — not user+password
          (see `docs/CLOUD-STORAGE-SETUP.md`)
      - **Per-backup unique secrets (non-KeePass layers)**:
          Each individual backup run generates a new unique restic repo password via
          `restic key add` + `restic key remove` (rewraps the master key; no data
          re-encryption). Stored in KeePass at a timestamped path per component:
            `Backup/{layer}/{component}/{YYYY-MM-DD_HH_MM_SS}/repo-password`
          A `current` alias key is also maintained:
            `Backup/{layer}/{component}/current` → latest timestamp subdirectory
          Secrets broker uses the snapshot timestamp to look up the exact key for
          any given snapshot at restore time. After `restic forget` prunes a snapshot,
          the corresponding KeePass entry is removed automatically.
          KeePass DB backup is exempt — its auth method (master password or configured
          token/key file) is never subject to per-backup rotation.
      - **KeePass DB backup — no restic layer**: the `.kdbx` file is already AES-256
          encrypted by KeePass; backed up as a plain rclone file copy to each configured
          destination; adding restic encryption would create a circular dependency (need
          the repo password from KeePass to decrypt backup of KeePass — irrecoverable)
      - **KeePass backup transport credentials** stored in `forge-manifest.json`, NOT in
          KeePass — the one exception to the "packages carry only KeePass references" rule;
          these credentials are embedded in forge/spawn/phoenix packages so a bare machine
          can retrieve the KeePass DB before KeePass is available
      - **Secrets broker configuration**: wizard records which KeePass path templates map
          to which components/layers so that automated backup and restore require no manual
          secret entry beyond the initial master password gate
      - **Space-aware component routing**: wizard records the target snapshot retention
          count and estimated component sizes; at runtime the backup engine probes
          available space before each run and routes individual components to destinations
          with sufficient room (see 6.B.3 for execution detail)
      - Retention policy per layer: number of snapshots to keep (default 5);
          permanent checkpoint: any snapshot can be tagged `checkpoint` and is
          excluded from rotation regardless of retention count
      - **Naming convention enforced by wizard**: all repo paths, KeePass key paths,
          snapshot tags, and KeePass DB filenames are constructed programmatically
          from cell_id, component metadata, and UTC timestamps — operators do not
          name backup artifacts; see 6.B.2 naming convention for the full scheme
      - All configuration serialised into `bootstrap-state.json` backup_config section

- [x] 6.B.2: `backup_config` section in `bootstrap-state-schema.json` — schema for:

      **Naming convention** (enforced programmatically; operators do not name artifacts manually):
        Component prefixes: `kdbx` | `cell-config` | `node-{hostname}` | `vm-{name}-{vmid}`
          | `ct-{name}-{ctid}` | `vol-{vm_name}-{vol_name}` | `svc-{service_name}`
        Timestamp format: `YYYY-MM-DD_HH_MM_SS` (UTC; underscores; matches project convention)
        Hash: 8 hex chars — SHA-256 of file content (KeePass files) or first 8 of UUID/snapshot ID
        Restic repo paths: `{destination_root}/{cell_id}/{layer}/{component_prefix}/`
        KeePass DB files: `kdbx_{cell_id}_{timestamp}_{hash8}.kdbx`
        Snapshot set IDs: `{cell_id}_{timestamp}_{run_hash8}` (UUID first 8 chars)
        Restic snapshot tags: `cell:{cell_id}`, `set:{snapshot_set_id}`,
          `component:{prefix}`, `layer:{layer}`, `run:{timestamp}`
        KeePass key paths: `Backup/{layer}/{component_prefix}/{timestamp}/repo-password`
          and `Backup/{layer}/{component_prefix}/current` (alias to latest)

      - Per-layer destination chain (ordered array; unlimited length):
          For config/appdata layers — each entry:
            `{type, rclone_remote, restic_repo_root, restic_repo_password_keepass_prefix,
              retention_count}`
            Restic repo path assembled as: `{restic_repo_root}/{cell_id}/{layer}/{component}/`
          For secrets/KeePass layer — each entry:
            `{type, rclone_remote, kdbx_destination_root}`
            Destination file named: `kdbx_{cell_id}_{timestamp}_{hash8}.kdbx`
            (no restic layer; transport credentials stored in forge-manifest.json)
      - Permanent checkpoint tag name (default: `checkpoint`)
      - Layer-level `all_failed_policy`: `alert` | `block_assessment` (default: both)
      - Per-layer backup history (appended on each run; trimmed to last 100 entries):
          `{run_at, snapshot_set_id, destinations_attempted, destinations_succeeded,
            consecutive_all_fail_count, components: [{component_id, component_prefix,
            destination, restic_snapshot_id, keepass_key_path, size_bytes, verified,
            routed_reason}]}`
          `snapshot_set_id`: `{cell_id}_{timestamp}_{run_hash8}` — human-readable;
          links all component snapshots belonging to the same logical backup point
      - Space routing metadata per component per run (embedded in components[]):
          `routed_reason`: `primary` | `space_fallback` | `chunked_split`

- [x] 6.B.3: `proxmox-bootstrap/run-backup.py` — backup execution engine:

      **Naming — all names constructed programmatically, never entered manually:**
      - Restic repo path: `{restic_repo_root}/{cell_id}/{layer}/{component_prefix}/`
          e.g. `b2:cell-backup/proxmox-cell-a/config/vm-forgejo-101/`
      - KeePass DB copy: `kdbx_{cell_id}_{timestamp}_{sha256_of_file[:8]}.kdbx`
          e.g. `kdbx_proxmox-cell-a_2026-06-01_03_00_00_a3f2b891.kdbx`
      - Snapshot set ID: `{cell_id}_{timestamp}_{snapshot_set_uuid[:8]}`
          e.g. `proxmox-cell-a_2026-06-01_03_00_00_f7c1d3a2`
      - Restic snapshot tags applied at creation: `cell:{cell_id}`, `set:{snapshot_set_id}`,
          `component:{component_prefix}`, `layer:{layer}`, `run:{timestamp}`
      - KeePass key path: `Backup/{layer}/{component_prefix}/{timestamp}/repo-password`

      **Per-backup secret rotation:**
      - For each component being backed up, generates a new unique passphrase
      - Adds it to the restic repo: `restic key add` (new key now unlocks the repo)
      - Stores it in KeePass at the timestamped path:
          `Backup/{layer}/{component_prefix}/{YYYY-MM-DD_HH_MM_SS}/repo-password`
      - Updates the `current` alias in KeePass to point to the new timestamp path
      - Removes the previous key from the repo: `restic key remove` (old password
          no longer works; only the newly generated key is valid going forward)
      - On pruning (after `restic forget`): removes the corresponding KeePass entry
          for each pruned snapshot's timestamp path; `current` always points to latest
      - KeePass master password gate fires once per session; all subsequent secret
          lookups and key rotations are automatic
      - **KeePass database backup**: triggered whenever configuration state backup runs;
          executed as a plain rclone copy of the `.kdbx` file — no restic layer, no key
          rotation; transport credentials read from `forge-manifest.json` (not KeePass);
          KeePass is already AES-256 encrypted and requires no additional encryption layer

      **Space-aware component routing:**
      - Before backing up each component, probes available space at each destination
          in the chain using rclone's `about` command (or filesystem `statvfs` for local)
      - Estimates required space: last snapshot size × 1.1 (10% growth headroom)
      - Routing logic per component:
          1. Primary destination has space → back up there (routed_reason: `primary`)
          2. Primary is full or insufficient → try next destination in chain
             (routed_reason: `space_fallback`)
          3. No single destination has sufficient space, but multiple have partial space:
             → Split by sub-components (e.g., each volume backed up independently to
                whichever destination has room for that volume)
             → Each sub-component gets its own restic repo, its own key rotation, its
                own KeePass path, and its own backup_history entry
             → The parent `snapshot_set_id` links all sub-component snapshots so restore
                knows they belong to the same logical backup point
             (routed_reason: `chunked_split`)
          4. Even sub-component splitting cannot fit within available space across all
             destinations → surfaces as a human-required decision; backup run records
             a BLOCKED status for the affected component; other components continue
      - All routing decisions (destination chosen, available space at run time,
          routed_reason) recorded in the component entry in `backup_history`
      - Restore reads routing from `backup_history` → secrets broker retrieves the
          correct key per component+destination+timestamp → restores each piece
          from its actual destination → assembles the full snapshot set automatically

      **Ordered destination chain execution:**
      - After space-aware routing determines where each component goes, backs up each
          component to its assigned destination
      - On completion runs `restic stats` to verify upload integrity (snapshot count
          and size must be consistent with expectations)
      - If verification fails or destination errors: logs with full error detail,
          marks destination as failed in this run, moves to next destination in chain
      - If all destinations fail for a layer:
          → Writes RED entry to backup_history
          → Increments `consecutive_all_fail_count`
          → Emits a structured failure record visible in the next assessment run
          → Never fails silently; surfaced in workbook, readiness report, and alerts

      **Retention and checkpoints:**
      - Applies `restic forget --prune --keep-last N` per destination after each
          successful backup (only on destinations that succeeded this run)
      - After pruning: removes corresponding per-snapshot KeePass entries; updates
          `current` alias to remain valid
      - Snapshots tagged `checkpoint` are excluded from forget regardless of N
      - Prompts operator to create a checkpoint if none exists after > 7 days

      **Run trigger:**
      - Triggered by assessment engine on completion of a full cluster assessment
      - Can also be run manually: `python3 proxmox-bootstrap/run-backup.py [--layer secrets|config|appdata]`
      - Dry-run mode: `--dry-run` shows what would be backed up, to which destinations,
          with current space probe results and routing decisions (no writes made)

- [x] 6.B.4: **Simple mode** — one wizard, uniform policy across layers:
      - Operator defines a single ordered destination chain that applies to all layers
      - Per-layer overrides available but not required
      - Recommended starting point; detailed mode layers on top as needed

- [x] 6.B.5: **Detailed mode** — per-node, per-VM, per-container, per-volume heterogeneous policy:
      - Each component defines its own ordered destination chain, retention count,
          and restic repo password (or inherits from parent explicitly)
      - Inheritance chain: cell → node → VM → container → volume; each level can
          override any field while inheriting the rest from the parent
      - Children create a sub-directory prefix at the inherited destination so backup
          data is co-located but separately addressable (`/cell/node/vm/volume/`)
      - Siblings' destination chains auto-suggested as defaults when configuring a new
          sibling (enter once, reuse across all sibling components)
      - Policy inheritance and credential reuse minimise repeated configuration entry
          while maintaining independent restic repos per component (dedup is per-repo)

- [x] 6.B.6: Backup readiness scoring in `readiness.py`:
      - RED: no destination configured for secrets or configuration state layers
      - RED: `consecutive_all_fail_count` ≥ 2 (two consecutive complete-chain failures)
      - RED: last successful backup older than 3× schedule interval
      - ORANGE: last successful backup older than 2× schedule interval
      - ORANGE: any destination in chain has failed in last 3 runs (partial coverage)
      - YELLOW: all destinations healthy but last backup older than 1× schedule interval
      - YELLOW: no permanent checkpoint exists
      - GREEN: all destinations reachable, last backup within schedule, checkpoint exists

- [x] 6.B.7: Backup status in recovery runbook — Appendix H:
      - Per-layer: destination chain with last-run status per destination (✓ / ✗ / skipped),
          last successful backup timestamp, snapshot count, most recent permanent checkpoint
      - All-fail history: if consecutive_all_fail_count > 0, shown prominently
      - Restic repo password KeePass paths listed (for manual recovery reference)

- [x] 6.B.8: `proxmox-bootstrap/restore-from-backup.py` — automated restore engine:

      **Design principle:** maximise automation via secrets broker; operator enters
      master password once at the gate; everything else is automatic.

      **Snapshot discovery and selection:**
      - Probes each configured destination (in chain order) for available restic snapshots
      - Presents snapshot list: timestamp, tag, component, size
      - Defaults to "latest" unless operator specifies a date or checkpoint tag
      - `--latest`, `--checkpoint` (most recent tagged snapshot), `--date YYYY-MM-DD`,
          `--tag NAME` selection flags

      **Automated secret retrieval for per-backup keys:**
      - For each component being restored, reads its `backup_history` entry to find:
          `{destination, restic_snapshot_id, keepass_key_path, routed_reason}`
      - Resolves `keepass_key_path` (the timestamped per-backup path) via secrets broker
          — automatically retrieves the unique key that was current for that specific backup
      - For chunked-split restores: reads all sub-component entries sharing the same
          `snapshot_set_id`; resolves each sub-component's key independently; restores
          each piece from its actual destination; assembles full snapshot set
      - For service-level restores (post-restic): retrieves service credentials from
          KeePass and re-injects into service config — no per-service password re-entry

      **Restore execution:**
      - Restores to target path; verifies file integrity post-restore via `restic check`
      - For chunked-split snapshot sets: restores sub-components in dependency order
          (volumes before containers, containers before VMs), assembles into target path
      - Generates structured restore report: component, destination, snapshot ID,
          timestamp, `routed_reason`, integrity verification result, KeePass path used
      - If a destination is unreachable at restore time, tries other destinations that
          hold the same component (if any — depends on whether backup ran to multiple)
      - Supports `--dry-run` (lists what would be restored, from where, which keys used)
      - Supports `--component` flag: restore a single VM, container, or volume
      - Supports `--snapshot-set` flag: restore all components of a specific backup point
          (identified by `snapshot_set_id` from `backup_history`)

- [x] 6.B.9: Documentation: `docs/CLOUD-STORAGE-SETUP.md` — step-by-step provider guides:
      - Google Drive (OAuth2 / Service Account — most complex; full walkthrough) ✓ written
      - Backblaze B2 (Application Key — simplest cloud option) ✓ written
      - AWS S3 (IAM user, access key/secret) ✓ written
      - Cloudflare R2 (S3-compatible, no egress fees) ✓ written
      - Self-hosted MinIO (S3-compatible, full privacy) ✓ written
      - Each guide dated; review reminder in document header

### Phase 7 — Service State

**7.1 — Service Contract Implementation**
- [x] Service Contract YAML spec format
- [x] Initial contracts for all known VMs
- [x] Service contract reader in Tier 2 collector
- [x] Service contract validator (observed vs. declared)
- [x] Dependency graph builder updated to use contracts as primary source

**7.2 — Service State Schema and Collection**
- [x] Finalise `service-state-schema.json` with `cell_id`
- [x] Service state collector
- [x] Service state in Tier 2 manifest
- [x] Service contract completeness in readiness scorer

**7.3 — External Dependency State (Phase 7 addition from v5.0)**
- [x] `data-model/external-dependency-state-schema.json`
- [x] External dependency declaration format (DNS provider, SMTP, cert authority) — `external_dependencies` in bootstrap-state.json; `doc-gen/external_dependencies.py` ExternalDependencyRegistry
- [x] Certificate expiry monitoring (RED ≤ 7d, ORANGE ≤ 30d, YELLOW ≤ 60d) — `_score_external_dependency_state()` in readiness.py
- [x] External dependency section in Recovery Runbook — Appendix G (endpoint, type, required_by, cert expiry with severity callouts)

**7.4 — Recovery Documentation Update (Service Layer)**
- [x] Service contract block per VM in restore sequence: provided interfaces,
      required interfaces, startup_after note, restart commands, secret references,
      per-interface health check checkboxes
- [x] Health check commands derived from contract: curl for HTTP/HTTPS (uses
      url_pattern when available, falls back to vm_ip:port), pg_isready for postgresql,
      nc for smtp, empty for ssh (already in standard block)
- [x] Service restart commands: ssh ubuntu@{ip} 'sudo systemctl restart {svc}'
- [x] Appendix A: edge type legend (SERVICE★/DEPENDS_ON/STORAGE/NETWORK/BACKUP)
      + ★ marker on SERVICE edges to distinguish contract-driven from heuristic

### Phase 8 — Network Topology as Code

- [x] 8.1: Network topology declaration format — `data-model/network-topology-schema.json`
      (bridges, VLANs, firewall policy) + `network_topology_declared` section in
      bootstrap-state-schema.json + canonical fixture in bootstrap-state.json
- [x] 8.2: Network topology collector — `proxmox-bootstrap/network_topology_collector.py`:
      parse_interfaces_file() parses /etc/network/interfaces format;
      collect_observed_bridges() SSHes to host (injectable runner for tests);
      compare_topology() diffs declared vs observed; merge_observed_topology()
      writes drift results back into bootstrap-state.json
- [x] 8.3: Network topology drift detection — compare_topology() returns
      (drift_detected: bool, drift_details: str); merge_observed_topology()
      persists both fields; readiness scorer surfaces as ORANGE/RED
- [x] 8.4: Recovery documentation Wave 0 — build_recovery_runbook() now emits
      a full "Wave 0 — Network Reconstruction" section before the restore sequence:
      per-bridge IP, ports, vlan_aware; verify commands (ip link, ip addr);
      reconstruct commands (ifreload -a from /etc/network/interfaces);
      drift warning if drift_detected; "NOT DECLARED" UNRESOLVED field if absent
- [x] 8.5: Network topology completeness in readiness scorer —
      _score_network_topology_completeness(): YELLOW if not declared; ORANGE if
      drift detected; RED if all declared bridges are missing in observed state

### Phase 9 — Phoenix Playbooks *(Stargate Process — reconstruction scripts)*

These are the playbooks that form the execution layer of the stargate process —
per-wave, per-VM scripts that reconstitute a failed node's identity on new hardware.
See Phase 12.E for the hatchery process playbooks (broodling spawn scripts).

- [x] 9.1: Phoenix playbook format and schema — `data-model/phoenix-playbook-schema.json`:
      schema_version, cell_id, target_node (hostname, role, k3s_role), identity
      (lan_ip, tailnet_ip, vmids, bridge_names, zfs_pool_name), hardware_profile,
      restoration_scope (full|partial|deferred), deferred_services, waves (playbook_wave
      → playbook_step with id, action, commands, validation, method, on_failure, secret_refs),
      estimated_total_minutes, validation_checklist
- [x] 9.2: Playbook generator — `proxmox-bootstrap/phoenix_playbook.py`:
      PhoenixPlaybookGenerator class + build_phoenix_playbook() factory;
      reads manifest (host_identity, vms, dns_registry, network_topology_declared,
      storage_config, provenance_registry); now_fn injectable for tests;
      _zfs_topology_from_disk_count() adapts topology to replacement hardware
- [x] 9.3: Wave 0 (network reconstruction) + Wave 1 (ZFS pool) + Wave 2 (host config) +
      Wave 3 (VM PBS restore, identity-preserving — same VMIDs, IPs, provenance info) +
      Wave 4 (k3s membership + Flux reconciliation) generated with pre-populated commands
- [x] 9.4: Wave 0.5 (template rebuild) playbook — _wave_05_template_rebuild() in
      PhoenixPlaybookGenerator; inserted at wave=2.5 between host config and VM restore;
      _os_variant_for_vm() reads k3s-cluster.yaml server_nodes[].os_variant;
      Ubuntu path: download ISO + qm create + qm template; Talos path scaffolded
- [x] 9.5: Per-VM RECREATE vs RESTORE decision — _vm_is_stateless() checks
      service_contract.backup_job==null AND provenance_registry.tofu_workspace present;
      stateless VMs: RECREATE (tofu apply + Ansible playbook); stateful VMs: RESTORE (qmrestore)
- [x] 9.6: Shell script generator — proxmox-bootstrap/phoenix_scripts.py:
      generate_wave_script(wave) → bash script with checkpoint tracking per step;
      generate_run_all_sh(playbook) → orchestrating entry point that calls each wave script
      in wave-number order with failure detection
- [x] 9.7: Playbook validator — proxmox-bootstrap/phoenix_validator.py:
      validate_playbook() → list of {severity, field, message} findings;
      ERROR: missing required fields, empty waves, duplicate wave/step IDs, invalid enum values,
      empty step commands; WARNING: missing vmids/bridges/pool in identity, non-ascending waves;
      is_valid() and summarise_findings() helper functions
- [x] 9.8: Playbook existence in readiness scorer — _score_phoenix_playbook_existence():
      YELLOW if neither phoenix_playbook nor phoenix_playbook_generated_at is present
      in the manifest; wired into score_graph() alongside other registry gap scorers

**9.T — Talos Alternative Support** *(optional; activate by setting os_variant: talos)*

*Foundation — build and config tooling:*
- [x] 9.T.1: `docs/TALOS-ALTERNATIVE.md` — prerequisites, build procedure for talos-1x-base
        template, talosctl installation, machine config generation, migration checklist
- [x] 9.T.2: `proxmox-bootstrap/build-talos-template.sh` — downloads Talos ISO,
        creates Proxmox VM, converts to template (talos-1x-base, VMID 9001)
- [x] 9.T.3: `proxmox-bootstrap/generate-talos-config.py` — generates talos machine
        configs from k3s-cluster.yaml (control plane + worker patches); stdlib only
- [x] 9.T.4: Talos template entry in bootstrap-state.json template registry
        (talos-1x-base alongside ubuntu-2204-base; separate base_image entry)
- [x] 9.T.5: bootstrap-state-schema.json — add `os_variant` enum (ubuntu | talos)
        to template registry entries and provenance_records
- [x] 9.T.6: doc-gen readiness scorer — YELLOW if os_variant=talos but no Talos
        machine config found in repo (talos-configs/ directory absent)
- [x] 9.T.7: Recovery runbook — emit Talos-specific reconstruction steps
        (talosctl apply-config instead of Ansible) when os_variant=talos
- [x] 9.T.8: Tests for Talos config generator and runbook rendering (57 tests)

*OS transition automation — Ubuntu → Talos:*
- [x] 9.T.9: `proxmox-bootstrap/migrate-k3s-to-talos.py` — automated migration script
        Steps: drain k3s node → snapshot VM → destroy Ubuntu VM → provision Talos VM
        from talos-1x-base template → apply machine config → verify cluster health →
        update bootstrap-state.json os_variant + provenance_records → commit to repo
        Flag: `--dry-run` prints plan without making changes
        Flag: `--skip-snapshot` for test environments where snapshot overhead is unwanted
        Guard: refuses to run if cluster health check fails pre-drain (RED readiness)
- [x] 9.T.10: Pre-migration checklist validator — confirms all prerequisites before
        migration begins: talos-1x-base template exists, machine config generated,
        Velero PVC backup current (ORANGE if any check fails; migration blocked until GREEN)
- [x] 9.T.11: Post-migration verifier — confirms k3s node rejoined cluster, all
        namespaces healthy, Flux reconciliation complete, PVCs reattached;
        writes migration completion record to bootstrap-state.json provenance_records
- [x] 9.T.12: Recovery runbook — "OS Variant Migration" appendix (Appendix I) documents
        all migration attempts from migration_history with per-record detail
        (node, direction, outcome, snapshot_vmid, error) and manual rollback commands.
        Both ODT and HTML renderers. 25 tests.

*OS transition automation — Talos → Ubuntu:*
- [x] 9.T.13: `proxmox-bootstrap/migrate-k3s-to-ubuntu.py` — automated reverse migration
        Steps: drain k3s node → snapshot VM → destroy Talos VM → provision Ubuntu VM
        from ubuntu-2204-base template → apply Cloud-Init + Ansible k3s-server role →
        verify cluster health → update bootstrap-state.json → commit to repo
        Same flags as 9.T.9 (--dry-run, --skip-snapshot)
        Guard: refuses to run if cluster health check fails pre-drain
- [x] 9.T.14: Shared migration library `proxmox-bootstrap/migrate_k3s_lib.py`
        Extract common steps from 9.T.9 and 9.T.13: drain, snapshot, VM destroy,
        health check, provenance record update. Both migration scripts import this.
- [x] 9.T.15: Migration state file `bootstrap-state.json migration_history` array
        Each completed migration appended: from_variant, to_variant, migrated_at,
        migrated_by, snapshot_vmid (for rollback), outcome
- [x] 9.T.16: Rollback procedure — if post-migration verifier fails, restore VM from
        pre-migration snapshot, update os_variant back, re-run health check;
        rollback outcome appended to migration_history (rollback() in migrate_k3s_lib.py)
- [x] 9.T.17: Tests for both migration scripts (mock Proxmox API + mock talosctl/ansible)
        48 tests in test_migration_k3s.py

### Phase 10 — Operational Documentation

- [x] 10.1: Operational documentation class design — `doc-gen/renderers/operational_report.py`;
      seven sections: overall readiness, drift summary, capacity, service health,
      secret completeness, external dependencies, time-sensitive actions
- [x] 10.2: Drift summary renderer — Section 2 reads manifest["drift"] (from compute_drift());
      shows from/to snapshot, severity, changed fields (capped at 30)
- [x] 10.3: Capacity trend renderer — Section 3 reads cpu/memory/storage from manifest;
      ORANGE/RED warnings on RAM ≥90% or storage ≥90% utilization
- [x] 10.4: Service health summary renderer — Section 4 reads manifest["service_state"];
      shows running/stopped/degraded counts and per-service status line
- [x] 10.5: Secret registry completeness renderer — Section 5 reads manifest["secret_registry"];
      shows total/with-path counts; lists secrets missing keepass_path
- [x] 10.6: Wire into engine.py — run_operational() function + `--mode operational` choice;
      loads all registries, computes drift + readiness, renders Operational-Report.html
- [x] 10.7: Scheduled refresh — `proxmox-bootstrap/setup-operational-schedule.sh` installs
      broodforge-operational.service + broodforge-operational.timer (every hour)

### Phase 11 — Capacity Model

- [x] 11.1: Capacity model schema — `capacity_model` section added to bootstrap-state-schema.json:
      thresholds (cpu/ram/storage warn/crit pcts + restoration_headroom_pct),
      observed (snapshot: ram/storage usage pcts + totals), trend (direction + days_to_full)
- [x] 11.2: Capacity tracking — `proxmox-bootstrap/capacity_collector.py`:
      collect_capacity_snapshot() reads cpu/memory/storage from manifest;
      merge_capacity_model() updates bootstrap-state.json with observed + trend
- [x] 11.3: Capacity validation in readiness scorer — _score_capacity_model():
      YELLOW: no capacity_model; YELLOW/ORANGE: RAM/storage above warn/crit threshold
- [x] 11.4: Trend analysis — compute_trend() derives direction (increasing/stable/decreasing)
      and days_to_full projection from ordered historical snapshots; uses linear rate
- [x] 11.5: ORANGE if target host cannot accommodate restored workload —
      check_restoration_headroom() compares sum(VM RAM) vs host RAM × (1 - headroom_pct)

### Phase 12 — Full Single-Cell Reconstruction Test

- [x] 12.1: End-to-end drill framework — `proxmox-bootstrap/reconstruction_drill.py`:
      DrillRecord (per-wave timing, gap tracking), start_drill() factory from phoenix playbook,
      save_drill_record() / get_last_drill() for bootstrap-state persistence,
      `reconstruction_drills[]` schema in bootstrap-state-schema.json;
      `docs/RECONSTRUCTION-DRILL.md` operator guide (live + tabletop modes)
- [x] 12.2: Reconstruction time measurement — DrillRecord.record_wave() tracks
      estimated vs actual minutes per wave; generate_drill_report() produces Markdown
      table with timing comparison and accuracy %; DrillRecord.accuracy_pct property
- [x] 12.3: Gap identification — DrillRecord.gaps_found/gaps_remediated; readiness scorer
      _score_reconstruction_drill(): YELLOW if no drill, YELLOW if > 90 days stale,
      ORANGE if last drill was failed/aborted; wired into score_graph()
- [x] 12.4: Scheduled drill activity — `proxmox-bootstrap/schedule-reconstruction-drill.sh`
      installs broodforge-drill-reminder.timer (fires every 90 days, logs journal reminder)

**Gate:** Phase 12 completion validates the single-cell foundation.
Track 2 begins after Phase 12.

### Phase 12.E — Node Spawn Bootstrap *(Hatchery Process)*

*The existing cluster is the hatchery. Additional nodes — broodlings — are spawned
from it via the **hatchery process**. Phase 12.E adds the ability to run the
hatchery process: the assessment engine produces a **spawn package** — a
self-contained archive of scripts and a reserved-resource data dump — that is
copied to a broodling after bare Proxmox installation and executed there. The
broodling joins the existing Proxmox cluster and k3s cluster without VMID, IP,
or hostname conflicts.*

**Hatchery process vs stargate process:**
The hatchery process (this phase) assigns *new* identity — VMIDs, IPs, hostnames
that don't conflict with anything already in the hatchery.
The stargate process (Phase 9) preserves *existing* identity — the exact VMIDs,
IPs, hostnames, and certs of a node that failed, reconstituted on new hardware.

**Context:** Phase 12 answers "can I rebuild this?" Phase 12.E answers "can I
spawn a broodling into this datacenter?" The assessment engine knows everything
the hatchery has reserved — IPs, VMIDs, hostnames, k3s join tokens, cluster
topology — and encodes that knowledge into the spawn package so the broodling
never needs to ask the operator what is already taken.

- [x] 12.E.1: **Hatchery state reader** — reads `bootstrap-state.json` and queries
      the live Assessment Engine API to extract a point-in-time reservation snapshot:
      all allocated VMIDs, all assigned IPs (from DNS registry + provenance records),
      all hostnames, Proxmox cluster join address, k3s server/worker counts,
      k3s join tokens (worker and server). Produces `spawn-manifest.json`.
      This is the authoritative "what the hatchery has reserved" data dump embedded
      in every spawn package.

- [x] 12.E.2: **Conflict validator** (`proxmox-bootstrap/validate-spawn.py`) —
      run before the spawn package is generated and again on the broodling before
      any deployment action:
      - No VMID collisions (proposed new VMIDs vs all VMIDs in spawn-manifest.json)
      - No IP collisions (proposed new IPs vs all IPs in spawn-manifest.json)
      - No hostname collisions (proposed hostnames vs all hostnames in spawn-manifest.json)
      - Placement policy satisfied (proposed roles are declared for this host type)
      - Capacity check: broodling RAM sufficient for its assigned VM roles
      RED finding on any collision blocks spawn package generation until resolved.
      The validator is designed to be re-run on the broodling from the spawn package
      itself, using only the embedded manifest (no live API access required).

- [x] 12.E.3: **Spawn planner with execution mode gate and service selection**
      (`proxmox-bootstrap/spawn-planner.py`) —

      The planner runs on the hatchery. **Execution mode is the first question**,
      because the answer determines whether service selection happens at all.

      **Step 0 — Network mode (asked before anything else):**

      Because the hatchery runs split-horizon DNS, the Headscale server URL in every
      spawn package is always the hatchery's FQDN (`host_identity.fqdn`):
        `https://hatchery.home.example.com:8080`
      LAN broodlings resolve this to the LAN IP via the hatchery's dnsmasq.
      WAN broodlings resolve this to the WAN IP via public DNS.
      The same spawn package works from both locations without modification.

      The planner still asks which network mode the broodling is on, because
      the SSH discovery path differs (direct IP vs tailnet IP):

      ```
      Is the broodling on the same LAN as the hatchery?
      [auto-detecting — trying {broodling-ip} directly... timeout 5s]

        1. Same LAN  — direct SSH using temporary root password
        2. WAN       — Headscale tailnet (generates auth key; Headscale URL is
                       hatchery.{domain} — already correct for both LAN and WAN)
        3. Specify   — enter broodling IP / hostname manually

      > _
      ```

      **LAN mode:** proceeds with the existing temporary root password flow.
        Broodling is configured to use hatchery as its DNS server (via DHCP or
        static config in spawn package), so `hatchery.{domain}` resolves to LAN IP.

      **WAN mode:** the planner calls:
        `headscale authkeys generate --expiration 1h --user broodforge`
        The auth key and `https://hatchery.{domain}:8080` are embedded in the
        spawn package. phase-00a on the broodling:
          Installs Tailscale: `curl -fsSL https://tailscale.com/install.sh | sh`
          Registers: `tailscale up --authkey {key}
                                   --login-server https://hatchery.{domain}:8080`
          (The FQDN resolves to WAN IP via public DNS, which routes to Headscale
          via the operator's router port forwarding.)
          Broodling appears on tailnet → hatchery SSHes to its tailnet IP for discovery.
        After spawn completes, Tailscale remains installed — the broodling is a
        permanent tailnet member. Its tailnet IP is recorded in bootstrap-state.json
        alongside its LAN IP (if any).

      **Step 1 — Execution mode (asked after network mode):**

      ```
      How should the spawn package run on the broodling?

        1. Autonomous (default)  — finalise service selection now; spawn.sh runs
                                   without prompting after the KeePass unlock gate
        2. Interactive            — no selection needed now; spawn.sh evaluates the
                                   broodling's hardware at runtime and presents the
                                   service menu there

      > _
      ```

      **If Interactive:** the planner records `execution_mode: interactive` and
      proceeds directly to package assembly. No service selection on the hatchery.
      The package includes all available service scripts. Service selection happens
      entirely on the broodling at execution time against actual hardware.

      **If Autonomous:** the planner continues to Step 2.

      For autonomous mode, the planner also generates a **suggested temporary root
      password** (readable passphrase format) at this point and displays it to the
      operator with the instruction to use it when setting the Proxmox root password
      during installation. The hatchery stores this password in memory for the
      duration of the spawn-planning session so it can use it for password-based SSH
      discovery without the operator re-entering it. The password is NOT stored in
      KeePass — it is temporary, replaced by a proper KeePass-managed credential
      during the spawn process.

      **Step 2 — Service selection (autonomous only):**

      The planner reads the service catalog (`metadata/service-catalog.yaml`) to
      know what the hatchery runs and the broodling's hardware profile to know what fits.

      **Mode 1 — Full mirror:**
      Selects all services that fit the broodling's hardware.
      Services that don't fit are listed with a reason (RAM, disk, dependency) and
      excluded. The operator reviews the exclusion list and confirms or switches mode.

      **Mode 2 — Select by group:**
      Services grouped by category (Infrastructure, Platform, Intelligence,
      Monitoring, Applications). Operator includes/excludes whole groups, then
      fine-tunes individual services within groups.

      **Mode 3 — Select individually:**
      Every service listed with hardware fit status, resource requirements, and
      dependencies. The planner enforces dependencies: selecting nextcloud
      automatically selects longhorn if not already selected.

      **Hardware fit display for each service:**
        [✓] fits — RAM available vs required shown; disk requirements shown
        [!] marginal — fits with reduced VM sizing; operator warned explicitly
        [✗] does not fit — specific shortfall shown (RAM delta, missing disk, etc.)
      Services marked [✗] are excluded regardless of selection.

      **The intelligence baseline is always included and cannot be deselected:**
      Proxmox cluster membership, k3s worker, assessment/doc engine visibility,
      `bootstrap-state.json` contribution. This is the minimum viable participation.

      **Produces `spawn-plan-{hostname}.json` containing:**
      - `disposition.execution_mode` — `autonomous` | `interactive`
      - `disposition.services` — selected service names (autonomous only; empty for interactive)
      - `disposition.mode` — `full-mirror` | `group` | `individual` (autonomous only)
      - `disposition.excluded` — services excluded with reason (autonomous only)
      - Non-conflicting VMID block, IPs, hostnames
      - ZFS pool topology from disk configuration
      - For autonomous: only VM roles, Cloud-Init snippets, Ansible roles for selected services
      - For interactive: full service catalog scripts included; selection deferred to broodling
      - k3s node labels and taints (autonomous: derived from selection; interactive: set at runtime)
      - Proxmox cluster join address (from manifest)
      - k3s join token type: worker always; server only if k3s-server selected (or selectable)
      - If 3rd server node possible: etcd migration plan included in interactive; locked in autonomous

- [x] 12.E.4: **Spawn hardware discovery (autonomous mode only)** — produces
      `hardware-profile-{hostname}.json` before the spawn package is generated.
      This is the input to the spawn planner for hardware-specific adaptation:
      disk topology → ZFS pool type, NIC inventory → bridge definitions, RAM → VM sizing.

      Two discovery paths depending on network mode selected in Step 0 of 12.E.3:

      **LAN mode — password-based SSH (same-network broodling):**
        The spawn planner generates a suggested temporary root password (readable
        passphrase format, e.g. `Ready.to.spawn.7`) at Step 0 selection time.
        The operator uses this password during Proxmox installation.
        The hatchery holds the password in session memory and SSHes directly:
          `python3 spawn_hardware_discovery.py --host {broodling-lan-ip} --password-prompt`
          (password retrieved from session, not re-entered by the operator)
          → `hardware-profile-{hostname}.json`
        If the operator used a different password, they enter it when prompted.
        Password transmitted over the trusted LAN only.
        Valid from: Proxmox installation complete.
        Valid until: Cloud-Init sets the real KeePass-managed credential.
        Not stored in KeePass; not persisted after the spawn session.

      **WAN mode — Headscale tailnet (cross-network broodling):**
        The spawn package contains the Headscale auth key and server URL.
        The broodling's `phase-00a` (runs before hardware pre-flight) installs
        Tailscale and registers with the hatchery's Headscale:
          `curl -fsSL https://tailscale.com/install.sh | sh`
          `tailscale up --authkey {key} --login-server {headscale_url}`
        Broodling appears on the tailnet → hatchery SSHes to its tailnet IP exactly
        as in LAN mode (temporary root password, same mechanism):
          `python3 spawn_hardware_discovery.py --host {tailnet-ip} --password-prompt`
        No port forwarding required. The WireGuard tunnel is the transport;
        the temporary root password is still the authentication.
        After spawn completes, Tailscale remains — the broodling is a permanent
        tailnet member. Its tailnet IP is recorded in bootstrap-state.json.

      **Interactive mode:** no hardware discovery on the hatchery is needed.
        spawn.sh discovers hardware locally on the broodling at runtime.
        In WAN mode, phase-00a (Tailscale join) still runs first so the hatchery
        can reach the broodling for any follow-up coordination.

      Discovery output is embedded in autonomous spawn packages so phase-00 can
      reference disk IDs and NIC layout without re-running discovery on the broodling.

- [x] 12.E.5: **Spawn IaC and config generator** — from `spawn-plan-{hostname}.json`:
      - OpenTofu `.auto.tfvars` for this host's VM set
      - Cloud-Init snippets with this host's allocated IPs (from spawn plan, not hatchery IPs)
      - Ansible inventory additions (this host appended to existing groups)
      - k3s join token embedded in Ansible role vars (from spawn manifest)

- [x] 12.E.6: **Spawn scripts** — generated shell scripts using the same
      checkpoint/failure-package/workbook-update library as recovery scripts.
      All scripts read from spawn-plan.json; bridge names, pool names, and IPs
      are consistent across phases because phase-00 creates what later phases reference.

      - `spawn.sh` — orchestrated entry point; runs all phases in order

      *Host-level phases (Proxmox host must be configured before VMs can exist):*

      - `phase-00-host-bootstrap.sh` — two sub-stages, always in order:

        **Sub-stage A: Hardware pre-flight (read-only, no changes made)**
        Re-scans the broodling's actual hardware and compares against the embedded
        `hardware-profile.json` and `spawn-plan.json`. This catches any divergence
        between what was discovered on the hatchery and what is actually present now.
        Checks (all must pass before sub-stage B runs):
          - Disk IDs in spawn plan exist on this host and have the expected capacity
          - NIC names/MACs match the embedded hardware profile
            (Proxmox can renumber NICs after kernel updates or hardware changes)
          - Available RAM ≥ sum of VM RAM in spawn plan + 10% host overhead
          - No existing ZFS pool with a name that conflicts with the planned pool
          - No existing network bridge with a name that conflicts with the plan
          - Conflict re-validation: re-runs validate-spawn.py against spawn-manifest.json
            (catches any hatchery reservations made between package generation and now)
        On any mismatch: generates a failure package with a clear "hardware mismatch"
        or "stale manifest" diagnosis, prints the diff, and exits without making
        any changes to the broodling. The operator re-runs discovery on the hatchery
        and regenerates the spawn package.
        On pass: proceeds to sub-stage B.

        **Sub-stage B: Host configuration (writes config, creates pool, activates network)**
        Must run before any VM creation because VMs reference bridges and datastores
        that only exist after this stage:
          set hostname + fix /etc/hosts (pvecm add fails if hostname → 127.0.0.1)
          write bridge definitions to /etc/network/interfaces (per NIC layout in plan)
          ifreload -a to activate bridges without full reboot
          zpool create per plan topology (disk IDs confirmed by pre-flight)
          pvesm add zfspool to register pool as Proxmox datastore
          configure apt repos (no-subscription or enterprise)
        Output: Proxmox host ready to accept VM provisioning and cluster join.

      - `phase-01-join-proxmox.sh` — `pvecm add <hatchery-address>` using Proxmox cluster
        join address and fingerprint from spawn manifest; idempotent (detects if
        already a member). New host now visible in Proxmox datacenter.

      *VM provisioning phases (depend on phase-00 bridge/datastore names existing):*

      - `phase-02-vms.sh` — `tofu apply` using tfvars from spawn plan; bridge
        names and datastore names in tfvars match what phase-00 created exactly.

      - `phase-03-cloudinit.sh` — install generated Cloud-Init snippets (user-data,
        network-config, vendor-data) into Proxmox snippet store on this host;
        start VMs; poll SSH readiness for each VM before proceeding.

      *Cluster join phases (depend on VMs running):*

      - `phase-04-join-k3s.sh` — run Ansible k3s-server or k3s-worker role against
        the new VMs using join token from spawn manifest; selects correct token type
        (worker or server) based on spawn plan role.

      - `phase-05-promote-ha.sh` (conditional) — SQLite → embedded etcd migration;
        only generated when this broodling creates the 3rd k3s server node. Existing
        hatchery cluster is quiesced, etcd promoted, control plane distributed. If this phase
        is not needed, it is omitted from the package entirely.

      - `phase-06-verify.sh` — cluster health check (all nodes Ready, all VMs
        running), re-runs conflict validator against live Proxmox and k3s state
        as final confirmation. Failure here generates a failure package.

      *[Automatic after phase-06 — no further operator action:]*
      *Flux CD detects new k3s nodes, schedules workloads per anti-affinity rules.*
      *Assessment Engine detects broodling in Proxmox API, updates scores.*
      *Documentation Engine regenerates topology with broodling included.*

- [x] 12.E.7: **Spawn package assembler** (`proxmox-bootstrap/assemble-spawn-package.py`) —
      bundles spawn-manifest.json, spawn-plan-{hostname}.json, generated scripts,
      OpenTofu tfvars, Cloud-Init snippets, Ansible additions, spawn workbook HTML,
      and the shared script library into:
      `spawn-package-{cell_id}-{hostname}-{YYYY-MM-DD_HH_MM_SS}.tar.gz`
      The package is self-contained and offline-capable: the broodling does not need
      to reach the hatchery's API during execution.
      **The package never contains the KeePass database or any secret values.**
      It contains only KeePass secret paths (references). See AD-042.

- [x] 12.E.7a: **KeePass unlock gate in spawn.sh** — before any phase accesses secrets,
      `spawn.sh` prompts the operator to enter the KeePass master password and verifies
      it unlocks the operator's KeePass database (copied separately to the broodling or
      accessed via a known path). Scripts retrieve individual secrets programmatically
      from the unlocked database; no secret value is written to the broodling's disk in
      plain text. The gate runs regardless of execution mode (autonomous or interactive).
      In autonomous mode, this is the only prompt before fully automated execution.
      In interactive mode, this gate is followed by the service selection prompt.

- [x] 12.E.8: **Spawn workbook** (HTML) — embedded in the spawn package; tracks
      each phase with the same checkpoint/status/timestamp/validation pattern as
      the recovery workbook:
      - Sheets: Overview, Discovery, Storage, Network, Proxmox-Join, VMs, k3s-Join, Validation
      - Machine-updated by each spawn script phase
      - Spawn failure package generated automatically if any phase fails

- [x] 12.E.9: **Bootstrap-state.json updater** — runs on the hatchery after the
      broodling reports successful spawn (phase-08-verify.sh exits 0); merges the broodling's
      hardware profile, allocated VMIDs, IPs, hostnames, and cluster role into
      `bootstrap-state.json`; adds provenance records for new VMs; commits to Forgejo.
      Assessment Engine reassessment triggered automatically by Forgejo webhook.

- [x] 12.E.10: **Disposition-aware assessment scoring** — the Assessment Engine
      reads `disposition.services` from each host's entry in `bootstrap-state.json`
      and adjusts placement compliance evaluation to match declared intent:
      - Placement compliance is checked per service, per host: is this service
        running on the hosts that declared it in their disposition?
      - A node without `prometheus` in its service list is not penalized for
        missing a Prometheus replica
      - A node without `k3s-server` is not scored against HA control-plane
        distribution requirements
      - A node without `pbs-datastore` is not flagged for missing backup targets
      - The assessment report shows each host's `disposition.services` list
        alongside its scores — visible confirmation of what each node is expected
        to contribute and whether it is delivering
      - `disposition.excluded` (services that didn't fit at spawn time) is also
        shown, so the operator knows what was intentionally left out vs. what
        drifted away after deployment
      - A mismatch between `disposition.services` and observed reality remains a
        RED finding — disposition does not excuse services that were selected but
        are not running

- [x] 12.E.11: **Spawn scenarios tested:**
      - Baseline only (small machine): joins cluster, visible to assessment, no workloads
      - Compute disposition: k3s workers added, Flux schedules workloads
      - Storage disposition: PBS datastore added, Longhorn replicas
      - Control-plane disposition: HA promotion if 3rd server node
      - Mixed disposition (compute + storage): combined deployment
      - Hardware insufficient for selected flag: flag dropped with warning, rest proceeds
      - Full peer disposition: matches hatchery capabilities
      All scenarios use fixture hardware profiles. Conflict detection validated with
      deliberate VMID/IP/hostname collision fixtures.

- [x] 12.E.12: **Documentation:** `proxmox-bootstrap/NODE-SPAWNING.md` — operator
       runbook covering: prerequisites (bare Proxmox installed, SSH access),
       running hardware discovery on the broodling, selecting disposition interactively
       on the hatchery, reviewing the spawn plan's hardware fit assessment and warnings,
       copying and executing the spawn package on the broodling, verifying cluster
       health, and confirming `bootstrap-state.json` is updated with the broodling's
       disposition and state.

**Note on hardware heterogeneity:** The spawn planner explicitly does NOT require
identical hardware. A second host with 6 HDDs gets raidz1; the first host with
2 SSDs has a mirror. Both run the same VM roles and software stack. Only the
hardware adaptation layer (ZFS topology, NIC bridge config, VM sizing within
available RAM) differs between them.

**Note on Talos variant:** If `os_variant: talos` is declared for k3s-server nodes
(see Milestone 9.T), the spawn planner emits Talos machine configs instead of
Cloud-Init for server VMs on the broodling. The spawn plan records `os_variant`
per VM, matching the existing cluster's declared variant.

---

## Track 2 — Expanded State Model

### Phase 13 — Hardware and Platform State

- [x] 13.1: `data-model/hardware-state-schema.json` (BIOS, firmware, disks, NICs, UPS)
- [x] 13.2: Hardware State Tier 1 collector (extend bootstrap assessment)
- [x] 13.3: `data-model/platform-state-schema.json` (Proxmox config, certs, packages)
- [x] 13.4: Platform State Tier 2 collector
- [x] 13.5: Hardware requirements declaration in Bootstrap State
- [x] 13.6: Pre-reconstruction hardware verification playbook
- [x] 13.7: Hardware and Platform readiness scoring

### Phase 14 — Cluster and Storage State

- [x] 14.1: `data-model/cluster-state-schema.json` (identity, topology, membership, history)
- [x] 14.2: Cluster State collector (Proxmox cluster API, Corosync, HA manager)
- [x] 14.3: `data-model/storage-state-schema.json` (ZFS, Ceph, CephFS, RBD, datastores)
- [x] 14.4: Storage State collector (ZFS CLI, Ceph status API)
- [x] 14.5: Ceph FSID in readiness scorer (RED if missing)
- [x] 14.6: Cluster and Storage waves in Reconstruction Playbook generator

### Phase 15 — Data Protection State

- [x] 15.1: `data-model/data-protection-state-schema.json` (PBS, jobs, retention, RTO/RPO)
- [x] 15.2: Data Protection collector (PBS API, backup job inventory, verification status)
- [x] 15.3: RTO/RPO declaration format and compliance scoring
- [x] 15.4: Backup encryption key recoverability check (RED if not recoverable)
- [x] 15.5: PBS self-recovery plan check (ORANGE if absent)
- [x] 15.6: Data Protection readiness scoring additions

### Phase 16 — Observability State

- [x] 16.1: `data-model/observability-state-schema.json` (monitoring stack, alerts, dashboards)
- [x] 16.2: Observability State collector
- [x] 16.3: Observability reconstruction in playbook generator
- [x] 16.4: Alert rule restoration in Recovery Runbook

### Phase 17 — Digital Twin Foundation

- [x] 17.1: Cell Identity schema and registry (`twin/federation/cells/`)
- [x] 17.2: Twin storage layout (full `twin/` directory structure)
- [x] 17.3: Twin state writer (all collectors write to twin, not only history/)
- [x] 17.4: Staleness manifest (per-field confidence and last-updated tracking)
- [x] 17.5: Twin consistency checker (stale, missing, conflicting state detection)
- [x] **17.6: `cell_id` migration — all existing schemas updated (federation gate)**

### Phase 18 — Capability and Secret Reference State

- [x] 18.1: `data-model/capability-state-schema.json` (all capability categories)
- [x] 18.2: Capability declaration format and initial declaration
- [x] 18.3: Capability verification in Tier 2 assessment
- [x] 18.4: Capability index builder (aggregation across all cells)
- [x] 18.5: `data-model/secret-reference-state-schema.json` (standalone, with `owning_cell`)
- [x] 18.6: Secret Reference State migration (extract from Bootstrap State)
- [x] 18.7: Capability-based readiness scoring additions

**Gate:** Phase 18 completion validates the expanded state model.
Track 3 begins after Phase 18.

---

## Track 3 — Digital Twin and Federation

### Phase 19 — Federation State and Trust Model

- [x] 19.1: `data-model/federation-state-schema.json` (cell registry, relationships, trust)
- [x] 19.2: Cell identity and federation registry
- [x] 19.3: Trust relationship schema and declaration format (all relationship types)
- [x] 19.4: Trust relationship verification procedure (CLI + automated check)
- [x] 19.5: Recovery relationship schema and declaration format
- [x] 19.6: Recovery relationship verification (backup reachable, history readable)
- [x] 19.7: Tier 3 assessment engine (cross-cell, federation-scope)
- [x] 19.8: Federation State tests

### Phase 20 — Federation Documentation Generation

- [x] 20.1: Federation Workbook renderer (all cells, all relationships, federation readiness)
- [x] 20.2: Federation Runbook renderer (coordination procedures)
- [x] 20.3: Cell Workbook (full 17-state view per cell)
- [x] 20.4: Cell Runbook (full cell reconstruction)
- [x] 20.5: Cluster Workbook and Runbook
- [x] 20.6: Node Workbook and Runbook
- [x] 20.7: Dependency Workbook (all five graph types, multi-cell scope)
- [x] 20.8: Command Reference Sheets (pre-populated for all known values)
- [x] 20.9: Validation Sheets (post-recovery checklists)

### Phase 21 — Failure Domain Modeling

- [x] 21.1: Failure domain taxonomy schema
- [x] 21.2: Failure propagation rules engine (storage → VMs → services propagation)
- [x] 21.3: Blast radius calculator (given failure at level X, enumerate affected)
- [x] 21.4: SPOF detection (components with no recovery alternative)
- [x] 21.5: Circular recovery dependency detection
- [x] 21.6: Failure domain analysis in readiness reports

### Phase 22 — Multi-Level Readiness Assessment

- [x] 22.1: Hardware-level readiness scoring (new inputs from Phase 13)
- [x] 22.2: Cluster-level readiness scoring (new inputs from Phase 14)
- [x] 22.3: Cell-level readiness (aggregation across all 17 state categories)
- [x] 22.4: Federation-level readiness (aggregation across all cells)
- [x] 22.5: Federation Readiness Report
- [x] 22.6: Tier 3 assessment integration with multi-level readiness

### Phase 23 — Federated Reconstruction Planning

- [x] 23.1: Recovery coordinator model (coordinator selection from capability index)
- [x] 23.2: Phoenix package assembly (history, docs, repos, secrets, backup locations)
- [x] 23.3: Capability matching (find available cells for each recovery need)
- [x] 23.4: Multi-phase reconstruction playbook generator (all 7 phases)
- [x] 23.5: Cross-cell trust establishment automation
- [x] 23.6: Temporary workload migration planning
- [x] 23.7: Federated reconstruction tests

### Phase 24 — Continuous Assessment and Twin Maintenance

- [x] 24.1: Scheduled assessment framework (cron-driven, cell-scoped)
- [x] 24.2: Repository ingestion hooks (git webhook → twin update on push)
- [x] 24.3: Deployment event hooks (tofu apply / ansible run → twin update)
- [x] 24.4: Staleness alerting (notify when state categories exceed threshold)
- [x] 24.5: Twin diff reporting (what changed in the twin since last report)
- [x] 24.6: PBS API integration for continuous Data Protection State updates
- [x] 24.7: Certificate expiry monitoring (continuous External Dependency State)

### Phase 25 — Reconstruction Validation

- [x] 25.1: Reconstruction drill framework (scheduled full-destroy + reconstruct)
- [x] 25.2: Reconstruction time measurement and RTO validation
- [x] 25.3: Automated post-reconstruction assessment and comparison
- [x] 25.4: Gap identification and remediation tracking
- [x] 25.5: Federation reconstruction drill (multi-cell coordinated scenario)

---

## Track 4 — Autonomous Operations

*Prerequisite: Tracks 1–3 complete. The assessment engine must be operational,
continuous assessment (Phase 24) running, and the digital twin current before
autonomous remediation can propose meaningful actions.*

### Design contract for autonomous remediation

The assessment engine has always surfaced gaps and scored them. Track 4 closes
the loop: from detection → proposal → human approval → execution → reassessment.

**The core constraint is this: remediation is proposed, not imposed.**
The system recommends; the operator approves; the system executes.
No autonomous action changes infrastructure state without a recorded human
approval. This constraint is not a configuration option — it is architectural.

**Scope of autonomous action.** The executor handles reversible, observable,
low-blast-radius operations. It explicitly does not handle:
- Destruction of data, VMs, volumes, or snapshots
- Changes to Proxmox cluster membership (those go through forge/spawn/phoenix flows)
- Modifications to authoritative metadata YAML files
- KeePass credential changes (those require the KeePass gate in an operator session)
- Network topology declaration changes (operators must update the source of truth)
- Any operation the operator has not explicitly approved in this session

Anything not on the allowed-action list is blocked at the executor layer,
regardless of what the planner proposes. An overly broad proposal is rejected
before it runs, not after.

---

### Phase 26 — Autonomous Remediation

*Closes the assess → detect → propose → approve → execute → reassess loop.*

**26.1 — Remediation Planner** (`proxmox-bootstrap/remediation_planner.py`)

Reads the current readiness report and twin state to produce a structured
`RemediationPlan`: an ordered list of `RemediationProposal` objects, each
with enough context for the operator to make an informed approval decision.

Each proposal records:
- `proposal_id` — stable UUID; survives across assessment cycles until resolved
- `issue_id` — references the specific gap or readiness finding that triggered it
- `severity` — mirrors the assessment score (YELLOW/ORANGE/RED) of the underlying issue
- `action_type` — enumerated type (see below); determines which executor handler runs
- `action_description` — human-readable "what will happen if you approve this"
- `target` — component, service name, or node hostname the action affects
- `dry_run_output` — what the action would produce, captured without making changes
- `reversibility` — `reversible` | `irreversible` | `manual-rollback`; RED is blocked unless reversible
- `estimated_duration_seconds` — from historical execution data
- `proposed_at` — UTC timestamp
- `prerequisite_ids` — other proposals that must execute successfully first

Allowed action types (exhaustive list — anything not here is rejected at the
executor):

| Action type | What it does | Reversibility |
|---|---|---|
| `restart-service` | `systemctl restart {svc}` on target VM | Reversible (stop again) |
| `run-backup` | `python3 run-backup.py --layer {layer}` | Reversible (restore from prior) |
| `renew-cert` | `certbot renew` or `acme.sh --renew` for near-expiry cert | Reversible (prior cert still valid) |
| `regenerate-phoenix` | Re-run phoenix playbook generator for stale node package | Reversible (old package kept) |
| `sync-cert-to-k8s` | Re-run `sync-cert-to-k8s.sh` to push renewed cert into cluster secrets | Reversible (old secret restored from cert) |
| `rotate-join-token` | Generate new k3s join token; update bootstrap-state.json | Manual rollback |
| `restart-assessment-timer` | `systemctl enable --now broodforge-operational.timer` | Reversible |
| `schedule-drill` | Append a drill reminder entry to bootstrap-state.json | Reversible (delete entry) |
| `flag-manual` | Mark a finding for manual operator attention; no system change | N/A |

The planner never proposes an action outside this list. Unknown findings produce
`flag-manual` proposals, never executable ones.

- [x] 26.1.1: `RemediationProposal` dataclass and schema additions to `bootstrap-state-schema.json`
- [x] 26.1.2: Planner logic — map each gap type to its allowed action type
- [x] 26.1.3: Dry-run execution for each action type (produces `dry_run_output` without making changes)
- [x] 26.1.4: Proposal deduplication — if an identical proposal already exists in the queue, update it rather than creating a duplicate
- [x] 26.1.5: Integration with `engine.py --mode operational` — proposals generated automatically at the end of each operational assessment run
- [x] 26.1.6: Tests (propose phase: 30+ cases covering all action types and edge cases)

**26.2 — Approval Queue** (`proxmox-bootstrap/remediation_queue.py`)

Manages the lifecycle of proposals from creation through execution.

State machine per proposal:
```
proposed → approved → executing → resolved
        ↘ rejected
        ↘ superseded   (newer proposal for same issue replaces this one)
        ↘ expired      (underlying issue resolved by other means before approval)
```

Queue storage: `remediations` array in `bootstrap-state.json`. Each entry persists
until resolved, rejected, or superseded. Queue is committed to Forgejo on every
state change so the record is version-controlled and auditable.

Approval record per transition:
- `approved_by` — operator identifier (hostname + Unix user, or dashboard session token)
- `approved_at` — UTC timestamp
- `approval_channel` — `cli` | `dashboard` | `auto-policy`
- `approval_note` — optional free-text comment from operator

Auto-approve policy (operator-configured, disabled by default):
- `auto_approve_threshold`: `null` (disabled) | `YELLOW` | `ORANGE`
- When set, proposals at or below the threshold are auto-approved on creation
- RED proposals are **never** auto-approved regardless of policy
- `irreversible` proposals are **never** auto-approved regardless of policy
- Auto-approvals are recorded with `approval_channel: auto-policy`

- [x] 26.2.1: Queue data model — `RemediationQueue`, state machine transitions, storage in bootstrap-state.json
- [x] 26.2.2: CLI for queue management (`python3 proxmox-bootstrap/remediation-cli.py`):
  - `list` — show pending proposals with dry-run summary
  - `approve {id}` — approve a single proposal
  - `approve-all --severity YELLOW` — batch approve by max severity
  - `reject {id} [--reason text]` — reject a proposal
  - `dry-run {id}` — re-run dry-run and display output
  - `history` — show resolved/rejected proposals
- [x] 26.2.3: Auto-approve policy configuration (stored in `bootstrap-state.json remediation_policy`)
- [x] 26.2.4: Proposal expiry — if the underlying issue is no longer present in the assessment, mark proposal as `expired` rather than leaving it in the queue
- [x] 26.2.5: Tests (queue lifecycle: 25+ cases)

**26.3 — Executor** (`proxmox-bootstrap/remediation_executor.py`)

Executes approved proposals with the same checkpoint and failure-package semantics
as spawn/forge/phoenix scripts.

Execution contract:
1. **Re-validate** the proposal before running: confirm the underlying issue still
   exists and the action type is still on the allowed list. Cancel if either check fails.
2. **Record the start** in bootstrap-state.json (status → `executing`, `started_at`).
3. **Dry-run first** — re-run dry-run and diff against the original. If significantly
   different, pause and surface for re-approval rather than proceeding.
4. **Execute** the action.
5. **Checkpoint** at each meaningful step (mirrors spawn checkpoint pattern).
6. On failure: generate a `RemediationFailurePackage` (same structure as spawn failure
   packages) and set status to `failed`. Never silently swallow errors.
7. On success: record `resolved_at`, `outcome`, and transition to `resolved`.
8. **Trigger reassessment** — queue a fresh operational assessment run so the twin
   reflects the post-remediation state.

KeePass gate: any action that requires secrets (e.g. `rotate-join-token`,
`run-backup`) requires the KeePass gate to be unlocked for that session. The
executor checks for the gate before starting; if not unlocked, it suspends
execution and prompts via `/dev/tty` — it never starts a secrets-accessing action
unattended.

- [x] 26.3.1: `RemediationExecutor` class — pre-validate, checkpoint, execute, post-record
- [x] 26.3.2: Handler per action type (one function per allowed action type from 26.1)
- [x] 26.3.3: KeePass gate integration — suspend if gate not unlocked for secrets-requiring actions
- [x] 26.3.4: `RemediationFailurePackage` — extends failure package format from spawn
- [x] 26.3.5: Post-execution reassessment trigger
- [x] 26.3.6: Tests (executor: 35+ cases, all action types + failure paths)

**26.4 — Dashboard Integration**

Expose the remediation queue in the broodforge sidecar dashboard (`broodforge_dashboard.py`)
so operators can review and approve proposals from the browser.

New endpoints:
- `GET /api/remediations` — list proposals (filterable by status and severity)
- `GET /api/remediations/{id}` — full proposal detail including dry-run output
- `POST /api/remediations/{id}/approve` — approve (requires `X-Broodforge-Token` header)
- `POST /api/remediations/{id}/reject` — reject with optional reason
- `POST /api/remediations/approve-batch` — approve multiple by severity threshold

Dashboard HTML additions:
- New **Remediations** section in the main dashboard page
- Pending proposals listed with: severity badge, action description, target, dry-run summary, approve/reject buttons
- Executed history section showing resolved and failed proposals
- Auto-approve policy display and toggle

Token requirement: all POST endpoints require the `X-Broodforge-Token` header
(already enforced for `analyze-failures`). A proposal approved from the dashboard
records `approval_channel: dashboard`.

- [x] 26.4.1: `GET /api/remediations` and `GET /api/remediations/{id}` endpoints
- [x] 26.4.2: `POST` approval/rejection endpoints with token gate
- [x] 26.4.3: Dashboard HTML section — proposal cards with approve/reject buttons
- [x] 26.4.4: Batch approve endpoint with severity filter
- [x] 26.4.5: Tests (dashboard endpoints: 15+ cases)

**26.5 — Feedback Loop and Reporting**

Close the loop: verify that approved remediations actually resolved the issue,
and surface the closed-loop record in operational reports.

- `RemediationRecord` — links a proposal, its execution result, and the post-execution
  assessment delta (was the gap actually closed?)
- Operational Report (Section 8 — new) — Remediation Summary:
  - Pending proposals awaiting approval (count by severity)
  - Recently executed proposals (last 30 days) with outcomes
  - Failed remediations requiring operator attention
  - Issues that were auto-approved and resolved without intervention
  - Issues that resisted remediation (executed but issue persists after reassessment)

- [x] 26.5.1: `RemediationRecord` — execution + post-assessment delta + closed-loop status
- [x] 26.5.2: Operational report Section 8 — Remediation Summary renderer
- [x] 26.5.3: HTML operational report update — Section 8 added to `html_operational_report.py`
- [x] 26.5.4: `resists_remediation` flag — if an action executed successfully but the
  underlying issue is still present in the next assessment, the proposal is marked
  `resisted` and escalated to the operator
- [x] 26.5.5: Tests (feedback loop: 20+ cases)

**26.6 — Policy Engine and Federation Remediation**

*Advanced optional sub-phase.*

**Policy engine** (`proxmox-bootstrap/remediation_policy.py`):
Fine-grained control over what can be auto-approved, what requires human approval,
and what is blocked entirely. Per-action-type overrides supplement the global
severity threshold.

Policy fields (stored in `bootstrap-state.json remediation_policy`):
- `auto_approve_threshold`: global max severity for auto-approval (default: null)
- `blocked_action_types`: list of action types that are always blocked regardless of approval
- `require_approval_action_types`: action types always requiring approval even if under threshold
- `max_concurrent_executions`: number of proposals that can execute simultaneously (default: 1)
- `execution_window`: time-of-day window when executions may run (cron-style expression)
- `notify_on_proposal`: emit a structured log event when new proposals are generated
- `notify_on_approval`: emit a structured log event when proposals are approved
- `notify_on_outcome`: emit a structured log event when proposals complete or fail

**Federation remediation**:
A federated remediation proposal is one that requires coordination across cells.
Example: Cell A's backup is failing because Cell B (the backup destination) is
full. The proposal must be visible to operators of both cells; approval from
the "owning cell" operator is required before execution.

Cross-cell proposals are stored in the federation state (Phase 19) alongside the
originating cell's bootstrap-state.json. The federation runbook (Phase 20) gains a
"Pending Remediations" section.

- [x] 26.6.1: `RemediationPolicy` dataclass and schema; CLI to update policy
- [x] 26.6.2: Execution window enforcement (don't execute outside configured hours)
- [x] 26.6.3: Concurrent execution limit (serialize by default; operator can allow parallel)
- [x] 26.6.4: Cross-cell proposal format — `owning_cell_id`, `requires_cell_approval[]`
- [x] 26.6.5: Federation remediation view in Federation Workbook (Phase 20 extension)
- [x] 26.6.6: Tests (policy engine: 20+ cases; cross-cell: 10+ cases)

**26.7 — Fully Autonomous Mode** *(optional — must be explicitly enabled by an operator)*

An opt-in execution mode in which the assessment engine detects issues, the
planner generates proposals, and the executor runs them without waiting for
per-action approval. The gated model (Phase 26.1–26.6) remains the default and
is always available regardless of whether this mode is active.

**This mode exists for operators who are comfortable with the bounded action
list and want the platform to self-maintain without manual intervention on
routine maintenance tasks.** It is not the right mode for initial deployment,
unstable environments, or any cell where operator oversight of each change is
required.

*Autonomous mode never changes which actions are possible — only who initiates
execution. The bounded action-type list, the hard exclusions, and the full audit
trail from Phases 26.1–26.6 apply without exception.*

---

**Enabling ceremony — two-step confirmation required**

Autonomous mode cannot be turned on by editing a config file directly. It
requires a deliberate interactive ceremony so the operator understands exactly
what they are enabling before it takes effect:

```
$ python3 proxmox-bootstrap/remediation-cli.py enable-autonomous

Current policy review
=====================
Cell:            proxmox-cell-a
Assessment:      operational (running every 1 hour)
Pending queue:   3 proposals awaiting approval
Action types in scope for autonomous execution:
  restart-service, run-backup, renew-cert, regenerate-phoenix,
  sync-cert-to-k8s, restart-assessment-timer, schedule-drill
Maximum severity for autonomous execution: ORANGE
Execution window: any time (no restriction)

HARD EXCLUSIONS — these are NEVER executed autonomously regardless of policy:
  ✗ Any action with reversibility: irreversible
  ✗ RED-severity findings
  ✗ Actions requiring KeePass gate (those remain per-action gated)
  ✗ Cross-cell actions (those remain per-cell-operator gated)

What will happen if you continue:
  Approved: new proposals at or below ORANGE will execute automatically
            on the next assessment cycle after they are proposed.
  NOT approved: the 3 existing proposals in the queue still require
                per-action approval — autonomous mode applies to new proposals
                generated after this point, not retroactively.

This mode will auto-disable after 30 days (2026-07-02) unless renewed.
To disable at any time: remediation-cli.py disable-autonomous

Type 'enable autonomous' to confirm, or Ctrl-C to cancel:
> _
```

The confirmation phrase must be typed exactly. A mistype aborts with no change.
After confirmation the mode is recorded in `bootstrap-state.json` with:
- `enabled_by` — Unix user + hostname at enable time
- `enabled_at` — UTC timestamp
- `enabled_via` — `cli` | `dashboard`
- `expires_at` — UTC timestamp (default 30 days; configurable; null = no expiry)
- `scope` — the exact policy in effect at enable time (snapshot)

The operator is shown a summary of the enabling record before the prompt
returns, confirming what was stored.

---

**Hard exclusions — enforced at the executor layer, not by policy**

These restrictions cannot be overridden by any policy setting. They are checked
inside the executor before any autonomous execution begins:

| Exclusion | Reason |
|---|---|
| `reversibility: irreversible` actions | Cannot be undone if the assessment was wrong |
| RED-severity findings | The system should not self-heal critical failures without a human confirming the diagnosis |
| KeePass-gated actions | Unattended secrets access requires a separate unlock mechanism not yet implemented; these remain per-action gated in all modes |
| Actions affecting more than one cell | Cross-cell blast radius requires coordinated approval |
| Actions on a cell whose last assessment is older than 2× the assessment interval | Stale state means the proposal may be based on outdated information |
| Actions during an active reconstruction drill | Do not remediate a cell that is deliberately in a degraded state for testing |

---

**Scope constraints — set at enable time**

The operator can restrict autonomous mode to a subset of actions and severity
levels at enable time. Restrictions are stored in the enabling record and cannot
be loosened without re-running the enabling ceremony.

| Constraint | Default | Meaning |
|---|---|---|
| `autonomous_action_types` | All safe types | List of action types that may execute autonomously; `rotate-join-token` excluded from default |
| `autonomous_max_severity` | `ORANGE` | Maximum severity level; cannot be set to `RED` |
| `autonomous_execution_window` | Any time | Cron-style expression restricting when executions may run |
| `autonomous_max_concurrent` | 1 | How many proposals may execute in parallel |
| `autonomous_expires_at` | 30 days | UTC timestamp after which mode auto-disables; `null` = no expiry |
| `autonomous_notify` | `true` | Emit a structured log event for every autonomous execution |

---

**Notifications — what happens without per-action approval**

Because the operator is not involved in each action, the platform must report
what it did. Every autonomous execution emits a structured notification event
that the operator can consume via:
- The dashboard **Remediation History** view (always)
- The operational report Section 8 "Autonomous Executions" subsection (always)
- SMTP email (if external SMTP dependency configured in bootstrap-state.json)
- A structured log entry in the systemd journal (always; can be monitored by any log aggregator)

The notification includes: what issue was detected, what action ran, what changed,
the outcome (success/failed/resisted), and the next scheduled reassessment time.

If an autonomous execution fails or a remediated issue persists after reassessment
(`resisted`), the finding is escalated: an immediate notification is sent and the
specific proposal is moved back to the `gated` approval mode until the operator
reviews it. Repeated failures disable autonomous mode for that action type
automatically.

---

**Disabling autonomous mode**

Autonomous mode can be disabled at any time with no confirmation required:

```
$ python3 proxmox-bootstrap/remediation-cli.py disable-autonomous
[remediation] Autonomous mode disabled.
[remediation] Proposals in queue: 2 now require per-action approval.
[remediation] Disable recorded: 2026-06-15T14:22:00Z by root@hatchery
```

Or from the dashboard via the "Disable autonomous mode" button (no confirmation
prompt in the UI — disabling is always safe and immediate).

Auto-disable triggers (without operator action):
- `expires_at` timestamp reached
- N consecutive failed executions (configurable; default: 3)
- N consecutive `resisted` outcomes (configurable; default: 2 for the same issue)
- Cell readiness drops to RED (the platform self-demotes out of autonomous mode
  when the cell is in a critical state)

Every auto-disable event is logged with the triggering reason and sent as a
high-priority notification.

---

**Dashboard integration**

New elements in `broodforge_dashboard.py`:
- Prominent **autonomous mode status badge** in the topbar: `AUTO` (green) when enabled, `GATED` (muted) when not
- **Enable/Disable** button in the Remediations section (Enable requires a confirmation modal that mirrors the CLI ceremony; Disable is immediate)
- **Autonomous executions** subsection in Remediation History — separate from the manual-approval history
- **Scope display** — shows the exact constraints in effect when autonomous mode is enabled
- **Auto-disable countdown** — shows time remaining until expiry if `expires_at` is set

---

- [x] 26.7.1: `autonomous_mode` field group in `bootstrap-state-schema.json` and `RemediationPolicy`
- [x] 26.7.2: Enabling ceremony in `remediation-cli.py` — two-step confirmation, scope review, enabling record
- [x] 26.7.3: Executor integration — skip approval-wait step for in-scope proposals when autonomous mode is active
- [x] 26.7.4: Hard exclusion enforcement in executor — checked independently of policy
- [x] 26.7.5: Auto-disable triggers (expiry, consecutive failures, RED cell state)
- [x] 26.7.6: Notification events — structured log + SMTP if configured + dashboard update
- [x] 26.7.7: Dashboard — autonomous mode badge, enable/disable controls, scope display, auto-disable countdown
- [x] 26.7.8: Stale-state guard — refuse autonomous execution if last assessment is older than 2× interval
- [x] 26.7.9: Drill guard — refuse autonomous execution while a reconstruction drill is active
- [x] 26.7.10: Tests:
      - Enabling ceremony: confirmation phrase correct/wrong/abort
      - Hard exclusions: RED, irreversible, KeePass-gated, stale-state, drill-active all blocked
      - Scope constraints: action type filter, severity cap, execution window
      - Auto-disable: expiry, consecutive failures, RED cell state
      - Notification events: structured log fields, SMTP trigger conditions
      - Re-enable after auto-disable: ceremony required again
      *(40+ test cases)*

---

**Gate:** Phase 26 completion (including 26.7) adds the full autonomous action layer.
Phases 26.1–26.6 deliver human-gated remediation. Phase 26.7 adds fully autonomous
execution as an explicit opt-in on top of that foundation.

**Track 4 begins after Track 3. No Track 4 phase requires any Track 4 prerequisite
beyond a working Phase 24 (continuous assessment) deployment.**

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

11. **Remediation is proposed, not imposed.** The assessment engine recommends;
    the operator approves; the system executes. No autonomous action changes
    infrastructure state without a recorded human approval. This is an
    architectural constraint, not a configuration option.
