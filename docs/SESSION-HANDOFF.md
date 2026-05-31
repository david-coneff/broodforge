# Session Handoff

Date: 2026-05-31 13:34:57 UTC
Status: Ready to resume at Milestone 6.1

---

## Where We Are

Architecture was revised to v5.0 (Federated Infrastructure Digital Twin Platform).
Read `docs/ARCHITECTURE-REVIEW-v5.md` before any structural decisions.
Read `ROADMAP.md` for the full three-track phase plan.

**The single most important v5.0 constraint:**
Every new schema must carry `cell_id` as a mandatory field (AD-013).

---

## What Was Completed This Session

### Architecture
- v5.0 Architecture Review (`docs/ARCHITECTURE-REVIEW-v5.md`) — full redesign:
  seventeen-state model, federation, digital twin, five dependency graph types,
  three assessment tiers, infrastructure cells, consolidation modes
- `ARCHITECTURE.md` and `ROADMAP.md` fully rewritten for v5.0

### Bootstrap Toolchain (proxmox-bootstrap/)

| File | Purpose |
|---|---|
| `suggest-names.py` | Naming convention engine — derives all names from (hostname, kp_root, cidr, vms) |
| `setup-secrets.py` | Secret generation wizard with KeePassXC CLI integration |
| `setup-external-backup.py` | External backup wizard — GitHub or encrypted archive |
| `init-bootstrap-state.py` | Guided init wizard — discovers, prompts, generates full bootstrap-state.json |
| `generate-network-configs.py` | Generates network-config snippets from bootstrap-state |
| `generate-user-data.py` | Generates user-data snippets from bootstrap-state |
| `roles.py` | Infrastructure role catalog with consolidation modes (full/recommended/minimal) |
| `backup.py` | Archive naming, GPG encryption, transfer, listing, pruning |

### Schemas (data-model/)

New schemas added this session (all have `cell_id`):
- `bootstrap-state-schema.json` — fully extended with host_identity, vm_defaults,
  storage_config, keepass_config, network_topology, external_backup, container declarations
- `service-state-schema.json` — observed services, DNS registrations, backup assignments
- `container-state-schema.json` — Tier 2 assessment output for containerized workloads

### Key Design Decisions Made This Session
- `cell_id` mandatory everywhere (AD-013)
- Consolidation modes: full (3 VMs) / recommended (2 VMs) / minimal (1 VM)
- External backup: GitHub or encrypted archive (both wired into recovery runbook Step 0)
- Container compatibility: infrastructure-layer check only — application-layer is per-service runbooks
- Archive naming: `{cell_id}_{YYYY-MM-DD_HH_MM_SS}_{6-char-hash}.tar.gz.gpg`
- Volume backup naming: `{cell_id}_{vm}_{container}_{volume}_{ts}_{hash}.tar.gz.gpg`
- KeePass path convention: `{root}/{hostname}/{secret}` for host, `{root}/vms/{vmid}-{name}/password` for VMs

### Tests
500 tests total, all passing.

---

## Next Action: Milestone 6.1

**Bootstrap State Schema and Repository Structure**

### Deliverables

1. Validate `data-model/bootstrap-state-schema.json` is complete for 6.1 (it is —
   schema was built this session)

2. `proxmox-bootstrap/bootstrap-state.json` — a real populated example (not just test
   fixture). The `tests/fixtures/bootstrap/bootstrap-state.json` fixture is the reference.

3. `data-model/service-state-schema.json` already created.

4. Schema validation tests — 90 tests in `test_bootstrap_service_schemas.py` already passing.

5. **Next concrete task:** Milestones 6.2–6.8 continue as per ROADMAP.md.

The roadmap milestone order after 6.1:
- **6.2** Cloud-Init Template Library ✅ (done this session)
- **6.3** Secret Registry reader in doc-gen (reads secret-registry.yaml, pre-populates recovery steps)
- **6.4** DNS Registry reader in doc-gen (reads dns-registry.yaml, replaces [VM_IP] placeholders)
- **6.5** Deployment Provenance
- **6.6** Template Registry
- **6.7** Tier 2 Bootstrap State Collector
- **6.8** Bootstrap Documentation Update

---

## Key File Locations

### Project root
```
Y:\My Drive\home\software_development\proxmox-assessment-engine\proxmox-assessment-engine\
```

### Architecture and planning
```
ARCHITECTURE.md                       v5.0 — 17-state model, federation, digital twin
ROADMAP.md                            v5.0 — three tracks, 25 phases
docs/ARCHITECTURE-REVIEW-v5.md        Full v5.0 review rationale
docs/CONTAINER-COMPATIBILITY-PLAN.md  Phase 21 container compatibility design
.ai/decisions.md                      AD-001 through AD-021
.ai/CURRENT_STATE.md                  Current milestone status
```

