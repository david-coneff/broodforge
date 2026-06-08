# Project Resume Block — broodforge

Instance of [PAP-State §3](../modules/PAP-State/PAP-State.md#3-project-resume-block)
(Project Resume Block), conforming to
[`resume-block.schema.yaml`](../modules/PAP-State/schemas/resume-block.schema.yaml).
This is **broodforge's own** resume block — a record of *broodforge's
codebase-development continuity*, governed going forward by PAP per
[`pap/revisions/2026-06-07_session-continuity-transition-to-pap.md`](../revisions/2026-06-07_session-continuity-transition-to-pap.md).
It is not, and does not describe, broodforge's *infrastructure remediation*
function (planner/queue/executor/policy) — that is the platform's product
behavior, not its development process, and is out of scope for this artifact
(see that transition record's "What this transition is — and is not" section).

---

- **project_identity**: Broodforge — a self-managing infrastructure platform
  for home-lab Proxmox + k3s environments (hardware assessment, cell forging,
  node spawning, phoenix recovery, continuous health monitoring, autonomous
  remediation). Six-layer lifecycle, seventeen-state model, three assessment
  tiers, five dependency-graph types. Architecture v7.1+. (Source:
  `.ai/context.md`, `.ai/CURRENT_STATE.md`.)

- **active_objective**: No implementation work is currently active. Per
  `.ai/NEXT_STEPS.md` and `.ai/CURRENT_STATE.md`, all roadmap milestones and
  all four planned intelligence tracks (through Phase 26 — Autonomous
  Operations) are complete, and the last `docs/SESSION-HANDOFF.md` entry
  (now superseded — see the transition record) named the platform's own next
  action as **"deploy to hardware"** (`python3 proxmox-bootstrap/forge-planner.py`
  on a real Proxmox host; see `FORGING.md`). **Four proposed (not-started)
  development items now exist in `ROADMAP.md`, all scoped phases with their
  own ADs**: Phase 1.H — Pre-Install Forge Package and Image Builder
  (AD-057, surfaced by the `new/` corpus analysis); **Phase 1.I —
  Recovery-Readiness Conformance** (AD-059 — a `recovery-readiness-
  certificate.json`/HTML generator, additive to `readiness.py`/`drift.py`/
  `dependencies.py`/snapshot store/Phase 12 drills); **Phase 1.J —
  Hypervisor Recovery: Constrained Accounts and Pre-Generated Spawn Media**
  (AD-060 — implements the accepted middle path *within* a firm
  architectural constraint the operator stated explicitly: no autonomous
  pathway may read and wield full root credentials against live
  hypervisors, with two narrow named exceptions for temporary,
  session-scoped credentials in node spawning and phoenix recovery); and
  **Phase 1.K — Granular Secret Access Silos: Vault Hierarchy and User
  Provisioning** (AD-061 — derived scoped KeePass vaults plus two
  operator-directed expansions: vault-of-vaults credential recordkeeping and
  VM/Proxmox-level user-provisioning templates). The latter three were
  **draft sketches as of 2026-06-07; the operator reacted to all three with
  itemized decisions on 2026-06-08, and they are now promoted** — see
  `active_milestone` (seventh) and `key_decisions_and_insights` in
  `SESSION_HANDOFF.md` for the full record. All four phases are candidates
  for a future development session, not mandates — none is started.

- **active_milestone**: (Updated — seventh milestone, same day, 2026-06-08.)
  The operator reacted to all three draft sketches recorded the previous day
  with explicit, itemized decisions — "Incorporate them into ROADMAP.md,
  ARCHITECTURE.md, and PAP-state. Here are the exact decisions" — and this
  milestone closes that thread completely: all three sketches are now scoped
  phases (1.I, 1.J, 1.K) with corresponding ADs (AD-059, AD-060, AD-061),
  exactly as the operator specified, including the operator's own expansions
  (vault-of-vaults recordkeeping, VM/Proxmox user-provisioning templates,
  and — most architecturally significant — **a firm, durable constraint
  (AD-060) ruling out any autonomous pathway that can read and wield full
  root credentials against live hypervisors**, binding on all future
  development, not just Phase 1.J's own scope). `ROADMAP.md` "Proposed Future
  Work" was rewritten in place: each sketch's heading, status line, and
  closing "if the operator wants to proceed" paragraph were converted to a
  scoped-phase block with a "Proposed scope" checklist and an AD reference,
  while the underlying analysis (including the formal-concept translation
  table and the hypervisor-credential risk evaluation) was preserved as the
  "source of this analysis" supporting material — nothing was deleted, only
  reframed from "draft, awaiting reaction" to "scoped, operator-confirmed."
  `ARCHITECTURE.md` gained AD-059/060/061 (in sequence, after AD-058) and its
  version-header date stamp was updated. `.ai/decisions.md` gained a combined
  AD-059/060/061 entry recording the rationale and consequences. This file,
  `SESSION_HANDOFF.md`, and `.ai/CURRENT_STATE.md` were updated to reflect
  the new state — no items remain in "draft sketch, awaiting reaction" status
  in `ROADMAP.md`.

  **Before this (sixth milestone, same day, earlier session):** Resumed per
  the operator's "continue using PAP-state" instruction; found a
  prior session had left the AD-058 guided-setup gap (named at the end of the
  fifth milestone, below) **mid-flight as uncommitted edits** — completed it:
  `security.mfa_method` is now wired end-to-end, **guided setup → forge
  manifest → `KeePassInitConfig`** (`guided_setup.py` suggest/check_conflicts,
  `forge_planner.py build_forge_manifest()`, `forge_keepass_init.py
  generate_keepass_init_config()` — the last of which had computed the value
  but never passed it to the returned config; that one missing line was the
  whole remaining gap). Added full test coverage
  (`test_guided_setup.py`/`test_forge_planner.py`, 6 new cases). While running
  the full suite to verify (standing practice before declaring done), found
  **one pre-existing failure unrelated to this work** —
  `test_phase19_federation.py::test_expiring_soon_still_valid` — confirmed via
  `git stash` it failed identically on untouched `main` (not a regression):
  `verify_trust()` in `federation_state.py` compared a real-wall-clock
  property (`relationship.is_expired` → `datetime.now(timezone.utc)`) against
  its own injected `now_fn`, so a fixture pinned to "now = 2026-06-01" with
  expiry "2026-06-08" started failing the moment real UTC crossed that date.
  Fixed it to compare against the injected `now` consistently (mirroring the
  correct pattern already used two lines below it for re-verification age).
  Recorded the full cycle in `docs/FEATURE-HISTORY.md`
  (`2026-06-08_12_36_41 UTC`) and regenerated its HTML twin. **Full suite:
  3844 passed** (was 3843 + 1 pre-existing failure — both now green, no
  regressions). See `SESSION_HANDOFF.md`'s `last_completed_step` for the
  complete account, including the named-but-deliberately-not-chased
  `datetime.now(`/`datetime.utcnow(` sweep candidate this surfaced.

  **Before this (fifth milestone, prior session, same day):** The
  operator reacted to the "Hypervisor Recovery Credentials" sketch
  (endorsing its constrained-recovery-account "middle path") and, in the
  same message, issued two further direct instructions, both now closed:
  (1) **AD-058** — second-factor auth (TOTP-authenticator or YubiKey only,
  *never* SMS/email) is now the **default**, not opt-in, for the KeePass
  unlock gate (`KeePassInitConfig.mfa_method` / `--mfa` flipped `"none"` →
  `"totp"`; the mechanism — `keepass_mfa.py` — already existed, fully
  tested, and already excluded SMS/email by design; only the *default* and
  documentation needed to change); one gap is named and deliberately left
  open — `guided_setup.py`/`forge_planner.py` don't yet prompt for MFA
  interactively. (2) `ROADMAP.html` (and, finding similar drift,
  `docs/FEATURE-HISTORY.html`) **regenerated** via
  `md_to_html.py --collapsible` — satisfying the operator's "revise the
  roadmap to use collapsible sections, it's quite lengthy" request *and*
  closing a content-drift gap worse than the one the prior milestone's new
  `test_meta_doc_sync.py` checks for (that test compares date stamps only;
  the hand-synced `ROADMAP.html` was actually missing entire `<h3>`
  sections that exist in `ROADMAP.md` — true regeneration fixes content
  drift, not just stamp drift). Both changes, plus AD-058's stamp-sync
  follow-through in `ARCHITECTURE.md`/`docs/ARCHITECTURE.html`, are recorded
  in a new dated cycle in `docs/FEATURE-HISTORY.md`
  (`2026-06-08_04_54_51 UTC`). All tests green
  (`test_meta_doc_sync.py`, `test_html_base_sync.py`, and the
  `keepass or mfa or forge_init or secrets or meta_doc or html_base or
  roadmap or feature_history` sweep — 156 passed). The three draft sketches
  from the fourth milestone (Recovery-Readiness Conformance, Hypervisor
  Recovery Credentials, Granular Secret Access Silos) remain in
  `ROADMAP.md` "Proposed Future Work," still awaiting promotion to
  phase/AD status. The intelligence/development side of the project remains
  feature-complete per its own governance corpus; the next milestone named
  in that corpus is an *operational* one (a real hardware run), not a
  development one — though `ROADMAP.md` now also names one *proposed*
  development item (Phase 1.H), three *draft* items (the sketches above),
  and one newly-named *gap* (AD-058's guided-setup MFA prompt) for whenever
  the operator chooses to engage with any of them.

- **active_risks**:
  - **(Updated 2026-06-07, second milestone — F1 and F2 now CLOSED):** The
    `pap`-driven audit recorded in
    [`pap/audits/2026-06-07_broodforge-pap-audit.md`](../audits/2026-06-07_broodforge-pap-audit.md)
    originally named three open, non-blocking findings. Two are now resolved
    by direct operator clarification of original intent, recorded as in-place
    annotations (nothing silently rewritten — originals preserved):
    - ~~F1 (Charter Purpose/SHALL-NOT text reads as broader than the system
      that exists)~~ — **CLOSED**. The operator clarified the SHALL-NOT
      list's "subjective judgments"/"recommendations" language always meant
      *specific-hardware* recommendations (product/pricing-database-grade
      calls, out of scope), not the platform's own resource-provisioning /
      deployment-strategy decisions for infrastructure it manages. Recorded
      as an in-place Scope note on `.ai/PROJECT_CHARTER.md` and `AD-040`.
    - ~~F2 (AD-034's "never takes autonomous action" boundary reads as
      crossed by Phase 26, with no decision record marking the crossing)~~ —
      **CLOSED**. The operator clarified autonomous action was always meant
      to be acceptable *when bounded by safeguards and recoverability* —
      AD-034's phrasing was under-specified, not the system's behavior wrong.
      Recorded as an in-place Amendment on `AD-034` and `AD-040`.
    - Both were genuine **textual ambiguities**, not real contradictions
      between governing text and built system — resolvable only by the
      documents' own author stating original intent, exactly as the audit's
      own Falsification perspective had hedged might be the case. See
      `pap/state/SESSION_HANDOFF.md`'s `key_decisions_and_insights` for the
      fuller account, and the audit record's own "Status update" banner and
      per-finding "Resolution" annotations for the canonical record.
  - **F3 — initially deferred, now CLOSED.** The untracked `new/` directory
    (~165 proposed-revision documents, not ~25 — the smaller count was an
    early estimate from filenames alone) was first explicitly deferred by
    the operator ("this is deferred for the moment"), then **explicitly
    un-deferred** by a later, separate, scoped instruction ("Analyze the
    `new/` directory ... and integrate relevant content into the roadmap and
    architecture" — with built-in guidance on what to integrate vs. defer).
    That analysis is done: **one** concrete, additive item was integrated
    (proposed **Phase 1.H — Pre-Install Forge Package and Image Builder**,
    in `ROADMAP.md` + `ARCHITECTURE.md` AD-057); three other named areas were
    checked and found already implemented; the rest — federation/
    civilization/century-scale specs and a parallel "RFC-graph
    self-governance" architecture series plus a formal axiomatic-kernel proof
    series — was explicitly named and deferred as out of scope for
    broodforge's actual product. See `SESSION_HANDOFF.md`'s third
    `milestone_checklist` block and the audit's F3 "Resolution" annotation
    for the full record. **Do not re-run this analysis** — read its output.
  - **(Added 2026-06-07, follow-up to F3 closure — now CLOSED, 2026-06-08,
    seventh milestone):** The operator partially walked back the formal
    axiomatic-kernel deferral above — not asking to implement it, but
    observing that beneath its category-theoretic framing it names two real
    concerns (provable recovery readiness; observed-state ↔ intent-manifest
    conformance) and asking for a draft of "what to do with these." A
    **DRAFT SKETCH** ("Recovery-Readiness Conformance") was written into
    `ROADMAP.md`'s "Proposed Future Work" section: a translation table
    mapping each formal construct to the broodforge mechanism that already
    plays its role informally, plus identification of **one** genuinely new
    artifact worth scoping further (a `recovery-readiness-certificate.json`
    composing existing scores/hashes/drill results). **The operator reacted
    on 2026-06-08** — "Recovery-Readiness Conformance → Scope as Phase 1.I"
    — and the sketch is now **Phase 1.I** (AD-059), promoted in place with
    the translation table preserved as supporting analysis. This thread is
    closed; no further reaction is awaited on this item.
  - F4 (an OBSERVATION, not a finding requiring action) stands as recorded —
    see the audit's status banner.
  - One deferred technical item from the prior (now-superseded)
    `docs/SESSION-HANDOFF.md`: "(A1) sys.path coupling in html workbooks +
    collect_tier2 that import from doc-gen/renderers via sys.path.insert —
    requires package restructure into a proper Python package. Low urgency —
    works correctly today."

- **blockers**: None known. (No BLOCKER-classified finding exists in the most
  recent PAP-AUDIT of broodforge; broodforge's own `docs/AUDIT-FINDINGS.md`
  cycles likewise show no open blocking item as of the last entry.)

- **next_action**: **(Updated — eighth milestone: operator directed
  implementation of all four scoped phases in order; sweep + Phase 1.H +
  Phase 1.I DONE and committed/pushed, Phase 1.K is up next.)** Order given:
  (1) repo-wide `datetime.now()`/`utcnow()` clock-injection sweep — **DONE**,
  commit `c1aef50` (fixed `remediation_executor.build_failure_package` + 9
  `_exec_*` handlers, `continuous_assessment.collect_pbs_state_update`,
  `platform_state_collector.compute_platform_health`/`platform_state_to_dict`;
  full suite 4134 passed before Phase 1.H's own additions); (2) **Phase 1.H**
  (AD-057, Pre-Install Forge Package and Image Builder) — **DONE**:
  `generate-bootstrap-image.py` + `_image_builder.py` produce a
  `bootstrap-image-{cell_id}-{ts}.tar.gz` staging bundle (`answer.toml`
  derived from forge-manifest.json, embedded forge package, first-boot
  systemd hook, hash manifest + AD-051 HTML twin, operator README); root
  password is a fresh single-use AD-039/AD-043-pattern discovery passphrase,
  never fixed/predictable/KeePass-stored. `FORGING.md`/`.html` gained
  "Step 0 — Build pre-install media (optional)". 62 new tests; full suite
  4140 passed, 1 skipped (4 pre-existing unrelated `test_opentofu.py`
  failures, confirmed present on `main` beforehand). FEATURE-HISTORY
  updated; commit pending alongside this PAP-state update.

  (3) **Phase 1.I** (AD-059, Recovery-Readiness Conformance Certificate) —
  **DONE**: `_recovery_readiness_certificate.py` +
  `generate-recovery-readiness-certificate.py` compose
  `recovery-readiness-certificate.json` + AD-051 HTML twin from existing
  evidence (`manifest_hash`/`graph_hash` SHA-256 over canonical JSON, the
  real `overall_score`/`overall_score_reason`/component-counts from
  `score_graph()`, a drift summary from `compute_drift()`, and the latest
  `DrillRecord` summary); `replay-snapshot.py` recomputes and asserts a
  stored snapshot's recorded hashes still match (ran clean — `[PASS]` —
  against the real `assessment_2026-05-29_02_05_00` snapshot);
  `history/index.py::build_index()` now records both hashes per snapshot
  entry; `compute_drift()` gained `now_fn` injection (an incidental
  clock-injection fix — `doc-gen/` wasn't in the original sweep's grep
  scope); a "Human Intervention Boundary" subsection was added to
  `ROADMAP.md`. **Premise correction**: AD-059 claimed RRS/ACS/DCS/CRS/OSS
  scores "already exist in readiness.py" — they don't (only a single
  `overall_score` does; the five-letter scheme is unpopulated UI code in
  `broodforge_dashboard.py`); the certificate composes the real signal and
  documents this finding inline rather than inventing the scheme AD-059
  itself says is unneeded. 56 new tests; full suite 4252 passed, 1 skipped
  (same 4 pre-existing `test_opentofu.py` failures). FEATURE-HISTORY +
  ROADMAP.html updated; commit pending alongside this PAP-state update.

  **Remaining in the operator's given order**: (4) **Phase 1.K** (AD-061,
  Scoped Vault Hierarchy + User Provisioning) — UP NEXT;
  (5) **Phase 1.J** (AD-060, Hypervisor Recovery Constrained Accounts +
  Pre-Generated Spawn Media — must respect the **firm AD-060 constraint**:
  no autonomous pathway may read/wield full root against live hypervisors;
  only node-spawn and phoenix-setup temporary credentials are exempted).
  After each phase: update FEATURE-HISTORY + HTML twin and PAP-state
  (this file, SESSION_HANDOFF, CURRENT_STATE), run full suite, commit, push.

  No open audit finding remains that requires action (F1/F2/F3/the
  Recovery-Readiness open-thread all closed and committed; F4 is an
  observation requiring no action). If the operator gives new direction on
  any of the four scoped phases, treat it the same way AD-058's gap was
  handled: pick it up, scope it precisely to what was asked, write the
  cycle into `docs/FEATURE-HISTORY.md`, and update this corpus again.

---

## Provenance

Created as part of
[`pap/revisions/2026-06-07_session-continuity-transition-to-pap.md`](../revisions/2026-06-07_session-continuity-transition-to-pap.md) —
the transition that moved broodforge's own session-continuity practice from
its pre-PAP prototype mechanisms (`.ai/AI_AGENT_BOOTSTRAP.md`,
`docs/SESSION-HANDOFF.md`) onto PAP-State's formally-specified Resume Block
and Session Handoff Protocol. Update this block at minimum at every session
boundary and at every major milestone, per the schema's `update_trigger`.
