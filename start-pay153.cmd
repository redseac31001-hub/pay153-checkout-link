@echo off
setlocal
cd /d "%~dp0"
title PAY.153 Checkout Link

set "PORT=18082"
set "ACTION=%~1"
if "%ACTION%"=="" set "ACTION=start"

if /I not "%ACTION%"=="start" if /I not "%ACTION%"=="restart" if /I not "%ACTION%"=="stop" (
  echo Usage: %~nx0 [start^|restart^|stop]
  exit /b 2
)

call :stop_existing
if errorlevel 1 exit /b 1
if /I "%ACTION%"=="stop" exit /b 0

set "PYTHON_CMD="
where python.exe >nul 2>&1
if not errorlevel 1 (
  python.exe -c "import flask, curl_cffi, cryptography" >nul 2>&1
  if not errorlevel 1 set "PYTHON_CMD=python.exe"
)

if not defined PYTHON_CMD (
  where py.exe >nul 2>&1
  if not errorlevel 1 (
    py.exe -3.11 -c "import flask, curl_cffi, cryptography" >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=py.exe -3.11"
  )
)

if not defined PYTHON_CMD (
  echo Python was found, but PAY.153 dependencies are missing.
  echo Install them with:
  echo   python -m pip install -r requirements.txt
  echo Or, when using Python 3.11:
  echo   py -3.11 -m pip install -r requirements.txt
  exit /b 1
)

if not exist "node_modules\jsdom\package.json" (
  where npm.cmd >nul 2>&1
  if errorlevel 1 (
    echo npm was not found on PATH. Run npm install before starting PAY.153.
    exit /b 1
  )
  echo Installing Sentinel Node dependencies ...
  call npm.cmd install --omit=dev --no-audit --no-fund
  if errorlevel 1 (
    echo Failed to install Sentinel Node dependencies.
    exit /b 1
  )
)

echo Starting PAY.153 Checkout Link on 127.0.0.1:%PORT% ...
%PYTHON_CMD% app.py
exit /b %ERRORLEVEL%

:stop_existing
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$port = %PORT%; $owners = @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue).OwningProcess; $seen = @{}; foreach ($owner in $owners) { if ($owner -and -not $seen.ContainsKey($owner)) { $seen[$owner] = $true; if ($owner -ne $PID) { Stop-Process -Id $owner -Force -ErrorAction SilentlyContinue } } }; Start-Sleep -Milliseconds 300"
if errorlevel 1 (
  echo Failed to clear the existing listener on port %PORT%.
  exit /b 1
)
exit /b 0