### Bootstrap toolchain
```
proxmox-bootstrap/
  init-bootstrap-state.py     Run first on a new cell
  setup-secrets.py            Run second — generates + stores secrets
  setup-external-backup.py    Run third — configures GitHub or archive backup
  generate-network-configs.py Run after any IP/topology change
  generate-user-data.py       Run after any VM/timezone/username change
  suggest-names.py            Naming convention engine (importable)
  roles.py                    Role catalog + consolidation modes
  backup.py                   Archive utilities
  SNIPPET-UPLOAD.md           How to upload snippets to Proxmox
  snippets/user-data/         Generated Cloud-Init user-data (4 VMs)
  snippets/network-config/    Generated Cloud-Init network-config (4 VMs)
  snippets/vendor-data/       Proxmox vendor-data (infra-bootstrap)
  ssh/public-keys/            SSH public keys (populated by setup-secrets.py)
```

### Schemas
```
data-model/
  bootstrap-state-schema.json     Bootstrap declaration (Cloud-Init, registries, containers)
  service-state-schema.json       Observed service state
  container-state-schema.json     Observed container state (Tier 2)
  observed-state-schema.json      Tier 1/2 manifest
  historical-state-schema.json    Snapshot index + drift records
  recovery-state-schema.json      Dependency graph + readiness
  declared-state-schema.json      OpenTofu state
  configured-state-schema.json    Ansible inventory
  validate.py                     Schema validator (stdlib only)
```

### Tests (500 total, all passing)
```
tests/unit/
  test_schema_validation.py       32 — observed/historical/recovery/declared/configured schemas
  test_analyze.py                 32 — manifest builder
  test_readiness.py               26 — readiness scorer
  test_drift.py                   17 — drift detection
  test_reproducibility.py          3 — deterministic doc generation
  test_bootstrap_service_schemas.py 90 — bootstrap + service schemas
  test_cloudinit_templates.py     62 — Cloud-Init snippet generation + consistency
  test_suggest_names.py           50 — naming convention + KeePass discovery
  test_roles.py                   80 — role catalog + consolidation modes
  test_backup.py                  50 — archive naming, encryption, listing
  test_container_schema.py        58 — container state + volume backup naming
```

### Doc-gen
```
doc-gen/engine.py               CLI — --mode bootstrap|recovery; loads external_backup
doc-gen/renderers/recovery_runbook.py   Recovery runbook with Step 0 (external backup retrieval)
doc-gen/drift.py                Field-level drift detection
doc-gen/readiness.py            Readiness scorer
doc-gen/dependencies.py         Dependency graph builder
```

---

## Test Commands

```
# Run all tests
py -3 tests/unit/test_schema_validation.py
py -3 tests/unit/test_bootstrap_service_schemas.py
py -3 tests/unit/test_cloudinit_templates.py
py -3 tests/unit/test_suggest_names.py
py -3 tests/unit/test_roles.py
py -3 tests/unit/test_backup.py
py -3 tests/unit/test_container_schema.py

# Run doc-gen (verify it works end-to-end)
PYTHONIOENCODING=utf-8 py -3 doc-gen/engine.py --mode bootstrap --manifest tests/fixtures/tier1/manifest.json
PYTHONIOENCODING=utf-8 py -3 doc-gen/engine.py --mode recovery  --manifest tests/fixtures/tier2/manifest.json

# Preview naming convention
py -3 proxmox-bootstrap/suggest-names.py --hostname pve01 --kp-root Infrastructure --cidr 192.168.50.0/24

# Preview role catalog
py -3 proxmox-bootstrap/roles.py

# Show backup archive filename format
py -3 -c "
import sys; sys.path.insert(0,'proxmox-bootstrap')
import importlib.util
spec = importlib.util.spec_from_file_location('b','proxmox-bootstrap/backup.py')
b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)
print(b.archive_filename('proxmox-cell-a'))
"
```

---

## Design Constraints to Preserve

- `analyze.py` and `validate.py`: Python 3 stdlib only (no pip)
- ODS/ODT renderers: zipfile + XML only (no odfpy)
- doc-gen: runs without network access (all data from manifest)
- UNRESOLVED fields: never silently omitted
- Historical snapshots: reproducible (same manifest → same docs)
- **`cell_id` mandatory in all schemas (v5.0 AD-013)**
- **Secret Registry entries must include `owning_cell` field**
- **Network-config snippets are GENERATED — edit bootstrap-state, re-run generator**
- **User-data snippets are GENERATED — edit bootstrap-state, re-run generator**
