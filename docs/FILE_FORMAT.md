# HydraFERS Event File Format

This document specifies the on-disk byte layout written by
`hydrafers.io.EventWriter` (the **new** versioned format) and the **legacy** Janus
list `.dat` layout that `hydrafers.io.EventReader` can also read for backward
compatibility.

All multi-byte integers and floats are **little-endian**. Event dicts handled by
this layer have the same shape `pyfers.get_event` returns (see CONTRACT.md §1):
the writer serializes the per-mode fields and the reader yields dicts of the
identical shape.

---

## 1. Detecting new vs legacy

A reader distinguishes the two formats by the first 8 bytes:

| First bytes | Format |
|---|---|
| ASCII `HYDRFERS` (`48 59 44 52 46 45 52 53`) | **New** HydraFERS format |
| anything else | **Legacy** Janus list `.dat` |

This is unambiguous: a legacy list file begins with the legacy *file-format
version major* byte (a small integer such as `0x03`), which can never be the
ASCII letter `H` (`0x48`).

---

## 2. New HydraFERS format (`format_version = 1`)

### 2.1 Overall structure

```
+----------------------------------------------------------+
| MAGIC          : 8 bytes  = "HYDRFERS"                    |
+----------------------------------------------------------+
| HEADER_LEN     : uint32   (LE) = byte length of JSON      |
+----------------------------------------------------------+
| HEADER_JSON    : HEADER_LEN bytes, UTF-8 JSON object      |
+----------------------------------------------------------+
| record[0]      : uint32 REC_LEN  +  REC_LEN payload bytes |
| record[1]      : uint32 REC_LEN  +  REC_LEN payload bytes |
| ...                                                       |
| record[N-1]    : uint32 REC_LEN  +  REC_LEN payload bytes |
+----------------------------------------------------------+
```

* The header is a single length-prefixed UTF-8 JSON object — human-inspectable,
  forward-compatible (unknown keys are preserved under `extra`).
* Every event is a **length-prefixed binary record**: a `uint32` byte length
  followed by exactly that many payload bytes. The length prefix lets a reader
  skip records it does not understand and makes the stream resynchronizable.
* The writer **buffers** records (default 4 MiB) and emits them to the OS in
  large sequential `write()` calls — never one syscall per event (CONTRACT.md §3).

### 2.2 JSON header fields

Serialized from `FileHeader`:

| Key | Type | Meaning |
|---|---|---|
| `format_version` | int | New-format version; `2` (was `1`; see §2.5). |
| `acquisition_mode` | str | `SPECT`, `TSPECT`, `TIMING`, `COUNT`, `WAVE`, `TEST`, `SERVICE`, or a 5203 mode (`COMMON_START`, …). |
| `energy_nbins` | int | PHA/energy histogram bin count (`EHistoNbin`); on 5203 carries `LeadTrailHistoNbin`. |
| `toa_lsb_ns` | float | ToA/ToT LSB in ns (e.g. `0.5` for 5202). |
| `start_time` | int | Run start time, epoch milliseconds. |
| `board_model` | str | Board model, e.g. `A5202` / `A5203`. |
| `run_number` | int | Run number (`-1` if unknown). |
| `time_unit` | str | `LSB` or `ns`. |
| `sw_release` | str | Producing software release. |
| `legacy` | bool | Always `false` in new files. |
| `board_family` | int | **v2.** FERSCode of the recording board (`5202` or `5203`); lets a reader interpret records without external context. Defaults to `5202` for v1 files. |
| `num_ch` | int | **v2.** Per-channel array width (`64` for 5202, `128` for 5203). Defaults to `64` for v1 files. |
| `meas_mode` | str | **v2.** A5203 time-measurement mode (`LEAD_ONLY` / `LEAD_TRAIL` / `LEAD_TOT8` / `LEAD_TOT11`); empty for 5202. |
| `extra` | object | Free-form metadata bag. |

> **A5203 (picoTDC) note.** A 5203 run contains only `REC_TIMING` and
> `REC_SERVICE` records. `REC_TIMING` already carries per-hit
> `channel(u8) edge(u8) toa(u32) tot(u16)` (§2.3), so the picoTDC's edge flag and
> 32-bit ToA need no new record type — only the `board_family` / `num_ch` /
> `meas_mode` header fields above tell a reader to read the timing hits as
> lead/trail edges over up to 128 channels rather than 5202 list data.

### 2.3 Record payload layout

Every record begins with a **common block**:

