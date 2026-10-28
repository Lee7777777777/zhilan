@echo off
rem ============================================================
rem  ZhiLan launcher - local Markdown knowledge base
rem  Double-click to run. Dependencies install automatically.
rem  Debug mode (DevTools + console):  "thisfile.bat" --debug
rem  Keep this file ASCII-only: cmd parses it with the OEM
rem  code page, so Chinese comments break the rem lines.
rem ============================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title ZhiLan Launcher

set "PY="
set "PYW="
where python >nul 2>nul && set "PY=python"
where pythonw >nul 2>nul && set "PYW=pythonw"
if not defined PY where py >nul 2>nul && set "PY=py -3"
if not defined PYW where py >nul 2>nul && set "PYW=py -3w"
if not defined PY (
    echo [ERROR] Python not found in PATH.
    echo         Install Python 3.10+ and tick "Add python.exe to PATH", then retry.
    pause
    exit /b 1
)
if not defined PYW set "PYW=%PY%"

%PY% -c "import webview, markdown_it, frontmatter, mdit_py_plugins" >nul 2>nul
if errorlevel 1 (
    echo [SETUP] Installing dependencies, please wait...
    %PY% -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Dependency install failed. Try manually:
        echo         python -m pip install -r requirements.txt
        pause
        exit /b 1
    )
)

if "%~1"=="--debug" (
    echo [DEBUG] DevTools enabled, console stays open.
    %PY% main.py --debug
    pause
    exit /b 0
)

start "" %PYW% main.py
endlocal
