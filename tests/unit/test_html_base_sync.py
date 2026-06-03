#!/usr/bin/env python3
"""Assert that proxmox-bootstrap/html_base.py and doc-gen/renderers/html_base.py
are identical when comment lines (lines starting with #) are excluded.

Catches accidental drift between the two copies of the shared module."""

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
BOOTSTRAP_COPY  = REPO_ROOT / "proxmox-bootstrap" / "html_base.py"
DOC_GEN_COPY    = REPO_ROOT / "doc-gen" / "renderers" / "html_base.py"


def _non_comment_lines(path: Path) -> list[str]:
    return [
        line.rstrip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    ]


class TestHtmlBaseSync(unittest.TestCase):
    def test_both_files_exist(self):
        self.assertTrue(BOOTSTRAP_COPY.exists(),  f"Missing: {BOOTSTRAP_COPY}")
        self.assertTrue(DOC_GEN_COPY.exists(),    f"Missing: {DOC_GEN_COPY}")

    def test_files_identical_excluding_comments(self):
        bootstrap_lines = _non_comment_lines(BOOTSTRAP_COPY)
        docgen_lines    = _non_comment_lines(DOC_GEN_COPY)
        self.assertEqual(
            bootstrap_lines, docgen_lines,
            "proxmox-bootstrap/html_base.py and doc-gen/renderers/html_base.py "
            "have diverged (excluding comment lines). Edit both files together.",
        )


if __name__ == "__main__":
    unittest.main()