| Field | Type | Notes |
|---|---|---|
| `tag` | uint8 | Record type (see below). |
| `board` | uint8 | Board index. |
| `dtq` | int32 | Data qualifier as returned by ferslib. |
| `tstamp_us` | float64 | Event timestamp in µs. |

Record `tag` values:

| Tag | Value | Mode |
|---|---|---|
| `REC_SPECT` | `0x01` | Spectroscopy / Spect+Timing |
| `REC_TIMING` | `0x02` | Timing (list) |
| `REC_COUNT` | `0x04` | Counting (MCS) |
| `REC_WAVE` | `0x08` | Waveform |
| `REC_SERVICE` | `0x2F` | Service event |
| `REC_TEST` | `0xFF` | Test |

`NUM_CH = 64` (5202 family). Per-channel arrays are fixed length `NUM_CH`;
per-hit / per-sample arrays are length `nhits` / `ns` / `nwords` as carried in
the record.

#### REC_SPECT (`0x01`) — SPECT and TSPECT

After the common block:

| Field | Type | Notes |
|---|---|---|
| `flags` | uint8 | bit0 (`SPECT_FLAG_TSPECT`) set ⇒ TSPECT (ToA/ToT present). |
| `rel_tstamp_us` | float64 | |
| `tstamp_clk` | uint64 | |
| `tref_tstamp` | uint64 | |
| `trigger_id` | uint64 | |
| `chmask` | uint64 | |
| `qdmask` | uint64 | |
| `energy_hg[64]` | uint16 × 64 | |
| `energy_lg[64]` | uint16 × 64 | |
| `toa[64]` | uint32 × 64 | **only if** `flags & SPECT_FLAG_TSPECT` |
| `tot[64]` | uint16 × 64 | **only if** `flags & SPECT_FLAG_TSPECT` |

#### REC_COUNT (`0x04`)

| Field | Type |
|---|---|
| `rel_tstamp_us` | float64 |
| `trigger_id` | uint64 |
| `chmask` | uint64 |
| `t_or_counts` | uint32 |
| `q_or_counts` | uint32 |
| `counts[64]` | uint32 × 64 |

#### REC_TIMING (`0x02`)

| Field | Type | Notes |
|---|---|---|
| `trigger_id` | uint64 | |
| `tref_tstamp` | uint64 | |
| `tstamp_clk` | uint64 | |
| `nhits` | uint32 | |
| `channel[nhits]` | uint8 × nhits | |
| `edge[nhits]` | uint8 × nhits | |
| `toa[nhits]` | uint32 × nhits | |
| `tot[nhits]` | uint16 × nhits | |

#### REC_WAVE (`0x08`)

| Field | Type |
|---|---|
| `trigger_id` | uint64 |
| `ns` | uint32 |
| `wave_hg[ns]` | uint16 × ns |
| `wave_lg[ns]` | uint16 × ns |
| `dig_probes[ns]` | uint8 × ns |

#### REC_SERVICE (`0x2F`)

| Field | Type |
|---|---|
| `pkt_size` | uint32 |
| `version` | uint32 |
| `format` | uint32 |
| `q_or_cnt` | uint32 |
| `t_or_cnt` | uint32 |
| `temp_fpga` | float32 |
| `temp_board` | float32 |
| `temp_tdc0` | float32 |
| `temp_tdc1` | float32 |
| `temp_hv` | float32 |
| `temp_detector` | float32 |
| `hv_vmon` | float32 |
| `hv_imon` | float32 |
| `hv_on` | uint8 |
| `hv_ramp` | uint8 |
| `hv_ovv` | uint8 |
| `hv_ovc` | uint8 |
| `status` | uint32 |
| `tdc_ro_status` | uint32 |
| `readout_flags` | uint32 |
| `tot_trg_cnt` | uint32 |
| `rej_trg_cnt` | uint32 |
| `suppr_trg_cnt` | uint32 |
| `ch_trg_cnt[64]` | uint32 × 64 |

#### REC_TEST (`0xFF`)

| Field | Type |
|---|---|
| `trigger_id` | uint64 |
| `nwords` | uint32 |
| `test_data[nwords]` | uint32 × nwords |

### 2.4 Sentinels

The reprocess-finished sentinel `{'dtq': -1, 'reprocess_finished': True}` and
`None` carry no payload and are **not** written; `write_event()` ignores them.

### 2.5 Versioning policy

* `format_version` lives in the JSON header. Bump it when the record encoding
  changes incompatibly.
* New header keys are additive: older readers preserve unknown keys under
  `extra` and keep working.
* Because every record is length-prefixed, a future writer may add record types
  or trailing fields; a reader that does not recognize a `tag` raises rather than
  silently misparsing.

