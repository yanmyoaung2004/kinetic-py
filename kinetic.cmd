@echo off
setlocal
set "VIRTUAL_ENV=%~dp0.venv"
set "PATH=%~dp0.venv\Scripts;%PATH%"

:: Store the directory where the user currently is
set "ORIGINAL_DIR=%CD%"

:: Change directory to where this script lives (your project root)
cd /d "%~dp0"

:: Run the executable
"%~dp0.venv\Scripts\kinetic.exe" %*

:: Restore the user's original directory context
cd /d "%ORIGINAL_DIR%"
endlocal