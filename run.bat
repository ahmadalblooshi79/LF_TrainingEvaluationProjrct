@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" run.py
) else (
  echo [خطأ] لم يُعثر على .venv\Scripts\python.exe — أنشئ البيئة الافتراضية أولاً.
  exit /b 1
)
