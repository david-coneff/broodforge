# Session Handoff

Last updated: 2026-06-02 UTC

## What Was Done This Session

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

**L1 — Dead code branch in security_analyzer.py:581** (fixed opportunistically)
- Removed `hasattr(f, 'content')` dead branch in `_finding_row()` — `SecurityFinding` only has `line_content`

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

## Remaining Work (LOW priority)

### LOW PRIORITY

**L2 — Move/retire docs**: `docs/CONTAINER-COMPATIBILITY-PLAN.md` → `deprecated/`
**L3 — Forge-manifest schema validation**: add JSON schema validation in forge_validator.py
**L4 — Fix flaky passphrase test**: mock RNG in test_forge_package_foundation.py::TestPassphraseFormat::test_length_in_range
**L5 — Receiver authentication**: add X-Broodforge-Token header check to hatchery_receiver.py
**L6 — .ai/ cleanup**: remove `.ai/SESSION-HANDOFF.md`, update `.ai/context.md`

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
