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


class BoardFamily(enum.IntEnum):
    """FERS board family, keyed on the ferslib ``FERSCode`` (FERSlib.h).

    The integer value is the verbatim ``FERSCode`` read from board flash
    (``board_info.fers_code``): 5202 = A5202/DT5202 (SiPM, spectroscopy +
    timing, 64 ch, HV); 5203 = A5203/DT5203 (picoTDC, timing only, up to
    128 ch, no HV). HydraFERS never mixes families in one running system
    (ferslib forbids it: event-building compares raw timestamps without clock
    normalisation, and the families share no acquisition mode).
    """

    A5202 = 5202
    A5203 = 5203

    @property
    def has_hv(self) -> bool:
        """Whether this family has an on-board HV bias generator (5202 only).

        The A5203 is a pure picoTDC front-end: every ``FERS_HV_*`` call returns
        ``FERSLIB_ERR_NOT_APPLICABLE`` for it, so any HV access is meaningless.
        """
        return self is BoardFamily.A5202

    @property
    def num_channels(self) -> int:
        """Nominal channel count for this family (64 for 5202, 128 for 5203)."""
        return 128 if self is BoardFamily.A5203 else 64

    @classmethod
    def from_code(cls, code: int) -> "BoardFamily":
        """Resolve a ferslib ``FERSCode`` integer to a :class:`BoardFamily`."""
        try:
            return cls(int(code))
        except ValueError as exc:
            raise ValueError(
                f"unknown FERSCode {code!r}; expected one of {[m.value for m in cls]}"
            ) from exc

    @classmethod
    def from_model_name(cls, name: str) -> "BoardFamily | None":
        """Best-effort family inference from a model name like ``"A5202"``.

        Used as a fallback when ``board_info.fers_code`` is unavailable. Returns
        ``None`` if the name matches no known family.
        """
        text = str(name).upper()
        if "5203" in text:
            return cls.A5203
        if "5202" in text:
            return cls.A5202
        return None


class AcqMode(enum.Enum):
    """A5202 acquisition mode (param ``AcquisitionMode``, [AcqMode] section).

    Each member's value is the verbatim ferslib combo string. Use
    :attr:`value` when calling ``set_param("AcquisitionMode", mode.value)``.
    This enum is the **5202** family; see :class:`AcqMode5203` for the picoTDC
    modes (which are a disjoint set despite sharing some register encodings).
    """

    SPECTROSCOPY = "SPECTROSCOPY"
    SPECT_TIMING = "SPECT_TIMING"
    TIMING_CSTART = "TIMING_CSTART"
    TIMING_CSTOP = "TIMING_CSTOP"
    COUNTING = "COUNTING"
    WAVEFORM = "WAVEFORM"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @property
    def family(self) -> "BoardFamily":
        """The board family these modes belong to (A5202)."""
        return BoardFamily.A5202

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

    @classmethod
    def from_string(cls, name: str) -> "AcqMode":
        """Parse a ferslib ``AcquisitionMode`` string (case-insensitive)."""
        key = str(name).strip().upper()
        for member in cls:
            if member.value == key:
                return member
        raise ValueError(
            f"unknown AcquisitionMode {name!r}; expected one of "
            f"{[m.value for m in cls]}"
        )


class AcqMode5203(enum.Enum):
    """A5203 (picoTDC) acquisition mode (param ``AcquisitionMode``, [AcqMode]).

    A disjoint set from :class:`AcqMode`: the picoTDC is timing-only, so every
    mode produces ``DTQ_TIMING`` list events (or ``DTQ_TEST`` for the test
    patterns). Each member carries the verbatim ferslib combo string.
    """

    COMMON_START = "COMMON_START"
    COMMON_STOP = "COMMON_STOP"
    TRG_MATCHING = "TRG_MATCHING"
    STREAMING = "STREAMING"
    TEST_MODE_1 = "TEST_MODE_1"
    TEST_MODE_2 = "TEST_MODE_2"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @property
    def family(self) -> "BoardFamily":
        """The board family these modes belong to (A5203)."""
        return BoardFamily.A5203

    def to_dtq(self) -> int:
        """Return the ``pyferslib.DTQ_*`` family this acquisition mode produces."""
        if self in (AcqMode5203.TEST_MODE_1, AcqMode5203.TEST_MODE_2):
            return pyferslib.DTQ_TEST
        return pyferslib.DTQ_TIMING

    @classmethod
    def from_string(cls, name: str) -> "AcqMode5203":
        """Parse a ferslib ``AcquisitionMode`` string (case-insensitive)."""
        key = str(name).strip().upper()
        for member in cls:
            if member.value == key:
                return member
        raise ValueError(
            f"unknown 5203 AcquisitionMode {name!r}; expected one of "
            f"{[m.value for m in cls]}"
        )


class MeasMode(enum.Enum):
    """A5203 time-measurement mode (param ``MeasMode``, [AcqMode], 5203-only).

    Selects which picoTDC edges/intervals are captured. LEAD_ONLY keeps only the
    leading edge; LEAD_TRAIL keeps both edges; LEAD_TOT8/LEAD_TOT11 keep the
    leading edge plus an 8- or 11-bit time-over-threshold. The A5202 has no
    equivalent (it measures charge, not edges).
    """

    LEAD_ONLY = "LEAD_ONLY"
    LEAD_TRAIL = "LEAD_TRAIL"
    LEAD_TOT8 = "LEAD_TOT8"
    LEAD_TOT11 = "LEAD_TOT11"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @property
    def has_trailing(self) -> bool:
        """Whether this mode records a trailing edge / ToT (i.e. not LEAD_ONLY)."""
        return self is not MeasMode.LEAD_ONLY

    @classmethod
    def from_string(cls, name: str) -> "MeasMode":
        """Parse a ferslib ``MeasMode`` string (case-insensitive)."""
        key = str(name).strip().upper()
        for member in cls:
            if member.value == key:
                return member
        raise ValueError(
            f"unknown MeasMode {name!r}; expected one of {[m.value for m in cls]}"
        )


def acq_mode_enum_for_family(family: "BoardFamily | int") -> type[enum.Enum]:
    """Return the AcquisitionMode enum class for a board family.

    ``BoardFamily.A5202`` (or ``5202``) -> :class:`AcqMode`;
    ``BoardFamily.A5203`` (or ``5203``) -> :class:`AcqMode5203`.
    """
    fam = BoardFamily.from_code(int(family))
    return AcqMode5203 if fam is BoardFamily.A5203 else AcqMode


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
    "BoardFamily",
    "AcqMode",
    "AcqMode5203",
    "MeasMode",
    "acq_mode_enum_for_family",
    "StartMode",
    "SortMode",
    "StopMode",
    "GainSelect",
]
