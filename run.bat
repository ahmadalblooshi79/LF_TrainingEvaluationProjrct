@echo off
chcp 65001 >nul
cd /d "%~dp0"
REM تطوير محلي — للسيرفر والشبكة الداخلية استخدم packaging\start_server.bat
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" run.py
) else (
  python run.py
)
