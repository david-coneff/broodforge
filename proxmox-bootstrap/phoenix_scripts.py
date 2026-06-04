#!/usr/bin/env python3
"""
phoenix_scripts.py — Shell script generator for phoenix playbooks (Phase 9.6).

Provides:
  generate_wave_script(wave)    — bash script for a single restoration wave
  generate_run_all_sh(playbook) — orchestrating run-all.sh entry point

Generated scripts use the checkpoint library pattern:
  checkpoint_start / checkpoint_complete / checkpoint_failed
  On any step failure: generates a failure package and exits.

Stdlib only. Generated scripts are bash; they run on the Proxmox host.
"""

import shlex
from typing import Optional

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SHEBANG = "#!/usr/bin/env bash"
_STRICT  = "set -euo pipefail"

_CHECKPOINT_STUB = '''\
# ---------------------------------------------------------------------------
# Checkpoint library stub
# (replace with lib/checkpoint.sh from the phoenix package for real execution)
# ---------------------------------------------------------------------------
CHECKPOINT_DIR="${SCRIPT_DIR}/.checkpoints"
mkdir -p "$CHECKPOINT_DIR"

checkpoint_start()  { echo "[checkpoint] START: $1"; }
checkpoint_done()   { touch "$CHECKPOINT_DIR/$1.done"; echo "[checkpoint] DONE: $1"; }
checkpoint_skip()   { echo "[checkpoint] SKIP (already done): $1"; }
checkpoint_failed() { echo "[checkpoint] FAILED: $1  — check $PHOENIX_LOG"; exit 1; }

is_done() { [ -f "$CHECKPOINT_DIR/$1.done" ]; }
'''

PHOENIX_KEEPASS_GATE_SH = '''\
#!/usr/bin/env bash
# phoenix-keepass-gate.sh — KeePass master password gate for phoenix run-all.sh
# Source this and call phoenix_keepass_gate() before any secrets are accessed.

PHOENIX_KDBX_PATH=""
PHOENIX_KDBX_UNLOCKED=0

phoenix_keepass_find_db() {
  local embedded
  embedded="$(ls "$SCRIPT_DIR"/kdbx/*.kdbx 2>/dev/null | head -1)"
  if [ -n "$embedded" ]; then
    PHOENIX_KDBX_PATH="$embedded"
    echo "[kdbx] Using embedded database: $PHOENIX_KDBX_PATH"
    return 0
  fi
  read -rp "[kdbx] Path to KeePass database (.kdbx): " PHOENIX_KDBX_PATH
  [ -f "$PHOENIX_KDBX_PATH" ] || { echo "[kdbx] Not found: $PHOENIX_KDBX_PATH" >&2; return 1; }
}

phoenix_keepass_gate() {
  [ "$PHOENIX_KDBX_UNLOCKED" -eq 1 ] && return 0
  echo "" >/dev/tty
  echo "=================================================================" >/dev/tty
  echo " KeePass Unlock Gate — phoenix run-all.sh" >/dev/tty
  echo " The master password is required once before wave execution." >/dev/tty
  echo " All subsequent secret lookups are automatic." >/dev/tty
  echo "=================================================================" >/dev/tty
  phoenix_keepass_find_db || { echo "[kdbx] Cannot locate database." >&2; exit 1; }
  read -rsp "[kdbx] Master password: " KEEPASS_MASTER_PASSWORD </dev/tty >/dev/tty
  echo "" >/dev/tty
  export PHOENIX_KDBX_PATH
  PHOENIX_KDBX_UNLOCKED=1
  echo "[kdbx] Unlocked. Secrets broker active." >/dev/tty
  echo "" >/dev/tty
}

kdbx_get() {
  local path="$1"
  if command -v keepassxc-cli &>/dev/null; then
    printf \'%s\\n\' "$KEEPASS_MASTER_PASSWORD" | \\
      keepassxc-cli show -q -a Password "$PHOENIX_KDBX_PATH" "$path" 2>/dev/null
  else
    echo "[kdbx] keepassxc-cli not found — retrieve \'$path\' manually" >&2
    echo "MANUAL_ENTRY_REQUIRED"
  fi
}
'''


def _header(title: str, wave_num, playbook: Optional[dict] = None) -> str:
    hostname  = ""
    cell_id   = ""
    generated = ""
    if playbook:
        hostname  = playbook.get("target_node", {}).get("hostname", "")
        cell_id   = playbook.get("cell_id", "")
        generated = playbook.get("generated_at", "")
    return (
        f"{_SHEBANG}\n"
        f"# {title}\n"
        f"# Node:      {hostname}\n"
        f"# Cell:      {cell_id}\n"
        f"# Generated: {generated}\n"
        f"# ---------------------------------------------------------------------------\n"
        f"{_STRICT}\n\n"
        f'SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"\n'
        f'PHOENIX_LOG="$SCRIPT_DIR/phoenix-$(date +%Y%m%d_%H%M%S).log"\n\n'
    )


