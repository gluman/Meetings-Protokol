@echo off
REM Uninstall Meeting-Protocol Windows Service
setlocal
net session >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
where nssm >nul 2>&1
if errorlevel 1 (
    echo nssm not found, nothing to do.
    exit /b 0
)
nssm stop MeetingProtocol >nul 2>&1
nssm remove MeetingProtocol confirm
echo Service MeetingProtocol removed.
endlocal
