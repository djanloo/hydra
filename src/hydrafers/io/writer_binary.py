"""Buffered binary event writer for the new HydraFERS file format.

Layer: ``hydrafers.io`` (pure Python; numpy only; NO ``pyfers`` import) — see
CONTRACT.md §0 and §3.

:class:`EventWriter` is used by the engine's ``WriterThread`` (never inline in the
readout loop). It accepts event dicts of exactly the shape ``pyfers.get_event``
returns (CONTRACT.md §1), serializes the per-mode fields into compact
length-prefixed binary records, and accumulates them in an in-memory buffer. The
buffer is flushed to disk in large sequential blocks (default 4 MiB) so the OS
sees few, large ``write`` calls rather than one syscall per event.

The byte layout produced here is documented in ``docs/FILE_FORMAT.md`` and read
back by :class:`hydrafers.io.reader.EventReader`.
"""

from __future__ import annotations

import io
import json
import struct
from pathlib import Path
from typing import Any

import numpy as np

from .formats import (
    DEFAULT_BUFFER_BYTES,
    ENDIAN,
    FORMAT_VERSION,
    LEN_STRUCT,
    MAGIC,
    NUM_CH,
    REC_COUNT,
    REC_SERVICE,
    REC_SPECT,
    REC_TEST,
    REC_TIMING,
    REC_WAVE,
    SPECT_FLAG_TSPECT,
    FileHeader,
)

# ---------------------------------------------------------------------------
# Fixed sub-record struct layouts (little-endian). All defined once so the
# reader can mirror them exactly.
# ---------------------------------------------------------------------------

# Common 1-byte record tag + common fields shared by every record:
#   tag(u8) board(u8) dtq(i32) tstamp_us(f64)
_COMMON = struct.Struct(ENDIAN + "B B i d")

# SPECT/TSPECT scalar block (after the common block + 1 flag byte):
#   rel_tstamp_us(f64) tstamp_clk(u64) tref_tstamp(u64) trigger_id(u64)
#   chmask(u64) qdmask(u64)
_SPECT_SCALARS = struct.Struct(ENDIAN + "d Q Q Q Q Q")

# COUNT scalar block:
#   rel_tstamp_us(f64) trigger_id(u64) chmask(u64)
#   t_or_counts(u32) q_or_counts(u32)
_COUNT_SCALARS = struct.Struct(ENDIAN + "d Q Q I I")

# TIMING scalar block (then nhits, then arrays):
#   trigger_id(u64) tref_tstamp(u64) tstamp_clk(u64) nhits(u32)
_TIMING_SCALARS = struct.Struct(ENDIAN + "Q Q Q I")

# WAVE scalar block:
#   trigger_id(u64) ns(u32)
_WAVE_SCALARS = struct.Struct(ENDIAN + "Q I")

# SERVICE scalar block:
#   pkt_size(u32) version(u32) format(u32)
#   q_or_cnt(u32) t_or_cnt(u32)
#   temp_fpga(f32) temp_board(f32) temp_tdc0(f32) temp_tdc1(f32)
#   temp_hv(f32) temp_detector(f32)
#   hv_vmon(f32) hv_imon(f32)
#   hv_on(u8) hv_ramp(u8) hv_ovv(u8) hv_ovc(u8)
#   status(u32) tdc_ro_status(u32) readout_flags(u32)
#   tot_trg_cnt(u32) rej_trg_cnt(u32) suppr_trg_cnt(u32)
_SERVICE_SCALARS = struct.Struct(
    ENDIAN + "I I I  I I  f f f f f f  f f  B B B B  I I I  I I I"
)

# TEST scalar block:
#   trigger_id(u64) nwords(u32)
_TEST_SCALARS = struct.Struct(ENDIAN + "Q I")


def _u8(value: Any) -> int:
    return int(value) & 0xFF


def _as_array(value: Any, count: int, dtype: np.dtype) -> np.ndarray:
    """Coerce ``value`` to a contiguous little-endian array of exactly ``count``.

    Accepts numpy arrays, lists, or anything array-like. Truncates or zero-pads
    to ``count`` so a malformed event can never corrupt the record framing.
    """
    arr = np.ascontiguousarray(value, dtype=dtype)
    arr = arr.reshape(-1)
    if arr.size == count:
        return arr
    out = np.zeros(count, dtype=dtype)
    n = min(arr.size, count)
    out[:n] = arr[:n]
    return out


