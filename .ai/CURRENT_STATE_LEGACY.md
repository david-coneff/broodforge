# Current State — LEGACY (pre-doc-gen architecture)

> This file records the state of the project before the documentation-generation
> architecture was introduced. It is preserved for historical reference.
> It is NOT the current state. See CURRENT_STATE.md for current status.

Version: 0.8

## Completed (legacy pae CLI codebase)

### Phase 1 – Foundation ✓
- Assessment schema, CLI, collector framework, parser framework, schema validation.

### Phase 2 – Node Parsers ✓
- Hardware, storage, network, Proxmox parsers.

### Phase 3 – SQLite History ✓
- HistoryDB (`assessments`, `changes`, `guest_summaries`), diff engine.
- CLI: `pae store`, `pae history`, `pae diff`.

### Phase 3b – Guest Inventory ✓
- `guest.schema.json`, guest inventory collection via Ansible, guest parser, guest report.
- CLI: `pae guest-collect`, `pae guest-report`.

### Phase 4 – Report Generation ✓
- Full node report, combined node+guest report.
- CLI: `pae report`, `pae full-report`.

### Phase 5 – History Repository Integration ✓
- `engine/repo.py` — push to GitHub / Forgejo via Contents API.
- CLI: `pae push`.

### Phase 6 – OpenTofu Declared State Ingestion ✓
- `schemas/declared_resource.schema.json`, `engine/opentofu.py`, `engine/compare.py`,
  `engine/report_compare.py`.
- CLI: `pae opentofu-ingest`, `pae compare`.
- 58 tests covering state parsing, comparison engine, CLI commands.

## Legacy test count: 286 tests across engine/, collector/, schemas/

## Note on legacy codebase
The engine/, collector/, schemas/, and tests/ (root-level) directories contain the
legacy pae CLI codebase. This code is complete and functional. It represents the
original assessment engine before the documentation-generation architecture (v4.0)
was designed.

The new architecture (doc-gen/, assessment/tier1/, data-model/, tests/unit/) was
built alongside the legacy code and does not replace it — it extends the project
toward automated documentation generation and disaster recovery capabilities.

Future work should consider whether and how to integrate the legacy pae CLI collectors
with the new Tier 2 assessment architecture.
