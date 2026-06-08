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
cannot be replayed during reconstruction. The provisioning gap is the primary obstacle
to automated disaster recovery.

## AD-007: Service Contracts replace heuristics as primary dependency source
**Date:** 2026-05-30
**Decision:** Declared Service Contracts (YAML files per service) are the primary source
of dependency graph edges. Name-pattern heuristics are retained as a fallback only.
**Rationale:** Heuristics based on VM name patterns are unreliable for novel service
names and produce incorrect restore sequences. Declared contracts are authoritative.

## AD-008: Secret Registry tracks references, never values
**Date:** 2026-05-30
**Decision:** The Secret Registry is a YAML file in the Bootstrap State repository that
maps secret identifiers to KeePass paths. It never contains secret values.
**Rationale:** Enables automated gap detection and pre-populated recovery steps
(operator knows exactly which KeePass entry to open) without creating a secret-in-repo
security risk.

## AD-009: DNS Registry eliminates [VM_IP] placeholders
**Date:** 2026-05-30
**Decision:** A DNS Registry maps hostnames to IPs for all VMs. Doc-gen reads the
registry and pre-populates commands with actual IP addresses.
**Rationale:** `[VM_IP]` placeholders require operator lookup during recovery, which
adds time and creates opportunities for error. Known values should always be pre-filled.

## AD-010: Three documentation classes (bootstrap, operational, recovery)
**Date:** 2026-05-30
**Decision:** Documentation is produced in three independent classes from the same
metadata model: Bootstrap (construction), Operational (administration), Recovery
(reconstruction). Previously only Bootstrap and Recovery existed.
**Rationale:** Operational documentation is a distinct use case (running environment
administration) that cannot be served by either bootstrap or recovery documentation.
Drift summaries and capacity trends have no place in a recovery runbook.

## AD-011: Deployment Provenance Records enable reproducible reconstruction
**Date:** 2026-05-30
**Decision:** Each VM deployment creates a Provenance Record capturing: tofu workspace
commit, cloud-init snippet hashes, ansible playbook commit, ansible inventory commit,
base template checksum, deployment timestamp and operator.
**Rationale:** Without a build receipt, reconstruction cannot be validated as equivalent
to the original deployment. Provenance records are the "replay tape" for automation.

## AD-012: Reconstruction Playbooks are generated artifacts
**Date:** 2026-05-30
**Decision:** Reconstruction Playbooks (executable shell scripts for full-destroy
reconstruction) are generated from the state model, not manually authored.
**Rationale:** Manually authored reconstruction scripts diverge from actual state.
Generated scripts are always consistent with the current state model.

## AD-013: Infrastructure Cell is the primary architectural object
**Date:** 2026-05-31
**Decision:** Infrastructure Cell replaces the implicit single-environment assumption.
Every schema carries `cell_id` as a mandatory field. Every assessment, every generated
output, every state document is cell-scoped.
**Rationale:** Single-environment assumptions cannot be patched into federation capability.
The cell concept must be foundational. Adding it as a retrofit creates a structural
discontinuity that breaks schema compatibility and forces re-architecture of all consumers.

## AD-014: Federation is a first-class object, not an extension
**Date:** 2026-05-31
**Decision:** Federation State, the capability index, the recovery relationship graph,
and the inter-cell trust model are managed as first-class architectural objects with
their own schemas (federation-state-schema.json), their own assessment tier (Tier 3),
and their own documentation class (Federation Workbook + Runbook).
**Rationale:** Federation relationships are too complex and too critical to model as
secondary attributes of cell state. The recovery graph, capability index, and trust
model each require independent query, update, and verification paths.

## AD-015: Recovery State removed from the state model
**Date:** 2026-05-31
**Decision:** Recovery State (workbooks, runbooks, readiness reports, reconstruction
playbooks) is reclassified from a state category to a documentation output class.
**Rationale:** Category error in v4.0. Infrastructure does not "have" recovery state
the way it has declared state. Recovery documentation is generated OUTPUT from the
seventeen genuine state categories. Conflating the two creates confusion about
authoritativeness (infrastructure state is authoritative; generated output is derived)
and about update mechanisms (state is collected; output is generated on demand).

