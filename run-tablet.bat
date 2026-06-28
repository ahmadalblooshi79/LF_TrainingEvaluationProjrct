@echo off
chcp 65001 >nul
cd /d "%~dp0"
REM تشغيل Flask للتابلت على المنفذ 8005 مع الاستماع على كل الواجهات (LAN/Wi-Fi)
set PORT=8005
set HOST=0.0.0.0
set LF_OPEN_BROWSER=0
if exist ".venv\Scripts\python.exe" (
  echo.
  echo  تشغيل السيرفر للتابلت على المنفذ %PORT%
  echo  استخدم عنوان LAN الذي يظهر أدناه في تطبيق Android
  echo.
  ".venv\Scripts\python.exe" run.py
) else (
  echo [خطأ] لم يُعثر على .venv\Scripts\python.exe
  exit /b 1
)
