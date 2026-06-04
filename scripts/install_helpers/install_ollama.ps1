param(
    [string]$Pm = 'winget',
    [int]$HasNvidia = 0
)
$ErrorActionPreference = 'Stop'

if (Get-Command ollama -ErrorAction SilentlyContinue) {
    Write-Host "    ollama already present."
} else {
    if ($Pm -eq 'winget') {
        winget install --id Ollama.Ollama -e --source winget --accept-package-agreements --accept-source-agreements
    } else {
        choco install -y ollama
    }
    $env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path', 'User')
}

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    throw 'ollama install failed.'
}

# Pull the default model referenced in .env.example (MiniMax-M3)
Write-Host "    Pulling model MiniMax-M3 (this may take a few minutes)..."
& ollama pull MiniMax-M3
if ($LASTEXITCODE -ne 0) {
    Write-Host "    WARNING: ollama pull failed. Will rely on external LLM API."
}

# Configure Ollama to listen on all interfaces (so reverse proxy / LAN works)
$ollamaCfg = Join-Path $env:USERPROFILE '.ollama\config.json'
$cfg = @{ listen_address = '0.0.0.0:11434' } | ConvertTo-Json
$dir = Split-Path $ollamaCfg -Parent
if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
Set-Content -Path $ollamaCfg -Value $cfg -Encoding UTF8
Write-Host "    Ollama config written to $ollamaCfg"

# Start Ollama service
$svc = Get-Service -Name 'Ollama' -ErrorAction SilentlyContinue
if ($svc) {
    Set-Service -Name 'Ollama' -StartupType Automatic
    Start-Service -Name 'Ollama' -ErrorAction SilentlyContinue
    Write-Host "    Ollama Windows Service started."
}
exit 0
