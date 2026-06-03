"""
test_failure_package_analyzer.py — Failure package analyzer and hatchery receiver.

Covers:
  - FailureReport parsing from dict
  - analyze_failure_report(): phase-aware diagnostics, fix suggestions, regeneration
  - analyze_failure_package(): tar.gz bundle parsing
  - assemble_failure_package(): create bundle in memory
  - export_to_usb(): copy to mount point
  - FAILURE_SHELL_FUNCTIONS: shell code content
  - PHASE_CATALOGUE: completeness
  - hatchery_receiver: receive_failure_package, list_received_packages,
    analyze_all_unanalyzed, mark_analyzed
"""

import io
import json
import os
import sys
import tarfile
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "proxmox-bootstrap"))

import failure_package_analyzer as _fpa
import hatchery_receiver as _hr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _report_dict(**kwargs) -> dict:
    base = {
        "package_id":      "spawn-pve01-cell-broodling01-2026-06-01",
        "broodling_host":  "broodling01",
        "cell_id":         "pve01-cell",
        "failed_phase":    "phase-00-preflight",
        "error_type":      "disk_missing",
        "error_message":   "Disk /dev/sdc not found",
        "failed_at":       "2026-06-01T12:00:00Z",
        "completed_phases": [],
    }
    base.update(kwargs)
    return base


