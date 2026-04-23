"""FastAPI app principal — API de auditoria SPED EFD."""

from __future__ import annotations

import warnings

# Pydantic emite UserWarning quando um campo se chama "register", pois
# ABCMeta.register existe em BaseModel. O campo é intencional (registro SPED).
warnings.filterwarnings(
    "ignore",
    message='Field name "register".*shadows an attribute',
    category=UserWarning,
)

import os  # noqa: E402

from fastapi import Depends, FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from api.auth import verify_api_key  # noqa: E402
from api.routers import files, records, report, rules, search, validation  # noqa: E402
from api.routers.audit_scope import router as audit_scope_router  # noqa: E402
from api.routers.clientes import router as clientes_router  # noqa: E402
from api.routers.xml import router as xml_router  # noqa: E402
from api.routers.ai import router as ai_router  # noqa: E402

import logging
import traceback

from fastapi.responses import JSONResponse
from starlette.requests import Request as StarletteRequest

_logger = logging.getLogger("api")

app = FastAPI(
    title="SPED EFD Audit API",
    description="API de auditoria e validação de arquivos SPED EFD",
    version="0.2.0",
)


@app.exception_handler(Exception)
async def _unhandled(request: StarletteRequest, exc: Exception) -> JSONResponse:
    tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
    _logger.error("Unhandled: %s\n%s", exc, "".join(tb))
    return JSONResponse(status_code=500, content={"detail": str(exc)})

# CORS — bug #2: wildcard + credentials viola spec; lista vem de ALLOWED_ORIGINS
_origins_env = os.getenv(
    "ALLOWED_ORIGINS", "http://localhost:5175,http://localhost:5173"
)
_allowed_origins = [o.strip() for o in _origins_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers — todos protegidos por API Key
_auth = [Depends(verify_api_key)]
app.include_router(files.router, dependencies=_auth)
app.include_router(records.router, dependencies=_auth)
app.include_router(validation.router, dependencies=_auth)
app.include_router(report.router, dependencies=_auth)
app.include_router(search.router, dependencies=_auth)
app.include_router(rules.router, dependencies=_auth)
app.include_router(audit_scope_router)
app.include_router(clientes_router, dependencies=_auth)
app.include_router(xml_router, dependencies=_auth)
app.include_router(ai_router, dependencies=_auth)


@app.on_event("startup")
def preload_model() -> None:
    """Pre-carrega o modelo de embeddings no startup para evitar delay na primeira validacao."""
    import threading

    def _load() -> None:
        try:
            from src.embeddings import get_model  # noqa: E402
            get_model()
        except Exception:  # noqa: S110
            pass  # Se falhar, carrega lazy depois

    threading.Thread(target=_load, daemon=True).start()


@app.get("/api/health")
def health() -> dict:
    """Health check público (sem API Key) — usado pelo frontend para exibir versão da API."""
    return {"status": "ok", "version": app.version}
