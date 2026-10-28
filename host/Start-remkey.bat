@echo off
rem remkey station service launcher (Windows).
rem Task Scheduler: trigger "At log on"; Program/script = this file; Start in = this folder.
rem Uses host\.venv if it exists, otherwise the py launcher. Extra arguments pass through,
rem e.g.  Start-remkey.bat --dry-run
title remkey station
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m remkey.station --config station.toml %*
) else (
    py -m remkey.station --config station.toml %*
)
echo.
echo remkey station stopped (exit code %ERRORLEVEL%). See remkey-station.log
pause
