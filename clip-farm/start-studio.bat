@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" studio.py %*
) else if exist "..\.venv\Scripts\python.exe" (
  "..\.venv\Scripts\python.exe" studio.py %*
) else (
  python studio.py %*
)
if errorlevel 1 pause
