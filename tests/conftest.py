"""Shared pytest fixtures for the pyfers SDK tests.

pyfers is a thin OOP wrapper over the compiled ``pyferslib`` binding, which talks
to real hardware. To test the SDK logic without a board, the ``fake`` fixture
monkeypatches only the *I/O* functions of the real ``pyferslib`` module with an
in-memory fake device registry — the module constants (``DTQ_*``, ``START_*``,
``CFG_*`` …) stay real, so enum/decode resolution is exercised for real.

pyfers accesses every binding symbol module-qualified (``pyferslib.open_device``),
so patching attributes on the module is seen by the SDK at call time.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import pyferslib

# Every pyferslib I/O function that pyfers.Board / pyfers.System calls.
_PATCHED = [
    "open_device", "close_device", "get_board_info", "configure",
    "set_param", "get_param", "read_register", "write_register", "send_command",
    "init_readout", "close_readout", "flush_data",
    "hv_init", "hv_get_status", "hv_set_onoff", "hv_get_vbias", "hv_set_vbias",
    "hv_set_imax", "hv_get_vmon", "hv_get_imon", "hv_get_int_temp",
    "hv_get_detector_temp",
    "start_acquisition", "stop_acquisition", "drain_events",
]


class FakeFers:
    """In-memory stand-in for the ``pyferslib`` I/O surface."""

    def __init__(self) -> None:
        self._next_handle = 0x1000
        self.devices: dict[int, dict] = {}     # handle -> state
        self.path_of: dict[int, str] = {}       # handle -> path
        self.fail_paths: set[str] = set()       # paths that raise on open
        self.no_info_paths: set[str] = set()    # paths whose get_board_info raises
        self.closed: list[int] = []             # handles closed, in order
        self.configured: list[tuple[int, int]] = []   # (handle, cfg_mode_int)
        self.readout_init: list[tuple[int, int]] = []  # (handle, romode)
        self.acq_calls: list[tuple] = []        # ("start"/"stop", handles, mode, run)
        self.drain_batches: list[list] = []     # successive drain_events results

    def _new_state(self) -> dict:
        return {
            "vbias": 0.0, "imax": 0.0, "on": 0,
            "vmon": 0.0, "imon": 0.0, "ramping": 0, "ovc": 0, "ovv": 0,
            "int_temp": 0.0, "detector_temp": 0.0,
            "params": {}, "registers": {}, "commands": [],
        }

    # ---------------------------------------------------------- lifecycle
    def open_device(self, path):
        if path in self.fail_paths:
            raise pyferslib.FERSError(-2, f"Can't open the device {path}")
        h = self._next_handle
        self._next_handle += 1
        self.devices[h] = self._new_state()
        self.path_of[h] = path
        return h

    def close_device(self, handle):
        self.closed.append(handle)
        self.devices.pop(handle, None)

    def get_board_info(self, handle):
        if self.path_of.get(handle) in self.no_info_paths:
            raise pyferslib.FERSError(-1, "no board info (concentrator)")
        return SimpleNamespace(pid=1234, model_name="A5202",
                               fpga_fwrev=0x010203, num_ch=64)

    # ---------------------------------------------------------- config / regs
    def configure(self, handle, mode_int):
        self.configured.append((handle, mode_int))

    def set_param(self, handle, name, value):
        self.devices[handle]["params"][name] = value

    def get_param(self, handle, name):
        return self.devices[handle]["params"].get(name, "")

    def read_register(self, handle, addr):
        return self.devices[handle]["registers"].get(addr, 0)

    def write_register(self, handle, addr, value):
        self.devices[handle]["registers"][addr] = value

    def send_command(self, handle, cmd):
        self.devices[handle]["commands"].append(cmd)

    # ---------------------------------------------------------- readout
    def init_readout(self, handle, romode):
        self.readout_init.append((handle, romode))
        return 1 << 20

    def close_readout(self, handle):
        self.devices[handle]["readout_closed"] = True

    def flush_data(self, handle):
        self.devices[handle]["flushed"] = True

    # ---------------------------------------------------------- HV
    def hv_init(self, handle):
        self.devices[handle]["hv_init"] = True

    def hv_get_status(self, handle):
        d = self.devices[handle]
        return (d["on"], d["ramping"], d["ovc"], d["ovv"])

    def hv_set_onoff(self, handle, on):
        self.devices[handle]["on"] = 1 if on else 0

    def hv_get_vbias(self, handle):
        return self.devices[handle]["vbias"]

    def hv_set_vbias(self, handle, value):
        self.devices[handle]["vbias"] = value

    def hv_set_imax(self, handle, value):
        self.devices[handle]["imax"] = value

    def hv_get_vmon(self, handle):
        return self.devices[handle]["vmon"]

    def hv_get_imon(self, handle):
        return self.devices[handle]["imon"]

    def hv_get_int_temp(self, handle):
        return self.devices[handle]["int_temp"]

    def hv_get_detector_temp(self, handle):
        return self.devices[handle]["detector_temp"]

    # ---------------------------------------------------------- data plane
    def start_acquisition(self, handles, mode_int, run):
        self.acq_calls.append(("start", list(handles), mode_int, run))

    def stop_acquisition(self, handles, mode_int, run):
        self.acq_calls.append(("stop", list(handles), mode_int, run))

    def drain_events(self, handles, batch):
        if self.drain_batches:
            return self.drain_batches.pop(0)
        return []


@pytest.fixture
def fake(monkeypatch):
    """Patch pyferslib I/O with a FakeFers; constants stay real."""
    f = FakeFers()
    for name in _PATCHED:
        monkeypatch.setattr(pyferslib, name, getattr(f, name), raising=False)
    return f
