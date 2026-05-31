# Session Handoff

Date: 2026-05-30
Status: Ready to resume at Milestone 5.6

---

## Where We Are

Phase 5 — Documentation Generation Foundation is 5/6 milestones complete.
The next session should begin at **Milestone 5.6 — Historical State Integration**.

Architecture was revised to v4.0 in this session. Read `docs/ARCHITECTURE-REVIEW-v4.md`
before making any structural decisions. The seven-state model and six-layer lifecycle
replace the previous five-state model.

---

## Project Instructions (from .ai/)

The AI context files are the authoritative project memory:

- `.ai/context.md` — what the project is, current phase, key design decisions
- `.ai/decisions.md` — AD-001 through AD-012, all architecture decisions with rationale

Read both before starting work.

---

## Key File Locations

### Project root
```
Y:\My Drive\home\software_development\proxmox-assessment-engine\proxmox-assessment-engine\
```

### Documentation
```
ARCHITECTURE.md               v4.0 — seven-state model, six-layer lifecycle
ROADMAP.md                    v4.0 — all phases and milestones
CURRENT_STATE.md              Current milestone status and gap table
docs/ARCHITECTURE-REVIEW-v4.md  Full review rationale (read this)
docs/MILESTONE-5-DESIGN.md    Original Phase 5 design doc (still accurate for 5.6)
```

### Schemas (all validated, all passing)
```
data-model/observed-state-schema.json   Tier 1/2 manifest (includes backup_inventory)
data-model/historical-state-schema.json Snapshot index + drift records
data-model/recovery-state-schema.json   Dependency graph + readiness report
data-model/declared-state-schema.json   OpenTofu state
data-model/configured-state-schema.json Ansible inventory
data-model/validate.py                  Schema validator (stdlib only)
```

### Assessment package
```
assessment/tier1/bootstrap.sh           Entry point
assessment/tier1/analyze.py             Manifest builder → manifest.json
assessment/tier1/collectors/            6 modular collectors
```

### Documentation generator
```
doc-gen/engine.py                       CLI: --mode bootstrap | recovery
doc-gen/analyzers.py                    10 DERIVED field analyzers
doc-gen/dependencies.py                 Dependency graph + topological sort
doc-gen/readiness.py                    GREEN/YELLOW/ORANGE/RED/BLOCKED scorer
doc-gen/readiness_report.py             Standalone Readiness-Report.md + .json
doc-gen/field-maps/bootstrap-fields.yaml
doc-gen/renderers/workbook.py           Bootstrap ODS (stdlib zipfile+XML)
doc-gen/renderers/runbook.py            Bootstrap ODT
doc-gen/renderers/recovery_workbook.py  Recovery ODS
doc-gen/renderers/recovery_runbook.py   Recovery ODT
```

### Tests (90 total, all passing)
```
tests/unit/test_schema_validation.py    32 tests — schema validator
tests/unit/test_analyze.py             32 tests — manifest builder
tests/unit/test_readiness.py           26 tests — readiness scorer
```

### Fixtures
```
tests/fixtures/tier1/manifest.json      Fresh Proxmox host (no VMs)
tests/fixtures/tier2/manifest.json      Deployed env (4 VMs + backup inventory)
tests/fixtures/tier2/recovery-state.json  Dependency graph + readiness report
tests/fixtures/history-index.json       Snapshot index (2 entries)
```

### History store (currently empty — 5.6 will populate it)
```
history/                                Created but empty
```

### Generated reports (for reference)
```
reports/bootstrap_tier1/Bootstrap-Workbook.ods
reports/bootstrap_tier1/Bootstrap-Runbook.odt
reports/recovery_tier2/Recovery-Workbook.ods
reports/recovery_tier2/Recovery-Runbook.odt
reports/recovery_tier2/Restore-Sequence.md
reports/recovery_tier2/Readiness-Report.md
reports/recovery_tier2/Readiness-Report.json
```

---

## Milestone 5.6 — Historical State Integration

### Objective

Make documentation reproducible from any past assessment snapshot.
Enable drift detection between assessments.
Wire historical state into doc-gen so generated documents show "as of last assessment" fields.

### Deliverables

1. `history/index.json` — snapshot index builder
2. `doc-gen/drift.py` — field-level manifest diff and documentation drift detector
3. `history/snapshots/` — populated with the two existing fixture manifests
4. `doc-gen/engine.py` — updated to load historical state and populate drift fields
5. `tests/unit/test_drift.py` — drift detection tests
6. Reproducibility verification test (regenerate docs from historical snapshot, compare)
7. `CURRENT_STATE.md` updated

### Step 1 — Snapshot index builder

Create `history/snapshots/` directory.
Copy the two fixture manifests into it as named snapshots.
Build `history/index.json` from the schema already defined in
`data-model/historical-state-schema.json`.

