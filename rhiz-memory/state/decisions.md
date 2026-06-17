> **Migration note (2026-06-17):** Migrated from `.ai/decisions.md` to
> `rhiz-memory/state/decisions.md` as part of adopting the rhiz-memory convention.

---

# Architecture Decisions

## AD-001: Two-tier assessment model
**Date:** 2026-05-30
**Decision:** Split assessment into Tier 1 (bootstrap, minimal deps) and Tier 2 (full engine).
**Rationale:** Tier 1 must run on unknown hardware with no tooling installed.
Conflating the two creates unnecessary complexity and dependency risk for the bootstrap case.

## AD-002: manifest.json as doc-gen contract
**Date:** 2026-05-30
**Decision:** The doc-gen layer reads only manifest.json, never raw collector files.
**Rationale:** Decouples collection format from documentation format.
Collector output format can change without breaking doc-gen.

## AD-003: UNRESOLVED is a first-class field state
**Date:** 2026-05-30
**Decision:** Missing data is always surfaced as UNRESOLVED with reason, collection guidance,
and readiness impact. Never silently omit.
**Rationale:** Silent gaps are worse than visible gaps. An operator who sees a blank field
may assume it doesn't matter. An UNRESOLVED field with impact rating forces a decision.

## AD-004: Workbook/runbook examples are style templates only
**Date:** 2026-05-30
**Decision:** The Stage 01-12 ODS/ODT files demonstrate structure and methodology but are
not final implementations. Generated documents will follow their structure but populate
fields from assessment data.
**Rationale:** The examples were manually authored. Treating them as authoritative would
perpetuate manual documentation maintenance.

## AD-005: Historical snapshot reproducibility is a hard requirement
**Date:** 2026-05-30
**Decision:** Any historical snapshot must regenerate the documentation current at that time.
**Rationale:** Recovery documentation must be trustworthy. If we cannot reproduce what we
said the infrastructure looked like at a given point, we cannot trust the documentation.

## AD-006: Cloud-Init elevated to first-class Bootstrap State
**Date:** 2026-05-30
**Decision:** Cloud-Init user-data, network-config, and snippets are tracked in a
dedicated Bootstrap State repository as versioned, hash-verified managed assets.
**Rationale:** Without Cloud-Init metadata in repository state, first-boot provisioning
cannot be replayed during reconstruction.

## AD-007: Service Contracts replace heuristics as primary dependency source
**Date:** 2026-05-30
**Decision:** Declared Service Contracts (YAML files per service) are the primary source
of dependency graph edges. Name-pattern heuristics are retained as a fallback only.
**Rationale:** Heuristics based on VM name patterns are unreliable for novel service
names and produce incorrect restore sequences.

## AD-008: Secret Registry tracks references, never values
**Date:** 2026-05-30
**Decision:** The Secret Registry is a YAML file in the Bootstrap State repository that
maps secret identifiers to KeePass paths. It never contains secret values.
**Rationale:** Enables automated gap detection and pre-populated recovery steps
without creating a secret-in-repo security risk.

## AD-009: DNS Registry eliminates [VM_IP] placeholders
**Date:** 2026-05-30
**Decision:** A DNS Registry maps hostnames to IPs for all VMs. Doc-gen reads the
registry and pre-populates commands with actual IP addresses.
**Rationale:** `[VM_IP]` placeholders require operator lookup during recovery.

## AD-010: Three documentation classes (bootstrap, operational, recovery)
**Date:** 2026-05-30
**Decision:** Documentation is produced in three independent classes from the same
metadata model: Bootstrap, Operational, and Recovery.
**Rationale:** Each is a distinct use case that cannot be served by the others.

## AD-011: Deployment Provenance Records enable reproducible reconstruction
**Date:** 2026-05-30
**Decision:** Each VM deployment creates a Provenance Record capturing: tofu workspace
commit, cloud-init snippet hashes, ansible playbook commit, ansible inventory commit,
base template checksum, deployment timestamp and operator.
**Rationale:** Without a build receipt, reconstruction cannot be validated as equivalent
to the original deployment.

## AD-012: Reconstruction Playbooks are generated artifacts
**Date:** 2026-05-30
**Decision:** Reconstruction Playbooks (executable shell scripts for full-destroy
reconstruction) are generated from the state model, not manually authored.
**Rationale:** Manually authored reconstruction scripts diverge from actual state.

## AD-013: Infrastructure Cell is the primary architectural object
**Date:** 2026-05-31
**Decision:** Infrastructure Cell replaces the implicit single-environment assumption.
Every schema carries `cell_id` as a mandatory field.
**Rationale:** Single-environment assumptions cannot be patched into federation capability.

## AD-014: Federation is a first-class object, not an extension
**Date:** 2026-05-31
**Decision:** Federation State, the capability index, the recovery relationship graph,
and the inter-cell trust model are managed as first-class architectural objects.
**Rationale:** Federation relationships are too complex and too critical to model as
secondary attributes of cell state.

