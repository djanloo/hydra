"""ReadoutThread: the tight ``pyferslib.drain_events`` producer loop (DATA-plane).

Layer: ``hydrafers.core`` (CONTRACT.md section 0). On the high-rate data-plane the
engine talks DIRECTLY to the faithful binding ``pyferslib`` -- not the ergonomic
``pyfers`` SDK -- to avoid per-event Python overhead (CONTRACT.md section 4,
FEASIBILITY_STUDY.md section 5.4). This thread does NOTHING except batch-pull events
and enqueue them: no disk, no statistics math, no decode, no plotting. That single
responsibility is the fix for the old JanusC single-thread loop that serialized
network, processing and disk I/O (FEASIBILITY_STUDY.md section 4.1/4.2).

``pyferslib.drain_events(handles, N)`` loops ``FERS_GetEvent`` in C up to ``N`` events
(or until none are ready) and returns a ``list[(board, dtq, event)]`` of bound
event-struct objects. The whole batch is enqueued as-is; field extraction into the
neutral io dict happens later in the WriterThread (the only place ``pyferslib`` event
objects are read for their fields).

Synchronization uses a ``threading.Event`` and the ring buffer's drop-accounted
``put`` -- there are NO ``Sleep()`` polling loops. ``drain_events`` releases the GIL
inside the C call, so this loop does not starve the other Python threads.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

import pyferslib

from .events import is_reprocess_sentinel
from .ringbuffer import RingBuffer

logger = logging.getLogger("hydrafers.core.readout")

# Max events pulled per C-side ``drain_events`` call. Large enough to amortize the
# per-call Python overhead; bounded so a burst cannot monopolize memory in one shot.
_DRAIN_BATCH = 1024

# After this many consecutive empty drains, take a bounded, interruptible pause via
# the stop event's wait (NOT a fixed Sleep) to keep the CPU sane while idle while
# remaining instantly responsive to a stop request.
_IDLE_BACKOFF_THRESHOLD = 200
_IDLE_BACKOFF_S = 0.001


class ReadoutThread(threading.Thread):
    """Producer thread: ``pyferslib.drain_events(handles, N)`` -> :class:`RingBuffer`.

    Parameters
    ----------
    handles:
        List of ferslib board handles passed verbatim to
        ``pyferslib.drain_events`` (obtained from ``pyfers.System.handles``).
    ring:
        Destination ring buffer for raw ``(board, dtq, event)`` tuples.
    stop_event:
        Set by the engine to request a graceful stop.
    drain_batch:
        Maximum events drained per C call (defaults to :data:`_DRAIN_BATCH`).
    on_reprocess_finished:
        Optional callback invoked once when offline raw-data reprocessing ends
        (a tuple with the ``RAWDATA_REPROCESS_FINISHED`` sentinel was returned).
    on_error:
        Optional callback invoked with the exception text if the loop aborts.
    """

    def __init__(
        self,
        handles: list[int],
        ring: RingBuffer,
        stop_event: threading.Event,
        drain_batch: int = _DRAIN_BATCH,
        on_reprocess_finished: Callable[[], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(name="hydrafers-readout", daemon=True)
        self._handles = list(handles)
        self._ring = ring
        self._stop = stop_event
        self._drain_batch = max(1, int(drain_batch))
        self._on_reprocess_finished = on_reprocess_finished
        self._on_error = on_error
        self._event_count = 0
        self._lock = threading.Lock()
        self.finished_reprocess = False

    @property
    def event_count(self) -> int:
        """Total events pulled from ferslib (including any dropped at the queue)."""
        with self._lock:
            return self._event_count

    def run(self) -> None:  # noqa: D401 - thread entry point
        """Run the producer loop until the stop event is set or an error occurs."""
        idle = 0
        logger.debug("readout loop starting for handles %s", self._handles)
        try:
            while not self._stop.is_set():
                batch: list[tuple[int, int, Any]] = pyferslib.drain_events(
                    self._handles, self._drain_batch
                )
                if not batch:
                    idle += 1
                    if idle >= _IDLE_BACKOFF_THRESHOLD:
                        idle = 0
                        # Interruptible pause: returns immediately if stop is set.
                        self._stop.wait(_IDLE_BACKOFF_S)
                    continue
                idle = 0

                stop_after = False
                count = 0
                for tup in batch:
                    board, dtq, _event = tup
                    if is_reprocess_sentinel(board, dtq):
                        self.finished_reprocess = True
                        stop_after = True
                        break
                    count += 1
                    # put() is non-blocking and drop-accounted; never stalls readout.
                    self._ring.put(tup)

                with self._lock:
                    self._event_count += count

                if stop_after:
                    logger.info("offline reprocessing finished")
                    if self._on_reprocess_finished is not None:
                        self._on_reprocess_finished()
                    break
        except Exception as exc:  # pragma: no cover - hardware/runtime failures
            logger.exception("readout loop aborted")
            if self._on_error is not None:
                self._on_error(f"readout error: {exc}")
        finally:
            logger.debug(
                "readout loop exiting (events=%d, dropped=%d)",
                self.event_count,
                self._ring.dropped(),
            )
