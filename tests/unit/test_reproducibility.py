"""
Reproducibility test: same manifest → identical outputs.

Tests the HTML renderers (primary output format) for determinism.
Same manifest must produce byte-identical HTML on every run.

NOTE: ODS/ODT renderers (workbook.py, runbook.py) are deprecated.
      The primary output format is HTML via html_bootstrap.py,
      html_recovery_runbook.py, and html_operational_report.py.
"""

import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent

TIER1_FIXTURE = ROOT / "tests" / "fixtures" / "tier1" / "manifest.json"

META_FIXED = {
    "generated_at":     "2026-01-01T00:00:00Z",
    "collected_at":     "2026-01-01T00:00:00Z",
    "generated_at_display": "2026-01-01 00:00:00 UTC",
    "tier":             1,
    "template_version": "bootstrap-v1.0",
    "field_counts":     {"AUTO": 10, "DERIVED": 5, "HUMAN": 3, "UNRESOLVED": 2},
    "unresolved_fields": [],
    "human_fields":     [],
    "drift":            None,
}


def _md5(data: str) -> str:
    return hashlib.md5(data.encode()).hexdigest()  # noqa: S324


class TestBootstrapReproducibility(unittest.TestCase):
    """Bootstrap HTML doc-gen must be deterministic: same manifest → same string."""

    def _generate_workbook(self, manifest: dict) -> str:
        from html_bootstrap import build_bootstrap_workbook_html
        return build_bootstrap_workbook_html(manifest, META_FIXED)

    def _generate_runbook(self, manifest: dict) -> str:
        from html_bootstrap import build_bootstrap_runbook_html
        return build_bootstrap_runbook_html(manifest, META_FIXED)

    def test_workbook_html_identical(self):
        manifest = json.loads(TIER1_FIXTURE.read_text())
        html1 = self._generate_workbook(manifest)
        html2 = self._generate_workbook(manifest)
        self.assertEqual(
            _md5(html1), _md5(html2),
            "Bootstrap Workbook HTML output is not deterministic"
        )

    def test_runbook_html_identical(self):
        manifest = json.loads(TIER1_FIXTURE.read_text())
        html1 = self._generate_runbook(manifest)
        html2 = self._generate_runbook(manifest)
        self.assertEqual(
            _md5(html1), _md5(html2),
            "Bootstrap Runbook HTML output is not deterministic"
        )

    def test_different_manifests_differ(self):
        """Sanity check: different manifests produce different output."""
        m1 = json.loads(TIER1_FIXTURE.read_text())
        m2 = json.loads(TIER1_FIXTURE.read_text())
        # Change a field the workbook actually renders (cell_id appears in the page)
        m2["cell_id"] = "different-test-cell"
        html1 = self._generate_workbook(m1)
        html2 = self._generate_workbook(m2)
        self.assertNotEqual(
            _md5(html1), _md5(html2),
            "Different manifests should produce different HTML output"
        )


class TestRecoveryRunbookReproducibility(unittest.TestCase):
    """Recovery runbook HTML must be deterministic."""

    def _generate(self, manifest: dict) -> str:
        from dependencies import build_graph
        from html_recovery_runbook import build_recovery_runbook_html
        from readiness import score_graph
        graph    = build_graph(manifest)
        readiness = score_graph(graph, manifest)
        return build_recovery_runbook_html(manifest, graph, readiness, META_FIXED)

    def test_recovery_runbook_html_identical(self):
        manifest = json.loads(TIER1_FIXTURE.read_text())
        html1 = self._generate(manifest)
        html2 = self._generate(manifest)
        self.assertEqual(
            _md5(html1), _md5(html2),
            "Recovery Runbook HTML output is not deterministic"
        )

    def test_different_manifests_differ(self):
        m1 = json.loads(TIER1_FIXTURE.read_text())
        m2 = json.loads(TIER1_FIXTURE.read_text())
        m2.setdefault("host", {})["hostname"] = "alt-host"
        html1 = self._generate(m1)
        html2 = self._generate(m2)
        self.assertNotEqual(
            _md5(html1), _md5(html2),
            "Different manifests should produce different recovery runbook HTML"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