## AD-015: Recovery State removed from the state model
**Date:** 2026-05-31
**Decision:** Recovery State is reclassified from a state category to a documentation
output class.
**Rationale:** Infrastructure does not "have" recovery state the way it has declared state.
Recovery documentation is generated OUTPUT from the seventeen genuine state categories.

## AD-016: Seventeen state categories replace seven
**Date:** 2026-05-31
**Decision:** The state model expands from seven to seventeen categories. New: Hardware
State, Platform State, Cluster State, Storage State, External Dependency State, Data
Protection State, Observability State, Secret Reference State (standalone), Capability
State, Federation State.
**Rationale:** The seven-category model cannot support hardware-level reconstruction,
cluster-aware recovery, external dependency tracking, capability-based recovery planning,
or cross-cell recovery coordination.

## AD-017: Five dependency graph types with distinct semantics
**Date:** 2026-05-31
**Decision:** The architecture maintains five dependency graphs: Operational, Recovery,
Trust, Execution, and Failure Domain. Each is stored and traversed independently.
**Rationale:** Conflating operational dependencies with recovery dependencies produces
incorrect recovery sequencing.

## AD-018: Capability State enables dynamic recovery planning
**Date:** 2026-05-31
**Decision:** Each cell declares its capabilities. Capabilities are verified at Tier 2
assessment. The capability index is maintained at federation scope.
**Rationale:** Without a verified capability index, federated reconstruction planning
must assume capabilities or discover them dynamically during a disaster.

## AD-019: Tier 3 Federation Assessment
**Date:** 2026-05-31
**Decision:** A Tier 3 assessment tier covers federation-scope state: trust relationship
verification, capability verification, cross-cell recovery relationship testing, and
federation readiness scoring.
**Rationale:** Tier 1 and Tier 2 assess single cells. Federation readiness requires
exercising trust and recovery relationships to confirm they function.

## AD-020: Digital Twin is the authoritative source for all generated outputs
**Date:** 2026-05-31
**Decision:** All documentation, all readiness reports, and all reconstruction playbooks
are generated from the Digital Twin. No output is manually authored.
**Rationale:** Manually authored documentation diverges from reality.

## AD-021: Staleness is a first-class field confidence level
**Date:** 2026-05-31
**Decision:** STALE is added as a field confidence level alongside DECLARED, OBSERVED,
DERIVED, INFERRED, HUMAN, and UNRESOLVED.
**Rationale:** UNRESOLVED means never populated. STALE means populated but potentially
outdated. These require different remediation.

## AD-032: Infrastructure Assessment Engine as first-class subsystem
**Date:** 2026-05-31
**Decision:** The Assessment Engine is a separate k3s subsystem from the Documentation
Engine, with its own Deployment (API server), PostgreSQL StatefulSet, and five assessor
CronJobs.
**Rationale:** Documenting what is and evaluating whether what is is correct are
different concerns.

## AD-033: Five scoring dimensions with composite Platform Health Score
**Date:** 2026-05-31
**Decision:** ACS (Architecture Compliance), RRS (Recovery Readiness), DCS
(Documentation Coverage), CRS (Capacity Risk), OSS (Operational Stability) aggregate
into composite PHS.
**Rationale:** Without scores and thresholds, the platform produces documentation
but provides no signal about whether anything needs attention.

## AD-034: Phase 1 rebalancing is detect/document/recommend only
**Date:** 2026-05-31
**Decision:** The Assessment Engine never takes autonomous infrastructure action.
Phase 2 automation is deferred to after Phase 12 and requires defined safeguards.
**Rationale:** Autonomous infrastructure actions can cause downtime, have cascading
effects, and must have tested rollback paths.

