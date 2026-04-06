"""Indexador: Markdown -> SQLite (FTS5 + embeddings)."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from tqdm import tqdm

from config import EMBEDDING_MODEL

from .embeddings import embed_texts, embedding_to_blob
from .models import Chunk, RegisterField

# ──────────────────────────────────────────────
# Schema
# ──────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT 'guia',
    register    TEXT,
    field_name  TEXT,
    heading     TEXT NOT NULL,
    content     TEXT NOT NULL,
    page_number INTEGER,
    embedding   BLOB
);

CREATE INDEX IF NOT EXISTS idx_chunks_category ON chunks(category);
CREATE INDEX IF NOT EXISTS idx_chunks_register ON chunks(register);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    category,
    register,
    field_name,
    heading,
    content,
    content='chunks',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

-- Triggers para manter FTS sincronizado
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, category, register, field_name, heading, content)
    VALUES (new.id, new.category, new.register, new.field_name, new.heading, new.content);
END;

CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, category, register, field_name, heading, content)
    VALUES ('delete', old.id, old.category, old.register, old.field_name, old.heading, old.content);
END;

CREATE TABLE IF NOT EXISTS register_fields (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    register    TEXT NOT NULL,
    field_no    INTEGER NOT NULL,
    field_name  TEXT NOT NULL,
    field_type  TEXT,
    field_size  INTEGER,
    decimals    INTEGER,
    required    TEXT,
    valid_values TEXT,
    description TEXT,
    UNIQUE(register, field_no)
);

CREATE TABLE IF NOT EXISTS indexed_files (
    source_file TEXT PRIMARY KEY,
    category    TEXT NOT NULL DEFAULT 'guia',
    indexed_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS embedding_metadata (
    id          INTEGER PRIMARY KEY,
    model_name  TEXT NOT NULL,
    model_version TEXT,
    indexed_at  TEXT DEFAULT (datetime('now')),
    chunks_count INTEGER
);
"""


