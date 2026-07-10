@echo off

setlocal

cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "packaging\advanced_installer\build_client_setup.ps1"

if errorlevel 1 pause

