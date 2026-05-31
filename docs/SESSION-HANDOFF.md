# Session Handoff

Date: 2026-05-31 20:45:00 UTC (2026-05-31 14:45:00 MDT)
Status: Ready to resume at Milestone 6.5 — Deployment Provenance

---

## Active Architecture: v7.0

Self-Documenting, Self-Assessing, Self-Recovering Infrastructure Platform.
k3s + Flux CD + Proxmox + four intelligence layers.
Full review: docs/ARCHITECTURE-REVIEW-v7.md | Roadmap: ROADMAP.md (12-phase)

---

## Completed This Project

### Phase 0 — Metadata Model
  proxmox-bootstrap/metadata/     Ten Tier 1 YAML files (human-authored, never generated)
  cell-identity, hardware-profile, network-topology, vm-roles, k3s-cluster,
  service-catalog, backup-policy, recovery-priority, placement-policy, naming-convention

### Phase 1 — Bootstrap Intelligence
  proxmox-bootstrap/discovery/discover.py         4 collectors (hardware/network/storage/proxmox)
  proxmox-bootstrap/planners/cluster_planner.py   k3s topology
  proxmox-bootstrap/planners/storage_planner.py   ZFS pool topology
  proxmox-bootstrap/planners/network_planner.py   Validates declared vs discovered
  proxmox-bootstrap/planners/naming_planner.py    All VM names, IPs, KeePass paths, DNS, repos
  proxmox-bootstrap/validation/capacity_validator.py   Hardware gate
  proxmox-bootstrap/validation/readiness_validator.py  Final gate before generators

### Phase 2 — Generators
  proxmox-bootstrap/generators/tofu-vars.py              plans/ → opentofu/
  proxmox-bootstrap/generators/cloud-init-gen.py         plans/ → snippets/
  proxmox-bootstrap/generators/ansible-inventory-gen.py  plans/ → ansible/inventory/
  proxmox-bootstrap/generators/k3s-config-gen.py         plans/ → ansible/roles/k3s-server/files/
  proxmox-bootstrap/generators/flux-bootstrap-gen.py     plans/ + metadata/ → scripts/

### Phase 3 — Ansible Roles
  ansible/group_vars/all.yaml
  ansible/roles/{common,forgejo,operations-vm,k3s-server}/
  ansible/playbooks/01-common.yaml  02-forgejo.yaml  03-operations.yaml  04-k3s.yaml

### Milestone 6.3 — Secret Registry
  proxmox-bootstrap/secret-registry.yaml         11 entries, owning_cell, KeePass paths
  doc-gen/registries.py::SecretRegistry          by-id, by-component lookups
  doc-gen/readiness.py                           ORANGE gap: secret registry missing
  doc-gen/renderers/recovery_runbook.py          "Secrets Required for Recovery" section + Appendix D
  ReadinessReport.registry_gaps                  new field

### Milestone 6.4 — DNS Registry
  proxmox-bootstrap/dns-registry.yaml            5 entries (host + 4 VMs)
  doc-gen/registries.py::DnsRegistry             by-vmid, by-hostname, by-role lookups
  doc-gen/readiness.py                           YELLOW gap: DNS registry missing
  doc-gen/renderers/recovery_runbook.py          _resolve_vm_ip() replaces [VM_IP] + Appendix C

**Tests: 887 total, all passing**

---

## Next Action: Milestone 6.5 — Deployment Provenance

Implement per-VM provenance tracking in the doc-gen pipeline.

### What provenance records already look like

`bootstrap-state.json` already has a `provenance_records` array. One record exists
in the fixture (tests/fixtures/bootstrap/bootstrap-state.json) for forgejo (vmid=101):

