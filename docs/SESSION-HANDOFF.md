# Session Handoff

Date: 2026-05-31 22:30:00 UTC (2026-05-31 16:30:00 MDT)
Status: Ready to resume at Milestone 6.7 — Tier 2 Collector (deferred from 6.5)

---

## Active Architecture: v7.0

Self-Documenting, Self-Assessing, Self-Recovering Infrastructure Platform.
k3s + Flux CD + Proxmox + four intelligence layers.
Full review: docs/ARCHITECTURE-REVIEW-v7.md | Roadmap: ROADMAP.md (12-phase)

---

## Completed This Project

### Phases 0–3 (proxmox-bootstrap + ansible)
See ROADMAP.md for full detail. All complete.

### Milestone 6.1 — Bootstrap State Schema
  data-model/bootstrap-state-schema.json   Full schema: Cloud-Init, templates, provenance,
                                            secrets, DNS, service contracts, hardware
  data-model/service-state-schema.json     Service state schema
  tests/unit/test_bootstrap_service_schemas.py   90 tests

### Milestone 6.2 — Cloud-Init Template Library
  proxmox-bootstrap/snippets/              user-data/, network-config/, vendor-data/
  proxmox-bootstrap/generate-network-configs.py   generator
  proxmox-bootstrap/generate-user-data.py          generator
  proxmox-bootstrap/SNIPPET-UPLOAD.md              upload procedure
  tests/unit/test_cloudinit_templates.py           62 tests

### Milestone 6.3 — Secret Registry
  proxmox-bootstrap/secret-registry.yaml   11 entries, owning_cell, KeePass paths
  doc-gen/registries.py::SecretRegistry    by-id, by-component lookups
  doc-gen/readiness.py                     ORANGE gap: secret registry missing
  doc-gen/renderers/recovery_runbook.py    "Secrets Required for Recovery" + Appendix D

### Milestone 6.4 — DNS Registry
  proxmox-bootstrap/dns-registry.yaml      5 entries (host + 4 VMs)
  doc-gen/registries.py::DnsRegistry       by-vmid, by-hostname lookups
  doc-gen/readiness.py                     YELLOW gap: DNS registry missing
  doc-gen/renderers/recovery_runbook.py    _resolve_vm_ip() + Appendix C

### Milestone 6.5 — Deployment Provenance (complete, except Tier 2 collector)
  doc-gen/provenance.py                    ProvenanceRegistry class (by-vmid, by-name, coverage())
  doc-gen/engine.py                        Injects provenance_registry from bootstrap-state.json
  doc-gen/readiness.py                     _score_provenance_completeness() — YELLOW per missing VM
                                           registry_gaps list contains both registry + provenance gaps
  doc-gen/renderers/recovery_runbook.py    Per-VM provenance block + Appendix E
  tests/unit/test_provenance.py            44 tests
  Note: Tier 2 collector (6.5 item 3) deferred → this is Milestone 6.7

### Milestone 6.6 — Template Registry and Base Image Tracking (complete)
  doc-gen/template_registry.py             TemplateRegistry class (get_base_image, get_template,
                                           template_for_vmid, available, counts, all_*)
  doc-gen/engine.py                        Injects base_images + templates from bootstrap-state.json
  doc-gen/readiness.py                     _score_template_registry_completeness() — ORANGE if missing
  doc-gen/renderers/recovery_runbook.py    Appendix F — Template Registry
  tests/unit/test_template_registry.py     56 tests
  tests/unit/test_registries.py            Updated 2 tests to also inject templates

**Tests: 987 total, all passing**

---

## Next Action: Milestone 6.7 — Tier 2 Collector

This milestone was deferred from 6.5 (item 3). It adds a shell/Python collector
that SSHs into Proxmox and populates provenance_records, base_images, and templates
in bootstrap-state.json by reading live system state.

### Background

The doc-gen engine already consumes provenance_records, base_images, and templates
from bootstrap-state.json. The Tier 2 collector's job is to *generate* those arrays
by inspecting the live Proxmox host — without requiring the operator to hand-populate them.

### Scope of 6.7

**1. `proxmox-bootstrap/collect-tier2.py`** (new)

A standalone Python script (stdlib only) that:
- SSHs into Proxmox using paramiko or subprocess+ssh (subprocess preferred for stdlib compliance)
- Runs `qm list`, `qm config <vmid>`, `pvesm status`, `pveversion` to enumerate state
- Populates:
  - `provenance_records` — one entry per VMID with vmid, name, deployed_at (stat mtime), template_name
  - `templates` — one entry per template VMID (templates have `template: 1` in qm config)
  - `base_images` — derived from template source_iso if discoverable via qm config notes or description
- Writes results to bootstrap-state.json (merges, does not replace existing manual entries)
- Flag: `--dry-run` prints what would be written without modifying bootstrap-state.json

**2. `proxmox-bootstrap/TIER2-COLLECTION.md`** (new)

Procedure for running the Tier 2 collector, what credentials are needed,
and how to verify output.

**3. `tests/unit/test_tier2_collector.py`** (new, ~30 tests)

- TestCollectorParsing — unit tests for each parse function with mock qm output
- TestDryRun — verify --dry-run produces correct JSON to stdout without modifying file
- TestMergeLogic — existing entries not overwritten when already populated

### Design constraints

- stdlib only (no pip dependencies in proxmox-bootstrap/ scripts)
- SSH via subprocess (avoids paramiko dependency)
- Must not overwrite existing manually-entered provenance fields
- ROADMAP.md says this milestone is YELLOW until at least one live collection run succeeds

### Key files for context

  proxmox-bootstrap/bootstrap-state.json schema:
    provenance_records[].vmid, name, deployed_at, tofu_workspace, tofu_commit,
                          template_name, cloudinit_user_data_hash, etc.
    templates[].name, base_image, proxmox_template_id, created_at, additional_packages
    base_images[].name, source_iso, checksum, created_at, included_packages

  doc-gen/template_registry.py    TemplateRegistry — consumer of these arrays
  doc-gen/provenance.py           ProvenanceRegistry — consumer of provenance_records
  tests/fixtures/bootstrap/bootstrap-state.json   canonical fixture with all arrays

---

## Key Files

  doc-gen/registries.py             SecretRegistry + DnsRegistry
  doc-gen/provenance.py             ProvenanceRegistry
  doc-gen/template_registry.py      TemplateRegistry (6.6 complete)
  doc-gen/readiness.py              _score_registry_completeness, _score_provenance_completeness,
                                     _score_template_registry_completeness
                                     registry_gaps list (all registry + provenance gaps)
  doc-gen/engine.py                 Injects: secret_registry, dns_registry, provenance_registry,
                                     base_images, templates
  tests/fixtures/bootstrap/bootstrap-state.json   canonical fixture
  tests/unit/test_registries.py     75 tests (6.3 + 6.4)
  tests/unit/test_provenance.py     44 tests (6.5)
  tests/unit/test_template_registry.py   56 tests (6.6)

## Design Constraints

  - stdlib only in planners/generators/validators (no pip)
  - cell_id mandatory on all schema documents
  - Metadata files are never generated
  - Generated artifacts are never the source of truth
  - POPULATE: markers = documentation coverage gaps
  - Filenames: YYYY-MM-DD_HH_MM_SS (UTC, underscores)
  - Documents: YYYY-MM-DD HH:MM:SS UTC (HH:MM:SS MDT)
