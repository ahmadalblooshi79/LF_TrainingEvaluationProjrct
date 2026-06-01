@echo off
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0packaging\start_server.bat"
