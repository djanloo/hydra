"""SpectrumPlot -- 1D histogram plot for PHA (HG/LG), ToA and ToT (CONTRACT.md s.6).

Layer: ``hydrafers.gui`` (PySide6 + pyqtgraph). NO gnuplot
(FEASIBILITY_STUDY.md section 4.4). This widget renders one of the per-(board,
channel) 1D histograms produced by
:meth:`hydrafers.core.AcquisitionEngine.histograms` -- the dict carries
``e_spec_hg`` / ``e_spec_lg`` (shape ``[nb, 64, e_nbins]``) and ``toa`` / ``tot``
(shape ``[nb, 64, toa_nbins]``).

The widget is a dumb view: the owning :class:`~hydrafers.gui.main_window.MainWindow`
calls :meth:`set_source` to choose which spectrum to show and :meth:`update_data`
on every QTimer tick with a fresh ``histograms()`` snapshot. The widget owns NO
engine reference and performs NO acquisition logic.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QVBoxLayout, QWidget

# Human label + histogram-key + colour for every selectable spectrum source.
# The key indexes the dict returned by ``AcquisitionEngine.histograms()``. Sources
# are split per board family (the 5202 builds energy spectra; the 5203 picoTDC
# builds lead/trail/ToT timing histograms), with a union exposed for the widget so
# any source can be selected.
SPECTRUM_SOURCES_5202: dict[str, tuple[str, str]] = {
    "Spectrum HG": ("e_spec_hg", "#1565c0"),
    "Spectrum LG": ("e_spec_lg", "#2e7d32"),
    "ToA": ("toa", "#ef6c00"),
    "ToT": ("tot", "#6a1b9a"),
}
SPECTRUM_SOURCES_5203: dict[str, tuple[str, str]] = {
    "Lead": ("lead", "#1565c0"),
    "Trail": ("trail", "#2e7d32"),
    "ToT": ("tot", "#6a1b9a"),
}
SPECTRUM_SOURCES: dict[str, tuple[str, str]] = {
    **SPECTRUM_SOURCES_5202,
    **SPECTRUM_SOURCES_5203,
}

# X-axis label per source key.
_X_LABEL: dict[str, str] = {
    "e_spec_hg": "Energy [ADC channel]",
    "e_spec_lg": "Energy [ADC channel]",
    "toa": "Time of Arrival [LSB]",
    "tot": "Time over Threshold [LSB]",
    "lead": "Leading edge [LSB]",
    "trail": "Trailing edge [LSB]",
}


def sources_for_family(family: int) -> dict[str, tuple[str, str]]:
    """Return the selectable spectrum sources for a board family (5202/5203)."""
    return SPECTRUM_SOURCES_5203 if int(family) == 5203 else SPECTRUM_SOURCES_5202


class SpectrumPlot(QWidget):
    """A single-spectrum 1D histogram plot (PHA / ToA / ToT).

    Parameters
    ----------
    parent:
        Optional Qt parent widget.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._board = 0
        self._channel = 0
        self._source = "Spectrum HG"
        self._last_snapshot: dict[str, np.ndarray] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # pyqtgraph on a light (CAEN Web Interface) theme.
        pg.setConfigOptions(antialias=True)
        self._plot = pg.PlotWidget(background="#ffffff")
        self._plot.showGrid(x=True, y=True, alpha=0.18)
        self._plot.setLabel("bottom", _X_LABEL[SPECTRUM_SOURCES[self._source][0]])
        self._plot.setLabel("left", "Counts")
        self._plot.getAxis("bottom").setPen("#90a4ae")
        self._plot.getAxis("left").setPen("#90a4ae")
        self._plot.getAxis("bottom").setTextPen("#546e7a")
        self._plot.getAxis("left").setTextPen("#546e7a")

        self._curve = self._plot.plot(
            [], [], stepMode="center", fillLevel=0,
            brush=pg.mkBrush("#1565c0"),
            pen=pg.mkPen("#0d47a1", width=1),
        )
        layout.addWidget(self._plot)

    # ----------------------------------------------------------------- API
    def set_source(self, source: str) -> None:
        """Select which spectrum (``Spectrum HG/LG``, ``ToA``, ``ToT``) to show."""
        if source not in SPECTRUM_SOURCES:
            return
        self._source = source
        key, colour = SPECTRUM_SOURCES[source]
        self._curve.setBrush(pg.mkBrush(colour))
        self._curve.setPen(pg.mkPen(colour, width=1))
        self._plot.setLabel("bottom", _X_LABEL.get(key, "Bin"))
        self._plot.setTitle(
            f"{source}  -  board {self._board}, channel {self._channel}",
            color="#546e7a", size="11pt",
        )
        if self._last_snapshot is not None:
            self.update_data(self._last_snapshot)

    def set_target(self, board: int, channel: int) -> None:
        """Select the (board, channel) pair whose spectrum is displayed."""
        self._board = max(0, int(board))
        self._channel = max(0, int(channel))
        self._plot.setTitle(
            f"{self._source}  -  board {self._board}, channel {self._channel}",
            color="#546e7a", size="11pt",
        )
        if self._last_snapshot is not None:
            self.update_data(self._last_snapshot)

    def update_data(self, histograms: dict[str, np.ndarray]) -> None:
        """Redraw from a fresh ``AcquisitionEngine.histograms()`` snapshot."""
        self._last_snapshot = histograms
        key, _colour = SPECTRUM_SOURCES[self._source]
        data = histograms.get(key)
        if data is None or data.ndim != 3:
            self._curve.setData([], [])
            return
        nb, nch, nbins = data.shape
        if self._board >= nb or self._channel >= nch or nbins == 0:
            self._curve.setData([], [])
            return
        counts = np.asarray(data[self._board, self._channel], dtype=np.float64)
        # stepMode="center" needs len(x) == len(y) + 1 (the bin edges).
        edges = np.arange(nbins + 1, dtype=np.float64)
        self._curve.setData(edges, counts)

    def clear(self) -> None:
        """Clear the displayed spectrum."""
        self._last_snapshot = None
        self._curve.setData([], [])
