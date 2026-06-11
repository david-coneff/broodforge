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

## Workflow & Operator Experience

Patterns in this section describe failures visible primarily from the
operator's vantage point: things that go wrong in the human-system
interface, in day-to-day operation, and in recovery from operational
problems.

### 1. Documentation Drift

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

### 2. No Recovery Path

**Definition**: An operation can fail but there's no documented or
implemented way to recover, retry, or undo from that failure state.
Distinct from State Machine Gaps: the state machine is fine — there's
just no exit from the error state.

**When to apply**: Any operation that writes state, provisions resources,
or performs multi-step work; resumable processes; long-running operations
that a real operator might need to restart after a crash.

**What to look for**:
- Operations that write partial state before a crash with no mechanism to
  detect or clear the partial write on retry.
- Resumable processes with no `--resume` or `--retry` flag or equivalent.
- Destructive steps with no rollback procedure documented or implemented.
- Error documentation that says "if this fails, contact support" rather
  than describing a concrete recovery path.

**Example**: A node provisioning phase writes half its state to
`bootstrap-state.json` then crashes — on retry, the system has no
mechanism to detect or clear the partial write.

---

### 3. One-Way Door

**Definition**: An irreversible operation doesn't warn the operator or
require confirmation.

**When to apply**: Any operation that deletes, wipes, or overwrites state;
destructive CLI commands; provisioning teardown steps.

**What to look for**:
- Destructive commands that execute immediately without a `--dry-run`,
  confirmation prompt, or `--force` gate.
- State-wiping operations buried inside larger automated workflows where
  the operator may not notice them.
- Any operation where the consequence of an accidental invocation is
  permanent data loss or configuration destruction.
- Absent or insufficient documentation that the operation is irreversible.

**Example**: `forge.sh` wipes an existing `bootstrap-state.json` without
prompting if one already exists.

---

### 4. Invisible Prerequisites

**Definition**: Prerequisites only become apparent when a step fails, not
surfaced upfront in validation or docs. Distinct from Assumed Preconditions
(which is about code silently failing) — this is about the operator having
no way to know a prerequisite was required until they're already deep into
a failing operation.

**When to apply**: Long-running operations with upfront setup requirements;
workflows that gate on external resources (credentials, network services,
pre-provisioned objects); any multi-step operation where a missing
dependency causes a late, cryptic failure.

**What to look for**:
- Errors that only manifest 10 or more minutes into a long operation.
- Preflight checks that are absent, incomplete, or never run before the
  main workflow begins.
- Required credentials, tokens, or config values that appear in error
  messages but nowhere in setup documentation.
- "Cannot connect to X" errors where X was never mentioned as a dependency.

**Example**: Spawn fails with a cryptic `KeyError` 20 minutes in because a
Headscale pre-auth key was never obtained — there was no preflight check.

---

### 5. Operator Knowledge Assumption

**Definition**: The system assumes the operator has context that exists
nowhere in the tooling, docs, or guides.

**When to apply**: CLI interfaces; configuration schemas; error messages;
any place where the operator must make a decision without sufficient
context being provided.

**What to look for**:
- CLI flags or config fields with no `--help` text, description, or
  documentation of expected values.
- Error messages that reference concepts, systems, or identifiers without
  explaining what they are or how to resolve the error.
- Guides that say "configure X" without specifying what value X should
  have or how to determine the correct value.
- Terminology used in tooling that is internal jargon with no glossary or
  contextual explanation.

**Example**: A forge manifest field named `pool` with no description of
what a Proxmox pool is or what value is expected.

---

### 6. Missing Escape Hatch

**Definition**: An automated process can reach a state the operator cannot
manually override or intervene in.

**When to apply**: Long-running background operations; processes that
acquire locks or write state; automation that proceeds without human
checkpoints; any workflow that could hang or crash while holding resources.

**What to look for**:
- Long-running background operations with no cancellation signal or
  interrupt path.
- Processes that hold lock files or exclusive state the operator can't
  inspect, override, or clear without process-level intervention.
- Automation that has no documented "manual escape" for when it gets stuck.
- Lock acquisition with no TTL, timeout, or stale-lock cleanup path.

**Example**: A spawning process acquires a lock file and crashes —
subsequent runs fail indefinitely because the lock is never released.

---

