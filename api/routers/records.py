"""Endpoints de registros SPED."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_db
from api.schemas.models import RecordInfo, RecordUpdate
from src.services.correction_service import apply_correction

router = APIRouter(prefix="/api/files/{file_id}/records", tags=["records"])


@router.get("", response_model=list[RecordInfo])
def list_records(
    file_id: int,
    block: str | None = None,
    register: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: sqlite3.Connection = Depends(get_db),
) -> list[RecordInfo]:
    """Lista registros do arquivo com filtros."""
    query = "SELECT * FROM sped_records WHERE file_id = ?"
    params: list = [file_id]

    if block:
        query += " AND block = ?"
        params.append(block)
    if register:
        query += " AND register = ?"
        params.append(register)
    if status:
        query += " AND status = ?"
        params.append(status)

    query += " ORDER BY line_number LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = db.execute(query, params).fetchall()
    return [RecordInfo(**dict(r)) for r in rows]


@router.get("/{record_id}", response_model=RecordInfo)
def get_record(file_id: int, record_id: int, db: sqlite3.Connection = Depends(get_db)) -> RecordInfo:
    """Detalhe de um registro."""
    row = db.execute(
        "SELECT * FROM sped_records WHERE id = ? AND file_id = ?",
        (record_id, file_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Registro não encontrado")
    return RecordInfo(**dict(row))


@router.put("/{record_id}")
def update_record(
    file_id: int,
    record_id: int,
    update: RecordUpdate,
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Aplica correção em um campo do registro."""
    success = apply_correction(
        db, file_id, record_id,
        field_no=update.field_no,
        field_name=update.field_name,
        new_value=update.new_value,
        error_id=update.error_id,
    )
    if not success:
        raise HTTPException(status_code=400, detail="Não foi possível aplicar a correção")
    return {"corrected": True, "record_id": record_id}
