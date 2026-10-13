@echo off
cd /d "%~dp0"
if not exist C:\fpv\Scripts\activate.bat (
  echo Chua cai dat. Hay bam dup file CAI_DAT.bat truoc.
  pause & exit /b 1
)
call C:\fpv\Scripts\activate.bat
python -m flowprovip
if errorlevel 1 pause
