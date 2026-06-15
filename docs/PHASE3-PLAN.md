# Broodforge — Phase 3.L–3.P Plan

*Proposed 2026-06-15. Phases to be merged into ROADMAP.md once the full-file rewrite
problem is resolved (ROADMAP.md is currently damaged — see revert note below).*

**ROADMAP.md revert required:** Commits `8590948` and `93b3ca9` on 2026-06-15
damaged ROADMAP.md (net ~3800 lines deleted). To restore, run on your local clone:
```
git revert 93b3ca9 8590948
# or: git reset --hard c80b7bc  (last known-good commit, then force-push)
```
After revert, splice the five phases below after the `### Phase 3.K` section and
before the `## Phases from` corpus section.

---

### Phase 3.L — OpenBao Secrets Broker *(proposed)*

**Purpose:** Introduce OpenBao as a machine-facing secrets API layer sitting between
runtime components and the KeePass credential store.  KeePass remains the
operator-facing encrypted vault (root of trust, AD-061); OpenBao becomes the
programmatic API that enforces RBAC, TTL leases, and produces an audit log — all
the things a CLI call to `keepassxc-cli` cannot provide.  The `child://` reference
scheme continues to work; only the implementation behind `kdbx_get_child()` changes.

**Topology (AD-074):** OpenBao runs as a systemd service on the Proxmox host (not
inside k3s).  Rationale: it must be reachable during bootstrap before k3s is up,
and it governs hypervisor-level secrets that must not depend on a cluster that may
be down during a recovery.  A single-node OpenBao instance is sufficient; HA is
deferred until Phase 3.P+ multi-node federation.  Listen address: loopback only
(`127.0.0.1:8200`); external access proxied through the governance VM's nginx.

**Bootstrap ceremony:** `lib/forge-lib.sh` `forge_openbao_seed()` — a one-time
seeding function called at the end of the Forging runbook (Phase 1.F).  It reads
each credential from the KeePass child DBs using the existing `kdbx_get_child()`
path, then writes each secret into the appropriate OpenBao path using `bao kv put`.
After seeding, `kdbx_get_child()` is switched to call the OpenBao API; the KeePass
side becomes read-only backup.  The seeding ceremony must be run under operator
presence (KeePass gate, AD-065 pattern).

**Auto-unseal (AD-075):** OpenBao sealed state blocks all secret reads.  On
Proxmox-host restart, a systemd `ExecStartPost` script calls
`lib/forge-lib.sh` `forge_openbao_unseal()`, which reads the unseal key shard from
a hardware-bound file (`/etc/broodforge/unseal-shard.enc`) decrypted by the
Proxmox-host's own SSH host key (using `openssl rsautl`).  The unseal shard itself
is generated at bootstrap and recorded in the forge-autonomous KeePass DB.
Threat model: physical access to the host already grants full compromise; the
unseal-at-boot mechanism adds no new attack surface over the current keepassxc-cli
approach.  TOTP-based manual unseal remains available as a fallback.

**Policy mapping:**
- `forge-autonomous` KeePass DB → OpenBao path `secret/autonomous/`; policy
  `autonomous-policy` allows `read` on `secret/autonomous/*`, `deny` on `write`.
- `forge-spawn` → `secret/spawn/`; policy `spawn-policy` allows `read/write`
  for session-scoped spawn credentials only; `deny` on `secret/autonomous/*`.
- `forge-migrate` → `secret/migrate/`; policy `migrate-policy` allows `read`
  on `secret/migrate/*` during a migration session; denies everything else.
  Each policy enforces TTL ≤ 24 h; spawn/migrate leases expire at session end.

**`lib/forge-lib.sh` change:** `kdbx_get_child()` gains a `--via-openbao` flag
(default once seeded).  Internally it calls `curl -s -H "X-Vault-Token: $BFVAULT_TOKEN"
http://127.0.0.1:8200/v1/secret/data/<path>` and extracts `.data.data.value`.
The token is read from `/run/broodforge/openbao-token` (tmpfs, mode 0600),
written by `forge_openbao_login()` at session start using the AppRole credentials
stored in `/etc/broodforge/approle-<role>.env`.  Fallback: if OpenBao is
unreachable, `kdbx_get_child()` falls through to the original `keepassxc-cli` path
and logs a `WARN_OPENBAO_FALLBACK` event.

**TOTP:** OpenBao's TOTP secrets engine (`totp/`) can replace `kdbx_totp()` for
services whose TOTP secret is already seeded into OpenBao.  The `kdbx_totp()`
function in `forge-lib.sh` gains a parallel `forge_openbao_totp()` path.  This is
a non-breaking change; operators may migrate TOTP secrets to OpenBao incrementally.

