# Axiomatic System Design Proposal

**Date:** 2026-06-09
**Scope:** `new/` corpus — formal axiomatic-kernel / proof-system series (v1.5–v1.27)
**Status:** Design proposal only — not implementation

---

## Context

The `new/` directory contains one `.md` file accessible as text:
`new/broodforge_state_separation_spec.md`. The 13 named PDFs were previously
analyzed and their translations captured exhaustively in `ROADMAP.md` (the
"Phase 1.I" analysis section). Those PDFs are:

- `broodforge_formal_state_transition_proofs_v1_8`
- `broodforge_compositional_proof_system_v1_11`
- `broodforge_completeness_boundary_conditions_v1_7`
- `broodforge_operational_validation_benchmarking_v1_23`
- `broodforge_deployment_certification_conformance_v1_24`
- `broodforge_root_manifest_crypto_spec_v0_4`
- `broodforge_system_graph_schema_v0_5`
- `broodforge_reconciliation_engine_spec_v0_6`
- `broodforge_reconciliation_semantics_v0_2`
- `broodforge_observability_audit_replay_v1_1`
- `broodforge_security_proof_invariant_guarantees_v1_5`
- `broodforge_failure_threat_model_hardening_v1_0`
- `broodforge_action_runtime_idempotent_layer_v0_7`

Phase 1.I (implemented, commit 3b32137) already extracted the two central
concerns from this series and implemented them: provable recovery readiness
(the `recovery-readiness-certificate.json` artifact) and observed-state ↔
intent-manifest conformance (`replay-snapshot.py`). Phase 1.M added deal
pre/post contracts and hypothesis property tests to three key modules.

This proposal identifies what remains worth doing — a second pass focused on
the properties the earlier analysis deferred as "possible additive extensions"
rather than the core deliverables of 1.I.

---

## What Phase 1.I + 1.M Already Cover (don't re-implement)

| Formal concept | Implemented as | Location |
|---|---|---|
| Root Manifest hash | `manifest_hash` (SHA-256, canonical JSON) | `_recovery_readiness_certificate.py`, snapshot index |
| System Graph hash | `graph_hash` | `_recovery_readiness_certificate.py`, snapshot index |
| Deployment Certificate | `recovery-readiness-certificate.json` + HTML | `generate-recovery-readiness-certificate.py` |
| Hash-chained replay | `replay-snapshot.py` re-derives scores from stored snapshot | `replay-snapshot.py` + `test_replay_snapshot.py` |
| Idempotent action runtime — handler-set invariant | `assert set(ALLOWED_ACTION_TYPES) == set(_HANDLERS.keys())` at module load | `remediation_executor.py:423` |
| Human Intervention Boundary | Documented in ROADMAP.md Phase 1.I section | prose, not code |
| deal contracts | `score_component`, `build_spawn_plan`, `generate_temp_password`, `build_derived_vault_plan` | `readiness.py`, `spawn_planner.py`, `_vault_hierarchy.py` |
| Hypothesis property tests | score result always valid; component_id echoed; service fit status valid; dependency resolution is superset; vault tier properties; temp password format | `test_readiness.py`, `test_spawn_planner.py`, `test_vault_hierarchy.py` |

---

## Findings from `new/broodforge_state_separation_spec.md`

This is the only `new/` document not previously analyzed in detail. Its core
claim is a dual-layer architecture:

- **Infrastructure State Layer (ISL):** bootstrap-state.json + metadata YAMLs.
  Must be deterministic, cryptographically verifiable, independent of
  application data. Recovery from ISL is guaranteed.
- **Application Data Layer (ADL):** history/snapshots/, backup content, runtime
  exports. Best-effort consistency, time-relative, explicitly non-deterministic.

The architectural rule is: **ISL must not depend on ADL for system correctness.**
The spec also defines a "strong consistency domain" (infrastructure must match
manifest exactly; deviations trigger reconciliation) and a "weak consistency
domain" (application data may be stale — tolerated).

broodforge already implements this split correctly in practice. The gap is that
it is nowhere *tested*. The "strong consistency domain" rule maps directly to the
reconciliation loop (Phase 26), but the convergence property of that loop is not
verified.

---

## Properties Worth Implementing

### P1 — ISL/ADL Independence Invariant (test)

**What the spec says:** "The Root Manifest MUST NOT depend on application data
snapshots for system correctness."

**What broodforge does today:** bootstrap-state.json and the 10 metadata YAMLs
are entirely independent of history/snapshots/ — they never reference snapshot
paths or snapshot-derived data. This is true by convention, not by any check.

