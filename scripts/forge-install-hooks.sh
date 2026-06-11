#!/usr/bin/env bash
# forge-install-hooks.sh — Install broodforge git hooks into .git/hooks/.
#
# Run this once after cloning or when hooks change.
# It's safe to re-run — existing hooks are backed up first.
#
# Usage:
#   bash scripts/forge-install-hooks.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
HOOKS_SRC="${REPO_ROOT}/git-hooks"
HOOKS_DST="${REPO_ROOT}/.git/hooks"

die()  { echo "[install-hooks] ERROR: $*" >&2; exit 1; }
info() { echo "[install-hooks] $*"; }

[[ -d "$HOOKS_DST" ]] || die ".git/hooks directory not found — are you in a git repo?"

# Create git-hooks source directory if needed
mkdir -p "$HOOKS_SRC"

# Write the pre-commit hook source
cat > "${HOOKS_SRC}/pre-commit" <<'HOOK'
#!/usr/bin/env bash
# Broodforge pre-commit hook — re-render docs HTML when .md sources change.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
RENDER_SH="${REPO_ROOT}/scripts/forge-render-docs.sh"

CHANGED_MD=$(git diff --cached --name-only --diff-filter=ACM 2>/dev/null \
  | grep -E '\.(md)$' || true)

if [[ -z "$CHANGED_MD" ]]; then
  exit 0
fi

if [[ ! -f "$RENDER_SH" ]]; then
  echo "[pre-commit] forge-render-docs.sh not found — skipping doc render"
  exit 0
fi

echo "[pre-commit] Markdown changes detected — re-rendering HTML docs..."

if bash "$RENDER_SH" --all 2>&1; then
  git add "${REPO_ROOT}/docs/ARCHITECTURE.html" \
          "${REPO_ROOT}/docs/README.html" \
          "${REPO_ROOT}/docs/"*.html 2>/dev/null || true
  echo "[pre-commit] HTML docs updated and staged."
else
  echo "[pre-commit] WARN: doc render failed — committing without updated HTML."
fi

exit 0
HOOK

chmod +x "${HOOKS_SRC}/pre-commit"

# Install each hook (backup existing if present)
for hook_file in "${HOOKS_SRC}"/*; do
  [[ -f "$hook_file" ]] || continue
  hook_name="$(basename "$hook_file")"
  dst="${HOOKS_DST}/${hook_name}"

  if [[ -f "$dst" ]]; then
    backup="${dst}.bak.$(date +%Y%m%d%H%M%S)"
    cp "$dst" "$backup"
    info "Backed up existing ${hook_name} → ${backup}"
  fi

  cp "$hook_file" "$dst"
  chmod +x "$dst"
  info "Installed: ${hook_name} → .git/hooks/${hook_name}"
done

info ""
info "Git hooks installed. They will run automatically on each commit."
info "To uninstall: rm .git/hooks/pre-commit"
