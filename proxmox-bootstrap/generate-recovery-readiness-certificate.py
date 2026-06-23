#!/usr/bin/env python3
"""
generate-recovery-readiness-certificate.py — CLI entry point for the
Recovery-Readiness Conformance Certificate builder (Phase 1.I, AD-059).

Loads bootstrap-state.json (or a Tier 1/2 manifest), builds the dependency
graph and readiness report, locates the latest drift summary and reconstruction
drill, and writes recovery-readiness-certificate.json + .html (AD-051 twin)
to an output directory.

This is autonomous, read-only composition — see the "Human Intervention
Boundary" documentation (FORGING.md) for which steps in the broader recovery-
readiness pipeline (e.g. running a reconstruction drill) require an operator.

Usage:
    python3 generate-recovery-readiness-certificate.py \\
        [--repo /path/to/broodforge] \\
        [--manifest forge-manifest.json] \\
        [--output-dir /opt/broodforge/certificates]

Produces:
    recovery-readiness-certificate.json
    recovery-readiness-certificate.html
"""

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "doc-gen"))

from _recovery_readiness_certificate import assemble_recovery_readiness_certificate

try:
    from html_package_manifest import build_recovery_readiness_certificate_html as _build_cert_html
    _HAS_CERT_HTML = True
except ImportError:
    _build_cert_html = None  # type: ignore
    _HAS_CERT_HTML = False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a recovery-readiness conformance certificate (Phase 1.I, AD-059)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--repo", default=None,
        help="Path to broodforge repo root (default: inferred from this script's location)",
    )
    parser.add_argument(
        "--manifest", default=None,
        help="Path to a manifest.json/forge-manifest.json/bootstrap-state.json to certify "
             "(default: load proxmox-bootstrap/bootstrap-state.json from the repo)",
    )
    parser.add_argument(
        "--output-dir", default=".",
        help="Directory to write the certificate into (default: current directory)",
    )
    args = parser.parse_args()

    if args.repo:
        repo_root = Path(args.repo)
    else:
        inferred = _HERE.parent
        repo_root = inferred if (inferred / "proxmox-bootstrap").is_dir() else None
        if repo_root is None:
            print("[error] Could not infer repo root; pass --repo explicitly.", file=sys.stderr)
            sys.exit(1)

    manifest = None
    if args.manifest:
        manifest_path = Path(args.manifest)
        if not manifest_path.exists():
            print(f"[error] Manifest not found: {manifest_path}", file=sys.stderr)
            sys.exit(1)
        manifest = json.loads(manifest_path.read_text())

    try:
        certificate, _manifest, _graph, _readiness = assemble_recovery_readiness_certificate(
            repo_root=repo_root,
            manifest=manifest,
        )
    except FileNotFoundError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "recovery-readiness-certificate.json"
    json_path.write_text(json.dumps(certificate, indent=2), encoding="utf-8")

    if _HAS_CERT_HTML:
        html_text = _build_cert_html(certificate)
    else:
        html_text = "<html><body><pre>" + json.dumps(certificate, indent=2) + "</pre></body></html>"
    html_path = output_dir / "recovery-readiness-certificate.html"
    html_path.write_text(html_text, encoding="utf-8")

    readiness = certificate.get("readiness") or {}
    drift = certificate.get("drift") or {}
    drill = certificate.get("latest_drill") or {}

    print(f"\n{'=' * 64}")
    print("  Recovery-Readiness Conformance Certificate Built")
    print(f"{'=' * 64}")
    print(f"  Certificate: {json_path}")
    print(f"  HTML twin:   {html_path}")
    print(f"  Cell:        {certificate.get('cell_id')}")
    print(f"  Manifest hash (SHA-256): {certificate.get('manifest_hash')}")
    print(f"  Graph hash    (SHA-256): {certificate.get('graph_hash')}")
    print(f"  Overall readiness:       {readiness.get('overall_score')} — {readiness.get('overall_score_reason')}")
    print(f"  Drift severity:          {drift.get('drift_severity') or 'n/a (no prior snapshot)'}")
    print(f"  Last drill outcome:      {drill.get('outcome') or 'n/a (no drill recorded)'}")
    print()


if __name__ == "__main__":
    main()
