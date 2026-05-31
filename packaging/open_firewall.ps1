#Requires -Version 5.1
# Allow inbound TCP port for LAN clients. Run PowerShell as Administrator.
param([int]$Port = 8005)
$ruleName = "LF Training Evaluation (TCP $Port)"
if (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue) {
    Write-Host "Rule already exists: $ruleName"
    exit 0
}
New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow `
    -Protocol TCP -LocalPort $Port -Profile Domain,Private
Write-Host "Allowed inbound TCP port $Port (Domain, Private profiles)."
