"""Endpoints de validação."""

from __future__ import annotations

import asyncio
import json
import sqlite3

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from api.deps import get_db, get_doc_db_path
from api.schemas.models import (
    AuditCheckInfo,
    AuditScope,
    ErrorSummary,
    PaginatedResponse,
    ValidationErrorInfo,
    ValidationResponse,
)
from src.services.context_builder import TaxRegime, build_context
from src.services.pipeline import PipelineProgress, cleanup_pipeline, get_pipeline_progress, run_pipeline
from src.services.reference_loader import ReferenceLoader
from src.services.validation_service import get_error_summary, get_errors

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

    async def event_generator():  # type: ignore[no-untyped-def]
        # Executar pipeline em thread separada para não bloquear o event loop
        def _run() -> PipelineProgress:
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

        # Evento final
        done_data = json.dumps({
            "total_errors": result.total_errors,
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


@router.get("/errors")
def list_errors(
    file_id: int,
    error_type: str | None = None,
    severity: str | None = None,
    categoria: str | None = "fiscal",
    certeza: str | None = None,
    impacto: str | None = None,
    page: int = 1,
    page_size: int = 100,
    db: sqlite3.Connection = Depends(get_db),
) -> PaginatedResponse[ValidationErrorInfo]:
    """Lista erros de validação com filtros e paginação."""
    from src.services.validation_service import get_errors_count

    total = get_errors_count(
        db, file_id,
        error_type=error_type, severity=severity,
        categoria=categoria, certeza=certeza, impacto=impacto,
    )

    offset = (page - 1) * page_size
    rows = get_errors(
        db, file_id,
        error_type=error_type, severity=severity,
        categoria=categoria, certeza=certeza, impacto=impacto,
        limit=page_size, offset=offset,
    )
    return PaginatedResponse(
        total=total,
        page=page,
        page_size=page_size,
        has_next=(page * page_size) < total,
        data=[ValidationErrorInfo(**r) for r in rows],
    )


@router.get("/summary", response_model=ErrorSummary)
def summary(file_id: int, db: sqlite3.Connection = Depends(get_db)) -> ErrorSummary:
    """Resumo dos erros por tipo e severidade."""
    return ErrorSummary(**get_error_summary(db, file_id))


@router.get("/audit-scope", response_model=AuditScope)
def audit_scope(
    file_id: int,
    db: sqlite3.Connection = Depends(get_db),
) -> AuditScope:
    """Dashboard de escopo da auditoria — MOD-11."""

    context = build_context(file_id, db)

    # Determinar tabelas externas disponíveis
    ref_loader = ReferenceLoader()
    available = ref_loader.available_tables()
    tabelas_externas = {
        "aliquotas_internas_uf": "disponivel" if "aliquotas_internas_uf" in available else "indisponivel",
        "fcp_por_uf": "disponivel" if "fcp_por_uf" in available else "indisponivel",
        "ncm_tipi": "indisponivel",
        "mva_por_ncm_uf": "indisponivel",
        "codigos_ajuste_uf": "indisponivel",
    }

    has_aliq_tables = tabelas_externas["aliquotas_internas_uf"] == "disponivel"
    is_simples = context.regime == TaxRegime.SIMPLES_NACIONAL

    # Definir checks executados
    checks: list[AuditCheckInfo] = [
        AuditCheckInfo(id="format_validation", status="ok", regras=9),
        AuditCheckInfo(id="field_validation", status="ok", regras=4),
        AuditCheckInfo(id="intra_register", status="ok", regras=10),
        AuditCheckInfo(id="cross_block", status="ok", regras=7),
        AuditCheckInfo(id="tax_recalculation", status="ok", regras=8),
        AuditCheckInfo(id="cst_validation", status="ok", regras=6),
        AuditCheckInfo(id="fiscal_semantics", status="ok", regras=13),
        AuditCheckInfo(
            id="audit_beneficios",
            status="parcial" if tabelas_externas["codigos_ajuste_uf"] == "indisponivel" else "ok",
            regras=50,
            motivo_parcial=(
                "Tabela 5.1.1 de codigos de ajuste por UF nao disponivel"
                if tabelas_externas["codigos_ajuste_uf"] == "indisponivel" else None
            ),
        ),
        AuditCheckInfo(
            id="difal_validation",
            status="ok" if has_aliq_tables else "nao_executado",
            regras=8,
            motivo_parcial=(
                "Tabelas de aliquotas internas por UF nao disponiveis"
                if not has_aliq_tables else None
            ),
        ),
        AuditCheckInfo(
            id="st_com_mva",
            status="nao_executado",
            regras=4,
            motivo_parcial="Tabelas MVA/pauta fiscal nao disponiveis",
        ),
        AuditCheckInfo(
            id="simples_nacional_cst",
            status="nao_aplicavel" if not is_simples else "ok",
            regras=10,
            motivo_parcial=(
                "Contribuinte em Regime Normal"
                if not is_simples else None
            ),
        ),
    ]

    # Calcular cobertura
    total_checks = len(checks)
    ok_count = sum(1 for c in checks if c.status == "ok")
    parcial_count = sum(1 for c in checks if c.status == "parcial")
    na_count = sum(1 for c in checks if c.status == "nao_aplicavel")

    applicable = total_checks - na_count
    cobertura = int(((ok_count + parcial_count * 0.5) / applicable) * 100) if applicable > 0 else 100

    # Período formatado
    periodo = ""
    if context.periodo_ini:
        periodo = f"{context.periodo_ini.month:02d}/{context.periodo_ini.year}"

    # Aviso
    aviso = None
    if cobertura < 100:
        nao_exec = [c.id for c in checks if c.status == "nao_executado"]
        parciais = [c.id for c in checks if c.status == "parcial"]
        partes = []
        if nao_exec:
            partes.append(f"Verificacoes nao executadas: {', '.join(nao_exec)}.")
        if parciais:
            partes.append(f"Verificacoes parciais: {', '.join(parciais)}.")
        aviso = (
            f"Este arquivo foi auditado com cobertura parcial ({cobertura}%). "
            + " ".join(partes)
        )

    return AuditScope(
        regime_identificado=context.regime.value,
        periodo=periodo,
        checks_executados=checks,
        tabelas_externas=tabelas_externas,
        cobertura_estimada_pct=cobertura,
        aviso=aviso,
    )


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
