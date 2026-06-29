# rhiz-memory — Broodforge Instance

**Protocol**: david-coneff/rhizome  
**Instance type**: Child repository  
**Project**: Broodforge — self-managing infrastructure platform

---

## Session startup

When starting a session on broodforge under the Rhizome methodology:

1. `david-coneff/rhizome` — `protocol/core/rhiz-core.md` (always loaded)
2. `david-coneff/rhizome` — `protocol/core/rhiz-core.manifest.yaml` (select modules for task)
3. `rhiz-memory/_instance.md` (this file — project identity + startup)
4. [`rhiz-memory/state/SESSION_HANDOFF.md`](state/SESSION_HANDOFF.md) (current work
   context and next action; portable save-state in
   [`state/RESUME_BLOCK.md`](state/RESUME_BLOCK.md))

The Rhizome protocol specs live entirely in `david-coneff/rhizome`. This repo
references them through the `tools-stable` channel (see Executable tooling below)
and never copies them — per rhiz-child-repo-convention
(`david-coneff/rhizome` → `protocol/docs/rhiz-child-repo-convention.md`) §1.

---

## Project identity and sovereign governance

Broodforge is a **self-managing infrastructure platform** for home-lab
Proxmox + k3s environments. It covers the full lifecycle:
hardware assessment → cell forging → node spawning → phoenix recovery →
continuous health monitoring → autonomous remediation.

### Project Charter (sovereign — outranks Rhizome protocol on project matters)

Broodforge:

**SHALL:**
- Collect facts
- Normalize facts
- Generate reports
- Track historical changes

**SHALL NOT:**
- Recommend upgrades, purchases, or replacements
- Make subjective judgments about specific hardware products

*Scope note*: the SHALL NOT items cover specific-hardware recommendations
requiring granular product/pricing knowledge. They do not constrain the
platform's own resource-provisioning and deployment-strategy decisions for
infrastructure it already manages — those are a function of its chartered
deployment strategy (see decisions.md AD-013, AD-014, AD-032, AD-034).

### Design principles

1. Facts over opinions.
2. No secrets stored by the engine.
3. Assessment outputs are private.
4. Source code is public-safe.
5. All reports derive from normalized schemas.
6. Historical tracking is a first-class feature.

---

## Architecture summary

**Architecture version**: v7.1  
**Model**: Seventeen-state model. Six-layer lifecycle. Three assessment tiers. Five dependency graphs.

### Six lifecycle phases

1. **Forge** — hardware assessment → forge-manifest.json → forge package → Proxmox + k3s base
2. **Spawn** — hatchery plans new broodling nodes → spawn package → bare-metal k3s join
3. **Phoenix** — full or partial cell recovery from phoenix playbook + KeePass-gated scripts
4. **Assess** — Tier 1/2/3 collectors feed bootstrap-state.json; readiness scorer (ACS/RRS/DCS/CRS/OSS)
5. **Monitor** — continuous assessment, security scanning, capacity model, drift detection
6. **Remediate** — autonomous remediation engine with planner → queue → executor → policy loop

### Codebase structure

| Area | Directories | Status |
|------|-------------|--------|
| Legacy pae CLI | `engine/`, `collector/`, `schemas/`, root-level `tests/` | Complete at v0.8. **Do not modify unless explicitly instructed.** |
| Doc-gen architecture | `assessment/`, `doc-gen/`, `data-model/`, `tests/unit/` | Active development — all new work goes here |
| Infrastructure | `ansible/`, `proxmox-bootstrap/`, `scripts/`, `config/` | Active |

### Key design constraints

