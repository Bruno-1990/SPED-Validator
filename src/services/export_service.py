"""Service de exportação: relatório de auditoria e arquivo SPED corrigido."""

from __future__ import annotations

import csv
import io
import json
import sqlite3


def export_report_structured(db: sqlite3.Connection, file_id: int) -> dict:
    """Gera relatório estruturado para renderização no frontend."""
    file_info = db.execute("SELECT * FROM sped_files WHERE id = ?", (file_id,)).fetchone()
    if not file_info:
        return {"error": "Arquivo não encontrado"}

    # Metadata
    metadata = {
        "filename": file_info[1],
        "cnpj": file_info[7] or None,
        "uf": file_info[8] or None,
        "period_start": file_info[3] or None,
        "period_end": file_info[4] or None,
        "company_name": file_info[5] or None,
    }

    total_records = file_info[9] or 0
    total_all_errors = file_info[10] or 0

    # Counts by severity
    sev_rows = db.execute(
        """SELECT severity, COUNT(*) FROM validation_errors
           WHERE file_id = ? AND status = 'open'
           GROUP BY severity""",
        (file_id,),
    ).fetchall()
    sev_counts = {r[0]: r[1] for r in sev_rows}

    total_errors = sev_counts.get("critical", 0) + sev_counts.get("error", 0)
    total_warnings = sev_counts.get("warning", 0) + sev_counts.get("info", 0)
    compliance_pct = round(
        ((total_records - total_all_errors) / total_records * 100) if total_records > 0 else 100.0,
        1,
    )

    # Sugestoes pendentes (erros com expected_value e botao Corrigir)
    pending_suggestions = db.execute(
        """SELECT COUNT(*) FROM validation_errors
           WHERE file_id = ? AND status = 'open' AND auto_correctable = 1
           AND expected_value IS NOT NULL""",
        (file_id,),
    ).fetchone()[0]

    # Correcoes ja aplicadas pelo usuario
    applied_corrections = db.execute(
        "SELECT COUNT(*) FROM corrections WHERE file_id = ?", (file_id,),
    ).fetchone()[0]

    summary = {
        "total_records": total_records,
        "total_errors": total_errors,
        "total_warnings": total_warnings,
        "compliance_pct": compliance_pct,
        "pending_suggestions": pending_suggestions,
        "applied_corrections": applied_corrections,
    }

    # Top findings
    findings_rows = db.execute(
        """SELECT error_type, severity, COUNT(*) as cnt,
                  MIN(friendly_message) as sample_msg
           FROM validation_errors
           WHERE file_id = ? AND status = 'open'
           GROUP BY error_type, severity
           ORDER BY cnt DESC LIMIT 10""",
        (file_id,),
    ).fetchall()

    top_findings = []
    for r in findings_rows:
        desc = r[3] or r[0]  # friendly_message or error_type
        # Truncar para uma linha
        if desc and len(desc) > 120:
            desc = desc[:117] + "..."
        top_findings.append({
            "error_type": r[0],
            "severity": r[1],
            "count": r[2],
            "description": desc,
        })

    # Corrections
    corr_rows = db.execute(
        """SELECT c.record_id, r.register, c.field_name, c.old_value, c.new_value,
                  c.applied_by, c.applied_at
           FROM corrections c
           LEFT JOIN sped_records r ON r.id = c.record_id
           WHERE c.file_id = ?
           ORDER BY c.applied_at""",
        (file_id,),
    ).fetchall()

    corrections = []
    for c in corr_rows:
        corrections.append({
            "register": c[1] or "-",
            "field_name": c[2] or "-",
            "old_value": c[3] or "",
            "new_value": c[4] or "",
            "applied_by": c[5] or "auto",
            "applied_at": c[6] or "",
        })

    # Conclusion
    parts = [f"Foram analisados {total_records:,} registros."]
    if total_errors > 0:
        parts.append(f"Identificados {total_errors} erros que necessitam correção.")
    if total_warnings > 0:
        parts.append(f"{total_warnings} alertas para revisão.")
    if pending_suggestions > 0:
        parts.append(f"{pending_suggestions} sugestões de correção aguardam aprovação.")
    if applied_corrections > 0:
        parts.append(f"{applied_corrections} correções aplicadas pelo analista.")
    if total_errors == 0 and total_warnings == 0:
        parts.append("Nenhuma irregularidade identificada.")
    parts.append(f"Conformidade geral: {compliance_pct}%.")

    conclusion = " ".join(parts)

    return {
        "metadata": metadata,
        "summary": summary,
        "top_findings": top_findings,
        "corrections": corrections,
        "conclusion": conclusion,
    }


