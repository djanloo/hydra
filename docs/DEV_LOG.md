# HydraFERS — dev log

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

### Status — TODO
- **Build + hardware**: compile `pyferslib` with **MSVC** (MinGW is discouraged —
  breaks the build), then validate on real 5202/5203. The 5202 comm is broken;
  debug when hardware is attached.
- Optional/nice-to-have: CLI/TUI (`textual`/`rich`) 5203 awareness; `extras` not
  installed. Live GUI run against real data once a binding is built.

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
