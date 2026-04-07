@echo off
chcp 65001 >nul 2>&1
title SPED EFD Audit v3.0
cd /d "%~dp0"

echo ============================================
echo   SPED EFD Audit System v3.0
echo   175 regras / 21 blocos / 1473 testes
echo ============================================
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
    echo   [SETUP] Criando ambiente virtual...
    python -m venv .venv-win
    if errorlevel 1 (
        echo [ERRO] Falha ao criar venv. Verifique Python.
        pause
        exit /b 1
    )
)

REM --- Ativar venv ---
call ".venv-win\Scripts\activate.bat"
set "PYTHONPATH=%CD%"

REM --- Instalar deps Python somente se necessario ---
pip show fastapi >nul 2>&1
if errorlevel 1 (
    echo   [SETUP] Instalando dependencias Python...
    python -m pip install --upgrade pip >nul 2>&1
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERRO] Falha ao instalar dependencias Python.
        pause
        exit /b 1
    )
) else (
    echo   [OK] Dependencias Python instaladas.
)

REM --- Instalar deps Frontend somente se necessario ---
if not exist "frontend\node_modules" (
    echo   [SETUP] Instalando dependencias Frontend...
    pushd frontend
    call npm install
    if errorlevel 1 (
        echo [ERRO] Falha ao instalar dependencias Frontend.
        popd
        pause
        exit /b 1
    )
    popd
) else (
    echo   [OK] Dependencias Frontend instaladas.
)

REM --- Criar diretorios necessarios ---
if not exist "db" mkdir db
if not exist "data\reference" mkdir data\reference
if not exist "data\tabelas" mkdir data\tabelas

REM --- Criar/migrar banco de dados ---
echo   [DB] Verificando banco de dados e migracoes...
python -c "from src.services.database import init_audit_db; init_audit_db('db/audit.db')" 2>nul

REM --- Verificar tabelas de referencia ---
if not exist "data\reference\aliquotas_internas_uf.yaml" (
    echo   [AVISO] Tabelas de referencia ausentes em data/reference/
    echo           DIFAL e FCP podem nao funcionar corretamente.
)

echo.
echo   Iniciando API na porta 8000...

REM --- Salvar caminho atual para os scripts ---
set "PROJECT_DIR=%CD%"

REM --- Criar script temporario API usando redirecionamento seguro ---
> "_run_api.bat" (
    echo @echo off
    echo chcp 65001 ^>nul 2^>^&1
    echo title SPED-API
    echo cd /d "%PROJECT_DIR%"
    echo call ".venv-win\Scripts\activate.bat"
    echo set "PYTHONPATH=%PROJECT_DIR%"
    echo echo.
    echo echo   [API] Iniciando uvicorn na porta 8000...
    echo echo.
    echo python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
    echo echo.
    echo echo   [API] Processo encerrado. Verifique erros acima.
    echo pause
)

REM --- Criar script temporario Frontend ---
> "_run_frontend.bat" (
    echo @echo off
    echo chcp 65001 ^>nul 2^>^&1
    echo title SPED-Frontend
    echo cd /d "%PROJECT_DIR%\frontend"
    echo echo.
    echo echo   [FRONTEND] Iniciando Vite na porta 3000...
    echo echo.
    echo call npm run dev
    echo echo.
    echo echo   [FRONTEND] Processo encerrado. Verifique erros acima.
    echo pause
)

start "SPED-API" /min "_run_api.bat"

echo   Aguardando API (8s)...
timeout /t 8 /nobreak >nul

echo   Iniciando Frontend na porta 3000...
start "SPED-Frontend" /min "_run_frontend.bat"

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

taskkill /fi "WINDOWTITLE eq SPED-API*" /f >nul 2>&1
taskkill /fi "WINDOWTITLE eq SPED-Frontend*" /f >nul 2>&1

del /q "_run_api.bat" >nul 2>&1
del /q "_run_frontend.bat" >nul 2>&1

echo   Encerrado.
