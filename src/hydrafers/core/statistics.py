"""StatsThread: compute rates + histograms at ~15 Hz and publish snapshots.

Layer: ``hydrafers.core`` (CONTRACT.md section 0). Consumes a throttled tap of decoded
events (the writer's ``stats_tap`` ring buffer), folds them into per-channel counters
and :class:`~hydrafers.core.events.HistogramSet`, and at a fixed cadence publishes an
immutable :class:`RunStatistics` snapshot to ``stats_queue`` plus refreshes the shared
histogram accumulator. Never blocks the readout (FEASIBILITY_STUDY.md section 4.1).

No ``Sleep()`` polling: the throttle is implemented with ``RingBuffer.get_batch``'s
blocking-with-timeout and a monotonic-clock cadence check, all interruptible via the
stop event. This thread also performs the periodic HV/temperature service reads for
the monitoring panel by consuming SERVICE events from the tap (no extra device I/O on
the hot path).
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Callable

import numpy as np

from .events import (
    NUM_CH,
    _BaseHistogramSet,
    is_count,
    is_service,
    is_spect,
    is_timing_only,
)
from .ringbuffer import RingBuffer
from .state import BoardStats, RunStatistics

logger = logging.getLogger("hydrafers.core.statistics")

# Publish cadence: ~15 Hz (CONTRACT.md section 4 / FEASIBILITY_STUDY.md section 4.1
# -- the human eye does not need more).
_PUBLISH_PERIOD_S = 1.0 / 15.0
_DRAIN_BATCH = 8192


class StatsThread(threading.Thread):
    """Aggregator thread: events tap -> ``RunStatistics`` + histograms at ~15 Hz.

    Parameters
    ----------
    tap:
        Ring buffer carrying a copy of every event (fed by the writer thread).
    nboards:
        Number of boards (sizes the per-channel arrays / histograms).
    run_number:
        Run number stamped into each snapshot.
    stats_queue:
        Bounded queue the snapshots are published to; the engine also exposes it
        via :meth:`AcquisitionEngine.stats_queue`.
    histograms:
        Shared :class:`HistogramSet` the engine hands out via ``histograms()``;
        guarded by ``hist_lock``.
    hist_lock:
        Lock protecting ``histograms`` reads/writes between this thread and the
        engine's ``histograms()`` accessor.
    stop_event:
        Requests a graceful stop; after it is set the thread drains residual taps
        and publishes one final snapshot.
    counting_mode:
        When True the MCS time bin is advanced once per publish tick.
    on_snapshot:
        Optional callback invoked with each published snapshot (used by the engine
        to update its ``statistics()`` accessor and per-board service state).
    """

    def __init__(
        self,
        tap: RingBuffer,
        nboards: int,
        run_number: int,
        stats_queue: "queue.Queue[RunStatistics]",
        histograms: _BaseHistogramSet,
        hist_lock: threading.Lock,
        stop_event: threading.Event,
        counting_mode: bool = False,
        on_snapshot: Callable[[RunStatistics], None] | None = None,
        num_ch: int = NUM_CH,
    ) -> None:
        super().__init__(name="hydrafers-stats", daemon=True)
        self._tap = tap
        self._nboards = max(0, int(nboards))
        self._num_ch = max(1, int(num_ch))
        self._run_number = int(run_number)
        self._queue = stats_queue
        self._hist = histograms
        self._hist_lock = hist_lock
        self._stop = stop_event
        self._counting_mode = bool(counting_mode)
        self._on_snapshot = on_snapshot

        # Working counters (only this thread mutates them).
        self._total_events = 0
        self._built_events = 0
        self._byte_count = 0
        self._ch_count = np.zeros((self._nboards, self._num_ch), dtype=np.uint64)
        self._per_board_events = np.zeros(self._nboards, dtype=np.uint64)
        self._per_board_bytes = np.zeros(self._nboards, dtype=np.uint64)

        # Latest service-event snapshot per board (for monitoring), kept under lock.
        self._service_lock = threading.Lock()
        self._service: dict[int, dict] = {}

        self._t0 = time.monotonic()

        # Rate computation references (for delta-based rates between ticks).
        self._last_tick = self._t0
        self._last_total = 0
        self._last_bytes = 0
        self._last_ch_count = np.zeros((self._nboards, self._num_ch), dtype=np.uint64)
        self._last_board_events = np.zeros(self._nboards, dtype=np.uint64)
        self._last_board_bytes = np.zeros(self._nboards, dtype=np.uint64)

    # ----------------------------------------------------------------- accessors
    def latest_service(self) -> dict[int, dict]:
        """Return the most recent service-event payload per board (copies)."""
        with self._service_lock:
            return {b: dict(v) for b, v in self._service.items()}

    # ----------------------------------------------------------------- internals
    def _fold_event(self, event: dict) -> None:
        dtq = int(event.get("dtq", -1))
        board = int(event.get("board", -1))

        if is_service(dtq):
            if 0 <= board:
                with self._service_lock:
                    self._service[board] = dict(event)
            return

        self._total_events += 1
        if 0 <= board < self._nboards:
            self._per_board_events[board] += 1

        nbytes = 0
        for value in event.values():
            if isinstance(value, np.ndarray):
                nbytes += int(value.nbytes)
        nbytes += 32
        self._byte_count += nbytes
        if 0 <= board < self._nboards:
            self._per_board_bytes[board] += nbytes

        # Channel-occupancy tally for ICR-like per-channel trigger rate.
        if 0 <= board < self._nboards:
            nc = self._num_ch
            if is_count(dtq):
                counts = event.get("counts")
                if counts is not None:
                    carr = np.asarray(counts).astype(np.uint64, copy=False)
                    n = min(len(carr), nc)
                    self._ch_count[board, :n] += carr[:n]
            elif is_timing_only(dtq):
                channel = event.get("channel")
                if channel is not None:
                    chan = np.asarray(channel).astype(np.int64, copy=False)
                    valid = (chan >= 0) & (chan < nc)
                    np.add.at(self._ch_count[board], chan[valid], 1)
            elif is_spect(dtq):
                # Each channel present in the channel mask contributes one hit.
                chmask = int(event.get("chmask", 0))
                if chmask:
                    bits = np.array(
                        [(chmask >> c) & 1 for c in range(nc)], dtype=np.uint64
                    )
                    self._ch_count[board] += bits

        # Event building: count events that carry a trigger_id as "built".
        if "trigger_id" in event:
            self._built_events += 1

        # Histogram accumulation under the shared lock.
        with self._hist_lock:
            self._hist.accumulate(event)

    def _build_snapshot(self) -> RunStatistics:
        now = time.monotonic()
        elapsed = now - self._t0
        dt = max(now - self._last_tick, 1e-6)

        d_total = self._total_events - self._last_total
        d_bytes = self._byte_count - self._last_bytes
        event_rate = d_total / dt
        data_rate_mbps = (d_bytes * 8.0) / (dt * 1e6)

        d_ch = (self._ch_count.astype(np.float64) - self._last_ch_count.astype(np.float64))
        ch_trg_rate = d_ch / dt

        per_board: dict[int, BoardStats] = {}
        for b in range(self._nboards):
            db_ev = int(self._per_board_events[b] - self._last_board_events[b])
            db_by = int(self._per_board_bytes[b] - self._last_board_bytes[b])
            per_board[b] = BoardStats(
                index=b,
                event_count=int(self._per_board_events[b]),
                event_rate_hz=db_ev / dt,
                byte_count=int(self._per_board_bytes[b]),
                data_rate_mbps=(db_by * 8.0) / (dt * 1e6),
                lost_events=0,
            )

        snapshot = RunStatistics(
            run_number=self._run_number,
            elapsed_s=elapsed,
            total_events=self._total_events,
            event_rate_hz=event_rate,
            byte_count=self._byte_count,
            data_rate_mbps=data_rate_mbps,
            built_events=self._built_events,
            per_board=per_board,
            ch_trg_rate=ch_trg_rate,
            ch_count=np.array(self._ch_count, copy=True),
        )

        # Advance rate references.
        self._last_tick = now
        self._last_total = self._total_events
        self._last_bytes = self._byte_count
        self._last_ch_count = np.array(self._ch_count, copy=True)
        self._last_board_events = np.array(self._per_board_events, copy=True)
        self._last_board_bytes = np.array(self._per_board_bytes, copy=True)
        return snapshot

    def _publish(self, snapshot: RunStatistics) -> None:
        if self._counting_mode:
            with self._hist_lock:
                self._hist.advance_mcs_bin()
        # Non-blocking publish: drop the oldest snapshot if the consumer lags.
        try:
            self._queue.put_nowait(snapshot)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(snapshot)
            except (queue.Empty, queue.Full):
                pass
        if self._on_snapshot is not None:
            self._on_snapshot(snapshot)

    def run(self) -> None:  # noqa: D401 - thread entry point
        """Fold tapped events and publish snapshots at the fixed cadence."""
        logger.debug("stats loop starting (nboards=%d)", self._nboards)
        next_publish = time.monotonic() + _PUBLISH_PERIOD_S
        try:
            while not self._stop.is_set():
                batch = self._tap.get_batch(_DRAIN_BATCH, timeout=_PUBLISH_PERIOD_S)
                for event in batch:
                    self._fold_event(event)
                if time.monotonic() >= next_publish:
                    self._publish(self._build_snapshot())
                    next_publish = time.monotonic() + _PUBLISH_PERIOD_S
            # Final drain + snapshot after stop.
            while True:
                batch = self._tap.get_batch(_DRAIN_BATCH, timeout=0.0)
                if not batch:
                    break
                for event in batch:
                    self._fold_event(event)
            self._publish(self._build_snapshot())
        except Exception:  # pragma: no cover - defensive
            logger.exception("stats loop aborted")
        finally:
            logger.debug("stats loop exiting (total=%d)", self._total_events)
