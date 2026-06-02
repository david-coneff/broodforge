"""
test_collector_utils.py — Tests for shared collector_utils module (S5).

Covers:
  - RunnerFn type alias exported
  - local_runner() callable signature
  - Collector modules import from collector_utils (not define own _local_runner)
"""
import os
import sys

_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_PB   = os.path.join(_ROOT, "proxmox-bootstrap")
if _PB not in sys.path:
    sys.path.insert(0, _PB)

import collector_utils as _cu


class TestCollectorUtils:
    def test_local_runner_is_callable(self):
        assert callable(_cu.local_runner)

    def test_local_runner_returns_string(self):
        result = _cu.local_runner("echo hello")
        assert isinstance(result, str)

    def test_runnerFn_type_alias_exported(self):
        assert hasattr(_cu, "RunnerFn")


class TestCollectorModulesUseSharedRunner:
    """All 5 state collectors should import from collector_utils, not define their own."""

    def _module_source(self, name: str) -> str:
        import importlib
        mod = importlib.import_module(name)
        import inspect
        return inspect.getsource(mod)

    def test_hardware_uses_shared_runner(self):
        src = self._module_source("hardware_state_collector")
        assert "from collector_utils import" in src
        # Verify the local definition is removed
        assert "def _local_runner" not in src

    def test_platform_uses_shared_runner(self):
        src = self._module_source("platform_state_collector")
        assert "from collector_utils import" in src
        assert "def _local_runner" not in src

    def test_cluster_uses_shared_runner(self):
        src = self._module_source("cluster_state_collector")
        assert "from collector_utils import" in src
        assert "def _local_runner" not in src

    def test_storage_uses_shared_runner(self):
        src = self._module_source("storage_state_collector")
        assert "from collector_utils import" in src
        assert "def _local_runner" not in src

    def test_data_protection_uses_shared_runner(self):
        src = self._module_source("data_protection_collector")
        assert "from collector_utils import" in src
        assert "def _local_runner" not in src

    def test_all_collectors_can_import(self):
        for name in (
            "hardware_state_collector",
            "platform_state_collector",
            "cluster_state_collector",
            "storage_state_collector",
            "data_protection_collector",
        ):
            import importlib
            mod = importlib.import_module(name)
            assert mod is not None
