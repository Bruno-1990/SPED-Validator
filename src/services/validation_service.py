"""Service orquestrador de validação completa."""

from __future__ import annotations

import sqlite3

from ..models import SpedRecord, ValidationError
from ..validator import load_field_definitions, validate_records
from ..validators.aliquota_validator import validate_aliquotas
from ..validators.audit_rules import validate_audit_rules
from ..validators.beneficio_audit_validator import validate_beneficio_audit
from ..validators.c190_validator import validate_c190
from ..validators.cross_block_validator import validate_cross_blocks
from ..validators.cst_validator import validate_cst_and_exemptions
from ..validators.fiscal_semantics import validate_fiscal_semantics
from ..validators.intra_register_validator import validate_intra_register
from ..validators.pendentes_validator import validate_pendentes
from ..validators.tax_recalc import recalculate_taxes


def run_full_validation(
    db: sqlite3.Connection,
    file_id: int,
    doc_db_path: str | None = None,
) -> list[ValidationError]:
    """Executa todas as camadas de validação em um arquivo SPED.

    1. Validação campo-a-campo (tipo, tamanho, obrigatório, valores válidos)
    2. Validação de formatos (CNPJ, CPF, datas, CFOP, etc.)
    3. Validação intra-registro (regras C100, C170, C190, E110)
    4. Cruzamento entre blocos (0 vs C/D, C vs E, bloco 9)
    5. Recálculo tributário (ICMS, ICMS-ST, IPI, PIS/COFINS)
    6. Validação CST e isenções + Bloco H

    Retorna lista consolidada de erros e persiste no banco.
    """
    db.execute("UPDATE sped_files SET status = 'validating' WHERE id = ?", (file_id,))
    db.commit()

    # Reconstruir registros do banco
    records = _load_records(db, file_id)
    all_errors: list[ValidationError] = []

    # 1. Campo-a-campo (se temos doc_db_path com definições)
    if doc_db_path:
        field_defs = load_field_definitions(doc_db_path)
        all_errors.extend(validate_records(records, field_defs))

    # 2+3. Intra-registro (inclui validação de formatos internamente)
    all_errors.extend(validate_intra_register(records))

    # 4. Cruzamento entre blocos
    all_errors.extend(validate_cross_blocks(records))

    # 5. Recálculo tributário
    all_errors.extend(recalculate_taxes(records))

    # 6. CST + isenções + Bloco H
    all_errors.extend(validate_cst_and_exemptions(records))

    # 7. Validação semântica fiscal (CST x alíquota zero, CST x CFOP)
    all_errors.extend(validate_fiscal_semantics(records))

    # 8. Regras de auditoria fiscal (cruzamentos avançados)
    all_errors.extend(validate_audit_rules(records))

    # 9. Validação de alíquotas
    all_errors.extend(validate_aliquotas(records))

    # 10. Consolidação C190
    all_errors.extend(validate_c190(records))

    # 11. Auditoria de benefícios fiscais
    all_errors.extend(validate_beneficio_audit(records))

    # 12. Regras pendentes
    all_errors.extend(validate_pendentes(records))

    # Persistir erros
    _persist_errors(db, file_id, all_errors)

    # Atualizar status
    db.execute(
        "UPDATE sped_files SET status = 'validated', total_errors = ? WHERE id = ?",
        (len(all_errors), file_id),
    )
    db.commit()

    # Log
    db.execute(
        "INSERT INTO audit_log (file_id, action, details) VALUES (?, ?, ?)",
        (file_id, "validate", f"Validação completa: {len(all_errors)} erros encontrados."),
    )
    db.commit()

    return all_errors


