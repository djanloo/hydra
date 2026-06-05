"""Event reader for HydraFERS files (new format) and legacy Janus list .dat.

Layer: ``hydrafers.io`` (pure Python; numpy only; NO ``pyfers`` import) — see
CONTRACT.md §0 and §3.

:class:`EventReader` transparently reads BOTH:

* the **new HydraFERS versioned format** produced by
  :class:`hydrafers.io.writer_binary.EventWriter`, and
* the **legacy Janus list ``.dat``** binary format, reproduced from
  ``janus-5202/src/outputfiles.c`` (``WriteListfileHeader`` + ``SaveList``).

Detection is by magic bytes: a new file starts with the 8-byte
:data:`~hydrafers.io.formats.MAGIC`; anything else is treated as a legacy list
file (whose first byte is the legacy major file-format version, never ``'H'``).

Iterating an :class:`EventReader` yields event dicts of the SAME shape that
``pyfers.get_event`` returns (CONTRACT.md §1), so downstream analysis code is
identical whether reading live events, new files, or legacy files.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any, BinaryIO, Iterator

import numpy as np

from .formats import (
    ENDIAN,
    LEGACY_DT_HG,
    LEGACY_DT_LG,
    LEGACY_DT_TOA,
    LEGACY_DT_TOT,
    LEGACY_DTQ_COUNT,
    LEGACY_DTQ_SPECT,
    LEGACY_DTQ_TIMING,
    LEGACY_DTQ_TSPECT,
    LEGACY_TYPEFILE_2ND_TSTAMP,
    LEGACY_UNIT_NS,
    LEN_PREFIX_SIZE,
    LEN_STRUCT,
    MAGIC,
    MAGIC_SIZE,
    NUM_CH,
    REC_COUNT,
    REC_SERVICE,
    REC_SPECT,
    REC_TEST,
    REC_TIMING,
    REC_WAVE,
    SPECT_FLAG_TSPECT,
    TOA_LSB_NS,
    FileHeader,
)

# Mirror the writer's fixed sub-record struct layouts exactly. -----------------
_COMMON = struct.Struct(ENDIAN + "B B i d")
_SPECT_SCALARS = struct.Struct(ENDIAN + "d Q Q Q Q Q")
_COUNT_SCALARS = struct.Struct(ENDIAN + "d Q Q I I")
_TIMING_SCALARS = struct.Struct(ENDIAN + "Q Q Q I")
_WAVE_SCALARS = struct.Struct(ENDIAN + "Q I")
_SERVICE_SCALARS = struct.Struct(
    ENDIAN + "I I I  I I  f f f f f f  f f  B B B B  I I I  I I I"
)
_TEST_SCALARS = struct.Struct(ENDIAN + "Q I")


class EventReader:
    """Iterable reader over a HydraFERS event file or a legacy Janus list .dat.

    Parameters
    ----------
    path:
        Path to the file to read.

    Examples
    --------
    >>> reader = EventReader("Run12_list.dat")
    >>> hdr = reader.header()
    >>> for ev in reader:
    ...     ...  # ev is a dict shaped like pyfers.get_event()
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        with open(self.path, "rb") as fp:
            self._is_new = fp.read(MAGIC_SIZE) == MAGIC
        if self._is_new:
            self._header = self._read_new_header()
        else:
            self._header = self._read_legacy_header()

    # ------------------------------------------------------------------
    # Public API (CONTRACT.md §3)
    # ------------------------------------------------------------------
    def header(self) -> FileHeader:
        """Return the :class:`FileHeader` (cached; parsed at construction)."""
        return self._header

    @property
    def is_legacy(self) -> bool:
        """``True`` if this file is a legacy Janus list ``.dat``."""
        return not self._is_new

    def __iter__(self) -> Iterator[dict]:
        if self._is_new:
            return self._iter_new()
        return self._iter_legacy()

    # ==================================================================
    # NEW FORMAT
    # ==================================================================
    def _read_new_header(self) -> FileHeader:
        with open(self.path, "rb") as fp:
            fp.seek(MAGIC_SIZE)
            (hlen,) = LEN_STRUCT.unpack(_read_exact(fp, LEN_PREFIX_SIZE))
            payload = _read_exact(fp, hlen)
        data = json.loads(payload.decode("utf-8"))
        return FileHeader.from_dict(data)

    def _iter_new(self) -> Iterator[dict]:
        with open(self.path, "rb") as fp:
            fp.seek(MAGIC_SIZE)
            (hlen,) = LEN_STRUCT.unpack(_read_exact(fp, LEN_PREFIX_SIZE))
            fp.seek(MAGIC_SIZE + LEN_PREFIX_SIZE + hlen)
            while True:
                prefix = fp.read(LEN_PREFIX_SIZE)
                if len(prefix) < LEN_PREFIX_SIZE:
                    break  # clean EOF
                (rlen,) = LEN_STRUCT.unpack(prefix)
                record = _read_exact(fp, rlen)
                yield _deserialize_new(record)

    # ==================================================================
    # LEGACY JANUS LIST .DAT
    # ==================================================================
    # Layout reproduced from janus-5202/src/outputfiles.c WriteListfileHeader.
    # NOTE: in that function the leading `fwrite(&header_size, ...)` is COMMENTED
    # OUT, so the file begins directly with the version bytes. The header is:
    #   fnumFVer (u8), snumFVer (u8),                 # file format version major.minor
    #   fnumSW   (u8), snumSW   (u8), tnumSW (u8),    # software release maj.min.patch
    #   brdVer   (u16),                               # board family (e.g. 5202)
    #   rn       (i16),                               # run number
    #   type_file(u8),                                # (AcquisitionMode & 0x0F) | (En2ndTs<<7)
    #   enbin    (u16),                               # EHistoNbin
    #   OutFileUnit (u8),                             # 0=LSB, 1=ns
    #   tmpLSB   (f32),                               # ToA/ToT LSB in ns
    #   start_time (i64)                              # epoch ms
    _LEGACY_HEADER = struct.Struct(ENDIAN + "B B  B B B  H h B H B f q")

    def _read_legacy_header(self) -> FileHeader:
        with open(self.path, "rb") as fp:
            raw = _read_exact(fp, self._LEGACY_HEADER.size)
        (
            fver_maj,
            fver_min,
            sw_maj,
            sw_min,
            sw_patch,
            brd_ver,
            run_num,
            type_file,
            enbin,
            unit,
            lsb,
            start_time,
        ) = self._LEGACY_HEADER.unpack(raw)

        mode_nibble = type_file & 0x0F
        acq_mode = {
            LEGACY_DTQ_SPECT: "SPECT",
            LEGACY_DTQ_TSPECT: "TSPECT",
            LEGACY_DTQ_TIMING: "TIMING",
            LEGACY_DTQ_COUNT: "COUNT",
        }.get(mode_nibble, f"UNKNOWN(0x{mode_nibble:02X})")

        return FileHeader(
            format_version=0,
            acquisition_mode=acq_mode,
            energy_nbins=int(enbin),
            toa_lsb_ns=float(lsb),
            start_time=int(start_time),
            board_model=str(int(brd_ver)),
            run_number=int(run_num),
            time_unit="ns" if unit == LEGACY_UNIT_NS else "LSB",
            sw_release=f"Janus {sw_maj}.{sw_min}.{sw_patch}",
            legacy=True,
            extra={
                "file_format_version": f"{fver_maj}.{fver_min}",
                "type_file": int(type_file),
            },
        )

    def _iter_legacy(self) -> Iterator[dict]:
        type_file = int(self._header.extra.get("type_file", 0))
        mode_nibble = type_file & 0x0F
        has_2nd_ts = bool(type_file & LEGACY_TYPEFILE_2ND_TSTAMP)
        unit_ns = self._header.time_unit == "ns"
        lsb = self._header.toa_lsb_ns

        with open(self.path, "rb") as fp:
            fp.seek(self._LEGACY_HEADER.size)
            while True:
                size_raw = fp.read(2)
                if len(size_raw) < 2:
                    break  # clean EOF
                (rec_size,) = struct.unpack(ENDIAN + "H", size_raw)
                if rec_size < 2:
                    break  # corrupt / truncated framing
                body = _read_exact(fp, rec_size - 2)
                if mode_nibble in (LEGACY_DTQ_SPECT, LEGACY_DTQ_TSPECT):
                    yield _legacy_spect_record(
                        body, mode_nibble, has_2nd_ts, unit_ns, lsb
                    )
                elif mode_nibble == LEGACY_DTQ_COUNT:
                    yield _legacy_count_record(body, has_2nd_ts)
                elif mode_nibble == LEGACY_DTQ_TIMING:
                    yield _legacy_timing_record(body, unit_ns, lsb)
                else:
                    # Unknown mode: cannot decode the body safely; stop.
                    break


