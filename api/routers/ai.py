"""Endpoints de IA para explicacao e revisao de erros fiscais."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import get_db
from src.services.db_types import AuditConnection
from src.services.ai_service import generate_explanation, get_cache_stats
from src.services.ai_review_service import review_error_group

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
    db: AuditConnection = Depends(get_db),
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
    db: AuditConnection = Depends(get_db),
) -> dict:
    """Estatísticas do cache de IA."""
    return get_cache_stats(db)


@router.post("/review/{file_id}/{error_type}")
def review_group(
    file_id: int,
    error_type: str,
    db: AuditConnection = Depends(get_db),
) -> dict:
    """Revisa grupo de erros com IA — tribunal de validacao.

    Monta dossie com dados reais do SPED e XML, envia para GPT-4o,
    e retorna veredito: valido | falso_positivo | inconclusivo.
    Resultado cacheado por (file_id, error_type).
    """
    # Verificar se arquivo existe
    sped = db.execute("SELECT id FROM sped_files WHERE id = ?", (file_id,)).fetchone()
    if not sped:
        raise HTTPException(status_code=404, detail="Arquivo SPED nao encontrado")

    # Verificar se tem erros desse tipo
    count = db.execute(
        "SELECT COUNT(*) FROM validation_errors WHERE file_id = ? AND error_type = ? AND status = 'open'",
        (file_id, error_type),
    ).fetchone()[0]
    if count == 0:
        raise HTTPException(status_code=404, detail=f"Nenhum erro do tipo {error_type} encontrado")

    return review_error_group(db, file_id, error_type)


@router.delete("/cache")
def clear_cache(
    db: AuditConnection = Depends(get_db),
) -> dict:
    """Limpa todo o cache de IA (force regeneration)."""
    count = db.execute("SELECT COUNT(*) FROM ai_error_cache").fetchone()[0]
    db.execute("DELETE FROM ai_error_cache")
    db.commit()
    return {"cleared": count}