## AD-016: Seventeen state categories replace seven
**Date:** 2026-05-31
**Decision:** The state model expands from seven to seventeen categories. New: Hardware
State, Platform State, Cluster State, Storage State, External Dependency State, Data
Protection State, Observability State, Secret Reference State (standalone), Capability
State, Federation State.
**Rationale:** The seven-category model cannot support hardware-level reconstruction
(no Hardware or Platform State), cluster-aware recovery (no Cluster State), external
dependency tracking (no External Dependency State), capability-based recovery planning
(no Capability State), or cross-cell recovery coordination (no Federation State).
Each gap represents a real scenario where the previous architecture produces incomplete
or incorrect recovery documentation.

## AD-017: Five dependency graph types with distinct semantics
**Date:** 2026-05-31
**Decision:** The architecture maintains five dependency graphs: Operational, Recovery,
Trust, Execution, and Failure Domain. Each is stored and traversed independently.
**Rationale:** Conflating operational dependencies with recovery dependencies produces
incorrect recovery sequencing. Cell A may operationally depend on Cell B's DNS while
Cell B holds Cell A's backups — these are different graphs with different traversal
requirements. Failure domain propagation requires a third graph that models blast radius,
not operational requirements. Trust and execution dependencies are required for federated
reconstruction planning and cannot be derived from operational graphs.

## AD-018: Capability State enables dynamic recovery planning
**Date:** 2026-05-31
**Decision:** Each cell declares its capabilities (compute, storage, execution, network,
assessment). Capabilities are verified at Tier 2 assessment. The capability index is
maintained at federation scope and used by reconstruction planners to identify which
available cell can assist recovery.
**Rationale:** Without a verified capability index, federated reconstruction planning
must assume capabilities or discover them dynamically during a disaster — the worst
possible time for discovery. Declared and verified capabilities enable recovery plans
to be generated and validated before they are needed.

## AD-019: Tier 3 Federation Assessment
**Date:** 2026-05-31
**Decision:** A Tier 3 assessment tier covers federation-scope state: trust relationship
verification, capability verification, cross-cell recovery relationship testing, and
federation readiness scoring. It runs from a designated assessment cell with
federation-scope trust relationships.
**Rationale:** Tier 1 and Tier 2 assess single cells. Neither can verify cross-cell
relationships. Federation readiness requires exercising trust and recovery relationships
to confirm they function — not merely that they are declared. A declared trust
relationship that fails in practice is worse than no relationship (it creates false confidence).

## AD-020: Digital Twin is the authoritative source for all generated outputs
**Date:** 2026-05-31
**Decision:** All documentation, all readiness reports, and all reconstruction playbooks
are generated from the Digital Twin. The twin is updated by assessment, repository
ingestion, deployment events, and operator declaration. No output is manually authored.
**Rationale:** Manually authored documentation diverges from reality. Generated
documentation is always consistent with the current twin state. Reproducibility (same
state → same output) is guaranteed by the twin's deterministic generation model. The
twin also provides a single query target for all consumer tools, eliminating the need
for each tool to aggregate state from multiple sources independently.

## AD-021: Staleness is a first-class field confidence level
**Date:** 2026-05-31
**Decision:** STALE is added as a field confidence level alongside DECLARED, OBSERVED,
DERIVED, INFERRED, HUMAN, and UNRESOLVED. Each state category has a declared staleness
threshold (Hardware: 30 days; Observed: 7 days; Data Protection: 1 day). Fields past
their threshold are marked STALE in the twin and in all generated outputs.
**Rationale:** UNRESOLVED means a field was never populated. STALE means it was
populated but may no longer be current. These require different remediation: UNRESOLVED
requires collection; STALE requires re-verification. An operator making recovery
decisions needs to know whether they are working with never-collected data (UNRESOLVED)
or potentially-outdated data (STALE). Conflating the two is a safety issue.

## AD-032: Infrastructure Assessment Engine as first-class subsystem
**Date:** 2026-05-31
**Decision:** The Assessment Engine is a separate k3s subsystem from the Documentation
Engine, with its own Deployment (API server), PostgreSQL StatefulSet, and five assessor
CronJobs. Five categories: Resource Health, Architectural Drift, Recovery Readiness,
Documentation Coverage, Placement Compliance.
**Rationale:** Documenting what is and evaluating whether what is is correct are
different concerns. Conflating them produces a system that does both poorly.

## AD-033: Five scoring dimensions with composite Platform Health Score
**Date:** 2026-05-31
**Decision:** ACS (Architecture Compliance), RRS (Recovery Readiness), DCS
(Documentation Coverage), CRS (Capacity Risk), OSS (Operational Stability) aggregate
into composite PHS. Scores use weighted averages with absolute blockers.
**Rationale:** Without scores and thresholds, the platform produces documentation
but provides no signal about whether anything needs attention.

