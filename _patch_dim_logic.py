path = r'proxmox-bootstrap\md_to_html.py'
with open(path, 'r', encoding='utf-8') as f:
    text = f.read()

# 1. CSS: body visibility:hidden hides everything in dim sections (including dashed buttons);
#    restore visibility for any non-dim section inside (the active nested one).
old1 = "  .nts-section.nts-dim>.nts-body{background:transparent!important}"
new1 = (
    "  .nts-section.nts-dim>.nts-body{background:transparent!important;visibility:hidden}\n"
    "  .nts-section:not(.nts-dim){visibility:visible}"
)
c1 = text.count(old1); assert c1 == 1, f"CSS body: {c1}"; text = text.replace(old1, new1); print("CSS body OK")

# 2. JS: fix dim condition to exclude ancestors AND descendants of activeNoteContainer.
#    Old logic: s !== active  (breaks when parent is clicked — its children become dim)
#    New logic: s is unrelated — not active, not an ancestor, not a descendant
old2 = "            var dim=(s!==activeNoteContainer);"
new2 = "            var dim=(s!==activeNoteContainer)&&!activeNoteContainer.contains(s)&&!s.contains(activeNoteContainer);"
c2 = text.count(old2); assert c2 == 1, f"JS dim: {c2}"; text = text.replace(old2, new2); print("JS dim OK")

with open(path, 'w', encoding='utf-8') as f:
    f.write(text)
print("Done.")
