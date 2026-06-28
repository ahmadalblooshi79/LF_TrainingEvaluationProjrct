@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo [1/2] إنشاء حزمة التوزيع...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0create_distribution.ps1"
if errorlevel 1 exit /b 1

echo.
echo [2/2] بناء ملف التثبيت Setup.exe...
set ISCC=
for %%P in (
  "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
  "C:\Program Files\Inno Setup 6\ISCC.exe"
) do if exist %%P set ISCC=%%~P

if not defined ISCC (
  echo.
  echo [تنبيه] Inno Setup غير مثبت — الحزمة جاهزة في dist\LF_TrainingEvaluation_Server.zip
  echo ثبّت Inno Setup 6 ثم أعد تشغيل هذا الملف لإنشاء Setup.exe
  pause
  exit /b 0
)

"%ISCC%" "%~dp0LF_Server_Setup.iss"
if errorlevel 1 (
  echo [فشل بناء Setup]
  pause
  exit /b 1
)

echo.
echo تم: dist\LF_TrainingEvaluation_Server_Setup.exe
pause
