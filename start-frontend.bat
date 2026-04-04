@echo off
chcp 65001 >nul 2>&1
title SPED-Frontend (porta 3000)
cd /d "%~dp0frontend"

if not exist "node_modules" (
    echo Instalando dependencias frontend...
    call npm install
)

echo Iniciando Frontend na porta 3000...
echo.
call npm run dev
echo.
echo Frontend encerrado. Verifique erros acima.
pause
