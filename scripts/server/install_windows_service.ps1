#Requires -Version 5.1
# Install the LF server as a Windows service (optional — auto-start with the OS).
param(
    [string]$ServerExe = "",
    [string]$ServiceName = "LFTrainingEvaluationServer",
    [int]$Port = 8005
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

if (-not $ServerExe) {
    $ServerExe = Join-Path $PSScriptRoot "..\..\dist\LF_TrainingEvaluation_Server\LF_TrainingEvaluation_Server.exe"
}
$ServerExe = (Resolve-Path $ServerExe).Path
if (-not (Test-Path $ServerExe)) {
    Write-Error "Server exe not found: $ServerExe — run BUILD_ADVANCED_SETUP.bat first."
}

$NssmCandidates = @(
    (Join-Path $PSScriptRoot "nssm\nssm.exe"),
    (Join-Path $PSScriptRoot "nssm\win64\nssm.exe"),
    "${env:ProgramFiles}\nssm\nssm.exe"
)
$Nssm = $NssmCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Nssm) {
    Write-Error "Install NSSM from https://nssm.cc/ and place nssm.exe in scripts\server\nssm\"
}

$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($svc) {
    Write-Host "Service exists — stopping and reinstalling..."
    & $Nssm stop $ServiceName confirm
    & $Nssm remove $ServiceName confirm
}

& $Nssm install $ServiceName $ServerExe
& $Nssm set $ServiceName AppDirectory (Split-Path $ServerExe)
& $Nssm set $ServiceName DisplayName "LF Training Evaluation Server"
& $Nssm set $ServiceName Description "LF Training Evaluation — LAN server (Ethernet/Wi-Fi)"
& $Nssm set $ServiceName Start SERVICE_AUTO_START
& $Nssm set $ServiceName AppEnvironmentExtra "HOST=0.0.0.0" "PORT=$Port" "LF_INSTALLED=1" "LF_OPEN_BROWSER=0"
& $Nssm start $ServiceName
Write-Host "Service installed and started: $ServiceName"
& (Join-Path $PSScriptRoot "add_firewall_rule.ps1") -Port $Port
