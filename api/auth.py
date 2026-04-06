"""Autenticação por API Key (MOD-15)."""

from __future__ import annotations

import logging
import os

from fastapi import Header, HTTPException

logger = logging.getLogger(__name__)


def verify_api_key(x_api_key: str | None = Header(None)) -> str:
    """Valida API Key enviada no header X-API-Key.

    - Se API_KEY não está configurada no ambiente: modo dev, aceita qualquer key.
    - Se API_KEY está configurada: exige match exato.
    - Retorna a key validada.
    """
    expected = os.getenv("API_KEY")

    if not expected:
        logger.warning("API_KEY não configurada — modo desenvolvimento (qualquer key aceita)")
        return x_api_key or "dev"

    if not x_api_key or x_api_key != expected:
        raise HTTPException(status_code=401, detail="API Key inválida ou ausente")

    return x_api_key
