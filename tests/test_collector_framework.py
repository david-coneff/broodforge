"""Tests for the collector framework (base + registry)."""

from unittest.mock import MagicMock

import pytest

from collector.base import BaseCollector
from collector.registry import CollectorRegistry


class ConcreteCollector(BaseCollector):
    name = "test_col"
    description = "test"

    def collect(self) -> dict:
        return {"ok": True}


class UnnamedCollector(BaseCollector):
    name = ""

    def collect(self) -> dict:
        return {}


def _reg(*collectors):
    reg = CollectorRegistry.__new__(CollectorRegistry)
    reg._collectors = {}
    for c in collectors:
        reg.register(c)
    return reg


def test_collect():
    assert ConcreteCollector().collect() == {"ok": True}


def test_default_available():
    assert ConcreteCollector().is_available() is True


def test_register_and_retrieve():
    c = ConcreteCollector()
    reg = _reg(c)
    assert "test_col" in reg.collectors
    assert reg.collectors["test_col"] is c


def test_unnamed_rejected():
    reg = _reg()
    with pytest.raises(ValueError):
        reg.register(UnnamedCollector())


def test_available_filters():
    c = ConcreteCollector()
    u = MagicMock(spec=BaseCollector)
    u.name = "unavailable"
    u.is_available.return_value = False
    reg = _reg(c)
    reg._collectors["unavailable"] = u
    assert "test_col" in reg.available()
    assert "unavailable" not in reg.available()


def test_collectors_returns_copy():
    reg = _reg(ConcreteCollector())
    copy = reg.collectors
    copy["injected"] = MagicMock()
    assert "injected" not in reg.collectors


def test_builtins_load():
    reg = CollectorRegistry()
    for name in ("hardware", "storage", "network", "proxmox"):
        assert name in reg.collectors
