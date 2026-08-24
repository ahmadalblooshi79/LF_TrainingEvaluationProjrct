@echo off
REM Build Judge Tablet APK v2.7.4 (eval list two-line title)
set PATH=%~dp0tools\flutter\bin;%PATH%
cd /d "%~dp0flutter_app"
call flutter build apk --release --flavor tablet --dart-define=LF_PRODUCT=tablet --dart-define=LF_APP_VERSION=2.7.4 --build-name=2.7.4 --build-number=13
if errorlevel 1 exit /b 1
if not exist "%~dp0dist" mkdir "%~dp0dist"
copy /Y "build\app\outputs\flutter-apk\app-tablet-release.apk" "%~dp0dist\judge-tablet-v2.7.4.apk"
echo.
echo Built: dist\judge-tablet-v2.7.4.apk
echo Package: ae.lf.training.lf_training_evaluation
echo Version: 2.7.4+13
