@echo off
cd /d "%~dp0"
echo ==========================================================
echo   Translator - debug start (console visible)
echo ==========================================================
echo.
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Dependencies not installed. Please run install.bat first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" "main.py"
echo.
echo Program exited with code %errorlevel%
pause