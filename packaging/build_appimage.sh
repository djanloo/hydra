#!/usr/bin/env bash
# Build a self-contained HydraFERS GUI AppImage for Linux.
#
#   1. PyInstaller bundles the GUI (Qt + pyferslib + libusb) into dist/hydrafers/
#   2. that folder is assembled into an AppDir with a .desktop + the GUI logo
#   3. appimagetool wraps the AppDir into a single portable *.AppImage
#
# Usage:  packaging/build_appimage.sh
# Env:    PYTHON=/path/to/venv/bin/python   (default: ~/.venvs/caen/bin/python)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PKG="$ROOT/packaging"
PYTHON="${PYTHON:-$HOME/.venvs/caen/bin/python}"
APP="HydraFERS"
ARCH="x86_64"
ICON_SRC="$ROOT/src/hydrafers/gui/imgs/light_bg.png"

cd "$ROOT"
echo "==> Repo:    $ROOT"
echo "==> Python:  $PYTHON"

# PyInstaller imports pyqtgraph/PySide6 in isolated subprocesses to enumerate
# submodules; on a headless box that triggers the Qt "xcb" platform plugin,
# which aborts when libxcb-cursor0 is absent (e.g. CI runners). Force the
# always-available offscreen platform so collection never needs a display.
export QT_QPA_PLATFORM=offscreen

# --- 1. PyInstaller -------------------------------------------------------
echo "==> Running PyInstaller…"
rm -rf "$ROOT/dist/hydrafers" "$ROOT/build/pyi"
"$PYTHON" -m PyInstaller --noconfirm \
    --distpath "$ROOT/dist" \
    --workpath "$ROOT/build/pyi" \
    "$PKG/hydrafers.spec"

[ -x "$ROOT/dist/hydrafers/hydrafers" ] || {
    echo "ERROR: PyInstaller did not produce dist/hydrafers/hydrafers" >&2
    exit 1
}

# Sanity: a working GUI bundle MUST contain PySide6 (Qt). If it doesn't, the
# build env was missing the [gui] extra and the AppImage would be tiny and fail
# to start — catch that here instead of shipping a broken artifact.
if ! ls -d "$ROOT"/dist/hydrafers/_internal/PySide6 >/dev/null 2>&1; then
    echo "ERROR: PySide6 not bundled — did you 'pip install .[gui]' before building?" >&2
    exit 1
fi

# --- 2. Assemble the AppDir ----------------------------------------------
echo "==> Assembling AppDir…"
APPDIR="$ROOT/build/AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" \
         "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/256x256/apps"

# PyInstaller onedir → usr/bin/hydrafers/
cp -a "$ROOT/dist/hydrafers" "$APPDIR/usr/bin/hydrafers"

# Icon (the logo shown in the GUI sidebar). Named after the .desktop Icon= key.
cp "$ICON_SRC" "$APPDIR/hydrafers.png"
cp "$ICON_SRC" "$APPDIR/usr/share/icons/hicolor/256x256/apps/hydrafers.png"

# Desktop entry (root copy is required by appimagetool).
cp "$PKG/hydrafers.desktop" "$APPDIR/hydrafers.desktop"
cp "$PKG/hydrafers.desktop" "$APPDIR/usr/share/applications/hydrafers.desktop"

# AppRun launcher.
cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/hydrafers/hydrafers" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

# --- 3. appimagetool ------------------------------------------------------
TOOL="$PKG/tools/appimagetool-$ARCH.AppImage"
if [ ! -x "$TOOL" ]; then
    echo "==> Downloading appimagetool…"
    mkdir -p "$PKG/tools"
    curl -fsSL -o "$TOOL" \
        "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$ARCH.AppImage"
    chmod +x "$TOOL"
fi

echo "==> Building AppImage…"
mkdir -p "$ROOT/dist"
OUT="$ROOT/dist/$APP-$ARCH.AppImage"
# Build to a temp name, then atomically rename over OUT. Writing OUT directly
# fails with "Text file busy" (ETXTBSY) if a previous AppImage is still running;
# rename replaces the directory entry without opening the running file.
OUT_TMP="$OUT.new.$$"
rm -f "$OUT_TMP"
# APPIMAGE_EXTRACT_AND_RUN avoids needing FUSE to run appimagetool itself.
APPIMAGE_EXTRACT_AND_RUN=1 ARCH="$ARCH" "$TOOL" "$APPDIR" "$OUT_TMP"
mv -f "$OUT_TMP" "$OUT"

echo ""
echo "==> Done:  $OUT"
ls -lh "$OUT"