---

## 3. Legacy Janus list `.dat` (read-only)

Reproduced from `janus-5202/src/outputfiles.c` (`WriteListfileHeader` and
`SaveList`). HydraFERS reads these but does **not** write them.

### 3.1 Header

> **Important:** in `WriteListfileHeader` the leading
> `fwrite(&header_size, ...)` is **commented out**, so the file begins directly
> with the version bytes (there is no leading size byte).

| Offset | Field | Type | Source |
|---|---|---|---|
| 0 | file-format version major | uint8 | `fnumFVer` (`FILE_LIST_VER`, e.g. `3`) |
| 1 | file-format version minor | uint8 | `snumFVer` (e.g. `4`) |
| 2 | software major | uint8 | `fnumSW` (`SW_RELEASE_NUM`) |
| 3 | software minor | uint8 | `snumSW` |
| 4 | software patch | uint8 | `tnumSW` |
| 5 | board family | uint16 | `brdVer` (e.g. `5202`) |
| 7 | run number | int16 | `rn` |
| 9 | `type_file` | uint8 | `(AcquisitionMode & 0x0F) \| (Enable_2nd_tstamp << 7)` |
| 10 | energy bins | uint16 | `EHistoNbin` |
| 12 | output unit | uint8 | `OutFileUnit`: 0 = LSB, 1 = ns |
| 13 | ToA/ToT LSB (ns) | float32 | `TOA_LSB_ns` (e.g. `0.5`) |
| 17 | start time | int64 | `Stats.start_time`, epoch ms |
| 25 | first record | — | records follow |

`type_file & 0x0F` selects the record decoder:
`0x01` = SPECT, `0x03` = TSPECT, `0x02` = TIMING, `0x04` = COUNT.
`type_file & 0x80` ⇒ a relative (2nd) timestamp is present in SPECT/COUNT records.

### 3.2 Record framing

Every record starts with a `uint16` **size** that **includes the 2 size bytes
themselves** (`size = sizeof(size) + body`). The decoder reads `size`, then
reads `size - 2` body bytes.

### 3.3 SPECT / TSPECT record body

```
b8            uint8          board
ts            float64        timestamp (µs)
[rel_ts       float64]       present if type_file & 0x80
[DeltaTref_f  float64]       present if TSPECT (mapped to ev['tref_tstamp_us'])
trgid         uint64
chmask        uint64
num_of_hits   uint16
repeat num_of_hits times, one per fired channel:
    ch        uint8
    datatype  uint8          bits: 0x01 LG, 0x02 HG, 0x10 ToA, 0x20 ToT
    [LG       uint16]        if datatype & 0x01
    [HG       uint16]        if datatype & 0x02
    [ToA      float32|uint32] if datatype & 0x10  (float32 ns when unit=ns, else uint32 LSB)
    [ToT      float32|uint16] if datatype & 0x20  (float32 ns when unit=ns, else uint16 LSB)
```

When the file unit is `ns`, ToA/ToT are stored as `value * TOA_LSB_ns`; the
reader divides by `toa_lsb_ns` to restore raw LSB integers so the resulting dict
matches the pyfers shape (`toa`: uint32[64], `tot`: uint16[64]). Energies are
placed into `energy_hg[ch]` / `energy_lg[ch]`; other channels are 0.

### 3.4 COUNT record body

```
b8            uint8          board
ts            float64
[rel_ts       float64]       present if type_file & 0x80
trgid         uint64
ev_chmask     uint64
num_of_hits   uint16
repeat num_of_hits times:
    chId      uint8
    count     uint64         -> stored into counts[chId] as uint32
```

### 3.5 TIMING record body

```
b8            uint8          board
fine_tstamp   float64        -> ev['tstamp_us']
nhits         uint16
repeat nhits times:
    channel   uint8
    datatype  uint8          bits: 0x10 ToA, 0x20 ToT
    [ToA      float32|uint32] if datatype & 0x10
    [ToT      float32|uint16] if datatype & 0x20
```

Legacy timing records carry **no** `trigger_id` (the writer omits it); the reader
sets `trigger_id = 0`. `edge` is not stored in the legacy format and is returned
as zeros.

### 3.6 Fields not representable

The legacy list format is lossy relative to the full ferslib event structs (it
stores only what the histogram/analysis pipeline needed). The reader fills any
field it cannot recover with `0` / empty so the emitted dict still has the
pyfers shape. The new HydraFERS format preserves all per-mode fields and should
be preferred for new acquisitions.
