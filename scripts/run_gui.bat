@echo off
cd /d "%~dp0\.."
call .venv\Scripts\activate.bat
python telhado_gui.py