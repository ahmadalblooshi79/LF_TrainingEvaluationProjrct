@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "VENV_PY=.venv\Scripts\python.exe"

REM Detect broken venv (missing, or home Python path moved / different machine).
"%VENV_PY%" -c "import sys" >nul 2>&1
if errorlevel 1 goto :ensure_venv

"%VENV_PY%" run.py
exit /b %ERRORLEVEL%

:ensure_venv
echo [INFO] .venv missing or broken — recreating...
call :find_python
if not defined HOST_PY (
  echo [ERROR] Python 3.14 not found. Install from https://www.python.org/downloads/
  exit /b 1
)
echo [INFO] Using host Python: %HOST_PY%
if exist ".venv" rmdir /s /q ".venv"
"%HOST_PY%" -m venv .venv
if errorlevel 1 (
  echo [ERROR] Failed to create .venv
  exit /b 1
)
"%VENV_PY%" -m pip install --upgrade pip
if errorlevel 1 (
  echo [ERROR] pip upgrade failed
  exit /b 1
)
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] pip install -r requirements.txt failed
  exit /b 1
)
echo [OK] .venv ready
"%VENV_PY%" run.py
exit /b %ERRORLEVEL%

:find_python
set "HOST_PY="
if exist "%ProgramFiles%\Python314\python.exe" (
  set "HOST_PY=%ProgramFiles%\Python314\python.exe"
  goto :eof
)
if exist "%LocalAppData%\Programs\Python\Python314\python.exe" (
  set "HOST_PY=%LocalAppData%\Programs\Python\Python314\python.exe"
  goto :eof
)
if exist "%LocalAppData%\Python\pythoncore-3.14-64\python.exe" (
  set "HOST_PY=%LocalAppData%\Python\pythoncore-3.14-64\python.exe"
  goto :eof
)
where py >nul 2>&1
if not errorlevel 1 (
  for /f "delims=" %%i in ('py -3.14 -c "import sys; print(sys.executable)" 2^>nul') do set "HOST_PY=%%i"
  if defined HOST_PY goto :eof
)
where python >nul 2>&1
if not errorlevel 1 (
  for /f "delims=" %%i in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "HOST_PY=%%i"
)
goto :eof