```json
{
  "vmid": 101,
  "name": "forgejo",
  "deployed_at": "2026-04-15T12:00:00Z",
  "tofu_workspace": "proxmox-vms",
  "tofu_commit": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
  "template_name": "ubuntu-2204-base",
  "template_checksum": "sha256:45f873...",
  "cloudinit_user_data_hash": "sha256:aabbcc...",
  "cloudinit_network_config_hash": "sha256:ddeeff...",
  "ansible_playbook": "site.yml",
  "ansible_commit": "b2c3d4e5f6...",
  "ansible_inventory_commit": "c3d4e5f6...",
  "deployed_by": "dave",
  "notes": null
}
```

VMs 100, 102, 103 (infra-bootstrap, inventory, assessment-engine) have **no** provenance
record — this is intentional. They should trigger YELLOW gaps in the readiness scorer.

### Files to create

**1. `doc-gen/provenance.py`** (new)

```python
class ProvenanceRegistry:
    def __init__(self, records: list):
        ...
    def available(self) -> bool: ...
    def count(self) -> int: ...
    def for_vmid(self, vmid) -> Optional[dict]: ...     # exact match on vmid field
    def for_name(self, name: str) -> Optional[dict]:   # exact match on name field
    def all(self) -> list: ...
    def coverage(self, vmids: list) -> dict:
        """Return {vmid: record_or_None} for every vmid in the list."""
```

No file I/O in the class. Loading functions:
```python
def build_provenance_registry(manifest: dict) -> ProvenanceRegistry:
    """Read manifest["provenance_registry"] (list injected by engine.py)."""
```

### Files to modify

**2. `doc-gen/engine.py`** — in `run_recovery()`, after the DNS registry block:

```python
_prov = bootstrap_state.get("provenance_records") or []
if _prov:
    manifest["provenance_registry"] = _prov
    print(f"[doc-gen] Provenance registry: {len(_prov)} record(s)")
else:
    print("[doc-gen] Provenance registry: not found in bootstrap-state")
```

**3. `doc-gen/readiness.py`** — add `_score_provenance_completeness(graph, manifest)`

Called at the end of `score_graph()`, same pattern as `_score_registry_completeness()`.
Add the returned gaps to `ReadinessReport.registry_gaps` (reuse the same list — it's
the "infrastructure completeness gaps" list, not just for registries).

Logic: for every VM node in the graph, check if provenance_registry has a record for
that vmid. If not: YELLOW gap with `gap_type="MISSING_PROVENANCE"`.

```python
def _score_provenance_completeness(graph, manifest: dict) -> list:
    prov_reg = manifest.get("provenance_registry") or []
    by_vmid = {r.get("vmid"): r for r in prov_reg if r.get("vmid") is not None}
    gaps = []
    for node in graph.nodes:
        if node.type != "vm":
            continue
        vmid = node.metadata.get("vmid")
        if vmid is not None and int(vmid) not in by_vmid:
            gaps.append(Gap(
                component_id=node.id,
                gap_type="MISSING_PROVENANCE",
                severity="YELLOW",
                description=f"No provenance record for {node.label} (vmid={vmid})",
                remediation="Record tofu workspace, ansible commit, and cloud-init hash after deployment",
                readiness_impact="Cannot verify deployed state matches repository; reconstruction may diverge",
            ))
    return gaps
```

In `score_graph()`, call this after `_score_registry_completeness()` and extend
`registry_gaps` with the result:

```python
registry_gaps = _score_registry_completeness(manifest)
registry_gaps += _score_provenance_completeness(graph, manifest)
```

**4. `doc-gen/renderers/recovery_runbook.py`** — in the per-VM restore loop

After the "Backup info" block for VM nodes, add a provenance block:

