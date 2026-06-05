@echo off
REM ===========================================================================
REM  Build the HydraFERS desktop GUI into a Windows executable.
REM
REM  Output:  dist\hydrafers\hydrafers.exe   (onedir bundle: exe + _internal\)
REM
REM  Prerequisites on the build machine:
REM    * Python 3.10-3.12  (the "py" launcher)
REM    * CMake             (https://cmake.org, on PATH)
REM    * Visual Studio Build Tools with the "Desktop development with C++"
REM      workload (MSVC + Windows SDK) -- needed to compile pyferslib.
REM
REM  Run from anywhere:   packaging\build_windows.bat
REM  Optional: pass  installer  to also build the Inno Setup installer
REM            (requires Inno Setup's ISCC.exe on PATH):
REM                packaging\build_windows.bat installer
REM ===========================================================================
setlocal enabledelayedexpansion

set "ROOT=%~dp0.."
pushd "%ROOT%"

echo ==^> Repo: %CD%

REM --- 1. Virtual environment ------------------------------------------------
if not exist ".venv-win\Scripts\python.exe" (
    echo ==^> Creating venv .venv-win
    py -3 -m venv .venv-win || goto :err
)
call ".venv-win\Scripts\activate.bat" || goto :err

REM --- 2. Build + install hydrafers (compiles pyferslib) + PyInstaller -------
echo ==^> Installing build deps and compiling pyferslib...
python -m pip install --upgrade pip || goto :err
python -m pip install . pyinstaller || goto :err

REM --- 3. PyInstaller --------------------------------------------------------
echo ==^> Running PyInstaller...
rmdir /s /q "dist\hydrafers" 2>nul
python -m PyInstaller --noconfirm ^
    --distpath "dist" ^
    --workpath "build\pyi" ^
    "packaging\hydrafers.spec" || goto :err

if not exist "dist\hydrafers\hydrafers.exe" (
    echo ERROR: PyInstaller did not produce dist\hydrafers\hydrafers.exe
    goto :err
)

echo.
echo ==^> Done: dist\hydrafers\hydrafers.exe

REM --- 4. Optional installer -------------------------------------------------
if /i "%~1"=="installer" (
    echo ==^> Building Inno Setup installer...
    where ISCC >nul 2>nul || (
        echo ERROR: ISCC.exe not found on PATH. Install Inno Setup first.
        goto :err
    )
    ISCC "packaging\hydrafers.iss" || goto :err
    echo ==^> Installer written to dist\
)

popd
endlocal
exit /b 0

:err
echo.
echo BUILD FAILED
popd
endlocal
exit /b 1