### 26. Cliff-Edge Error

**Definition**: The system accepts invalid input or bad state silently for
a long time, then fails deep in a process rather than at input time. "Fail
fast" is the violated principle. Distinct from Assumed Preconditions (which
is about code assuming state exists) — this is specifically about *when*
validation happens relative to when work begins.

**When to apply**: Large multi-step operations that accept upfront
configuration; CLIs that accept flags processed much later; provisioning
workflows where config is parsed early but evaluated late.

**What to look for**:
- Config parsed at startup but only accessed many steps later.
- Large operations that don't validate inputs before beginning substantive
  work.
- CLIs that accept contradictory flags without warning.
- Errors that could have been caught in seconds but only surface after
  minutes of work.

**Example**: A spawn operation accepts a misconfigured manifest, provisions
a VM, installs k3s, then fails because the network config was wrong from
the start — hours of work undone by a config error that could have been
caught in 2 seconds.

---

### 27. Feedback Vacuum

**Definition**: A long-running operation produces no progress output,
leaving the operator unable to distinguish "working," "hung," and
"silently failed." Especially dangerous for infrastructure tools where
operations take minutes.

**When to apply**: Any operation that takes more than a few seconds;
subprocess invocations; multi-phase workflows; any operation where an
operator might wait and wonder.

**What to look for**:
- Long subprocess calls with no stdout capture or progress indication.
- Phases that run for >30 seconds with no output.
- Operations that print only on success or final failure.
- No progress bar, spinner, log stream, or periodic heartbeat message.

**Example**: An ansible phase runs for several minutes with no output —
the operator stares at a blank terminal, eventually Ctrl-C's, and the
system is now in a partial state.

---

### 28. Missing Observability

**Definition**: A critical system state or event exists that's invisible
to both the monitoring dashboard and any operator-accessible output.
Distinct from Audit Log Gap (forensic reconstruction) — this is about
real-time visibility.

**When to apply**: Dashboard and status display code; any state that's
tracked internally but not surfaced; health checks; monitoring
integrations.

**What to look for**:
- State fields written to files but never surfaced in the dashboard.
- Health conditions that exist in code but have no corresponding metric
  or status display.
- Events that can only be discovered by reading raw state files.
- Monitoring that covers infrastructure metrics but misses
  application-level state.

**Example**: The KeePass vault unlock status is tracked internally but the
dashboard has no indicator of whether the vault is currently accessible.

---

### 29. Silent Success

**Definition**: Operations complete without any confirmation output,
leaving the operator unsure whether the action was taken. The complement
to Silent Degradation.

**When to apply**: CLI tools and commands that modify state; operations
that an operator will invoke and then wait for confirmation; any action
where the operator needs to know it worked.

**What to look for**:
- Functions that return without printing anything on success.
- CLI commands that exit 0 with no stdout.
- Operations that modify state with no acknowledgment.
- Action verbs (delete, update, create, authorize) with no corresponding
  success message.

**Example**: An authorization CLI completes successfully but prints
nothing — the operator has no confirmation the action was actually taken.

---

### 30. Alert Fatigue Setup

**Definition**: The system generates so many warnings or log entries for
expected/benign conditions that operators learn to ignore them, causing
real alerts to be missed.

**When to apply**: Any system with warnings, alerts, or log output;
monitoring configurations; health check implementations; any tooling used
frequently enough that operators develop scan habits.

**What to look for**:
- Warnings emitted on every run for conditions that are always present.
- Verbose logging that can't be turned off or filtered.
- Status checks that always warn about intentionally-unconfigured features.
- Warning counts that grow so large that new warnings are invisible.

**Example**: Every dashboard load emits a WARNING about optional backup
integration not being configured — after seeing it 100 times, operators
stop reading warnings entirely.

---

## Implementation Correctness

> **Pre-flight note**: Before applying these patterns manually, run both the static analysis pre-flight (PAP-AUDIT §5) and the dynamic analysis pre-flight (PAP-AUDIT §6). Static tools surface structural gaps; dynamic tools (beartype, hypothesis, mutmut, etc.) exercise runtime behavior. Together they seed the patterns below with concrete findings before any manual reasoning begins.

Patterns in this section describe failures in how code is written: missing
error handling, broken retry semantics, inadequate testing, and structural
choices that make correctness hard to verify.

