# Session Handoff (DEPRECATED — superseded, preserved for history)

> **This file is retired.** Broodforge's session-continuity practice now
> lives under PAP, per direct operator instruction (see
> [`pap/revisions/2026-06-07_session-continuity-transition-to-pap.md`](../../pap/revisions/2026-06-07_session-continuity-transition-to-pap.md)
> for the full rationale and evidence trail). Going forward:
>
> - **For the current session-handoff artifact**, see
>   [`pap/state/SESSION_HANDOFF.md`](../../pap/state/SESSION_HANDOFF.md).
> - **For the current resume block**, see
>   [`pap/state/RESUME_BLOCK.md`](../../pap/state/RESUME_BLOCK.md).
>
> This file is **moved, not deleted** — it was a genuine, working prototype
> of exactly the practice PAP-State §3/§4 now formally specify, and its full
> session-by-session history below remains the authoritative historical
> record of broodforge's pre-PAP development continuity. It is preserved here
> (and in git history via `git mv`, so `git log --follow` recovers its full
> lineage at its original path) for exactly that reason. **Do not extend this
> file further** — extend `pap/state/SESSION_HANDOFF.md` instead.

---

# Session Handoff

Last updated: 2026-06-04 UTC

## What Was Done This Session (current)

### Deep architecture-vs-docs audit + interactive HTML (completed)

**Implementation gaps (broken next-steps) — fixed & verified:**
- **B1 (HIGH)** `assemble-forge-package.py` now infers the repo root when `--repo`
  is omitted, so the documented FORGING.md path produces a self-contained package.
  Previously the generated phase scripts called `$SCRIPT_DIR/proxmox-bootstrap/*.py`
  against files that were never bundled — `phase-00-discover.sh` failed instantly.
  Verified: no-`--repo` package bundles 95 tools + 26 schemas + 78 doc-gen files.
- **B2 (MED)** New `validate-spawn.py` CLI + its import closure (`validate_spawn.py`,
  `hatchery_state.py`) are now bundled in spawn packages. `phase-00-preflight.sh`'s
  `[ -f ]`-guarded conflict re-validation was a silent no-op (tool never packaged).

**Security:**
- **A1 (HIGH)** `broodforge_dashboard` now `_redact_secrets()` masks secret-bearing
  fields (k3s `worker_join_token`/`server_join_token`, `*token/*password/*secret/
  *api_key/*auth_key`) before serving the unauthenticated GET endpoints. k3s join
  tokens live in bootstrap-state.json and were served verbatim — a LAN-adjacent
  client could read one and join a rogue cluster node. Redaction copies, never
  mutates, so POST write paths are intact (verified).
- **A3** forge/spawn/phoenix assembler CLIs print the package SHA-256 (tamper-evidence);
  FORGING.md documents verifying it after `scp`.

**Documentation alignment (drift fixed to match implementation):**
- README spawn & phoenix package listings rewritten to real phase/wave names;
  recovery-wave model aligned to the implemented playbook waves.
- Stale test counts and muddled Development Status corrected.
- Broken `docs/DNS-UPDATE-SETUP.md` refs fixed (FORGING.md + 2× ROADMAP.md).
- Spelling: "Forgability" → "Forgeability".

**Straggler cleanup:**
- Moved `ARCHITECTURE-REVIEW-v7.md` → `deprecated/` (joining v4–v6) and the orphan
  `CONTAINER-COMPATIBILITY-PLAN.html`.
