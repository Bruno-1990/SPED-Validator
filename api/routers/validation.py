"""Endpoints de validação."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
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
from src.services.rate_limiter import check_validation_rate_limit
from src.services.db_types import AuditConnection
from src.services.validation_service import get_error_summary, get_errors

router = APIRouter(prefix="/api/files/{file_id}", tags=["validation"])

_MODES = ("sped_only", "sped_xml")


def _require_xml_for_sped_xml_mode(db: AuditConnection, file_id: int) -> None:
    try:
        row = db.execute(
            "SELECT COUNT(*) FROM nfe_xmls WHERE file_id = ? AND status = 'active'",
            (file_id,),
        ).fetchone()
        n = int(row[0] if row and row[0] is not None else 0)
    except Exception:
        n = 0
    if n == 0:
        raise HTTPException(
            status_code=400,
            detail="Modo sped_xml requer ao menos um XML NF-e ativo vinculado ao arquivo.",
        )


@router.post("/validate", response_model=ValidationResponse)
def validate(
    file_id: int,
    request: Request,
    db: AuditConnection = Depends(get_db),
    mode: str = Query("sped_only", description="sped_only | sped_xml"),
) -> ValidationResponse:
    """Executa validação completa do arquivo (síncrono, compatível com versão anterior)."""
    check_validation_rate_limit(request)
    if mode not in _MODES:
        raise HTTPException(status_code=400, detail=f"mode invalido; use {_MODES}")
    if mode == "sped_xml":
        _require_xml_for_sped_xml_mode(db, file_id)
    doc_db = get_doc_db_path()
    progress = run_pipeline(db, file_id, doc_db_path=doc_db, validation_mode=mode)
    cleanup_pipeline(file_id)
    return ValidationResponse(
        file_id=file_id,
        total_errors=progress.total_errors,
        status="validated",
    )


@router.get("/validate/stream")
async def validate_stream(
    file_id: int,
    mode: str = Query("sped_only", description="sped_only | sped_xml"),
) -> StreamingResponse:
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
    if mode not in _MODES:
        raise HTTPException(status_code=400, detail=f"mode invalido; use {_MODES}")

    async def event_generator():  # type: ignore[no-untyped-def]
        # Executar pipeline em thread separada para não bloquear o event loop
        def _run() -> PipelineProgress:
            conn = get_connection(AUDIT_DB_PATH)
            try:
                if mode == "sped_xml":
                    cur = conn.execute(
                        "SELECT COUNT(*) FROM nfe_xmls WHERE file_id = ? AND status = 'active'",
                        (file_id,),
                    ).fetchone()
                    n = int(cur[0] if cur and cur[0] is not None else 0)
                    if n == 0:
                        raise ValueError(
                            "Modo sped_xml requer ao menos um XML NF-e ativo vinculado ao arquivo."
                        )
                return run_pipeline(conn, file_id, doc_db_path=doc_db, validation_mode=mode)
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
    db: AuditConnection = Depends(get_db),
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
def summary(file_id: int, db: AuditConnection = Depends(get_db)) -> ErrorSummary:
    """Resumo dos erros por tipo e severidade."""
    return ErrorSummary(**get_error_summary(db, file_id))


def _has_xml_cruzamento(db: AuditConnection, file_id: int) -> bool:
    """Verifica se o cruzamento XML foi executado (ha resultados persistidos)."""
    try:
        from src.services.db_helpers import scalar_or
        cnt = scalar_or(
            db.execute("SELECT COUNT(*) FROM nfe_cruzamento WHERE file_id = ?", (file_id,))
        )
        if cnt > 0:
            return True
        # Pode ter rodado sem divergencias — verifica via validation_errors
        cnt2 = scalar_or(
            db.execute(
                "SELECT COUNT(*) FROM validation_errors WHERE file_id = ? AND categoria = 'cruzamento_xml'",
                (file_id,),
            )
        )
        if cnt2 > 0:
            return True
        row = db.execute(
            "SELECT xml_crossref_completed_at FROM sped_files WHERE id = ?",
            (file_id,),
        ).fetchone()
        if row is not None:
            v = row[0] if isinstance(row, tuple) else row.get("xml_crossref_completed_at")
            return bool(v)
        return False
    except Exception:
        return False


@router.get("/audit-scope", response_model=AuditScope)
def audit_scope(
    file_id: int,
    db: AuditConnection = Depends(get_db),
) -> AuditScope:
    """Dashboard de escopo da auditoria — MOD-11."""

    context = build_context(file_id, db, validation_mode="sped_xml")

    # Determinar tabelas externas disponíveis
    ref_loader = ReferenceLoader()
    available = ref_loader.available_tables()
    tabelas_externas = {
        "aliquotas_internas_uf": "disponivel" if "aliquotas_internas_uf" in available else "indisponivel",
        "fcp_por_uf": "disponivel" if "fcp_por_uf" in available else "indisponivel",
        "ncm_tipi": "disponivel" if "ncm_tipi_categorias" in available else "indisponivel",
        "mva_por_ncm_uf": "disponivel" if "mva_por_ncm_uf" in available else "indisponivel",
        "codigos_ajuste_uf": "disponivel" if "codigos_ajuste_uf" in available else "indisponivel",
    }

    has_aliq_tables = tabelas_externas["aliquotas_internas_uf"] == "disponivel"
    has_mva_tables = tabelas_externas["mva_por_ncm_uf"] == "disponivel"
    is_simples = context.regime == TaxRegime.SIMPLES_NACIONAL

    # Verificar benefícios fiscais ativos
    has_beneficios = bool(context.beneficios_ativos)

    # ── Detectar conteudo real do arquivo ──
    def _count_reg(register: str) -> int:
        return db.execute(
            "SELECT COUNT(*) FROM sped_records WHERE file_id = ? AND register = ?",
            (file_id, register),
        ).fetchone()[0]

    def _count_block(block: str) -> int:
        return db.execute(
            "SELECT COUNT(*) FROM sped_records WHERE file_id = ? AND block = ?",
            (file_id, block),
        ).fetchone()[0]

    has_c100 = _count_reg("C100") > 0
    has_c170 = _count_reg("C170") > 0
    has_c190 = _count_reg("C190") > 0
    has_bloco_d = _count_block("D") > 5  # D001+D990 sempre existem
    has_bloco_k = _count_block("K") > 5  # K001+K990 sempre existem
    has_bloco_h = _count_reg("H010") > 0
    has_e110 = _count_reg("E110") > 0
    has_e111 = _count_reg("E111") > 0
    has_e115 = _count_reg("E115") > 0
    has_c197 = _count_reg("C197") > 0
    is_validated = db.execute(
        "SELECT status FROM sped_files WHERE id = ?", (file_id,)
    ).fetchone()[0] == "validated"

    # XMLs vinculados e cruzamento executado
    has_xmls = False
    has_xml_cruzamento = False
    try:
        xml_count = db.execute(
            "SELECT COUNT(*) FROM nfe_xmls WHERE file_id = ?", (file_id,)
        ).fetchone()[0]
        has_xmls = xml_count > 0
        if has_xmls:
            has_xml_cruzamento = _has_xml_cruzamento(db, file_id)
    except Exception:
        pass

    # Verificar benefícios fiscais ativos
    has_beneficios = bool(context.beneficios_ativos)

    # ── Helper: status baseado em se validacao rodou e se tem dados ──
    def _check(has_data: bool, needs_table: bool = True, table_ok: bool = True) -> str:
        if not is_validated:
            return "nao_executado"
        if not has_data:
            return "nao_aplicavel"
        if needs_table and not table_ok:
            return "parcial"
        return "ok"

    def _motivo(status: str, sem_dados: str = "", sem_tabela: str = "", nao_validado: str = "") -> str | None:
        if status == "nao_executado":
            return nao_validado or "Validacao SPED nao executada"
        if status == "nao_aplicavel":
            return sem_dados
        if status == "parcial":
            return sem_tabela
        return None

    # ── Checks dinamicos (30 validators) ──

    # Estrutural: sempre roda se validado
    s_fmt = _check(True)
    s_fld = _check(True)
    s_intra = _check(True)

    # Cruzamento entre blocos: depende de ter C100+C170+C190
    s_cross = _check(has_c100 and has_c170)
    s_recalc = _check(has_c100 and has_c170)
    s_cst = _check(has_c100)
    s_semantics = _check(has_c100)
    s_pis = _check(has_c170)
    s_param = _check(has_c170)
    s_ncm = _check(has_c170)
    s_aliq = _check(has_c170, needs_table=True, table_ok=has_aliq_tables)
    s_c190 = _check(has_c190)
    s_bloco_d = _check(has_bloco_d)
    # Beneficio pode vir de E111, E115, C197 ou XMLs com cBenef
    has_beneficio_data = has_e111 or has_e115 or has_c197
    s_audit_ben = _check(has_beneficio_data, needs_table=True, table_ok=tabelas_externas["codigos_ajuste_uf"] == "disponivel")
    s_pend = _check(has_c100)
    s_bc = _check(has_c170)
    s_difal = _check(has_c170, needs_table=True, table_ok=has_aliq_tables)
    s_ben_fiscal = _check(has_c100)
    s_ben_cross = _check(has_beneficios)
    s_dev = _check(has_c100)
    s_ipi = _check(has_c170)
    s_dest = _check(has_c100)
    s_cfop = _check(has_c170)
    s_st = _check(has_c170, needs_table=True, table_ok=has_mva_tables)
    s_simples = "nao_aplicavel" if not is_simples else _check(True)
    s_apur = _check(has_e110)
    s_c_serv = _check(has_c100)
    s_bloco_k = _check(has_bloco_k)
    s_retif = _check(True)

    # XML crossref
    if has_xml_cruzamento:
        s_xml = "ok"
    elif has_xmls:
        s_xml = "parcial"
    else:
        s_xml = "nao_executado"

    checks: list[AuditCheckInfo] = [
        # Estágio 1: Estrutural
        AuditCheckInfo(id="format_validation", status=s_fmt, regras=9,
                       motivo_parcial=_motivo(s_fmt)),
        AuditCheckInfo(id="field_validation", status=s_fld, regras=4,
                       motivo_parcial=_motivo(s_fld)),
        AuditCheckInfo(id="intra_register", status=s_intra, regras=10,
                       motivo_parcial=_motivo(s_intra)),
        # Estágio 2: Cruzamento
        AuditCheckInfo(id="cross_block", status=s_cross, regras=7,
                       motivo_parcial=_motivo(s_cross, sem_dados="Sem registros C100/C170 para cruzar")),
        AuditCheckInfo(id="tax_recalculation", status=s_recalc, regras=8,
                       motivo_parcial=_motivo(s_recalc, sem_dados="Sem registros C100/C170 para recalcular")),
        AuditCheckInfo(id="cst_validation", status=s_cst, regras=6,
                       motivo_parcial=_motivo(s_cst, sem_dados="Sem registros C100")),
        AuditCheckInfo(id="fiscal_semantics", status=s_semantics, regras=13,
                       motivo_parcial=_motivo(s_semantics, sem_dados="Sem registros C100")),
        AuditCheckInfo(id="pis_cofins", status=s_pis, regras=6,
                       motivo_parcial=_motivo(s_pis, sem_dados="Sem itens C170")),
        AuditCheckInfo(id="parametrizacao", status=s_param, regras=3,
                       motivo_parcial=_motivo(s_param, sem_dados="Sem itens C170")),
        AuditCheckInfo(id="ncm_validation", status=s_ncm, regras=6,
                       motivo_parcial=_motivo(s_ncm, sem_dados="Sem itens C170")),
        AuditCheckInfo(id="aliquota_validation", status=s_aliq, regras=7,
                       motivo_parcial=_motivo(s_aliq, sem_tabela="Aliquotas por UF nao disponiveis")),
        AuditCheckInfo(id="c190_consolidation", status=s_c190, regras=2,
                       motivo_parcial=_motivo(s_c190, sem_dados="Sem registros C190")),
        AuditCheckInfo(id="bloco_d", status=s_bloco_d, regras=6,
                       motivo_parcial=_motivo(s_bloco_d, sem_dados="Arquivo nao possui Bloco D (CT-e)")),
        AuditCheckInfo(id="audit_beneficios", status=s_audit_ben, regras=50,
                       motivo_parcial=_motivo(s_audit_ben, sem_dados="Sem registros de beneficio (E111/E115/C197)", sem_tabela="Tabela 5.1.1 de codigos de ajuste nao disponivel")),
        AuditCheckInfo(id="pendentes", status=s_pend, regras=5,
                       motivo_parcial=_motivo(s_pend, sem_dados="Sem registros C100")),
        AuditCheckInfo(id="base_calculo", status=s_bc, regras=5,
                       motivo_parcial=_motivo(s_bc, sem_dados="Sem itens C170")),
        AuditCheckInfo(id="difal_validation", status=s_difal, regras=12,
                       motivo_parcial=_motivo(s_difal, sem_tabela="Tabelas de aliquotas por UF nao disponiveis")),
        AuditCheckInfo(id="beneficio_fiscal", status=s_ben_fiscal, regras=3,
                       motivo_parcial=_motivo(s_ben_fiscal, sem_dados="Sem registros C100")),
        AuditCheckInfo(id="beneficio_cross", status=s_ben_cross, regras=9,
                       motivo_parcial=_motivo(s_ben_cross, sem_dados="Nenhum beneficio fiscal cadastrado para este contribuinte")),
        AuditCheckInfo(id="devolucao", status=s_dev, regras=3,
                       motivo_parcial=_motivo(s_dev, sem_dados="Sem registros C100")),
        AuditCheckInfo(id="ipi_validation", status=s_ipi, regras=3,
                       motivo_parcial=_motivo(s_ipi, sem_dados="Sem itens C170")),
        AuditCheckInfo(id="destinatario", status=s_dest, regras=3,
                       motivo_parcial=_motivo(s_dest, sem_dados="Sem registros C100")),
        AuditCheckInfo(id="cfop_validation", status=s_cfop, regras=3,
                       motivo_parcial=_motivo(s_cfop, sem_dados="Sem itens C170")),
        AuditCheckInfo(id="st_validation", status=s_st, regras=8,
                       motivo_parcial=_motivo(s_st, sem_tabela="Tabelas MVA/pauta fiscal nao disponiveis")),
        AuditCheckInfo(id="simples_nacional", status=s_simples, regras=12,
                       motivo_parcial="Contribuinte em Regime Normal" if not is_simples else _motivo(s_simples)),
        AuditCheckInfo(id="apuracao_icms", status=s_apur, regras=11,
                       motivo_parcial=_motivo(s_apur, sem_dados="Sem registro E110 (apuracao)")),
        AuditCheckInfo(id="bloco_c_servicos", status=s_c_serv, regras=4,
                       motivo_parcial=_motivo(s_c_serv, sem_dados="Sem registros C100")),
        AuditCheckInfo(id="bloco_k", status=s_bloco_k, regras=4,
                       motivo_parcial=_motivo(s_bloco_k, sem_dados="Arquivo nao possui Bloco K (producao/estoque)")),
        AuditCheckInfo(id="retificador", status=s_retif, regras=2,
                       motivo_parcial=_motivo(s_retif)),
        # Cruzamento NF-e XML
        AuditCheckInfo(
            id="xml_crossref", status=s_xml, regras=17,
            motivo_parcial=(
                None if s_xml == "ok"
                else "XMLs vinculados mas cruzamento nao executado" if has_xmls
                else "Nenhum XML de NF-e vinculado"
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


@router.post("/findings/{finding_id}/resolve")
def resolve_finding(
    file_id: int,
    finding_id: int,
    body: dict,
    db: AuditConnection = Depends(get_db),
) -> dict:
    """Registra resolucao de um apontamento (aceitar/rejeitar/postergar/ciencia)."""
    from src.services.correction_service import resolve_finding as _resolve

    status = body.get("status", "")
    rule_id = body.get("rule_id", "")
    justificativa = body.get("justificativa")
    user_id = body.get("user_id")
    prazo_revisao = body.get("prazo_revisao")

    ok = _resolve(
        db, file_id, finding_id, rule_id,
        status=status, user_id=user_id,
        justificativa=justificativa,
        prazo_revisao=prazo_revisao,
    )
    if not ok:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail="Status invalido ou justificativa insuficiente para rejeicao (min 20 chars).",
        )
    return {"resolved": True, "finding_id": finding_id, "status": status}


@router.get("/findings/resolutions")
def list_finding_resolutions(
    file_id: int,
    db: AuditConnection = Depends(get_db),
) -> list[dict]:
    """Lista resolucoes de apontamentos do arquivo."""
    from src.services.correction_service import get_finding_resolutions
    return get_finding_resolutions(db, file_id)


@router.delete("/errors/{error_id}")
def dismiss_error(
    file_id: int,
    error_id: int,
    db: AuditConnection = Depends(get_db),
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


@router.delete("/errors/group/{error_type}")
def dismiss_error_group(
    file_id: int,
    error_type: str,
    db: AuditConnection = Depends(get_db),
) -> dict:
    """Ignora (remove) todos os erros de um tipo especifico."""
    deleted = db.execute(
        "DELETE FROM validation_errors WHERE file_id = ? AND error_type = ? AND status = 'open'",
        (file_id, error_type),
    ).rowcount
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
        (file_id, "dismiss_group", f"{deleted} erros do tipo {error_type} ignorados pelo analista."),
    )
    db.commit()
    return {"dismissed": deleted, "error_type": error_type, "total_errors": total}


@router.delete("/errors")
def dismiss_all_errors(
    file_id: int,
    db: AuditConnection = Depends(get_db),
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