### 7. Assumed Preconditions

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

**Example**: `spawn_planner` assumes `bootstrap-state.json` exists and
contains a k3s token, with no helpful error if it doesn't.

---

### 8. Silent Degradation

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

**Example**: Forge phases 04/05 self-checkpointing as complete when the
underlying provisioning was never attempted — the operator has no way to
distinguish a genuine success from a silent skip.

---

### 9. State Machine Gaps

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

**Example**: Phoenix recovery starting without verifying that a valid
forge manifest and KeePass vault exist — if either is absent or
corrupted, the recovery procedure produces misleading errors rather than
failing early with a clear diagnosis.

---

### 10. Happy Path Only

**Definition**: Code handles the success case but has no error handling,
edge cases, or input validation. Distinct from Silent Degradation: the
error isn't swallowed — the code just crashes unexpectedly rather than
handling the failure gracefully.

**When to apply**: Any function that calls external systems, invokes
subprocesses, reads user input, or performs I/O; CLI tools; any code path
that could receive unexpected input or encounter partial failures.

**What to look for**:
- Functions with no `try`/`except` (or equivalent) around operations that
  can fail.
- CLI tools that accept input with no validation — no type checks, range
  checks, or existence checks.
- Scripts that assume every subprocess call succeeds, with no `returncode`
  check.
- Missing handling for empty results, null values, or partial responses
  from external services.

**Example**: `forge_scripts.py` calls `subprocess.run()` without checking
`returncode` — a failed Ansible step goes undetected and the workflow
continues as if it succeeded.

---

### 11. Idempotency Gap

**Definition**: An operation intended to be re-runnable has hidden side
effects that cause problems on retry. Critical for infrastructure tooling
where retrying after a partial failure is normal.

**When to apply**: Any operation described as "safe to re-run" or
"idempotent"; provisioning and bootstrap workflows; operations used as
remediation steps; any workflow where "run again to fix" is documented
advice.

**What to look for**:
- Operations that append to a list or log rather than overwrite or
  de-duplicate.
- Provisioning steps that fail if the resource already exists without
  first checking for its existence.
- State files that accumulate entries rather than being replaced on
  re-run.
- Any "run again to fix" instruction that hasn't been tested against a
  pre-existing partial state.

**Example**: A node registration step adds an entry to a JSON list each
time it runs — re-running after a partial failure produces duplicate
entries that break subsequent processing.

---

### 12. Non-Atomic Multi-Step

**Definition**: An operation performs several steps that must all succeed
but can fail partway through, leaving the system in a partial or
inconsistent state with no cleanup.

**When to apply**: Multi-phase provisioning; resource creation workflows;
any operation that creates or modifies multiple things that must be
consistent with each other.

**What to look for**:
- Multi-phase operations with no rollback or cleanup on partial failure.
- State written before confirmation of success — VMID recorded in state
  before the VM is fully configured, for example.
- Resources created before the last required resource is confirmed
  available.
- Operations that leave behind "half-created" resources (orphaned VMs,
  partial config files, stale records) on failure.

**Example**: Spawn creates a VM and writes its VMID to state, then fails
to configure networking — the VMID is in state but the VM is
misconfigured, and subsequent runs don't clean up the inconsistency.

---

### 13. Test/Production Divergence

**Definition**: Tests pass because they mock away or stub out the exact
behavior that would fail in production.

**When to apply**: Any test suite that uses mocks, stubs, or fixtures;
integration tests; any test that patches environment variables, file
paths, or external service responses.

**What to look for**:
- Mocks that return hardcoded success regardless of input — tests are
  green because the mock never exercises the failure path.
- Tests that don't exercise the actual integration point (the test mocks
  the network call rather than making a real call against a test service).
- Fixtures that assume conditions production doesn't guarantee (a required
  env var is always set in the fixture but never in production).
- Tests that pass with `--no-actual-io` or equivalent flags that would
  fail without them.

**Example**: A test mocks `os.environ` to inject a k3s token — but
production never exports the variable, so the test is green while the
production code fails with a `KeyError`.

---

### 14. Missing Seam

**Definition**: No injection point exists for testing or substitution,
making it impossible to verify behavior in isolation or replace a
dependency without modifying the code under test.

