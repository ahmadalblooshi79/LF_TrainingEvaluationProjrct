#Requires -Version 5.1
<#
  Build LF_TrainingEvaluation_Client_Setup.exe (client launcher + Advanced Installer).

  Run from project root: BUILD_CLIENT_SETUP.bat

  Client reads server IP from client.ini in the install folder.
#>
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root

$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    Write-Error "Missing .venv under $Root — create it, then: pip install -r requirements-build.txt"
}

$FinalSetup = Join-Path $Root "dist\LF_TrainingEvaluation_Client_Setup.exe"
$AIP = Join-Path $Root "packaging\advanced_installer\LF_TrainingEvaluation_Client.aip"
$AIDir = Split-Path $AIP

function Invoke-AiEdit {
    param(
        [Parameter(Mandatory = $true)][string]$AiCom,
        [Parameter(Mandatory = $true)][string]$AipPath,
        [Parameter(Mandatory = $true)][string[]]$EditArgs
    )
    & $AiCom /edit $AipPath @EditArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Advanced Installer failed: /edit $($EditArgs -join ' ')"
    }
}

function Find-AdvancedInstallerCom {
    $patterns = @(
        "${env:ProgramFiles(x86)}\Caphyon\Advanced Installer*\bin\x86\AdvancedInstaller.com",
        "${env:ProgramFiles}\Caphyon\Advanced Installer*\bin\x86\AdvancedInstaller.com"
    )
    foreach ($p in $patterns) {
        $hit = Get-Item $p -ErrorAction SilentlyContinue | Sort-Object { $_.FullName } -Descending | Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    return $null
}

function Remove-AiShortcutQuiet {
    param(
        [Parameter(Mandatory = $true)][string]$AiCom,
        [Parameter(Mandatory = $true)][string]$AipPath,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Dir
    )
    & $AiCom /edit $AipPath /DelShortcut -name $Name -dir $Dir 2>&1 | Out-Null
}

function Update-AiClientMetadata {
    param([Parameter(Mandatory = $true)][string]$AiCom, [Parameter(Mandatory = $true)][string]$AipPath)
    Invoke-AiEdit -AiCom $AiCom -AipPath $AipPath -EditArgs @('/SetProperty', 'ProductName=LF Training Evaluation Client')
    Invoke-AiEdit -AiCom $AiCom -AipPath $AipPath -EditArgs @('/SetProperty', 'ProductVersion=1.0.0')
    Invoke-AiEdit -AiCom $AiCom -AipPath $AipPath -EditArgs @('/SetProperty', 'Manufacturer=Land Forces')
    Invoke-AiEdit -AiCom $AiCom -AipPath $AipPath -EditArgs @('/SetProperty', 'ARPPRODUCTNAME=نظام إدارة التمارين — عميل')
}

function Update-AiClientInstallPaths {
    param([Parameter(Mandatory = $true)][string]$AiCom, [Parameter(Mandatory = $true)][string]$AipPath)
    Invoke-AiEdit -AiCom $AiCom -AipPath $AipPath -EditArgs @(
        '/SetAppdir', '-buildname', 'DefaultBuild', '-path', '[ProgramFiles64Folder][Manufacturer]\[ProductName]'
    )
    Invoke-AiEdit -AiCom $AiCom -AipPath $AipPath -EditArgs @(
        '/SetShortcutdir', '-buildname', 'DefaultBuild', '-path', '[ProgramMenuFolder][ProductName]'
    )
}

function Sync-AiAppDir {
    param(
        [Parameter(Mandatory = $true)][string]$AiCom,
        [Parameter(Mandatory = $true)][string]$AipPath,
        [Parameter(Mandatory = $true)][string]$StagePath
    )
    & $AiCom /edit $AipPath /NewSync APPDIR $StagePath -existingfiles delete
    if ($LASTEXITCODE -ne 0) {
        & $AiCom /edit $AipPath /ResetSync APPDIR -clearcontent
        & $AiCom /edit $AipPath /NewSync APPDIR $StagePath -existingfiles delete
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Could not sync client staging into installer project: $StagePath"
        }
    }
    & $AiCom /edit $AipPath /RefreshSync APPDIR
    if ($LASTEXITCODE -ne 0) {
        Write-Error "RefreshSync APPDIR failed."
    }
}

function Ensure-AiClientShortcuts {
    param(
        [Parameter(Mandatory = $true)][string]$AiCom,
        [Parameter(Mandatory = $true)][string]$AipPath
    )
    $target = 'APPDIR\LF_TrainingEvaluation_Client.exe'
    $oldNames = @(
        'LF Training Evaluation Client',
        'Open LF Training Evaluation Client'
    )
    foreach ($dir in @('DesktopFolder', 'SHORTCUTDIR', 'APPDIR')) {
        foreach ($name in $oldNames) {
            Remove-AiShortcutQuiet -AiCom $AiCom -AipPath $AipPath -Name $name -Dir $dir
        }
    }
    foreach ($entry in @(
            @{ Name = 'LF Training Evaluation Client'; Dir = 'DesktopFolder' },
            @{ Name = 'LF Training Evaluation Client'; Dir = 'SHORTCUTDIR' },
            @{ Name = 'Open LF Training Evaluation Client'; Dir = 'APPDIR' }
        )) {
        Invoke-AiEdit -AiCom $AiCom -AipPath $AipPath -EditArgs @(
            '/NewShortcut',
            '-name', $entry.Name,
            '-dir', $entry.Dir,
            '-target', $target,
            '-wkdir', 'APPDIR',
            '-desc', 'Open LF Training Evaluation (client)'
        )
    }
}

