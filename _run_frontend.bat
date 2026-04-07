@echo off
chcp 65001 >nul 2>&1
title SPED-Frontend
cd /d "C:\Users\bmb19\OneDrive\Documentos\work\SPED\frontend"
echo.
echo   [FRONTEND] Iniciando Vite na porta 3000...
echo.
call npm run dev
echo.
echo   [FRONTEND] Processo encerrado. Verifique erros acima.
pause
