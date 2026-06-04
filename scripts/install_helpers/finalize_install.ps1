param([string]$Root)
$ErrorActionPreference = 'Stop'

# --- .env ----------------------------------------------------------------
$envFile = Join-Path $Root '.env'
$envExample = Join-Path $Root '.env.example'
if (-not (Test-Path $envFile) -and (Test-Path $envExample)) {
    Copy-Item $envExample $envFile
    Write-Host "    Created .env from .env.example."

    # Generate a fresh WEB_SESSION_SECRET
    $sec = (1..32 | ForEach-Object { '{0:x2}' -f (Get-Random -Max 256) }) -join ''
    (Get-Content $envFile) -replace 'WEB_SESSION_SECRET=.*', "WEB_SESSION_SECRET=$sec" | Set-Content $envFile
    Write-Host "    Generated fresh WEB_SESSION_SECRET (64 hex chars)."
} else {
    Write-Host "    .env already exists, leaving untouched."
}

# --- Start Menu shortcuts -----------------------------------------------
$startMenu = [System.Environment]::GetFolderPath('StartMenu')
$appDir = Join-Path $startMenu 'Programs\Meeting-Protocol'
if (-not (Test-Path $appDir)) { New-Item -ItemType Directory -Path $appDir -Force | Out-Null }

$runBat = Join-Path $Root 'scripts\run.bat'
$serviceInstall = Join-Path $Root 'scripts\service_install.bat'
$serviceUninstall = Join-Path $Root 'scripts\service_uninstall.bat'

$WshShell = New-Object -ComObject WScript.Shell

# Shortcut: Start (dev)
$sc1 = $WshShell.CreateShortcut((Join-Path $appDir 'Start Meeting-Protocol (dev).lnk'))
$sc1.TargetPath = $runBat
$sc1.WorkingDirectory = $Root
$sc1.IconLocation = 'shell32.dll,13'
$sc1.Description = 'Run Meeting-Protocol locally in console (with reload)'
$sc1.Save()

# Shortcut: Install as service
$sc2 = $WshShell.CreateShortcut((Join-Path $appDir 'Install as Windows Service.lnk'))
$sc2.TargetPath = $serviceInstall
$sc2.WorkingDirectory = $Root
$sc2.IconLocation = 'shell32.dll,21'
$sc2.Description = 'Register Meeting-Protocol as auto-start Windows Service'
$sc2.Save()

# Shortcut: Uninstall service
$sc3 = $WshShell.CreateShortcut((Join-Path $appDir 'Uninstall Windows Service.lnk'))
$sc3.TargetPath = $serviceUninstall
$sc3.WorkingDirectory = $Root
$sc3.IconLocation = 'shell32.dll,131'
$sc3.Description = 'Remove Meeting-Protocol Windows Service'
$sc3.Save()

# Shortcut: Edit .env
$sc4 = $WshShell.CreateShortcut((Join-Path $appDir 'Edit .env.lnk'))
$sc4.TargetPath = 'notepad.exe'
$sc4.Arguments = (Join-Path $Root '.env')
$sc4.WorkingDirectory = $Root
$sc4.IconLocation = 'shell32.dll,70'
$sc4.Save()

# Shortcut: Open web UI
$sc5 = $WshShell.CreateShortcut((Join-Path $appDir 'Open Web UI.lnk'))
$sc5.TargetPath = 'http://127.0.0.1:8765/'
$sc5.IconLocation = 'shell32.dll,13'
$sc5.Save()

Write-Host "    Start Menu shortcuts created: $appDir"

# --- Whisper Windows Service (if whisper-server.exe present) ------------
$whisperExe = Join-Path $env:ProgramFiles 'Meeting-Protocol\whisper.cpp\build\bin\Release\whisper-server.exe'
if ((Test-Path $whisperExe) -and (Get-Command nssm -ErrorAction SilentlyContinue)) {
    $svcName = 'MeetingProtocol-Whisper'
    $existing = Get-Service -Name $svcName -ErrorAction SilentlyContinue
    if (-not $existing) {
        $modelDir = Join-Path $env:ProgramFiles 'Meeting-Protocol\whisper.cpp\models'
        & nssm install $svcName $whisperExe "-m $modelDir\ggml-large-v3.bin --port 9000 --host 0.0.0.0"
        & nssm set $svcName AppDirectory (Split-Path $whisperExe -Parent)
        & nssm set $svcName DisplayName 'Meeting-Protocol Whisper ASR'
        & nssm set $svcName Start SERVICE_AUTO_START
        & nssm set $svcName AppStdout (Join-Path $Root 'logs\whisper.log')
        & nssm set $svcName AppStderr (Join-Path $Root 'logs\whisper.log')
        $logsDir = Join-Path $Root 'logs'
        if (-not (Test-Path $logsDir)) { New-Item -ItemType Directory -Path $logsDir -Force | Out-Null }
        & nssm set $svcName AppStdout (Join-Path $logsDir 'whisper.log')
        & nssm set $svcName AppStderr (Join-Path $logsDir 'whisper.log')
        Write-Host "    Installed Windows Service: $svcName (auto-start)"
    } else {
        Write-Host "    Windows Service $svcName already exists."
    }
}

# --- .gitignore safety check --------------------------------------------
$gi = Join-Path $Root '.gitignore'
if (Test-Path $gi) {
    $need = @('.env', '.venv/', 'storage/audio/', 'storage/protocols/', 'logs/')
    $cur = Get-Content $gi -Raw
    $add = @()
    foreach ($n in $need) {
        if ($cur -notmatch [regex]::Escape($n)) { $add += $n }
    }
    if ($add.Count -gt 0) {
        Add-Content -Path $gi -Value "`n# added by install.bat" -Encoding UTF8
        Add-Content -Path $gi -Value ($add -join "`n") -Encoding UTF8
        Write-Host "    .gitignore updated with: $($add -join ', ')"
    }
}
Write-Host "    Finalize complete."
exit 0