## AD-034: Phase 1 rebalancing is detect/document/recommend only
**Date:** 2026-05-31
**Decision:** The Assessment Engine never takes autonomous infrastructure action.
Phase 2 automation is deferred to after Phase 12 and requires defined safeguards.
**Rationale:** Autonomous infrastructure actions can cause downtime, have cascading
effects, and must have tested rollback paths. These prerequisites take time to build.

**Amendment (2026-06-07 — see AD-040):** The line above ("never takes
autonomous infrastructure action") overstated the original intent and is
revised. **Operative phrasing, going forward:** *Broodforge MAY take
autonomous infrastructure action, provided it is bounded by defined
safeguards and recoverable* — i.e., exactly the two preconditions this
entry's own Rationale already named ("must have tested rollback paths,"
"these prerequisites take time to build") as the thing Phase 2 automation
was waiting on. Phase 26's policy-gated, opt-in, dry-run-comparing,
rollback-capable remediation engine is the realization of that
precondition being met — not a violation of this decision, properly read.
The original Date/Decision/Rationale lines above are left intact as the
historical record of what was decided on 2026-05-31 (and of the reasoning
that, followed through to its own conclusion, now licenses this amendment);
nothing here erases or contradicts them — it completes the thought they
left open ("requires defined safeguards" → safeguards now exist → action
is now licensed, exactly as this entry always said it would be once they did).

## AD-035: intelligence/ namespace deploys before applications/ namespace
**Date:** 2026-05-31
**Decision:** All intelligence-layer workloads (documentation engine, assessment engine,
recovery generator) must be Running and healthy before any user application is deployed.
Enforced by Flux CD dependency declarations. Gate: PHS >= 80.
**Rationale:** The platform must understand itself before hosting workloads.
An undocumented platform cannot be recovered reliably.

## AD-036: Failure packages are generated before script exit
**Date:** 2026-05-31
**Decision:** failure-package.sh is sourced at the top of every recovery script.
Error traps fire failure package generation before exit. Failure analysis capability
must not itself fail.
**Rationale:** The failure package is the input to the self-improvement loop.
Losing it because the generation code ran after the error means losing the data
needed to fix the problem.

## AD-037: ODS updates are atomic with plaintext fallback
**Date:** 2026-05-31
**Decision:** Every ODS update creates a backup, modifies a temp file, validates the
temp file, then atomically replaces the original. If ODS update fails, recovery
continues and logs to recovery-fallback.log.
**Rationale:** The audit trail is important; recovery is more important.

## AD-038: Documentation commits are batched to reduce Git noise
**Date:** 2026-05-31
**Decision:** Documentation Engine batches commits with a minimum 10-minute interval.
Assessment reports have a dedicated repository (docs-assessments/) separate from
architectural documentation.
**Rationale:** Frequent automated commits to a shared repository create noise that
obscures human-authored changes and makes git log unusable for review.

