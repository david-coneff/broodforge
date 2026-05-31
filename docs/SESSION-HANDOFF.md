# Session Handoff

Date: 2026-05-31 21:15:00 UTC (2026-05-31 15:15:00 MDT)
Status: Ready to resume at Milestone 6.6 — Template Registry and Base Image Tracking

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
  Note: Tier 2 collector (6.5 item 3) deferred to Milestone 6.7

**Tests: 931 total, all passing**

---

## Next Action: Milestone 6.6 — Template Registry and Base Image Tracking

### What already exists

`bootstrap-state.json` already has `base_images` and `templates` arrays.
The bootstrap-state fixture has:
  - `base_images`: one entry (ubuntu-2204-base ISO, checksum, included_packages)
  - `templates`:   one entry (ubuntu-2204-base, proxmox_template_id=9000)

### Files to create

**1. `doc-gen/template_registry.py`** (new)

```python
class TemplateRegistry:
    def __init__(self, base_images: list, templates: list): ...
    def available(self) -> bool: ...          # True if either list is non-empty
    def base_image_count(self) -> int: ...
    def template_count(self) -> int: ...
    def get_base_image(self, name: str) -> Optional[dict]: ...
    def get_template(self, name: str) -> Optional[dict]: ...
    def all_base_images(self) -> list: ...
    def all_templates(self) -> list: ...
    def template_for_vmid(self, vmid, vm_list: list) -> Optional[dict]:
        """Look up the template used by a VM (via vm_list vm→template_name mapping)."""

def build_template_registry(manifest: dict) -> TemplateRegistry:
    """Read manifest["base_images"] and manifest["templates"]."""
```

**2. `doc-gen/engine.py`** — in `run_recovery()`, after provenance block:

```python
_base_images = bootstrap_state.get("base_images") or []
_templates   = bootstrap_state.get("templates") or []
if _base_images or _templates:
    manifest["base_images"] = _base_images
    manifest["templates"]   = _templates
    print(f"[doc-gen] Template registry: {len(_templates)} template(s), "
          f"{len(_base_images)} base image(s)")
else:
    print("[doc-gen] Template registry: not found in bootstrap-state")
```

**3. `doc-gen/readiness.py`** — add `_score_template_registry_completeness(manifest)`

ORANGE gap if `manifest.get("templates")` is empty/missing.
Rationale: without template registry, VM reconstruction requires manual base-image
research; ORANGE (same severity as secret registry — blocks automated reconstruction).

Add to `score_graph()` after provenance completeness line:
```python
registry_gaps += _score_template_registry_completeness(manifest)
```

**4. `doc-gen/renderers/recovery_runbook.py`**

Add **Appendix F — Template Registry** (same pattern as C/D/E):
- Lists all templates with their base_image, proxmox_template_id, created_at
- Lists all base_images with source_iso, checksum, included_packages

**5. `tests/unit/test_template_registry.py`** (new, ~35 tests)

Classes:
- `TestTemplateRegistryEmpty`         — available/count/get/all return correct defaults
- `TestTemplateRegistryData`          — get_base_image, get_template, template_for_vmid
- `TestLoadFromFixture`               — fixture has base_images + templates, verify structure
- `TestTemplateCompletenessScoring`   — ORANGE gap if templates missing, no gap if present
- `TestRunbookTemplateAppendix`       — Appendix F present, template names appear

### bootstrap-state fixture shape for reference

```json
"base_images": [{
  "name": "ubuntu-2204-base",
  "source_iso": "ubuntu-22.04.4-live-server-amd64.iso",
  "source_url": "https://releases.ubuntu.com/...",
  "checksum": "sha256:45f873...",
  "created_at": "2026-04-01T10:00:00Z",
  "included_packages": ["python3", "qemu-guest-agent", "openssh-server", "cloud-init"],
  "notes": null
}],
"templates": [{
  "name": "ubuntu-2204-base",
  "base_image": "ubuntu-2204-base",
  "proxmox_template_id": 9000,
  "created_at": "2026-04-01T11:00:00Z",
  "additional_packages": [],
  "build_notes": "..."
}]
```

### Important rules

- ORANGE for missing template registry (same as secret registry) per ROADMAP.md 6.6
- Follow the exact same pattern as `registries.py` and `provenance.py`
- TemplateRegistry.available() → True if EITHER base_images OR templates is non-empty
- After 6.6: update test_registries.py test that injects all registries to also inject
  base_images and templates in manifest

---

## Key Files

  doc-gen/registries.py         SecretRegistry + DnsRegistry
  doc-gen/provenance.py         ProvenanceRegistry
  doc-gen/template_registry.py  TO CREATE — 6.6
  doc-gen/readiness.py          _score_registry_completeness, _score_provenance_completeness
                                 registry_gaps list (both registry + provenance gaps)
  doc-gen/engine.py             Injects secret_registry, dns_registry, provenance_registry
                                 TO ADD: base_images, templates injection
  tests/fixtures/bootstrap/bootstrap-state.json   canonical fixture (base_images + templates present)
  tests/unit/test_registries.py    75 tests (6.3 + 6.4)
  tests/unit/test_provenance.py    44 tests (6.5)
  tests/unit/test_template_registry.py   TO CREATE (6.6)

## Design Constraints

  - stdlib only in planners/generators/validators (no pip)
  - cell_id mandatory on all schema documents
  - Metadata files are never generated
  - Generated artifacts are never the source of truth
  - POPULATE: markers = documentation coverage gaps
  - Filenames: YYYY-MM-DD_HH_MM_SS (UTC, underscores)
  - Documents: YYYY-MM-DD HH:MM:SS UTC (HH:MM:SS MDT)
