# broodforge migrations

This directory contains schema migration scripts applied by `migration_manager.py`
whenever the `schema_version` in `bootstrap-state.json` is older than the version
the current codebase expects (`CURRENT_SCHEMA_VERSION` from `proxmox-bootstrap/version.py`).

---

## Schema version format

Version strings use the format:

```
YYYY-MM-DD_HH-MM-SS_<7-char-hash>
```

Examples:

```
2026-06-09_00-00-00_0000000    ← baseline (zeroed hash = before versioning existed)
2026-07-01_08-30-00_a3b4c5d
2026-08-15_14-22-11_ff00123
```

The special sentinel `"initial"` represents state that pre-dates the versioning
system and sorts before all real versions.

The hash portion is the 7-character abbreviated git hash of the commit that
established the schema change.  `0000000` is reserved for the baseline version.

Versions are ordered by their timestamp prefix (`YYYY-MM-DD_HH-MM-SS`); the hash
suffix is not used for ordering.

---

## Naming convention

Migration scripts must be named:

```
migrate_<from>__to__<to>.py
```

The separator is **double underscore** (`__to__`).  Single underscores occur
inside the version strings themselves, so a double underscore is necessary to
unambiguously identify the boundary.

Examples:

```
migrate_initial__to__2026-06-09_00-00-00_0000000.py
migrate_2026-06-09_00-00-00_0000000__to__2026-07-01_08-30-00_a3b4c5d.py
migrate_2026-07-01_08-30-00_a3b4c5d__to__2026-08-15_14-22-11_ff00123.py
```

`migration_manager.py` discovers these files by globbing `migrate_*__to__*.py`,
parses the version strings from the filename (splitting on `__to__`), and runs
them in ascending from-version order, starting from the version recorded in
`bootstrap-state.json`.

---

## The `run(state_dir)` contract

Every migration script must expose exactly one public function:

```python
def run(state_dir: str) -> None:
    ...
```

| Rule | Detail |
|------|--------|
| **Signature** | Accepts `state_dir: str` — the path to the directory containing `bootstrap-state.json` and any other state files. |
| **Return value** | `None`. Raise an exception to signal failure; `migration_manager.py` catches it and records the error. |
| **Idempotent** | The migration must be safe to re-run. Check whether the transformation has already been applied before applying it. |
| **Updates schema_version** | The migration must write the new `schema_version` value into `bootstrap-state.json` before returning. |
| **No side effects outside state_dir** | Migrations must only read/write files within `state_dir`. They must not call external services, systemd units, or shell commands. |
| **Stdlib only** | Migration scripts must not import third-party packages. They run in the same environment as `migration_manager.py` (stdlib only). |

---

## Example migration script

```python
"""migrate_2026-06-09_00-00-00_0000000__to__2026-07-01_08-30-00_a3b4c5d.py

Add 'cell_tier' field to bootstrap-state.json.
"""

import json
from pathlib import Path

_TARGET_VERSION = "2026-07-01_08-30-00_a3b4c5d"
_STATE_FILENAME = "bootstrap-state.json"


def run(state_dir: str) -> None:
    state_file = Path(state_dir) / _STATE_FILENAME
    with open(state_file, encoding="utf-8") as fh:
        state = json.load(fh)

    if state.get("schema_version") == _TARGET_VERSION:
        return  # already applied — idempotent

    state.setdefault("cell_tier", "primary")
    state["schema_version"] = _TARGET_VERSION

    with open(state_file, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
```

---

## Version file and stamping ceremony

The codebase's expected schema version is stored in:

```
proxmox-bootstrap/version.py
```

This file contains a single constant:

```python
SCHEMA_VERSION: str = "2026-06-09_00-00-00_0000000"
```

It is **not edited by hand**.  Update it (and recompute the package hash) by
running:

```bash
bash scripts/forge-stamp-version.sh
# or with an explicit version:
bash scripts/forge-stamp-version.sh 2026-07-01_08-30-00_a3b4c5d
```

