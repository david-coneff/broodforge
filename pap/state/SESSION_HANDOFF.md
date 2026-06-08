# Session Handoff — broodforge

Instance of [PAP-State §4](../modules/PAP-State/PAP-State.md#4-session-handoff-protocol)
(Session Handoff Protocol), conforming in shape to
[`session-handoff.schema.yaml`](../modules/PAP-State/schemas/session-handoff.schema.yaml).
This is **broodforge's own** session-handoff artifact — the durable,
self-contained "what a cold reader needs to resume broodforge's
codebase-development work" record, now governed by PAP per
[`pap/revisions/2026-06-07_session-continuity-transition-to-pap.md`](../revisions/2026-06-07_session-continuity-transition-to-pap.md),
which also explains *why* this artifact now exists here rather than at
`docs/SESSION-HANDOFF.md` (its pre-PAP, now-superseded predecessor — moved,
not deleted, to `docs/deprecated/SESSION-HANDOFF.md`, with full prior-session
history intact and recoverable).

**On scope**: this handoff concerns broodforge's own *development* continuity
— the "revision protocol for the codebase itself" the operator named when
commissioning this transition. It is not, and must not become, a record of
broodforge's *infrastructure-remediation* operations (the planner → queue →
executor → policy loop the platform runs against the systems it manages) —
that is the platform's product behavior, governed by its own operational
artifacts (`bootstrap-state.json`, `FORGING.md`, the dashboard, etc.), not by
this development-side ledger. Keeping that line visible here is itself part
of what this transition exists to make durable.

---

