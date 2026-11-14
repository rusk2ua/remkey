@echo off
rem Install or update remkey into the same Python that Start-remkey.bat runs:
rem host\.venv if it exists, otherwise the py launcher.
rem   Install-remkey.bat          remkey only
rem   Install-remkey.bat cloud    plus boto3, for the cloud copy of the dashboard
cd /d "%~dp0"
set "EXTRA="
if /i "%~1"=="cloud" set "EXTRA=[cloud]"
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=py"
)
echo Installing remkey%EXTRA% into: %PY%
"%PY%" -m pip install -e ".%EXTRA%"
if errorlevel 1 (
    echo.
    echo Install FAILED: see the error above, fix it and run this again.
    pause
    exit /b 1
)
echo.
echo Done. Restart the station service to pick up the changes.
