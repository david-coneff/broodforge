"""Tests for CLI framework."""

import json

import pytest

from engine.cli import build_parser, cmd_validate


def test_parser_requires_subcommand():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_collect_defaults():
    parser = build_parser()
    args = parser.parse_args(["collect"])
    assert args.command == "collect"
    assert args.output is None
    assert args.collectors is None


def test_collect_flags():
    parser = build_parser()
    args = parser.parse_args(["collect", "--output", "/tmp/x.json", "--collectors", "hardware"])
    assert args.output == "/tmp/x.json"
    assert args.collectors == "hardware"


def test_parse_requires_input():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["parse"])


def test_report_default_format():
    parser = build_parser()
    args = parser.parse_args(["report", "--input", "f.json"])
    assert args.format == "markdown"


def test_validate_valid(tmp_path):
    f = tmp_path / "a.json"
    f.write_text(json.dumps({
        "schema_version": "1.0",
        "timestamp": "2024-01-01T00:00:00+00:00",
        "hostname": "pve01.example.com",
    }))
    parser = build_parser()
    args = parser.parse_args(["validate", "--input", str(f)])
    assert cmd_validate(args) == 0


def test_validate_invalid(tmp_path):
    f = tmp_path / "b.json"
    f.write_text(json.dumps({"hardware": {}}))
    parser = build_parser()
    args = parser.parse_args(["validate", "--input", str(f)])
    assert cmd_validate(args) == 1
