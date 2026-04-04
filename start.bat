@echo off
chcp 65001 >nul 2>&1
title SPED EFD Audit

echo ============================================
echo   SPED EFD Audit System
echo ============================================
echo.

cd /d "%~dp0"
echo        Diretorio: %CD%
echo.

REM --- Verificar Python ---
where python >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao encontrado. Instale Python 3.10+
    pause
    exit /b 1
)

REM --- Verificar venv ---
if not exist ".venv-win\Scripts\activate.bat" (
    echo Criando ambiente virtual...
    python -m venv .venv-win
)

REM --- Verificar Node ---
where npm >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Node.js nao encontrado. Instale Node.js 18+
    pause
    exit /b 1
)

REM --- Iniciar API ---
echo Iniciando API...
start "" "%~dp0start-api.bat"

echo Aguardando API (10s)...
timeout /t 10 /nobreak >nul

REM --- Iniciar Frontend ---
echo Iniciando Frontend...
start "" "%~dp0start-frontend.bat"

echo Aguardando Frontend (10s)...
timeout /t 10 /nobreak >nul

echo.
echo ============================================
echo   App:       http://localhost:3000
echo   API Docs:  http://localhost:8000/docs
echo ============================================
echo.

start "" http://localhost:3000

echo Feche as janelas SPED-API e SPED-Frontend para encerrar.
pause
