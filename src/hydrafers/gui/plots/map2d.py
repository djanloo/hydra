"""Map2DPlot -- 2D per-channel rate / charge map (CONTRACT.md section 6).

Layer: ``hydrafers.gui`` (PySide6 + pyqtgraph). NO gnuplot
(FEASIBILITY_STUDY.md section 4.4). Reproduces the old Janus "2D-TrgRate" /
"2D-Charge" plots (janus-5202/gui/ctrl.py ``plot_options``): the 64 channels of a
board laid out on an 8x8 grid, colour-mapped by per-channel total counts (from the
``cnt_2d`` histogram, shape ``[nb, 64]``) or by per-channel trigger rate (from
``RunStatistics.ch_trg_rate``, shape ``[nb, 64]``).

The widget is a dumb view: :meth:`update_counts` / :meth:`update_rate` are called by
:class:`~hydrafers.gui.main_window.MainWindow` from the Qt loop. It owns no engine
reference.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QVBoxLayout, QWidget

# The 520X family has 64 channels arranged as an 8x8 pixel map.
_GRID = 8
_NUM_CH = _GRID * _GRID


class Map2DPlot(QWidget):
    """An 8x8 per-channel heat-map of counts or trigger rate.

    Parameters
    ----------
    parent:
        Optional Qt parent widget.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._board = 0
        self._mode = "counts"  # or "rate"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        pg.setConfigOptions(antialias=False)
        self._plot = pg.PlotWidget(background="#ffffff")
        self._plot.setAspectLocked(True)
        self._plot.invertY(True)  # channel 0 at the top-left, like the pixel map
        self._plot.setLabel("bottom", "column")
        self._plot.setLabel("left", "row")
        self._plot.getAxis("bottom").setPen("#90a4ae")
        self._plot.getAxis("left").setPen("#90a4ae")
        self._plot.getAxis("bottom").setTextPen("#546e7a")
        self._plot.getAxis("left").setTextPen("#546e7a")
        self._plot.setXRange(0, _GRID, padding=0)
        self._plot.setYRange(0, _GRID, padding=0)

        self._image = pg.ImageItem()
        # A perceptually ordered colour map (blue -> red), light at the low end.
        cmap = pg.colormap.get("viridis")
        self._image.setLookupTable(cmap.getLookupTable(0.0, 1.0, 256))
        self._plot.addItem(self._image)

        # A colour bar gives the viewer the count/rate scale.
        self._colorbar = pg.ColorBarItem(
            values=(0, 1), colorMap=cmap, label="counts", width=14,
        )
        self._colorbar.setImageItem(self._image, insert_in=self._plot.getPlotItem())

        layout.addWidget(self._plot)

    # ----------------------------------------------------------------- API
    def set_board(self, board: int) -> None:
        """Select which board's channel map is displayed."""
        self._board = max(0, int(board))

    def update_counts(self, cnt_2d: np.ndarray) -> None:
        """Update from the ``cnt_2d`` histogram (per-channel totals)."""
        self._mode = "counts"
        self._colorbar.setLabels({"counts": "counts"} if False else None)
        self._render(cnt_2d, label="counts")

    def update_rate(self, ch_trg_rate: np.ndarray) -> None:
        """Update from ``RunStatistics.ch_trg_rate`` (per-channel Hz)."""
        self._mode = "rate"
        self._render(ch_trg_rate, label="Hz")

    # ----------------------------------------------------------- internals
    def _render(self, data: np.ndarray, label: str) -> None:
        if data is None:
            return
        arr = np.asarray(data, dtype=np.float64)
        if arr.ndim != 2 or self._board >= arr.shape[0]:
            self._image.clear()
            return
        row = arr[self._board]
        if row.size < _NUM_CH:
            padded = np.zeros(_NUM_CH, dtype=np.float64)
            padded[: row.size] = row
            row = padded
        grid = row[:_NUM_CH].reshape(_GRID, _GRID)
        # ImageItem indexes [x, y]; transpose so axis 0 maps to columns.
        self._image.setImage(grid.T, autoLevels=False)
        vmax = float(grid.max()) if grid.size else 1.0
        if vmax <= 0.0:
            vmax = 1.0
        self._colorbar.setLevels((0.0, vmax))
        try:
            self._colorbar.setLabel(label)
        except Exception:
            pass

    def clear(self) -> None:
        """Clear the displayed map."""
        self._image.clear()
