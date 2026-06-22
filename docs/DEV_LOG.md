# HydraFERS — dev log

## ferslib upgrade 1.3.0 → 2.2.0 (2026-06-22)

Vendored ferslib bumped from a hybrid 1.3.0 snapshot to **release/v2.2.0** (latest
release line; `main`=2.0.0, tags stop at v2.0.0-beta). Sources pulled from
`gitlab.caen.it/fers/software/ferslib.git`. File list identical to vendored (12 src
+ 9 include) → no CMake source-list change. Verified raw connect to a real **A5203**
(`eth:192.168.50.3`) + `pyfers.System` (family/has_hv/init_readout) + **90 tests green**.

- **Binding port** ([native/bindings/pyferslib.cpp](../native/bindings/pyferslib.cpp)):
  - `ServEvent_t` was split upstream into `ServEvent5202_t`/`5203_t`/`5204_t` (different
    field subsets). Kept ONE stable Python `ServEvent` wrapper, populated per-family via
    `from_5202`/`from_5203`/`from_5204`; absent fields read 0. `build_event` now takes the
    board `fers_code`, resolved once per batch from `handles[0]` (homogeneous system) via
    a cached `FERS_GetBoardInfo`.
  - TDL: `FERS_InitTDLchains` → `FERS_EnumTDLchains` (renamed `enum_tdl_chains`); added
    `sync_tdl_chains` (`FERS_SyncTDLchains`). pyfers SDK didn't use the old name, so no
    Python breakage.
  - Fixed a latent bug: `ListEvent` ToA is read from `tstamp[]` for 5202 but `ToA[]` for
    5203 (pre-2.2.0 always read `tstamp` → zero ToA on 5203). Added 5204 List/Counting
    variants too.
