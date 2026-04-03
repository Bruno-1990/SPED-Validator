"""Endpoints de busca na documentação."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from api.deps import get_doc_db_path
from api.schemas.models import SearchResultInfo

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("", response_model=list[SearchResultInfo])
def search_docs(
    q: str = Query(..., description="Texto de busca"),
    register: str | None = Query(None, description="Filtrar por registro (ex: C100)"),
    field_name: str | None = Query(None, description="Filtrar por campo (ex: IND_OPER)"),
    top_k: int = Query(5, ge=1, le=20, description="Número de resultados"),
) -> list[SearchResultInfo]:
    """Busca na documentação SPED indexada."""
    doc_db = get_doc_db_path()
    if not doc_db:
        raise HTTPException(status_code=503, detail="Banco de documentação não disponível")

    from src.searcher import search

    results = search(query=q, db_path=doc_db, register=register, field_name=field_name, top_k=top_k)

    return [
        SearchResultInfo(
            source_file=r.chunk.source_file,
            register=r.chunk.register,
            field_name=r.chunk.field_name,
            heading=r.chunk.heading,
            content=r.chunk.content,
            score=r.score,
            source=r.source,
        )
        for r in results
    ]
