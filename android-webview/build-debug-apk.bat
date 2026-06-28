@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not defined ANDROID_HOME (
  if exist "%LOCALAPPDATA%\Android\Sdk" (
    set "ANDROID_HOME=%LOCALAPPDATA%\Android\Sdk"
  )
)

if not defined ANDROID_HOME (
  echo [خطأ] لم يُعثر على Android SDK.
  echo ثبّت Android Studio ثم أعد المحاولة، أو عيّن ANDROID_HOME.
  exit /b 1
)

if not exist "gradle\wrapper\gradle-wrapper.jar" (
  echo [خطأ] gradle-wrapper.jar غير موجود. شغّل: powershell -File scripts\fetch-gradle-wrapper.ps1
  exit /b 1
)

call gradlew.bat assembleDebug
if errorlevel 1 exit /b 1

echo.
echo  تم البناء بنجاح:
echo  app\build\outputs\apk\debug\app-debug.apk
echo.
