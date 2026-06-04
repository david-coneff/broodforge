#!/usr/bin/env python3
"""
inject_html_theme.py — Progressive-enhancement theme toggle + copy buttons for
hand-authored HTML documents.

The md_to_html.py converter bakes the light/dark toggle and per-code-block copy
buttons into every doc it generates. Some HTML docs are hand-authored instead
(docs/ARCHITECTURE.html, docs/SETUP-GUIDE.html). This script retro-fits those
with the same behaviour without rewriting them:

  * adds a fixed top-right light/dark toggle (persisted in localStorage);
  * injects a `body.light{…}` palette that overrides the doc's CSS variables
    (plus the Broodforge phase-color collapsibles used by ARCHITECTURE.html);
  * wraps every <pre> with a Copy button at run time.

Idempotent: a marker comment prevents double injection. Re-run any time.

Usage:
    python3 inject_html_theme.py FILE.html [FILE2.html ...]

Stdlib only.
"""

import sys
from pathlib import Path

_MARKER = "<!-- bf-theme-injected -->"

_CSS = """
<style>/* bf-theme */
  body.light{--bg:#ffffff;--bg2:#f4f5f7;--bg3:#eceff2;--border:#d0d7de;--text:#1f2328;--muted:#57606a;
    --accent:#0969da;--green:#1a7f37;--yellow:#9a6700;--orange:#bc4c00;--red:#cf222e;
    --code-bg:#f6f8fa;--forge-h:#8250df;--spawn-h:#0969da;--phoenix-h:#bc4c00}
  /* ARCHITECTURE.html phase collapsibles: light overrides */
  body.light details.phase-a>summary{background:#f3eefc;border-color:#d8c8f0}
  body.light details.phase-a>.detail-body{background:#faf7ff;border-color:#e6dcf6}
  body.light details.phase-b>summary{background:#eaf2fb;border-color:#c4dcf0}
  body.light details.phase-b>.detail-body{background:#f5f9fe;border-color:#dceaf6}
  body.light details.phase-c>summary{background:#fdf0e8;border-color:#f0d2bc}
  body.light details.phase-c>.detail-body{background:#fff8f3;border-color:#f6e2d2}
  body.light details.phase-d>summary{background:#eafaef;border-color:#c8eed2}
  body.light details.phase-d>.detail-body{background:#f5fdf7;border-color:#dcf2e2}
  body.light pre{color:#0a3069}
  #bf-theme-btn{position:fixed;top:14px;right:16px;z-index:50;background:var(--bg3,#2a2f3a);
    color:var(--text,#cdd6f4);border:1px solid var(--border,#3a3f4d);border-radius:6px;padding:5px 12px;
    cursor:pointer;font-size:.8em;font-family:inherit}
  #bf-theme-btn:hover{border-color:var(--accent,#89b4fa);color:var(--accent,#89b4fa)}
  .bf-codewrap{position:relative}
  .bf-copy{position:absolute;top:6px;right:6px;background:var(--bg3,#2a2f3a);color:var(--muted,#7f8498);
    border:1px solid var(--border,#3a3f4d);border-radius:4px;padding:2px 9px;cursor:pointer;font-size:.72em;
    font-family:inherit;opacity:.55;transition:opacity .12s}
  .bf-codewrap:hover .bf-copy{opacity:1}
  .bf-copy:hover{border-color:var(--accent,#89b4fa);color:var(--accent,#89b4fa)}
  @media print{#bf-theme-btn,.bf-copy{display:none}}
</style>
"""

_JS = r"""
<script>/* bf-theme */
(function(){
  var btn=document.createElement('button'); btn.id='bf-theme-btn'; btn.type='button';
  document.body.appendChild(btn);
  function lbl(){ btn.textContent=document.body.classList.contains('light')?'☾ Dark':'☀ Light'; }
  try{ if(localStorage.getItem('bf:theme')==='light') document.body.classList.add('light'); }catch(e){}
  lbl();
  btn.addEventListener('click',function(){ document.body.classList.toggle('light');
    try{localStorage.setItem('bf:theme',document.body.classList.contains('light')?'light':'dark');}catch(e){}
    lbl(); });
  var pres=document.querySelectorAll('pre');
  for(var i=0;i<pres.length;i++){ (function(pre){
    if(pre.parentElement && pre.parentElement.classList.contains('bf-codewrap')) return;
    var w=document.createElement('div'); w.className='bf-codewrap';
    pre.parentNode.insertBefore(w,pre); w.appendChild(pre);
    var c=document.createElement('button'); c.className='bf-copy'; c.type='button'; c.textContent='Copy';
    w.appendChild(c);
    c.addEventListener('click',function(){ var t=pre.innerText;
      var done=function(){var o=c.textContent;c.textContent='Copied!';setTimeout(function(){c.textContent=o;},1200);};
      if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(t).then(done,done);}
      else{var ta=document.createElement('textarea');ta.value=t;document.body.appendChild(ta);ta.select();
        try{document.execCommand('copy');}catch(e){}document.body.removeChild(ta);done();}
    });
  })(pres[i]); }
})();
</script>
"""


def inject(path: Path) -> bool:
    html = path.read_text(encoding="utf-8")
    if _MARKER in html:
        return False
    payload_css = _MARKER + "\n" + _CSS
    if "</head>" in html:
        html = html.replace("</head>", payload_css + "</head>", 1)
    else:
        html = payload_css + html
    if "</body>" in html:
        html = html.replace("</body>", _JS + "</body>", 1)
    else:
        html = html + _JS
    path.write_text(html, encoding="utf-8")
    return True


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: inject_html_theme.py FILE.html [FILE2.html ...]", file=sys.stderr)
        sys.exit(2)
    for arg in sys.argv[1:]:
        p = Path(arg)
        if not p.exists():
            print(f"[inject] not found: {p}", file=sys.stderr)
            continue
        changed = inject(p)
        print(f"[inject] {'updated' if changed else 'already injected'}: {p}")


if __name__ == "__main__":
    main()
