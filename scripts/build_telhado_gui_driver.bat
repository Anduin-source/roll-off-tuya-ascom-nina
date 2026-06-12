@echo off
setlocal
cd /d "%~dp0\.."
call .venv\Scripts\activate.bat

pyinstaller --onefile --noconsole --name dome_driver dome_driver.py
if errorlevel 1 exit /b 1

pyinstaller --onefile --noconsole --name TelhadoGUI --hidden-import tuya_cloud telhado_gui.py
if errorlevel 1 exit /b 1

set OUT_DIR=dist\TelhadoControleEntrega
if exist "%OUT_DIR%" rmdir /s /q "%OUT_DIR%"
mkdir "%OUT_DIR%"

copy /Y dist\dome_driver.exe "%OUT_DIR%\dome_driver.exe" >nul
copy /Y dist\TelhadoGUI.exe "%OUT_DIR%\TelhadoGUI.exe" >nul
copy /Y config_exemplo.json "%OUT_DIR%\config_exemplo.json" >nul
copy /Y scripts\iniciar_telhado_gui.bat "%OUT_DIR%\iniciar_telhado_gui.bat" >nul
copy /Y docs\README_TELHADO_GUI.txt "%OUT_DIR%\README_TELHADO_GUI.txt" >nul

echo.
echo Pacote pronto em: %OUT_DIR%
echo Copie config_exemplo.json para config.json e preencha antes de usar.
