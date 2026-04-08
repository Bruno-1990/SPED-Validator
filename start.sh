#!/bin/bash
# SPED EFD Audit System v3.0 - Start Script (Linux/WSL)
set -e
cd "$(dirname "$0")"

echo "============================================"
echo "  SPED EFD Audit System v3.0"
echo "  175 regras | 21 blocos | 1473 testes"
echo "============================================"
echo ""

# --- Verificar Python ---
if ! command -v python3 &>/dev/null; then
    echo "[ERRO] Python3 nao encontrado. Instale Python 3.10+"
    exit 1
fi

# --- Verificar Node ---
if ! command -v npm &>/dev/null; then
    echo "[ERRO] Node.js/npm nao encontrado. Instale Node.js 18+"
    exit 1
fi

# --- Verificar/criar venv ---
VENV_DIR=".venv-linux"
if [ ! -f "$VENV_DIR/bin/activate" ]; then
    echo "  [SETUP] Criando ambiente virtual..."
    python3 -m venv "$VENV_DIR"
fi

# --- Ativar venv ---
source "$VENV_DIR/bin/activate"
export PYTHONPATH="$(pwd)"

# --- Instalar deps Python somente se necessario ---
if ! pip show fastapi &>/dev/null; then
    echo "  [SETUP] Instalando dependencias Python..."
    python -m pip install --upgrade pip -q
    python -m pip install -r requirements.txt
else
    echo "  [OK] Dependencias Python instaladas."
fi

# --- Instalar deps Frontend somente se necessario ---
if [ ! -d "frontend/node_modules" ]; then
    echo "  [SETUP] Instalando dependencias Frontend..."
    cd frontend
    npm install
    cd ..
else
    echo "  [OK] Dependencias Frontend instaladas."
fi

# --- Criar diretorios necessarios ---
mkdir -p db data/reference data/tabelas

# --- Criar/migrar banco de dados ---
echo "  [DB] Verificando banco de dados e migracoes..."
python -c "from src.services.database import init_audit_db; init_audit_db('db/audit.db')" 2>/dev/null || true

# --- Verificar tabelas de referencia ---
if [ ! -f "data/reference/aliquotas_internas_uf.yaml" ]; then
    echo "  [AVISO] Tabelas de referencia ausentes em data/reference/"
    echo "          DIFAL e FCP podem nao funcionar corretamente."
fi

echo ""
echo "  Iniciando API (porta 8000)..."

# --- Iniciar API em background ---
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000 &
API_PID=$!

echo "  Aguardando API (8s)..."
sleep 8

# --- Verificar se API subiu ---
if ! kill -0 $API_PID 2>/dev/null; then
    echo "[ERRO] API falhou ao iniciar. Verifique os logs acima."
    exit 1
fi

echo "  Iniciando Frontend (porta 3000)..."

# --- Iniciar Frontend em background ---
cd frontend
npm run dev &
FRONT_PID=$!
cd ..

sleep 5

echo ""
echo "============================================"
echo "  App:       http://localhost:3000"
echo "  API Docs:  http://localhost:8000/docs"
echo "============================================"
echo ""

# --- Tentar abrir no browser ---
if command -v xdg-open &>/dev/null; then
    xdg-open http://localhost:3000 2>/dev/null || true
elif command -v wslview &>/dev/null; then
    wslview http://localhost:3000 2>/dev/null || true
fi

echo "  Pressione Ctrl+C para ENCERRAR tudo."
echo ""

# --- Trap para limpar ao sair ---
cleanup() {
    echo ""
    echo "  Encerrando processos..."
    kill $API_PID 2>/dev/null || true
    kill $FRONT_PID 2>/dev/null || true
    wait $API_PID 2>/dev/null || true
    wait $FRONT_PID 2>/dev/null || true
    echo "  Encerrado."
}

trap cleanup EXIT INT TERM

# Aguardar processos
wait
