@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo [ERROR] Dependencies not installed. Please run install.bat first.
    echo.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "main.py"
exit /b 0