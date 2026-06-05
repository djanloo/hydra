# HydraFERS

Modern renewal of the CAEN FERS / Janus DAQ software.

Replaces the old two-process design (Python tkinter GUI + JanusC.exe over a TCP socket)
with a **single multithreaded Python application** that drives the unchanged `ferslib` C
library through the `pyfers` pybind11 extension module.

```
 +--------------------------------------------------------------+
 |                  HydraFERS (single Python app)               |
 |   +----------------+  stats queue / callbacks  +----------+  |
 |   | AcquisitionEng | ------------------------> | Frontend |  |
 |   | readout/writer | <------- commands -------- | GUI/CLI  |  |
 |   | /stats threads |                            +----------+  |
 |   +-------+--------+                                         |
 |           | pyfers (GIL released in C calls)                 |
 +-----------+--------------------------------------------------+
        +-----v-----+
        |  ferslib  |  <- UNCHANGED (vendored in native/ferslib)
        +-----+-----+
        [ FERS hardware (DT5202 / DT5203 / DT5204) ]
```

---

## Requirements

### Hardware / OS

| Item | Minimum |
|---|---|
| OS | Windows 10/11 x64 or Linux x86_64 |
| Python | 3.10+ |
| CMake | 3.16+ |
| C++ compiler | MSVC 2019/2022, GCC 10+, Clang 12+ |
| Hardware | CAEN FERS DT5202 / DT5203 / DT5204 connected via Ethernet, USB, or TDLink |

### Python runtime dependencies

| Package | Required for |
|---|---|
| `numpy >= 1.24` | Core event data arrays (always needed) |
| `pydantic >= 2` | Configuration validation (always needed) |
| `pyyaml >= 6` | Config file load/save (always needed) |
| `PySide6 >= 6.5` | Qt6 GUI — install via `pip install hydrafers[gui]` |
| `pyqtgraph >= 0.13` | Embedded plots in GUI — same extra |
| `textual >= 0.50` | TUI interactive mode — install via `pip install hydrafers[cli]` |
| `rich >= 13` | Formatted terminal output — same extra |

**Base install** (no GUI, no TUI) is sufficient for batch / headless operation:

```
pip install hydrafers
```

**GUI desktop install:**

```
pip install "hydrafers[gui]"
```

**TUI / CLI interactive install:**

```
pip install "hydrafers[cli]"
```

**Everything:**

```
pip install "hydrafers[all]"
```

---

## Building the native extension (`pyfers`)

`pyfers` is the pybind11 module that bridges Python to `ferslib`.
It is compiled from `native/bindings/pyfers.cpp` against the frozen ferslib sources in
`native/ferslib/`.

### Option A — pip (recommended for end users)

```
# From the HydraFERS/ directory:
pip install .
# or with GUI extras:
pip install ".[gui]"
```

`scikit-build-core` drives CMake automatically, builds `pyfers`, and installs everything
into your active environment in a single step.

### Option B — cmake --preset (recommended for developers)

Three presets are provided in `CMakePresets.json`:

| Preset | Generator | Use case |
|---|---|---|
| `vs2022` | Visual Studio 17 2022 x64 | Open `build-vs/hydrafers.sln` in VS for debugging |
| `ninja-release` | Ninja | Fast command-line build (MSVC, clang-cl, or GCC) |
| `mingw` | Ninja + MinGW toolchain | Cross-compile / native MinGW build |

```
# VS 2022 solution (open build-vs/hydrafers.sln in Visual Studio):
cmake --preset vs2022
cmake --build --preset vs2022

# Ninja (uses whatever compiler CMake finds on PATH):
cmake --preset ninja-release
cmake --build --preset ninja-release

# MinGW cross / native:
cmake --preset mingw
cmake --build --preset mingw
```

After building, the `pyfers` module ends up in the corresponding `build-*/` directory.
To make `import pyfers` work without installing, add that directory to `PYTHONPATH`:

```
# PowerShell example:
$env:PYTHONPATH = "$PWD\build\;$env:PYTHONPATH"
python -c "import pyfers; print(pyfers.lib_release())"
```

### Option C — cmake -G "Visual Studio 17 2022" (explicit generator)

```
cmake -S . -B build-manual -G "Visual Studio 17 2022" -A x64
cmake --build build-manual --config Release
```

---

## Running

### GUI (Qt6 desktop application)

```
hydrafers-gui                        # entry point installed by pip
# or
python -m hydrafers.gui              # directly from source
```

The GUI opens a PySide6 window with a sidebar, device tree, status/monitoring panels,
live pyqtgraph plots (PHA spectrum, ToA/ToT, MCS, 2D rate map), config editor, HV
control, and register access panel.

Load a YAML config file via File > Open Config, connect to your boards, then click Start.

### CLI — interactive TUI (Textual)

