#!/bin/bash
# Setup automatico do SPED EFD Audit System
set -e

echo "============================================"
echo "  SPED EFD Audit - Setup Automatico"
echo "============================================"

# 1. Backend
echo ""
echo "[1/4] Instalando dependencias Python..."
if command -v uv &> /dev/null; then
    uv venv .venv 2>/dev/null || true
    source .venv/bin/activate
    uv pip install -e ".[dev]" fastapi uvicorn python-multipart
else
    python3 -m venv .venv 2>/dev/null || true
    source .venv/bin/activate
    pip install -e ".[dev]" fastapi uvicorn python-multipart
fi

# 2. Frontend
echo ""
echo "[2/4] Instalando dependencias Frontend..."
if [ -d "frontend" ]; then
    cd frontend
    npm install
    cd ..
fi

# 3. Converter e indexar documentacao (se disponivel)
echo ""
echo "[3/4] Verificando banco de documentacao..."
if [ -f "db/sped.db" ]; then
    echo "  Banco de documentacao ja existe (db/sped.db)"
else
    echo "  Banco de documentacao nao encontrado."
    echo "  Execute: python cli.py convert && python cli.py index"
fi

# 4. Testes
echo ""
echo "[4/4] Executando testes..."
python3 -m pytest tests/ -q --tb=short

echo ""
echo "============================================"
echo "  Setup completo!"
echo ""
echo "  Para iniciar:"
echo "    API:      uvicorn api.main:app --reload"
echo "    Frontend: cd frontend && npm run dev"
echo "    Swagger:  http://localhost:8000/docs"
echo "    App:      http://localhost:3000"
echo "============================================"
