@echo off
chcp 65001 >nul
cd /d "%~dp0.."
title LF Training Evaluation Server

if not exist ".venv\Scripts\python.exe" (
  echo لم يُنصَّب النظام بعد. شغّل أولاً: packaging\install.bat
  pause
  exit /b 1
)

set LF_INSTALL_MODE=1
set FLASK_DEBUG=0
set LF_OPEN_BROWSER=1
set PORT=8005
set HOST=0.0.0.0

echo.
echo تشغيل الخادم — لإيقافه أغلق هذه النافذة أو اضغط Ctrl+C
echo.

".venv\Scripts\python.exe" "packaging\app_main.py"
pause
