# Deprecated — Legacy pae CLI Codebase

## What is this

This directory contains deprecated design documents and artifacts from before the
documentation-generation architecture (v4.0) was designed.

The legacy **pae CLI source code** is preserved at the **repository root**, not here,
because moving it would break git history. See below for locations.

## Legacy pae CLI source code (at repo root)

```
engine/         Original engine: CLI, schema, parser, report, db, diff,
                repo push, opentofu ingestion, comparison
collector/      Original collector framework: base, registry, hardware,
                storage, network, proxmox, guests
schemas/        Original JSON schemas: assessment.schema.json,
                guest.schema.json, declared_resource.schema.json
tests/          Original 286 tests for all of the above
pyproject.toml  Original package definition (pae CLI entry point)
```

These are complete and functional (version 0.8). Do not modify them.
Do not run them as part of the current project workflow.

## Contents of this directory

```
deprecated/
  README.md                   This file
  DESIGN_NEXT_MILESTONE.md    Pre-v4.0 design doc (superseded by ARCHITECTURE.md v4.0)
```

## Why the legacy code is preserved

The legacy codebase informed the v4.0 architecture. Several concepts — the collector
framework, schema validation, OpenTofu ingestion, and diff engine — are directly
relevant to Tier 2 assessment work in Phases 6–7 of the current roadmap.

## What supersedes it

The active codebase:

```
assessment/     Tier 1 bootstrap assessment (replaces legacy collector/)
doc-gen/        Documentation generation engine (new capability)
data-model/     Seven-state JSON schemas (extends legacy schemas/)
tests/unit/     New test suite (110 tests, growing)
tests/fixtures/ Sample manifests for testing
```

Architecture: `ARCHITECTURE.md` and `docs/ARCHITECTURE-REVIEW-v4.md`.

## What to do with the legacy code

- **Read it** when building the Tier 2 full assessment engine — `collector/base.py`,
  `collector/registry.py`, and `engine/modules/` are good reference implementations.
- **Read it** when building the OpenTofu Declared State collector — `engine/opentofu.py`
  and `engine/compare.py` are complete and well-tested.
- **Read it** when extending history/drift — `engine/db.py` and `engine/diff.py` show
  a working history/diff pattern.
- **Do not** import from it in new code — migrate logic into the new architecture instead.
- **Do not delete it** until the functionality has been fully migrated.
