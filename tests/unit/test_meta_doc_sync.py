#!/usr/bin/env python3
"""Assert that broodforge's own governing docs (ROADMAP, ARCHITECTURE) carry
the same Version/Date stamp in both their Markdown source and their hand-styled
HTML companion.

broodforge's product generates drift reports for the infrastructure it manages
(doc-gen/drift.py) — but its own meta-documentation has no equivalent check,
so a Markdown edit routinely lands without its HTML counterpart being touched
(observed: ROADMAP.html and docs/ARCHITECTURE.html both several days stale
relative to their .md sources as of 2026-06-07). This test is broodforge's
"trigger" for keeping its own docs honest: it fails the moment one half of a
pair is updated without the other, the same way test_html_base_sync.py catches
drift between the two copies of html_base.py."""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent

# (markdown source, HTML companion, human label)
DOC_PAIRS = [
    (REPO_ROOT / "ROADMAP.md", REPO_ROOT / "ROADMAP.html", "ROADMAP"),
    (REPO_ROOT / "ARCHITECTURE.md", REPO_ROOT / "docs" / "ARCHITECTURE.html", "ARCHITECTURE"),
]

# Matches "Last updated: 2026-06-07", "Date: 2026-05-31", "Updated: 2026-06-02"
# — the three label spellings actually in use across these docs.
_STAMP_RE = re.compile(r"(?:Last updated|Date|Updated)\s*:\s*(\d{4}-\d{2}-\d{2})", re.IGNORECASE)


def _first_stamp(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = _STAMP_RE.search(text)
    if not match:
        raise AssertionError(f"No 'Last updated:'/'Date:'/'Updated:' YYYY-MM-DD stamp found in {path}")
    return match.group(1)


class TestMetaDocSync(unittest.TestCase):
    def test_doc_pairs_exist(self):
        for md_path, html_path, _label in DOC_PAIRS:
            self.assertTrue(md_path.exists(), f"Missing: {md_path}")
            self.assertTrue(html_path.exists(), f"Missing: {html_path}")

    def test_stamps_match(self):
        for md_path, html_path, label in DOC_PAIRS:
            md_stamp = _first_stamp(md_path)
            html_stamp = _first_stamp(html_path)
            self.assertEqual(
                md_stamp, html_stamp,
                f"{label}: {md_path.name} is stamped {md_stamp} but "
                f"{html_path.relative_to(REPO_ROOT)} is stamped {html_stamp} — "
                f"they have drifted. Update both together (the .md is the "
                f"source of truth; carry its date/version stamp and the "
                f"substance of the change into the .html companion).",
            )


if __name__ == "__main__":
    unittest.main()
