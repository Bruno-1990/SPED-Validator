"""Service de exportação: relatório de auditoria e arquivo SPED corrigido."""

from __future__ import annotations

import csv
import io
import json
import sqlite3


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
