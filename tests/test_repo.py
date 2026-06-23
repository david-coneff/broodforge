"""
Tests for Phase 5: history repository push module and CLI push command.

All HTTP calls are mocked — no network access required.
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import urllib.error
from unittest.mock import patch

import pytest

from engine.cli import build_parser, cmd_push
from engine.repo import (
    PushResult,
    _api_base,
    _owner_repo,
    detect_remote,
    load_token,
    push_files,
)

# ===========================================================================
# detect_remote
# ===========================================================================

class TestDetectRemote:
    def test_github_https(self):
        assert detect_remote("https://github.com/owner/repo") == "github"

    def test_github_with_git_suffix(self):
        assert detect_remote("https://github.com/owner/repo.git") == "github"

    def test_forgejo_https(self):
        assert detect_remote("https://git.example.com/owner/repo") == "forgejo"

    def test_forgejo_custom_port(self):
        assert detect_remote("https://git.lab.local:3000/owner/repo") == "forgejo"

    def test_unknown_ssh(self):
        assert detect_remote("git@github.com:owner/repo.git") == "unknown"

    def test_empty_string(self):
        assert detect_remote("") == "unknown"


# ===========================================================================
# _api_base
# ===========================================================================

class TestApiBase:
    def test_github(self):
        assert _api_base("https://github.com/owner/repo") == "https://api.github.com"

    def test_forgejo(self):
        base = _api_base("https://git.example.com/owner/repo")
        assert base == "https://git.example.com/api/v1"

    def test_forgejo_with_port(self):
        base = _api_base("https://git.lab.local:3000/owner/repo")
        assert base == "https://git.lab.local:3000/api/v1"


# ===========================================================================
# _owner_repo
# ===========================================================================

class TestOwnerRepo:
    def test_github(self):
        owner, repo = _owner_repo("https://github.com/myorg/myrepo")
        assert owner == "myorg" and repo == "myrepo"

    def test_git_suffix_stripped(self):
        owner, repo = _owner_repo("https://github.com/myorg/myrepo.git")
        assert repo == "myrepo"

    def test_forgejo(self):
        owner, repo = _owner_repo("https://git.example.com/dave/history")
        assert owner == "dave" and repo == "history"

    def test_trailing_slash(self):
        owner, repo = _owner_repo("https://github.com/myorg/myrepo/")
        assert owner == "myorg" and repo == "myrepo"


# ===========================================================================
# load_token
# ===========================================================================

class TestLoadToken:
    def test_reads_token(self, tmp_path):
        f = tmp_path / "token.txt"
        f.write_text("ghp_abc123\n")
        assert load_token(f) == "ghp_abc123"

    def test_strips_whitespace(self, tmp_path):
        f = tmp_path / "token.txt"
        f.write_text("  mytoken  \n")
        assert load_token(f) == "mytoken"

    def test_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_token(tmp_path / "nonexistent.txt")

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("   \n")
        with pytest.raises(ValueError):
            load_token(f)

    def test_token_not_logged(self, tmp_path, capsys):
        """The token value must never be printed."""
        f = tmp_path / "token.txt"
        secret = "SUPER_SECRET_TOKEN_VALUE"
        f.write_text(secret)
        token = load_token(f)
        assert token == secret
        # Loading the token must not print it
        out, err = capsys.readouterr()
        assert secret not in out
        assert secret not in err


# ===========================================================================
# PushResult
# ===========================================================================

class TestPushResult:
    def test_ok_default(self):
        r = PushResult(ok=True)
        assert r.ok is True
        assert r.pushed == []
        assert r.errors == []

    def test_summary_nothing_pushed(self):
        assert "Nothing pushed" in PushResult(ok=True).summary()

    def test_summary_pushed(self):
        r = PushResult(ok=True, pushed=["report.md", "history.db"])
        assert "2 file(s)" in r.summary()
        assert "report.md" in r.summary()

    def test_summary_errors(self):
        r = PushResult(ok=False, errors=["missing.md"])
        assert "Failed" in r.summary()
        assert "missing.md" in r.summary()


# ===========================================================================
# push_files (mocked HTTP)
# ===========================================================================

def _make_mock_urlopen(existing_sha: str | None = None, put_response: dict | None = None):
    """Return a context manager mock for urllib.request.urlopen."""

    class _FakeResponse:
        def __init__(self, data: bytes):
            self._data = data

        def read(self) -> bytes:
            return self._data

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    call_count = [0]

    def _urlopen(req):
        call_count[0] += 1
        method = req.get_method()
        if method == "GET":
            if existing_sha:
                return _FakeResponse(json.dumps({"sha": existing_sha}).encode())
            # 404 → file doesn't exist
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
        if method == "PUT":
            payload = put_response or {"content": {"sha": "newsha123"}}
            return _FakeResponse(json.dumps(payload).encode())
        raise AssertionError(f"Unexpected method: {method}")

    return _urlopen


class TestPushFiles:
    def _write(self, tmp_path, name="report.md", content=b"# Report"):
        f = tmp_path / name
        f.write_bytes(content)
        return f

    def test_new_file_pushed(self, tmp_path):
        f = self._write(tmp_path)
        with patch("urllib.request.urlopen", side_effect=_make_mock_urlopen()):
            result = push_files(
                repo_url="https://github.com/owner/repo",
                token="tok",
                files=[f],
            )
        assert result.ok
        assert "report.md" in result.pushed

    def test_existing_file_updated(self, tmp_path):
        f = self._write(tmp_path)
        with patch("urllib.request.urlopen", side_effect=_make_mock_urlopen(existing_sha="abc")):
            result = push_files(
                repo_url="https://github.com/owner/repo",
                token="tok",
                files=[f],
            )
        assert result.ok
        assert "report.md" in result.pushed

    def test_missing_file_recorded_as_error(self, tmp_path):
        with patch("urllib.request.urlopen", side_effect=_make_mock_urlopen()):
            result = push_files(
                repo_url="https://github.com/owner/repo",
                token="tok",
                files=[tmp_path / "nonexistent.md"],
            )
        assert not result.ok
        assert len(result.errors) == 1

    def test_multiple_files(self, tmp_path):
        f1 = self._write(tmp_path, "a.md")
        f2 = self._write(tmp_path, "b.db", b"sqlite data")
        with patch("urllib.request.urlopen", side_effect=_make_mock_urlopen()):
            result = push_files(
                repo_url="https://github.com/owner/repo",
                token="tok",
                files=[f1, f2],
            )
        assert result.ok
        assert len(result.pushed) == 2

    def test_dest_prefix_applied(self, tmp_path):
        f = self._write(tmp_path)
        captured_urls = []

        def _urlopen(req):
            captured_urls.append(req.full_url)
            if req.get_method() == "GET":
                raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
            return type("R", (), {"read": lambda s: b'{"content":{}}', "__enter__": lambda s: s, "__exit__": lambda s, *a: None})()

        with patch("urllib.request.urlopen", side_effect=_urlopen):
            push_files(
                repo_url="https://github.com/owner/repo",
                token="tok",
                files=[f],
                dest_prefix="assessments/",
            )
        # The PUT URL should include the prefix
        [u for u in captured_urls if "PUT" not in u]
        assert any("assessments/report.md" in u for u in captured_urls)

    def test_http_error_recorded(self, tmp_path):
        f = self._write(tmp_path)

        def _bad_urlopen(req):
            if req.get_method() == "GET":
                raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, None)

        with patch("urllib.request.urlopen", side_effect=_bad_urlopen):
            result = push_files(
                repo_url="https://github.com/owner/repo",
                token="tok",
                files=[f],
            )
        assert not result.ok
        assert len(result.errors) == 1

    def test_forgejo_url_structure(self, tmp_path):
        f = self._write(tmp_path)
        captured_urls = []

        def _urlopen(req):
            captured_urls.append(req.full_url)
            if req.get_method() == "GET":
                raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
            return type("R", (), {"read": lambda s: b'{"content":{}}', "__enter__": lambda s: s, "__exit__": lambda s, *a: None})()

        with patch("urllib.request.urlopen", side_effect=_urlopen):
            push_files(
                repo_url="https://git.example.com/dave/history",
                token="tok",
                files=[f],
            )
        assert any("git.example.com/api/v1" in u for u in captured_urls)

    def test_token_not_in_result_messages(self, tmp_path):
        """Token value must not appear in any result message."""
        f = self._write(tmp_path)
        secret = "MY_SECRET_TOKEN_XYZ"
        with patch("urllib.request.urlopen", side_effect=_make_mock_urlopen()):
            result = push_files(
                repo_url="https://github.com/owner/repo",
                token=secret,
                files=[f],
            )
        for msg in result.messages:
            assert secret not in msg, f"Token leaked in message: {msg}"

    def test_content_encoded_correctly(self, tmp_path):
        """Verify the file content is base64-encoded in the PUT body."""
        content = b"hello world"
        f = self._write(tmp_path, content=content)
        put_bodies = []

        def _urlopen(req):
            if req.get_method() == "GET":
                raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
            put_bodies.append(json.loads(req.data))
            return type("R", (), {"read": lambda s: b'{"content":{}}', "__enter__": lambda s: s, "__exit__": lambda s, *a: None})()

        with patch("urllib.request.urlopen", side_effect=_urlopen):
            push_files(
                repo_url="https://github.com/owner/repo",
                token="tok",
                files=[f],
            )
        assert put_bodies
        decoded = base64.b64decode(put_bodies[0]["content"])
        assert decoded == content


# ===========================================================================
# CLI – pae push
# ===========================================================================

def _capture(fn):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn()
    return rc, buf.getvalue()


class TestPushCLI:
    def _write(self, tmp_path, name="report.md"):
        f = tmp_path / name
        f.write_bytes(b"# Report")
        return f

    def _token_file(self, tmp_path, token="ghp_testtoken"):
        f = tmp_path / "token.txt"
        f.write_text(token)
        return f

    def test_push_success(self, tmp_path):
        f = self._write(tmp_path)
        tf = self._token_file(tmp_path)
        args = build_parser().parse_args([
            "push", "--repo", "https://github.com/owner/repo",
            "--files", str(f),
            "--token-file", str(tf),
        ])
        with patch("urllib.request.urlopen", side_effect=_make_mock_urlopen()):
            rc, out = _capture(lambda: cmd_push(args))
        assert rc == 0
        assert "report.md" in out

    def test_push_missing_token_fails(self, tmp_path, monkeypatch):
        f = self._write(tmp_path)
        monkeypatch.delenv("PAE_TOKEN", raising=False)
        args = build_parser().parse_args([
            "push", "--repo", "https://github.com/owner/repo",
            "--files", str(f),
        ])
        rc, _ = _capture(lambda: cmd_push(args))
        assert rc == 1

    def test_push_env_token(self, tmp_path, monkeypatch):
        f = self._write(tmp_path)
        monkeypatch.setenv("PAE_TOKEN", "env_token_value")
        args = build_parser().parse_args([
            "push", "--repo", "https://github.com/owner/repo",
            "--files", str(f),
        ])
        with patch("urllib.request.urlopen", side_effect=_make_mock_urlopen()):
            rc, out = _capture(lambda: cmd_push(args))
        assert rc == 0

    def test_push_bad_token_file_fails(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PAE_TOKEN", raising=False)
        f = self._write(tmp_path)
        args = build_parser().parse_args([
            "push", "--repo", "https://github.com/owner/repo",
            "--files", str(f),
            "--token-file", str(tmp_path / "missing_token.txt"),
        ])
        rc, _ = _capture(lambda: cmd_push(args))
        assert rc == 1

    def test_push_with_prefix(self, tmp_path):
        f = self._write(tmp_path)
        tf = self._token_file(tmp_path)
        captured_urls = []

        def _urlopen(req):
            captured_urls.append(req.full_url)
            if req.get_method() == "GET":
                raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
            return type("R", (), {"read": lambda s: b'{"content":{}}', "__enter__": lambda s: s, "__exit__": lambda s, *a: None})()

        args = build_parser().parse_args([
            "push", "--repo", "https://github.com/owner/repo",
            "--files", str(f),
            "--token-file", str(tf),
            "--prefix", "reports/",
        ])
        with patch("urllib.request.urlopen", side_effect=_urlopen):
            cmd_push(args)
        assert any("reports/report.md" in u for u in captured_urls)

    def test_push_custom_branch(self, tmp_path):
        f = self._write(tmp_path)
        tf = self._token_file(tmp_path)
        put_bodies = []

        def _urlopen(req):
            if req.get_method() == "GET":
                raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
            put_bodies.append(json.loads(req.data))
            return type("R", (), {"read": lambda s: b'{"content":{}}', "__enter__": lambda s: s, "__exit__": lambda s, *a: None})()

        args = build_parser().parse_args([
            "push", "--repo", "https://github.com/owner/repo",
            "--files", str(f),
            "--token-file", str(tf),
            "--branch", "history",
        ])
        with patch("urllib.request.urlopen", side_effect=_urlopen):
            cmd_push(args)
        assert put_bodies[0]["branch"] == "history"

    def test_push_token_not_in_output(self, tmp_path):
        """Token must not appear in any stdout output."""
        f = self._write(tmp_path)
        secret = "SUPER_SECRET_123"
        tf = tmp_path / "tok.txt"
        tf.write_text(secret)
        args = build_parser().parse_args([
            "push", "--repo", "https://github.com/owner/repo",
            "--files", str(f),
            "--token-file", str(tf),
        ])
        with patch("urllib.request.urlopen", side_effect=_make_mock_urlopen()):
            rc, out = _capture(lambda: cmd_push(args))
        assert secret not in out

    def test_push_forgejo_remote(self, tmp_path):
        f = self._write(tmp_path)
        tf = self._token_file(tmp_path)
        args = build_parser().parse_args([
            "push", "--repo", "https://git.example.com/dave/history",
            "--files", str(f),
            "--token-file", str(tf),
        ])
        with patch("urllib.request.urlopen", side_effect=_make_mock_urlopen()):
            rc, out = _capture(lambda: cmd_push(args))
        assert rc == 0
        assert "forgejo" in out
