@echo off
setlocal
cd /d "%~dp0"
set "JAVA_HOME=C:\Program Files\Android\Android Studio\jbr"
set "PATH=%JAVA_HOME%\bin;%PATH%"

set "SDK=%LOCALAPPDATA%\Android\Sdk"
if not exist "local.properties" (
  echo sdk.dir=%SDK:\=\\%> local.properties
)

REM استخدم gradle من Android Studio إن وُجد، وإلا حمّل الـ wrapper
set "STUDIO_GRADLE="
for /d %%D in ("C:\Program Files\Android\Android Studio\gradle\*") do set "STUDIO_GRADLE=%%D"

if not exist "gradle\wrapper" mkdir "gradle\wrapper"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ver='8.9'; $zip=\"$env:TEMP\gradle-$ver-bin.zip\"; $url=\"https://services.gradle.org/distributions/gradle-$ver-bin.zip\"; if (-not (Test-Path $zip)) { Invoke-WebRequest -Uri $url -OutFile $zip }; $dest=\"$env:TEMP\gradle-$ver\"; if (-not (Test-Path \"$dest\bin\gradle.bat\")) { Expand-Archive -Path $zip -DestinationPath $env:TEMP -Force }; & \"$dest\bin\gradle.bat\" wrapper --gradle-version $ver"

if errorlevel 1 (
  echo [ERROR] Failed to generate Gradle wrapper
  exit /b 1
)
echo [OK] Gradle wrapper ready
endlocal
