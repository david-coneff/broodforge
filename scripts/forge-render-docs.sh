#!/usr/bin/env bash
# forge-render-docs.sh — Render Markdown documentation to styled HTML.
#
# By default renders ARCHITECTURE.md → docs/ARCHITECTURE.html and
# README.md → docs/README.html (optional).
#
# This script is designed to run:
#   - Manually: bash scripts/forge-render-docs.sh
#   - As a git pre-commit hook: .git/hooks/pre-commit calls this
#   - On a daily schedule: via scheduled task (see docs/SCHEDULING.md)
#
# Usage:
#   bash scripts/forge-render-docs.sh [--all] [--input FILE --output FILE]
#
# Flags:
#   --all              Render all known Markdown docs (default when no flags given)
#   --input FILE       Single input .md file
#   --output FILE      Output .html path for --input
#
# Exit codes:
#   0 — all docs rendered
#   1 — error

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RENDER_PY="${REPO_ROOT}/lib/forge-render-docs.py"

die()  { echo "[render-docs] ERROR: $*" >&2; exit 1; }
info() { echo "[render-docs] $*"; }

[[ -f "$RENDER_PY" ]] || die "forge-render-docs.py not found at $RENDER_PY"

INPUT_FILE=""
OUTPUT_FILE=""
RENDER_ALL=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --all)    RENDER_ALL=1; shift ;;
    --input)  INPUT_FILE="$2"; RENDER_ALL=0; shift 2 ;;
    --output) OUTPUT_FILE="$2"; shift 2 ;;
    --help)
      grep '^#' "$0" | head -25 | sed 's/^# \?//'
      exit 0
      ;;
    *) die "Unknown argument: $1" ;;
  esac
done

_render() {
  local input="$1"
  local output="$2"
  python3 "$RENDER_PY" --input "$input" --output "$output"
}

if [[ $RENDER_ALL -eq 1 ]]; then
  # Render all known docs
  _render "${REPO_ROOT}/ARCHITECTURE.md"  "${REPO_ROOT}/docs/ARCHITECTURE.html"
  _render "${REPO_ROOT}/README.md"         "${REPO_ROOT}/docs/README.html"

  # Render any .md files in docs/ that have no corresponding .html
  for md_file in "${REPO_ROOT}/docs/"*.md; do
    [[ -f "$md_file" ]] || continue
    html_file="${md_file%.md}.html"
    _render "$md_file" "$html_file"
  done

  info "All docs rendered."
else
  [[ -n "$INPUT_FILE"  ]] || die "--input is required"
  [[ -n "$OUTPUT_FILE" ]] || die "--output is required"
  _render "$INPUT_FILE" "$OUTPUT_FILE"
fi
