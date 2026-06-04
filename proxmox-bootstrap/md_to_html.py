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
  #bf-toolbar{position:fixed;top:14px;right:16px;z-index:50;display:flex;gap:8px}
  #bf-toolbar button{background:var(--btn-bg);color:var(--text);border:1px solid var(--border);
    border-radius:var(--radius);padding:5px 12px;cursor:pointer;font-size:.8em;font-family:inherit}
  #bf-toolbar button:hover{border-color:var(--accent);color:var(--accent)}
  /* attachments */
  .attachments{margin-top:30px;border-top:1px solid var(--border);padding-top:14px}
  .attachments input[type=file]{color:var(--muted);font-size:.85em;margin-top:6px}
  .attach-list{list-style:none;margin:10px 0 0;padding:0}
  .attach-list li{display:flex;align-items:center;gap:10px;background:var(--bg2);border:1px solid var(--border);
    border-radius:var(--radius);padding:5px 10px;margin:4px 0;font-size:.85em}
  .attach-list .sz{color:var(--muted);font-size:.9em}
  .attach-list button{margin-left:auto;background:none;border:1px solid var(--border);color:var(--muted);
    border-radius:4px;cursor:pointer;padding:1px 8px;font-size:.85em}
  .attach-list button:hover{border-color:var(--red);color:var(--red)}
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
  // ---- attachments + export package (walkthrough docs only) ----
  var atts = [];  // {name, type, bytes:Uint8Array}
  var fileInput = document.getElementById('bf-attach-input');
  var attList = document.getElementById('bf-attach-list');
  function fmtSize(n){ return n<1024?n+' B':(n<1048576?(n/1024).toFixed(1)+' KB':(n/1048576).toFixed(1)+' MB'); }
  function renderAtts(){
    if(!attList) return;
    attList.innerHTML='';
    atts.forEach(function(a, idx){
      var li=document.createElement('li');
      var nm=document.createElement('span'); nm.textContent=a.name;
      var sz=document.createElement('span'); sz.className='sz'; sz.textContent=fmtSize(a.bytes.length);
      var rm=document.createElement('button'); rm.type='button'; rm.textContent='remove';
      rm.addEventListener('click', function(){ atts.splice(idx,1); renderAtts(); });
      li.appendChild(nm); li.appendChild(sz); li.appendChild(rm); attList.appendChild(li);
    });
  }
  if(fileInput){
    fileInput.addEventListener('change', function(){
      var files=Array.prototype.slice.call(fileInput.files||[]);
      var pending=files.length; if(!pending) return;
      files.forEach(function(f){
        var rd=new FileReader();
        rd.onload=function(){ atts.push({name:f.name, type:f.type||'application/octet-stream', bytes:new Uint8Array(rd.result)});
          if(--pending===0) renderAtts(); };
        rd.readAsArrayBuffer(f);
      });
      fileInput.value='';
    });
  }
  var crcTable=(function(){ var t=[],c,n,k; for(n=0;n<256;n++){ c=n; for(k=0;k<8;k++){ c=(c&1)?(0xEDB88320^(c>>>1)):(c>>>1); } t[n]=c>>>0; } return t; })();
  function crc32(buf){ var c=0xFFFFFFFF; for(var i=0;i<buf.length;i++){ c=crcTable[(c^buf[i])&0xFF]^(c>>>8); } return (c^0xFFFFFFFF)>>>0; }
  function enc(s){ return new TextEncoder().encode(s); }
  function buildZip(entries){
    var d=new Date();
    var dt=((d.getHours()<<11)|(d.getMinutes()<<5)|Math.floor(d.getSeconds()/2))&0xFFFF;
    var dd=(((d.getFullYear()-1980)<<9)|((d.getMonth()+1)<<5)|d.getDate())&0xFFFF;
    function u16(v){ return [v&0xFF,(v>>>8)&0xFF]; }
    function u32(v){ return [v&0xFF,(v>>>8)&0xFF,(v>>>16)&0xFF,(v>>>24)&0xFF]; }
    var parts=[], central=[], offset=0;
    entries.forEach(function(e){
      var nameB=enc(e.name), crc=crc32(e.bytes), sz=e.bytes.length;
      var lh=[].concat(u32(0x04034b50),u16(20),u16(0),u16(0),u16(dt),u16(dd),u32(crc),u32(sz),u32(sz),u16(nameB.length),u16(0));
      parts.push(new Uint8Array(lh)); parts.push(nameB); parts.push(e.bytes);
      var cd=[].concat(u32(0x02014b50),u16(20),u16(20),u16(0),u16(0),u16(dt),u16(dd),u32(crc),u32(sz),u32(sz),u16(nameB.length),u16(0),u16(0),u16(0),u16(0),u32(0),u32(offset));
      central.push(new Uint8Array(cd)); central.push(nameB);
      offset += lh.length + nameB.length + sz;
    });
    var cdSize=0; central.forEach(function(c){ cdSize+=c.length; });
    var eocd=[].concat(u32(0x06054b50),u16(0),u16(0),u16(entries.length),u16(entries.length),u32(cdSize),u32(offset),u16(0));
    return new Blob(parts.concat(central, [new Uint8Array(eocd)]), {type:'application/zip'});
  }
  function pad(n){ return (n<10?'0':'')+n; }
  function stamp(){ var d=new Date(); return d.getFullYear()+'_'+pad(d.getMonth()+1)+'_'+pad(d.getDate())+'_'+pad(d.getHours())+'_'+pad(d.getMinutes())+'_'+pad(d.getSeconds()); }
  function titleSlug(){ return (document.title||'Walkthrough').trim().replace(/\s+/g,'-').replace(/[^A-Za-z0-9_-]/g,'') || 'Walkthrough'; }
  function collect(){
    var params={}, pin=document.querySelectorAll('.param-input');
    for(var i=0;i<pin.length;i++){ params[pin[i].dataset.var]=pin[i].value; }
    var notes=[], nf=document.querySelectorAll('.notefield');
    for(var j=0;j<nf.length;j++){ var lab=nf[j].querySelector('label'), inp=nf[j].querySelector('.note-input,.note-area');
      if(inp) notes.push({label:lab?lab.textContent:'', value:inp.value}); }
    var sn=document.getElementById('bf-session-notes');
    return {params:params, notes:notes, session_notes:sn?sn.value:''};
  }
  function notesMd(data){
    var L=['# '+(document.title||'Walkthrough')+' — Record','','Exported: '+new Date().toString(),''];
    var pk=Object.keys(data.params);
    if(pk.length){ L.push('## Parameters'); pk.forEach(function(k){ L.push('- '+k+': '+data.params[k]); }); L.push(''); }
    if(data.notes.length){ L.push('## Notes'); data.notes.forEach(function(n){ L.push('### '+n.label,(n.value||'(blank)'),''); }); }
    L.push('## Session Notes', (data.session_notes||'(blank)'), '');
    if(atts.length){ L.push('## Attachments'); atts.forEach(function(a){ L.push('- attachments/'+a.name+' ('+fmtSize(a.bytes.length)+')'); }); L.push(''); }
    return L.join('\n');
  }
  var exportBtn=document.getElementById('bf-export-btn');
  if(exportBtn){
    exportBtn.addEventListener('click', function(){
      var data=collect(), entries=[];
      entries.push({name:'notes.md', bytes:enc(notesMd(data))});
      entries.push({name:'record.json', bytes:enc(JSON.stringify({title:document.title, exported_at:new Date().toISOString(),
        parameters:data.params, notes:data.notes, session_notes:data.session_notes,
        attachments:atts.map(function(a){ return {name:a.name, size:a.bytes.length, type:a.type}; })}, null, 2))});
      atts.forEach(function(a){ entries.push({name:'attachments/'+a.name, bytes:a.bytes}); });
      var url=URL.createObjectURL(buildZip(entries));
      var a=document.createElement('a'); a.href=url; a.download=titleSlug()+'_'+stamp()+'.zip';
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      setTimeout(function(){ URL.revokeObjectURL(url); }, 1000);
      var o=exportBtn.textContent; exportBtn.textContent='Saved ✓'; setTimeout(function(){ exportBtn.textContent=o; }, 1400);
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

    # A "walkthrough" is any doc with live parameters or note fields — those get
    # the Attachments area and the Export-package button. Reference docs do not.
    is_walkthrough = bool(tpl_vars) or bool(re.search(r"(?m)^@(?:field|area)\[", md))

    toolbar = "<div id=\"bf-toolbar\">"
    if is_walkthrough:
        toolbar += '<button id="bf-export-btn" type="button">⬇ Export</button>'
    toolbar += '<button id="bf-theme-btn" type="button">☀ Light</button></div>'

    attachments = ""
    if is_walkthrough:
        attachments = (
            '<div class="attachments"><h2>Attachments</h2>'
            '<p style="color:var(--muted);font-size:.85em">Attach logs, screenshots, or command '
            'output for this run. Files are bundled into the exported package (held in this tab '
            'until you Export). <strong>Export</strong> (top-right) saves parameters, notes, and '
            'attachments as a timestamped <code>.zip</code>.</p>'
            '<input type="file" id="bf-attach-input" multiple>'
            '<ul class="attach-list" id="bf-attach-list"></ul></div>'
        )

    session_notes = (
        '<div class="session-notes"><h2>Session Notes</h2>'
        '<p style="color:var(--muted);font-size:.85em">Anything unexpected, or that did not fit the '
        'steps above. Saved in your browser.</p>'
        '<textarea id="bf-session-notes" placeholder="notes…"></textarea></div>'
    )

    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f"<title>{html.escape(title)}</title>\n"
        f"<style>{_CSS}</style>\n"
        "</head>\n"
        f'<body data-doc="{_doc_slug(title)}">\n'
        f"{toolbar}\n{meta}\n{params_panel}\n{body}\n{attachments}\n{session_notes}\n"
        f"<script>{_JS}</script>\n"
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
