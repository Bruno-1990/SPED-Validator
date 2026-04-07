"""Service orquestrador de validação completa."""

from __future__ import annotations

import sqlite3

from ..models import SpedRecord, ValidationError
from ..validator import load_field_definitions, validate_records
from .context_builder import build_context
from .rule_loader import RuleLoader

# Cache certeza/impacto por error_type do rules.yaml
_CERTEZA_IMPACTO_CACHE: dict[str, tuple[str, str]] | None = None


def _load_certeza_impacto() -> dict[str, tuple[str, str]]:
    """Carrega mapeamento error_type -> (certeza, impacto) do rules.yaml."""
    global _CERTEZA_IMPACTO_CACHE
    if _CERTEZA_IMPACTO_CACHE is not None:
        return _CERTEZA_IMPACTO_CACHE

    loader = RuleLoader()
    rules = loader.load_all_rules()
    mapping: dict[str, tuple[str, str]] = {}
    for rule in rules:
        rule_id = rule.get("id", "")
        certeza = rule.get("certeza", "objetivo")
        impacto = rule.get("impacto", "relevante")
        # Map by rule id (primary) and error_type (fallback)
        mapping[rule_id] = (certeza, impacto)
        error_type = rule.get("error_type", "")
        if error_type and error_type not in mapping:
            mapping[error_type] = (certeza, impacto)
    _CERTEZA_IMPACTO_CACHE = mapping
    return mapping
from ..validators.aliquota_validator import validate_aliquotas  # noqa: E402
from ..validators.audit_rules import validate_audit_rules  # noqa: E402
from ..validators.beneficio_audit_validator import validate_beneficio_audit  # noqa: E402
from ..validators.bloco_c_servicos_validator import validate_bloco_c_servicos  # noqa: E402
from ..validators.c190_validator import validate_c190  # noqa: E402
from ..validators.correction_hypothesis import validate_with_hypotheses  # noqa: E402
from ..validators.cross_block_validator import validate_cross_blocks  # noqa: E402
from ..validators.cst_hypothesis import validate_cst_hypotheses  # noqa: E402
from ..validators.cst_validator import validate_cst_and_exemptions  # noqa: E402
from ..validators.difal_validator import validate_difal  # noqa: E402
from ..validators.fiscal_semantics import validate_fiscal_semantics  # noqa: E402
from ..validators.intra_register_validator import validate_intra_register  # noqa: E402
from ..validators.pendentes_validator import validate_pendentes  # noqa: E402
from ..validators.retificador_validator import validate_retificador  # noqa: E402
from ..validators.st_validator import validate_st  # noqa: E402
from ..validators.tax_recalc import recalculate_taxes  # noqa: E402


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

    # Construir contexto de validação (regime, caches)
    context = build_context(file_id, db)

    # MOD-04: Carregar apenas regras vigentes para o período do arquivo
    if context.periodo_ini and context.periodo_fim:
        loader = RuleLoader()
        active_rules = loader.load_rules_for_period(
            context.periodo_ini, context.periodo_fim
        )
        context.active_rules = [r["id"] for r in active_rules]

    # Reconstruir registros do banco
    records = _load_records(db, file_id)
    all_errors: list[ValidationError] = []

    # 1. Campo-a-campo (se temos doc_db_path com definições)
    if doc_db_path:
        field_defs = load_field_definitions(doc_db_path)
        all_errors.extend(validate_records(records, field_defs))

    # 2+3. Intra-registro (inclui validação de formatos internamente)
    all_errors.extend(validate_intra_register(records, context=context))

    # 4. Cruzamento entre blocos
    all_errors.extend(validate_cross_blocks(records, context=context))

    # 5. Recálculo tributário
    all_errors.extend(recalculate_taxes(records, context=context))

    # 5b. ICMS-ST (ST_001-ST_004)
    all_errors.extend(validate_st(records, context=context))

    # 6. CST + isenções + Bloco H
    all_errors.extend(validate_cst_and_exemptions(records, context=context))

    # 7. Validação semântica fiscal (CST x alíquota zero, CST x CFOP)
    all_errors.extend(validate_fiscal_semantics(records, context=context))

    # 8. Regras de auditoria fiscal (cruzamentos avançados)
    all_errors.extend(validate_audit_rules(records, context=context))

    # 9. Validação de alíquotas
    all_errors.extend(validate_aliquotas(records, context=context))

    # 10. Consolidação C190
    all_errors.extend(validate_c190(records, context=context))

    # 11. Auditoria de benefícios fiscais
    all_errors.extend(validate_beneficio_audit(records, context=context))

    # 12. Regras pendentes
    all_errors.extend(validate_pendentes(records, context=context))

    # 14. DIFAL (Diferencial de Aliquota Interestadual)
    all_errors.extend(validate_difal(records, context=context))

    # 13. Hipoteses de correcao inteligente (aliquota e CST)
    all_errors.extend(validate_with_hypotheses(records, context=context))
    all_errors.extend(validate_cst_hypotheses(records, context=context))

    # 15. Retificadores (MOD-16)
    all_errors.extend(validate_retificador(records, db=db, file_id=file_id))

    # 16. Bloco C Servicos — C400/C490/C500/C590 (MOD-17)
    all_errors.extend(validate_bloco_c_servicos(records, context=context))

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