**When to apply**: Any code with hard dependencies on time, external
services, file system paths, or global state; modules that are difficult
to unit-test; code where "testing this" requires spinning up the full
system.

**What to look for**:
- `datetime.now()` (or equivalent) called directly rather than via an
  injected clock.
- Hardcoded file paths or connection strings that can't be overridden
  without code changes.
- Global singletons instantiated at import time with no way to substitute
  a test double.
- Functions that reach out to external services directly rather than
  through an interface that could be swapped.

**Example**: A scoring module calls `datetime.now()` directly — tests
can't control the clock, so time-sensitive behavior (expiry, scheduling)
can't be verified without real-time waits.

---

### 31. Regression Blind Spot

**Definition**: A class of behavior has zero test coverage, meaning any
regression there is invisible until production. Distinct from
Test/Production Divergence (tests that test the wrong thing) — this is
about areas with no tests at all.

**When to apply**: Any time new code is added to an untested area; bug fix
rounds; any feature with complex output or behavior; auditing test suite
coverage.

**What to look for**:
- Public functions with no corresponding test file.
- Integration paths that are only exercised manually.
- Error handling code that's never tested.
- Output-generating code (formatters, script generators, serializers) with
  no output assertions.

**Example**: A shell-script generation function had no tests across three
bug fix rounds — each fix introduced a new bug because nothing was
verifying the output.

---

### 32. Leaky Abstraction

**Definition**: Lower-level implementation details bleed through an
abstraction boundary, forcing callers to know about internals they
shouldn't need to care about.

**When to apply**: Module or class interfaces; functions that return data
structures; any place where an abstraction is supposed to hide
implementation details.

**What to look for**:
- Functions that return raw internal data structures instead of clean
  types.
- Abstractions that raise implementation-specific exceptions.
- Callers that must know which underlying tool is being used.
- API return values that require callers to perform post-processing that
  should be internal.

**Example**: A vault module returns raw dicts that callers must access by
exact key name — a key rename breaks all callers at runtime, not at
import time.

---

### 33. Action at a Distance

**Definition**: A change in one place causes unexpected effects in a
seemingly unrelated place, with no obvious causal link in the code.
Often caused by shared mutable state or implicit coupling.

**When to apply**: Any code that uses global state; functions with side
effects beyond their obvious return value; modules that share mutable data
structures.

**What to look for**:
- Global variables multiple modules write to.
- Functions with side effects beyond their obvious return value.
- Operations that modify shared state as a byproduct.
- Behavior that changes based on call order with no explicit dependency.

**Example**: Calling a manifest builder also writes to a global template
cache — a second call with different arguments doesn't produce a fresh
manifest because the cache is stale.

---

### 34. Abstraction Inversion

**Definition**: Low-level code imports from high-level modules to avoid
re-implementing something, inverting the dependency direction the
architecture intends. Creates circular import risks and makes the
low-level component impossible to use without dragging in the whole stack.

**When to apply**: Utility and helper modules; any module that should be a
foundation for others; architectural layer audits; import graph reviews.

**What to look for**:
- Utility/helper modules that import from orchestration or UI modules.
- Any import that goes "upward" in the architectural layer diagram.
- Low-level components whose tests require initializing high-level systems.
- Modules that can't be used standalone because of upward dependencies.

**Example**: A low-level state serializer imports from the top-level forge
orchestrator to reuse a formatting helper — now the serializer can't be
used in tests without initializing the full forge stack.

---

## Security & Reliability

Patterns in this section describe failures that create security
vulnerabilities or reliability hazards — things that are fine under
normal conditions but dangerous under adversarial or degraded conditions.

### 15. Fail Open

**Definition**: On error, timeout, or unexpected input, the system defaults
to permissive/allowed rather than denied/safe.

**When to apply**: Authentication and authorization logic; gating checks;
any place where an error result is converted to an access decision.

**What to look for**:
- Auth checks that return `True` (allow) on exception rather than raising
  or returning `False`.
- Missing `else` branches in security gate conditionals — the gating logic
  only explicitly handles the deny case, falling through to allow by
  default.
- Timeout handlers in auth flows that grant access rather than blocking
  when the auth service is slow.
- Exception handlers that log a warning but continue execution rather than
  aborting.

**Example**: A token validation function wraps its logic in
`try/except Exception: return True` — a malformed token, network error,
or unexpected input grants access instead of rejecting.