def get_errors(
    db: sqlite3.Connection,
    file_id: int,
    error_type: str | None = None,
    severity: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Lista erros de validação com filtros opcionais."""
    query = "SELECT * FROM validation_errors WHERE file_id = ?"
    params: list = [file_id]

    if error_type:
        query += " AND error_type = ?"
        params.append(error_type)
    if severity:
        query += " AND severity = ?"
        params.append(severity)

    query += " ORDER BY line_number LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = db.execute(query, params).fetchall()
    return [dict(r) if hasattr(r, "keys") else {} for r in rows]


def get_error_summary(db: sqlite3.Connection, file_id: int) -> dict:
    """Retorna resumo dos erros por tipo e severidade."""
    by_type = db.execute(
        """SELECT error_type, COUNT(*) as count
           FROM validation_errors WHERE file_id = ?
           GROUP BY error_type ORDER BY count DESC""",
        (file_id,),
    ).fetchall()

    by_severity = db.execute(
        """SELECT severity, COUNT(*) as count
           FROM validation_errors WHERE file_id = ?
           GROUP BY severity""",
        (file_id,),
    ).fetchall()

    total = db.execute(
        "SELECT COUNT(*) FROM validation_errors WHERE file_id = ?",
        (file_id,),
    ).fetchone()

    return {
        "total": total[0] if total else 0,
        "by_type": {r[0]: r[1] for r in by_type},
        "by_severity": {r[0]: r[1] for r in by_severity},
    }


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _load_records(db: sqlite3.Connection, file_id: int) -> list[SpedRecord]:
    """Reconstrói SpedRecords a partir do banco."""
    import json
    rows = db.execute(
        """SELECT line_number, register, fields_json, raw_line
           FROM sped_records WHERE file_id = ? ORDER BY line_number""",
        (file_id,),
    ).fetchall()

    records = []
    for row in rows:
        ln, reg, fj, raw = row[0], row[1], row[2], row[3]
        records.append(SpedRecord(
            line_number=ln,
            register=reg,
            fields=json.loads(fj),
            raw_line=raw,
        ))
    return records


def _severity_for(error_type: str) -> str:
    """Determina severidade com base no tipo de erro."""
    critical = {
        "CALCULO_DIVERGENTE", "CRUZAMENTO_DIVERGENTE",
        "SOMA_DIVERGENTE", "CONTAGEM_DIVERGENTE",
        "CFOP_INTERESTADUAL_DESTINO_INTERNO",
        "PARAMETRIZACAO_SISTEMICA_INCORRETA",
        "BENEFICIO_CARGA_REDUZIDA_DOCUMENTO",
        # Fase 1 — alíquotas e C190
        "ALIQ_INTERESTADUAL_INVALIDA",
        "ALIQ_INTERNA_EM_INTERESTADUAL",
        "ALIQ_MEDIA_INDEVIDA",
        "C190_DIVERGE_C170",
        # Auditoria benefícios — critical
        "BENEFICIO_DEBITO_NAO_INTEGRAL",
        "AJUSTE_SEM_LASTRO_DOCUMENTAL",
        "AJUSTE_SOMA_DIVERGENTE",
        "DEVOLUCAO_BENEFICIO_NAO_REVERTIDO",
        "SOBREPOSICAO_BENEFICIOS",
        "BENEFICIO_VALOR_DESPROPORCIONAL",
        "ST_APURACAO_INCONSISTENTE",
        "ESCRITURACAO_DIVERGE_DOCUMENTO",
        "TRILHA_BENEFICIO_INCOMPLETA",
        "ICMS_EFETIVO_SEM_TRILHA",
        "BENEFICIO_FORA_ESCOPO",
        "MISTURA_INSTITUTOS_TRIBUTARIOS",
        "BENEFICIO_EXECUCAO_INCORRETA",
        "BASE_BENEFICIO_INFLADA",
        "AJUSTE_NUMERICO_SEM_VALIDADE_JURIDICA",
        "CODIGO_AJUSTE_INCOMPATIVEL",
        "TRILHA_BENEFICIO_AUSENTE",
        "BENEFICIO_SEM_GOVERNANCA",
        "C190_CONSOLIDACAO_INDEVIDA",
        # Pendentes — error
        "DESONERACAO_SEM_MOTIVO",
    }
    warning = {
        "DATE_OUT_OF_PERIOD", "DATE_ORDER", "MISSING_CONDITIONAL",
        "REF_INEXISTENTE",
        "CST_ALIQ_ZERO_FORTE", "CST_CFOP_INCOMPATIVEL",
        "MONOFASICO_NCM_INCOMPATIVEL", "MONOFASICO_CST_INCORRETO",
        "DIFERIMENTO_COM_DEBITO", "VOLUME_ISENTO_ATIPICO",
        "REMESSA_SEM_RETORNO", "CREDITO_USO_CONSUMO_INDEVIDO",
        "IPI_REFLEXO_INCORRETO",
        # Fase 1 — alíquotas, CST e C190
        "ALIQ_INTERESTADUAL_EM_INTERNA",
        "C190_COMBINACAO_INCOMPATIVEL",
        "CST_020_SEM_REDUCAO",
        # Auditoria benefícios — warning
        "SALDO_CREDOR_RECORRENTE",
        "AJUSTE_CODIGO_GENERICO",
        "DIVERGENCIA_DOCUMENTO_ESCRITURACAO",
        "CREDITO_ENTRADA_SEM_SAIDA",
        "INVENTARIO_INCONSISTENTE_TRIBUTARIO",
        "TOTALIZACAO_BENEFICIO_DIVERGENTE",
        "BENEFICIO_PERFIL_INCOMPATIVEL",
        "BENEFICIO_SEM_SEGREGACAO_DESTINATARIO",
        "SPED_CONTRIBUICOES_DIVERGENTE",
        # Pendentes — warning
        "BENEFICIO_NAO_VINCULADO",
        "DEVOLUCAO_INCONSISTENTE",
        "IPI_ALIQ_NCM_DIVERGENTE",
    }
    info = {
        "CST_ALIQ_ZERO_MODERADO", "CST_ALIQ_ZERO_INFO",
        "IPI_CST_ALIQ_ZERO", "PIS_CST_ALIQ_ZERO", "COFINS_CST_ALIQ_ZERO",
        "MONOFASICO_ENTRADA_CST04",
        "INVENTARIO_ITEM_PARADO", "REGISTROS_ESSENCIAIS_AUSENTES",
        # Auditoria benefícios — info
        "CHECKLIST_INCOMPLETO",
        "CLASSIFICACAO_TIPO_ERRO",
        "ACHADO_LIMITADO_AO_SPED",
        # Pendentes — info
        "ANOMALIA_HISTORICA",
    }
    # MONOFASICO_ALIQ_INVALIDA e MONOFASICO_VALOR_INDEVIDO caem no default "error"
    if error_type in critical:
        return "critical"
    if error_type in warning:
        return "warning"
    if error_type in info:
        return "info"
    return "error"


def _persist_errors(db: sqlite3.Connection, file_id: int, errors: list[ValidationError]) -> None:
    """Persiste erros de validação no banco."""
    # Limpar erros anteriores
    db.execute("DELETE FROM validation_errors WHERE file_id = ?", (file_id,))

    for err in errors:
        db.execute(
            """INSERT INTO validation_errors
               (file_id, line_number, register, field_no, field_name, value,
                error_type, severity, message, expected_value)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                file_id, err.line_number, err.register, err.field_no,
                err.field_name, err.value, err.error_type,
                _severity_for(err.error_type), err.message,
                err.expected_value,
            ),
        )
    db.commit()
