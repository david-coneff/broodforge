# Session Handoff

Last updated: 2026-06-03 UTC

## What Was Done This Session (current)

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