**Key rotation:** `forge_rotate_secret()` in `lib/forge-lib.sh` writes a new value
to the OpenBao KV path, increments the KV version, and records the rotation as a
`SecretRotationRecord` published to the EventBus (Phase 3.A) and covered by the
Governance Integrity Chain (Phase 3.I).  The old KeePass DB entry is updated
simultaneously using `keepassxc-cli edit` to keep both stores in sync.

**Files to create/modify:**
- `lib/forge-lib.sh` — `kdbx_get_child()` + `forge_openbao_seed()` + `forge_openbao_unseal()` + `forge_openbao_login()` + `forge_openbao_totp()`
- `proxmox-bootstrap/openbao/install-openbao.sh` — download, verify, install systemd unit
- `proxmox-bootstrap/openbao/openbao-policies/` — `autonomous-policy.hcl`, `spawn-policy.hcl`, `migrate-policy.hcl`
- `proxmox-bootstrap/openbao/openbao-unseal.sh` — boot-time unseal helper
- `docs/OPENBAO-SETUP.md` + `docs/OPENBAO-SETUP.html` — operator walkthrough (add to doc-manifest.json)
- Tests: `tests/test_openbao_broker.py` (~20 unit tests covering seed, login, get, rotate, fallback)

**Dependencies:** Phase 3.H (Secrets & Trust Brokerage) — 3.L is the concrete
OpenBao backend for the abstract `SecretsBroker` defined in 3.H.  Integrates with
Phase 3.I (Governance Integrity Chain) for rotation audit records.

**Operator decisions required:**
- Confirm that loopback-only OpenBao on the Proxmox host is the right topology
  (alternative: run in a dedicated governance LXC).
- Choose unseal-shard encryption: SSH host key (current plan) vs. a TPM-backed
  sealing (more secure but requires TPM 2.0 hardware confirmation).
- Confirm whether forge-autonomous credentials should be seeded into OpenBao at all,
  or whether autonomous-mode scripts should continue to call KeePass directly.

---

### Phase 3.M — Markdown Source Editor (Standalone Tool) *(proposed)*

**Purpose:** Provide a standalone HTML editor tool (`docs/bf-editor.html`) that
operators launch when they want to edit a doc's markdown source and regenerate it.
This keeps individual doc pages lightweight — no editor machinery embedded in each
generated HTML file.

**Design (standalone tool approach):** A dedicated `docs/bf-editor.html` file,
not generated by `md_to_html.py`, contains the full editor UI.  It is opened via
an "✎ Edit" badge in the left-side nav of every generated doc page (alongside the
existing Light/Dark mode badge).  The badge passes the current doc's manifest id
as a URL parameter: `bf-editor.html?id=forging`.  The editor page then:
- Fetches the doc's markdown source via `GET /api/docs/source?id=<id>` from
  `broodforge_dashboard.py`, displaying it in a full-page CodeMirror-style textarea
  (using only inline JS — no CDN; a ~12 KB minimal syntax-highlight shim is inlined).
- Provides a lint pass: scans for unknown `@directive` syntax and malformed
  `@credential[...]` refs; highlights offending lines in a gutter.
- "Save & Regenerate" POSTs `{id, source}` to `POST /api/docs/edit`; dashboard
  writes the `.md` file and runs `regenerate_docs.py --id=<id>`.  On success,
  the editor offers a link to reload the regenerated doc page.
- Fallback when dashboard is not running: "⬇ Download .md" button only (uses a
  pre-fetched source stored in sessionStorage from the originating doc page).

**How the originating doc page passes context:** `md_to_html.py` embeds the doc
manifest id as `<meta name="bf-doc-id" content="{id}">` in the `<head>`.  The
"✎ Edit" nav badge reads this meta tag and opens
`bf-editor.html?id={id}` in a new tab.  No markdown source is embedded in the
generated HTML (keeps file sizes down and avoids self-referential editing).

**Why standalone over embedded:**
- Keeps every generated HTML page lightweight (no ~20 KB editor JS per doc).
- Avoids the self-referential problem of `bf-editor.html` editing itself.
- The editor is one file to maintain rather than a block duplicated across all docs.
- Operators who never edit docs pay no cost.

**Files to create/modify:**
- `docs/bf-editor.html` — standalone editor (hand-authored, not in doc-manifest.json;
  analogous to `bfvault.html` which is also hand-authored).
- `proxmox-bootstrap/md_to_html.py` — add `<meta name="bf-doc-id">` to `<head>`;
  add "✎ Edit" badge to the left-side nav toolbar.
- `proxmox-bootstrap/broodforge_dashboard.py` — add `GET /api/docs/source?id=<id>`
  (returns raw markdown) and `POST /api/docs/edit` (writes .md + regenerates).
