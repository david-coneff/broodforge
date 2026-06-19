"""
tests/unit/test_version_stamp.py — Unit tests for version_stamp.py

Covers: schema loading, _parse_schema_builtin, HashRules extraction,
_should_include, compute_codebase_hash, generate_stamp, CLI flags.
"""
from __future__ import annotations

import hashlib
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "proxmox-bootstrap"))
from version_stamp import (
    HashRules,
    _parse_schema_builtin,
    _rules_from_schema,
    _load_schema,
    _schema_path,
    _should_include,
    compute_codebase_hash,
    generate_stamp,
    main,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_MINIMAL_SCHEMA = {
    "schema_version": 1,
    "hash": {"algorithm": "sha256", "truncate_chars": 8},
    "include": {"extensions": [{"ext": ".py"}, {"ext": ".sh"}, {"ext": ".yaml"},
                                {"ext": ".yml"}, {"ext": ".toml"}, {"ext": ".bats"}]},
    "exclude": {
        "extensions": [{"ext": ".md"}, {"ext": ".html"}, {"ext": ".pdf"},
                       {"ext": ".txt"}, {"ext": ".png"}, {"ext": ".jpg"},
                       {"ext": ".jpeg"}, {"ext": ".gif"}, {"ext": ".svg"},
                       {"ext": ".ico"}, {"ext": ".zip"}, {"ext": ".tar"},
                       {"ext": ".gz"}, {"ext": ".bz2"}],
        "directories": [
            {"name": ".git"}, {"name": ".ai"}, {"name": "pap"},
            {"name": "docs"}, {"name": "__pycache__"}, {"name": ".pytest_cache"},
            {"name": ".mypy_cache"}, {"name": ".ruff_cache"},
            {"name": "node_modules"},
        ],
    },
}


@pytest.fixture()
def rules() -> HashRules:
    return _rules_from_schema(_MINIMAL_SCHEMA)


def _make_schema_file(repo_root: Path) -> None:
    """Write the minimal schema into the expected location."""
    schema_dir = repo_root / "proxmox-bootstrap"
    schema_dir.mkdir(exist_ok=True)
    import yaml  # may raise ImportError — but tests using this fixture need yaml or the builtin parser
    schema_path = schema_dir / "version-hash-schema.yaml"
    # Write as a simple YAML that the builtin parser can also handle
    lines = [
        "schema_version: 1\n",
        "hash:\n",
        "  algorithm: sha256\n",
        "  truncate_chars: 8\n",
        "include:\n",
        "  extensions:\n",
    ]
    for e in [".py", ".sh", ".yaml", ".yml", ".toml", ".bats"]:
        lines.append(f'    - ext: "{e}"\n')
    lines.append("exclude:\n  extensions:\n")
    for e in [".md", ".html", ".pdf", ".txt", ".png", ".jpg", ".jpeg",
              ".gif", ".svg", ".ico", ".zip", ".tar", ".gz", ".bz2"]:
        lines.append(f'    - ext: "{e}"\n')
    lines.append("  directories:\n")
    for d in [".git", ".ai", "pap", "docs", "__pycache__",
              ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules"]:
        lines.append(f'    - name: "{d}"\n')
    schema_path.write_text("".join(lines))


# ---------------------------------------------------------------------------
# _parse_schema_builtin
# ---------------------------------------------------------------------------

class TestParseSchemaBuiltin:
    _YAML = textwrap.dedent("""\
        schema_version: 1
        include:
          extensions:
            - ext: ".py"
              reason: Python
            - ext: ".sh"
              reason: Shell
        exclude:
          extensions:
            - ext: ".md"
              reason: Markdown docs
            - ext: ".html"
              reason: HTML
          directories:
            - name: ".git"
              reason: VCS metadata
            - name: "pap"
              reason: PAP docs
            - name: "chatgpt architecture"
              reason: Removed corpus
    """)

    def test_parses_include_exts(self):
        schema = _parse_schema_builtin(self._YAML)
        exts = [e["ext"] for e in schema["include"]["extensions"]]
        assert ".py" in exts and ".sh" in exts

    def test_parses_exclude_exts(self):
        schema = _parse_schema_builtin(self._YAML)
        exts = [e["ext"] for e in schema["exclude"]["extensions"]]
        assert ".md" in exts and ".html" in exts

    def test_parses_exclude_dirs(self):
        schema = _parse_schema_builtin(self._YAML)
        dirs = [d["name"] for d in schema["exclude"]["directories"]]
        assert ".git" in dirs and "pap" in dirs

    def test_handles_space_in_dir_name(self):
        schema = _parse_schema_builtin(self._YAML)
        dirs = [d["name"] for d in schema["exclude"]["directories"]]
        assert "chatgpt architecture" in dirs

    def test_empty_text_produces_empty_lists(self):
        schema = _parse_schema_builtin("schema_version: 1\n")
        assert schema["include"]["extensions"] == []
        assert schema["exclude"]["extensions"] == []
        assert schema["exclude"]["directories"] == []


# ---------------------------------------------------------------------------
# _rules_from_schema
# ---------------------------------------------------------------------------

class TestRulesFromSchema:
    def test_include_exts_lowercased(self):
        rules = _rules_from_schema(_MINIMAL_SCHEMA)
        assert ".py" in rules.include_exts
        assert ".YAML" not in rules.include_exts  # always lower

    def test_exclude_exts_present(self):
        rules = _rules_from_schema(_MINIMAL_SCHEMA)
        assert ".md" in rules.exclude_exts

    def test_exclude_dirs_present(self):
        rules = _rules_from_schema(_MINIMAL_SCHEMA)
        assert ".git" in rules.exclude_dirs
        assert "pap" in rules.exclude_dirs

    def test_empty_schema_produces_empty_rules(self):
        rules = _rules_from_schema({})
        assert len(rules.include_exts) == 0
        assert len(rules.exclude_exts) == 0
        assert len(rules.exclude_dirs) == 0


# ---------------------------------------------------------------------------
# _should_include
# ---------------------------------------------------------------------------

class TestShouldInclude:
    def test_python_file_included(self, tmp_path, rules):
        f = tmp_path / "foo.py"
        f.write_text("x = 1")
        assert _should_include(f, tmp_path, rules) is True

    def test_shell_file_included(self, tmp_path, rules):
        f = tmp_path / "foo.sh"
        f.write_text("#!/bin/bash")
        assert _should_include(f, tmp_path, rules) is True

    def test_yaml_included(self, tmp_path, rules):
        f = tmp_path / "config.yaml"
        f.write_text("key: value")
        assert _should_include(f, tmp_path, rules) is True

    def test_toml_included(self, tmp_path, rules):
        f = tmp_path / "pyproject.toml"
        f.write_text("[tool.ruff]")
        assert _should_include(f, tmp_path, rules) is True

    def test_bats_included(self, tmp_path, rules):
        f = tmp_path / "test_forge.bats"
        f.write_text("@test 'ok' { true; }")
        assert _should_include(f, tmp_path, rules) is True

    def test_markdown_excluded(self, tmp_path, rules):
        f = tmp_path / "ROADMAP.md"
        f.write_text("# Roadmap")
        assert _should_include(f, tmp_path, rules) is False

    def test_html_excluded(self, tmp_path, rules):
        f = tmp_path / "ROADMAP.html"
        f.write_text("<html></html>")
        assert _should_include(f, tmp_path, rules) is False

    def test_pdf_excluded(self, tmp_path, rules):
        f = tmp_path / "spec.pdf"
        f.write_bytes(b"%PDF-1.4")
        assert _should_include(f, tmp_path, rules) is False

    def test_git_dir_excluded(self, tmp_path, rules):
        d = tmp_path / ".git"
        d.mkdir()
        py = d / "hook.py"
        py.write_text("x=1")
        assert _should_include(py, tmp_path, rules) is False

    def test_hidden_dir_excluded(self, tmp_path, rules):
        d = tmp_path / ".somecache"
        d.mkdir()
        f = d / "data.py"
        f.write_text("x=1")
        assert _should_include(f, tmp_path, rules) is False

    def test_ai_dir_excluded(self, tmp_path, rules):
        d = tmp_path / ".ai"
        d.mkdir()
        f = d / "context.py"
        f.write_text("x=1")
        assert _should_include(f, tmp_path, rules) is False

    def test_pap_dir_excluded(self, tmp_path, rules):
        d = tmp_path / "pap"
        d.mkdir()
        f = d / "audit.py"
        f.write_text("x=1")
        assert _should_include(f, tmp_path, rules) is False

    def test_docs_dir_excluded(self, tmp_path, rules):
        d = tmp_path / "docs"
        d.mkdir()
        f = d / "helper.py"
        f.write_text("x=1")
        assert _should_include(f, tmp_path, rules) is False

    def test_nested_excluded_dir(self, tmp_path, rules):
        d = tmp_path / "pap" / "modules"
        d.mkdir(parents=True)
        f = d / "tool.py"
        f.write_text("x=1")
        assert _should_include(f, tmp_path, rules) is False

    def test_nested_included_file(self, tmp_path, rules):
        d = tmp_path / "proxmox-bootstrap"
        d.mkdir()
        f = d / "manager.py"
        f.write_text("x=1")
        assert _should_include(f, tmp_path, rules) is True

    def test_directory_not_included(self, tmp_path, rules):
        d = tmp_path / "mydir.py"
        d.mkdir()
        assert _should_include(d, tmp_path, rules) is False

    def test_unknown_extension_excluded(self, tmp_path, rules):
        f = tmp_path / "data.csv"
        f.write_text("a,b,c")
        assert _should_include(f, tmp_path, rules) is False

    def test_extension_check_case_insensitive(self, tmp_path, rules):
        f = tmp_path / "script.PY"
        f.write_text("x=1")
        assert _should_include(f, tmp_path, rules) is True


# ---------------------------------------------------------------------------
# compute_codebase_hash
# ---------------------------------------------------------------------------

class TestComputeCodebaseHash:
    def test_returns_eight_hex_chars(self, tmp_path, rules):
        (tmp_path / "foo.py").write_text("x=1")
        h = compute_codebase_hash(tmp_path, rules=rules)
        assert len(h) == 8
        assert all(c in "0123456789abcdef" for c in h)

    def test_deterministic(self, tmp_path, rules):
        (tmp_path / "a.py").write_text("x=1")
        (tmp_path / "b.sh").write_text("#!/bin/bash")
        assert compute_codebase_hash(tmp_path, rules=rules) == \
               compute_codebase_hash(tmp_path, rules=rules)

    def test_changes_on_content_change(self, tmp_path, rules):
        p = tmp_path / "foo.py"
        p.write_text("x=1")
        h1 = compute_codebase_hash(tmp_path, rules=rules)
        p.write_text("x=2")
        assert compute_codebase_hash(tmp_path, rules=rules) != h1

    def test_changes_on_rename(self, tmp_path, rules):
        p = tmp_path / "foo.py"
        p.write_text("x=1")
        h1 = compute_codebase_hash(tmp_path, rules=rules)
        p.rename(tmp_path / "bar.py")
        assert compute_codebase_hash(tmp_path, rules=rules) != h1

    def test_doc_files_do_not_affect_hash(self, tmp_path, rules):
        (tmp_path / "foo.py").write_text("x=1")
        h1 = compute_codebase_hash(tmp_path, rules=rules)
        (tmp_path / "ROADMAP.md").write_text("# Updated roadmap")
        assert compute_codebase_hash(tmp_path, rules=rules) == h1

    def test_pap_files_do_not_affect_hash(self, tmp_path, rules):
        (tmp_path / "foo.py").write_text("x=1")
        h1 = compute_codebase_hash(tmp_path, rules=rules)
        pap = tmp_path / "pap"
        pap.mkdir()
        (pap / "state.py").write_text("state = {}")
        assert compute_codebase_hash(tmp_path, rules=rules) == h1

    def test_raises_when_no_files(self, tmp_path, rules):
        (tmp_path / "README.md").write_text("# hi")
        with pytest.raises(RuntimeError, match="No codebase files found"):
            compute_codebase_hash(tmp_path, rules=rules)

    def test_hash_matches_manual_computation(self, tmp_path, rules):
        """Hash must equal SHA-256 of (sorted path+NUL+content+NUL) concatenated."""
        files = {"a.py": "a", "m.sh": "m", "z.py": "z"}
        for name, content in files.items():
            (tmp_path / name).write_text(content)
        h = compute_codebase_hash(tmp_path, rules=rules)

        digest = hashlib.sha256()
        for rel in sorted(files):  # lexicographic order
            digest.update(rel.encode("utf-8"))
            digest.update(b"\x00")
            digest.update(files[rel].encode("utf-8"))
            digest.update(b"\x00")
        assert h == digest.hexdigest()[:8]

    def test_loads_schema_from_file_when_rules_none(self, tmp_path):
        """When rules=None, schema is loaded from proxmox-bootstrap/version-hash-schema.yaml."""
        schema_dir = tmp_path / "proxmox-bootstrap"
        schema_dir.mkdir()
        schema_yaml = (
            "schema_version: 1\n"
            "include:\n  extensions:\n    - ext: \".py\"\n"
            "exclude:\n  extensions:\n    - ext: \".md\"\n"
            "  directories:\n    - name: \".git\"\n"
        )
        (schema_dir / "version-hash-schema.yaml").write_text(schema_yaml)
        (tmp_path / "foo.py").write_text("x=1")
        h = compute_codebase_hash(tmp_path)  # rules=None → loads schema
        assert len(h) == 8


# ---------------------------------------------------------------------------
# generate_stamp
# ---------------------------------------------------------------------------

class TestGenerateStamp:
    def test_format(self, tmp_path, rules):
        (tmp_path / "foo.py").write_text("x=1")
        fixed = datetime(2026, 6, 13, 19, 30, 0, tzinfo=timezone.utc)
        stamp = generate_stamp(tmp_path, now_fn=lambda: fixed, rules=rules)
        assert stamp.startswith("2026-06-13_19-30-00_UTC_")
        assert len(stamp) == len("2026-06-13_19-30-00_UTC_") + 8

    def test_shorthash_matches_compute(self, tmp_path, rules):
        (tmp_path / "foo.py").write_text("x=1")
        fixed = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        stamp = generate_stamp(tmp_path, now_fn=lambda: fixed, rules=rules)
        assert stamp.split("_")[-1] == compute_codebase_hash(tmp_path, rules=rules)

    def test_default_now_fn_produces_valid_stamp(self, tmp_path, rules):
        (tmp_path / "foo.py").write_text("x=1")
        stamp = generate_stamp(tmp_path, rules=rules)
        parts = stamp.split("_")
        assert len(parts) == 4 and len(parts[3]) == 8


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _make_test_repo(tmp_path: Path) -> None:
    """Create a minimal repo with schema file for CLI tests."""
    schema_dir = tmp_path / "proxmox-bootstrap"
    schema_dir.mkdir()
    schema_yaml = (
        "schema_version: 1\n"
        "hash:\n  algorithm: sha256\n  truncate_chars: 8\n"
        "include:\n  extensions:\n    - ext: \".py\"\n    - ext: \".sh\"\n"
        "    - ext: \".yaml\"\n    - ext: \".yml\"\n    - ext: \".toml\"\n"
        "    - ext: \".bats\"\n"
        "exclude:\n  extensions:\n    - ext: \".md\"\n    - ext: \".html\"\n"
        "  directories:\n    - name: \".git\"\n    - name: \"pap\"\n"
        "    - name: \".ai\"\n    - name: \"docs\"\n"
        "    - name: \"__pycache__\"\n    - name: \".pytest_cache\"\n"
    )
    (schema_dir / "version-hash-schema.yaml").write_text(schema_yaml)
    (tmp_path / "foo.py").write_text("x=1")


class TestCLI:
    def test_hash_only(self, tmp_path, capsys):
        _make_test_repo(tmp_path)
        main(["--repo-root", str(tmp_path), "--hash-only"])
        out = capsys.readouterr().out.strip()
        assert len(out) == 8 and all(c in "0123456789abcdef" for c in out)

    def test_timestamp_only(self, tmp_path, capsys):
        _make_test_repo(tmp_path)
        main(["--repo-root", str(tmp_path), "--timestamp-only"])
        out = capsys.readouterr().out.strip()
        assert len(out) == 23 and out[4] == "-" and out[10] == "_"

    def test_list_files(self, tmp_path, capsys):
        _make_test_repo(tmp_path)
        (tmp_path / "bar.md").write_text("# doc")
        main(["--repo-root", str(tmp_path), "--list-files"])
        out = capsys.readouterr().out
        assert "foo.py" in out
        assert "bar.md" not in out

    def test_show_schema(self, tmp_path, capsys):
        _make_test_repo(tmp_path)
        main(["--repo-root", str(tmp_path), "--show-schema"])
        out = capsys.readouterr().out
        assert "schema_version" in out
        assert "include exts" in out
        assert "exclude dirs" in out

    def test_full_stamp_format(self, tmp_path, capsys):
        _make_test_repo(tmp_path)
        main(["--repo-root", str(tmp_path)])
        out = capsys.readouterr().out.strip()
        parts = out.split("_")
        assert len(parts) == 4 and len(parts[3]) == 8

    def test_bad_repo_root_exits(self, tmp_path):
        with pytest.raises(SystemExit) as exc:
            main(["--repo-root", str(tmp_path / "nonexistent")])
        assert exc.value.code == 2

    def test_missing_schema_raises(self, tmp_path, capsys):
        """If schema file is absent, FileNotFoundError should propagate."""
        (tmp_path / "foo.py").write_text("x=1")
        with pytest.raises(FileNotFoundError, match="Schema file not found"):
            main(["--repo-root", str(tmp_path), "--hash-only"])