**Proposed implementation:** A pytest test (in `tests/unit/test_state_separation.py`
or appended to `test_reproducibility.py`) that:
1. Loads bootstrap-state.json and all metadata YAMLs.
2. Serializes them to canonical JSON.
3. Asserts that no value in the serialized ISL contains a path string matching
   `history/snapshots/` or `history/index.json`.
4. Asserts that no ISL field has a key named `snapshot_id`, `snapshot_ref`, or
   `from_snapshot`.

This is a structural invariant check, not a logic test. Five lines of code.
Value: catches future code changes that accidentally couple ISL to ADL — the
exact failure mode the spec is guarding against.

**Priority:** High. Cheap, zero new dependencies.

---

### P2 — Drift Domain Classification (extension to `drift.py`)

**What the formal series says:** The reconciliation semantics spec (v0_2) and
drift classification sections describe a "deviation vector δ" with a domain
axis — structural, behavioral, performance, security — not just HIGH/MEDIUM/LOW
severity.

**What broodforge does today:** `drift.py` classifies changes as HIGH/MEDIUM/LOW
based on field path patterns (`ip`, `hostname`, `version`, etc.). There is no
domain axis. The drift record output has `drift_severity` but no `drift_domain`.

**What this would add:** a `drift_domain` field on each diff entry, derived from
the field path using a small pattern table:

```python
_STRUCTURAL = ("topology", "vmid", "hostname", "network", "gateway", "bridge",
               "disk", "storage", "interface", "vlan", "pool")
_SECURITY   = ("secret", "keepass", "credential", "mfa", "key", "cert", "tls",
               "password", "token", "auth")
_BEHAVIORAL = ("service", "contract", "restart", "command", "healthcheck",
               "dependency", "policy", "schedule")
_PERFORMANCE = ("ram", "cpu", "memory", "cores", "disk_gb", "capacity",
                "limit", "threshold")

def _domain(path: str) -> str:
    lp = path.lower()
    if any(p in lp for p in _SECURITY):   return "security"
    if any(p in lp for p in _STRUCTURAL): return "structural"
    if any(p in lp for p in _BEHAVIORAL): return "behavioral"
    if any(p in lp for p in _PERFORMANCE): return "performance"
    return "configuration"
```

Each `diff` entry in the drift record gains `"drift_domain": domain`. The
aggregate record gains `"domains_affected": [list of unique domains]`.

**Why this is worth it:** The formal series is right that HIGH/MEDIUM/LOW alone
doesn't distinguish "a hostname changed" (structural, affects reconstruction)
from "a secret path changed" (security, affects KeePass gating) from "a service
healthcheck command changed" (behavioral, affects service restart). The domain
axis makes drift reports more actionable and closer to what the reconciliation
engine needs when prioritizing which deviations to address first.

**Implementation location:** `doc-gen/drift.py` — additive, non-breaking (new
fields alongside existing ones). Update `test_drift.py` with domain assertions.

**Priority:** Medium-high. About 30 lines of code plus test updates. No new
dependencies.

---

### P3 — Reconciliation Convergence Tracking

**What the formal series says:** The reconciliation engine spec (v0_6) defines
`R(actual, spec) → next` with "fixed-point convergence required" — each
cycle's deviation vector must shrink monotonically until it reaches zero or a
stable minimum. The reconciliation semantics spec (v0_2) adds that this must
be *measured*, not assumed.

**What broodforge does today:** `remediation_executor.py`'s `execute_proposal()`
produces a `RemediationResult(success, outcome, steps)` and records
`resolved_at` + `outcome` in the queue. There is no before/after deviation
count, no convergence assertion, and no historical record of whether cycles are
converging.

**Proposed implementation:**

Add to `remediation_executor.py`'s `execute_proposal()`:
1. Before execution: capture a deviation snapshot — count of active non-resolved
   remediation proposals in the queue (`queue["proposals"]` where
   `status != "resolved"`). Call this `pre_deviation_count`.
2. After execution: re-count. Call this `post_deviation_count`.
3. Store `pre_deviation_count` and `post_deviation_count` in the
   `RemediationResult`.
4. If `success` and `post_deviation_count > pre_deviation_count`, emit a
   warning log: "Remediation cycle increased deviation count — possible
   repair loop."

Add to `remediation_queue.py` a `convergence_history()` function that reads
the queue's terminal (resolved/failed) entries and returns a list of
`(resolved_at, pre, post)` tuples — enough to plot or assert that the
deviation series is non-increasing over time.

Add a hypothesis property test: given a sequence of RemediationResult objects
with `success=True`, if the series is monotonically non-increasing in deviation
count, `convergence_history()` should return no warnings.

