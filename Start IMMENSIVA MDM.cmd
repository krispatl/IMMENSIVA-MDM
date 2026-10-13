@echo off
cd /d "%~dp0"
if exist "runtime\pythonw.exe" (
  start "" "runtime\pythonw.exe" -m immensiva_mdm.launcher
) else (
  python -m immensiva_mdm.launcher
  if errorlevel 1 pause
)
