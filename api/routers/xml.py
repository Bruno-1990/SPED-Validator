"""Endpoints de cruzamento NF-e XML x SPED EFD."""

from __future__ import annotations

import json
import queue
import threading

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from starlette.responses import StreamingResponse

from api.deps import AUDIT_DB_PATH, DOC_DB_PATH, get_db
from src.services.database import get_connection
from src.services.db_types import AuditConnection
from src.services.xml_service import cruzar_xml_vs_sped, upload_nfe_xmls
from src.services.cross_engine import CrossValidationEngine
from src.services.pipeline import run_pipeline, cleanup_pipeline

router = APIRouter(prefix="/api/files/{file_id}/xml", tags=["xml"])


@router.post("/upload")
def upload_xmls(
    file_id: int,
    modo_periodo: str = "validar",
    files: list[UploadFile] = File(...),
    db: AuditConnection = Depends(get_db),
) -> dict:
    """Upload batch de XMLs de NF-e vinculados a um SPED.

    Query params:
        modo_periodo: "validar" (pausa se houver fora de periodo),
                      "importar_todos" ou "pular_fora".
    """
    # Verificar se SPED existe e buscar periodo
    sped = db.execute(
        "SELECT id, period_start, period_end FROM sped_files WHERE id = ?", (file_id,)
    ).fetchone()
    if not sped:
        raise HTTPException(status_code=404, detail="Arquivo SPED nao encontrado")

    period_start = sped[1] if sped[1] else None
    period_end = sped[2] if sped[2] else None

    xml_files: list[tuple[str, bytes]] = []
    for f in files:
        content = f.file.read()
        xml_files.append((f.filename or "unknown.xml", content))

    stats = upload_nfe_xmls(
        db, file_id, xml_files,
        period_start=period_start,
        period_end=period_end,
        modo_periodo=modo_periodo,
    )
    return stats


@router.get("")
def list_xmls(
    file_id: int,
    db: AuditConnection = Depends(get_db),
) -> dict:
    """Lista XMLs vinculados ao SPED com resumo."""
    rows = db.execute(
        "SELECT id, chave_nfe, numero_nfe, serie, cnpj_emitente, "
        "vl_doc, vl_icms, prot_cstat, status, upload_date "
        "FROM nfe_xmls WHERE file_id = ? AND status = 'active' ORDER BY numero_nfe",
        (file_id,),
    ).fetchall()

    xmls = []
    for r in rows:
        xmls.append({
            "id": r[0], "chave_nfe": r[1], "numero_nfe": r[2], "serie": r[3],
            "cnpj_emitente": r[4], "vl_doc": r[5], "vl_icms": r[6],
            "prot_cstat": r[7], "status": r[8], "upload_date": r[9],
        })

    total = len(xmls)
    autorizadas = sum(1 for x in xmls if x["prot_cstat"] == "100")
    canceladas = sum(1 for x in xmls if x["prot_cstat"] in ("101", "135"))

    return {
        "file_id": file_id,
        "total": total,
        "autorizadas": autorizadas,
        "canceladas": canceladas,
        "xmls": xmls,
    }


@router.post("/cruzar")
def executar_cruzamento(
    file_id: int,
    db: AuditConnection = Depends(get_db),
) -> dict:
    """Executa (ou re-executa) o cruzamento XML vs SPED."""
    sped = db.execute("SELECT id FROM sped_files WHERE id = ?", (file_id,)).fetchone()
    if not sped:
        raise HTTPException(status_code=404, detail="Arquivo SPED nao encontrado")

    xmls_count = db.execute(
        "SELECT COUNT(*) FROM nfe_xmls WHERE file_id = ? AND status = 'active'",
        (file_id,),
    ).fetchone()[0]
    if xmls_count == 0:
        raise HTTPException(status_code=400, detail="Nenhum XML vinculado a este SPED")

    # 1. Cruzamento legacy (XML001-XML017)
    findings = cruzar_xml_vs_sped(db, file_id)

    # 2. Motor XC (XC001-XC095) — roda automaticamente junto
    xc_summary = {}
    try:
        sped_info = db.execute(
            "SELECT regime_tributario, cod_ver FROM sped_files WHERE id = ?", (file_id,)
        ).fetchone()
        regime = sped_info[0] or "" if sped_info else ""
        cod_ver = str(sped_info[1] or "") if sped_info else ""

        engine = CrossValidationEngine(db, file_id, regime=regime, cod_ver=cod_ver)
        xc_findings = engine.run()
        engine.persist_findings()
        engine.persist_to_legacy_table()
        xc_summary = engine.get_summary()
    except Exception:
        pass  # Motor XC e complementar, nao bloqueia o legacy

    total_legacy = len(findings)
    total_xc = xc_summary.get("total_errors", 0)

    return {
        "file_id": file_id,
        "xmls_analisados": xmls_count,
        "divergencias": total_legacy + total_xc,
        "legacy": total_legacy,
        "motor_xc": total_xc,
        "por_severidade": {
            "critical": sum(1 for f in findings if f["severity"] == "critical"),
            "error": sum(1 for f in findings if f["severity"] == "error") + xc_summary.get("by_severity", {}).get("error", 0),
            "warning": sum(1 for f in findings if f["severity"] == "warning") + xc_summary.get("by_severity", {}).get("warning", 0),
        },
    }


