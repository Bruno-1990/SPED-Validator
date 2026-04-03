"""FastAPI app principal — API de auditoria SPED EFD."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import files, records, report, search, validation

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


@app.get("/api/health")
def health() -> dict:
    """Health check."""
    return {"status": "ok", "version": "0.2.0"}