def _step_block(step: dict) -> str:
    """Render a single playbook step as a bash block with checkpoint tracking."""
    sid     = step.get("id", "?")
    action  = step.get("action", "")
    cmds    = step.get("commands") or []
    val     = step.get("validation") or []
    on_fail = step.get("on_failure", "abort")

    checkpoint_key = f"step-{sid}".replace(".", "-")
    ck_q = shlex.quote(checkpoint_key)  # single-quoted for bash function args

    lines = [
        f"",
        f"# ── Step {sid}: {action}",
        f'if is_done {ck_q}; then',
        f'    checkpoint_skip {ck_q}',
        f"else",
        f'    checkpoint_start {ck_q}',
        f"    echo '[step {sid}] {action}'",
    ]

    for cmd in cmds:
        stripped = cmd.strip()
        if not stripped:
            lines.append("    ")
        elif stripped.startswith("#"):
            lines.append(f"    {stripped}")
        else:
            lines.append(f"    {stripped} \\")
            lines[-1] = lines[-1].rstrip("\\").rstrip() + ""
            # Emit normally
            lines[-1] = f"    {stripped}"

    if val:
        lines.append(f"    # Validation:")
        for v in val:
            lines.append(f"    # {v.strip()}")

    if on_fail == "abort":
        lines += [
            f'    checkpoint_done {ck_q} \\',
            f'        || {{ checkpoint_failed {ck_q}; exit 1; }}',
        ]
    else:
        lines.append(f'    checkpoint_done {ck_q}')

    lines.append("fi")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Wave script generator
# ---------------------------------------------------------------------------

def generate_wave_script(wave: dict, playbook: Optional[dict] = None) -> str:
    """
    Generate a self-contained bash script for a single restoration wave.

    Args:
        wave:     a wave dict from phoenix_playbook.build()["waves"]
        playbook: the full playbook dict (for header metadata)

    Returns:
        A bash script string. Write to a file like phase-00-network.sh.
    """
    wave_num  = wave.get("wave", "?")
    wave_name = wave.get("name", "")
    wave_desc = (wave.get("description") or "").strip()
    est_mins  = wave.get("estimated_minutes")
    prereqs   = wave.get("prerequisites") or []
    steps     = wave.get("steps") or []

    script_name = f"phase-{str(wave_num).replace('.', '-')}-{wave_name.lower().replace(' ', '-')}.sh"

    lines = [_header(f"Wave {wave_num} — {wave_name}  [{script_name}]", wave_num, playbook)]
    lines.append(_CHECKPOINT_STUB)

    if wave_desc:
        lines.append(f"# Purpose: {wave_desc}")
    if est_mins:
        lines.append(f"# Estimated: {est_mins} minutes")
    if prereqs:
        lines.append("# Prerequisites:")
        for p in prereqs:
            lines.append(f"#   - {p}")
    lines.append("")
    lines.append(f'echo ""')
    lines.append(f"echo '[Wave {wave_num}] {wave_name}'")
    if est_mins:
        lines.append(f"echo '[Wave {wave_num}] Estimated: {est_mins} minutes'")
    lines.append(f'echo ""')

    for step in steps:
        lines.append(_step_block(step))

    lines.append("")
    lines.append(f"echo '[Wave {wave_num}] Complete.'")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# run-all.sh generator
# ---------------------------------------------------------------------------

def generate_run_all_sh(playbook: dict) -> str:
    """
    Generate the orchestrating run-all.sh entry point that calls each wave
    script in order, with checkpoint tracking and failure-package generation.

    Args:
        playbook: the full playbook dict from phoenix_playbook.build()

    Returns:
        A bash script string. Write to run-all.sh in the phoenix package root.
    """
    hostname    = playbook.get("target_node", {}).get("hostname", "unknown")
    cell_id     = playbook.get("cell_id", "")
    generated   = playbook.get("generated_at", "")
    est_total   = playbook.get("estimated_total_minutes", "?")
    scope       = playbook.get("restoration_scope", "full")
    waves       = playbook.get("waves") or []
    checklist   = playbook.get("validation_checklist") or []

    lines = [
        _header(f"Phoenix run-all.sh — {hostname}", None, playbook),
        _CHECKPOINT_STUB,
        f'# ── KeePass unlock gate ──────────────────────────────────────────────',
        f'if [ -f "$SCRIPT_DIR/lib/phoenix-keepass-gate.sh" ]; then',
        f'  source "$SCRIPT_DIR/lib/phoenix-keepass-gate.sh"',
        f'  phoenix_keepass_gate',
        f'fi',
        f'',
        f"echo '============================================================='",
        f"echo ' Phoenix Restoration: {hostname}'",
        f"echo ' Cell:   {cell_id}'",
        f"echo ' Scope:  {scope}'",
        f"echo ' Waves:  {len(waves)}'",
        f"echo ' Estimated: {est_total} minutes'",
        f"echo ' Generated: {generated}'",
        f"echo '============================================================='",
        f'echo ""',
        "",
    ]

    for wave in sorted(waves, key=lambda w: w.get("wave", 0)):
        wave_num  = wave.get("wave", "?")
        wave_name = wave.get("name", "")
        est_mins  = wave.get("estimated_minutes", "?")
        script    = f"phase-{str(wave_num).replace('.', '-')}-{wave_name.lower().replace(' ', '-')}.sh"
        script_q  = shlex.quote(script)  # single-quoted script name — prevents $() in wave_name

        lines += [
            f"# ── Wave {wave_num}: {wave_name} ({est_mins}m)",
            f"echo '[phoenix] Starting Wave {wave_num}: {wave_name}'",
            f'bash "$SCRIPT_DIR/"{script_q} \\',
            f"    || {{ echo '[phoenix] FAILED at Wave {wave_num}: {wave_name}'; exit 1; }}",
            f"echo '[phoenix] Wave {wave_num} complete.'",
            f'echo ""',
            "",
        ]

    lines += [
        f"echo '============================================================='",
        f"echo ' Phoenix Restoration Complete: {hostname}'",
        f"echo '============================================================='",
        f'echo ""',
        f"echo ' Post-restoration validation checklist:'",
    ]
    for item in checklist:
        lines.append(f"echo '   - {item}'")
    lines += [
        f'echo ""',
        f"echo ' Update bootstrap-state.json and commit to Forgejo.'",
        f'echo ""',
    ]

    return "\n".join(lines) + "\n"
