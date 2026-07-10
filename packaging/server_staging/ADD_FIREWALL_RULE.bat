@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\server\add_firewall_rule.ps1"
exit /b 0
