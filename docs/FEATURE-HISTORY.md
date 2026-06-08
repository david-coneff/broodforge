# Broodforge Feature & Design-Intent History

**Trailing history of features and design intents** requested over time, newest cycle
last. Each entry records its **origin** (USER-REQUESTED vs. GAP-FILL — devised to fill
an under-specified idea), **status**, and **verification depth**:

- `static` — grep/pattern checks only
- `cli-probe` — `--help` / flag-existence checks
- `smoke` — ran the code path with synthetic/mocked inputs
- `unit` — covered by the pytest suite
- `deep-arch` — full execution pathway traced for gaps
- `user-tested` — confirmed by a real user on hardware (record version + feedback)

Timestamps are `YYYY-MM-DD_HH_MM_SS` UTC.

---

**Cycle: 2026-06-04_12_37_46 UTC**

## Interactive HTML documentation toolkit (`proxmox-bootstrap/md_to_html.py`)

| Feature | Origin | Status | Verification |
|---|---|---|---|
| Markdown → themed self-contained HTML | GAP-FILL (README/ROADMAP/etc. needed HTML twins) | Implemented | smoke (structure asserts on every generated doc) |
| Light/dark theme toggle (persisted) | USER-REQUESTED | Implemented | smoke (toggle + `body.light` present in output) |
| Per-code-block Copy buttons | USER-REQUESTED | Implemented | smoke |
| Live-templated commands (`{{VAR}}` → Parameters panel, live rewrite) | USER-REQUESTED | Implemented | smoke (param inputs + `.tpl` slots in drill HTML) |
| Note fields (`@field`/`@area`) + auto Session Notes | USER-REQUESTED | Implemented | smoke |
| File **Attachments** + **Export** to timestamped ZIP (`Title_YYYY_MM_DD_HH_MM_SS.zip`) | USER-REQUESTED | Implemented | smoke + **format-validated**: ported the JS CRC32/ZIP builder to Python and confirmed `zipfile` reads + CRC-checks the output |
| Theme toggle injected into hand-authored HTML (`inject_html_theme.py`) | GAP-FILL | Implemented | smoke (markers + balanced tags) |
| `--collapsible` (## sections → `<details>`) | GAP-FILL (FEATURE-HISTORY needs collapsible per memory) | Implemented | smoke |

> **Not yet user-tested.** The export/attachments + live-template UX has only been
> validated structurally and (for the ZIP) by format round-trip. A real browser test
> by the user would raise confidence to `user-tested`.

## Forge / spawn / phoenix workflow completeness (audit-driven)

| Feature | Origin | Status | Verification |
|---|---|---|---|
| Forge package self-bundles library code | GAP-FILL (docs implied it) | Implemented | smoke (tarball contents) + unit |
| Dashboard secret redaction on unauth GET | GAP-FILL (security) | Implemented | smoke (mask + non-mutation) + unit |
| `validate-spawn.py` conflict re-validator CLI + bundling | GAP-FILL | Implemented | smoke (collision→exit1, clean→exit0) |
| Phoenix playbook generation entry point (`phoenix-planner --state`) | GAP-FILL (missing step) | Implemented | smoke (generate→assemble→package) |
| `engine.py --set-timezone` (AD-045) | USER-REQUESTED (architecture decision) | Implemented | smoke |
| `spawn_hardware_discovery.py` CLI + sshpass password auth | GAP-FILL (documented step had no CLI) | Implemented | cli-probe + smoke (mocked runner) |
| `setup_ddns.py` CLI (both forge + manual forms) | GAP-FILL | Implemented | smoke (both forms, units written) |
| `init-bootstrap-state.py` manifest-seeded non-interactive init | GAP-FILL (would hang forge.sh) | Implemented | smoke (stdin-closed, seeded) |
| `setup_dnsmasq/headscale/tls.py` CLIs (forge phase-03) | GAP-FILL (were library-only no-ops) | Implemented | smoke (each writes a real config; dnsmasq `hostname` field bug also fixed) |
| Forge OpenTofu VM modules + Ansible inventory generation | GAP-FILL | **Not implemented** — deploy-to-hardware milestone | deep-arch (gap confirmed); documented in FORGING.md |

## Documentation integrity

| Feature | Origin | Status | Verification |
|---|---|---|---|
| All documented `python3` commands resolve + flags implemented | USER-REQUESTED (no broken steps) | Implemented | deep-arch (import-aware flag cross-reference: 0 mismatches) |
| Durable `DESIGN-HISTORY.md` replacing versioned review churn | USER-REQUESTED | Implemented | static |
| `AUDIT-FINDINGS.md` (this trailing audit log) | USER-REQUESTED | Implemented | n/a |
| `FEATURE-HISTORY.md` (+ collapsible HTML) | USER-REQUESTED | Implemented | n/a |

---

**Cycle: 2026-06-08_04_54_51 UTC**

## Security & documentation: MFA-by-default, collapsible roadmap

| Feature | Origin | Status | Verification |
|---|---|---|---|
| KeePass unlock gate now defaults to second-factor (`mfa_method` / `--mfa` default flips `"none"` → `"totp"`; AD-058) | USER-REQUESTED ("for high level functions of any kind, we should be requiring 2nd factor authentication as a default, not just a password") | Implemented | unit (`test_keepass_mfa.py`, 49 passed; `test_mfa_method_field_default` updated to assert `"totp"`) |
| MFA method constrained to authenticator-app TOTP or YubiKey only — SMS/email OTP deliberately never offered | USER-REQUESTED ("the 2nd factor method should be limited to TOTP-authenticator or yubikey, not SMS based TOTP or email-based TOTP since this have greater vulnerability to being hacked") | Implemented (pre-existing `keepass_mfa.py` already had no SMS/email path; default flip + AD-058 make the constraint the documented baseline) | unit + static (grep confirms no SMS/email OTP code path exists anywhere in `keepass_mfa.py` / `forge_keepass_init.py`) |

---

**Cycle: 2026-06-08_12_36_41 UTC**

## AD-058 follow-up: MFA method now seen and confirmed at forge time (guided-setup gap closed)

The prior cycle named one open gap: the `"totp"` MFA default was *inherited
silently* — `guided_setup.py`/`forge_planner.py` didn't surface it for operator
confirmation. This cycle closes that gap end-to-end (guided setup → forge
manifest → KeePass init), completing work a prior session had left mid-flight
(uncommitted edits found already started in the working tree on resume).

| Feature | Origin | Status | Verification |
|---|---|---|---|
| `security.mfa_method` added to the guided-setup `security` group (suggest → `"totp"`; `check_conflicts` validates against `{none, totp, yubikey}`, rejects SMS/email-style values, warns on `"none"` as an explicit AD-058 opt-out) | GAP-FILL (closes the named AD-058 follow-up — "seen and confirmed," not silently inherited) | Implemented | unit (`test_guided_setup.py`: suggest + 4 new `check_conflicts` cases) |
| `build_forge_manifest()` writes `keepass_config.mfa_method` from the guided session's `security.mfa_method` choice when present, else the `"totp"` default | GAP-FILL | Implemented | unit (`test_forge_planner.py::test_mfa_method_defaults_to_totp`, `::test_mfa_method_from_guided_session`) |
| `generate_keepass_init_config()` reads `forge_manifest["keepass_config"]["mfa_method"]` and threads it into the returned `KeePassInitConfig` (was computed but not wired through — completed the in-flight edit) | GAP-FILL | Implemented | unit (full `keepass`/`mfa`/`forge_planner`/`guided_setup` sweep: 363 passed) |
| Fixed `verify_trust()` (`federation_state.py`) comparing `relationship.is_expired` (real wall-clock `datetime.now()`) against an injected `now_fn` — caused `test_phase19_federation.py::test_expiring_soon_still_valid` to flip red the moment real UTC time passed the fixture's fixed "soon" expiry date | GAP-FILL (latent bug surfaced by the calendar advancing past the test's fixed fixture date — same class of issue PAP/audit work has repeatedly flagged: real-time calls inside logic meant to be driven by injected clocks) | Implemented | unit (`test_phase19_federation.py`: 51 passed; full suite: 3844 passed) |

