"""Pythonic enumerations for the FERS SDK.

Role: typed, self-documenting replacements for the magic strings/ints that the
faithful binding (``pyferslib``) inherits from the C library. Each enum member
carries the *verbatim* ferslib option string (so it can be handed straight to
``pyferslib.set_param``) and, where relevant, a helper that resolves it to the
matching ``pyferslib`` integer constant.

Layer: ``pyfers`` (CONTRACT.md section 1b). This module imports ``pyferslib``
ONLY (for its module constants), and nothing from Qt or hydrafers.

The option lists mirror ``docs/param_defs_reference.txt`` exactly:
  * ``AcquisitionMode`` -> :class:`AcqMode`
  * ``StartRunMode``    -> :class:`StartMode`
  * ``EventBuildingMode`` -> :class:`SortMode`
  * ``StopRunMode``     -> :class:`StopMode`
  * ``GainSelect``      -> :class:`GainSelect`
"""

from __future__ import annotations

import enum

import pyferslib


class AcqMode(enum.Enum):
    """Acquisition mode (param ``AcquisitionMode``, [AcqMode] section).

    Each member's value is the verbatim ferslib combo string. Use
    :attr:`value` when calling ``set_param("AcquisitionMode", mode.value)``.
    """

    SPECTROSCOPY = "SPECTROSCOPY"
    SPECT_TIMING = "SPECT_TIMING"
    TIMING_CSTART = "TIMING_CSTART"
    TIMING_CSTOP = "TIMING_CSTOP"
    COUNTING = "COUNTING"
    WAVEFORM = "WAVEFORM"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    def to_dtq(self) -> int:
        """Return the ``pyferslib.DTQ_*`` family this acquisition mode produces.

        SPECT_TIMING produces spectroscopy events that also carry timing, hence
        the combined ``DTQ_SPECT | DTQ_TIMING`` mask.
        """
        mapping = {
            AcqMode.SPECTROSCOPY: pyferslib.DTQ_SPECT,
            AcqMode.SPECT_TIMING: pyferslib.DTQ_SPECT | pyferslib.DTQ_TIMING,
            AcqMode.TIMING_CSTART: pyferslib.DTQ_TIMING,
            AcqMode.TIMING_CSTOP: pyferslib.DTQ_TIMING,
            AcqMode.COUNTING: pyferslib.DTQ_COUNT,
            AcqMode.WAVEFORM: pyferslib.DTQ_WAVE,
        }
        return mapping[self]


class StartMode(enum.Enum):
    """Run start/synchronization mode (param ``StartRunMode``, [RunCtrl]).

    Each member carries the verbatim ferslib combo string; :meth:`to_ferslib_int`
    resolves it to the matching ``pyferslib.START_*`` integer used by
    ``start_acquisition`` / ``stop_acquisition`` / ``sync_tdl_chains``.
    """

    ASYNC = "ASYNC"
    TDL = "TDL"
    TDL_EXTRUN = "TDL_EXTRUN"
    TDL_GPS = "TDL_GPS"
    CHAIN_T0 = "CHAIN_T0"
    CHAIN_T1 = "CHAIN_T1"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    def to_ferslib_int(self) -> int:
        """Resolve this start mode to its ``pyferslib.START_*`` integer code."""
        mapping = {
            StartMode.ASYNC: pyferslib.START_ASYNC,
            StartMode.TDL: pyferslib.START_TDL,
            StartMode.TDL_EXTRUN: pyferslib.START_TDL_EXTRUN,
            StartMode.TDL_GPS: pyferslib.START_TDL_GPS,
            StartMode.CHAIN_T0: pyferslib.START_CHAIN_T0,
            StartMode.CHAIN_T1: pyferslib.START_CHAIN_T1,
        }
        return mapping[self]

    @classmethod
    def from_string(cls, name: str) -> "StartMode":
        """Parse a ferslib ``StartRunMode`` string (case-insensitive)."""
        key = str(name).strip().upper()
        for member in cls:
            if member.value == key:
                return member
        raise ValueError(
            f"unknown StartRunMode {name!r}; expected one of "
            f"{[m.value for m in cls]}"
        )


class SortMode(enum.Enum):
    """Event-building / sorting mode (param ``EventBuildingMode``, [RunCtrl]).

    Each member carries the verbatim ferslib combo string; :meth:`to_romode`
    resolves it to the matching ``pyferslib.ROMODE_*`` readout constant used by
    ``init_readout``.
    """

    DISABLED = "DISABLED"
    TRGTIME = "TRGTIME_SORTING"
    TRGID = "TRGID_SORTING"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    def to_romode(self) -> int:
        """Resolve this sort mode to its ``pyferslib.ROMODE_*`` integer code."""
        mapping = {
            SortMode.DISABLED: pyferslib.ROMODE_DISABLE_SORTING,
            SortMode.TRGTIME: pyferslib.ROMODE_TRGTIME_SORTING,
            SortMode.TRGID: pyferslib.ROMODE_TRGID_SORTING,
        }
        return mapping[self]

    @classmethod
    def from_string(cls, name: str) -> "SortMode":
        """Parse a ferslib ``EventBuildingMode`` string (case-insensitive)."""
        key = str(name).strip().upper()
        for member in cls:
            if member.value == key:
                return member
        raise ValueError(
            f"unknown EventBuildingMode {name!r}; expected one of "
            f"{[m.value for m in cls]}"
        )


class StopMode(enum.Enum):
    """Run stop policy (param ``StopRunMode``, [RunCtrl]).

    ferslib treats this as a Janus-level policy (MANUAL / preset time / preset
    counts); each member carries the verbatim combo string and the matching
    ``STOPRUN_*`` integer the legacy library uses.
    """

    MANUAL = "MANUAL"
    PRESET_TIME = "PRESET_TIME"
    PRESET_COUNTS = "PRESET_COUNTS"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    def to_ferslib_int(self) -> int:
        """Resolve to the ``STOPRUN_*`` integer (0=manual, 1=time, 2=counts)."""
        mapping = {
            StopMode.MANUAL: 0,
            StopMode.PRESET_TIME: 1,
            StopMode.PRESET_COUNTS: 2,
        }
        return mapping[self]

    @classmethod
    def from_string(cls, name: str) -> "StopMode":
        """Parse a ferslib ``StopRunMode`` string (case-insensitive)."""
        key = str(name).strip().upper()
        for member in cls:
            if member.value == key:
                return member
        raise ValueError(
            f"unknown StopRunMode {name!r}; expected one of "
            f"{[m.value for m in cls]}"
        )


class GainSelect(enum.Enum):
    """Output gain selection (param ``GainSelect``, [Spectroscopy]).

    HIGH/LOW select a single gain branch, AUTO picks HG unless saturated, BOTH
    keeps both. Each member carries the verbatim ferslib combo string.
    """

    HIGH = "HIGH"
    LOW = "LOW"
    AUTO = "AUTO"
    BOTH = "BOTH"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @classmethod
    def from_string(cls, name: str) -> "GainSelect":
        """Parse a ferslib ``GainSelect`` string (case-insensitive)."""
        key = str(name).strip().upper()
        for member in cls:
            if member.value == key:
                return member
        raise ValueError(
            f"unknown GainSelect {name!r}; expected one of "
            f"{[m.value for m in cls]}"
        )


__all__ = [
    "AcqMode",
    "StartMode",
    "SortMode",
    "StopMode",
    "GainSelect",
]
