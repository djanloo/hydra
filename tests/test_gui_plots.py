"""Offscreen smoke tests for the board-family-aware plot widgets.

Skipped entirely when PySide6 is not installed (e.g. minimal CI). Runs headless
via the Qt 'offscreen' platform so it needs no display.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication  # noqa: E402

from hydrafers.gui.plots.map2d import Map2DPlot, _grid_dims  # noqa: E402
from hydrafers.gui.plots.spectrum import (  # noqa: E402
    SpectrumPlot,
    sources_for_family,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_sources_per_family():
    assert list(sources_for_family(5202)) == ["Spectrum HG", "Spectrum LG", "ToA", "ToT"]
    assert list(sources_for_family(5203)) == ["Lead", "Trail", "ToT"]


def test_grid_dims():
    assert _grid_dims(64) == (8, 8)
    assert _grid_dims(128) == (8, 16)


def test_spectrum_plot_renders_5203_lead(qapp):
    snap = {
        "lead": np.random.randint(0, 50, (1, 128, 256)).astype(np.uint32),
        "trail": np.zeros((1, 128, 256), np.uint32),
        "tot": np.zeros((1, 128, 64), np.uint32),
        "cnt_2d": np.zeros((1, 128), np.uint64),
    }
    sp = SpectrumPlot()
    sp.set_source("Lead")
    sp.set_target(0, 100)  # a channel only the 128-ch 5203 has
    sp.update_data(snap)  # must not raise


def test_map2d_adapts_to_channel_count(qapp):
    m128 = Map2DPlot()
    m128.set_num_ch(128)
    m128.set_board(0)
    m128.update_counts(np.random.randint(0, 9, (1, 128)).astype(np.uint64))
    m128.update_rate(np.random.rand(1, 128))
    assert (m128._rows, m128._cols) == (8, 16)

    m64 = Map2DPlot()
    m64.set_num_ch(64)
    m64.update_counts(np.random.randint(0, 9, (1, 64)).astype(np.uint64))
    assert (m64._rows, m64._cols) == (8, 8)
