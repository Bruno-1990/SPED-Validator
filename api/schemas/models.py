"""Pydantic models para request/response da API."""

from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, field_validator

T = TypeVar("T")


# ──────────────────────────────────────────────
# Pagination
# ──────────────────────────────────────────────

class PaginatedResponse(BaseModel, Generic[T]):
    total: int
    page: int
    page_size: int
    has_next: bool
    data: list[T]  # type: ignore[valid-type]

# ──────────────────────────────────────────────
# Files
# ──────────────────────────────────────────────

class FileInfo(BaseModel):
    id: int
    filename: str
    hash_sha256: str
    upload_date: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    company_name: str | None = None
    cnpj: str | None = None
    uf: str | None = None
    total_records: int = 0
    total_errors: int = 0
    status: str = "uploaded"
    auto_corrections_applied: int = 0
    cod_ver: int = 0
    is_retificador: bool = False
    original_file_id: int | None = None


class FileUploadResponse(BaseModel):
    file_id: int
    filename: str
    total_records: int
    status: str


# ──────────────────────────────────────────────
# Records
# ──────────────────────────────────────────────

class RecordInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    file_id: int
    line_number: int
    register: str
    block: str
    fields_json: str
    raw_line: str
    status: str = "pending"


class RecordUpdate(BaseModel):
    field_no: int
    field_name: str
    new_value: str
    error_id: int | None = None


class CorrectionRequest(BaseModel):
    field_no: int
    field_name: str
    new_value: str
    error_id: int | None = None
    justificativa: str
    correction_type: Literal["deterministic", "assisted", "manual"]
    rule_id: str

    @field_validator("justificativa")
    @classmethod
    def justificativa_min_length(cls, v: str) -> str:
        if len(v.strip()) < 20:
            raise ValueError("Justificativa deve ter no mínimo 20 caracteres")
        return v.strip()


# ──────────────────────────────────────────────
# Validation
# ──────────────────────────────────────────────

class ValidationErrorInfo(BaseModel):
    id: int
    file_id: int
    record_id: int | None = None
    line_number: int
    register: str
    field_no: int | None = None
    field_name: str | None = None
    value: str | None = None
    error_type: str
    severity: str
    message: str
    friendly_message: str | None = None
    doc_suggestion: str | None = None
    legal_basis: str | None = None
    expected_value: str | None = None
    auto_correctable: bool = False
    status: str = "open"
    categoria: str = "fiscal"
    certeza: str = "objetivo"
    impacto: str = "relevante"
    materialidade: float = 0


class ErrorSummary(BaseModel):
    total: int
    by_type: dict[str, int]
    by_severity: dict[str, int]


class ValidationResponse(BaseModel):
    file_id: int
    total_errors: int
    status: str


# ──────────────────────────────────────────────
# Audit Scope (MOD-11)
# ──────────────────────────────────────────────

class AuditCheckInfo(BaseModel):
    id: str
    status: str  # ok | parcial | nao_executado | nao_aplicavel
    regras: int = 0
    motivo_parcial: str | None = None


class AuditScope(BaseModel):
    regime_identificado: str
    periodo: str
    checks_executados: list[AuditCheckInfo]
    tabelas_externas: dict[str, str]
    cobertura_estimada_pct: int
    aviso: str | None = None


# ──────────────────────────────────────────────
# Search
# ──────────────────────────────────────────────

class SearchResultInfo(BaseModel):
    source_file: str
    register: str | None = None
    field_name: str | None = None
    heading: str
    content: str
    score: float
    source: str


# ──────────────────────────────────────────────
# Report
# ──────────────────────────────────────────────

class ReportResponse(BaseModel):
    file_id: int
    format: str
    content: str
