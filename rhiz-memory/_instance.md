# rhiz-memory — Broodforge Instance

**Protocol**: david-coneff/rhizome  
**Instance type**: Child repository  
**Project**: Broodforge — self-managing infrastructure platform

---

## Session startup

When starting a session on broodforge under the Rhizome methodology:

1. `david-coneff/rhizome` — `rhizome/core/rhiz-core.md` (always loaded)
2. `david-coneff/rhizome` — `rhizome/core/rhiz-core.manifest.yaml` (select modules for task)
3. `rhiz-memory/_instance.md` (this file — project identity + startup)
4. `rhiz-memory/state/SESSION_HANDOFF.md` (current work context and next action)

The Rhizome protocol specs live entirely in `david-coneff/rhizome`. Do not
read the `pap/` directory in this repo — it is a stale embedded copy of an
old version of Rhizome and is scheduled for deletion (see §Legacy cleanup
below).

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
platform’s own resource-provisioning and deployment-strategy decisions for
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

---

## Memory structure

| Category | Location |
|---|---|
| Governance | `rhiz-memory/_instance.md` (this file) |
| Decisions | `rhiz-memory/state/decisions.md` |
| Evidence | Cited inline in audit records and session handoffs |
| Planning | `rhiz-memory/state/SESSION_HANDOFF.md`, `ROADMAP.md` |
| State | `rhiz-memory/state/SESSION_HANDOFF.md`, `rhiz-memory/state/RESUME_BLOCK.md` |
| Risk | `rhiz-memory/audits/` (audit finding registers) |
| Debt | Named inline in audit findings |
| Research | `rhiz-memory/audits/` |
| Assumptions | Named inline where made; no separate assumption log yet |
| Contracts | `manifest.json` schema; `pyproject.toml`; `schemas/` |
| Testing | `tests/`, `tests/unit/` |
| Dependencies | `pyproject.toml`; `ansible/requirements.yml` |
| Documentation | `README.md`, `ARCHITECTURE.md`, `docs/` |
| Oversight | `rhiz-memory/audits/` |

---

## Legacy cleanup (pending)

The following directories predate the current architecture and should be
deleted once their content is confirmed migrated:

| Directory | What it is | Action |
|-----------|-----------|--------|
| `pap/` | Full embedded copy of old PAP protocol (rhizome predecessor). Stale — canonical protocol is now `david-coneff/rhizome`. | **Delete** — nothing in this dir belongs in broodforge |
| `.ai/` | Pre-rhizome AI governance files (bootstrap, state, decisions, audits). Superseded by `rhiz-memory/`. | **Migrate then delete** — `decisions.md` → `rhiz-memory/state/decisions.md`; audit files → `rhiz-memory/audits/`; bootstrap → this file |
| `.audit/` | Empty placeholder directory | **Delete** |

Until cleanup is complete, treat `.ai/decisions.md` and `.ai/CURRENT_STATE.md`
as the authoritative state documents — they have not yet been migrated to
`rhiz-memory/state/`.
