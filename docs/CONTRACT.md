# HydraFERS — Interface Contract (BINDING)

**This document is the single source of truth for all cross-component interfaces.**
Every implementation MUST adhere to the names, signatures, and data shapes defined here.
If something is underspecified, follow the conventions already established here; do not invent
divergent names.

HydraFERS is the modern renewal of the CAEN FERS / Janus DAQ software. It replaces the old
two-process design (Python tkinter GUI ↔ JanusC.exe over a TCP socket) with a single
multithreaded Python application, organized in a **two-layer Python stack** over `ferslib`
(unchanged C library):

```
 ferslib (C, frozen, vendored in native/ferslib)
   → pyferslib   (C++ pybind11 module)  — FAITHFUL 1:1 binding: same functions, structs,
   │                                       types, constants; string-based param API kept.
   → pyfers      (pure-Python package)  — PYTHONIC SDK: OOP Board/System, enums, properties,
   │                                       typed events, context managers, exceptions.
   → hydrafers.core (engine)            — threads (readout/writer/stats), file IO, run control.
   │                                       Uses pyfers for the CONTROL-plane and pyferslib
   │                                       (drain_events) for the high-rate DATA-plane.
   → hydrafers.cli / hydrafers.gui      — interchangeable frontends over AcquisitionEngine.
```

Importable names: compiled module `import pyferslib`; pure-Python SDK `import pyfers`;
application `import hydrafers`. (NB: this REASSIGNS the names vs the old WIP repo, where the
compiled module was `pyfers`. Here `pyferslib` = the binding, `pyfers` = the pythonic layer.)

---

## 0. Layered dependency rules (STRICT)

```
pyferslib (C++)        ← depends only on ferslib
pyfers (Python)        ← imports pyferslib ONLY; no Qt, no hydrafers
hydrafers.config       ← pure Python (pydantic, pyyaml); imports NOTHING from pyferslib/pyfers/Qt
hydrafers.io           ← pure Python (numpy); imports NOTHING from pyferslib/pyfers/Qt
hydrafers.core         ← imports pyfers (control-plane) + pyferslib (data-plane) + config + io
hydrafers.cli          ← imports hydrafers.core + hydrafers.config; NO pyferslib/pyfers/Qt direct
hydrafers.gui          ← imports hydrafers.core + hydrafers.config; PySide6 + pyqtgraph
```
Rationale: `pyferslib` tracks the C API and changes only when ferslib changes; `pyfers` is where
ergonomic/design choices live and can iterate without recompiling; `hydrafers.core` is the DAQ
application engine with ZERO presentation logic. CLI and GUI are interchangeable frontends over the
identical `AcquisitionEngine` API.

---

## 1a. `pyferslib` — faithful 1:1 binding (native/bindings/pyferslib.cpp)

A pybind11 module that mirrors ferslib **as-is**: same functions, same structs/types, same
constants. NO renaming of params, NO OOP, string-based param API kept verbatim. This layer does not
"fix" any design — it transliterates the C API.

Conventions:
- `PYBIND11_MODULE(pyferslib, m)`.
- All ferslib calls release the GIL (`py::gil_scoped_release`).
- **Error handling (the one concession to Python):** a ferslib return `< 0` raises
  `pyferslib.FERSError(code, message)` where message comes from `FERS_GetLastError`. (`RAWDATA_REPROCESS_FINISHED`
  == 4 is NOT an error — it is returned/flagged, see get_event.)
- **Out-parameters become return values** (e.g. `FERS_OpenDevice(path, &handle)` → `open_device(path) -> int`).
- Handles are plain `int`.

