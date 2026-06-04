param([string]$Pm = 'winget')
$ErrorActionPreference = 'Stop'

if (Get-Command caddy -ErrorAction SilentlyContinue) {
    Write-Host "    caddy already present."
} else {
    if ($Pm -eq 'winget') {
        winget install --id CaddyServer.Caddy -e --source winget --accept-package-agreements --accept-source-agreements
    } else {
        choco install -y caddy
    }
    $env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path', 'User')
}

if (-not (Get-Command caddy -ErrorAction SilentlyContinue)) { throw 'caddy install failed.' }

# Generate a self-signed cert for development HTTPS
$root = (Get-Location).Path
$cfgDir = Join-Path $root 'caddy'
if (-not (Test-Path $cfgDir)) { New-Item -ItemType Directory -Path $cfgDir -Force | Out-Null }
$certDir = Join-Path $cfgDir 'certs'
if (-not (Test-Path $certDir)) { New-Item -ItemType Directory -Path $certDir -Force | Out-Null }
$crt = Join-Path $certDir 'localhost.crt'
$key = Join-Path $certDir 'localhost.key'
if (-not (Test-Path $crt) -or -not (Test-Path $key)) {
    Write-Host "    Generating self-signed cert for localhost..."
    & caddy trust
    & caddy reverse-proxy --from https://localhost:8443 --to http://127.0.0.1:8765
    # We don't actually start the proxy here, just pre-stage a Caddyfile
    @"
:8443 {
    tls $crt $key
    reverse_proxy 127.0.0.1:8765
}
"@ | Set-Content -Path (Join-Path $cfgDir 'Caddyfile') -Encoding UTF8
}
Write-Host "    caddy installed. Caddyfile at: $cfgDir\Caddyfile"
exit 0