```
hydrafers-cli                        # opens the Textual TUI
# or
python -m hydrafers.cli
```

The TUI shows a live stats dashboard, board status tree, and start/stop controls in the
terminal.

### CLI — headless batch mode

```
# Run for 1 hour, save data, run number 12:
hydrafers-cli run --config run.yaml --duration 3600 --output ./data --run-number 12

# Stop after 1 000 000 events:
hydrafers-cli run --config run.yaml --counts 1000000 --output ./data

# 30-second throughput benchmark (events/s, MB/s, dropped events):
hydrafers-cli benchmark --config run.yaml --duration 30

# Convert a legacy Janus_Config.txt to modern YAML:
hydrafers-cli convert-config old_Janus_Config.txt new.yaml
```

Batch mode exits with code 0 on success, non-zero on error, suitable for scripts and
scheduled jobs.

---

## Configuration

HydraFERS uses **YAML** as its on-disk format. A single file captures the full
configuration (global parameters, per-board overrides, per-channel arrays).

```yaml
# Example: run.yaml
boards:
  - Open: "eth:192.168.50.3"
    HV_Vbias: "62.5 V"
    HV_Imax: "10.0 mA"

AcquisitionMode: "Spectroscopy"
RunNumber: 0
...
```

Parameter names are kept identical to `ferslib` parameter names (from
`docs/param_defs_reference.txt`) because they are passed verbatim to `pyfers.set_param`.

To migrate a legacy `Janus_Config.txt`:

```
hydrafers-cli convert-config Janus_Config.txt my_config.yaml
```

---

## Project layout

```
HydraFERS/
+-- CMakeLists.txt          # top-level CMake; builds ferslib (static) + pyfers module
+-- CMakePresets.json       # VS 2022 / Ninja / MinGW presets
+-- pyproject.toml          # scikit-build-core + package metadata + entry points
+-- README.md               # this file
+-- .gitignore
+-- cmake/
|   +-- mingw-toolchain.cmake   # MinGW cross-compile toolchain
|   +-- mingw-shims/            # case-sensitivity header shims for MinGW
+-- native/
|   +-- ferslib/            # FROZEN ferslib source (do not modify)
|   |   +-- src/            # .c / .cpp sources
|   |   +-- include/        # FERSlib.h and friends
|   +-- bindings/
|       +-- pyfers.cpp      # pybind11 module source
+-- src/
|   +-- hydrafers/          # Python package (src-layout)
|       +-- config/         # YAML config, pydantic models, legacy converter
|       +-- io/             # EventWriter / EventReader
|       +-- core/           # AcquisitionEngine + threads (readout/writer/stats)
|       +-- cli/            # Textual TUI + batch runner
|       +-- gui/            # PySide6 GUI + pyqtgraph plots
|       +-- resources/      # QSS stylesheet, icons, default.yaml
+-- docs/
|   +-- CONTRACT.md         # binding interface contract (ground truth)
|   +-- param_defs_reference.txt
|   +-- janus_config_example.txt
+-- tests/
    +-- ...                 # pytest test suite
```

---

## Architecture overview

The key architectural decision is the strict separation of the **Acquisition Engine**
(no UI logic) from the **frontends** (GUI and CLI), connected by thread-safe queues:

- **ReadoutThread**: tight loop calling `pyfers.get_event(handles)`, pushes raw event
  dicts into a bounded `queue.Queue`. GIL is released inside the ferslib C call, so this
  loop achieves near-native throughput.
- **WriterThread**: drains the event queue and calls `hydrafers.io.EventWriter` (large
  sequential writes, buffered). Disk I/O never stalls readout.
- **StatsThread**: recomputes `RunStatistics` and histograms at 10-20 Hz, pushes
  snapshots to `stats_queue()`. Never blocks readout.
- **Frontend** (GUI or CLI): polls `stats_queue()` at display rate (~15 Hz), never
  touches ferslib directly.

This eliminates the bandwidth penalty of the old single-threaded JanusC main loop, where
readout, statistics, disk writes, and gnuplot calls were all serialized in one cycle.

---

## Build system notes

CMake is the single build system for all native code. It is used both as:

- A command-line / CI build tool (via `cmake --preset ...`).
- A Visual Studio solution generator (`cmake -G "Visual Studio 17 2022"`).
- The CMake backend driven by `scikit-build-core` when running `pip install`.

The `meson.build` from the predecessor project is NOT present here; CMake was chosen as
the single build system to reduce maintenance overhead (one build system, not two).

ferslib is compiled as a **static library** so that the `pyfers` wheel is self-contained
on Windows (no separate `ferslib.dll` to distribute).

---

## License

ferslib is distributed under the GNU General Public License v2.
HydraFERS Python code is distributed under the same GPL-2.0-or-later terms.
See `native/ferslib/` for the original CAEN ferslib license notice.
