param([string]$Pm = 'winget')
$ErrorActionPreference = 'Stop'

$ff = (Get-Command ffmpeg -ErrorAction SilentlyContinue)
if ($ff) { Write-Host "    ffmpeg already at: $($ff.Source)"; exit 0 }

if ($Pm -eq 'winget') {
    winget install --id Gyan.FFmpeg -e --source winget --accept-package-agreements --accept-source-agreements
} else {
    choco install -y ffmpeg
}

$env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path', 'User')
$ff = (Get-Command ffmpeg -ErrorAction SilentlyContinue)
if (-not $ff) { throw 'ffmpeg install failed.' }
Write-Host "    ffmpeg installed at: $($ff.Source)"
exit 0