- `proxmox-bootstrap/regenerate_docs.py` — add `--id=<id>` single-doc rebuild flag.
- `docs/doc-manifest.json` — no change (bf-editor.html is hand-authored like bfvault.html).

**Operator decisions required:**
- Confirm whether `bf-editor.html` should open in a new tab (clean separation) or
  as an overlay panel within the originating doc page.
- Decide whether the editor should support WYSIWYG rendered preview alongside the
  markdown source (requires calling a `/api/docs/preview` endpoint that runs
  md_to_html.py on the unsaved draft and returns the body HTML).

---

### Phase 3.N — TOTP QR Code in HTML Pages *(proposed)*

**Purpose:** Walkthrough docs that set up TOTP-protected services need a scannable
QR code so the operator can scan-to-add in an authenticator app without typing a
base32 secret manually.  The TOTP secret must not be hardcoded in the HTML (which
lands in git); instead it is drawn from the `@credential` field the operator has
already filled in for that secret.

**New directive:** `@totp-qr[Service Name|TOTP_VAR|account@example.com]`
- Renders a `<div class="bf-totp-qr-block">` containing:
  - A `<canvas id="bf-totp-qr-{slug}" width="200" height="200">` (QR render target)
  - A `<p class="bf-totp-qr-hint">Scan with your authenticator app</p>`
  - A `<button class="bf-totp-peek-btn" data-for="{slug}">Show secret</button>` that
    toggles a `<span class="bf-totp-peek-text">` with the base32 value (for copy-paste)
  - The canvas starts blank; it is rendered when the referenced credential field is non-empty.
- Parser addition in `md_to_html.py` `_render_blocks()`: add `@totp-qr` to the
  directive-matching block (alongside `@credential`, `@field`, etc.) at line ~2640.
  The three arguments are: display name (issuer), the credential variable name
  (must match an `@credential[...|VAR]` in the same doc), and the account name for
  the `otpauth://` URI.

**QR generation (AD-077):** Inline a compact pure-JS QR encoder.  The chosen
library is a minimised port of Kazuhiko Arase's `qrcode-generator` (~6 KB
minified).  It is pasted verbatim into the generated HTML's `<script>` block
(inside the existing large inline script in `md_to_html.py`).  No CDN fetch.
The `otpauth://` URI is constructed as:
`otpauth://totp/<issuer>%3A<account>?secret=<BASE32>&issuer=<issuer>&algorithm=SHA1&digits=6&period=30`.

**Credential field integration:** The existing `@credential` directive fires a
`credential-changed` custom event (dispatched by the `cred-input` handler in the
inline JS).  The `@totp-qr` block listens for this event on the matching variable
name, rebuilds the `otpauth://` URI, and re-renders the canvas via the QR library's
`qrcode()` function.  If the field is cleared, the canvas is blanked.

**Print safety:** The QR `<canvas>` block has CSS `background:#fff; padding:8px;`
applied unconditionally (not via CSS custom property) so it remains white even in
dark mode.  Minimum canvas size: 200×200 px (enforced in the directive renderer).
The `<div class="bf-totp-qr-block">` has `page-break-inside: avoid` for print.

**Files to create/modify:**
- `proxmox-bootstrap/md_to_html.py` — add `@totp-qr` directive parser in
  `_render_blocks()`, render the HTML block, add QR library JS (~6 KB) and
  event-listener wiring to the inline `<script>`.
- Tests: add `test_totp_qr_directive` in `tests/test_md_to_html.py` — verify the
  canvas element is rendered, the credential slug is wired correctly, and that the
  `otpauth://` URI template is well-formed for known inputs.

**Operator decisions required:**
- Confirm the `qrcode-generator` JS library is acceptable (MIT licensed, ~6 KB).
  Alternative: write a minimal QR encoder from scratch (~15 KB but zero dependency).
- Confirm the `account` field in `@totp-qr[Service|VAR|account]` is the right
  third argument (vs. auto-deriving it from the `@field[Username|...]` field in the
  same doc).

---

### Phase 3.O — TOC Tiered Numbering *(proposed)*

**Purpose:** Replace the current flat h2-only Table of Contents with a
full-hierarchy numbered TOC that mirrors the collapsible section tree, highlights
the currently-visible section, and optionally prefixes section headings with their
numeric badge.

**Current state (from `md_to_html.py` lines 2869–2982):**
- `_render_blocks()` parses `#{1,4}` headings; only `level == 2` entries are
  appended to the `toc` list (line 2879).
- `render_html()` builds a flat `<ol>` from the h2-only entries (lines 2973–2981).
- CSS: `#bf-toc ol { list-style: decimal }` — single-level decimal numbering.
- No IntersectionObserver; no active-link highlighting.

