"""
Broodforge – CLI entry point.

Usage:
    pae collect        [--output FILE] [--collectors LIST]
    pae parse          --input FILE [--output FILE]
    pae report         --input FILE [--output FILE] [--format FORMAT]
    pae validate       --input FILE
    pae store          --input FILE --db FILE
    pae history        --db FILE [--hostname HOST] [--limit N]
    pae diff           --db FILE --id1 N --id2 N
    pae full-report    --input FILE [--output FILE]
    pae guest-collect  --inventory FILE [--output FILE] [--limit HOSTS]
    pae guest-report   --input FILE [--output FILE]
    pae push           --repo URL --files FILE [FILE ...] [--token-file FILE]
                       [--branch BRANCH] [--message MSG] [--prefix PATH]
    pae opentofu-ingest --state FILE [--input FILE] [--output FILE]
    pae compare        --input FILE [--output FILE]
"""

import argparse
import json
import sys
from pathlib import Path


def cmd_collect(args: argparse.Namespace) -> int:
    """Run collectors and write a raw audit JSON file."""
    from collector.registry import CollectorRegistry

    registry = CollectorRegistry()
    enabled = set(args.collectors.split(",")) if args.collectors else None

    results: dict = {}
    for name, collector in registry.collectors.items():
        if enabled is not None and name not in enabled:
            continue
        try:
            results[name] = collector.collect()
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] collector '{name}' failed: {exc}", file=sys.stderr)
            results[name] = {"error": str(exc)}

    output = json.dumps(results, indent=2, default=str)
    if args.output:
        Path(args.output).write_text(output)
        print(f"Raw audit written to {args.output}")
    else:
        print(output)
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    """Parse a raw audit file into a normalized assessment."""
    from engine.parser import parse_raw_audit

    raw = json.loads(Path(args.input).read_text())
    assessment = parse_raw_audit(raw)

    output = json.dumps(assessment, indent=2, default=str)
    if args.output:
        Path(args.output).write_text(output)
        print(f"Assessment written to {args.output}")
    else:
        print(output)
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    """Generate a report from a normalized assessment."""
    from engine.report import generate_report

    assessment = json.loads(Path(args.input).read_text())
    report = generate_report(assessment, fmt=args.format)

    if args.output:
        Path(args.output).write_text(report)
        print(f"Report written to {args.output}")
    else:
        print(report)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate a JSON file against the assessment schema."""
    from engine.schema import validate_assessment

    data = json.loads(Path(args.input).read_text())
    errors = validate_assessment(data)
    if errors:
        for err in errors:
            print(f"[ERROR] {err}", file=sys.stderr)
        return 1
    print("Validation passed.")
    return 0


def cmd_store(args: argparse.Namespace) -> int:
    """Store a normalized assessment in the SQLite history database."""
    from engine.db import HistoryDB

    assessment = json.loads(Path(args.input).read_text())
    db = HistoryDB(args.db)
    row_id = db.store(assessment)
    db.close()
    print(f"Stored as id={row_id}  hostname={assessment.get('hostname','?')}  ts={assessment.get('timestamp','?')}")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    """List stored assessments from the SQLite history database."""
    from engine.db import HistoryDB

    db = HistoryDB(args.db)
    rows = db.list_assessments(hostname=args.hostname, limit=args.limit)
    db.close()

    if not rows:
        print("No assessments found.")
        return 0

    # Header
    print(f"{'ID':>6}  {'HOSTNAME':<30}  {'TIMESTAMP':<35}  SCHEMA")
    print("-" * 90)
    for r in rows:
        print(f"{r['id']:>6}  {r['hostname']:<30}  {r['timestamp']:<35}  {r['schema_ver']}")
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    """Show field-level differences between two stored assessments."""
    from engine.db import HistoryDB
    from engine.diff import diff_assessments, format_diff

    db = HistoryDB(args.db)
    a1 = db.fetch(args.id1)
    a2 = db.fetch(args.id2)
    db.close()

    if a1 is None:
        print(f"[ERROR] id={args.id1} not found", file=sys.stderr)
        return 1
    if a2 is None:
        print(f"[ERROR] id={args.id2} not found", file=sys.stderr)
        return 1

    changes = diff_assessments(a1, a2)
    print(f"Diff: id={args.id1} ({a1.get('timestamp','?')}) → id={args.id2} ({a2.get('timestamp','?')})")
    print(f"Hostname: {a1.get('hostname','?')}")
    print()
    print(format_diff(changes))
    return 0


def cmd_full_report(args: argparse.Namespace) -> int:
    """Generate a combined node + guest assessment Markdown report."""
    from engine.report_combined import generate_combined_report

    assessment = json.loads(Path(args.input).read_text())
    report = generate_combined_report(assessment)

    if args.output:
        Path(args.output).write_text(report)
        print(f"Combined report written to {args.output}")
    else:
        print(report)
    return 0


def cmd_opentofu_ingest(args: argparse.Namespace) -> int:
    """Parse an OpenTofu/Terraform state file and merge into an assessment."""
    from engine.opentofu import ingest_state

    if args.input:
        assessment = json.loads(Path(args.input).read_text())
    else:
        import datetime, socket
        assessment = {
            "schema_version": "1.0",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "hostname": socket.getfqdn(),
        }

    try:
        assessment = ingest_state(assessment, args.state)
    except Exception as exc:
        print(f"[ERROR] Failed to ingest state file: {exc}", file=sys.stderr)
        return 1

    n = len(assessment.get("declared_resources") or [])
    output = json.dumps(assessment, indent=2, default=str)
    if args.output:
        Path(args.output).write_text(output)
        print(f"Assessment written to {args.output}  ({n} declared resources)")
    else:
        print(output)
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    """Generate a Declared vs Configured vs Observed comparison report."""
    from engine.report_compare import generate_comparison_report

    assessment = json.loads(Path(args.input).read_text())
    report = generate_comparison_report(assessment)

    if args.output:
        Path(args.output).write_text(report)
        print(f"Comparison report written to {args.output}")
    else:
        print(report)
    return 0


def cmd_push(args: argparse.Namespace) -> int:
    """Push files to a GitHub or Forgejo history repository."""
    from engine.repo import load_token, push_files, detect_remote

    # Token: --token-file takes precedence; fall back to PAE_TOKEN env var
    import os
    token: str | None = None
    if args.token_file:
        try:
            token = load_token(args.token_file)
        except Exception as exc:
            print(f"[ERROR] Could not read token file: {exc}", file=sys.stderr)
            return 1
    else:
        token = os.environ.get("PAE_TOKEN")

    if not token:
        print(
            "[ERROR] No token provided. Use --token-file or set PAE_TOKEN environment variable.",
            file=sys.stderr,
        )
        return 1

    kind = detect_remote(args.repo)
    print(f"Remote: {args.repo}  (detected: {kind})")

    result = push_files(
        repo_url=args.repo,
        token=token,
        files=args.files,
        message=args.message,
        branch=args.branch,
        dest_prefix=args.prefix or "",
    )

    for msg in result.messages:
        print(msg)

    if not result.ok:
        print(f"[WARN] Push completed with {len(result.errors)} error(s).", file=sys.stderr)
        return 1

    print(result.summary())
    return 0


def cmd_guest_collect(args: argparse.Namespace) -> int:
    """Collect guest facts from an Ansible inventory and merge into an assessment."""
    from engine.modules.guest_inventory import collect_all_guests

    limit = args.limit.split(",") if args.limit else None

    try:
        guests = collect_all_guests(args.inventory, limit=limit)
    except Exception as exc:
        print(f"[ERROR] Guest collection failed: {exc}", file=sys.stderr)
        return 1

    # If an existing assessment file is provided, merge guests in; otherwise build minimal wrapper.
    if args.input:
        assessment = json.loads(Path(args.input).read_text())
    else:
        import datetime, socket
        from engine.modules.guest_parser import parse_guests
        assessment = {
            "schema_version": "1.0",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "hostname": socket.getfqdn(),
        }

    assessment["guests"] = guests
    assessment["state_sources"] = {
        "configured": {
            "tool": "ansible",
            "inventory_path": args.inventory,
            "collected": bool(guests),
        },
        "observed": {
            "tool": "broodforge",
            "collected": True,
        },
        "declared": {
            "tool": None,
            "state_path": None,
            "collected": False,
        },
    }

    output = json.dumps(assessment, indent=2, default=str)
    if args.output:
        Path(args.output).write_text(output)
        print(f"Guest assessment written to {args.output}  ({len(guests)} guests)")
    else:
        print(output)
    return 0


def cmd_guest_report(args: argparse.Namespace) -> int:
    """Generate a guest assessment Markdown report."""
    from engine.report_guest import generate_guest_report

    assessment = json.loads(Path(args.input).read_text())
    report = generate_guest_report(assessment)

    if args.output:
        Path(args.output).write_text(report)
        print(f"Guest report written to {args.output}")
    else:
        print(report)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pae",
        description="Broodforge",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    # collect
    p = sub.add_parser("collect", help="Run collectors and produce a raw audit")
    p.add_argument("--output", "-o", metavar="FILE", help="Write output to FILE (default: stdout)")
    p.add_argument("--collectors", metavar="LIST", help="Comma-separated list of collectors to run (default: all)")
    p.set_defaults(func=cmd_collect)

    # parse
    p = sub.add_parser("parse", help="Parse a raw audit into a normalized assessment")
    p.add_argument("--input", "-i", required=True, metavar="FILE")
    p.add_argument("--output", "-o", metavar="FILE")
    p.set_defaults(func=cmd_parse)

    # report
    p = sub.add_parser("report", help="Generate a report from a normalized assessment")
    p.add_argument("--input", "-i", required=True, metavar="FILE")
    p.add_argument("--output", "-o", metavar="FILE")
    p.add_argument("--format", "-f", default="markdown", choices=["markdown", "json"], metavar="FORMAT")
    p.set_defaults(func=cmd_report)

    # validate
    p = sub.add_parser("validate", help="Validate a JSON file against the assessment schema")
    p.add_argument("--input", "-i", required=True, metavar="FILE")
    p.set_defaults(func=cmd_validate)

    # store
    p = sub.add_parser("store", help="Store a normalized assessment in the history database")
    p.add_argument("--input", "-i", required=True, metavar="FILE", help="Assessment JSON file")
    p.add_argument("--db", required=True, metavar="FILE", help="SQLite database path")
    p.set_defaults(func=cmd_store)

    # history
    p = sub.add_parser("history", help="List assessments stored in the history database")
    p.add_argument("--db", required=True, metavar="FILE", help="SQLite database path")
    p.add_argument("--hostname", metavar="HOST", help="Filter by hostname")
    p.add_argument("--limit", type=int, default=20, metavar="N", help="Max rows to show (default: 20)")
    p.set_defaults(func=cmd_history)

    # diff
    p = sub.add_parser("diff", help="Show field-level diff between two stored assessments")
    p.add_argument("--db", required=True, metavar="FILE", help="SQLite database path")
    p.add_argument("--id1", type=int, required=True, metavar="N", help="Older assessment id")
    p.add_argument("--id2", type=int, required=True, metavar="N", help="Newer assessment id")
    p.set_defaults(func=cmd_diff)

    # full-report
    p = sub.add_parser("full-report", help="Generate a combined node + guest Markdown report")
    p.add_argument("--input", "-i", required=True, metavar="FILE", help="Assessment JSON file")
    p.add_argument("--output", "-o", metavar="FILE", help="Write report to FILE (default: stdout)")
    p.set_defaults(func=cmd_full_report)

    # opentofu-ingest
    p = sub.add_parser("opentofu-ingest", help="Ingest an OpenTofu/Terraform state file into an assessment")
    p.add_argument("--state", required=True, metavar="FILE", help="Path to terraform.tfstate")
    p.add_argument("--input", "-i", metavar="FILE", help="Existing assessment JSON to merge into")
    p.add_argument("--output", "-o", metavar="FILE")
    p.set_defaults(func=cmd_opentofu_ingest)

    # compare
    p = sub.add_parser("compare", help="Generate a Declared vs Configured vs Observed report")
    p.add_argument("--input", "-i", required=True, metavar="FILE", help="Assessment JSON file")
    p.add_argument("--output", "-o", metavar="FILE")
    p.set_defaults(func=cmd_compare)

    # push
    p = sub.add_parser("push", help="Push files to a GitHub/Forgejo history repository")
    p.add_argument("--repo", required=True, metavar="URL", help="Repository URL")
    p.add_argument("--files", required=True, nargs="+", metavar="FILE", help="Files to push")
    p.add_argument("--token-file", metavar="FILE", help="Path to file containing API token")
    p.add_argument("--branch", default="main", metavar="BRANCH")
    p.add_argument("--message", default="Assessment update", metavar="MSG")
    p.add_argument("--prefix", default="", metavar="PATH", help="Destination path prefix in repo")
    p.set_defaults(func=cmd_push)

    # guest-collect
    p = sub.add_parser("guest-collect", help="Collect guest facts via Ansible inventory")
    p.add_argument("--inventory", "-i", required=True, metavar="FILE", help="Ansible inventory path")
    p.add_argument("--input", metavar="FILE", help="Existing assessment JSON to merge guests into")
    p.add_argument("--output", "-o", metavar="FILE", help="Write output to FILE (default: stdout)")
    p.add_argument("--limit", metavar="HOSTS", help="Comma-separated list of hostnames to collect")
    p.set_defaults(func=cmd_guest_collect)

    # guest-report
    p = sub.add_parser("guest-report", help="Generate a guest assessment Markdown report")
    p.add_argument("--input", "-i", required=True, metavar="FILE", help="Assessment JSON file")
    p.add_argument("--output", "-o", metavar="FILE", help="Write report to FILE (default: stdout)")
    p.set_defaults(func=cmd_guest_report)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
