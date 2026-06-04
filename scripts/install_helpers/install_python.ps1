param([string]$Pm = 'winget')
$ErrorActionPreference = 'Stop'

function Get-PyVersion {
    try { & python -Version 2>$null | Select-String -Pattern '\d+\.\d+' | ForEach-Object { $_.Matches.Value } } catch {}
}

$cur = (Get-PyVersion) -join ''
if ($cur) {
    $parts = $cur -split '\.'
    $maj = [int]$parts[0]; $min = [int]$parts[1]
    if ($maj -ge 3 -and $min -ge 11) {
        Write-Host "    Python $cur already present."
        exit 0
    }
    Write-Host "    Python $cur too old, need 3.11+."
}

if ($Pm -eq 'winget') {
    winget install --id Python.Python.3.12 -e --source winget --accept-package-agreements --accept-source-agreements
} else {
    choco install -y python312
}

# Refresh PATH
$env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path', 'User')
$cur = (Get-PyVersion) -join ''
if (-not $cur) { throw 'Python install failed.' }
Write-Host "    Python $cur installed."
exit 0
