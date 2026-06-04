@echo off
REM Install Meeting-Protocol as a Windows Service via NSSM
setlocal
net session >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

where nssm >nul 2>&1
if errorlevel 1 (
    echo ERROR: nssm not found. Run install.bat first.
    exit /b 1
)

set "ROOT=%~dp0..\"
set "VENV_PY=%ROOT%.venv\Scripts\python.exe"
set "LOGS=%ROOT%logs"
if not exist "%LOGS%" mkdir "%LOGS%"

set "SVC=MeetingProtocol"
nssm stop %SVC% >nul 2>&1
nssm remove %SVC% confirm >nul 2>&1
nssm install %SVC% "%VENV_PY%" "-m uvicorn app.main:app --host 127.0.0.1 --port 8765"
nssm set %SVC% AppDirectory "%ROOT%"
nssm set %SVC% DisplayName "Meeting-Protocol Web Service"
nssm set %SVC% Start SERVICE_AUTO_START
nssm set %SVC% AppStdout "%LOGS%\service.log"
nssm set %SVC% AppStderr "%LOGS%\service.log"
nssm set %SVC% AppRotateFiles 1
nssm set %SVC% AppRotateBytes 10485760

nssm start %SVC%
echo Service %SVC% installed and started.
echo Tail logs: type %LOGS%\service.log
endlocal