### Bound struct types (exposed as `py::class_`, read-only data classes mirroring FERSlib.h)
Expose the real structs with their real field names (snake_case-ized is allowed but keep them
recognizable). Fixed C arrays (`energyHG[64]`) and pointer+length (`wave_hg`/`ns`) are exposed as
**read-only NumPy arrays COPIED out of the reused ferslib buffer** (never a view — the buffer is
recycled). Bind:
- `BoardInfo`   ← FERS_BoardInfo_t  {pid, fers_code, pcb_revision, model_code, model_name, form_factor, num_ch, fpga_fwrev, uc_fwrev}
- `CncInfo`     ← FERS_CncInfo_t    {pid, pcb_revision, model_code, model_name, fpga_fwrev, sw_rev, mac_10gbe, master_slave, num_link, chains:list[ChainInfo]}
- `ChainInfo`   ← FERS_TDL_ChainInfo_t {status, board_count, rrt, event_count, byte_count, event_rate, mbps}
- `SpectEvent`  ← SpectEvent_t  {tstamp_us, rel_tstamp_us, tstamp_clk, tref_tstamp, trigger_id, chmask, qdmask, energy_hg:u16[64], energy_lg:u16[64], toa:u32[64] (from .tstamp), tot:u16[64]}
- `CountingEvent` ← CountingEvent_t {tstamp_us, rel_tstamp_us, trigger_id, chmask, counts:u32[64], t_or_counts, q_or_counts}
- `WaveEvent`   ← WaveEvent_t   {tstamp_us, trigger_id, ns, wave_hg:u16[ns], wave_lg:u16[ns], dig_probes:u8[ns]}
- `ListEvent`   ← ListEvent_t   {tstamp_us, tref_tstamp, tstamp_clk, trigger_id, nhits, channel:u8[nhits], edge:u8[nhits], toa:u32[nhits] (from .tstamp), tot:u16[nhits]}
- `ServEvent`   ← ServEvent_t   {tstamp_us, update_time, pkt_size, version, format, ch_trg_cnt:u32[64], q_or_cnt, t_or_cnt, temp_fpga, temp_board, temp_tdc0, temp_tdc1, temp_hv, temp_detector, hv_vmon, hv_imon, hv_status_on, hv_status_ramp, hv_status_ovv, hv_status_ovc, status, tdc_ro_status, readout_flags, tot_trg_cnt, rej_trg_cnt, suppr_trg_cnt}
- `TestEvent`   ← TestEvent_t   {tstamp_us, trigger_id, nwords, test_data:u32[nwords]}
Read `MAX_LIST_SIZE`, `MAX_TEST_NWORDS` from FERSlib.h; copy only valid prefixes (nhits/nwords/ns).

### Module constants (exposed as m.attr)
```
CFG_HARD=0, CFG_SOFT=1
ROMODE_DISABLE_SORTING=0x0000, ROMODE_TRGTIME_SORTING=0x0001, ROMODE_TRGID_SORTING=0x0002
START_ASYNC=0, START_TDL=0x11, START_TDL_EXTRUN=0x12, START_TDL_EXTRUN_EXTCLK=0x13,
START_TDL_EXTCLK=0x14, START_TDL_GPS=0x16, START_CHAIN_T0=4, START_CHAIN_T1=5
DTQ_SPECT=0x01, DTQ_TIMING=0x02, DTQ_COUNT=0x04, DTQ_WAVE=0x08, DTQ_SERVICE=0x2F, DTQ_TEST=0xFF
RAWDATA_REPROCESS_FINISHED=4
```

