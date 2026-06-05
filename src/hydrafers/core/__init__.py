"""``hydrafers.core`` -- the multithreaded FERS acquisition engine.

Layer (CONTRACT.md section 0): depends on ``pyfers`` + ``hydrafers.config`` +
``hydrafers.io``. Contains ZERO presentation logic; CLI and GUI frontends are
interchangeable consumers of the identical :class:`AcquisitionEngine` API.

Public API (CONTRACT.md section 4)::

    from hydrafers.core import AcquisitionEngine, AcqState, BoardStatus, RunStatistics

The engine fixes the old JanusC single-thread bottleneck with a producer/consumer
threading model: a tight readout thread feeds a bounded ring buffer; a writer thread
drains it to disk; a stats thread computes rates/histograms at ~15 Hz. See
FEASIBILITY_STUDY.md sections 3 and 4 for the rationale.
"""

from __future__ import annotations

from .engine import AcquisitionEngine
from .state import AcqState, BoardStats, BoardStatus, RunStatistics

__all__ = [
    "AcquisitionEngine",
    "AcqState",
    "BoardStatus",
    "RunStatistics",
    "BoardStats",
]
