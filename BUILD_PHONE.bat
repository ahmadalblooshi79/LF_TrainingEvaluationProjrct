@echo off
REM Build Judge Phone APK v1.0 for Samsung S25 Ultra frame (480x1040)
set PATH=%~dp0tools\flutter\bin;%PATH%
cd /d "%~dp0flutter_app"
call flutter build apk --release --flavor phone --dart-define=LF_PRODUCT=phone --dart-define=LF_APP_VERSION=1.0.0 --build-name=1.0.0 --build-number=2
if errorlevel 1 exit /b 1
copy /Y "build\app\outputs\flutter-apk\app-phone-release.apk" "%~dp0dist\judge-phone-v1.0.apk"
echo.
echo Built: dist\judge-phone-v1.0.apk
echo Package: ae.lf.training.lf_training_evaluation.phone
echo Version: 1.0.0 (from tablet 2.7.0 codebase)
