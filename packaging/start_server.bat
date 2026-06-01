@echo off
chcp 65001 >nul
cd /d "%~dp0.."
title LF Training Evaluation Server — LAN / Wi-Fi

if not exist ".venv\Scripts\python.exe" (
  echo.
  echo لم يُنصَّب النظام بعد. شغّل أولاً: INSTALL.bat
  echo   أو: packaging\install.bat
  echo.
  pause
  exit /b 1
)

rem الإعدادات الافتراضية — يُكمّلها ملف .env في جذر المشروع
if not defined LF_INSTALL_MODE set LF_INSTALL_MODE=1
if not defined FLASK_DEBUG set FLASK_DEBUG=0
if not defined LF_OPEN_BROWSER set LF_OPEN_BROWSER=1
if not defined PORT set PORT=8005
if not defined HOST set HOST=0.0.0.0
if not defined WAITRESS_THREADS set WAITRESS_THREADS=16

echo.
echo ============================================================
echo   تشغيل الخادم — LAN / Wi-Fi
echo   لإيقافه: أغلق هذه النافذة أو اضغط Ctrl+C
echo ============================================================
echo   السيرفر: متصفح على هذا الجهاز
echo   العملاء: متصفح فقط — بدون تنصيب — نفس الشبكة أو Wi-Fi
echo ============================================================
echo.

".venv\Scripts\python.exe" "packaging\app_main.py"
pause
