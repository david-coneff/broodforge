#!/usr/bin/env python3
"""
md_to_html.py — Minimal, stdlib-only Markdown → HTML converter for Broodforge.

Renders a self-contained, interactive HTML document in the Broodforge theme.
Every generated page includes:

  * a light/dark theme toggle (top-right, persisted in localStorage);
  * a "Copy" button on every code block;
  * live-templated commands — any `{{VAR}}` / `{{VAR=default}}` placeholder inside
    a code block becomes an editable parameter. A "Parameters" panel at the top
    of the page collects them; editing a value rewrites every command that uses
    it, and the Copy button copies the resolved command;
  * walkthrough note fields — `@field[Label]` (single line) / `@area[Label]`
    (multi-line) render labeled inputs the operator can fill while following the
    steps, so a drill or forge has a traceable record;
  * an always-present "Session Notes" textarea at the bottom for anything that
    didn't fit the structured flow.

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
    --code-bg:#181b21;--code-text:#a6e3a1;--radius:6px;--btn-bg:#2a2f3a}
  body.light{--bg:#ffffff;--bg2:#f4f5f7;--bg3:#eceff2;--border:#d0d7de;--text:#1f2328;--muted:#57606a;
    --accent:#0969da;--green:#1a7f37;--yellow:#9a6700;--orange:#bc4c00;--red:#cf222e;
    --code-bg:#f6f8fa;--code-text:#0a3069;--btn-bg:#eaeef2}
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--text);font-family:'Segoe UI',system-ui,-apple-system,sans-serif;
    font-size:14px;line-height:1.6;padding:24px 24px 80px;max-width:1100px;margin:0 auto;
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
  #bf-theme-btn{position:fixed;top:14px;right:16px;z-index:50;background:var(--btn-bg);color:var(--text);
    border:1px solid var(--border);border-radius:var(--radius);padding:5px 12px;cursor:pointer;
    font-size:.8em;font-family:inherit}
  #bf-theme-btn:hover{border-color:var(--accent);color:var(--accent)}
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
  .session-notes{margin-top:36px;border-top:1px solid var(--border);padding-top:14px}
  @media print{body{padding:12px;max-width:none}#bf-theme-btn,.copy-btn{display:none}
    .param-input,.note-input,.note-area,#bf-session-notes{border:1px solid #999}}
"""

_JS = r"""
(function(){
  var ns = 'bf:' + (document.body.dataset.doc || 'doc') + ':';
  // ---- theme ----
  try{ if(localStorage.getItem('bf:theme')==='light') document.body.classList.add('light'); }catch(e){}
  var tb = document.getElementById('bf-theme-btn');
  function lbl(){ tb.textContent = document.body.classList.contains('light') ? '☾ Dark' : '☀ Light'; }
  if(tb){ lbl(); tb.addEventListener('click', function(){
    document.body.classList.toggle('light');
    try{ localStorage.setItem('bf:theme', document.body.classList.contains('light')?'light':'dark'); }catch(e){}
    lbl();
  }); }
  // ---- live template parameters ----
  function applyVar(name, val){
    var slots = document.querySelectorAll('.tpl[data-var="'+name+'"]');
    for(var i=0;i<slots.length;i++){ slots[i].textContent = val; }
  }
  var inputs = document.querySelectorAll('.param-input');
  for(var i=0;i<inputs.length;i++){
    (function(inp){
      var name = inp.dataset.var, k = ns+'param:'+name;
      try{ var s = localStorage.getItem(k); if(s!==null) inp.value = s; }catch(e){}
      applyVar(name, inp.value);
      inp.addEventListener('input', function(){
        applyVar(name, inp.value);
        try{ localStorage.setItem(k, inp.value); }catch(e){}
      });
    })(inputs[i]);
  }
  // ---- note fields + session notes (persisted) ----
  var notes = document.querySelectorAll('.note-input,.note-area,#bf-session-notes');
  for(var j=0;j<notes.length;j++){
    (function(el){
      var id = el.dataset.note || el.id, k = ns+'note:'+id;
      try{ var s = localStorage.getItem(k); if(s!==null) el.value = s; }catch(e){}
      el.addEventListener('input', function(){ try{ localStorage.setItem(k, el.value); }catch(e){} });
    })(notes[j]);
  }
  // ---- copy buttons ----
  var btns = document.querySelectorAll('.copy-btn');
  for(var b=0;b<btns.length;b++){
    btns[b].addEventListener('click', function(){
      var btn = this, pre = btn.parentElement.querySelector('pre');
      var text = pre.innerText;
      var done = function(){ var o=btn.textContent; btn.textContent='Copied!'; setTimeout(function(){btn.textContent=o;},1200); };
      if(navigator.clipboard && navigator.clipboard.writeText){
        navigator.clipboard.writeText(text).then(done, function(){ done(); });
      } else {
        var ta=document.createElement('textarea'); ta.value=text; document.body.appendChild(ta);
        ta.select(); try{document.execCommand('copy');}catch(e){} document.body.removeChild(ta); done();
      }
    });
  }
})();
"""


