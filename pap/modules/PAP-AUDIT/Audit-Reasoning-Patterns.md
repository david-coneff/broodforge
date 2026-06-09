# Audit Reasoning Patterns

A library of named analysis lenses for PAP-audits. Consult this catalog
when performing a Systematic Review ([PAP-AUDIT §1](PAP-AUDIT.md#1-systematic-review-governance))
or an APDRP pass ([PAP-AUDIT §2](PAP-AUDIT.md#2-adversarial-perspectives-deep-review-protocol-apdrp)) —
each pattern names a class of flaw that recurs across systems and is easily
missed without a concrete lens to look through.

**How to use**: Step through the catalog actively during each review. For
each pattern, ask: "does any form of this appear in the artifact under
review?" The patterns are most productive during the **Falsification
perspective** (what would have to be true for this to be wrong?) and the
**Future-reconstruction perspective** (could a resuming operator detect
the problem from artifacts alone?), but are applicable across all four
APDRP perspectives.

---

## Patterns

### 1. Catch-22 / Circular Dependency

**Definition**: A requires B, B requires A. Neither can be initialized
without the other already existing.

**When to apply**: Initialization sequences, bootstrap flows, any workflow
where two components each list the other as a precondition.

**What to look for**:
- "Component A cannot start without X" and "X is produced by Component B"
  and "Component B cannot start without A" appearing in the same flow.
- Bootstrap documentation that describes a sequence but glosses over how
  the *first* step in that sequence can actually be satisfied.
- Components that list each other under "dependencies" or "requires."
- A handoff step that names an artifact as its input and a separate step
  that names the same artifact as its output, but which step runs first
  is never specified.

**Example**: spawn needs the k3s join token that forge was supposed to
write, but forge only writes it after k3s is running, which requires a
node to have already joined.

---

### 2. Assumed Preconditions

**Definition**: An operation assumes a particular state or resource exists
without verifying or documenting that assumption.

**When to apply**: Functions that read from state files; workflows that
chain steps; CLI tools that accept inputs; any operation that begins by
consuming something another operation was expected to produce.

**What to look for**:
- Code that opens or reads a state file without checking it exists first,
  or that produces an unhelpful generic error (rather than a diagnostic
  one) if it doesn't.
- Workflow step N that has no explicit "verify step N-1 completed
  successfully" guard before proceeding.
- CLI invocations that accept a required flag without validating the
  upstream dependency that flag depends on.
- Comments that say "assumes X is set up" without a runtime check
  enforcing it.
- Documentation that describes a step as "run after X" but no code or
  tooling enforces that ordering.

**Example**: spawn_planner assumes `bootstrap-state.json` exists and
contains a k3s token, with no helpful error if it doesn't.

---

### 3. Orphaned Outputs

**Definition**: The system produces something — a file, a value, a record
— that nothing ever reads or acts on.

**When to apply**: Any time the system generates state files, writes
structured output, produces return values, or emits records that another
component was presumably meant to consume.

**What to look for**:
- State fields that appear in write paths but in no read paths.
- Generated files that have no documented consumer — nothing in any
  downstream workflow names them as an input.
- Return values discarded at every call site (check the full set of
  callers, not just one).
- Files listed under "outputs" in one component's specification with no
  corresponding "inputs" or "reads" entry in any other component's.
- Data written into a format specifically designed for machine consumption
  (structured JSON, YAML, etc.) but consumed only by humans — or not at
  all.

**Example**: A certificate generator that writes a JSON bundle to disk,
but no downstream workflow ever reads it or presents it to the operator.

---

### 4. Silent Degradation

**Definition**: An error is caught and swallowed, leaving the system in a
wrong-but-non-crashing state. The operator has no signal that something
went wrong.

**When to apply**: Error handling paths, phase-transition logic,
checkpoint and progress-tracking code, any place where a failure
result is transformed into a "done" or "success" signal.

**What to look for**:
- Bare exception handlers with no logging or re-raise (`except: pass`,
  `catch {}`, `_ = err`).
- Functions that return `None`, `null`, or an empty value on error without
  logging anything or setting an error flag the caller can check.
- Phases or pipeline stages that write a "completed" checkpoint based on
  code *reaching* a point rather than verifying the *result* of the
  operation at that point.
- Log lines that say a step "succeeded" or "finished" without evidence
  that the underlying operation was ever attempted.
- Status fields updated to a terminal state as a default rather than as a
  consequence of verified completion.

**Example**: forge phases 04/05 self-checkpointing as complete when the
underlying provisioning was never attempted — the operator has no way to
distinguish a genuine success from a silent skip.

---

### 5. State Machine Gaps

**Definition**: An operation assumes the system is in a particular state
but does not validate that assumption first, and the assumed state may not
hold.

**When to apply**: Operations with implicit ordering requirements;
resumable processes that can be entered mid-sequence; multi-phase
workflows where later phases depend on earlier ones having completed
correctly.

**What to look for**:
- Resumable processes that do not verify prior steps before continuing —
  "resume from phase N" that does not first confirm phase N-1 actually
  succeeded.
- Operations that lack a "precondition check" phase altogether; the phase
  list jumps directly to action steps.
- Phase or stage numbering that implies ordering but no runtime enforcement
  of that order (nothing prevents a caller from invoking phase 4 before
  phase 2).
- Recovery or remediation procedures that describe what to do "once the
  environment is in state X" without describing how to verify the
  environment *is* in state X before starting.
- Conditional logic that branches on assumed state ("if initialized, then
  ...") with no validation that the assumed branch condition is actually
  true.

**Example**: phoenix recovery starting without verifying that a valid
forge manifest and KeePass vault exist — if either is absent or
corrupted, the recovery procedure produces misleading errors rather than
failing early with a clear diagnosis.

---

### 6. Documentation Drift

**Definition**: Documentation — guides, runbooks, READMEs, setup wizards,
help text — describes a workflow or interface that no longer matches the
current code.

**When to apply**: Any time documentation and code coexist and could have
diverged; especially after refactors, renames, or interface changes.

**What to look for**:
- CLI flags or subcommands referenced in docs that have been renamed,
  removed, or split since the doc was written.
- Workflow steps that reference files, directories, or artifacts by names
  that no longer match what the code actually produces.
- Setup or installation guides that omit steps added after the guide was
  written (new dependencies, new configuration files, new required
  environment variables).
- Version numbers, timestamps, or "as of" markers in the docs that predate
  a significant interface or behavior change.
- Code comments that describe behavior accurately for a prior
  implementation but are now misleading after the behavior changed.
- Error messages or UI copy that references concepts renamed in the code.

**Example**: A setup guide referencing `--bootstrap-manifest` when the
flag in the current code is `--manifest` — the guide silently fails every
operator who follows it.

---

## Provenance

Created at direct operator request (2026-06-08) to seed a reusable audit
lens library for PAP-audit prompts. Patterns are drawn from recurring
failure modes observed during hands-on broodforge audits conducted under
[PAP-AUDIT](PAP-AUDIT.md). Integrated into the PAP-AUDIT module via
[PAP-AUDIT §5](PAP-AUDIT.md#5-audit-reasoning-patterns-catalog).
Synced from master PAP project (`PAP/pap/modules/PAP-AUDIT/`) into
broodforge's local PAP state on 2026-06-08.
