@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (
  echo Chua cai dat. Hay bam dup file CAI_DAT.bat truoc.
  pause & exit /b 1
)
call .venv\Scripts\activate.bat
python -m flowprovip
if errorlevel 1 pause