The index schema (already defined):
```json
{
  "snapshots": [
    {
      "id": "bootstrap_2026-05-01_10_00_00",
      "tier": 1,
      "collected_at": "2026-05-01T10:00:00Z",
      "archive_path": "history/snapshots/bootstrap_2026-05-01_10_00_00.tar.gz",
      "manifest_path": "history/snapshots/bootstrap_2026-05-01_10_00_00/manifest.json",
      "template_version": "bootstrap-v1.0",
      "doc_generation_ids": [],
      "notes": ""
    }
  ],
  "latest_tier1_id": "...",
  "latest_tier2_id": "..."
}
```

Build `history/index.py` — a small CLI tool that:
- Scans `history/snapshots/` for manifest.json files
- Builds and writes `history/index.json`
- Run: `python3 history/index.py`

### Step 2 — Drift detector

Create `doc-gen/drift.py`. It should:

- Accept two manifest dicts (from_manifest, to_manifest)
- Walk all paths in the manifest using dot-notation
- For each path that exists in both: compare values, record changes
- For each path in from but not to: record removal
- For each path in to but not from: record addition
- Assign severity: IP/hostname changes = HIGH, version changes = MEDIUM, counts = LOW
- Return a drift record matching `historical-state-schema.json` drift record format:

```python
{
  "from_snapshot": "bootstrap_2026-05-01_10_00_00",
  "to_snapshot":   "assessment_2026-05-29_02_05_00",
  "generated_at":  "...",
  "diffs": [
    {
      "path": "memory.available_gb",
      "from_value": 61.2,
      "to_value": 18.3,
      "severity": "LOW",
      "documentation_impact": "Available RAM changed — capacity fields are stale"
    }
  ],
  "drift_severity": "LOW",
  "doc_fields_stale": []
}
```

Also add `doc_field_drift()` — given a drift record and a field map,
identify which generated document fields are now stale.

### Step 3 — Wire into doc-gen

Update `doc-gen/engine.py` recovery mode to:
- Load the latest historical snapshot from `history/index.json`
- Run drift detector between historical snapshot and current manifest
- Add a "Drift Since Last Assessment" section to the generation report
- Pass drift data to workbook renderer for a new "Drift" sheet

Update `doc-gen/engine.py` bootstrap mode to:
- Check if a prior bootstrap snapshot exists in history
- If so, note which fields have changed since last bootstrap

### Step 4 — Reproducibility test

Write `tests/unit/test_reproducibility.py`:
- Load the tier1 fixture manifest
- Run the full bootstrap doc-gen pipeline
- Store the output checksums
- Run again with the same manifest
- Assert that ODS and ODT outputs are byte-identical (deterministic generation)

This validates the reproducibility requirement from the design doc.

### Step 5 — Tests

Write `tests/unit/test_drift.py` covering:
- No changes between identical manifests → empty diffs
- IP address change → HIGH severity
- Version change → MEDIUM severity
- New VM added → detected as addition
- VM removed → detected as removal
- Nested path changes (e.g. storage.zfs_pools[0].free_gb)
- Severity escalation (drift_severity = worst of all diffs)
- doc_field_drift identifies stale fields correctly

---

## After 5.6 — Phase 6 (Bootstrap State)

The highest-value next work after 5.6 is **Milestone 6.3 — Secret Registry** and
**Milestone 6.4 — DNS Registry**, because these two items directly eliminate the
`[KEEPASS_PATH]` and `[VM_IP]` placeholders that remain in the current recovery
documentation.

After those two, do **Milestone 6.2 — Cloud-Init Template Library** to build the
actual snippet files that will pre-populate the Bootstrap Documentation Stage 02–N.

Full Phase 6 ordering is in `ROADMAP.md`.

---

## Test Commands

Run all tests to confirm clean starting state:
```bash
cd <project-root>
python3 tests/unit/test_schema_validation.py   # 32 tests
python3 tests/unit/test_analyze.py             # 32 tests
python3 tests/unit/test_readiness.py           # 26 tests
```

Run doc-gen to confirm it works:
```bash
python3 doc-gen/engine.py --mode bootstrap --manifest tests/fixtures/tier1/manifest.json
python3 doc-gen/engine.py --mode recovery  --manifest tests/fixtures/tier2/manifest.json
```

Validate all fixtures against schemas:
```bash
python3 data-model/validate.py --all tests/fixtures/
```

All three should complete without errors before beginning 5.6 work.

---

## Design Constraints to Preserve

- `analyze.py` and `validate.py` use **Python 3 stdlib only** (no pip installs)
- ODS and ODT renderers use **zipfile + XML only** (no odfpy)
- All doc-gen runs **without network access** (all data from manifest)
- UNRESOLVED fields are **never silently omitted** — always include reason + impact
- Historical snapshots must be **reproducible** — same manifest → same docs
