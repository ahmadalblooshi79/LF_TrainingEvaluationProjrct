@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0\.."

set "VENV_PY=.venv\Scripts\python.exe"
set "VENV_PIP=.venv\Scripts\pip.exe"

if not exist "%VENV_PY%" (
  echo [خطأ] لم يُعثر على البيئة الافتراضية .venv
  echo أنشئها أولاً ثم ثبّت المتطلبات:
  echo   py -3.14 -m venv .venv
  echo   .venv\Scripts\pip install -r requirements.txt
  pause
  exit /b 1
)

echo [1/3] تثبيت أدوات البناء...
"%VENV_PIP%" install -q -r requirements.txt -r installer\requirements-build.txt
if errorlevel 1 (
  echo [فشل تثبيت المتطلبات]
  pause
  exit /b 1
)

echo.
echo [2/3] بناء حزمة PyInstaller...
"%VENV_PY%" -m PyInstaller installer\LF_TrainingEvaluation.spec --noconfirm --clean
if errorlevel 1 (
  echo [فشل PyInstaller]
  pause
  exit /b 1
)

if not exist "dist\LF_TrainingEvaluation_Server\LF_TrainingEvaluation_Server.exe" (
  echo [خطأ] لم يُنشأ الملف التنفيذي المتوقع.
  pause
  exit /b 1
)

echo.
echo تم إنشاء الحزمة:
echo   dist\LF_TrainingEvaluation_Server\
echo   dist\LF_TrainingEvaluation_Server\LF_TrainingEvaluation_Server.exe
echo.

echo [3/3] بناء ملف التثبيت Setup.exe...
set "ISCC="
for %%P in (
  "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
  "C:\Program Files\Inno Setup 6\ISCC.exe"
) do if exist %%P set "ISCC=%%~P"

if not defined ISCC (
  echo.
  echo [تنبيه] Inno Setup غير مثبت — الحزمة جاهزة للتشغيل المباشر من المجلد أعلاه.
  echo لإنشاء Setup.exe ثبّت Inno Setup 6 ثم أعد تشغيل هذا الملف:
  echo   https://jrsoftware.org/isinfo.php
  pause
  exit /b 0
)

"%ISCC%" "installer\LF_Desktop_Setup.iss"
if errorlevel 1 (
  echo [فشل بناء Setup]
  pause
  exit /b 1
)

echo.
echo ============================================
echo  اكتمل البناء
echo ============================================
echo  ملف التثبيت: dist\LF_TrainingEvaluation_Desktop_Setup.exe
echo  للتجربة المحلية: dist\LF_TrainingEvaluation_Server\LF_TrainingEvaluation_Server.exe
echo ============================================
pause