# =====================================================================
# NEW-FORMAT record deserialization (mirror of writer_binary._serialize)
# =====================================================================
def _deserialize_new(record: bytes) -> dict:
    tag, board, dtq, tstamp_us = _COMMON.unpack_from(record, 0)
    off = _COMMON.size
    ev: dict[str, Any] = {"board": int(board), "dtq": int(dtq), "tstamp_us": float(tstamp_us)}

    if tag == REC_SPECT:
        (flag,) = struct.unpack_from(ENDIAN + "B", record, off)
        off += 1
        tspect = bool(flag & SPECT_FLAG_TSPECT)
        (rel, ts_clk, tref, trg, chmask, qdmask) = _SPECT_SCALARS.unpack_from(record, off)
        off += _SPECT_SCALARS.size
        ev.update(
            rel_tstamp_us=float(rel),
            tstamp_clk=int(ts_clk),
            tref_tstamp=int(tref),
            trigger_id=int(trg),
            chmask=int(chmask),
            qdmask=int(qdmask),
        )
        ev["energy_hg"], off = _take(record, off, NUM_CH, "<u2")
        ev["energy_lg"], off = _take(record, off, NUM_CH, "<u2")
        if tspect:
            ev["toa"], off = _take(record, off, NUM_CH, "<u4")
            ev["tot"], off = _take(record, off, NUM_CH, "<u2")
        return ev

    if tag == REC_COUNT:
        (rel, trg, chmask, t_or, q_or) = _COUNT_SCALARS.unpack_from(record, off)
        off += _COUNT_SCALARS.size
        ev.update(
            rel_tstamp_us=float(rel),
            trigger_id=int(trg),
            chmask=int(chmask),
            t_or_counts=int(t_or),
            q_or_counts=int(q_or),
        )
        ev["counts"], off = _take(record, off, NUM_CH, "<u4")
        return ev

    if tag == REC_TIMING:
        (trg, tref, ts_clk, nhits) = _TIMING_SCALARS.unpack_from(record, off)
        off += _TIMING_SCALARS.size
        nhits = int(nhits)
        ev.update(
            trigger_id=int(trg),
            tref_tstamp=int(tref),
            tstamp_clk=int(ts_clk),
            nhits=nhits,
        )
        ev["channel"], off = _take(record, off, nhits, "<u1")
        ev["edge"], off = _take(record, off, nhits, "<u1")
        ev["toa"], off = _take(record, off, nhits, "<u4")
        ev["tot"], off = _take(record, off, nhits, "<u2")
        return ev

    if tag == REC_WAVE:
        (trg, ns) = _WAVE_SCALARS.unpack_from(record, off)
        off += _WAVE_SCALARS.size
        ns = int(ns)
        ev.update(trigger_id=int(trg), ns=ns)
        ev["wave_hg"], off = _take(record, off, ns, "<u2")
        ev["wave_lg"], off = _take(record, off, ns, "<u2")
        ev["dig_probes"], off = _take(record, off, ns, "<u1")
        return ev

    if tag == REC_SERVICE:
        fields = _SERVICE_SCALARS.unpack_from(record, off)
        off += _SERVICE_SCALARS.size
        (
            pkt_size, version, fmt, q_or, t_or,
            tfpga, tboard, ttdc0, ttdc1, thv, tdet,
            vmon, imon, hv_on, hv_ramp, hv_ovv, hv_ovc,
            status, tdc_ro, ro_flags, tot_trg, rej_trg, suppr_trg,
        ) = fields
        ev.update(
            pkt_size=int(pkt_size), version=int(version), format=int(fmt),
            q_or_cnt=int(q_or), t_or_cnt=int(t_or),
            temp_fpga=float(tfpga), temp_board=float(tboard),
            temp_tdc0=float(ttdc0), temp_tdc1=float(ttdc1),
            temp_hv=float(thv), temp_detector=float(tdet),
            hv_vmon=float(vmon), hv_imon=float(imon),
            hv_on=int(hv_on), hv_ramp=int(hv_ramp),
            hv_ovv=int(hv_ovv), hv_ovc=int(hv_ovc),
            status=int(status), tdc_ro_status=int(tdc_ro),
            readout_flags=int(ro_flags),
            tot_trg_cnt=int(tot_trg), rej_trg_cnt=int(rej_trg),
            suppr_trg_cnt=int(suppr_trg),
        )
        ev["ch_trg_cnt"], off = _take(record, off, NUM_CH, "<u4")
        return ev

    if tag == REC_TEST:
        (trg, nwords) = _TEST_SCALARS.unpack_from(record, off)
        off += _TEST_SCALARS.size
        nwords = int(nwords)
        ev.update(trigger_id=int(trg), nwords=nwords)
        ev["test_data"], off = _take(record, off, nwords, "<u4")
        return ev

    raise ValueError(f"EventReader: unknown new-format record tag 0x{tag:02X}")


