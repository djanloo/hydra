"""Embedded pyqtgraph plot widgets for the HydraFERS GUI (CONTRACT.md section 6).

Layer: ``hydrafers.gui`` (PySide6 + pyqtgraph). NO gnuplot anywhere
(FEASIBILITY_STUDY.md section 4.4). Each widget consumes the numpy arrays handed
out by :meth:`hydrafers.core.AcquisitionEngine.histograms` /
:meth:`~hydrafers.core.AcquisitionEngine.statistics` and renders them in-process.

Modules:
    * :mod:`~hydrafers.gui.plots.spectrum` -- PHA (HG/LG) / ToA / ToT histograms.
    * :mod:`~hydrafers.gui.plots.map2d`    -- 2D per-channel rate / charge map.
    * :mod:`~hydrafers.gui.plots.mcs`      -- multi-channel-scaler counts vs time.
"""

from __future__ import annotations

__all__ = ["SpectrumPlot", "Map2DPlot", "MCSPlot"]


def __getattr__(name: str):
    """Lazy re-exports so importing the package does not require pyqtgraph."""
    _table = {
        "SpectrumPlot": ("spectrum", "SpectrumPlot"),
        "Map2DPlot": ("map2d", "Map2DPlot"),
        "MCSPlot": ("mcs", "MCSPlot"),
    }
    if name in _table:
        module_name, attr = _table[name]
        import importlib

        module = importlib.import_module(f"hydrafers.gui.plots.{module_name}")
        return getattr(module, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
