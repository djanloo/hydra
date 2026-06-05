"""hydrafers.gui -- PySide6 desktop frontend for HydraFERS (CONTRACT.md section 6).

Layer (CONTRACT.md section 0): depends only on ``hydrafers.core`` and
``hydrafers.config``; uses PySide6 + pyqtgraph for presentation. It contains ALL
the GUI presentation logic and NONE of the acquisition logic -- the engine
(``hydrafers.core.AcquisitionEngine``) owns its own threads and is driven purely
through its public API.

The GUI owns an :class:`~hydrafers.core.AcquisitionEngine`, drives
connect / configure / start / stop, and polls ``engine.stats_queue()`` from a
``QTimer`` (~15 Hz) to refresh the tables and embedded pyqtgraph plots. Engine
observers (``on_state_change`` / ``on_error`` / ``on_log``) fire on engine
threads and are wrapped to emit Qt signals so they land in the Qt event loop.

Style target is the CAEN Web Interface (light theme, left sidebar, device tree,
status tables, LED indicators) -- see ``screenshots_gui/`` and ``gui/style.qss``.

Public API:
    * :class:`MainWindow`  -- the top-level ``QMainWindow``.
    * :func:`main`         -- process entry point (``python -m hydrafers.gui``).
"""

from __future__ import annotations

__all__ = ["MainWindow", "main"]


def __getattr__(name: str):
    """Lazily expose ``MainWindow`` / ``main`` without importing PySide6 eagerly.

    Importing this package (e.g. for ``hydrafers.gui.__version__`` style probing
    or test collection) must not hard-require PySide6 to be installed.
    """
    if name == "MainWindow":
        from hydrafers.gui.main_window import MainWindow

        return MainWindow
    if name == "main":
        from hydrafers.gui.__main__ import main

        return main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
