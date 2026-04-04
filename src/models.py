"""Dataclasses centrais do sistema SPED EFD."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass
class SpedRecord:
    """Um registro (linha) de um arquivo SPED EFD."""
    line_number: int
    register: str          # ex: "C100"
    fields: list[str]      # valores posicionais (inclui o código do registro)
    raw_line: str


@dataclass
class RegisterField:
    """Definição de um campo de registro extraída da documentação."""
    register: str          # ex: "C100"
    field_no: int          # posição: 1, 2, 3...
    field_name: str        # ex: "IND_OPER"
    field_type: str | None = None     # "C" (char), "N" (numérico)
    field_size: int | None = None
    decimals: int | None = None
    required: str | None = None       # "O", "OC", "N"
    valid_values: list[str] | None = None  # ex: ["0", "1"]
    description: str | None = None

    def valid_values_json(self) -> str | None:
        """Serializa valid_values para armazenamento no SQLite."""
        if self.valid_values is None:
            return None
        return json.dumps(self.valid_values)

    @staticmethod
    def valid_values_from_json(raw: str | None) -> list[str] | None:
        """Deserializa valid_values do SQLite."""
        if raw is None:
            return None
        return list(json.loads(raw))


@dataclass
class ValidationError:
    """Erro encontrado ao validar um registro SPED."""
    line_number: int
    register: str
    field_no: int
    field_name: str
    value: str
    error_type: str        # INVALID_VALUE, WRONG_TYPE, WRONG_SIZE, MISSING_REQUIRED
    message: str
    expected_value: str | None = None  # Valor correto quando calculável (para auto-correção)


@dataclass
class Chunk:
    """Um trecho de documentação indexado para busca."""
    id: int | None = None
    source_file: str = ""
    category: str = "guia"        # "guia" ou "legislacao"
    register: str | None = None
    field_name: str | None = None
    heading: str = ""
    content: str = ""
    page_number: int | None = None
    embedding: bytes | None = None


@dataclass
class SearchResult:
    """Resultado de uma busca na documentação."""
    chunk: Chunk
    score: float
    source: str = ""       # "fts", "semantic", "hybrid"
