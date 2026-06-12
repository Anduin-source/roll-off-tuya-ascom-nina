@echo off
setlocal
cd /d "%~dp0\.."
call .venv\Scripts\activate.bat
pyinstaller --onefile --name PainelCoberturas painel_local\servidor.py
if errorlevel 1 exit /b 1

set OUT_DIR=dist\PainelCoberturasEntrega
if exist "%OUT_DIR%" rmdir /s /q "%OUT_DIR%"
mkdir "%OUT_DIR%"

copy /Y dist\PainelCoberturas.exe "%OUT_DIR%\PainelCoberturas.exe" >nul
copy /Y painel_local\devices_exemplo.json "%OUT_DIR%\devices.json" >nul
copy /Y painel_local\iniciar_painel.bat "%OUT_DIR%\iniciar_painel.bat" >nul
copy /Y painel_local\README_CADU.txt "%OUT_DIR%\README_CADU.txt" >nul

echo.
echo Pacote pronto em: %OUT_DIR%
echo Envie a pasta PainelCoberturasEntrega para o Cadu.
