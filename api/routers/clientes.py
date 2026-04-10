"""Endpoint de consulta de clientes (MySQL DCTF_WEB)."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException

from src.services.client_service import buscar_cliente

router = APIRouter(prefix="/api/clientes", tags=["clientes"])


def _normalizar_cnpj(cnpj: str) -> str:
    """Remove tudo que nao e digito."""
    return re.sub(r"\D", "", cnpj)


@router.get("/cnpj/{cnpj}")
def get_by_cnpj(cnpj: str) -> dict:
    """Busca cliente pelo CNPJ (aceita formatado ou somente digitos)."""
    cnpj_limpo = _normalizar_cnpj(cnpj)
    if len(cnpj_limpo) != 14:
        raise HTTPException(status_code=400, detail="CNPJ deve ter 14 digitos")

    cliente = buscar_cliente(cnpj_limpo)
    if not cliente.encontrado:
        raise HTTPException(status_code=404, detail="Cliente nao encontrado")

    return {
        "cnpj": cnpj_limpo,
        "razao_social": cliente.razao_social,
        "fantasia": cliente.fantasia,
        "regime_tributario": cliente.regime_tributario,
        "beneficios_fiscais": cliente.beneficios_fiscais,
        "simples_optante": cliente.simples_optante,
        "uf": cliente.uf,
        "tipo_empresa": cliente.tipo_empresa,
        "porte": cliente.porte,
        "situacao_cadastral": cliente.situacao_cadastral,
    }
