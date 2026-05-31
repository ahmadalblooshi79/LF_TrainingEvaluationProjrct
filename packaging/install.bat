@echo off
cd /d "%~dp0.."
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
if errorlevel 1 (
  echo.
  echo INSTALL FAILED. See messages above.
  echo Arabic guide: packaging\README_INSTALL_AR.md
  pause
  exit /b 1
)
echo.
pause
