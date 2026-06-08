#!/usr/bin/env python3
"""
replay-snapshot.py — Snapshot replay / conformance check (Phase 1.I, AD-059).

Re-derives a stored snapshot's `manifest_hash` and `graph_hash` from its raw
`manifest.json`, recomputes its dependency graph and readiness report, and
asserts the recomputed hashes match the values recorded in `history/index.json`
at snapshot-build time.

This turns "snapshots are reproducible" — an existing design constraint
(`.ai/CURRENT_STATE.md` "Key Design Constraints") — from an assumption into a
checked, reportable fact, per Phase 1.I's roadmap scope. It is autonomous,
read-only verification: no files are modified, no operator action is required.

Usage:
    python3 replay-snapshot.py <snapshot-id> [--repo /path/to/broodforge]
    python3 replay-snapshot.py --manifest history/snapshots/<id>/manifest.json \\
        --expect-manifest-hash <hex> --expect-graph-hash <hex>

Exit status:
    0  recomputed hashes match the recorded values (and readiness re-derives
       without error) — conformance holds
    1  mismatch found, snapshot/manifest not found, or doc-gen modules missing
"""

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "doc-gen"))

from _recovery_readiness_certificate import hash_dict

try:
    from dependencies import build_graph
    from readiness import score_graph
    _HAS_DOC_GEN = True
except ImportError:
    build_graph = None  # type: ignore
    score_graph = None  # type: ignore
    _HAS_DOC_GEN = False


def replay_snapshot(manifest: dict) -> dict:
    """
    Recompute manifest_hash, graph_hash, and the readiness signal from a raw
    manifest dict — the same derivation `_recovery_readiness_certificate`
    performs at certificate-generation time.

    Returns a dict: {manifest_hash, graph_hash, overall_score, overall_score_reason}.
    """
    if not _HAS_DOC_GEN:
        raise RuntimeError("dependencies/readiness modules are required to replay a snapshot")

    manifest_hash = hash_dict(manifest)
    graph = build_graph(manifest)
    graph_dict = graph.to_dict()
    graph_hash = hash_dict(graph_dict)
    readiness = score_graph(graph, manifest)

    return {
        "manifest_hash": manifest_hash,
        "graph_hash": graph_hash,
        "overall_score": readiness.overall_score,
        "overall_score_reason": readiness.overall_score_reason,
    }


def compare_replay(recomputed: dict, recorded_manifest_hash, recorded_graph_hash) -> dict:
    """
    Compare recomputed hashes against recorded ones.

    Returns {"match": bool, "mismatches": [str, ...]}.
    """
    mismatches = []
    if recorded_manifest_hash is not None and recomputed["manifest_hash"] != recorded_manifest_hash:
        mismatches.append(
            f"manifest_hash mismatch: recorded={recorded_manifest_hash} "
            f"recomputed={recomputed['manifest_hash']}"
        )
    if recorded_graph_hash is not None and recomputed["graph_hash"] != recorded_graph_hash:
        mismatches.append(
            f"graph_hash mismatch: recorded={recorded_graph_hash} "
            f"recomputed={recomputed['graph_hash']}"
        )
    return {"match": len(mismatches) == 0, "mismatches": mismatches}


def _find_snapshot_entry(index: dict, snapshot_id: str) -> dict:
    for entry in index.get("snapshots") or []:
        if entry.get("id") == snapshot_id:
            return entry
    raise KeyError(f"Snapshot '{snapshot_id}' not found in history/index.json")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay a stored snapshot and assert its recorded hashes match (Phase 1.I, AD-059)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "snapshot_id", nargs="?", default=None,
        help="Snapshot ID to replay (looked up in history/index.json)",
    )
    parser.add_argument("--repo", default=None, help="Path to broodforge repo root")
    parser.add_argument("--manifest", default=None,
                        help="Path to a manifest.json to replay directly (bypasses index lookup)")
    parser.add_argument("--expect-manifest-hash", default=None,
                        help="Expected manifest_hash to compare against (used with --manifest)")
    parser.add_argument("--expect-graph-hash", default=None,
                        help="Expected graph_hash to compare against (used with --manifest)")
    args = parser.parse_args()

    if not _HAS_DOC_GEN:
        print("[error] dependencies/readiness modules not importable — cannot replay.", file=sys.stderr)
        sys.exit(1)

    if args.repo:
        repo_root = Path(args.repo)
    else:
        inferred = _HERE.parent
        repo_root = inferred if (inferred / "proxmox-bootstrap").is_dir() else Path(".")

    if args.manifest:
        manifest_path = Path(args.manifest)
        if not manifest_path.exists():
            print(f"[error] Manifest not found: {manifest_path}", file=sys.stderr)
            sys.exit(1)
        manifest = json.loads(manifest_path.read_text())
        recorded_manifest_hash = args.expect_manifest_hash
        recorded_graph_hash = args.expect_graph_hash
        label = str(manifest_path)
    else:
        if not args.snapshot_id:
            print("[error] Provide a snapshot-id or --manifest.", file=sys.stderr)
            sys.exit(1)

        index_path = repo_root / "history" / "index.json"
        if not index_path.exists():
            print(f"[error] Index not found: {index_path}", file=sys.stderr)
            sys.exit(1)

        index = json.loads(index_path.read_text())
        try:
            entry = _find_snapshot_entry(index, args.snapshot_id)
        except KeyError as exc:
            print(f"[error] {exc}", file=sys.stderr)
            sys.exit(1)

        manifest_path = repo_root / entry["manifest_path"]
        if not manifest_path.exists():
            print(f"[error] Manifest not found: {manifest_path}", file=sys.stderr)
            sys.exit(1)

        manifest = json.loads(manifest_path.read_text())
        recorded_manifest_hash = entry.get("manifest_hash")
        recorded_graph_hash = entry.get("graph_hash")
        label = args.snapshot_id

    recomputed = replay_snapshot(manifest)
    result = compare_replay(recomputed, recorded_manifest_hash, recorded_graph_hash)

    print(f"\n{'=' * 64}")
    print(f"  Snapshot Replay — {label}")
    print(f"{'=' * 64}")
    print(f"  Recomputed manifest_hash: {recomputed['manifest_hash']}")
    print(f"  Recorded   manifest_hash: {recorded_manifest_hash}")
    print(f"  Recomputed graph_hash:    {recomputed['graph_hash']}")
    print(f"  Recorded   graph_hash:    {recorded_graph_hash}")
    print(f"  Re-derived overall_score: {recomputed['overall_score']} — {recomputed['overall_score_reason']}")
    print()

    if result["match"]:
        print("  [PASS] Replay matches recorded hashes — snapshot is reproducible.")
        print()
        sys.exit(0)
    else:
        print("  [FAIL] Replay mismatch — recorded snapshot does not reproduce:")
        for m in result["mismatches"]:
            print(f"    - {m}")
        print()
        sys.exit(1)


if __name__ == "__main__":
    main()