function Copy-SetupExeSafe {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Dest
    )
    $destDir = Split-Path $Dest -Parent
    if (-not (Test-Path $destDir)) {
        New-Item -ItemType Directory -Path $destDir -Force | Out-Null
    }
    $altDest = [System.IO.Path]::ChangeExtension($Dest, ".new.exe")
    if (Test-Path $altDest) { Remove-Item $altDest -Force -ErrorAction SilentlyContinue }
    try {
        Copy-Item -LiteralPath $Source -Destination $altDest -Force
        if (Test-Path $Dest) {
            Remove-Item -LiteralPath $Dest -Force -ErrorAction Stop
        }
        Rename-Item -LiteralPath $altDest -NewName (Split-Path $Dest -Leaf) -Force
        return $Dest
    } catch {
        Write-Host ""
        Write-Host "  WARNING: Could not replace locked installer:" -ForegroundColor Yellow
        Write-Host "    $Dest" -ForegroundColor Yellow
        Write-Host "  Close any running setup, then use:" -ForegroundColor Yellow
        Write-Host "    $altDest" -ForegroundColor Yellow
        return $altDest
    }
}

Write-Host "[1/4] PyInstaller — client launcher..." -ForegroundColor Cyan
& $VenvPy -m pip install -q -r (Join-Path $Root "requirements-build.txt")
& $VenvPy -m PyInstaller --noconfirm --clean (Join-Path $Root "packaging\lf_client.spec")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$ClientExe = Join-Path $Root "dist\LF_TrainingEvaluation_Client.exe"
if (-not (Test-Path $ClientExe)) {
    Write-Error "Client launcher was not created: $ClientExe"
}

Write-Host "[2/4] Staging client files..." -ForegroundColor Cyan
$Stage = Join-Path $Root "packaging\client_staging_dist"
if (Test-Path $Stage) { Remove-Item $Stage -Recurse -Force }
New-Item -ItemType Directory -Path $Stage | Out-Null
Copy-Item $ClientExe $Stage -Force
Copy-Item (Join-Path $Root "packaging\client_staging\client.ini") $Stage -Force

$AI = Find-AdvancedInstallerCom
if (-not $AI) {
    Write-Error "Advanced Installer is required for the client setup. Install from https://www.advancedinstaller.com/download.html"
}

Write-Host "[3/4] Advanced Installer — client project..." -ForegroundColor Cyan
New-Item -ItemType Directory -Path $AIDir -Force | Out-Null
if (-not (Test-Path $AIP)) {
    & $AI /newproject $AIP -type "professional" -lang "en" -overwrite
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Invoke-AiEdit -AiCom $AI -AipPath $AIP -EditArgs @('/SetPackageType', 'x64')
    Invoke-AiEdit -AiCom $AI -AipPath $AIP -EditArgs @('/SetOutputType', 'ExeInside', '-buildname', 'DefaultBuild')
    Write-Host "  Created $AIP (ExeInside)." -ForegroundColor DarkYellow
}
Update-AiClientMetadata -AiCom $AI -AipPath $AIP
Update-AiClientInstallPaths -AiCom $AI -AipPath $AIP
Sync-AiAppDir -AiCom $AI -AipPath $AIP -StagePath $Stage
Ensure-AiClientShortcuts -AiCom $AI -AipPath $AIP

Write-Host "[4/4] Advanced Installer — build client setup.exe..." -ForegroundColor Cyan
& $AI /edit $AIP /SetOutputType ExeInside -buildname DefaultBuild
& $AI /rebuild $AIP
if ($LASTEXITCODE -ne 0) {
    Write-Error "Advanced Installer client build failed."
}

$SetupFilesDir = Join-Path $AIDir "LF_TrainingEvaluation_Client-SetupFiles"
$OutExe = Get-ChildItem -Path $SetupFilesDir -Filter "*.exe" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $OutExe) {
    Write-Error "No client setup EXE from Advanced Installer."
}
$copiedTo = Copy-SetupExeSafe -Source $OutExe.FullName -Dest $FinalSetup
Write-Host ""
Write-Host "  Client installer: $copiedTo"
Write-Host "  Size: $([math]::Round((Get-Item $copiedTo).Length / 1MB, 1)) MB"
Write-Host ""
Write-Host "  Install path: Program Files\Land Forces\LF Training Evaluation Client\"
Write-Host "  Edit client.ini after install: set host=SERVER_IP"
Write-Host "  Desktop shortcut opens: http://SERVER_IP:8005/"