## AD-039: Codebase-development session-continuity practice transitions to PAP
**Date:** 2026-06-07
**Decision:** Broodforge's own pre-PAP prototype mechanisms for tracking
codebase-development continuity — `.ai/AI_AGENT_BOOTSTRAP.md`'s hand-built
"read in this order" bootstrap and `docs/SESSION-HANDOFF.md`'s rolling
session-progress log — are retired in favor of PAP-State's formally-specified
equivalents (Startup Protocol §1, Project Resume Block §3, Session Handoff
Protocol §4), now instantiated at `pap/state/RESUME_BLOCK.md` and
`pap/state/SESSION_HANDOFF.md`. `docs/SESSION-HANDOFF.md` is moved (`git mv`,
full history preserved), not deleted, to `docs/deprecated/SESSION-HANDOFF.md`,
with an in-place banner pointing forward; `.ai/AI_AGENT_BOOTSTRAP.md` is
rewritten in place to route through the new artifacts and PAP's Startup
Protocol. Full rationale, evidence, and migration record:
[`pap/revisions/2026-06-07_session-continuity-transition-to-pap.md`](../pap/revisions/2026-06-07_session-continuity-transition-to-pap.md).
**Rationale:** Direct operator instruction, framed as a scope distinction:
broodforge's *revision protocol for its own codebase* (session-handoff,
progress-tracking — i.e., how development sessions on broodforge's source are
picked up and handed off) is a different concern from broodforge's
*remediation process for failing nodes and the general functions it
performs* (the platform's own product behavior — assessment, forging,
spawning, phoenix recovery, autonomous remediation). The former is exactly
the kind of durable-continuity practice PAP exists to formalize; the latter
remains entirely broodforge's own, governed by `.ai/PROJECT_CHARTER.md` and
the rest of the `.ai/` corpus, untouched by this decision
(`PAP_CHARTER.md` §2.3 — PAP's analytical reach does not extend into, and
this decision does not cede, broodforge's own constitutional authority over
its product). Verified before acting: neither retiring artifact's name or
content had crept into `.ai/PROJECT_CHARTER.md` itself (it is 269 bytes —
Purpose plus four SHALL / four SHALL-NOT lines — and names neither).
**Consequences:** Future codebase-development sessions read
`pap/state/RESUME_BLOCK.md` and `pap/state/SESSION_HANDOFF.md` (per the
rewritten `.ai/AI_AGENT_BOOTSTRAP.md`), not `docs/SESSION-HANDOFF.md`. The
full pre-transition session history (1142 lines, "Previous Session Work"
through "Architecture Notes") remains intact and readable at
`docs/deprecated/SESSION-HANDOFF.md` and via `git log --follow`.

## AD-040: Charter SHALL-NOT scope clarified; AD-034 phrasing amended to license safeguarded autonomous action
**Date:** 2026-06-07
**Decision:** Two coordinated clarifications of original intent — made
together because both resolve ambiguity the same review surfaced
(PAP-AUDIT findings F1 and F2,
[`pap/audits/2026-06-07_broodforge-pap-audit.md`](../pap/audits/2026-06-07_broodforge-pap-audit.md)),
and both are recorded *in place*, alongside the original text they clarify,
rather than as silent rewrites:

1. **`PROJECT_CHARTER.md`'s SHALL-NOT list gains a Scope note** (added
   in-place, original four items left intact): "Recommend upgrades /
   purchases / replacements" and "Make subjective judgments" name
   *specific-hardware* recommendations — what product or component to buy,
   add, or swap into a node — which would require granular product-and-
   pricing knowledge out of this project's scope. They do not bound the
   platform's own resource-provisioning / deployment-strategy decisions for
   infrastructure it manages (a broad function of its chartered deployment
   strategy — see AD-013/AD-014/AD-032 — not a "subjective judgment" in the
   excluded, hardware-specific sense).
2. **AD-034 gains an in-place Amendment** (original Date/Decision/Rationale
   left intact as the historical record): its absolute phrasing ("never
   takes autonomous infrastructure action") overstated original intent.
   Operative rule, going forward: autonomous infrastructure action is
   licensed *provided it is bounded by defined safeguards and recoverable* —
   precisely the precondition AD-034's own Rationale already named as the
   thing "Phase 2 automation" was waiting on, and precisely what Phase 26's
   policy-gated, opt-in, dry-run-comparing, rollback-capable remediation
   engine now provides.

**Rationale:** Direct operator clarification of original intent, given
verbatim in response to PAP-AUDIT F1/F2 (quoted in full in
[`pap/audits/2026-06-07_broodforge-pap-audit.md`](../pap/audits/2026-06-07_broodforge-pap-audit.md)'s
Resolution annotations): *"the subjective judgements language was regarding
any suggestions of hardware changes or upgrades, or what to put into a
second node, etc., since this is outside the scope of the project... [an
auto-suggest mechanism for] how to provision resources within an existing
node or a new node... is more a broad function of its deployment strategy,
not a suggestion mechanism for specific hardware (which would require very
granular information about specific pc products, pricing databases, etc.
that is outside the scope of what this project should do)"* and *"autonomous
action is ok in some cases, as long as bounded by safeguards and
recoverability for autonomous actions that might go wrong. if the exact
phrasing needs revision, then do so to account for this."*
**Consequences:** Closes PAP-AUDIT findings F1 and F2 — both were genuine
*ambiguities* in the governing text (confirmed directly by the document's
own author/owner, who is the only authority able to resolve what its
original intent was), not contradictions between the text and the system;
the text, not the system, needed correcting, and now has been — in place,
annotated, with the original wording preserved as the historical record of
what was first written and why it needed this clarification.
