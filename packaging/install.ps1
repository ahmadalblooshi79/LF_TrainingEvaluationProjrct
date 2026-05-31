#Requires -Version 5.1
<#
.SYNOPSIS
  Install LF Training Evaluation server (Windows).
.DESCRIPTION
  Creates Python venv, installs requirements, optional firewall rule for port 8005.
  Data directory: %LOCALAPPDATA%\LF_TrainingEvaluation (when LF_INSTALL_MODE=1).
#>
param(
    [switch]$SkipFirewall,
    [int]$Port = 8005
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  LF Training Evaluation - Server Install" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Folder: $Root"
Write-Host ""

function Find-Python {
    $candidates = @(
        (Get-Command py -ErrorAction SilentlyContinue),
        (Get-Command python -ErrorAction SilentlyContinue)
    ) | Where-Object { $_ }
    foreach ($cmd in $candidates) {
        try {
            $ver = & $cmd.Source -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
            if ($ver -match '^3\.(1[1-9]|[2-9][0-9])') { return $cmd.Source }
        } catch {}
    }
    return $null
}

$py = Find-Python
if (-not $py) {
    Write-Host "ERROR: Python 3.11+ not found." -ForegroundColor Red
    Write-Host "Install from https://www.python.org/downloads/ (check Add to PATH), then run again."
    exit 1
}
Write-Host "Python: $py" -ForegroundColor Green

$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "Creating virtual environment .venv ..."
    & $py -m venv ".venv"
}
& $venvPy -m pip install --upgrade pip
& $venvPy -m pip install -r "requirements.txt"

$envExample = Join-Path $Root "packaging\.env.server.example"
$envTarget = Join-Path $Root ".env"
if ((Test-Path $envExample) -and -not (Test-Path $envTarget)) {
    Copy-Item $envExample $envTarget
    Write-Host "Created .env from template - change SECRET_KEY before production." -ForegroundColor Yellow
}

Write-Host "Verifying application ..."
& $venvPy -c "from app import create_app; create_app(); print('OK: application loads')"

if (-not $SkipFirewall) {
    $ruleName = "LF Training Evaluation (TCP $Port)"
    $existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
    if (-not $existing) {
        try {
            New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow `
                -Protocol TCP -LocalPort $Port -Profile Domain,Private | Out-Null
            Write-Host "Firewall: allowed inbound TCP port $Port (Domain, Private)." -ForegroundColor Green
        } catch {
            Write-Host "Firewall: could not add rule. Run as Administrator or use -SkipFirewall" -ForegroundColor Yellow
        }
    } else {
        Write-Host "Firewall: rule already exists." -ForegroundColor Gray
    }
}

$startBat = Join-Path $Root "packaging\start_server.bat"
Write-Host ""
Write-Host "Install finished." -ForegroundColor Green
Write-Host "Start server: double-click" -ForegroundColor Green
Write-Host "  $startBat"
Write-Host ""
Write-Host "LAN/Wi-Fi clients: use http://<server-IP>:$Port/ shown in the server window." -ForegroundColor Cyan
Write-Host "Arabic guide: packaging\README_INSTALL_AR.md"
Write-Host ""
