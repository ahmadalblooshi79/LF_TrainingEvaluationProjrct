@echo off
setlocal
cd /d "%~dp0"

set "PROJECT=android\judge-tablet"
set "OUT=dist"

if not exist "%PROJECT%\gradlew.bat" (
  echo [INFO] Generating Gradle wrapper...
  where gradle >nul 2>&1
  if errorlevel 1 (
    echo [ERROR] Gradle not found. Install Android Studio or Gradle, then re-run.
    exit /b 1
  )
  pushd "%PROJECT%"
  gradle wrapper --gradle-version 8.7
  popd
)

echo [INFO] Building installable debug APK (signed)...
pushd "%PROJECT%"
call gradlew.bat assembleDebug --no-daemon
set "RC=%ERRORLEVEL%"
popd
if not "%RC%"=="0" (
  echo [ERROR] Gradle build failed with code %RC%
  exit /b %RC%
)

if not exist "%OUT%" mkdir "%OUT%"
set "APK=%PROJECT%\app\build\outputs\apk\debug\app-debug.apk"
if not exist "%APK%" (
  echo [ERROR] APK not found: %APK%
  exit /b 1
)
copy /Y "%APK%" "%OUT%\LF_Judge_Tablet.apk" >nul
echo [OK] APK ready: %OUT%\LF_Judge_Tablet.apk
exit /b 0
