"""Endpoints de relatório e exportação."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from api.deps import get_db
from src.services.export_service import (
    export_corrected_sped,
    export_errors_csv,
    export_errors_json,
    export_report_markdown,
    export_report_structured,
)

router = APIRouter(prefix="/api/files/{file_id}", tags=["report"])


@router.get("/report/structured")
def get_structured_report(
    file_id: int,
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Relatório estruturado para renderização no frontend."""
    return export_report_structured(db, file_id)


@router.get("/report")
def get_report(
    file_id: int,
    format: str = "md",
    db: sqlite3.Connection = Depends(get_db),
) -> PlainTextResponse:
    """Gera relatório de auditoria.

    Formatos: md (markdown), csv, json
    """
    if format == "md":
        content = export_report_markdown(db, file_id)
        return PlainTextResponse(content, media_type="text/markdown")
    elif format == "csv":
        content = export_errors_csv(db, file_id)
        return PlainTextResponse(content, media_type="text/csv")
    elif format == "json":
        content = export_errors_json(db, file_id)
        return PlainTextResponse(content, media_type="application/json")
    else:
        raise HTTPException(status_code=400, detail=f"Formato '{format}' não suportado. Use: md, csv, json")


@router.get("/download")
def download_corrected(
    file_id: int,
    db: sqlite3.Connection = Depends(get_db),
) -> PlainTextResponse:
    """Baixa arquivo SPED corrigido (.txt pipe-delimited)."""
    content = export_corrected_sped(db, file_id)
    return PlainTextResponse(
        content,
        media_type="text/plain",
        headers={"Content-Disposition": f"attachment; filename=sped_corrigido_{file_id}.txt"},
    )
