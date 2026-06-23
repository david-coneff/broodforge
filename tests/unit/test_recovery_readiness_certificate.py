"""
test_recovery_readiness_certificate.py — Tests for Phase 1.I (AD-059):
  _recovery_readiness_certificate.py  — certificate composer + assembler
  html_package_manifest.py            — build_recovery_readiness_certificate_html (AD-051 twin)
  drift.py::compute_drift             — now_fn clock-injection parameter
  history/index.py::build_index       — manifest_hash/graph_hash recording
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import _recovery_readiness_certificate as _rrc
import html_package_manifest as _hpm
from dependencies import build_graph
from drift import compute_drift
from readiness import score_graph

from history.index import build_index

_NOW_ISO = "2026-06-08T12:00:00+00:00"
_NOW = datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc)


def _now_fn():
    return _NOW_ISO


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _manifest(cell_id="pve01-cell"):
    return {
        "schema_version": "1.0",
        "cell_id": cell_id,
        "assessment_tier": 2,
        "collected_at": "2026-06-01T00:00:00Z",
        "host": {
            "hostname": "pve01",
            "proxmox_version": "8.2",
            "kernel_version": "6.8.0",
        },
        "storage": {
            "zfs_pools": [
                {"name": "rpool", "topology": "mirror", "total_gb": 1000,
                 "free_gb": 500, "state": "ONLINE", "devices": ["sda", "sdb"]},
            ],
            "pve_storage": [],
        },
        "network": {"bridges": []},
        "vms": [],
        "containers": [],
        "backup_inventory": {},
    }


def _graph_dict(manifest):
    return build_graph(manifest).to_dict()


def _readiness_dict(manifest):
    g = build_graph(manifest)
    return score_graph(g, manifest).to_dict()


def _drift_summary():
    m1 = _manifest()
    m2 = _manifest()
    m2["host"]["kernel_version"] = "6.8.1"
    return compute_drift(m1, m2, "snap_a", "snap_b", now_fn=_now_fn)


def _drill(outcome="success", with_timings=True):
    rec = {
        "drill_id": "pve01-cell_2026-06-01_00_00_00",
        "started_at": "2026-06-01T00:00:00+00:00",
        "completed_at": "2026-06-01T02:00:00+00:00",
        "playbook_generated_at": "2026-05-30T00:00:00+00:00",
        "outcome": outcome,
        "total_estimated_minutes": 120,
        "total_actual_minutes": 110,
        "wave_timings": [],
        "gaps_found": ["Bridge vmbr1 missing"],
        "gaps_remediated": [],
        "notes": None,
    }
    if with_timings:
        rec["wave_timings"] = [
            {"wave": 1, "name": "Host", "estimated_minutes": 30, "actual_minutes": 25, "completed": True},
            {"wave": 2, "name": "Storage", "estimated_minutes": 40, "actual_minutes": 45, "completed": True},
            {"wave": 3, "name": "VMs", "estimated_minutes": 50, "actual_minutes": None, "completed": False},
        ]
    return rec


# ===========================================================================
# canonical_json / hash_dict
# ===========================================================================

class TestHashing:
    def test_canonical_json_sorts_keys(self):
        a = _rrc.canonical_json({"b": 1, "a": 2})
        b = _rrc.canonical_json({"a": 2, "b": 1})
        assert a == b

    def test_hash_dict_deterministic(self):
        d = {"x": [1, 2, 3], "y": {"z": "value"}}
        assert _rrc.hash_dict(d) == _rrc.hash_dict(d)

    def test_hash_dict_order_independent(self):
        assert _rrc.hash_dict({"a": 1, "b": 2}) == _rrc.hash_dict({"b": 2, "a": 1})

    def test_hash_dict_changes_with_content(self):
        assert _rrc.hash_dict({"a": 1}) != _rrc.hash_dict({"a": 2})

    def test_hash_dict_is_sha256_hex(self):
        h = _rrc.hash_dict({"a": 1})
        assert len(h) == 64
        int(h, 16)  # raises ValueError if not hex


# ===========================================================================
# summarize_readiness — the AD-059 correction
# ===========================================================================

class TestSummarizeReadiness:
    def test_carries_real_overall_score(self):
        manifest = _manifest()
        readiness = _readiness_dict(manifest)
        summary = _rrc.summarize_readiness(readiness)
        assert summary["overall_score"] == readiness["overall_score"]
        assert summary["overall_score_reason"] == readiness["overall_score_reason"]

    def test_does_not_invent_rrs_acs_dcs_crs_oss_keys(self):
        manifest = _manifest()
        readiness = _readiness_dict(manifest)
        summary = _rrc.summarize_readiness(readiness)
        for fake_key in ("RRS", "ACS", "DCS", "CRS", "OSS",
                         "rrs", "acs", "dcs", "crs", "oss"):
            assert fake_key not in summary
        # The correction note legitimately *mentions* the fictional abbreviations
        # while explaining they have no backing computation — but no top-level
        # field besides "note" should carry that text.
        non_note = {k: v for k, v in summary.items() if k != "note"}
        assert "RRS" not in json.dumps(non_note)

    def test_component_score_counts_sum_to_component_count(self):
        manifest = _manifest()
        readiness = _readiness_dict(manifest)
        summary = _rrc.summarize_readiness(readiness)
        assert sum(summary["component_score_counts"].values()) == summary["component_count"]

    def test_includes_correction_note(self):
        summary = _rrc.summarize_readiness(_readiness_dict(_manifest()))
        assert "readiness.py" in summary["note"]
        assert "five" in summary["note"].lower() or "RRS" in summary["note"]


# ===========================================================================
# summarize_drift
# ===========================================================================

class TestSummarizeDrift:
    def test_unavailable_when_none(self):
        summary = _rrc.summarize_drift(None)
        assert summary["available"] is False
        assert summary["diff_count"] == 0

    def test_available_summarizes_real_drift(self):
        drift = _drift_summary()
        summary = _rrc.summarize_drift(drift)
        assert summary["available"] is True
        assert summary["drift_severity"] == drift["drift_severity"]
        assert summary["diff_count"] == len(drift["diffs"])

    def test_does_not_include_full_diff_list(self):
        summary = _rrc.summarize_drift(_drift_summary())
        assert "diffs" not in summary

    def test_severity_counts_sum_to_diff_count(self):
        summary = _rrc.summarize_drift(_drift_summary())
        assert sum(summary["diff_severity_counts"].values()) == summary["diff_count"]


# ===========================================================================
# summarize_drill
# ===========================================================================

class TestSummarizeDrill:
    def test_unavailable_when_none(self):
        summary = _rrc.summarize_drill(None)
        assert summary["available"] is False
        assert summary["drill_id"] is None

    def test_available_summarizes_real_drill(self):
        drill = _drill()
        summary = _rrc.summarize_drill(drill)
        assert summary["available"] is True
        assert summary["drill_id"] == drill["drill_id"]
        assert summary["outcome"] == "success"

    def test_completed_waves_counted(self):
        summary = _rrc.summarize_drill(_drill())
        assert summary["completed_waves"] == 2
        assert summary["total_waves"] == 3

    def test_accuracy_pct_computed_from_estimate_vs_actual(self):
        summary = _rrc.summarize_drill(_drill())
        # est=120, act=110 -> 100*(1 - 10/120) ~= 91.7
        assert summary["accuracy_pct"] == round(100.0 * (1.0 - abs(110 - 120) / 120), 1)

    def test_accuracy_pct_none_when_missing_data(self):
        drill = _drill()
        drill["total_actual_minutes"] = None
        summary = _rrc.summarize_drill(drill)
        assert summary["accuracy_pct"] is None


# ===========================================================================
# build_recovery_readiness_certificate — composition
# ===========================================================================

class TestBuildCertificate:
    def _build(self, **overrides):
        manifest = overrides.pop("manifest", _manifest())
        graph = overrides.pop("graph", _graph_dict(manifest))
        readiness = overrides.pop("readiness", _readiness_dict(manifest))
        drift = overrides.pop("drift", _drift_summary())
        drill = overrides.pop("drill", _drill())
        return _rrc.build_recovery_readiness_certificate(
            manifest=manifest, graph=graph, readiness_report=readiness,
            drift_summary=drift, latest_drill=drill, now_fn=_now_fn, **overrides
        )

    def test_returns_dict_with_expected_top_level_keys(self):
        cert = self._build()
        for key in ("schema_version", "certificate_id", "generated_at", "cell_id",
                    "manifest_hash", "graph_hash", "readiness", "drift", "latest_drill", "notes"):
            assert key in cert

    def test_uses_injected_clock(self):
        cert = self._build()
        assert cert["generated_at"] == _NOW_ISO

    def test_real_clock_fallback(self):
        manifest = _manifest()
        cert = _rrc.build_recovery_readiness_certificate(
            manifest=manifest, graph=_graph_dict(manifest),
            readiness_report=_readiness_dict(manifest),
        )
        # ISO-8601 timestamp parses without error
        datetime.fromisoformat(cert["generated_at"])

    def test_carries_cell_id_from_manifest(self):
        cert = self._build(manifest=_manifest(cell_id="other-cell"))
        assert cert["cell_id"] == "other-cell"

    def test_manifest_hash_matches_hash_dict(self):
        manifest = _manifest()
        cert = self._build(manifest=manifest)
        assert cert["manifest_hash"] == _rrc.hash_dict(manifest)

    def test_graph_hash_matches_hash_dict(self):
        manifest = _manifest()
        graph = _graph_dict(manifest)
        cert = self._build(manifest=manifest, graph=graph)
        assert cert["graph_hash"] == _rrc.hash_dict(graph)

    def test_hash_determinism_same_inputs_same_hash(self):
        manifest = _manifest()
        graph = _graph_dict(manifest)
        readiness = _readiness_dict(manifest)
        cert1 = _rrc.build_recovery_readiness_certificate(
            manifest=manifest, graph=graph, readiness_report=readiness, now_fn=_now_fn)
        cert2 = _rrc.build_recovery_readiness_certificate(
            manifest=manifest, graph=graph, readiness_report=readiness, now_fn=_now_fn)
        assert cert1["manifest_hash"] == cert2["manifest_hash"]
        assert cert1["graph_hash"] == cert2["graph_hash"]

    def test_hash_changes_with_manifest_content(self):
        m1 = _manifest()
        m2 = _manifest()
        m2["host"]["kernel_version"] = "different"
        cert1 = self._build(manifest=m1, graph=_graph_dict(m1), readiness=_readiness_dict(m1))
        cert2 = self._build(manifest=m2, graph=_graph_dict(m2), readiness=_readiness_dict(m2))
        assert cert1["manifest_hash"] != cert2["manifest_hash"]

    def test_correction_honored_no_invented_score_keys(self):
        cert = self._build()
        as_json = json.dumps(cert)
        for fake_key in ('"RRS"', '"ACS"', '"DCS"', '"CRS"', '"OSS"'):
            assert fake_key not in as_json
        assert cert["readiness"]["overall_score"] in (
            "GREEN", "YELLOW", "ORANGE", "RED", "BLOCKED", "UNKNOWN"
        )

    def test_handles_missing_drift_and_drill(self):
        cert = self._build(drift=None, drill=None)
        assert cert["drift"]["available"] is False
        assert cert["latest_drill"]["available"] is False

    def test_certificate_id_contains_cell_id(self):
        cert = self._build(manifest=_manifest(cell_id="zz-cell"),
                           graph=_graph_dict(_manifest(cell_id="zz-cell")),
                           readiness=_readiness_dict(_manifest(cell_id="zz-cell")))
        assert "zz-cell" in cert["certificate_id"]

    def test_json_serializable(self):
        cert = self._build()
        json.dumps(cert)  # raises if not serializable


# ===========================================================================
# build_recovery_readiness_certificate_html
# ===========================================================================

class TestCertificateHtml:
    def _cert(self):
        manifest = _manifest()
        return _rrc.build_recovery_readiness_certificate(
            manifest=manifest, graph=_graph_dict(manifest),
            readiness_report=_readiness_dict(manifest),
            drift_summary=_drift_summary(), latest_drill=_drill(), now_fn=_now_fn,
        )

    def test_returns_html_string(self):
        html = _hpm.build_recovery_readiness_certificate_html(self._cert())
        assert isinstance(html, str)
        assert html.startswith("<!DOCTYPE html>")

    def test_contains_cell_id_and_hashes(self):
        cert = self._cert()
        html = _hpm.build_recovery_readiness_certificate_html(cert)
        assert cert["cell_id"] in html
        assert cert["manifest_hash"] in html
        assert cert["graph_hash"] in html

    def test_contains_overall_score(self):
        cert = self._cert()
        html = _hpm.build_recovery_readiness_certificate_html(cert)
        assert cert["readiness"]["overall_score"] in html

    def test_contains_correction_note(self):
        cert = self._cert()
        html = _hpm.build_recovery_readiness_certificate_html(cert)
        assert "readiness.py" in html

    def test_contains_drill_outcome(self):
        cert = self._cert()
        html = _hpm.build_recovery_readiness_certificate_html(cert)
        assert "success" in html

    def test_no_drill_renders_warning(self):
        manifest = _manifest()
        cert = _rrc.build_recovery_readiness_certificate(
            manifest=manifest, graph=_graph_dict(manifest),
            readiness_report=_readiness_dict(manifest),
            drift_summary=None, latest_drill=None, now_fn=_now_fn,
        )
        html = _hpm.build_recovery_readiness_certificate_html(cert)
        assert "No reconstruction drill" in html

    def test_does_not_render_invented_score_labels(self):
        html = _hpm.build_recovery_readiness_certificate_html(self._cert())
        for fake_label in ("RRS:", "ACS:", "DCS:", "CRS:", "OSS:"):
            assert fake_label not in html


# ===========================================================================
# compute_drift — now_fn clock injection (AD-059 fix-while-touching)
# ===========================================================================

class TestComputeDriftNowFn:
    def test_injected_clock_used_for_generated_at(self):
        m1, m2 = _manifest(), _manifest()
        m2["host"]["kernel_version"] = "x"
        result = compute_drift(m1, m2, "a", "b", now_fn=_now_fn)
        assert result["generated_at"] == _NOW_ISO

    def test_real_clock_fallback_when_no_now_fn(self):
        m1, m2 = _manifest(), _manifest()
        m2["host"]["kernel_version"] = "x"
        result = compute_drift(m1, m2, "a", "b")
        datetime.fromisoformat(result["generated_at"])

    def test_deterministic_under_injection(self):
        m1, m2 = _manifest(), _manifest()
        m2["host"]["kernel_version"] = "x"
        r1 = compute_drift(m1, m2, "a", "b", now_fn=_now_fn)
        r2 = compute_drift(m1, m2, "a", "b", now_fn=_now_fn)
        assert r1["generated_at"] == r2["generated_at"] == _NOW_ISO


# ===========================================================================
# history/index.py::build_index — manifest_hash/graph_hash recording
# ===========================================================================

class TestBuildIndexHashes:
    def _write_snapshot(self, root: Path, snap_id: str, manifest: dict):
        snap_dir = root / "history" / "snapshots" / snap_id
        snap_dir.mkdir(parents=True, exist_ok=True)
        (snap_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def test_entries_carry_manifest_and_graph_hash(self, tmp_path):
        manifest = _manifest()
        manifest["collected_at"] = "2026-06-01T00:00:00Z"
        self._write_snapshot(tmp_path, "snap_a", manifest)

        index = build_index(tmp_path)
        assert len(index["snapshots"]) == 1
        entry = index["snapshots"][0]
        assert entry["manifest_hash"] == _rrc.hash_dict(manifest)
        assert entry["graph_hash"] == _rrc.hash_dict(_graph_dict(manifest))

    def test_existing_keys_preserved(self, tmp_path):
        manifest = _manifest()
        manifest["collected_at"] = "2026-06-01T00:00:00Z"
        self._write_snapshot(tmp_path, "snap_a", manifest)

        entry = build_index(tmp_path)["snapshots"][0]
        for key in ("id", "tier", "collected_at", "archive_path",
                    "manifest_path", "template_version", "doc_generation_ids", "notes"):
            assert key in entry

    def test_hash_changes_when_manifest_changes(self, tmp_path):
        m1 = _manifest()
        m1["collected_at"] = "2026-06-01T00:00:00Z"
        self._write_snapshot(tmp_path, "snap_a", m1)

        m2 = _manifest()
        m2["collected_at"] = "2026-06-02T00:00:00Z"
        m2["host"]["kernel_version"] = "different"
        self._write_snapshot(tmp_path, "snap_b", m2)

        entries = {e["id"]: e for e in build_index(tmp_path)["snapshots"]}
        assert entries["snap_a"]["manifest_hash"] != entries["snap_b"]["manifest_hash"]

    def test_cell_id_carried_through(self, tmp_path):
        manifest = _manifest(cell_id="my-test-cell")
        manifest["collected_at"] = "2026-06-01T00:00:00Z"
        self._write_snapshot(tmp_path, "snap_a", manifest)

        index = build_index(tmp_path)
        assert index.get("cell_id") == "my-test-cell"
