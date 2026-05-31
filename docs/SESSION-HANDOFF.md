# Session Handoff

Date: 2026-05-31
Status: Ready to resume at Milestone 6.1

---

## Where We Are

Architecture was revised to v5.0 in this session. This supersedes v4.0.
Read `docs/ARCHITECTURE-REVIEW-v5.md` before making any structural decisions.

**The single most important v5.0 constraint:**
Every new schema must carry `cell_id` as a mandatory field (AD-013).
This is the federation-readiness gate. Do not create schemas without it.

Phase 5 is complete (5.1–5.6). Next work is Phase 6 — Bootstrap State.
The implementation work (Phases 6–12) is unchanged from v4.0 in scope, but all schemas
must be federation-ready from the start.

---

## Project Instructions (from .ai/)

- `.ai/context.md` — what the project is, key design decisions
- `.ai/decisions.md` — AD-001 through AD-021, all architecture decisions with rationale
- `.ai/CURRENT_STATE.md` — current milestone status

---

## Key Architecture Documents

```
ARCHITECTURE.md                  v5.0 — 17-state model, federation, digital twin
ROADMAP.md                       v5.0 — three tracks, 25 phases
docs/ARCHITECTURE-REVIEW-v5.md  Full v5.0 review rationale (read before structural decisions)
docs/ARCHITECTURE-REVIEW-v4.md  Retained for reference
```

---

## Key Implementation File Locations

### Schemas (data-model/)
```
observed-state-schema.json       Tier 1/2 manifest (exists, needs cell_id)
historical-state-schema.json     Snapshot index + drift records (exists, needs cell_id)
recovery-state-schema.json       Dependency graph + readiness (exists, needs cell_id)
declared-state-schema.json       OpenTofu state (exists, needs cell_id)
configured-state-schema.json     Ansible inventory (exists, needs cell_id)
validate.py                      Schema validator (stdlib only)

--- TO BE CREATED (Phase 6+) ---
bootstrap-state-schema.json      Cloud-Init, images, templates, provenance, secrets, DNS
service-state-schema.json        Service contracts, DNS, backup assignments
hardware-state-schema.json       BIOS, firmware, disks, NICs (Phase 13)
platform-state-schema.json       Proxmox config, certs, packages (Phase 13)
cluster-state-schema.json        Cluster topology, membership (Phase 14)
storage-state-schema.json        ZFS, Ceph, datastores (Phase 14)
external-dependency-state-schema.json  DNS providers, SMTP, certs (Phase 15)
data-protection-state-schema.json      PBS, backup jobs, RTO/RPO (Phase 15)
observability-state-schema.json        Monitoring, alerts, dashboards (Phase 16)
secret-reference-state-schema.json     Standalone secret registry (Phase 18)
capability-state-schema.json           Cell capabilities (Phase 18)
federation-state-schema.json           Trust, relationships, cell registry (Phase 19)
```

### Assessment
```
assessment/tier1/bootstrap.sh    Entry point
assessment/tier1/analyze.py      Manifest builder → manifest.json
assessment/tier1/collectors/     6 modular collectors
```

### Documentation Generator
```
doc-gen/engine.py                CLI: --mode bootstrap | recovery (+ drift)
doc-gen/analyzers.py             10 DERIVED field analyzers
doc-gen/dependencies.py          Dependency graph + topological sort
doc-gen/drift.py                 Field-level manifest diff
doc-gen/readiness.py             GREEN/YELLOW/ORANGE/RED/BLOCKED scorer
doc-gen/readiness_report.py      Standalone Readiness-Report.md + .json
doc-gen/renderers/               ODS and ODT generators (stdlib only)
```

### Tests (110 total, all passing)
```
tests/unit/test_schema_validation.py   32 tests
tests/unit/test_analyze.py             32 tests
tests/unit/test_readiness.py           26 tests
tests/unit/test_drift.py               17 tests
tests/unit/test_reproducibility.py     3 tests
```

### History Store
```
history/index.py                 Snapshot index builder CLI
history/index.json               Snapshot index (2 entries)
history/snapshots/               Historical manifest snapshots
```

---

## Milestone 6.1 — Bootstrap State Schema

### Objective

Create the bootstrap-state-schema.json and service-state-schema.json.
Create the proxmox-bootstrap/ repository structure.

### Critical constraint: cell_id mandatory

Every schema created in Phase 6+ must include:
```json
{
  "cell_id": { "type": "string", "description": "Identity of the owning Infrastructure Cell" }
}
```

### Deliverables

1. `data-model/bootstrap-state-schema.json` containing:
   - `cell_id` (mandatory)
   - Cloud-Init snippet manifests (per VM: user-data, network-config, vendor-data paths + hashes)
   - Base image registry (ISO name, checksum, source URL, created_at)
   - VM template registry (template name, base image, packages, created_at)
   - Deployment provenance records (per VM: tofu commit, ansible commit, cloud-init hashes)
   - Secret Registry (id, description, keepass_path, owning_cell, required_by, required_for)
   - DNS Registry (hostname, ip, vmid, role)
   - Service Contract format (service, vm, provided_interfaces, required_interfaces, startup_after)
   - Hardware bootstrap requirements (BIOS flags required: VT-x, IOMMU, etc.)
   - First-boot ordering constraints

2. `data-model/service-state-schema.json` containing:
   - `cell_id` (mandatory)
   - Running service inventory
   - Service contracts
   - DNS registrations
   - Backup job assignments
   - Secret references per service

3. `proxmox-bootstrap/` repository structure (directory layout + README)

4. Schema validation tests for both schemas

5. `CURRENT_STATE.md` updated

---

## Test Commands

Run all tests to confirm clean starting state:
```
py -3 tests/unit/test_schema_validation.py
py -3 tests/unit/test_analyze.py
py -3 tests/unit/test_readiness.py
py -3 tests/unit/test_drift.py
py -3 tests/unit/test_reproducibility.py
```

Run doc-gen to confirm it works:
```
py -3 doc-gen/engine.py --mode bootstrap --manifest tests/fixtures/tier1/manifest.json
py -3 doc-gen/engine.py --mode recovery  --manifest tests/fixtures/tier2/manifest.json
```

All should complete without errors before beginning 6.1 work.

---

## Design Constraints to Preserve

- `analyze.py` and `validate.py`: Python 3 stdlib only (no pip)
- ODS/ODT renderers: zipfile + XML only (no odfpy)
- doc-gen: runs without network access (all data from manifest)
- UNRESOLVED fields: never silently omitted
- Historical snapshots: reproducible (same manifest → same docs)
- **NEW: `cell_id` mandatory in all schemas (v5.0 AD-013)**
- **NEW: Secret Registry entries must include `owning_cell` field (v5.0 AD-016)**
