@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo  ============================================
echo   تثبيت سيرفر نظام التحليل الذكي
echo  ============================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_server.ps1" %*
if errorlevel 1 (
  echo.
  echo [فشل التثبيت]
  pause
  exit /b 1
)
echo.
pause