### Functions (names mirror FERSlib.h, de-prefixed + snake_case)
```
# device & info
open_device(path:str) -> int                       # FERS_OpenDevice
close_device(handle:int) -> None                    # FERS_CloseDevice
is_open(path:str) -> bool                           # FERS_IsOpen
get_num_boards_connected() -> int                   # FERS_GetNumBrdConnected
get_board_info(handle:int) -> BoardInfo             # FERS_GetBoardInfo
get_cnc_info(handle:int) -> CncInfo                 # FERS_GetCncInfo
get_clock_period(handle:int) -> float               # FERS_GetClockPeriod
reset_ip_address(handle:int) -> None                # FERS_Reset_IPaddress
get_last_error() -> str                             # FERS_GetLastError
lib_release() -> str                                # FERS_GetLibReleaseNum
# config (string-based, kept verbatim)
load_config_file(path:str) -> None                  # FERS_LoadConfigFile
set_param(handle:int, name:str, value:str) -> None  # FERS_SetParam
get_param(handle:int, name:str) -> str              # FERS_GetParam (buf 1024)
configure(handle:int, mode:int) -> None             # FERS_configure
# tdl
init_tdl_chains(handle:int, delay_adjust:np.ndarray[8,16] f32) -> None   # FERS_InitTDLchains
enum_tdl_chains(handle:int) -> np.ndarray[8,16] f32 # FERS_EnumTDLchains
sync_tdl_chains(handles:list[int], start_mode:int) -> None              # FERS_SyncTDLchains
tdl_chains_initialized(handle:int) -> bool          # FERS_TDLchainsInitialized
# readout
init_readout(handle:int, ro_mode:int) -> int        # FERS_InitReadout (returns allocated_size)
close_readout(handle:int) -> None                   # FERS_CloseReadout
flush_data(handle:int) -> None                      # FERS_FlushData
# acquisition
start_acquisition(handles:list[int], start_mode:int, run_num:int) -> None   # FERS_StartAcquisition
stop_acquisition(handles:list[int], start_mode:int, run_num:int) -> None    # FERS_StopAcquisition
get_event(handles:list[int]) -> tuple[int,int,object] | None
    # Wraps FERS_GetEvent(int* handle, &bindex, &dtq, &tstamp_us, &Event, &nb).
    # Returns None if nb==0. Else returns (board:int, dtq:int, event) where `event` is one of the
    # bound struct objects above chosen by (dtq & 0xF) / dtq==0x2F service. Raises FERSError if ret<0.
    # If ret==RAWDATA_REPROCESS_FINISHED, return (-1, RAWDATA_REPROCESS_FINISHED, None).
drain_events(handles:list[int], max_events:int) -> list[tuple[int,int,object]]
    # DATA-PLANE primitive: loops FERS_GetEvent in C up to max_events or until nb==0, collecting
    # (board,dtq,event). Reduces per-event Python call overhead. Clearly a convenience over get_event.
# registers & commands
read_register(handle:int, address:int) -> int       # FERS_ReadRegister
write_register(handle:int, address:int, data:int) -> None
write_register_slice(handle:int, address:int, start_bit:int, stop_bit:int, data:int) -> None
send_command(handle:int, cmd:int) -> None            # FERS_SendCommand
# HV
hv_init(handle:int) -> None
hv_set_onoff(handle:int, on:bool) -> None
hv_get_status(handle:int) -> tuple[int,int,int,int]  # (on, ramping, ovc, ovv)
hv_set_vbias(handle:int, vbias:float) -> None
hv_get_vbias(handle:int) -> float
hv_get_vmon(handle:int) -> float
hv_set_imax(handle:int, imax:float) -> None
hv_get_imon(handle:int) -> float
hv_get_int_temp(handle:int) -> float
hv_get_detector_temp(handle:int) -> float
# temperatures
get_fpga_temp(handle:int) -> float
get_board_temp(handle:int) -> float
```

---

## 1b. `pyfers` — pythonic SDK (src/pyfers/)

Pure-Python package over `pyferslib`. This is where C-dictated design is fixed: OOP board access,
enums instead of magic ints, properties instead of string set_param, typed events, context managers,
exceptions. Imports `pyferslib` ONLY.

Files: `src/pyfers/__init__.py`, `enums.py`, `errors.py`, `events.py`, `board.py`, `system.py`.

### Enums (`pyfers.enums`)
Mirror the option lists in docs/param_defs_reference.txt as `enum.Enum`, each member carrying the
ferslib string value so it can be passed to set_param. At minimum:
`AcqMode` (SPECTROSCOPY, SPECT_TIMING, TIMING_CSTART, TIMING_CSTOP, COUNTING, WAVEFORM),
`StartMode` (ASYNC, TDL, TDL_EXTRUN, TDL_GPS, CHAIN_T0, CHAIN_T1 — each also maps to a pyferslib.START_* int),
`SortMode` (DISABLED→ROMODE_DISABLE_SORTING, TRGTIME→TRGTIME_SORTING, TRGID→TRGID_SORTING),
`StopMode` (MANUAL, PRESET_TIME, PRESET_COUNTS), `GainSelect` (HIGH, LOW, AUTO, BOTH).
Provide helpers: `StartMode.to_ferslib_int()`, `SortMode.to_romode()`.