**Why this matters:** The reconciliation engine is Phase 26's core claim. Right
now "did remediation help?" is answered by looking at pass/fail outcome, not by
measuring whether the system state is actually converging. The formal series is
correct that convergence is a measurable, testable property, not an assumption.
This adds about 40 lines of code and turns "the remediator ran" into "the
remediator converged."

**Priority:** Medium. Moderate effort. No new dependencies.

---

### P4 — Idempotency Invariant Test Suite (formal I1–I5)

**What the formal series says:** `broodforge_action_runtime_idempotent_layer_v0_7`
defines five global invariants (I1–I5) for the action runtime:
- I1: Action handlers are a closed, fixed set (no runtime registration).
- I2: Each action type has exactly one handler.
- I3: Handler execution is idempotent (running twice leaves the same state as
  running once).
- I4: No action handler holds persistent state between invocations.
- I5: Handler failures do not corrupt the queue.

**What broodforge does today:**
- I1 + I2: Enforced by `assert set(ALLOWED_ACTION_TYPES) == set(_HANDLERS.keys())`
  at module load in `remediation_executor.py:423`. This is correct and already
  tested implicitly (any test that imports the module triggers the assert).
- I3: Required by Phase 26 design ("actions are already required to be
  idempotent") but not verified by any test.
- I4: True by inspection (handlers are stateless functions), but not asserted.
- I5: Covered by existing failure-path tests in `test_remediation.py` but not
  named explicitly as an invariant.

**Proposed implementation:** A dedicated test class `TestIdempotencyInvariants`
in `tests/unit/test_remediation.py` (or a new
`tests/unit/test_action_invariants.py`):

- **I1+I2 smoke test:** `import remediation_executor` — the module-load assert
  already fires. Add an explicit test that constructs `_HANDLERS` and
  `ALLOWED_ACTION_TYPES` and asserts they're equal. This makes the invariant
  visible in the test report rather than only failing on import.
- **I3 idempotency test:** For each dry-run-capable handler (most handlers
  accept a `dry_run=True` flag or can be called with a mock state), run it
  twice with the same proposal on the same state dict and assert the state
  dict is identical after both calls.
- **I4 statelessness test:** Call a handler, then call it again and assert
  the handler function object has no `__dict__` entries (no instance state
  accumulated between calls).
- **I5 failure isolation test:** Inject an error mid-handler and assert the
  queue entry is in `"failed"` state (not `"in_progress"` or `"resolved"`)
  and the queue dict itself is a valid JSON-serializable structure after the
  failure.

**Priority:** Medium. I3 is the most valuable new test (I1+I2 already exist
implicitly; I4 and I5 are easily verifiable). Requires mocking handlers
with the existing mock patterns already in `test_remediation.py`.

---

### P5 — State Transition Completeness Boundary (property test)

**What the formal series says:** `broodforge_completeness_boundary_conditions_v1_7`
and `broodforge_formal_state_transition_proofs_v1_8` together assert that the
17-state lifecycle (Planned → Provisioned → Running → … → Decommissioned) is
a total function — every state has at least one defined outgoing transition, no
state is a dead end except the declared terminal states (Decommissioned,
Failed), and no transition leads to an undefined state name.

**What broodforge does today:** The 17-state model exists in the schema
(`bootstrap-state-schema.json`) and is documented in `ARCHITECTURE.md`, but
the transition table is described in prose, not encoded as a machine-readable
structure. There's no test that the transition graph is complete or acyclic
(except that terminal states are terminals).

**Proposed implementation:** In `tests/unit/test_state_transitions.py` (new file):

1. Define the transition table as a Python dict (mirroring ARCHITECTURE.md —
   this is just encoding what already exists):
   ```python
   TRANSITIONS = {
       "planned":        {"provisioned", "failed"},
       "provisioned":    {"running", "failed"},
       "running":        {"degraded", "decommissioned"},
       ...
       "failed":         set(),       # terminal
       "decommissioned": set(),       # terminal
   }
   TERMINAL_STATES = {"failed", "decommissioned"}
   ```
2. Assert: every state in `TRANSITIONS` has at least one outgoing transition,
   unless it is in `TERMINAL_STATES`.
3. Assert: every target state in any transition set is itself a key in
   `TRANSITIONS` (no undefined states reachable).
4. Assert: the non-terminal subgraph has no isolated nodes (every non-terminal
   state is reachable from "planned").
5. Hypothesis: `@given(state=st.sampled_from(list(TRANSITIONS)))` — assert
   `TRANSITIONS[state]` is a set, and each element is in `TRANSITIONS`.

**Priority:** Medium-low. Zero runtime dependencies (pure dict test). Useful
as a guard that future state-model changes don't silently introduce dead ends.
The main cost is encoding the transition table — roughly 20 lines.

---

## What to Skip (Philosophical / Out of Scope)

These are named explicitly to close the question rather than leave it open.

**Ed25519 root-of-trust chains and cryptographic signing apparatus**
(`broodforge_root_manifest_crypto_spec_v0_4`): The formal series proposes
signing bootstrap-state.json with Ed25519 keypairs and maintaining a
chain of signed states. This is heavier than broodforge's actual threat model:
broodforge uses git as its tamper-evidence layer (commit history + Forgejo)
and KeePass for secret gating. Adding a separate Ed25519 signing ceremony would
create a parallel trust mechanism with no integration into the existing
KeePass-gated forge/spawn/phoenix workflow. The SHA-256 manifest hash in Phase
1.I's certificate is the right level of tamper-evidence for a homelab operator
with git.

**Category-theoretic compositional proof objects** (`broodforge_compositional_proof_system_v1_11`):
The spec defines "proof objects" as first-class values that compose via
functors. This requires a proof-carrying runtime, which broodforge is not and
should not be. The underlying concern — "can I verify that a composed
operation preserves invariants?" — is addressed by the deal contracts and
hypothesis tests in Phase 1.M.

**Metatheoretic irreducibility and terminal synthesis theorems**
(`broodforge_completeness_boundary_conditions_v1_7` heavy sections): These
describe formal completeness proofs about the specification itself — that no
further axiom can be added without inconsistency. This governs the spec corpus
as a formal system; it has no operational analog in a homelab Proxmox manager.

**Formal certification levels with external auditor conformance**
(`broodforge_deployment_certification_conformance_v1_24`): The spec proposes
multi-level certification tiers (Level 0 through Level 4) with third-party
audit requirements. For broodforge's actual deployment target (a single-operator
homelab), the recovery-readiness certificate from Phase 1.I is the correct
level of formalism. External certification adds process overhead without
improving the operator's actual recovery capability.

