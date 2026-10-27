@echo off
REM Build a single ISO_QC.exe on Windows (Python 3.10+ required)
cd /d "%~dp0"
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto fail
python -m PyInstaller --noconfirm --onefile --console --name ISO_QC --exclude-module pymupdf.layout --exclude-module pymupdf4llm --exclude-module pymupdf_layout --exclude-module onnxruntime --exclude-module tkinter iso_qc.py
if errorlevel 1 goto fail
echo.
echo [DONE] dist\ISO_QC.exe was created.
echo Copy it next to the "CIMS MARK-UP ISO" and "AS BUILT ISO" folders and double-click it.
pause
exit /b 0
:fail
echo.
echo [ERROR] Build failed. Check that Python is installed and on PATH ("python --version").
pause
exit /b 1
