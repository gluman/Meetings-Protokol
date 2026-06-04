@echo off
REM ============================================================
REM Meeting-Protocol — Windows dev launcher
REM Loads .env into current shell then starts uvicorn
REM ============================================================
setlocal

if not exist .venv\Scripts\python.exe (
    echo ERROR: .venv not found. Run install.bat first.
    exit /b 1
)

if not exist .env (
    echo ERROR: .env not found. Copy from .env.example and fill in keys.
    exit /b 1
)

REM Load .env into environment (KEY=VALUE per line, ignore comments/blanks)
for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
    set "line=%%a"
    if not "!line:~0,1!"=="#" if not "%%a"=="" (
        set "%%a=%%b"
    )
)

echo Starting Meeting-Protocol on http://127.0.0.1:8765
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8765 --reload
endlocal
