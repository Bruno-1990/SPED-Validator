"""Dataclasses centrais do sistema SPED EFD."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass
class SpedRecord:
    """Um registro (linha) de um arquivo SPED EFD."""
    line_number: int
    register: str          # ex: "C100"
    fields: dict[str, str] # campos nomeados: {"REG": "C100", "IND_OPER": "0", ...}
    raw_line: str


def get_field(record: SpedRecord, field_name: str, default: str = "") -> str:
    """Retorna valor de um campo pelo nome, com default seguro."""
    return record.fields.get(field_name, default)


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
    categoria: str = "fiscal"          # 'fiscal' ou 'governance'
    certeza: str = "objetivo"          # 'objetivo' | 'provavel' | 'indicio'
    impacto: str = "relevante"         # 'critico' | 'relevante' | 'informativo'

    @property
    def error_hash(self) -> str:
        """Hash SHA256 que identifica unicamente esta ocorrencia de erro.

        Composicao: line_number + register + field_name + error_type + value
        Permite deduplicacao entre validacoes, rastreabilidade de correcoes
        e vinculacao de revisoes IA ao erro especifico.
        """
        return compute_error_hash(
            self.line_number, self.register, self.field_name,
            self.error_type, self.value,
        )


def compute_error_hash(
    line_number: int,
    register: str,
    field_name: str | None,
    error_type: str,
    value: str | None,
) -> str:
    """Gera hash SHA256 que identifica unicamente uma ocorrencia de erro.

    O hash NAO inclui file_id (para permitir comparacao entre arquivos
    do mesmo contribuinte) nem message (que pode mudar entre versoes).

    Inclui:
    - line_number: posicao no arquivo
    - register: tipo de registro (C100, E210, etc.)
    - field_name: campo afetado (VL_ICMS, etc.)
    - error_type: regra que detectou (XML004, ST_APURACAO_INCONSISTENTE, etc.)
    - value: valor encontrado (para distinguir erros no mesmo campo com valores diferentes)
    """
    import hashlib
    raw = f"{line_number}|{register}|{field_name or ''}|{error_type}|{value or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


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