---

### 16. Single Point of Failure

**Definition**: The entire workflow depends on a single component with no
fallback or degraded mode.

**When to apply**: Infrastructure components that many operations depend
on; credential stores; state files that are the sole source of truth;
any component whose unavailability blocks all forward progress.

**What to look for**:
- A single service, file, or credential that every operation in the system
  depends on, with no alternative path if it's unavailable.
- Operations that can't proceed at all if one "optional" component is
  missing — optional in theory, required in practice.
- No degraded or read-only mode for core operations when a non-critical
  dependency is unavailable.
- No retry or circuit-breaker logic for calls to the critical component.

**Example**: All cell operations require the KeePass vault to be unlocked
— if the vault file is corrupted, no operation can proceed and there's no
degraded read-only mode for non-sensitive operations.

---

### 17. Credential Sprawl

**Definition**: Secrets exist in multiple places (config files, env vars,
state files, hardcoded defaults), making rotation and revocation
unreliable because rotating one copy leaves others stale.

**When to apply**: Any system with credentials, tokens, or secrets; any
workflow that generates or distributes credentials; configuration schemas
that include sensitive fields.

**What to look for**:
- The same credential or secret appearing in more than one file, env var,
  or config section.
- Copy-paste of secret values rather than references to a single canonical
  location.
- Generated files that embed secrets from a source config — rotating the
  source doesn't update the generated copy.
- Hardcoded default credentials that exist alongside runtime-configured
  ones.

**Example**: A database password appears in both the forge manifest and a
generated `.env` file — rotating the manifest value doesn't update the
`.env`, leaving a stale credential in place.

---

### 18. Audit Log Gap

**Definition**: Significant operations occur without any log entry, making
forensic reconstruction of "what happened" impossible after the fact.

**When to apply**: State-modifying operations; authentication and
authorization events; remediation and recovery actions; any operation
whose execution history matters for debugging or compliance.

**What to look for**:
- State changes with no log call — the state file changes but nothing
  records when, why, or by whom.
- Authentication events (successful and failed) not recorded in any
  persistent log.
- Operations that log only to stderr — after a restart, nothing captures
  what was done.
- Remediation or recovery actions that execute and modify system state
  but leave no persistent trace.

**Example**: Remediation actions execute and modify system state but log
only to stderr — after a restart, there's no record of what was changed
or when.

---

### 19. Time-of-Check/Time-of-Use (TOCTOU)

**Definition**: A condition is checked at one point but the system assumes
it still holds when the dependent action runs, even though it can change
in between.

**When to apply**: Resource allocation (IDs, ports, file names); permission
checks before privileged operations; any concurrent or distributed workflow
where state can change between check and use.

**What to look for**:
- `if resource.exists(): use(resource)` patterns with no atomic
  check-and-use.
- Permission checks performed before a privileged operation with any gap
  between the check and the operation.
- Resource uniqueness checks (VMID, port number, file name) that are
  followed by allocation, with no atomic reservation step.
- Race conditions in concurrent workflows where two actors can pass the
  same check simultaneously.

**Example**: Spawn checks that a VMID is unallocated, then allocates it
200ms later — a concurrent spawn can grab the same VMID in between,
resulting in two VMs with the same ID.

---

### 35. Confused Deputy

**Definition**: A privileged component can be directed by a less-privileged
caller to perform actions using its elevated privileges, without proper
authorization checks on the request itself.

**When to apply**: Any daemon, server, or service that runs with elevated
privileges; APIs that execute privileged operations; any component that
acts on behalf of another.

**What to look for**:
- Daemon/server processes that accept commands and execute them using their
  own credentials.
- Tools that run as root and accept parameters from stdin/env.
- Any case where "who is asking" isn't verified separately from "what is
  being asked."
- APIs that execute privileged operations without checking whether the
  caller is authorized to request them.

**Example**: A dashboard API executes privileged remediation operations
based on HTTP request content — if the auth check has any gap, an attacker
can direct the privileged daemon to act on their behalf.

---

### 36. Over-Privileged Component

**Definition**: A component runs with more privilege than its task requires.
If compromised, the blast radius is larger than necessary.

**When to apply**: Any service, daemon, or process that runs with elevated
privileges; credential scoping; filesystem permission reviews; any component
whose privilege level isn't explicitly justified.

