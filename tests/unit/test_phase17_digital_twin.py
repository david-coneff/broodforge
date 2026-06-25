"""
test_phase17_digital_twin.py — Tests for Phase 17: Digital Twin Foundation.

Covers:
  17.1  data-model/cell-identity-schema.json
  17.2  TwinPaths — twin directory layout
  17.3  TwinStateWriter — write/read state, write_all
  17.4  StalenessManifest — staleness computation
  17.5  twin_consistency_checker.py
        readiness.py — _score_twin_consistency
  17.6  build_cell_identity from forge manifest
"""

import json
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

import twin_consistency_checker as _tcc
import twin_state_writer as _tw

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _forge_manifest():
    return {
        "schema_version": "1.0",
        "cell_id": "pve01-cell",
        "generated_at": "2026-06-01T12:00:00+00:00",
        "setup_mode": "autonomous",
        "host_identity": {
            "hostname": "pve01",
            "domain": "home.example.com",
            "fqdn": "pve01.home.example.com",
            "cell_id": "pve01-cell",
            "timezone": "America/Denver",
        },
        "network_topology": {
            "profile": "wan",
            "management_cidr": "192.168.1.0/24",
            "gateway": "192.168.1.1",
            "wan_config": {
                "headscale_url": "https://pve01.home.example.com:8080",
            },
        },
    }

def _state_doc(category="hardware", cell_id="pve01-cell"):
    return {
        "schema_version": "1.0",
        "cell_id": cell_id,
        "collected_at": "2026-06-01T12:00:00+00:00",
        "node_hostname": "pve01",
    }


# ===========================================================================
# 17.1 — cell-identity-schema.json
# ===========================================================================

class TestCellIdentitySchema:
    def _schema(self):
        path = os.path.join(_ROOT, "data-model", "cell-identity-schema.json")
        with open(path) as f:
            return json.load(f)

    def test_schema_loads(self):
        s = self._schema()
        assert s["title"] == "Cell Identity"

    def test_required_fields(self):
        s = self._schema()
        assert "cell_id" in s["required"]
        assert "registered_at" in s["required"]
        assert "host_identity" in s["required"]

    def test_valid_minimal(self):
        try:
            import jsonschema
        except ImportError:
            import pytest; pytest.skip("jsonschema not installed")  # noqa: I001
        s = self._schema()
        jsonschema.validate({
            "schema_version": "1.0",
            "cell_id": "pve01-cell",
            "registered_at": "2026-06-01T12:00:00+00:00",
            "host_identity": {
                "hostname": "pve01",
                "fqdn": "pve01.home.example.com",
            },
        }, s)

    def test_capabilities_array(self):
        s = self._schema()
        assert s["properties"]["capabilities"]["type"] == "array"

    def test_federation_trust_object(self):
        s = self._schema()
        assert "federation_trust" in s["properties"]


# ===========================================================================
# 17.2 — TwinPaths
# ===========================================================================

class TestTwinPaths:
    def test_cell_dir(self, tmp_path):
        p = _tw.TwinPaths(str(tmp_path), "test-cell")
        assert "test-cell" in str(p.cell_dir)

    def test_state_dir_is_child_of_cell(self, tmp_path):
        p = _tw.TwinPaths(str(tmp_path), "test-cell")
        assert p.state_dir.parent == p.cell_dir

    def test_identity_path(self, tmp_path):
        p = _tw.TwinPaths(str(tmp_path), "test-cell")
        assert p.identity_path.name == "identity.json"

    def test_staleness_path(self, tmp_path):
        p = _tw.TwinPaths(str(tmp_path), "test-cell")
        assert p.staleness_path.name == "staleness.json"

    def test_state_path_per_category(self, tmp_path):
        p = _tw.TwinPaths(str(tmp_path), "test-cell")
        path = p.state_path("hardware")
        assert path.name == "hardware.json"

    def test_all_state_paths_returns_all_categories(self, tmp_path):
        p = _tw.TwinPaths(str(tmp_path), "test-cell")
        all_paths = p.all_state_paths()
        for cat in _tw.ALL_STATE_CATEGORIES:
            assert cat in all_paths


