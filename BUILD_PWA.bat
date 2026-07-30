@echo off
setlocal
cd /d "%~dp0"

echo Building Judge Tablet PWA (Flutter Web)...
echo.

where flutter >nul 2>&1
if errorlevel 1 (
  echo ERROR: Flutter is not in PATH.
  exit /b 1
)

cd flutter_app
call flutter pub get
if errorlevel 1 exit /b 1

REM Same-origin under Flask /tablet/
call flutter build web --release --base-href /tablet/
if errorlevel 1 (
  echo ERROR: flutter build web failed.
  exit /b 1
)

cd ..
if not exist "dist" mkdir dist
if exist "dist\tablet_pwa" rmdir /s /q "dist\tablet_pwa"
xcopy /e /i /y "flutter_app\build\web\*" "dist\tablet_pwa\" >nul
if errorlevel 1 (
  echo ERROR: failed to copy PWA to dist\tablet_pwa
  exit /b 1
)

echo.
echo PWA built successfully.
echo   Source: flutter_app\build\web
echo   Dist:   dist\tablet_pwa
echo.
echo Start the server (run.bat), then open:
echo   http://127.0.0.1:PORT/tablet/
echo.
exit /b 0
