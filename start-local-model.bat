@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" scripts\setup_local_brain.py --serve
pause
