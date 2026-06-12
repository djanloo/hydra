"""Engine state types: ``AcqState`` enum and immutable status/statistics dataclasses.

Layer: ``hydrafers.core`` (per CONTRACT.md section 0). This module is pure Python
(stdlib + numpy) and holds NO presentation logic and NO pyfers calls; it only defines
the data shapes that flow from the engine threads out to frontends as immutable
snapshot copies.

The names and field layouts here are BINDING per CONTRACT.md section 4.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field, replace

import numpy as np

# Number of channels per board for all per-channel snapshot arrays. The 520X
# family exposes 64 channels (FERSLIB_MAX_NCH_5202); per-channel snapshot arrays
# are sized to this fixed width regardless of the actual board channel count.
NUM_CH: int = 64


class AcqState(enum.Enum):
    """Acquisition engine lifecycle state (CONTRACT.md section 4).

    Numeric values are part of the contract and must not change.
    """

    DISCONNECTED = 0
    CONNECTING = 1
    READY = 2  # hw connected, configured, not acquiring
    STARTING = 3
    RUNNING = 4
    STOPPING = 5
    EMPTYING = 6
    ERROR = -1
    UPGRADING_FW = 7


@dataclass(frozen=True)
class BoardStatus:
    """Immutable snapshot of a single board's monitoring state.

    Returned (as a list) from :meth:`AcquisitionEngine.board_status`. All fields
    are plain scalars so the snapshot is trivially copyable and thread-safe to
    hand to a frontend.
    """

    index: int
    handle: int
    pid: int
    model_name: str
    fpga_fw: str
    connected: bool
    temp_fpga: float
    temp_board: float
    temp_hv: float
    temp_detector: float
    hv_on: bool
    hv_vmon: float
    hv_imon: float
    status_reg: int


@dataclass(frozen=True)
class BoardStats:
    """Per-board throughput counters within a :class:`RunStatistics` snapshot."""

    index: int
    event_count: int = 0
    event_rate_hz: float = 0.0
    byte_count: int = 0
    data_rate_mbps: float = 0.0
    lost_events: int = 0


@dataclass(frozen=True)
class RunStatistics:
    """Immutable snapshot of run-wide statistics (CONTRACT.md section 4).

    Per-channel arrays have shape ``[nboards, NUM_CH]``. Snapshots returned to
    frontends always own copies of their numpy arrays so the engine can keep
    mutating its working buffers without aliasing the handed-out data.
    """

    run_number: int = 0
    elapsed_s: float = 0.0
    total_events: int = 0
    event_rate_hz: float = 0.0
    byte_count: int = 0
    data_rate_mbps: float = 0.0
    built_events: int = 0
    per_board: dict[int, BoardStats] = field(default_factory=dict)
    # per-channel arrays (np.ndarray, shape [nboards, NUM_CH]):
    ch_trg_rate: np.ndarray = field(
        default_factory=lambda: np.zeros((0, NUM_CH), dtype=np.float64)
    )
    ch_count: np.ndarray = field(
        default_factory=lambda: np.zeros((0, NUM_CH), dtype=np.uint64)
    )

    @staticmethod
    def empty(
        nboards: int = 0, run_number: int = 0, num_ch: int = NUM_CH
    ) -> "RunStatistics":
        """Build a zeroed snapshot sized for ``nboards`` boards x ``num_ch`` channels.

        ``num_ch`` is 64 for the A5202 family and 128 for the A5203 (picoTDC).
        """
        nc = max(1, int(num_ch))
        return RunStatistics(
            run_number=run_number,
            per_board={i: BoardStats(index=i) for i in range(nboards)},
            ch_trg_rate=np.zeros((nboards, nc), dtype=np.float64),
            ch_count=np.zeros((nboards, nc), dtype=np.uint64),
        )

    def copy(self) -> "RunStatistics":
        """Return a deep-enough copy: numpy arrays and the per_board dict are cloned."""
        return replace(
            self,
            per_board=dict(self.per_board),
            ch_trg_rate=np.array(self.ch_trg_rate, copy=True),
            ch_count=np.array(self.ch_count, copy=True),
        )
