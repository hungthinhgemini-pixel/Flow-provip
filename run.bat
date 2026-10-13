@echo off
cd /d "%~dp0"
if not exist C:\fpv\Scripts\activate.bat (
  echo Chua cai dat. Hay bam dup file CAI_DAT.bat truoc.
  pause & exit /b 1
)
call CAP_NHAT.bat
call C:\fpv\Scripts\activate.bat
pip install -q -r requirements.txt >nul 2>nul
python -m flowprovip
if errorlevel 1 pause
