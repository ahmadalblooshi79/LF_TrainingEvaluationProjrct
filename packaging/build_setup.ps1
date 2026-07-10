#Requires -Version 5.1
<#
  Build setup.exe via PyInstaller + 7-Zip SFX (no Advanced Installer).

  Run: BUILD_SETUP.bat or packaging\build_setup.ps1

  Console output is English only — Arabic RTL breaks in Windows PowerShell.
#>
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    Write-Error "Missing .venv — create it, then: pip install -r requirements-build.txt"
}

Write-Host "[1/4] PyInstaller..." -ForegroundColor Cyan
& $VenvPy -m pip install -q -r (Join-Path $Root "requirements-build.txt")
& $VenvPy -m PyInstaller --noconfirm --clean (Join-Path $Root "packaging\lf_server.spec")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$BuildDir = Join-Path $Root "dist\LF_TrainingEvaluation_Server"
if (-not (Test-Path (Join-Path $BuildDir "LF_TrainingEvaluation_Server.exe"))) {
    Write-Error "LF_TrainingEvaluation_Server.exe not found in dist\LF_TrainingEvaluation_Server"
}

Write-Host "[2/4] 7-Zip archive..." -ForegroundColor Cyan
$SevenZip = @(
    "${env:ProgramFiles}\7-Zip\7z.exe",
    "${env:ProgramFiles(x86)}\7-Zip\7z.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $SevenZip) {
    Write-Error "Install 7-Zip from https://www.7-zip.org/ and retry."
}

$OutDir = Join-Path $Root "dist"
$Archive = Join-Path $OutDir "LF_TrainingEvaluation.7z"
if (Test-Path $Archive) { Remove-Item $Archive -Force }
& $SevenZip a -t7z -mx=9 $Archive (Join-Path $BuildDir "*")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[3/4] SFX merge -> setup.exe..." -ForegroundColor Cyan
$SfxModule = Join-Path (Split-Path $SevenZip) "7zSD.sfx"
if (-not (Test-Path $SfxModule)) {
    Write-Error "7zSD.sfx not found next to 7z.exe"
}
$Config = Join-Path $Root "packaging\sfx_install.txt"
$SetupExe = Join-Path $OutDir "LF_TrainingEvaluation_Setup.exe"
if (Test-Path $SetupExe) { Remove-Item $SetupExe -Force }

$fs = [System.IO.File]::Open($SetupExe, [System.IO.FileMode]::Create)
try {
    $sfxBytes = [System.IO.File]::ReadAllBytes($SfxModule)
    $cfgBytes = [System.IO.File]::ReadAllBytes($Config)
    $arcBytes = [System.IO.File]::ReadAllBytes($Archive)
    $fs.Write($sfxBytes, 0, $sfxBytes.Length)
    $fs.Write($cfgBytes, 0, $cfgBytes.Length)
    $fs.Write($arcBytes, 0, $arcBytes.Length)
} finally {
    $fs.Close()
}

Write-Host "[4/4] Done." -ForegroundColor Green
Write-Host ""
Write-Host "  Installer: $SetupExe"
Write-Host "  Size: ~$([math]::Round((Get-Item $SetupExe).Length / 1MB, 1)) MB"
Write-Host ""
Write-Host "  Data folder: %LOCALAPPDATA%\LF_TrainingEvaluation\"
