#!/usr/bin/env python3
"""MOD-09: Migra fields_json de formato array (legado) para dict nomeado.

Uso:
    python scripts/migrate_fields_json.py <caminho_banco.db>

O script:
1. Le todos os registros do banco com fields_json em formato array (list)
2. Detecta formato antigo: json.loads(fields_json) retorna list
3. Converte para dict usando REGISTER_FIELDS
4. Atualiza o banco in-place

Seguro para rodar multiplas vezes (idempotente).
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

# Adicionar raiz do projeto ao path
_project_root = Path(__file__).parent.parent
sys.path.insert(0, str(_project_root))

from src.validators.helpers import fields_to_dict  # noqa: E402


def migrate_fields_json(db_path: str) -> dict[str, int]:
    """Migra registros com fields_json em formato list para dict.

    Retorna estatisticas: {"total": N, "migrated": M, "already_dict": K, "errors": E}
    """
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")

    stats = {"total": 0, "migrated": 0, "already_dict": 0, "errors": 0}

    rows = conn.execute(
        "SELECT id, register, fields_json FROM sped_records"
    ).fetchall()

    stats["total"] = len(rows)
    batch: list[tuple[str, int]] = []

    for row_id, register, fields_json_raw in rows:
        try:
            parsed = json.loads(fields_json_raw)
        except (json.JSONDecodeError, TypeError):
            stats["errors"] += 1
            continue

        if isinstance(parsed, dict):
            stats["already_dict"] += 1
            continue

        if isinstance(parsed, list):
            named = fields_to_dict(register, parsed)
            batch.append((json.dumps(named, ensure_ascii=False), row_id))
            stats["migrated"] += 1
        else:
            stats["errors"] += 1

    # Aplicar em batch
    if batch:
        conn.executemany(
            "UPDATE sped_records SET fields_json = ? WHERE id = ?",
            batch,
        )
        conn.commit()

    conn.close()
    return stats


def main() -> None:
    if len(sys.argv) < 2:
        print("Uso: python scripts/migrate_fields_json.py <caminho_banco.db>")
        sys.exit(1)

    db_path = sys.argv[1]
    if not Path(db_path).exists():
        print(f"Erro: banco '{db_path}' nao encontrado.")
        sys.exit(1)

    print(f"Migrando fields_json em: {db_path}")
    stats = migrate_fields_json(db_path)

    print(f"  Total de registros: {stats['total']}")
    print(f"  Ja em formato dict: {stats['already_dict']}")
    print(f"  Migrados (list->dict): {stats['migrated']}")
    print(f"  Erros: {stats['errors']}")

    if stats["migrated"] > 0:
        print("Migracao concluida com sucesso.")
    elif stats["already_dict"] == stats["total"]:
        print("Todos os registros ja estao no formato dict. Nada a fazer.")
    else:
        print("Nenhum registro migrado.")


if __name__ == "__main__":
    main()
