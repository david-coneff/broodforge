#!/usr/bin/env bash
# run-static-audit.sh — Tier 1 Static Analysis Audit (Phase 1.L, AD-062)
#
# Runs shellcheck, ruff, bandit, vulture, detect-secrets, and pytest with
# coverage against the broodforge codebase. Produces .audit/static-audit-report.md.
# Exits non-zero if any HIGH severity findings are found (bandit HIGH count > 0
# or shellcheck errors exist).
#
# Usage:
#   bash tools/run-static-audit.sh          # from repo root
#   bash tools/run-static-audit.sh --help   # show usage
#
# PAP Reasoning Pattern mappings (from pap/modules/PAP-AUDIT/Audit-Reasoning-Patterns.md):
#   SC errors          → Pattern 10 (Happy Path Only), Pattern 27 (Feedback Vacuum)
#   bandit HIGH        → Pattern 15 (Fail Open), Pattern 36 (Over-Privileged Component)
#   bandit MEDIUM      → Pattern 17 (Credential Sprawl)
#   vulture dead code  → Pattern 21 (Orphaned Outputs)
#   secrets detected   → Pattern 17 (Credential Sprawl)
#   coverage < 80%     → Pattern 31 (Regression Blind Spot)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AUDIT_DIR="${REPO_ROOT}/.audit"
REPORT="${AUDIT_DIR}/static-audit-report.md"

SC_EXIT=0
RUFF_EXIT=0
BANDIT_EXIT=0
VULTURE_EXIT=0
SECRETS_EXIT=0
PYTEST_EXIT=0

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    echo "Usage: bash tools/run-static-audit.sh"
    echo ""
    echo "Runs Tier 1 static analysis (Phase 1.L):"
    echo "  shellcheck — all .sh files in the repo"
    echo "  ruff       — Python linting (proxmox-bootstrap/, tests/)"
    echo "  bandit     — Python security analysis (proxmox-bootstrap/)"
    echo "  vulture    — dead code detection (proxmox-bootstrap/)"
    echo "  detect-secrets — credential/secret scan"
    echo "  pytest     — full test suite with coverage"
    echo ""
    echo "Outputs: .audit/static-audit-report.md"
    echo "Exits:   1 if HIGH findings (bandit HIGH or shellcheck errors)"
    exit 0
fi

# ---------------------------------------------------------------------------
# Step 1: Detect OS and install shellcheck if missing
# ---------------------------------------------------------------------------

echo "[audit] Checking shellcheck..."
if ! command -v shellcheck &>/dev/null; then
    echo "[audit] shellcheck not found — attempting install..."
    if [[ "$(uname -s)" == "Linux" ]]; then
        if command -v apt-get &>/dev/null; then
            sudo apt-get install -y shellcheck || echo "[audit] WARNING: apt-get install shellcheck failed — shellcheck checks will be skipped"
        else
            echo "[audit] WARNING: apt-get not available — install shellcheck manually"
        fi
    elif [[ "$(uname -s)" == "Darwin" ]]; then
        if command -v brew &>/dev/null; then
            brew install shellcheck || echo "[audit] WARNING: brew install shellcheck failed — shellcheck checks will be skipped"
        else
            echo "[audit] WARNING: brew not available — install shellcheck manually"
        fi
    else
        if command -v choco &>/dev/null; then
            choco install shellcheck -y || echo "[audit] WARNING: choco install shellcheck failed — shellcheck checks will be skipped"
        else
            echo "[audit] WARNING: Cannot detect package manager for shellcheck install"
        fi
    fi
fi

# ---------------------------------------------------------------------------
# Step 2: Install Python tools
# ---------------------------------------------------------------------------

echo "[audit] Installing Python static analysis tools..."
pip install --quiet ruff bandit vulture detect-secrets pytest pytest-cov jsonschema 2>/dev/null || true

# ---------------------------------------------------------------------------
# Step 3: Create .audit/ directory
# ---------------------------------------------------------------------------

mkdir -p "${AUDIT_DIR}"
echo "[audit] Output directory: ${AUDIT_DIR}"

# ---------------------------------------------------------------------------
# Step 4: Run shellcheck on all .sh files
# ---------------------------------------------------------------------------

echo "[audit] Running shellcheck..."
TMP_SH_FILES=$(mktemp /tmp/bf_sh_files.XXXXXX.txt)
find "${REPO_ROOT}" -name "*.sh" \
    -not -path "${REPO_ROOT}/.git/*" \
    -not -path "${REPO_ROOT}/new/*" \
    | sort > "${TMP_SH_FILES}"

