#!/usr/bin/env python3
# SYNC REQUIRED: This file is a copy of doc-gen/renderers/html_base.py.
# ALWAYS edit BOTH files together. Run tests/unit/test_html_base_sync.py to
# verify they are identical (comment lines excluded). CI will catch drift.
"""
html_base.py — Shared HTML rendering infrastructure for broodforge documents.

All runbooks, workbooks, and reports are self-contained HTML files that:
  - Work offline with no external dependencies
  - Include interactive checkboxes (state persisted in localStorage)
  - Checkbox behavior: when checked, shows " done" in italics to the right;
    NO strikethrough on label text. This is universal across all HTML documents.
  - Are readable in any modern browser and print-friendly

Public API:
  html_page(title, body, *, doc_id, meta)  → complete HTML string
  h(level, text, *, id)                    → <hN> element
  p(text)                                  → <p> element
  code(text)                               → inline <code>
  pre(text)                                → <pre><code> block
  checkbox_item(label, *, item_id, indent) → interactive checkbox row
  section(title, body, *, open_, id_)     → collapsible <details>
  score_badge(score)                       → coloured score badge
  table(headers, rows)                     → <table>
  dl(pairs)                               → <dl> definition list
  callout(kind, text)                      → .tip / .warn / .danger box
  divider()                                → <hr>
  ul(items)                                → <ul>
  ol(items)                                → <ol>

Stdlib only. No external dependencies.
"""

from html import escape as _e


# ---------------------------------------------------------------------------
# CSS + JS (embedded once per page)
# ---------------------------------------------------------------------------

_CSS = """\
*,*::before,*::after{box-sizing:border-box}
body{font-family:system-ui,-apple-system,'Segoe UI',Arial,sans-serif;
  font-size:14px;line-height:1.55;color:#1a1a2e;background:#fafafa;
  margin:0;padding:0}
header{background:#1a1a2e;color:#e8eaf6;padding:16px 24px}
header h1{margin:0;font-size:1.5em;font-weight:700;letter-spacing:.02em}
header .meta{font-size:.85em;opacity:.75;margin-top:4px}
main{max-width:1100px;margin:0 auto;padding:20px 24px}
h1{font-size:1.4em;color:#1a1a2e;border-bottom:2px solid #1a1a2e;
  padding-bottom:4px;margin-top:1.5em}
h2{font-size:1.2em;color:#1f3864;border-bottom:1px solid #d6e4f0;
  padding-bottom:2px;margin-top:1.4em}
h3{font-size:1.05em;color:#1f3864;margin-top:1.2em}
h4{font-size:.95em;color:#333;margin-top:1em}
p{margin:.4em 0 .8em}
code{font-family:'Cascadia Code','Fira Mono','JetBrains Mono',
  'Courier New',monospace;font-size:.9em;
  background:#f0f2f5;border-radius:3px;padding:1px 5px;color:#2d3748}
pre{background:#f0f2f5;border-left:3px solid #4a90d9;
  padding:10px 14px;overflow-x:auto;border-radius:0 4px 4px 0;margin:.6em 0}
pre code{background:none;padding:0;border:none;font-size:.88em}
a{color:#1f78d1}
hr{border:none;border-top:1px solid #dee2e6;margin:16px 0}
/* --- Details/summary (collapsible sections) --- */
details{border:1px solid #dee2e6;border-radius:4px;margin:.6em 0}
details>summary{
  cursor:pointer;padding:8px 12px;background:#f0f4f8;
  font-weight:600;list-style:none;
  border-radius:4px;user-select:none}
details>summary::before{content:"▶ ";font-size:.8em;color:#6c757d}
details[open]>summary::before{content:"▼ "}
details>summary::-webkit-details-marker{display:none}
details .section-body{padding:8px 16px 12px}
/* --- Tables --- */
table{width:100%;border-collapse:collapse;font-size:.9em;margin:.6em 0}
th{background:#1f3864;color:#fff;text-align:left;padding:7px 10px;font-weight:600}
td{padding:6px 10px;border-bottom:1px solid #dee2e6;vertical-align:top}
tr:nth-child(even) td{background:#f7f9fc}
/* --- Score badges --- */
.score{display:inline-block;font-weight:700;font-size:.82em;
  padding:2px 7px;border-radius:3px;letter-spacing:.04em}
.score-green{background:#d4edda;color:#155724}
.score-yellow{background:#fff3cd;color:#856404}
.score-orange{background:#fde8d0;color:#7c3c00}
.score-red{background:#f8d7da;color:#721c24}
.score-blocked{background:#e2e3e5;color:#383d41}
/* --- Checkboxes --- */
.check-list{list-style:none;padding:0;margin:.4em 0}
.check-list li{margin:.25em 0}
.check-item{display:flex;align-items:baseline;gap:.5em;
  padding:3px 0;cursor:pointer}
.check-item input[type=checkbox]{
  flex-shrink:0;width:14px;height:14px;cursor:pointer;margin:0;
  accent-color:#1f3864}
.check-item .check-label{flex:1;line-height:1.4}
/* Checked state: show " done" in italics — NO strikethrough */
.check-item.checked .check-label::after{
  content:" done";font-style:italic;color:#28a745;
  font-size:.88em;margin-left:.3em}
.check-item.checked input[type=checkbox]{accent-color:#28a745}
/* Indented sub-items */
.check-item.indent-1{padding-left:20px}
.check-item.indent-2{padding-left:40px}
/* --- Callout boxes --- */
.callout{border-left:4px solid;padding:8px 12px;
  margin:.6em 0;border-radius:0 4px 4px 0;font-size:.9em}
.tip{border-color:#0d6efd;background:#e7f1ff;color:#084298}
.warn{border-color:#ffc107;background:#fff8e1;color:#664d03}
.danger{border-color:#dc3545;background:#fce4e4;color:#5a1a22}
/* --- Definition list --- */
dl{display:grid;grid-template-columns:auto 1fr;gap:2px 12px;
  margin:.4em 0;font-size:.9em}
dt{font-weight:600;color:#555;padding:3px 0;white-space:nowrap}
dd{margin:0;padding:3px 0;border-bottom:1px dotted #e0e0e0}
/* --- Print --- */
@media print{
  header{background:#1a1a2e!important;-webkit-print-color-adjust:exact}
  details{border:1px solid #ccc}
  details>summary{background:#e8eaf6!important}
  details:not([open])>summary::after{content:" (collapsed)"}
  .score{-webkit-print-color-adjust:exact}
  .callout{-webkit-print-color-adjust:exact}
}
"""