# ===========================================================================
# 17.3 — TwinStateWriter
# ===========================================================================

class TestTwinStateWriter:
    def _writer(self, tmp_path):
        return _tw.TwinStateWriter(str(tmp_path / "twin"), "test-cell")

    def test_write_state_creates_file(self, tmp_path):
        w = self._writer(tmp_path)
        path = w.write_state("hardware", _state_doc("hardware"))
        assert path.exists()

    def test_write_state_content_correct(self, tmp_path):
        w = self._writer(tmp_path)
        doc = _state_doc("hardware", cell_id="test-cell")
        w.write_state("hardware", doc)
        loaded = json.loads(w.paths.state_path("hardware").read_text())
        assert loaded["cell_id"] == "test-cell"

    def test_read_state_returns_dict(self, tmp_path):
        w = self._writer(tmp_path)
        doc = _state_doc("cluster")
        w.write_state("cluster", doc)
        result = w.read_state("cluster")
        assert result is not None
        assert result["schema_version"] == "1.0"

    def test_read_state_missing_returns_none(self, tmp_path):
        w = self._writer(tmp_path)
        assert w.read_state("nonexistent") is None

    def test_write_all_writes_multiple(self, tmp_path):
        w = self._writer(tmp_path)
        state_map = {
            "hardware": _state_doc("hardware"),
            "cluster":  _state_doc("cluster"),
        }
        paths = w.write_all(state_map)
        assert "hardware" in paths
        assert paths["hardware"].exists()
        assert paths["cluster"].exists()

    def test_write_cell_identity(self, tmp_path):
        w = self._writer(tmp_path)
        identity = _tw.build_cell_identity(_forge_manifest())
        path = w.write_cell_identity(identity)
        assert path.exists()
        loaded = json.loads(path.read_text())
        assert loaded["cell_id"] == "pve01-cell"

    def test_read_cell_identity_returns_dict(self, tmp_path):
        w = self._writer(tmp_path)
        identity = _tw.build_cell_identity(_forge_manifest())
        w.write_cell_identity(identity)
        result = w.read_cell_identity()
        assert result is not None
        assert result["cell_id"] == "pve01-cell"

    def test_read_cell_identity_missing_returns_none(self, tmp_path):
        w = self._writer(tmp_path)
        assert w.read_cell_identity() is None


# ===========================================================================
# 17.4 — StalenessManifest
# ===========================================================================

