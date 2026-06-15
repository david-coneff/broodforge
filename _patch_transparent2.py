path = r'proxmox-bootstrap\md_to_html.py'
with open(path, 'r', encoding='utf-8') as f:
    text = f.read()

old = "  .nts-section.nts-dim>.nts-body>.nts-ch>button{opacity:0!important;pointer-events:none}"
new = (
    "  .nts-section.nts-dim>.nts-body>.nts-ch>button{opacity:0!important;pointer-events:none}\n"
    "  .nts-section.nts-dim>.nts-body{background:transparent!important}"
)
c = text.count(old); assert c == 1, f"count:{c}"; text = text.replace(old, new); print("OK")

with open(path, 'w', encoding='utf-8') as f:
    f.write(text)
print("Done.")
