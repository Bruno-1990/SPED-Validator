"""Endpoints de validação."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from api.deps import get_db, get_doc_db_path
from api.schemas.models import ErrorSummary, ValidationErrorInfo, ValidationResponse
from src.services.validation_service import get_error_summary, get_errors, run_full_validation

router = APIRouter(prefix="/api/files/{file_id}", tags=["validation"])


@router.post("/validate", response_model=ValidationResponse)
def validate(file_id: int, db: sqlite3.Connection = Depends(get_db)) -> ValidationResponse:
    """Executa validação completa do arquivo."""
    doc_db = get_doc_db_path()
    errors = run_full_validation(db, file_id, doc_db_path=doc_db)
    return ValidationResponse(file_id=file_id, total_errors=len(errors), status="validated")


@router.get("/errors", response_model=list[ValidationErrorInfo])
def list_errors(
    file_id: int,
    error_type: str | None = None,
    severity: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: sqlite3.Connection = Depends(get_db),
) -> list[ValidationErrorInfo]:
    """Lista erros de validação com filtros."""
    rows = get_errors(db, file_id, error_type=error_type, severity=severity, limit=limit, offset=offset)
    return [ValidationErrorInfo(**r) for r in rows]


@router.get("/summary", response_model=ErrorSummary)
def summary(file_id: int, db: sqlite3.Connection = Depends(get_db)) -> ErrorSummary:
    """Resumo dos erros por tipo e severidade."""
    return ErrorSummary(**get_error_summary(db, file_id))