> Full suite: **3844 passed** (was 3843 + 1 pre-existing failure from the
> `federation_state.py` clock bug above — both now green).
| `ROADMAP.html` regenerated with collapsible (`<details>`/`<summary>`) sections via `md_to_html.py --collapsible`, matching `FEATURE-HISTORY.html`'s pattern | USER-REQUESTED ("broodforge's roadmap should be revised to use collapsible sections, it's quite lengthy at this point") | Implemented | smoke (`<details>`/`</details>` balanced: 9/9; `test_meta_doc_sync.py` passes) — regeneration also closed a content-drift gap the prior hand-sync missed (three draft-sketch `<h3>` sections existed in `ROADMAP.md` but were absent from the old `ROADMAP.html`) |

---

**Cycle: 2026-06-08_15_42_18 UTC**

## Three Roadmap draft sketches promoted to scoped phases (operator decisions incorporated)

The operator reacted to all three "draft sketch, awaiting reaction" items
added the previous day (Recovery-Readiness Conformance, Hypervisor Recovery
Credentials, Granular Secret Access Silos for Human Operators) with itemized,
exact decisions on all three at once: *"The operator has made decisions on
all three roadmap sketches. Incorporate them into ROADMAP.md, ARCHITECTURE.md,
and PAP-state."* This is a pure documentation/scoping cycle — no code was
touched, so no test run was required (per the operator's own execution rule).

| Feature | Origin | Status | Verification |
|---|---|---|---|
| **Phase 1.I — Recovery-Readiness Conformance** scoped (`recovery-readiness-certificate.json`/HTML generator, additive to `readiness.py`/`drift.py`/`dependencies.py`/snapshot store/Phase 12 drills); **AD-059** added to `ARCHITECTURE.md` | USER-REQUESTED ("Recovery-Readiness Conformance → Scope as Phase 1.I... Build as additive extensions... Write an AD for it") | Scoped (proposed, not started) | static (doc-only; ROADMAP.md `Phase 1.I` block + ARCHITECTURE.md AD-059 cross-referenced) |
| **Phase 1.J — Hypervisor Recovery: Constrained Accounts and Pre-Generated Spawn Media** scoped (forced-command recovery accounts, break-glass root annotation on existing `secret-registry.yaml` entries, pre-generated human-gated spawn-media credentials, plus a new phoenix temporary-credential extension); **AD-060** added — a **firm architectural constraint**, binding on all future development: no autonomous pathway may read and wield full root credentials against live hypervisors, with two narrow named exceptions (node spawning, phoenix recovery — both temporary, session-scoped credentials only) | USER-REQUESTED ("The operator explicitly rules out any autonomous pathway that can read and wield full root credentials against live hypervisors — write this as a firm architectural constraint... The three-part middle path... is accepted as stated") | Scoped (proposed, not started) | static (doc-only; ROADMAP.md `Phase 1.J` block + ARCHITECTURE.md AD-060 cross-referenced) |
| **Phase 1.K — Granular Secret Access Silos: Vault Hierarchy and User Provisioning** scoped (`Role`/`Scope` registry, `derive-scoped-vault` generator, plus two operator-added expansions: vault-of-vaults credential recordkeeping and VM/Proxmox-level user-provisioning templates); **AD-061** added | USER-REQUESTED ("Higher-tier vaults must include records of the access credentials for lower-tier scopes... A mechanism for creating users at the VM level and Proxmox level... Scope this as a numbered phase... Write an AD for the vault hierarchy + user provisioning design") | Scoped (proposed, not started) | static (doc-only; ROADMAP.md `Phase 1.K` block + ARCHITECTURE.md AD-061 cross-referenced) |
| `.ai/decisions.md` gains a combined AD-059/AD-060/AD-061 entry recording the decision, rationale, and consequences (including AD-060's binding scope beyond Phase 1.J alone) | USER-REQUESTED | Implemented | static |
| `pap/state/SESSION_HANDOFF.md` / `RESUME_BLOCK.md` updated (seventh milestone) — closes the "Recovery-Readiness Conformance" open thread in `active_risks`, records the operator's decisions verbatim in `key_decisions_and_insights`, rewrites `next_action`/`active_objective` to reflect that zero items remain in draft/awaiting-reaction status | USER-REQUESTED ("Update SESSION-HANDOFF.md, CURRENT_STATE.md, RESUME_BLOCK.md") | Implemented | static |

> No code touched this cycle — pure documentation/scoping. `ROADMAP.md`
> "Proposed Future Work" now holds four scoped-but-not-started phases
> (1.H/1.I/1.J/1.K), each with its own AD, none mandatory, no priority order
> implied by their letters.

---

**Cycle: 2026-06-08_17_28_29 UTC**

## Clock-injection sweep + Phase 1.H (AD-057) implemented

Operator directed implementation of all four scoped-but-not-started phases in
order, starting with a repo-wide sweep for `datetime.now()`/`utcnow()` calls
that bypass the injected `now_fn` clock-injection convention (a recurring
class of latent bug — see the AD-058-follow-up cycle above for one prior
instance), then Phase 1.H.

| Feature | Origin | Status | Verification |
|---|---|---|---|
| Clock-injection sweep: `remediation_executor.build_failure_package` + all 9 `_exec_*` action handlers, `continuous_assessment.collect_pbs_state_update`, and `platform_state_collector.compute_platform_health`/`platform_state_to_dict` now thread `now_fn` instead of calling `datetime.now()` directly (audit-trail `failed_at`/drill `due_at`/`added_at`/PBS `collected_at`/cert-expiry timestamps are now deterministic under injected clocks); odd `__import__("datetime")` lazy-import in `reconstruction-drill.py` cleaned up to a normal top-level import | GAP-FILL (latent non-determinism — same class of bug AD-058-follow-up's `federation_state.verify_trust` fix addressed) | Implemented | unit (full suite: 4134 passed, 1 skipped — 4 pre-existing unrelated `test_opentofu.py` failures confirmed present on `main` before this change via `git stash`) |
| **Phase 1.H — Pre-Install Forge Package and Image Builder (AD-057)**: `generate-bootstrap-image.py` CLI + `_image_builder.py` module produce a `bootstrap-image-{cell_id}-{timestamp}.tar.gz` "staging bundle" — `answer.toml` (Proxmox 8+ automated-installer answer file derived from `forge-manifest.json` host_identity/network_topology fields, AD-049), an embedded forge package (reuses `assemble_forge_package`), a first-boot systemd hook + installer script that runs `forge.sh` unattended on first boot, a hash/contents manifest + AD-051 HTML twin (`build_bootstrap_image_manifest_html` added to `html_package_manifest.py`), and an operator README explaining how to combine the bundle with the official Proxmox VE ISO via `proxmox-auto-install-assistant` | USER-REQUESTED (Roadmap Phase 1.H checklist, promoted from AD-057) | Implemented | unit (`test_image_builder.py`: 62 passed; full suite: 4140 passed, 1 skipped) |
| `answer.toml` root-password handling: `generate_install_passphrase()` produces a fresh, single-use `Capital.boot.word.N` discovery passphrase (mirrors the AD-039/AD-043 Cloud-Init temporary-password pattern — never fixed/predictable, never written to KeePass, replaced by phase-03's KeePass-managed credential, printed once at build time and documented as one-time-use in the README/HTML manifest) | GAP-FILL (closes the "package never contains real secrets" invariant for the new artifact — `answer.toml` has no KeePass-reference indirection available at install time) | Implemented | unit (`test_no_fixed_default_password` asserts two generated `answer.toml`s never share a root-password line) |
| `FORGING.md`/`FORGING.html` gain "Step 0 — Build pre-install media (optional)" — explicitly framed as an optional alternative; the existing "Proxmox already installed" path remains the supported baseline | USER-REQUESTED (Roadmap Phase 1.H checklist item) | Implemented | static (regenerated via `md_to_html.py`) |

> Honesty constraint honored: the bundle is explicitly documented (CLI output,
> README, HTML manifest) as a *staging bundle* an operator combines with the
> official Proxmox VE ISO via Proxmox's own remastering tooling — broodforge
> neither downloads, mounts, nor redistributes Proxmox media, consistent with
> AD-040's reference-stack-only scope. Full suite: **4140 passed, 1 skipped**
> (4 pre-existing unrelated `test_opentofu.py` failures, confirmed present on
> `main` before any of this cycle's changes).

---

**Cycle: 2026-06-08_19_05_00 UTC**

## Phase 1.I — Recovery-Readiness Conformance Certificate (AD-059) implemented

Second of the four scoped phases the operator directed be implemented in
order. Built as additive composition over existing evidence-producing
modules — no new scoring system, no Ed25519/category-theoretic apparatus,
exactly as AD-059 scopes it.

| Feature | Origin | Status | Verification |
|---|---|---|---|
| `recovery-readiness-certificate.json` + AD-051 HTML twin (`_recovery_readiness_certificate.py`, `generate-recovery-readiness-certificate.py`, `build_recovery_readiness_certificate_html`): one timestamped record composing `manifest_hash`/`graph_hash` (SHA-256 over canonical sorted-key JSON), the real readiness signal (`overall_score`/`overall_score_reason`/component-score counts), a drift summary (severity + diff counts), and the latest reconstruction-drill summary (outcome/accuracy/waves/gaps) | USER-REQUESTED (Roadmap Phase 1.I checklist, promoted from AD-059) | Implemented | unit (`test_recovery_readiness_certificate.py`: 44 passed) |
| **Correction to AD-059's premise, documented rather than perpetuated**: AD-059 claimed "RRS/ACS/DCS/CRS/OSS scores already exist in readiness.py" — investigation found this is aspirational, not actual. `readiness.py::score_graph()` produces a single `overall_score` (GREEN/YELLOW/ORANGE/RED/BLOCKED) + `overall_score_reason` + a `components` list; the five-letter abbreviation scheme exists only as defensive/unpopulated UI code in `broodforge_dashboard.py` (`_scores_from_readiness()` reads a `scores`/`summary` dict nothing ever assigns). The certificate composes the **real** `overall_score` signal and documents this finding inline (`_READINESS_NOTE`, rendered in the HTML twin) rather than inventing a five-category scoring system that AD-059 itself says is unnecessary | GAP-FILL (closes a premise gap discovered while implementing — avoids perpetuating dead-code-shaped fiction in a new conformance artifact) | Implemented | unit (`test_does_not_invent_rrs_acs_dcs_crs_oss_keys`, `test_correction_honored_no_invented_score_keys`, `test_does_not_render_invented_score_labels`) |
| `replay-snapshot.py` — recomputes a stored snapshot's `manifest_hash`/`graph_hash`/`overall_score` from its raw `manifest.json` and asserts the recomputed hashes match the values recorded in `history/index.json` at snapshot-build time (exit 0 = conformance holds, exit 1 = mismatch + diff explanation); turns "snapshots are reproducible" from an assumption into a checked, reportable fact | USER-REQUESTED (Roadmap Phase 1.I checklist item (c)) | Implemented | unit (`test_replay_snapshot.py`: 12 passed) + smoke (ran against the real `assessment_2026-05-29_02_05_00` snapshot — `[PASS]`) |
| `history/index.py::build_index()` now computes and records `manifest_hash`/`graph_hash` per snapshot entry in `history/index.json` (additive keys; hashes live in the regenerated index rather than mutating raw historical `manifest.json` captures) | USER-REQUESTED (Roadmap Phase 1.I checklist item (b)) | Implemented | unit + smoke (`history/index.json` regenerated; both existing snapshot entries now carry both hashes) |
| `compute_drift()` (`doc-gen/drift.py`) gains `now_fn` clock injection for `generated_at` (was a direct `datetime.now(timezone.utc)` call — same latent-bug class the prior cycle's sweep fixed elsewhere, missed because `doc-gen/` wasn't in that sweep's grep scope; existing callers pass no `now_fn` so behavior is unchanged) | GAP-FILL (same class as the AD-058-follow-up `federation_state` fix and the prior cycle's sweep) | Implemented | unit (deterministic `generated_at` under injection + real-clock fallback asserted) |
| "Human Intervention Boundary" documentation pass — new subsection in `ROADMAP.md`'s Phase 1.I scope block enumerating what's autonomous (certificate generation, hash recording, replay/conformance check, readiness/drift scoring — all read-only composition) vs. operator-required (running reconstruction drills, KeePass master-password entry, restic/rclone restore execution, acting on certificate findings) | USER-REQUESTED (Roadmap Phase 1.I checklist item (d)) | Implemented | static (`ROADMAP.html` regenerated, collapsible sections balanced) |

> Full suite: **4252 passed, 1 skipped** (same 4 pre-existing unrelated
> `test_opentofu.py` failures, confirmed unchanged from clean `main`). New
> tests: 56 (44 + 12).
