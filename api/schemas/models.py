"""Pydantic models para request/response da API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

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


# ──────────────────────────────────────────────
# Validation
# ──────────────────────────────────────────────

class ValidationErrorInfo(BaseModel):
    id: int
    file_id: int
    line_number: int
    register: str
    field_no: int | None = None
    field_name: str | None = None
    value: str | None = None
    error_type: str
    severity: str
    message: str
    status: str = "open"


class ErrorSummary(BaseModel):
    total: int
    by_type: dict[str, int]
    by_severity: dict[str, int]


class ValidationResponse(BaseModel):
    file_id: int
    total_errors: int
    status: str


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
