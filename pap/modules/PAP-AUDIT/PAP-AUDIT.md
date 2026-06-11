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

## 5. Static Analysis Pre-Flight

Run these tools **first**, before the dynamic pre-flight (§6) and manual reasoning-pattern analysis (§7). Their output directly seeds the manual audit: coverage gaps tell you where to look for Regression Blind Spots; vulture output seeds the Orphaned Outputs check; bandit output seeds the security-pattern checks. Record all findings per the classification taxonomy in §3.

All tools are free/open-source (MIT, Apache 2.0, or GPL). Python tools install via `pip install <tool>`; shellcheck installs via system package manager (`brew install shellcheck`, `apt install shellcheck`, etc.).

### 5.1 shellcheck — Shell Script Static Analysis

**What it catches**: Unexported variables, quoting issues, command substitution errors, unset variable references, portability problems.

**Patterns directly surfaced**: Silent Degradation, Happy Path Only, Assumed Preconditions (in shell context).

**Command**:
```
shellcheck **/*.sh
```

Also apply to any bash-script outputs the project generates at runtime.

### 5.2 ruff (or flake8) — Python Linting

**What it catches**: Undefined names, unused imports, unreachable code, syntax errors.

**Patterns directly surfaced**: Orphaned Outputs (unused imports/functions), Silent Degradation (unreachable exception handlers).

**Command**:
```
ruff check .
```

### 5.3 bandit — Python Security Analysis

**What it catches**: Hardcoded passwords, shell injection, insecure subprocess use (`shell=True`), unsafe deserialization, weak crypto.

**Patterns directly surfaced**: Confused Deputy, Credential Sprawl, Fail Open.

**Command**:
```
bandit -r . -ll
```

(`-ll` reports medium- and high-severity findings; use `-l` for a full pass including low-severity.)

### 5.4 pytest --cov — Test Coverage Measurement

**What it catches**: Untested code paths and uncovered branches.

**Patterns directly surfaced**: Regression Blind Spot, Happy Path Only (branches never exercised).

**Command**:
```
pytest --cov --cov-report=term-missing --cov-branch
```

Every uncovered branch is a candidate Regression Blind Spot or Happy Path Only finding — treat coverage gaps as actionable audit input, not just a metric.

### 5.5 vulture — Dead Code Detection

**What it catches**: Unused functions, classes, variables, and imports.

**Patterns directly surfaced**: Orphaned Outputs, Abstraction Inversion.

**Command**:
```
vulture . --min-confidence 80
```

Feed vulture's output directly into the Orphaned Outputs pattern check in §7.

### 5.6 detect-secrets — Credential Scanning

**What it catches**: Hardcoded secrets, API keys, tokens, and passwords embedded in source files.

**Patterns directly surfaced**: Credential Sprawl, Hardcoded Environment.

**Command**:
```
detect-secrets scan --baseline .secrets.baseline
```

Establish a baseline on first run; subsequent runs diff against it to surface new additions.

### 5.7 semgrep — Pattern-Based Analysis

**What it catches**: Standard security and correctness anti-patterns via the auto ruleset; project-specific anti-patterns via custom rules (e.g. `datetime.now()` bypass, `subprocess` without `check=True`, bare `except`).

**Patterns directly surfaced**: Missing Seam, Test/Production Divergence, TOCTOU.

**Commands**:
```
semgrep --config=auto .
```

For project-specific patterns, add custom rules targeting anti-patterns most relevant to this codebase (e.g. unchecked subprocess calls, mocked production paths).

### 5.8 mypy — Static Type Checking

**What it catches**: `None` used as a value, wrong argument types, missing return paths.

**Patterns directly surfaced**: Assumed Preconditions, Happy Path Only, Silent Degradation.

**Command**:
```
mypy . --ignore-missing-imports
```

### Pre-Flight Workflow

1. Run all tools applicable to the project's language stack; skip irrelevant tools.
2. Triage output: classify each finding per §3 (BLOCKER / DEFECT / RISK / IMPROVEMENT / OBSERVATION).
3. Carry findings forward into the dynamic pre-flight (§6) and manual reasoning-pattern pass (§7):
   - Coverage gaps → Regression Blind Spot, Happy Path Only
   - vulture output → Orphaned Outputs, Abstraction Inversion
   - bandit / detect-secrets output → Confused Deputy, Credential Sprawl, Fail Open, Hardcoded Environment
   - mypy / ruff output → Silent Degradation, Assumed Preconditions, Orphaned Outputs
   - semgrep output → Missing Seam, Test/Production Divergence, TOCTOU
4. Include pre-flight results in the Audit Record (§4).

