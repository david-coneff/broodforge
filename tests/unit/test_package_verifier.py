"""
Tests for proxmox-bootstrap/package_verifier.py (Phase 1.N, R8-003).

Covers:
  - _collect_files() excludes package-descriptor.json (self-exclusion + suffix rule)
  - _collect_files() is deterministic across two calls
  - _collect_files() excludes files with excluded suffixes (.json, .toml, .log, .lock, .jsonl)
  - _collect_files() excludes files under excluded directories (__pycache__, .audit, backups)
  - _collect_files() excludes .secrets.baseline by name
  - stamp() creates package-descriptor.json with the required keys
  - verify() returns 0 when package is unmodified after stamp
  - verify() returns 1 when stored hash does not match current hash

Run: pytest tests/unit/test_package_verifier.py -v
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
BOOTSTRAP_REPO = REPO_ROOT / "proxmox-bootstrap"


# ---------------------------------------------------------------------------
# Module loader helpers
# ---------------------------------------------------------------------------

def _load_verifier():
    """Load package_verifier as a fresh module instance (real REPO_ROOT)."""
    spec = importlib.util.spec_from_file_location(
        "package_verifier", BOOTSTRAP_REPO / "package_verifier.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _load_verifier_with_descriptor(tmp_path: Path):
    """Load package_verifier with DESCRIPTOR_PATH redirected into tmp_path.

    stamp() and verify() use DESCRIPTOR_PATH at call time (global lookup),
    so reassigning the attribute on the loaded module object is sufficient.
    _collect_files() continues to scan the real repo root — only the descriptor
    write/read target is redirected.
    """
    pv = _load_verifier()
    pv.DESCRIPTOR_PATH = tmp_path / "package-descriptor.json"
    return pv


# ---------------------------------------------------------------------------
# _collect_files() tests
# ---------------------------------------------------------------------------

def test_descriptor_self_excluded():
    """package-descriptor.json must never appear in _collect_files() output.

    The file is excluded both by the .json suffix rule and by the explicit
    self-exclusion guard (circular-dependency protection).
    """
    pv = _load_verifier()
    files = pv._collect_files()
    result_names = {f.name for f in files}
    assert "package-descriptor.json" not in result_names, (
        "package-descriptor.json was found in _collect_files() output — "
        "self-exclusion or .json suffix exclusion is broken"
    )


def test_hash_determinism():
    """Two consecutive calls to _collect_files() must return identical file lists,
    and compute_hash() must produce the same digest for both."""
    pv = _load_verifier()
    files1 = pv._collect_files()
    files2 = pv._collect_files()
    assert files1 == files2, (
        "_collect_files() returned different results on two calls — not deterministic"
    )
    digest1, _ = pv.compute_hash(files1)
    digest2, _ = pv.compute_hash(files2)
    assert digest1 == digest2, (
        "compute_hash() returned different digests for identical file lists"
    )


def test_excluded_suffixes():
    """Files with excluded suffixes must not appear in _collect_files() output.

    Excluded: .json, .toml, .log, .lock, .jsonl, .pyc, .pyo
    """
    pv = _load_verifier()
    files = pv._collect_files()
    excluded_suffixes = {".json", ".toml", ".log", ".lock", ".jsonl", ".pyc", ".pyo"}
    bad = [f for f in files if f.suffix in excluded_suffixes]
    assert not bad, (
        f"_collect_files() returned files with excluded suffixes: "
        f"{[str(f) for f in bad[:5]]}"
    )


def test_excluded_dirs():
    """Files under excluded directories must not appear in _collect_files() output.

    Excluded directory components: __pycache__, .audit, backups
    """
    pv = _load_verifier()
    files = pv._collect_files()
    excluded_dirs = {"__pycache__", ".audit", "backups"}
    bad = [f for f in files if any(part in excluded_dirs for part in f.parts)]
    assert not bad, (
        f"_collect_files() returned files from excluded directories: "
        f"{[str(f) for f in bad[:5]]}"
    )


def test_excluded_names():
    """.secrets.baseline must not appear in _collect_files() output."""
    pv = _load_verifier()
    files = pv._collect_files()
    result_names = {f.name for f in files}
    assert ".secrets.baseline" not in result_names, (
        ".secrets.baseline was found in _collect_files() output — "
        "excluded-names rule is broken"
    )


# ---------------------------------------------------------------------------
# stamp() tests
# ---------------------------------------------------------------------------

def test_stamp_creates_descriptor(tmp_path: Path):
    """stamp() must create package-descriptor.json with the required top-level keys."""
    pv = _load_verifier_with_descriptor(tmp_path)
    pv.stamp()

    descriptor_path = tmp_path / "package-descriptor.json"
    assert descriptor_path.exists(), "stamp() did not create package-descriptor.json"

    data = json.loads(descriptor_path.read_text(encoding="utf-8"))
    for key in ("schema_version", "package_hash", "stamped_at", "files_hashed"):
        assert key in data, f"stamp() descriptor is missing required key: {key!r}"

    assert isinstance(data["files_hashed"], list), "files_hashed must be a list"
    assert len(data["package_hash"]) == 64, (
        f"package_hash must be a 64-char hex SHA-256 digest, "
        f"got {len(data['package_hash'])} chars"
    )


# ---------------------------------------------------------------------------
# verify() tests
# ---------------------------------------------------------------------------

def test_verify_pass(tmp_path: Path):
    """verify() must return 0 when package is stamped and then immediately verified."""
    pv = _load_verifier_with_descriptor(tmp_path)
    pv.stamp()
    result = pv.verify()
    assert result == 0, f"verify() returned {result} instead of 0 (OK) after fresh stamp"


def test_verify_fail(tmp_path: Path):
    """verify() must return 1 when the stored hash does not match the current hash.

    Simulates what happens after a file is modified post-stamp by corrupting
    the stored package_hash directly.
    """
    pv = _load_verifier_with_descriptor(tmp_path)
    pv.stamp()

    # Corrupt the stored hash (simulates a modified file changing the digest)
    descriptor_path = tmp_path / "package-descriptor.json"
    data = json.loads(descriptor_path.read_text(encoding="utf-8"))
    data["package_hash"] = "0" * 64   # definitely wrong
    descriptor_path.write_text(json.dumps(data), encoding="utf-8")

    result = pv.verify()
    assert result == 1, (
        f"verify() returned {result} instead of 1 (MISMATCH) when hash was corrupted"
    )


def test_verify_missing_descriptor(tmp_path: Path):
    """verify() must return 2 when no descriptor has been created yet.

    This is the expected state on a fresh clone before forge-stamp-version.sh
    has been run.  The verifier must not crash — it must return exit code 2
    so callers (e.g. forge-migrate.sh) can distinguish 'not stamped yet'
    from 'hash mismatch'.
    """
    pv = _load_verifier_with_descriptor(tmp_path)
    # DESCRIPTOR_PATH is redirected into tmp_path but the file does not exist yet
    assert not pv.DESCRIPTOR_PATH.exists(), "Precondition: descriptor must not exist"
    result = pv.verify()
    assert result == 2, (
        f"verify() returned {result} instead of 2 (DESCRIPTOR_NOT_FOUND) "
        "when no descriptor exists"
    )


# ===========================================================================
# State descriptor tests
# ===========================================================================
#
# These tests exercise the three public state verifier functions:
#   collect_state_files(), stamp_state_descriptor(), verify_state_descriptor()
#
# Each test builds a scratch state_dir in tmp_path to avoid touching real
# state files on disk and to keep tests hermetic.


def _load_verifier_with_state_descriptor(tmp_path: Path):
    """Load package_verifier with both descriptors redirected into tmp_path.

    This redirects _DEFAULT_STATE_DESCRIPTOR_PATH so that stamp_state_descriptor
    and verify_state_descriptor use a temp location, while still scanning the
    real repo root for state files via collect_state_files().
    """
    pv = _load_verifier_with_descriptor(tmp_path)
    pv._DEFAULT_STATE_DESCRIPTOR_PATH = tmp_path / "state-descriptor.json"
    return pv


def _make_state_dir(tmp_path: Path, files: dict) -> Path:
    """Create a scratch state directory with the given filename → content map."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    for name, content in files.items():
        (state_dir / name).write_text(content, encoding="utf-8")
    return state_dir


