"""Per-family live histograms: factory + 5202/5203 accumulation shapes."""

from __future__ import annotations

import numpy as np
import pyferslib

from hydrafers.core.events import (
    HistogramSet,
    HistogramSet5203,
    make_histogram_set,
)


def test_factory_picks_family():
    assert isinstance(make_histogram_set(5202, 1), HistogramSet)
    assert isinstance(make_histogram_set(5203, 1), HistogramSet5203)
    # default channel widths per family
    assert make_histogram_set(5202, 1).num_ch == 64
    assert make_histogram_set(5203, 1).num_ch == 128


def test_5202_spectrum_accumulation():
    h = make_histogram_set(5202, 1, num_ch=64, e_nbins=256)
    energy = np.full(64, 1 << 13, dtype=np.uint32)  # mid-scale (14-bit) -> bin ~128
    h.accumulate(
        {"board": 0, "dtq": pyferslib.DTQ_SPECT, "chmask": 0,
         "energy_hg": energy, "energy_lg": energy}
    )
    snap = h.snapshot()
    assert int(snap["e_spec_hg"].sum()) == 64  # one entry per channel
    assert int(snap["e_spec_hg"][0, 0].argmax()) == 128


def test_5203_lead_trail_split_by_edge():
    h = make_histogram_set(5203, 1, num_ch=128, lt_nbins=256, tot_nbins=64)
    ev = {
        "board": 0, "dtq": pyferslib.DTQ_TIMING, "nhits": 4,
        "channel": np.array([0, 0, 5, 5]),
        "edge": np.array([0, 1, 0, 1]),     # leading, trailing, leading, trailing
        "toa": np.array([10, 20, 30, 40]),
        "tot": np.array([3, 0, 7, 0]),
    }
    h.accumulate(ev)
    snap = h.snapshot()
    assert int(snap["lead"].sum()) == 2
    assert int(snap["trail"].sum()) == 2
    assert int(snap["tot"].sum()) == 4
    assert int(snap["cnt_2d"][0, 0]) == 2
    assert int(snap["cnt_2d"][0, 5]) == 2


def test_5203_without_edge_treats_hits_as_leading():
    h = make_histogram_set(5203, 1, num_ch=128)
    ev = {
        "board": 0, "dtq": pyferslib.DTQ_TIMING, "nhits": 2,
        "channel": np.array([1, 2]), "toa": np.array([5, 6]), "tot": np.array([1, 1]),
    }
    h.accumulate(ev)
    snap = h.snapshot()
    assert int(snap["lead"].sum()) == 2
    assert int(snap["trail"].sum()) == 0


def test_out_of_range_board_is_ignored():
    h = make_histogram_set(5203, 1)
    h.accumulate(
        {"board": 9, "dtq": pyferslib.DTQ_TIMING, "channel": np.array([0]),
         "toa": np.array([1]), "tot": np.array([0])}
    )
    assert int(h.snapshot()["cnt_2d"].sum()) == 0