- **Build flags** ([CMakeLists.txt](../CMakeLists.txt)), matching how CAEN ships it (janus
  .vcxproj): `UNICODE`/`_UNICODE` on the ferslib target (the non-UNICODE branches, e.g.
  FERS_LLusb.cpp USB enum, are stale and don't compile), and `/FIstdbool.h` on MSVC
  (2.2.0 commented out `#include FERS_MultiPlatform.h` and guards `<stdbool.h>` behind
  `#ifndef WIN32`, so FERS_LLeth.c/FERS_LLtdl.c lose C `bool`). **No ferslib source was
  modified.** Public API is char*-based, so UNICODE doesn't change the binding boundary.
- Cross-checked the readout call order against janus-5203/5202: open → GetBoardInfo →
  (TDL enum/sync only for concentrators) → InitReadout → configure(CFG_HARD) →
  StartAcquisition → GetEvent. The engine already matches; no `FERS_PostConfigure` needed
  for direct Ethernet.
- **GPS param fixed by the upgrade:** `GPSPPSSource`/`GPSTimeUTC` (which broke GUI connect)
  were UNKNOWN to the 1.3.0 parser (→ -14) but ARE recognized by 2.2.0. Verified on the real
  5203.
- **Still open (separate config bug, NOT a lib issue):** `engine.connect()` still fails
  because `HydraConfig.to_ferslib_params()` forwards ~30 application-level pseudo-params that
  ferslib never accepted in ANY version. Probed live on the 5203 (`set_param` each, 2.2.0):
  rejected pseudo-params include `EventBuildingMode`, `TstampCoincWindow`/`TrgTimeWindow`,
  `PresetTime`/`PresetCounts`, the `Job*`/`EnableJobs`/`RunSleep`/`RunNumber_AutoIncr` run
  control, `DataFilePath`/`OF_*`/`DataAnalysis` output, and all histogram config
  (`EHistoNbin`/`ToAHistoNbin`/`LeadTrailHistoNbin`/`ToTHistoNbin`/`*Rebin`/`*HistoMin`/
  `MCSHistoNbin`), plus `EnableListZeroSuppr`/`EnableWalkCorrection`/`WalkFitCoeff`. These are
  Janus *app* settings the old JanusC consumed itself; the engine must split hardware params
  (→ set_param) from app params (consumed in `hydrafers.core`). NB ferslib labels -14 a
  "WARNING" and JanusC continues past it — pyferslib instead raises, making it fatal; the
  config split is the right fix, but relaxing set_param on -14 is an alternative to weigh.
  Also two genuine 5203 *value* mismatches [-26]: `DigitalProbe0='TRG_ACCEPTED'` and
  `DigitalProbe1='TX_DATA_VALID'` are not valid 5203 settings in 2.2.0 — default_5203.yaml
  needs updating.

---


> Running notes kept **inside the repo** (versioned) so they travel across
> machines via `git`. Claude updates and commits this each work session; it is
> the portable source of truth for "what's done / what's next". (Claude's own
> `~/.claude` memory is machine-local and does NOT sync — this file does.)

---

## A5203 (picoTDC) dual-board integration

Goal: one HydraFERS binary driving **both** the A5202 (SiPM, spectroscopy+timing,
64 ch, HV) and A5203 (picoTDC, timing-only, up to 128 ch, no HV). A run is always
**homogeneous** — ferslib forbids mixing families (see `A5203_INTEGRATION_STUDY.md`).
Branch: `feat/5203-integration`.

### User decisions
1. Never mixed boards on one setup → homogeneous-only (enforced at `System.open`).
2. `MeasMode` is per-board (global), not per-channel.
3. File: `REC_TIMING` carries an edge flag; keep the layout agile across tests.
4. No 5203 hardware yet (~2 days out); the 5202 comm is currently **broken**
   (debug both when hardware is connected). Develop against a pyferslib stub.
5. A5256 adapter must be supported (used ~90% of test-run time).

### Status — DONE (committed on the branch, 85 tests green)
- **pyfers SDK** (`f42600c`): `BoardFamily`, `AcqMode5203`/`MeasMode`,
  `Board.family/has_hv/fers_code`, `System.family` + mixed-fleet rejection.
- **config** (`5f6da44`): `BaseHydraConfig`; `HydraConfig` = A5202 (back-compat);
  `HydraConfig5203` + `Board5203Config` + picoTDC sections (TDC/DataAnalysis/
  Adapters, 128-ch masks, MeasMode, A5256 DiscrThreshold). Loader auto-detects
  `board_family`; converter render/parse + `detect_family` + lenient legacy
  import. **Verified converting the real janus-5202 and janus-5203 configs.**
  `default_5203.yaml` bundled.
- **core** (`09cf9d3`): `_BaseHistogramSet` + `HistogramSet` (A5202, param num_ch)
  + `HistogramSet5203` (lead/trail split by edge + ToT, 128 ch) +
  `make_histogram_set`. Engine `_board_family()`/`_resolve_num_ch()` +
  family-aware `_reindex_snapshots`; `StatsThread`/`RunStatistics` take num_ch.
- **io** (`95902f3`): `FileHeader` v2 self-describing (`board_family`/`num_ch`/
  `meas_mode`); `FORMAT_VERSION=2`; v1 files still read. `REC_TIMING` already
  stored per-hit `channel(u8)/edge(u8)/toa(u32)/tot(u16)` → 5203 round-trips with
  no new record type.
- **gui plots** (`f8b4c57`): `sources_for_family` (5202 energy / 5203 Lead/Trail/
  ToT); `Map2DPlot` grid adapts (64→8×8, 128→8×16); fixed a pre-existing
  `update_counts` crash. Validated offscreen.

- **gui family-aware tabs** (`68ab579`): conditional tabs (chosen over a device
  tree — runs are homogeneous). config_form gained the A5203 section tables
  (Acquisition/TDC/DataAnalysis/Adapters/RunCtrl/Output) + per-family helpers;
  ChannelArrayDialog/BoardParams/BoardScopeForm parameterized (64/128 ch, float
  DiscrThreshold). main_window: `_family`/`_num_ch` drive the settings tabs,
  per-channel grid, spectra sources, map geometry, registers and HV page (5203
  shows a "no HV" note); `_collect_config` builds the family's classes; loading
  a different-family config rebuilds the stack. Validated offscreen.
- **gui Connect page** (`5b5402c`): removed the per-board enable checkbox — a row
  with a non-empty path is a board.

### Build — DONE on this machine (MSVC)
`pyferslib` compiles and installs with **MSVC (VS 2022 Community)**; the full
test suite (90) passes against the **real** compiled binding, not the stub.

Recipe (Windows, from `hydra/`, MinGW is discouraged — force `cl`):
```
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
set CC=cl & set CXX=cl
..\hydravenv\Scripts\python.exe -m pip wheel . --no-deps -w dist -v   # build the wheel
..\hydravenv\Scripts\python.exe -m pip install --force-reinstall --no-deps dist\hydrafers-*.whl
```
Notes: forcing `CC/CXX=cl` keeps CMake from picking the Strawberry-Perl gcc on
PATH. Produces `hydrafers-0.0.6-cp314-cp314-win_amd64.whl`; installs the
`pyferslib.cp314-win_amd64.pyd` module + `pyfers`/`hydrafers` packages and the
`hydrafers` / `hydrafers-gui` / `hydrafers-cli` / `hydrafers-tui` entry points.
The dev `build-debug/pyferslib.py` stub is only needed on a machine WITHOUT a
built binding (it's gitignored); delete it once the real `.pyd` is installed so
pytest uses the real module.

### Status — TODO
- **Hardware validation**: run on real 5202/5203. The 5202 comm is broken;
  debug when hardware is attached.
- Optional/nice-to-have: CLI/TUI (`textual`/`rich`) 5203 awareness; `extras` not
  installed. Live GUI run against real data once hardware is connected.

### Dev environment (this machine)
- Python **3.14** in `../hydravenv` (was empty; now has pydantic, numpy, pyyaml,
  pytest, PySide6 6.11.1, pyqtgraph).
- Build tools present: CMake 3.29, Ninja, git, MinGW gcc 13.2, `Python.h`.
  **Missing for the build**: MSVC `cl` (install VS Build Tools 2022, "Desktop
  development with C++"), plus pip backends `scikit-build-core` + `pybind11`.
- Dev-only `build-debug/pyferslib.py` is a pure-Python stub (gitignored) exposing
  the real FERSlib.h constants so the SDK/app import & test without the compiled
  extension. Delete it once a real binding is built locally.
- Run tests: `QT_QPA_PLATFORM=offscreen python -m pytest tests/ -q`
  (GUI tests skip if PySide6 is absent).