### Errors (`pyfers.errors`)
Re-export `FERSError` from pyferslib; add `ConfigError(ValueError)`.

### Typed events (`pyfers.events`)
Lightweight dataclasses wrapping the pyferslib struct objects for ergonomic, documented access:
`SpectEvent, CountingEvent, WaveEvent, ListEvent, ServiceEvent, TestEvent`, each with a
`from_raw(board:int, raw)` classmethod and `.board`, `.dtq`, `.tstamp_us` plus numpy fields.
`decode(board, dtq, raw) -> one of the above`. (NB: the engine data-plane does NOT have to go
through these — it may consume pyferslib structs directly; these are for interactive/SDK users.)

### `pyfers.board.Board`
```python
class Board:
    def __init__(self, path:str): ...        # does not open yet
    @property handle:int                      # valid after open()
    @property info: BoardInfo                 # cached pyferslib BoardInfo (pythonic attrs)
    @property is_open:bool
    hv: "HV"                                  # sub-object (see below)
    def open(self) -> "Board"
    def close(self) -> None
    def init_readout(self, sort:SortMode=SortMode.DISABLED) -> None
    def configure(self, mode:str="hard") -> None     # pyferslib.configure CFG_HARD/CFG_SOFT
    def set_param(self, name:str, value:str) -> None  # escape hatch to the string API
    def get_param(self, name:str) -> str
    def read_register(self, address:int) -> int
    def write_register(self, address:int, value:int) -> None
    def __enter__/__exit__                      # context manager -> open()/close()

class HV:    # bound to a Board; properties translate to pyferslib hv_* calls
    on: bool            # get via hv_get_status, set via hv_set_onoff
    vbias: float        # hv_get_vbias / hv_set_vbias
    imax: float         # hv_set_imax
    vmon: float (ro)    # hv_get_vmon
    imon: float (ro)    # hv_get_imon
    status: dict (ro)   # {on,ramping,ovc,ovv}
    int_temp: float (ro); detector_temp: float (ro)
    def init(self) -> None
```

### `pyfers.system.System`  (multi-board + concentrator orchestration)
```python
class System:
    def __init__(self, boards:list[Board]): ...
    @classmethod
    def open(cls, *paths:str) -> "System"        # open all
    @classmethod
    def from_config(cls, cfg) -> "System"        # paths from a hydrafers.config.HydraConfig (duck-typed: cfg with .boards paths)
    @property boards: list[Board]
    @property handles: list[int]                  # for the engine data-plane (pyferslib.drain_events)
    def configure(self, params:Iterable[tuple[int,str,str]], mode:str="hard") -> None
        # params = (board_index, name, value) tuples (e.g. from cfg.to_ferslib_params()); applies via set_param then configure
    def start_run(self, start_mode:StartMode=StartMode.ASYNC, run_number:int=0) -> None
    def stop_run(self, start_mode:StartMode=StartMode.ASYNC, run_number:int=0) -> None
    def events(self, max_batch:int=256) -> Iterator[events.*]   # yields typed events (uses pyferslib.drain_events)
    def flush(self) -> None
    def close(self) -> None
    def __enter__/__exit__
```
`pyfers` must be usable standalone (an SDK): `with pyfers.System.open("eth:...") as s: s.boards[0].hv.vbias = 62.5`.

---

## 2. `hydrafers.config` — configuration layer (UNCHANGED from prior contract; pure Python)

YAML on-disk, single shareable file, pydantic v2 validation. Public API:
```python
from hydrafers.config import HydraConfig, load_config, save_config, convert_janus_txt, default_config
```
`HydraConfig` mirrors docs/param_defs_reference.txt (sections, scope g/b/c, combo validation,
unit-strings kept verbatim). Methods:
- `to_ferslib_params() -> list[tuple[int,str,str]]`  (board_index, ferslib_param_name, value_str) — fed to `System.configure`.
- `to_legacy_txt() -> str`  (the Janus_Config.txt format, docs/janus_config_example.txt).
- `board_paths() -> list[str]` (connection strings, for `System.from_config`).
Ship `src/hydrafers/config/default.yaml`. Imports NOTHING from pyferslib/pyfers.