def _take(buf: bytes, off: int, count: int, dtype: str) -> tuple[np.ndarray, int]:
    """Read ``count`` little-endian elements of ``dtype`` from ``buf`` at ``off``.

    Returns a *copy* (the buffer is local to the record, but copying keeps the
    returned dict safe to retain) and the new offset.
    """
    nbytes = count * np.dtype(dtype).itemsize
    arr = np.frombuffer(buf, dtype=np.dtype(dtype), count=count, offset=off).copy()
    return arr, off + nbytes


# =====================================================================
# LEGACY record deserialization (mirror of outputfiles.c SaveList)
# =====================================================================
def _legacy_spect_record(
    body: bytes, mode_nibble: int, has_2nd_ts: bool, unit_ns: bool, lsb: float
) -> dict:
    """Decode one legacy SPECT / SPECT_TIMING record body (size prefix consumed).

    Field order (after the consumed 2-byte size), from SaveList:
        b8 (u8), ts (f64),
        [rel_tstamp_us (f64) if type_file & 0x80],
        [DeltaTref_f (f64) if TSpect],
        trgid (u64), chmask (u64), num_of_hits (u16),
        then per fired channel:
            i (u8), datatype (u8),
            [energyLG (u16) if dt & 0x01],
            [energyHG (u16) if dt & 0x02],
            [ToA: f32 if unit==ns else u32, if dt & 0x10],
            [ToT: f32 if unit==ns else u16, if dt & 0x20]
    """
    is_tspect = mode_nibble == LEGACY_DTQ_TSPECT
    off = 0
    (board,) = struct.unpack_from(ENDIAN + "B", body, off); off += 1
    (ts,) = struct.unpack_from(ENDIAN + "d", body, off); off += 8
    rel = 0.0
    if has_2nd_ts:
        (rel,) = struct.unpack_from(ENDIAN + "d", body, off); off += 8
    delta_tref = 0.0
    if is_tspect:
        (delta_tref,) = struct.unpack_from(ENDIAN + "d", body, off); off += 8
    (trgid,) = struct.unpack_from(ENDIAN + "Q", body, off); off += 8
    (chmask,) = struct.unpack_from(ENDIAN + "Q", body, off); off += 8
    (nhits,) = struct.unpack_from(ENDIAN + "H", body, off); off += 2

    energy_hg = np.zeros(NUM_CH, dtype=np.uint16)
    energy_lg = np.zeros(NUM_CH, dtype=np.uint16)
    toa = np.zeros(NUM_CH, dtype=np.uint32)
    tot = np.zeros(NUM_CH, dtype=np.uint16)

    for _ in range(nhits):
        (ch,) = struct.unpack_from(ENDIAN + "B", body, off); off += 1
        (dt,) = struct.unpack_from(ENDIAN + "B", body, off); off += 1
        ch = int(ch)
        if dt & LEGACY_DT_LG:
            (val,) = struct.unpack_from(ENDIAN + "H", body, off); off += 2
            if ch < NUM_CH:
                energy_lg[ch] = val
        if dt & LEGACY_DT_HG:
            (val,) = struct.unpack_from(ENDIAN + "H", body, off); off += 2
            if ch < NUM_CH:
                energy_hg[ch] = val
        if dt & LEGACY_DT_TOA:
            if unit_ns:
                (fval,) = struct.unpack_from(ENDIAN + "f", body, off); off += 4
                raw = int(round(fval / lsb)) if lsb else int(round(fval))
            else:
                (raw,) = struct.unpack_from(ENDIAN + "I", body, off); off += 4
            if ch < NUM_CH:
                toa[ch] = raw & 0xFFFFFFFF
        if dt & LEGACY_DT_TOT:
            if unit_ns:
                (fval,) = struct.unpack_from(ENDIAN + "f", body, off); off += 4
                raw = int(round(fval / lsb)) if lsb else int(round(fval))
            else:
                (raw,) = struct.unpack_from(ENDIAN + "H", body, off); off += 2
            if ch < NUM_CH:
                tot[ch] = raw & 0xFFFF

    dtq = LEGACY_DTQ_TSPECT if is_tspect else LEGACY_DTQ_SPECT
    if has_2nd_ts:
        dtq |= 0x80
    ev: dict[str, Any] = {
        "board": int(board),
        "dtq": int(dtq),
        "tstamp_us": float(ts),
        "rel_tstamp_us": float(rel),
        "tstamp_clk": 0,
        # DeltaTref_f (us) is the only Tref info preserved by the legacy writer;
        # store it under tref_tstamp_us so no information is silently dropped.
        "tref_tstamp": 0,
        "tref_tstamp_us": float(delta_tref),
        "trigger_id": int(trgid),
        "chmask": int(chmask),
        "qdmask": 0,
        "energy_hg": energy_hg,
        "energy_lg": energy_lg,
    }
    if is_tspect:
        ev["toa"] = toa
        ev["tot"] = tot
    return ev


