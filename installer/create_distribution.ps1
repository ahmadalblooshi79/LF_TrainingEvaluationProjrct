#Requires -Version 5.1
<#
  إنشاء حزمة توزيع جاهزة للتثبيت (مجلد + ملف ZIP).
  الاستخدام: powershell -File installer\create_distribution.ps1
#>
$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$DistName = "LF_TrainingEvaluation_Server"
$OutDir = Join-Path $ProjectRoot "dist\$DistName"
$ZipPath = Join-Path $ProjectRoot "dist\$DistName.zip"

$ExcludeDirs = @(
    ".git", ".venv", "__pycache__", ".cursor", "node_modules",
    "android-webview\.gradle", "android-webview\app\build",
    "android-webview\build", "dist", ".idea"
)

function Should-Skip([string]$RelativePath) {
    $norm = $RelativePath -replace '\\', '/'
    foreach ($ex in $ExcludeDirs) {
        $exNorm = $ex -replace '\\', '/'
        if ($norm -eq $exNorm -or $norm.StartsWith("$exNorm/")) { return $true }
    }
    if ($norm -match '\.pyc$') { return $true }
    if ($norm -match 'exercises\.db-wal$|exercises\.db-shm$') { return $true }
    return $false
}

Write-Host "إنشاء حزمة التوزيع في: $OutDir"

if (Test-Path $OutDir) { Remove-Item $OutDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

Get-ChildItem -Path $ProjectRoot -Force | ForEach-Object {
    $rel = $_.Name
    if (Should-Skip $rel) { return }
    $dest = Join-Path $OutDir $rel
    if ($_.PSIsContainer) {
        Copy-Item -Path $_.FullName -Destination $dest -Recurse -Force
    } else {
        Copy-Item -Path $_.FullName -Destination $dest -Force
    }
}

# تنظيف داخل المجلدات المنسوخة
Get-ChildItem -Path $OutDir -Recurse -Directory -Force | ForEach-Object {
    $rel = $_.FullName.Substring($OutDir.Length + 1)
    if (Should-Skip $rel) {
        Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
    }
}

if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
Compress-Archive -Path $OutDir -DestinationPath $ZipPath -Force

Write-Host ""
Write-Host "تم إنشاء:" -ForegroundColor Green
Write-Host "  $OutDir"
Write-Host "  $ZipPath"
Write-Host ""
Write-Host "للتثبيت على جهاز آخر: فك الضغط ثم شغّل INSTALL_SERVER.bat"
