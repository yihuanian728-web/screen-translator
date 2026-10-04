@echo off
cd /d "%~dp0"
echo ==========================================================
echo   Translator - install offline OCR (RapidOCR, recommended)
echo ==========================================================
echo.
echo  Why: the OCR engine built into Windows only knows the
echo  languages installed in your system. Most Chinese PCs have
echo  no English OCR pack, so English text gets recognised as
echo  garbage such as "b rown (0)^<". RapidOCR ships its own
echo  Chinese+English models, works offline, and scores 1.00
echo  on our tests. Cost: about 100-200 MB of downloads.
echo.
pause
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Dependencies not installed. Please run install.bat first.
    pause
    exit /b 1
)
echo Installing rapidocr-onnxruntime ...
".venv\Scripts\python.exe" -m pip install rapidocr-onnxruntime
if errorlevel 1 (
    echo Default index failed, retrying with Tsinghua mirror ...
    ".venv\Scripts\python.exe" -m pip install rapidocr-onnxruntime -i https://pypi.tuna.tsinghua.edu.cn/simple
)
if errorlevel 1 (
    echo.
    echo [ERROR] Install failed. Check your network.
    pause
    exit /b 1
)
echo.
echo Done. Running selftest ...
".venv\Scripts\python.exe" "main.py" --selftest
echo.
pause