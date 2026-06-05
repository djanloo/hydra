"""Typed, ergonomic event wrappers for the FERS SDK.

Role: present the read-only struct objects produced by the faithful binding
(``pyferslib`` ``SpectEvent``/``CountingEvent``/...) as documented Python
dataclasses with stable, snake_case attributes and the event's ``board``/``dtq``
context attached. These are for interactive and SDK use; the high-rate engine
data-plane may keep consuming the raw ``pyferslib`` structs directly (CONTRACT.md
section 1b note).

Layer: ``pyfers`` (CONTRACT.md section 1b). Imports ``pyferslib`` ONLY.

``decode(board, dtq, raw)`` chooses the right wrapper from the data-qualifier:
the low nibble selects the family (SPECT/TIMING/COUNT/WAVE) while the full byte
distinguishes SERVICE (0x2F) and TEST (0xFF).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pyferslib


def _get(raw: Any, *names: str, default: Any = None) -> Any:
    """Return the first present attribute of ``raw`` among ``names``.

    The faithful binding snake_case-izes the C field names (CONTRACT.md section
    1a), but we accept the original C spellings too so the wrappers keep working
    regardless of the exact binding convention.
    """
    for name in names:
        if hasattr(raw, name):
            return getattr(raw, name)
    return default


def _as_array(value: Any) -> np.ndarray | None:
    """Coerce a struct field to a numpy array (copy), or ``None`` if absent."""
    if value is None:
        return None
    return np.asarray(value)


@dataclass
class SpectEvent:
    """Spectroscopy event (optionally with timing), ``DTQ_SPECT`` family.

    Carries per-channel high/low gain energies and, in SPECT_TIMING mode, the
    per-channel ToA (from the struct ``tstamp`` array) and ToT.
    """

    board: int
    dtq: int
    tstamp_us: float
    rel_tstamp_us: float
    tstamp_clk: int
    tref_tstamp: int
    trigger_id: int
    chmask: int
    qdmask: int
    energy_hg: np.ndarray | None = None
    energy_lg: np.ndarray | None = None
    toa: np.ndarray | None = None
    tot: np.ndarray | None = None

    @classmethod
    def from_raw(cls, board: int, raw: Any, dtq: int = pyferslib.DTQ_SPECT) -> "SpectEvent":
        """Build a :class:`SpectEvent` from a raw ``pyferslib.SpectEvent``."""
        return cls(
            board=int(board),
            dtq=int(dtq),
            tstamp_us=float(_get(raw, "tstamp_us", default=0.0)),
            rel_tstamp_us=float(_get(raw, "rel_tstamp_us", default=0.0)),
            tstamp_clk=int(_get(raw, "tstamp_clk", default=0)),
            tref_tstamp=int(_get(raw, "tref_tstamp", "Tref_tstamp", default=0)),
            trigger_id=int(_get(raw, "trigger_id", default=0)),
            chmask=int(_get(raw, "chmask", default=0)),
            qdmask=int(_get(raw, "qdmask", default=0)),
            energy_hg=_as_array(_get(raw, "energy_hg", "energyHG")),
            energy_lg=_as_array(_get(raw, "energy_lg", "energyLG")),
            toa=_as_array(_get(raw, "toa", "tstamp")),
            tot=_as_array(_get(raw, "tot", "ToT")),
        )


@dataclass
class CountingEvent:
    """Counting / MCS event, ``DTQ_COUNT`` family."""

    board: int
    dtq: int
    tstamp_us: float
    rel_tstamp_us: float
    trigger_id: int
    chmask: int
    counts: np.ndarray | None = None
    t_or_counts: int = 0
    q_or_counts: int = 0

    @classmethod
    def from_raw(cls, board: int, raw: Any, dtq: int = pyferslib.DTQ_COUNT) -> "CountingEvent":
        """Build a :class:`CountingEvent` from a raw ``pyferslib.CountingEvent``."""
        return cls(
            board=int(board),
            dtq=int(dtq),
            tstamp_us=float(_get(raw, "tstamp_us", default=0.0)),
            rel_tstamp_us=float(_get(raw, "rel_tstamp_us", default=0.0)),
            trigger_id=int(_get(raw, "trigger_id", default=0)),
            chmask=int(_get(raw, "chmask", default=0)),
            counts=_as_array(_get(raw, "counts")),
            t_or_counts=int(_get(raw, "t_or_counts", "t_or_cnt", default=0)),
            q_or_counts=int(_get(raw, "q_or_counts", "q_or_cnt", default=0)),
        )


@dataclass
class WaveEvent:
    """Waveform event, ``DTQ_WAVE`` family.

    ``ns`` is the number of valid samples; the wave arrays are length-``ns``.
    """

    board: int
    dtq: int
    tstamp_us: float
    trigger_id: int
    ns: int
    wave_hg: np.ndarray | None = None
    wave_lg: np.ndarray | None = None
    dig_probes: np.ndarray | None = None

    @classmethod
    def from_raw(cls, board: int, raw: Any, dtq: int = pyferslib.DTQ_WAVE) -> "WaveEvent":
        """Build a :class:`WaveEvent` from a raw ``pyferslib.WaveEvent``."""
        return cls(
            board=int(board),
            dtq=int(dtq),
            tstamp_us=float(_get(raw, "tstamp_us", default=0.0)),
            trigger_id=int(_get(raw, "trigger_id", default=0)),
            ns=int(_get(raw, "ns", default=0)),
            wave_hg=_as_array(_get(raw, "wave_hg")),
            wave_lg=_as_array(_get(raw, "wave_lg")),
            dig_probes=_as_array(_get(raw, "dig_probes")),
        )


@dataclass
class ListEvent:
    """Timing list event, pure ``DTQ_TIMING`` family.

    ``nhits`` is the number of valid hits; the per-hit arrays are length-``nhits``
    (channel, edge, toa from the struct ``tstamp`` array, tot).
    """

    board: int
    dtq: int
    tstamp_us: float
    tref_tstamp: int
    tstamp_clk: int
    trigger_id: int
    nhits: int
    channel: np.ndarray | None = None
    edge: np.ndarray | None = None
    toa: np.ndarray | None = None
    tot: np.ndarray | None = None

    @classmethod
    def from_raw(cls, board: int, raw: Any, dtq: int = pyferslib.DTQ_TIMING) -> "ListEvent":
        """Build a :class:`ListEvent` from a raw ``pyferslib.ListEvent``."""
        return cls(
            board=int(board),
            dtq=int(dtq),
            tstamp_us=float(_get(raw, "tstamp_us", default=0.0)),
            tref_tstamp=int(_get(raw, "tref_tstamp", "Tref_tstamp", default=0)),
            tstamp_clk=int(_get(raw, "tstamp_clk", default=0)),
            trigger_id=int(_get(raw, "trigger_id", default=0)),
            nhits=int(_get(raw, "nhits", default=0)),
            channel=_as_array(_get(raw, "channel")),
            edge=_as_array(_get(raw, "edge")),
            toa=_as_array(_get(raw, "toa", "tstamp", "ToA")),
            tot=_as_array(_get(raw, "tot", "ToT")),
        )


@dataclass
class ServiceEvent:
    """Service event (``DTQ_SERVICE`` == 0x2F): HV, temperatures, counters."""

    board: int
    dtq: int
    tstamp_us: float
    update_time: int
    pkt_size: int
    version: int
    format: int
    ch_trg_cnt: np.ndarray | None = None
    q_or_cnt: int = 0
    t_or_cnt: int = 0
    temp_fpga: float = 0.0
    temp_board: float = 0.0
    temp_tdc0: float = 0.0
    temp_tdc1: float = 0.0
    temp_hv: float = 0.0
    temp_detector: float = 0.0
    hv_vmon: float = 0.0
    hv_imon: float = 0.0
    hv_status_on: int = 0
    hv_status_ramp: int = 0
    hv_status_ovv: int = 0
    hv_status_ovc: int = 0
    status: int = 0
    tdc_ro_status: int = 0
    readout_flags: int = 0
    tot_trg_cnt: int = 0
    rej_trg_cnt: int = 0
    suppr_trg_cnt: int = 0

    @classmethod
    def from_raw(cls, board: int, raw: Any, dtq: int = pyferslib.DTQ_SERVICE) -> "ServiceEvent":
        """Build a :class:`ServiceEvent` from a raw ``pyferslib.ServEvent``."""
        return cls(
            board=int(board),
            dtq=int(dtq),
            tstamp_us=float(_get(raw, "tstamp_us", default=0.0)),
            update_time=int(_get(raw, "update_time", default=0)),
            pkt_size=int(_get(raw, "pkt_size", default=0)),
            version=int(_get(raw, "version", default=0)),
            format=int(_get(raw, "format", default=0)),
            ch_trg_cnt=_as_array(_get(raw, "ch_trg_cnt")),
            q_or_cnt=int(_get(raw, "q_or_cnt", default=0)),
            t_or_cnt=int(_get(raw, "t_or_cnt", default=0)),
            temp_fpga=float(_get(raw, "temp_fpga", "tempFPGA", default=0.0)),
            temp_board=float(_get(raw, "temp_board", "tempBoard", default=0.0)),
            temp_tdc0=float(_get(raw, "temp_tdc0", default=0.0)),
            temp_tdc1=float(_get(raw, "temp_tdc1", default=0.0)),
            temp_hv=float(_get(raw, "temp_hv", "tempHV", default=0.0)),
            temp_detector=float(_get(raw, "temp_detector", "tempDetector", default=0.0)),
            hv_vmon=float(_get(raw, "hv_vmon", "hv_Vmon", default=0.0)),
            hv_imon=float(_get(raw, "hv_imon", "hv_Imon", default=0.0)),
            hv_status_on=int(_get(raw, "hv_status_on", default=0)),
            hv_status_ramp=int(_get(raw, "hv_status_ramp", default=0)),
            hv_status_ovv=int(_get(raw, "hv_status_ovv", default=0)),
            hv_status_ovc=int(_get(raw, "hv_status_ovc", default=0)),
            status=int(_get(raw, "status", "Status", default=0)),
            tdc_ro_status=int(_get(raw, "tdc_ro_status", "TDCROStatus", default=0)),
            readout_flags=int(_get(raw, "readout_flags", "ReadoutFlags", default=0)),
            tot_trg_cnt=int(_get(raw, "tot_trg_cnt", "TotTrg_cnt", default=0)),
            rej_trg_cnt=int(_get(raw, "rej_trg_cnt", "RejTrg_cnt", default=0)),
            suppr_trg_cnt=int(_get(raw, "suppr_trg_cnt", "SupprTrg_cnt", default=0)),
        )


@dataclass
class TestEvent:
    """Test-pattern event (``DTQ_TEST`` == 0xFF)."""

    board: int
    dtq: int
    tstamp_us: float
    trigger_id: int
    nwords: int
    test_data: np.ndarray | None = None

    @classmethod
    def from_raw(cls, board: int, raw: Any, dtq: int = pyferslib.DTQ_TEST) -> "TestEvent":
        """Build a :class:`TestEvent` from a raw ``pyferslib.TestEvent``."""
        return cls(
            board=int(board),
            dtq=int(dtq),
            tstamp_us=float(_get(raw, "tstamp_us", default=0.0)),
            trigger_id=int(_get(raw, "trigger_id", default=0)),
            nwords=int(_get(raw, "nwords", default=0)),
            test_data=_as_array(_get(raw, "test_data")),
        )


# Family mask: the low nibble of the data-qualifier selects the event family.
_DTQ_FAMILY_MASK = 0x0F


def decode(board: int, dtq: int, raw: Any) -> Any:
    """Wrap a raw ``pyferslib`` event struct in its typed dataclass.

    Selection rule (CONTRACT.md section 1a/1b):
      * ``dtq == DTQ_SERVICE`` (0x2F) -> :class:`ServiceEvent`
      * ``dtq == DTQ_TEST``    (0xFF) -> :class:`TestEvent`
      * otherwise the low nibble selects the family:
          - SPECT bit set                -> :class:`SpectEvent`
          - TIMING set, SPECT clear      -> :class:`ListEvent`
          - COUNT bit set                -> :class:`CountingEvent`
          - WAVE bit set                 -> :class:`WaveEvent`

    Raises :class:`ValueError` for an unrecognized data-qualifier.
    """
    dtq = int(dtq)
    if dtq == pyferslib.DTQ_SERVICE:
        return ServiceEvent.from_raw(board, raw, dtq)
    if dtq == pyferslib.DTQ_TEST:
        return TestEvent.from_raw(board, raw, dtq)

    family = dtq & _DTQ_FAMILY_MASK
    if family & pyferslib.DTQ_SPECT:
        return SpectEvent.from_raw(board, raw, dtq)
    if family & pyferslib.DTQ_TIMING:
        return ListEvent.from_raw(board, raw, dtq)
    if family & pyferslib.DTQ_COUNT:
        return CountingEvent.from_raw(board, raw, dtq)
    if family & pyferslib.DTQ_WAVE:
        return WaveEvent.from_raw(board, raw, dtq)

    raise ValueError(f"unrecognized data qualifier dtq=0x{dtq:02X}")


__all__ = [
    "SpectEvent",
    "CountingEvent",
    "WaveEvent",
    "ListEvent",
    "ServiceEvent",
    "TestEvent",
    "decode",
]
