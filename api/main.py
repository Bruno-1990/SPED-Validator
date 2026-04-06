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

from fastapi import Depends, FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from api.auth import verify_api_key  # noqa: E402
from api.routers import files, records, report, rules, search, validation  # noqa: E402

app = FastAPI(
    title="SPED EFD Audit API",
    description="API de auditoria e validação de arquivos SPED EFD",
    version="0.2.0",
)

# CORS — permitir frontend local
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
    """Health check."""
    return {"status": "ok", "version": "0.2.0"}