- **status**: IDLE — no active codebase-development session. All roadmap
  milestones and intelligence tracks are complete per `.ai/CURRENT_STATE.md`
  / `.ai/NEXT_STEPS.md`; the platform's own next named action is operational
  ("deploy to hardware"), not developmental. **Four** *proposed*
  (not-started) development items now exist — Phase 1.H, 1.I, 1.J, and 1.K,
  see below — each scoped with its own AD; none is mandatory. **Updated
  2026-06-08** (this artifact's own `update_trigger` — PAP-State §3/§4 —
  fired at the seventh milestone described below, the day's third update).

- **objective**: None currently active. Three threads have completed since
  this file was first written: (1) the continuity-transition this file is the
  centerpiece of (see `milestone_checklist`'s first six items, all `[x]`);
  (2) **resolving PAP-AUDIT findings F1 and F2**; and (3), **the `new/`
  corpus analysis (F3)** — initially deferred, then explicitly un-deferred by
  direct operator instruction ("Analyze the `new/` directory ... and
  integrate relevant content into the roadmap and architecture"). See the
  new `milestone_checklist` entries and `key_decisions_and_insights` below.
  Before all three: the last active development objective (per the
  now-superseded `docs/SESSION-HANDOFF.md`'s final entry) was a "deep
  architecture-vs-docs audit + interactive HTML" pass, completed and closed
  with "4000 passed, 1 skipped (Windows-only). No regressions."

- **source_materials** (what a resuming agent should read, and why):
  - [`pap/state/RESUME_BLOCK.md`](RESUME_BLOCK.md) — the current portable
    save-state this handoff carries (see `resume_block_ref`, below);
    read it first.
  - [`pap/audits/2026-06-07_broodforge-pap-audit.md`](../audits/2026-06-07_broodforge-pap-audit.md) —
    **updated same day**: F1 and F2 are now closed (in-place "Resolution"
    annotations on each finding, plus a status banner near the top of the
    file); F3 remains open and explicitly deferred by the operator; F4
    (an OBSERVATION) stands as recorded. Read the status banner first.
  - `.ai/CURRENT_STATE.md`, `.ai/NEXT_STEPS.md`, `.ai/decisions.md`,
    `.ai/context.md` — broodforge's own canonical governance/continuity
    corpus; still its own sovereign authority (PAP does not supersede it —
    `PAP_CHARTER.md` §2.3).
  - `docs/deprecated/SESSION-HANDOFF.md` — the full pre-transition session
    history (1142 lines: "Previous Session Work," "Remaining Work,"
    "Previous Sessions," test-count history, architecture notes). Preserved
    in full, moved (not deleted) — read it for *historical* development
    context; do not extend it further (extend this file instead).
  - `new/claude prompt.txt` and the ~165 chapter/spec/RFC documents alongside
    it — **no longer a deferred corpus (F3 is now CLOSED)**. The operator
    explicitly un-deferred this and commissioned its analysis ("Analyze the
    `new/` directory ... and integrate relevant content into the roadmap and
    architecture"). The analysis is done: see `ROADMAP.md`'s "Proposed Future
    Work — from `new/` corpus analysis" section (Phase 1.H — Pre-Install
    Forge Package and Image Builder, the one concrete item integrated, plus
    "What was reviewed and found already covered" and "What was deferred and
    why" — the latter explaining, by name, why the bulk of the corpus
    — federation/civilization/century-scale specs, the RFC-graph
    self-governance series, and the formal axiomatic-kernel proof series —
    stays out of scope), `ARCHITECTURE.md` AD-057, and this audit's F3
    "Resolution" annotation. **Do not re-run that analysis** — read its
    output instead; if something looks missed, that is a finding to record
    against the existing analysis, not grounds to redo it from scratch.

- **key_decisions_and_insights** (conclusions already reached — do not
  re-derive):
  - Broodforge's pre-PAP session-continuity mechanisms
    (`.ai/AI_AGENT_BOOTSTRAP.md`'s "read in this order" bootstrap and
    `docs/SESSION-HANDOFF.md`'s rolling session log) were genuine, working
    *prototypes* of exactly what PAP-State §1/§3/§4 now formally specify —
    not mistakes, and not to be treated as such. `docs/SESSION-HANDOFF.md`'s
    own "M3" entry shows broodforge's maintainers had *already* once
    deduplicated a stray copy (`.ai/SESSION-HANDOFF.md`, "stale duplicate")
    — direct evidence the underlying continuity-tracking *need* was real and
    recurring well before PAP arrived to formalize it.
  - This transition does **not** put broodforge "under PAP governance" in
    the constitutional sense — `.ai/PROJECT_CHARTER.md` remains broodforge's
    sovereign top-level authority (`PAP_CHARTER.md` §2.3, `pap/README.md`).
    What transitions is narrower and more concrete: the specific *mechanism*
    broodforge's own maintainers use to track and hand off codebase-
    development continuity, by direct operator instruction, because PAP's
    formal version of that mechanism is now available and superior in
    exactly the ways a prototype is normally superseded by a matured form
    of the same idea (named shape, machine-form schema, explicit
    update-triggers, a Resume Block it doesn't redefine but points to).
  - "Broodforge's own revision protocol for its codebase" is explicitly
    **not** the same thing as "broodforge's remediation process for failing
    nodes and the general functions it performs" — the operator drew this
    line explicitly when commissioning this transition, and it is the single
    most important distinction this artifact and its sibling `RESUME_BLOCK.md`
    exist to keep visible to a future cold reader.
  - **(Added same day, second milestone) F1 and F2 were textual ambiguities,
    not real contradictions** — both dissolved the moment broodforge's
    operator (the Charter's and the Decision Record's own author) supplied
    the original-intent definitions neither document had recorded: the
    Charter's "no subjective judgments / recommendations" language named
    *specific-hardware* recommendations only (not the platform's own
    deployment-strategy decisions), and AD-034's "never takes autonomous
    action" was always meant to read "...without defined safeguards and
    recoverability." Recorded as in-place annotations (Charter Scope note,
    AD-034 Amendment, AD-040, audit Resolution notes) — **originals preserved,
    nothing silently rewritten**. Do not re-litigate either question; both
    are closed, by the only authority able to close them.
  - This is a concrete, worked example of something `pap/audits/2026-06-07_broodforge-pap-audit.md`'s
    own APDRP review anticipated in the abstract (its Falsification
    perspective named "if 'subjective judgment' were defined elsewhere in a
    narrower sense, this finding would dissolve" as the one thing that would
    undo F1) and could not, by itself, resolve — some questions an audit can
    only frame; only the artifact's author can answer them. Worth remembering
    the next time a finding's resolution looks like it depends on intent
    rather than evidence: name that plainly, and ask, rather than guess.
  - **(Added same day, third milestone) F3 — "deferred" was a snapshot of
    operator intent at a moment in time, not a permanent classification.**
    The same operator who said "this is deferred for the moment" later, in
    a separate instruction, explicitly un-deferred it — *with* scoping
    guidance baked into the instruction itself ("some sections get into
    highly speculative, philosophical territory... do NOT deeply integrate
    or analyze those — defer them. Focus only on items that have a realistic
    software implementation path"). The resulting analysis found the ~165
    document corpus to be overwhelmingly *not* about broodforge's actual
    product (a Proxmox/k3s home-lab platform) — most of it describes either
    governing the specification corpus itself (a parallel "RFC graph"
    self-governance architecture: Coherence Ledger, Master Control Plane,
    Orchestration Kernel, etc.) or multi-generational/civilizational
    continuity concerns at a scale far beyond broodforge's charter. Exactly
    **one** concretely implementable, additive idea surfaced cleanly: a
    pre-install "Image Builder" that closes the gap between "operator already
    has Proxmox installed" (today's only path) and "bare metal, nothing
    installed yet" (what Chapter 16/Spec 70/148 name as the unsolved case) —
    recorded as proposed Phase 1.H. Three other named areas (documentation
    engine, runbook generation, UI/visualization) were checked against the
    existing codebase and found *already* substantially implemented — a
    useful confirmation that broodforge's own independent design arrived at
    similar conclusions to this corpus on the parts that actually overlap.
    Don't re-derive any of this; read `ROADMAP.md`'s "Proposed Future Work"
    section and `ARCHITECTURE.md` AD-057 for the full record.
  - **(Added 2026-06-08, seventh milestone) The operator's reaction to all
    three draft sketches — verbatim, itemized, and now fully written up.**
    After the three draft sketches sat for one day awaiting reaction (per
    each one's own "Status: draft for discussion — awaiting operator
    reaction" framing, and `RESUME_BLOCK.md`'s explicit "let the operator
    react, not pre-emptively promote" guidance), the operator returned with
    an instruction that named exact decisions for all three at once:
    *"The operator has made decisions on all three roadmap sketches.
    Incorporate them into ROADMAP.md, ARCHITECTURE.md, and PAP-state."*
    The decisions, in summary (full text is in the commissioning instruction
    itself, preserved in this session's transcript and reflected verbatim in
    `.ai/decisions.md`'s combined AD-059/060/061 entry):
    1. **Recovery-Readiness Conformance → scoped as Phase 1.I**, with the
       certificate generator built additively onto `readiness.py`/`drift.py`/
       `dependencies.py`/snapshot store/Phase 12 drills, plus an AD (AD-059).
    2. **Hypervisor Recovery Credentials → "middle path accepted, with
       clarifications."** The operator went *beyond* simply endorsing the
       sketch's recommendation — they elevated it to **"a firm architectural
       constraint"**: *"The operator explicitly rules out any autonomous
       pathway that can read and wield full root credentials against live
       hypervisors — write this as a firm architectural constraint (AD)."*
       Two exceptions were *named by the operator themselves*, not proposed
       by the sketch: node spawning (already partly in place) and — newly —
       **phoenix recovery packages**, where *"a temporary root credential
       used only during the phoenix setup phase, with a hard requirement
       that the operator changes it after the setup session completes"* is
       explicitly sanctioned and scoped into the phoenix package design.
       The three-part middle path (forced-command recovery accounts,
       human-unlock break-glass root, pre-generated spawn-media credentials
       with human authorization) is *"accepted as stated."* Recorded as
       **Phase 1.J** + **AD-060** — and AD-060 is written as a constraint
       binding on *all* future development, not scoped narrowly to Phase
       1.J, exactly because the operator framed it as architectural, not
       merely a recommendation for one feature.
    3. **Granular Secret Access Silos → "expand and scope."** The base
       "multiple derived vaults" design is kept, plus two operator-added
       requirements not present in the original sketch: *"Higher-tier vaults
       must include records of the access credentials for lower-tier
       scopes"* (a vault-of-vaults recordkeeping property — so a god-mode
       operator can always recover a scoped vault's passphrase from their
       own vault) and *"A mechanism for creating users at the VM level and
       Proxmox level, with default templates corresponding to the proposed
       scope divisions."* Recorded as **Phase 1.K** + **AD-061**.
    All three are now written into `ROADMAP.md` (each sketch converted
    in-place to a scoped-phase block — heading, status line, and closing
    paragraph rewritten; the underlying analysis preserved as "source of
    this analysis" supporting material, nothing deleted), `ARCHITECTURE.md`
    (AD-059/060/061 added in sequence after AD-058, version-header date
    bumped), and `.ai/decisions.md` (one combined entry). **Do not re-derive
    or re-evaluate any of these three decisions** — they are the operator's
    own exact words, already incorporated; if something looks like it needs
    refinement, that is a *new* instruction to seek, not grounds to second-
    guess what was already decided.

- **milestone_checklist**:
  - [x] Identify broodforge's pre-PAP session-continuity prototype mechanisms
        (`.ai/AI_AGENT_BOOTSTRAP.md`, `docs/SESSION-HANDOFF.md`) and confirm
        neither had crept into `.ai/PROJECT_CHARTER.md` itself (it had not —
        the charter is 269 bytes, four Purpose/SHALL/SHALL-NOT lines, no
        mention of either mechanism).
  - [x] Instantiate PAP-State's formal replacements in broodforge's own
        (previously-empty) `pap/state/`: this file and `RESUME_BLOCK.md`.
  - [x] Move (not delete) `docs/SESSION-HANDOFF.md` to
        `docs/deprecated/SESSION-HANDOFF.md`, preserving its full session
        history and git lineage (`git mv`), with an in-place banner pointing
        forward to this file.
  - [x] Rewrite `.ai/AI_AGENT_BOOTSTRAP.md`'s "read in this order" / "then"
        steps to route through PAP's Startup Protocol and this file, instead
        of the retired `docs/SESSION-HANDOFF.md`.
  - [x] Repoint `README.md`'s "latest session context" pointer to this file.
  - [x] Record the transition as a Decision Record in broodforge's own
        `.ai/decisions.md` (AD-039) — so a reader of broodforge's governance
        corpus *alone*, with no knowledge of `pap/`, can still discover that
        and why this changed.
  - [x] Write the full transition record in
        [`pap/revisions/2026-06-07_session-continuity-transition-to-pap.md`](../revisions/2026-06-07_session-continuity-transition-to-pap.md)
        (evidence, rationale, migration steps, what is — and is not —
        in scope, APDRP-style review of the one real risk this kind of
        change carries: silent loss of historical continuity content).

  **— second milestone, same day: resolving PAP-AUDIT F1/F2 —**
  - [x] Operator supplied original-intent clarifications for both findings
        (quoted verbatim in `AD-040` and in each finding's Resolution
        annotation) — directly, unprompted by any question from this side;
        recorded as received, not paraphrased.
  - [x] Added an in-place Scope note to `.ai/PROJECT_CHARTER.md` (original
        four-item SHALL-NOT list left intact) recording the
        specific-hardware-vs-deployment-strategy line the operator drew.
  - [x] Added an in-place Amendment to `AD-034` in `.ai/decisions.md`
        (original Date/Decision/Rationale left intact) stating the corrected
        operative rule: autonomous action licensed when bounded by
        safeguards and recoverable.
  - [x] Recorded both as one coordinated act, `AD-040`, in `.ai/decisions.md`
        — quoting the operator's clarifications verbatim, cross-referencing
        both in-place amendments and the audit findings they close.
  - [x] Annotated `pap/audits/2026-06-07_broodforge-pap-audit.md` in place:
        a status-update banner near the top; "Resolution" notes on F1 and F2
        (original finding text untouched); an APDRP addendum tying the
        Falsification perspective's named dissolution-condition to what then
        actually happened; strikethrough-preserved "Summary of suggested
        work" entries showing suggested-vs-actual remedy for a future reader.
  - [x] Updated this file and `RESUME_BLOCK.md` to reflect the F1/F2
        resolution milestone.

  **— third milestone, same day: analyzing and integrating the `new/`
  corpus (closing F3) —**
  - [x] Operator issued a direct, scoped instruction to analyze `new/` and
        integrate relevant content into `ROADMAP.md`/`ARCHITECTURE.md`,
        explicitly un-deferring F3 — with scoping guidance built directly
        into the instruction (integrate items with "a realistic software
        implementation path... pre-install forge package creation, any
        management tooling, monitoring, orchestration, or documentation
        generation features"; defer "highly speculative, philosophical
        territory — e.g., cross-civilization knowledge transfer, 100-year
        planning scenarios").
  - [x] Read `pap/state/SESSION_HANDOFF.md`/`RESUME_BLOCK.md` (this file's
        own prior state — confirming F3's "deferred" framing) and the
        existing `ROADMAP.md`/`ARCHITECTURE.md`/`.ai/CURRENT_STATE.md`
        as the source-of-truth baseline before editing either.
  - [x] Surveyed all ~165 documents in `new/` by filename + extracted and
        read full text of the ~22 most plausibly relevant ones (bootstrap/
        first-node architecture, forge package lifecycle, documentation
        engine, runbook generation, reference UI/CLI/API, observability,
        orchestration/control-plane, plus the corpus's own "how to read me"
        entry document `BroodForge_Synthesis_Entry_For_Claude_Analysis_v1.docx`
        and `broodforge.json`) and three "axiomatic kernel" PDFs, to confirm
        the speculative/governance-of-specs framing extended through that
        whole series before deferring it.
  - [x] Identified exactly one concretely-implementable, additive gap: a
        pre-install "Image Builder" — closing the difference between
        broodforge's current only-supported path ("operator already has
        Proxmox VE installed on the target host," per `FORGING.md`'s
        prerequisites) and what Chapter 16/Spec 70/148 name as the unsolved
        case ("a BroodForge environment should be creatable without
        requiring an existing BroodForge deployment... Image Builder
        Architecture may generate ISO images, USB installation media").
        Recorded as proposed **Phase 1.H — Pre-Install Forge Package and
        Image Builder** in `ROADMAP.md`'s new "Proposed Future Work" section,
        and as **AD-057** in `ARCHITECTURE.md`.
  - [x] Cross-checked three other corpus areas (Documentation Engine /
        Spec 60, Runbook Generation / Spec 82, Reference UI-Visualization /
        Spec 88, Reference API-CLI / Spec 87) against the existing codebase
        (`doc-gen/`, `dependencies.py`, `capability_state.py`,
        `failure_domain.py`, Phase 9/10 phoenix + operational documentation)
        and recorded them as "already covered, no gap" rather than silently
        dropping them — visible in `ROADMAP.md`'s "What was reviewed and
        found already covered."
  - [x] Recorded, by name, what was deferred and why — federation/economic/
        marketplace/trust specs (138–145), knowledge-civilization/century-
        scale/succession specs (116–132), the RFC-graph self-governance
        series (Coherence Dashboard, Master Control Plane, Orchestration
        Kernel, Coherence Ledger, Bootstrap Order Generator, Post-Bootstrap
        Verification — these govern *the spec corpus as a system*, a
        different problem than the one broodforge solves), and the formal
        axiomatic-kernel/category-theoretic proof PDF series (v1.5–v1.27,
        plus `broodforge.json`'s own `fidelity_translation_only` /
        "forbidden: spec_rewrite, semantic_reinterpretation" framing, which
        reads as "implement me verbatim as a parallel system" rather than
        "mine me for ideas") — in `ROADMAP.md`'s "What was deferred and why."
  - [x] Annotated `pap/audits/2026-06-07_broodforge-pap-audit.md` in place:
        updated the status banner to record F3 as closed, and added an
        in-place "Resolution" annotation on F3 itself (original finding text
        untouched), addressing both halves of the original RISK (loss —
        `new/` is now referenced from governed artifacts; silent scope
        ambiguity — `ROADMAP.md`/`ARCHITECTURE.md` now name what in `new/`
        is, and is not, part of broodforge's forward direction).
  - [x] Updated this file and `RESUME_BLOCK.md` to reflect the new state —
        the very update this protocol's `update_trigger` calls for at every
        major milestone (you are reading the result of that update now).

- **last_completed_step**: (Updated — seventh milestone, same day, 2026-06-08.)
  The operator returned with itemized, exact decisions on all three draft
  sketches that had sat "awaiting operator reaction" since the fourth
  milestone (`new/` corpus follow-up): *"The operator has made decisions on
  all three roadmap sketches. Incorporate them into ROADMAP.md,
  ARCHITECTURE.md, and PAP-state. Here are the exact decisions"* — followed
  by the full, itemized text quoted in `key_decisions_and_insights` above.
  This was a **documentation/scoping task, not a code change** — promoting
  three sketches to scoped phases plus ADs, exactly as specified:
  - **`ROADMAP.md`**: each of the three "DRAFT SKETCH" sections rewritten
    in place — heading retitled to its new phase number and name (**Phase
    1.I** — Recovery-Readiness Conformance; **Phase 1.J** — Hypervisor
    Recovery: Constrained Accounts and Pre-Generated Spawn Media; **Phase
    1.K** — Granular Secret Access Silos: Vault Hierarchy and User
    Provisioning), status line changed from "draft for discussion — NOT a
    scoped phase" to "scoped 2026-06-08 — proposed, not started," a
    "Proposed scope" checklist added (mirroring Phase 1.H's format —
    `- [ ]` items, "explicitly out of scope" callouts where relevant, an "AD
    reference" line), and each closing "if the operator wants to proceed"
    paragraph rewritten to record that the direction was confirmed. The
    underlying analysis in each sketch (the formal-concept translation
    table; the hypervisor-credential risk evaluation; the vault-hierarchy
    design rationale) was preserved verbatim as "source of this analysis"
    supporting material — nothing deleted, only reframed from "draft,
    awaiting reaction" to "scoped, operator-confirmed." The "Last updated"
    stamp at the top of `ROADMAP.md` was rewritten to name all three new
    phases and their ADs.
  - **`ARCHITECTURE.md`**: three new AD rows added in sequence —
    **AD-059** (Recovery-Readiness Conformance Certificate, Phase 1.I),
    **AD-060** (the firm architectural constraint — *"no autonomous pathway
    may read and wield full root credentials against live hypervisors"* —
    plus its two named exceptions and the accepted three-part middle path,
    Phase 1.J), and **AD-061** (Granular Secret Access Silo Vault Hierarchy
    and User Provisioning, including the operator's two expansions, Phase
    1.K). Placed correctly in numeric sequence *after* AD-058 (a small
    self-correction mid-edit: they were first appended after AD-057/before
    AD-058 by an ordering slip, caught and fixed before this record was
    written — the table now reads 057→058→059→060→061 in order). The
    version-header `Date:` line was updated to name all three new ADs.
  - **`.ai/decisions.md`**: one combined entry — "AD-059/AD-060/AD-061:
    Three Roadmap draft sketches promoted to scoped phases" — recording the
    decision, rationale (each sketch was written specifically to be reacted
    to; the operator's itemized response closes that thread cleanly), and
    consequences (AD-060 in particular binds *all* future development
    touching hypervisor root credentials, not just Phase 1.J).
  - **PAP-state** (`RESUME_BLOCK.md`, this file): both updated to record
    the seventh milestone, close the "Recovery-Readiness Conformance" open
    thread named in `active_risks`, and rewrite `active_objective`/
    `next_action` to reflect that **zero items now remain in "draft sketch,
    awaiting operator reaction" status** — all four proposed development
    items (1.H/1.I/1.J/1.K) sit at the same "scoped, proposed, not started"
    tier.
  No code was touched — this is a pure documentation/scoping milestone, so
  **no test run was required** (per the operator's own execution rule: "Run
  tests if any code is touched; otherwise just doc/state updates are fine").
  Recorded as a GAP-FILL-adjacent, USER-REQUESTED cycle (the operator
  supplied the decisions; the write-up faithfully incorporates them) in
  `docs/FEATURE-HISTORY.md` per the standing `feature_revision_process`
  convention — see that file's newest dated entry for the full record.

  **Before this (sixth milestone, same day, earlier session):**
  Resumed per the operator's standing instruction to "continue broodforge work
  using PAP-state." On reading this file's own `next_action` (below, from the
  fifth milestone) plus the working tree, found a prior session had left
  exactly the gap this file already named — AD-058's "MFA selection is still
  CLI-flag-only... inherited silently rather than seen and confirmed" — mid-
  flight as **uncommitted partial edits** (`forge_keepass_init.py`,
  `forge_planner.py`, `guided_setup.py`: `security.mfa_method` field added to
  guided setup, `build_forge_manifest()` reading it into
  `keepass_config.mfa_method`, and a local `mfa_method` variable computed in
  `generate_keepass_init_config()` — but never passed to the returned
  `KeePassInitConfig`, so the wiring was incomplete and untested). Completed
  it rather than starting over or discarding:
  - Added `mfa_method=mfa_method` to the `KeePassInitConfig(...)` constructor
    call in `forge_keepass_init.py` (the one missing line closing the chain
    guided-setup → forge-manifest → KeePass-init-config).
  - Added test coverage for the now-complete chain: `test_guided_setup.py`
    (`test_suggest_mfa_method_is_totp`, four `check_conflicts` cases —
    totp/yubikey clean, `"none"` warns per AD-058, `"sms"` rejected as
    unsupported) and `test_forge_planner.py`
    (`test_mfa_method_defaults_to_totp`, `test_mfa_method_from_guided_session`
    — confirms an explicit `"yubikey"` choice recorded via
    `record_manual_field` propagates all the way to
    `manifest["keepass_config"]["mfa_method"]`).
  - Ran the full suite before declaring done (standing practice — never trust
    "looks complete," verify): found **one pre-existing failure** unrelated to
    this work — `test_phase19_federation.py::test_expiring_soon_still_valid`
    — confirmed via `git stash` that it failed identically on the untouched
    `main` tip, i.e. **not a regression from this session's edits**, but a
    latent bug the calendar had just walked into: `verify_trust()` in
    `federation_state.py` checked `relationship.is_expired` (a property that
    calls real `datetime.now(timezone.utc)`) instead of comparing against the
    function's own injected `now_fn` — so a test fixture pinned to "now =
    2026-06-01" with an expiry of "2026-06-08" started failing the instant
    real UTC crossed that date. Fixed by computing the expiry comparison
    inline against the injected `now` (mirroring how the re-verification-age
    check just below it already does it correctly) rather than calling the
    real-clock property — a one-line-class fix to a real, dated bug, not a
    test-tuning hack. Named here explicitly because it is exactly the kind of
    "real-time call inside logic meant to be driven by an injected clock"
    defect that PAP/audit work has repeatedly flagged elsewhere in this
    codebase — worth a future grep sweep (`datetime.now(` / `datetime.utcnow(`
    outside of `now_fn` plumbing) if the operator wants to harden against the
    whole class, though that is **not** done here (scope discipline — fix the
    one bug found, name the pattern, don't go hunting beyond what broke).
  - Recorded the full cycle in `docs/FEATURE-HISTORY.md`
    (`2026-06-08_12_36_41 UTC`, GAP-FILL — closes a named follow-up, not a
    fresh operator request) and regenerated its HTML twin via
    `md_to_html.py --collapsible` (the now-established pattern from the prior
    milestone, keeping `test_meta_doc_sync.py`/`test_html_base_sync.py`
    green). Updated `.ai/CURRENT_STATE.md` to index the closure.
  Verified: full suite **3844 passed** (was 3843 passed + 1 pre-existing
  failure — both the new MFA-chain tests and the federation fix are included
  in that count; no regressions).

  **Before this (fifth milestone, same prior session):**
  The operator reacted to the "Hypervisor Recovery Credentials" sketch and,
  in the same message, issued two further direct instructions — both acted
  on immediately as "autonomous work that doesn't require operator
  decisions" once their shape was clear:
  1. **Endorsed** the constrained-recovery-account "middle path" from that
     sketch ("the middle path you suggest ... seems like the reasonable
     approach rather than storing root permanently in keepass") — recorded
     as confirmation; no further action required on that sketch itself.
  2. **New security-policy directive**: "for high level functions of any
     kind, we should be requiring 2nd factor authentication as a default,
     not just a password — the 2nd factor method should be limited to
     TOTP-authenticator or yubikey, not SMS based TOTP or email-based TOTP
     since this have greater vulnerability to being hacked." Investigation
     found broodforge **already has** a fully-implemented, fully-tested MFA
     mechanism (`proxmox-bootstrap/keepass_mfa.py` — TOTP per RFC 6238 +
     YubiKey HMAC-SHA1 challenge-response, 49 passing tests) that exactly
     matches this requirement (app/hardware-based, never SMS/email) — the
     gap was only that it **defaulted to off** (`mfa_method = "none"`) and
     was reachable solely via an undocumented `--mfa` CLI flag, with no
     guided-setup prompt surfacing the choice. Closed that gap with a
     minimal, additive default-flip (no new mechanism):
     - `KeePassInitConfig.mfa_method` default `"none"` → `"totp"`
       (`proxmox-bootstrap/forge_keepass_init.py`)
     - `--mfa` CLI flag default `"none"` → `"totp"`, with help text
       documenting *why* SMS/email are never offered as choices
     - `tests/unit/test_keepass_mfa.py::test_mfa_method_field_default`
       updated to assert the new default (was pinned to `"none"`)
     - **AD-058** added to `ARCHITECTURE.md`, recording the policy change,
       quoting the operator's instruction verbatim, explicitly stating the
       SMS/email exclusion as deliberate permanent design (not an oversight
       to revisit), and naming the one **gap noted, not yet closed**: MFA
       selection is still CLI-flag-only — `guided_setup.py`/`forge_planner.py`
       do not yet prompt for it interactively, so the new default is
       *inherited silently* rather than *seen and confirmed* — recorded as
       a proposed follow-up for a future session, not actioned now.
     Verified scope of the change with a codebase-wide grep for
     `mfa_method`/`--mfa` (confined to exactly the three files touched) and
     a broader sweep (`-k "keepass or mfa or forge_init or secrets"` — 152
     passed).
  3. **New formatting request**: "broodforge's roadmap should be revised to
     use collapsible sections, it's quite lengthy at this point" (confirmed:
     2459 lines). Found the exact tool already exists and is already proven
     elsewhere — `proxmox-bootstrap/md_to_html.py --collapsible` (wraps each
     `##` section in `<details>`/`<summary>`), already used to generate
     `docs/FEATURE-HISTORY.html`. Regenerated `ROADMAP.html` with it
     (`md_to_html.py ROADMAP.md ROADMAP.html --collapsible`) rather than
     hand-adding `<details>` blocks — both because it is the established
     pattern (consistent styling/toolbar/theme-toggle with
     `FEATURE-HISTORY.html`) and because **doing so closed a second, worse
     doc-drift gap than the one `test_meta_doc_sync.py` (added last
     milestone) checks for**: that test only compares date *stamps* — it
     turned out the prior hand-synced `ROADMAP.html` was missing entire
     `<h3>` sections (the three draft sketches existed in `ROADMAP.md` but
     not in its HTML twin), a content gap the stamp-only test cannot see.
     True regeneration guarantees content sync, not just stamp sync — a
     stronger remedy than the test alone for any doc that has a generator.
     (The same regeneration was applied to `docs/FEATURE-HISTORY.md` →
     `.html`, which had drifted similarly after this session's own edits to
     it — both now byte-faithful to their `.md` sources.) `docs/
     ARCHITECTURE.html` was checked and found to be a *different*,
     hand-authored document (no `doc-meta`/generator marker) — left as-is,
     not a candidate for this treatment. AD-058 was also folded into both
     `ARCHITECTURE.md`'s and `docs/ARCHITECTURE.html`'s "Updated:" stamps
     (previously named only AD-057), keeping `test_meta_doc_sync.py`
     semantically honest. Recorded all of the above — the MFA-default flip
     and the collapsible-roadmap regeneration — as a new dated cycle in
     `docs/FEATURE-HISTORY.md` (USER-REQUESTED, `unit`/`smoke`/`static`
     verification depths), per the operator's standing
     `feature_revision_process` convention.
  Verified: `tests/unit/test_meta_doc_sync.py` (2 passed),
  `test_html_base_sync.py` (paired, 4 passed together), and the broader
  `keepass or mfa or forge_init or secrets or meta_doc or html_base or
  roadmap or feature_history` sweep (156 passed) all green after every
  change in this milestone.

  **Before this (fourth milestone, same session):** Following direct
  operator instruction ("proceed with any autonomous roadmap/architecture
  work that you can that doesn't require my decisions, with the occasional
  session-handoff commit"), extended the draft-sketch thread with two more
  sketches and closed a doc-drift gap the operator spotted by inspection:
  - Added **DRAFT SKETCH — Hypervisor Recovery Credentials**: the operator's
    requested "thorough evaluation" of permanently storing Proxmox root
    passwords in KeePass, written up as a recommendation *against* an
    autonomous pathway that can wield full root against live hypervisors
    (named as the one line broodforge should not cross — unbounded blast
    radius, exactly the kind of autonomy the newly-amended AD-034/AD-040
    "bounded by safeguards and recoverability" framing was not meant to
    license), with a concrete middle path: constrained forced-command
    recovery accounts, full root as break-glass behind the *existing*
    human-unlock gate (AD-042, no new pathway), and pre-generated
    human-gated spawn-media credentials (the operator's own proposal,
    adopted as sound).
  - Added **DRAFT SKETCH — Granular Secret Access Silos for Human
    Operators**: the operator's question about tiered, hierarchically-scoped
    human access to secrets (service operator vs. "god-mode" sysadmin,
    scoped to cell/node/VM). Confirmed "god mode" is the right homelab
    default (operator's own framing); sketched a design — derive scoped
    sub-vaults from the canonical KeePass DB along the hierarchy
    `secret-registry.yaml` *already* encodes (`owning_cell`, `required_by:
    [host:X]/[vm:X]`) — that needs no new dependency and changes nothing
    about the trust-model foundations, because KeePass/KDBX has no native
    per-user role layer (named explicitly as the constraint that shapes the
    whole design).
  - Added **`tests/unit/test_meta_doc_sync.py`**, addressing the operator's
    *first* observation this session — "roadmap.html and roadmap.md... is
    not updated... we need to implement some way for changes to the
    broodforge codebase to also trigger its own internal process for
    updating its documentation." Investigation found the drift was worse
    than the operator's example: `ROADMAP.html` (stamped 2026-06-03 vs. the
    `.md`'s 2026-06-07) *and* `docs/ARCHITECTURE.html` (stamped 2026-06-02)
    *and* `ARCHITECTURE.md`'s own header (stamped 2026-05-31, stale relative
    to its own AD-057 entry from `bbc2bdd`) — three different stamps, none
    agreeing. Rather than build a markdown→HTML generator (these `.html`
    files are hand-styled with theme toggles/copy buttons — generating them
    would destroy that), added a drift-detection test mirroring the existing
    `test_html_base_sync.py` pattern: it extracts the version/date stamp
    from each `.md` and its `.html` companion and fails the suite if they
    disagree. Ran it — it failed immediately on the real drift (proving the
    mechanism works), then synced all three stamps and it now passes. This
    *is* the "trigger": broodforge's suite already runs every change cycle,
    so a doc edit that forgets its companion now turns it red immediately —
    the same self-documentation philosophy `doc-gen/drift.py` applies to the
    managed infrastructure, pointed at broodforge's own meta-docs.
  All three sketches are explicitly marked **draft / not phases / not ADs**
  — exactly the "autonomous work that doesn't require operator decisions"
  framing requested: they advance the roadmap's *thinking* without
  committing the operator to anything. `.ai/NEXT_STEPS.md` and
  `.ai/CURRENT_STATE.md` updated to index all three plus the new test.
  Before this: wrote the first **DRAFT SKETCH — Recovery-Readiness
  Conformance** (translation table mapping all 13 axiomatic-kernel/
  proof-system PDFs' formal constructs to existing broodforge mechanisms;
  identified the `recovery-readiness-certificate.json` artifact as the one
  genuinely new piece) — in direct response to the operator reconsidering
  part of the F3 deferral and asking to "start drafting what to do with
  these." Before *that*: wrote `ROADMAP.md`'s "Proposed Future Work — from
  `new/` corpus analysis" section (Phase 1.H, "already covered," "what was
  deferred and why"), `ARCHITECTURE.md` AD-057, and the audit's F3
  status-banner update + Resolution annotation (commit `bbc2bdd`); and,
  before that, the F1/F2 resolution milestone (`b0a05ce`) and the continuity
  transition itself (`6f0e9c8`) — see the earlier milestone-checklist blocks.

- **next_action**: **(Updated — eighth milestone, in progress.)** The
  operator gave a direct, ordered execution instruction: implement all four
  scoped phases (1.H → 1.I → 1.K → 1.J) plus a clock-injection cleanup item,
  fully autonomously, committing after each. Progress so far:

  1. **`datetime.now()`/`utcnow()` clock-injection sweep — DONE**, commit
     `c1aef50`/pushed. Fixed `remediation_executor.build_failure_package` +
     all 9 `_exec_*` action handlers (audit-trail `failed_at`, drill
     `due_at`/`added_at`), `continuous_assessment.collect_pbs_state_update`
     (`collected_at`), `platform_state_collector.compute_platform_health`/
     `platform_state_to_dict` (cert-expiry calc) — all now thread `now_fn`
     instead of calling the real clock directly. Cleaned up an odd
     `__import__("datetime")` lazy-import in `reconstruction-drill.py`.
     Several other suspicious call sites were checked and left alone with
     documented reasons (true CLI/HTTP leaf entry points with no `now_fn`
     anywhere in their call chain — see the agent's report for the full list).
  2. **Phase 1.H / AD-057 (Pre-Install Forge Package and Image Builder) —
     DONE**, commit pending. `generate-bootstrap-image.py` (CLI) +
     `_image_builder.py` (module) produce a `bootstrap-image-{cell_id}-
     {timestamp}.tar.gz` "staging bundle": `answer.toml` (Proxmox 8+
     automated-installer answer file derived from forge-manifest.json
     `host_identity`/`network_topology`, AD-049 fields — answered once),
     an embedded forge package (reuses `assemble_forge_package`), a
     first-boot systemd unit + installer script that runs `forge.sh`
     unattended, a hash/contents manifest + AD-051 HTML twin
     (`build_bootstrap_image_manifest_html` in `html_package_manifest.py`),
     and an operator README. **Honesty constraint honored**: explicitly
     documented (CLI banner, README, HTML manifest) as a *staging bundle*
     the operator combines with the official Proxmox VE ISO via
     `proxmox-auto-install-assistant` — broodforge does not download, mount,
     or redistribute Proxmox media (AD-040 reference-stack scope).
     **Root-password handling**: `generate_install_passphrase()` produces a
     fresh, single-use `Capital.boot.word.N` passphrase — same pattern as
     the AD-039/AD-043 Cloud-Init discovery password, never fixed/
     predictable/KeePass-stored, replaced by phase-03's vaulted credential,
     printed once at build time, documented as one-time-use everywhere.
     `FORGING.md`/`.html` gained "Step 0 — Build pre-install media
     (optional)". 62 new tests (`test_image_builder.py`); full suite 4140
     passed, 1 skipped (the same 4 pre-existing unrelated `test_opentofu.py`
     failures, confirmed present on `main` before any of this work).
     `docs/FEATURE-HISTORY.md`/`.html` updated with a new cycle entry.

  3. **Phase 1.I / AD-059 (Recovery-Readiness Conformance Certificate) —
     DONE**, commit pending. `_recovery_readiness_certificate.py` (module) +
     `generate-recovery-readiness-certificate.py` (CLI) compose a
     `recovery-readiness-certificate.json` + AD-051 HTML twin
     (`build_recovery_readiness_certificate_html` in
     `html_package_manifest.py`) out of evidence broodforge already
     produces: `manifest_hash`/`graph_hash` (SHA-256 over canonical
     sorted-key JSON of the manifest and `build_graph().to_dict()`), the
     real readiness signal (`overall_score`/`overall_score_reason`/
     component-score counts from `score_graph()`), a drift summary
     (severity + diff counts from `compute_drift()`), and the latest
     reconstruction-drill summary (outcome/accuracy/waves/gaps from
     `DrillRecord.to_dict()`). `replay-snapshot.py` recomputes a stored
     snapshot's hashes from its raw `manifest.json` and asserts they match
     `history/index.json`'s recorded values (exit 0 = conformance holds);
     ran it against the real `assessment_2026-05-29_02_05_00` snapshot —
     `[PASS]`. `history/index.py::build_index()` now records
     `manifest_hash`/`graph_hash` per snapshot entry (additive; lives in
     the regenerated index, not the raw historical `manifest.json`
     captures). `compute_drift()` gained `now_fn` injection for
     `generated_at` (was a direct-clock call `doc-gen/` missed in the
     sweep — fixed in passing, callers unaffected). A "Human Intervention
     Boundary" subsection was added to `ROADMAP.md`'s Phase 1.I block.
     **Premise correction, documented not chased**: AD-059 claimed
     "RRS/ACS/DCS/CRS/OSS scores already exist in readiness.py" — they
     don't; `score_graph()` produces one `overall_score` plus `components`,
     and the five-letter scheme exists only as unpopulated defensive code
     in `broodforge_dashboard.py`. The certificate composes the *real*
     `overall_score` signal and states this finding inline (`_READINESS_NOTE`,
     surfaced in the HTML) rather than inventing the five-category scheme
     AD-059 itself says is unneeded. 56 new tests
     (`test_recovery_readiness_certificate.py` + `test_replay_snapshot.py`);
     full suite 4252 passed, 1 skipped (same 4 pre-existing
     `test_opentofu.py` failures). `docs/FEATURE-HISTORY.md`/`.html` and
     `ROADMAP.html` updated.

  4. **Phase 1.K / AD-061 (Granular Secret Access Silos: Vault Hierarchy
     and User Provisioning) — DONE**, commit pending. Built as "more
     vaults derived from the one vault" — no broker, no ACL layer, no live
     KDBX manipulation, exactly AD-061's accepted design (the constraint:
     `.kdbx` is single-master-password, no native per-user role layer).
     `role-scope-registry.yaml` (new authoritative per-cell YAML, mirrors
     `secret-registry.yaml`'s documented-header style and sits beside it —
     a `data-model/` JSON-Schema pair would be disproportionate for a
     3-entry registry) declares named roles (`service-operator`/
     `node-sysadmin`/`god-mode`), glob-pattern scopes over
     `secret-registry.yaml`'s `owning_cell`/`required_by`/`secret_type`/
     `required_for` vocabulary plus an `excludes` denylist facet, and role
     holders. `_vault_hierarchy.py` + `derive-scoped-vault.py` (CLI) match
     entries against scope globs (`fnmatch`), compose a derived-vault
     *plan* — in-scope entries, a freshly-generated passphrase
     (`generate_master_password_suggestion()`), the AD-044-pattern
     KeePass record path `Vaults/{role}/{timestamp}/passphrase` for
     vault-of-vaults bookkeeping in the parent vault, and the
     `keepassxc-cli` command sequence an operator runs to build it
     (mirrors `forge_keepass_init.py::render_init_commands()` — broodforge
     never opens/writes binary `.kdbx` files anywhere, confirmed) — plus
     an AD-051 HTML twin (`build_scoped_vault_plan_html`). The `god-mode`
     tier is refused outright (`ValueError`) — deriving "everything" from
     "everything" under a weaker fresh passphrase would be a strictly
     worse duplicate. **Operator-directed expansions**: vault-of-vaults
     recordkeeping (`vault_record_path()`) and user-provisioning
     templates — `generate_vm_account_template()` produces an additive
     Cloud-Init account block in the exact shape
     `spawn_iac_generator.py::generate_cloudinit_user_data()` already
     emits, `generate_proxmox_account_commands()` produces templated
     `pveum user add`/`aclmod`/`user token add` sequences with role-tiered
     PVE roles. **Authorization model / revocation=rotate+reissue**
     documented as design statements (true by construction / honest
     non-guarantees) in the registry header, `describe_vault_plan()`, and
     HTML — deliberately *not* built as enforcement machinery (nothing to
     check that isn't already true by construction). Generated passphrases
     are shown once at CLI runtime only, never persisted — confirmed
     absent from JSON/HTML artifacts by test. Ran the CLI end-to-end
     against the real registries (`service-operator` → 9/11 entries,
     `pve01-*` denylisted). 40 new tests (`test_vault_hierarchy.py`); full
     suite 4292 passed, 1 skipped (same 4 pre-existing `test_opentofu.py`
     failures). `docs/FEATURE-HISTORY.md`/`.html` updated.

  5. **Phase 1.J / AD-060 (Hypervisor Recovery: Constrained Accounts and
     Pre-Generated Spawn Media) — DONE**, commit pending — the FOURTH AND
     FINAL phase, closing the milestone. AD-060 is a firm architectural
     SHALL-NOT ("no autonomous pathway may read or wield a permanent
     hypervisor root credential and act on a live hypervisor — root has
     no boundary by definition"), with exactly two narrow named
     exceptions (node-spawn discovery, phoenix-setup), both time-limited
     and requiring operator rotation after. Implemented all three
     accepted-design parts plus the phoenix extension:
     **(a)** `_recovery_accounts.py` (+ `setup_recovery_account.py` CLI,
     `build_recovery_account_plan_html` AD-051 twin) generates a
     `command="<menu-script>"`-gated `authorized_keys` line (plus
     `no-pty,no-port-forwarding,no-X11-forwarding,no-agent-forwarding`)
     and a fixed-menu POSIX-`sh` script (status/logs/vmlist/vmstart/
     vmstop) — structurally incapable of an arbitrary-shell escape:
     `$SSH_ORIGINAL_COMMAND` is matched against a fixed enumerated `case`
     of literal verbs only (never `eval`/`sh -c`/backticks), and the only
     operator-influenced value (VMID) is regex-validated
     (`^[0-9]{1,6}$`) before reaching `exec qm start/stop`; broodforge
     generates strings only, never installs/runs/connects through it.
     **(b)** `secret-registry.yaml` gains an optional
     `access_policy: break-glass-human-only` annotation (documented in
     its header schema) on `pve01-root-password`;
     `describe_break_glass_pointer()` surfaces only `id`/`keepass_path`/
     `description` (a location, never a value) for runbook display — "the
     runbook tells the operator where to look," the existing AD-042
     human-unlock gate unchanged. **(c)** `_image_builder.py` gains
     `build_pregenerated_spawn_media_record()` (runs the existing AD-043
     `generate_install_passphrase()` at *build* time, AD-060(c)) paired
     with a `pending_join_authorizations` state record (in
     `bootstrap-state.json`, the same recorded-operator-decision shape
     AD-041's autonomous-mode confirmation uses) that stores only a
     SHA-256 `passphrase_hash`, defaults `authorized: false`, and is
     flippable ONLY by the new human-operated `authorize-spawn-media-
     join.py` CLI (`--operator` required, refuses unknown/already-
     authorized bundles, never auto-flips). **(d)** `phoenix_playbook.py`
     gains `generate_phoenix_session_credential()` (mirrors
     `generate_temp_password`/`generate_install_passphrase` —
     `Capital.phoenix.word.N`) and `phoenix_session_credential_section()`,
     wired into `PhoenixPlaybookGenerator.build()` as a new
     `temporary_session_credential` section recording `scope:
     "phoenix-setup-session-only"`, a bounded `valid_window`, and a
     `rotation_requirement` stating *in the generated output itself* —
     "ROTATE THIS CREDENTIAL THE MOMENT THIS RECOVERY SESSION COMPLETES…
     broodforge does not and cannot autonomously verify or perform
     rotation (doing so would itself be the autonomous full-root pathway
     AD-060 forbids)." **Constraint-honored confirmation**: grepped
     `pve0.*root.*password|root-password|root_password` across
     `proxmox-bootstrap/*.py` (excl. tests) — every match is pre-existing
     (KeePass path-name generation, the AD-039 temp-credential exception,
     the AD-043 single-use discovery passphrase); no new/modified code
     reads a permanent root-credential value, confirmed by both the grep
     and structural guard tests in all three new test files
     (`TestConstraintHonoredNoRootCredentialReads`). 96 new tests
     (`test_recovery_accounts.py` 46, `test_spawn_media_authorization.py`
     27, `test_phoenix_session_credential.py` 23); full suite 4388
     passed, 1 skipped (same 4 pre-existing `test_opentofu.py` failures).
     `docs/FEATURE-HISTORY.md`/`.html` updated.

  **MILESTONE CLOSED** — all five operator-directed items now done in
  the specified order: datetime sweep, Phase 1.H (AD-057), Phase 1.I
  (AD-059), Phase 1.K (AD-061), Phase 1.J (AD-060). Remaining for this
  session: commit + push the Phase 1.J work and PAP-state updates (per
  the operator's standing `feature_revision_process` / "push on commit"
  preferences), then report a closing summary of everything implemented
  across the whole milestone — the operator's explicitly requested final
  action ("report a summary of what was implemented and committed vs.
  what remains").

  **`ROADMAP.md` "Proposed Future Work"** held zero items in "draft sketch,
  awaiting operator reaction" status entering this milestone — all four
  phases were already scoped with their own ADs; this milestone is executing
  them in the operator's specified order, not re-scoping them.

  Worth naming to the operator if they ask "what's left" or "anything you
  noticed": the **clock-injection bug class** — `verify_trust()`
  (sixth-milestone fix) and `compute_drift()` (this milestone's incidental
  fix) were both real-wall-clock calls that should have threaded `now_fn`.
  Both are now fixed; the original repo-wide sweep (commit `c1aef50`,
  first item above) covered `proxmox-bootstrap/` exhaustively, and
  `doc-gen/drift.py` is now also clean. No other instances are currently
  known, but a resuming agent should treat any newly-written
  `datetime.now(`/`utcnow(` call sharing a scope with an available
  `now_fn` as suspect by default — this is the third confirmed instance
  of the same class.

- **resume_instructions**:
  1. Read `RESUME_BLOCK.md` (this file's `resume_block_ref`) for the
     one-screen save-state.
  2. Read this file's `source_materials` list, in the order given, to avoid
     re-deriving anything in `key_decisions_and_insights`.
  3. Confirm the transition's milestone checklist is still all-`[x]` (i.e.,
     nothing has silently regressed — e.g., a future edit accidentally
     reintroducing a reference to the deprecated `docs/SESSION-HANDOFF.md`
     path). If anything has changed, that is itself a finding worth
     recording, not silently re-fixing.
  4. Pick up the `next_action` above, or escalate per
     [PAP-Core §6.2](../core/PAP-Core.md#62-escalation-and-disagreement-governance)
     if neither this file nor `RESUME_BLOCK.md` resolves what to do next.

- **resume_block_ref**: [`RESUME_BLOCK.md`](RESUME_BLOCK.md)

---

## Provenance

Written as the centerpiece artifact of
[`pap/revisions/2026-06-07_session-continuity-transition-to-pap.md`](../revisions/2026-06-07_session-continuity-transition-to-pap.md),
commissioned by direct operator instruction: *"address the fact that there
were prototype mechanisms for session-handoff, tracking progress, etc. that
left artifacts in the codebase prior to pap's introduction... they need to be
handed off to pap and removed from the broodforge infrastructure, since
revision protocols for the codebase itself of broodforge (not broodforge's
remediation process for failing nodes and general functions it should
perform) should transition to pap."* See that record for the full evidence
trail, the APDRP-style review of the transition itself, and the historical
content this file's predecessor (`docs/deprecated/SESSION-HANDOFF.md`)
preserves in full.
