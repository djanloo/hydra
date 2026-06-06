"""Tests for pyfers.errors and the public package surface."""

from __future__ import annotations

import pyfers
from pyfers import ConfigError, FERSError


def test_configerror_is_valueerror():
    assert issubclass(ConfigError, ValueError)


def test_ferserror_carries_code_and_message():
    e = FERSError(-2, "Can't open the Eth device")
    assert e.code == -2
    assert "Can't open the Eth device" in str(e)


def test_public_exports_present():
    expected = [
        "System", "Board", "HV",
        "AcqMode", "StartMode", "SortMode", "StopMode", "GainSelect",
        "FERSError", "ConfigError",
        "SpectEvent", "CountingEvent", "WaveEvent", "ListEvent",
        "ServiceEvent", "TestEvent", "decode", "events",
    ]
    for name in expected:
        assert hasattr(pyfers, name), f"pyfers.{name} missing from public API"