def _legacy_count_record(body: bytes, has_2nd_ts: bool) -> dict:
    """Decode one legacy COUNTING record body.

    Field order (after the 2-byte size), from SaveList:
        b8 (u8), ts (f64),
        [rel_tstamp_us (f64) if type_file & 0x80],
        trgid (u64), ev_chmask (u64), num_of_hits (u16),
        then per hit: chId (u8), count (u64)
    """
    off = 0
    (board,) = struct.unpack_from(ENDIAN + "B", body, off); off += 1
    (ts,) = struct.unpack_from(ENDIAN + "d", body, off); off += 8
    rel = 0.0
    if has_2nd_ts:
        (rel,) = struct.unpack_from(ENDIAN + "d", body, off); off += 8
    (trgid,) = struct.unpack_from(ENDIAN + "Q", body, off); off += 8
    (chmask,) = struct.unpack_from(ENDIAN + "Q", body, off); off += 8
    (nhits,) = struct.unpack_from(ENDIAN + "H", body, off); off += 2

    counts = np.zeros(NUM_CH, dtype=np.uint32)
    for _ in range(nhits):
        (ch,) = struct.unpack_from(ENDIAN + "B", body, off); off += 1
        (cnt,) = struct.unpack_from(ENDIAN + "Q", body, off); off += 8
        if int(ch) < NUM_CH:
            counts[int(ch)] = cnt & 0xFFFFFFFF

    dtq = LEGACY_DTQ_COUNT | (0x80 if has_2nd_ts else 0)
    return {
        "board": int(board),
        "dtq": int(dtq),
        "tstamp_us": float(ts),
        "rel_tstamp_us": float(rel),
        "trigger_id": int(trgid),
        "chmask": int(chmask),
        "counts": counts,
        "t_or_counts": 0,
        "q_or_counts": 0,
    }