# ---------------------------------------------------------------------------
# collect_state_files() tests
# ---------------------------------------------------------------------------

def test_state_descriptor_self_excluded(tmp_path: Path):
    """state-descriptor.json must never appear in collect_state_files() output.

    The file records its own hash — including it would create a self-reference
    loop (hash unknown before writing; writing changes the hash).
    """
    pv = _load_verifier()
    state_dir = _make_state_dir(tmp_path, {
        "bootstrap-state.json": '{"schema_version": "test"}',
        "state-descriptor.json": '{"state_hash": "aaa"}',  # must be excluded
    })
    descriptor_path = state_dir / "state-descriptor.json"
    files = pv.collect_state_files(state_dir, descriptor_path)
    result_names = {f.name for f in files}
    assert "state-descriptor.json" not in result_names, (
        "state-descriptor.json was found in collect_state_files() output — "
        "self-reference loop protection is broken"
    )


def test_package_descriptor_excluded_from_state(tmp_path: Path):
    """package-descriptor.json must never appear in collect_state_files() output.

    MUTUAL EXCLUSION rule: neither descriptor is ever included in the other's
    content set.  package-descriptor.json records static source integrity and
    must not appear in the state hash.
    """
    pv = _load_verifier()
    state_dir = _make_state_dir(tmp_path, {
        "bootstrap-state.json": '{"schema_version": "test"}',
        "package-descriptor.json": '{"package_hash": "bbb"}',  # must be excluded
    })
    descriptor_path = tmp_path / "state-descriptor.json"
    files = pv.collect_state_files(state_dir, descriptor_path)
    result_names = {f.name for f in files}
    assert "package-descriptor.json" not in result_names, (
        "package-descriptor.json was found in collect_state_files() output — "
        "mutual exclusion rule is broken"
    )