@router.get("/cruzar/stream")
async def cruzar_stream(file_id: int) -> StreamingResponse:
    """Executa cruzamento XML vs SPED com streaming SSE de progresso."""
    # Mesmo caminho que get_db / validate_stream (SQLite ou DATABASE_URL -> PostgreSQL)
    db_path = AUDIT_DB_PATH

    # Validacoes iniciais com conexao temporaria
    conn_check = get_connection(db_path)
    try:
        sped = conn_check.execute("SELECT id FROM sped_files WHERE id = ?", (file_id,)).fetchone()
        if not sped:
            raise HTTPException(status_code=404, detail="Arquivo SPED nao encontrado")
        xmls_count = conn_check.execute(
            "SELECT COUNT(*) FROM nfe_xmls WHERE file_id = ? AND status = 'active'", (file_id,)
        ).fetchone()[0]
        if xmls_count == 0:
            raise HTTPException(status_code=400, detail="Nenhum XML vinculado a este SPED")
    finally:
        conn_check.close()

    progress_queue: queue.Queue = queue.Queue()

    def run_cruzamento():
        conn = get_connection(AUDIT_DB_PATH)
        try:
            def on_progress(pct: int, msg: str):
                # Cruzamento XML ocupa 0-40% do progresso total
                progress_queue.put(("progress", int(pct * 0.4), msg))

            findings = cruzar_xml_vs_sped(conn, file_id, on_progress=on_progress)

            # Motor XC (XC001-XC095) — roda junto automaticamente
            xc_total = 0
            try:
                progress_queue.put(("progress", 36, "Motor XC: regras avancadas XC001-XC095..."))
                sped_info = conn.execute(
                    "SELECT regime_tributario, cod_ver FROM sped_files WHERE id = ?", (file_id,)
                ).fetchone()
                regime = sped_info[0] or "" if sped_info else ""
                cod_ver = str(sped_info[1] or "") if sped_info else ""

                engine = CrossValidationEngine(conn, file_id, regime=regime, cod_ver=cod_ver)
                engine.run()
                engine.persist_findings()
                engine.persist_to_legacy_table()
                xc_total = engine.get_summary().get("total_errors", 0)
            except Exception:
                pass

            cruzamento_result = {
                "file_id": file_id,
                "xmls_analisados": xmls_count,
                "divergencias": len(findings) + xc_total,
                "legacy": len(findings),
                "motor_xc": xc_total,
                "por_severidade": {
                    "critical": sum(1 for f in findings if f["severity"] == "critical"),
                    "error": sum(1 for f in findings if f["severity"] == "error"),
                    "warning": sum(1 for f in findings if f["severity"] == "warning"),
                },
            }

            # ── Encadear pipeline de validacao SPED completo ──
            progress_queue.put(("progress", 40, "Iniciando auditoria fiscal SPED..."))
            doc_db = str(DOC_DB_PATH) if DOC_DB_PATH.exists() else None

            pipeline_result = run_pipeline(
                conn, file_id, doc_db_path=doc_db, validation_mode="sped_xml"
            )
            cleanup_pipeline(file_id)
            progress_queue.put(("progress", 98, "Auditoria fiscal concluida."))

            result = {
                **cruzamento_result,
                "pipeline_completo": True,
                "total_erros_fiscal": pipeline_result.total_errors,
                "status": "validated",
            }
            progress_queue.put(("done", result))
        except Exception as exc:
            progress_queue.put(("error", str(exc)))
        finally:
            conn.close()

    thread = threading.Thread(target=run_cruzamento, daemon=True)
    thread.start()

    async def event_generator():
        while True:
            try:
                item = progress_queue.get(timeout=600)
            except queue.Empty:
                # Nome distinto de "error" para nao colidir com o evento nativo do EventSource no browser.
                yield "event: cruzar_error\ndata: {\"error\": \"timeout\"}\n\n"
                break

            if item[0] == "progress":
                data = json.dumps({"pct": item[1], "msg": item[2]}, ensure_ascii=False)
                yield f"event: progress\ndata: {data}\n\n"
            elif item[0] == "done":
                data = json.dumps(item[1], ensure_ascii=False)
                yield f"event: done\ndata: {data}\n\n"
                break
            elif item[0] == "error":
                data = json.dumps({"error": item[1]}, ensure_ascii=False)
                yield f"event: cruzar_error\ndata: {data}\n\n"
                break

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/cruzamento")
def get_cruzamento(
    file_id: int,
    rule_id: str | None = None,
    severity: str | None = None,
    db: AuditConnection = Depends(get_db),
) -> dict:
    """Retorna resultado do cruzamento (legacy + Motor XC unificados).

    Prioridade: cross_validation_findings (Motor XC, dados mais ricos).
    Complementa com nfe_cruzamento (legacy XML###) para regras que so existem la.
    """
    items: list[dict] = []
    seen_keys: set[tuple] = set()

    # 1. Buscar do Motor XC (cross_validation_findings) — dados mais ricos
    q_xc = "SELECT * FROM cross_validation_findings WHERE file_id = ?"
    p_xc: list = [file_id]
    if rule_id:
        q_xc += " AND rule_id = ?"
        p_xc.append(rule_id)
    if severity:
        q_xc += " AND severity = ?"
        p_xc.append(severity)
    q_xc += " ORDER BY action_priority, severity, rule_id"

    try:
        cur = db.execute(q_xc, p_xc)
        cols = [d[0] for d in cur.description] if cur.description else []
        for r in cur.fetchall():
            xc = dict(r) if hasattr(r, "keys") else dict(zip(cols, r))
            key = (xc.get("rule_id", ""), xc.get("chave_nfe", ""))
            seen_keys.add(key)
            items.append({
                "id": xc.get("id"),
                "file_id": xc.get("file_id"),
                "nfe_id": None,
                "chave_nfe": xc.get("chave_nfe", ""),
                "rule_id": xc.get("rule_id", ""),
                "severity": xc.get("severity", ""),
                "campo_xml": xc.get("xml_field", ""),
                "valor_xml": xc.get("value_xml", ""),
                "campo_sped": xc.get("sped_field", ""),
                "valor_sped": xc.get("value_sped", ""),
                "diferenca": 0.0,
                "message": xc.get("description", ""),
                "status": xc.get("review_status", "novo"),
                "created_at": xc.get("created_at"),
                "confidence": xc.get("confidence", ""),
                "action_priority": xc.get("action_priority", ""),
                "suggested_action": xc.get("suggested_action", ""),
                "error_type": xc.get("error_type", ""),
                "is_derived": xc.get("is_derived", 0),
            })
    except Exception:
        pass  # Tabela pode nao existir em bancos antigos

    # 2. Complementar com nfe_cruzamento (legacy) — apenas regras que NAO vieram do XC
    q_leg = "SELECT * FROM nfe_cruzamento WHERE file_id = ?"
    p_leg: list = [file_id]
    if rule_id:
        q_leg += " AND rule_id = ?"
        p_leg.append(rule_id)
    if severity:
        q_leg += " AND severity = ?"
        p_leg.append(severity)
    q_leg += " ORDER BY severity, rule_id, chave_nfe"

    try:
        cur2 = db.execute(q_leg, p_leg)
        cols2 = [d[0] for d in cur2.description] if cur2.description else []
        for r in cur2.fetchall():
            it = dict(r) if hasattr(r, "keys") else dict(zip(cols2, r))
            key = (it.get("rule_id", ""), it.get("chave_nfe", ""))
            if key in seen_keys:
                continue  # Ja veio do XC
            seen_keys.add(key)
            items.append(it)
    except Exception:
        pass

    # Enriquecer com numero_nfe
    nfe_numeros: dict[str, str] = {}
    try:
        nfe_rows = db.execute(
            "SELECT chave_nfe, numero_nfe FROM nfe_xmls WHERE file_id = ?",
            (file_id,),
        ).fetchall()
        for r in nfe_rows:
            nfe_numeros[r["chave_nfe"]] = str(r["numero_nfe"] or "")
    except Exception:
        pass

    for item in items:
        item["numero_nfe"] = nfe_numeros.get(item.get("chave_nfe", ""), "")

    return {
        "file_id": file_id,
        "total": len(items),
        "divergencias": items,
    }


