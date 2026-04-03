"""Parser de arquivos SPED EFD (pipe-delimited)."""

from __future__ import annotations

from pathlib import Path

from .models import SpedRecord

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
            fields=parts,
            raw_line=line,
        ))

    return records


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
