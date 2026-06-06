"""Tests for pyfers.events — decode() routing and from_raw field extraction."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import pyferslib
from pyfers.events import (
    CountingEvent,
    ListEvent,
    ServiceEvent,
    SpectEvent,
    WaveEvent,
    decode,
)
# Alias to avoid pytest trying to collect the `TestEvent` dataclass as a test class.
from pyfers.events import TestEvent as _TestEvent


def test_decode_spect_with_c_spelling_fallback():
    # energyLG is the original C spelling; the wrapper must still pick it up.
    raw = SimpleNamespace(tstamp_us=1.5, trigger_id=7, chmask=0xF,
                          energy_hg=[1, 2, 3], energyLG=[4, 5, 6])
    ev = decode(board=2, dtq=pyferslib.DTQ_SPECT, raw=raw)
    assert isinstance(ev, SpectEvent)
    assert (ev.board, ev.dtq) == (2, pyferslib.DTQ_SPECT)
    assert ev.tstamp_us == 1.5 and ev.trigger_id == 7 and ev.chmask == 0xF
    assert list(ev.energy_hg) == [1, 2, 3]
    assert list(ev.energy_lg) == [4, 5, 6]


def test_decode_spect_wins_over_timing_nibble():
    # SPECT_TIMING sets both bits; SPECT must take precedence -> SpectEvent.
    ev = decode(0, pyferslib.DTQ_SPECT | pyferslib.DTQ_TIMING, SimpleNamespace())
    assert isinstance(ev, SpectEvent)


def test_decode_pure_timing_is_list_event():
    ev = decode(0, pyferslib.DTQ_TIMING, SimpleNamespace(nhits=3, channel=[0, 1, 2]))
    assert isinstance(ev, ListEvent)
    assert ev.nhits == 3
    assert list(ev.channel) == [0, 1, 2]


def test_decode_counting_and_wave():
    c = decode(0, pyferslib.DTQ_COUNT, SimpleNamespace(counts=[1, 2], t_or_cnt=9))
    assert isinstance(c, CountingEvent)
    assert list(c.counts) == [1, 2]
    assert c.t_or_counts == 9  # t_or_cnt C-spelling fallback

    w = decode(0, pyferslib.DTQ_WAVE, SimpleNamespace(ns=5, wave_hg=[0, 1, 2, 3, 4]))
    assert isinstance(w, WaveEvent)
    assert w.ns == 5 and list(w.wave_hg) == [0, 1, 2, 3, 4]


def test_decode_service_by_full_byte():
    raw = SimpleNamespace(tempFPGA=40.0, hv_Vmon=62.0, hv_imon=0.3)
    ev = decode(0, pyferslib.DTQ_SERVICE, raw)
    assert isinstance(ev, ServiceEvent)
    assert ev.temp_fpga == 40.0   # tempFPGA fallback
    assert ev.hv_vmon == 62.0     # hv_Vmon fallback


def test_decode_test_by_full_byte():
    ev = decode(0, pyferslib.DTQ_TEST, SimpleNamespace(nwords=4, test_data=[1, 2, 3, 4]))
    assert isinstance(ev, _TestEvent)
    assert ev.nwords == 4 and list(ev.test_data) == [1, 2, 3, 4]


def test_decode_missing_fields_default_safely():
    # An empty struct must not crash; numeric fields default, arrays stay None.
    ev = decode(0, pyferslib.DTQ_SPECT, SimpleNamespace())
    assert ev.tstamp_us == 0.0 and ev.trigger_id == 0
    assert ev.energy_hg is None


def test_decode_unknown_dtq_raises():
    # 0x10: low nibble 0 -> no family bit, and not SERVICE/TEST.
    with pytest.raises(ValueError):
        decode(0, 0x10, SimpleNamespace())
