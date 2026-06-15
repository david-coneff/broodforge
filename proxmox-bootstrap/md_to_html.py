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

# ---------------------------------------------------------------------------
# Theme + interaction assets (shared by every generated doc, and exported for
# injection into hand-authored HTML via theme_assets()).
# ---------------------------------------------------------------------------

_CSS = """
  :root{--bg:#1a1d23;--bg2:#22262e;--bg3:#2a2f3a;--border:#3a3f4d;--text:#cdd6f4;--muted:#7f8498;
    --accent:#89b4fa;--green:#a6e3a1;--yellow:#f9e2af;--orange:#fab387;--red:#f38ba8;
    --code-bg:#181b21;--code-text:#a6e3a1;--radius:6px;--btn-bg:#2a2f3a;--bg2-rgb:34,38,46}
  body.light{--bg:#ffffff;--bg2:#f4f5f7;--bg3:#eceff2;--border:#6b7a8a;--text:#1f2328;--muted:#57606a;
    --accent:#0969da;--green:#1a7f37;--yellow:#9a6700;--orange:#bc4c00;--red:#cf222e;
    --code-bg:#f6f8fa;--code-text:#0a3069;--btn-bg:#eaeef2;--bg2-rgb:244,245,247}
  *{box-sizing:border-box;margin:0;padding:0}
  html,body{height:100%;overflow:hidden;margin:0;padding:0}
  body{background:var(--bg);color:var(--text);font-family:'Segoe UI',system-ui,-apple-system,sans-serif;
    font-size:14px;line-height:1.6;
    transition:background .15s,color .15s}
  h1{color:var(--accent);font-size:1.7em;margin:18px 0 4px}
  h2{color:var(--accent);font-size:1.05em;margin:24px 0 8px;text-transform:uppercase;letter-spacing:.05em;
    border-bottom:1px solid var(--border);padding-bottom:4px}
  h3{color:var(--accent);font-size:.95em;margin:14px 0 6px}
  h4{color:var(--muted);font-size:.82em;margin:10px 0 4px;text-transform:uppercase;letter-spacing:.08em}
  h5,h6{color:var(--muted);font-size:.8em;margin:8px 0 4px}
  a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
  p{margin:8px 0}ul,ol{margin:8px 0 8px 22px}li{margin:4px 0}
  li>ul,li>ol{margin:4px 0 4px 18px}
  strong{color:var(--text);font-weight:600}
  hr{border:none;border-top:1px solid var(--border);margin:20px 0}
  blockquote{border-left:3px solid var(--accent);background:var(--bg2);margin:10px 0;
    padding:8px 14px;border-radius:0 var(--radius) var(--radius) 0;color:var(--text)}
  code{background:var(--code-bg);color:var(--code-text);padding:1px 5px;border-radius:3px;
    font-family:'Cascadia Code','Fira Code',Consolas,monospace;font-size:.9em}
  pre{background:var(--code-bg);border:1px solid var(--border);border-radius:var(--radius);
    padding:12px 14px;overflow-x:auto;margin:0;font-family:'Cascadia Code','Fira Code',Consolas,monospace;
    font-size:.85em;color:var(--code-text);white-space:pre}
  pre code{background:none;padding:0;color:inherit}
  table{width:100%;border-collapse:collapse;margin:10px 0;font-size:.88em}
  th{background:var(--bg2);color:var(--muted);text-align:left;padding:6px 8px;
    border-bottom:1px solid var(--border);font-weight:600;font-size:.8em;text-transform:uppercase;letter-spacing:.05em}
  td{padding:5px 8px;border-bottom:1px solid var(--bg3);vertical-align:top}
  tr:last-child td{border-bottom:none}
  .doc-meta{color:var(--muted);font-size:.8em;margin:4px 0 20px}
  /* theme toggle */
  #bf-toolbar{position:sticky;top:0;z-index:50;display:flex;flex-direction:column;
    background:var(--bg);border-bottom:3px solid var(--accent);margin-bottom:14px}
  .bf-toolbar-main{display:flex;align-items:center;flex-wrap:wrap;gap:6px 8px;padding:12px 0 6px}
  .bf-toolbar-end{margin-left:auto;display:flex;align-items:center;gap:6px 8px;flex-wrap:wrap}
  .bf-attach-bar{display:flex;align-items:center;gap:10px;
    padding:4px 0 6px;border-top:1px solid var(--border)}
  .bf-attach-hint{color:var(--muted);font-size:.76em}
  .bf-attach-bar-end{margin-left:auto;display:flex;align-items:center;gap:6px}
  /* unified toolbar element height — all buttons and badge-links are 28px tall */
  #bf-toolbar button{background:var(--btn-bg);color:var(--text);border:1px solid var(--border);
    border-radius:var(--radius);padding:0 12px;cursor:pointer;font-size:.8em;font-family:inherit;
    height:28px;display:inline-flex;align-items:center;box-sizing:border-box;line-height:1;
    flex-shrink:0}
  #bf-toolbar button:hover{border-color:var(--accent);color:var(--accent)}
  #bf-collapse-all,#bf-expand-all{padding:0 12px}
  #bf-collapse-all:hover,#bf-expand-all:hover{border-color:var(--accent);color:var(--accent)}
  #bf-section-count{color:var(--text);font-size:.75em;white-space:nowrap;
    display:inline-flex;align-items:center;text-align:center;font-variant-numeric:tabular-nums;
    font-family:'Consolas','Cascadia Code','SF Mono','Menlo',monospace;
    border:1px solid var(--border);border-radius:var(--radius);padding:0 8px;background:var(--bg2);
    height:28px;box-sizing:border-box;flex-shrink:0}
  .about-docs-link{background:var(--btn-bg);color:var(--text);border:1px solid var(--border);
    border-radius:var(--radius);padding:0 10px;display:inline-flex;align-items:center;
    font-size:.8em;text-decoration:none;cursor:pointer;flex-shrink:0;font-family:inherit;
    height:28px;box-sizing:border-box;line-height:1}
  .about-docs-link:hover{border-color:var(--accent);color:var(--accent)}
  /* attachments - toolbar dropdown panel */
  #bf-attach-count{font-size:.75em;opacity:.8}
  #bf-attach-panel{position:absolute;top:100%;right:0;width:360px;
    background:var(--bg2);border:1px solid var(--border);border-top:none;
    border-radius:0 0 var(--radius) var(--radius);
    box-shadow:0 6px 18px rgba(0,0,0,.38);z-index:51;
    display:none;padding:12px 14px}
  #bf-attach-panel.open{display:block}
  #bf-attach-zone{border:1.5px dashed var(--border);border-radius:var(--radius);
    background:var(--bg);padding:12px 14px;display:flex;align-items:center;
    gap:10px;cursor:default;transition:border-color .15s,background .15s;margin-bottom:6px}
  #bf-attach-zone.drag-over{border-color:var(--accent);background:rgba(137,180,250,.06)}
  .bf-attach-prompt{color:var(--muted);font-size:.82em;flex:1}
  .bf-attach-btn{background:var(--btn-bg);color:var(--text);border:1px solid var(--border);
    border-radius:var(--radius);padding:4px 10px;font-size:.78em;cursor:pointer;
    font-family:inherit;flex-shrink:0;white-space:nowrap}
  .bf-attach-btn:hover{border-color:var(--accent);color:var(--accent)}
  .attach-list{list-style:none;margin:4px 0 0;padding:0}
  .attach-list li{display:flex;align-items:center;gap:8px;background:var(--bg2);border:1px solid var(--border);
    border-radius:var(--radius);padding:4px 8px;margin:3px 0;font-size:.82em}
  .attach-list .sz{color:var(--muted);font-size:.9em}
  .attach-list button{margin-left:auto;background:none;border:1px solid var(--border);color:var(--muted);
    border-radius:4px;cursor:pointer;padding:1px 6px;font-size:.82em}
  .attach-list button:hover{border-color:var(--red);color:var(--red)}
  /* doc navigation panel */
  #bf-nav-panel{position:fixed;width:300px;
    background:var(--bg2);border:1px solid var(--border);
    border-radius:var(--radius);
    box-shadow:0 6px 18px rgba(0,0,0,.38);z-index:9999;
    display:none;padding:8px 0;max-height:70vh;overflow-y:auto}
  #bf-nav-panel.open{display:block}
  .bf-nav-group{padding:4px 0}
  .bf-nav-group-label{font-size:.68em;color:var(--muted);font-weight:700;
    text-transform:uppercase;letter-spacing:.08em;padding:6px 14px 3px}
  .bf-nav-item{display:block;padding:5px 14px;font-size:.82em;color:var(--text);
    text-decoration:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .bf-nav-item:hover{background:var(--bg3);color:var(--accent)}
  .bf-nav-item.current{color:var(--accent);font-weight:600;
    border-left:2px solid var(--accent);padding-left:12px}
  .bf-nav-sep{height:1px;background:var(--border);margin:4px 0}
  /* collapsible sections (--collapsible) */
  details.section{margin:8px 0;border:1px solid var(--border);border-radius:var(--radius);overflow:hidden}
  details.section>summary{background:var(--bg2);color:var(--accent);cursor:pointer;user-select:none;
    padding:9px 14px;font-weight:600;font-size:1.0em;list-style:none;text-transform:uppercase;
    letter-spacing:.04em;display:flex;align-items:center;gap:6px}
  details.section>summary::-webkit-details-marker{display:none}
  details.section>summary::before{content:'▶';font-size:.7em;color:var(--muted);margin-right:4px;flex-shrink:0;transition:transform .15s}
  details.section[open]>summary::before{transform:rotate(90deg)}
  details.section>summary>*:not(.bf-sub-controls){flex:1;margin:0;padding:0}
  details.section>summary h2{display:inline;border:none;margin:0;padding:0;font-size:inherit;color:inherit;letter-spacing:inherit}
  details.section .sec-body{padding:6px 16px 14px}
  /* code block + copy */
  .codewrap{position:relative;margin:10px 0}
  .copy-btn{position:absolute;top:6px;right:6px;background:var(--btn-bg);color:var(--muted);
    border:1px solid var(--border);border-radius:4px;padding:2px 9px;cursor:pointer;font-size:.72em;
    font-family:inherit;opacity:.55;transition:opacity .12s}
  .codewrap:hover .copy-btn{opacity:1}
  .copy-btn:hover{border-color:var(--accent);color:var(--accent)}
  .tpl{color:var(--orange);background:rgba(250,179,135,.13);border-radius:3px;padding:0 2px}
  body.light .tpl{background:rgba(188,76,0,.10)}
  /* parameters panel */
  .params{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);
    padding:12px 16px;margin:14px 0 18px}
  .params h3{margin:0 0 8px;color:var(--accent)}
  .params .hint{color:var(--muted);font-size:.8em;margin-bottom:10px}
  .param-row{display:flex;align-items:center;gap:10px;margin:6px 0;flex-wrap:wrap}
  .param-row label{min-width:200px;font-family:monospace;font-size:.85em;color:var(--muted)}
  .param-input,.note-input,.note-area,#bf-session-notes{background:var(--code-bg);color:var(--text);
    border:1px solid var(--border);border-radius:4px;padding:5px 8px;font-family:'Cascadia Code',Consolas,monospace;
    font-size:.85em;flex:1;min-width:220px}
  .param-input:focus,.note-input:focus,.note-area:focus,#bf-session-notes:focus{outline:none;border-color:var(--accent)}
  /* note fields */
  .notefield{margin:10px 0}
  .notefield label{display:block;font-size:.82em;color:var(--muted);margin-bottom:3px;font-weight:600}
  .note-area,#bf-session-notes{width:100%;min-height:70px;resize:vertical;flex:none}
  /* collapsible subsections — all heading levels h2-h6 */
  details.subsection{margin:4px 0;border-top:1px solid var(--border)}
  details.subsection>summary.sub-summary{list-style:none;cursor:pointer;user-select:none;
    display:flex;align-items:center;padding:5px 0;gap:6px}
  details.subsection>summary.sub-summary::-webkit-details-marker{display:none}
  details.subsection>summary.sub-summary::before{content:'▶';font-size:.65em;color:var(--muted);
    flex-shrink:0;transition:transform .12s}
  details.subsection[open]>summary.sub-summary::before{transform:rotate(90deg)}
  details.subsection>summary.sub-summary>*:not(.bf-sub-controls){flex:1;display:inline;
    margin:0;padding:0;font-size:inherit;color:inherit}
  details.subsection .sub-body{padding-left:14px;padding-bottom:6px}
  /* +/- controls and clear button appear right-aligned in the summary row */
  .bf-sub-controls{display:flex;gap:3px;flex-shrink:0;margin-left:auto;margin-right:10px;align-items:center}
  .bf-sub-expand,.bf-sub-collapse{background:var(--bg3);border:1px solid var(--border);
    color:var(--muted);border-radius:3px;padding:0 6px;cursor:pointer;font-size:.78em;
    line-height:1.6;font-family:inherit;font-weight:700;outline:none}
  .bf-sub-expand:hover,.bf-sub-collapse:hover{border-color:var(--accent);color:var(--accent)}
  .bf-ctrl-sep{width:10px;flex-shrink:0}
  /* ghost = always-present placeholder when button not applicable */
  .bf-ctrl-ghost{color:transparent !important;pointer-events:none;cursor:default;opacity:0.25}
  /* ── split-pane layout ─────────────────────────────────────────────────────────────────── */
  #bf-app{display:flex;height:100vh;overflow:hidden}
  #bf-doc-pane{flex:1 1 auto;overflow-y:auto;padding:0 28px 80px;min-width:0;scrollbar-gutter:stable}
  #bf-drag{flex:0 0 5px;cursor:col-resize;background:var(--border);
    transition:background .1s;z-index:20}
  #bf-drag:hover,#bf-drag.dragging{background:var(--accent)}
  #bf-notes-pane{flex:0 0 320px;min-width:300px;max-width:60vw;
    display:flex;flex-direction:column;
    border-left:1px solid var(--border);background:var(--bg2);overflow:hidden}
  #bf-notes-header{padding:8px 10px 6px;border-bottom:1px solid var(--border);
    flex:0 0 auto;display:flex;align-items:center;gap:6px;min-width:0;overflow:hidden}
  #bf-notes-header span{color:var(--accent);font-size:.82em;font-weight:700;
    text-transform:uppercase;letter-spacing:.06em;flex:1;min-width:0;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
  .nts-export-btn{background:var(--btn-bg);color:var(--muted);border:1px solid var(--border);
    border-radius:var(--radius);padding:2px 8px;cursor:pointer;font-size:.72em;
    font-family:inherit;flex-shrink:0}
  .nts-export-btn:hover{border-color:var(--accent);color:var(--accent)}
  #bf-notes-body{flex:1;overflow-y:auto;padding:8px 10px 20px;scrollbar-gutter:stable}
  #bf-session-notes{width:100%;min-height:80px;resize:vertical}
  /* ── notes tree (recursive collapsible sections) ──────────────────────────────────────────── */
  .nts-divider{border:none;border-top:1px solid var(--border);margin:10px 0 6px}
  .nts-label{color:var(--muted);font-size:.72em;font-weight:600;text-transform:uppercase;
    letter-spacing:.07em;margin:0 0 4px}
  .nts-section{margin:4px 0;border:1px solid var(--border);border-radius:var(--radius);
    overflow:hidden}
  /* dim only a section's OWN header + direct body content — nested sections unaffected */
  .nts-section.nts-dim{border-color:transparent!important}
  .nts-section.nts-dim>summary.nts-hdr{pointer-events:none}
  .nts-section.nts-dim>.nts-body>textarea.note-area{border-color:transparent!important;background:transparent!important}
  .nts-section.nts-dim>.nts-body>textarea.note-area::placeholder{opacity:0!important}
  .nts-section.nts-dim>.nts-body>.nts-add-btn{opacity:0!important;pointer-events:none}
  .nts-section.nts-dim>.nts-body{background:transparent!important}
  .nts-section>summary.nts-hdr{list-style:none;cursor:pointer;user-select:none;
    display:flex;align-items:center;gap:4px;background:var(--bg3);
    padding:5px 8px;font-size:.79em}
  .nts-section>summary.nts-hdr::-webkit-details-marker{display:none}
  .nts-section>summary.nts-hdr::before{content:'\25B6';font-size:.6em;color:var(--muted);
    flex-shrink:0;transition:transform .1s;margin-right:2px}
  .nts-section[open]>summary.nts-hdr::before{transform:rotate(90deg)}
  .nts-hdr-title{flex:1;background:none;border:none;
    border-bottom:1px solid transparent;color:var(--text);font-size:inherit;
    font-family:inherit;cursor:text;padding:0 2px;min-width:0}
  .nts-hdr-title:focus{outline:none;border-bottom-color:var(--accent)}
  .nts-hdr-btn{background:none;border:none;color:var(--muted);cursor:pointer;
    padding:0 4px;font-size:.95em;line-height:1;border-radius:3px;flex-shrink:0}
  .nts-hdr-btn:hover{color:var(--accent)}
  .nts-hdr-btn.del{color:var(--red)}
  .nts-hdr-btn.del:hover{opacity:.75}
  .nts-body{padding:5px 8px 8px;background:transparent}
  .nts-body textarea{width:100%;min-height:50px;resize:vertical;margin-bottom:4px;
    font-size:.81em}
  .nts-add-btn{display:block;width:100%;background:none;
    border:1px dashed var(--border);color:var(--muted);border-radius:var(--radius);
    padding:3px;cursor:pointer;font-size:.72em;margin-top:4px;font-family:inherit}
  .nts-add-btn:hover{border-color:var(--accent);color:var(--accent)}
  #bf-notes-add-root{width:100%;background:var(--btn-bg);color:var(--text);
    border:1px solid var(--border);border-radius:var(--radius);
    padding:4px 10px;cursor:pointer;font-size:.78em;font-family:inherit;margin-top:8px}
  #bf-notes-add-root:hover{border-color:var(--accent);color:var(--accent)}
  /* notes panel icon buttons */
  #bf-notes-toggle,#bf-notes-float-btn{background:none;border:none;color:var(--muted);cursor:pointer;
    padding:2px 6px;font-size:.85em;line-height:1;border-radius:3px;flex-shrink:0}
  #bf-notes-toggle:hover,#bf-notes-float-btn:hover{color:var(--accent)}
  .nts-clear-btn{background:none;border:none;color:var(--muted);cursor:pointer;
    padding:2px 6px;font-size:.85em;line-height:1;border-radius:3px;flex-shrink:0}
  .nts-clear-btn:hover{color:var(--red)}
  /* ── notes collapsed ── */
  #bf-notes-pane.collapsed{flex:0 0 30px !important;min-width:30px;overflow:hidden}
  #bf-notes-pane.collapsed #bf-notes-body,
  #bf-notes-pane.collapsed .nts-export-btn,
  #bf-notes-pane.collapsed .nts-clear-btn,
  #bf-notes-pane.collapsed #bf-notes-float-btn{display:none}
  #bf-notes-pane.collapsed #bf-notes-header{
    writing-mode:vertical-rl;flex-direction:row;
    padding:14px 4px;gap:10px;justify-content:flex-start}
  #bf-notes-pane.collapsed #bf-notes-header>span{
    writing-mode:vertical-rl;text-orientation:mixed}
  #bf-drag.notes-hidden{display:none}
  /* ── notes floating / pop-out ── */
  #bf-notes-pane.floating{
    position:fixed !important;
    width:400px;height:70vh;
    flex:none !important;min-width:400px !important;max-width:unset !important;
    border-radius:8px;border:2px solid var(--accent) !important;
    box-shadow:0 8px 32px rgba(0,0,0,.55);
    z-index:300;resize:both;overflow:hidden;
    /* background driven by JS via --notes-bg-alpha; border stays at full opacity */
    background:rgba(var(--bg2-rgb),var(--notes-bg-alpha,1)) !important;
    backdrop-filter:blur(var(--notes-blur,0px));
    -webkit-backdrop-filter:blur(var(--notes-blur,0px));
    transition:background .15s,backdrop-filter .15s}
  #bf-notes-pane.floating #bf-notes-header{cursor:move;user-select:none}
  #bf-notes-pane.floating~#bf-drag,#bf-drag.notes-floating{display:none}
  /* opacity + blur controls (only visible when floating) */
  #bf-notes-opacity-ctrl{display:none;flex-direction:column;gap:2px;
    font-size:.63em;color:var(--muted);flex-shrink:0;white-space:nowrap}
  #bf-notes-pane.floating #bf-notes-opacity-ctrl{display:flex}
  .bf-ctrl-row{display:flex;align-items:center;gap:3px}
  .bf-ctrl-label{min-width:34px;text-align:right}
  #bf-notes-opacity-val,#bf-notes-blur-val{min-width:30px;text-align:center;font-variant-numeric:tabular-nums}
  .bf-op-btn{background:var(--btn-bg);color:var(--muted);border:1px solid var(--border);
    border-radius:3px;width:16px;height:16px;padding:0;cursor:pointer;font-size:.75em;
    line-height:1;display:flex;align-items:center;justify-content:center;font-family:inherit}
  .bf-op-btn:hover{border-color:var(--accent);color:var(--accent)}
  /* ── walkthrough hint (compact) ── */
  #bf-walkthrough-hint{font-size:.8em;color:var(--muted);
    border-left:2px solid var(--border);padding:3px 10px;margin:0 0 10px;line-height:1.5}
  #bf-walkthrough-hint a{color:var(--accent);text-decoration:none}
  #bf-walkthrough-hint a:hover{text-decoration:underline}
  /* ── params panel ── */
  #params,#params.params{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);
    padding:12px 16px;margin:0 0 18px}
  #params h3{margin:0 0 8px;color:var(--accent);font-size:.9em}
  .params-hint{color:var(--muted);font-size:.8em;margin-bottom:10px}

  /* ── credential fields ──────────────────────────────────────────────────────────────────── */
  .cred-field{background:rgba(243,139,168,.05);border:1px solid rgba(243,139,168,.3);
    border-radius:var(--radius);padding:10px 12px;margin:10px 0}
  .cred-badge{color:var(--red);font-size:.72em;font-weight:400;margin-left:6px}
  .cred-row{display:flex;align-items:center;gap:6px;margin:4px 0}
  .cred-input{flex:1}
  .cred-toggle{background:var(--btn-bg);border:1px solid var(--border);border-radius:4px;
    cursor:pointer;padding:4px 8px;font-size:.85em;color:var(--muted);flex-shrink:0}
  .cred-toggle:hover{color:var(--accent);border-color:var(--accent)}
  .cred-hint{color:var(--orange);font-size:.75em;display:block;margin-top:3px}
  .cred-methods{display:flex;gap:12px;margin:5px 0 6px;flex-wrap:wrap}
  .cred-method-opt{display:flex;align-items:center;gap:5px;font-size:.82em;color:var(--muted);cursor:pointer;user-select:none}
  .cred-method-opt input[type=checkbox]{accent-color:var(--accent);cursor:pointer;width:13px;height:13px}
  .cred-method-section{margin-top:4px}
  .cred-section-label{font-size:.72em;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.05em;margin-bottom:3px}
  .cred-confirm-row{margin-top:4px}
  .cred-confirm-input{flex:1;border-color:var(--border)}
  .cred-match-indicator{font-size:.8em;padding:0 6px;flex-shrink:0;font-weight:600}
  .cred-match-ok{color:var(--green)}.cred-match-fail{color:var(--red)}
  /* ── suggest controls (schema select + suggest button) ────────────────────────────────────── */
  .bf-suggest-select{background:var(--bg3);color:var(--muted);border:1px solid var(--border);
    border-radius:var(--radius);padding:4px 6px;font-size:.78em;font-family:inherit;
    cursor:pointer;flex-shrink:0}
  .bf-suggest-select:hover,.bf-suggest-select:focus{border-color:var(--accent);outline:none}
  .bf-suggest-btn{background:var(--bg3);color:var(--muted);border:1px solid var(--border);
    border-radius:var(--radius);padding:4px 10px;font-size:.78em;font-family:inherit;
    cursor:pointer;flex-shrink:0;white-space:nowrap}
  .bf-suggest-btn:hover{border-color:var(--accent);color:var(--accent)}
  /* ── masked credential spans in code blocks ─────────────────────────────────────────────── */
  .cred-tpl{background:rgba(243,139,168,.15);color:var(--red);border-radius:3px;
    padding:0 4px;letter-spacing:.12em;cursor:default;font-style:normal;
    border-bottom:1px dashed var(--red)}
  /* ── export encryption modal ─────────────────────────────────────────────────────────────────── */
  #bf-enc-modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.65);
    z-index:9000;align-items:center;justify-content:center}
  #bf-enc-modal.active{display:flex}
  #bf-enc-box{background:var(--bg2);border:1px solid var(--border);border-radius:8px;
    padding:24px 28px;max-width:520px;width:92%;box-shadow:0 8px 32px rgba(0,0,0,.5)}
  #bf-enc-box h3{color:var(--red);margin:0 0 12px;font-size:1em;display:flex;align-items:center;gap:8px}
  #bf-enc-box p{color:var(--muted);font-size:.85em;margin:6px 0}
  .enc-phrase-row{display:flex;align-items:center;gap:8px;margin:14px 0 6px}
  .enc-phrase-row input{flex:1;font-family:'Cascadia Code',Consolas,monospace;font-size:.92em;
    background:var(--bg3);border:1px solid var(--border);border-radius:var(--radius);
    padding:7px 10px;color:var(--text)}
  .enc-phrase-row button{background:var(--btn-bg);border:1px solid var(--border);
    border-radius:var(--radius);padding:7px 10px;cursor:pointer;color:var(--muted);
    font-size:.8em;white-space:nowrap}
  .enc-phrase-row button:hover{border-color:var(--accent);color:var(--accent)}
  .enc-hint{color:var(--orange);font-size:.75em;margin:0 0 16px}
  .enc-actions{display:flex;gap:10px;margin-top:18px;flex-wrap:wrap}
  .enc-actions button{flex:1;padding:9px 14px;border-radius:var(--radius);cursor:pointer;
    font-size:.88em;font-family:inherit;border:1px solid var(--border)}
  #bf-enc-confirm{background:var(--accent);color:#1a1d23;border-color:var(--accent);font-weight:600}
  #bf-enc-confirm:hover{opacity:.88}
  #bf-enc-plain{background:var(--btn-bg);color:var(--muted)}
  #bf-enc-plain:hover{border-color:var(--muted);color:var(--text)}
  #bf-enc-cancel{background:transparent;color:var(--muted);flex:0 0 auto}
  #bf-enc-cancel:hover{color:var(--red)}
  /* ── radio/checkbox choice fields ─────────────────────────────────────────────────────────────────────── */
  .choice-field{margin:10px 0}
  .choice-rows{display:grid;grid-template-columns:18px max-content 1fr;
    align-items:center;column-gap:8px;row-gap:5px;margin:4px 0}
  .choice-row{display:contents}
  .choice-label{font-size:.88em;cursor:pointer;user-select:none;white-space:nowrap}
  .choice-note{min-width:120px}
  /* ── tabular input fields ───────────────────────────────────────────────────────────────────────── */
  .table-field{margin:10px 0}
  .input-table-wrap{overflow-x:auto;margin:4px 0 6px}
  .input-table{width:100%;border-collapse:collapse;font-size:.85em}
  .input-table th{background:var(--bg2);color:var(--muted);padding:5px 8px;
    text-align:left;border:1px solid var(--border);font-size:.78em;
    text-transform:uppercase;letter-spacing:.05em}
  .input-table td{padding:3px 4px;border:1px solid var(--bg3);vertical-align:top}
  .input-table td input{width:100%;background:var(--code-bg);color:var(--text);
    border:1px solid transparent;border-radius:3px;padding:4px 6px;
    font-family:inherit;font-size:inherit}
  .input-table td input:focus{outline:none;border-color:var(--accent)}
  .input-table td textarea{width:100%;background:var(--code-bg);color:var(--text);
    border:1px solid transparent;border-radius:3px;padding:4px 6px;
    font-family:inherit;font-size:.85em;resize:vertical;min-height:36px}
  .input-table td textarea:focus{outline:none;border-color:var(--accent)}
  .row-del-btn{background:none;border:none;color:var(--muted);cursor:pointer;
    font-size:1em;padding:2px 4px;border-radius:3px}
  .row-del-btn:hover{color:var(--red)}
  .add-row-btn{background:var(--btn-bg);color:var(--muted);border:1px dashed var(--border);
    border-radius:var(--radius);padding:4px 14px;cursor:pointer;font-size:.78em;
    font-family:inherit;margin-top:2px}
  .add-row-btn:hover{border-color:var(--accent);color:var(--accent)}
  /* ── terminal parse fields ─────────────────────────────────────────────────────────────────────────── */
  .parse-field{margin:10px 0;background:var(--bg2);border:1px solid var(--border);
    border-radius:var(--radius);padding:10px 12px}
  .parse-row{display:flex;gap:8px;margin:4px 0;align-items:flex-start}
  .parse-input{flex:1;background:var(--code-bg);color:var(--code-text);
    border:1px solid var(--border);border-radius:4px;padding:6px 8px;
    font-family:'Cascadia Code',Consolas,monospace;font-size:.82em;resize:vertical;min-height:60px}
  .parse-input:focus{outline:none;border-color:var(--accent)}
  .parse-btn{background:var(--btn-bg);color:var(--text);border:1px solid var(--border);
    border-radius:var(--radius);padding:6px 12px;cursor:pointer;font-size:.8em;
    font-family:inherit;flex-shrink:0;white-space:nowrap}
  .parse-btn:hover{border-color:var(--accent);color:var(--accent)}
  .parse-result{background:var(--bg3);border-radius:4px;padding:6px 10px;
    margin-top:5px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:.82em}
  .parse-found{color:var(--muted)}
  .parse-value{font-family:'Cascadia Code',Consolas,monospace;color:var(--green)}
  .parse-apply{background:var(--btn-bg);color:var(--accent);border:1px solid var(--accent);
    border-radius:4px;padding:2px 10px;cursor:pointer;font-size:.78em;font-family:inherit}
  .parse-apply:hover{background:var(--accent);color:var(--bg)}
  /* ── filename auto-suggest fields ──────────────────────────────────────────────────────────────────────────── */
  .filename-field{margin:10px 0}
  .filename-row{display:flex;gap:6px;align-items:center}
  .filename-input{flex:1;font-family:'Cascadia Code',Consolas,monospace;font-size:.85em}
  .filename-suggest-btn{background:var(--btn-bg);color:var(--muted);
    border:1px solid var(--border);border-radius:4px;padding:4px 10px;
    cursor:pointer;font-size:.78em;font-family:inherit;flex-shrink:0}
  .filename-suggest-btn:hover{border-color:var(--accent);color:var(--accent)}
  .filename-dep-warn{background:rgba(249,226,175,.08);border:1px solid rgba(249,226,175,.4);
    border-radius:4px;padding:5px 10px;margin-top:4px;font-size:.78em;
    display:flex;align-items:center;gap:8px;flex-wrap:wrap}
  .dep-warn-text{color:var(--yellow);flex:1}
  .dep-highlight-btn{background:none;border:1px solid var(--yellow);color:var(--yellow);
    border-radius:4px;padding:2px 8px;cursor:pointer;font-size:.75em;font-family:inherit;flex-shrink:0}
  .dep-highlight-btn:hover{background:var(--yellow);color:var(--bg)}
  /* ── directory path fields ───────────────────────────────────────────────────────────────────────────────── */
  .dir-field{margin:10px 0}
  .dir-input{font-family:'Cascadia Code',Consolas,monospace;font-size:.85em}
  .note-input.val-warn,.param-input.val-warn{border-color:#f0a000!important;outline:none}
  .val-hint{color:#f0a000;font-size:.75em;margin-top:2px;display:block}
  /* table of contents */
  #bf-toc{border:1px solid var(--border);border-radius:var(--radius);margin-bottom:14px}
  #bf-toc>summary{background:var(--btn-bg);padding:6px 14px;cursor:pointer;
    user-select:none;list-style:none;font-size:.88em;font-weight:600;color:var(--muted);
    border-radius:var(--radius);letter-spacing:.04em;text-transform:uppercase}
  #bf-toc>summary::-webkit-details-marker{display:none}
  #bf-toc[open]>summary{border-radius:var(--radius) var(--radius) 0 0}
  #bf-toc nav{padding:8px 16px 12px}
  #bf-toc ul{margin:0;padding:0;list-style:none}
  #bf-toc li{margin:2px 0;font-size:.88em}
  #bf-toc a{color:var(--accent);text-decoration:none}
  #bf-toc a:hover{text-decoration:underline}
  .bf-toc-num{color:var(--muted);font-variant-numeric:tabular-nums;margin-right:4px}
  .bf-toc-l2{padding-left:18px;margin-top:2px}
  .bf-toc-l3{padding-left:16px;margin-top:2px}
  .bf-toc-section>summary{list-style:none;cursor:pointer;padding:1px 0}
  .bf-toc-section>summary::-webkit-details-marker{display:none}
  .bf-toc-section[open]>summary::before{content:'\25BE ';font-size:.75em;color:var(--muted)}
  .bf-toc-section>summary::before{content:'\25B8 ';font-size:.75em;color:var(--muted)}
  .bf-toc-active>a{color:var(--accent)!important;font-weight:600}
  .bf-section-num{float:right;font-size:.75em;color:var(--muted);font-variant-numeric:tabular-nums;margin-left:8px;opacity:.7}
  .select-input{width:100%;max-width:360px;padding:3px 8px;height:30px;
    background:var(--code-bg);color:var(--text);border:1px solid var(--border);
    border-radius:var(--radius);font-family:inherit;font-size:.88em}
  .dir-hint{color:var(--muted);font-size:.75em;display:block;margin-top:3px}
  /* ── clear buttons ────────────────────────────────────────────────────────────────────────────────────── */
  #bf-clear-fields-btn{background:var(--btn-bg);color:var(--muted);
    border:1px solid var(--border);border-radius:var(--radius);
    padding:5px 12px;cursor:pointer;font-size:.8em;font-family:inherit}
  #bf-clear-fields-btn:hover{border-color:var(--red);color:var(--red)}
  .sec-clear-btn{background:none;border:1px solid var(--border);color:var(--muted);
    border-radius:3px;padding:0 6px;cursor:pointer;font-size:.72em;
    line-height:1.6;font-family:inherit}
  .sec-clear-btn:hover{border-color:var(--red);color:var(--red)}
  /* ── inline editor ──────────────────────────────────────────────────────────────────────────────────────── */
  .bf-editable-block{position:relative}
  .bf-edit-btn{position:absolute;top:2px;right:2px;opacity:0;background:var(--btn-bg);
    color:var(--muted);border:1px solid var(--border);border-radius:3px;
    padding:1px 6px;font-size:.68em;cursor:pointer;transition:opacity .15s;z-index:10;
    font-family:inherit}
  .bf-editable-block:hover .bf-edit-btn{opacity:1}
  .bf-edit-btn:hover{border-color:var(--accent);color:var(--accent)}
  .bf-edit-area{width:100%;min-height:60px;resize:vertical;background:var(--code-bg);
    color:var(--text);border:1px solid var(--accent);border-radius:var(--radius);
    padding:6px 8px;font-family:inherit;font-size:.9em;line-height:1.6;
    box-sizing:border-box;margin:4px 0}
  .bf-edit-controls{display:flex;gap:6px;margin-bottom:6px}
  .bf-edit-save{background:var(--accent);color:var(--bg);border:none;border-radius:3px;
    padding:3px 10px;cursor:pointer;font-size:.78em;font-family:inherit}
  .bf-edit-cancel{background:none;color:var(--muted);border:1px solid var(--border);
    border-radius:3px;padding:3px 10px;cursor:pointer;font-size:.78em;font-family:inherit}
  .bf-edited-mark{font-size:.65em;color:var(--muted);margin-left:6px;opacity:.7}
  @media print{#bf-doc-pane{padding:12px}#bf-notes-pane,#bf-drag{display:none}
    #bf-theme-btn,.copy-btn{display:none}
    .bf-sub-controls,.bf-edit-btn,.bf-edit-controls{display:none}
    .param-input,.note-input,.note-area,#bf-session-notes{border:1px solid #999}}
"""