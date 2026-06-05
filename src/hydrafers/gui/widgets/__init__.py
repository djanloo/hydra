"""Reusable PySide6 widgets for the HydraFERS GUI (CONTRACT.md section 6).

Layer: ``hydrafers.gui`` (PySide6). Pure presentation widgets; they hold no
acquisition logic and talk to the engine only through values passed in by
:class:`hydrafers.gui.main_window.MainWindow`.

Modules:
    * :mod:`~hydrafers.gui.widgets.sidebar`        -- CAEN-WI style nav rail.
    * :mod:`~hydrafers.gui.widgets.device_tree`    -- link / board device tree.
    * :mod:`~hydrafers.gui.widgets.status_table`   -- key/value status table.
    * :mod:`~hydrafers.gui.widgets.led`            -- coloured LED indicator.
    * :mod:`~hydrafers.gui.widgets.stat_panel`     -- live run-statistics panel.
    * :mod:`~hydrafers.gui.widgets.config_editor`  -- HydraConfig form editor.
    * :mod:`~hydrafers.gui.widgets.hv_panel`       -- HV control panel.
    * :mod:`~hydrafers.gui.widgets.register_panel` -- register read/write panel.
    * :mod:`~hydrafers.gui.widgets.log_panel`      -- log / message console.
"""

from __future__ import annotations

__all__ = [
    "Led",
    "Sidebar",
    "DeviceTree",
    "StatusTable",
    "StatPanel",
    "ConfigEditor",
    "HVPanel",
    "RegisterPanel",
    "LogPanel",
]


def __getattr__(name: str):
    """Lazy re-exports so importing the package does not require PySide6."""
    _table = {
        "Led": ("led", "Led"),
        "Sidebar": ("sidebar", "Sidebar"),
        "DeviceTree": ("device_tree", "DeviceTree"),
        "StatusTable": ("status_table", "StatusTable"),
        "StatPanel": ("stat_panel", "StatPanel"),
        "ConfigEditor": ("config_editor", "ConfigEditor"),
        "HVPanel": ("hv_panel", "HVPanel"),
        "RegisterPanel": ("register_panel", "RegisterPanel"),
        "LogPanel": ("log_panel", "LogPanel"),
    }
    if name in _table:
        module_name, attr = _table[name]
        import importlib

        module = importlib.import_module(f"hydrafers.gui.widgets.{module_name}")
        return getattr(module, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
