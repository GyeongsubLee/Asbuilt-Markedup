@echo off
REM 이 파일을 MARK-UP / AS-BUILT 폴더가 있는 폴더에 두고 더블클릭 (Python 설치 시)
cd /d "%~dp0"
python "%~dp0iso_qc.py" --base "%~dp0." %*
pause
