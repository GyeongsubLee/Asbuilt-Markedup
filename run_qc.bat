@echo off
REM Put this file (with iso_qc.py and the isoqc folder) next to the MARK-UP / AS-BUILT folders
cd /d "%~dp0"
chcp 65001 >nul
python "%~dp0iso_qc.py" --base "%~dp0." --no-pause %*
pause
