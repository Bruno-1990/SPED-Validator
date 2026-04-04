@echo off
chcp 65001 >nul 2>&1
title SPED - Ingestao de Documentos
cd /d "%~dp0"

if not exist ".venv-win\Scripts\activate.bat" (
    echo [ERRO] Ambiente virtual nao encontrado. Execute start.bat primeiro.
    pause
    exit /b 1
)

call ".venv-win\Scripts\activate.bat"
set PYTHONPATH=%CD%

python ingest.py %*
