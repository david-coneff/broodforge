"""
test_security_analyzer.py — Security Analyzer tests.

Covers:
  scan_logs      — log file secret pattern detection (LOG-001 through LOG-008)
  scan_scripts   — shell script unsafe pattern detection (SCRIPT-001 through SCRIPT-007)
  scan_manifest  — manifest plaintext field detection (MANIFEST-001, MANIFEST-002)
  SecurityReport — red/orange/yellow counts, scoring
  security_posture_score — scoring function
  _score_security_posture — readiness.py integration
  build_security_report_html — HTML output structure
  dashboard      — _security_from_state, generate_dashboard_html security section
"""

import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "proxmox-bootstrap"))

import security_analyzer as _sa


def _now():
    return "2026-06-02T12:00:00+00:00"


def _tmp_file(content: str, suffix=".log") -> str:
    """Write content to a temp file and return the path."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False)
    f.write(content)
    f.close()
    return f.name


# ===========================================================================
# Log scanner
# ===========================================================================

class TestScanLogs:

    def test_detects_totp_seed(self):
        path = _tmp_file("totp_secret = JBSWY3DPEHPK3PXP\n")
        findings = _sa.scan_logs([path])
        assert any(f.rule_id == "LOG-001" for f in findings)
        assert findings[0].severity == "RED"

    def test_detects_private_key(self):
        path = _tmp_file("-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n")
        findings = _sa.scan_logs([path])
        assert any(f.rule_id == "LOG-002" for f in findings)
        assert findings[0].severity == "RED"

    def test_detects_password_in_log(self):
        path = _tmp_file("password=mysecretpassword123\n")
        findings = _sa.scan_logs([path])
        red = [f for f in findings if f.severity == "RED"]
        assert red  # LOG-003 match

    def test_detects_k3s_token(self):
        path = _tmp_file("K3S_TOKEN=K1abcdef1234567890abcdef1234567890:server:deadbeef\n")
        findings = _sa.scan_logs([path])
        assert any(f.rule_id == "LOG-004" for f in findings)

    def test_detects_api_key(self):
        path = _tmp_file("api_key=sk-1234567890abcdefABCDEF1234567890\n")
        findings = _sa.scan_logs([path])
        assert any(f.severity in ("RED", "ORANGE") for f in findings)

    def test_detects_restic_password(self):
        path = _tmp_file("RESTIC_PASSWORD=correct-horse-battery-staple\n")
        findings = _sa.scan_logs([path])
        assert any(f.rule_id == "LOG-006" for f in findings)

    def test_detects_bearer_token_in_header(self):
        path = _tmp_file("Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc\n")
        findings = _sa.scan_logs([path])
        assert any(f.rule_id == "LOG-008" for f in findings)
        assert findings[0].severity == "YELLOW"

    def test_no_false_positive_on_null(self):
        path = _tmp_file("password=null\n")
        findings = _sa.scan_logs([path])
        # 'null' shouldn't trigger
        red_password = [f for f in findings if f.rule_id == "LOG-003"]
        assert not red_password

    def test_no_false_positive_on_empty(self):
        path = _tmp_file("password=''\n")
        findings = _sa.scan_logs([path])
        red_password = [f for f in findings if f.rule_id == "LOG-003"]
        assert not red_password

    def test_line_content_sanitised(self):
        path = _tmp_file("password=s3cr3tV@lue!\n")
        findings = _sa.scan_logs([path])
        assert findings
        # Actual password should not appear in finding content
        for f in findings:
            assert "s3cr3tV@lue" not in f.line_content

    def test_missing_file_ignored(self):
        findings = _sa.scan_logs(["/nonexistent/path/forge.log"])
        assert findings == []

    def test_multiple_patterns_same_line(self):
        path = _tmp_file("password=secret123 api_key=abc123def456\n")
        findings = _sa.scan_logs([path])
        assert len(findings) >= 1  # at least one match

    def test_line_number_recorded(self):
        path = _tmp_file("safe line\npassword=exposed_secret_value\nanother safe line\n")
        findings = _sa.scan_logs([path])
        pw_findings = [f for f in findings if f.rule_id == "LOG-003"]
        assert pw_findings[0].line_number == 2


# ===========================================================================
# Script scanner
# ===========================================================================

class TestScanScripts:

    def test_detects_strict_host_checking_no(self):
        path = _tmp_file("ssh -o StrictHostKeyChecking=no user@host\n", suffix=".sh")
        findings = _sa.scan_scripts([path])
        assert any(f.rule_id == "SCRIPT-001" for f in findings)
        assert findings[0].severity == "ORANGE"

    def test_strict_host_checking_allowed_in_phase_00(self):
        # StrictHostKeyChecking=no is acceptable in first-connect scripts
        path = _tmp_file("ssh -o StrictHostKeyChecking=no user@host\n", suffix=".sh")
        # Rename to phase-00 pattern by using temp file with appropriate name
        import shutil
        d = tempfile.mkdtemp()
        p00_path = os.path.join(d, "phase-00-host-bootstrap.sh")
        shutil.copy(path, p00_path)
        findings = _sa.scan_scripts([p00_path])
        strict = [f for f in findings if f.rule_id == "SCRIPT-001"]
        assert not strict  # allowed in first-connect script

    def test_detects_password_on_cmdline(self):
        path = _tmp_file("sshpass -p mysecretpassword ssh user@host\n", suffix=".sh")
        findings = _sa.scan_scripts([path])
        assert any(f.rule_id == "SCRIPT-002" for f in findings)
        assert findings[0].severity == "RED"

    def test_detects_export_secret_env(self):
        path = _tmp_file("export PASSWORD=mysecretpassword123\n", suffix=".sh")
        findings = _sa.scan_scripts([path])
        assert any(f.rule_id == "SCRIPT-003" for f in findings)
        assert findings[0].severity == "RED"

    def test_detects_echo_pipe_to_crypto(self):
        path = _tmp_file("echo 'mypassword' | restic -r /backup\n", suffix=".sh")
        findings = _sa.scan_scripts([path])
        assert any(f.rule_id == "SCRIPT-004" for f in findings)
        assert findings[0].severity == "ORANGE"

    def test_detects_hardcoded_bearer_in_curl(self):
        path = _tmp_file(
            'curl -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.secret" '
            'https://api.example.com/\n',
            suffix=".sh",
        )
        findings = _sa.scan_scripts([path])
        assert any(f.rule_id == "SCRIPT-005" for f in findings)

    def test_detects_set_minus_x(self):
        path = _tmp_file("set -x\nsome_command\n", suffix=".sh")
        findings = _sa.scan_scripts([path])
        assert any(f.rule_id == "SCRIPT-006" for f in findings)
        assert findings[0].severity == "YELLOW"

    def test_detects_known_hosts_dev_null(self):
        path = _tmp_file("ssh -o UserKnownHostsFile=/dev/null user@host\n", suffix=".sh")
        findings = _sa.scan_scripts([path])
        assert any(f.rule_id == "SCRIPT-007" for f in findings)

    def test_comment_lines_ignored(self):
        path = _tmp_file("# export PASSWORD=example_shown_in_comment\n", suffix=".sh")
        findings = _sa.scan_scripts([path])
        assert not any(f.rule_id == "SCRIPT-003" for f in findings)

    def test_clean_script_no_findings(self):
        path = _tmp_file(
            "#!/bin/bash\nset -euo pipefail\necho 'Deploying...'\n",
            suffix=".sh",
        )
        findings = _sa.scan_scripts([path])
        assert findings == []


# ===========================================================================
# Manifest scanner
# ===========================================================================

class TestScanManifest:

    def test_detects_plaintext_password_field(self):
        state = {"password": "mysecretpassword123"}
        findings = _sa.scan_manifest(state)
        assert any(f.rule_id == "MANIFEST-002" for f in findings)
        assert findings[0].severity == "RED"

    def test_keepass_reference_not_flagged(self):
        state = {"password": "Infrastructure/myservice/password"}
        findings = _sa.scan_manifest(state)
        assert not any(f.rule_id == "MANIFEST-002" for f in findings)

    def test_private_key_in_field(self):
        state = {"private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIEow..."}
        findings = _sa.scan_manifest(state)
        assert any(f.rule_id == "MANIFEST-001" for f in findings)
        assert findings[0].severity == "RED"

    def test_nested_password_field(self):
        state = {"vm_defaults": {"keepass": {"password": "actualplaintextpassword"}}}
        findings = _sa.scan_manifest(state)
        assert any(f.rule_id == "MANIFEST-002" for f in findings)

    def test_null_value_not_flagged(self):
        state = {"password": None}
        findings = _sa.scan_manifest(state)
        assert not findings

    def test_empty_string_not_flagged(self):
        state = {"password": ""}
        findings = _sa.scan_manifest(state)
        assert not findings

    def test_boolean_not_flagged(self):
        state = {"password": False}
        findings = _sa.scan_manifest(state)
        assert not findings

    def test_non_sensitive_field_name_not_flagged(self):
        state = {"hostname": "pve01", "cell_id": "pve01-cell"}
        findings = _sa.scan_manifest(state)
        assert not findings

    def test_short_value_not_flagged(self):
        state = {"password": "ab"}  # too short to be a real password
        findings = _sa.scan_manifest(state)
        assert not findings

    def test_api_token_field_flagged(self):
        state = {"api_token": "sk-1234567890abcdefABCDEF"}
        findings = _sa.scan_manifest(state)
        assert any(f.rule_id == "MANIFEST-002" for f in findings)

    def test_list_items_traversed(self):
        state = {"secrets": [{"password": "mysecretpassword123"}]}
        findings = _sa.scan_manifest(state)
        assert any(f.rule_id == "MANIFEST-002" for f in findings)


# ===========================================================================
# SecurityReport and scoring
# ===========================================================================

class TestSecurityReport:

    def _report_with(self, sev_list):
        r = _sa.SecurityReport(cell_id="test", scanned_at=_now(), base_dir=".")
        for sev in sev_list:
            r.findings.append(_sa.SecurityFinding(
                severity=sev, category="log-leak", file_path="test.log",
                line_number=1, line_content="[REDACTED]",
                description="test", remediation="rotate", rule_id="TEST-001",
            ))
        return r

    def test_red_count(self):
        r = self._report_with(["RED", "RED", "ORANGE"])
        assert r.red_count == 2
        assert r.orange_count == 1

    def test_yellow_count(self):
        r = self._report_with(["YELLOW", "YELLOW"])
        assert r.yellow_count == 2

    def test_score_red_when_any_red(self):
        r = self._report_with(["YELLOW", "RED"])
        assert _sa.security_posture_score(r) == "RED"

    def test_score_orange_when_orange_no_red(self):
        r = self._report_with(["YELLOW", "ORANGE"])
        assert _sa.security_posture_score(r) == "ORANGE"

    def test_score_yellow_when_only_yellow(self):
        r = self._report_with(["YELLOW"])
        assert _sa.security_posture_score(r) == "YELLOW"

    def test_score_green_when_empty(self):
        r = self._report_with([])
        assert _sa.security_posture_score(r) == "GREEN"

    def test_reason_mentions_count(self):
        r = self._report_with(["RED", "RED"])
        reason = _sa.security_posture_reason(r)
        assert "2" in reason
        assert "leak" in reason.lower()


# ===========================================================================
# HTML report
# ===========================================================================

class TestSecurityReportHtml:

    def test_html_contains_score(self):
        r = _sa.SecurityReport(cell_id="pve01-cell", scanned_at=_now(), base_dir=".")
        r.findings.append(_sa.SecurityFinding(
            severity="RED", category="log-leak", file_path="forge.log",
            line_number=5, line_content="password=[REDACTED]",
            description="Password in log", remediation="Rotate", rule_id="LOG-003",
        ))
        html = _sa.build_security_report_html(r)
        assert "Security Posture: RED" in html
        assert "pve01-cell" in html

    def test_html_sanitised_no_actual_secrets(self):
        r = _sa.SecurityReport(cell_id="test", scanned_at=_now(), base_dir=".")
        r.findings.append(_sa.SecurityFinding(
            severity="RED", category="log-leak", file_path="spawn.log",
            line_number=10, line_content="password=[REDACTED]",
            description="Exposed", remediation="Rotate", rule_id="LOG-003",
        ))
        html = _sa.build_security_report_html(r)
        # Actual secret value must not appear; REDACTED should
        assert "REDACTED" in html
        assert "mysecretpassword" not in html

    def test_html_shows_rule_ids(self):
        r = _sa.SecurityReport(cell_id="test", scanned_at=_now(), base_dir=".")
        r.findings.append(_sa.SecurityFinding(
            severity="ORANGE", category="script-unsafe", file_path="spawn.sh",
            line_number=3, line_content="StrictHostKeyChecking=no",
            description="Unsafe SSH", remediation="Use accept-new", rule_id="SCRIPT-001",
        ))
        html = _sa.build_security_report_html(r)
        assert "SCRIPT-001" in html

    def test_html_green_report(self):
        r = _sa.SecurityReport(cell_id="test", scanned_at=_now(), base_dir=".")
        html = _sa.build_security_report_html(r)
        assert "Security Posture: GREEN" in html
        assert "No immediate remediation required" in html

    def test_html_is_valid_structure(self):
        r = _sa.SecurityReport(cell_id="test", scanned_at=_now(), base_dir=".")
        html = _sa.build_security_report_html(r)
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html
        assert 'charset="UTF-8"' in html


# ===========================================================================
# Readiness integration
# ===========================================================================

class TestReadinessSecurityPosture:

    def test_no_scan_gives_yellow(self):
        sys.path.insert(0, os.path.join(_ROOT, "doc-gen"))
        import readiness as _r
        manifest = {"cell_id": "test"}  # no security_scan key
        gaps = _r._score_security_posture(manifest)
        assert any(g.severity == "YELLOW" for g in gaps)
        assert any("no_security_scan" in g.gap_type for g in gaps)

    def test_red_findings_give_red(self):
        sys.path.insert(0, os.path.join(_ROOT, "doc-gen"))
        import readiness as _r
        manifest = {
            "security_scan": {
                "last_result": {
                    "red_count": 2, "orange_count": 0, "yellow_count": 0,
                    "scanned_at": _now(), "score": "RED",
                }
            }
        }
        gaps = _r._score_security_posture(manifest)
        assert any(g.severity == "RED" for g in gaps)

    def test_orange_findings_give_orange(self):
        sys.path.insert(0, os.path.join(_ROOT, "doc-gen"))
        import readiness as _r
        manifest = {
            "security_scan": {
                "last_result": {
                    "red_count": 0, "orange_count": 1, "yellow_count": 0,
                    "scanned_at": _now(), "score": "ORANGE",
                }
            }
        }
        gaps = _r._score_security_posture(manifest)
        assert any(g.severity == "ORANGE" for g in gaps)

    def test_yellow_only_findings_give_yellow(self):
        sys.path.insert(0, os.path.join(_ROOT, "doc-gen"))
        import readiness as _r
        manifest = {
            "security_scan": {
                "last_result": {
                    "red_count": 0, "orange_count": 0, "yellow_count": 3,
                    "scanned_at": _now(), "score": "YELLOW",
                }
            }
        }
        gaps = _r._score_security_posture(manifest)
        assert any(g.severity == "YELLOW" for g in gaps)

    def test_clean_scan_gives_no_gaps(self):
        sys.path.insert(0, os.path.join(_ROOT, "doc-gen"))
        import readiness as _r
        manifest = {
            "security_scan": {
                "last_result": {
                    "red_count": 0, "orange_count": 0, "yellow_count": 0,
                    "scanned_at": _now(), "score": "GREEN",
                }
            }
        }
        gaps = _r._score_security_posture(manifest)
        assert gaps == []


# ===========================================================================
# Dashboard integration
# ===========================================================================

class TestDashboardSecurity:

    def _state_with_scan(self, red=0, orange=0, yellow=0, score="GREEN"):
        return {
            "cell_id": "test-cell",
            "security_scan": {
                "last_result": {
                    "scanned_at": _now(),
                    "red_count": red,
                    "orange_count": orange,
                    "yellow_count": yellow,
                    "files_scanned": 5,
                    "score": score,
                    "findings": [],
                }
            }
        }

    def test_security_from_state_green(self):
        from broodforge_dashboard import _security_from_state
        sec = _security_from_state(self._state_with_scan())
        assert sec["score"] == "GREEN"
        assert sec["red_count"] == 0
        assert sec["has_scan"] is True

    def test_security_from_state_red(self):
        from broodforge_dashboard import _security_from_state
        sec = _security_from_state(self._state_with_scan(red=2, score="RED"))
        assert sec["red_count"] == 2
        assert sec["score"] == "RED"

    def test_security_from_state_no_scan(self):
        from broodforge_dashboard import _security_from_state
        sec = _security_from_state({"cell_id": "test"})
        assert sec["has_scan"] is False
        assert sec["red_count"] == 0

    def test_dashboard_html_includes_security_section(self):
        from broodforge_dashboard import generate_dashboard_html, DashboardConfig
        state = self._state_with_scan()
        cfg = DashboardConfig()
        sec = {
            "scanned_at": _now()[:16],
            "red_count": 0, "orange_count": 0, "yellow_count": 0,
            "files_scanned": 5, "score": "GREEN",
            "findings": [], "has_scan": True,
        }
        html = generate_dashboard_html(state, {}, [], [], {}, cfg, security=sec)
        assert "Security Posture" in html

    def test_dashboard_html_shows_no_scan_tip(self):
        from broodforge_dashboard import generate_dashboard_html, DashboardConfig
        state = {"cell_id": "test"}
        cfg = DashboardConfig()
        html = generate_dashboard_html(state, {}, [], [], {}, cfg, security={"has_scan": False})
        assert "security_analyzer.py" in html or "No security scan" in html


# ===========================================================================
# write_security_scan_result
# ===========================================================================

class TestWriteSecurityScanResult:
    def _report(self, red=0, orange=0, yellow=0):
        findings = []
        for _ in range(red):
            findings.append(_sa.SecurityFinding(
                severity="RED", category="log-leak", rule_id="LOG-001",
                file_path="/tmp/test.log", line_number=1,
                line_content="REDACTED", description="leak", remediation="rotate",
            ))
        for _ in range(orange):
            findings.append(_sa.SecurityFinding(
                severity="ORANGE", category="script-unsafe", rule_id="SCRIPT-001",
                file_path="/tmp/test.sh", line_number=5,
                line_content="StrictHostKeyChecking=no", description="unsafe ssh",
                remediation="use accept-new",
            ))
        for _ in range(yellow):
            findings.append(_sa.SecurityFinding(
                severity="YELLOW", category="log-leak", rule_id="LOG-003",
                file_path="/tmp/test.log", line_number=2,
                line_content="REDACTED", description="suspicious", remediation="review",
            ))
        r = _sa.SecurityReport(
            cell_id="test-cell",
            scanned_at="2026-06-01T12:00:00+00:00",
            base_dir="/tmp",
            findings=findings,
            files_scanned=10,
        )
        return r

    def test_creates_state_file_if_absent(self, tmp_path):
        from security_analyzer import write_security_scan_result
        state_path = str(tmp_path / "bootstrap-state.json")
        write_security_scan_result(state_path, self._report())
        import json
        with open(state_path) as f:
            state = json.load(f)
        assert "security_scan" in state
        assert "last_result" in state["security_scan"]

    def test_writes_posture(self, tmp_path):
        from security_analyzer import write_security_scan_result
        state_path = str(tmp_path / "state.json")
        write_security_scan_result(state_path, self._report(red=2))
        import json
        with open(state_path) as f:
            state = json.load(f)
        assert state["security_scan"]["last_result"]["posture"] == "RED"

    def test_writes_counts(self, tmp_path):
        from security_analyzer import write_security_scan_result
        state_path = str(tmp_path / "state.json")
        write_security_scan_result(state_path, self._report(red=1, orange=2, yellow=3))
        import json
        with open(state_path) as f:
            state = json.load(f)
        lr = state["security_scan"]["last_result"]
        assert lr["red_count"] == 1
        assert lr["orange_count"] == 2
        assert lr["yellow_count"] == 3

    def test_preserves_existing_state_fields(self, tmp_path):
        import json
        from security_analyzer import write_security_scan_result
        state_path = str(tmp_path / "state.json")
        with open(state_path, "w") as f:
            json.dump({"cell_id": "preserved", "version": "1.0"}, f)
        write_security_scan_result(state_path, self._report())
        with open(state_path) as f:
            state = json.load(f)
        assert state["cell_id"] == "preserved"
        assert state["version"] == "1.0"
        assert "security_scan" in state

    def test_findings_serialized(self, tmp_path):
        import json
        from security_analyzer import write_security_scan_result
        state_path = str(tmp_path / "state.json")
        write_security_scan_result(state_path, self._report(red=1))
        with open(state_path) as f:
            state = json.load(f)
        findings = state["security_scan"]["last_result"]["findings"]
        assert len(findings) == 1
        assert findings[0]["severity"] == "RED"
        assert findings[0]["rule_id"] == "LOG-001"

    def test_green_scan_posture(self, tmp_path):
        import json
        from security_analyzer import write_security_scan_result
        state_path = str(tmp_path / "state.json")
        write_security_scan_result(state_path, self._report())
        with open(state_path) as f:
            state = json.load(f)
        assert state["security_scan"]["last_result"]["posture"] == "GREEN"


# ===========================================================================
# watch() — continuous mode
# ===========================================================================

class TestWatch:
    def test_watch_emits_finding_for_new_content(self, tmp_path):
        import threading
        import time
        from security_analyzer import watch, SecurityFinding

        log = tmp_path / "service.log"
        log.write_text("")

        findings = []
        stop = threading.Event()

        def cb(f: SecurityFinding):
            findings.append(f)
            stop.set()

        t = threading.Thread(target=watch, args=([str(log)], cb, stop), kwargs={"poll_interval": 0.05})
        t.daemon = True
        t.start()

        # Give watcher time to start
        time.sleep(0.1)
        # Write a line matching LOG-001 (TOTP seed pattern)
        with open(str(log), "a") as f:
            f.write("TOTP_SECRET=JBSWY3DPEHPK3PXP some text\n")

        t.join(timeout=3.0)
        assert len(findings) >= 1
        assert findings[0].category == "log-leak"

    def test_watch_no_emit_for_non_matching(self, tmp_path):
        import threading
        import time
        from security_analyzer import watch

        log = tmp_path / "clean.log"
        log.write_text("")

        findings = []
        stop = threading.Event()
        cb = lambda f: findings.append(f)

        t = threading.Thread(target=watch, args=([str(log)], cb, stop), kwargs={"poll_interval": 0.05})
        t.daemon = True
        t.start()

        time.sleep(0.1)
        with open(str(log), "a") as f:
            f.write("INFO: everything is fine\n")

        time.sleep(0.3)
        stop.set()
        t.join(timeout=2.0)
        assert findings == []

    def test_watch_stops_on_event(self, tmp_path):
        import threading
        import time
        from security_analyzer import watch

        log = tmp_path / "noop.log"
        log.write_text("")
        stop = threading.Event()

        t = threading.Thread(target=watch, args=([str(log)], lambda f: None, stop), kwargs={"poll_interval": 0.05})
        t.daemon = True
        t.start()

        time.sleep(0.1)
        stop.set()
        t.join(timeout=2.0)
        assert not t.is_alive()

    def test_watch_handles_missing_file(self, tmp_path):
        import threading
        import time
        from security_analyzer import watch

        stop = threading.Event()
        t = threading.Thread(
            target=watch,
            args=([str(tmp_path / "nonexistent.log")], lambda f: None, stop),
            kwargs={"poll_interval": 0.05},
        )
        t.daemon = True
        t.start()
        time.sleep(0.1)
        stop.set()
        t.join(timeout=2.0)
        # Should not crash for missing files
        assert not t.is_alive()


# ===========================================================================
# _find_shell_scripts — recursive scan
# ===========================================================================

class TestFindShellScriptsRecursive:
    def test_finds_scripts_in_subdirectories(self, tmp_path):
        from security_analyzer import _find_shell_scripts

        # Create nested structure mirroring assessment/tier1/collectors/
        subdir = tmp_path / "assessment" / "tier1" / "collectors"
        subdir.mkdir(parents=True)
        script = subdir / "collect-metrics.sh"
        script.write_text("#!/bin/bash\necho ok\n")

        results = _find_shell_scripts(str(tmp_path))
        assert str(script) in results

    def test_finds_scripts_in_proxmox_bootstrap(self, tmp_path):
        from security_analyzer import _find_shell_scripts

        pb = tmp_path / "proxmox-bootstrap"
        pb.mkdir()
        s = pb / "forge.sh"
        s.write_text("#!/bin/bash\n")
        results = _find_shell_scripts(str(tmp_path))
        assert str(s) in results

    def test_skips_hidden_directories(self, tmp_path):
        from security_analyzer import _find_shell_scripts

        hidden = tmp_path / ".hidden"
        hidden.mkdir()
        s = hidden / "secret.sh"
        s.write_text("#!/bin/bash\n")
        results = _find_shell_scripts(str(tmp_path))
        assert str(s) not in results

    def test_no_duplicates(self, tmp_path):
        from security_analyzer import _find_shell_scripts

        s = tmp_path / "test.sh"
        s.write_text("#!/bin/bash\n")
        results = _find_shell_scripts(str(tmp_path))
        assert len(results) == len(set(results))