---

## 3. `hydrafers.io` — output file layer (pure Python; numpy; NO pyferslib/pyfers import)

```python
from hydrafers.io import EventWriter, EventReader, FileHeader
```
The writer/reader operate on a **neutral event representation = a plain dict** (so io stays decoupled
from pyferslib). The engine's WriterThread extracts fields from pyferslib event objects into this dict.
Dict keys per mode mirror the struct fields in §1a (snake_case, numpy arrays), e.g. spect:
`{'board','dtq','tstamp_us','trigger_id','chmask','energy_hg','energy_lg','toa','tot'}`.
```python
class EventWriter:                 # buffered (default 4 MiB), large sequential writes, thread-friendly
    def __init__(self, path, header:FileHeader, buffer_bytes:int=4*1024*1024)
    def write_event(self, event:dict) -> None
    def flush(self) -> None ; def close(self) -> None
class EventReader:                 # reads new HydraFERS format AND legacy Janus list .dat
    def __init__(self, path)
    def header(self) -> FileHeader
    def __iter__(self) -> Iterator[dict]
@dataclass
class FileHeader:
    format_version:int; acquisition_mode:str; energy_nbins:int; toa_lsb_ns:float
    start_time:int; board_model:str
```
New format: length-prefixed JSON header (magic bytes to distinguish from legacy) + length-prefixed
binary event records, format_version=1. Legacy reader follows janus-5202/src/outputfiles.c
(WriteListfileHeader). Document the byte layout in docs/FILE_FORMAT.md.

---

## 4. `hydrafers.core` — acquisition engine (NO UI logic)

Public API (UNCHANGED names from prior contract):
```python
from hydrafers.core import AcquisitionEngine, AcqState, BoardStatus, RunStatistics
```
`AcqState`: DISCONNECTED=0, CONNECTING=1, READY=2, STARTING=3, RUNNING=4, STOPPING=5, EMPTYING=6, ERROR=-1, UPGRADING_FW=7.
`BoardStatus`: index, handle, pid, model_name, fpga_fw, connected, temp_fpga, temp_board, temp_hv, temp_detector, hv_on, hv_vmon, hv_imon, status_reg.
`RunStatistics`: run_number, elapsed_s, total_events, event_rate_hz, byte_count, data_rate_mbps, built_events, per_board:dict, ch_trg_rate:np.ndarray[nb,64], ch_count:np.ndarray[nb,64], dropped_events:int.

```python
class AcquisitionEngine:
    def __init__(self, config:HydraConfig|None=None)
    # lifecycle
    def connect(self) -> None          # builds pyfers.System.from_config; open; init_readout; configure; hv init
    def disconnect(self) -> None
    def configure(self, config:HydraConfig, soft:bool=False) -> None
    def start_run(self, run_number:int|None=None) -> None
    def stop_run(self) -> None
    def close(self) -> None            # safe from atexit
    # snapshots (thread-safe copies)
    @property state:AcqState
    def board_status(self) -> list[BoardStatus]
    def statistics(self) -> RunStatistics
    def histograms(self) -> dict        # {'e_spec_hg':ndarray[nb,64,nbins], 'toa':..., 'mcs':..., 'cnt_2d':...}
    # live subscription
    def stats_queue(self) -> queue.Queue        # RunStatistics snapshots ~15 Hz
    # HV / registers
    def hv_set(self, board_index:int, on:bool, vbias:float|None=None, imax:float|None=None) -> None
    def hv_status(self, board_index:int) -> dict
    def read_register(self, board_index:int, address:int) -> int
    def write_register(self, board_index:int, address:int, value:int) -> None
    # observers (called from engine threads; frontends must marshal to their loop)
    on_state_change: Callable[[AcqState],None] | None
    on_error: Callable[[str],None] | None
    on_log: Callable[[str,str],None] | None     # (level, message)
```

### Threading model — uses BOTH layers per their plane
- The engine holds a `pyfers.System` for the **control-plane**: connect/configure/start/stop/HV/registers
  go through `pyfers` (ergonomic, low-frequency).
