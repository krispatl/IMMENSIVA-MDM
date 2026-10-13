@echo off
cd /d "%~dp0"
if exist "runtime\python.exe" (
  "runtime\python.exe" -m immensiva_mdm.launcher --stop
) else (
  python -m immensiva_mdm.launcher --stop
)
if errorlevel 1 pause
