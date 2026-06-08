# PAP-AUDIT — Broodforge (analytical use of PAP, not PAP self-audit)

| Field | Value |
|---|---|
| Audited artifact | Broodforge — the platform itself: its `.ai/` governance corpus, `docs/` history, code/subsystem inventory as evidenced in `CURRENT_STATE.md`, `decisions.md`, `context.md`, `NEXT_STEPS.md`, `docs/AUDIT-FINDINGS.md`, and the working tree's untracked content |
| Audited by | PAP-AUDIT (`pap/modules/PAP-AUDIT/PAP-AUDIT.md`, populated at commit `3f8b12d` / module content anchored at `bab96b0` per the source repository's `CANONICAL_PROTOCOL_INDEX.md`) |
| Readiness verdict | **`ready`** (no BLOCKER-classified finding — see "Verdict rationale" below) |
| Blocking findings | None |
| APDRP review ref | §"APDRP review" below (full four-perspective pass on this audit's central finding, F1) |
| Audited at | 2026-06-07 |

> **Status update (same day, recorded in place — original review text below
> is otherwise untouched)**: of the four findings this review registered,
> **F1 and F2 are now closed** — both were resolved hours after this review
> was delivered, by the one party with standing to resolve them: broodforge's
> own operator, who clarified original intent directly (see each finding's
> in-place "Resolution" annotation, and `.ai/decisions.md` `AD-040`). **F3
> remains open but explicitly deferred** by the same operator ("`new/` are
> some proposed revisions that need to be analyzed... this is deferred for
> the moment"). **F4** (an OBSERVATION, not an actionable finding) stands as
> recorded. The readiness verdict (`ready`) is unchanged — it never depended
> on F1/F2's resolution, since neither was ever BLOCKER-classified.

## Scope statement (read this first)

Per direct operator instruction: *"let's do a pap-audit from the installed pap
in broodforge's repository now. for analysis purposes, let's be clear that pap
itself is not the analysis subject, only the broodforge project that it lies
within. audit broodforge and generate a summary of suggested work."*

**The analysis subject is broodforge — not PAP.** This audit is run *using*
PAP-AUDIT's machinery (loaded from this repository's own populated `pap/`
copy) *against* broodforge's own state, exactly as `pap/README.md` describes:
the output below is **findings and recommendations offered to broodforge's own
governance** (`.ai/decisions.md`, `.ai/NEXT_STEPS.md`,
`.ai/PROJECT_CHARTER.md`, or wherever broodforge's maintainers judge the right
place to record a response) — never directives issued by PAP's authority, and
PAP claims no standing to resolve any of them unilaterally
(`PAP_CHARTER.md` §2.3 in PAP's source repository).

## 1. Systematic Review performed

- **Architecture / Purpose review** — compared `.ai/PROJECT_CHARTER.md`'s
  stated Purpose and SHALL/SHALL NOT clauses against `.ai/CURRENT_STATE.md`'s
  inventory of completed phases, `.ai/context.md`'s system description, and
  `.ai/decisions.md`'s Architecture Decision Records (AD-001 through AD-038).
- **Repository census glance** — checked `git status --porcelain` for
  untracked material the governance corpus does not account for; cross-checked
  the result against `.ai/` and `docs/` for any mention.
- **Decision-lineage spot-check** — searched `.ai/decisions.md` for any
  record that amends, narrows, or supersedes AD-034 (the one ADR that most
  directly bears on the Purpose/implementation question below).
- **Self-audit-history cross-check** — scanned `docs/AUDIT-FINDINGS.md` (15
  "Audit cycle N" entries, 2026-06-04 through present) to confirm whether
  broodforge's own audit practice — which is real, frequent, and procedurally
  mature — had already surfaced either finding below. (It had not: those
  cycles are scoped to "Documented Steps vs. Implementation," a narrower,
  more mechanical cross-reference than the Purpose-vs-built-system and
  census-level questions this review asks.)

## 2. Finding Register

Classified per PAP-AUDIT §3 (BLOCKER / DEFECT / RISK / IMPROVEMENT /
OBSERVATION).

### F1 — DEFECT: `PROJECT_CHARTER.md`'s stated Purpose has not kept pace with the platform it charters

**Evidence:**
- `.ai/PROJECT_CHARTER.md` (last substantively touched 2026-05-30, per
  `git log`) states the Purpose in four lines: *"Provide objective
  infrastructure assessment."* Its SHALL list is "Collect facts / Normalize
  facts / Generate reports / Track historical changes." Its SHALL NOT list is
  "Recommend upgrades / Recommend purchases / Recommend replacements / Make
  subjective judgments."
- `.ai/context.md` (the platform's own current self-description) calls
  broodforge *"a self-managing infrastructure platform"* whose objectives
  include *"Self-recovering: autonomous remediation proposals with
  policy-gated execution"* and whose sixth lifecycle phase is *"Remediate —
  autonomous remediation engine with planner → queue → executor → policy
  loop."*
- `.ai/CURRENT_STATE.md` records Phase 26 ("Autonomous Remediation") as
  **Complete**: `remediation_planner.py`, `remediation_queue.py`,
  `remediation_executor.py`, `remediation_policy.py`, a CLI, dashboard
  integration ("remediations section, autonomous mode badge, approve/reject
  API"), and a dedicated operational-report section — 94 tests.
- A *planner* that proposes what to remediate, and a *policy* engine that
  decides when a proposal may execute, are — in substance — the "subjective
  judgments" and "recommendations" the Charter's SHALL NOT list names. The
  Charter's text describes a narrower, purely descriptive tool than the
  platform `context.md` and `CURRENT_STATE.md` both now describe broodforge
  as being.

**Why this is a DEFECT, not a BLOCKER**: nothing here stops broodforge's
continued operation or development — Phase 26 shipped, runs, and is tested.
The defect is in the *governance artifact's* fidelity to the *built system*:
a future reader of `PROJECT_CHARTER.md` alone would not learn that broodforge
plans and (under policy gates) executes remediation — exactly the kind of
"stated authority vs. observed reality" gap PAP-State §6.4 (Contradiction
Governance) names, and exactly the kind of finding PAP-AUDIT exists to
register without resolving (resolution is broodforge's call — see Scope
statement).

**Mitigating context, recorded for balance**: `context.md` itself frames the
remediation engine as *"proposals with policy-gated execution"* requiring
*"explicit opt-in (\"enable autonomous\") + policy gate"* — i.e., broodforge's
own current self-description already shows awareness that *unconditioned*
autonomous action would be a different (and more concerning) thing than what
was actually built. The gap is specifically that `PROJECT_CHARTER.md` — the
chartering document — was not updated to say so when Phase 26 landed; the
safeguard exists in the implementation and in `context.md`, but not in the
one document whose job is to authorize the system's scope in the first place.

**Resolution (2026-06-07 — recorded in place; original finding text above
left untouched as the record of what this review observed and why)**:
broodforge's operator — the Charter's own author and the only authority able
to state what its original intent actually was — clarified, directly and in
response to this finding, that the SHALL-NOT items were never meant to bound
the platform's *own* deployment-strategy/resource-provisioning decisions at
all; they named *specific-hardware* recommendations only (verbatim: *"the
subjective judgements language was regarding any suggestions of hardware
changes or upgrades, or what to put into a second node, etc., since this is
outside the scope of the project... [a mechanism for] how to provision
resources within an existing node or a new node... is more a broad function
of its deployment strategy, not a suggestion mechanism for specific hardware
[which] would require very granular information about specific pc products,
pricing databases, etc. that is outside the scope of what this project should
do"*). That is: **this finding surfaced a genuine textual ambiguity, not a
genuine contradiction** — the Charter's terse four-line SHALL-NOT list under-
specified its own scope, in a way that made Phase 26 *look* like a boundary
violation to a cold reader (this auditor included) when, per its author's own
clarification, it was always within the chartered deployment-strategy
function. The remedy applied — recorded as
[`AD-040`](../../.ai/decisions.md#ad-040-charter-shall-not-scope-clarified-ad-034-phrasing-amended-to-license-safeguarded-autonomous-action) —
adds an in-place Scope note to `PROJECT_CHARTER.md` (original four SHALL-NOT
items left intact) drawing exactly the line the operator named: specific-
hardware/product/pricing recommendations (excluded, ultra vires) vs.
resource-provisioning/deployment-strategy decisions (chartered, in scope).
**F1 is closed** — not because the system changed, but because the text that
seemed to contradict it has now been clarified, by the one party with
standing to say what it meant, to show that it didn't.

### F2 — DEFECT: AD-034's boundary was crossed by Phase 26 with no decision record marking the crossing

**Evidence:**
- AD-034 (dated 2026-05-31): *"The Assessment Engine never takes autonomous
  infrastructure action. Phase 2 automation is deferred to after Phase 12 and
  requires defined safeguards."*
- `.ai/decisions.md` runs through AD-038 (also dated 2026-05-31) — no AD
  amends, narrows, supersedes, or even cross-references AD-034 in light of
  Phase 26's later (≈2026-06-03) completion. A search for "remediation" or
  "autonomous" in `decisions.md` returns only AD-034 itself.
- Phase 26 is precisely the deferred capability AD-034 names — "Phase 2
  automation… requires defined safeguards" — now apparently built *with*
  safeguards (policy gates, opt-in, approve/reject API, per `context.md` and
  `CURRENT_STATE.md`). That is good news about the engineering. But the
  *decision* that the deferred threshold had been met, the safeguards judged
  sufficient, and AD-034's boundary could now be crossed, was never recorded
  as a decision in its own right — leaving AD-034 standing, unqualified, as
  if it still described the system's boundary.

**Why this is a DEFECT, not a BLOCKER**: this is a *traceability* gap, not an
operational one — the system functions and is tested either way. But it is
exactly the kind of silent drift between "what the decision record says
governs" and "what was actually decided and built" that a future maintainer
(or a future PAP census) would have no way to reconstruct without already
knowing the answer. `decisions.md`'s own AD-021 ("Staleness is a first-class
field confidence level") shows broodforge already values exactly this kind of
explicit state-tracking for *infrastructure* data; this finding observes the
same discipline has a gap in the *governance* layer.

**Relationship to F1**: F1 and F2 are two faces of one underlying event (Phase
26 crossing a previously-stated boundary) seen through two different
documents — the Charter (constitutional Purpose) and the Decision Record
(specific historical commitment). They are recorded separately because each
names a different artifact's specific obligation (Purpose-fidelity vs.
decision-lineage), and a fix to one would not necessarily fix the other — but
a single remediation effort could plausibly close both at once (see "Summary
of suggested work," below).

**Resolution (2026-06-07 — recorded in place; original finding text above
left untouched)**: the operator confirmed this finding's *premise* — AD-034's
absolute phrasing ("never takes autonomous infrastructure action") did not
match intent — but resolved it by *correcting the rule's wording* rather than
by writing the missing decision-record this finding called for (verbatim:
*"autonomous action is ok in some cases, as long as bounded by safeguards and
recoverability for autonomous actions that might go wrong. if the exact
phrasing needs revision, then do so to account for this"*). Recorded as an
in-place **Amendment** on AD-034 itself (original Date/Decision/Rationale
left intact as the historical record of what was first decided and why) plus
a coordinating [`AD-040`](../../.ai/decisions.md#ad-040-charter-shall-not-scope-clarified-ad-034-phrasing-amended-to-license-safeguarded-autonomous-action)
entry: the operative rule is now *"autonomous infrastructure action is
licensed provided it is bounded by defined safeguards and recoverable"* —
precisely AD-034's own original Rationale, carried to the conclusion it had
always pointed toward ("requires defined safeguards" → Phase 26 built them →
the boundary it deferred crossing is now properly, traceably crossed).
**F2 is closed** — the missing decision record this finding asked for now
exists (AD-040, cross-referencing the AD-034 amendment), and the rule's text
now says what its author always meant it to.

### F3 — RISK: an entire untracked architecture-corpus (`new/`) sits outside governance, describing a system substantially larger than the one `NEXT_STEPS.md` says is "complete"

**Evidence:**
- `git status --porcelain` shows exactly one untracked entry: `?? new/`.
- `new/` contains ~25 chapter-length `.docx` specification documents (e.g.
  *"BroodForge_Chapter_*_Authority Plane Architecture"*, *"...Secrets and
  Credential Architecture"*, *"...Authority Broker Specification"*,
  *"...Hatchery Node and Knowledge Plane Specification"*, *"...Federation/
  Multi-Site Architecture"*), a `broodforge_state_separation_spec.md`
  (proposing an Infrastructure-State-Layer / Application-Data-Layer split
  organized around a cryptographically-signed Root Manifest), a
  `broodforge.json`, and a `claude prompt.txt` whose three lines read as a
  **not-yet-executed instruction** — *"First read
  BroodForge_Synthesis_Entry_For_Claude_Analysis_v1.docx, then read
  broodforge.json. begin analysis and any revision necessary of the
  architecture from the charter and specifications. Develop a roadmap…
  Show me a report."*
- A repository-wide search for any of these documents' distinctive terms
  (`BroodForge_Chapter`, `Authority Plane`, `Hatchery Node`,
  `Synthesis_Entry`) inside `.ai/` or `docs/` returns **no matches** — the
  governance corpus does not yet know this material exists.
- Meanwhile `.ai/NEXT_STEPS.md` states, in full effect: *"All planned phases
  are complete,"* naming only four small "Future (unscoped)" items
  (multi-node cluster assessment, dynamic-inventory improvements, OpenTofu
  remote state, a report index) — none of which resemble the system `new/`
  describes (Authority/Execution/Secrets Brokers, OPA policy governance,
  Hatchery Nodes, multi-site Federation, a Root-Manifest state model).

**Why RISK rather than DEFECT or OBSERVATION**: nothing is *wrong* yet — this
may simply be staged input for a future analysis session that has not been run
(the embedded prompt reads exactly that way), placed deliberately and about to
be acted on. But two real risks track from leaving it as-is: (a) **loss** —
`new/` is untracked; a `git clean`, a bad rebase, or a careless `.gitignore`
edit could destroy ~25 chapters of specification work with no recovery path
(contrast broodforge's own AD-005, "Historical snapshot reproducibility is a
hard requirement," and AD-011's provenance-record discipline — both name
exactly this class of concern for *infrastructure* state; `new/`'s content is
ungoverned by an equivalent norm); and (b) **silent scope ambiguity** — if
this material *does* represent broodforge's next direction, every day it sits
uncommitted and unindexed is a day `NEXT_STEPS.md`'s "all phases complete"
claim and the actual trajectory of the project diverge further, for any reader
relying on the governance corpus alone (precisely the Census concern PAP-State
§5 names: "does the Repository Memory Structure still account for everything
that exists, and does everything that should exist, exist?").

### F4 — OBSERVATION: this audit corroborates, and now formally registers, a tension `pap/README.md` had already named in passing

`pap/README.md` (written while populating this very `pap/` tree, earlier the
same day) already flagged, in its boundary-explanation section, *"the
charter/reality tension already visible between `.ai/PROJECT_CHARTER.md`'s
'assessment only, no judgments/recommendations' framing and the platform's
actual, completed Phase 26 Autonomous Remediation engine — a finding PAP's
modules can register and reason about, but whose resolution is broodforge's
call, not PAP's."* This audit's F1 is that same tension, now run through
PAP-AUDIT's formal finding-classification machinery rather than named in
passing — recorded here as an OBSERVATION in its own right because the
*continuity* between an informal note and a formal finding is itself worth
making legible to a future reader (PAP-Core §6.3's "future-reconstruction"
standard: could someone, cold, see that these are the same thread?).

## 3. APDRP review (on F1 — the audit's central, most load-bearing finding)

Per PAP-AUDIT §2, run because F1 is the finding most likely to be read as a
"major" tension by broodforge's own governance, should they choose to act on
it.

- **Validation** — Does the evidence actually establish the gap claimed? Yes:
  the Charter's own text ("objective… SHALL NOT… subjective judgments") is
  quoted verbatim and compared directly against `context.md`'s and
  `CURRENT_STATE.md`'s own self-descriptions (also quoted verbatim) — not
  against an external standard or this auditor's inference about what the
  system "should" do. The contradiction is between the project's own documents,
  which is the strongest evidentiary footing a finding of this kind can have.
- **Falsification** — What would make this finding wrong? If `PROJECT_CHARTER.md`
  had been revised after Phase 26 landed (making the quoted text stale-but-
  superseded rather than current-and-contradicted), or if "recommend" /
  "subjective judgment" in the Charter's SHALL NOT list were defined elsewhere
  in a narrower technical sense that excludes remediation planning, this
  finding would dissolve. Neither was found: `git log` shows the Charter's
  last substantive change predates Phase 26's completion, and no glossary or
  scoping clause narrows "recommend" / "subjective judgment" anywhere in the
  `.ai/` corpus that this review located.
- **Alternative-solution perspective** — Is there a reading where no gap
  exists at all? Yes, one is plausible and is recorded for balance: one could
  argue the Charter governs only the *Assessment Engine* specifically (its
  Purpose line: "objective infrastructure assessment"), while Phase 26's
  remediation engine is a *distinct* subsystem the Charter never claimed to
  bound. Weighed against that: `context.md` describes assessment and
  remediation as integrated phases of *one* lifecycle ("Assess… Remediate"),
  not as separate chartered and unchartered zones — and `PROJECT_CHARTER.md`
  is broodforge's *top-level* charter (per `pap/README.md`'s own framing,
  "broodforge's own sovereign top-level authority"), not an Assessment-Engine-
  scoped sub-charter. If the narrower reading is broodforge's intended one,
  that itself is exactly the kind of clarification F1 recommends making
  explicit — the alternative reading doesn't eliminate the gap, it relocates
  it to "the Charter's own scope is ambiguous as written."
- **Future-reconstruction** — Could a future maintainer, with no memory of
  Phase 26's development history, read `PROJECT_CHARTER.md` cold and correctly
  predict that broodforge plans and executes remediation under policy gates?
  No — and that is the finding's core: the Charter alone underdescribes the
  system. `context.md` and `CURRENT_STATE.md` could each independently fill
  that gap for a reader who finds them, but neither is the *chartering*
  document, and PAP-State §2's Repository Memory Structure exists precisely so
  that "what governs this system" and "what the system actually is" don't
  require a multi-document reconciliation exercise to align.

**Unresolved-disagreement note** (PAP-AUDIT §2's closing instruction —
"preserved, not hidden"): the Alternative-solution perspective's narrower
reading (Charter governs only the Assessment Engine) is *not* refuted by this
review — it is a live, plausible interpretation that would substantially
change how broodforge should respond to F1 (rewrite the Charter's Purpose vs.
clarify its scope vs. do nothing because no gap exists under that reading).
This auditor takes no position on which reading broodforge's maintainers
should adopt; that determination is exactly the kind of call `pap/README.md`
§"boundary" reserves to broodforge's own governance.

**Resolution note (2026-06-07 — added in place; the review above is left
exactly as performed, including its uncertainty, because that uncertainty is
itself the evidence that the resolution below required the operator's
authority to settle, not this auditor's analysis)**: the Falsification
perspective named, as the one thing that would dissolve this finding, a
scenario this auditor could not find evidence for — *"if 'recommend' /
'subjective judgment' in the Charter's SHALL NOT list were defined elsewhere
in a narrower technical sense that excludes remediation planning, this
finding would dissolve."* That is exactly what then happened — not via a
pre-existing definition this review missed, but via the operator directly
*supplying* the narrower, original-intent definition no document had yet
recorded (see F1's "Resolution," above, and `AD-040`). And the
Alternative-solution perspective's open disagreement (does the Charter govern
only the Assessment Engine, or the whole platform?) is now answered too, as a
side effect: the operator's clarification describes a *single, platform-wide*
scope rule (specific-hardware recommendations excluded; the platform's own
deployment-strategy decisions — wherever in the platform they occur — are
not), which neither perspective had articulated, and which dissolves the
disagreement by replacing both candidate readings with a third, more precise
one. This is recorded as a small, concrete instance of exactly what
PAP-AUDIT §2 anticipates an APDRP review *cannot*, by itself, always do —
adjudicate a question whose answer lives in an author's intent, not in the
artifact's text — and of why "preserve the disagreement, don't hide it" is
the right discipline up to the point where the one party who *can* resolve it
does.

## 4. Verdict rationale

**`ready`.** PAP-AUDIT §4 requires at least one BLOCKER-classified finding to
support any verdict other than `ready`; this review surfaced none. All three
substantive findings (F1, F2 — DEFECT; F3 — RISK) describe *governance-corpus
fidelity and hygiene* gaps — places where broodforge's documentation of itself
has not kept pace with broodforge's own development — not operational defects
in the platform itself. `.ai/NEXT_STEPS.md`'s "all planned phases complete"
claim, broodforge's mature and frequent self-audit cadence (15 "Audit cycle N"
entries since 2026-06-04, each with method/findings/fix-attempt sections), and
the absence of any open BLOCKER in this review or in `docs/AUDIT-FINDINGS.md`'s
own recent cycles together support treating broodforge as a system that is
*operationally* sound and ready for continued work — with three specific,
named, non-blocking items worth its maintainers' attention.

## 5. Summary of suggested work

*(Offered as findings/recommendations for broodforge's governance to weigh —
per the Scope statement, none of these are directives. Ordered roughly by
how cheaply each closes relative to the clarity it would add.)*

1. **✅ DONE (2026-06-07, `AD-040`)** — ~~Reconcile `PROJECT_CHARTER.md`'s
   Purpose/SHALL-NOT clauses with the built system (closes F1)~~ — resolved
   by neither (a) nor (b) below, but by a third path this auditor had not
   anticipated: the operator clarified that the SHALL-NOT text was never
   meant to bound the platform's deployment-strategy function at all — it
   named *specific-hardware* recommendations only. `PROJECT_CHARTER.md`
   gained an in-place Scope note recording that original intent (see F1's
   Resolution annotation, above). The recommendation as originally framed
   is preserved below for the record — for a future reader to see what was
   *suggested* against what was *actually* the right fix once the authority
   able to say so weighed in:

   ~~either (a) narrow the Charter's explicit scope
   to name which subsystem(s) "objective… no subjective judgments" actually
   bounds (if the Assessment-Engine-only reading is correct), or (b) revise
   the Purpose and SHALL/SHALL NOT lists to describe the self-managing,
   self-remediating platform `context.md` and `CURRENT_STATE.md` already
   describe broodforge as being — including naming the safeguards
   (`context.md`'s "explicit opt-in + policy gate") that make "the system now
   makes recommendations and, under gates, acts on them" a *governed* capability
   rather than an uncharted one. Either path is broodforge's call (F1's
   Alternative-solution perspective leaves both open); what matters is that
   *one* of them gets recorded, closing the gap between the chartering document
   and the system it charters.~~

2. **✅ DONE (2026-06-07, `AD-040` + an in-place Amendment on `AD-034`)** —
   ~~Record the AD-034-crossing as its own decision (closes F2)~~ — resolved
   essentially as suggested, though by *amending AD-034's own phrasing in
   place* (with the original text preserved as history) rather than by a
   freestanding crossing-record: the operator confirmed AD-034's absolute
   wording ("never takes autonomous infrastructure action") had overstated
   intent, and directed a phrasing fix. `AD-040` now states the operative
   rule plainly — autonomous action is licensed when bounded by safeguards
   and recoverable — cross-referencing the AD-034 amendment that carries
   AD-034's own original Rationale to the conclusion it had always pointed
   toward. See F2's Resolution annotation, above, and the original
   recommendation, preserved for the record:

   ~~add a
   decision record (AD-039 or similar) that explicitly: names AD-034's original
   boundary, states that Phase 26 crosses it, and records *why that crossing
   was judged acceptable* (which safeguards were built, why they satisfy
   AD-034's "requires defined safeguards" clause, and what — if anything —
   remains deferred). This single record would give a future reader exactly
   what AD-021's "staleness as a first-class field" already gives infrastructure
   data: an explicit, dated statement of "this superseded that, and here is
   why," rather than two ADRs that silently disagree. Note: this recommendation
   and #1 both touch the same underlying event and could plausibly be satisfied
   by one coordinated edit pass — but each closes a different artifact's
   specific obligation, so each should be checked off independently even if
   done together.~~ (In the event, #1 and #2 *were* resolved by one
   coordinated act — `AD-040` — exactly as this note speculated they might be.)

3. **Decide what `new/` is, and make that decision durable (closes F3)** — at
   minimum, either (a) commit it (with a message naming what it is and why it's
   here — e.g., "staged specification corpus for a future architecture-revision
   pass, not yet integrated"), removing the loss-risk named in F3(a); or (b) if
   it is *not* meant to persist in this repository (e.g., scratch input staged
   for a one-off session elsewhere), move it out and note that fact somewhere a
   future census would find it. Either action is far cheaper than the
   alternative — discovering, months from now, that ~25 chapters of
   architecture work either vanished or sat unexplained in a working tree. If
   (a), a brief pointer from `.ai/NEXT_STEPS.md` ("a larger architecture-revision
   proposal is staged in `new/`, pending a dedicated analysis pass — see
   `new/claude prompt.txt`") would close the silent-scope-ambiguity half of F3
   too, at near-zero cost.

4. **Optional, lowest-priority — extend `docs/AUDIT-FINDINGS.md`'s own
   cross-reference scope (relates to, does not replace, F1/F2)**: broodforge's
   self-audit cycles are frequent and procedurally strong but are explicitly
   scoped to "Documented Steps vs. Implementation" — a narrower question than
   "does the *chartering* document's stated Purpose still match the built
   system." Nothing requires broodforge to widen that scope; this is named only
   because F1 and F2 are exactly the kind of finding that scope is structurally
   unlikely to surface on its own (as in fact it had not, across 15 cycles),
   and a one-line note in that file's "Method" section acknowledging the
   boundary would help a future reader understand why a Charter-fidelity gap
   could persist through 15 audit cycles without contradiction — it wasn't
   missed; it was out of frame.

## Provenance

Commissioned by direct operator instruction (verbatim, quoted in full in
"Scope statement," above), run against broodforge's own state using the
`pap/` tree populated into this repository earlier the same day (commit
`06b8aee`) by a prior operator instruction ("now, using the currently adopted
pap, populate pap/ in broodforge"). This is the first live exercise, anywhere,
of PAP-AUDIT run *analytically* — against a project other than PAP's own
source repository — and is therefore also the first concrete instance of the
boundary `PAP_CHARTER.md` §2.3 and `pap/README.md` both describe in the
abstract: every finding above is offered as a recommendation to broodforge's
own governance, not a directive from PAP's, and this record claims no
authority to resolve any of them — only to name them clearly enough that
broodforge's maintainers can.