def test_source_files_excluded_from_state(tmp_path: Path):
    """Source files (.py, .sh, .md) must not appear in collect_state_files() output.

    These file types belong in the package hash, not the state hash.
    The state globs only match *.json and *.toml — this test confirms that
    source-file extensions placed in the state_dir are not included.
    """
    pv = _load_verifier()
    state_dir = _make_state_dir(tmp_path, {
        "bootstrap-state.json": '{"schema_version": "test"}',
        "setup.py": "# python source",       # must be excluded
        "setup.sh": "#!/usr/bin/env bash",   # must be excluded
        "README.md": "# doc",                # must be excluded
    })
    descriptor_path = tmp_path / "state-descriptor.json"
    files = pv.collect_state_files(state_dir, descriptor_path)
    result_names = {f.name for f in files}
    for excluded in ("setup.py", "setup.sh", "README.md"):
        assert excluded not in result_names, (
            f"{excluded!r} was found in collect_state_files() output — "
            "source files must not appear in the state hash"
        )


# ---------------------------------------------------------------------------
# stamp_state_descriptor() tests
# ---------------------------------------------------------------------------

def test_stamp_state_creates_descriptor(tmp_path: Path):
    """stamp_state_descriptor() must create state-descriptor.json with required keys."""
    pv = _load_verifier()
    state_dir = _make_state_dir(tmp_path, {
        "bootstrap-state.json": '{"schema_version": "test"}',
    })
    descriptor_path = tmp_path / "state-descriptor.json"

    from datetime import datetime, timezone
    fixed_now = datetime(2026, 6, 9, 12, 0, 0, tzinfo=timezone.utc)

    result = pv.stamp_state_descriptor(
        state_dir, descriptor_path, now_fn=lambda: fixed_now
    )

    assert descriptor_path.exists(), "stamp_state_descriptor() did not create state-descriptor.json"

    data = json.loads(descriptor_path.read_text(encoding="utf-8"))
    for key in ("state_hash", "stamped_at", "state_dir", "files_hashed"):
        assert key in data, f"stamp_state_descriptor() descriptor is missing required key: {key!r}"

    # schema_version must NOT appear in the state descriptor (belongs to package descriptor only)
    assert "schema_version" not in data, (
        "schema_version must not appear in the state descriptor — "
        "it belongs to the package descriptor only"
    )

    assert isinstance(data["files_hashed"], list), "files_hashed must be a list"
    assert len(data["state_hash"]) == 64, (
        f"state_hash must be a 64-char hex SHA-256 digest, "
        f"got {len(data['state_hash'])} chars"
    )
    assert data["stamped_at"] == "2026-06-09T12:00:00Z", (
        "now_fn clock injection did not produce expected timestamp"
    )


