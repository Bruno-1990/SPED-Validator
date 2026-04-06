"""Configuracoes de caminhos e parametros do sistema."""

import os
from pathlib import Path

# Versão do motor de regras
ENGINE_VERSION = "3.0.0"

# Autenticação
API_KEY = os.getenv("API_KEY")

# Diretorio raiz do projeto
ROOT_DIR = Path(__file__).parent

# Diretorios de dados - fonte dos documentos
DOCS_ROOT = Path(os.getenv("DOCS_ROOT", str(ROOT_DIR / "data" / "source")))
GUIA_DIR = DOCS_ROOT / "guia pratico"
LEGISLACAO_DIR = DOCS_ROOT / "legislacao"

# Saida markdown (separada por categoria)
MARKDOWN_DIR = ROOT_DIR / "data" / "markdown"
MARKDOWN_GUIA_DIR = MARKDOWN_DIR / "guia"
MARKDOWN_LEGISLACAO_DIR = MARKDOWN_DIR / "legislacao"

# Arquivos SPED para validar
SPED_FILES_DIR = ROOT_DIR / "data" / "sped_files"

# Banco de dados
DB_DIR = ROOT_DIR / "db"
DB_DIR.mkdir(exist_ok=True)
DB_PATH = DB_DIR / "sped.db"

# Modelo de embeddings
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384
EMBEDDING_BATCH_SIZE = 64

# Busca
SEARCH_TOP_K = 5
RRF_K = 60

# Categorias de documentos
CATEGORIES = {
    "guia": "Guia Pratico EFD",
    "legislacao": "Legislacao e normas",
}
