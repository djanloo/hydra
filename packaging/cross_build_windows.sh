#!/usr/bin/env bash
# EXPERIMENTAL: cross-compile the pyferslib.pyd Windows extension from Linux with
# mingw-w64. This builds ONLY the compiled module — it does NOT (and cannot)
# produce the GUI .exe, because PyInstaller does not cross-compile. Use it to get
# a Windows wheel/.pyd; for the actual app build on Windows (build_windows.bat) or
# the GitHub Actions windows runner.
#
# Caveats (read before trusting the output):
#   * The module is MinGW/GCC-built and links msvcrt.dll, while CPython on Windows
#     uses the UCRT — mixing CRTs is unofficial and must be runtime-tested on a
#     real Windows box. Don't pass FILE*/CRT objects across the boundary.
#   * It depends on libgcc_s_seh-1.dll and libstdc++-6.dll (copied next to the
#     output here) unless you make them fully static.
#
# Prerequisites (Debian/Ubuntu):
#   sudo apt-get install -y gcc-mingw-w64-x86-64 g++-mingw-w64-x86-64 \
#                           mingw-w64-tools cmake make curl unzip
#
# Usage:  packaging/cross_build_windows.sh [PYVER]   (default 3.12.7)
set -euo pipefail

PYVER="${1:-3.12.7}"
PYTAG="${PYVER%.*}"                  # 3.12
PYNODOT="${PYTAG/./}"                # 312
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-$HOME/.venvs/caen/bin/python}"
WORK="/tmp/hydra-winpy-$PYNODOT"
OUT="$ROOT/build-win"
PREFIX=x86_64-w64-mingw32

echo "==> mingw toolchain: $($PREFIX-g++ --version | head -1)"

# --- 1. Windows CPython headers + import library (from the NuGet package) ------
mkdir -p "$WORK"
if [ ! -f "$WORK/pkg/tools/python$PYNODOT.dll" ]; then
    echo "==> downloading Windows CPython $PYVER (NuGet)…"
    curl -fsSL -o "$WORK/python.nupkg" \
        "https://www.nuget.org/api/v2/package/python/$PYVER"
    unzip -o -q "$WORK/python.nupkg" -d "$WORK/pkg"
fi
WINC="$WORK/pkg/tools/include"

# --- 2. mingw import library from the DLL -------------------------------------
mkdir -p "$WORK/imp"
if [ ! -f "$WORK/imp/libpython$PYNODOT.dll.a" ]; then
    echo "==> generating libpython$PYNODOT.dll.a…"
    ( cd "$WORK/imp"
      gendef "../pkg/tools/python$PYNODOT.dll" >/dev/null
      $PREFIX-dlltool -d "python$PYNODOT.def" -l "libpython$PYNODOT.dll.a" \
          -D "python$PYNODOT.dll" )
fi
WLIB="$WORK/imp/libpython$PYNODOT.dll.a"

# --- 3. empty stub libs so the leaked Linux -ldl/-lutil resolve to nothing -----
mkdir -p "$WORK/stub"
$PREFIX-ar crs "$WORK/stub/libdl.a"
$PREFIX-ar crs "$WORK/stub/libutil.a"

# --- 4. configure + build ------------------------------------------------------
PB="$("$PYTHON" -c 'import pybind11; print(pybind11.get_cmake_dir())')"
echo "==> configuring (pybind11 at $PB)…"
rm -rf "$OUT"
cmake -S "$ROOT" -B "$OUT" -G "Unix Makefiles" \
    -DCMAKE_TOOLCHAIN_FILE="$ROOT/packaging/mingw-w64-toolchain.cmake" \
    -DCMAKE_BUILD_TYPE=Release \
    -Dpybind11_DIR="$PB" -DPYBIND11_FINDPYTHON=ON \
    -DPython_INCLUDE_DIR="$WINC" -DPython_LIBRARY="$WLIB" -DPython_VERSION="$PYVER" \
    -DPYTHON_MODULE_EXTENSION=.pyd \
    -DCMAKE_MODULE_LINKER_FLAGS="-L$WORK/stub" \
    -DCMAKE_SHARED_LINKER_FLAGS="-L$WORK/stub"
    # NOTE: _CAEN_FERS_EXPORT is now set on the pyferslib target in CMakeLists.txt,
    # so it no longer needs to be forced here.
cmake --build "$OUT" --target pyferslib -- -j"$(nproc)"

# --- 5. copy the GCC/C++ runtime DLLs next to the module ----------------------
GCCDIR="$(dirname "$($PREFIX-g++ -print-file-name=libstdc++-6.dll)")"
for dll in libstdc++-6.dll libgcc_s_seh-1.dll; do
    src="$($PREFIX-g++ -print-file-name=$dll)"
    [ -f "$src" ] && cp -f "$src" "$OUT/" || true
done

echo ""
echo "==> Done: $OUT/pyferslib.pyd"
file "$OUT/pyferslib.pyd"
echo "    Runtime DLLs copied alongside: libstdc++-6.dll, libgcc_s_seh-1.dll"
echo "    NOTE: validate on a real Windows machine; this is unofficial (MinGW vs UCRT)."