@router.post("/cruzar-xc")
def executar_cruzamento_xc(
    file_id: int,
    db: AuditConnection = Depends(get_db),
) -> dict:
    """Executa Motor de Cruzamento XC (regras XC001-XC095)."""
    sped = db.execute("SELECT id, regime_tributario, cod_ver FROM sped_files WHERE id = ?", (file_id,)).fetchone()
    if not sped:
        raise HTTPException(status_code=404, detail="Arquivo SPED nao encontrado")

    xmls_count = db.execute(
        "SELECT COUNT(*) FROM nfe_xmls WHERE file_id = ? AND status = 'active'",
        (file_id,),
    ).fetchone()[0]
    if xmls_count == 0:
        raise HTTPException(status_code=400, detail="Nenhum XML vinculado a este SPED")

    regime = sped[1] or "" if len(sped) > 1 else ""
    cod_ver = str(sped[2] or "") if len(sped) > 2 else ""

    engine = CrossValidationEngine(db, file_id, regime=regime, cod_ver=cod_ver)
    findings = engine.run()
    engine.persist_findings()
    engine.persist_to_legacy_table()

    return engine.get_summary()


@router.get("/cruzamento-xc")
def get_cruzamento_xc(
    file_id: int,
    rule_id: str | None = None,
    severity: str | None = None,
    action_priority: str | None = None,
    review_status: str | None = None,
    hide_derived: bool = False,
    db: AuditConnection = Depends(get_db),
) -> dict:
    """Retorna findings XC com filtros avancados."""
    query = "SELECT * FROM cross_validation_findings WHERE file_id = ?"
    params: list = [file_id]

    if rule_id:
        query += " AND rule_id = ?"
        params.append(rule_id)
    if severity:
        query += " AND severity = ?"
        params.append(severity)
    if action_priority:
        query += " AND action_priority = ?"
        params.append(action_priority)
    if review_status:
        query += " AND review_status = ?"
        params.append(review_status)
    if hide_derived:
        query += " AND is_derived = 0"

    query += " ORDER BY action_priority, severity, rule_id"
    rows = db.execute(query, params).fetchall()

    items = []
    for r in rows:
        if hasattr(r, "keys"):
            items.append(dict(r))
        else:
            cols = [d[0] for d in db.execute("SELECT * FROM cross_validation_findings LIMIT 0").description]
            items.append(dict(zip(cols, r)))

    # Resumo
    by_severity = {}
    by_priority = {}
    for item in items:
        sev = item.get("severity", "")
        pri = item.get("action_priority", "")
        by_severity[sev] = by_severity.get(sev, 0) + 1
        by_priority[pri] = by_priority.get(pri, 0) + 1

    return {
        "file_id": file_id,
        "total": len(items),
        "by_severity": by_severity,
        "by_priority": by_priority,
        "findings": items,
    }


@router.delete("/{xml_id}")
def delete_xml(
    file_id: int,
    xml_id: int,
    db: AuditConnection = Depends(get_db),
) -> dict:
    """Remove um XML e seus itens/cruzamentos."""
    db.execute("DELETE FROM nfe_itens WHERE nfe_id = ?", (xml_id,))
    db.execute("DELETE FROM nfe_cruzamento WHERE nfe_id = ?", (xml_id,))
    db.execute("DELETE FROM nfe_xmls WHERE id = ? AND file_id = ?", (xml_id, file_id))
    db.commit()
    return {"deleted": True, "xml_id": xml_id}