def _legacy_timing_record(body: bytes, unit_ns: bool, lsb: float) -> dict:
    """Decode one legacy TIMING (list) record body.

    Field order (after the 2-byte size), from SaveList:
        b8 (u8), fine_tstamp (f64), nhits (u16),
        then per hit: channel (u8), datatype (u8),
            [ToA: f32 if unit==ns else u32, if dt & 0x10],
            [ToT: f32 if unit==ns else u16, if dt & 0x20]
    Note: timing records carry no trigger_id (the legacy writer omits it).
    """
    off = 0
    (board,) = struct.unpack_from(ENDIAN + "B", body, off); off += 1
    (fine_ts,) = struct.unpack_from(ENDIAN + "d", body, off); off += 8
    (nhits,) = struct.unpack_from(ENDIAN + "H", body, off); off += 2
    nhits = int(nhits)

    channel = np.zeros(nhits, dtype=np.uint8)
    edge = np.zeros(nhits, dtype=np.uint8)
    toa = np.zeros(nhits, dtype=np.uint32)
    tot = np.zeros(nhits, dtype=np.uint16)

    for i in range(nhits):
        (ch,) = struct.unpack_from(ENDIAN + "B", body, off); off += 1
        (dt,) = struct.unpack_from(ENDIAN + "B", body, off); off += 1
        channel[i] = ch
        if dt & LEGACY_DT_TOA:
            if unit_ns:
                (fval,) = struct.unpack_from(ENDIAN + "f", body, off); off += 4
                toa[i] = (int(round(fval / lsb)) if lsb else int(round(fval))) & 0xFFFFFFFF
            else:
                (raw,) = struct.unpack_from(ENDIAN + "I", body, off); off += 4
                toa[i] = raw & 0xFFFFFFFF
        if dt & LEGACY_DT_TOT:
            if unit_ns:
                (fval,) = struct.unpack_from(ENDIAN + "f", body, off); off += 4
                tot[i] = (int(round(fval / lsb)) if lsb else int(round(fval))) & 0xFFFF
            else:
                (raw,) = struct.unpack_from(ENDIAN + "H", body, off); off += 2
                tot[i] = raw & 0xFFFF

    # fine_tstamp (us) is what the legacy writer persists for timing records.
    return {
        "board": int(board),
        "dtq": int(LEGACY_DTQ_TIMING),
        "tstamp_us": float(fine_ts),
        "trigger_id": 0,
        "nhits": nhits,
        "tref_tstamp": 0,
        "tstamp_clk": 0,
        "channel": channel,
        "edge": edge,
        "toa": toa,
        "tot": tot,
    }


# =====================================================================
# Helpers
# =====================================================================
def _read_exact(fp: BinaryIO, n: int) -> bytes:
    """Read exactly ``n`` bytes or raise ``EOFError`` on a short/truncated read."""
    data = fp.read(n)
    if len(data) != n:
        raise EOFError(
            f"unexpected EOF: wanted {n} bytes, got {len(data)} in {getattr(fp, 'name', '<stream>')}"
        )
    return data
