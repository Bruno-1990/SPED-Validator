"""Endpoints de registros SPED."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_db
from src.services.db_types import AuditConnection
from api.schemas.models import CorrectionRequest, PaginatedResponse, RecordInfo
from src.services.correction_service import (
    CorrectionNotAllowed,
    MissingJustificativa,
    apply_correction,
)

router = APIRouter(prefix="/api/files/{file_id}/records", tags=["records"])


@router.get("")
def list_records(
    file_id: int,
    block: str | None = None,
    register: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 100,
    db: AuditConnection = Depends(get_db),
) -> PaginatedResponse[RecordInfo]:
    """Lista registros do arquivo com filtros e paginação."""
    where = "WHERE file_id = ?"
    params: list = [file_id]

    if block:
        where += " AND block = ?"
        params.append(block)
    if register:
        where += " AND register = ?"
        params.append(register)
    if status:
        where += " AND status = ?"
        params.append(status)

    total = db.execute(f"SELECT COUNT(*) FROM sped_records {where}", params).fetchone()[0]  # noqa: S608  # nosec B608

    offset = (page - 1) * page_size
    query = f"SELECT * FROM sped_records {where} ORDER BY line_number LIMIT ? OFFSET ?"  # noqa: S608  # nosec B608
    rows = db.execute(query, [*params, page_size, offset]).fetchall()

    return PaginatedResponse(
        total=total,
        page=page,
        page_size=page_size,
        has_next=(page * page_size) < total,
        data=[RecordInfo(**dict(r)) for r in rows],
    )


@router.get("/{record_id}", response_model=RecordInfo)
def get_record(file_id: int, record_id: int, db: AuditConnection = Depends(get_db)) -> RecordInfo:
    """Detalhe de um registro."""
    row = db.execute(
        "SELECT * FROM sped_records WHERE id = ? AND file_id = ?",
        (record_id, file_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Registro não encontrado")
    return RecordInfo(**dict(row))


_PROHIBITED_FIELDS = frozenset({
    "CST_ICMS", "CFOP", "ALIQ_ICMS", "CST_IPI", "COD_AJ_APUR", "VL_AJ_APUR",
})


@router.put("/{record_id}")
def update_record(
    file_id: int,
    record_id: int,
    update: CorrectionRequest,
    db: AuditConnection = Depends(get_db),
) -> dict:
    """Aplica correção em um campo do registro com aprovação humana obrigatória."""
    if update.field_name in _PROHIBITED_FIELDS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Campo '{update.field_name}' não pode ser corrigido automaticamente. "
                "Correções de CST, CFOP, alíquota e ajustes de apuração exigem "
                "retificação manual do SPED junto à SEFAZ por profissional habilitado."
            ),
        )

    try:
        success = apply_correction(
            db, file_id, record_id,
            field_no=update.field_no,
            field_name=update.field_name,
            new_value=update.new_value,
            error_id=update.error_id,
            justificativa=update.justificativa,
            correction_type=update.correction_type,
            rule_id=update.rule_id,
        )
    except CorrectionNotAllowed as e:
        raise HTTPException(status_code=403, detail=str(e))
    except MissingJustificativa as e:
        raise HTTPException(status_code=422, detail=str(e))
    if not success:
        raise HTTPException(status_code=400, detail="Não foi possível aplicar a correção")
    return {"corrected": True, "record_id": record_id}