def _build_errors_where(
    file_id: int,
    error_type: str | None = None,
    severity: str | None = None,
    categoria: str | None = "fiscal",
    certeza: str | None = None,
    impacto: str | None = None,
) -> tuple[str, list]:
    """Constrói cláusula WHERE para filtros de erros."""
    where = "WHERE file_id = ?"
    params: list = [file_id]

    if categoria:
        where += " AND COALESCE(categoria, 'fiscal') = ?"
        params.append(categoria)
    if error_type:
        where += " AND error_type = ?"
        params.append(error_type)
    if severity:
        where += " AND severity = ?"
        params.append(severity)
    if certeza:
        where += " AND COALESCE(certeza, 'objetivo') = ?"
        params.append(certeza)
    if impacto:
        where += " AND COALESCE(impacto, 'relevante') = ?"
        params.append(impacto)

    return where, params


def get_errors_count(
    db: sqlite3.Connection,
    file_id: int,
    error_type: str | None = None,
    severity: str | None = None,
    categoria: str | None = "fiscal",
    certeza: str | None = None,
    impacto: str | None = None,
) -> int:
    """Conta total de erros com filtros opcionais."""
    where, params = _build_errors_where(
        file_id, error_type=error_type, severity=severity,
        categoria=categoria, certeza=certeza, impacto=impacto,
    )
    row = db.execute(f"SELECT COUNT(*) FROM validation_errors {where}", params).fetchone()  # noqa: S608  # nosec B608
    return row[0] if row else 0


