@echo off
chcp 65001 >nul 2>&1
title SPED-API
cd /d "C:\Users\bmb19\OneDrive\Documentos\work\SPED"
call ".venv-win\Scripts\activate.bat"
set "PYTHONPATH=C:\Users\bmb19\OneDrive\Documentos\work\SPED"
echo.
echo   [API] Iniciando uvicorn na porta 8000...
echo.
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
echo.
echo   [API] Processo encerrado. Verifique erros acima.
pause
