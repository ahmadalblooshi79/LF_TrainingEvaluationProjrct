$ErrorActionPreference = "Stop"
$jarUrl = "https://github.com/gradle/gradle/raw/v8.7.0/gradle/wrapper/gradle-wrapper.jar"
$dest = Join-Path $PSScriptRoot "..\gradle\wrapper\gradle-wrapper.jar"
$destDir = Split-Path $dest -Parent
if (-not (Test-Path $destDir)) { New-Item -ItemType Directory -Path $destDir -Force | Out-Null }
Write-Host "Downloading gradle-wrapper.jar ..."
Invoke-WebRequest -Uri $jarUrl -OutFile $dest -UseBasicParsing
Write-Host "Saved: $dest"