**Operational validation benchmarking as a continuous regression system**
(`broodforge_operational_validation_benchmarking_v1_23`): The spec describes
a benchmarking framework that continuously measures against a fixed performance
baseline and fails if scores regress. This is a reasonable CI concept, but it
requires a stable test environment with fixed hardware characteristics —
not compatible with a homelab whose hardware is the variable being managed.
The existing reconstruction drill (Phase 12) is the correct manual analog.

---

## Implementation Map

| Property | File(s) | Effort | Priority |
|---|---|---|---|
| P1 — ISL/ADL independence invariant | `tests/unit/test_state_separation.py` (new) | ~20 lines | High |
| P2 — Drift domain classification | `doc-gen/drift.py` (extend `_severity`/`compute_drift`), `tests/unit/test_drift.py` | ~40 lines code + tests | Medium-high |
| P3 — Reconciliation convergence tracking | `proxmox-bootstrap/remediation_executor.py`, `remediation_queue.py`, `tests/unit/test_remediation.py` | ~50 lines + hypothesis test | Medium |
| P4 — Idempotency invariant test suite (I1–I5) | `tests/unit/test_remediation.py` or new `test_action_invariants.py` | ~60 lines | Medium |
| P5 — State transition completeness | `tests/unit/test_state_transitions.py` (new) | ~30 lines | Medium-low |

Total: approximately 200 lines of new code and tests, no new runtime
dependencies, all expressible with the existing hypothesis/deal/pytest stack.

---

## Notes on the `new/broodforge_state_separation_spec.md` Specifically

The spec's Section 6 ("Consistency Model") is the piece with the most direct
runtime relevance. Its "Strong Consistency Domain" rule — "any deviation
triggers reconciliation repair loop" — is already the Phase 26 remediation
planner's job description. The "Weak Consistency Domain" rule — application
data may be stale — is correctly modeled by the best-effort snapshot restore
documented in Phase 1.I's Human Intervention Boundary.

The spec's Section 9 ("Security Model") states: "Storage systems are assumed
hostile or unreliable." This matches broodforge's existing `replay-snapshot.py`
design (re-derive and verify rather than trust stored values), the hash fields
in the snapshot index, and the KeePass-offline-first approach. No new
implementation is needed here — the spec's security model is consistent with
AD-040 and already implemented.

The spec's Sections 3–5 (the ISL/ADL structure and recovery phases) are fully
reflected in broodforge's existing architecture. The only gap — addressed by
P1 above — is that the independence rule is maintained by convention rather
than by a checked invariant.
