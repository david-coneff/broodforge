# AI Agent Bootstrap

## Read in this order

1. `.ai/PROJECT_CHARTER.md`
2. `.ai/DESIGN_PRINCIPLES.md`
3. `.ai/IMPLEMENTATION_RULES.md`
4. `.ai/CURRENT_STATE.md`        ← current milestone status
5. `.ai/context.md`              ← architecture summary and key decisions
6. `.ai/decisions.md`            ← AD-001 through AD-012
7. `docs/SESSION-HANDOFF.md`     ← exact starting point, file locations, step-by-step plan

## Then

8. Verify the mount is live and files are visible (see SESSION-HANDOFF.md)
9. Run the three pre-flight test commands (see SESSION-HANDOFF.md)
10. Implement the milestone described in SESSION-HANDOFF.md
11. Update tests
12. Update `CURRENT_STATE.md` and `docs/SESSION-HANDOFF.md` when complete

## Important

There are two codebases in this repository:

**Legacy pae CLI** (`engine/`, `collector/`, `schemas/`, `tests/` at root level)
Complete as of version 0.8. Do not modify unless explicitly instructed.
See `.ai/CURRENT_STATE_LEGACY.md` for its history.

**Doc-gen architecture** (`assessment/`, `doc-gen/`, `data-model/`, `tests/unit/`)
Active development. This is where all new work happens.
Architecture version: 4.0 — seven-state model, six-layer lifecycle.
