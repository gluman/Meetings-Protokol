param([string]$Pm = 'winget')
$ErrorActionPreference = 'Stop'

if (Get-Command nssm -ErrorAction SilentlyContinue) {
    Write-Host "    nssm already present."; exit 0
}

if ($Pm -eq 'winget') {
    winget install --id nssm.nssm -e --source winget --accept-package-agreements --accept-source-agreements
} else {
    choco install -y nssm
}
$env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path', 'User')
if (-not (Get-Command nssm -ErrorAction SilentlyContinue)) { throw 'nssm install failed.' }
Write-Host "    nssm installed."
exit 0
