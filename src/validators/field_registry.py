"""FieldRegistry: resolve (register, field_name) → índice de campo no pipe-delimited SPED.

Carregado uma vez do banco register_fields (quando disponível) ou do REGISTER_FIELDS
em memória. Thread-safe para leitura após inicialização.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from config import DB_PATH
from ..validators.helpers import REGISTER_FIELDS


class FieldNotFoundError(Exception):
    pass


class FieldRegistry:
    """Resolve (register, field_name) → índice de campo no pipe-delimited SPED.

    Carregado uma vez do banco register_fields, cached em memória.
    Thread-safe para leitura após inicialização.
    """

    _instance: Optional["FieldRegistry"] = None
    _registry: dict[tuple[str, str], int] = {}

    def __init__(self, db_path: Path = DB_PATH):
        self._db_path = db_path
        self._registry = {}
        self._load()

    def _load(self) -> None:
        loaded_from_db = False
        try:
            conn = sqlite3.connect(self._db_path)
            try:
                rows = conn.execute(
                    "SELECT register, field_name, field_no FROM register_fields"
                ).fetchall()
                for register, field_name, field_no in rows:
                    # field_no no banco é 1-based; fields[] na lista é 0-based
                    self._registry[(register.upper(), field_name.upper())] = field_no
                loaded_from_db = bool(rows)
            finally:
                conn.close()
        except (sqlite3.OperationalError, FileNotFoundError):
            pass

        # Fallback: usar REGISTER_FIELDS do helpers.py
        if not loaded_from_db:
            for register, field_names in REGISTER_FIELDS.items():
                for idx, fname in enumerate(field_names):
                    self._registry[(register.upper(), fname.upper())] = idx

    @classmethod
    def get_instance(cls, db_path: Path = DB_PATH) -> "FieldRegistry":
        if cls._instance is None:
            cls._instance = cls(db_path)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Para testes — reseta o singleton."""
        cls._instance = None

    def get_index(self, register: str, field_name: str) -> int:
        """Retorna o índice para acessar o campo na lista fields[].

        Exemplo: register='C170', field_name='CST_ICMS'
        """
        key = (register.upper(), field_name.upper())
        idx = self._registry.get(key)
        if idx is None:
            raise FieldNotFoundError(
                f"Campo {field_name!r} não encontrado no registro {register!r}. "
                f"Verifique se register_fields foi carregado corretamente."
            )
        return idx

    def get_field_safe(
        self, fields: list[str], register: str, field_name: str, default: str = ""
    ) -> str:
        """Versão segura: retorna o valor do campo ou default se não encontrado."""
        try:
            idx = self.get_index(register, field_name)
            return fields[idx] if idx < len(fields) else default
        except FieldNotFoundError:
            return default

    def has_field(self, register: str, field_name: str) -> bool:
        return (register.upper(), field_name.upper()) in self._registry

    def list_fields(self, register: str) -> list[tuple[str, int]]:
        """Lista todos os campos conhecidos de um registro com seus índices."""
        prefix = register.upper()
        return [
            (fname, idx)
            for (reg, fname), idx in self._registry.items()
            if reg == prefix
        ]


# Instância global conveniente (lazy)
def get_registry(db_path: Path = DB_PATH) -> FieldRegistry:
    return FieldRegistry.get_instance(db_path)