_JS = r"""
(function(){
  var docKey = document.title || 'broodforge';
  function storeKey(id){ return docKey + '::' + id; }

  function applyState(cb){
    var item = cb.closest('.check-item');
    if(cb.checked){ item.classList.add('checked'); }
    else           { item.classList.remove('checked'); }
  }

  function init(){
    document.querySelectorAll('.check-item input[type=checkbox]').forEach(function(cb){
      var id = cb.id;
      if(id){
        var stored = localStorage.getItem(storeKey(id));
        if(stored === '1'){ cb.checked = true; }
      }
      applyState(cb);
      cb.addEventListener('change', function(){
        applyState(cb);
        if(id){
          if(cb.checked){ localStorage.setItem(storeKey(id),'1'); }
          else           { localStorage.removeItem(storeKey(id)); }
        }
      });
    });
  }

  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', init);
  } else { init(); }
})();
"""


# ---------------------------------------------------------------------------
# Page assembler
# ---------------------------------------------------------------------------

def html_page(
    title:   str,
    body:    str,
    *,
    doc_id:  str = "",
    meta:    str = "",
) -> str:
    """
    Assemble a complete, self-contained HTML page.

    title:  document title (shown in browser tab + header)
    body:   inner HTML content
    doc_id: short ID (used as localStorage prefix); defaults to title
    meta:   optional subtitle / metadata line in header
    """
    esc_title = _e(title)
    header_meta = f'<div class="meta">{_e(meta)}</div>' if meta else ""
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n'
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f'<title>{esc_title}</title>\n'
        f'<style>{_CSS}</style>\n'
        "</head>\n<body>\n"
        f'<header><h1>{esc_title}</h1>{header_meta}</header>\n'
        f'<main>{body}</main>\n'
        f"<script>{_JS}</script>\n"
        "</body>\n</html>"
    )


# ---------------------------------------------------------------------------
# Element builders
# ---------------------------------------------------------------------------

def h(level: int, text: str, *, id_: str = "") -> str:
    """Heading h1–h4."""
    eid = f' id="{_e(id_)}"' if id_ else ""
    return f"<h{level}{eid}>{_e(text)}</h{level}>\n"


def p(text: str) -> str:
    """Paragraph. text may contain pre-escaped HTML."""
    return f"<p>{text}</p>\n"


def code(text: str) -> str:
    """Inline code span."""
    return f"<code>{_e(text)}</code>"


def pre(text: str) -> str:
    """Preformatted code block."""
    return f"<pre><code>{_e(text)}</code></pre>\n"


def ul(items: list[str]) -> str:
    """Unordered list. Items may contain pre-escaped HTML."""
    if not items:
        return ""
    li = "".join(f"<li>{item}</li>\n" for item in items)
    return f"<ul>{li}</ul>\n"


def ol(items: list[str]) -> str:
    """Ordered list."""
    if not items:
        return ""
    li = "".join(f"<li>{item}</li>\n" for item in items)
    return f"<ol>{li}</ol>\n"


