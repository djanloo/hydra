# PyInstaller spec for the HydraFERS desktop GUI (onedir).
#
# Build from the repo root:
#     pyinstaller packaging/hydrafers.spec
#
# Produces dist/hydrafers/ (the exe + _internal/). The build_appimage.sh script
# wraps that folder into an AppImage. The same spec works on Windows (yields
# dist/hydrafers/hydrafers.exe), which an installer (Inno Setup/NSIS) can wrap.

import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

# SPECPATH is the directory containing this spec (…/hydra/packaging).
ROOT = os.path.dirname(os.path.abspath(SPECPATH))
GUI = os.path.join(ROOT, "src", "hydrafers", "gui")

# Windows wants a .ico for the EXE icon; other platforms take the PNG.
if sys.platform == "win32":
    APP_ICON = os.path.join(GUI, "imgs", "hydrafers.ico")
else:
    APP_ICON = os.path.join(GUI, "imgs", "light_bg.png")

# Data files the app loads at runtime via Path(__file__).parent — keep them at
# the same package-relative location so that resolution keeps working bundled.
datas = [
    (os.path.join(GUI, "style.qss"), "hydrafers/gui"),
    (os.path.join(GUI, "imgs"), "hydrafers/gui/imgs"),
    (os.path.join(ROOT, "src", "hydrafers", "config", "default.yaml"), "hydrafers/config"),
]
binaries = []
hiddenimports = ["pyferslib"]
hiddenimports += collect_submodules("hydrafers")

# pyqtgraph does a lot of lazy importing; pull it in wholesale.
pg_datas, pg_bins, pg_hidden = collect_all("pyqtgraph")
datas += pg_datas
binaries += pg_bins
hiddenimports += pg_hidden

# qtawesome ships icon fonts as data files that must be bundled too.
qta_datas, qta_bins, qta_hidden = collect_all("qtawesome")
datas += qta_datas
binaries += qta_bins
hiddenimports += qta_hidden

# Trim heavy Qt modules the GUI never touches (halves the bundle size).
excludes = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQml",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtPdf",
    "PySide6.QtSensors",
    "PySide6.QtPositioning",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtSerialPort",
    "PySide6.QtTest",
    "PyQt5",
    "PyQt6",
    "tkinter",
    "matplotlib",
]

block_cipher = None

a = Analysis(
    [os.path.join(SPECPATH, "launch_gui.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="hydrafers",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,   # GUI app: no terminal window on Windows
    icon=APP_ICON,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="hydrafers",
)
