@echo off

REM ============================================================

REM Meeting-Protocol — Windows MAX installer

REM

REM Полный авто-установщик: Python 3.11+, FFmpeg, Ollama,

REM whisper.cpp + large-v3, Caddy (HTTPS reverse proxy),

REM NSSM-сервисы, Start Menu shortcuts, GPU detect.

REM

REM Запускать в cmd от АДМИНИСТРАТОРА. Скрипт сам попросит

REM elevation через UAC, если запущен не из admin shell.

REM ============================================================

setlocal EnableDelayedExpansion



REM --- Self-elevate to Administrator -------------------------------------

net session >nul 2>&1

if %ERRORLEVEL% NEQ 0 (

    echo.

    echo === Re-launching with Administrator privileges ===

    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"

    exit /b

)



set "ROOT=%~dp0"

cd /d "%ROOT%"



echo.

echo ===============================================================

echo  Meeting-Protocol — Windows MAX installer

echo  Target dir: %CD%

echo  Date: %DATE% %TIME%

echo ===============================================================

echo.



REM --- Choose package manager --------------------------------------------

set "PM=winget"

where winget >nul 2>&1

if %ERRORLEVEL% NEQ 0 (

    where choco >nul 2>&1

    if %ERRORLEVEL% EQU 0 (

        set "PM=choco"

    ) else (

        echo No package manager found. Installing Chocolatey...

        powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\install_helpers\install_chocolatey.ps1"

        set "PM=choco"

    )

)

echo Package manager: %PM%

echo.



REM --- GPU detect ---------------------------------------------------------

echo [detect] Checking for NVIDIA GPU...

powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\install_helpers\detect_gpu.ps1"

set "HAS_NVIDIA=%ERRORLEVEL%"



REM --- Install Python 3.11+ ----------------------------------------------

echo.

echo [1/9] Python 3.11+...

powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\install_helpers\install_python.ps1" -Pm %PM%

if errorlevel 1 goto :fail

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PY_VER=%%v

echo     Python %PY_VER% ready.



REM --- Create venv --------------------------------------------------------

echo.

echo [2/9] Virtual environment .venv ...

if exist .venv (

    echo     .venv already exists, skipping creation.

) else (

    python -m venv .venv

    if errorlevel 1 goto :fail

)

set "VENV_PY=%ROOT%.venv\Scripts\python.exe"

set "VENV_PIP=%ROOT%.venv\Scripts\pip.exe"

%VENV_PY% -m pip install --upgrade pip --quiet

if errorlevel 1 (

    echo     WARNING: pip upgrade failed, continuing.

)



REM --- Install Python requirements ---------------------------------------

echo.

echo [3/9] Python packages from requirements.txt ...

%VENV_PY% -m pip install -r requirements.txt

if errorlevel 1 goto :fail



REM --- Install FFmpeg -----------------------------------------------------

echo.

echo [4/9] FFmpeg (for mp4/m4a input) ...

powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\install_helpers\install_ffmpeg.ps1" -Pm %PM%

if errorlevel 1 (

    echo     WARNING: FFmpeg install failed. Audio upload of mp4/m4a will not work.

)



REM --- Install Ollama + recommended model --------------------------------

echo.

echo [5/9] Ollama + MiniMax-M3 model ...

powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\install_helpers\install_ollama.ps1" -Pm %PM% -HasNvidia %HAS_NVIDIA%

if errorlevel 1 (

    echo     WARNING: Ollama install failed. LLM will use external API only.

)



REM --- Install whisper.cpp + large-v3 ------------------------------------

REM --- Install whisper.cpp (model downloaded separately — see README_MODELS.md) ----
echo.
echo [6/9] whisper.cpp server (model via download_models.bat) ...

powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\install_helpers\install_whisper.ps1" -Pm %PM% -HasNvidia %HAS_NVIDIA%

if errorlevel 1 (
    echo     WARNING: whisper.cpp install failed. ASR will not work locally.
)

)



REM --- Install Caddy (HTTPS reverse proxy) -------------------------------

echo.

echo [7/9] Caddy (HTTPS reverse proxy with self-signed fallback) ...

powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\install_helpers\install_caddy.ps1" -Pm %PM%

if errorlevel 1 (

    echo     WARNING: Caddy install failed. Service will be HTTP-only.

)



REM --- Install NSSM (service manager) -------------------------------------

echo.

echo [8/9] NSSM (Windows Service helper) ...

powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\install_helpers\install_nssm.ps1" -Pm %PM%

if errorlevel 1 (

    echo     WARNING: NSSM install failed. Service will not auto-start on boot.

)



REM --- Configure .env, Start Menu shortcuts, optional service ------------

echo.

echo [9/9] .env configuration, Start Menu shortcuts, optional service...

powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\install_helpers\finalize_install.ps1" -Root "%ROOT%"



echo.

echo ===============================================================

echo  INSTALL COMPLETE

echo ===============================================================

echo.

echo Next steps:

echo   1. Edit .env        (set MINIMAX_API_KEY, AUTOAI_API_KEY, passwords)

echo   2. Start in dev:   scripts\run.bat

echo   3. Install as service: scripts\service_install.bat

echo   4. Start Menu:    "Meeting-Protocol" folder

echo.

echo GPU detected: %HAS_NVIDIA% ^(0=yes, 1=no^)

echo.

endlocal

exit /b 0



:fail

echo.

echo ===============================================================

echo  INSTALL FAILED at last step. See messages above.

echo ===============================================================

endlocal

exit /b 1

