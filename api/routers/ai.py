"""Endpoints de IA para explicação de erros fiscais."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import get_db
from src.services.ai_service import generate_explanation, get_cache_stats

router = APIRouter(prefix="/api/ai", tags=["ai"])


class ExplainRequest(BaseModel):
    error_type: str
    message: str
    regime: str = ""
    uf: str = ""
    beneficio_codigo: str = ""
    ind_oper: str = ""
    campo_principal: str = ""
    rule_id: str = ""
    value: str = ""
    expected_value: str = ""
    register: str = ""
    severity: str = ""


@router.post("/explain")
def explain_error(
    req: ExplainRequest,
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Gera explicação de erro via IA (com cache incremental).

    Retorna texto cacheado se disponível, senão chama OpenAI e salva.
    """
    result = generate_explanation(
        db=db,
        error_type=req.error_type,
        message=req.message,
        regime=req.regime,
        uf=req.uf,
        beneficio_codigo=req.beneficio_codigo,
        ind_oper=req.ind_oper,
        campo_principal=req.campo_principal,
        rule_id=req.rule_id,
        value=req.value,
        expected_value=req.expected_value,
        register=req.register,
        severity=req.severity,
    )
    return result


@router.get("/cache/stats")
def cache_stats(
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Estatísticas do cache de IA."""
    return get_cache_stats(db)


@router.delete("/cache")
def clear_cache(
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Limpa todo o cache de IA (force regeneration)."""
    count = db.execute("SELECT COUNT(*) FROM ai_error_cache").fetchone()[0]
    db.execute("DELETE FROM ai_error_cache")
    db.commit()
    return {"cleared": count}