def theme_assets() -> tuple:
    """Return (css, js, toggle_button_html) for injection into bespoke HTML docs."""
    return _CSS, _JS, '<button id="bf-theme-btn" type="button">☀ Light</button>'


# ---------------------------------------------------------------------------
# Inline rendering
# ---------------------------------------------------------------------------

def _inline(text: str) -> str:
    text = html.escape(text, quote=False)
    spans: list = []

    def _stash(m: "re.Match") -> str:
        spans.append(m.group(1))
        return f"\x00{len(spans) - 1}\x00"

    text = re.sub(r"`([^`]+)`", _stash, text)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"\*\*([^*]+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\x00(\d+)\x00", lambda m: f"<code>{spans[int(m.group(1))]}</code>", text)
    return text


# ---------------------------------------------------------------------------
# Template placeholders inside code blocks
# ---------------------------------------------------------------------------

_TPL_RE = re.compile(r"\{\{\s*([A-Za-z][\w-]*)\s*(?:=([^}]*))?\}\}")


def _render_code(raw: str, tpl_vars: dict) -> str:
    """HTML-escape code, then turn {{VAR}} / {{VAR=default}} into live slots."""
    escaped = html.escape(raw, quote=False)

    def _repl(m: "re.Match") -> str:
        name = m.group(1)
        default = (m.group(2) or "").strip()
        if name not in tpl_vars:
            tpl_vars[name] = default
        shown = tpl_vars[name] or name
        return f'<span class="tpl" data-var="{html.escape(name)}">{html.escape(shown)}</span>'

    return _TPL_RE.sub(_repl, escaped)


# ---------------------------------------------------------------------------
# Block rendering
# ---------------------------------------------------------------------------

def _is_table_sep(line: str) -> bool:
    s = line.strip()
    if "|" not in s and "-" not in s:
        return False
    s = s.strip("|")
    cells = s.split("|")
    if not cells:
        return False
    for c in cells:
        c = c.strip()
        if not c or not re.fullmatch(r":?-+:?", c):
            return False
    return True


def _split_row(line: str) -> list:
    s = line.strip()
    s = re.sub(r"^\|", "", s)
    s = re.sub(r"\|$", "", s)
    return [c.strip() for c in s.split("|")]


def _render_blocks(md: str, tpl_vars: dict) -> str:
    lines = md.split("\n")
    out: list = []
    i, n = 0, len(lines)

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # Note-field markers: @field[Label]  /  @area[Label]
        m = re.match(r"^@(field|area)\[(.+?)\]\s*$", stripped)
        if m:
            kind, label = m.group(1), m.group(2)
            slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:48] or "note"
            if kind == "field":
                out.append(
                    f'<div class="notefield"><label>{html.escape(label)}</label>'
                    f'<input type="text" class="note-input" data-note="{slug}" '
                    f'placeholder="record here…"></div>'
                )
            else:
                out.append(
                    f'<div class="notefield"><label>{html.escape(label)}</label>'
                    f'<textarea class="note-area" data-note="{slug}" '
                    f'placeholder="record here…"></textarea></div>'
                )
            i += 1
            continue

        # Fenced code block
        m = re.match(r"^(\s*)(`{3,}|~{3,})(.*)$", line)
        if m:
            fence = m.group(2)[0]
            buf: list = []
            i += 1
            while i < n and not re.match(rf"^\s*{fence}{{3,}}\s*$", lines[i]):
                buf.append(lines[i])
                i += 1
            i += 1
            code = _render_code("\n".join(buf), tpl_vars)
            out.append(
                '<div class="codewrap"><button class="copy-btn" type="button">Copy</button>'
                f"<pre><code>{code}</code></pre></div>"
            )
            continue

        # Heading
        m = re.match(r"^(#{1,6})\s+(.*?)\s*#*$", line)
        if m:
            level = len(m.group(1))
            out.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
            i += 1
            continue

        # Horizontal rule
        if re.fullmatch(r"(\s*[-*_]){3,}\s*", line) and set(stripped) <= {"-", "*", "_", " "}:
            out.append("<hr>")
            i += 1
            continue

        # Table
        if "|" in line and i + 1 < n and _is_table_sep(lines[i + 1]):
            header = _split_row(line)
            i += 2
            body: list = []
            while i < n and "|" in lines[i] and lines[i].strip():
                body.append(_split_row(lines[i]))
                i += 1
            thead = "".join(f"<th>{_inline(c)}</th>" for c in header)
            rows_html = ""
            for row in body:
                cells = (row + [""] * len(header))[: len(header)]
                rows_html += "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells) + "</tr>"
            out.append(f"<table><thead><tr>{thead}</tr></thead><tbody>{rows_html}</tbody></table>")
            continue

        # Blockquote
        if re.match(r"^\s*>\s?", line):
            buf = []
            while i < n and re.match(r"^\s*>\s?", lines[i]):
                buf.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            inner = " ".join(b.strip() for b in buf if b.strip())
            out.append(f"<blockquote>{_inline(inner)}</blockquote>")
            continue

        # Lists
        if re.match(r"^\s*([-*+]|\d+\.)\s+", line):
            i = _render_list(lines, i, out)
            continue

        # Paragraph
        buf = []
        while i < n and lines[i].strip() and not _starts_block(lines[i], lines, i):
            buf.append(lines[i].strip())
            i += 1
        out.append(f"<p>{_inline(' '.join(buf))}</p>")

    return "\n".join(out)