**New TOC structure (AD-078):**
- `_render_blocks()`: capture h2, h3, and h4 into the `toc` list (remove the
  `if level == 2:` guard; pass all levels ≤ 4).  The `toc` list entry becomes
  `(hid, raw_title, level)` — already the existing schema, no format change.
- `render_html()`: build nested `<ul>` instead of flat `<ol>`.  Walk the
  `toc_entries` list, maintaining a stack of open `<ul>` elements.  On each entry:
  - If `level > current_depth`: open a new `<ul class="bf-toc-L{level}">`.
  - If `level < current_depth`: close `</ul>` until depths match.
  - Emit `<li data-hid="{hid}"><a href="#{hid}">{title}</a></li>`.
  A JS function `bf_assign_toc_numbers()` post-processes the rendered `<ul>` tree:
  it walks each `<li>` in DFS order, maintains a counter per depth, and prepends a
  `<span class="bf-toc-num">1.2.3</span>` to each `<a>` element.

**IntersectionObserver:** An inline JS block instantiates a single
`IntersectionObserver` with `rootMargin: "-10% 0px -80% 0px"` (fires when a
section's `<summary>` enters the top 10–20% viewport band).  On intersection:
1. Removes `bf-toc-active` from all TOC `<li>` elements.
2. Reads the `data-hid` attribute of the intersecting element and adds
   `bf-toc-active` to the matching `<li data-hid="...">` in the TOC.
CSS: `#bf-toc li.bf-toc-active > a { font-weight: 600; color: var(--accent-strong); }`.

**Heading number badge:** `bf_assign_toc_numbers()` also writes
`data-sec-num="1.2.3"` attributes on each `<details>` element; CSS
`details[data-sec-num] > summary::before { content: attr(data-sec-num) " "; }`
renders the badge inline.  Styled with `opacity: 0.45; font-size: .8em`.

**Files to create/modify:**
- `proxmox-bootstrap/md_to_html.py`:
  - `_render_blocks()` line 2879: remove `if level == 2:` guard.
  - `render_html()` lines 2972–2982: replace flat `<ol>` with nested `<ul>` builder.
  - Inline `<script>`: add `bf_assign_toc_numbers()` and IntersectionObserver.
  - CSS block lines 448–458: add `.bf-toc-L3`, `.bf-toc-L4`, `.bf-toc-active`,
    `details[data-sec-num] > summary::before`.
- Tests: `tests/test_md_to_html.py` — verify h3/h4 entries in TOC, nested `<ul>` structure.

**Operator decisions required:**
- Confirm numeric-only (1.2.3) vs. operator-choosable style per doc.
- Confirm whether heading number badge is default-on or opt-in via `--numbered-headings`.

---

### Phase 3.P — Setup Guide Markdown Migration *(proposed)*

**Purpose:** Migrate `docs/SETUP-GUIDE.html` from hand-authored HTML to a markdown
source generated by `md_to_html.py`.  Currently `doc-manifest.json` marks this doc
`"handAuthored": true` with no `source` field.  After migration it will be authored
as `docs/SETUP-GUIDE.md` and generated like every other doc, unlocking all schema
directives, inline editing, session notes, and automatic TOC.

**Migration steps:**
1. **Audit SETUP-GUIDE.html for schema element opportunities.**  Identify:
   (a) values the operator must supply → `@field`;
   (b) credentials (passwords, API keys) → `@credential`;
   (c) step-by-step checklist items → `@check`;
   (d) choices between alternatives → `@select` or `@radio`;
   (e) directory paths → `@dir`;
   (f) expected terminal output → `@parse`.
2. **Author `docs/SETUP-GUIDE.md`** using the schema.
3. **Update `proxmox-bootstrap/doc-manifest.json`:** add `"source"`, remove
   `"handAuthored": true`, add `"flags": ["--collapsible"]`.
4. **Regenerate** via `regenerate_docs.py --id=setup-guide` (Phase 3.M `--id` flag).
5. **Visual equivalence check:** side-by-side diff of old and new HTML.

**Files to create/modify:**
- `docs/SETUP-GUIDE.md` — new markdown source.
- `docs/SETUP-GUIDE.html` — regenerated output.
- `proxmox-bootstrap/doc-manifest.json` — update entry.

**Dependencies:** Phase 3.M (standalone editor) is not required but strongly
recommended first — iterating on SETUP-GUIDE.md is much faster with the editor.

**Operator decisions required:**
- Archive old hand-authored HTML in `docs/archive/` or overwrite directly?
- Doc type: `"guide"` (reference) or `"runbook"` (operator-action sequence with
  `--playbook` flag)?
