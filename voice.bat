@echo off
setlocal
set "VIRTUAL_ENV=%~dp0.venv"
set "PATH=%~dp0.venv\Scripts;%PATH%"
cd /d "%~dp0"

:: Start kinetic in background
start "KINETIC" cmd /c "%~dp0.venv\Scripts\kinetic.exe"

:: Wait for API to be ready
echo Waiting for API...
timeout /t 8 /nobreak >nul

:: Run voice chat
"%~dp0.venv\Scripts\python.exe" voice_chat.py

endlocal
