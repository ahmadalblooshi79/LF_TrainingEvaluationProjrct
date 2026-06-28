#Requires -Version 5.1
<#
  تثبيت سيرفر نظام التحليل الذكي على Windows
  ينشئ بيئة Python، يثبّت المتطلبات، ويُنشئ اختصارات التشغيل.
#>
param(
    [switch]$SkipFirewall,
    [switch]$InstallService
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$InstallerDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $InstallerDir "..")
Set-Location $ProjectRoot

function Write-Step([string]$Msg) {
    Write-Host ""
    Write-Host "==> $Msg" -ForegroundColor Cyan
}

function Find-Python {
    $candidates = @(
        @{ Cmd = "py"; Args = @("-3.14") },
        @{ Cmd = "py"; Args = @("-3.13") },
        @{ Cmd = "py"; Args = @("-3.12") },
        @{ Cmd = "py"; Args = @("-3") },
        @{ Cmd = "python"; Args = @() }
    )
    foreach ($c in $candidates) {
        try {
            $ver = & $c.Cmd @($c.Args + @("-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")) 2>$null
            if ($LASTEXITCODE -eq 0 -and $ver) {
                return @{ Executable = $c.Cmd; Args = $c.Args; Version = $ver.Trim() }
            }
        } catch { }
    }
    return $null
}

Write-Step "التحقق من Python"
$py = Find-Python
if (-not $py) {
    Write-Host "[خطأ] لم يُعثر على Python. ثبّت Python 3.12+ من https://www.python.org/downloads/" -ForegroundColor Red
    exit 1
}
Write-Host "Python $($py.Version) — $($py.Executable) $($py.Args -join ' ')"

Write-Step "إنشاء البيئة الافتراضية .venv"
$venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    $createArgs = @($py.Args + @("-m", "venv", ".venv"))
    & $py.Executable @createArgs
    if ($LASTEXITCODE -ne 0) { throw "فشل إنشاء .venv" }
}

Write-Step "تثبيت المتطلبات"
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r (Join-Path $ProjectRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "فشل pip install" }

Write-Step "إنشاء اختصارات التشغيل"
$startBat = Join-Path $InstallerDir "START_SERVER.bat"
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "نظام التحليل الذكي - السيرفر.lnk"
$wsh = New-Object -ComObject WScript.Shell
$sc = $wsh.CreateShortcut($shortcutPath)
$sc.TargetPath = $startBat
$sc.WorkingDirectory = $ProjectRoot
$sc.Description = "تشغيل سيرفر نظام التحليل الذكي للتابلت"
$sc.Save()
Write-Host "اختصار سطح المكتب: $shortcutPath"

$programs = [Environment]::GetFolderPath("Programs")
$startMenuDir = Join-Path $programs "نظام التحليل الذكي"
New-Item -ItemType Directory -Force -Path $startMenuDir | Out-Null
$smShortcut = Join-Path $startMenuDir "تشغيل السيرفر.lnk"
$sc2 = $wsh.CreateShortcut($smShortcut)
$sc2.TargetPath = $startBat
$sc2.WorkingDirectory = $ProjectRoot
$sc2.Save()

if (-not $SkipFirewall) {
    Write-Step "قاعدة جدار الحماية للمنفذ 8005"
    $ruleName = "LF Training Evaluation Server (TCP 8005)"
    $existing = netsh advfirewall firewall show rule name="$ruleName" 2>$null
    if ($LASTEXITCODE -ne 0) {
        try {
            netsh advfirewall firewall add rule name="$ruleName" dir=in action=allow protocol=TCP localport=8005 | Out-Null
            Write-Host "تمت إضافة قاعدة الجدار."
        } catch {
            Write-Host "تخطّي الجدار (قد تحتاج تشغيل كمسؤول)." -ForegroundColor Yellow
        }
    } else {
        Write-Host "قاعدة الجدار موجودة مسبقاً."
    }
}

if ($InstallService) {
    Write-Step "تثبيت خدمة Windows"
    $svcBat = Join-Path $ProjectRoot "scripts\windows_service\install_service.bat"
    if (Test-Path $svcBat) {
        Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "`"$svcBat`"" -Verb RunAs -Wait
    }
}

Write-Step "عنوان الشبكة المحلية"
try {
    & $venvPython -c "from app.network_util import primary_lan_ipv4; print(primary_lan_ipv4() or 'غير متاح')"
} catch {
    Write-Host "شغّل السيرفر لمعرفة عنوان LAN من نافذة التشغيل."
}

Write-Host ""
Write-Host "اكتمل التثبيت." -ForegroundColor Green
Write-Host "لتشغيل السيرفر: انقر اختصار سطح المكتب أو شغّل installer\START_SERVER.bat"
Write-Host "المنفذ الافتراضي: 8005 — عيّنه في تطبيق التابلت."
Write-Host ""
