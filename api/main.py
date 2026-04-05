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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import files, records, report, rules, search, validation

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

# Routers
app.include_router(files.router)
app.include_router(records.router)
app.include_router(validation.router)
app.include_router(report.router)
app.include_router(search.router)
app.include_router(rules.router)


@app.on_event("startup")
def preload_model() -> None:
    """Pre-carrega o modelo de embeddings no startup para evitar delay na primeira validacao."""
    import threading

    def _load():
        try:
            from src.embeddings import get_model
            get_model()
        except Exception:
            pass  # Se falhar, carrega lazy depois

    threading.Thread(target=_load, daemon=True).start()


@app.get("/api/health")
def health() -> dict:
    """Health check."""
    return {"status": "ok", "version": "0.2.0"}
