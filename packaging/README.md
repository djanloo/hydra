# Packaging the HydraFERS GUI

The desktop GUI (`hydrafers gui`) can be bundled into a self-contained app for
each OS. The PyInstaller spec ([`hydrafers.spec`](hydrafers.spec)) is shared by
both platforms; only the wrapping differs.

> ⚠️ `pyferslib` is a compiled C++ extension, so you **cannot cross-compile**:
> build the Windows `.exe` on Windows and the Linux AppImage on Linux (or use a
> CI matrix).

## Files

| File | Purpose |
|------|---------|
| `hydrafers.spec`     | PyInstaller spec (onedir, GUI, trimmed Qt) — both OSes |
| `launch_gui.py`      | Entry-point script PyInstaller analyses |
| `build_appimage.sh`  | Linux: PyInstaller → AppDir → AppImage |
| `build_windows.bat`  | Windows: build pyferslib → PyInstaller → (opt.) installer |
| `hydrafers.iss`      | Inno Setup script → Windows installer `.exe` |
| `hydrafers.desktop`  | Linux desktop entry |

## Linux → AppImage

```bash
make appimage          # or: PYTHON=~/.venvs/caen/bin/python bash packaging/build_appimage.sh
```

Output: `dist/HydraFERS-x86_64.AppImage` (single portable file).

## Windows → .exe

Prerequisites on the Windows build machine:

* Python 3.10–3.12 (the `py` launcher)
* CMake (on `PATH`)
* Visual Studio Build Tools with **Desktop development with C++** (MSVC + SDK)

```bat
packaging\build_windows.bat
```

Output: `dist\hydrafers\hydrafers.exe` (onedir bundle: the exe + `_internal\`).

To also produce an installer (needs [Inno Setup](https://jrsoftware.org/isdl.php)
with `ISCC.exe` on `PATH`):

```bat
packaging\build_windows.bat installer
```

Output: `dist\HydraFERS-Setup-1.0.0.exe`.

## Icon

The app/installer icon is generated from the GUI sidebar logo
(`src/hydrafers/gui/imgs/light_bg.png`):

* Linux: the PNG is used directly.
* Windows: a multi-resolution `hydrafers.ico` (16–256 px) is used.

Regenerate the `.ico` after changing the logo:

```bash
python -c "from PIL import Image; Image.open('src/hydrafers/gui/imgs/light_bg.png').convert('RGBA').save('src/hydrafers/gui/imgs/hydrafers.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])"
```
