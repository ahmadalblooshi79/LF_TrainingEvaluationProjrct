#Requires -Version 5.1
<#
.SYNOPSIS
  Install LF Training Evaluation server (Windows).
.DESCRIPTION
  Creates Python venv, installs requirements, firewall rule for LAN/Wi-Fi port 8005,
  desktop shortcut, and .env with a random SECRET_KEY.
  Data directory: %LOCALAPPDATA%\LF_TrainingEvaluation (when LF_INSTALL_MODE=1).
#>
param(
    [switch]$SkipFirewall,
    [switch]$SkipDesktopShortcut,
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

function New-RandomSecretKey {
    $bytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return [Convert]::ToBase64String($bytes)
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
    $secret = New-RandomSecretKey
    (Get-Content $envTarget -Raw) -replace 'SECRET_KEY=change-me-to-a-long-random-string', "SECRET_KEY=$secret" | Set-Content $envTarget -Encoding UTF8
    Write-Host "Created .env with random SECRET_KEY." -ForegroundColor Green
} elseif (-not (Test-Path $envTarget)) {
    @"
SECRET_KEY=$(New-RandomSecretKey)
PORT=$Port
HOST=0.0.0.0
LF_INSTALL_MODE=1
FLASK_DEBUG=0
LF_OPEN_BROWSER=1
WAITRESS_THREADS=16
LF_HEARTBEAT_POLL_MS=2000
LF_HEARTBEAT_FAST_POLL_MS=1000
"@ | Set-Content $envTarget -Encoding UTF8
    Write-Host "Created .env with defaults." -ForegroundColor Green
}

Write-Host "Verifying application ..."
& $venvPy -c "from app import create_app; create_app(); print('OK: application loads')"

if (-not $SkipFirewall) {
    $ruleName = "LF Training Evaluation (TCP $Port)"
    $existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
    if (-not $existing) {
        try {
            New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow `
                -Protocol TCP -LocalPort $Port -Profile Domain,Private,Public | Out-Null
            Write-Host "Firewall: allowed inbound TCP port $Port (Domain, Private, Public)." -ForegroundColor Green
            Write-Host "  Covers LAN cable and internal Wi-Fi." -ForegroundColor Gray
        } catch {
            Write-Host "Firewall: could not add rule. Run as Administrator or use -SkipFirewall" -ForegroundColor Yellow
            Write-Host "  Or run: packaging\open_firewall.ps1 (as Admin)" -ForegroundColor Yellow
        }
    } else {
        Write-Host "Firewall: rule already exists." -ForegroundColor Gray
    }
}

$startBat = Join-Path $Root "packaging\start_server.bat"
if (-not $SkipDesktopShortcut) {
    try {
        $desktop = [Environment]::GetFolderPath("Desktop")
        $lnkPath = Join-Path $desktop "LF Training Evaluation Server.lnk"
        $shell = New-Object -ComObject WScript.Shell
        $sc = $shell.CreateShortcut($lnkPath)
        $sc.TargetPath = $startBat
        $sc.WorkingDirectory = $Root
        $sc.Description = "Start LF Training Evaluation server (LAN / Wi-Fi)"
        $sc.Save()
        Write-Host "Desktop shortcut created." -ForegroundColor Green
    } catch {
        Write-Host "Could not create desktop shortcut (non-fatal)." -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "Install finished." -ForegroundColor Green
Write-Host ""
Write-Host "  SERVER (this PC):" -ForegroundColor Cyan
Write-Host "    Double-click: START_SERVER.bat"
Write-Host "    Or: packaging\start_server.bat"
Write-Host ""
Write-Host "  CLIENTS (other devices - browser only, no install):" -ForegroundColor Cyan
Write-Host "    Open Chrome/Edge on the same LAN or Wi-Fi network"
Write-Host "    Use: http://<server-IP>:$Port/"
Write-Host "    (IP addresses appear in the server window when started)"
Write-Host ""
Write-Host "Arabic guide: packaging\README_INSTALL_AR.md"
Write-Host ""
