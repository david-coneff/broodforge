#!/usr/bin/env python3
"""
fuzz_spawn_planner.py — Atheris coverage-guided fuzz target for spawn planner logic.

Fuzzes spawn_planner.py assess_service_fit() with arbitrary resource values.

Usage (Linux only — atheris requires libFuzzer):
    python tests/fuzz/fuzz_spawn_planner.py -runs=10000

On non-Linux platforms or without atheris installed this module imports
cleanly but does nothing — it is a no-op so the test suite can import it.
"""

import struct
import sys

try:
    import atheris
    _HAS_ATHERIS = True
except ImportError:
    _HAS_ATHERIS = False

try:
    from spawn_planner import FIT_MARGINAL, FIT_NO_FIT, FIT_OK, ServiceCatalog, assess_service_fit
    _HAS_SPAWN = True
except ImportError:
    _HAS_SPAWN = False

_CATALOG_RAW = [
    {"name": "k3s-worker", "ram_gb": 4, "disk_gb": 20, "baseline": True, "vm_count": 1},
    {"name": "longhorn",   "ram_gb": 4, "disk_gb": 100, "dependencies": ["k3s-worker"], "vm_count": 1},
]


def _fuzz_assess_service_fit(data: bytes) -> None:
    """Feed arbitrary byte pairs as (available_ram, available_disk) floats."""
    if not _HAS_SPAWN:
        return
    try:
        fdp = atheris.FuzzedDataProvider(data)
        ram_gb  = fdp.ConsumeFloat()
        disk_gb = fdp.ConsumeFloat()
        catalog = ServiceCatalog.from_list(_CATALOG_RAW)
        svc = catalog.get("k3s-worker")
        hw = {"total_ram_gb": 32, "total_disk_gb": 500}
        result = assess_service_fit(svc, hw, available_ram_gb=ram_gb, available_disk_gb=disk_gb)
        assert result.status in (FIT_OK, FIT_MARGINAL, FIT_NO_FIT)
    except (ValueError, TypeError, struct.error, OverflowError):
        pass  # expected for garbage inputs


if __name__ == "__main__" and _HAS_ATHERIS and _HAS_SPAWN:
    atheris.Setup(sys.argv, _fuzz_assess_service_fit)
    atheris.Fuzz()
