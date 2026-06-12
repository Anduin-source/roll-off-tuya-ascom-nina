@echo off
cd /d "%~dp0"
start "Painel Coberturas" "%~dp0PainelCoberturas.exe"
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:5000"
echo.
echo Painel iniciado.
echo Se o navegador nao abriu, acesse: http://127.0.0.1:5000
echo Para encerrar, feche a janela do PainelCoberturas.exe.
pause
