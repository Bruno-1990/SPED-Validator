"""Endpoints de cruzamento NF-e XML x SPED EFD."""

from __future__ import annotations

import json
import queue
import sqlite3
import threading

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from starlette.responses import StreamingResponse

from api.deps import get_db
from src.services.xml_service import cruzar_xml_vs_sped, upload_nfe_xmls
from src.services.database import get_connection

router = APIRouter(prefix="/api/files/{file_id}/xml", tags=["xml"])


@router.post("/upload")
def upload_xmls(
    file_id: int,
    modo_periodo: str = "validar",
    files: list[UploadFile] = File(...),
    db: sqlite3.Connection = Depends(get_db),
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
    db: sqlite3.Connection = Depends(get_db),
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
    db: sqlite3.Connection = Depends(get_db),
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

    findings = cruzar_xml_vs_sped(db, file_id)

    return {
        "file_id": file_id,
        "xmls_analisados": xmls_count,
        "divergencias": len(findings),
        "por_severidade": {
            "critical": sum(1 for f in findings if f["severity"] == "critical"),
            "error": sum(1 for f in findings if f["severity"] == "error"),
            "warning": sum(1 for f in findings if f["severity"] == "warning"),
        },
    }


@router.get("/cruzar/stream")
async def cruzar_stream(file_id: int) -> StreamingResponse:
    """Executa cruzamento XML vs SPED com streaming SSE de progresso."""
    from pathlib import Path

    db_path = Path("db/audit.db")

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
        conn = get_connection(db_path)
        try:
            def on_progress(pct: int, msg: str):
                progress_queue.put(("progress", pct, msg))

            findings = cruzar_xml_vs_sped(conn, file_id, on_progress=on_progress)
            result = {
                "file_id": file_id,
                "xmls_analisados": xmls_count,
                "divergencias": len(findings),
                "por_severidade": {
                    "critical": sum(1 for f in findings if f["severity"] == "critical"),
                    "error": sum(1 for f in findings if f["severity"] == "error"),
                    "warning": sum(1 for f in findings if f["severity"] == "warning"),
                },
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
                item = progress_queue.get(timeout=60)
            except queue.Empty:
                yield "event: error\ndata: {\"error\": \"timeout\"}\n\n"
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
                yield f"event: error\ndata: {data}\n\n"
                break

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/cruzamento")
def get_cruzamento(
    file_id: int,
    rule_id: str | None = None,
    severity: str | None = None,
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Retorna resultado do cruzamento com filtros opcionais."""
    query = "SELECT * FROM nfe_cruzamento WHERE file_id = ?"
    params: list = [file_id]

    if rule_id:
        query += " AND rule_id = ?"
        params.append(rule_id)
    if severity:
        query += " AND severity = ?"
        params.append(severity)

    query += " ORDER BY severity, rule_id, chave_nfe"
    rows = db.execute(query, params).fetchall()

    # Mapear colunas
    cols = [d[0] for d in db.execute("SELECT * FROM nfe_cruzamento LIMIT 0").description]
    items = [dict(zip(cols, r)) for r in rows]

    # Enriquecer com numero_nfe de cada NF-e (para exibicao no frontend)
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


@router.delete("/{xml_id}")
def delete_xml(
    file_id: int,
    xml_id: int,
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Remove um XML e seus itens/cruzamentos."""
    db.execute("DELETE FROM nfe_itens WHERE nfe_id = ?", (xml_id,))
    db.execute("DELETE FROM nfe_cruzamento WHERE nfe_id = ?", (xml_id,))
    db.execute("DELETE FROM nfe_xmls WHERE id = ? AND file_id = ?", (xml_id, file_id))
    db.commit()
    return {"deleted": True, "xml_id": xml_id}