```python
prov_reg = manifest.get("provenance_registry") or []
prov = next((r for r in prov_reg
             if r.get("vmid") == node.metadata.get("vmid")), None)
if prov:
    rb.h3(f"Deployment Provenance: {node.label}")
    rb.field("Deployed at",       prov.get("deployed_at", "unknown"), "AUTO", "")
    rb.field("OpenTofu workspace", prov.get("tofu_workspace", "unknown"), "AUTO", "")
    rb.field("OpenTofu commit",   prov.get("tofu_commit", "unknown")[:12] + "...", "AUTO", "")
    rb.field("Ansible commit",    prov.get("ansible_commit", "unknown")[:12] + "...", "AUTO", "")
    rb.field("Template",          prov.get("template_name", "unknown"), "AUTO", "")
    rb.field("Cloud-Init hash",   prov.get("cloudinit_user_data_hash", "unknown")[:20] + "...", "AUTO",
             "Compare against current snippet to verify parity")
    rb.note("Verify reconstruction matches this provenance record before closing the incident.")
else:
    rb.field("Deployment provenance", "NOT RECORDED", "UNRESOLVED",
             "No provenance record found — cannot verify reconstruction matches original deployment")
```

Also add **Appendix E — Deployment Provenance** (same pattern as Appendix C/D).

### Files to create

**5. `tests/unit/test_provenance.py`** (new)

Target ~35 tests across:
- `TestProvenanceRegistryEmpty` — available/count/for_vmid/for_name return correct defaults
- `TestProvenanceRegistryData` — lookups by vmid, by name, coverage()
- `TestLoadFromFixture` — fixture has correct shape, for_vmid(101) returns forgejo record,
  for_vmid(100/102/103) returns None
- `TestProvenanceCompletenessScoring` — _score_provenance_completeness():
    - all VMs have records → no gaps
    - some VMs missing → YELLOW gaps for those VMs
    - gap_type is MISSING_PROVENANCE
    - nodes of type != "vm" are not checked (host, storage, network nodes)
- `TestRunbookProvenanceSection` — rendered ODT contains provenance fields when record present,
    shows "NOT RECORDED" when absent, Appendix E present

### Important implementation rules

- Provenance is YELLOW (not ORANGE) per ROADMAP.md 6.5
- ProvenanceRegistry class must match the pattern in doc-gen/registries.py:
  `.available()`, `.count()`, `.all()` returning list copies
- ODT content in tests: use the `_odt_text(odt_bytes)` helper pattern from
  tests/unit/test_registries.py (unzip, read all XML files as text)
- `manifest["provenance_registry"]` key convention (engine.py injects it)
- Node.metadata["vmid"] is an int; prov record "vmid" is also int; be consistent

---

## File Map

```
doc-gen/
  engine.py              Modified: inject provenance_registry into manifest
  readiness.py           Modified: _score_provenance_completeness(), extend registry_gaps
  registries.py          Unchanged (SecretRegistry + DnsRegistry — 6.3/6.4)
  provenance.py          CREATE: ProvenanceRegistry class + build_provenance_registry()
  renderers/
    recovery_runbook.py  Modified: per-VM provenance block + Appendix E
    recovery_workbook.py No changes needed for 6.5
tests/unit/
  test_provenance.py     CREATE: ~35 tests
  test_registries.py     Unchanged (75 tests — 6.3/6.4)
tests/fixtures/bootstrap/
  bootstrap-state.json   Unchanged (already has provenance_records for vmid=101)
```

---

## How to run tests

```
py -3 tests/unit/test_provenance.py
```

Run the full suite to confirm no regressions:
```
for f in tests/unit/test_*.py; do py -3 "$f" 2>&1 | grep -E "^(OK|FAIL|Ran)"; done
```

Expected: 17 test files, all OK. New total will be ~920+ tests.

---

## Key Architecture Rules

- stdlib only in planners/generators/validators (no pip)
- cell_id mandatory on all schema documents (AD-013)
- Metadata files are never generated (Tier 1 = human-authored only)
- Generated artifacts are never the source of truth
- POPULATE: markers = documentation coverage gaps
- Filenames: YYYY-MM-DD_HH_MM_SS (UTC, underscores)
- Documents: YYYY-MM-DD HH:MM:SS UTC (HH:MM:SS MDT)
- doc-gen registries/provenance: load from manifest keys injected by engine.py;
  fall back to file sources only as secondary option