**What to look for**:
- Processes that run as root when they only need one specific capability.
- Services with broad filesystem access when they only need one directory.
- Tokens with admin scope when read-only would suffice.
- Components that share a privilege level with unrelated components.

**Example**: A webhook receiver runs as the same user as the forge
orchestrator — a compromise of the receiver grants full forge capabilities
including KeePass access.

---

## Architecture

Patterns in this section describe structural failures: design choices at
the system or module level that create problems independent of any
individual operation's correctness.

### 20. Catch-22 / Circular Dependency

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

**Example**: Spawn needs the k3s join token that forge was supposed to
write, but forge only writes it after k3s is running, which requires a
node to have already joined.

---

### 21. Orphaned Outputs

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

### 22. Dual Authority

**Definition**: Two different sources of truth for the same data exist with
no reconciliation mechanism — one gets updated, the other doesn't.

**When to apply**: Any system with multiple representations of the same
data; state files that are echoed to caches or databases; configuration
data also stored in generated artifacts.

**What to look for**:
- The same value stored in both a state file and a config file, with
  no synchronization mechanism.
- Manifest data also cached in a database or in-memory store with no
  invalidation strategy.
- Documentation that duplicates code-level constants (magic numbers,
  thresholds, identifiers) with no single source of truth.
- Any place where two systems "agree" by coincidence rather than by
  design.

**Example**: The cell's node list exists in both `bootstrap-state.json`
and the dashboard's in-memory cache — they can diverge after a crash,
and there's no mechanism to detect or resolve the divergence.

---

### 23. Version Skew

**Definition**: Two components have compatible interfaces today but nothing
enforces that they'll stay compatible as each evolves independently.

**When to apply**: Any inter-component data exchange; file formats shared
between producer and consumer; API contracts between services or modules.

**What to look for**:
- Inter-component contracts defined by convention or informal agreement
  rather than by schema, assertion, or version negotiation.
- Components sharing data formats with no version field — any format
  change silently breaks the consumer.
- Cases where correctness relies on both sides being updated together, with
  no mechanism to detect or prevent partial updates.
- Shared serialization formats with no migration path for old data.

**Example**: Forge writes `bootstrap-state.json` in a format spawn reads
— but there's no schema version field, so a format change in forge
silently breaks spawn without any error until the bad data is consumed.

---

### 24. Layer Violation

**Definition**: A component reaches past its proper architectural layer to
directly access internals of a lower (or higher) layer.

**When to apply**: Any codebase with documented or de-facto architectural
layers; imports between modules in different layers; any place where a
high-level component consumes raw output from a low-level one.

**What to look for**:
- UI or dashboard code parsing raw state files or generated scripts
  rather than reading from a canonical API or data layer.
- Low-level utility modules importing from high-level orchestration
  modules.
- Any import that crosses documented architecture layer boundaries.
- Components that scrape or parse the output of other components
  rather than consuming a defined interface.

**Example**: The dashboard directly parses `forge_scripts.py`'s generated
bash to extract hostnames, rather than reading from the canonical state
file — tightly coupling two layers that should be independent.

---

### 25. Configuration Explosion

**Definition**: Too many configuration options with no documented sensible
defaults, forcing the operator to make decisions they don't have context
for.

**When to apply**: Configuration schemas; manifest formats; any CLI tool or
framework with many tunable parameters; complex setup wizards.

**What to look for**:
- Config schemas with many required fields and no documented defaults.
- Options that interact with each other in undocumented ways — setting
  option A to X means option B must be set to Y, but this isn't described.
- Anything where the operator must understand implementation internals to
  make a correct configuration choice.
- Configuration that "works" with any value but silently produces wrong
  behavior for incorrect choices.

**Example**: A spawn plan requires 15 fields to be set manually with no
defaults, and several interact (e.g. `ha_mode` and `k3s.role` must be
consistent) in ways not described anywhere in the docs or tooling.

---

### 37. Hardcoded Environment

**Definition**: Values that should be configurable (paths, hostnames,
ports, thresholds, timeouts) are baked into code, making the system
impossible to adapt without code changes. The opposite of Configuration
Explosion.

**When to apply**: Any code that references filesystem paths, network
addresses, or tunable constants; deployment scripts; any code that would
need to change to deploy in a different environment.

