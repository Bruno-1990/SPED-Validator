@echo off
chcp 65001 >nul 2>&1
title Git Push - SPED Validator

echo ============================================
echo   Git Push - SPED Validator
echo ============================================
echo.

cd /d "%~dp0"

echo Status atual:
echo.
git status --short
echo.

set /p MSG="Digite a mensagem do commit: "

if "%MSG%"=="" (
    echo [ERRO] Mensagem do commit nao pode ser vazia.
    pause
    exit /b 1
)

echo.
echo [1/4] Adicionando arquivos...
git add -A

echo [2/4] Criando commit...
git commit -m "%MSG%"
if errorlevel 1 (
    echo [ERRO] Falha ao criar commit.
    pause
    exit /b 1
)

echo [3/4] Rebase na main...
git fetch SPED-Validator main
git rebase SPED-Validator/main
if errorlevel 1 (
    echo [ERRO] Conflito no rebase. Resolva manualmente.
    pause
    exit /b 1
)

echo [4/4] Push para main...
git push SPED-Validator HEAD:main
if errorlevel 1 (
    echo [ERRO] Falha no push. Verifique sua autenticacao.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Push concluido com sucesso!
echo ============================================
echo.
pause
