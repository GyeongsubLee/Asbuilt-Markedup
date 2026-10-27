@echo off
REM Windows 에서 단일 실행파일(ISO_QC.exe) 만들기 - Python 3.10 이상 필요
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --onefile --console --name ISO_QC iso_qc.py
echo.
echo dist\ISO_QC.exe 가 만들어졌습니다. "CIMS MARK-UP ISO" / "AS BUILT ISO" 폴더가 있는 곳에 복사해서 실행하세요.
pause
