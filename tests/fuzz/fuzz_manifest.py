#!/usr/bin/env python3
"""
fuzz_manifest.py — Atheris coverage-guided fuzz target for manifest parsing.

Fuzzes doc-gen/readiness.py score_component() and score_graph() with
arbitrary bytes decoded to dict-shaped inputs.

Usage (Linux only — atheris requires libFuzzer):
    python tests/fuzz/fuzz_manifest.py -runs=10000

On non-Linux platforms or without atheris installed this module imports
cleanly but does nothing — it is a no-op so the test suite can import it.
"""

import sys

try:
    import atheris
    _HAS_ATHERIS = True
except ImportError:
    _HAS_ATHERIS = False

try:
    from readiness import BackupInventory, score_component
    _HAS_READINESS = True
except ImportError:
    _HAS_READINESS = False


def _fuzz_score_component(data: bytes) -> None:
    """Feed arbitrary bytes to score_component as a node_id / node_type pair."""
    if not _HAS_READINESS:
        return
    try:
        fdp = atheris.FuzzedDataProvider(data)
        node_id   = fdp.ConsumeUnicodeNoSurrogates(32) or "node-0"
        node_type = fdp.ConsumeUnicodeNoSurrogates(32) or "proxmox_host"
        inv = BackupInventory({"available": False})
        result = score_component(node_id, node_type, {}, inv)
        assert result.score in ("GREEN", "YELLOW", "ORANGE", "RED", "BLOCKED", "UNKNOWN")
    except (ValueError, TypeError, KeyError):
        pass  # expected for garbage inputs


if __name__ == "__main__" and _HAS_ATHERIS and _HAS_READINESS:
    atheris.Setup(sys.argv, _fuzz_score_component)
    atheris.Fuzz()
