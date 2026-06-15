#!/usr/bin/env python3
"""
md_to_html.py — Minimal, stdlib-only Markdown → HTML converter for Broodforge.

Renders a self-contained, interactive HTML document in the Broodforge theme.
Every generated page includes:

  * a light/dark theme toggle (top-right, persisted in localStorage);
  * a “Copy” button on command code blocks (bash/sh/shell/console/cmd/powershell);
  * live-templated commands — any `{{VAR}}` / `{{VAR=default}}` placeholder inside
    a code block becomes an editable parameter. A “Parameters” panel at the top
    of the page collects them; editing a value rewrites every command that uses
    it, and the Copy button copies the resolved command;
  * walkthrough note fields — `@field[Label]` (single line) / `@area[Label]`
    (multi-line) render labeled inputs the operator can fill while following the
    steps, so a drill or forge has a traceable record;
  * an always-present “Session Notes” textarea at the bottom for anything that
    didn’t fit the structured flow.

All note/parameter values persist per-document in localStorage.

Supported Markdown: ATX headings, fenced code blocks (verbatim, box-drawing safe),
GitHub tables, ordered/unordered lists (one level of nesting), blockquotes,
horizontal rules, paragraphs, and inline `code` / **bold** / [text](url). Single
`*`/`_` italics are intentionally NOT interpreted (they would mangle identifiers
like __main__ and network_topology.ssl_*).

Usage:
    python3 md_to_html.py INPUT.md OUTPUT.html [--title "Title"]

Stdlib only.
"""

import argparse
import html
import json
import re
import sys
from pathlib import Path
