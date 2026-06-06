"""Tests for pyfers.enums — verbatim option strings + ferslib int resolution."""

from __future__ import annotations

import pytest

import pyferslib
from pyfers import AcqMode, GainSelect, SortMode, StartMode, StopMode


# ------------------------------------------------------------------ StartMode
def test_startmode_to_ferslib_int():
    assert StartMode.ASYNC.to_ferslib_int() == pyferslib.START_ASYNC
    assert StartMode.TDL.to_ferslib_int() == pyferslib.START_TDL
    assert StartMode.CHAIN_T0.to_ferslib_int() == pyferslib.START_CHAIN_T0
    assert StartMode.CHAIN_T1.to_ferslib_int() == pyferslib.START_CHAIN_T1


@pytest.mark.parametrize(
    "text, member",
    [("async", StartMode.ASYNC), ("TDL", StartMode.TDL),
     ("  chain_t1  ", StartMode.CHAIN_T1)],
)
def test_startmode_from_string_case_insensitive(text, member):
    assert StartMode.from_string(text) is member


def test_startmode_from_string_invalid():
    with pytest.raises(ValueError):
        StartMode.from_string("nope")


# ------------------------------------------------------------------- SortMode
def test_sortmode_to_romode():
    assert SortMode.DISABLED.to_romode() == pyferslib.ROMODE_DISABLE_SORTING
    assert SortMode.TRGTIME.to_romode() == pyferslib.ROMODE_TRGTIME_SORTING
    assert SortMode.TRGID.to_romode() == pyferslib.ROMODE_TRGID_SORTING


def test_sortmode_from_string_uses_verbatim_value():
    # The wire value is "TRGTIME_SORTING", not the member name "TRGTIME".
    assert SortMode.from_string("trgtime_sorting") is SortMode.TRGTIME
    assert SortMode.TRGTIME.value == "TRGTIME_SORTING"


# ------------------------------------------------------------------- StopMode
def test_stopmode_ints_and_parse():
    assert StopMode.MANUAL.to_ferslib_int() == 0
    assert StopMode.PRESET_TIME.to_ferslib_int() == 1
    assert StopMode.PRESET_COUNTS.to_ferslib_int() == 2
    assert StopMode.from_string("preset_counts") is StopMode.PRESET_COUNTS


# -------------------------------------------------------------------- AcqMode
def test_acqmode_to_dtq():
    assert AcqMode.SPECTROSCOPY.to_dtq() == pyferslib.DTQ_SPECT
    assert AcqMode.SPECT_TIMING.to_dtq() == (pyferslib.DTQ_SPECT | pyferslib.DTQ_TIMING)
    assert AcqMode.TIMING_CSTART.to_dtq() == pyferslib.DTQ_TIMING
    assert AcqMode.COUNTING.to_dtq() == pyferslib.DTQ_COUNT
    assert AcqMode.WAVEFORM.to_dtq() == pyferslib.DTQ_WAVE


# ----------------------------------------------------------------- GainSelect
def test_gainselect_parse():
    assert GainSelect.from_string("high") is GainSelect.HIGH
    assert GainSelect.from_string("BOTH") is GainSelect.BOTH
    with pytest.raises(ValueError):
        GainSelect.from_string("ultra")


def test_str_returns_verbatim_value():
    assert str(AcqMode.SPECT_TIMING) == "SPECT_TIMING"
    assert str(StartMode.ASYNC) == "ASYNC"
