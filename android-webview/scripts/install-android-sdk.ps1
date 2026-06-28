$ErrorActionPreference = "Stop"
$sdkRoot = Join-Path $env:LOCALAPPDATA "Android\Sdk"
$cmdToolsDir = Join-Path $sdkRoot "cmdline-tools\latest"
$sdkManager = Join-Path $cmdToolsDir "bin\sdkmanager.bat"

if (-not (Test-Path $sdkManager)) {
    Write-Host "Installing Android command-line tools into $sdkRoot"
    New-Item -ItemType Directory -Force -Path (Split-Path $cmdToolsDir -Parent) | Out-Null
    $zipPath = Join-Path $env:TEMP ("android-cmdline-tools-" + [guid]::NewGuid().ToString() + ".zip")
    $url = "https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip"
    Invoke-WebRequest -Uri $url -OutFile $zipPath -UseBasicParsing
    $extractRoot = Join-Path $env:TEMP "android-cmdline-tools"
    if (Test-Path $extractRoot) { Remove-Item $extractRoot -Recurse -Force }
    Expand-Archive -Path $zipPath -DestinationPath $extractRoot -Force
    New-Item -ItemType Directory -Force -Path $cmdToolsDir | Out-Null
    Copy-Item -Path (Join-Path $extractRoot "cmdline-tools\*") -Destination $cmdToolsDir -Recurse -Force
}

$env:ANDROID_HOME = $sdkRoot
$env:ANDROID_SDK_ROOT = $sdkRoot

Write-Host "Accepting SDK licenses..."
1..80 | ForEach-Object { "y" } | & $sdkManager --sdk_root=$sdkRoot --licenses

Write-Host "Installing platform-tools, android-34, build-tools..."
& $sdkManager --sdk_root=$sdkRoot "platform-tools" "platforms;android-34" "build-tools;34.0.0"

Write-Host "Done. ANDROID_HOME=$sdkRoot"