def init_db(db_path: str | Path) -> sqlite3.Connection:
    """Cria o banco e as tabelas se não existirem."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_SCHEMA)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def index_all_markdown(
    markdown_dir: str | Path,
    db_path: str | Path,
    category: str = "guia",
    skip_existing: bool = True,
) -> int:
    """Indexa todos os arquivos .md de um diretorio.

    Args:
        category: 'guia' para Guia Pratico, 'legislacao' para legislacao/normas.

    Retorna o numero de chunks inseridos.
    """
    markdown_dir = Path(markdown_dir)
    conn = init_db(db_path)
    total_chunks = 0

    md_files = sorted(markdown_dir.glob("*.md"))

    for md_path in tqdm(md_files, desc=f"Indexando {category}"):
        if skip_existing:
            row = conn.execute(
                "SELECT 1 FROM indexed_files WHERE source_file = ? AND category = ?",
                (md_path.name, category),
            ).fetchone()
            if row:
                continue

        content = md_path.read_text(encoding="utf-8")
        chunks = _chunk_markdown(content, md_path.name, category)
        fields = _extract_register_fields(content)

        if chunks:
            total_chunks += _insert_chunks(conn, chunks, category)

        if fields:
            _insert_register_fields(conn, fields)

        conn.execute(
            "INSERT OR REPLACE INTO indexed_files (source_file, category) VALUES (?, ?)",
            (md_path.name, category),
        )
        conn.commit()

    conn.close()
    return total_chunks


# ──────────────────────────────────────────────
# Chunking
# ──────────────────────────────────────────────

def _chunk_markdown(content: str, source_file: str, category: str = "guia") -> list[Chunk]:
    """Divide o Markdown em chunks pesquisáveis.

    Estratégia:
    - Split por headings ## (nível de registro)
    - Dentro de cada seção, cria chunks separados para:
      - Texto descritivo
      - Cada linha de tabela de campos (1 chunk por campo)
    """
    chunks: list[Chunk] = []
    # Dividir por headings de nível 2 ou 3 (## ou ###)
    sections = re.split(r"(?=^#{2,3}\s)", content, flags=re.MULTILINE)

    for section in sections:
        if not section.strip():
            continue

        heading = _extract_heading(section)
        register = _extract_register_code(heading)

        # Separar tabelas do texto
        table_blocks, text_blocks = _split_tables_and_text(section)

        # Chunk do texto descritivo
        for text in text_blocks:
            text = text.strip()
            if text and len(text) > 20:
                chunks.append(Chunk(
                    source_file=source_file,
                    register=register,
                    heading=heading,
                    content=text,
                ))

        # Chunks individuais por linha de tabela de campos
        for table in table_blocks:
            rows = _parse_markdown_table(table)
            if not rows:
                continue

            header = rows[0]
            for row in rows[1:]:
                field_name = _guess_field_name(header, row)
                row_text = " | ".join(f"{h}: {v}" for h, v in zip(header, row, strict=False) if v.strip())
                if row_text.strip():
                    chunks.append(Chunk(
                        source_file=source_file,
                        register=register,
                        field_name=field_name,
                        heading=heading,
                        content=row_text,
                    ))

    return chunks


def _extract_heading(section: str) -> str:
    """Extrai o texto do primeiro heading de uma seção."""
    match = re.match(r"^#{1,4}\s+(.+)", section, re.MULTILINE)
    return match.group(1).strip() if match else "(sem título)"


def _extract_register_code(text: str) -> str | None:
    """Extrai código de registro (ex: C100) de um texto."""
    match = re.search(r"\b([A-Z][0-9]{3,4})\b", text)
    return match.group(1) if match else None


def _split_tables_and_text(section: str) -> tuple[list[str], list[str]]:
    """Separa blocos de tabela Markdown de blocos de texto."""
    tables: list[str] = []
    texts: list[str] = []
    current_block: list[str] = []
    in_table = False

    for line in section.split("\n"):
        is_table_line = line.strip().startswith("|") and "|" in line.strip()[1:]

        if is_table_line and not in_table:
            # Início de tabela — salvar texto acumulado
            if current_block:
                texts.append("\n".join(current_block))
                current_block = []
            in_table = True
            current_block.append(line)
        elif is_table_line and in_table:
            current_block.append(line)
        elif not is_table_line and in_table:
            # Fim de tabela
            tables.append("\n".join(current_block))
            current_block = [line] if line.strip() else []
            in_table = False
        else:
            current_block.append(line)

    # Bloco final
    if current_block:
        if in_table:
            tables.append("\n".join(current_block))
        else:
            texts.append("\n".join(current_block))

    return tables, texts


def _parse_markdown_table(table_text: str) -> list[list[str]]:
    """Parseia uma tabela Markdown em lista de listas."""
    rows: list[list[str]] = []
    for line in table_text.strip().split("\n"):
        line = line.strip()
        if not line.startswith("|"):
            continue
        # Pular linha separadora (|---|---|)
        if re.match(r"^\|[\s\-:|]+\|$", line):
            continue
        cells = [c.strip() for c in line.split("|")]
        # Remover primeiro e último vazios
        cells = cells[1:-1] if len(cells) >= 2 else cells
        rows.append(cells)
    return rows


def _guess_field_name(header: list[str], row: list[str]) -> str | None:
    """Tenta identificar o nome do campo a partir dos dados da linha."""
    # Procurar coluna "Campo" ou "Nome" no header
    for i, h in enumerate(header):
        h_lower = h.lower().strip()
        if h_lower in ("campo", "nome", "field", "name") and i < len(row):
            val = row[i].strip()
            if val:
                return val
    # Se não achou, tentar segunda coluna (padrão SPED: No | Campo | ...)
    if len(row) >= 2 and row[1].strip():
        return row[1].strip()
    return None


# ──────────────────────────────────────────────
# Register Fields extraction
# ──────────────────────────────────────────────

def _extract_register_fields(content: str) -> list[RegisterField]:
    """Extrai definições de campos de registros das tabelas do Markdown."""
    fields: list[RegisterField] = []
    sections = re.split(r"(?=^#{2,3}\s)", content, flags=re.MULTILINE)

    for section in sections:
        heading = _extract_heading(section)
        register = _extract_register_code(heading)
        if not register:
            continue

        tables, _ = _split_tables_and_text(section)
        for table in tables:
            rows = _parse_markdown_table(table)
            if len(rows) < 2:
                continue

            header = [h.lower().strip() for h in rows[0]]
            # Verificar se parece uma tabela de campos SPED
            if not _is_field_definition_table(header):
                continue

            col_map = _map_columns(header)

            # Detectar o registro real da tabela: se o campo REG (nº 01)
            # contém "texto fixo contendo X990/X001", usar esse código
            # em vez do heading (previne contaminação entre seções).
            table_register = _detect_table_register(rows, col_map) or register

            for row in rows[1:]:
                field = _row_to_register_field(table_register, row, col_map)
                if field:
                    fields.append(field)

    return fields


def _detect_table_register(rows: list[list[str]], col_map: dict[str, int]) -> str | None:
    """Detecta o registro real de uma tabela olhando a descrição do campo REG.

    Ex: 'Texto fixo contendo "E990"' → retorna 'E990'.
    Previne que campos sejam atribuídos ao registro errado quando o Markdown
    tem tabelas de múltiplos registros na mesma seção.
    """
    desc_col = col_map.get("descricao")
    campo_col = col_map.get("campo")
    if desc_col is None:
        return None

    for row in rows[1:]:  # pular header
        campo = row[campo_col].strip() if campo_col is not None and campo_col < len(row) else ""
        if campo.upper() != "REG":
            continue
        desc = row[desc_col] if desc_col < len(row) else ""
        match = re.search(r'["\u201c]([A-Z]\d{3})["\u201d]', desc)
        if match:
            return match.group(1)

    return None


def _is_field_definition_table(header: list[str]) -> bool:
    """Verifica se os headers indicam uma tabela de definição de campos."""
    keywords = {"nº", "no", "campo", "descrição", "descricao", "tipo", "tam", "tamanho"}
    header_set = {h.strip().lower() for h in header}
    return len(header_set & keywords) >= 2


def _map_columns(header: list[str]) -> dict[str, int]:
    """Mapeia nomes de colunas para índices."""
    mapping: dict[str, int] = {}
    for i, h in enumerate(header):
        h = h.strip().lower()
        if h in ("nº", "no", "n°", "num"):
            mapping["no"] = i
        elif h in ("campo", "nome", "name"):
            mapping["campo"] = i
        elif h in ("descrição", "descricao", "description", "desc"):
            mapping["descricao"] = i
        elif h in ("tipo", "type"):
            mapping["tipo"] = i
        elif h in ("tam", "tamanho", "size"):
            mapping["tamanho"] = i
        elif h in ("dec", "decimal", "decimais"):
            mapping["decimal"] = i
        elif h in ("obrig", "obrigatório", "obrigatorio", "required"):
            mapping["obrig"] = i
        elif h in ("valores válidos", "valores validos", "valid"):
            mapping["valores"] = i
    return mapping


def _row_to_register_field(
    register: str,
    row: list[str],
    col_map: dict[str, int],
) -> RegisterField | None:
    """Converte uma linha de tabela em RegisterField."""
    def get(key: str) -> str:
        idx = col_map.get(key)
        if idx is not None and idx < len(row):
            return row[idx].strip()
        return ""

    field_no_str = get("no")
    field_name = get("campo")

    if not field_name:
        return None

    # Parsear número do campo
    try:
        field_no = int(re.sub(r"[^\d]", "", field_no_str)) if field_no_str else 0
    except ValueError:
        field_no = 0

    # Parsear tamanho
    size_str = get("tamanho")
    try:
        field_size = int(re.sub(r"[^\d]", "", size_str)) if size_str else None
    except ValueError:
        field_size = None

    # Parsear decimais
    dec_str = get("decimal")
    try:
        decimals = int(re.sub(r"[^\d]", "", dec_str)) if dec_str and dec_str != "-" else None
    except ValueError:
        decimals = None

    # Parsear valores válidos
    valores_str = get("valores")
    valid_values = None
    if valores_str:
        # Tentar extrair valores entre aspas ou separados por vírgula
        found = re.findall(r'"([^"]+)"', valores_str)
        if not found:
            found = [v.strip() for v in valores_str.split(",") if v.strip()]
        if found:
            valid_values = found

    return RegisterField(
        register=register,
        field_no=field_no,
        field_name=field_name,
        field_type=get("tipo") or None,
        field_size=field_size,
        decimals=decimals,
        required=get("obrig") or None,
        valid_values=valid_values,
        description=get("descricao") or None,
    )


# ──────────────────────────────────────────────
# Insert into DB
# ──────────────────────────────────────────────

def _insert_chunks(conn: sqlite3.Connection, chunks: list[Chunk], category: str = "guia") -> int:
    """Insere chunks no banco e gera embeddings."""
    texts = [c.content for c in chunks]

    # Gerar embeddings em batch
    embeddings = embed_texts(texts)

    for chunk, emb in zip(chunks, embeddings, strict=False):
        conn.execute(
            """INSERT INTO chunks
               (source_file, category, register, field_name, heading, content, page_number, embedding)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                chunk.source_file,
                category,
                chunk.register,
                chunk.field_name,
                chunk.heading,
                chunk.content,
                chunk.page_number,
                embedding_to_blob(emb),
            ),
        )

    # Registrar modelo de embeddings usado
    conn.execute(
        """INSERT OR REPLACE INTO embedding_metadata (id, model_name, model_version, chunks_count)
           VALUES (1, ?, ?, ?)""",
        (EMBEDDING_MODEL, None, conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]),
    )
    conn.commit()

    return len(chunks)


def _insert_register_fields(conn: sqlite3.Connection, fields: list[RegisterField]) -> int:
    """Insere definições de campos no banco."""
    inserted = 0
    for f in fields:
        try:
            conn.execute(
                """INSERT OR REPLACE INTO register_fields
                   (register, field_no, field_name, field_type, field_size,
                    decimals, required, valid_values, description)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    f.register, f.field_no, f.field_name, f.field_type,
                    f.field_size, f.decimals, f.required,
                    f.valid_values_json(), f.description,
                ),
            )
            inserted += 1
        except sqlite3.IntegrityError:
            pass
    return inserted
