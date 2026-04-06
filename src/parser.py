"""Parser de arquivos SPED EFD (pipe-delimited)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Generator
from pathlib import Path

from .models import SpedRecord
from .validators.helpers import fields_to_dict

# Encodings usados pela Receita Federal
_ENCODINGS = ["latin-1", "cp1252", "utf-8"]


def parse_sped_file(filepath: str | Path) -> list[SpedRecord]:
    """Lê um arquivo SPED EFD e retorna lista de registros parseados.

    Tenta latin-1 primeiro (padrão PVA), depois cp1252, depois utf-8.
    """
    filepath = Path(filepath)
    content = _read_with_fallback(filepath)
    records: list[SpedRecord] = []

    for line_number, line in enumerate(content.splitlines(), start=1):
        line = line.strip()
        if not line or not line.startswith("|"):
            continue

        # Remove pipes inicial e final, split nos intermediários
        parts = line.split("|")
        # |campo1|campo2|...| gera ['', 'campo1', 'campo2', ..., '']
        parts = parts[1:-1] if len(parts) >= 2 else parts

        if not parts:
            continue

        register = parts[0].strip()
        records.append(SpedRecord(
            line_number=line_number,
            register=register,
            fields=fields_to_dict(register, parts),
            raw_line=line,
        ))

    return records


def _detect_encoding(filepath: Path) -> str:
    """Detecta o encoding do arquivo lendo os primeiros bytes."""
    sample = filepath.read_bytes()[:8192]
    for enc in _ENCODINGS:
        try:
            sample.decode(enc)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue
    return "latin-1"


def parse_file_streaming(
    filepath: str | Path,
    file_id: int,
    db: sqlite3.Connection,
    batch_size: int = 1000,
) -> Generator[int, None, None]:
    """Leitura streaming linha a linha com persistência incremental.

    Processa o arquivo em batches de ``batch_size`` linhas, persistindo cada
    batch no banco para evitar carregar o arquivo inteiro em memória.

    Yields o número total de registros persistidos após cada batch.
    """
    filepath = Path(filepath)
    encoding = _detect_encoding(filepath)
    batch: list[tuple] = []
    total = 0

    with open(filepath, encoding=encoding, errors="replace") as fh:
        for line_number, raw_line in enumerate(fh, start=1):
            line = raw_line.strip()
            if not line or not line.startswith("|"):
                continue

            parts = line.split("|")
            parts = parts[1:-1] if len(parts) >= 2 else parts
            if not parts:
                continue

            register = parts[0].strip()
            block = register[0] if register else ""
            fields = fields_to_dict(register, parts)

            batch.append((
                file_id, line_number, register, block,
                json.dumps(fields, ensure_ascii=False), line,
            ))

            if len(batch) >= batch_size:
                _persist_batch(db, batch)
                total += len(batch)
                batch = []
                yield total

    if batch:
        _persist_batch(db, batch)
        total += len(batch)
        yield total


def _persist_batch(db: sqlite3.Connection, batch: list[tuple]) -> None:
    """Persiste um batch de registros no banco."""
    db.executemany(
        """INSERT INTO sped_records
           (file_id, line_number, register, block, fields_json, raw_line)
           VALUES (?, ?, ?, ?, ?, ?)""",
        batch,
    )
    db.commit()


def _read_with_fallback(filepath: Path) -> str:
    """Tenta ler o arquivo com diferentes encodings."""
    raw = filepath.read_bytes()
    for enc in _ENCODINGS:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    # Último recurso: ignora erros
    return raw.decode("latin-1", errors="replace")


def group_by_register(records: list[SpedRecord]) -> dict[str, list[SpedRecord]]:
    """Agrupa registros pelo código de registro (ex: todos os C100 juntos)."""
    groups: dict[str, list[SpedRecord]] = {}
    for rec in records:
        groups.setdefault(rec.register, []).append(rec)
    return groups


def get_register_hierarchy(records: list[SpedRecord]) -> list[tuple[SpedRecord, list[SpedRecord]]]:
    """Identifica hierarquia pai/filho em registros SPED.

    Ex: C100 é pai de C170, C190, etc. Um registro pai é seguido por
    seus filhos até o próximo registro do mesmo nível ou superior.
    """
    hierarchy: list[tuple[SpedRecord, list[SpedRecord]]] = []
    current_parent: SpedRecord | None = None
    children: list[SpedRecord] = []

    for rec in records:
        level = _register_level(rec.register)
        if level <= 1:
            # Registro de nível de abertura/fechamento de bloco
            if current_parent is not None:
                hierarchy.append((current_parent, children))
            current_parent = None
            children = []
        elif level == 2:
            # Novo registro pai (ex: C100)
            if current_parent is not None:
                hierarchy.append((current_parent, children))
            current_parent = rec
            children = []
        else:
            # Registro filho (ex: C170, C190)
            children.append(rec)

    if current_parent is not None:
        hierarchy.append((current_parent, children))

    return hierarchy


def _register_level(register: str) -> int:
    """Determina o nível hierárquico de um registro SPED.

    Registros terminados em 001/990/999 são abertura/fechamento.
    Registros com último dígito 0 (ex: C100) são nível pai.
    Outros (ex: C170) são filhos.
    """
    if not register or len(register) < 2:
        return 0

    suffix = register[-3:] if len(register) >= 4 else register[-2:]
    if suffix in ("001", "990", "999", "000", "0000", "9999", "0001", "9900"):
        return 1

    # Registros como C100, D100, E100 = nível pai
    # Registros como C170, C190, D150 = nível filho
    try:
        num = int(register[1:])
        if num % 100 == 0:
            return 2
        return 3
    except ValueError:
        return 0
