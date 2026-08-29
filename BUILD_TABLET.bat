@echo off

REM Build Judge Tablet APK v2.7.10 (action-eval slot_id fix)

set PATH=%~dp0tools\flutter\bin;%PATH%

cd /d "%~dp0flutter_app"

call flutter build apk --release --flavor tablet --dart-define=LF_PRODUCT=tablet --dart-define=LF_APP_VERSION=2.7.10 --build-name=2.7.10 --build-number=24

if errorlevel 1 exit /b 1

if not exist "%~dp0dist" mkdir "%~dp0dist"

copy /Y "build\app\outputs\flutter-apk\app-tablet-release.apk" "%~dp0dist\judge-tablet-v2.7.10.apk"

echo.

echo Built: dist\judge-tablet-v2.7.10.apk

echo Package: ae.lf.training.lf_training_evaluation

echo Version: 2.7.10+24
