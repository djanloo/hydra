"""File-format definitions for the HydraFERS output layer.

Layer: ``hydrafers.io`` (pure Python; numpy only; NO ``pyfers`` import) — see
CONTRACT.md §0. This module owns the ``FileHeader`` dataclass plus all byte-layout
constants and versioning needed by both the writer (``writer_binary.py``) and the
reader (``reader.py``).

Two on-disk formats are handled by this package:

* **New HydraFERS format** (``format_version`` starting at 1): an 8-byte magic,
  a 4-byte little-endian length-prefixed UTF-8 JSON header, then a stream of
  4-byte little-endian length-prefixed binary event records. Designed for large
  sequential writes (the writer buffers; it never issues one syscall per event).
* **Legacy Janus list ``.dat`` format**: reproduced for backward-compatible
  *reading* only, faithfully following ``janus-5202/src/outputfiles.c``
  (``WriteListfileHeader`` + ``SaveList``). The legacy writer is intentionally
  not provided — HydraFERS writes the new format.

The byte layout is documented in ``docs/FILE_FORMAT.md``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field, asdict
from typing import Any

# ---------------------------------------------------------------------------
# New HydraFERS format constants
# ---------------------------------------------------------------------------

#: Magic bytes at the very start of a new-format file. 8 bytes, ASCII.
#: Chosen so it cannot collide with a legacy list .dat file, whose first byte is
#: the major file-format version number (a small integer such as 0x03), never
#: the ASCII letter 'H' (0x48).
MAGIC: bytes = b"HYDRFERS"
MAGIC_SIZE: int = len(MAGIC)

#: Current new-format version written by :class:`~hydrafers.io.EventWriter`.
#: v2 adds the self-describing ``board_family`` / ``num_ch`` / ``meas_mode``
#: header fields so a reader can interpret a file without external context
#: (A5202 energy vs A5203 picoTDC lead/trail). v1 files remain readable — the
#: missing fields fall back to their A5202 defaults via ``FileHeader.from_dict``.
FORMAT_VERSION: int = 2

#: All multi-byte integers/floats in the new format are little-endian.
ENDIAN: str = "<"

#: The JSON header and every event record are prefixed by a 4-byte unsigned
#: little-endian length. ``LEN_STRUCT`` packs/unpacks that prefix.
LEN_STRUCT: struct.Struct = struct.Struct(ENDIAN + "I")
LEN_PREFIX_SIZE: int = LEN_STRUCT.size

#: Default write buffer (bytes). The writer accumulates this much before issuing
#: a single large sequential write to the OS — see CONTRACT.md §3.
DEFAULT_BUFFER_BYTES: int = 4 * 1024 * 1024

#: Number of channels per board for the 5202 family (FERSLIB_MAX_NCH_5202).
#: Per-channel event arrays (energy_hg/energy_lg/toa/tot/counts/ch_trg_cnt) are
#: this length in the dicts pyfers returns.
NUM_CH: int = 64

# ---------------------------------------------------------------------------
# Per-mode record type tags (new format only)
# ---------------------------------------------------------------------------
# Each event record begins with a 1-byte record-type tag so the reader can
# dispatch deserialization without consulting the header acquisition mode. The
# tags intentionally mirror the ferslib data-qualifier nibble where it makes
# sense, but they are an independent, stable on-disk contract.

REC_SPECT: int = 0x01      # SPECT and TSPECT (a flag in the record distinguishes them)
REC_COUNT: int = 0x04
REC_TIMING: int = 0x02
REC_WAVE: int = 0x08
REC_SERVICE: int = 0x2F
REC_TEST: int = 0xFF

#: Bit set in the SPECT record flags byte when the event is TSPECT (timing+spect),
#: i.e. it carries per-channel ToA/ToT in addition to HG/LG energies.
SPECT_FLAG_TSPECT: int = 0x01

# ---------------------------------------------------------------------------
# Legacy Janus list .dat constants (read-only support)
# ---------------------------------------------------------------------------
# Reproduced from janus-5202/src/outputfiles.c and JanusC.h.

#: Legacy "File Format Version" string (JanusC.h FILE_LIST_VER).
LEGACY_FILE_LIST_VER: str = "3.4"

#: Legacy data-qualifier nibble values used inside list records (DTQ_* in FERSlib.h).
LEGACY_DTQ_SPECT: int = 0x01
LEGACY_DTQ_TIMING: int = 0x02
LEGACY_DTQ_TSPECT: int = 0x03
LEGACY_DTQ_COUNT: int = 0x04

#: ``type_file`` bit set when a second (relative) timestamp is present in records
#: (outputfiles.c: ``type_file = (AcquisitionMode & 0x0F) | (Enable_2nd_tstamp<<7)``).
LEGACY_TYPEFILE_2ND_TSTAMP: int = 0x80

#: Per-channel datatype bits used inside legacy SPECT / TIMING records (SaveList).
LEGACY_DT_LG: int = 0x01     # low-gain energy present
LEGACY_DT_HG: int = 0x02     # high-gain energy present
LEGACY_DT_TOA: int = 0x10    # ToA (timestamp) present
LEGACY_DT_TOT: int = 0x20    # ToT present

#: OutFileUnit values (param OF_OutFileUnit): 0 = LSB (raw integer), 1 = ns (float).
LEGACY_UNIT_LSB: int = 0
LEGACY_UNIT_NS: int = 1

#: ToA/ToT LSB for the 5202 (FERSlib.h TOA_LSB_ns).
TOA_LSB_NS: float = 0.5


@dataclass
class FileHeader:
    """Self-describing header for a HydraFERS event file.

    The same dataclass is produced by :meth:`EventReader.header` for both the new
    and the legacy formats; legacy-only fields are filled on a best-effort basis
    when reading old files and preserved for round-tripping where possible.

    Attributes
    ----------
    format_version:
        New-format version (starts at 1). For legacy files this is set to 0 and
        :attr:`legacy` is ``True``.
    acquisition_mode:
        Human-readable acquisition mode, e.g. ``"SPECT"``, ``"TSPECT"``,
        ``"TIMING"``, ``"COUNT"``, ``"WAVE"``, ``"TEST"``, ``"SERVICE"``.
    energy_nbins:
        Number of bins in the energy/PHA histogram (``EHistoNbin``).
    toa_lsb_ns:
        ToA/ToT least-significant-bit value in nanoseconds.
    start_time:
        Run start time, epoch milliseconds.
    board_model:
        Board model string, e.g. ``"A5202"`` / ``"5202"``.
    run_number:
        Run number (legacy ``rn``; -1 if unknown).
    time_unit:
        Unit used for ToA/ToT values inside records: ``"LSB"`` or ``"ns"``.
    sw_release:
        Producing software release string.
    legacy:
        ``True`` when the header was reconstructed from a legacy list ``.dat``.
    extra:
        Free-form metadata bag, serialized into the JSON header of new files and
        ignored (empty) for legacy files.
    """

    format_version: int = FORMAT_VERSION
    acquisition_mode: str = "SPECT"
    energy_nbins: int = 4096
    toa_lsb_ns: float = TOA_LSB_NS
    start_time: int = 0
    board_model: str = "A5202"
    run_number: int = -1
    time_unit: str = "LSB"
    sw_release: str = "HydraFERS"
    legacy: bool = False
    #: Board family / FERSCode this file was recorded from (5202 or 5203). Lets a
    #: reader pick the right interpretation (energy vs picoTDC lead/trail) without
    #: external context. Defaults to 5202 for v1 files that predate the field.
    board_family: int = 5202
    #: Per-channel array width of the recording board (64 for 5202, 128 for 5203).
    num_ch: int = NUM_CH
    #: A5203 time-measurement mode (LEAD_ONLY / LEAD_TRAIL / LEAD_TOT8 / LEAD_TOT11);
    #: empty for the A5202 family.
    meas_mode: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a plain JSON-serializable dict of this header."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FileHeader":
        """Build a :class:`FileHeader` from a dict, ignoring unknown keys.

        Unknown keys are preserved under ``extra`` so future format revisions do
        not lose information when round-tripped through an older reader.
        """
        known = cls.__dataclass_fields__.keys()
        kwargs: dict[str, Any] = {}
        unknown: dict[str, Any] = {}
        for key, value in data.items():
            if key in known and key != "extra":
                kwargs[key] = value
            elif key == "extra":
                unknown.update(value or {})
            else:
                unknown[key] = value
        header = cls(**kwargs)
        if unknown:
            header.extra.update(unknown)
        return header
