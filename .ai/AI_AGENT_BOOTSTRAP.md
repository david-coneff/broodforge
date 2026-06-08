# AI Agent Bootstrap

> **Note on this file's history**: steps 7–12 below originally pointed at
> `docs/SESSION-HANDOFF.md` — a hand-built, working prototype of session
> continuity that predated PAP's introduction to this repository. That
> mechanism (and `docs/SESSION-HANDOFF.md` itself) has been retired in favor
> of PAP-State's formally-specified equivalents, by direct operator
> instruction; see
> [`pap/revisions/2026-06-07_session-continuity-transition-to-pap.md`](../pap/revisions/2026-06-07_session-continuity-transition-to-pap.md)
> for the full rationale, evidence, and what changed. This file's *governance
> reading order* (steps 1–6) is unchanged and remains broodforge's own
> sovereign authority — `.ai/PROJECT_CHARTER.md` and its siblings still
> outrank everything in `pap/` (`PAP_CHARTER.md` §2.3).

## Read in this order

1. `.ai/PROJECT_CHARTER.md`
2. `.ai/DESIGN_PRINCIPLES.md`
3. `.ai/IMPLEMENTATION_RULES.md`
4. `.ai/CURRENT_STATE.md`        ← current milestone status
5. `.ai/context.md`              ← architecture summary and key decisions
6. `.ai/decisions.md`            ← AD-001 through AD-039
7. `pap/state/RESUME_BLOCK.md`   ← portable save-state: identity, objective,
                                    milestone, risks, blockers, next action
8. `pap/state/SESSION_HANDOFF.md` ← exact starting point: status, source
                                    materials (with why), decisions not to
                                    re-derive, milestone checklist, last
                                    completed step, next action, resume steps

## Then

Follow [PAP-Core's Startup Protocol](../pap/core/PAP-Core.md) and
[PAP-State §1](../pap/modules/PAP-State/PAP-State.md#1-startup-protocol),
loaded from this repository's own populated `pap/` tree:

9. Scan repository status; detect uncommitted changes; if any exist, follow
   PAP-State §1.3's procedure for deciding whether to revert or continue
   (consulting `pap/state/SESSION_HANDOFF.md` for stated intent).
10. Determine the current objective from `pap/state/RESUME_BLOCK.md` /
    `pap/state/SESSION_HANDOFF.md` — escalate per
    [PAP-Core §6.2](../pap/core/PAP-Core.md#62-escalation-and-disagreement-governance)
    if neither resolves it.
11. Implement the milestone; update tests.
12. Update `.ai/CURRENT_STATE.md`, `pap/state/RESUME_BLOCK.md`, and
    `pap/state/SESSION_HANDOFF.md` when complete — at minimum at every
    session boundary and every major milestone (PAP-State §3/§4
    `update_trigger`).

## Important

There are two codebases in this repository:

**Legacy pae CLI** (`engine/`, `collector/`, `schemas/`, `tests/` at root level)
Complete as of version 0.8. Do not modify unless explicitly instructed.
See `.ai/CURRENT_STATE_LEGACY.md` for its history.

**Doc-gen architecture** (`assessment/`, `doc-gen/`, `data-model/`, `tests/unit/`)
Active development. This is where all new work happens.
Architecture version: 4.0 — seven-state model, six-layer lifecycle.

## A note on scope (read before assuming "PAP governs broodforge now")

Steps 7–12 changed *which mechanism* tracks broodforge's own
codebase-development continuity — not *who governs broodforge*.
`.ai/PROJECT_CHARTER.md` remains broodforge's sovereign top-level authority,
exactly as before. PAP's modules, when run analytically against broodforge's
state (e.g. [`pap/audits/2026-06-07_broodforge-pap-audit.md`](../pap/audits/2026-06-07_broodforge-pap-audit.md)),
produce *findings and recommendations offered to* broodforge's own
governance — never directives (`PAP_CHARTER.md` §2.3; see also `pap/README.md`).
And neither this file nor the artifacts it now points to have anything to do
with broodforge's *infrastructure-remediation* function (the
planner → queue → executor → policy loop the platform runs against the
systems it manages) — that is the platform's product behavior, not its
development process, and is governed by its own operational artifacts, not
by these.