class TestStalenessManifest:
    def _writer(self, tmp_path):
        return _tw.TwinStateWriter(str(tmp_path / "twin"), "test-cell")

    def test_update_staleness_no_files(self, tmp_path):
        w = self._writer(tmp_path)
        manifest = w.update_staleness()
        assert isinstance(manifest, _tw.StalenessManifest)
        assert manifest.entries == []

    def test_update_staleness_with_file(self, tmp_path):
        w = self._writer(tmp_path)
        w.write_state("hardware", _state_doc("hardware"))
        manifest = w.update_staleness()
        assert any(e.category == "hardware" for e in manifest.entries)

    def test_fresh_state_not_stale(self, tmp_path):
        w = self._writer(tmp_path)
        w.write_state("hardware", _state_doc("hardware"))
        manifest = w.update_staleness()
        entry = manifest.get_entry("hardware")
        assert entry is not None
        assert entry.is_stale is False

    def test_stale_categories_empty_when_fresh(self, tmp_path):
        w = self._writer(tmp_path)
        w.write_state("hardware", _state_doc("hardware"))
        manifest = w.update_staleness()
        assert manifest.stale_categories() == []

    def test_missing_categories_includes_absent(self, tmp_path):
        w = self._writer(tmp_path)
        w.write_state("hardware", _state_doc("hardware"))
        manifest = w.update_staleness()
        missing = manifest.missing_categories()
        # All categories except hardware should be missing
        assert "hardware" not in missing
        assert "cluster" in missing

    def test_sha256_set_on_entry(self, tmp_path):
        w = self._writer(tmp_path)
        w.write_state("platform", _state_doc("platform"))
        manifest = w.update_staleness()
        entry = manifest.get_entry("platform")
        assert entry is not None
        assert entry.sha256 and entry.sha256.startswith("sha256:")

    def test_staleness_json_written(self, tmp_path):
        w = self._writer(tmp_path)
        w.write_state("hardware", _state_doc("hardware"))
        w.update_staleness()
        assert w.paths.staleness_path.exists()

    def test_read_staleness_after_write(self, tmp_path):
        w = self._writer(tmp_path)
        w.write_state("hardware", _state_doc("hardware"))
        w.update_staleness()
        manifest = _tw.read_staleness(w.paths)
        assert manifest is not None
        assert manifest.cell_id == "test-cell"

    def test_all_state_categories_constant(self):
        assert "hardware" in _tw.ALL_STATE_CATEGORIES
        assert "cluster" in _tw.ALL_STATE_CATEGORIES
        assert "observability" in _tw.ALL_STATE_CATEGORIES
        assert len(_tw.ALL_STATE_CATEGORIES) == 7


# ===========================================================================
# 17.6 — build_cell_identity
# ===========================================================================

class TestBuildCellIdentity:
    def test_returns_dict(self):
        identity = _tw.build_cell_identity(_forge_manifest())
        assert isinstance(identity, dict)

    def test_cell_id_correct(self):
        identity = _tw.build_cell_identity(_forge_manifest())
        assert identity["cell_id"] == "pve01-cell"

    def test_hostname_correct(self):
        identity = _tw.build_cell_identity(_forge_manifest())
        assert identity["host_identity"]["hostname"] == "pve01"

    def test_network_profile_wan(self):
        identity = _tw.build_cell_identity(_forge_manifest())
        assert identity["network_profile"] == "wan"

    def test_headscale_url_set(self):
        identity = _tw.build_cell_identity(_forge_manifest())
        assert "pve01.home.example.com" in (identity.get("headscale_url") or "")

    def test_timezone_in_host_identity(self):
        identity = _tw.build_cell_identity(_forge_manifest())
        assert identity["host_identity"]["timezone"] == "America/Denver"

    def test_twin_state_paths_populated(self):
        identity = _tw.build_cell_identity(_forge_manifest())
        paths = identity.get("twin_state_paths") or {}
        assert "hardware" in paths
        assert "pve01-cell" in paths["hardware"]

    def test_schema_version(self):
        identity = _tw.build_cell_identity(_forge_manifest())
        assert identity["schema_version"] == "1.0"


# ===========================================================================
# 17.5 — twin_consistency_checker
# ===========================================================================

