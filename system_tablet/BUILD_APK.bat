@echo off
setlocal
cd /d "%~dp0"

set "JAVA_HOME=C:\Program Files\Android\Android Studio\jbr"
set "PATH=%JAVA_HOME%\bin;%PATH%"

if not exist "gradle\wrapper\gradle-wrapper.jar" (
  echo [INFO] Preparing Gradle Wrapper...
  call "%~dp0setup_gradle_wrapper.bat" || exit /b 1
)

echo [INFO] Building System Tablet debug APK...
call gradlew.bat assembleDebug --no-daemon
if errorlevel 1 exit /b 1

set "OUT=app\build\outputs\apk\debug\app-debug.apk"
set "DIST=%~dp0..\dist"
if not exist "%DIST%" mkdir "%DIST%"
copy /Y "%OUT%" "%DIST%\system-tablet-v1.0.0.apk" >nul
echo.
echo [OK] APK: %DIST%\system-tablet-v1.0.0.apk
echo Package: com.lf.systemtablet
endlocal
