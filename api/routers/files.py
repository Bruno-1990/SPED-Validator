"""Endpoints de arquivos SPED."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from api.deps import get_db
from api.schemas.models import FileInfo, FileUploadResponse
from src.services.file_service import delete_file, get_file, list_files, upload_file

router = APIRouter(prefix="/api/files", tags=["files"])


@router.post("/upload", response_model=FileUploadResponse)
def upload(file: UploadFile, db: sqlite3.Connection = Depends(get_db)) -> FileUploadResponse:
    """Upload de arquivo SPED EFD."""
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
        content = file.file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        file_id = upload_file(db, tmp_path)
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
