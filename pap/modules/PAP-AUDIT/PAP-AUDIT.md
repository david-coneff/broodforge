# PAP-AUDIT

Status: Canonical (realized from [Deliverable 4](../../revisions/synthesis/04_Canonical_PAP_Revision.md) Part II)
Operates under [PAP-Core](../../core/PAP-Core.md) authority. Loaded
when performing or recording a review, audit, or major-change
evaluation.

**Scope**: Systematic review, finding classification, adversarial deep
review, and the formal audit-record contract — the machinery that
makes "audit the project" (Success Criterion, [PAP-Core](../../core/PAP-Core.md) §7)
a repeatable procedure with a known output shape.

---

## 1. Systematic Review Governance

Perform, periodically:

- **Architecture reviews** — does the system as built still match
  `SYSTEM_ARCHITECTURE.md` and the adopted Decision Records?
- **Subsystem reviews** — focused reviews of one bounded part, deep
  enough to surface findings a project-wide pass would miss.
- **Repository census reviews** — does the Repository Memory Structure
  ([PAP-State](../PAP-State/PAP-State.md) §2) still account for
  everything that exists, and does everything that should exist, exist?

## 2. Adversarial Perspectives Deep Review Protocol (APDRP)

Major changes and major governance revisions shall be reviewed from
**four perspectives**:

1. **Validation perspective** — does this hold up on its own terms? Is
   it internally consistent and does it achieve its stated purpose?
2. **Falsification perspective** — what would have to be true for this
   to be *wrong*? Actively look for that, rather than for confirmation.
3. **Alternative-solution perspective** — what other approach would
   address the same need, and why was this one chosen over it?
4. **Future-reconstruction perspective** — could a future operator,
   with no access to this reasoning, arrive at the same understanding
   from the artifacts alone? If not, what's missing?

**Unresolved disagreements arising from any perspective shall be
preserved, not hidden** — restating [PAP-Core](../../core/PAP-Core.md) §6.3
at the level of concrete review output: an unresolved finding is still
a finding, and removing it from the record is worse than leaving it open.

## 3. Finding Classification

Every review finding is classified as exactly one of:

| Classification | Meaning |
|---|---|
| **BLOCKER** | Work cannot responsibly proceed until this is resolved. |
| **DEFECT** | Something is wrong and should be fixed, but work can continue around it. |
| **RISK** | Nothing is wrong yet, but something could go wrong; track it. |
| **IMPROVEMENT** | Not wrong, but could be better; optional. |
| **OBSERVATION** | Worth recording for future reference; no action implied. |

## 4. Audit Verdict and Status Record

Formalizes the contract that produced `pap_audit_status` in
`UPCCMP_PROTOCOL_RESUME_BLOCK.yaml` — direct evidence this practice was
real and in active use before any procedure governed it. An audit
record states, at minimum:

- which artifact was audited, and by reference to which protocol/
  module version the audit was performed,
- a **readiness verdict** drawn from a fixed taxonomy: `ready`,
  `conditionally_ready`, `not_ready`,
- **blocking findings**, if any (each classified per §3 — a
  `conditionally_ready` or `not_ready` verdict requires at least one
  BLOCKER-classified finding explaining why),
- a pointer to where the full review (with all four APDRP
  perspectives, if performed) is recorded.

Machine-form schema: [`schemas/audit-artifact.schema.yaml`](schemas/audit-artifact.schema.yaml).
`UPCCMP_PROTOCOL_RESUME_BLOCK.yaml`'s `pap_audit_status` block is the
canonical worked example of an instance conforming to it
(retroactively — it predates the schema, exactly as the sample UPCCP
artifact predates the UPCCP-CSP spec).

## 5. Audit Reasoning Patterns Catalog

A set of named, recurring failure patterns — analysis lenses that
auditors are instructed to step through actively during any Systematic
Review (§1) or APDRP pass (§2). For each pattern, ask: "does any form
of this appear in the artifact under review?"

The patterns are particularly productive during the **Falsification
perspective** (actively looking for what could be wrong) and the
**Future-reconstruction perspective** (could a resuming operator detect
the problem from artifacts alone?), but apply across all four APDRP
perspectives.

Current catalog: [`Audit-Reasoning-Patterns.md`](Audit-Reasoning-Patterns.md)

Seeded patterns: Catch-22 / Circular Dependency, Assumed Preconditions,
Orphaned Outputs, Silent Degradation, State Machine Gaps, Documentation
Drift.

## Provenance

Realizes Part II ("PAP-AUDIT") of
[Deliverable 4](../../revisions/synthesis/04_Canonical_PAP_Revision.md). Carries
forward UPCCMP 22-09's Systematic Review Governance, Finding
Classification, and full-form APDRP (PAP 22-39 retained only a
compressed echo — see [Gap Analysis](../../revisions/synthesis/02_Gap_Analysis.md) §1.5
and §5), plus the audit-status record shape evidenced in
`UPCCMP_PROTOCOL_RESUME_BLOCK.yaml`.
