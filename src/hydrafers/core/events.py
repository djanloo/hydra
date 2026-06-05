"""Event helpers: data-qualifier classification, config->enum/mode mapping,
neutral-dict extraction from ``pyferslib`` event objects, and live histograms.

Layer: ``hydrafers.core`` (CONTRACT.md section 0). The acquisition engine straddles
BOTH Python layers per the data/control split:

* the **data-plane** consumes ``pyferslib`` directly -- this module imports
  ``pyferslib`` for its module-level constants (``DTQ_*``,
  ``RAWDATA_REPROCESS_FINISHED``) and reads the bound event-struct objects' fields;
* the **control-plane** uses ``pyfers`` enums -- this module imports the ``pyfers``
  enums (``StartMode``, ``SortMode``, ``StopMode``, ``AcqMode``) so the engine can
  translate a validated :class:`~hydrafers.config.HydraConfig` (combo strings from
  ``docs/param_defs_reference.txt``) into the typed arguments the SDK expects.

The :func:`extract_event` function is the heart of the WriterThread's field
extraction: it copies the relevant fields out of a ``pyferslib`` event-struct object
into the *neutral dict* representation (CONTRACT.md section 3) that ``hydrafers.io``
consumes. ``hydrafers.io`` must NOT import ``pyferslib``; this module is the only
place where ``pyferslib`` event objects are read.

This module contains ZERO presentation logic and performs NO device I/O.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pyfers
import pyferslib

# Number of channels in the 520X per-channel event arrays (FERSLIB_MAX_NCH_5202).
NUM_CH = 64

# The low nibble of dtq selects the event family; SERVICE/TEST use the full byte.
_DTQ_FAMILY_MASK = 0x0F


# ---------------------------------------------------------------------------
# config combo strings -> pyfers control-plane enums
# ---------------------------------------------------------------------------
# StartRunMode combo options (docs/param_defs_reference.txt [RunCtrl]) -> StartMode.
# TDL_EXTRUN / TDL_EXTRUN_EXTCLK / TDL_EXTCLK collapse onto the TDL external-run
# family; the contract's StartMode enum exposes the canonical members below.
START_MODE_MAP: dict[str, "pyfers.StartMode"] = {
    "ASYNC": pyfers.StartMode.ASYNC,
    "TDL": pyfers.StartMode.TDL,
    "TDL_EXTRUN": pyfers.StartMode.TDL_EXTRUN,
    "TDL_EXTRUN_EXTCLK": pyfers.StartMode.TDL_EXTRUN,
    "TDL_EXTCLK": pyfers.StartMode.TDL_EXTRUN,
    "TDL_GPS": pyfers.StartMode.TDL_GPS,
    "CHAIN_T0": pyfers.StartMode.CHAIN_T0,
    "CHAIN_T1": pyfers.StartMode.CHAIN_T1,
}

# EventBuildingMode combo options -> SortMode (-> ROMODE_* via SortMode.to_romode()).
EVENT_BUILDING_MAP: dict[str, "pyfers.SortMode"] = {
    "DISABLED": pyfers.SortMode.DISABLED,
    "TRGTIME_SORTING": pyfers.SortMode.TRGTIME,
    "TRGID_SORTING": pyfers.SortMode.TRGID,
}

# StopRunMode combo options -> StopMode.
STOP_MODE_MAP: dict[str, "pyfers.StopMode"] = {
    "MANUAL": pyfers.StopMode.MANUAL,
    "PRESET_TIME": pyfers.StopMode.PRESET_TIME,
    "PRESET_COUNTS": pyfers.StopMode.PRESET_COUNTS,
}

# AcquisitionMode combo option -> AcqMode (control-plane enum carrying the ferslib
# string) and -> the dtq family the readout will produce (used to size histograms).
ACQ_MODE_MAP: dict[str, "pyfers.AcqMode"] = {
    "SPECTROSCOPY": pyfers.AcqMode.SPECTROSCOPY,
    "SPECT_TIMING": pyfers.AcqMode.SPECT_TIMING,
    "TIMING_CSTART": pyfers.AcqMode.TIMING_CSTART,
    "TIMING_CSTOP": pyfers.AcqMode.TIMING_CSTOP,
    "COUNTING": pyfers.AcqMode.COUNTING,
    "WAVEFORM": pyfers.AcqMode.WAVEFORM,
}

ACQ_MODE_FAMILY: dict[str, int] = {
    "SPECTROSCOPY": pyferslib.DTQ_SPECT,
    "SPECT_TIMING": pyferslib.DTQ_SPECT | pyferslib.DTQ_TIMING,
    "TIMING_CSTART": pyferslib.DTQ_TIMING,
    "TIMING_CSTOP": pyferslib.DTQ_TIMING,
    "COUNTING": pyferslib.DTQ_COUNT,
    "WAVEFORM": pyferslib.DTQ_WAVE,
}


def map_start_mode(name: str) -> "pyfers.StartMode":
    """Map a ``StartRunMode`` config string to a :class:`pyfers.StartMode`.

    Raises ``ValueError`` for an unknown option so misconfiguration fails loudly.
    """
    try:
        return START_MODE_MAP[name.strip().upper()]
    except KeyError as exc:
        raise ValueError(
            f"unknown StartRunMode {name!r}; expected one of {sorted(START_MODE_MAP)}"
        ) from exc


def map_event_building_mode(name: str) -> "pyfers.SortMode":
    """Map an ``EventBuildingMode`` config string to a :class:`pyfers.SortMode`."""
    try:
        return EVENT_BUILDING_MAP[name.strip().upper()]
    except KeyError as exc:
        raise ValueError(
            f"unknown EventBuildingMode {name!r}; expected one of "
            f"{sorted(EVENT_BUILDING_MAP)}"
        ) from exc


def map_stop_mode(name: str) -> "pyfers.StopMode":
    """Map a ``StopRunMode`` config string to a :class:`pyfers.StopMode`."""
    try:
        return STOP_MODE_MAP[name.strip().upper()]
    except KeyError as exc:
        raise ValueError(
            f"unknown StopRunMode {name!r}; expected one of {sorted(STOP_MODE_MAP)}"
        ) from exc


def map_acq_mode(name: str) -> "pyfers.AcqMode":
    """Map an ``AcquisitionMode`` config string to a :class:`pyfers.AcqMode`."""
    return ACQ_MODE_MAP.get(name.strip().upper(), pyfers.AcqMode.SPECTROSCOPY)


def map_acq_mode_family(name: str) -> int:
    """Map an ``AcquisitionMode`` config string to its expected dtq family mask."""
    return ACQ_MODE_FAMILY.get(name.strip().upper(), pyferslib.DTQ_SPECT)


# ---------------------------------------------------------------------------
# data-qualifier classification (mirror FERSlib.h / CONTRACT.md section 1a)
# ---------------------------------------------------------------------------
def dtq_family(dtq: int) -> int:
    """Return the low-nibble event family of a raw data qualifier."""
    return dtq & _DTQ_FAMILY_MASK


def is_service(dtq: int) -> bool:
    """True if the event is a service event (HV/temperature/counters)."""
    return dtq == pyferslib.DTQ_SERVICE


def is_test(dtq: int) -> bool:
    """True if the event is a test-pattern event."""
    return dtq == pyferslib.DTQ_TEST


def is_spect(dtq: int) -> bool:
    """True for SPECT or TSPECT events (carry energyHG/energyLG arrays)."""
    return dtq != pyferslib.DTQ_SERVICE and (dtq & pyferslib.DTQ_SPECT) != 0


def is_tspect(dtq: int) -> bool:
    """True for a TSPECT event (SPECT + TIMING; carries per-channel ToA/ToT)."""
    return (
        dtq != pyferslib.DTQ_SERVICE
        and (dtq & pyferslib.DTQ_SPECT) != 0
        and (dtq & pyferslib.DTQ_TIMING) != 0
    )


def is_timing_only(dtq: int) -> bool:
    """True for a pure timing (list) event, i.e. TIMING set but SPECT clear."""
    return (
        dtq != pyferslib.DTQ_SERVICE
        and (dtq & pyferslib.DTQ_TIMING) != 0
        and (dtq & pyferslib.DTQ_SPECT) == 0
    )


def is_count(dtq: int) -> bool:
    """True for a counting (MCS) event."""
    return dtq != pyferslib.DTQ_SERVICE and (dtq & pyferslib.DTQ_COUNT) != 0


def is_wave(dtq: int) -> bool:
    """True for a waveform event."""
    return dtq != pyferslib.DTQ_SERVICE and (dtq & pyferslib.DTQ_WAVE) != 0


def is_reprocess_sentinel(board: int, dtq: int) -> bool:
    """True if a drained tuple is the end-of-offline-reprocessing sentinel.

    ``pyferslib.drain_events`` / ``get_event`` flag the end of offline raw-data
    reprocessing as ``(-1, RAWDATA_REPROCESS_FINISHED, None)`` (CONTRACT.md 1a).
    """
    return board < 0 and dtq == pyferslib.RAWDATA_REPROCESS_FINISHED


# ---------------------------------------------------------------------------
# neutral-dict extraction from pyferslib event-struct objects (CONTRACT.md 3)
# ---------------------------------------------------------------------------
def _arr(value: Any) -> np.ndarray:
    """Return ``value`` as a numpy array (already a copied array from pyferslib)."""
    return np.asarray(value)


def extract_event(board: int, dtq: int, raw: Any) -> dict[str, Any] | None:
    """Copy a ``pyferslib`` event-struct object into the neutral io dict.

    This is the ONLY place ``pyferslib`` event objects are read. The returned dict
    has exactly the per-mode key set ``hydrafers.io.EventWriter`` expects
    (CONTRACT.md section 3). Returns ``None`` for the reprocess sentinel or an
    unrecognised qualifier (so the writer never sees a malformed record).

    The bound struct field names follow CONTRACT.md section 1a (snake_case,
    ``toa`` derived from the C ``tstamp`` array, copied NumPy arrays).
    """
    if raw is None:
        return None
    if is_service(dtq):
        return _extract_service(board, dtq, raw)
    if is_test(dtq):
        return _extract_test(board, dtq, raw)
    if is_spect(dtq):
        return _extract_spect(board, dtq, raw)
    if is_timing_only(dtq):
        return _extract_timing(board, dtq, raw)
    if is_count(dtq):
        return _extract_count(board, dtq, raw)
    if is_wave(dtq):
        return _extract_wave(board, dtq, raw)
    return None


def _extract_spect(board: int, dtq: int, raw: Any) -> dict[str, Any]:
    event: dict[str, Any] = {
        "board": int(board),
        "dtq": int(dtq),
        "tstamp_us": float(raw.tstamp_us),
        "rel_tstamp_us": float(getattr(raw, "rel_tstamp_us", 0.0)),
        "tstamp_clk": int(getattr(raw, "tstamp_clk", 0)),
        "tref_tstamp": int(getattr(raw, "tref_tstamp", 0)),
        "trigger_id": int(raw.trigger_id),
        "chmask": int(raw.chmask),
        "qdmask": int(getattr(raw, "qdmask", 0)),
        "energy_hg": _arr(raw.energy_hg),
        "energy_lg": _arr(raw.energy_lg),
    }
    # TSPECT events additionally carry per-channel ToA (.tstamp -> toa) and ToT.
    if is_tspect(dtq):
        event["toa"] = _arr(raw.toa)
        event["tot"] = _arr(raw.tot)
    return event


def _extract_count(board: int, dtq: int, raw: Any) -> dict[str, Any]:
    return {
        "board": int(board),
        "dtq": int(dtq),
        "tstamp_us": float(raw.tstamp_us),
        "rel_tstamp_us": float(getattr(raw, "rel_tstamp_us", 0.0)),
        "trigger_id": int(raw.trigger_id),
        "chmask": int(raw.chmask),
        "counts": _arr(raw.counts),
        "t_or_counts": int(getattr(raw, "t_or_counts", 0)),
        "q_or_counts": int(getattr(raw, "q_or_counts", 0)),
    }


def _extract_timing(board: int, dtq: int, raw: Any) -> dict[str, Any]:
    nhits = int(raw.nhits)
    return {
        "board": int(board),
        "dtq": int(dtq),
        "tstamp_us": float(raw.tstamp_us),
        "tref_tstamp": int(getattr(raw, "tref_tstamp", 0)),
        "tstamp_clk": int(getattr(raw, "tstamp_clk", 0)),
        "trigger_id": int(raw.trigger_id),
        "nhits": nhits,
        "channel": _arr(raw.channel),
        "edge": _arr(raw.edge),
        "toa": _arr(raw.toa),
        "tot": _arr(raw.tot),
    }


def _extract_wave(board: int, dtq: int, raw: Any) -> dict[str, Any]:
    ns = int(raw.ns)
    return {
        "board": int(board),
        "dtq": int(dtq),
        "tstamp_us": float(raw.tstamp_us),
        "trigger_id": int(raw.trigger_id),
        "ns": ns,
        "wave_hg": _arr(raw.wave_hg),
        "wave_lg": _arr(raw.wave_lg),
        "dig_probes": _arr(raw.dig_probes),
    }


def _extract_service(board: int, dtq: int, raw: Any) -> dict[str, Any]:
    # The bound ServEvent exposes hv_status_on/ramp/ovv/ovc; the io dict (and the
    # engine's service tap) use the shorter hv_on/hv_ramp/hv_ovv/hv_ovc keys.
    return {
        "board": int(board),
        "dtq": int(dtq),
        "tstamp_us": float(raw.tstamp_us),
        "update_time": int(getattr(raw, "update_time", 0)),
        "pkt_size": int(getattr(raw, "pkt_size", 0)),
        "version": int(getattr(raw, "version", 0)),
        "format": int(getattr(raw, "format", 0)),
        "ch_trg_cnt": _arr(raw.ch_trg_cnt),
        "q_or_cnt": int(getattr(raw, "q_or_cnt", 0)),
        "t_or_cnt": int(getattr(raw, "t_or_cnt", 0)),
        "temp_fpga": float(getattr(raw, "temp_fpga", 0.0)),
        "temp_board": float(getattr(raw, "temp_board", 0.0)),
        "temp_tdc0": float(getattr(raw, "temp_tdc0", 0.0)),
        "temp_tdc1": float(getattr(raw, "temp_tdc1", 0.0)),
        "temp_hv": float(getattr(raw, "temp_hv", 0.0)),
        "temp_detector": float(getattr(raw, "temp_detector", 0.0)),
        "hv_vmon": float(getattr(raw, "hv_vmon", 0.0)),
        "hv_imon": float(getattr(raw, "hv_imon", 0.0)),
        "hv_on": int(getattr(raw, "hv_status_on", 0)),
        "hv_ramp": int(getattr(raw, "hv_status_ramp", 0)),
        "hv_ovv": int(getattr(raw, "hv_status_ovv", 0)),
        "hv_ovc": int(getattr(raw, "hv_status_ovc", 0)),
        "status": int(getattr(raw, "status", 0)),
        "tdc_ro_status": int(getattr(raw, "tdc_ro_status", 0)),
        "readout_flags": int(getattr(raw, "readout_flags", 0)),
        "tot_trg_cnt": int(getattr(raw, "tot_trg_cnt", 0)),
        "rej_trg_cnt": int(getattr(raw, "rej_trg_cnt", 0)),
        "suppr_trg_cnt": int(getattr(raw, "suppr_trg_cnt", 0)),
    }


def _extract_test(board: int, dtq: int, raw: Any) -> dict[str, Any]:
    nwords = int(raw.nwords)
    return {
        "board": int(board),
        "dtq": int(dtq),
        "tstamp_us": float(raw.tstamp_us),
        "trigger_id": int(raw.trigger_id),
        "nwords": nwords,
        "test_data": _arr(raw.test_data),
    }


def event_nbytes(event: dict[str, Any]) -> int:
    """Estimate the raw payload size of an extracted event in bytes.

    Used only for data-rate (MB/s) statistics, not for storage. Sums the numpy
    array payloads present in the event dict (energy/toa/tot/counts/waveform/...);
    falls back to a small fixed header cost for scalar-only events.
    """
    total = 32  # nominal header / scalar fields
    for value in event.values():
        if isinstance(value, np.ndarray):
            total += int(value.nbytes)
    return total


class HistogramSet:
    """Mutable accumulator for the live histograms exposed via ``histograms()``.

    Shapes (CONTRACT.md section 4 ``histograms()``):
      * ``e_spec_hg`` / ``e_spec_lg`` : ``[nboards, NUM_CH, e_nbins]`` uint32
      * ``toa``                       : ``[nboards, NUM_CH, toa_nbins]`` uint32
      * ``tot``                       : ``[nboards, NUM_CH, toa_nbins]`` uint32
      * ``mcs``                       : ``[nboards, mcs_nbins]`` uint32 (counts vs time)
      * ``cnt_2d``                    : ``[nboards, NUM_CH]`` uint64 (per-channel totals)

    The engine owns one instance, mutated only by the stats thread. ``snapshot()``
    returns independent copies for handing to frontends.
    """

    def __init__(
        self,
        nboards: int,
        e_nbins: int = 4096,
        toa_nbins: int = 4096,
        mcs_nbins: int = 4096,
    ) -> None:
        self.nboards = max(0, int(nboards))
        self.e_nbins = max(1, int(e_nbins))
        self.toa_nbins = max(1, int(toa_nbins))
        self.mcs_nbins = max(1, int(mcs_nbins))
        nb = self.nboards
        self.e_spec_hg = np.zeros((nb, NUM_CH, self.e_nbins), dtype=np.uint32)
        self.e_spec_lg = np.zeros((nb, NUM_CH, self.e_nbins), dtype=np.uint32)
        self.toa = np.zeros((nb, NUM_CH, self.toa_nbins), dtype=np.uint32)
        self.tot = np.zeros((nb, NUM_CH, self.toa_nbins), dtype=np.uint32)
        self.mcs = np.zeros((nb, self.mcs_nbins), dtype=np.uint32)
        self.cnt_2d = np.zeros((nb, NUM_CH), dtype=np.uint64)
        self._mcs_bin = 0  # advancing time bin index for the MCS strip chart

    def reset(self) -> None:
        """Zero all histograms (called at start_run)."""
        self.e_spec_hg.fill(0)
        self.e_spec_lg.fill(0)
        self.toa.fill(0)
        self.tot.fill(0)
        self.mcs.fill(0)
        self.cnt_2d.fill(0)
        self._mcs_bin = 0

    def _shift_index(self, values: np.ndarray, nbins: int) -> np.ndarray:
        """Clip a uint array of bin indices into ``[0, nbins)`` for safe scatter."""
        idx = values.astype(np.int64, copy=False)
        np.clip(idx, 0, nbins - 1, out=idx)
        return idx

    def _bin_scale(self, values: np.ndarray, src_bits: int, nbins: int) -> np.ndarray:
        """Scale raw ``src_bits``-wide values down onto ``nbins`` histogram bins."""
        max_val = 1 << src_bits
        idx = (values.astype(np.int64, copy=False) * nbins) // max_val
        np.clip(idx, 0, nbins - 1, out=idx)
        return idx

    def accumulate(self, event: dict[str, Any]) -> None:
        """Fold one extracted event into the histograms.

        Out-of-range boards are ignored so a misreported board index can never
        corrupt memory.
        """
        board = int(event.get("board", -1))
        if board < 0 or board >= self.nboards:
            return
        dtq = int(event.get("dtq", -1))
        if dtq < 0:
            return

        if is_spect(dtq):
            self._accumulate_spect(board, event)
        if is_timing_only(dtq):
            self._accumulate_timing(board, event)
        if is_count(dtq):
            self._accumulate_count(board, event)

    def _accumulate_spect(self, board: int, event: dict[str, Any]) -> None:
        hg = event.get("energy_hg")
        lg = event.get("energy_lg")
        if hg is not None:
            idx = self._bin_scale(np.asarray(hg), 14, self.e_nbins)
            ch = np.arange(min(len(idx), NUM_CH))
            np.add.at(self.e_spec_hg, (board, ch, idx[: len(ch)]), 1)
        if lg is not None:
            idx = self._bin_scale(np.asarray(lg), 14, self.e_nbins)
            ch = np.arange(min(len(idx), NUM_CH))
            np.add.at(self.e_spec_lg, (board, ch, idx[: len(ch)]), 1)
        # TSPECT carries per-channel ToA/ToT too.
        toa = event.get("toa")
        tot = event.get("tot")
        if toa is not None and np.asarray(toa).ndim == 1 and len(np.asarray(toa)) >= NUM_CH:
            idx = self._shift_index(np.asarray(toa)[:NUM_CH], self.toa_nbins)
            ch = np.arange(NUM_CH)
            np.add.at(self.toa, (board, ch, idx), 1)
        if tot is not None and np.asarray(tot).ndim == 1 and len(np.asarray(tot)) >= NUM_CH:
            idx = self._shift_index(np.asarray(tot)[:NUM_CH], self.toa_nbins)
            ch = np.arange(NUM_CH)
            np.add.at(self.tot, (board, ch, idx), 1)

    def _accumulate_timing(self, board: int, event: dict[str, Any]) -> None:
        channel = event.get("channel")
        toa = event.get("toa")
        tot = event.get("tot")
        if channel is None:
            return
        chan = np.asarray(channel).astype(np.int64, copy=False)
        valid = (chan >= 0) & (chan < NUM_CH)
        if not valid.any():
            return
        chan = chan[valid]
        if toa is not None:
            tarr = np.asarray(toa)[valid]
            idx = self._shift_index(tarr, self.toa_nbins)
            np.add.at(self.toa, (board, chan, idx), 1)
        if tot is not None:
            totarr = np.asarray(tot)[valid]
            idx = self._shift_index(totarr, self.toa_nbins)
            np.add.at(self.tot, (board, chan, idx), 1)
        np.add.at(self.cnt_2d, (board, chan), 1)

    def _accumulate_count(self, board: int, event: dict[str, Any]) -> None:
        counts = event.get("counts")
        if counts is None:
            return
        carr = np.asarray(counts).astype(np.uint64, copy=False)
        n = min(len(carr), NUM_CH)
        self.cnt_2d[board, :n] += carr[:n]
        # MCS strip: total counts in this event accumulate into the current time bin.
        total = int(carr.sum())
        self.mcs[board, self._mcs_bin % self.mcs_nbins] += total

    def advance_mcs_bin(self) -> None:
        """Advance the MCS time bin (called once per stats tick in counting mode)."""
        self._mcs_bin += 1

    def snapshot(self) -> dict[str, np.ndarray]:
        """Return independent copies of every histogram for a frontend."""
        return {
            "e_spec_hg": np.array(self.e_spec_hg, copy=True),
            "e_spec_lg": np.array(self.e_spec_lg, copy=True),
            "toa": np.array(self.toa, copy=True),
            "tot": np.array(self.tot, copy=True),
            "mcs": np.array(self.mcs, copy=True),
            "cnt_2d": np.array(self.cnt_2d, copy=True),
        }
