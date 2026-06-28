@echo off
chcp 65001 >nul
cd /d "%~dp0\.."
title نظام التحليل الذكي — السيرفر

set PORT=8005
set HOST=0.0.0.0
set LF_OPEN_BROWSER=0

if not exist ".venv\Scripts\python.exe" (
  echo [خطأ] لم يُثبَّت السيرفر بعد. شغّل installer\INSTALL_SERVER.bat أولاً.
  pause
  exit /b 1
)

echo.
echo  تشغيل السيرفر على المنفذ %PORT% ...
echo  عنوان LAN يظهر أدناه — عيّنه في تطبيق التابلت.
echo  لإيقاف السيرفر: Ctrl+C
echo.

".venv\Scripts\python.exe" run.py
if errorlevel 1 pause
