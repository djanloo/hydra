"""pyfers -- the pythonic SDK over the faithful ``pyferslib`` binding.

Role: this is the ergonomic, object-oriented layer of the HydraFERS stack
(CONTRACT.md section 1b). It fixes the C-dictated design of ``pyferslib`` with
OOP board/system access, enums instead of magic ints, properties instead of the
string ``set_param`` API, typed event dataclasses, context managers and Python
exceptions.

Layer: ``pyfers``. Imports ``pyferslib`` ONLY (no Qt, no hydrafers). It can be
used entirely standalone as an SDK::

    import pyfers
    with pyfers.System.open("eth:192.168.50.3") as sys:
        board = sys.boards[0]
        board.hv.vbias = 62.5
        board.hv.on = True
        sys.configure(my_config.to_ferslib_params())
        sys.start_run(pyfers.StartMode.ASYNC, run_number=1)
        for ev in sys.events():
            print(ev.tstamp_us)
        sys.stop_run()

Public surface (re-exported here):
  * :class:`System`, :class:`Board`, :class:`HV`
  * enums: :class:`AcqMode`, :class:`StartMode`, :class:`SortMode`,
    :class:`StopMode`, :class:`GainSelect`
  * errors: :class:`FERSError`, :class:`ConfigError`
  * typed events + :func:`decode` (also reachable as ``pyfers.events.*``)
  * a convenience re-export of the ``pyferslib`` integer constants
    (``START_*``, ``ROMODE_*``, ``DTQ_*``, ``CFG_*``,
    ``RAWDATA_REPROCESS_FINISHED``) so callers need not reach into the binding
    for the occasional raw code.
"""

from __future__ import annotations

import pyferslib

from . import events
from .board import HV, Board
from .enums import AcqMode, GainSelect, SortMode, StartMode, StopMode
from .errors import ConfigError, FERSError
from .events import (
    CountingEvent,
    ListEvent,
    ServiceEvent,
    SpectEvent,
    TestEvent,
    WaveEvent,
    decode,
)
from .system import System

__version__ = "0.0.5"

# --- convenience re-export of pyferslib integer constants ---------------------
# These are plain ints mirrored from FERSlib.h. Re-exporting them keeps the SDK
# self-sufficient (so users/engine code can write ``pyfers.START_ASYNC`` etc.)
# without importing the lower binding directly. Names that are missing on a
# minimal/test ``pyferslib`` are simply skipped.
_CONST_NAMES = (
    "CFG_HARD",
    "CFG_SOFT",
    "ROMODE_DISABLE_SORTING",
    "ROMODE_TRGTIME_SORTING",
    "ROMODE_TRGID_SORTING",
    "START_ASYNC",
    "START_TDL",
    "START_TDL_EXTRUN",
    "START_TDL_EXTRUN_EXTCLK",
    "START_TDL_EXTCLK",
    "START_TDL_GPS",
    "START_CHAIN_T0",
    "START_CHAIN_T1",
    "DTQ_SPECT",
    "DTQ_TIMING",
    "DTQ_COUNT",
    "DTQ_WAVE",
    "DTQ_SERVICE",
    "DTQ_TEST",
    "RAWDATA_REPROCESS_FINISHED",
)

for _name in _CONST_NAMES:
    if hasattr(pyferslib, _name):
        globals()[_name] = getattr(pyferslib, _name)

__all__ = [
    "__version__",
    # core SDK
    "System",
    "Board",
    "HV",
    # enums
    "AcqMode",
    "StartMode",
    "SortMode",
    "StopMode",
    "GainSelect",
    # errors
    "FERSError",
    "ConfigError",
    # events
    "events",
    "SpectEvent",
    "CountingEvent",
    "WaveEvent",
    "ListEvent",
    "ServiceEvent",
    "TestEvent",
    "decode",
    # re-exported constants
    *[_n for _n in _CONST_NAMES if _n in globals()],
]
