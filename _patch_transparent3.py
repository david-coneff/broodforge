path = r'proxmox-bootstrap\md_to_html.py'
with open(path, 'r', encoding='utf-8') as f:
    text = f.read()

# Replace the body background-only rule with visibility:hidden too,
# and add a restoration rule so nested active sections show through.
old = "  .nts-section.nts-dim>.nts-body{background:transparent!important}"
new = (
    "  .nts-section.nts-dim>.nts-body{background:transparent!important;visibility:hidden}\n"
    "  .nts-section:not(.nts-dim){visibility:visible}"
)
c = text.count(old); assert c == 1, f"count:{c}"; text = text.replace(old, new); print("OK")

with open(path, 'w', encoding='utf-8') as f:
    f.write(text)
print("Done.")