def _make_failure_package_bytes(report_dict: dict) -> bytes:
    """Create a minimal in-memory failure package tar.gz."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        raw = json.dumps(report_dict).encode()
        info = tarfile.TarInfo(name="failure-report.json")
        info.size = len(raw)
        tar.addfile(info, io.BytesIO(raw))
    return buf.getvalue()


# ===========================================================================
# FailureReport parsing
# ===========================================================================

class TestParseFailureReport:
    def test_basic_fields(self):
        r = _fpa.parse_failure_report(_report_dict())
        assert r.package_id == "spawn-pve01-cell-broodling01-2026-06-01"
        assert r.broodling_host == "broodling01"
        assert r.failed_phase == "phase-00-preflight"
        assert r.error_type == "disk_missing"

    def test_completed_phases(self):
        r = _fpa.parse_failure_report(_report_dict(completed_phases=["phase-00-preflight"]))
        assert "phase-00-preflight" in r.completed_phases

    def test_missing_error_type_inferred(self):
        d = _report_dict()
        del d["error_type"]
        d["error_message"] = "disk /dev/sdb not found"
        r = _fpa.parse_failure_report(d)
        assert r.error_type == "disk_missing"

    def test_infer_vmid_conflict(self):
        d = _report_dict(error_type=None, error_message="vmid 101 conflict detected")
        r = _fpa.parse_failure_report(d)
        assert r.error_type == "vmid_conflict"

    def test_infer_token_expired(self):
        d = _report_dict(error_type=None, error_message="join token expired")
        r = _fpa.parse_failure_report(d)
        assert r.error_type == "token_expired"

    def test_infer_fingerprint(self):
        d = _report_dict(error_type=None, error_message="fingerprint mismatch")
        r = _fpa.parse_failure_report(d)
        assert r.error_type == "join_fingerprint"


# ===========================================================================
# analyze_failure_report
# ===========================================================================

class TestAnalyzeFailureReport:
    def _analyze(self, **kwargs) -> _fpa.FailureDiagnosis:
        report = _fpa.parse_failure_report(_report_dict(**kwargs))
        return _fpa.analyze_failure_report(report)

    def test_returns_failure_diagnosis(self):
        d = self._analyze()
        assert isinstance(d, _fpa.FailureDiagnosis)

    def test_phase_description_set(self):
        d = self._analyze()
        assert "Hardware pre-flight" in d.phase_description

    def test_diagnosis_text(self):
        d = self._analyze(error_type="disk_missing")
        assert "disk" in d.diagnosis.lower()

    def test_fix_suggestions_not_empty(self):
        d = self._analyze(error_type="disk_missing")
        assert len(d.suggested_fixes) > 0

    def test_disk_missing_fix_suggests_lsblk(self):
        d = self._analyze(error_type="disk_missing")
        combined = " ".join(d.suggested_fixes)
        assert "lsblk" in combined

    def test_can_regenerate_disk_missing_false(self):
        d = self._analyze(error_type="disk_missing")
        assert d.can_regenerate is False

    def test_can_regenerate_vmid_conflict_true(self):
        d = self._analyze(failed_phase="phase-00-preflight", error_type="vmid_conflict")
        assert d.can_regenerate is True
        assert len(d.regeneration_steps) > 0

    def test_can_regenerate_stale_manifest(self):
        d = self._analyze(error_type="stale_manifest")
        assert d.can_regenerate is True

    def test_can_regenerate_token_expired(self):
        d = self._analyze(failed_phase="phase-04-k3s", error_type="token_expired")
        assert d.can_regenerate is True

    def test_completed_phases_preserved(self):
        d = self._analyze(
            failed_phase="phase-02-vms",
            completed_phases=["phase-00-preflight", "phase-00-host", "phase-01-proxmox"],
        )
        assert "phase-00-preflight" in d.completed_phases
        assert "phase-01-proxmox" in d.completed_phases

    def test_unknown_phase(self):
        d = self._analyze(failed_phase="phase-99-mystery", error_type="unknown")
        assert "mystery" in d.phase_description or "Unknown" in d.phase_description

    def test_unknown_error_type_has_fallback_fixes(self):
        d = self._analyze(error_type="totally_unknown_error")
        assert len(d.suggested_fixes) > 0

    def test_k3s_phase(self):
        d = self._analyze(failed_phase="phase-04-k3s", error_type="ansible_unreachable")
        assert "ssh" in " ".join(d.suggested_fixes).lower()

    def test_join_fingerprint_fix(self):
        d = self._analyze(failed_phase="phase-01-proxmox", error_type="join_fingerprint")
        combined = " ".join(d.suggested_fixes)
        assert "fingerprint" in combined.lower()


# ===========================================================================
# analyze_failure_package (tar.gz)
# ===========================================================================

class TestAnalyzeFailurePackage:
    def test_analyze_from_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_bytes = _make_failure_package_bytes(_report_dict(error_type="disk_missing"))
            path = os.path.join(tmpdir, "failure-test.tar.gz")
            with open(path, "wb") as f:
                f.write(pkg_bytes)
            d = _fpa.analyze_failure_package(path)
            assert isinstance(d, _fpa.FailureDiagnosis)
            assert d.error_type == "disk_missing"

    def test_missing_file_raises(self):
        import pytest
        with pytest.raises(FileNotFoundError):
            _fpa.analyze_failure_package("/tmp/does-not-exist.tar.gz")

    def test_no_report_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "empty.tar.gz")
            with tarfile.open(path, "w:gz") as tar:
                pass  # empty archive
            import pytest
            with pytest.raises(ValueError):
                _fpa.analyze_failure_package(path)


# ===========================================================================
# assemble_failure_package
# ===========================================================================

class TestAssembleFailurePackage:
    def test_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report = _report_dict()
            path = _fpa.assemble_failure_package(report, output_dir=tmpdir)
            assert os.path.exists(path)
            assert path.endswith(".tar.gz")

    def test_contains_failure_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report = _report_dict()
            path = _fpa.assemble_failure_package(report, output_dir=tmpdir)
            with tarfile.open(path, "r:gz") as tar:
                names = tar.getnames()
                assert "failure-report.json" in names

    def test_package_is_valid_gzip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report = _report_dict()
            path = _fpa.assemble_failure_package(report, output_dir=tmpdir)
            assert tarfile.is_tarfile(path)

    def test_roundtrip_analyze(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report = _report_dict(error_type="vmid_conflict")
            path = _fpa.assemble_failure_package(report, output_dir=tmpdir)
            d = _fpa.analyze_failure_package(path)
            assert d.error_type == "vmid_conflict"
            assert d.can_regenerate is True


# ===========================================================================
# export_to_usb
# ===========================================================================

class TestExportToUsb:
    def test_copies_file(self):
        with tempfile.TemporaryDirectory() as src_dir, \
             tempfile.TemporaryDirectory() as usb_dir:
            pkg_path = os.path.join(src_dir, "failure-test.tar.gz")
            with open(pkg_path, "wb") as f:
                f.write(_make_failure_package_bytes(_report_dict()))
            dest = _fpa.export_to_usb(pkg_path, usb_dir)
            assert os.path.exists(dest)

    def test_missing_mount_point_raises(self):
        import pytest
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_path = os.path.join(tmpdir, "fail.tar.gz")
            with open(pkg_path, "wb") as f:
                f.write(b"fake")
            with pytest.raises(OSError):
                _fpa.export_to_usb(pkg_path, "/nonexistent/usb/mount")


# ===========================================================================
# FAILURE_SHELL_FUNCTIONS
# ===========================================================================

class TestFailureShellFunctions:
    def test_contains_generate_function(self):
        assert "generate_failure_package()" in _fpa.FAILURE_SHELL_FUNCTIONS

    def test_contains_failure_report_write(self):
        assert "_write_failure_report()" in _fpa.FAILURE_SHELL_FUNCTIONS

    def test_contains_network_export(self):
        assert "HATCHERY_RECEIVER_URL" in _fpa.FAILURE_SHELL_FUNCTIONS

    def test_contains_usb_instructions(self):
        assert "USB" in _fpa.FAILURE_SHELL_FUNCTIONS or "usb" in _fpa.FAILURE_SHELL_FUNCTIONS.lower()

    def test_curl_not_in_process_args(self):
        # Secret content should use env vars or stdin, not appear in curl args
        # This test ensures the curl POST sends the file body, not inline data
        assert "--data-binary" in _fpa.FAILURE_SHELL_FUNCTIONS


# ===========================================================================
# PHASE_CATALOGUE completeness
# ===========================================================================

class TestPhaseCatalogue:
    def test_all_spawn_phases_present(self):
        phases = set(_fpa.PHASE_CATALOGUE.keys())
        for expected in [
            "phase-00-preflight", "phase-00-host", "phase-01-proxmox",
            "phase-02-vms", "phase-03-cloudinit", "phase-04-k3s",
            "phase-05-ha", "phase-06-verify",
        ]:
            assert expected in phases

    def test_each_phase_has_description(self):
        for phase, info in _fpa.PHASE_CATALOGUE.items():
            assert "description" in info, f"{phase} missing description"

    def test_each_phase_has_error_categories(self):
        for phase, info in _fpa.PHASE_CATALOGUE.items():
            assert "error_categories" in info, f"{phase} missing error_categories"
            assert len(info["error_categories"]) > 0


# ===========================================================================
# FailureDiagnosis.to_markdown / summary_lines
# ===========================================================================

class TestFailureDiagnosisSummary:
    def _make(self) -> _fpa.FailureDiagnosis:
        report = _fpa.parse_failure_report(_report_dict(
            error_type="vmid_conflict",
            completed_phases=["phase-00-preflight"],
        ))
        return _fpa.analyze_failure_report(report)

    def test_to_markdown_returns_string(self):
        d = self._make()
        assert isinstance(d.to_markdown(), str)

    def test_to_markdown_contains_phase(self):
        d = self._make()
        assert "phase-00-preflight" in d.to_markdown()

    def test_to_markdown_contains_fixes(self):
        d = self._make()
        assert "1." in d.to_markdown()

    def test_to_markdown_contains_regeneration(self):
        d = self._make()
        md = d.to_markdown()
        assert "Regeneration" in md or "regenerate" in md.lower()


# ===========================================================================
# hatchery_receiver
# ===========================================================================

class TestReceiveFailurePackage:
    def test_stores_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data = _make_failure_package_bytes(_report_dict())
            path = _hr.receive_failure_package(data, "fail-test.tar.gz", storage_dir=tmpdir)
            assert os.path.exists(path)

    def test_creates_receipt(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data = _make_failure_package_bytes(_report_dict())
            path = _hr.receive_failure_package(data, "fail-test.tar.gz", storage_dir=tmpdir)
            receipt_path = path + ".receipt.json"
            assert os.path.exists(receipt_path)
            with open(receipt_path) as f:
                receipt = json.load(f)
            assert receipt["filename"] == "fail-test.tar.gz"
            assert receipt["analyzed"] is False

    def test_receipt_records_size(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data = _make_failure_package_bytes(_report_dict())
            path = _hr.receive_failure_package(data, "fail-test.tar.gz", storage_dir=tmpdir)
            with open(path + ".receipt.json") as f:
                receipt = json.load(f)
            assert receipt["size_bytes"] == len(data)

    def test_creates_storage_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sub = os.path.join(tmpdir, "new-subdir")
            data = _make_failure_package_bytes(_report_dict())
            _hr.receive_failure_package(data, "fail.tar.gz", storage_dir=sub)
            assert os.path.isdir(sub)


class TestListReceivedPackages:
    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            assert _hr.list_received_packages(tmpdir) == []

    def test_nonexistent_dir(self):
        assert _hr.list_received_packages("/nonexistent") == []

    def test_lists_packages(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data = _make_failure_package_bytes(_report_dict())
            _hr.receive_failure_package(data, "fail-a.tar.gz", storage_dir=tmpdir)
            _hr.receive_failure_package(data, "fail-b.tar.gz", storage_dir=tmpdir)
            packages = _hr.list_received_packages(tmpdir)
            assert len(packages) == 2
            names = {p["filename"] for p in packages}
            assert "fail-a.tar.gz" in names
            assert "fail-b.tar.gz" in names


class TestMarkAnalyzed:
    def test_marks_analyzed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data = _make_failure_package_bytes(_report_dict())
            path = _hr.receive_failure_package(data, "fail.tar.gz", storage_dir=tmpdir)
            report = _fpa.parse_failure_report(_report_dict())
            diag = _fpa.analyze_failure_report(report)
            _hr.mark_analyzed(path, diag)
            with open(path + ".receipt.json") as f:
                receipt = json.load(f)
            assert receipt["analyzed"] is True
            assert receipt["error_type"] == "disk_missing"


class TestAnalyzeAllUnanalyzed:
    def test_analyzes_unanalyzed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data = _make_failure_package_bytes(_report_dict(error_type="vmid_conflict"))
            _hr.receive_failure_package(data, "fail.tar.gz", storage_dir=tmpdir)
            results = _hr.analyze_all_unanalyzed(tmpdir)
            assert len(results) == 1
            assert results[0].error_type == "vmid_conflict"

    def test_skips_already_analyzed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data = _make_failure_package_bytes(_report_dict())
            path = _hr.receive_failure_package(data, "fail.tar.gz", storage_dir=tmpdir)
            # Mark as analyzed
            report = _fpa.parse_failure_report(_report_dict())
            diag = _fpa.analyze_failure_report(report)
            _hr.mark_analyzed(path, diag)
            # Should skip
            results = _hr.analyze_all_unanalyzed(tmpdir)
            assert len(results) == 0


# ===========================================================================
# HatcheryReceiverConfig — auth token field
# ===========================================================================

class TestHatcheryReceiverConfigAuth:
    def test_default_auth_token_empty(self):
        cfg = _hr.HatcheryReceiverConfig()
        assert cfg.auth_token == ""

    def test_auth_token_set(self):
        cfg = _hr.HatcheryReceiverConfig(auth_token="secret-token-123")
        assert cfg.auth_token == "secret-token-123"

    def test_auth_token_in_server_handler(self):
        """Handler must reject requests when token is configured but not provided."""
        import io
        from http.server import BaseHTTPRequestHandler
        from unittest.mock import MagicMock

        cfg = _hr.HatcheryReceiverConfig(auth_token="test-token")

        class _Handler(_hr._ReceiverHandler):
            _config = cfg

        # Build a minimal mock request with missing token
        mock_request = MagicMock()
        mock_request.makefile.return_value = io.BytesIO(b"")
        handler = _Handler.__new__(_Handler)
        handler.headers = {"Content-Length": "0"}
        handler.path = "/api/failure-packages"
        handler.client_address = ("127.0.0.1", 1234)
        handler.rfile = io.BytesIO(b"")

        sent_errors = []
        handler.send_error = lambda code, msg="": sent_errors.append(code)
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = io.BytesIO()
        handler.log_message = lambda *a: None

        handler.do_POST()
        assert 401 in sent_errors

    def test_auth_token_accepted_with_correct_header(self):
        """Handler must accept requests when correct token is provided."""
        import io
        from unittest.mock import MagicMock
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _hr.HatcheryReceiverConfig(auth_token="correct-token", storage_dir=tmpdir)

            class _Handler(_hr._ReceiverHandler):
                _config = cfg

            data = _make_failure_package_bytes(_report_dict())
            handler = _Handler.__new__(_Handler)
            handler.headers = {
                "Content-Length": str(len(data)),
                "X-Broodforge-Token": "correct-token",
                "X-Package-Name": "test.tar.gz",
            }
            handler.path = "/api/failure-packages"
            handler.client_address = ("127.0.0.1", 1234)
            handler.rfile = io.BytesIO(data)

            responses = []
            handler.send_error = lambda code, msg="": responses.append(("error", code))
            handler.send_response = lambda code: responses.append(("ok", code))
            handler.send_header = MagicMock()
            handler.end_headers = MagicMock()
            handler.wfile = io.BytesIO()
            handler.log_message = lambda *a: None

            handler.do_POST()
            assert any(r == ("ok", 200) for r in responses)

    def test_negative_content_length_rejected(self):
        """Negative Content-Length must be rejected with 400 to prevent unbounded read."""
        import io
        from unittest.mock import MagicMock

        cfg = _hr.HatcheryReceiverConfig(auth_token="")

        class _Handler(_hr._ReceiverHandler):
            _config = cfg

        handler = _Handler.__new__(_Handler)
        handler.headers = {"Content-Length": "-1"}
        handler.path = "/api/failure-packages"
        handler.client_address = ("127.0.0.1", 1234)
        handler.rfile = io.BytesIO(b"")

        sent_errors = []
        handler.send_error = lambda code, msg="": sent_errors.append(code)
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = io.BytesIO()
        handler.log_message = lambda *a: None

        handler._handle_failure_package()
        assert 400 in sent_errors

    def test_negative_content_length_spawn_complete_rejected(self):
        """Negative Content-Length on /api/spawn-complete must be rejected with 400."""
        import io
        from unittest.mock import MagicMock

        cfg = _hr.HatcheryReceiverConfig(auth_token="")

        class _Handler(_hr._ReceiverHandler):
            _config = cfg

        handler = _Handler.__new__(_Handler)
        handler.headers = {"Content-Length": "-1"}
        handler.path = "/api/spawn-complete"
        handler.client_address = ("127.0.0.1", 1234)
        handler.rfile = io.BytesIO(b"")

        sent_errors = []
        handler.send_error = lambda code, msg="": sent_errors.append(code)
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = io.BytesIO()
        handler.log_message = lambda *a: None

        handler._handle_spawn_complete()
        assert 400 in sent_errors
