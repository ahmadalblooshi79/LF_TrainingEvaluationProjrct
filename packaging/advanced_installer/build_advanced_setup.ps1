#Requires -Version 5.1
<#
  Build LF_TrainingEvaluation_Setup.exe (PyInstaller + Advanced Installer).
  Fallback: 7-Zip SFX when Advanced Installer is not installed.

  Run from project root: BUILD_ADVANCED_SETUP.bat

  Note: Console output is English only — Arabic RTL breaks in Windows PowerShell.
#>
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root

$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    Write-Error "Missing .venv under $Root — create it, then: pip install -r requirements-build.txt"
}

$FinalSetup = Join-Path $Root "dist\LF_TrainingEvaluation_Setup.exe"
$SfxConfig = Join-Path $Root "packaging\sfx_install.txt"

function Find-SevenZip {
    $candidates = @(
        "${env:ProgramFiles}\7-Zip\7z.exe",
        "${env:ProgramFiles(x86)}\7-Zip\7z.exe"
    )
    foreach ($p in $candidates) {
        if (Test-Path $p) { return $p }
    }
    return $null
}

function Build-SfxSetupExe {
    param(
        [Parameter(Mandatory = $true)][string]$SourceDir,
        [Parameter(Mandatory = $true)][string]$OutputExe,
        [Parameter(Mandatory = $true)][string]$SfxConfigPath
    )
    $SevenZip = Find-SevenZip
    if (-not $SevenZip) {
        Write-Error "Install 7-Zip from https://www.7-zip.org/ to build LF_TrainingEvaluation_Setup.exe"
    }
    $SfxModule = Join-Path (Split-Path $SevenZip) "7zSD.sfx"
    if (-not (Test-Path $SfxModule)) {
        Write-Error "7zSD.sfx not found next to 7z.exe"
    }
    if (-not (Test-Path $SfxConfigPath)) {
        Write-Error "SFX config missing: $SfxConfigPath"
    }

    $Archive = [System.IO.Path]::ChangeExtension($OutputExe, ".7z")
    if (Test-Path $Archive) { Remove-Item $Archive -Force }
    if (Test-Path $OutputExe) { Remove-Item $OutputExe -Force }

    Write-Host "  7-Zip archive..." -ForegroundColor DarkGray
    & $SevenZip a -t7z -mx=9 $Archive (Join-Path $SourceDir "*")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "  Merging SFX..." -ForegroundColor DarkGray
    $fs = [System.IO.File]::Open($OutputExe, [System.IO.FileMode]::Create)
    try {
        foreach ($part in @($SfxModule, $SfxConfigPath, $Archive)) {
            $bytes = [System.IO.File]::ReadAllBytes($part)
            $fs.Write($bytes, 0, $bytes.Length)
        }
    } finally {
        $fs.Close()
    }
    if (Test-Path $Archive) { Remove-Item $Archive -Force }
}

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

function Update-AiInstallPaths {
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
    # NewSync (not AddFolder): embeds staged PyInstaller output into APPDIR.
    & $AiCom /edit $AipPath /NewSync APPDIR $StagePath -existingfiles delete
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  Resetting APPDIR sync and retrying..." -ForegroundColor DarkGray
        & $AiCom /edit $AipPath /ResetSync APPDIR -clearcontent
        & $AiCom /edit $AipPath /NewSync APPDIR $StagePath -existingfiles delete
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Could not sync staging folder into installer project: $StagePath"
        }
    }
    & $AiCom /edit $AipPath /RefreshSync APPDIR
    if ($LASTEXITCODE -ne 0) {
        Write-Error "RefreshSync APPDIR failed."
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
        Write-Host "  Close any running setup/antivirus scan, then use:" -ForegroundColor Yellow
        Write-Host "    $altDest" -ForegroundColor Yellow
        return $altDest
    }
}

