"""Configuracoes de caminhos e parametros do sistema."""

from pathlib import Path

# Diretorio raiz do projeto
ROOT_DIR = Path(__file__).parent

# Diretorios de dados - fonte dos documentos
DOCS_ROOT = Path(r"C:\Users\bmb19\OneDrive\Área de Trabalho\SPED2.0")
GUIA_DIR = DOCS_ROOT / "guia pratico"
LEGISLACAO_DIR = DOCS_ROOT / "legislaação"

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
