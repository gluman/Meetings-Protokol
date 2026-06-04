@echo off
REM ============================================================
REM Meeting-Protocol — Windows installer
REM Запускать в PowerShell или cmd от обычного пользователя
REM ============================================================
setlocal EnableDelayedExpansion

echo.
echo === Meeting-Protocol: Windows install script ===
echo.

REM 1. Locate Python 3.11+ on PATH or via py launcher
echo [1/5] Checking Python...
set PY_CMD=
where python >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PY_VER=%%v
    echo     Found python %PY_VER%
    set PY_CMD=python
) else (
    where py >nul 2>&1
    if %ERRORLEVEL% EQU 0 (
        for /f "tokens=2" %%v in ('py --version 2^>^&1') do set PY_VER=%%v
        echo     Found py launcher: %PY_VER%
        set PY_CMD=py
    ) else (
        echo     ERROR: Python not found on PATH.
        echo     Install Python 3.11+ from https://www.python.org/downloads/
        echo     During install, tick "Add python.exe to PATH".
        exit /b 1
    )
)

REM Verify version >= 3.11
for /f "tokens=1,2 delims=." %%a in ("%PY_VER%") do (
    set MAJOR=%%a
    set MINOR=%%b
)
if %MAJOR% LSS 3 (
    echo     ERROR: Python %PY_VER% is too old. Need 3.11+.
    exit /b 1
)
if %MAJOR% EQU 3 if %MINOR% LSS 11 (
    echo     ERROR: Python %PY_VER% is too old. Need 3.11+.
    exit /b 1
)

REM 2. Create venv
echo.
echo [2/5] Creating virtual environment .venv...
if exist .venv (
    echo     .venv already exists, skipping creation.
) else (
    %PY_CMD% -m venv .venv
    if errorlevel 1 (
        echo     ERROR: failed to create venv.
        exit /b 1
    )
)
set VENV_PY=.venv\Scripts\python.exe
set VENV_PIP=.venv\Scripts\pip.exe
%VENV_PY% --version >nul 2>&1
if errorlevel 1 (
    echo     ERROR: venv python not found at %VENV_PY%.
    exit /b 1
)

REM 3. Upgrade pip
echo.
echo [3/5] Upgrading pip...
%VENV_PY% -m pip install --upgrade pip --quiet
if errorlevel 1 (
    echo     WARNING: pip upgrade failed, continuing with current version.
)

REM 4. Install requirements
echo.
echo [4/5] Installing Python dependencies from requirements.txt...
%VENV_PY% -m pip install -r requirements.txt
if errorlevel 1 (
    echo     ERROR: pip install failed.
    exit /b 1
)

REM 5. Create .env from .env.example if missing
echo.
echo [5/5] Setting up .env...
if not exist .env (
    if exist .env.example (
        copy /Y .env.example .env >nul
        echo     Created .env from .env.example.
        echo     IMPORTANT: edit .env and fill in API keys before running.
    ) else (
        echo     WARNING: .env.example not found, skipping.
    )
) else (
    echo     .env already exists, leaving it untouched.
)

echo.
echo ============================================================
echo Install complete.
echo.
echo Next steps:
echo   1. Edit .env      — fill in API keys (LLM provider, etc.)
echo   2. Run service:   scripts\run.bat
echo ============================================================
echo.
endlocal