def _starts_block(line: str, lines: list, idx: int) -> bool:
    if re.match(r"^(\s*)(`{3,}|~{3,})", line):
        return True
    if re.match(r"^#{1,6}\s+", line):
        return True
    if re.match(r"^\s*([-*+]|\d+\.)\s+", line):
        return True
    if re.match(r"^\s*>\s?", line):
        return True
    if re.match(r"^@(field|area)\[", line.strip()):
        return True
    if re.fullmatch(r"(\s*[-*_]){3,}\s*", line) and set(line.strip()) <= {"-", "*", "_", " "}:
        return True
    if "|" in line and idx + 1 < len(lines) and _is_table_sep(lines[idx + 1]):
        return True
    return False


def _render_list(lines: list, i: int, out: list) -> int:
    n = len(lines)
    base_indent = len(lines[i]) - len(lines[i].lstrip())
    ordered = bool(re.match(r"^\s*\d+\.\s+", lines[i]))
    tag = "ol" if ordered else "ul"
    out.append(f"<{tag}>")
    while i < n:
        line = lines[i]
        if not line.strip():
            if i + 1 < n and re.match(r"^\s*([-*+]|\d+\.)\s+", lines[i + 1]):
                i += 1
                continue
            break
        m = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)$", line)
        if not m:
            break
        indent = len(m.group(1))
        if indent < base_indent:
            break
        if indent >= base_indent + 2 and out and not out[-1].endswith("</li>"):
            i = _render_list(lines, i, out)
            continue
        out.append(f"<li>{_inline(m.group(3))}</li>")
        i += 1
    out.append(f"</{tag}>")
    return i


# ---------------------------------------------------------------------------
# Document assembly
# ---------------------------------------------------------------------------

def _doc_slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48] or "doc"


def render_html(md: str, title: str, source_name: str = "") -> str:
    tpl_vars: dict = {}
    body = _render_blocks(md, tpl_vars)

    meta = (f'<div class="doc-meta">Generated from <code>{html.escape(source_name)}</code> '
            f'— self-contained · print-friendly · values saved in your browser</div>'
            ) if source_name else ""

    params_panel = ""
    if tpl_vars:
        rows = ""
        for name, default in tpl_vars.items():
            rows += (
                f'<div class="param-row"><label for="p-{html.escape(name)}">{html.escape(name)}</label>'
                f'<input class="param-input" id="p-{html.escape(name)}" data-var="{html.escape(name)}" '
                f'type="text" value="{html.escape(default)}" placeholder="{html.escape(name)}"></div>'
            )
        params_panel = (
            '<div class="params"><h3>Parameters</h3>'
            '<div class="hint">Fill these in — every command below updates live, and the '
            'Copy button copies the resolved command.</div>'
            f"{rows}</div>"
        )

    session_notes = (
        '<div class="session-notes"><h2>Session Notes</h2>'
        '<p style="color:var(--muted);font-size:.85em">Anything unexpected, or that did not fit the '
        'steps above. Saved in your browser.</p>'
        '<textarea id="bf-session-notes" placeholder="notes…"></textarea></div>'
    )

    _, js, toggle = theme_assets()
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f"<title>{html.escape(title)}</title>\n"
        f"<style>{_CSS}</style>\n"
        "</head>\n"
        f'<body data-doc="{_doc_slug(title)}">\n'
        f"{toggle}\n{meta}\n{params_panel}\n{body}\n{session_notes}\n"
        f"<script>{js}</script>\n"
        "</body>\n</html>\n"
    )


def convert_file(src: Path, dst: Path, title: str = "") -> None:
    md = src.read_text(encoding="utf-8-sig")
    if not title:
        m = re.search(r"^#\s+(.*)$", md, re.MULTILINE)
        title = m.group(1).strip() if m else src.stem
    dst.write_text(render_html(md, title, src.name), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Convert a Markdown file to themed, interactive HTML")
    ap.add_argument("input", help="Input .md file")
    ap.add_argument("output", help="Output .html file")
    ap.add_argument("--title", default="", help="Document title (default: first H1)")
    args = ap.parse_args()
    src = Path(args.input)
    if not src.exists():
        print(f"[md_to_html] not found: {src}", file=sys.stderr)
        sys.exit(2)
    convert_file(src, Path(args.output), args.title)
    print(f"[md_to_html] wrote {args.output}")


if __name__ == "__main__":
    main()