**What to look for**:
- Absolute paths in source code.
- Hardcoded IP addresses or hostnames.
- Magic numbers with no named constant or config entry.
- Constants that would need to change for a different deployment
  environment.

**Example**: A forge script hardcodes `/var/lib/broodforge` as the state
directory — deploying on a system where that path isn't writable requires
a code change rather than a config change.

---

### 38. Package Integrity Self-Verification

**Definition**: A distributable or deployable package carries no
cryptographic descriptor of its own contents, making it impossible to
verify the package's authenticity before deployment and impossible to
detect when the codebase drifts from the last recorded state.

**When to apply**: Any package, installer, migration bundle, or artifact
that will be distributed or deployed to a host where the operator cannot
easily verify provenance; any project that uses PAP for revision
management; migration workflows where a package is applied to a live
system; any project where "did the right version get deployed?" is a
question that could arise after the fact.

**What to look for**:
- A deployable package with no `package-descriptor.json` (or equivalent)
  recording the SHA-256 of its content set, the sorted list of files
  hashed, and the timestamp the descriptor was last stamped.
- No `stamp` tool (or equivalent) to recompute and update the descriptor
  after any change to the package.
- No `verify` tool (or equivalent) to check the current package state
  against the recorded descriptor, with a non-zero exit on mismatch.
- A deployment or migration runbook with no pre-use integrity check step.
- A descriptor that exists but is not regenerated by the release
  ceremony — a stale hash is as dangerous as no hash.
- No list of exactly which files are included in the hash, making it
  impossible to reproduce the hash independently.
- The descriptor file itself included in the hashed content set — this is
  a self-referential loop: the hash cannot be known until the descriptor
  is written, but writing the descriptor changes the hash, making stable
  convergence impossible. The descriptor file must be explicitly excluded
  from the content set before computing the hash. The `files_hashed`
  field records this exclusion implicitly by omitting the descriptor's
  own path.

**Example**: A migration package is distributed to a remote host and
applied without any pre-use integrity check — an accidental manual edit,
bitflip in transit, or wrong-version deployment is undetectable until the
migration produces wrong results, and forensic reconstruction of "what
was actually applied" is impossible.

**Dual-descriptor pattern (advanced)**: For systems where source files and
operational state files have different lifecycles, a single package descriptor
is insufficient.  Consider tracking two separate descriptors:

- **Package descriptor** (`package-descriptor.json`) — SHA-256 over static source
  files (`.py`, `.sh`, `.md`); updated at release time by the stamp tool.
- **State descriptor** (`state-descriptor.json`) — SHA-256 over operational state
  files (`manifest.toml`, `bootstrap-state.json`, active migration scripts, etc.);
  updated after any state-mutating operation (migration, spawn, phoenix restore).

**Mutual exclusion rule (critical)**: neither descriptor is ever included in the
other's content set.  The package hash excludes all state files (`.json`, `.toml`,
`.jsonl`); the state hash excludes all source files (`.py`, `.sh`, `.md`).
Critically, each descriptor file itself is explicitly excluded from its own hash
computation (self-reference loop protection), and each is excluded from the other's
hash (cross-contamination prevention).  This mutual exclusion must be enforced in
code — not just documented — so that future additions to either content set cannot
accidentally re-introduce either descriptor file.

This pattern ensures that a state change (e.g. a migration updating
`bootstrap-state.json`) does not invalidate the package hash, and a source change
does not reset the state hash.  Both can be verified independently and at any time
on a live deployed instance.