- **ReadoutThread** (core/readout.py): tight loop calling `pyferslib.drain_events(system.handles, N)`
  (DATA-plane, direct to the faithful binding for minimal per-event overhead); pushes the returned
  (board,dtq,event) tuples into a bounded queue. Does NOTHING else — no disk, no stats, no decode.
- **WriterThread** (core/writer.py): drains the queue, extracts fields from each pyferslib event object
  into the neutral dict (§3), hands to `hydrafers.io.EventWriter` (buffered, large sequential writes).
- **StatsThread** (core/statistics.py): consumes a throttled tap (counters/sampled events), recomputes
  RunStatistics + histograms at ~15 Hz, pushes snapshots to `stats_queue()`. Never blocks readout.
- **ServiceThread** (or folded into stats): periodically reads HV/temps via the `pyfers` System when not
  running, for the monitoring panel.
- NO `Sleep()` busy-polling — use queue timeouts / `threading.Event`. Guard shared state with locks;
  return immutable snapshot copies. Map config StartMode→StartMode enum, StopMode, EventBuildingMode→SortMode.

---

## 5. `hydrafers.cli` — headless/TUI frontend (imports core+config ONLY)
```
cli/app.py       : Textual TUI (board tree, live stats table, sparklines, start/stop, state)
cli/batch.py     : argparse runner: run(--config --duration|--counts --output --run-number),
                   benchmark(--config --duration -> events/s, MB/s, drops), convert-config, tui
cli/__main__.py  : def main(): dispatch; entry point hydrafers-cli
```
Subscribes to engine.stats_queue(); Rich for plain output; Ctrl-C stops run + closes engine cleanly.

## 6. `hydrafers.gui` — PySide6 desktop frontend (PySide6 + pyqtgraph; NO gnuplot/tkinter)
Style target = CAEN Web Interface (sidebar + device tree + status tables + LEDs; see screenshots_gui/).
```
gui/main_window.py : QMainWindow; left sidebar nav + central QStackedWidget pages
gui/style.qss      : professional dark/neutral theme
gui/widgets/       : sidebar.py, device_tree.py, status_table.py, led.py, stat_panel.py,
                     config_editor.py (form from HydraConfig schema; load/save the YAML),
                     hv_panel.py, register_panel.py, log_panel.py
gui/plots/         : spectrum.py (PHA/ToA/ToT), map2d.py (rate/charge), mcs.py (counts vs time)
gui/__main__.py    : def main(): QApplication, load style.qss, MainWindow; entry hydrafers-gui
```
Owns an AcquisitionEngine; polls engine.stats_queue() via a QTimer (~15 Hz); wraps engine observers
into Qt signals (never touch widgets directly from engine threads).

## 7. Build system (CMake, Visual Studio-compatible)
```
CMakeLists.txt    : builds ferslib (native/ferslib, SOURCE UNCHANGED) then the pybind11 module
                    `pyferslib` (native/bindings/pyferslib.cpp) linking it. MSVC supported;
                    `cmake -G "Visual Studio 17 2022"` must work.
CMakePresets.json : VS + Ninja + mingw presets.
pyproject.toml    : scikit-build-core backend; installs the compiled `pyferslib` module AND the pure
                    Python packages `pyfers` and `hydrafers` (src-layout). console_scripts:
                    hydrafers-gui = hydrafers.gui.__main__:main ; hydrafers-cli = hydrafers.cli.__main__:main.
                    deps: numpy, pydantic>=2, pyyaml; extras [gui]=PySide6,pyqtgraph ; [cli]=textual,rich.
cmake/            : mingw-shims + mingw-toolchain.cmake (already vendored).
```
Base on the proven pyferslib/CMakeLists.txt + pyproject.toml. CMake only (no meson).

## 8. Conventions
snake_case funcs, PascalCase classes, UPPER constants; type hints everywhere; dataclasses for plain
data; pydantic only in config. ferslib param names/values used VERBATIM as strings. No global mutable
state in core. Module docstrings stating role + layer. stdlib `logging` (logger `hydrafers.<mod>` /
`pyfers.<mod>`); engine routes user-facing messages via on_log. No `print` in library code.
