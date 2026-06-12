"""Offscreen tests that the main window adapts its tabs/pages to the board family.

Conditional-tabs approach (a run is always homogeneous): the A5202 shows HV +
Spectroscopy with 64-channel grids and energy spectra; the A5203 hides those,
shows TDC/Data-Analysis/Adapters, uses 128-channel grids and Lead/Trail/ToT
sources. Skipped when PySide6 is absent.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication  # noqa: E402

from hydrafers.config import default_config  # noqa: E402
from hydrafers.gui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _sources(win):
    return [win._spec_source.itemText(i) for i in range(win._spec_source.count())]


def test_mainwindow_5202_layout(qapp):
    w = MainWindow(config=default_config(5202))
    try:
        assert w._family == 5202 and w._num_ch == 64
        assert {"hv_bias", "spectroscopy", "test_probe"} <= set(w._section_forms)
        assert len(w._ch_labels) == 64
        assert w._spec_channel.maximum() == 63
        assert _sources(w) == ["Spectrum HG", "Spectrum LG", "ToA", "ToT"]
    finally:
        w.deleteLater()


def test_mainwindow_5203_layout(qapp):
    w = MainWindow(config=default_config(5203))
    try:
        assert w._family == 5203 and w._num_ch == 128
        # 5203 hides HV/spectroscopy/test-probe, adds TDC/Data-Analysis/Adapters
        assert "hv_bias" not in w._section_forms
        assert "spectroscopy" not in w._section_forms
        assert {"tdc", "data_analysis", "adapters"} <= set(w._section_forms)
        assert len(w._ch_labels) == 128
        assert w._spec_channel.maximum() == 127
        assert _sources(w) == ["Lead", "Trail", "ToT"]
        assert (w._map2d_plot._rows, w._map2d_plot._cols) == (8, 16)
    finally:
        w.deleteLater()


def test_mainwindow_runtime_family_switch(qapp):
    w = MainWindow(config=default_config(5202))
    try:
        assert "hv_bias" in w._section_forms and len(w._ch_labels) == 64
        # simulate loading a 5203 config: the loader path sets family + rebuilds
        w._config = default_config(5203)
        w._family = 5203
        w._num_ch = 128
        w._rebuild_stack()
        assert "tdc" in w._section_forms and "hv_bias" not in w._section_forms
        assert len(w._ch_labels) == 128
        assert _sources(w) == ["Lead", "Trail", "ToT"]
    finally:
        w.deleteLater()


def test_collect_config_matches_family(qapp):
    from hydrafers.config import HydraConfig, HydraConfig5203

    w2 = MainWindow(config=default_config(5202))
    try:
        assert isinstance(w2._collect_config(), HydraConfig)
    finally:
        w2.deleteLater()

    w3 = MainWindow(config=default_config(5203))
    try:
        cfg = w3._collect_config()
        assert isinstance(cfg, HydraConfig5203)
        assert cfg.board_family == 5203
    finally:
        w3.deleteLater()