class TestTwinConsistencyChecker:
    def _setup(self, tmp_path):
        twin_root = str(tmp_path / "twin")
        writer = _tw.TwinStateWriter(twin_root, "pve01-cell")
        return twin_root, writer

    def test_empty_twin_missing_warnings(self, tmp_path):
        twin_root, writer = self._setup(tmp_path)
        writer.paths.cell_dir.mkdir(parents=True, exist_ok=True)
        report = _tcc.check_twin_consistency(twin_root, "pve01-cell")
        missing = [f for f in report.findings if f.check_type == "MISSING"]
        assert len(missing) >= len(_tw.ALL_STATE_CATEGORIES)

    def test_consistent_twin_no_errors(self, tmp_path):
        twin_root, writer = self._setup(tmp_path)
        # Write identity and all state categories
        identity = _tw.build_cell_identity(_forge_manifest())
        writer.write_cell_identity(identity)
        for cat in _tw.ALL_STATE_CATEGORIES:
            writer.write_state(cat, _state_doc(cat))
        report = _tcc.check_twin_consistency(twin_root, "pve01-cell")
        assert _tcc.is_twin_consistent(report)
        assert report.errors == []

    def test_cell_id_conflict_detected(self, tmp_path):
        twin_root, writer = self._setup(tmp_path)
        # Write state with wrong cell_id
        bad_doc = _state_doc("hardware", cell_id="wrong-cell")
        writer.write_state("hardware", bad_doc)
        report = _tcc.check_twin_consistency(twin_root, "pve01-cell")
        conflicts = [f for f in report.findings if f.check_type == "CELL_ID_CONFLICT"]
        assert conflicts

    def test_missing_identity_warning(self, tmp_path):
        twin_root, writer = self._setup(tmp_path)
        writer.paths.cell_dir.mkdir(parents=True, exist_ok=True)
        report = _tcc.check_twin_consistency(twin_root, "pve01-cell")
        identity_findings = [f for f in report.findings if f.category == "identity"]
        assert any(f.check_type == "MISSING" for f in identity_findings)

    def test_is_twin_consistent_false_with_errors(self, tmp_path):
        twin_root, writer = self._setup(tmp_path)
        bad_doc = _state_doc("hardware", cell_id="wrong-cell")
        writer.write_state("hardware", bad_doc)
        report = _tcc.check_twin_consistency(twin_root, "pve01-cell")
        assert not _tcc.is_twin_consistent(report)

    def test_summarise_consistency(self, tmp_path):
        twin_root, writer = self._setup(tmp_path)
        writer.paths.cell_dir.mkdir(parents=True, exist_ok=True)
        report = _tcc.check_twin_consistency(twin_root, "pve01-cell")
        summary = _tcc.summarise_consistency(report)
        assert "pve01-cell" in summary

    def test_consistency_report_checked_at_set(self, tmp_path):
        twin_root, writer = self._setup(tmp_path)
        writer.paths.cell_dir.mkdir(parents=True, exist_ok=True)
        report = _tcc.check_twin_consistency(twin_root, "pve01-cell")
        assert report.checked_at


# ===========================================================================
# 17.5 — readiness scoring
# ===========================================================================

from readiness import _score_twin_consistency


class TestScoreTwinConsistency:
    def test_no_twin_no_root_no_gap(self):
        # No twin_consistency and no twin_root → no gap (twin not configured yet)
        gaps = _score_twin_consistency({})
        assert not gaps

    def test_twin_root_without_consistency_yellow(self):
        manifest = {"twin_root": "twin/"}
        gaps = _score_twin_consistency(manifest)
        assert any(g.gap_type == "MISSING_TWIN_CONSISTENCY" for g in gaps)

    def test_consistent_twin_no_gaps(self):
        manifest = {
            "twin_consistency": {
                "errors": [],
                "warnings": [],
            }
        }
        gaps = _score_twin_consistency(manifest)
        assert not gaps

    def test_cell_id_conflict_orange(self):
        manifest = {
            "twin_consistency": {
                "errors": [
                    {"category": "hardware", "check_type": "CELL_ID_CONFLICT",
                     "message": "conflict"},
                ],
                "warnings": [],
            }
        }
        gaps = _score_twin_consistency(manifest)
        assert any(g.gap_type == "TWIN_CELL_ID_CONFLICT" and g.severity == "ORANGE" for g in gaps)

    def test_stale_state_yellow(self):
        manifest = {
            "twin_consistency": {
                "errors": [],
                "warnings": [
                    {"category": "hardware", "check_type": "STALE", "message": "stale"},
                ],
            }
        }
        gaps = _score_twin_consistency(manifest)
        assert any(g.gap_type == "TWIN_STATE_STALE" and g.severity == "YELLOW" for g in gaps)
