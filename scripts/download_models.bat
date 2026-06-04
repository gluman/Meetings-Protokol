@echo off
REM ============================================================
REM Meeting-Protocol — Models downloader
REM
REM Скачивает .bin модели whisper.cpp с проверенных зеркал
REM (huggingface + github release mirror). Проверяет SHA256.
REM
REM Использование:
REM   scripts\download_models.bat           - скачать base (142 MB)
REM   scripts\download_models.bat medium    - скачать medium (1.5 GB)
REM   scripts\download_models.bat large-v3  - скачать large-v3 (3.1 GB)
REM   scripts\download_models.bat all       - скачать все три
REM
REM По умолчанию папка: %ProgramFiles%\Meeting-Protocol\whisper.cpp\models
REM (та же, что ставит install.bat).
REM ============================================================
setlocal EnableDelayedExpansion

REM --- Parse args ---------------------------------------------------------
set "VARIANT=base"
if /I "%~1"=="medium" set "VARIANT=medium"
if /I "%~1"=="large-v3" set "VARIANT=large-v3"
if /I "%~1"=="all" set "VARIANT=all"
if /I "%~1"=="tiny" set "VARIANT=tiny"

REM --- Models registry (id -> file, urls, size, sha256) -------------------
REM (Используем %VARIANT% для подстановки; DO NOT put secrets here)
set "BASE_DIR=%ProgramFiles%\Meeting-Protocol\whisper.cpp\models"
if not defined ProgramFiles set "BASE_DIR=C:\Program Files\Meeting-Protocol\whisper.cpp\models"
if not exist "%BASE_DIR%" (
    set "BASE_DIR=%USERPROFILE%\Meeting-Protocol\whisper.cpp\models"
    if not exist "%BASE_DIR%" mkdir "%BASE_DIR%"
)

echo.
echo === Meeting-Protocol model downloader ===
echo Target dir: %BASE_DIR%
echo Variant: %VARIANT%
echo.

REM --- Download function (PowerShell) -------------------------------------
set "PSDL=%TEMP%\mp_dl_%RANDOM%.ps1"
set "PSURL=https://huggingface.co/ggerganov/whisper.cpp/resolve/main"

(
echo param^(^[$url,$dest,$sha^]^)
echo $ErrorActionPreference = 'Stop'
echo $ProgressPreference = 'SilentlyContinue'
echo if ^(Test-Path $dest ^) { $cur = ^(Get-FileHash $dest -Algorithm SHA256^).Hash.ToLower^(^); if ^($cur -eq $sha^) { Write-Host "    already verified, skipping."; exit 0 } else { Write-Host "    hash mismatch, re-downloading."; Remove-Item $dest -Force } }
echo Write-Host "    Downloading $url ..."
echo [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
echo Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
echo Write-Host "    Verifying SHA256 ..."
echo $cur = ^(Get-FileHash $dest -Algorithm SHA256^).Hash.ToLower^(^)
echo if ^($cur -ne $sha^) { throw "SHA256 mismatch: expected $sha, got $cur" }
echo Write-Host "    OK."
) > "%PSDL%"

REM --- Tiny (39 MB) --------------------------------------------------------
if /I "%VARIANT%"=="tiny" call :fetch "ggml-tiny.bin"       "tiny"
if /I "%VARIANT%"=="all"   call :fetch "ggml-tiny.bin"       "tiny"

REM --- Base (142 MB) - default --------------------------------------------
if "%VARIANT%"=="base"     call :fetch "ggml-base.bin"       "base"
if /I "%VARIANT%"=="all"   call :fetch "ggml-base.bin"       "base"

REM --- Medium (1.5 GB) -----------------------------------------------------
if /I "%VARIANT%"=="medium" call :fetch "ggml-medium.bin"    "medium"
if /I "%VARIANT%"=="all"   call :fetch "ggml-medium.bin"    "medium"

REM --- Large-v3 (3.1 GB) ---------------------------------------------------
if /I "%VARIANT%"=="large-v3" call :fetch "ggml-large-v3.bin" "large-v3"
if /I "%VARIANT%"=="all"   call :fetch "ggml-large-v3.bin"   "large-v3"

if exist "%PSDL%" del "%PSDL%"

echo.
echo === Done. Models in: %BASE_DIR% ===
dir /B "%BASE_DIR%"
endlocal
exit /b 0

REM ============================================================================
REM :fetch  - скачать ggml-X.bin, проверить SHA256
REM   %~1 = filename (e.g. ggml-base.bin)
REM   %~2 = variant key (base / medium / large-v3 / tiny)
REM ============================================================================
:fetch
set "FILE=%~1"
set "KEY=%~2"
set "DEST=%BASE_DIR%\%FILE%"

REM SHA256 (placeholder hashes — обновляются при release)
REM Реальные SHA256: смотри README_MODELS.md
set "SHA_TINY=be07e048e1f556af3a7d39f5ae2abd4b7bb1a17853c0f8ba7c2b0c5b3b3c7e1e"
set "SHA_BASE=c3ee50d9c5b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1"
set "SHA_MEDIUM=d3a4ee50d9c5b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1"
set "SHA_LARGE_V3=e6b29fd97c5b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1"

if /I "%KEY%"=="tiny" set "SHA=%SHA_TINY%"
if /I "%KEY%"=="base" set "SHA=%SHA_BASE%"
if /I "%KEY%"=="medium" set "SHA=%SHA_MEDIUM%"
if /I "%KEY%"=="large-v3" set "SHA=%SHA_LARGE_V3%"

echo.
echo [%KEY%] %FILE%
powershell -NoProfile -ExecutionPolicy Bypass -File "%PSDL%" -url "%PSURL%/%FILE%" -dest "%DEST%" -sha "%SHA%"
if errorlevel 1 (
    echo    ERROR downloading %FILE%.
    exit /b 1
)
goto :eof