## 6. Dynamic Analysis Pre-Flight

Run these tools **after** the static pre-flight (§5) and **before** deep manual reasoning-pattern analysis (§7). Dynamic tools exercise code at runtime and discover failures that static analysis cannot — a type annotation can be structurally valid yet violated by the values that actually flow through it; a test suite can cover every line yet fail to detect the mutations that matter.

All tools are free/open-source. Python tools install via `pip install <tool>`; bats installs via system package manager.

**No deployment needed** (runs against source or the existing test suite):
`beartype`, `deal`/`icontract`, `hypothesis`, `mutmut`, `bats`

**Requires a running service**:
`schemathesis` (HTTP API must be reachable; use `--app` with a test-mode server to avoid needing full infrastructure), `atheris` (long-running fuzzer; run locally or in a dedicated CI stage)

### Recommended Integration Order

Apply from cheapest (zero new test code) to most involved:

| Step | Tool | Effort |
|---|---|---|
| 1 | `beartype` | Add one line to `conftest.py`; zero new tests |
| 2 | `deal` / `icontract` | Decorate critical functions with contracts |
| 3 | `hypothesis` | Write property tests for pure logic |
| 4 | `mutmut` | Run after any major test suite addition |
| 5 | `bats` | Write `.bats` files for shell scripts |
| 6 | `schemathesis` | Run against API in test mode with mock backends |
| 7 | `atheris` | Create fuzz targets; run extended passes |

### Score Interpretation

- **Mutation score** (`mutmut`): < 60% = test suite hollow — RISK or DEFECT finding; 60–80% = acceptable; > 80% = strong. Report the score in the audit record.
- **Coverage vs. mutation**: high line coverage combined with a low mutation score indicates tests that exercise code without asserting anything meaningful — a stronger Regression Blind Spot finding than coverage alone would suggest.
- **`schemathesis` failures**: any 5xx response from a generated request is a DEFECT; unhandled input shapes are Assumed Preconditions findings.

### 6.1 beartype — Runtime Type Checking

**What it catches**: Type annotation violations that only manifest with real runtime values — `Optional` not handled, union-type narrowing errors, incorrect return types.

**Patterns directly surfaced**: Assumed Preconditions, Silent Degradation.

**Setup**: Add to `conftest.py`:
```python
from beartype.claw import beartype_this_package
beartype_this_package()
```

No new test code required. Violations surface as `BeartypeException` during normal `pytest` runs.

### 6.2 deal / icontract — Contract-Based Invariant Testing

**What it catches**: Violated preconditions (bad inputs reaching a function), violated postconditions (bad outputs leaving a function), broken invariants (object state corruption).

**Patterns directly surfaced**: Assumed Preconditions, State Machine Gaps, Idempotency Gap.

**Setup**: Decorate functions with contracts; contracts are verified automatically during pytest runs:
```python
import deal

@deal.pre(lambda count: count >= 0)
@deal.post(lambda result: result is not None)
def schedule_items(count: int) -> list:
    ...
```

Use `deal` for simple pre/postconditions; use `icontract` for richer invariant expression.

### 6.3 hypothesis — Property-Based Testing

**What it catches**: Edge cases in pure logic that example-based tests miss: off-by-one errors, empty-collection handling, ordering assumptions, integer overflow.

**Patterns directly surfaced**: Happy Path Only, Assumed Preconditions, Idempotency Gap.

**Apply to**: Pure logic functions — planners, scorers, parsers, generators. No running system needed. Hypothesis generates thousands of random structured inputs and shrinks failures to minimal examples.

```python
from hypothesis import given, strategies as st

@given(st.lists(st.integers()))
def test_scorer_handles_any_list(items):
    result = score_items(items)
    assert result >= 0
```

### 6.4 mutmut — Mutation Testing

**What it catches**: Test suite gaps where tests pass even when the code is subtly broken. Introduces small mutations (flips `>` to `>=`, removes `not`, changes `+` to `-`) and checks whether any test fails.

**Patterns directly surfaced**: Regression Blind Spot, Happy Path Only.

**Apply after**: Any major test suite addition.

**Command**:
```
mutmut run
mutmut results
```

Score interpretation: see §6 Score Interpretation above. Record the mutation score in the audit record alongside coverage.

### 6.5 bats — Bash Script Testing

**What it catches**: Failures in generated shell scripts and provisioning scripts: missing error handling, wrong exit codes, assumed command presence, and quoting bugs not caught by shellcheck.

**Patterns directly surfaced**: Happy Path Only, Assumed Preconditions, Silent Degradation (in bash context).

**Apply to**: Any project that generates or ships shell scripts. No real hardware needed — mock system commands with bats fixtures.