# ---------------------------------------------------------------------------
# verify_state_descriptor() tests
# ---------------------------------------------------------------------------

def test_verify_state_pass(tmp_path: Path):
    """verify_state_descriptor() must return (True, []) immediately after stamping."""
    pv = _load_verifier()
    state_dir = _make_state_dir(tmp_path, {
        "bootstrap-state.json": '{"schema_version": "test"}',
        "manifest.toml": 'cell = "primary"',
    })
    descriptor_path = tmp_path / "state-descriptor.json"

    pv.stamp_state_descriptor(state_dir, descriptor_path)
    ok, errors = pv.verify_state_descriptor(state_dir, descriptor_path)

    assert ok is True, (
        f"verify_state_descriptor() returned ok=False after fresh stamp; errors: {errors}"
    )
    assert errors == [], f"verify_state_descriptor() returned non-empty errors on pass: {errors}"


def test_verify_state_fail(tmp_path: Path):
    """verify_state_descriptor() must return (False, [...]) when the stored hash is wrong.

    Simulates post-stamp state mutation by corrupting the stored state_hash directly,
    mirroring the same pattern used in test_verify_fail() for the package descriptor.
    """
    pv = _load_verifier()
    state_dir = _make_state_dir(tmp_path, {
        "bootstrap-state.json": '{"schema_version": "test"}',
    })
    descriptor_path = tmp_path / "state-descriptor.json"

    pv.stamp_state_descriptor(state_dir, descriptor_path)

    # Corrupt the stored hash (simulates a state file change after stamp)
    data = json.loads(descriptor_path.read_text(encoding="utf-8"))
    data["state_hash"] = "0" * 64   # definitely wrong
    descriptor_path.write_text(json.dumps(data), encoding="utf-8")

    ok, errors = pv.verify_state_descriptor(state_dir, descriptor_path)

    assert ok is False, (
        "verify_state_descriptor() returned ok=True even with a corrupted state_hash"
    )
    assert errors, "verify_state_descriptor() returned empty errors on mismatch"
    assert any("mismatch" in e for e in errors), (
        f"Expected a 'mismatch' message in errors, got: {errors}"
    )


def test_verify_state_missing_descriptor(tmp_path: Path):
    """verify_state_descriptor() must return (False, errors) with 'not found' message
    when no state descriptor exists yet.

    This is the expected state before forge-stamp-state.sh has been run.
    Callers use the 'not found' substring in errors[0] to map to exit code 2.
    """
    pv = _load_verifier()
    state_dir = _make_state_dir(tmp_path, {
        "bootstrap-state.json": '{"schema_version": "test"}',
    })
    descriptor_path = tmp_path / "state-descriptor.json"
    assert not descriptor_path.exists(), "Precondition: descriptor must not exist"

    ok, errors = pv.verify_state_descriptor(state_dir, descriptor_path)

    assert ok is False, (
        "verify_state_descriptor() returned ok=True when descriptor is absent"
    )
    assert errors, "verify_state_descriptor() returned empty errors when descriptor is absent"
    assert any("not found" in e for e in errors), (
        f"Expected 'not found' in errors so callers can map to exit code 2, got: {errors}"
    )
