@echo off
chcp 65001 >nul
cd /d "%~dp0\.."
REM تثبيت خدمة Windows لتشغيل Flask تلقائياً عند بدء النظام (يتطلب تشغيل كمسؤول)
set SERVICE_NAME=LFTrainingEvaluationServer
set PYTHON_EXE=%~dp0..\..\.venv\Scripts\python.exe
set RUNNER=%~dp0lf_service_runner.py
if not exist "%PYTHON_EXE%" (
  echo [خطأ] لم يُعثر على .venv — أنشئ البيئة أولاً.
  exit /b 1
)
sc create %SERVICE_NAME% binPath= "\"%PYTHON_EXE%\" \"%RUNNER%\"" start= auto DisplayName= "LF Training Evaluation Server"
sc description %SERVICE_NAME% "Flask server for LF Training Evaluation — WiFi tablets"
sc start %SERVICE_NAME%
echo.
echo تم إنشاء الخدمة %SERVICE_NAME%
echo لإزالتها: sc stop %SERVICE_NAME% ^&^& sc delete %SERVICE_NAME%
pause
