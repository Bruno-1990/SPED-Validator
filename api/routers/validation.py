"""Endpoints de validação."""

from __future__ import annotations

import asyncio
import json
import sqlite3

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from api.deps import get_db, get_doc_db_path
from api.schemas.models import ErrorSummary, ValidationErrorInfo, ValidationResponse
from src.services.pipeline import cleanup_pipeline, get_pipeline_progress, run_pipeline
from src.services.validation_service import get_error_summary, get_errors, run_full_validation

router = APIRouter(prefix="/api/files/{file_id}", tags=["validation"])


@router.post("/validate", response_model=ValidationResponse)
def validate(file_id: int, db: sqlite3.Connection = Depends(get_db)) -> ValidationResponse:
    """Executa validação completa do arquivo (síncrono, compatível com versão anterior)."""
    doc_db = get_doc_db_path()
    progress = run_pipeline(db, file_id, doc_db_path=doc_db)
    cleanup_pipeline(file_id)
    return ValidationResponse(
        file_id=file_id,
        total_errors=progress.total_errors,
        status="validated",
    )


@router.get("/validate/stream")
async def validate_stream(file_id: int) -> StreamingResponse:
    """Executa validação com streaming SSE de progresso em tempo real.

    Emite eventos:
    - progress: atualização de estágio e progresso
    - stage_complete: estágio finalizado com contagem de erros
    - auto_correction: correções automáticas aplicadas
    - done: pipeline concluído
    """
    from api.deps import AUDIT_DB_PATH, DOC_DB_PATH
    from src.services.database import get_connection

    doc_db = str(DOC_DB_PATH) if DOC_DB_PATH.exists() else None

    async def event_generator():
        # Executar pipeline em thread separada para não bloquear o event loop
        def _run():
            conn = get_connection(AUDIT_DB_PATH)
            try:
                return run_pipeline(conn, file_id, doc_db_path=doc_db)
            finally:
                conn.close()

        task = asyncio.get_event_loop().run_in_executor(None, _run)

        last_stage = ""
        last_progress = -1
        heartbeat_counter = 0

        while not task.done():
            await asyncio.sleep(0.5)
            heartbeat_counter += 1

            progress = get_pipeline_progress(file_id)
            if not progress:
                # Heartbeat a cada 5s para manter conexao viva
                if heartbeat_counter % 10 == 0:
                    yield ": heartbeat\n\n"
                continue

            # Emitir evento de progresso quando há mudança
            if progress.stage != last_stage or progress.stage_progress != last_progress:
                data = json.dumps(progress.to_dict(), ensure_ascii=False)

                # Emitir stage_complete quando muda de estágio
                if last_stage and progress.stage != last_stage and last_stage != "pending":
                    stage_data = json.dumps({
                        "stage": last_stage,
                        "errors_found": progress.errors_by_stage.get(last_stage, 0),
                    }, ensure_ascii=False)
                    yield f"event: stage_complete\ndata: {stage_data}\n\n"

                yield f"event: progress\ndata: {data}\n\n"
                last_stage = progress.stage
                last_progress = progress.stage_progress
                heartbeat_counter = 0
            elif heartbeat_counter % 10 == 0:
                # Heartbeat a cada 5s quando sem mudanca de progresso
                yield ": heartbeat\n\n"

        # Pipeline concluído — emitir eventos finais
        try:
            result = task.result()
        except Exception as e:
            error_data = json.dumps({"error": str(e)}, ensure_ascii=False)
            yield f"event: error\ndata: {error_data}\n\n"
            return

        # Último stage_complete
        if last_stage and last_stage not in ("concluido", "pending", "erro"):
            stage_data = json.dumps({
                "stage": last_stage,
                "errors_found": result.errors_by_stage.get(last_stage, 0),
            }, ensure_ascii=False)
            yield f"event: stage_complete\ndata: {stage_data}\n\n"

        # Evento de auto-correção
        if result.auto_corrected > 0:
            auto_data = json.dumps({
                "corrected": result.auto_corrected,
            }, ensure_ascii=False)
            yield f"event: auto_correction\ndata: {auto_data}\n\n"

        # Evento final
        done_data = json.dumps({
            "total_errors": result.total_errors,
            "auto_corrected": result.auto_corrected,
            "status": "validated",
            "errors_by_stage": result.errors_by_stage,
        }, ensure_ascii=False)
        yield f"event: done\ndata: {done_data}\n\n"

        cleanup_pipeline(file_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/errors", response_model=list[ValidationErrorInfo])
def list_errors(
    file_id: int,
    error_type: str | None = None,
    severity: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: sqlite3.Connection = Depends(get_db),
) -> list[ValidationErrorInfo]:
    """Lista erros de validação com filtros."""
    rows = get_errors(db, file_id, error_type=error_type, severity=severity, limit=limit, offset=offset)
    return [ValidationErrorInfo(**r) for r in rows]


@router.get("/summary", response_model=ErrorSummary)
def summary(file_id: int, db: sqlite3.Connection = Depends(get_db)) -> ErrorSummary:
    """Resumo dos erros por tipo e severidade."""
    return ErrorSummary(**get_error_summary(db, file_id))


@router.delete("/errors/{error_id}")
def dismiss_error(
    file_id: int,
    error_id: int,
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Ignora (remove) um erro individual."""
    db.execute(
        "DELETE FROM validation_errors WHERE id = ? AND file_id = ?",
        (error_id, file_id),
    )
    # Atualizar contagem
    total = db.execute(
        "SELECT COUNT(*) FROM validation_errors WHERE file_id = ? AND status = 'open'",
        (file_id,),
    ).fetchone()[0]
    db.execute(
        "UPDATE sped_files SET total_errors = ? WHERE id = ?",
        (total, file_id),
    )
    db.commit()
    db.execute(
        "INSERT INTO audit_log (file_id, action, details) VALUES (?, ?, ?)",
        (file_id, "dismiss", f"Erro {error_id} ignorado pelo analista."),
    )
    db.commit()
    return {"dismissed": True, "total_errors": total}


@router.delete("/errors")
def dismiss_all_errors(
    file_id: int,
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Ignora (remove) todos os erros abertos do arquivo."""
    deleted = db.execute(
        "DELETE FROM validation_errors WHERE file_id = ? AND status = 'open'",
        (file_id,),
    ).rowcount
    # Atualizar contagem
    total = db.execute(
        "SELECT COUNT(*) FROM validation_errors WHERE file_id = ?",
        (file_id,),
    ).fetchone()[0]
    db.execute(
        "UPDATE sped_files SET total_errors = ? WHERE id = ?",
        (total, file_id),
    )
    db.commit()
    db.execute(
        "INSERT INTO audit_log (file_id, action, details) VALUES (?, ?, ?)",
        (file_id, "dismiss_all", f"{deleted} erros ignorados pelo analista."),
    )
    db.commit()
    return {"dismissed": deleted, "total_errors": total}