def export_corrected_sped(db: sqlite3.Connection, file_id: int) -> str:
    """Gera arquivo SPED corrigido (pipe-delimited) a partir dos registros no banco."""
    rows = db.execute(
        """SELECT raw_line FROM sped_records
           WHERE file_id = ? ORDER BY line_number""",
        (file_id,),
    ).fetchall()
    return "\n".join(r[0] for r in rows) + "\n"


def export_report_markdown(db: sqlite3.Connection, file_id: int) -> str:
    """Gera relatório de auditoria em Markdown."""
    file_info = db.execute("SELECT * FROM sped_files WHERE id = ?", (file_id,)).fetchone()
    if not file_info:
        return "# Arquivo não encontrado\n"

    lines = []
    # Acessar por índice (funciona com tuple e sqlite3.Row)
    name = file_info[1]
    cnpj = file_info[7] or ""
    period_s = file_info[3] or ""
    period_e = file_info[4] or ""
    total_rec = file_info[9] or 0
    total_err = file_info[10] or 0

    lines.append("# Relatório de Auditoria SPED EFD\n")
    lines.append(f"**Arquivo:** {name}")
    if cnpj:
        lines.append(f"**CNPJ:** {cnpj}")
    if period_s and period_e:
        lines.append(f"**Período:** {period_s} a {period_e}")
    lines.append("")

    lines.append("## Resumo\n")
    lines.append(f"- Total de registros: {total_rec}")
    lines.append(f"- Total de erros: {total_err}")
    if total_rec and total_rec > 0:
        pct = ((total_rec - total_err) / total_rec) * 100
        lines.append(f"- Conformidade: {pct:.1f}%")
    lines.append("")

    # Erros por tipo
    by_type = db.execute(
        """SELECT error_type, severity, COUNT(*) as count
           FROM validation_errors WHERE file_id = ?
           GROUP BY error_type, severity ORDER BY count DESC""",
        (file_id,),
    ).fetchall()

    if by_type:
        lines.append("## Erros por Tipo\n")
        lines.append("| Tipo | Severidade | Quantidade |")
        lines.append("|------|-----------|------------|")
        for row in by_type:
            lines.append(f"| {row[0]} | {row[1]} | {row[2]} |")
        lines.append("")

    # Detalhamento dos erros (top 50)
    errors = db.execute(
        """SELECT line_number, register, field_name, error_type, severity, message
           FROM validation_errors WHERE file_id = ?
           ORDER BY severity DESC, line_number LIMIT 50""",
        (file_id,),
    ).fetchall()

    if errors:
        lines.append("## Detalhamento (top 50)\n")
        for err in errors:
            ln, reg, field, etype, sev, msg = err[0], err[1], err[2], err[3], err[4], err[5]
            lines.append(f"### Linha {ln} | {reg} | {field or '-'} [{sev}]\n")
            lines.append(f"- **Tipo:** {etype}")
            lines.append(f"- **Mensagem:** {msg}")
            lines.append("")

    # Correções aplicadas
    corrections = db.execute(
        """SELECT record_id, field_no, field_name, old_value, new_value, applied_at
           FROM corrections WHERE file_id = ? ORDER BY applied_at""",
        (file_id,),
    ).fetchall()

    if corrections:
        lines.append("## Correções Aplicadas\n")
        lines.append("| Registro | Campo | Valor Anterior | Valor Novo | Data |")
        lines.append("|----------|-------|---------------|------------|------|")
        for c in corrections:
            lines.append(f"| {c[0]} | {c[2]} | `{c[3]}` | `{c[4]}` | {c[5]} |")
        lines.append("")

    return "\n".join(lines)


def export_errors_csv(db: sqlite3.Connection, file_id: int) -> str:
    """Exporta erros de validação como CSV."""
    errors = db.execute(
        """SELECT line_number, register, field_no, field_name, value,
                  error_type, severity, message, status
           FROM validation_errors WHERE file_id = ?
           ORDER BY line_number""",
        (file_id,),
    ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "linha", "registro", "campo_no", "campo_nome", "valor",
        "tipo_erro", "severidade", "mensagem", "status",
    ])
    for row in errors:
        writer.writerow(list(row))

    return output.getvalue()


def export_errors_json(db: sqlite3.Connection, file_id: int) -> str:
    """Exporta erros de validação como JSON."""
    errors = db.execute(
        """SELECT line_number, register, field_no, field_name, value,
                  error_type, severity, message, status
           FROM validation_errors WHERE file_id = ?
           ORDER BY line_number""",
        (file_id,),
    ).fetchall()

    result = []
    for row in errors:
        result.append({
            "linha": row[0],
            "registro": row[1],
            "campo_no": row[2],
            "campo_nome": row[3],
            "valor": row[4],
            "tipo_erro": row[5],
            "severidade": row[6],
            "mensagem": row[7],
            "status": row[8],
        })

    return json.dumps(result, ensure_ascii=False, indent=2)
