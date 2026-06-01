#Requires -Version 5.1
<#
.SYNOPSIS
  Verify server is listening and reachable on LAN/Wi-Fi port.
.PARAMETER Port
  TCP port (default 8005).
.PARAMETER ServerHost
  IP or hostname to test from a client PC. Omit on server to test localhost only.
#>
param(
    [int]$Port = 8005,
    [string]$ServerHost = "127.0.0.1"
)

$ErrorActionPreference = "Continue"
Write-Host ""
Write-Host "LF Training Evaluation - network check" -ForegroundColor Cyan
Write-Host "  Target: ${ServerHost}:${Port}"
Write-Host ""

$ok = $false
try {
    $client = New-Object System.Net.Sockets.TcpClient
    $iar = $client.BeginConnect($ServerHost, $Port, $null, $null)
    $wait = $iar.AsyncWaitHandle.WaitOne(3000, $false)
    if ($wait -and $client.Connected) {
        $client.EndConnect($iar)
        $ok = $true
    }
    $client.Close()
} catch {
    $ok = $false
}

if ($ok) {
    Write-Host "OK: Port $Port is reachable at $ServerHost" -ForegroundColor Green
    Write-Host "  Open browser: http://${ServerHost}:${Port}/"
} else {
    Write-Host "FAIL: Cannot connect to ${ServerHost}:${Port}" -ForegroundColor Red
    Write-Host "  On server: run START_SERVER.bat and keep the window open."
    Write-Host "  On server: run INSTALL.bat as Administrator (firewall)."
    Write-Host "  Use the LAN/Wi-Fi IP shown in the server window, not 127.0.0.1 from other PCs."
    Write-Host "  Guest Wi-Fi may isolate devices - use internal network."
}
Write-Host ""
