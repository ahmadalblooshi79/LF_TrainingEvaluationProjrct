@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo  ============================================
echo   تثبيت سيرفر نظام التحليل الذكي
echo  ============================================
echo.
call "%~dp0installer\INSTALL_SERVER.bat"
