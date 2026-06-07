"""HydraFERS — top-level package (CONTRACT.md §0).

HydraFERS is the modern renewal of the CAEN FERS / Janus DAQ software. It
replaces the old two-process design (Python tkinter GUI <-> JanusC.exe over a
TCP socket) with a single multithreaded Python application layered on
``ferslib`` (unchanged C library) via the ``pyfers`` pybind11 module.

Layer diagram (CONTRACT.md §0):

    pyfers (C++)           <- depends only on ferslib
    hydrafers.config       <- pure Python (pydantic, pyyaml); NO pyfers import
    hydrafers.io           <- pure Python (numpy); NO pyfers import
    hydrafers.core         <- depends on pyfers + hydrafers.config + hydrafers.io
    hydrafers.cli          <- depends on hydrafers.core (+ config); NO pyfers/Qt import
    hydrafers.gui          <- depends on hydrafers.core (+ config); PySide6 + pyqtgraph

This ``__init__.py`` re-exports the two types that frontends (GUI, CLI) need most
often so they can write::

    from hydrafers import AcquisitionEngine, HydraConfig

rather than navigating into sub-packages directly.

Logging: the ``hydrafers`` logger hierarchy uses stdlib ``logging``; configure a
handler before importing this package to capture startup messages.
"""

from __future__ import annotations

__version__: str = "0.0.6"
__author__: str = "CAEN SpA — Front-End Division"

# Re-export the configuration root model (pure Python; always importable,
# even without the compiled ``pyfers`` module).
from hydrafers.config import HydraConfig as HydraConfig  # noqa: F401

# Re-export the acquisition engine (requires pyfers at import time because
# hydrafers.core.events imports it for module-level constant look-ups).
# Frontends that run without hardware (e.g. unit tests) monkeypatch pyfers into
# sys.modules *before* importing hydrafers.core.
from hydrafers.core import AcquisitionEngine as AcquisitionEngine  # noqa: F401

__all__: list[str] = [
    "__version__",
    "__author__",
    "AcquisitionEngine",
    "HydraConfig",
]