This script:
1. Updates `version.py` with the new `SCHEMA_VERSION`
2. Calls `package_verifier.py --stamp` to recompute `package-descriptor.json`

Run `bash scripts/forge-stamp-version.sh` after **any** change to the package
source (Python files, shell scripts, migration scripts, or `manifest.toml`).

---

## Package integrity verification

```bash
bash scripts/forge-verify-package.sh
```

Computes the current content hash and compares it to the stored descriptor.
Use this as a sanity check at any time.

**Note:** `package-descriptor.json` is deliberately **excluded** from the hash
computation to avoid a circular dependency (the descriptor records the hash of
everything else — including itself would make the hash impossible to compute).

---

## Migration ceremony

The full operator ceremony for applying a migration is:

```bash
# 1. Verify package integrity (non-fatal warning if mismatch)
bash scripts/forge-verify-package.sh

# 2. Run the orchestrator (quiesce → phoenix pack → backup → migrate → resume)
sudo bash scripts/forge-migrate.sh
```

`forge-migrate.sh` automatically:
- Runs `forge-verify-package.sh` as a pre-flight check (warns but does not abort)
- Calls `forge-quiesce.sh` to freeze state
- Attempts to generate a phoenix recovery package via `forge-phoenix-pack.sh`
  (prompts operator to export it before proceeding; currently a stub, exits
  gracefully with `FORGE_INCOMPLETE` until the phoenix CLI is wired)
- Creates a timestamped backup of all state files
- Runs `migration_manager.py`
- Calls `forge-resume.sh` on success, or restores the backup on failure

Skip the phoenix gate with `--skip-phoenix` (discouraged outside of testing):

```bash
sudo bash scripts/forge-migrate.sh --skip-phoenix
```

---

## State descriptor

After any successful migration, the state hash must be updated to reflect the
post-migration state.  `forge-migrate.sh` does this automatically; when running
`migration_manager.py` directly, call the stamp script manually:

```bash
bash scripts/forge-stamp-state.sh --state-dir /var/lib/broodforge
# or, for development (state-dir defaults to repo root):
bash scripts/forge-stamp-state.sh
```

This writes (or updates) `proxmox-bootstrap/state-descriptor.json` with a fresh
SHA-256 digest of all current state files.

**What the state hash covers:**

| Included | Excluded |
|----------|----------|
| `*.json` and `*.toml` files directly in `state-dir` | `state-descriptor.json` (self-reference loop) |
| `migrations/migrate_initial__to__*.py` (active migration script) | `package-descriptor.json` (mutual exclusion — source integrity, not state) |
| | `migration-history.jsonl` (append-only log) |
| | `*.lock` files (transient) |
| | Files under `backups/` (snapshots, not current state) |

**Mutual exclusion rule**: neither `package-descriptor.json` nor
`state-descriptor.json` is ever included in the other's content set.  The
package hash covers static source files; the state hash covers operational
state files.  The two descriptors track separate concerns and must never
reference each other's content.

Verify the state hash at any time:

```bash
bash scripts/forge-verify-state.sh --state-dir /var/lib/broodforge
```

Prints `State integrity: OK` or `State integrity: MISMATCH` and exits with the
appropriate code (0 = OK, 1 = mismatch, 2 = descriptor not found).

**When to re-stamp** (beyond migration):

Any operation that mutates state files should call `forge-stamp-state.sh`
afterward:
- Spawn completion (when implemented — call from `forge-spawn.sh`)
- Phoenix restore (when implemented — call from `forge-phoenix-restore.sh`)
- Manual edits to `manifest.toml` or other state files

---

## Migration history

Every run (successful or failed) is appended to
`/var/lib/broodforge/migration-history.jsonl` by `migration_manager.py` as a
single JSON line. Each record contains:

| Field | Description |
|-------|-------------|
| `from_version` | Schema version before this migration |
| `to_version` | Schema version this migration targets |
| `script` | Filename of the migration script |
| `ran_at` | ISO 8601 UTC timestamp |
| `success` | `true` / `false` |
| `dry_run` | `true` if `--dry-run` was passed |
| `error` | Error message string, or `null` on success |
