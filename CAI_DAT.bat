@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   CAI DAT FLOW PROVIP (chi can lam 1 lan)
echo ============================================
echo.

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo [1/4] Dang cai Python...
  winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
  if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
)
if not defined PY (
  echo.
  echo KHONG CAI DUOC PYTHON TU DONG.
  echo Hay vao https://www.python.org/downloads/ cai Python, nho tick "Add python.exe to PATH", roi bam lai file nay.
  pause & exit /b 1
)

where ffprobe >nul 2>nul
if errorlevel 1 (
  echo [2/4] Dang cai FFmpeg...
  winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
) else (
  echo [2/4] FFmpeg da co.
)

echo [3/4] Dang cai thu vien (mat vai phut, dung tat cua so)...
if exist "C:\fpv" rmdir /s /q "C:\fpv"
%PY% -m venv C:\fpv
if errorlevel 1 ( echo LOI tao moi truong. & pause & exit /b 1 )
call C:\fpv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 ( echo LOI cai thu vien. Chup man hinh gui cho nguoi ho tro. & pause & exit /b 1 )
playwright install chromium

echo [4/4] Tao bieu tuong ngoai Desktop...
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Flow ProVip.lnk');$s.TargetPath='%~dp0run.bat';$s.WorkingDirectory='%~dp0';$s.Save()"

echo.
echo ============================================
echo   XONG! Tu gio bam bieu tuong "Flow ProVip" ngoai Desktop de chay.
echo   (Neu lan dau bao thieu FFmpeg: tat va mo lai may/cua so)
echo ============================================
pause
