"""Endpoints de arquivos SPED."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from api.deps import get_db
from api.schemas.models import FileInfo, FileUploadResponse
from src.services.file_service import clear_all_audit, clear_audit, delete_file, get_file, list_files, upload_file

router = APIRouter(prefix="/api/files", tags=["files"])

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB


@router.post("/upload", response_model=FileUploadResponse)
def upload(
    file: UploadFile,
    regime: str | None = None,
    db: sqlite3.Connection = Depends(get_db),
) -> FileUploadResponse:
    """Upload de arquivo SPED EFD com limite de 100 MB e leitura streaming.

    Query params:
        regime: 'normal' | 'simples_nacional' | None (auto-detectar via IND_PERFIL)
    """
    # Leitura streaming em chunks de 1 MB
    chunk_size = 1024 * 1024
    total_read = 0
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
        while True:
            chunk = file.file.read(chunk_size)
            if not chunk:
                break
            total_read += len(chunk)
            if total_read > MAX_FILE_SIZE:
                tmp_path = Path(tmp.name)
                tmp_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"Arquivo excede o limite de 100 MB ({total_read / (1024*1024):.0f} MB recebidos)",
                )
            tmp.write(chunk)
        tmp_path = Path(tmp.name)

    try:
        file_id = upload_file(db, tmp_path)

        # Salvar regime informado pelo usuario (override)
        if regime in ("normal", "simples_nacional"):
            db.execute(
                "UPDATE sped_files SET regime_override = ? WHERE id = ?",
                (regime, file_id),
            )
            db.commit()

        info = get_file(db, file_id)
        if not info:
            raise HTTPException(status_code=500, detail="Erro ao processar arquivo")
        return FileUploadResponse(
            file_id=file_id,
            filename=file.filename or "unknown",
            total_records=info["total_records"],
            status=info["status"],
        )
    finally:
        tmp_path.unlink(missing_ok=True)


@router.get("", response_model=list[FileInfo])
def list_all(db: sqlite3.Connection = Depends(get_db)) -> list[FileInfo]:
    """Lista todos os arquivos processados."""
    files = list_files(db)
    return [FileInfo(**f) for f in files]


@router.delete("/audit")
def clear_all_audits(db: sqlite3.Connection = Depends(get_db)) -> dict:
    """Limpa todos os dados de validação/audit de TODOS os arquivos."""
    removed = clear_all_audit(db)
    return {"cleared": True, "removed": removed}


@router.get("/{file_id}", response_model=FileInfo)
def get_detail(file_id: int, db: sqlite3.Connection = Depends(get_db)) -> FileInfo:
    """Detalhes de um arquivo."""
    info = get_file(db, file_id)
    if not info:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    return FileInfo(**info)


@router.delete("/{file_id}")
def delete(file_id: int, db: sqlite3.Connection = Depends(get_db)) -> dict:
    """Remove arquivo e todos os dados associados."""
    if not delete_file(db, file_id):
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    return {"deleted": True}


@router.delete("/{file_id}/audit")
def clear_file_audit(file_id: int, db: sqlite3.Connection = Depends(get_db)) -> dict:
    """Limpa todos os dados de validação/audit, mantendo o arquivo e registros."""
    removed = clear_audit(db, file_id)
    if removed < 0:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    return {"cleared": True, "removed": removed}
