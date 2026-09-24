@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo [INFO] Stop the running system before updating.
echo [INFO] This updates program files only and keeps local exercise data.

set "VENV_PY=.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
  echo [ERROR] .venv not found. Run run.bat once first.
  exit /b 1
)

"%VENV_PY%" scripts\update_from_github.py
exit /b %ERRORLEVEL%
