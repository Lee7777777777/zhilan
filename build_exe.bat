@echo off
rem ============================================================
rem  Build ZhiLan into a single exe (dist\ZhiLan.exe)
rem  Requires: python + internet for the first run (pip install)
rem  Keep this file ASCII-only; cmd parses .bat with the OEM code page.
rem ============================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title ZhiLan Build

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found in PATH.
    pause
    exit /b 1
)

python -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
    echo [SETUP] Installing PyInstaller...
    python -m pip install pyinstaller
    if errorlevel 1 (echo [ERROR] pip install failed. & pause & exit /b 1)
)

echo [BUILD] Packing single-file exe, this takes a few minutes...
python -m PyInstaller --noconfirm --clean zhilan.spec
if errorlevel 1 (
    echo [ERROR] Build failed. See messages above.
    pause
    exit /b 1
)

echo.
echo [OK] Done: dist\知览.exe
echo      Copy it anywhere; your data stays in a "library" folder next to the exe.
pause
