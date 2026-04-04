@echo off
chcp 65001 >nul 2>&1
title SPED EFD Audit
cd /d "%~dp0"

echo ============================================
echo   SPED EFD Audit System
echo ============================================
echo.
echo   Diretorio: %CD%
echo.

REM --- Verificar Python ---
where python >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao encontrado. Instale Python 3.10+
    pause
    exit /b 1
)

REM --- Verificar Node ---
where npm >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Node.js nao encontrado. Instale Node.js 18+
    pause
    exit /b 1
)

REM --- Verificar/criar venv ---
if not exist ".venv-win\Scripts\activate.bat" (
    echo   Criando ambiente virtual...
    python -m venv .venv-win
)

REM --- Ativar venv e atualizar pip ---
call ".venv-win\Scripts\activate.bat"
set PYTHONPATH=%CD%

echo   Atualizando pip...
python -m pip install --upgrade pip >nul 2>&1

pip show fastapi >nul 2>&1
if errorlevel 1 (
    echo   Instalando dependencias Python...
    python -m pip install -r requirements.txt
)

REM --- Verificar deps Frontend ---
if not exist "frontend\node_modules" (
    echo   Instalando dependencias Frontend...
    pushd frontend
    call npm install
    popd
)

REM --- Criar scripts temporarios para evitar problema de aspas ---
echo @echo off > "%~dp0_run_api.bat"
echo title SPED-API (porta 8000) >> "%~dp0_run_api.bat"
echo cd /d "%~dp0" >> "%~dp0_run_api.bat"
echo call ".venv-win\Scripts\activate.bat" >> "%~dp0_run_api.bat"
echo set PYTHONPATH=%~dp0 >> "%~dp0_run_api.bat"
echo python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000 >> "%~dp0_run_api.bat"
echo pause >> "%~dp0_run_api.bat"

echo @echo off > "%~dp0_run_frontend.bat"
echo title SPED-Frontend (porta 3000) >> "%~dp0_run_frontend.bat"
echo cd /d "%~dp0frontend" >> "%~dp0_run_frontend.bat"
echo call npm run dev >> "%~dp0_run_frontend.bat"
echo pause >> "%~dp0_run_frontend.bat"

echo.
echo   Iniciando API (porta 8000)...
start "" /min "%~dp0_run_api.bat"

echo   Aguardando API (8s)...
timeout /t 8 /nobreak >nul

echo   Iniciando Frontend (porta 3000)...
start "" /min "%~dp0_run_frontend.bat"

echo   Aguardando Frontend (5s)...
timeout /t 5 /nobreak >nul

echo.
echo ============================================
echo   App:       http://localhost:3000
echo   API Docs:  http://localhost:8000/docs
echo ============================================
echo.

start "" http://localhost:3000

echo   Pressione qualquer tecla para ENCERRAR tudo.
echo.
pause >nul

echo.
echo   Encerrando processos...

REM --- Matar processos ---
taskkill /fi "WINDOWTITLE eq SPED-API*" /f >nul 2>&1
taskkill /fi "WINDOWTITLE eq SPED-Frontend*" /f >nul 2>&1

REM --- Limpar scripts temporarios ---
del /q "%~dp0_run_api.bat" >nul 2>&1
del /q "%~dp0_run_frontend.bat" >nul 2>&1

echo   Encerrado.