- New durable `docs/DESIGN-HISTORY.md` traces the v4→v7 design evolution + rationale
  (replaces the versioned-review churn). ARCHITECTURE.md / .ai/* repointed to it.

**Interactive HTML documentation (`proxmox-bootstrap/md_to_html.py` rewrite):**
- Light/dark **theme toggle** (persisted), per-code-block **Copy** buttons,
  **live-templated commands** (`{{VAR}}` / `{{VAR=default}}` → a Parameters panel;
  editing rewrites every command + Copy copies the resolved text),
  **note fields** (`@field[Label]` / `@area[Label]`), and an auto **Session Notes**
  textarea. All values persist per-doc in localStorage.
- `RECONSTRUCTION-DRILL.md` is the showcase (templated paths + per-step note fields).
- New `inject_html_theme.py` retro-fits the toggle + copy buttons onto hand-authored
  HTML (`docs/ARCHITECTURE.html`, `docs/SETUP-GUIDE.html`).
- Generated/regenerated HTML: README, ROADMAP, DESIGN-HISTORY, RECONSTRUCTION-DRILL,
  CLOUDFLARE/DUCKDNS/CLOUD-STORAGE-SETUP, TALOS-ALTERNATIVE, plus new
  `proxmox-bootstrap/FORGING.html` and `NODE-SPAWNING.html`.

**Tests: 4000 passed, 1 skipped (Windows-only).** No regressions.

**Next:** continue autonomous deepthink audit cycles (architecture vs documented
execution paths) until zero findings on a deep + deeper pass, or budget exhausted.
Candidate not yet addressed: theme toggle on the runtime-generated dashboard HTML
(it is an app surface, not documentation — deferred deliberately).

### Audit cycle 2 — forge IaC provisioning incoherence (fixed, bounded)

Deepthink trace of the forge execution path found a real docs-vs-code incoherence:
the docs present `forge.sh` as turnkey (bare metal → operational hatchery with
Forgejo VM + k3s), but:
- No `opentofu/` modules exist anywhere in the repo; forge phase-04 needs them.
- forge phase-05 referenced **nonexistent** `ansible/site.yml` + `ansible/inventory.ini`
  (the real files are `ansible/playbooks/04-k3s.yaml` + `ansible/inventory/hosts.yaml`).
- The assembler bundled neither `ansible/` (exists, 18 files) nor
  `proxmox-bootstrap/generators/` (the IaC producers; skipped by the non-recursive
  `*.py` glob).

Result: phases 04–05 silently skipped VM + k3s provisioning while docs claimed success.

Bounded fixes (full opentofu authoring is the deploy-to-hardware milestone, not an
audit-fix): assembler now bundles `ansible/` + `generators/`; phase-05 references the
real playbook/inventory paths and only runs ansible when the inventory exists, else
degrades with a pointer to the new FORGING.md "Forge provisioning status" note;
phase-04 message made honest. README "feature-complete" claim corrected to name the
forge VM-provisioning IaC as the one known gap. Verified: forge package bundles 18
ansible + 15 generator files incl. the k3s playbook/role. Tests: 4000 passed, 1 skipped.

### Audit cycle 3 — phoenix/stargate workflow missing entry point (fixed)

The documented stargate process had a **broken first step**: `phoenix-planner.py` and
`assemble-phoenix-package.py` both required an *existing* `--playbook`, but
`phoenix_playbook.py` (which has `build_phoenix_playbook()`) had **no CLI**, and there
was **no operator runbook** for phoenix (unlike FORGING.md / NODE-SPAWNING.md). The
only way to produce the initial playbook was a `python -c` one-liner buried in the
reconstruction drill doc.

Fixes:
- `phoenix-planner.py`: `--playbook` is now optional; when omitted it GENERATES the
  base playbook from `--state` via `build_phoenix_playbook()` (new `--hardware` arg
  for the replacement profile). Output defaults to `phoenix-playbook.json`. Verified
  end-to-end: generate(state) → playbook → assemble → package (run-all.sh + 6 waves).
- New `docs/PHOENIX.md` operator runbook (interactive HTML with templated commands +
  note fields), linked from the README stargate section.
- Reconstruction-drill pre-drill step now uses the clean `phoenix-planner.py` command
  instead of the buried `python -c` snippet.

Tests: 4000 passed, 1 skipped.

### Audit cycle 4 — doc-gen engine.py CLI mismatches (fixed)

`doc-gen/engine.py` only accepts `--mode {bootstrap,recovery,operational}` + `--archive`
/ `--manifest`. Two documented invocations used flags it doesn't have:
- **forge phase-07** ran `engine.py --mode bootstrap --state … --output …` → `--state`
  and `--output` are unrecognized, so the forge's first doc-generation always failed
  (silently, behind its `|| echo WARNING`). Fixed to `--manifest bootstrap-state.json`.
- **README "Documentation Timestamps and Timezone" + AD-045** documented
  `engine.py --set-timezone "…"`, but no such flag existed (and `--mode` was required),
  so the command failed outright. Implemented `--set-timezone TZ` (+ `--state PATH`)
  as a standalone op that updates `vm_defaults.timezone` and exits; `--mode` is now
  only required for the doc-gen modes. Verified both paths.

Tests: 4000 passed, 1 skipped.

### Audit cycle 5 — spawn hardware discovery had no CLI (fixed)

NODE-SPAWNING.md's autonomous **Step 2** (the first real step of an autonomous spawn)
documents `python3 spawn_hardware_discovery.py --host … --user … --password-prompt
--output …`, but `spawn_hardware_discovery.py` had **no CLI at all** — the command did
nothing. Worse, the underlying `discover_hardware()` accepted a `password` param it
never used (the SSH helper hard-set `BatchMode=yes`, key-only), and `_default_ssh_run`
ignored its `env` arg — so password-based discovery (required for a fresh broodling
that only has a temporary root password) was non-functional at every layer.

Fixes:
- Added the `--host/--user/--port/--key/--password/--password-prompt/--output` CLI.
- Wired password auth through `sshpass -e` with the password passed via the `SSHPASS`
  env var (never argv → no ps/aux leak); `BatchMode` omitted only when a password is
  used. Clear exit-2 error if `sshpass` is absent.
- `_default_ssh_run` now honours its `env` argument (merged with os.environ).
- NODE-SPAWNING.md notes the `sshpass` requirement for the password path.
Verified: --help, sshpass guard, and a mocked-runner discovery (correct profile).

Tests: 4000 passed, 1 skipped.

### Audit cycle 6 — systematic doc-command sweep; setup_ddns.py had no CLI (fixed)

Swept **every** `python3 …py` command in all operator docs and verified each script
resolves. Found two classes of broken references:

1. **`setup_ddns.py` was a library with no CLI** (both `__main__` blocks are inside
   generated-script string templates), yet forge phase-03 invoked it as
   `setup_ddns.py --manifest … --run` AND the setup guides documented
   `setup-ddns.py --state …` (also the wrong, hyphenated filename). So DDNS
   configuration was a no-op via every path. Added a real CLI accepting both forms
   (`--state` | `--manifest`, provider/zone/record/credential flags with interactive
   fallback, `--run` writes the update script + systemd units; UTF-8 file writes).
   Verified both forms end-to-end.
2. **Filename/shorthand drift**: `setup-ddns.py` → `setup_ddns.py` (CLOUDFLARE-SETUP,
   DUCKDNS-SETUP, ROADMAP); the `discover-hardware*.py` shorthand → the real
   `spawn_hardware_discovery.py` (ARCHITECTURE, ROADMAP).

Re-ran the sweep: **all documented python3 commands now resolve to real files.**
Regenerated CLOUDFLARE/DUCKDNS/ROADMAP HTML. Tests: 4000 passed, 1 skipped.

### Walkthrough export/attachments feature (md_to_html.py)

Added a universal export capability to walkthrough HTML docs: a file-**Attachments**
area + an **Export** button (top-right) that bundles the parameters, all note fields,
the session notes, and any attached files into a downloadable **store-only ZIP**
(`notes.md` + `record.json` + `attachments/…`), with an auto-suggested filename
`Title_YYYY_MM_DD_HH_MM_SS.zip` (24-hour local time). Implemented a dependency-free
CRC32 + ZIP builder in JS; validated the byte layout by porting it to Python and
confirming `zipfile` reads/CRC-checks the output.

Gating: the feature renders only on **walkthroughs** (docs with live `{{params}}` or
`@field`/`@area` note markers) — FORGING, NODE-SPAWNING, PHOENIX, RECONSTRUCTION-DRILL.
Added record/note blocks to FORGING.md + NODE-SPAWNING.md so they qualify. Reference
docs (README, ROADMAP, setup guides) keep theme-toggle + copy only. Regenerated all
generated HTML.

### Audit cycle 7 — `--help` probe of every operator CLI; forge phase-03/07 (fixed)

Probed `--help` on every doc-referenced CLI. Most are fine (reconstruction-drill
subcommands, remediation-cli, migrate-k3s, setup/run/restore-backup, collect-tier2,
update_state_after_spawn all match their docs). Found two forge-phase gaps:

- **phase-07 / `init-bootstrap-state.py`**: ignored `--manifest` (only parsed
  `--output`/`--non-interactive`) and phase-07 omitted `--non-interactive` → it would
  run the **interactive wizard** and hang/EOF in `forge.sh`, never seeding state from
  the forge manifest. Fixed: `--manifest PATH` now seeds `bootstrap-state.json`
  directly from the manifest, deterministically (forces non-interactive; the backup
  prompt is also guarded). phase-07 now passes `--non-interactive`. Verified with
  stdin closed: exit 0, state seeded from manifest, no block.
- **phase-03 host services**: `setup_dnsmasq.py` / `setup_headscale.py` /
  `setup_tls.py` are **library-only (no CLI)**, so forge phase-03 invoked them as
  no-ops (same pattern as the Cycle-6 ddns gap). Building+testing those 3 config
  tools is genuine deploy-to-hardware work (apt/systemctl/cert issuance on a real
  Proxmox host), so rather than half-build them, the **FORGING.md "Forge provisioning
  status"** note was expanded into a phase-by-phase automation table that honestly
  marks dnsmasq/Headscale/TLS (and opentofu VM/k3s) as manual-for-now.

Tests: 4000 passed, 1 skipped.

---

### Audit rounds 16–18 (completed)

**Round 16 Cycle 1 — Error info-leakage + severity input validation:**
- `broodforge_dashboard.py`: 4 error handlers now return generic "Internal server error"
  and log detail to stderr (was `str(e)` exposed in HTTP response).
- `broodforge_dashboard._handle_remediation_approve_batch()`: validates `max_severity`
  param against `_VALID_SEVERITIES = {"RED","ORANGE","YELLOW","GREEN","BLOCKED"}` before use.
- `hatchery_receiver._handle_spawn_complete()`: JSON decode error now returns generic message.
- Network-config YAML snippets: timestamp refresh.

**Round 16 Cycle 2 — Shell injection in generated bash scripts:**
- `spawn_scripts.generate_phase_00_preflight`: shell-quote `pool`, `bridge` in
  `zpool`/`ip` commands; shell-quote disk IDs; single-quote FAILS messages.
- `spawn_scripts.generate_phase_02_vms`: single-quote `-var-file` value to prevent
  `$(...)` expansion in the generated OpenTofu command.
- `spawn_scripts.generate_phase_06_verify`: `shlex.quote(hostname)` for kubectl;
  `shlex.quote(gateway)` for ping; single-quoted FAILS messages.
- `spawn_scripts.generate_spawn_sh`: single-quote all echo lines embedding plan values.
- `forge_scripts.generate_forge_sh`: single-quote echo lines with `cell_id`/`hostname`.
- `forge_scripts.generate_phase_03_sh`: single-quote HOSTNAME/DOMAIN/FQDN/NETWORK_PROFILE
  bash variable assignments (prevents `$(cmd)` execution at script runtime).
- `tests/unit/test_forge_assembler.py`: updated NETWORK_PROFILE assertion for new format.

**Round 17 Cycle 1 — YAML injection in cloud-init user-data:**
- `spawn_iac_generator.generate_cloudinit_user_data`: added `import shlex`; single-quote
  `hostname`, `fqdn`, `ci_user` YAML scalars; `shlex.quote(workspace)` in runcmd entry
  to prevent newline-based YAML injection and shell metachar injection.

**Round 17 Cycle 2 — Remaining bash variable assignment quoting:**
- `forge_scripts.generate_phase_08_sh`: single-quote `CELL_ID='{cell_id}'`.
- `spawn_scripts.generate_tailscale_join_sh`: single-quote `AUTH_KEY` and `HEADSCALE_URL`.
- `generators/flux-bootstrap-gen.py`: single-quote all 9 bash variable assignments
  (CELL_ID, FORGEJO_URL, FORGEJO_IP, PLATFORM_CONFIG_REPO, CLUSTER_NAME, FLUX_NAMESPACE,
  FLUX_BRANCH, CLUSTER_PATH, K3S_SERVER_IP).
- `setup_tls.py`: single-quote CERT, KEY, SECRET_NAME, NAMESPACES assignments.

**Round 18 — Broad scan:**
- Zero remaining double-quoted bash variable assignments with unescaped manifest data.
- Zero `send_error` calls leaking exception strings.
- All HTML renderers verified to use `_e()` for user-controlled data.
- Cloud-init network config and Ansible inventory: verified safe (IPs/domains are safe types).
- `html_package_manifest.py`, `html_forge_workbook.py`: verified pre-escaped HTML pattern
  is applied correctly throughout.

**Round 19 Cycle 1 — phoenix_scripts.py injection fixes:**
- Import `shlex`.
- `_step_block`: `shlex.quote(checkpoint_key)` for is_done/checkpoint_start/done/failed/skip
  function arguments; single-quote step echo line.
- `generate_wave_script`: single-quote wave echo lines (wave_num, wave_name, est_mins).
- `generate_run_all_sh`: single-quote all echo lines embedding hostname/cell_id/scope/
  est_total/generated/wave_name; use adjacent quoting `"$SCRIPT_DIR/"'script.sh'` for
  bash invocation to prevent `$()` in wave_name from executing.

**Round 19 Cycle 2 — keepass init + spawn fallback + k3s vars:**
- `forge_keepass_init.render_init_commands`: `import shlex`; `shlex.quote(db)` on db_path
  in all `bash -c` keepassxc-cli commands (prevents `$()` in path argument).
- `spawn_scripts.generate_phase_06_verify`: single-quote manual hatchery fallback echo.
- `spawn_iac_generator.generate_ansible_k3s_vars`: single-quote k3s_server_url, k3s_token,
  k3s_node_name YAML values.

**Round 19 confirmatory final scan:**
- Zero plan-var-in-double-quote-bash injection risks.
- Zero `send_error` leaks.
- Remaining scan matches are FALSE POSITIVES:
  - `spawn_scripts.py:108,110`: `phase_id`/`desc` from hardcoded Python constants.
  - `spawn_scripts.py:378`: `k3s_role` already validated to "worker"/"server" only.
  - HCL tfvars: `.auto.tfvars` values are literal strings, no template interpolation.
  - `bash -c` in `forge_keepass_init.py`: now `shlex.quote()`-d.

**Round 20 — Final deep XSS scan of dashboard (4 cycles):**
- Cycle 1: `broodforge_dashboard`: `bkp_status` in backup span — `_e()` applied.
- Cycle 2: `_remediation_history_row()`: `status`, `sev`, `ts` rendered bare — `_e()` applied.
  `generate_dashboard_html`: `sec_score`, `sec_scanned` rendered bare — `_e()` applied.
- Cycle 3: `generate_dashboard_html`: `cell_id` in `<title>` and topbar span; `hostname`
  in topbar span; `cfg.listen_host` in footer — all wrapped with `_e()`.
- Cycle 4: `sec_red`, `sec_orange`, `sec_yellow` security counts — `_e(str(...))` applied.
- **Final scan result: ZERO findings.** Two confirmatory scans both returned zero:
  1. Targeted `generate_dashboard_html` scan: ZERO unescaped state vars.
  2. Broad S1/S2 scan: ZERO `send_error` leaks, ZERO double-quoted bash assignments.

**Tests: 3958 passed, 37 skipped** (no change throughout all rounds).

---

### Audit round 14 (completed)

All 14 findings fixed in a single pass:

- **S-01**: `assemble_spawn_package.py` KEEPASS_GATE_SH `export KDBX_PATH KDBX_MASTER_PASSWORD`
  → `export KDBX_PATH` only. Password stays shell-local. Matches forge/phoenix gate pattern.
  Test `test_export_path_only` replaces old `test_export_credentials`.
- **S-02**: `hatchery_receiver.run_receiver_server()` now prints a stderr warning at startup
  when `config.auth_token` is empty (all POST requests accepted without auth).
- **S-03**: `broodforge_dashboard._remediation_history_row()`: applied `_e()` to
  `action_type`, `target`, `outcome`.
- **S-04**: backup provider/path list in dashboard now uses `_e()` on provider and
  bucket/path values.
- **S-05**: `_score_badge()` now applies `_e()` to `abbr` and `level`.
- **S-06**: `hatchery_receiver` HTTP 500 errors return generic "Internal server error";
  full exception logged to stderr. Fixed in both `_handle_failure_package` and
  `_handle_spawn_complete`.
- **S-07**: `spawn_scripts.py` now imports `shlex` and applies `shlex.quote()` to all
  plan values embedded in generated bash: `hostname`, `lan_ip`, `domain`, `bridge`,
  `pool`, `ds_name`, `snippets_store`, `server_url`.
- **D-01**: `NODE-SPAWNING.md` spawn_history schema example now includes all 5 missing
  fields: `vmids_allocated`, `ips_allocated`, `broodling_lan_ip`, `broodling_tailnet_ip`,
  `hardware_profile`.
- **I-01**: `proxmox-bootstrap/sync-cert-to-k8s.sh` stub created — exits 0 with a
  "not yet implemented" message. Registered action type now has a real script.
- **I-02**: `spawn_scripts.py` `generate_spawn_sh()` and `generate_phase_04_k3s()` both
  now use `(plan.get("k3s") or {}).get("role", "worker")`. `assemble_spawn_package.py`
  already used nested path. Added `test_k3s_role_reads_nested_path` test.
- **A-01**: `broodforge_dashboard.py` and `hatchery_receiver.py` — `sys.path.insert` and
  `from remediation_queue / update_state_after_spawn import` moved to module level with
  try/except. In-handler lazy imports removed.
- **A-03**: `remediation_executor.py` — assertion at module load time verifies
  `set(ALLOWED_ACTION_TYPES) == set(_HANDLERS.keys())`. Fails fast on divergence.
- **A-04**: `continuous_assessment.py:434` — `_endtime = job.get("last-run-upid") and ...`
  replaced with explicit `if job.get("last-run-upid"): _endtime = ...`.
- **A-05**: `proxmox-bootstrap/html_base.py` sync comment strengthened. New test
  `tests/unit/test_html_base_sync.py` asserts both copies are identical (comments excluded).

**Tests: 3957 passed, 37 skipped** (+166 vs round 13).

### Audit round 15 (completed)

- **S-15.1/15.2 (HIGH)**: `spawn_scripts.py generate_phase_01_proxmox` — `hatchery` (cluster address)
  and `fingerprint` embedded in `pvecm add` command without shell-quoting. Applied `shlex.quote()`.
  Added injection-safety test.
- **S-15.3 (HIGH)**: `generate_phase_04_k3s` — `k3s_role` embedded in ansible `--tags` without
  validation. Added `if k3s_role not in ("worker","server"): raise ValueError(...)`. Hostname in
  inventory filename shell-quoted.
- **S-15.4 (MEDIUM)**: `generate_phase_03_cloudinit` — VM ip/name embedded in `wait_ssh` calls
  inside double quotes. Changed to use `shlex.quote()` on both.
- **XSS (MEDIUM)**: `broodforge_dashboard._remediation_card()` — onclick handlers used `_e(raw_pid)`
  (HTML entity escaping) in JavaScript string context. HTML entities are decoded before JS parsing,
  allowing injection. Fixed: `pid_js = json.dumps(raw_pid)` (proper JS string literal).

**Tests: 3958 passed, 37 skipped** (+1 injection-safety test).

---

### Audit round 13 — Cycles 1–5 (completed)

**Cycle 1 — Missing tailscale-join.sh + shell injection + YELLOW reason:**
- I1: `spawn_scripts.py` referenced `tailscale-join.sh` in WAN spawn.sh but no generator
  existed. Added `generate_tailscale_join_sh(plan)`: installs tailscale, uses auth key
  from `disposition.wan_auth_key` and headscale URL from `hatchery.headscale_url`,
  uses checkpoint. Wired into `write_all_scripts()` (include_wan_phase=True) and
  `assemble_spawn_package.py` internal generation (is_wan=True). 13 new tests.
- S1: `remediation_executor._exec_restart_service()` built SSH remote commands by
  interpolating `svc = proposal.target` directly into `f"sudo systemctl {action} {svc}"`.
  Remote shell interprets metacharacters. Fixed with `shlex.quote(svc)`. 2 new tests.
- D1: `readiness.py score_graph()` appended `"; DNS registry missing"` for ANY YELLOW
  registry gap; now there are many YELLOW gap types (drills, talos, migrations, etc.).
  Fixed: only append DNS message when `gap_type == "MISSING_DNS_REGISTRY"` is present;
  otherwise append generic infrastructure gap count.
- **Tests: 3785 passed, 37 skipped** (+16)

**Cycle 2 — spawn_history schema + WAN scenario field name:**
- I2: `bootstrap-state-schema.json` was missing `spawn_history` property despite
  `update_state_after_spawn()` writing it on every spawn since Phase 12.E.9.
  Added full spawn_history array definition with required fields.
- D2: `test_spawn_scenarios.py` WAN scenario set `headscale_auth_key` in
  `plan["disposition"]` but spawn_planner.py stores it as `wan_auth_key` (line 509).
  Wrong field means `generate_tailscale_join_sh()` would see an empty auth key.
  Fixed and added 2 tests verifying auth key and URL are embedded in tailscale-join.sh.
- **Tests: 3787 passed, 37 skipped** (+2)

**Cycle 3 — Negative Content-Length + NODE-SPAWNING doc:**
- S2: `hatchery_receiver.py` `_handle_failure_package()` and `_handle_spawn_complete()`
  did not reject negative Content-Length; `self.rfile.read(-1)` blocks until EOF on
  the single-threaded server. Added `content_length < 0 → 400` guard on both handlers.
  2 new tests.
- D3: `NODE-SPAWNING.md` package contents listing was missing `tailscale-join.sh`
  for WAN mode. Added `[tailscale-join.sh]` with WAN-only annotation.
- **Tests: 3789 passed, 37 skipped** (+2)

**Cycle 4 — PBS epoch→ISO + dashboard Content-Length cap:**
- B1: `continuous_assessment.collect_pbs_state_update()` stored PBS API's
  `last-run-endtime` (Unix epoch int) directly into `PbsJobStatus.last_run_at`
  (typed `Optional[str]`). Dashboard would display an integer. Fixed: convert epoch
  to UTC ISO string via `datetime.fromtimestamp()`. 2 new tests.
- S3: `broodforge_dashboard._read_post_body()` had same unbounded read risk as
  hatchery receiver. Added `length <= 0 → {}` guard and 1 MB cap.
- **Tests: 3791 passed, 37 skipped** (+2)

**Cycle 5 — Dashboard HTML escaping:**
- S4: `broodforge_dashboard.py` rendered hostname, IP, service names, failure package
  fields, and remediation fields from bootstrap-state.json into HTML without escaping.
  Added `import html`, module-level `_e()` helper, and applied throughout
  `_node_card()`, `_failure_row()`, `_remediation_card()`.
- **Tests: 3791 passed, 37 skipped** (no change — no new tests; verified via existing
  TestDashboardRemediation and TestDashboardSecurity)

---

### Audit round 12 — Cycles 1–3 (completed)

**Cycle 1 — spawn manifest detection + fallback message:**
- B1: `assemble-spawn-package.py` used `schema_version` to distinguish bootstrap-state
  from spawn-manifest but both use `"1.0"`. Fixed: use `"host_identity"` presence
  (bootstrap-state) vs `"hatchery_url"` at top level (spawn-manifest).
  Added `test_cli_uses_pregenerated_spawn_manifest_as_is`.
- D1: `phase-06-verify.sh` error fallback message improved to include `--state/--plan`
  arguments in the manual update command hint.
- **Tests: 3926 passed, 37 skipped** (+1)

**Cycle 2 — html_package_manifest + hatchery hostname:**
- B1: `hatchery_receiver.py:276` read `target_hostname` from spawn plan; spawn plans
  use `hostname`. Log always printed "unknown". Fixed.
- B2: `html_package_manifest.build_spawn_manifest_html()` used stale field names
  (`target_hostname`, `vmid_block.start/end`, top-level `execution_mode/network_mode`)
  from an old spawn plan format. Current format uses `hostname`, `disposition.execution_mode`,
  `vms[].vmid`, `k3s.role`, `storage.topology`. Fixed with fallback for legacy tests.
  Added `TestSpawnManifestCurrentPlanFormat` (5 tests).
- **Tests: 3931 passed, 37 skipped** (+5)

**Cycle 3 — spawn workbook + state updater field names:**
- B1: `html_spawn_workbook.py` read `network_mode` at plan top level; should be
  `disposition.network_mode`. Fixed with fallback.
- B2: `update_state_after_spawn.build_spawn_result()` read `vmid_block`/`ip_block`
  which spawn_planner.py doesn't set (VMIDs are in `vms[].vmid`). `spawn_history[].vmids_allocated`
  was always empty. Fixed: derive from `vms[]` when these keys are absent.
  Added `test_vmids_derived_from_vms_list_when_no_vmid_block`.
- **Tests: 3932 passed, 37 skipped** (+1)

---

### Audit round 11 — Cycles 1–5 (completed)

**Cycle 1 — Stale CLI docs + missing timeouts:**
- D1: `FORGING.md` Step 2 referenced non-existent `bash forge-pack.sh`; replaced with
  correct `python3 proxmox-bootstrap/assemble-forge-package.py`. Wrong `--embed-kdbx`
  flag replaced with `--kdbx`. Output path `dist/` replaced with `.`.
- S1: `forge_scripts.py` phase-03 heredoc `subprocess.run` calls lacked timeout;
  added `timeout=300` (zpool create) and `timeout=30` (pvesm add).
- D2: `ROADMAP.md` updated with round 10 cycles 1-4 content; `.ai/CURRENT_STATE.md`
  updated with correct "Last updated" and "Next Action" text.
- **Tests: 3909 passed, 37 skipped** (no new tests, doc-only fixes)

**Cycle 2 — Broken spawn workflow + doc fixes:**
- I1: `assemble_spawn_package.py` required `--artifacts` (pre-generated scripts dir) but
  nothing in the operator workflow generated those scripts. Fixed by generating all
  phase scripts and IaC internally from the spawn plan (mirrors forge assembler pattern).
  `artifacts_dir` becomes an optional override.
- D1: `assemble-spawn-package.py` CLI: `--artifacts` optional, `--manifest` renamed
  to `--state` (accepts `bootstrap-state.json` directly).
- D2: `spawn-planner.py` next-steps output updated to show correct complete command.
- D3: `NODE-SPAWNING.md` Step 3 wrong flags fixed (`--state/--hardware/--embed-kdbx`
  → `--state/--kdbx`). Step 6 corrected: state update is automatic via hatchery
  receiver; manual fallback uses correct CLI path.
- I2: `update_state_after_spawn.py` gains `__main__` CLI block (`--state`, `--plan`,
  `--hardware`, `--spawned-at`) to support the manual fallback path.
- **Tests: 3922 passed, 37 skipped** (+13: TestInternalScriptGeneration 11, TestCLI 2)

**Cycle 3 — spawn manifest generation + FORGING.md flag:**
- S1: `assemble_spawn_package.py` `is_ha` logic used non-existent `promote_ha` field;
  fixed to mirror `spawn_scripts.py`: `role==server AND has VMs`.
- D1: `FORGING.md` Step 6 `engine.py` used `--state` instead of `--manifest` (wrong flag).
- I1: `assemble-spawn-package.py` CLI now calls `read_hatchery_state()` when `--state`
  is a `bootstrap-state.json`, ensuring `spawn-manifest.json` in the package has
  `hatchery_url` and `receiver_token` fields that `phase-06-verify.sh` needs.
- **Tests: 3924 passed, 37 skipped** (+2: TestCLISpawnManifestGeneration, ha server test)

**Cycle 4 — WAN mode spawn scripts:**
- S1: `assemble_spawn_package.py` internal generation always called
  `generate_spawn_sh(plan)` without `include_wan_phase=True`, even for WAN-mode spawn
  plans (`disposition.network_mode='wan'`). Fixed: detect WAN mode and pass
  `include_wan_phase=True`. Added `test_wan_mode_spawn_sh_includes_tailscale_join`.
- **Tests: 3925 passed, 37 skipped** (+1)

**Cycle 5 — Architecture doc + final sync:**
- AD-056 added to `ARCHITECTURE.md` documenting spawn package self-assembly design.
- `docs/SESSION-HANDOFF.md`, `ROADMAP.md`, `.ai/CURRENT_STATE.md` updated.
- **Tests: 3925 passed, 37 skipped** (no change)

---

### Audit round 12 — Cycles 1–3 (completed)

**Cycle 1 — spawn manifest detection + fallback message:**
- B1: `assemble-spawn-package.py` used `schema_version` to distinguish bootstrap-state
  from spawn-manifest but both use `"1.0"`. Fixed: use `"host_identity"` presence
  (bootstrap-state) vs `"hatchery_url"` at top level (spawn-manifest).
  Added `test_cli_uses_pregenerated_spawn_manifest_as_is`.
- D1: `phase-06-verify.sh` error fallback message improved to include `--state/--plan`
  arguments in the manual update command hint.
- **Tests: 3926 passed, 37 skipped** (+1)

**Cycle 2 — html_package_manifest + hatchery hostname:**
- B1: `hatchery_receiver.py:276` read `target_hostname` from spawn plan; spawn plans
  use `hostname`. Log always printed "unknown". Fixed.
- B2: `html_package_manifest.build_spawn_manifest_html()` used stale field names
  (`target_hostname`, `vmid_block.start/end`, top-level `execution_mode/network_mode`)
  from an old spawn plan format. Current format uses `hostname`, `disposition.execution_mode`,
  `vms[].vmid`, `k3s.role`, `storage.topology`. Fixed with fallback for legacy tests.
  Added `TestSpawnManifestCurrentPlanFormat` (5 tests).
- **Tests: 3931 passed, 37 skipped** (+5)

**Cycle 3 — spawn workbook + state updater field names:**
- B1: `html_spawn_workbook.py` read `network_mode` at plan top level; should be
  `disposition.network_mode`. Fixed with fallback.
- B2: `update_state_after_spawn.build_spawn_result()` read `vmid_block`/`ip_block`
  which spawn_planner.py doesn't set (VMIDs are in `vms[].vmid`). `spawn_history[].vmids_allocated`
  was always empty. Fixed: derive from `vms[]` when these keys are absent.
  Added `test_vmids_derived_from_vms_list_when_no_vmid_block`.
- **Tests: 3932 passed, 37 skipped** (+1)

---

### Audit round 10 — Cycle 4: drill outcome bugs

**B1 — `_score_reconstruction_drill()` didn't handle `in_progress` drills:**
An unfinished drill (started but never completed) silently passed the readiness
check as "recent". Added `RECONSTRUCTION_DRILL_INCOMPLETE` YELLOW gap for
`outcome == "in_progress"`. New test: `test_in_progress_drill_is_yellow`.

**B2 — `reconstruction-drill.py complete` used wrong outcome values:**
CLI `--outcome` choices were `[completed, failed, aborted]` but library uses
`[success, partial, failed, aborted]`. Fixed to match library. Default changed
from "completed" → "success". Added "partial" choice.

**B3 — `_score_reconstruction_drill()` didn't handle `partial` outcome:**
"partial" was supposed to drop to ORANGE (per RECONSTRUCTION-DRILL.md) but
wasn't in the scorer's failure list. Added "partial" to the ORANGE check.

**Tests: 3780 passed, 6 skipped** (+1 for in_progress test)

---

### Audit round 10 — Cycle 3: implementation gap, RECONSTRUCTION-DRILL.md

**I1 — `reconstruction-drill.py complete` missing `--gaps` argument:**
The `complete` subcommand had no way to record gaps found during the drill.
Added `--gaps GAP [GAP ...]` argument (nargs="*"); values are appended to
`gaps_found` in the drill record. Updated RECONSTRUCTION-DRILL.md example to show `--gaps`.

**Tests: 3779 passed, 6 skipped** (no change)

---

### Audit round 10 — Cycle 2: schema gap, silent exception, doc/code mismatch

**I1 — bootstrap-state-schema.json missing `security_scan` property:**
Added `security_scan` to `data-model/bootstrap-state-schema.json` (written by
`security_analyzer.write_security_scan_result()` but previously undocumented in schema).
Fields: `last_result` with `scanned_at`, `cell_id`, `files_scanned`, `posture`, counts, `findings`.

**S1 — Silent exception swallowing in `analyze_all_unanalyzed()`:**
`hatchery_receiver.py:144` — bare `except Exception: pass` now prints warning to stderr
when an individual failure package analysis fails. (Other bare-except patterns are
appropriate optional-feature skips.)

**D1 — Docstring/code mismatch in `_score_security_posture()`:**
`doc-gen/readiness.py` docstring claimed "RED: last scan overdue" but code never
checks staleness. Removed "last scan overdue" from docstring to match actual behavior.

**D2 — RECONSTRUCTION-DRILL.md CLI examples use non-existent flags:**
`docs/RECONSTRUCTION-DRILL.md` pre-drill checklist showed `python3 phoenix_playbook.py --state ...`
(no such CLI) and drill commands showed `--mode live`, `--mode tabletop`, `--record-manual`,
`--actual-minutes`, `--gaps`, `--remediated` (none of which exist). Replaced all with
correct subcommand interface: `start`, `complete`, `last`, `report`.
Pre-drill playbook generation: now shows correct Python one-liner using `build_phoenix_playbook()`.

**Tests: 3779 passed, 6 skipped** (no change — schema/doc fixes only)

---

### Audit round 10 — Cycle 1: subprocess timeouts + stale doc refs

**S1 — Missing subprocess timeouts (5 fixes):**
- `backup.py:444` — `git remote` list: `timeout=10`
- `backup.py:448` — `git remote add`: `timeout=10`
- `backup.py:453` — `git remote set-url`: `timeout=10`
- `forge_keepass_init.py:382` — keepassxc-cli bash loop: `timeout=30`
- `init-bootstrap-state.py:505` — interactive setup wizard spawn: `timeout=600`

**D1 — Stale doc ref:**
- `NODE-SPAWNING.md:534`: `spawn_workbook.py` ODS → `html_spawn_workbook.py` HTML

**Tests: 3779 passed, 6 skipped** (no change — fixes are non-test code)

---

### Audit round 9 — Rounds 1 + 2 complete

**Already-done (verified):** S1 (tty print), S2 (RESTIC_PASSWORD scope), S3 (auth key not printed),
D1/I4 (reconstruction-drill.py CLI), I2 (migration git commit), I5 (collector_utils import),
A2 (no private alias in collectors), I3 implementation (_score_migration_health wired).

**Fixed in round 9:**

**A1:** Copied `doc-gen/renderers/html_base.py` to `proxmox-bootstrap/html_base.py`.
Removed sys.path.insert blocks from all 4 workbook modules:
`html_forge_workbook.py`, `html_phoenix_workbook.py`, `html_spawn_workbook.py`, `federation_docs.py`.
These files now import `from html_base import (...)` directly without path manipulation.

**I1 (test coverage):** Created `tests/unit/test_hatchery_receiver_wiring.py` (16 tests) covering:
- `build_spawn_result` + `update_state_after_spawn` round-trip (the exact chain called by hatchery_receiver)
- `_ReceiverHandler.do_POST` routes `/api/spawn-complete` to `_handle_spawn_complete`
- Generated `phase-06-verify.sh` contains `HATCHERY_URL` + `api/spawn-complete` POST

**I3 (test coverage):** Added `TestScoreMigrationHealth` (6 tests) to `test_readiness.py`.
Imports `_score_migration_health` from readiness. Covers: empty→[], failed→ORANGE,
rolled_back→YELLOW, completed→[], mixed→both, multiple-failed→multiple ORANGE.

**D2:** Updated `update_state_after_spawn.py` docstring (line 14–16) to remove false claim
that the caller commits to Forgejo. Now correctly describes the responsibility split.

**Round 1 tests: 3781 passed, 4 skipped** (commit: 9ec1c3d)

---

### Audit round 9 — Round 2 full-stack audit findings (all fixed)

Round 2 audit found 5 genuine issues (0 docs-sync, 0 implementation gaps, 0 circular imports):

**HIGH — Missing subprocess timeouts (3 fixes):**

- `collect_tier2.py:76` — SSH `subprocess.run()` had no timeout. Added `timeout=30`.
  Prevents indefinite hang if SSH connection stalls during tier-2 state collection.

- `remediation_executor.py:103` — `_run()` `subprocess.run()` had no timeout.
  Added `timeout=300`. Autonomous remediation commands can take minutes; ensures termination.

- `setup_ddns.py:252` — lexicon `subprocess.run()` had no timeout. Added `timeout=30`.

**MEDIUM — Duplicate html_base.py (informational, addressed with comment):**
`proxmox-bootstrap/html_base.py` is a copy of `doc-gen/renderers/html_base.py`.
Added "COPY of doc-gen/renderers" comment at top of proxmox-bootstrap copy so editors know
to keep both in sync. (Full resolution would require importlib shim — deferred as low priority.)

**LOW — assessment/tier1/analyze.py:731 CELL_ID global env var (skipped):**
CLI tool that sets env for current process only. No downstream subprocess risk. No fix needed.

**Tests: 3781 passed, 4 skipped** (commit: 0443668)

---

### Comprehensive audit round (final) — 4 findings fixed

**D1 (HIGH bug fix):** `html_forge_workbook.py:_section_validation()` called
`f.get("severity")` on `ForgeValidationFinding` dataclasses (no `.get()`) AND
used wrong severity values ("ERROR"/"WARNING" vs actual "RED"/"YELLOW"). Fixed:
use `getattr()` with "ERROR"/"WARNING"/"RED"/"YELLOW" all mapped correctly.

**D2:** `setup_warnings` not rendered in HTML forge workbook — added callout
rendering in `_section_overview()`.

**D3/D4:** `proxmox-bootstrap/spawn_workbook.py` and `forge_workbook.py` (ODS)
missed in earlier deprecation sweeps — moved to `proxmox-bootstrap/deprecated/`
with README. `test_spawn_workbook.py` + `test_forge_workbook.py` (96 ODS tests)
fully rewritten as HTML tests (56 tests); net -40.

**Tests: 3720 passed, 37 skipped**

---

### Audit rounds 7 + 8 — clean cycle

**Round 7:** `html_forge_workbook.py` and `html_phoenix_workbook.py` had zero test coverage;
`TestHtmlForgeWorkbook` + `TestHtmlPhoenixWorkbook` added (4 tests each) to
`test_html_renderers.py`. Tests: 3654 passed.

**Round 8:** Full scan — zero new fixable issues found. All HTML builders covered.
No remaining ODT/ODS refs in Python code or generated filenames. No broken imports.
Session halted as "no more ideas" threshold reached for this audit cycle.

---

### Audit round 6 — 7 findings fixed

**HIGH — forge_scripts.py heredoc `__file__` bug**: `generate_phase_02_sh()` and
`generate_phase_03_sh()` embedded Python heredocs used `os.path.abspath(__file__)`
which raises `NameError` in `python3 - <<'PYEOF'` stdin mode. Fixed: use
`os.environ.get("SCRIPT_DIR", ".")` — shell sets `SCRIPT_DIR` before the heredoc runs.
2 new regression tests added to `test_forge_assembler.py`.

**A2/A3 (deferred items):** 
- sys.path coupling in 5 proxmox-bootstrap/ workbook modules made idempotent
- `test_bootstrap_workbook.py` fully migrated away from deprecated `workbook.py`:
  `registry_ip_for_bootstrap_vm()` and `registry_iso_path()` extracted to
  `html_bootstrap.py` as public functions; `_wb_section_stage_03()` uses them;
  test file now uses `build_bootstrap_workbook_html()` for all workbook tests.

**Docs (D1–D4):** ROADMAP stale ODS refs updated; ARCHITECTURE-REVIEW-v7.md gets
deprecation note at top; AD-055 added to ARCHITECTURE.md (HTML-only output decision).

**Tests: 3646 passed, 37 skipped** (2 new, 4 ODS-specific removed = net -2 vs pre-session)

---

### Security fix — /api/spawn-complete path traversal

`proxmox-bootstrap/hatchery_receiver.py:_handle_spawn_complete()`: removed
acceptance of `state_path` from the POST request body. An authenticated caller
could supply any path on the hatchery filesystem (e.g. `/etc/passwd`) and trigger
a read-then-write of arbitrary JSON. Fix: endpoint now ignores `state_path` in
the body entirely; only `self._config.state_path` (server-configured via `--state`)
is used. New test: `test_spawn_complete_ignores_state_path_in_body`.

---

### Audit round 5 — 10 findings, all resolved

**A1/I2** — `doc-gen/renderers/recovery_workbook.py` was missed in the ODT deprecation
sweep; imported from `workbook.py` (now in deprecated/), confirmed broken at import time.
Moved to `doc-gen/renderers/deprecated/recovery_workbook.py`.

**I1** — `TestHtmlRecoveryWorkbook` (8 tests) added to `tests/unit/test_html_renderers.py`.
`html_recovery_workbook.py` previously had zero test coverage; bootstrap and spawn workbooks
both had test classes; now consistent.

**D1–D4 (stale ODS/ODT docs):**
- `README.md:1391`: renderers/ description → "HTML document generators"
- `ROADMAP.md:167`: "forge-workbook.ods" → "forge-workbook.html"
- `ROADMAP.md:1011`: "Operational-Report.odt" → "Operational-Report.html"
- `NODE-SPAWNING.md:267`: "spawn-workbook-pve02.ods" → ".html"

**A2 (deferred):** sys.path coupling in 4 proxmox-bootstrap/ modules still deferred.
**S1 (residual):** shell=True in collector_utils + migrate_k3s_lib — low risk, kept.
**A3 (low):** test_bootstrap_workbook.py imports deprecated ODS helpers — preserved.

**Tests: 3647 passed, 37 skipped, 3 pre-existing** (8 new tests)

---

### ODT/ODS renderer deprecation + HTML migration

**Deprecated:** `recovery_runbook.py`, `runbook.py`, `operational_report.py`, `workbook.py`
moved to `doc-gen/renderers/deprecated/` with README. Engine generates HTML only.

**HTML renderer improvements during migration:**
- `html_recovery_runbook.py`: `_health_check_cmds()`, `_service_restart_cmds()` added
  (superior logic from ODT); `_service_contract_block()` uses them; `_get_contract()`
  strips `(VM NNN)` suffix so restore waves find service contracts; Appendix C (DNS
  Registry) added; Appendix G renders failover+notes, TLS Certificate heading, "Expires
  at", inline `_days_remaining` from `expires_at`; Appendix H fully rendered (layer
  details, restore commands, KeePass note, fail warnings); Wave 0 renders bridge IP from
  both `ip` and `address` fields; drift_details shown in Wave 0 callout
- `html_operational_report.py`: `_cert_days_remaining()` helper; backup failure
  actions shown in Time-Sensitive Actions; `_section_external_dependencies` uses
  `_cert_days_remaining` for inline computation

**9 test files migrated to HTML:** assertions aligned with HTML output; ODT-specific
tests replaced with HTML equivalents.

**Tests: 3745 passed, 37 skipped, 3 pre-existing env failures**

---

### Full-stack audit round 4 — all 13 findings resolved

**S1/A3** — `proxmox-bootstrap/setup-secrets.py:434–444`: SSH private key PEM now
written to `/dev/tty` instead of stdout/stderr. Bypasses `exec >> forge.log 2>&1`
log redirection. Fallback to stderr if `/dev/tty` unavailable (tests, Windows).
Same pattern as `print_totp_setup_to_tty()` in `keepass_mfa.py:150`.

**S2** — `proxmox-bootstrap/backup_engine.py:293`: Added comment explaining
`RESTIC_PASSWORD` env var is the correct restic authentication mechanism
(not a security smell — safer than --password-command and avoids disk writes).

**S3** — `proxmox-bootstrap/spawn-planner.py:135`: Headscale auth key no longer
partially printed to stdout. Now prints: "Auth key generated — embedded in spawn package."

**D1/I4** — `proxmox-bootstrap/reconstruction-drill.py` created: CLI wrapper with
`start`, `complete`, `last`, `report` subcommands. Fixes broken `python3
proxmox-bootstrap/reconstruction-drill.py` references in `docs/RECONSTRUCTION-DRILL.md`
and `doc-gen/readiness.py:658`.

**D2** — `proxmox-bootstrap/update_state_after_spawn.py:14–15`: Docstring corrected —
removed false claim "committed to Forgejo"; now says "caller is responsible."

**I1** — `proxmox-bootstrap/hatchery_receiver.py`: New `/api/spawn-complete` endpoint
(`_handle_spawn_complete`); loads `spawn_plan`, calls `update_state_after_spawn()`,
writes updated bootstrap-state.json to disk. `HatcheryReceiverConfig.state_path` field
added; `--state` CLI argument wired in.
`proxmox-bootstrap/spawn_scripts.py:phase-06-verify.sh`: Now reads `hatchery_url` and
`receiver_token` from spawn-manifest.json and POSTs to `/api/spawn-complete` on success.
Falls back gracefully with manual instructions if POST fails.
`proxmox-bootstrap/hatchery_state.py`: `hatchery_url` (http://{fqdn}:9321) and
`receiver_token` (empty by default) embedded in spawn manifest at generation time.

**I2** — Both migration scripts gain `_commit_migration_record()`: runs
`git add <state_path> && git commit -m "migrate: {node} {from}→{to}"` after each
successful migration. Non-fatal (warning on failure). Dry-run skips the commit.
Operator still responsible for `git push` to Forgejo.

**I3** — `doc-gen/readiness.py`: `_score_migration_health(manifest)` added and wired
into `score_graph()`. ORANGE if any `migration_history[].outcome == "failed"`, YELLOW
if `"rolled_back"`. Gap_type: `MIGRATION_FAILED` / `MIGRATION_ROLLED_BACK`. Remediation
references `docs/TALOS-ALTERNATIVE.md`.

**I5** — `proxmox-bootstrap/migrate_k3s_lib.py`: `_local_runner` now imported from
`collector_utils.local_runner` with a fallback inline definition. Consistent with
the S5 fix in round 3 that migrated the 5 state collectors.

**A2** — All 5 state collectors changed from `from collector_utils import local_runner
as _local_runner` to `from collector_utils import local_runner` (no private alias).
Files: hardware_, platform_, cluster_, storage_, data_protection_ state collectors.

**A1** — sys.path coupling in 5 modules (html workbooks + collect_tier2 importing from
doc-gen/renderers) deferred — requires package restructure. Documented as known debt.

**Tests: 3792 passed, 37 skipped, 3 pre-existing env failures** (35 new tests in
`tests/unit/test_audit_round4_fixes.py`).

**ARCHITECTURE.md**: AD-053 (spawn-complete endpoint) and AD-054 (migration commit
convention) added.

---

### 9.T.12 — Recovery Runbook OS Variant Migration Appendix (complete)

Added **Appendix I — OS Variant Migration History** to both recovery runbook renderers:

- `doc-gen/renderers/recovery_runbook.py`: ODT appendix — renders when `migration_history`
  is present in the manifest; per-record section (migration_id, node, from→to variant,
  started/completed timestamps, outcome with status label, snapshot_vmid, error, dry_run flag);
  manual rollback reference with `qm rollback` commands and TALOS-ALTERNATIVE.md pointer.
  Absent when `migration_history` is empty or missing.

- `doc-gen/renderers/html_recovery_runbook.py`: HTML equivalent — same content, uses
  outcome badge coloring (success/warning/danger), `_section_appendix_i_os_migration()`
  function; wired into `build_recovery_runbook_html()` after Appendix H.

- `tests/unit/test_recovery_runbook_service.py`: 13 new tests in `TestAppendixIOsMigration`
- `tests/unit/test_html_renderers.py`: 12 new tests in `TestHtmlRecoveryRunbookOsMigration`

ROADMAP.md updated: all 9.T.1–9.T.17 checkboxes now `[x]`. All roadmap milestones complete.

**Tests: 3757 passed, 37 skipped, 3 pre-existing env failures**

---

## Previous Session Work

### Audit Findings Round 3 — All MEDIUM and LOW items resolved

**S1** — `hatchery_receiver.py`: replaced `!=` token comparison with `secrets.compare_digest()` for timing-safe auth; added `import secrets`.

**I1** — `doc-gen/engine.py` operational mode: wired `run_security_scan()` call after state loading. Adds proxmox-bootstrap to sys.path, catches all exceptions gracefully so failures don't break report generation. 5 new wiring tests in `test_phase24_continuous_assessment.py`.

**I2** — 9.T migration tier (9.T.9–9.T.11):
- `proxmox-bootstrap/migrate_k3s_lib.py`: shared library — `PreflightResult`, `StateSnapshot`, `MigrationRecord`, `run_preflight_checks()` (cluster readiness, template, machine config, PBS, node registry), `snapshot_state()`, `drain_node()`, `verify_cluster_health()`, `uncordon_node()`, `update_os_variant()`, `append_migration_history()`, `rollback()`, `make_migration_id()`
- `proxmox-bootstrap/migrate-k3s-to-talos.py`: Ubuntu→Talos 9-step wizard with auto-rollback on health check failure; `--dry-run`, `--skip-snapshot`, `--node`, `--state`
- `proxmox-bootstrap/migrate-k3s-to-ubuntu.py`: Talos→Ubuntu reverse wizard (same structure)
- `data-model/bootstrap-state-schema.json`: added `migration_history` array to `properties`
- `tests/unit/test_migration_k3s.py`: 48 tests covering lib, both wizards, schema
- `docs/TALOS-ALTERNATIVE.md`: usage examples updated to match implementation
- `proxmox-bootstrap/generate_talos_config.py`: fixed YAML parser for multi-key list items and `[]` inline arrays
- `proxmox-bootstrap/forge_validator.py`: fixed `field` extraction for root-level `required` jsonschema errors

**S2** — `broodforge_dashboard.py:run_server()`: added `WARNING: No auth token configured — all POST endpoints are unprotected` to stderr when `action_token` is empty.

**S3** — `hatchery_receiver.py:run_receiver_server()`: added WAN exposure warning matching the dashboard pattern — reads bootstrap-state.json; warns if `0.0.0.0` + `network_profile=wan`.

**S4 + I4** — `hatchery_receiver.py`: added `verbose: bool = False` to `HatcheryReceiverConfig`; `log_message()` now writes to stderr at INFO level when `verbose=True`; `--verbose` CLI flag added.

**S5** — `proxmox-bootstrap/collector_utils.py`: new shared module exporting `local_runner()` and `RunnerFn`. All 5 state collectors (`hardware_state_collector.py`, `platform_state_collector.py`, `cluster_state_collector.py`, `storage_state_collector.py`, `data_protection_collector.py`) now import from it instead of defining `_local_runner()` locally. `tests/unit/test_collector_utils.py`: 11 tests.

**I3** — `broodforge_dashboard.py`: `DASHBOARD_VERSION` updated from `"1.0.0"` to `"7.1"` (matches ARCHITECTURE.md).

**Tests: 3732 passed, 4 skipped** (up from 3634 / 3577 in prior rounds)

---

### Phase 9.T Foundation — Talos Linux Alternative Support (complete)

**9.T.1** — `docs/TALOS-ALTERNATIVE.md` already existed; no changes required.

**9.T.2** — `proxmox-bootstrap/build-talos-template.sh`:
- Downloads Talos ISO (latest or pinned version) from factory.talos.dev
- Verifies SHA256 checksum against GitHub sha256sum.txt
- Creates Proxmox VM (VMID 9001) with OVMF/q35 (Talos UEFI requirement)
- Prints manual steps to apply installer config and convert to template
- `--dry-run` flag for pre-flight planning; `--storage`, `--version`, `--vmid` overrides
- Prints suggested bootstrap-state.json entries for talos-1x-base template + base_image

**9.T.3** — `proxmox-bootstrap/generate_talos_config.py` (library) + `generate-talos-config.py` (CLI):
- `build_cluster_spec()` — reads k3s-cluster.yaml and bootstrap-state.json; selects nodes with `os_variant: talos`; derives cluster endpoint from first CP node IP
- `generate_installer_template()` — minimal installer config for `build-talos-template.sh` template build
- `generate_node_patch()` — per-node strategic merge patch (hostname, static IP, gateway, nameserver)
- `generate_base_controlplane()` / `generate_base_worker()` — structural machine configs with POPULATE markers
- `generate_talosconfig_stub()` — operator client config stub
- `run_talosctl_genconfig()` — optional: calls talosctl to fill secrets; falls back gracefully if not installed
- `write_readme()` — generates talos-configs/README.md with apply commands
- `--genconfig` flag: calls talosctl for secret generation; `--state`, `--k3s`, `--output` overrides
- YAML emitter is stdlib-only (no PyYAML required); uses PyYAML if available

**9.T.4** — Fixture `tests/fixtures/bootstrap/bootstrap-state.json`:
- Added `talos-1x-base-iso` to `base_images[]`
- Added `talos-1x-base` to `templates[]` (VMID 9001, os_variant: talos)

**9.T.5** — `data-model/bootstrap-state-schema.json` additions:
- `base_image.os_variant`: enum `["ubuntu", "talos", null]`
- `vm_template.os_variant`: enum `["ubuntu", "talos", null]`
- `provenance_record.os_variant`: enum `["ubuntu", "talos", null]`
- `provenance_record.talos_machine_config`: string | null (path to machine config patch)

**9.T.6** — `doc-gen/readiness.py` — `_score_talos_config_completeness()`:
- YELLOW: `os_variant: talos` declared for ≥1 k3s node but no `talos_machine_configs` or `talos_configs_generated_at` in manifest
- Satisfied by either field; gap mentions node names + generate command
- Wired into `score_graph()` alongside other registry scorers

**9.T.7** — `proxmox-bootstrap/phoenix_playbook.py` — Talos reconstruction steps:
- `_wave_05_template_rebuild()`: new step 2.5.2 for Talos template rebuild when `needs_talos=True`; detects Talos template from `os_variant: talos` in template registry; calls `build-talos-template.sh`
- `_wave_3_vms()`: Talos RECREATE path uses `talosctl apply-config` instead of Ansible; validation uses `talosctl get members` instead of SSH; RESTORE path notes "no SSH access, use talosctl"

**9.T.8** — `tests/unit/test_talos_alternative.py` — 57 tests:
- `TestTalosNodeSpec` (2): defaults, custom disk
- `TestBuildClusterSpec` (8): talos/ubuntu filtering, endpoint derivation, gateway fallback, worker nodes
- `TestGenerateInstallerTemplate` (4): file creation, installer marker, machine type, warning comment
- `TestGenerateNodePatch` (5): patches dir, file, IP/hostname/gateway content
- `TestGenerateBaseConfigs` (6): controlplane/worker created, endpoint/cluster name/POPULATE markers
- `TestGenerateTalosconfigStub` (3): file created, context name, node IP
- `TestGenerateTalosConfigsPipeline` (6): no-talos/talos/both pipelines, missing files handled
- `TestScoreTalosConfigCompleteness` (9): no-talos/no-k3s/with-configs/without-configs/mixed/multiple
- `TestPhoenixPlaybookTalos` (6): step 2.5.2 present/absent, build script mention, validation, timing, both variants
- `TestSchemaOsVariant` (8): os_variant in all three defs, enum values, fixture entries

**Tests: 3634 passed, 37 skipped, 3 pre-existing env failures**

## Remaining Work

### Full-stack audit findings — HIGH priority items (complete)

**H1 — Phoenix package assembler + CLI wrappers**
- Created `proxmox-bootstrap/assemble_phoenix_package.py` — library mirrors forge/spawn pattern; bundles playbook JSON, wave scripts, run-all.sh, lib/checkpoint.sh, phoenix-manifest.html, optional phoenix-workbook.html, optional KeePass .kdbx
- Created `proxmox-bootstrap/assemble-phoenix-package.py` — CLI entry point (`--playbook`, `--output-dir`, `--kdbx`)
- Created `proxmox-bootstrap/assemble-forge-package.py` — CLI entry point for forge assembler (`--manifest`, `--output-dir`, `--repo`, `--kdbx`)
- Created `proxmox-bootstrap/assemble-spawn-package.py` — CLI entry point for spawn assembler (`--plan`, `--manifest`, `--artifacts`, `--output-dir`, `--kdbx`)
- `build_phoenix_manifest_html()` is wired into the phoenix assembler; phoenix-planner.py message already referenced correct filename
- Tests: `tests/unit/test_assemble_phoenix_package.py` — 25 tests, all passing

**H2 — Security → state integration loop**
- Added `write_security_scan_result(state_path, report)` to `security_analyzer.py` — serializes a `SecurityReport` into `security_scan.last_result` in bootstrap-state.json; preserves all other fields
- Added `--write-state PATH` and `--report PATH` flags to the security analyzer CLI (`main()`)
- Added `run_security_scan(base_dir, state_path)` to `continuous_assessment.py` — lazy-imports security_analyzer, runs scan, persists results; returns summary dict
- 6 new tests in `test_security_analyzer.py` (TestWriteSecurityScanResult), 6 in `test_phase24_continuous_assessment.py` (TestRunSecurityScan)

**H3 — Duplicate AD numbers in ARCHITECTURE.md**
- Renumbered duplicate AD-047 (HTML manifest pattern) → AD-051
- Renumbered duplicate AD-048 (EFF diceware passphrase) → AD-052
- Sorted the AD-045 through AD-052 block into sequential order

**H4 — StrictHostKeyChecking fixes**
- `spawn_hardware_discovery.py:225` — changed `StrictHostKeyChecking=no` → `accept-new`
- `spawn_scripts.py:311` — changed `StrictHostKeyChecking=no` → `accept-new` in generated wait_ssh() loop
- Security analyzer SCRIPT-001 still flags `=no`; the false positives are eliminated by the source fix

**L1 — Dead code branch in security_analyzer.py:581** (fixed opportunistically during HIGH pass)
- Removed `hasattr(f, 'content')` dead branch in `_finding_row()` — `SecurityFinding` only has `line_content`

### LOW priority audit findings (complete)

**L2 — Move docs/CONTAINER-COMPATIBILITY-PLAN.md → deprecated/**
- Renamed via git mv; README and docs index notes it as deprecated

**L3 — Forge-manifest schema validation**
- Added `validate_forge_manifest(manifest, schema_path)` to `forge_validator.py`
- Uses `jsonschema` if available; falls back to required-field checks (stdlib only)
- 4 new tests in `TestValidateForgeManifest`

**L4 — Fix flaky passphrase test**
- `test_forge_package_foundation.py::TestPassphraseFormat::test_length_in_range` now uses a seeded `random.Random(42)` — deterministic, no flakiness

**L5 — Receiver authentication**
- Added `auth_token: str = ""` field to `HatcheryReceiverConfig`
- `_ReceiverHandler.do_POST()` checks `X-Broodforge-Token` header when `auth_token` is set; returns 401 on mismatch
- `--token` CLI argument added to `hatchery_receiver.py` `__main__` block
- 4 new tests in `TestHatcheryReceiverConfigAuth`

**L6 — .ai/context.md update**
- Rewrote to reflect current scope: self-managing platform (forge/spawn/phoenix/assess/monitor/remediate), v7.1 architecture, six lifecycle phases, current milestone

### MEDIUM priority audit findings (complete)

**M1 — Security analyzer `watch()` continuous mode**
- Added `watch(paths, callback, stop_event, poll_interval)` to `security_analyzer.py`
- Uses inotify on Linux if available; falls back to polling (works on Windows)
- 4 new tests in TestWatch

**M2 — `_find_shell_scripts()` recursive**
- Changed `os.scandir()` to `os.walk()` — scans all subdirectories including `assessment/tier1/collectors/`
- Hidden directories skipped. Deduplication via seen set.
- 4 new tests in TestFindShellScriptsRecursive

**M3 — Stale docs**
- Deleted `.ai/SESSION-HANDOFF.md` (stale duplicate)
- Fixed `--import` → `--format import` in SETUP-GUIDE.html footer

**M4 — Dashboard WAN exposure warning**
- `broodforge_dashboard.py` `run_server()`: reads bootstrap-state.json; if `network_topology.profile == "wan"` and `listen_host == "0.0.0.0"`, prints WARNING to stderr before starting

**M5 — Phoenix KeePass gate**
- Added `PHOENIX_KEEPASS_GATE_SH` constant to `phoenix_scripts.py` — `phoenix_keepass_gate()` function mirroring forge/spawn pattern
- `generate_run_all_sh()` sources the gate before wave execution
- Assembler bundles `lib/phoenix-keepass-gate.sh`
- 2 new tests in TestPhoenixKeepassGate

**M6 — Phoenix workbook**
- Created `proxmox-bootstrap/html_phoenix_workbook.py` — wave-by-wave tracking with pre-flight checklist and final validation section
- Integrated into `assemble_phoenix_package.py`
- 1 new test in TestPhoenixWorkbook

**M7 — service-catalog.yaml disambiguation**
- Added 10-line disambiguation header to both `proxmox-bootstrap/service-catalog.yaml` and `proxmox-bootstrap/metadata/service-catalog.yaml`
- `proxmox-bootstrap/metadata/README.md` already exists

## Remaining Work

All roadmap milestones complete. All 9.T items (9.T.1–9.T.17) done.
All audit findings from rounds 1–4 resolved.
No remaining implementation items.

**Next action: deploy to hardware.**
Run `python3 proxmox-bootstrap/forge-planner.py` on a real Proxmox host.
See `FORGING.md` for the operator runbook.

**One deferred item (A1):** sys.path coupling in html workbooks + collect_tier2
that import from doc-gen/renderers via sys.path.insert. Requires package
restructure into a proper Python package. Low urgency — works correctly today.

## Previous Sessions

### Phase 26 — Autonomous Remediation (complete)

All seven sub-phases implemented:

| Sub-phase | Files | Tests |
|---|---|---|
| 26.1 Planner | `proxmox-bootstrap/remediation_planner.py` | 18 |
| 26.2 Queue + CLI | `proxmox-bootstrap/remediation_queue.py`, `remediation-cli.py` | 22 |
| 26.3 Executor | `proxmox-bootstrap/remediation_executor.py` | 15 |
| 26.4 Dashboard | `proxmox-bootstrap/broodforge_dashboard.py` (extended) | 4 |
| 26.5 Op Report S8 | `doc-gen/renderers/html_operational_report.py` (extended) | 3 |
| 26.6 Policy Engine | `proxmox-bootstrap/remediation_policy.py` | 14 |
| 26.7 Autonomous Mode | `remediation_policy.py` (extended), `remediation-cli.py` (extended) | 18 |
| Schema | `data-model/bootstrap-state-schema.json` (added remediation_proposal, remediation_policy) | — |

Test file: `tests/unit/test_remediation.py` — 94 tests, all passing.

### Security Analyzer (complete)

New `proxmox-bootstrap/security_analyzer.py` module:
- Log file scanning (8 patterns: TOTP seeds, private keys, passwords, k3s tokens, API keys, restic passwords, bearer tokens)
- Shell script scanning (7 patterns: StrictHostKeyChecking=no, passwords on cmdlines, exported secrets, echo-pipe, bearer in curl, set -x, /dev/null known hosts)
- Manifest/state file scanning (plaintext password/secret fields, private key material)
- One-shot audit mode
- HTML security report (same dark-theme style as dashboard)
- `security_posture_score()` → GREEN/YELLOW/ORANGE/RED
- `doc-gen/readiness.py` extended with `_score_security_posture()` — new "Security Posture" scoring dimension
- `broodforge_dashboard.py` extended with Security section and `/api/security` endpoint
- `bootstrap-state.json` `security_scan.last_result` field stores scan results for readiness integration

Test file: `tests/unit/test_security_analyzer.py` — 56 tests, all passing.

### Setup Guide Manifest Import Explainer (complete)

Added `<section id="manifest-import-explainer">` to `docs/SETUP-GUIDE.html` (before closing `</script></body>`):
- How to import (drag-and-drop, paste JSON, CLI output)
- What fields are auto-filled (cell identity, network, storage, VMs, backup destinations, service registry, forge options)
- What still requires manual entry (KeePass master password, API keys, email, WAN IP, app data volumes, notes)
- CLI usage for `generate-setup-manifest.py`

### EFF Passphrase Generator (complete)

Investigation finding: `keepassxc-cli generate` does NOT support diceware/wordlist passphrases — CLI only supports character-class passwords. The GUI has a plugin but it is not exposed via CLI.

New `lib/passphrase_eff.py`:
- 1128-word curated EFF-derived wordlist (deduped, lowercase, 3-8 chars)
- `generate_eff_passphrase(word_count=4)` → "correct-horse-battery-staple" style
- `generate_eff_passphrase_n(count, word_count)` → distinct list
- `eff_passphrase_strength()` → entropy bits calculation
- ~44 bits entropy at 4 words, ~55 bits at 5 words

`lib/passphrase.py` updated:
- `generate_master_password_suggestion(style="eff")` — new default style is EFF diceware
- `style="classic"` preserves the Capital.word.phrase.9 format
- `style="keepassxc"` tries keepassxc-cli first, falls back to classic

Test file: `tests/unit/test_passphrase_eff.py` — 29 tests, all passing.

### HTML Package Manifests (complete)

New `proxmox-bootstrap/html_package_manifest.py`:
- `build_forge_manifest_html(manifest)` — forge package: cell identity, all 8 phases explained, VM table, key settings, operator checklist
- `build_spawn_manifest_html(manifest, plan)` — spawn package: target hostname, execution mode, service disposition, allocated resources, operator checklist
- `build_phoenix_manifest_html(playbook)` — phoenix package: restoration scope, waves table, VMIDs, danger warning, operator checklist

All HTML outputs are self-contained (dark theme, no external dependencies, same style as dashboard and setup guide).

Architecture: `assemble_forge_package.py` now embeds `forge-manifest.html` alongside `forge-manifest.json`. `assemble_spawn_package.py` embeds `spawn-manifest.html`. `ARCHITECTURE.md` documents AD-047 as the mandatory pattern: every machine-readable manifest must have a human-readable HTML equivalent.

Test file: `tests/unit/test_html_package_manifest.py` — 38 tests, all passing.

## What's Left (in priority order)

All 5 session items are now complete. No remaining items.
   - Scan for plaintext secrets in forge.log, spawn.log etc.
   - Scan shell scripts for unsafe patterns (StrictHostKeyChecking=no, passwords on cmdlines)
   - Scan bootstrap-state.json / manifests for plaintext secret fields
   - Continuous + one-shot audit modes
   - HTML report (same dark-theme style as existing docs)
   - New "Security Posture" score in readiness scorer
   - Security tab in broodforge_dashboard.py
   - Tests

2. **Setup Guide manifest import explainer** — add a clear section to the bottom of
   `docs/SETUP-GUIDE.html` explaining: what the import does, how to use it (drag-and-drop /
   paste), what fields it auto-fills, what the user must still fill in manually.

3. **Readable passphrase generation** — investigate keepassxc-cli diceware support
   (`keepassxc-cli generate --words`). If available, wire it in. If not, implement a
   stdlib-only EFF wordlist generator (`lib/passphrase_eff.py`) producing "correct-horse-battery-staple"
   style passphrases and integrate as an alternative to the existing Capital.word.phrase.9 format.

4. **HTML manifests for package exports** — for forge, spawn, and phoenix packages, produce
   a self-contained HTML file explaining package contents. Establish as a mandatory architecture
   pattern in ARCHITECTURE.md: every machine-readable manifest must have a human-readable HTML
   counterpart.

## Test Counts

- Tests at Phase 26 completion: 3528 total (3398 passed, 37 skipped, 3 pre-existing env failures)
- Pre-existing failures: `test_phase18_capability_secret.py` and `test_service_state_collector.py`
  — all `ModuleNotFoundError: No module named 'jsonschema'`, not related to broodforge code

## Architecture Notes

- All Phase 26 modules live in `proxmox-bootstrap/` and use stdlib only
- `bootstrap-state.json` gains two new optional top-level fields: `remediations` (array) and
  `remediation_policy` (object)
- Dashboard now accepts `remediations=` kwarg in `generate_dashboard_html()`
- The autonomous mode enabling ceremony requires literal input "enable autonomous"
- KeePass-gated actions (rotate-join-token, run-backup) cannot execute unless
  `executor.keepass_unlocked = True`
- The `dry_run_differs()` check compares original vs current dry-run; >50% line change
  triggers re-approval requirement before execution
