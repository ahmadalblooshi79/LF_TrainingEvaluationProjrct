#Requires -Version 5.1
# Open Windows Firewall port for the LF server (run as Administrator).
param(
    [int]$Port = 8005,
    [string]$RuleName = "LF Training Evaluation Server"
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$existing = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Firewall rule already exists: $RuleName"
    exit 0
}
New-NetFirewallRule `
    -DisplayName $RuleName `
    -Direction Inbound `
    -Action Allow `
    -Protocol TCP `
    -LocalPort $Port `
    -Profile Domain,Private | Out-Null
Write-Host "Opened TCP port $Port — rule: $RuleName"
