"""
Tests for Phase 1.L/1.M: assess_code_health(), DynamicHealthScore, and dashboard Code Health card.
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "proxmox-bootstrap"))

from continuous_assessment import (
    assess_code_health, CodeHealthScore, _score_code_health,
    assess_dynamic_health, DynamicHealthScore, _score_dynamic_health,
    code_health_to_remediation_candidates,
    dynamic_health_to_remediation_candidates,
    collect_health_remediation_candidates,
)


class TestScoreCodeHealth:
    def test_perfect_score(self):
        score = _score_code_health(0, 0, 0, 0.0, 95.0)
        assert score == 100

    def test_high_bandit_penalized(self):
        score = _score_code_health(0, 2, 0, 0.0, 95.0)
        assert score <= 70

    def test_low_coverage_penalized(self):
        score = _score_code_health(0, 0, 0, 0.0, 50.0)
        assert score < 100

    def test_score_clamped_to_zero(self):
        score = _score_code_health(100, 10, 10, 50.0, 0.0)
        assert score == 0

    def test_score_not_negative(self):
        score = _score_code_health(999, 999, 999, 100.0, 0.0)
        assert score >= 0

    def test_shellcheck_penalty(self):
        # 10 shellcheck findings → -30 (capped)
        score_many = _score_code_health(10, 0, 0, 0.0, 95.0)
        score_none = _score_code_health(0, 0, 0, 0.0, 95.0)
        assert score_many < score_none

    def test_medium_bandit_penalty(self):
        score_with = _score_code_health(0, 0, 3, 0.0, 95.0)
        score_without = _score_code_health(0, 0, 0, 0.0, 95.0)
        assert score_with < score_without

    def test_vulture_penalty(self):
        score_with = _score_code_health(0, 0, 0, 20.0, 95.0)
        score_without = _score_code_health(0, 0, 0, 0.0, 95.0)
        assert score_with < score_without

    def test_coverage_at_80_no_penalty(self):
        score = _score_code_health(0, 0, 0, 0.0, 80.0)
        assert score == 100

    def test_coverage_below_80_penalized(self):
        # 60% coverage → penalty = int((80-60)*0.5) = 10
        score = _score_code_health(0, 0, 0, 0.0, 60.0)
        assert score < 100


class TestAssessCodeHealth:
    def _make_run_fn(self, shellcheck_findings=None, bandit_results=None, vulture_lines=None):
        """Factory for a mock subprocess.run that returns test data."""
        def run_fn(cmd, **kwargs):
            result = MagicMock()
            result.returncode = 0
            if isinstance(cmd, list) and cmd and "shellcheck" in cmd[0]:
                result.stdout = json.dumps(shellcheck_findings or [])
            elif isinstance(cmd, list) and cmd and "bandit" in cmd[0]:
                data = {"results": bandit_results or []}
                result.stdout = json.dumps(data)
            elif isinstance(cmd, list) and cmd and "vulture" in cmd[0]:
                lines = vulture_lines or []
                result.stdout = "\n".join(lines)
            else:
                result.stdout = ""
            return result
        return run_fn

    def test_returns_code_health_score(self):
        run_fn = self._make_run_fn()
        result = assess_code_health(".", run_fn=run_fn)
        assert isinstance(result, CodeHealthScore)

    def test_counts_shellcheck_findings(self):
        findings = [
            {"level": "error", "message": "foo", "line": 1, "code": "SC2034"},
            {"level": "warning", "message": "bar", "line": 2, "code": "SC2035"},
        ]
        run_fn = self._make_run_fn(shellcheck_findings=findings)
        result = assess_code_health(".", run_fn=run_fn)
        assert result.shellcheck_findings == 2

    def test_counts_bandit_high_and_medium(self):
        bandit_results = [
            {"issue_severity": "HIGH", "issue_text": "Use of exec"},
            {"issue_severity": "MEDIUM", "issue_text": "Use of assert"},
            {"issue_severity": "LOW", "issue_text": "Trivial"},
        ]
        run_fn = self._make_run_fn(bandit_results=bandit_results)
        result = assess_code_health(".", run_fn=run_fn)
        assert result.bandit_high_count == 1
        assert result.bandit_medium_count == 1

    def test_overall_score_decreases_with_findings(self):
        bandit_results = [{"issue_severity": "HIGH", "issue_text": "foo"}] * 3
        run_fn = self._make_run_fn(bandit_results=bandit_results)
        result = assess_code_health(".", run_fn=run_fn)
        assert result.overall <= 70  # 3 HIGH findings (-30) cap score at 70

    def test_shellcheck_not_installed_does_not_crash(self):
        def run_fn(cmd, **kwargs):
            if isinstance(cmd, list) and cmd and "shellcheck" in cmd[0]:
                raise FileNotFoundError("shellcheck not found")
            result = MagicMock()
            result.stdout = json.dumps({"results": []})
            return result
        result = assess_code_health(".", run_fn=run_fn)
        assert isinstance(result, CodeHealthScore)
        assert result.shellcheck_findings == 0

    def test_bandit_not_installed_does_not_crash(self):
        def run_fn(cmd, **kwargs):
            if isinstance(cmd, list) and cmd and "bandit" in cmd[0]:
                raise FileNotFoundError("bandit not found")
            result = MagicMock()
            result.stdout = "[]"
            return result
        result = assess_code_health(".", run_fn=run_fn)
        assert isinstance(result, CodeHealthScore)
        assert result.bandit_high_count == 0

    def test_assessed_at_is_set(self):
        run_fn = self._make_run_fn()
        result = assess_code_health(".", run_fn=run_fn)
        assert result.assessed_at != ""

    def test_no_high_findings_high_score(self):
        run_fn = self._make_run_fn(shellcheck_findings=[], bandit_results=[])
        result = assess_code_health(".", run_fn=run_fn)
        # No shellcheck/bandit HIGH findings — overall should be at least 50
        # (coverage_pct will be 0.0 since no .audit/coverage.json exists in test CWD,
        # which applies a coverage penalty, so we can't assert 100)
        assert result.overall >= 50
        assert result.bandit_high_count == 0
        assert result.shellcheck_findings == 0

    def test_custom_now_fn(self):
        run_fn = self._make_run_fn()
        result = assess_code_health(".", run_fn=run_fn, now_fn=lambda: "2026-06-08T00:00:00+00:00")
        assert result.assessed_at == "2026-06-08T00:00:00+00:00"

    def test_bandit_json_decode_error_does_not_crash(self):
        def run_fn(cmd, **kwargs):
            result = MagicMock()
            result.stdout = "not valid json {"
            return result
        result = assess_code_health(".", run_fn=run_fn)
        assert isinstance(result, CodeHealthScore)

    def test_bandit_low_not_counted(self):
        bandit_results = [
            {"issue_severity": "LOW", "issue_text": "Trivial"},
            {"issue_severity": "LOW", "issue_text": "Minor"},
        ]
        run_fn = self._make_run_fn(bandit_results=bandit_results)
        result = assess_code_health(".", run_fn=run_fn)
        assert result.bandit_high_count == 0
        assert result.bandit_medium_count == 0


class TestCodeHealthRemediationCandidates:
    def test_high_bandit_produces_candidates(self):
        """HIGH bandit findings should surface as remediation candidates."""
        from broodforge_dashboard import _code_health_to_remediation_candidates
        score = CodeHealthScore(bandit_high_count=2, bandit_medium_count=0, overall=60)
        candidates = _code_health_to_remediation_candidates(score)
        assert len(candidates) > 0
        assert any(
            "bandit" in c.get("description", "").lower()
            or "security" in c.get("description", "").lower()
            or "HIGH" in c.get("description", "")
            for c in candidates
        )

    def test_clean_codebase_no_candidates(self):
        from broodforge_dashboard import _code_health_to_remediation_candidates
        score = CodeHealthScore(bandit_high_count=0, shellcheck_findings=0, overall=95)
        candidates = _code_health_to_remediation_candidates(score)
        assert len(candidates) == 0

    def test_high_shellcheck_produces_candidates(self):
        from broodforge_dashboard import _code_health_to_remediation_candidates
        score = CodeHealthScore(bandit_high_count=0, shellcheck_findings=10, overall=70)
        candidates = _code_health_to_remediation_candidates(score)
        assert len(candidates) > 0

    def test_low_shellcheck_no_candidate(self):
        from broodforge_dashboard import _code_health_to_remediation_candidates
        # threshold is >= 5 findings for a remediation candidate
        score = CodeHealthScore(bandit_high_count=0, shellcheck_findings=3, overall=91)
        candidates = _code_health_to_remediation_candidates(score)
        assert len(candidates) == 0

    def test_candidate_has_required_keys(self):
        from broodforge_dashboard import _code_health_to_remediation_candidates
        score = CodeHealthScore(bandit_high_count=1, overall=70)
        candidates = _code_health_to_remediation_candidates(score)
        assert len(candidates) >= 1
        c = candidates[0]
        assert "type" in c
        assert "severity" in c
        assert "description" in c
        assert "source" in c
        assert "proposed_at" in c


class TestDashboardCodeHealthCard:
    def test_code_health_card_renders(self):
        """Dashboard Code Health card should render without errors."""
        from broodforge_dashboard import _build_code_health_card
        score = CodeHealthScore(
            shellcheck_findings=2,
            bandit_high_count=1,
            bandit_medium_count=3,
            vulture_dead_pct=5.0,
            coverage_pct=75.0,
            overall=65,
            assessed_at="2026-06-08T00:00:00+00:00",
        )
        html = _build_code_health_card(score)
        assert "Code Health" in html or "overall" in html.lower() or "65" in html
        assert "65" in html  # overall score
        assert "<div" in html

    def test_code_health_card_handles_error(self):
        from broodforge_dashboard import _build_code_health_card
        score = CodeHealthScore(error="shellcheck not found", overall=0)
        html = _build_code_health_card(score)
        assert "<div" in html
        assert "shellcheck" in html.lower() or "unavailable" in html.lower() or "error" in html.lower()

    def test_code_health_card_shows_bandit_tip(self):
        from broodforge_dashboard import _build_code_health_card
        score = CodeHealthScore(bandit_high_count=2, overall=70)
        html = _build_code_health_card(score)
        assert "bandit" in html.lower()

    def test_code_health_card_shows_shellcheck_tip(self):
        from broodforge_dashboard import _build_code_health_card
        score = CodeHealthScore(shellcheck_findings=5, overall=85)
        html = _build_code_health_card(score)
        assert "shellcheck" in html.lower()

    def test_code_health_card_green_score(self):
        from broodforge_dashboard import _build_code_health_card
        score = CodeHealthScore(overall=95)
        html = _build_code_health_card(score)
        assert "95" in html
        # green color used for high scores
        assert "green" in html

    def test_code_health_card_shows_coverage(self):
        from broodforge_dashboard import _build_code_health_card
        score = CodeHealthScore(coverage_pct=82.5, overall=100)
        html = _build_code_health_card(score)
        assert "82.5" in html

    def test_generate_dashboard_html_includes_code_health(self):
        """generate_dashboard_html should accept and render code_health kwarg."""
        from broodforge_dashboard import generate_dashboard_html, DashboardConfig
        cfg = DashboardConfig()
        score = CodeHealthScore(overall=88, bandit_high_count=0, shellcheck_findings=0)
        html = generate_dashboard_html(
            state={}, scores={}, nodes=[], failures=[], backup={},
            cfg=cfg, code_health=score,
        )
        assert "Code Health" in html
        assert "88" in html

    def test_code_health_card_label_is_static_score(self):
        """Overall score label should read 'Static score' (not 'Overall score')."""
        from broodforge_dashboard import _build_code_health_card
        score = CodeHealthScore(overall=77)
        html = _build_code_health_card(score)
        assert "Static" in html or "static" in html


# ---------------------------------------------------------------------------
# Phase 1.M: DynamicHealthScore scoring tests
# ---------------------------------------------------------------------------

class TestScoreDynamicHealth:
    def test_perfect_score(self):
        score = _score_dynamic_health(0, 85.0, 0, 5)
        assert score == 100

    def test_hypothesis_failures_penalized(self):
        score = _score_dynamic_health(2, 85.0, 0, 5)
        assert score <= 60

    def test_hypothesis_penalty_capped_at_40(self):
        score_2 = _score_dynamic_health(2, 85.0, 0, 0)
        score_5 = _score_dynamic_health(5, 85.0, 0, 0)
        assert score_5 == score_2  # penalty caps at 40

    def test_low_mutation_score_blocker(self):
        score = _score_dynamic_health(0, 30.0, 0, 10)
        assert score <= 65  # -35 penalty

    def test_medium_mutation_score_defect(self):
        score = _score_dynamic_health(0, 50.0, 0, 10)
        assert score <= 80  # -20 penalty

    def test_good_mutation_score_no_major_penalty(self):
        score = _score_dynamic_health(0, 85.0, 0, 10)
        assert score >= 95

    def test_mutation_score_minus1_skipped(self):
        # -1.0 means not run — should not penalize
        score_no_mut = _score_dynamic_health(0, -1.0, 0, 0)
        score_good_mut = _score_dynamic_health(0, 85.0, 0, 0)
        assert score_no_mut == score_good_mut

    def test_bats_failures_penalized(self):
        score = _score_dynamic_health(0, 85.0, 2, 5)
        assert score <= 80

    def test_bats_no_tests_no_penalty(self):
        score_no_bats = _score_dynamic_health(0, 85.0, 0, 0)
        score_good_bats = _score_dynamic_health(0, 85.0, 0, 5)
        assert score_no_bats == score_good_bats

    def test_score_never_negative(self):
        score = _score_dynamic_health(999, 0.0, 999, 999)
        assert score == 0


class TestAssessDynamicHealth:
    """Tests for assess_dynamic_health() with injectable run_fn."""

    def _make_run_fn(self, stdout="", returncode=0):
        def run_fn(cmd, **kwargs):
            result = MagicMock()
            result.stdout = stdout
            result.returncode = returncode
            return result
        return run_fn

    def test_returns_dynamic_health_score(self, tmp_path):
        result = assess_dynamic_health(str(tmp_path), run_fn=self._make_run_fn())
        assert isinstance(result, DynamicHealthScore)

    def test_not_implemented_when_no_given_and_no_bats(self, tmp_path):
        # tmp_path has no test files → no @given, no .bats → not_implemented
        result = assess_dynamic_health(str(tmp_path), run_fn=self._make_run_fn())
        assert result.not_implemented is True
        assert result.overall == -1

    def test_hypothesis_failures_counted(self, tmp_path):
        # Create a test file with @given decorator to trigger hypothesis run
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_prop.py").write_text("@given\ndef test_x(): pass\n")

        mutmut_out = "Killed 8 of 10 mutants"

        def run_fn(cmd, **kwargs):
            result = MagicMock()
            if "pytest" in cmd:
                result.stdout = "2 failed, 3 passed"
            elif "mutmut" in cmd and "results" in cmd:
                result.stdout = mutmut_out
            else:
                result.stdout = ""
            result.returncode = 0
            return result

        result = assess_dynamic_health(str(tmp_path), run_fn=run_fn)
        assert result.hypothesis_failures == 2

    def test_mutation_score_parsed(self, tmp_path):
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_prop.py").write_text("@given\ndef test_x(): pass\n")

        def run_fn(cmd, **kwargs):
            result = MagicMock()
            if "mutmut" in cmd and "results" in cmd:
                result.stdout = "Killed 7 of 10 mutants"
            else:
                result.stdout = "0 failed"
            result.returncode = 0
            return result

        result = assess_dynamic_health(str(tmp_path), run_fn=run_fn)
        assert result.mutation_score_pct == pytest.approx(70.0)

    def test_bats_counts_parsed(self, tmp_path):
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        bash_dir = test_dir / "bash"
        bash_dir.mkdir()
        bats_file = bash_dir / "test_smoke.bats"
        bats_file.write_text("@test 'something' { true; }\n")

        def run_fn(cmd, **kwargs):
            result = MagicMock()
            if "bats" in str(cmd):
                result.stdout = "ok 1 something\nok 2 another\nnot ok 3 broken\n"
            elif "mutmut" in str(cmd) and "results" in str(cmd):
                result.stdout = "Killed 8 of 10 mutants"
            else:
                result.stdout = "0 failed"
            result.returncode = 0
            return result

        result = assess_dynamic_health(str(tmp_path), run_fn=run_fn)
        assert result.bats_passed == 2
        assert result.bats_failed == 1
        assert result.bats_total == 3

    def test_custom_now_fn(self, tmp_path):
        result = assess_dynamic_health(
            str(tmp_path), run_fn=self._make_run_fn(),
            now_fn=lambda: "2026-06-08T12:00:00+00:00",
        )
        assert result.assessed_at == "2026-06-08T12:00:00+00:00"

    def test_run_fn_exception_returns_error(self, tmp_path):
        def run_fn(cmd, **kwargs):
            raise RuntimeError("subprocess failed")
        result = assess_dynamic_health(str(tmp_path), run_fn=run_fn)
        assert isinstance(result, DynamicHealthScore)
        assert result.error is not None


class TestDynamicRemediationCandidates:
    def test_hypothesis_failures_produce_high_candidate(self):
        from broodforge_dashboard import _code_health_to_remediation_candidates
        static = CodeHealthScore(overall=90)
        dynamic = DynamicHealthScore(hypothesis_failures=3, overall=60)
        candidates = _code_health_to_remediation_candidates(static, dynamic=dynamic)
        assert any(
            "hypothesis" in c.get("description", "").lower()
            for c in candidates
        )
        assert any(c.get("severity") == "HIGH" for c in candidates)

    def test_low_mutation_score_high_candidate(self):
        from broodforge_dashboard import _code_health_to_remediation_candidates
        static = CodeHealthScore(overall=90)
        dynamic = DynamicHealthScore(mutation_score_pct=35.0, overall=65)
        candidates = _code_health_to_remediation_candidates(static, dynamic=dynamic)
        assert any(
            "mutation" in c.get("description", "").lower() or "mutmut" in c.get("description", "").lower()
            for c in candidates
        )
        assert any(c.get("severity") == "HIGH" for c in candidates)

    def test_medium_mutation_score_medium_candidate(self):
        from broodforge_dashboard import _code_health_to_remediation_candidates
        static = CodeHealthScore(overall=90)
        dynamic = DynamicHealthScore(mutation_score_pct=55.0, overall=80)
        candidates = _code_health_to_remediation_candidates(static, dynamic=dynamic)
        assert any(
            ("mutation" in c.get("description", "").lower() or "mutmut" in c.get("description", "").lower())
            and c.get("severity") == "MEDIUM"
            for c in candidates
        )

    def test_bats_failures_produce_high_candidate(self):
        from broodforge_dashboard import _code_health_to_remediation_candidates
        static = CodeHealthScore(overall=90)
        dynamic = DynamicHealthScore(bats_failed=2, bats_total=5, bats_passed=3, overall=80)
        candidates = _code_health_to_remediation_candidates(static, dynamic=dynamic)
        assert any(
            "bats" in c.get("description", "").lower() or "bash" in c.get("description", "").lower()
            for c in candidates
        )

    def test_clean_dynamic_no_extra_candidates(self):
        from broodforge_dashboard import _code_health_to_remediation_candidates
        static = CodeHealthScore(overall=90)
        dynamic = DynamicHealthScore(
            hypothesis_failures=0, mutation_score_pct=85.0,
            bats_failed=0, bats_total=5, bats_passed=5, overall=100,
        )
        candidates = _code_health_to_remediation_candidates(static, dynamic=dynamic)
        assert len(candidates) == 0

    def test_not_implemented_dynamic_no_candidates(self):
        from broodforge_dashboard import _code_health_to_remediation_candidates
        static = CodeHealthScore(overall=90)
        dynamic = DynamicHealthScore(not_implemented=True, overall=-1)
        candidates = _code_health_to_remediation_candidates(static, dynamic=dynamic)
        # not_implemented means no dynamic infrastructure yet — no candidates
        assert not any(
            "hypothesis" in c.get("description", "").lower()
            or "mutation" in c.get("description", "").lower()
            or "bats" in c.get("description", "").lower()
            for c in candidates
        )


class TestDashboardDynamicSubcard:
    def test_not_implemented_shows_message(self):
        from broodforge_dashboard import _build_dynamic_health_subcard
        dynamic = DynamicHealthScore(not_implemented=True, overall=-1)
        html = _build_dynamic_health_subcard(dynamic)
        assert "not" in html.lower() or "implement" in html.lower() or "configur" in html.lower()

    def test_scores_shown_when_implemented(self):
        from broodforge_dashboard import _build_dynamic_health_subcard
        dynamic = DynamicHealthScore(
            hypothesis_failures=0,
            mutation_score_pct=78.0,
            bats_passed=4,
            bats_total=5,
            bats_failed=1,
            overall=82,
        )
        html = _build_dynamic_health_subcard(dynamic)
        assert "82" in html or "78" in html or "4" in html

    def test_hypothesis_failures_highlighted(self):
        from broodforge_dashboard import _build_dynamic_health_subcard
        dynamic = DynamicHealthScore(hypothesis_failures=3, overall=60)
        html = _build_dynamic_health_subcard(dynamic)
        assert "3" in html or "hypothesis" in html.lower()

    def test_subcard_returns_html_string(self):
        from broodforge_dashboard import _build_dynamic_health_subcard
        dynamic = DynamicHealthScore(overall=100, not_implemented=False)
        html = _build_dynamic_health_subcard(dynamic)
        assert isinstance(html, str)
        assert "<" in html


# ---------------------------------------------------------------------------
# Fix 2 — code_health_to_remediation_candidates() in continuous_assessment.py
# ---------------------------------------------------------------------------

class TestCodeHealthCandidatesInContinuousAssessment:
    """Verify the authoritative remediation-candidate logic lives in continuous_assessment."""

    def test_high_bandit_produces_candidate(self):
        score = CodeHealthScore(bandit_high_count=2, overall=60)
        candidates = code_health_to_remediation_candidates(score)
        assert len(candidates) == 1
        assert candidates[0]["severity"] == "HIGH"
        assert "bandit" in candidates[0]["description"].lower()
        assert candidates[0]["source"] == "assess_code_health/bandit"

    def test_clean_static_no_candidates(self):
        score = CodeHealthScore(bandit_high_count=0, shellcheck_findings=0, overall=95)
        assert code_health_to_remediation_candidates(score) == []

    def test_shellcheck_threshold_5(self):
        below = CodeHealthScore(shellcheck_findings=4, overall=88)
        at_threshold = CodeHealthScore(shellcheck_findings=5, overall=85)
        assert code_health_to_remediation_candidates(below) == []
        assert len(code_health_to_remediation_candidates(at_threshold)) == 1

    def test_candidate_has_required_keys(self):
        score = CodeHealthScore(bandit_high_count=1, overall=70)
        candidates = code_health_to_remediation_candidates(score)
        c = candidates[0]
        assert "type" in c and "severity" in c and "description" in c
        assert "source" in c and "proposed_at" in c

    def test_dashboard_wrapper_delegates_to_ca(self):
        """broodforge_dashboard._code_health_to_remediation_candidates delegates to ca."""
        from broodforge_dashboard import _code_health_to_remediation_candidates as _dash
        score = CodeHealthScore(bandit_high_count=1, overall=70)
        dash_result = _dash(score)
        ca_result = code_health_to_remediation_candidates(score)
        # Strip proposed_at before comparing — both calls use datetime.now() so
        # microseconds differ; the test verifies delegation, not timestamp equality.
        def _strip_ts(candidates):
            return [{k: v for k, v in c.items() if k != "proposed_at"} for c in candidates]
        assert _strip_ts(dash_result) == _strip_ts(ca_result)


class TestDynamicHealthCandidatesInContinuousAssessment:
    """Verify dynamic_health_to_remediation_candidates in continuous_assessment."""

    def test_hypothesis_failures_produce_high(self):
        score = DynamicHealthScore(hypothesis_failures=2, overall=60)
        candidates = dynamic_health_to_remediation_candidates(score)
        assert any(c["severity"] == "HIGH" and "hypothesis" in c["description"].lower()
                   for c in candidates)

    def test_not_implemented_returns_empty(self):
        score = DynamicHealthScore(not_implemented=True, overall=-1)
        assert dynamic_health_to_remediation_candidates(score) == []

    def test_error_returns_empty(self):
        score = DynamicHealthScore(error="subprocess failed", overall=-1)
        assert dynamic_health_to_remediation_candidates(score) == []

    def test_low_mutation_score_high_severity(self):
        score = DynamicHealthScore(mutation_score_pct=30.0, overall=65)
        candidates = dynamic_health_to_remediation_candidates(score)
        assert any(c["severity"] == "HIGH" and "mutation" in c["description"].lower()
                   for c in candidates)

    def test_medium_mutation_score_medium_severity(self):
        score = DynamicHealthScore(mutation_score_pct=60.0, overall=80)
        candidates = dynamic_health_to_remediation_candidates(score)
        assert any(c["severity"] == "MEDIUM" and "mutation" in c["description"].lower()
                   for c in candidates)

    def test_bats_failures_produce_high(self):
        score = DynamicHealthScore(bats_failed=2, bats_total=5, bats_passed=3, overall=80)
        candidates = dynamic_health_to_remediation_candidates(score)
        assert any(c["severity"] == "HIGH" and "bats" in c["description"].lower()
                   for c in candidates)

    def test_clean_dynamic_no_candidates(self):
        score = DynamicHealthScore(
            hypothesis_failures=0, mutation_score_pct=85.0,
            bats_failed=0, bats_total=5, bats_passed=5, overall=100,
        )
        assert dynamic_health_to_remediation_candidates(score) == []

    def test_dashboard_wrapper_merges_both(self):
        """Dashboard wrapper merges static + dynamic candidates correctly."""
        from broodforge_dashboard import _code_health_to_remediation_candidates as _dash
        static = CodeHealthScore(bandit_high_count=1, overall=70)
        dynamic = DynamicHealthScore(hypothesis_failures=1, overall=80)
        candidates = _dash(static, dynamic=dynamic)
        sources = {c["source"] for c in candidates}
        assert "assess_code_health/bandit" in sources
        assert "assess_dynamic_health/hypothesis" in sources


class TestCollectHealthRemediationCandidates:
    def test_returns_list(self, tmp_path):
        def _run(cmd, **kw):
            m = MagicMock()
            m.stdout = "[]" if "bandit" not in str(cmd) else '{"results":[]}'
            m.returncode = 0
            return m

        result = collect_health_remediation_candidates(str(tmp_path), run_fn=_run)
        assert isinstance(result, list)

    def test_clean_run_returns_empty(self, tmp_path):
        def _run(cmd, **kw):
            m = MagicMock()
            if "bandit" in str(cmd):
                m.stdout = '{"results":[]}'
            elif "shellcheck" in str(cmd):
                m.stdout = "[]"
            else:
                m.stdout = ""
            m.returncode = 0
            return m

        result = collect_health_remediation_candidates(str(tmp_path), run_fn=_run)
        assert result == []


# ---------------------------------------------------------------------------
# R7-002 — clock injection (now_fn) in candidate functions
# ---------------------------------------------------------------------------

class TestCandidateFunctionsClockInjection:
    """Verify now_fn is honoured in both candidate converter functions (R7-002 fix)."""

    _FIXED_NOW = "2026-01-01T00:00:00+00:00"

    def test_static_candidates_now_fn_injected(self):
        score = CodeHealthScore(bandit_high_count=1, overall=70)
        candidates = code_health_to_remediation_candidates(
            score, now_fn=lambda: self._FIXED_NOW
        )
        assert len(candidates) == 1
        assert candidates[0]["proposed_at"] == self._FIXED_NOW

    def test_dynamic_candidates_now_fn_injected(self):
        score = DynamicHealthScore(hypothesis_failures=1, overall=70)
        candidates = dynamic_health_to_remediation_candidates(
            score, now_fn=lambda: self._FIXED_NOW
        )
        assert any(c["proposed_at"] == self._FIXED_NOW for c in candidates)

    def test_collect_candidates_now_fn_propagated(self, tmp_path):
        def _run(cmd, **kw):
            m = MagicMock()
            if "bandit" in str(cmd):
                m.stdout = '{"results": [{"issue_severity": "HIGH", "issue_confidence": "HIGH", "filename": "x.py", "line_number": 1, "issue_text": "test", "test_id": "B001", "test_name": "test", "issue_cwe": {"id": 1, "link": "x"}, "more_info": "x"}]}'
            else:
                m.stdout = ""
            m.returncode = 0
            return m

        candidates = collect_health_remediation_candidates(
            str(tmp_path), run_fn=_run, now_fn=lambda: self._FIXED_NOW
        )
        assert all(c["proposed_at"] == self._FIXED_NOW for c in candidates)
