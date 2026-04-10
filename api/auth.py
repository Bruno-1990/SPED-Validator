"""Autenticação por API Key (MOD-15)."""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from fastapi import Header, HTTPException, Query

load_dotenv()

logger = logging.getLogger(__name__)
_dev_mode_logged = False


def verify_api_key(
    x_api_key: str | None = Header(None),
    api_key: str | None = Query(None, alias="api_key"),
) -> str:
    """Valida API Key via header X-API-Key ou query param ?api_key=.

    O fallback por query param e necessario para EventSource (SSE),
    que nao suporta headers customizados.

    - Se API_KEY nao esta configurada no ambiente: modo dev, aceita qualquer key.
    - Se API_KEY esta configurada: exige match exato.
    """
    key = x_api_key or api_key
    expected = os.getenv("API_KEY")

    if not expected:
        global _dev_mode_logged  # noqa: PLW0603
        if not _dev_mode_logged:
            logger.warning("API_KEY nao configurada — modo desenvolvimento (qualquer key aceita)")
            _dev_mode_logged = True
        return key or "dev"

    if not key or key != expected:
        raise HTTPException(status_code=401, detail="API Key invalida ou ausente")

    return key