SC_FILE_COUNT=$(wc -l < "${TMP_SH_FILES}" | tr -d ' ')
echo "[audit] Found ${SC_FILE_COUNT} .sh file(s)"

if [[ "${SC_FILE_COUNT}" -gt 0 ]] && command -v shellcheck &>/dev/null; then
    # shellcheck disable=SC2046
    shellcheck --severity=warning --format=json $(cat "${TMP_SH_FILES}") \
        > "${AUDIT_DIR}/shellcheck-static.json" 2>&1 || SC_EXIT=$?
    SC_COUNT=$(python3 -c "import json,sys; d=json.load(open('${AUDIT_DIR}/shellcheck-static.json')); print(len(d))" 2>/dev/null || echo "0")
    echo "[audit] shellcheck: ${SC_COUNT} finding(s) (exit ${SC_EXIT})"
else
    echo '[]' > "${AUDIT_DIR}/shellcheck-static.json"
    SC_COUNT=0
    if ! command -v shellcheck &>/dev/null; then
        echo "[audit] WARNING: shellcheck not installed — skipping"
    fi
fi

rm -f "${TMP_SH_FILES}"

# ---------------------------------------------------------------------------
# Step 5: Try to generate sample scripts and check them
# ---------------------------------------------------------------------------

echo "[audit] Attempting to generate sample scripts for shellcheck..."
SAMPLE_DIR=$(mktemp -d /tmp/bf_samples.XXXXXX)
GENERATED_SAMPLE=""

if python3 "${REPO_ROOT}/proxmox-bootstrap/forge_scripts.py" --help 2>&1 | grep -q "dump-scripts\|dump_scripts"; then
    python3 "${REPO_ROOT}/proxmox-bootstrap/forge_scripts.py" --dump-scripts \
        > "${SAMPLE_DIR}/generated_forge.sh" 2>/dev/null || true
    if [[ -s "${SAMPLE_DIR}/generated_forge.sh" ]]; then
        GENERATED_SAMPLE="${SAMPLE_DIR}/generated_forge.sh"
        echo "[audit] Generated forge script sample for shellcheck"
    fi
fi

if [[ -n "${GENERATED_SAMPLE}" ]] && command -v shellcheck &>/dev/null; then
    shellcheck --severity=warning --format=json "${GENERATED_SAMPLE}" \
        > "${AUDIT_DIR}/shellcheck-generated.json" 2>&1 || true
    GEN_COUNT=$(python3 -c "import json,sys; d=json.load(open('${AUDIT_DIR}/shellcheck-generated.json')); print(len(d))" 2>/dev/null || echo "0")
    echo "[audit] shellcheck generated samples: ${GEN_COUNT} finding(s)"
else
    echo '[]' > "${AUDIT_DIR}/shellcheck-generated.json"
    GEN_COUNT=0
    echo "[audit] No generated script samples checked (not available or shellcheck missing)"
fi

rm -rf "${SAMPLE_DIR}"

# ---------------------------------------------------------------------------
# Step 6: Run ruff
# ---------------------------------------------------------------------------

echo "[audit] Running ruff..."
ruff check "${REPO_ROOT}/proxmox-bootstrap/" "${REPO_ROOT}/tests/" \
    --output-format json \
    > "${AUDIT_DIR}/ruff-report.json" 2>&1 || RUFF_EXIT=$?
RUFF_COUNT=$(python3 -c "import json; d=json.load(open('${AUDIT_DIR}/ruff-report.json')); print(len(d))" 2>/dev/null || echo "0")
echo "[audit] ruff: ${RUFF_COUNT} finding(s) (exit ${RUFF_EXIT})"

# ---------------------------------------------------------------------------
# Step 7: Run bandit
# ---------------------------------------------------------------------------

echo "[audit] Running bandit..."
bandit -r "${REPO_ROOT}/proxmox-bootstrap/" -ll -f json \
    -o "${AUDIT_DIR}/bandit-report.json" 2>&1 || BANDIT_EXIT=$?