class EventWriter:
    """Buffered, thread-friendly binary writer for HydraFERS event files.

    Parameters
    ----------
    path:
        Output file path. Truncated/created on construction.
    header:
        :class:`~hydrafers.io.formats.FileHeader` describing the run; written
        immediately as a length-prefixed JSON line after the magic.
    buffer_bytes:
        Soft threshold (bytes). Once the in-memory buffer reaches this size it is
        flushed to disk in a single sequential write. Defaults to 4 MiB
        (CONTRACT.md §3).

    Notes
    -----
    Not internally locked: the engine drives this from a single dedicated
    ``WriterThread`` (CONTRACT.md §4). Usable as a context manager.
    """

    def __init__(
        self,
        path: str | Path,
        header: FileHeader,
        buffer_bytes: int = DEFAULT_BUFFER_BYTES,
    ) -> None:
        self.path = Path(path)
        self.header = header
        self.buffer_bytes = max(int(buffer_bytes), 64 * 1024)
        self._buf = bytearray()
        self._event_count = 0
        self._closed = False

        # raw=open(...): we do our own buffering, so a small OS buffer is fine.
        self._fp = open(self.path, "wb")
        self._write_file_header()

    # ------------------------------------------------------------------
    # Public API (CONTRACT.md §3)
    # ------------------------------------------------------------------
    def write_event(self, event: dict) -> None:
        """Serialize ``event`` and append it to the buffer.

        ``event`` must be a dict of the shape ``pyfers.get_event`` returns. The
        reprocess-finished sentinel (``{'dtq': -1, 'reprocess_finished': True}``)
        and ``None`` are silently ignored — they carry no payload to persist.
        """
        if self._closed:
            raise ValueError("write_event() on a closed EventWriter")
        if event is None:
            return
        if event.get("reprocess_finished") or int(event.get("dtq", -1)) < 0:
            return

        record = self._serialize(event)
        self._buf += LEN_STRUCT.pack(len(record))
        self._buf += record
        self._event_count += 1

        if len(self._buf) >= self.buffer_bytes:
            self._drain()

    def flush(self) -> None:
        """Drain the in-memory buffer to the OS and flush the file object.

        This pushes all buffered records out via a single sequential ``write``
        and flushes the Python file object's small OS-level buffer. It does NOT
        ``os.fsync`` (forcing the physical disk) on every call, which would
        defeat the large-sequential-write design; durability to media happens on
        :meth:`close` / when the OS schedules it.
        """
        if self._closed:
            return
        self._drain()
        self._fp.flush()

    def close(self) -> None:
        """Flush remaining data and close the underlying file. Idempotent."""
        if self._closed:
            return
        try:
            self._drain()
            self._fp.flush()
        finally:
            self._fp.close()
            self._closed = True

    @property
    def event_count(self) -> int:
        """Number of events written so far (excludes ignored sentinels)."""
        return self._event_count

    def __enter__(self) -> "EventWriter":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _write_file_header(self) -> None:
        """Write magic + length-prefixed JSON header at the start of the file."""
        hdr = self.header.to_dict()
        hdr["format_version"] = FORMAT_VERSION
        hdr["legacy"] = False
        payload = json.dumps(hdr, separators=(",", ":")).encode("utf-8")
        self._fp.write(MAGIC)
        self._fp.write(LEN_STRUCT.pack(len(payload)))
        self._fp.write(payload)

    def _drain(self) -> None:
        """Write the whole buffer to disk in one sequential call and clear it."""
        if self._buf:
            self._fp.write(self._buf)
            self._buf.clear()

    # -- per-mode serialization -----------------------------------------
    def _serialize(self, ev: dict) -> bytes:
        """Dispatch to the per-mode serializer based on the data qualifier."""
        dtq = int(ev["dtq"])
        if dtq == 0x2F:
            return self._ser_service(ev)
        if dtq == 0xFF:
            return self._ser_test(ev)
        low = dtq & 0x0F
        if low in (0x01, 0x03):          # SPECT or TSPECT
            return self._ser_spect(ev, tspect=(low == 0x03))
        if low == 0x04:                  # COUNT
            return self._ser_count(ev)
        if low == 0x02:                  # TIMING
            return self._ser_timing(ev)
        if low == 0x08:                  # WAVE
            return self._ser_wave(ev)
        raise ValueError(f"EventWriter: unsupported dtq=0x{dtq:02X}")

    def _common(self, ev: dict, tag: int) -> bytes:
        return _COMMON.pack(
            tag,
            _u8(ev["board"]),
            int(ev["dtq"]),
            float(ev["tstamp_us"]),
        )

    def _ser_spect(self, ev: dict, tspect: bool) -> bytes:
        out = io.BytesIO()
        out.write(self._common(ev, REC_SPECT))
        out.write(struct.pack(ENDIAN + "B", SPECT_FLAG_TSPECT if tspect else 0))
        out.write(
            _SPECT_SCALARS.pack(
                float(ev.get("rel_tstamp_us", 0.0)),
                int(ev.get("tstamp_clk", 0)),
                int(ev.get("tref_tstamp", 0)),
                int(ev.get("trigger_id", 0)),
                int(ev.get("chmask", 0)),
                int(ev.get("qdmask", 0)),
            )
        )
        out.write(_as_array(ev["energy_hg"], NUM_CH, np.dtype("<u2")).tobytes())
        out.write(_as_array(ev["energy_lg"], NUM_CH, np.dtype("<u2")).tobytes())
        if tspect:
            out.write(_as_array(ev["toa"], NUM_CH, np.dtype("<u4")).tobytes())
            out.write(_as_array(ev["tot"], NUM_CH, np.dtype("<u2")).tobytes())
        return out.getvalue()

    def _ser_count(self, ev: dict) -> bytes:
        out = io.BytesIO()
        out.write(self._common(ev, REC_COUNT))
        out.write(
            _COUNT_SCALARS.pack(
                float(ev.get("rel_tstamp_us", 0.0)),
                int(ev.get("trigger_id", 0)),
                int(ev.get("chmask", 0)),
                int(ev.get("t_or_counts", 0)),
                int(ev.get("q_or_counts", 0)),
            )
        )
        out.write(_as_array(ev["counts"], NUM_CH, np.dtype("<u4")).tobytes())
        return out.getvalue()

    def _ser_timing(self, ev: dict) -> bytes:
        nhits = int(ev["nhits"])
        out = io.BytesIO()
        out.write(self._common(ev, REC_TIMING))
        out.write(
            _TIMING_SCALARS.pack(
                int(ev.get("trigger_id", 0)),
                int(ev.get("tref_tstamp", 0)),
                int(ev.get("tstamp_clk", 0)),
                nhits,
            )
        )
        out.write(_as_array(ev["channel"], nhits, np.dtype("<u1")).tobytes())
        out.write(_as_array(ev["edge"], nhits, np.dtype("<u1")).tobytes())
        out.write(_as_array(ev["toa"], nhits, np.dtype("<u4")).tobytes())
        out.write(_as_array(ev["tot"], nhits, np.dtype("<u2")).tobytes())
        return out.getvalue()

    def _ser_wave(self, ev: dict) -> bytes:
        ns = int(ev["ns"])
        out = io.BytesIO()
        out.write(self._common(ev, REC_WAVE))
        out.write(
            _WAVE_SCALARS.pack(
                int(ev.get("trigger_id", 0)),
                ns,
            )
        )
        out.write(_as_array(ev["wave_hg"], ns, np.dtype("<u2")).tobytes())
        out.write(_as_array(ev["wave_lg"], ns, np.dtype("<u2")).tobytes())
        out.write(_as_array(ev["dig_probes"], ns, np.dtype("<u1")).tobytes())
        return out.getvalue()

    def _ser_service(self, ev: dict) -> bytes:
        out = io.BytesIO()
        out.write(self._common(ev, REC_SERVICE))
        out.write(
            _SERVICE_SCALARS.pack(
                int(ev.get("pkt_size", 0)),
                int(ev.get("version", 0)),
                int(ev.get("format", 0)),
                int(ev.get("q_or_cnt", 0)),
                int(ev.get("t_or_cnt", 0)),
                float(ev.get("temp_fpga", 0.0)),
                float(ev.get("temp_board", 0.0)),
                float(ev.get("temp_tdc0", 0.0)),
                float(ev.get("temp_tdc1", 0.0)),
                float(ev.get("temp_hv", 0.0)),
                float(ev.get("temp_detector", 0.0)),
                float(ev.get("hv_vmon", 0.0)),
                float(ev.get("hv_imon", 0.0)),
                _u8(ev.get("hv_on", 0)),
                _u8(ev.get("hv_ramp", 0)),
                _u8(ev.get("hv_ovv", 0)),
                _u8(ev.get("hv_ovc", 0)),
                int(ev.get("status", 0)),
                int(ev.get("tdc_ro_status", 0)),
                int(ev.get("readout_flags", 0)),
                int(ev.get("tot_trg_cnt", 0)),
                int(ev.get("rej_trg_cnt", 0)),
                int(ev.get("suppr_trg_cnt", 0)),
            )
        )
        out.write(_as_array(ev["ch_trg_cnt"], NUM_CH, np.dtype("<u4")).tobytes())
        return out.getvalue()

    def _ser_test(self, ev: dict) -> bytes:
        nwords = int(ev["nwords"])
        out = io.BytesIO()
        out.write(self._common(ev, REC_TEST))
        out.write(_TEST_SCALARS.pack(int(ev.get("trigger_id", 0)), nwords))
        out.write(_as_array(ev["test_data"], nwords, np.dtype("<u4")).tobytes())
        return out.getvalue()