- `manifest.json` is the contract between assessment layer and doc-gen layer
- doc-gen never reads raw collector files directly
- Field classification: AUTO / DERIVED / HUMAN / UNRESOLVED
- UNRESOLVED fields are never silently omitted (reason + guidance + impact always present)
- All HTML output is self-contained dark-theme (no external dependencies)
- Tier 1 assessment uses Python 3 stdlib only (no pip installs)
- Historical snapshots must be reproducible (same manifest → same docs)
- Autonomous remediation requires explicit opt-in + policy gate
- KeePass-gated actions require `keepass_unlocked = True`
- Every machine-readable manifest has a human-readable HTML counterpart (AD-047)
- **AD-060 (binding on all future development):** No autonomous pathway may read
  and wield full root credentials against live hypervisors. Two named exceptions:
  node spawning (Cloud-Init) and phoenix setup (temporary session credential,
  operator must rotate after session completes).

---

## Memory structure

Per rhiz-State §2 (`david-coneff/rhizome` → `protocol/modules/rhiz-state/rhiz-state.md`),
the fourteen memory categories and where each is addressed in this repo:

| Category | Location |
|---|---|
| Decisions | [`rhiz-memory/state/decisions.md`](state/decisions.md); project governance in this `_instance.md` |
| Evidence | Cited inline in audit records and session handoffs |
| Planning | [`rhiz-memory/state/SESSION_HANDOFF.md`](state/SESSION_HANDOFF.md), `ROADMAP.md` |
| State | [`rhiz-memory/state/SESSION_HANDOFF.md`](state/SESSION_HANDOFF.md), [`rhiz-memory/state/RESUME_BLOCK.md`](state/RESUME_BLOCK.md) |
| Risk | [`rhiz-memory/audits/`](audits/index.md) (audit finding registers) |
| Debt | Named inline in audit findings |
| Research | [`rhiz-memory/audits/`](audits/index.md) |
| Assumptions | Named inline where made; no separate assumption log yet |
| Contracts | `manifest.json` schema; `pyproject.toml`; `schemas/`; the `tools/rhiz.py` channel bootstrap |
| Testing | `tests/`, `tests/unit/` |
| Dependencies | `pyproject.toml`; `ansible/requirements.yml`; rhiz tooling via the `tools-stable` channel |
| Documentation | `README.md`, `ARCHITECTURE.md`, `docs/` |
| Oversight | [`rhiz-memory/audits/`](audits/index.md) |
| Failure Paths | Per-finding root causes recorded in the audit records under [`rhiz-memory/audits/`](audits/index.md) |

---

## Executable tooling

Broodforge resolves rhizome's tooling (`rhiz-lint`, `rhiz-search`, `doc-graph`)
through the shared **`tools-stable`** channel — referenced, never copied — per
rhiz-child-repo-convention §1.1:

- `tools/rhiz.py` — the stable bootstrap shim. It resolves
  `david-coneff/rhizome@tools-stable` into a gitignored `.rhiz-tools/` cache and
  forwards a subcommand (`lint`, `search`, `docs`, `verify`, `maintain`) with this
  repo as `--root`. Locally, `RHIZ_TOOLS_PATH=<sibling rhizome> python3 tools/rhiz.py lint`
  runs auth-free.
- `.rhiz-lint.json` — this repo's layout (`knowledge_roots: rhiz-memory`;
  `entry_points: README.md`, `rhiz-memory/_instance.md`). The methodology layer is
  linted; product docs (`docs/`, `proxmox-bootstrap/`, …) keep their own indexes.
- `.github/workflows/rhiz-maintain.yml` — the mechanical maintenance loop in CI.
  The rhizome-checkout `token:` line ships commented; `RHIZOME_TOOLS_TOKEN` is only
  needed if rhizome goes private (`david-coneff/rhizome` → `protocol/docs/tooling-access.md`).

## Provenance

Broodforge predates the current convention: it carried an embedded `pap/` protocol
copy (PAP, Rhizome's predecessor), retired 2026-06-17 when the memory layer moved
under `rhiz-memory/`. Migrated to the present Rhizome methodology 2026-06-29:
session-startup paths repointed from the old `rhizome/core/...` to `protocol/core/...`
(the B-series rename), the loose `audits/` records given a discoverable
[`index.md`](audits/index.md), stale `pap/...` links in `README.md` repointed, and
the executable-tooling channel wired up (above). The historical PAP-AUDIT records
keep their original names and provenance notes unchanged.