function Update-AiProductMetadata {
    param([Parameter(Mandatory = $true)][string]$AiCom, [Parameter(Mandatory = $true)][string]$AipPath)
    Invoke-AiEdit -AiCom $AiCom -AipPath $AipPath -EditArgs @('/SetProperty', 'ProductName=LF Training Evaluation')
    Invoke-AiEdit -AiCom $AiCom -AipPath $AipPath -EditArgs @('/SetProperty', 'ProductVersion=1.0.0')
    Invoke-AiEdit -AiCom $AiCom -AipPath $AipPath -EditArgs @('/SetProperty', 'Manufacturer=Land Forces')
    # Arabic product name for Windows UI only (stored in .aip, not printed here)
    Invoke-AiEdit -AiCom $AiCom -AipPath $AipPath -EditArgs @('/SetProperty', 'ARPPRODUCTNAME=نظام إدارة التمارين')
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

function Ensure-AiServerShortcuts {
    param(
        [Parameter(Mandatory = $true)][string]$AiCom,
        [Parameter(Mandatory = $true)][string]$AipPath
    )
    $target = 'APPDIR\LF_TrainingEvaluation_Open.exe'
    $oldNames = @(
        'LF Training Evaluation',
        'Open LF Training Evaluation',
        'LF Training Server',
        'Start Server (Console)'
    )
    foreach ($dir in @('DesktopFolder', 'SHORTCUTDIR', 'APPDIR')) {
        foreach ($name in $oldNames) {
            Remove-AiShortcutQuiet -AiCom $AiCom -AipPath $AipPath -Name $name -Dir $dir
        }
    }
    foreach ($entry in @(
            @{ Name = 'LF Training Evaluation'; Dir = 'DesktopFolder' },
            @{ Name = 'LF Training Evaluation'; Dir = 'SHORTCUTDIR' },
            @{ Name = 'Open LF Training Evaluation'; Dir = 'APPDIR' }
        )) {
        Invoke-AiEdit -AiCom $AiCom -AipPath $AipPath -EditArgs @(
            '/NewShortcut',
            '-name', $entry.Name,
            '-dir', $entry.Dir,
            '-target', $target,
            '-wkdir', 'APPDIR',
            '-desc', 'Open LF Training Evaluation'
        )
    }
}

Write-Host "[1/5] PyInstaller — server bundle..." -ForegroundColor Cyan
& $VenvPy -m pip install -q -r (Join-Path $Root "requirements-build.txt")
& $VenvPy -m PyInstaller --noconfirm --clean (Join-Path $Root "packaging\lf_server.spec")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$DistServer = Join-Path $Root "dist\LF_TrainingEvaluation_Server"
$ServerExe = Join-Path $DistServer "LF_TrainingEvaluation_Server.exe"
if (-not (Test-Path $ServerExe)) {
    Write-Error "Server exe was not created: $ServerExe"
}

Write-Host "  PyInstaller — open launcher..." -ForegroundColor DarkGray
& $VenvPy -m PyInstaller --noconfirm --clean (Join-Path $Root "packaging\lf_open_system.spec")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$OpenExe = Join-Path $Root "dist\LF_TrainingEvaluation_Open.exe"
if (-not (Test-Path $OpenExe)) {
    Write-Error "Open launcher was not created: $OpenExe"
}

Write-Host "[2/5] Staging install files..." -ForegroundColor Cyan
$Stage = Join-Path $Root "packaging\staging"
if (Test-Path $Stage) { Remove-Item $Stage -Recurse -Force }
New-Item -ItemType Directory -Path $Stage | Out-Null
Copy-Item -Path (Join-Path $DistServer "*") -Destination $Stage -Recurse -Force
Copy-Item $OpenExe $Stage -Force
Copy-Item (Join-Path $Root "packaging\server_staging\START_SERVER.bat") $Stage -Force
Copy-Item (Join-Path $Root "packaging\server_staging\ADD_FIREWALL_RULE.bat") $Stage -Force
New-Item -ItemType Directory -Path (Join-Path $Stage "scripts\server") -Force | Out-Null
Copy-Item (Join-Path $Root "scripts\server\add_firewall_rule.ps1") (Join-Path $Stage "scripts\server\") -Force

$AIP = Join-Path $Root "packaging\advanced_installer\LF_TrainingEvaluation.aip"
$AIDir = Split-Path $AIP
New-Item -ItemType Directory -Path $AIDir -Force | Out-Null

$AI = Find-AdvancedInstallerCom
if (-not $AI) {
    Write-Host ""
    Write-Host "[3/5] Advanced Installer not found — SFX fallback..." -ForegroundColor Yellow
    Build-SfxSetupExe -SourceDir $Stage -OutputExe $FinalSetup -SfxConfigPath $SfxConfig
    Write-Host "[4/5] (skipped)" -ForegroundColor DarkGray
    Write-Host "[5/5] Done (SFX)." -ForegroundColor Green
    Write-Host ""
    Write-Host "  Installer: $FinalSetup"
    Write-Host "  Size: $([math]::Round((Get-Item $FinalSetup).Length / 1MB, 1)) MB"
    Write-Host ""
    Write-Host "  Install Advanced Installer: https://www.advancedinstaller.com/download.html"
    Write-Host "  Server bundle: $ServerExe"
    exit 0
}

Write-Host "[3/5] Advanced Installer — project..." -ForegroundColor Cyan
if (-not (Test-Path $AIP)) {
    & $AI /newproject $AIP -type "professional" -lang "en" -overwrite
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Invoke-AiEdit -AiCom $AI -AipPath $AIP -EditArgs @('/SetPackageType', 'x64')
    Invoke-AiEdit -AiCom $AI -AipPath $AIP -EditArgs @('/SetOutputType', 'ExeInside', '-buildname', 'DefaultBuild')
    Write-Host "  Created $AIP (ExeInside)." -ForegroundColor DarkYellow
} else {
    Write-Host "  Syncing staged files into APPDIR..." -ForegroundColor DarkGray
}
Update-AiProductMetadata -AiCom $AI -AipPath $AIP
Update-AiInstallPaths -AiCom $AI -AipPath $AIP
$stageFiles = @(Get-ChildItem -Path $Stage -Recurse -File -ErrorAction SilentlyContinue)
if ($stageFiles.Count -lt 1) {
    Write-Error "Staging folder is empty: $Stage"
}
Write-Host "  Staged $($stageFiles.Count) file(s)." -ForegroundColor DarkGray
Sync-AiAppDir -AiCom $AI -AipPath $AIP -StagePath $Stage
Ensure-AiServerShortcuts -AiCom $AI -AipPath $AIP

Write-Host "[4/5] Advanced Installer — build setup.exe..." -ForegroundColor Cyan
& $AI /edit $AIP /SetOutputType ExeInside -buildname DefaultBuild
& $AI /rebuild $AIP
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Advanced Installer build failed — SFX fallback..." -ForegroundColor Yellow
    Build-SfxSetupExe -SourceDir $Stage -OutputExe $FinalSetup -SfxConfigPath $SfxConfig
    Write-Host "  Installer: $FinalSetup"
    exit 0
}

Write-Host "[5/5] Done." -ForegroundColor Green
$SetupFilesDir = Join-Path $AIDir "LF_TrainingEvaluation-SetupFiles"
$OutExe = Get-ChildItem -Path $SetupFilesDir -Filter "*.exe" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $OutExe) {
    $OutExe = Get-ChildItem -Path $AIDir -Filter "*.exe" -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -notmatch '\\staging\\' } |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
}
if ($OutExe) {
    $copiedTo = Copy-SetupExeSafe -Source $OutExe.FullName -Dest $FinalSetup
    Write-Host ""
    Write-Host "  Installer: $copiedTo"
    Write-Host "  Size: $([math]::Round((Get-Item $copiedTo).Length / 1MB, 1)) MB"
} else {
    Write-Host "  No EXE from Advanced Installer — SFX fallback..." -ForegroundColor Yellow
    Build-SfxSetupExe -SourceDir $Stage -OutputExe $FinalSetup -SfxConfigPath $SfxConfig
    Write-Host ""
    Write-Host "  Installer: $FinalSetup"
    Write-Host "  Size: $([math]::Round((Get-Item $FinalSetup).Length / 1MB, 1)) MB"
    Write-Host "  Tip: enable EXE Setup in Advanced Installer > Media for AI builds."
}
Write-Host ""
Write-Host "  Install path: Program Files\Land Forces\LF Training Evaluation\"
Write-Host "  Desktop shortcut: LF Training Evaluation -> LF_TrainingEvaluation_Open.exe"
Write-Host "  After install: server listens on 0.0.0.0 (Ethernet + Wi-Fi)."
Write-Host "  Data folder: %LOCALAPPDATA%\LF_TrainingEvaluation\"
Write-Host "  If an old empty 'Your Application' install exists, uninstall it first."
