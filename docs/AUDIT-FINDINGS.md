# Broodforge Audit Findings — Documented Steps vs. Implementation

**Single, continuously-revised audit log.** Each analysis cycle appends a section
with a timestamp (`YYYY-MM-DD_HH_MM_SS` UTC). Findings are marked **[FIXED]**,
**[OUTSTANDING]**, or **[DOCUMENTED]** (a real gap that is now honestly described in
the operator docs rather than silently broken). Nothing is deleted — this is a
trailing history.

---

## Audit cycle — 2026-06-04_12_37_46 UTC

### Method

Cross-referenced **every documented user-guide step** against the implemented software:

1. **Script existence** — every `python3 …py` command in all docs resolves to a real file.
2. **CLI functionality** — every referenced CLI runs (`--help` probe).
3. **Flag-level (import-aware)** — every `--flag` used in a documented command is
   implemented in the target script *or a module it delegates to* (the hyphen-CLI →
   underscore-module wrapper pattern is followed).
4. **Subcommands** — `reconstruction-drill.py` (start/complete/last/report) and
   `remediation-cli.py` (list/approve/approve-all/reject/dry-run/history/status/
   enable-autonomous/disable-autonomous) match their docs.
5. **`bash *.sh` references** — all exist (forge.sh/spawn.sh/run-all.sh are generated
   at package-assembly time; schedule-reconstruction-drill.sh exists).

### Result of automated cross-reference

- Script existence: **0 missing.**
- Flag-level mismatches: **0.**
- Subcommand / bash-script references: **0 missing.**

The automated documented-command surface is **clean**. The remaining findings below
are *implementation* gaps where `forge.sh` invokes a tool that does not yet do its job
— surfaced by deep execution tracing, not by flag matching.

### Findings this cycle

| # | Area | Finding | Status |
|---|---|---|---|
| F1 | forge phase-03 | `setup_dnsmasq.py` is library-only (no CLI); phase-03 invokes it → **no-op** (dnsmasq not configured, checkpoint marks success) | **[FIXING]** add CLI |
| F2 | forge phase-03 | `setup_headscale.py` is library-only (no CLI); phase-03 invokes it → **no-op** | **[FIXING]** add CLI |
| F3 | forge phase-03 | `setup_tls.py` is library-only (no CLI); phase-03 invokes it → **no-op** | **[FIXING]** add CLI |
| F4 | forge phase-04 | No `opentofu/` modules exist; phase-04 self-skips VM provisioning | **[DOCUMENTED]** deploy-to-hardware milestone (FORGING status table) |
| F5 | forge phase-05 | `ansible/inventory/hosts.yaml` is not generated end-to-end; phase-05 self-skips | **[DOCUMENTED]** deploy-to-hardware milestone (FORGING status table) |

### Fix attempt

(Recorded in the next cycle section below after fixes + re-audit.)

---

## Trailing history of fixes (cycles 1–7, this session)

All verified by re-audit and the pytest suite (4000 passed, 1 skipped) at the time.

| Finding | Resolution | Status |
|---|---|---|
| Forge package shipped without its library code (`--repo` optional, docs omit it) → phase-00 fails | Assembler infers repo root by default; verified bundles 95 tools + 26 schemas + 78 doc-gen | **[FIXED]** |
| Dashboard `/api/state` (unauth) leaked k3s join tokens from bootstrap-state.json | `_redact_secrets()` on all unauth GET endpoints | **[FIXED]** |
| Spawn pre-flight `validate-spawn.py` referenced but never bundled (silent skip) | New `validate-spawn.py` CLI + closure bundled | **[FIXED]** |
| Forge IaC: `ansible/` + `generators/` not bundled; phase-05 referenced wrong filenames | Bundle both; fix phase-05 paths; honest status note | **[FIXED]** |
| Stargate workflow had no playbook-generation entry point | `phoenix-planner.py --state` now generates; new `docs/PHOENIX.md` | **[FIXED]** |
| `engine.py` invoked with unsupported `--state`/`--output` (forge phase-07) | Switched to `--manifest` | **[FIXED]** |
| `engine.py --set-timezone` documented (AD-045) but unimplemented | Implemented `--set-timezone TZ` | **[FIXED]** |
| `spawn_hardware_discovery.py` (NODE-SPAWNING step 1) had no CLI; password auth dead | Added CLI + `sshpass` password auth (no argv leak) | **[FIXED]** |
| `setup_ddns.py` library invoked as CLI by forge + docs; `setup-ddns.py` filename wrong | Real CLI (both forms); fixed all references | **[FIXED]** |
| `init-bootstrap-state.py` (forge phase-07) ignored `--manifest`, would hang interactively | `--manifest` seeds state non-interactively; phase-07 passes `--non-interactive` | **[FIXED]** |
| Stale spawn/phoenix phase names, test counts, broken doc links, "Forgability" spelling | Corrected across README/ROADMAP/FORGING/ARCHITECTURE | **[FIXED]** |
