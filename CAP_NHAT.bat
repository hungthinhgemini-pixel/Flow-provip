@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Dang kiem tra ban cap nhat...
set "ZIP=%TEMP%\fpv_update.zip"
set "DIR=%TEMP%\fpv_update"
if exist "%DIR%" rmdir /s /q "%DIR%"
powershell -NoProfile -Command "try { [Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest -UseBasicParsing -TimeoutSec 20 -Uri 'https://github.com/hungthinhgemini-pixel/Flow-provip/archive/refs/heads/claude/adoring-albattani-ovqpgp.zip' -OutFile '%ZIP%'; Expand-Archive -Force '%ZIP%' '%DIR%'; exit 0 } catch { exit 1 }"
if errorlevel 1 (
  echo Khong tai duoc ban moi - dung ban hien tai.
  exit /b 0
)
for /d %%D in ("%DIR%\*") do (
  xcopy /e /y /q "%%D\flowprovip" "%~dp0flowprovip\" >nul
  copy /y "%%D\requirements.txt" "%~dp0requirements.txt" >nul
  copy /y "%%D\CAP_NHAT.bat" "%~dp0CAP_NHAT.bat.new" >nul
)
echo Da cap nhat xong.
exit /b 0