def dl(pairs: list[tuple[str, str]]) -> str:
    """Definition list of (term, definition) pairs."""
    if not pairs:
        return ""
    rows = "".join(
        f"<dt>{_e(k)}</dt><dd>{_e(v) if isinstance(v, str) else v}</dd>\n"
        for k, v in pairs
    )
    return f"<dl>{rows}</dl>\n"


def table(headers: list[str], rows: list[list[str]]) -> str:
    """HTML table. Cell content may be pre-escaped HTML."""
    th = "".join(f"<th>{_e(h_)}</th>" for h_ in headers)
    body_rows = ""
    for row in rows:
        tds = "".join(f"<td>{cell}</td>" for cell in row)
        body_rows += f"<tr>{tds}</tr>\n"
    return f"<table><thead><tr>{th}</tr></thead><tbody>{body_rows}</tbody></table>\n"


def callout(kind: str, text: str) -> str:
    """
    Callout box.

    kind: "tip" | "warn" | "danger"
    """
    kind = kind.lower()
    if kind not in ("tip", "warn", "danger"):
        kind = "tip"
    return f'<div class="callout {kind}">{text}</div>\n'


def divider() -> str:
    return "<hr>\n"


def score_badge(score: str) -> str:
    """Return a coloured score badge span."""
    s = score.upper() if score else "?"
    cls_map = {
        "GREEN": "score-green", "YELLOW": "score-yellow",
        "ORANGE": "score-orange", "RED": "score-red",
        "BLOCKED": "score-blocked",
    }
    cls = cls_map.get(s, "score-blocked")
    return f'<span class="score {cls}">{_e(s)}</span>'


def section(title: str, body: str, *, open_: bool = True, id_: str = "") -> str:
    """
    Collapsible <details>/<summary> section.

    open_: whether the section is expanded by default
    """
    attr_open = " open" if open_ else ""
    eid = f' id="{_e(id_)}"' if id_ else ""
    return (
        f'<details{attr_open}{eid}>\n'
        f'<summary>{_e(title)}</summary>\n'
        f'<div class="section-body">{body}</div>\n'
        f'</details>\n'
    )


# ---------------------------------------------------------------------------
# Checkbox infrastructure
# ---------------------------------------------------------------------------

_checkbox_counter = 0


def _next_cb_id(prefix: str = "cb") -> str:
    global _checkbox_counter
    _checkbox_counter += 1
    return f"{prefix}-{_checkbox_counter}"


def reset_checkbox_counter() -> None:
    """Reset the global checkbox ID counter (call before generating a new document)."""
    global _checkbox_counter
    _checkbox_counter = 0


def checkbox_item(
    label:    str,
    *,
    item_id:  str = "",
    indent:   int = 0,
    raw_label: bool = False,
) -> str:
    """
    A single interactive checkbox row.

    label:      text shown next to checkbox
    item_id:    stable ID for localStorage persistence (auto-generated if empty)
    indent:     0/1/2 — indentation level
    raw_label:  if True, label is treated as pre-escaped HTML

    Behavior: when checked, appends " done" in italics. No strikethrough.
    """
    cb_id = item_id or _next_cb_id()
    indent_cls = f" indent-{indent}" if indent else ""
    label_html = label if raw_label else _e(label)
    return (
        f'<li class="check-item{indent_cls}">'
        f'<input type="checkbox" id="{_e(cb_id)}">'
        f'<label class="check-label" for="{_e(cb_id)}">{label_html}</label>'
        f'</li>\n'
    )


def checkbox_list(
    items: list[str | tuple],
    *,
    id_prefix: str = "",
) -> str:
    """
    Build a <ul class="check-list"> of checkbox items.

    items: list of:
      str             → simple label
      (label, id)     → label with explicit ID
      (label, id, indent) → label with ID and indent level
    """
    rows = ""
    for i, item in enumerate(items):
        if isinstance(item, str):
            label, item_id, indent = item, "", 0
        elif len(item) == 2:
            label, item_id = item
            indent = 0
        else:
            label, item_id, indent = item[0], item[1], item[2]
        if not item_id and id_prefix:
            item_id = f"{id_prefix}-{i}"
        rows += checkbox_item(label, item_id=item_id, indent=indent)
    return f'<ul class="check-list">\n{rows}</ul>\n'


# ---------------------------------------------------------------------------
# Commands block helper
# ---------------------------------------------------------------------------

def commands_block(cmds: list[str], heading: str = "") -> str:
    """Render a list of shell commands as a preformatted block with optional heading."""
    parts = ""
    if heading:
        parts += h(4, heading)
    parts += pre("\n".join(cmds))
    return parts
