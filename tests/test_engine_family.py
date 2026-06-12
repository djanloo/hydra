"""Engine wiring is board-family aware (histogram type + channel width).

Drives ``AcquisitionEngine.connect()`` against the in-memory fake binding for
both families and checks the engine builds the right live-histogram accumulator
and sizes its per-channel snapshots to 64 (A5202) or 128 (A5203).
"""

from __future__ import annotations

import numpy as np

from hydrafers.config import default_config
from hydrafers.core.engine import AcquisitionEngine
from hydrafers.core.events import HistogramSet, HistogramSet5203
from hydrafers.core.state import AcqState


def _connect(fake, config):
    eng = AcquisitionEngine(config)
    eng.connect()
    return eng


def test_engine_5202_uses_energy_histograms(fake):
    cfg = default_config(5202)
    eng = _connect(fake, cfg)
    try:
        assert eng.state is AcqState.READY
        assert eng._board_family() == 5202
        assert eng._num_ch == 64
        assert isinstance(eng._histograms, HistogramSet)
        snap = eng.histograms()
        assert "e_spec_hg" in snap and snap["e_spec_hg"].shape[1] == 64
        assert eng.statistics().ch_count.shape[1] == 64
    finally:
        eng.disconnect()


def test_engine_5203_uses_lead_trail_histograms(fake):
    cfg = default_config(5203)
    # make the opened board report itself as a 5203
    for path in cfg.board_paths():
        fake.family_of[path] = 5203
    eng = _connect(fake, cfg)
    try:
        assert eng.state is AcqState.READY
        assert eng._board_family() == 5203
        assert eng._num_ch == 128
        assert isinstance(eng._histograms, HistogramSet5203)
        snap = eng.histograms()
        assert {"lead", "trail", "tot"} <= set(snap)
        assert snap["lead"].shape[1] == 128
        assert "e_spec_hg" not in snap
        assert eng.statistics().ch_count.shape[1] == 128
    finally:
        eng.disconnect()


def test_engine_5203_system_family_detected(fake):
    cfg = default_config(5203)
    for path in cfg.board_paths():
        fake.family_of[path] = 5203
    eng = _connect(fake, cfg)
    try:
        assert eng.system is not None
        assert int(eng.system.family) == 5203
        # the 5203 boards have no HV
        assert all(not b.has_hv for b in eng.system.boards)
    finally:
        eng.disconnect()
