"""Bounded event ring buffer with drop accounting and backpressure.

Layer: ``hydrafers.core`` (CONTRACT.md section 0). Pure stdlib. This decouples the
readout producer from the writer/stats consumers so a slow disk or stats tick can
never stall ``pyfers.get_event`` (the core fix for the old single-thread JanusC
bottleneck described in FEASIBILITY_STUDY.md section 4.1/4.3).

Backpressure policy: when full, ``put`` does NOT block the readout; it drops the
event and increments a counter so the loss is accounted for and logged, never
silently lost (CONTRACT.md section 4 readout-thread requirement).
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RingStats:
    """Immutable snapshot of ring-buffer counters."""

    capacity: int
    size: int
    enqueued: int
    dequeued: int
    dropped: int
    high_water: int


class RingBuffer:
    """A bounded FIFO of event dicts shared between readout and consumers.

    Wraps ``queue.Queue`` (which is internally thread-safe) and adds:
      * non-blocking drop-on-full producer path with a dropped counter,
      * blocking-with-timeout consumer paths (no Sleep-poll loops),
      * a high-water mark and throughput counters for diagnostics.
    """

    def __init__(self, capacity: int = 100_000) -> None:
        if capacity <= 0:
            raise ValueError("ring buffer capacity must be positive")
        self._capacity = int(capacity)
        self._q: "queue.Queue[Any]" = queue.Queue(maxsize=self._capacity)
        self._lock = threading.Lock()
        self._enqueued = 0
        self._dequeued = 0
        self._dropped = 0
        self._high_water = 0

    @property
    def capacity(self) -> int:
        return self._capacity

    def put(self, item: Any) -> bool:
        """Enqueue ``item`` without blocking.

        Returns ``True`` if stored, ``False`` if the buffer was full and the item
        was dropped (the dropped counter is bumped). The readout thread relies on
        this never blocking.
        """
        try:
            self._q.put_nowait(item)
        except queue.Full:
            with self._lock:
                self._dropped += 1
            return False
        with self._lock:
            self._enqueued += 1
            cur = self._q.qsize()
            if cur > self._high_water:
                self._high_water = cur
        return True

    def get(self, timeout: float = 0.1) -> Any | None:
        """Dequeue one item, blocking up to ``timeout`` seconds.

        Returns ``None`` on timeout (lets the consumer re-check its stop event
        without a busy spin).
        """
        try:
            item = self._q.get(timeout=timeout)
        except queue.Empty:
            return None
        with self._lock:
            self._dequeued += 1
        return item

    def get_batch(self, max_items: int, timeout: float = 0.1) -> list[Any]:
        """Dequeue up to ``max_items`` items.

        Blocks up to ``timeout`` for the first item, then drains whatever else is
        immediately available without further blocking. Enables large sequential
        writes (CONTRACT.md section 3 / FEASIBILITY_STUDY.md section 4.3).
        """
        batch: list[Any] = []
        first = self.get(timeout=timeout)
        if first is None:
            return batch
        batch.append(first)
        while len(batch) < max_items:
            try:
                item = self._q.get_nowait()
            except queue.Empty:
                break
            with self._lock:
                self._dequeued += 1
            batch.append(item)
        return batch

    def qsize(self) -> int:
        """Approximate number of queued items."""
        return self._q.qsize()

    def dropped(self) -> int:
        """Total events dropped due to backpressure since construction/reset."""
        with self._lock:
            return self._dropped

    def reset_counters(self) -> None:
        """Reset throughput counters (called at start_run); does not drain items."""
        with self._lock:
            self._enqueued = 0
            self._dequeued = 0
            self._dropped = 0
            self._high_water = 0

    def clear(self) -> None:
        """Discard all queued items without counting them as dequeued."""
        while True:
            try:
                self._q.get_nowait()
            except queue.Empty:
                break

    def stats(self) -> RingStats:
        """Return an immutable snapshot of the buffer counters."""
        with self._lock:
            return RingStats(
                capacity=self._capacity,
                size=self._q.qsize(),
                enqueued=self._enqueued,
                dequeued=self._dequeued,
                dropped=self._dropped,
                high_water=self._high_water,
            )
