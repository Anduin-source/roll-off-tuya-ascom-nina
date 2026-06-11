@echo off
cd /d "%~dp0\.."
call .venv\Scripts\activate.bat
python dome_driver.py
