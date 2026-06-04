param(
    [string]$Pm = 'winget',
    [int]$HasNvidia = 0
)
$ErrorActionPreference = 'Stop'

$baseDir = Join-Path $env:ProgramFiles 'Meeting-Protocol'
$whisperDir = Join-Path $baseDir 'whisper.cpp'
$modelDir = Join-Path $whisperDir 'models'

if (Test-Path (Join-Path $whisperDir 'build\bin\Release\whisper-server.exe')) {
    Write-Host "    whisper-server.exe already present."
} else {
    if (-not (Test-Path $baseDir)) { New-Item -ItemType Directory -Path $baseDir -Force | Out-Null }

    # Native Windows build via winget (ggml-org ships a prebuilt package)
    if ($Pm -eq 'winget') {
        $pkg = if ($HasNvidia -eq 0) { 'ggml-org.whisper.cpp.CUDA' } else { 'ggml-org.whisper.cpp.CPU' }
        winget install --id $pkg -e --source winget --accept-package-agreements --accept-source-agreements `
            --install-location $whisperDir
    } else {
        choco install -y whisper-cpp --params="'/InstallDir:$whisperDir'"
    }
}

if (-not (Test-Path (Join-Path $whisperDir 'build\bin\Release\whisper-server.exe'))) {
    throw 'whisper-server.exe not found after install.'
}

# Создаём папку models (если ещё нет) — но НЕ скачиваем модели
# (они слишком большие для install.bat). Используйте scripts\download_models.bat
# или скачайте вручную. См. README_MODELS.md.
if (-not (Test-Path $modelDir)) {
    New-Item -ItemType Directory -Path $modelDir -Force | Out-Null
    Write-Host "    Created empty models dir: $modelDir"
}

# Проверим, есть ли хоть какая-то модель (для whisper-server чтобы стартовал)
$existingModels = @(Get-ChildItem -Path $modelDir -Filter 'ggml-*.bin' -ErrorAction SilentlyContinue)
if ($existingModels.Count -eq 0) {
    Write-Host "    WARNING: no ggml-*.bin model in $modelDir"
    Write-Host "    Run: scripts\download_models.bat base"
    Write-Host "    Or download manually: https://huggingface.co/ggerganov/whisper.cpp"
} else {
    Write-Host "    Found model: $($existingModels[0].Name)"
}

# Add to PATH for current user
$userPath = [System.Environment]::GetEnvironmentVariable('Path', 'User')
if ($userPath -notlike "*$whisperDir\build\bin\Release*") {
    [System.Environment]::SetEnvironmentVariable('Path', "$userPath;$whisperDir\build\bin\Release", 'User')
    $env:Path += ";$whisperDir\build\bin\Release"
    Write-Host "    whisper.cpp added to user PATH."
}

Write-Host "    whisper.cpp + large-v3 ready at: $whisperDir"
exit 0
