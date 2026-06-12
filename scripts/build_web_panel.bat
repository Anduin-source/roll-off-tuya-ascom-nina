@echo off
cd /d "%~dp0\.."
call .venv\Scripts\activate.bat
pyinstaller --onefile --name PainelCoberturas painel_local\servidor.py
