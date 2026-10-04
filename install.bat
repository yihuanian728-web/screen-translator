@echo off
cd /d "%~dp0"
echo ==========================================================
echo   Translator - install dependencies
echo ==========================================================
echo.
if not exist ".venv\Scripts\python.exe" (
    echo [1/4] Creating virtual environment .venv ...
    where py >nul 2>nul
    if %errorlevel%==0 ( py -3 -m venv .venv ) else ( python -m venv .venv )
    if not exist ".venv\Scripts\python.exe" (
        echo.
        echo [ERROR] Could not create venv. Install Python 3.9+ first:
        echo         https://www.python.org/downloads/
        echo.
        pause
        exit /b 1
    )
) else (
    echo [1/4] .venv already exists, skip.
)
echo [2/4] Upgrading pip ...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
echo [3/4] Installing Pillow + Windows OCR binding ...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Default index failed, retrying with Tsinghua mirror ...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
)
echo [4/4] Installing uiautomation (needed to read selected text) ...
".venv\Scripts\python.exe" -m pip install uiautomation
if errorlevel 1 (
    ".venv\Scripts\python.exe" -m pip install uiautomation -i https://pypi.tuna.tsinghua.edu.cn/simple
)
echo.
echo ----------------------------------------------------------
echo  Done. Next:
echo    1) install_ocr.bat   - offline OCR engine (recommended)
echo    2) start.bat         - launch the app
echo    3) doctor.bat        - verify environment
echo ----------------------------------------------------------
echo.
pause