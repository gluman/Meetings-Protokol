# detect_gpu.ps1 — emit exit 0 if NVIDIA GPU found, 1 otherwise
$gpu = Get-WmiObject Win32_VideoController | Where-Object { $_.Name -match 'NVIDIA' }
if ($gpu) {
    Write-Host "    GPU: $($gpu.Name)"
    exit 0
} else {
    Write-Host "    No NVIDIA GPU detected (CPU-only mode)."
    exit 1
}