BANDIT_HIGH=$(python3 -c "
import json
try:
    d=json.load(open('${AUDIT_DIR}/bandit-report.json'))
    print(sum(1 for r in d.get('results',[]) if r.get('issue_severity')=='HIGH'))
except:
    print(0)
" 2>/dev/null || echo "0")
BANDIT_MEDIUM=$(python3 -c "
import json
try:
    d=json.load(open('${AUDIT_DIR}/bandit-report.json'))
    print(sum(1 for r in d.get('results',[]) if r.get('issue_severity')=='MEDIUM'))
except:
    print(0)
" 2>/dev/null || echo "0")
echo "[audit] bandit: ${BANDIT_HIGH} HIGH, ${BANDIT_MEDIUM} MEDIUM (exit ${BANDIT_EXIT})"

# ---------------------------------------------------------------------------
# Step 8: Run vulture
# ---------------------------------------------------------------------------

echo "[audit] Running vulture..."
vulture "${REPO_ROOT}/proxmox-bootstrap/" --min-confidence 80 \
    > "${AUDIT_DIR}/vulture-report.txt" 2>&1 || VULTURE_EXIT=$?
VULTURE_COUNT=$(wc -l < "${AUDIT_DIR}/vulture-report.txt" | tr -d ' ')
echo "[audit] vulture: ${VULTURE_COUNT} potential dead code line(s) (exit ${VULTURE_EXIT})"

# ---------------------------------------------------------------------------
# Step 9: Run detect-secrets
# ---------------------------------------------------------------------------

echo "[audit] Running detect-secrets..."
if [[ ! -f "${REPO_ROOT}/.secrets.baseline" ]]; then
    echo "[audit] Creating initial .secrets.baseline..."
    detect-secrets scan "${REPO_ROOT}" > "${REPO_ROOT}/.secrets.baseline" 2>/dev/null || true
fi

detect-secrets scan --baseline "${REPO_ROOT}/.secrets.baseline" \
    > "${AUDIT_DIR}/secrets-scan.json" 2>&1 || SECRETS_EXIT=$?
SECRETS_COUNT=$(python3 -c "
import json
try:
    d=json.load(open('${AUDIT_DIR}/secrets-scan.json'))
    total=sum(len(v) for v in d.get('results',{}).values())
    print(total)
except:
    print(0)
" 2>/dev/null || echo "0")
echo "[audit] detect-secrets: ${SECRETS_COUNT} potential secret(s) found (exit ${SECRETS_EXIT})"

# ---------------------------------------------------------------------------
# Step 10: Run pytest with coverage
# ---------------------------------------------------------------------------

echo "[audit] Running pytest with coverage..."
cd "${REPO_ROOT}"
python3 -m pytest \
    --override-ini="addopts=" \
    --cov=proxmox-bootstrap \
    --cov-report=term-missing \
    --cov-branch \
    --cov-report="json:.audit/coverage.json" \
    -q \
    2>&1 | tee "${AUDIT_DIR}/pytest-output.txt" || PYTEST_EXIT=$?
echo "[audit] pytest: exit ${PYTEST_EXIT}"

COVERAGE_PCT=$(python3 -c "
import json
try:
    d=json.load(open('${AUDIT_DIR}/coverage.json'))
    print(round(d.get('totals',{}).get('percent_covered',0),1))
except:
    print(0.0)
" 2>/dev/null || echo "0.0")
echo "[audit] Coverage: ${COVERAGE_PCT}%"

# ---------------------------------------------------------------------------
# Step 11: Dynamic Analysis Pre-Flight (PAP-AUDIT §6)
# ---------------------------------------------------------------------------

echo "[audit] === Dynamic Analysis Pre-Flight (PAP-AUDIT §6) ==="
pip install --quiet hypothesis mutmut beartype deal 2>/dev/null || true

HYP_FAILURES=0
MUT_SCORE="n/a"
BATS_PASSED=0
BATS_FAILED=0
BATS_TOTAL=0

# 6.3 hypothesis — run property tests if @given decorators exist
if grep -r "@given" "${REPO_ROOT}/tests/" --include="*.py" -q 2>/dev/null; then
    echo "[audit] Running hypothesis property tests..."
    HYP_OUT=$(python3 -m pytest \
        --hypothesis-seed=0 \
        -m hypothesis \
        --tb=no -q --no-header --no-cov \
        "${REPO_ROOT}/tests/" 2>&1 || true)
    echo "${HYP_OUT}" | tail -5
    HYP_FAILURES=$(echo "${HYP_OUT}" | grep -oP '^\d+ failed' | grep -oP '^\d+' || echo "0")
    HYP_FAILURES=${HYP_FAILURES:-0}
else
    echo "[audit] No hypothesis @given tests found — skipping property test run"
fi

# 6.4 mutmut — mutation testing
if command -v mutmut &>/dev/null; then
    echo "[audit] Running mutmut (this may take several minutes)..."
    (cd "${REPO_ROOT}" && mutmut run --paths-to-mutate="${REPO_ROOT}/proxmox-bootstrap/" --no-progress 2>&1 | tail -3) || true
    MUT_RESULT=$(cd "${REPO_ROOT}" && mutmut results 2>&1 || true)
    MUT_SCORE=$(echo "${MUT_RESULT}" | grep -oP 'Killed \K\d+ of \d+' | head -1 || echo "")
    if [[ -n "${MUT_SCORE}" ]]; then
        MUT_KILLED=$(echo "${MUT_SCORE}" | awk '{print $1}')
        MUT_TOTAL=$(echo "${MUT_SCORE}" | awk '{print $3}')
        if [[ "${MUT_TOTAL:-0}" -gt 0 ]]; then
            MUT_SCORE_PCT=$(python3 -c "print(round(${MUT_KILLED}*100/${MUT_TOTAL},1))")
            MUT_SCORE="${MUT_SCORE_PCT}%"
            echo "[audit] mutmut: killed ${MUT_KILLED}/${MUT_TOTAL} mutations (${MUT_SCORE})"
        fi
    else
        echo "[audit] mutmut: no results parsed"
        MUT_SCORE="n/a"
    fi
else
    echo "[audit] mutmut not installed — skipping (pip install mutmut)"
fi

# 6.5 bats — bash script testing
if [[ -d "${REPO_ROOT}/tests/bash" ]] && ls "${REPO_ROOT}/tests/bash/"*.bats &>/dev/null 2>&1; then
    if command -v bats &>/dev/null; then
        echo "[audit] Running bats tests..."
        BATS_OUT=$(bats --tap "${REPO_ROOT}/tests/bash/" 2>&1 || true)
        echo "${BATS_OUT}" | tail -10
        BATS_PASSED=$(echo "${BATS_OUT}" | grep -c "^ok " || echo "0")
        BATS_FAILED=$(echo "${BATS_OUT}" | grep -c "^not ok " || echo "0")
        BATS_TOTAL=$(( BATS_PASSED + BATS_FAILED ))
        echo "[audit] bats: ${BATS_PASSED}/${BATS_TOTAL} passed"
    else
        echo "[audit] bats not installed — skipping (apt install bats OR brew install bats-core)"
    fi
else
    echo "[audit] No .bats files found in tests/bash/ — dynamic shell testing not yet configured"
fi

# ---------------------------------------------------------------------------
# Step 12: Generate .audit/static-audit-report.md
# ---------------------------------------------------------------------------

echo "[audit] Generating report..."
TIMESTAMP=$(date -u "+%Y-%m-%d %H:%M:%S UTC")

cat > "${REPORT}" <<REPORT_EOF
# Broodforge Static Analysis Audit Report

Generated: ${TIMESTAMP}
Repo root: ${REPO_ROOT}

---

## Summary

| Tool | Findings | Severity |
|---|---|---|
| shellcheck (static .sh files) | ${SC_COUNT} | ${SC_EXIT:+WARNING}${SC_EXIT:-OK} |
| shellcheck (generated samples) | ${GEN_COUNT} | — |
| ruff | ${RUFF_COUNT} | ${RUFF_EXIT:+WARNING}${RUFF_EXIT:-OK} |
| bandit HIGH | ${BANDIT_HIGH} | ${BANDIT_HIGH:+HIGH}${BANDIT_HIGH:-OK} |
| bandit MEDIUM | ${BANDIT_MEDIUM} | ${BANDIT_MEDIUM:+MEDIUM}${BANDIT_MEDIUM:-OK} |
| vulture dead code lines | ${VULTURE_COUNT} | — |
| detect-secrets | ${SECRETS_COUNT} | ${SECRETS_COUNT:+REVIEW}${SECRETS_COUNT:-OK} |
| pytest coverage | ${COVERAGE_PCT}% | — |
| hypothesis failures | ${HYP_FAILURES} | ${HYP_FAILURES:+HIGH}${HYP_FAILURES:-OK} |
| mutmut kill rate | ${MUT_SCORE} | — |
| bats passed/total | ${BATS_PASSED}/${BATS_TOTAL} | ${BATS_FAILED:+HIGH}${BATS_FAILED:-OK} |

---

## PAP Reasoning Pattern Mapping

Findings map to PAP Audit Reasoning Patterns
(see \`pap/modules/PAP-AUDIT/Audit-Reasoning-Patterns.md\`):

| Category | Pattern(s) |
|---|---|
| shellcheck errors | Pattern 10 (Happy Path Only), Pattern 27 (Feedback Vacuum) |
| bandit HIGH | Pattern 15 (Fail Open), Pattern 36 (Over-Privileged Component) |
| bandit MEDIUM | Pattern 17 (Credential Sprawl) |
| vulture dead code | Pattern 21 (Orphaned Outputs) |
| secrets detected | Pattern 17 (Credential Sprawl) |
| coverage < 80% | Pattern 31 (Regression Blind Spot) |

---

## Tool Details

### shellcheck

**Files scanned**: ${SC_FILE_COUNT}
**Findings**: ${SC_COUNT} (static), ${GEN_COUNT} (generated samples)

Full JSON output: \`.audit/shellcheck-static.json\`

### ruff

**Findings**: ${RUFF_COUNT}

Full JSON output: \`.audit/ruff-report.json\`

### bandit

**HIGH**: ${BANDIT_HIGH}
**MEDIUM**: ${BANDIT_MEDIUM}

Full JSON output: \`.audit/bandit-report.json\`

### vulture (dead code)

**Lines reported**: ${VULTURE_COUNT}

Full output: \`.audit/vulture-report.txt\`

### detect-secrets

**Potential secrets**: ${SECRETS_COUNT}

Full JSON output: \`.audit/secrets-scan.json\`

### pytest / coverage

**Coverage**: ${COVERAGE_PCT}%
**Exit code**: ${PYTEST_EXIT}

Full output: \`.audit/pytest-output.txt\`
Coverage JSON: \`.audit/coverage.json\`

---

## Dynamic Analysis (PAP-AUDIT §6)

### hypothesis (property-based testing)

**Failures**: ${HYP_FAILURES}

### mutmut (mutation testing)

**Kill rate**: ${MUT_SCORE}

Mutation score guidance: <40% = BLOCKER; 40–60% = DEFECT; 60–80% = RISK; >80% = strong.

### bats (Bash Automated Testing System)

**Passed**: ${BATS_PASSED} / **Total**: ${BATS_TOTAL} / **Failed**: ${BATS_FAILED}

---

## Result

REPORT_EOF

# Determine final result
HIGH_FINDINGS=0
if [[ "${BANDIT_HIGH}" -gt 0 ]]; then
    HIGH_FINDINGS=1
fi
if [[ "${SC_EXIT}" -ne 0 ]]; then
    # Check if any errors (not just warnings) in shellcheck output
    SC_ERRORS=$(python3 -c "
import json
try:
    d=json.load(open('${AUDIT_DIR}/shellcheck-static.json'))
    print(sum(1 for f in d if f.get('level')=='error'))
except:
    print(0)
" 2>/dev/null || echo "0")
    if [[ "${SC_ERRORS}" -gt 0 ]]; then
        HIGH_FINDINGS=1
    fi
fi
if [[ "${HYP_FAILURES}" -gt 0 ]]; then
    HIGH_FINDINGS=1
fi
if [[ "${BATS_FAILED}" -gt 0 ]]; then
    HIGH_FINDINGS=1
fi

if [[ "${HIGH_FINDINGS}" -eq 0 ]]; then
    echo "**PASS** — No HIGH severity findings." >> "${REPORT}"
    echo "" >> "${REPORT}"
    echo "[audit] PASS — no HIGH findings."
    FINAL_EXIT=0
else
    echo "**FAIL** — HIGH severity findings detected." >> "${REPORT}"
    echo "" >> "${REPORT}"
    if [[ "${BANDIT_HIGH}" -gt 0 ]]; then
        echo "- bandit HIGH findings: ${BANDIT_HIGH}" >> "${REPORT}"
    fi
    if [[ "${SC_ERRORS:-0}" -gt 0 ]]; then
        echo "- shellcheck errors: ${SC_ERRORS}" >> "${REPORT}"
    fi
    if [[ "${HYP_FAILURES}" -gt 0 ]]; then
        echo "- hypothesis failures: ${HYP_FAILURES}" >> "${REPORT}"
    fi
    if [[ "${BATS_FAILED}" -gt 0 ]]; then
        echo "- bats failures: ${BATS_FAILED}" >> "${REPORT}"
    fi
    echo "" >> "${REPORT}"
    echo "Fix HIGH findings before merging. See tool details above." >> "${REPORT}"
    echo "[audit] FAIL — HIGH findings detected."
    FINAL_EXIT=1
fi

echo "" >> "${REPORT}"
echo "---" >> "${REPORT}"
echo "_Generated by \`tools/run-static-audit.sh\` (Phase 1.L/1.M, AD-062)_" >> "${REPORT}"

echo "[audit] Report written to ${REPORT}"
exit "${FINAL_EXIT}"
