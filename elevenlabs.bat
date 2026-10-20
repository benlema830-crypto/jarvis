@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" elevenlabs_voice.py %*
pause
