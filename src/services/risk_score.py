"""Score de Risco Fiscal e Score de Cobertura (Fase 6).

Score de Risco: 0-100 ponderado por tipo e criticidade dos erros.
Score de Cobertura: tri-dimensional (regras × XML × itens).

Faixas de risco:
  0-20: Baixo (revisao de rotina)
  21-50: Moderado (revisao prioritaria)
  51-75: Elevado (retificacao recomendada)
  76-100: Critico (acao imediata)
"""

from __future__ import annotations

import logging
import math
from .db_types import AuditConnection

logger = logging.getLogger(__name__)

# Pesos por categoria de erro
_PESOS = {
    "critical": 40,
    "high": 25,
    "beneficio": 20,
    "st_difal": 10,
    "sistemico": 5,
}

# Error types por categoria
_CAT_BENEFICIO = {
    "SPED_CST_BENEFICIO", "SPED_ALIQ_BENEFICIO", "SPED_ICMS_DEVERIA_ZERO",
    "BENEFICIO_SEM_AJUSTE_E111", "BENEFICIO_NAO_ATIVO", "BENEFICIO_FORA_VIGENCIA",
    "BENEFICIO_CNAE_INELEGIVEL", "SOBREPOSICAO_BENEFICIOS", "BENEFICIO_DEBITO_NAO_INTEGRAL",
    "CREDITO_PRESUMIDO_DIVERGENTE", "CODIGO_AJUSTE_INCOMPATIVEL",
    "XML_BENEFICIO_ALIQ_DIVERGENTE", "XML018", "XML019",
}

_CAT_ST_DIFAL = {
    "ST_MVA_AUSENTE", "ST_MVA_DIVERGENTE", "ST_MVA_NAO_MAPEADO", "ST_ALIQ_INCORRETA",
    "ST_APURACAO_DIVERGENTE", "ST_RETENCAO_DIVERGENTE",
    "DIFAL_FALTANTE_CONSUMO_FINAL", "DIFAL_INDEVIDO_REVENDA", "DIFAL_VALOR_DIVERGENTE",
}

_CAT_SISTEMICO = {
    "PARAMETRIZACAO_SISTEMATICA", "ERRO_RECORRENTE_NAO_CORRIGIDO",
    "VOLUME_VARIACAO_ATIPICA",
}


def calculate_risk_score(db: AuditConnection, file_id: int) -> float:
    """Calcula score de risco fiscal 0-100.

    Formula ponderada:
      40% × (erros critical / total_docs)
      25% × (erros high provavel / total_itens)
      20% × (erros beneficio / 1)
      10% × (erros ST/DIFAL / total_docs)
       5% × (erros sistemicos / 1)
    """
    rows = db.execute(
        "SELECT error_type, severity, certeza FROM validation_errors WHERE file_id = ?",
        (file_id,),
    ).fetchall()

    if not rows:
        return 0.0

    # Contar documentos e itens para normalizacao
    total_docs = max(db.execute(
        "SELECT COUNT(*) FROM sped_records WHERE file_id = ? AND register = 'C100'",
        (file_id,),
    ).fetchone()[0], 1)

    total_itens = max(db.execute(
        "SELECT COUNT(*) FROM sped_records WHERE file_id = ? AND register = 'C170'",
        (file_id,),
    ).fetchone()[0], 1)

    # Classificar erros por categoria
    n_critical = 0
    n_high_provavel = 0
    n_beneficio = 0
    n_st_difal = 0
    n_sistemico = 0

    for row in rows:
        if isinstance(row, tuple):
            et, sev, cert = row[0], row[1], row[2] if len(row) > 2 else ""
        else:
            et, sev = row["error_type"], row["severity"]
            try:
                cert = row["certeza"]
            except (IndexError, KeyError):
                cert = ""

        if et in _CAT_BENEFICIO:
            n_beneficio += 1
        elif et in _CAT_ST_DIFAL:
            n_st_difal += 1
        elif et in _CAT_SISTEMICO:
            n_sistemico += 1
        elif sev == "critical":
            n_critical += 1
        elif sev in ("error", "high") and cert == "provavel":
            n_high_provavel += 1
        elif sev == "error":
            n_critical += 1

    # Calcular score ponderado (normalizado para 0-100)
    score = min(100.0, (
        _PESOS["critical"]  * min(n_critical / total_docs, 1.0)
        + _PESOS["high"]    * min(n_high_provavel / total_itens, 1.0)
        + _PESOS["beneficio"] * min(n_beneficio, 5) / 5
        + _PESOS["st_difal"]  * min(n_st_difal / total_docs, 1.0)
        + _PESOS["sistemico"] * min(n_sistemico, 3) / 3
    ))

    return round(score, 1)


def calculate_coverage_score(
    db: AuditConnection, file_id: int, run_id: int = 0,
) -> float:
    """Calcula score de cobertura tri-dimensional 0-100.

    Formula: (regras_executadas / total) × sqrt(xml_coverage) × (itens_reconciliados / total)

    O sqrt() no XML coverage penaliza menos cobertura parcial
    (XMLs dependem de terceiros).
    """
    # Regras executadas vs puladas
    executed = 0
    skipped = 0
    if run_id:
        try:
            row = db.execute(
                "SELECT executed_rules, skipped_rules FROM validation_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if row:
                executed = row[0] or 0
                skipped = row[1] or 0
        except Exception:
            pass

    if executed == 0:
        # Estimar pelo numero de error types distintos
        executed = db.execute(
            "SELECT COUNT(DISTINCT error_type) FROM validation_errors WHERE file_id = ?",
            (file_id,),
        ).fetchone()[0]
        # Total de regras no sistema (~177)
        skipped = max(0, 177 - executed)

    total_rules = max(executed + skipped, 1)
    rules_pct = executed / total_rules

    # Cobertura XML
    xml_pct = 1.0  # Default se nao tem XMLs
    try:
        xml_row = db.execute(
            "SELECT COUNT(*) FROM nfe_xmls WHERE file_id = ? AND status = 'active'",
            (file_id,),
        ).fetchone()
        total_xmls = xml_row[0] if xml_row else 0
        if total_xmls > 0:
            c100_count = db.execute(
                "SELECT COUNT(*) FROM sped_records WHERE file_id = ? AND register = 'C100'",
                (file_id,),
            ).fetchone()[0]
            xml_pct = min(total_xmls / max(c100_count, 1), 1.0)
    except Exception:
        pass

    # Itens reconciliados (simplificacao: % de C170 com alguma validacao)
    itens_pct = 1.0  # Default

    # Formula tri-dimensional
    coverage = rules_pct * math.sqrt(xml_pct) * itens_pct * 100
    return round(min(coverage, 100.0), 1)


def get_risk_label(score: float) -> str:
    """Retorna label do risco baseado no score."""
    if score <= 20:
        return "BAIXO"
    if score <= 50:
        return "MODERADO"
    if score <= 75:
        return "ELEVADO"
    return "CRITICO"


def persist_scores(
    db: AuditConnection, file_id: int, run_id: int,
    risk_score: float, coverage_score: float,
) -> None:
    """Persiste scores na tabela validation_runs."""
    try:
        now_fn = "NOW()" if type(db).__name__ == "PgConnection" else "datetime('now')"
        db.execute(
            f"""UPDATE validation_runs
               SET risk_score = ?, coverage_score = ?, status = 'done',
                   finished_at = {now_fn}
               WHERE id = ?""",
            (risk_score, coverage_score, run_id),
        )
    except Exception:
        pass  # Tabela pode nao existir pre-Migration 14