**Companion pattern**: **Embedded Version Constant** (#39) — the version
recorded in the package descriptor should itself be a baked-in static
constant, not a runtime git call.

---

### 39. Embedded Version Constant

**Definition**: A package's version is not baked in as a static constant
at release time, but is instead computed at runtime via `git describe`,
`git rev-parse`, or equivalent. On a deployed host where the git
repository is absent or git is not installed, the version is empty,
wrong, or raises an error — making forensic reconstruction of "which
version was applied" impossible from logs alone.

**When to apply**: Any package or service that exposes or logs a version
identifier; any deployment where the target host may not have git
installed or the repository checked out; packages distributed as archives
rather than live checkouts.

**What to look for**:
- A version string computed via `subprocess.run(["git", ...])` or
  `git describe` in any production code path.
- A version value that changes based on the environment (development vs.
  production) rather than being fixed at release time.
- No dedicated `version.py` (or equivalent) containing a static string
  constant written by the release tool.
- A release procedure with no explicit step to update and commit the
  version constant before packaging.
- A version format consisting of a bare hash with no human-readable
  timestamp component — a bare hash is valid but harder to interpret and
  order than `YYYY-MM-DD_HH-MM-SS_<hash>`.
- A version constant that exists but is only updated manually rather than
  being written atomically by the same tool that stamps the integrity
  descriptor.

**Example**: A deployed migration runner calls `git rev-parse HEAD` to
log its version — on the target host, which has no git installation, this
raises a `FileNotFoundError`. The version is logged as `unknown`, making
it impossible to determine which revision was applied without examining
file content directly.

**Companion pattern**: **Package Integrity Self-Verification** (#38) —
the static version constant is one of the fields recorded in the
integrity descriptor; the two patterns are most effective when applied
together.

---

## Provenance

Created at direct operator request (2026-06-08) to seed a reusable audit
lens library for PAP-audit prompts. Patterns are drawn from recurring
failure modes observed during hands-on broodforge audits conducted under
[PAP-AUDIT](PAP-AUDIT.md). Integrated into the PAP-AUDIT module via
[PAP-AUDIT §5](PAP-AUDIT.md#5-audit-reasoning-patterns-catalog).

Extended (2026-06-08) with 19 additional patterns organized into four
thematic sections: Workflow & Operator Experience, Implementation
Correctness, Security & Reliability, and Architecture. The original 6
patterns were reorganized into these sections for coherence (Documentation
Drift → Workflow; Assumed Preconditions, Silent Degradation, State Machine
Gaps → Implementation Correctness; Catch-22, Orphaned Outputs →
Architecture).

Extended (2026-06-08) with 12 additional patterns (#26–37): Cliff-Edge
Error, Feedback Vacuum, Missing Observability, Silent Success, Alert
Fatigue Setup (Workflow & Operator Experience); Regression Blind Spot,
Leaky Abstraction, Action at a Distance, Abstraction Inversion
(Implementation Correctness); Confused Deputy, Over-Privileged Component
(Security & Reliability); Hardcoded Environment (Architecture).

Extended (2026-06-09) with 2 additional patterns (#38–39): Package
Integrity Self-Verification, Embedded Version Constant (Architecture).
Codified from implementation in the broodforge project; generically
applicable to any project that ships a deployable artifact under PAP
revision management.

---

## Dynamic Analysis and the Patterns Catalog

The static analysis toolchain that seeds this catalog (§5 in
[PAP-AUDIT.md](PAP-AUDIT.md)) is necessary but not sufficient. The
following dynamic analysis tools complement the static pass and are
documented in [PAP-AUDIT §6](PAP-AUDIT.md#6-dynamic-analysis-pre-flight):

| Tool | Primary patterns surfaced |
|---|---|
| **hypothesis** (property-based testing) | Happy Path Only, Assumed Preconditions, Idempotency Gap |
| **mutmut** (mutation testing) | Regression Blind Spot, Happy Path Only |
| **bats** (bash script testing) | Happy Path Only, Silent Degradation (bash), Assumed Preconditions |
| **beartype** / **typeguard** (runtime type verification) | Assumed Preconditions, Silent Degradation |
| **deal** / **icontract** (design-by-contract) | Assumed Preconditions, State Machine Gaps, Idempotency Gap |
| **schemathesis** (HTTP API property testing) | Assumed Preconditions, Fail Open, Test/Production Divergence |
| **atheris** (coverage-guided fuzzing) | Assumed Preconditions, Silent Degradation, Happy Path Only |

**Key relationship**: high line coverage combined with a low mutation
score (mutmut) is a stronger Regression Blind Spot finding than coverage
alone suggests — it indicates tests that *exercise* code without
*asserting* anything meaningful. Report both metrics in audit records.

Dynamic analysis tool integration is part of the standard pre-flight
workflow and feeds directly into the patterns catalog pass. See
[PAP-AUDIT §6](PAP-AUDIT.md#6-dynamic-analysis-pre-flight) for the
full integration workflow and score interpretation guidance.