def get_errors(
    db: sqlite3.Connection,
    file_id: int,
    error_type: str | None = None,
    severity: str | None = None,
    categoria: str | None = "fiscal",
    certeza: str | None = None,
    impacto: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Lista erros de validação com filtros opcionais."""
    where, params = _build_errors_where(
        file_id, error_type=error_type, severity=severity,
        categoria=categoria, certeza=certeza, impacto=impacto,
    )

    query = f"SELECT * FROM validation_errors {where} ORDER BY line_number LIMIT ? OFFSET ?"  # noqa: S608  # nosec B608
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
    """Reconstroi SpedRecords a partir do banco.

    Suporta tanto o formato novo (dict nomeado) quanto o legado (list).
    Se encontrar list, converte automaticamente para dict usando REGISTER_FIELDS.
    """
    import json

    from ..validators.helpers import fields_to_dict

    rows = db.execute(
        """SELECT line_number, register, fields_json, raw_line
           FROM sped_records WHERE file_id = ? ORDER BY line_number""",
        (file_id,),
    ).fetchall()

    records = []
    for row in rows:
        ln, reg, fj, raw = row[0], row[1], row[2], row[3]
        parsed = json.loads(fj)
        if isinstance(parsed, list):
            parsed = fields_to_dict(reg, parsed)
        records.append(SpedRecord(
            line_number=ln,
            register=reg,
            fields=parsed,
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
        "AJUSTE_SOMA_DIVERGENTE",
        "ST_APURACAO_INCONSISTENTE",
        "ESCRITURACAO_DIVERGE_DOCUMENTO",
        "TRILHA_BENEFICIO_INCOMPLETA",
        "ICMS_EFETIVO_SEM_TRILHA",
        "BENEFICIO_FORA_ESCOPO",
        "BENEFICIO_EXECUCAO_INCORRETA",
        "BASE_BENEFICIO_INFLADA",
        "AJUSTE_NUMERICO_SEM_VALIDADE_JURIDICA",
        "CODIGO_AJUSTE_INCOMPATIVEL",
        "TRILHA_BENEFICIO_AUSENTE",
        "BENEFICIO_SEM_GOVERNANCA",
        "C190_CONSOLIDACAO_INDEVIDA",
        # Pendentes — error
        "DESONERACAO_SEM_MOTIVO",
        # Hipotese de correcao
        "ALIQ_ICMS_AUSENTE",
        "CST_HIPOTESE",
        # Arredondamento de aliquota
        "CALCULO_ARREDONDAMENTO",
        # DIFAL — critical
        "DIFAL_FALTANTE_CONSUMO_FINAL",
        "DIFAL_ALIQ_INTERNA_INCORRETA",
        # ST — error
        "ST_CST60_DEBITO_INDEVIDO",
        # Retificadores — error
        "RET_001",
        # MOD-17 — Bloco C Servicos
        "CS_C490_SOMA_DIVERGENTE",
        "CS_C590_DIVERGE_C510",
        # Base de calculo — error
        "BASE_MENOR_SEM_JUSTIFICATIVA",
        "FRETE_CIF_FORA_BASE",
        # IPI — error
        "IPI_CST_MONETARIO_INCOMPATIVEL",
        # DEST — error
        "DEST_UF_IE_INCOMPATIVEL",
        "DEST_UF_CEP_INCOMPATIVEL",
        # CFOP — critical
        "CFOP_INTERESTADUAL_MESMA_UF",
        "CFOP_INTERNO_OUTRA_UF",
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
        # Auditoria benefícios — warning (analiticas/heuristicas, nao erro objetivo)
        "AJUSTE_SEM_LASTRO_DOCUMENTAL",
        "DEVOLUCAO_BENEFICIO_NAO_REVERTIDO",
        "SOBREPOSICAO_BENEFICIOS",
        "BENEFICIO_VALOR_DESPROPORCIONAL",
        "MISTURA_INSTITUTOS_TRIBUTARIOS",
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
        # Base de calculo — warning
        "BASE_SUPERIOR_RAZOAVEL",
        "FRETE_FOB_NA_BASE",
        "DESPESAS_ACESSORIAS_FORA_BASE",
        # IPI — warning
        "IPI_REFLEXO_BC_ICMS",
        # DEST — warning
        "DEST_IE_INCONSISTENTE",
        # CFOP — warning
        "CFOP_DIFAL_INCOMPATIVEL",
        # DIFAL — warning
        "DIFAL_VERIFICACAO_INCOMPLETA",
        "DIFAL_INDEVIDO_REVENDA",
        "DIFAL_UF_DESTINO_INCONSISTENTE",
        "DIFAL_BASE_INCONSISTENTE",
        "DIFAL_FCP_AUSENTE",
        "DIFAL_PERFIL_INCOMPATIVEL",
        # ST — warning (indicios/heuristicas)
        "ST_BC_MENOR_QUE_ITEM",
        "ST_MISTURA_DIFAL",
        # Retificadores — warning
        "RET_002",
        # Simples Nacional — warning (indicios, sem RBT12)
        "SN_CREDITO_ZERADO_OU_FORA_RANGE",
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
        # DIFAL — info
        "DIFAL_CONSUMO_FINAL_SEM_MARCADOR",
        # Pendentes — info
        "ANOMALIA_HISTORICA",
        # Simples Nacional — info (deteccao de anomalia, nao erro)
        "SN_CREDITO_INCONSISTENTE",
    }
    # MONOFASICO_ALIQ_INVALIDA e MONOFASICO_VALOR_INDEVIDO caem no default "error"
    if error_type in critical:
        return "critical"
    if error_type in warning:
        return "warning"
    if error_type in info:
        return "info"
    return "error"


def _calc_materialidade(err: ValidationError) -> float:
    """Calcula materialidade financeira (R$) de um erro de validação.

    Para erros matemáticos com value e expected_value numéricos,
    retorna abs(value - expected_value). Caso contrário retorna 0.
    """
    val = err.value
    exp = err.expected_value
    if not val or not exp:
        return 0.0
    try:
        # Normalizar separadores: aceitar "1.234,56" -> "1234.56"
        def _parse(s: str) -> float:
            s = s.strip().replace(" ", "")
            # Se tem vírgula como decimal (ex: "1234,56" ou "1.234,56")
            if "," in s:
                s = s.replace(".", "").replace(",", ".")
            return float(s)

        v = _parse(val)
        e = _parse(exp)
        return abs(v - e)
    except (ValueError, TypeError):
        return 0.0


def _persist_errors(db: sqlite3.Connection, file_id: int, errors: list[ValidationError]) -> None:
    """Persiste erros de validação no banco."""
    # Limpar correções e erros anteriores (corrections referencia validation_errors)
    db.execute("DELETE FROM corrections WHERE file_id = ?", (file_id,))
    db.execute("DELETE FROM validation_errors WHERE file_id = ?", (file_id,))

    # Cache line_number -> record_id
    line_to_record: dict[int, int] = {}
    rows = db.execute(
        "SELECT id, line_number FROM sped_records WHERE file_id = ?", (file_id,),
    ).fetchall()
    for r in rows:
        line_to_record[r[1]] = r[0]

    ci_map = _load_certeza_impacto()

    for err in errors:
        record_id = line_to_record.get(err.line_number) if err.line_number > 0 else None
        # Resolve certeza/impacto: prefer value from error itself, fallback to rules.yaml
        certeza = err.certeza
        impacto = err.impacto
        if certeza == "objetivo" and impacto == "relevante":
            # Defaults — try to enrich from rules.yaml
            ci = ci_map.get(err.error_type, ("objetivo", "relevante"))
            certeza, impacto = ci
        materialidade = _calc_materialidade(err)
        db.execute(
            """INSERT INTO validation_errors
               (file_id, record_id, line_number, register, field_no, field_name, value,
                error_type, severity, message, expected_value, categoria, certeza, impacto,
                materialidade)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                file_id, record_id, err.line_number, err.register, err.field_no,
                err.field_name, err.value, err.error_type,
                _severity_for(err.error_type), err.message,
                err.expected_value, err.categoria, certeza, impacto,
                materialidade,
            ),
        )
    db.commit()