**Amendment (2026-06-07 — see AD-040):** The line above ("never takes
autonomous infrastructure action") overstated the original intent and is
revised. **Operative phrasing, going forward:** *Broodforge MAY take
autonomous infrastructure action, provided it is bounded by defined
safeguards and recoverable* — i.e., exactly the two preconditions this
entry's own Rationale already named as the thing Phase 2 automation
was waiting on. Phase 26's policy-gated, opt-in, dry-run-comparing,
rollback-capable remediation engine is the realization of that
precondition being met — not a violation of this decision, properly read.
The original Date/Decision/Rationale lines above are left intact as the
historical record.

## AD-035: intelligence/ namespace deploys before applications/ namespace
**Date:** 2026-05-31
**Decision:** All intelligence-layer workloads must be Running and healthy before any
user application is deployed. Enforced by Flux CD dependency declarations. Gate: PHS >= 80.

## AD-036: Failure packages are generated before script exit
**Date:** 2026-05-31
**Decision:** failure-package.sh is sourced at the top of every recovery script.
Error traps fire failure package generation before exit.

## AD-037: ODS updates are atomic with plaintext fallback
**Date:** 2026-05-31
**Decision:** Every ODS update creates a backup, modifies a temp file, validates the
temp file, then atomically replaces the original. If ODS update fails, recovery
continues and logs to recovery-fallback.log.

## AD-038: Documentation commits are batched to reduce Git noise
**Date:** 2026-05-31
**Decision:** Documentation Engine batches commits with a minimum 10-minute interval.
Assessment reports have a dedicated repository (docs-assessments/).

## AD-039: Codebase-development session-continuity practice transitions to PAP
**Date:** 2026-06-07
**Decision:** Broodforge's pre-PAP prototype mechanisms for tracking
codebase-development continuity are retired in favor of PAP-State's
formally-specified equivalents, now instantiated at `pap/state/RESUME_BLOCK.md`
and `pap/state/SESSION_HANDOFF.md`.
**Rationale:** Direct operator instruction, framed as a scope distinction:
broodforge's *revision protocol for its own codebase* is a different concern
from broodforge's *remediation process for failing nodes*.

**Update (2026-06-17):** PAP-State artifacts migrated to `rhiz-memory/state/`
as part of adopting the rhiz-memory convention. `pap/` directory deleted.

## AD-040: Charter SHALL-NOT scope clarified; AD-034 phrasing amended to license safeguarded autonomous action
**Date:** 2026-06-07
**Decision:** Two coordinated clarifications of original intent, resolving
PAP-AUDIT findings F1 and F2:

1. **`PROJECT_CHARTER.md`'s SHALL-NOT list gains a Scope note**: "Recommend upgrades /
   purchases / replacements" and "Make subjective judgments" name
   *specific-hardware* recommendations only. They do not bound the
   platform's own resource-provisioning / deployment-strategy decisions.
2. **AD-034 gains an in-place Amendment**: its absolute phrasing ("never
   takes autonomous infrastructure action") overstated original intent.
   Operative rule, going forward: autonomous infrastructure action is
   licensed *provided it is bounded by defined safeguards and recoverable*.

## AD-041: `new/` proposed-revision corpus analyzed and triaged; one item (Phase 1.H) integrated

**Date:** 2026-06-07
**Decision:** The `new/` directory (~165 documents) has been read, triaged, and
selectively integrated per direct operator instruction.
One concretely-implementable, additive gap surfaced: **Phase 1.H — Pre-Install
Forge Package and Image Builder** (recorded in ROADMAP.md and as AD-057).
Three other areas were found already substantially implemented.
The remainder is explicitly deferred (named individually in ROADMAP.md).

## AD-059/AD-060/AD-061: Three Roadmap draft sketches promoted to scoped phases (Recovery-Readiness Conformance, Hypervisor Recovery Credentials, Granular Secret Access Silos)
**Date:** 2026-06-08
**Decision:** The operator reacted to all three draft sketches with explicit,
scoped decisions, promoting each from "draft for discussion" to a numbered
phase plus an architecture decision record:

1. **Recovery-Readiness Conformance → Phase 1.I**, AD-059. Scope: a
   `recovery-readiness-certificate.json`/HTML generator bundling manifest
   hash, graph hash, readiness score, drift summary, and latest drill result.
   No cryptographic root-of-trust apparatus or formal certification levels.
2. **Hypervisor Recovery Credentials → Phase 1.J**, AD-060. The operator
   **explicitly ruled out any autonomous pathway that can read and wield
   full root credentials against live hypervisors** — recorded as a firm
   architectural constraint (a SHALL-NOT), because root has no boundary
   by definition. Two narrow exceptions are explicitly allowed, both bounded
   to a single node's temporary credential: (a) node spawning (already in
   place via Cloud-Init), and (b) phoenix recovery packages. The three-part
   middle path (forced-command recovery accounts, human-unlock break-glass
   root, pre-generated spawn-media credentials with human authorization) is
   **accepted as stated** and recorded as Phase 1.J's implementation targets.
3. **Granular Secret Access Silos → Phase 1.K**, AD-061. The
   "multiple derived vaults" design is kept, expanded with: (a) higher-tier
   vaults must record access credentials for lower-tier scopes (vault-of-
   vaults); (b) a mechanism for creating users at VM level and Proxmox level
   with default templates corresponding to the proposed scope divisions.

**Rationale:** Each sketch was written specifically to be reacted to —
awaiting operator direction before promotion. The operator's direct, itemized
decisions on all three close that open thread cleanly.

**Consequences:** AD-060 in particular establishes a constraint binding on
*all* future development, not just Phase 1.J's own scope — any later proposal
for an autonomous pathway touching hypervisor root credentials must be
evaluated against it, and the two named exceptions (node spawning, phoenix)
are the only ones currently sanctioned.
