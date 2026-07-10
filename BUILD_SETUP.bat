@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "packaging\build_setup.ps1"
if errorlevel 1 pause
