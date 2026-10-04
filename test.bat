@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Dependencies not installed. Please run install.bat first.
    pause
    exit /b 1
)
echo [1/6] Environment + translation providers
".venv\Scripts\python.exe" "main.py" --doctor
echo.
echo [2/6] Offline selftest (image - OCR - direction)
".venv\Scripts\python.exe" "main.py" --selftest
echo.
echo [3/6] GUI smoke test
".venv\Scripts\python.exe" "main.py" --smoke
echo.
echo [4/6] Selection reading test (opens Notepad briefly)
".venv\Scripts\python.exe" "main.py" --selection-test
echo.
echo [5/6] Selection end-to-end (synthesizes a real mouse drag!)
".venv\Scripts\python.exe" "main.py" --selection-e2e
echo.
echo [6/6] Screenshot region end-to-end (a window will flash)
".venv\Scripts\python.exe" "main.py" --e2e
echo.
echo ==========================================================
echo  All done. Look for [OK] / [FAIL] markers above.
echo ==========================================================
pause