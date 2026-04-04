@echo off
chcp 65001 >nul 2>&1
title SPED-API (porta 8000)
cd /d "%~dp0"

call ".venv-win\Scripts\activate.bat"
set PYTHONPATH=%CD%;%PYTHONPATH%

echo Verificando dependencias...
pip show fastapi >nul 2>&1
if errorlevel 1 (
    echo Instalando dependencias...
    python -m pip install -r requirements.txt
)

echo Iniciando API na porta 8000...
echo.
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
echo.
echo API encerrada. Verifique erros acima.
pause
