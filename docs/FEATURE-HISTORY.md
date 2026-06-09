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

---

**Cycle: 2026-06-08_20_15_00 UTC**

## Phase 1.K — Granular Secret Access Silos: Vault Hierarchy and User Provisioning (AD-061) implemented

Third of the four scoped phases the operator directed be implemented in
order. Built as a "more vaults derived from the one vault" design — no
broker, no ACL layer, no live KDBX manipulation — exactly as AD-061 scopes
it (the constraint: `.kdbx` files are single-master-password with no native
per-user role layer).

| Feature | Origin | Status | Verification |
|---|---|---|---|
| `role-scope-registry.yaml` — new authoritative per-cell YAML (mirrors `secret-registry.yaml`'s documented-header style, placed alongside it rather than adding a disproportionate `data-model/` JSON-Schema pair for a 3-entry registry) declaring named roles (`service-operator`/`node-sysadmin`/`god-mode`), glob-pattern scopes over `secret-registry.yaml`'s existing `owning_cell`/`required_by`/`secret_type`/`required_for` vocabulary (with an `excludes` denylist facet), and which humans hold each role | USER-REQUESTED (Roadmap Phase 1.K checklist item 1, AD-061) | Implemented | unit (`test_vault_hierarchy.py`: registry-loading + scope-matching classes) |
| `_vault_hierarchy.py` + `derive-scoped-vault.py` — `derive-scoped-vault` generator: matches `secret-registry.yaml` entries against a role's scope globs (stdlib `fnmatch`), composes a derived-vault *plan* (in-scope entries, a freshly-generated passphrase via `lib/passphrase.py::generate_master_password_suggestion()`, the AD-044-style KeePass record path `Vaults/{role}/{timestamp}/passphrase` for the parent-vault bookkeeping entry, and the `keepassxc-cli` command sequence an operator runs to actually build it) + AD-051 HTML twin (`build_scoped_vault_plan_html`) | USER-REQUESTED (Roadmap Phase 1.K checklist item 2, AD-061) | Implemented | unit + smoke (ran against the real registries — `service-operator` → 9/11 entries with `pve01-*` denylisted; passphrase confirmed absent from persisted JSON/HTML, shown once at CLI runtime only) |
| **No live KDBX manipulation, confirmed by design-pattern match**: verified no module in broodforge opens/writes binary `.kdbx` files or shells out to live Proxmox/KeePass APIs — `forge_keepass_init.py`/`setup-secrets.py` both *generate command strings* for an operator to run. `_vault_hierarchy.py` follows that exact pattern (`render_derive_vault_commands()` mirrors `render_init_commands()`); the `god-mode` tier is refused outright (`build_derived_vault_plan` raises `ValueError`) since deriving "everything" from "everything" under a weaker fresh passphrase would only produce a strictly-worse duplicate of the canonical vault | GAP-FILL (closes the "how does this actually get built without a live KDBX-manipulation layer" question AD-061 leaves implicit) | Implemented | unit (`test_no_live_kdbx_manipulation`-equivalent assertions; god-mode-refusal test) |
| Vault-of-vaults recordkeeping (operator-directed AD-061 expansion) — each derived vault's generated passphrase is recorded as a `KeePassEntry`-shaped bookkeeping record at a generated, AD-044-pattern path in the *next tier up*'s vault, so a higher-tier holder can always recover a lower-tier scoped vault's passphrase | USER-REQUESTED (Roadmap Phase 1.K checklist item 3, AD-061 expansion 1) | Implemented | unit (`vault_record_path()` path-construction tests) |
| User-provisioning templates (operator-directed AD-061 expansion) — `generate_vm_account_template()` produces an additive Cloud-Init account block in the exact shape `spawn_iac_generator.py::generate_cloudinit_user_data()` already emits (for splicing into its `users:` list — not a parallel system); `generate_proxmox_account_commands()` produces templated `pveum user add`/`aclmod`/`user token add` command sequences with role-tiered PVE roles (`PVEVMUser`/`PVEAdmin`/`Administrator`) | USER-REQUESTED (Roadmap Phase 1.K checklist item 4, AD-061 expansion 2) | Implemented | unit (cloud-init account-block shape + pveum command-sequence tests) |
| Authorization model ("only canonical-vault holders can mint scoped vaults — true by construction") and Revocation-as-rotate+reissue ("an honest non-guarantee — a derived vault cannot leak ciphertext it never received") documented as design statements (not enforcement machinery — there is nothing to check that isn't already true by construction) in the registry header, `describe_vault_plan()`'s human-readable output, and dedicated HTML sections | USER-REQUESTED (Roadmap Phase 1.K checklist items 5–6, AD-061) | Implemented | static (no permission-check system built — confirmed proportionate to scope) |

> Full suite: **4292 passed, 1 skipped** (same 4 pre-existing unrelated
> `test_opentofu.py` failures, confirmed unchanged from clean `main`). New
> tests: 40 (`test_vault_hierarchy.py`).

---

**Cycle: 2026-06-08_21_40_00 UTC**

## Phase 1.J — Hypervisor Recovery: Constrained Accounts and Pre-Generated Spawn Media (AD-060) implemented

Fourth and final of the four scoped phases the operator directed be
implemented in order — closing the milestone. AD-060 is a firm
architectural SHALL-NOT ("no autonomous pathway may read or wield full
root credentials against live hypervisors — root has no boundary by
definition"), with exactly two narrow, named, time-limited exceptions
(node-spawn discovery and phoenix-setup credentials, both requiring
operator rotation after). Every artifact below was built and reviewed
against that boundary first; feature completeness was secondary to it.

| Feature | Origin | Status | Verification |
|---|---|---|---|
| **(a) Constrained, forced-command recovery accounts** — `_recovery_accounts.py` (+ `setup_recovery_account.py` CLI, `build_recovery_account_plan_html` AD-051 twin): generates an `authorized_keys` line gated by `command="<menu-script>"` plus the standard forced-command restriction set (`no-pty,no-port-forwarding,no-X11-forwarding,no-agent-forwarding`), and the fixed-menu POSIX-`sh` script string itself (status/logs/vmlist/vmstart/vmstop/help). Structurally incapable of becoming a shell: `$SSH_ORIGINAL_COMMAND` is matched against a fixed enumerated `case` of literal verbs only — never `eval`/`sh -c`/backticks — and the one operator-influenced value (VMID) is regex-validated (`^[0-9]{1,6}$`) before reaching `exec qm start/stop`. broodforge generates strings only; it never installs, runs, or connects through this account itself | USER-REQUESTED (Roadmap Phase 1.J checklist item (a), AD-060) | Implemented | unit (`test_recovery_accounts.py`: 46 passed, incl. shell-metacharacter-rejection and "no eval/exec-of-input" structural assertions) |
| **(b) Break-glass root — documentation/storage annotation only** — `secret-registry.yaml` gains an optional `access_policy: break-glass-human-only` field (documented in the file's header-comment schema) on `pve01-root-password`; `_recovery_accounts.describe_break_glass_pointer()` surfaces only `id`/`keepass_path`/`description` (a location, never a value) for display in generated recovery runbooks/menus — "the runbook tells the operator where to look, they unlock KeePass and type it themselves" (the existing AD-042 human-unlock gate, unchanged) | USER-REQUESTED (Roadmap Phase 1.J checklist item (b), AD-060) | Implemented | unit (structural guard asserting the function reads only location/description fields, never a `value`/`password`/`secret` field, and that no KeePass/SSH-client import or connection call exists anywhere in the module) |
| **(c) Pre-generated spawn-media credentials + human authorization gate** — `_image_builder.py` gains `build_pregenerated_spawn_media_record()` (runs the existing AD-043 `generate_install_passphrase()` at *build* time instead of install time, per AD-060(c)) paired with `build_pending_join_authorization()` — a `pending_join_authorizations` state-record entry (in `bootstrap-state.json`, the same recorded-operator-decision shape AD-041's autonomous-mode confirmation already uses) that stores only a SHA-256 `passphrase_hash`, defaults `authorized: false`, and can be flipped to `true` ONLY by the new human-operated `authorize-spawn-media-join.py` CLI (`--operator` required for audit attribution; refuses to authorize unknown bundles or re-authorize already-authorized ones; never auto-creates or auto-flips) | USER-REQUESTED (Roadmap Phase 1.J checklist item (c), AD-060) | Implemented | unit (`test_spawn_media_authorization.py`: 27 passed, incl. hash-only persistence, default-`authorized=false`, and CLI refusal-path assertions) |
| **(d) Phoenix temporary-credential extension** — `phoenix_playbook.py` gains `generate_phoenix_session_credential()` (mirrors `spawn_planner.generate_temp_password`/`_image_builder.generate_install_passphrase` — same readable `Capital.phoenix.word.N` shape, `random.Random(seed)` test-determinism convention) and `phoenix_session_credential_section()`, wired into `PhoenixPlaybookGenerator.build()` as a new `temporary_session_credential` top-level section recording: `scope: "phoenix-setup-session-only"`, a bounded `valid_window` (ends when Wave 2 restores the KeePass-managed credential), and a `rotation_requirement` stating *in the generated output itself* — "ROTATE THIS CREDENTIAL THE MOMENT THIS RECOVERY SESSION COMPLETES… broodforge does not and cannot autonomously verify or perform rotation (doing so would itself be the autonomous full-root pathway AD-060 forbids)" | USER-REQUESTED (Roadmap Phase 1.J checklist item (d), AD-060) | Implemented | unit (`test_phoenix_session_credential.py`: 23 passed, incl. assertions that the rotation requirement and session-only scope appear in the generated playbook dict, and that the credential is never written to KeePass) |

> **Constraint-honored confirmation** (the load-bearing fact of this cycle):
> `grep -rn "pve0.*root.*password\|root-password\|root_password" --include="*.py" proxmox-bootstrap/`
> (excluding tests) shows only pre-existing matches — KeePass *path-name*
> generation (`suggest-names.py`, `setup-secrets.py`), the AD-039 named
> temporary-credential exception (`spawn_planner.py`), and the AD-043
> single-use *discovery* passphrase in `answer.toml` (`_image_builder.py`,
> `html_package_manifest.py`, `generate-bootstrap-image.py`). **No new or
> modified code in this cycle reads a permanent hypervisor root-credential
> value or wields one against a live hypervisor** — every new module
> generates strings/records for an operator (or an already-trusted phase-03
> step) to install, exactly mirroring `_image_builder.generate_first_boot_install_sh`'s
> established "broodforge writes the script, the operator/package runs it"
> convention. Both temporary-credential exceptions (node-spawn, phoenix-setup)
> are visibly bounded in their generated output as time-limited/session-scoped
> with mandatory operator rotation after — never the cell's permanent keystore.

> Full suite: **4388 passed, 1 skipped** (same 4 pre-existing unrelated
> `test_opentofu.py` failures, confirmed unchanged from clean `main`). New
> tests: 96 (46 + 27 + 23).

---

**Milestone closed.** All five operator-directed items from this session's
ordered execution list are now implemented and committed: the `datetime.now()`
clock-injection sweep, Phase 1.H (AD-057), Phase 1.I (AD-059), Phase 1.K
(AD-061), and Phase 1.J (AD-060) — the latter four corresponding to AD-057/
059/060/061, the four "ready-to-start" phases named in the operator's
directive, implemented strictly in the specified order with Phase 1.J last
per its explicit constraint-sensitivity. Full suite at milestone close:
**4388 passed, 1 skipped, 4 deselected** (pre-existing, unrelated, unchanged
from clean `main`).

---

**Cycle: 2026-06-08_22_41_33 UTC**

## Image Builder GUI Wizard — `forge-image-builder.html` (Phase 1.H addition, AD-057)

Cross-platform operator GUI for `generate-bootstrap-image.py` — a
self-contained HTML wizard that turns the CLI's eight flags into a guided
form with live command preview and clipboard copy. No server required;
works offline by opening the file directly in a browser.

| Feature | Origin | Status | Verification |
|---|---|---|---|
| `proxmox-bootstrap/forge-image-builder.html` — self-contained wizard covering all `generate-bootstrap-image.py` arguments: `--manifest` (required, with inline validation), `--output-dir`, `--filesystem` (dropdown: zfs/ext4/xfs/btrfs), `--keyboard`, `--country`, `--disk` (repeatable list with add/remove), `--repo`, `--kdbx` (optional, in a collapsible section). Live JavaScript command builder updates as the operator types; POSIX shell-quoting applied to all path values; clipboard-copy button with fallback for `file://` context | USER-REQUESTED (operator-directed addition to Phase 1.H / AD-057) | Implemented | static + smoke (opened in browser, verified live command preview, copy button, dark/light toggle, validation banner on empty --manifest) |
| Matches existing broodforge HTML pattern — same CSS variable dark theme with light toggle as `FORGING.html` and `NODE-SPAWNING.html`; same `proxmox-bootstrap/` placement alongside the CLI tool it wraps; fully self-contained (no CDN, no external fonts, no server) | GAP-FILL (consistency with AD-025's "self-contained HTML" standard) | Implemented | static |
| Post-bundle next-steps section — numbered walkthrough of what to do after `generate-bootstrap-image.py` completes: download official Proxmox VE ISO, extract bundle, run `proxmox-auto-install-assistant prepare-iso`, install first-boot hook, boot target machine, rotate install passphrase | GAP-FILL (closes the "what do I do with the tar.gz" question) | Implemented | static |
| CLI reference table embedded in collapsible section — all eight flags with defaults and descriptions | GAP-FILL (operator reference without opening generate-bootstrap-image.py) | Implemented | static |
| AD-057 updated — status changed from "proposed; not started" to "implemented (commit 072112e)" with GUI addition note; ARCHITECTURE.md date header updated | USER-REQUESTED (documentation hygiene per feature_revision_process convention) | Implemented | static |
| **Future enhancement noted in AD-057**: a `/api/run-image-builder` endpoint in `broodforge_dashboard.py` could stream builder output directly from the dashboard — deferred, clipboard-copy is the MVP and works fully offline | GAP-FILL (named explicitly so it is not silently lost) | Documented (not built) | n/a |

> No new Python tests required — `forge-image-builder.html` is a pure
> client-side HTML file with no Python module to cover. The existing
> `test_meta_doc_sync.py` and `test_html_base_sync.py` are unaffected
> (the wizard is not a `.md`→`.html` companion and does not use
> `html_base.py`). Full suite: **4388 passed, 1 skipped** (unchanged —
> no code touched).

---

**Cycle: 2026-06-08_12_00_00 UTC — PAP Audit Fixes (34-finding full-codebase scan)**

## PAP audit 2026-06-08 — CRITICAL + HIGH fixes

| Feature | Origin | Status | Verification |
|---|---|---|---|
| Phases 04/05 exit 2 (NOT_IMPLEMENTED) instead of self-checkpointing as done (`forge_scripts.py`) | USER-REQUESTED (audit F-001/F-002) | Implemented | unit (4332 passed) |
| `forge.sh` `_forge_incomplete` flag + FORGE INCOMPLETE banner + exit 1 | USER-REQUESTED (audit F-017/F-028) | Implemented | unit |
| `sync-cert-to-k8s.sh` exits 1 with loud error instead of silent exit 0 | USER-REQUESTED (audit F-003) | Implemented | static |
| Phase-06 validates FORGEJO_TOKEN before `flux bootstrap` | USER-REQUESTED (audit F-019) | Implemented | unit |
| Phase-07 writes `bootstrap-state.json` to canonical `/var/lib/broodforge/` path | USER-REQUESTED (audit F-009) | Implemented | unit |
| Phase-08 drops `--allow-empty`; only commits when state file changed | USER-REQUESTED (audit F-033) | Implemented | unit |
| Dashboard `_scores_from_readiness()` passes through `overall_score`; OVR badge fallback | USER-REQUESTED (audit F-008/F-029) | Implemented | unit |
| `DashboardConfig.save()` raises loudly on OSError instead of silently swallowing | USER-REQUESTED (audit F-010/F-032) | Implemented | unit |
| `_serve_doc_file()` 3-step docs resolution + configurable `docs_path` | USER-REQUESTED (audit F-014/F-030) | Implemented | unit |
| `spawn_planner.py` fail-fast if k3s join tokens absent from `bootstrap-state.json` | USER-REQUESTED (audit F-011/F-020) | Implemented | unit |
| WAN spawn fail-fast if `wan_auth_key` absent | USER-REQUESTED (audit F-021) | Implemented | unit |
| `generate-bootstrap-image.py` validates `--interface`/`--disk` at build time | USER-REQUESTED (audit F-018) | Implemented | unit |
| Prominent install-passphrase banner (`!! SINGLE-USE — RECORD THIS NOW !!`) | USER-REQUESTED (audit F-023) | Implemented | static |

## PAP audit 2026-06-08 — MEDIUM + LOW fixes

| Feature | Origin | Status | Verification |
|---|---|---|---|
| `forge_keepass_init.py` `include_wan` no-op: removed dead `wan_paths` computation; added explanatory comment | USER-REQUESTED (audit F-004) | Implemented | static |
| `guided_setup.py` added `backup.secrets_destinations` suggest handler | USER-REQUESTED (audit F-005) | Implemented | unit |
| `guided_setup.py` replaced `network_topology_collector._zfs_topology_from_disk_count` private import with inline 5-line logic (stdlib-only contract) | USER-REQUESTED (audit F-006) | Implemented | unit |
| `ROADMAP.md` Phase 1.I/1.J/1.K scope items marked `[x]`; status blocks updated to "implemented" | USER-REQUESTED (audit F-007/F-031) | Implemented | static |
| `_vault_hierarchy.py` fallback passphrase uses `secrets.token_urlsafe(24)` instead of deterministic `GENERATE-AT-RUNTIME-{role}` | USER-REQUESTED (audit F-012) | Implemented | unit |
| Phase-03 wires `setup_recovery_account.py`; reads `host_identity.operator_ssh_key` from manifest; writes plan to `/var/lib/broodforge/recovery-plans/` | USER-REQUESTED (audit F-015) | Implemented | unit |
| `FORGING.md` Step 0 NOTE block: clarifies Step 1 (forge-planner.py) must run first | USER-REQUESTED (audit F-022) | Implemented | static |
| `describe_vault_plan()` shows explicit "Operator steps required (N entries)" section with numbered actions | USER-REQUESTED (audit F-024) | Implemented | unit |
| `summarize_drift()` adds `note` key when drift unavailable (insufficient history message) | USER-REQUESTED (audit F-025) | Implemented | unit |
| `phoenix_playbook.py` Wave 2 step 2.2: KeePass-managed credential delivery path documented (path, copy method, rotation requirement) | USER-REQUESTED (audit F-026) | Implemented | unit |
| `forge_keepass_init.py` TOTP provisioned AFTER KeePass DB creation commands execute | USER-REQUESTED (audit F-027) | Implemented | static |
| `_recovery_readiness_certificate.py` `drills[0]` comment clarifies newest-first via `insert(0,…)` | USER-REQUESTED (audit F-016/F-034) | Implemented | static |

> Full test suite: **4332 passed, 1 skipped** (pre-existing `test_opentofu.py` failure excluded).

---

**Cycle: 2026-06-08_23_00_00 UTC — PAP Audit Round 2 Fixes (N-001 through N-004)**

## PAP audit 2026-06-08 R2 — HIGH fixes

| Feature | Origin | Status | Verification |
|---|---|---|---|
| Phase-05 `_worker_token`/`_server_token` now `export`-ed before the `python3 - <<PYEOF` heredoc — fixes `KeyError` that aborted phase-05 after ansible succeeded, leaving k3s tokens never written to `bootstrap-state.json` (`forge_scripts.py:601–602`) | USER-REQUESTED (audit N-001) | Implemented | unit (2 new tests: `test_phase_05_exports_worker_token_before_heredoc`, `test_phase_05_export_precedes_heredoc`) |
| Phase-06 exits 2 (NOT_IMPLEMENTED) instead of 1 when Forgejo credentials are missing — allows `forge.sh` to set `_forge_incomplete=1` and reach the FORGE_INCOMPLETE banner rather than aborting with confusing "FAIL phase-06" error (`forge_scripts.py:658–670`) | USER-REQUESTED (audit N-002) | Implemented | unit (1 new test: `test_phase_06_exits_2_when_credentials_missing`) |

## PAP audit 2026-06-08 R2 — MEDIUM fixes

| Feature | Origin | Status | Verification |
|---|---|---|---|
| `NODE-SPAWNING.md` "WAN mode prerequisites" section added — covers Headscale server prerequisite, `headscale preauthkeys create` command, `--wan-auth-key` CLI flag usage, Tailscale install on hatchery, `wan_endpoint` reachability, and a summary checklist (`proxmox-bootstrap/NODE-SPAWNING.md`) | USER-REQUESTED (audit N-003) | Implemented | static |
| `generate-bootstrap-image.py` now calls `build_pregenerated_spawn_media_record()` + `record_pending_join_authorization()` — wires Phase 1.J authorization pipeline; new `--state` flag writes a `pending_join_authorizations` record to `bootstrap-state.json` so `authorize-spawn-media-join.py` has a record to gate (`generate-bootstrap-image.py`, `_image_builder.py`) | USER-REQUESTED (audit N-004) | Implemented | unit (12 new tests across `TestBuildPregeneratedSpawnMediaRecord` and `TestRecordPendingJoinAuthorization`) |

> Full test suite: **4403 passed, 1 skipped** (pre-existing `test_opentofu.py` failures unchanged).
