"""
collector_utils.py — Shared utilities for state collector modules.

Provides the RunnerFn type alias and _local_runner() implementation
used by all five collector modules:
  data_protection_collector.py
  storage_state_collector.py
  cluster_state_collector.py
  platform_state_collector.py
  hardware_state_collector.py

Stdlib only.
"""

from typing import Callable

RunnerFn = Callable[[str], str]


def local_runner(cmd: str) -> str:
    """Run a shell command locally and return stdout. Timeout: 30s."""
    import subprocess
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
    return result.stdout
