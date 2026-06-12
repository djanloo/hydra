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

# The 520X family has 64 channels arranged as an 8x8 pixel map; the 5203 has up
# to 128 channels. The grid geometry adapts to the channel count via set_num_ch().
_GRID = 8
_NUM_CH = _GRID * _GRID


def _grid_dims(num_ch: int) -> tuple[int, int]:
    """Return ``(rows, cols)`` for a near-rectangular layout of ``num_ch`` cells.

    64 -> 8x8, 128 -> 8x16 (two 64-ch picoTDCs side by side). Falls back to a
    near-square grid for any other count.
    """
    n = max(1, int(num_ch))
    if n == 64:
        return 8, 8
    if n == 128:
        return 8, 16
    cols = int(np.ceil(np.sqrt(n)))
    rows = int(np.ceil(n / cols))
    return rows, cols


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
        self._rows, self._cols = _grid_dims(_NUM_CH)
        self._num_ch = _NUM_CH

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
        self._plot.setXRange(0, self._cols, padding=0)
        self._plot.setYRange(0, self._rows, padding=0)

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

    def set_num_ch(self, num_ch: int) -> None:
        """Set the channel count and re-lay the grid (64 -> 8x8, 128 -> 8x16)."""
        self._num_ch = max(1, int(num_ch))
        self._rows, self._cols = _grid_dims(self._num_ch)
        self._plot.setXRange(0, self._cols, padding=0)
        self._plot.setYRange(0, self._rows, padding=0)

    def update_counts(self, cnt_2d: np.ndarray) -> None:
        """Update from the ``cnt_2d`` histogram (per-channel totals)."""
        self._mode = "counts"
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
        ncells = self._rows * self._cols
        if row.size < ncells:
            padded = np.zeros(ncells, dtype=np.float64)
            padded[: row.size] = row
            row = padded
        grid = row[:ncells].reshape(self._rows, self._cols)
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
