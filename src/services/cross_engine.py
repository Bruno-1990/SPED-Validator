"""Motor de Cruzamento NF-e XML x SPED EFD — CrossValidationEngine.

Pipeline de 10 etapas conforme motor_cruzamento_v_final.txt.
Regras XC001-XC095 com variantes.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from datetime import datetime

from .cross_engine_models import (
    COFINS_GRUPO_MAP,
    CST_FROM_XML_GROUP,
    GRUPOS_SEM_BC_ICMS,
    LEGACY_RULE_MAP,
    PIS_GRUPO_MAP,
    SUGGESTED_ACTIONS,
    XC_TO_LEGACY,
    ActionPriority,
    Confidence,
    CrossValidationFinding,
    DocumentScope,
    ItemMatchState,
    ItemNature,
    ItemPair,
    RuleOutcome,
    Severity,
    XmlItemParsed,
)
from .document_scope_builder import DocumentScopeBuilder, _to_float, _norm

# ──────────────────────────────────────────────────────────────────────
# Batch INSERT otimizado (PG: execute_values / SQLite: executemany)
# ──────────────────────────────────────────────────────────────────────

_BATCH_SIZE = 500


def _is_pg(db) -> bool:
    from .db_types import is_pg
    return is_pg(db)


def _batch_insert(db, sql_template: str, rows: list[tuple], batch_size: int = _BATCH_SIZE) -> None:
    """INSERT em lote otimizado.

    Para PostgreSQL usa execute_values (1 round-trip por batch).
    Para SQLite usa executemany nativo (ja otimizado).
    """
    if not rows:
        return

    if _is_pg(db):
        # Extrair colunas e construir template para execute_values
        try:
            from psycopg2.extras import execute_values as _pg_exec_values
            # Converter sql_template com ? para %s
            from .database_pg import _convert_placeholders
            converted = _convert_placeholders(sql_template)

            # Extrair parte antes de VALUES e gerar template
            idx = converted.upper().find("VALUES")
            insert_part = converted[:idx].strip()
            n_cols = len(rows[0])
            tpl = "(" + ",".join(["%s"] * n_cols) + ")"

            raw_conn = db._conn  # acesso direto ao psycopg2 connection
            cur = raw_conn.cursor()
            try:
                for i in range(0, len(rows), batch_size):
                    chunk = rows[i : i + batch_size]
                    _pg_exec_values(cur, f"{insert_part} VALUES %s", chunk, template=tpl)
            finally:
                cur.close()
            return
        except (ImportError, AttributeError):
            pass  # fallback para executemany

    # SQLite ou fallback
    for i in range(0, len(rows), batch_size):
        chunk = rows[i : i + batch_size]
        db.executemany(sql_template, chunk)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _make_finding(
    rule_id: str,
    error_type: str,
    severity: str = "error",
    confidence: str = "alta",
    description: str = "",
    sped_register: str = "",
    sped_field: str = "",
    value_sped: str = "",
    xml_field: str = "",
    value_xml: str = "",
    suggested_action: str = "investigar",
    tipo_irregularidade: str = "",
    root_cause_group: str = "",
    regime_context: str = "",
    benefit_context: str = "",
    rule_outcome: RuleOutcome = RuleOutcome.EXECUTED_ERROR,
    evidence: dict | None = None,
) -> CrossValidationFinding:
    return CrossValidationFinding(
        rule_id=rule_id,
        legacy_rule_id=XC_TO_LEGACY.get(rule_id, ""),
        error_type=error_type,
        rule_outcome=rule_outcome,
        tipo_irregularidade=tipo_irregularidade,
        severity=severity,
        confidence=confidence,
        sped_register=sped_register,
        sped_field=sped_field,
        value_sped=str(value_sped),
        xml_field=xml_field,
        value_xml=str(value_xml),
        description=description,
        evidence=json.dumps(evidence) if evidence else "",
        suggested_action=suggested_action,
        root_cause_group=root_cause_group,
        regime_context=regime_context,
        benefit_context=benefit_context,
    )


# ──────────────────────────────────────────────────────────────────────
# CAMADA A — Estrutural (XC001-XC007)
# ──────────────────────────────────────────────────────────────────────

def run_layer_a(scope: DocumentScope) -> list[CrossValidationFinding]:
    """Regras estruturais: existencia de C100 e XML no escopo."""
    findings = []

    # XC001 — XML presente sem C100 correspondente
    if scope.match_status == "sem_c100":
        findings.append(_make_finding(
            "XC001", "XML_SEM_C100_CORRESPONDENTE",
            severity="critico", confidence="alta",
            description=(
                f"NF-e {scope.chave_nfe[-8:]}... presente no XML mas "
                f"nao encontrada no SPED (sem registro C100 com CHV_NFE correspondente)."
            ),
            xml_field="chNFe", value_xml=scope.chave_nfe,
            suggested_action="corrigir_no_sped",
        ))

    # XC002 — C100 com CHV_NFE sem XML correspondente
    if scope.match_status == "sem_xml" and scope.xml_eligible:
        findings.append(_make_finding(
            "XC002", "C100_SEM_XML_CORRESPONDENTE",
            severity="error", confidence="alta",
            description=(
                f"C100 linha {scope.c100_line_number}: CHV_NFE {scope.chave_nfe[-8:]}... "
                f"sem XML correspondente enviado."
            ),
            sped_register="C100", sped_field="CHV_NFE",
            value_sped=scope.chave_nfe,
            suggested_action="investigar",
        ))

    # XC003-XC006 executados na Camada D (totais), pois dependem do match

    return findings


# ──────────────────────────────────────────────────────────────────────
# CAMADA D — Identidade e Status (XC008-XC013)
# ──────────────────────────────────────────────────────────────────────

def run_layer_d_identity(scope: DocumentScope) -> list[CrossValidationFinding]:
    """Regras de identidade: cancelamento, denegacao, CNPJ, UF."""
    findings = []
    if not scope.has_xml or scope.match_status in ("sem_c100", "sem_xml", "NAO_APLICAVEL"):
        return findings

    xml = scope.xml_data
    cstat = str(xml.get("prot_cstat", ""))

    # XC008 — Nota cancelada escriturada
    if cstat in ("101", "135"):
        cod_sit = scope.cod_sit
        # C100.COD_SIT deveria ser 02 ou 04 para cancelada
        if cod_sit not in ("02", "04"):
            findings.append(_make_finding(
                "XC008", "XML_NOTA_CANCELADA_ESCRITURADA",
                severity="critico", confidence="alta",
                description=(
                    f"NF-e {scope.chave_nfe[-8:]}... foi CANCELADA na SEFAZ "
                    f"(cStat={cstat}) mas está escriturada no SPED com COD_SIT={cod_sit}."
                ),
                sped_register="C100", sped_field="COD_SIT",
                value_sped=cod_sit, xml_field="cStat", value_xml=cstat,
                suggested_action="corrigir_no_sped",
                tipo_irregularidade="CANCELAMENTO",
                root_cause_group=f"XC008|C100|COD_SIT",
            ))

    # XC008b — Nota denegada escriturada
    if cstat in ("110", "301", "302"):
        findings.append(_make_finding(
            "XC008b", "NOTA_DENEGADA_ESCRITURADA",
            severity="critico", confidence="alta",
            description=(
                f"NF-e {scope.chave_nfe[-8:]}... está DENEGADA pela SEFAZ "
                f"(cStat={cstat}) e não deveria existir no SPED. "
                f"Nota denegada nunca foi autorizada."
            ),
            sped_register="C100", sped_field="COD_SIT",
            value_sped=scope.cod_sit, xml_field="cStat", value_xml=cstat,
            suggested_action="revisar_xml_emissor",
            tipo_irregularidade="DENEGACAO",
            root_cause_group=f"XC008b|C100|COD_SIT",
        ))

    # XC012 — C100_CNPJ_DIVERGENTE (legacy XML016)
    cnpj_xml = _norm(xml.get("cnpj_emitente", ""))
    # Para IND_EMIT=0, comparar cnpj_emitente; para IND_EMIT=1, cnpj_destinatario
    if scope.ind_emit == "1":
        cnpj_xml = _norm(xml.get("cnpj_destinatario", "")) or cnpj_xml

    cod_part = scope.get_c100_field("COD_PART")
    # Nao temos CNPJ direto no C100, precisaria do 0150.
    # Comparacao simplificada se cnpj disponivel no xml_data
    cnpj_sped = _norm(xml.get("_cnpj_participante_sped", ""))
    if cnpj_xml and cnpj_sped and cnpj_xml != cnpj_sped:
        findings.append(_make_finding(
            "XC012", "C100_CNPJ_DIVERGENTE",
            severity="error", confidence="alta",
            description=(
                f"CNPJ divergente: XML={cnpj_xml[:8]}... vs "
                f"SPED 0150={cnpj_sped[:8]}..."
            ),
            sped_register="C100", sped_field="COD_PART",
            value_sped=cnpj_sped, xml_field="emit/CNPJ", value_xml=cnpj_xml,
            suggested_action="revisar_cadastro",
        ))

    # XC013 — C100_UF_DIVERGENTE (legacy XML017)
    uf_xml = (xml.get("uf_emitente", "") or "").strip().upper()
    uf_sped = (xml.get("_uf_participante_sped", "") or "").strip().upper()
    if uf_xml and uf_sped and uf_xml != uf_sped:
        findings.append(_make_finding(
            "XC013", "C100_UF_DIVERGENTE",
            severity="warning", confidence="alta",
            description=f"UF divergente: XML={uf_xml} vs SPED 0150={uf_sped}.",
            sped_register="C100", sped_field="COD_PART",
            value_sped=uf_sped, xml_field="emit/enderEmit/UF", value_xml=uf_xml,
            suggested_action="revisar_cadastro",
        ))

    return findings


# ──────────────────────────────────────────────────────────────────────
# CAMADA D — Totais (XC014-XC017) — legacy XML012-XML015
# ──────────────────────────────────────────────────────────────────────

def run_layer_d_totals(scope: DocumentScope) -> list[CrossValidationFinding]:
    """Regras de totais: VL_DOC, VL_MERC, VL_ICMS, VL_IPI."""
    findings = []
    if not scope.has_xml or scope.match_status not in ("matched", "cancelada"):
        return findings

    # Supressao: se is_complementar=1, nao executar (spec 3.3)
    if scope.is_complementar == 1:
        return findings

    xml_tot = scope.xml_totais
    tol = 0.02  # tolerancia padrao

    # Confidence rebaixada se indicio de complementar (1 sinal apenas)
    # cod_sit=06 sem C113 ou C113 sem cod_sit=06
    confidence = "alta"
    note = ""
    if scope.cod_sit == "06" or scope.is_complementar == 0:
        # Checa se ha 1 sinal
        if scope.cod_sit == "06":
            confidence = "media"
            note = " (possível NF complementar — 1 sinal apenas, confidence rebaixada)"

    # XC003 / XC014 — VL_DOC (total da nota) — legacy XML003/XML012
    vl_doc_xml = xml_tot.get("vNF", 0.0)
    vl_doc_sped = scope.vl_doc
    diff_doc = abs(vl_doc_sped - vl_doc_xml)
    if diff_doc > tol and (vl_doc_xml > 0 or vl_doc_sped > 0):
        findings.append(_make_finding(
            "XC003", "VL_DOC_DIVERGENTE",
            severity="critico", confidence=confidence,
            description=(
                f"VL_DOC divergente: SPED={vl_doc_sped:.2f} vs "
                f"XML(vNF)={vl_doc_xml:.2f} (diff={diff_doc:.2f}){note}"
            ),
            sped_register="C100", sped_field="VL_DOC",
            value_sped=f"{vl_doc_sped:.2f}",
            xml_field="total/ICMSTot/vNF",
            value_xml=f"{vl_doc_xml:.2f}",
            suggested_action="corrigir_no_sped",
            evidence={"diferenca": round(diff_doc, 2)},
        ))

    # XC004 / XC016 — VL_ICMS — legacy XML004/XML014
    vl_icms_xml = xml_tot.get("vICMS", 0.0)
    vl_icms_sped = scope.vl_icms
    diff_icms = abs(vl_icms_sped - vl_icms_xml)
    if diff_icms > tol and (vl_icms_xml > 0 or vl_icms_sped > 0):
        findings.append(_make_finding(
            "XC004", "VL_ICMS_DIVERGENTE",
            severity="critico", confidence=confidence,
            description=(
                f"VL_ICMS divergente: SPED={vl_icms_sped:.2f} vs "
                f"XML(vICMS)={vl_icms_xml:.2f} (diff={diff_icms:.2f}){note}"
            ),
            sped_register="C100", sped_field="VL_ICMS",
            value_sped=f"{vl_icms_sped:.2f}",
            xml_field="total/ICMSTot/vICMS",
            value_xml=f"{vl_icms_xml:.2f}",
            suggested_action="corrigir_no_sped",
            evidence={"diferenca": round(diff_icms, 2)},
        ))

    # XC005 — VL_ICMS_ST — legacy XML005
    vl_st_xml = xml_tot.get("vST", 0.0)
    vl_st_sped = scope.vl_icms_st
    diff_st = abs(vl_st_sped - vl_st_xml)
    if diff_st > tol and (vl_st_xml > 0 or vl_st_sped > 0):
        findings.append(_make_finding(
            "XC005", "VL_ICMS_ST_DIVERGENTE",
            severity="error", confidence=confidence,
            description=(
                f"VL_ICMS_ST divergente: SPED={vl_st_sped:.2f} vs "
                f"XML(vST)={vl_st_xml:.2f} (diff={diff_st:.2f}){note}"
            ),
            sped_register="C100", sped_field="VL_ICMS_ST",
            value_sped=f"{vl_st_sped:.2f}",
            xml_field="total/ICMSTot/vST",
            value_xml=f"{vl_st_xml:.2f}",
            suggested_action="corrigir_no_sped",
        ))

    # XC006 / XC017 — VL_IPI — legacy XML006/XML015
    vl_ipi_xml = xml_tot.get("vIPI", 0.0)
    vl_ipi_sped = scope.vl_ipi
    diff_ipi = abs(vl_ipi_sped - vl_ipi_xml)
    if diff_ipi > tol and (vl_ipi_xml > 0 or vl_ipi_sped > 0):
        findings.append(_make_finding(
            "XC006", "VL_IPI_DIVERGENTE",
            severity="error", confidence=confidence,
            description=(
                f"VL_IPI divergente: SPED={vl_ipi_sped:.2f} vs "
                f"XML(vIPI)={vl_ipi_xml:.2f} (diff={diff_ipi:.2f}){note}"
            ),
            sped_register="C100", sped_field="VL_IPI",
            value_sped=f"{vl_ipi_sped:.2f}",
            xml_field="total/ICMSTot/vIPI",
            value_xml=f"{vl_ipi_xml:.2f}",
            suggested_action="corrigir_no_sped",
        ))

    # XC015 — VL_MERC (mercadoria) — legacy XML013
    vl_merc_xml = xml_tot.get("vProd", 0.0)
    vl_merc_sped = scope.vl_merc
    diff_merc = abs(vl_merc_sped - vl_merc_xml)
    if diff_merc > tol and (vl_merc_xml > 0 or vl_merc_sped > 0):
        findings.append(_make_finding(
            "XC015", "C100_MERC_DIVERGENTE",
            severity="error", confidence=confidence,
            description=(
                f"VL_MERC divergente: SPED={vl_merc_sped:.2f} vs "
                f"XML(vProd)={vl_merc_xml:.2f} (diff={diff_merc:.2f}){note}"
            ),
            sped_register="C100", sped_field="VL_MERC",
            value_sped=f"{vl_merc_sped:.2f}",
            xml_field="total/ICMSTot/vProd",
            value_xml=f"{vl_merc_xml:.2f}",
            suggested_action="corrigir_no_sped",
        ))

    # XC023d — VL_FRT (frete documento)
    vl_frt_xml = xml_tot.get("vFrete", 0.0)
    vl_frt_sped = scope.vl_frt
    diff_frt = abs(vl_frt_sped - vl_frt_xml)
    if diff_frt > tol and (vl_frt_xml > 0 or vl_frt_sped > 0):
        findings.append(_make_finding(
            "XC023d", "FRETE_DOCUMENTO_DIVERGENTE",
            severity="warning", confidence="alta",
            description=(
                f"VL_FRT divergente: SPED={vl_frt_sped:.2f} vs "
                f"XML(vFrete)={vl_frt_xml:.2f}"
            ),
            sped_register="C100", sped_field="VL_FRT",
            value_sped=f"{vl_frt_sped:.2f}",
            xml_field="total/ICMSTot/vFrete",
            value_xml=f"{vl_frt_xml:.2f}",
            suggested_action="corrigir_no_sped",
        ))

    # XC023e — VL_SEG (seguro documento)
    vl_seg_xml = xml_tot.get("vSeg", 0.0)
    vl_seg_sped = scope.vl_seg
    diff_seg = abs(vl_seg_sped - vl_seg_xml)
    if diff_seg > tol and (vl_seg_xml > 0 or vl_seg_sped > 0):
        findings.append(_make_finding(
            "XC023e", "SEGURO_DOCUMENTO_DIVERGENTE",
            severity="warning", confidence="alta",
            description=(
                f"VL_SEG divergente: SPED={vl_seg_sped:.2f} vs "
                f"XML(vSeg)={vl_seg_xml:.2f}"
            ),
            sped_register="C100", sped_field="VL_SEG",
            value_sped=f"{vl_seg_sped:.2f}",
            xml_field="total/ICMSTot/vSeg",
            value_xml=f"{vl_seg_xml:.2f}",
            suggested_action="corrigir_no_sped",
        ))

    # XC023f — VL_OUT_DA (outras despesas documento)
    vl_out_xml = xml_tot.get("vOutro", 0.0)
    vl_out_sped = scope.vl_out_da
    diff_out = abs(vl_out_sped - vl_out_xml)
    if diff_out > tol and (vl_out_xml > 0 or vl_out_sped > 0):
        findings.append(_make_finding(
            "XC023f", "OUTRAS_DESPESAS_DOCUMENTO_DIVERGENTE",
            severity="warning", confidence="alta",
            description=(
                f"VL_OUT_DA divergente: SPED={vl_out_sped:.2f} vs "
                f"XML(vOutro)={vl_out_xml:.2f}"
            ),
            sped_register="C100", sped_field="VL_OUT_DA",
            value_sped=f"{vl_out_sped:.2f}",
            xml_field="total/ICMSTot/vOutro",
            value_xml=f"{vl_out_xml:.2f}",
            suggested_action="corrigir_no_sped",
        ))

    return findings


# ──────────────────────────────────────────────────────────────────────
# CAMADA E — Itens (XC018-XC030)
# ──────────────────────────────────────────────────────────────────────

def _run_item_rules(scope: DocumentScope, pair: ItemPair) -> list[CrossValidationFinding]:
    """Executa regras de item para um par (C170, XML item)."""
    findings = []
    c170 = pair.c170
    xi = pair.xml_item
    if c170 is None or xi is None:
        return findings

    tol = 0.02

    # XC019b — Pareamento ambiguo (bloqueia demais regras)
    if pair.match_state == ItemMatchState.AMBIGUO:
        findings.append(_make_finding(
            "XC019b", "ITEM_PAREAMENTO_AMBIGUO",
            severity="warning", confidence="media",
            description=(
                f"Item C170 #{c170.num_item} tem pareamento ambíguo com "
                f"item XML #{xi.num_item} (score={pair.match_score:.0%}). "
                f"Regras de item subsequentes não executadas."
            ),
            sped_register="C170", sped_field="NUM_ITEM",
            value_sped=str(c170.num_item),
            xml_field="det/@nItem", value_xml=str(xi.num_item),
            suggested_action="investigar",
            rule_outcome=RuleOutcome.AMBIGUOUS_MATCH,
        ))
        return findings  # Bloqueia regras subsequentes

    # XC020 — CST_DIVERGENTE (com logica IND_EMIT)
    findings.extend(_check_xc020(scope, c170, xi))

    # XC021 — CFOP_DIVERGENTE
    if c170.cfop and xi.cfop and c170.cfop[:4] != xi.cfop[:4]:
        findings.append(_make_finding(
            "XC021", "CFOP_DIVERGENTE",
            severity="warning", confidence="alta",
            description=(
                f"CFOP divergente no item #{c170.num_item}: "
                f"SPED={c170.cfop} vs XML={xi.cfop}"
            ),
            sped_register="C170", sped_field="CFOP",
            value_sped=c170.cfop, xml_field="det/prod/CFOP", value_xml=xi.cfop,
            suggested_action="revisar_parametrizacao_erp",
        ))

    # XC022 — NCM_DIVERGENTE
    ncm_s = _norm(c170.ncm)[:8]
    ncm_x = _norm(xi.ncm)[:8]
    if ncm_s and ncm_x and ncm_s != ncm_x:
        findings.append(_make_finding(
            "XC022", "NCM_DIVERGENTE",
            severity="warning", confidence="alta",
            description=(
                f"NCM divergente no item #{c170.num_item}: "
                f"SPED={ncm_s} vs XML={ncm_x}"
            ),
            sped_register="C170", sped_field="NCM",
            value_sped=ncm_s, xml_field="det/prod/NCM", value_xml=ncm_x,
            suggested_action="revisar_parametrizacao_erp",
        ))

    # XC023 — VL_ITEM_DIVERGENTE
    diff_item = abs(c170.vl_item - xi.vl_prod)
    if diff_item > tol and (xi.vl_prod > 0 or c170.vl_item > 0):
        findings.append(_make_finding(
            "XC023", "VL_ITEM_DIVERGENTE",
            severity="error", confidence="alta",
            description=(
                f"VL_ITEM divergente no item #{c170.num_item}: "
                f"SPED={c170.vl_item:.2f} vs XML(vProd)={xi.vl_prod:.2f} "
                f"(diff={diff_item:.2f})"
            ),
            sped_register="C170", sped_field="VL_ITEM",
            value_sped=f"{c170.vl_item:.2f}",
            xml_field="det/prod/vProd",
            value_xml=f"{xi.vl_prod:.2f}",
            suggested_action="corrigir_no_sped",
        ))

    # XC023b — QUANTIDADE_ITEM_DIVERGENTE
    if xi.qtd is not None and c170.qtd > 0:
        diff_qtd = abs(c170.qtd - xi.qtd)
        if diff_qtd > 0.001:
            findings.append(_make_finding(
                "XC023b", "QUANTIDADE_ITEM_DIVERGENTE",
                severity="warning", confidence="alta",
                description=(
                    f"QTD divergente no item #{c170.num_item}: "
                    f"SPED={c170.qtd} vs XML(qCom)={xi.qtd}"
                ),
                sped_register="C170", sped_field="QTD",
                value_sped=str(c170.qtd),
                xml_field="det/prod/qCom",
                value_xml=str(xi.qtd),
                suggested_action="corrigir_no_sped",
            ))

    # XC023c — DESCONTO_ITEM_DIVERGENTE
    diff_desc = abs(c170.vl_desc - xi.vl_desc)
    if diff_desc > tol and (xi.vl_desc > 0 or c170.vl_desc > 0):
        findings.append(_make_finding(
            "XC023c", "DESCONTO_ITEM_DIVERGENTE",
            severity="warning", confidence="alta",
            description=(
                f"VL_DESC divergente no item #{c170.num_item}: "
                f"SPED={c170.vl_desc:.2f} vs XML(vDesc)={xi.vl_desc:.2f}"
            ),
            sped_register="C170", sped_field="VL_DESC",
            value_sped=f"{c170.vl_desc:.2f}",
            xml_field="det/prod/vDesc",
            value_xml=f"{xi.vl_desc:.2f}",
            suggested_action="corrigir_no_sped",
        ))

    # XC024/XC024b — BC ICMS (com pre-condicao de grupo)
    findings.extend(_check_xc024(c170, xi))

    # XC025/XC025b — Aliquota ICMS (com pre-condicao de grupo)
    findings.extend(_check_xc025(c170, xi))

    # XC026/XC026b — VL_ICMS item (com pre-condicao de grupo)
    findings.extend(_check_xc026(c170, xi))

    # XC028/XC028b/XC028c — IPI (com pre-condicao de grupo)
    f = _check_xc028(c170, xi)
    if f:
        findings.append(f)

    # XC029/XC029b — PIS
    f = _check_xc029(c170, xi)
    if f:
        findings.append(f)

    # XC030 — COFINS
    f = _check_xc030(c170, xi)
    if f:
        findings.append(f)

    return findings


def _check_xc020(scope: DocumentScope, c170, xi) -> list[CrossValidationFinding]:
    """XC020 — CST_DIVERGENTE com logica IND_EMIT (spec seção 3.4)."""
    findings = []

    if scope.ind_emit == "1":
        # Destinatario: CST/CSOSN escolhido pelo declarante com base no SEU regime
        cst = c170.cst_icms
        regime = scope.regime

        if regime in ("normal", "NORMAL", "LR", "LP"):
            try:
                if cst and int(cst) >= 100:
                    findings.append(_make_finding(
                        "XC031", "CSOSN_EM_REGIME_NORMAL",
                        severity="error", confidence="alta",
                        description=(
                            f"Empresa em regime normal escriturando entrada "
                            f"com CSOSN ({cst}) no item #{c170.num_item}."
                        ),
                        sped_register="C170", sped_field="CST_ICMS",
                        value_sped=cst,
                        suggested_action="corrigir_no_sped",
                        regime_context=regime,
                    ))
            except ValueError:
                pass

        if regime in ("simples_nacional", "SN", "MEI"):
            try:
                if cst and int(cst) < 100:
                    findings.append(_make_finding(
                        "XC032", "CST_NORMAL_EM_REGIME_SN",
                        severity="warning", confidence="media",
                        description=(
                            f"Empresa SN escriturando entrada com CST de "
                            f"regime normal ({cst}) no item #{c170.num_item}."
                        ),
                        sped_register="C170", sped_field="CST_ICMS",
                        value_sped=cst,
                        suggested_action="revisar_parametrizacao_erp",
                        regime_context=regime,
                    ))
            except ValueError:
                pass
    else:
        # Emitente (IND_EMIT=0): comparacao direta
        cst_sped = c170.cst_icms
        grupo = xi.grupo_icms
        cst_xml = CST_FROM_XML_GROUP.get(grupo, "")
        if cst_xml and cst_sped and cst_sped != cst_xml:
            findings.append(_make_finding(
                "XC020", "CST_DIVERGENTE",
                severity="error", confidence="alta",
                description=(
                    f"CST divergente no item #{c170.num_item}: "
                    f"SPED={cst_sped} vs XML({grupo})={cst_xml}"
                ),
                sped_register="C170", sped_field="CST_ICMS",
                value_sped=cst_sped,
                xml_field=f"det/imposto/ICMS/{grupo}",
                value_xml=cst_xml,
                suggested_action="corrigir_no_sped",
                root_cause_group=f"XC020|C170|CST_ICMS",
            ))

    return findings


def _check_xc024(c170, xi) -> list[CrossValidationFinding]:
    """XC024/XC024b — BC ICMS com pre-condicao GRUPOS_SEM_BC (spec seção 3.4)."""
    findings = []
    grupo = xi.grupo_icms
    tol = 0.02

    if grupo in GRUPOS_SEM_BC_ICMS:
        # Grupo sem BC: se SPED tem BC > 0, e indevida
        if c170.vl_bc_icms > 0:
            findings.append(_make_finding(
                "XC024b", "BC_ICMS_INDEVIDA_EM_CST_SEM_TRIBUTACAO",
                severity="error", confidence="alta",
                description=(
                    f"BC ICMS indevida no item #{c170.num_item}: "
                    f"VL_BC_ICMS={c170.vl_bc_icms:.2f} com grupo {grupo} "
                    f"(isento/ST — nao deveria ter BC)."
                ),
                sped_register="C170", sped_field="VL_BC_ICMS",
                value_sped=f"{c170.vl_bc_icms:.2f}",
                xml_field=f"det/imposto/ICMS/{grupo}",
                suggested_action="corrigir_no_sped",
            ))
    else:
        # Comparacao normal
        diff = abs(c170.vl_bc_icms - xi.vbc_icms)
        if diff > tol and (xi.vbc_icms > 0 or c170.vl_bc_icms > 0):
            findings.append(_make_finding(
                "XC024", "BC_ICMS_DIVERGENTE",
                severity="error", confidence="alta",
                description=(
                    f"VL_BC_ICMS divergente no item #{c170.num_item}: "
                    f"SPED={c170.vl_bc_icms:.2f} vs XML(vBC)={xi.vbc_icms:.2f}"
                ),
                sped_register="C170", sped_field="VL_BC_ICMS",
                value_sped=f"{c170.vl_bc_icms:.2f}",
                xml_field=f"det/imposto/ICMS/*/vBC",
                value_xml=f"{xi.vbc_icms:.2f}",
                suggested_action="corrigir_no_sped",
            ))

    return findings


def _check_xc025(c170, xi) -> list[CrossValidationFinding]:
    """XC025/XC025b — Aliquota ICMS."""
    findings = []
    grupo = xi.grupo_icms

    if grupo in GRUPOS_SEM_BC_ICMS:
        if c170.aliq_icms > 0:
            findings.append(_make_finding(
                "XC025b", "ALIQ_ICMS_INDEVIDA_EM_CST_SEM_TRIBUTACAO",
                severity="error", confidence="alta",
                description=(
                    f"ALIQ_ICMS indevida no item #{c170.num_item}: "
                    f"ALIQ_ICMS={c170.aliq_icms:.2f} com grupo {grupo}."
                ),
                sped_register="C170", sped_field="ALIQ_ICMS",
                value_sped=f"{c170.aliq_icms:.2f}",
                suggested_action="corrigir_no_sped",
            ))
    else:
        diff = abs(c170.aliq_icms - xi.aliq_icms)
        if diff > 0.01 and (xi.aliq_icms > 0 or c170.aliq_icms > 0):
            findings.append(_make_finding(
                "XC025", "ALIQ_ICMS_DIVERGENTE",
                severity="error", confidence="alta",
                description=(
                    f"ALIQ_ICMS divergente no item #{c170.num_item}: "
                    f"SPED={c170.aliq_icms:.2f} vs XML(pICMS)={xi.aliq_icms:.2f}"
                ),
                sped_register="C170", sped_field="ALIQ_ICMS",
                value_sped=f"{c170.aliq_icms:.2f}",
                xml_field=f"det/imposto/ICMS/*/pICMS",
                value_xml=f"{xi.aliq_icms:.2f}",
                suggested_action="corrigir_no_sped",
            ))

    return findings


def _check_xc026(c170, xi) -> list[CrossValidationFinding]:
    """XC026/XC026b — VL_ICMS item."""
    findings = []
    grupo = xi.grupo_icms
    tol = 0.02

    if grupo in GRUPOS_SEM_BC_ICMS:
        if c170.vl_icms > 0:
            findings.append(_make_finding(
                "XC026b", "ICMS_INDEVIDO_EM_CST_SEM_TRIBUTACAO",
                severity="error", confidence="alta",
                description=(
                    f"VL_ICMS indevido no item #{c170.num_item}: "
                    f"VL_ICMS={c170.vl_icms:.2f} com grupo {grupo}."
                ),
                sped_register="C170", sped_field="VL_ICMS",
                value_sped=f"{c170.vl_icms:.2f}",
                suggested_action="corrigir_no_sped",
            ))
    else:
        diff = abs(c170.vl_icms - xi.vl_icms)
        if diff > tol and (xi.vl_icms > 0 or c170.vl_icms > 0):
            findings.append(_make_finding(
                "XC026", "VL_ICMS_ITEM_DIVERGENTE",
                severity="error", confidence="alta",
                description=(
                    f"VL_ICMS divergente no item #{c170.num_item}: "
                    f"SPED={c170.vl_icms:.2f} vs XML(vICMS)={xi.vl_icms:.2f}"
                ),
                sped_register="C170", sped_field="VL_ICMS",
                value_sped=f"{c170.vl_icms:.2f}",
                xml_field=f"det/imposto/ICMS/*/vICMS",
                value_xml=f"{xi.vl_icms:.2f}",
                suggested_action="corrigir_no_sped",
            ))

    return findings


def _check_xc028(c170, xi) -> CrossValidationFinding | None:
    """XC028/XC028b/XC028c — IPI com pre-condicao de grupo (spec seção 3.4)."""
    grupo_ipi = xi.grupo_ipi

    if grupo_ipi is None:
        if c170.vl_ipi > 0:
            return _make_finding(
                "XC028b", "IPI_SEM_RESPALDO_XML",
                severity="warning",
                description=(
                    f"IPI escriturado no item #{c170.num_item} "
                    f"(VL_IPI={c170.vl_ipi:.2f}) sem grupo IPI no XML."
                ),
                sped_register="C170", sped_field="VL_IPI",
                value_sped=f"{c170.vl_ipi:.2f}",
                suggested_action="investigar",
            )
        return None

    if grupo_ipi == "IPINT":
        if c170.vl_ipi > 0:
            return _make_finding(
                "XC028c", "IPI_INDEVIDO_ITEM_ISENTO",
                severity="error",
                description=(
                    f"IPI indevido no item #{c170.num_item}: "
                    f"VL_IPI={c170.vl_ipi:.2f} com grupo IPINT (isento)."
                ),
                sped_register="C170", sped_field="VL_IPI",
                value_sped=f"{c170.vl_ipi:.2f}",
                suggested_action="corrigir_no_sped",
            )
        return None

    # IPITrib: comparacao normal
    diff = abs(c170.vl_ipi - xi.vl_ipi)
    if diff > 0.01 and (xi.vl_ipi > 0 or c170.vl_ipi > 0):
        return _make_finding(
            "XC028", "IPI_DIVERGENTE",
            severity="error", confidence="alta",
            description=(
                f"VL_IPI divergente no item #{c170.num_item}: "
                f"SPED={c170.vl_ipi:.2f} vs XML={xi.vl_ipi:.2f}"
            ),
            sped_register="C170", sped_field="VL_IPI",
            value_sped=f"{c170.vl_ipi:.2f}",
            xml_field="det/imposto/IPI/IPITrib/vIPI",
            value_xml=f"{xi.vl_ipi:.2f}",
            suggested_action="corrigir_no_sped",
        )

    return None


def _check_xc029(c170, xi) -> CrossValidationFinding | None:
    """XC029/XC029b — PIS com modalidade de tributacao (spec seção 3.4)."""
    grupo = xi.grupo_pis
    if not grupo:
        # Sem grupo PIS no XML — se SPED tem PIS > 0, informar
        if c170.vl_pis > 0.01:
            return _make_finding(
                "XC029b", "PIS_SEM_RESPALDO_XML",
                severity="warning",
                description=(
                    f"PIS escriturado no item #{c170.num_item} "
                    f"(VL_PIS={c170.vl_pis:.2f}) sem grupo PIS no XML."
                ),
                sped_register="C170", sped_field="VL_PIS",
                value_sped=f"{c170.vl_pis:.2f}",
                suggested_action="investigar",
            )
        return None

    config = PIS_GRUPO_MAP.get(grupo)
    if not config:
        return None

    if config["tipo"] == "nao_trib":
        if c170.vl_pis > 0.01:
            return _make_finding(
                "XC029b", "PIS_INDEVIDO_ITEM_NAO_TRIBUTADO",
                severity="warning",
                description=(
                    f"PIS indevido no item #{c170.num_item}: "
                    f"VL_PIS={c170.vl_pis:.2f} com grupo {grupo} (não tributado)."
                ),
                sped_register="C170", sped_field="VL_PIS",
                value_sped=f"{c170.vl_pis:.2f}",
                suggested_action="corrigir_no_sped",
            )
        return None

    # Para ad_valorem e outros: comparar VL_PIS
    vl_pis_xml = xi.vl_pis
    diff = abs(c170.vl_pis - vl_pis_xml)
    if diff > 0.02 and (vl_pis_xml > 0 or c170.vl_pis > 0):
        return _make_finding(
            "XC029", "VL_PIS_DIVERGENTE",
            severity="warning", confidence="alta",
            description=(
                f"VL_PIS divergente no item #{c170.num_item}: "
                f"SPED={c170.vl_pis:.2f} vs XML={vl_pis_xml:.2f}"
            ),
            sped_register="C170", sped_field="VL_PIS",
            value_sped=f"{c170.vl_pis:.2f}",
            xml_field=f"det/imposto/PIS/{grupo}/vPIS",
            value_xml=f"{vl_pis_xml:.2f}",
            suggested_action="corrigir_no_sped",
        )

    return None


def _check_xc030(c170, xi) -> CrossValidationFinding | None:
    """XC030 — COFINS divergente (mesma logica de XC029 para COFINS)."""
    grupo = xi.grupo_cofins
    if not grupo:
        if c170.vl_cofins > 0.01:
            return _make_finding(
                "XC030", "COFINS_SEM_RESPALDO_XML",
                severity="warning",
                description=(
                    f"COFINS escriturado no item #{c170.num_item} "
                    f"(VL_COFINS={c170.vl_cofins:.2f}) sem grupo COFINS no XML."
                ),
                sped_register="C170", sped_field="VL_COFINS",
                value_sped=f"{c170.vl_cofins:.2f}",
                suggested_action="investigar",
            )
        return None

    config = COFINS_GRUPO_MAP.get(grupo)
    if not config:
        return None

    if config["tipo"] == "nao_trib":
        if c170.vl_cofins > 0.01:
            return _make_finding(
                "XC030", "COFINS_INDEVIDO_ITEM_NAO_TRIBUTADO",
                severity="warning",
                description=(
                    f"COFINS indevido no item #{c170.num_item}: "
                    f"VL_COFINS={c170.vl_cofins:.2f} com grupo {grupo} (não tributado)."
                ),
                sped_register="C170", sped_field="VL_COFINS",
                value_sped=f"{c170.vl_cofins:.2f}",
                suggested_action="corrigir_no_sped",
            )
        return None

    vl_cofins_xml = xi.vl_cofins
    diff = abs(c170.vl_cofins - vl_cofins_xml)
    if diff > 0.02 and (vl_cofins_xml > 0 or c170.vl_cofins > 0):
        return _make_finding(
            "XC030", "VL_COFINS_DIVERGENTE",
            severity="warning", confidence="alta",
            description=(
                f"VL_COFINS divergente no item #{c170.num_item}: "
                f"SPED={c170.vl_cofins:.2f} vs XML={vl_cofins_xml:.2f}"
            ),
            sped_register="C170", sped_field="VL_COFINS",
            value_sped=f"{c170.vl_cofins:.2f}",
            xml_field=f"det/imposto/COFINS/{grupo}/vCOFINS",
            value_xml=f"{vl_cofins_xml:.2f}",
            suggested_action="corrigir_no_sped",
        )

    return None


def run_layer_e_items(scope: DocumentScope) -> list[CrossValidationFinding]:
    """Camada E: executa regras de item para todos os pares do escopo."""
    findings = []
    if not scope.has_xml or scope.match_status in ("sem_c100", "sem_xml", "NAO_APLICAVEL"):
        return findings

    # XC018 — Item XML sem C170 correspondente
    for xi in scope.xml_items_sem_match:
        findings.append(_make_finding(
            "XC018", "ITEM_XML_SEM_C170",
            severity="warning", confidence="alta",
            description=(
                f"Item XML #{xi.num_item} (cProd={xi.cod_produto}) "
                f"sem C170 correspondente no SPED."
            ),
            xml_field="det/@nItem", value_xml=str(xi.num_item),
            sped_register="C170",
            suggested_action="corrigir_no_sped",
        ))

    # XC019 — C170 sem item XML correspondente
    for c170 in scope.c170_sem_match:
        findings.append(_make_finding(
            "XC019", "C170_SEM_ITEM_XML",
            severity="warning", confidence="alta",
            description=(
                f"C170 #{c170.num_item} (COD_ITEM={c170.cod_item}) "
                f"sem item XML correspondente."
            ),
            sped_register="C170", sped_field="NUM_ITEM",
            value_sped=str(c170.num_item),
            suggested_action="investigar",
        ))

    # Regras por par
    for pair in scope.item_pairs:
        findings.extend(_run_item_rules(scope, pair))

    return findings


# ──────────────────────────────────────────────────────────────────────
# FAMILIAS AVANCADAS (XC06x, XC07x, XC08x, XC09x)
# ──────────────────────────────────────────────────────────────────────

def run_family_xc07x(scope: DocumentScope) -> list[CrossValidationFinding]:
    """Familia XC07x — Devolucao, Remessa, Complemento."""
    findings = []
    if not scope.has_xml:
        return findings

    cfop = scope.get_c100_field("CFOP") or ""
    cfop4 = cfop[:4]

    # CFOPs de devolucao
    cfops_devolucao = {
        "1201", "1202", "1410", "2201", "2202", "2410",
        "5201", "5202", "5410", "6201", "6202", "6410",
    }

    if cfop4 in cfops_devolucao:
        # XC070 — Devolucao sem nota origem referenciada
        # Verificamos se tem C113 (via is_complementar ou diretamente)
        # Simplificacao: se nao e complementar e CFOP de devolucao, gerar indicio
        if scope.is_complementar == 0:
            findings.append(_make_finding(
                "XC070", "DEVOLUCAO_SEM_NOTA_ORIGEM_REFERENCIADA",
                severity="warning", confidence="media",
                description=(
                    f"CFOP de devolução ({cfop4}) sem C113 referenciando "
                    f"a nota de origem."
                ),
                sped_register="C100", sped_field="CFOP",
                value_sped=cfop4,
                suggested_action="investigar",
            ))

    # XC074 — Complemento com delta incorreto
    if scope.is_complementar == 1:
        # Informativo: NF complementar identificada
        findings.append(_make_finding(
            "XC074", "NOTA_COMPLEMENTAR_IDENTIFICADA",
            severity="info", confidence="alta",
            description=(
                f"NF-e {scope.chave_nfe[-8:]}... identificada como complementar "
                f"(COD_SIT=06 + C113 presente)."
            ),
            sped_register="C100", sped_field="COD_SIT",
            value_sped="06",
            suggested_action="investigar",
            rule_outcome=RuleOutcome.EXECUTED_OK,
        ))

    return findings


def run_family_xc08x(scope: DocumentScope) -> list[CrossValidationFinding]:
    """Familia XC08x — Importacao e C120."""
    findings = []
    if not scope.has_xml:
        return findings

    # Pre-condicao: CFOP iniciando com "3" (importacao)
    cfop = scope.get_c100_field("CFOP") or ""
    if not cfop.startswith("3"):
        # Verificar nos itens
        has_import = any(
            p.c170 and p.c170.cfop and p.c170.cfop.startswith("3")
            for p in scope.item_pairs
        )
        if not has_import:
            return findings

    # XC080 — Importacao sem C120 (simplificado — checaria C120 no banco)
    # Registrado como indicio pois C120 precisa de lookup no banco
    findings.append(_make_finding(
        "XC080", "IMPORTACAO_SEM_C120",
        severity="warning", confidence="media",
        description=(
            f"NF-e com CFOP de importação — verificar presença de C120."
        ),
        sped_register="C100",
        suggested_action="investigar",
        rule_outcome=RuleOutcome.NOT_EXECUTED_MISSING_DATA,
    ))

    return findings


def run_family_xc09x(scope: DocumentScope, benefit_context: str = "") -> list[CrossValidationFinding]:
    """Familia XC09x — cBenef, C197, Desoneracao."""
    findings = []
    if not scope.has_xml:
        return findings

    # Verificar vICMSDeson no XML
    xml_tot = scope.xml_totais
    v_icms_deson = xml_tot.get("vICMSDeson", 0.0)

    if v_icms_deson > 0:
        # XC093 — vICMSDeson sem ajuste apuracao (indicio)
        findings.append(_make_finding(
            "XC093", "VICMSDESON_SEM_AJUSTE_APURACAO",
            severity="warning", confidence="media",
            description=(
                f"vICMSDeson={v_icms_deson:.2f} no XML — verificar E111 "
                f"com código de desoneração no período."
            ),
            xml_field="total/ICMSTot/vICMSDeson",
            value_xml=f"{v_icms_deson:.2f}",
            sped_register="E111",
            suggested_action="revisar_apuracao",
            benefit_context=benefit_context,
        ))

    return findings


# ──────────────────────────────────────────────────────────────────────
# XC051 — Validacao triangular C190 vs C170 vs XML
# ──────────────────────────────────────────────────────────────────────

def run_xc051_c190_triangular(scope: DocumentScope) -> list[CrossValidationFinding]:
    """XC051 — Cruzamento triangular C190 x C170 x XML por grupo (CST+CFOP+ALIQ).

    Para cada grupo C190 do documento:
    - Soma VL_ITEM dos C170 pareados do mesmo grupo
    - Soma vl_prod dos itens XML do mesmo grupo
    - Compara C190.VL_OPR contra ambas somas
    - Diagnostica: quem diverge de quem (XML confirma C170? XML confirma C190?)
    """
    findings = []
    if not scope.has_xml or scope.match_status not in ("matched",):
        return findings
    if not scope.c190_records:
        return findings

    tol = 1.00  # tolerancia de consolidacao (rounding_policy spec)

    # Agrupar C170 pareados por (CST, CFOP, ALIQ)
    c170_by_group: dict[str, float] = defaultdict(float)
    c170_icms_by_group: dict[str, float] = defaultdict(float)
    for pair in scope.item_pairs:
        if pair.c170 is None:
            continue
        c = pair.c170
        cst = c.cst_icms.zfill(3) if len(c.cst_icms) == 2 else c.cst_icms
        key = f"{cst}|{c.cfop[:4]}|{c.aliq_icms:.2f}"
        vl_liq = c.vl_item - c.vl_desc
        c170_by_group[key] += vl_liq
        c170_icms_by_group[key] += c.vl_icms

    # Tambem somar C170 sem match XML (itens internos do SPED)
    for c in scope.c170_sem_match:
        cst = c.cst_icms.zfill(3) if len(c.cst_icms) == 2 else c.cst_icms
        key = f"{cst}|{c.cfop[:4]}|{c.aliq_icms:.2f}"
        vl_liq = c.vl_item - c.vl_desc
        c170_by_group[key] += vl_liq
        c170_icms_by_group[key] += c.vl_icms

    # Agrupar XML items por (CST, CFOP, ALIQ)
    xml_by_group: dict[str, float] = defaultdict(float)
    xml_icms_by_group: dict[str, float] = defaultdict(float)
    for pair in scope.item_pairs:
        if pair.xml_item is None:
            continue
        xi = pair.xml_item
        cst = xi.cst_icms.zfill(3) if len(xi.cst_icms) == 2 else xi.cst_icms
        key = f"{cst}|{xi.cfop[:4]}|{xi.aliq_icms:.2f}"
        vl_liq = xi.vl_prod - xi.vl_desc
        xml_by_group[key] += vl_liq
        xml_icms_by_group[key] += xi.vl_icms

    for xi in scope.xml_items_sem_match:
        cst = xi.cst_icms.zfill(3) if len(xi.cst_icms) == 2 else xi.cst_icms
        key = f"{cst}|{xi.cfop[:4]}|{xi.aliq_icms:.2f}"
        vl_liq = xi.vl_prod - xi.vl_desc
        xml_by_group[key] += vl_liq
        xml_icms_by_group[key] += xi.vl_icms

    # Para cada C190, comparar triangularmente
    for c190 in scope.c190_records:
        cst = c190.get("CST_ICMS", "")
        cfop = c190.get("CFOP", "")[:4]
        aliq = c190.get("ALIQ_ICMS", 0.0)
        vl_opr = c190.get("VL_OPR", 0.0)
        vl_icms_c190 = c190.get("VL_ICMS", 0.0)
        key = f"{cst}|{cfop}|{aliq:.2f}"

        soma_c170 = round(c170_by_group.get(key, 0.0), 2)
        soma_xml = round(xml_by_group.get(key, 0.0), 2)

        if vl_opr == 0 and soma_c170 == 0 and soma_xml == 0:
            continue

        diff_c190_c170 = abs(vl_opr - soma_c170)
        diff_c190_xml = abs(vl_opr - soma_xml)
        diff_c170_xml = abs(soma_c170 - soma_xml)

        # VL_OPR pode incluir despesas rateadas que nao estao no XML, entao
        # a comparacao triangular foca em QUEM diverge de QUEM
        if diff_c190_c170 > tol:
            # Diagnostico triangular
            if soma_xml > 0 and diff_c170_xml < tol:
                diag = (
                    f"XML confirma C170 (soma={soma_xml:.2f}) — "
                    f"provavel erro no totalizador C190."
                )
                confidence = "alta"
            elif soma_xml > 0 and diff_c190_xml < tol:
                diag = (
                    f"XML confirma C190 (soma={soma_xml:.2f}) — "
                    f"provavel erro nos itens C170."
                )
                confidence = "alta"
            elif soma_xml > 0:
                diag = (
                    f"XML (soma={soma_xml:.2f}) diverge de ambos — "
                    f"revisar XML, C170 e C190."
                )
                confidence = "media"
            else:
                diag = "Sem XML para este grupo — validacao bilateral apenas."
                confidence = "alta"

            findings.append(_make_finding(
                "XC051", "C190_DIVERGE_C170_TRIANGULAR",
                severity="error", confidence=confidence,
                description=(
                    f"C190 (CST={cst} CFOP={cfop} ALIQ={aliq:.2f}%): "
                    f"VL_OPR={vl_opr:.2f} diverge da soma C170={soma_c170:.2f} "
                    f"(dif={diff_c190_c170:.2f}). {diag}"
                ),
                sped_register="C190", sped_field="VL_OPR",
                value_sped=f"{vl_opr:.2f}",
                xml_field="soma(vProd-vDesc) por grupo",
                value_xml=f"{soma_xml:.2f}" if soma_xml > 0 else "",
                suggested_action="corrigir_no_sped",
                evidence={
                    "c190_vl_opr": vl_opr,
                    "soma_c170": soma_c170,
                    "soma_xml": soma_xml,
                    "grupo": key,
                },
            ))

        # VL_ICMS triangular
        soma_icms_c170 = round(c170_icms_by_group.get(key, 0.0), 2)
        soma_icms_xml = round(xml_icms_by_group.get(key, 0.0), 2)
        diff_icms = abs(vl_icms_c190 - soma_icms_c170)

        if diff_icms > tol and (vl_icms_c190 > 0 or soma_icms_c170 > 0):
            if soma_icms_xml > 0 and abs(soma_icms_c170 - soma_icms_xml) < tol:
                diag_icms = f"XML confirma C170 — provavel erro no C190."
            elif soma_icms_xml > 0 and abs(vl_icms_c190 - soma_icms_xml) < tol:
                diag_icms = f"XML confirma C190 — provavel erro nos C170."
            else:
                diag_icms = f"Revisar todos."

            findings.append(_make_finding(
                "XC051", "C190_VL_ICMS_DIVERGE_TRIANGULAR",
                severity="error", confidence="alta",
                description=(
                    f"C190 (CST={cst} CFOP={cfop}): "
                    f"VL_ICMS={vl_icms_c190:.2f} vs soma C170={soma_icms_c170:.2f} "
                    f"(dif={diff_icms:.2f}). {diag_icms}"
                ),
                sped_register="C190", sped_field="VL_ICMS",
                value_sped=f"{vl_icms_c190:.2f}",
                suggested_action="corrigir_no_sped",
            ))

    return findings


# ──────────────────────────────────────────────────────────────────────
# ETAPA 9 — Deduplicacao inteligente
# ──────────────────────────────────────────────────────────────────────

def deduplicate_findings(findings: list[CrossValidationFinding]) -> list[CrossValidationFinding]:
    """Agrupa findings por root_cause_group e marca derivados (spec seção 2.5)."""
    groups: dict[str, list[CrossValidationFinding]] = defaultdict(list)
    no_group = []

    for f in findings:
        if f.root_cause_group:
            groups[f.root_cause_group].append(f)
        else:
            no_group.append(f)

    result = list(no_group)

    for group_key, group_findings in groups.items():
        if len(group_findings) <= 1:
            result.extend(group_findings)
            continue

        # Primeiro finding (causa raiz) fica intacto
        root = group_findings[0]
        root.is_derived = False
        result.append(root)

        # Demais marcados como derivados
        for derived in group_findings[1:]:
            derived.is_derived = True
            derived.rule_outcome = RuleOutcome.SUPPRESSED_BY_ROOT_CAUSE
            result.append(derived)

    return result


# ──────────────────────────────────────────────────────────────────────
# Priorizacao (action_priority)
# ──────────────────────────────────────────────────────────────────────

def assign_priority(finding: CrossValidationFinding) -> str:
    """Atribui action_priority (P1-P4) conforme spec seção 4.2."""
    if finding.severity == "critico":
        return "P1"
    if finding.severity == "error":
        if finding.sped_field in ("VL_ICMS", "VL_PIS", "VL_COFINS", "VL_IPI",
                                   "VL_BC_ICMS", "ALIQ_ICMS"):
            return "P1"
        return "P2"
    if finding.severity == "warning":
        if finding.confidence in ("alta", "media"):
            return "P3"
        return "P4"
    return "P4"


# ──────────────────────────────────────────────────────────────────────
# ENGINE PRINCIPAL
# ──────────────────────────────────────────────────────────────────────

class CrossValidationEngine:
    """Motor de Cruzamento NF-e XML x SPED EFD.

    Pipeline de 10 etapas conforme motor_cruzamento_v_final.txt.
    """

    def __init__(self, db, file_id: int, regime: str = "", cod_ver: str = "",
                 benefit_context: str = ""):
        self.db = db
        self.file_id = file_id
        self.regime = regime
        self.cod_ver = cod_ver
        self.benefit_context = benefit_context
        self.scopes: list[DocumentScope] = []
        self.all_findings: list[CrossValidationFinding] = []

    def run(self) -> list[CrossValidationFinding]:
        """Executa pipeline completo de cruzamento."""
        logger.info("CrossValidationEngine: iniciando para file_id=%d", self.file_id)

        # Etapa 0 — Construcao de escopos (elegibilidade + pareamento)
        builder = DocumentScopeBuilder(
            self.db, self.file_id, regime=self.regime, cod_ver=self.cod_ver,
        )
        self.scopes = builder.build_all()

        if not self.scopes:
            logger.info("CrossValidationEngine: nenhum escopo construido")
            return []

        # Etapas 1-8: executar regras por escopo
        for scope in self.scopes:
            scope.regime = self.regime
            scope_findings = []

            # Etapa 1 — Camada A: Estrutural
            scope_findings.extend(run_layer_a(scope))

            # Etapa 2 — Camada D: Identidade e Status
            scope_findings.extend(run_layer_d_identity(scope))

            # Etapa 3 — Camada D: Totais
            scope_findings.extend(run_layer_d_totals(scope))

            # Etapas 4-5 — Camada E: Itens (pareamento ja feito no builder)
            scope_findings.extend(run_layer_e_items(scope))

            # Etapa 8 — Familias avancadas
            scope_findings.extend(run_family_xc07x(scope))
            scope_findings.extend(run_family_xc08x(scope))
            scope_findings.extend(run_family_xc09x(scope, self.benefit_context))

            # XC051 — Validacao triangular C190 vs C170 vs XML
            scope_findings.extend(run_xc051_c190_triangular(scope))

            # Enriquecer findings com dados do escopo
            for f in scope_findings:
                f.file_id = self.file_id
                f.document_scope_id = scope.id
                f.chave_nfe = scope.chave_nfe
                f.nfe_id = scope.nfe_id
                f.regime_context = f.regime_context or self.regime
                f.layout_version_detected = self.cod_ver

            scope.findings = scope_findings
            self.all_findings.extend(scope_findings)

        # Etapa 9 — Deduplicacao
        self.all_findings = deduplicate_findings(self.all_findings)

        # Atribuir prioridades
        for f in self.all_findings:
            f.action_priority = assign_priority(f)

        logger.info(
            "CrossValidationEngine: %d findings gerados (%d EXECUTED_ERROR, %d derivados)",
            len(self.all_findings),
            sum(1 for f in self.all_findings if f.rule_outcome == RuleOutcome.EXECUTED_ERROR),
            sum(1 for f in self.all_findings if f.is_derived),
        )

        return self.all_findings

    def persist_findings(self) -> int:
        """Persiste findings na tabela cross_validation_findings (batch otimizado)."""
        if not self.all_findings:
            return 0

        self.db.execute(
            "DELETE FROM cross_validation_findings WHERE file_id = ?",
            (self.file_id,),
        )

        rows = []
        for f in self.all_findings:
            if f.rule_outcome == RuleOutcome.EXECUTED_OK:
                continue
            rows.append((
                f.file_id, f.chave_nfe, f.rule_id, f.legacy_rule_id, f.rule_version,
                f.reference_pack_version, f.benefit_context_version,
                f.layout_version_detected, f.config_hash,
                f.error_type,
                f.rule_outcome.value if isinstance(f.rule_outcome, RuleOutcome) else f.rule_outcome,
                f.tipo_irregularidade,
                f.severity, f.confidence,
                f.sped_register, f.sped_field, f.value_sped,
                f.xml_field, f.value_xml,
                f.description, f.evidence, f.regime_context, f.benefit_context,
                f.suggested_action,
                f.root_cause_group, 1 if f.is_derived else 0,
                f.risk_score, f.technical_risk_score,
                f.fiscal_impact_estimate, f.action_priority,
                f.review_status,
            ))

        sql = """INSERT INTO cross_validation_findings (
            file_id, chave_nfe, rule_id, legacy_rule_id, rule_version,
            reference_pack_version, benefit_context_version,
            layout_version_detected, config_hash,
            error_type, rule_outcome, tipo_irregularidade,
            severity, confidence,
            sped_register, sped_field, value_sped,
            xml_field, value_xml,
            description, evidence, regime_context, benefit_context,
            suggested_action,
            root_cause_group, is_derived,
            risk_score, technical_risk_score,
            fiscal_impact_estimate, action_priority,
            review_status
        ) VALUES (
            ?, ?, ?, ?, ?,
            ?, ?,
            ?, ?,
            ?, ?, ?,
            ?, ?,
            ?, ?, ?,
            ?, ?,
            ?, ?, ?, ?,
            ?,
            ?, ?,
            ?, ?,
            ?, ?,
            ?
        )"""
        _batch_insert(self.db, sql, rows)
        self.db.commit()
        logger.info("CrossValidationEngine: %d findings persistidos", len(rows))
        return len(rows)

    def persist_to_legacy_table(self) -> int:
        """Persiste tambem na tabela nfe_cruzamento (batch otimizado, retrocompatibilidade)."""
        if not self.all_findings:
            return 0

        self.db.execute(
            "DELETE FROM nfe_cruzamento WHERE file_id = ? AND rule_id LIKE ?",
            (self.file_id, "XC%"),
        )

        rows = []
        for f in self.all_findings:
            if f.rule_outcome in (RuleOutcome.EXECUTED_OK, RuleOutcome.NOT_APPLICABLE):
                continue
            rows.append((
                f.file_id, f.nfe_id or None, f.chave_nfe,
                f.rule_id, f.severity,
                f.xml_field, f.value_xml,
                f.sped_field, f.value_sped,
                0.0,
                f.description,
                "open",
            ))

        sql = """INSERT INTO nfe_cruzamento (
            file_id, nfe_id, chave_nfe, rule_id, severity,
            campo_xml, valor_xml, campo_sped, valor_sped,
            diferenca, message, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        _batch_insert(self.db, sql, rows)
        self.db.commit()
        return len(rows)

    def get_summary(self) -> dict:
        """Retorna resumo dos findings."""
        by_severity = defaultdict(int)
        by_rule = defaultdict(int)
        by_priority = defaultdict(int)

        for f in self.all_findings:
            if f.rule_outcome == RuleOutcome.EXECUTED_ERROR and not f.is_derived:
                by_severity[f.severity] += 1
                by_rule[f.rule_id] += 1
                by_priority[f.action_priority] += 1

        return {
            "total_findings": len(self.all_findings),
            "total_errors": sum(
                1 for f in self.all_findings
                if f.rule_outcome == RuleOutcome.EXECUTED_ERROR and not f.is_derived
            ),
            "total_derived": sum(1 for f in self.all_findings if f.is_derived),
            "total_scopes": len(self.scopes),
            "scopes_matched": sum(1 for s in self.scopes if s.match_status == "matched"),
            "scopes_sem_xml": sum(1 for s in self.scopes if s.match_status == "sem_xml"),
            "scopes_sem_c100": sum(1 for s in self.scopes if s.match_status == "sem_c100"),
            "by_severity": dict(by_severity),
            "by_rule": dict(by_rule),
            "by_priority": dict(by_priority),
        }
