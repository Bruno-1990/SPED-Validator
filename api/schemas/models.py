"""Pydantic models para request/response da API."""

from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

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
    model_config = ConfigDict(coerce_numbers_to_str=False)

    id: int
    filename: str
    hash_sha256: str
    upload_date: str | None = None

    @field_validator("upload_date", mode="before")
    @classmethod
    def _coerce_upload_date(cls, v):  # noqa: N805
        if v is None:
            return v
        if not isinstance(v, str):
            return str(v)
        return v
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
    rule_id: str = "MANUAL"
    correction_type: Literal["deterministic", "assisted", "manual"] = "manual"
    justificativa: str = "Correcao aplicada via interface"

    @field_validator("justificativa")
    @classmethod
    def justificativa_min_length(cls, v: str, info: ValidationInfo) -> str:
        rid = str((info.data or {}).get("rule_id") or "")
        ct = str((info.data or {}).get("correction_type") or "")
        # Correcoes manuais e assistidas com rule_id generico: minimo reduzido
        if ct == "manual" or rid in ("MANUAL", ""):
            return (v or "").strip() or "Correcao manual via interface"
        min_len = 10 if rid.startswith("FM_") else 20
        s = (v or "").strip()
        if len(s) < min_len:
            raise ValueError(f"Justificativa deve ter no minimo {min_len} caracteres")
        return s


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
    error_hash: str | None = None


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
