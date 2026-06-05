"""WriterThread: drains raw events, extracts fields, writes via ``hydrafers.io``.

Layer: ``hydrafers.core`` (CONTRACT.md section 0). Depends on the ring buffer,
``hydrafers.core.events`` (the ``pyferslib`` field-extraction) and ``hydrafers.io``
(section 3). Runs independently of the readout so disk I/O never stalls the data-plane
(FEASIBILITY_STUDY.md section 4.3). Drains in batches to favour large sequential
writes over per-event syscalls.

This thread is where the data-plane crosses back into a layer-neutral world: it pulls
the raw ``(board, dtq, event)`` tuples produced by the readout (the ``event`` is a
``pyferslib`` bound struct), and calls :func:`hydrafers.core.events.extract_event` to
copy the relevant fields into the *neutral dict* (CONTRACT.md section 3). Only this
side of the engine ever reads ``pyferslib`` event objects; ``hydrafers.io`` receives
plain dicts and never imports ``pyferslib``.

The extracted dict is also forwarded to the stats thread (a second ring buffer tap)
and folded into per-board throughput counters. This thread performs NO statistics math
and NO presentation. Synchronization is via ``RingBuffer`` blocking-with-timeout and a
``threading.Event``; there are NO ``Sleep()`` polls.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from .events import event_nbytes, extract_event, is_service, is_test
from .ringbuffer import RingBuffer

logger = logging.getLogger("hydrafers.core.writer")

# Max raw events drained and processed per batch (bounds per-iteration memory; large
# enough to amortize syscalls).
_WRITE_BATCH = 4096


class WriterThread(threading.Thread):
    """Consumer thread: raw tuples -> neutral dict -> ``EventWriter`` + stats tap.

    Parameters
    ----------
    ring:
        Source ring buffer of ``(board, dtq, event)`` tuples from the readout.
    writer:
        A ``hydrafers.io.EventWriter`` (or ``None`` to discard data, e.g. for a
        pure throughput benchmark). The writer is owned by the caller; this thread
        flushes it but does not close it.
    stop_event:
        Requests a graceful stop. On stop, the thread drains whatever remains in
        the ring buffer before exiting (the EMPTYING phase).
    stats_tap:
        Optional ring buffer receiving the extracted event dicts for the stats
        thread. Service/test events are forwarded too (stats reads HV/temperature
        taps from SERVICE events without extra device I/O).
    on_error:
        Optional callback invoked with the failure text if writing aborts.
    """

    def __init__(
        self,
        ring: RingBuffer,
        writer: object | None,
        stop_event: threading.Event,
        stats_tap: RingBuffer | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(name="hydrafers-writer", daemon=True)
        self._ring = ring
        self._writer = writer
        self._stop = stop_event
        self._stats_tap = stats_tap
        self._on_error = on_error
        self._lock = threading.Lock()
        self._written = 0
        self._service_count = 0
        self._byte_count = 0
        # Per-board counters: board_index -> [events, bytes]
        self._per_board: dict[int, list[int]] = {}

    # ----------------------------------------------------------------- snapshots
    @property
    def written(self) -> int:
        with self._lock:
            return self._written

    @property
    def byte_count(self) -> int:
        with self._lock:
            return self._byte_count

    def per_board_counts(self) -> dict[int, tuple[int, int]]:
        """Return ``{board_index: (events, bytes)}`` as an immutable-ish copy."""
        with self._lock:
            return {b: (c[0], c[1]) for b, c in self._per_board.items()}

    # ----------------------------------------------------------------- internals
    def _account(self, event: dict) -> None:
        board = int(event.get("board", -1))
        nbytes = event_nbytes(event)
        with self._lock:
            self._byte_count += nbytes
            if board >= 0:
                slot = self._per_board.setdefault(board, [0, 0])
                slot[0] += 1
                slot[1] += nbytes
            if is_service(event.get("dtq", -1)):
                self._service_count += 1

    def _handle_batch(self, batch: list[tuple[int, int, Any]]) -> None:
        for tup in batch:
            board, dtq, raw = tup
            # Extract the pyferslib struct fields into the neutral io dict here --
            # this is the only place pyferslib event objects are read.
            event = extract_event(board, dtq, raw)
            if event is None:
                continue
            self._account(event)
            # Forward to stats tap first (cheap; drop-on-full so it can't stall us).
            if self._stats_tap is not None:
                self._stats_tap.put(event)
            # Service/test events are not persisted to the physics list file.
            if self._writer is not None and not is_service(dtq) and not is_test(dtq):
                self._writer.write_event(event)
                with self._lock:
                    self._written += 1

    def run(self) -> None:  # noqa: D401 - thread entry point
        """Drain-and-write loop; on stop, fully empties the ring before exiting."""
        logger.debug("writer loop starting")
        try:
            # Normal running phase.
            while not self._stop.is_set():
                batch = self._ring.get_batch(_WRITE_BATCH, timeout=0.1)
                if batch:
                    self._handle_batch(batch)
                    if self._writer is not None:
                        self._writer.flush()
            # EMPTYING phase: drain residual events with no further blocking.
            while True:
                batch = self._ring.get_batch(_WRITE_BATCH, timeout=0.0)
                if not batch:
                    break
                self._handle_batch(batch)
            if self._writer is not None:
                self._writer.flush()
        except Exception as exc:  # pragma: no cover - disk/runtime failures
            logger.exception("writer loop aborted")
            if self._on_error is not None:
                self._on_error(f"writer error: {exc}")
        finally:
            logger.debug("writer loop exiting (written=%d)", self.written)