**Setup**: Create `tests/bash/` and write `.bats` files:
```bash
@test "provisioner exits nonzero when target is missing" {
    run bash provisioner.sh --target /nonexistent
    [ "$status" -ne 0 ]
}
```

Install: `brew install bats-core` or `apt install bats`.

### 6.6 schemathesis — HTTP API Property Testing

**What it catches**: Unhandled input shapes that cause 5xx errors, missing input validation, schema/implementation drift.

**Patterns directly surfaced**: Assumed Preconditions, Happy Path Only, Test/Production Divergence.

**Apply to**: Any project with HTTP endpoints. Start the API in test mode with mock backends; no full deployment needed.

**Command**:
```
schemathesis run http://localhost:8000/openapi.json --checks all
```

Any 5xx response from a generated request is an Assumed Preconditions or Silent Degradation finding. Schema violations that the implementation silently accepts are Test/Production Divergence findings.

### 6.7 atheris — Coverage-Guided Fuzzing

**What it catches**: Crashes, assertion failures, and uncaught exceptions triggered by unexpected input shapes that neither example tests nor property tests explored.

**Patterns directly surfaced**: Assumed Preconditions, Silent Degradation, Happy Path Only.

**Apply to**: Parsers, deserializers, any function that processes external or untrusted input.

**Setup**: Create `tests/fuzz/` with fuzz targets:
```python
import atheris
import sys

def TestOneInput(data):
    fdp = atheris.FuzzedDataProvider(data)
    parse_config(fdp.ConsumeUnicodeNoSurrogates(100))

atheris.Setup(sys.argv, TestOneInput)
atheris.Fuzz()
```

Run locally for extended passes; integrate short-duration CI runs (`-runs=10000`) to catch regressions.

### Dynamic Pre-Flight Workflow

1. Add `beartype_this_package()` to `conftest.py` and run `pytest` — violations are immediate, zero-effort findings.
2. Decorate highest-risk functions with `deal`/`icontract` contracts and run `pytest` again.
3. Write `hypothesis` property tests for pure logic functions; run `pytest`.
4. After any major test suite addition, run `mutmut` and record the mutation score.
5. For projects with shell scripts, write `tests/bash/*.bats` and run `bats tests/bash/`.
6. For projects with HTTP endpoints, start the API in test mode and run `schemathesis`.
7. For parsers and input-handling functions, create `tests/fuzz/` targets and run `atheris`.
8. Classify all failures per §3 and carry findings forward into the manual pattern pass (§7).

## 7. Audit Reasoning Patterns Catalog

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

Current catalog: 39 patterns organized into four sections —
**Workflow & Operator Experience** (Documentation Drift, No Recovery Path,
One-Way Door, Invisible Prerequisites, Operator Knowledge Assumption,
Missing Escape Hatch, Cliff-Edge Error, Feedback Vacuum, Missing
Observability, Silent Success, Alert Fatigue Setup), **Implementation
Correctness** (Assumed Preconditions, Silent Degradation, State Machine
Gaps, Happy Path Only, Idempotency Gap, Non-Atomic Multi-Step,
Test/Production Divergence, Missing Seam, Regression Blind Spot, Leaky
Abstraction, Action at a Distance, Abstraction Inversion), **Security &
Reliability** (Fail Open, Single Point of Failure, Credential Sprawl,
Audit Log Gap, TOCTOU, Confused Deputy, Over-Privileged Component), and
**Architecture** (Catch-22 / Circular Dependency, Orphaned Outputs, Dual
Authority, Version Skew, Layer Violation, Configuration Explosion,
Hardcoded Environment, Package Integrity Self-Verification, Embedded
Version Constant).

**For projects that ship a deployable artifact** (package, installer,
migration bundle): pay particular attention to patterns #38 (Package
Integrity Self-Verification) and #39 (Embedded Version Constant). A
missing integrity descriptor is a RISK; a descriptor that is not
regenerated as part of the release ceremony is a DEFECT; a version
string computed at runtime via `git` on the deployed host is a DEFECT.

## Provenance

Realizes Part II ("PAP-AUDIT") of
[Deliverable 4](../../revisions/synthesis/04_Canonical_PAP_Revision.md). Carries
forward UPCCMP 22-09's Systematic Review Governance, Finding
Classification, and full-form APDRP (PAP 22-39 retained only a
compressed echo — see [Gap Analysis](../../revisions/synthesis/02_Gap_Analysis.md) §1.5
and §5), plus the audit-status record shape evidenced in
`UPCCMP_PROTOCOL_RESUME_BLOCK.yaml`.
