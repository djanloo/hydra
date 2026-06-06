"""Tests for pyfers.Board / pyfers.HV against the fake pyferslib backend."""

from __future__ import annotations

import pytest

import pyferslib
from pyfers import Board
from pyfers.errors import ConfigError


def test_open_close_lifecycle(fake):
    b = Board("eth:1.2.3.4")
    assert not b.is_open
    with pytest.raises(ConfigError):
        _ = b.handle
    with pytest.raises(ConfigError):
        _ = b.info

    b.open()
    assert b.is_open
    assert b.handle in fake.devices
    assert b.info.model_name == "A5202"

    # open() is idempotent: same handle, no second device created.
    h = b.handle
    assert b.open() is b
    assert b.handle == h

    b.close()
    assert not b.is_open
    assert h in fake.closed
    b.close()  # idempotent — must not raise


def test_open_tolerates_missing_board_info(fake):
    fake.no_info_paths.add("tdl:0:0:0")
    b = Board("tdl:0:0:0").open()
    assert b.is_open
    # info raises (None internally) but the board is still usable.
    with pytest.raises(ConfigError):
        _ = b.info


def test_context_manager_opens_and_closes(fake):
    with Board("eth:x") as b:
        assert b.is_open
        h = b.handle
    assert h in fake.closed


def test_set_get_param_and_registers(fake):
    b = Board("eth:x").open()
    b.set_param("AcquisitionMode", "COUNTING")
    assert b.get_param("AcquisitionMode") == "COUNTING"
    assert b.get_param("Unset") == ""

    b.write_register(0x1080, 0xABCD)
    assert b.read_register(0x1080) == 0xABCD

    b.send_command(0x14)
    assert fake.devices[b.handle]["commands"] == [0x14]


def test_configure_mode_validation(fake):
    b = Board("eth:x").open()
    b.configure("hard")
    b.configure("SOFT")  # case-insensitive
    assert (b.handle, pyferslib.CFG_HARD) in fake.configured
    assert (b.handle, pyferslib.CFG_SOFT) in fake.configured
    with pytest.raises(ConfigError):
        b.configure("medium")


def test_init_readout_uses_romode(fake):
    from pyfers import SortMode
    b = Board("eth:x").open()
    size = b.init_readout(SortMode.TRGID)
    assert size == (1 << 20)
    assert fake.readout_init == [(b.handle, pyferslib.ROMODE_TRGID_SORTING)]


def test_hv_property_round_trips(fake):
    b = Board("eth:x").open()

    b.hv.vbias = 62.5
    assert b.hv.vbias == 62.5

    b.hv.imax = 10.0           # ferslib has setter only; SDK caches for readback
    assert b.hv.imax == 10.0

    assert b.hv.on is False
    b.hv.on = True
    assert b.hv.on is True

    # read-only monitors come from the (fake) device state
    fake.devices[b.handle].update(vmon=61.9, imon=0.42, int_temp=38.0,
                                  detector_temp=21.0, ramping=1)
    assert b.hv.vmon == 61.9
    assert b.hv.imon == 0.42
    assert b.hv.int_temp == 38.0
    assert b.hv.detector_temp == 21.0

    st = b.hv.status
    assert set(st) == {"on", "ramping", "ovc", "ovv"}
    assert st["on"] == 1 and st["ramping"] == 1


def test_hv_requires_open_board(fake):
    b = Board("eth:x")  # not opened
    with pytest.raises(ConfigError):
        b.hv.vbias = 1.0
    with pytest.raises(ConfigError):
        _ = b.hv.vmon
