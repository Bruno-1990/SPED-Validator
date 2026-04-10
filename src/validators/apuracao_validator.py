"""Validador de apuração ICMS — reconciliação (C190+D190+D590)→E110→E111→E116.

PRD v2/v3:
- RF001-DEB: Σ (C190+D190+D590).VL_ICMS (CST débito, saída) == E110.VL_TOT_DEBITOS
- RF002-CRE: Σ (C190+D190).VL_ICMS (CST crédito, entrada) == E110.VL_TOT_CREDITOS
- RF003-SALDO: Consistência interna do saldo E110
- RF004-AJ-SUM: Σ E111 débito == E110.VL_AJ_DEBITOS; Σ E111 crédito == E110.VL_AJ_CREDITOS
- RF008-E116-EXIST: VL_ICMS_RECOLHER > 0 → E116 presente
- RF009-E116-VALOR: Σ E116.VL_OR == VL_ICMS_RECOLHER + VL_TOT_DED

Referência TS: data/apuration.reconciler.ts, data/reconciler.utils.ts
Base legal: GP-317 §E110, LC-87 art.12/20, COTEPE-44 Reg.D190/D590
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import SpedRecord, ValidationError
from ..parser import group_by_register
from .helpers import (
    CST_DIFERIMENTO,
    CST_TRIBUTADO,
    F_C190_CST,
    F_C190_CFOP,
    F_C190_VL_ICMS,
    F_E110_VL_AJ_CREDITOS,
    F_E110_VL_AJ_DEBITOS,
    F_E110_VL_ESTORNOS_CRED,
    F_E110_VL_ESTORNOS_DEB,
    F_E110_VL_ICMS_RECOLHER,
    F_E110_VL_SLD_APURADO,
    F_E110_VL_SLD_CREDOR_ANT,
    F_E110_VL_SLD_CREDOR_TRANSPORTAR,
    F_E110_VL_TOT_CREDITOS,
    F_E110_VL_TOT_DEBITOS,
    F_E110_VL_TOT_DED,
    F_E111_COD_AJ_APUR,
    F_E111_VL_AJ_APUR,
    get_field,
    make_generic_error,
    to_float,
    trib,
)

if TYPE_CHECKING:
    from ..services.context_builder import ValidationContext

# ──────────────────────────────────────────────
# CSTs por tipo de registro (referência: reconciler.utils.ts)
# Mantidos separados para evolução independente por bloco.
# ──────────────────────────────────────────────

# C190 — Notas Fiscais de mercadoria (Bloco C)
_CST_C190_DEBITO = {"00", "10", "20", "51", "70", "90"}
_CST_C190_CREDITO = {"00", "20", "90"}

# D190 — CT-e / NFST (Bloco D — transporte)
_CST_D190_DEBITO = {"00", "20", "51", "70", "90"}
_CST_D190_CREDITO = {"00", "20", "90"}

# D590 — NFSC (Bloco D — comunicação)
_CST_D590_DEBITO = {"00", "20", "51", "70", "90"}

# CFOPs de subcontratação (EX-D-002): ICMS já recolhido pelo contratante
_CFOP_SUBCONTRATACAO = {"5932", "6932"}


# ──────────────────────────────────────────────
# API pública
# ──────────────────────────────────────────────

def validate_apuracao(
    records: list[SpedRecord],
    context: ValidationContext | None = None,
) -> list[ValidationError]:
    """Reconciliação C190→E110→E111→E116 (PRD v2 Fase 1)."""
    from ..services.context_builder import TaxRegime

    # Simples Nacional não apura ICMS pelo regime normal (EX-RF001-02)
    if context and context.regime == TaxRegime.SIMPLES_NACIONAL:
        return []

    groups = group_by_register(records)
    errors: list[ValidationError] = []

    e110_list = groups.get("E110", [])
    if not e110_list:
        return []  # Sem E110 → sem apuração para validar

    e110 = e110_list[0]
    e111_list = groups.get("E111", [])
    e116_list = groups.get("E116", [])
    c190_list = groups.get("C190", [])
    d190_list = groups.get("D190", [])
    d590_list = groups.get("D590", [])

    # RF001-DEB: Reconciliação débitos (C190 + D190 + D590)
    errors.extend(_rf001_debitos(c190_list, d190_list, d590_list, e110))

    # RF002-CRE: Reconciliação créditos (C190 + D190)
    errors.extend(_rf002_creditos(c190_list, d190_list, e110))

    # RF003-SALDO: Consistência interna E110
    errors.extend(_rf003_saldo(e110))

    # RF004-AJ-SUM: Soma E111 fecha E110
    errors.extend(_rf004_ajustes(e111_list, e110))

    # RF008/RF009: Recolhimento E116
    errors.extend(_rf008_rf009_recolhimento(e110, e116_list))

    return errors


# ──────────────────────────────────────────────
# RF001-DEB: Σ C190.VL_ICMS (saída, CST débito) == E110.VL_TOT_DEBITOS
# ──────────────────────────────────────────────

def _rf001_debitos(
    c190_list: list[SpedRecord],
    d190_list: list[SpedRecord],
    d590_list: list[SpedRecord],
    e110: SpedRecord,
) -> list[ValidationError]:
    """RF001-DEB: reconciliação de débitos (C190+D190+D590) → E110.

    Referência: apuration.reconciler.ts — reconciliarDebitos()
    """
    # Etapa 1a: débitos C190 (mercadorias)
    deb_c190 = 0.0
    for rec in c190_list:
        cfop = get_field(rec, F_C190_CFOP)
        cst = trib(get_field(rec, F_C190_CST))
        vl_icms = to_float(get_field(rec, F_C190_VL_ICMS))
        if cfop and cfop[0] in ("5", "6", "7") and cst in _CST_C190_DEBITO:
            if cst in CST_DIFERIMENTO:
                continue  # EX-RF001-01: diferimento não entra no débito imediato
            deb_c190 += vl_icms

    # Etapa 1b: débitos D190 (transporte — CT-e)
    deb_d190 = 0.0
    for rec in d190_list:
        cfop = get_field(rec, "CFOP")
        cst = trib(get_field(rec, "CST_ICMS"))
        vl_icms = to_float(get_field(rec, "VL_ICMS"))
        cod_sit = get_field(rec, "COD_SIT") if hasattr(rec, 'fields') else ""
        # EX-D-004: CT-e cancelado (COD_SIT=02) não entra
        if cod_sit == "02":
            continue
        # EX-D-002: subcontratação CFOP 5932/6932 já recolhido pelo contratante
        if cfop in _CFOP_SUBCONTRATACAO:
            continue
        # Saída (CFOP 5xxx/6xxx) com CST de débito
        if cfop and cfop[0] in ("5", "6") and cst in _CST_D190_DEBITO:
            if cst in CST_DIFERIMENTO:
                continue
            deb_d190 += vl_icms

    # Etapa 1c: débitos D590 (comunicação — NFSC)
    deb_d590 = 0.0
    for rec in d590_list:
        cst = trib(get_field(rec, "CST_ICMS"))
        vl_icms = to_float(get_field(rec, "VL_ICMS"))
        if cst in _CST_D590_DEBITO and cst not in CST_DIFERIMENTO:
            deb_d590 += vl_icms

    debitos_total = round(deb_c190 + deb_d190 + deb_d590, 2)
    declarado = to_float(get_field(e110, F_E110_VL_TOT_DEBITOS))
    diferenca = abs(debitos_total - declarado)

    # Tolerância: MAX(0.01, declarado * 0.00001) — half-even compatible
    tolerancia = max(0.01, declarado * 0.00001) if declarado > 0 else 0.01

    if diferenca <= tolerancia:
        return []

    # Classificar severidade
    if declarado == 0 and debitos_total > 0:
        sev_label = "CRITICO"
    elif diferenca > 10000:
        sev_label = "CRITICO"
    elif diferenca > 100:
        sev_label = "ALTO"
    else:
        sev_label = "MEDIO"

    # Composição do breakdown
    breakdown_parts = [f"C190={deb_c190:,.2f}"]
    if deb_d190 > 0:
        breakdown_parts.append(f"D190={deb_d190:,.2f}")
    if deb_d590 > 0:
        breakdown_parts.append(f"D590={deb_d590:,.2f}")

    return [make_generic_error(
        "RF001_DEBITOS_DIVERGENTE",
        (
            f"RF001-DEB: Debitos calculados ({' + '.join(breakdown_parts)}) = "
            f"R$ {debitos_total:,.2f}, mas E110.VL_TOT_DEBITOS = R$ {declarado:,.2f}. "
            f"Diferenca: R$ {diferenca:,.2f} [{sev_label}]. "
            f"Base legal: GP-317 E110 VL_TOT_DEBITOS, LC-87 art.12, COTEPE-44 Reg.D190."
        ),
        register="E110",
        value=f"{declarado:.2f}",
    )]


# ──────────────────────────────────────────────
# RF002-CRE: Σ C190.VL_ICMS (entrada, CST crédito) == E110.VL_TOT_CREDITOS
# ──────────────────────────────────────────────

def _rf002_creditos(
    c190_list: list[SpedRecord],
    d190_list: list[SpedRecord],
    e110: SpedRecord,
) -> list[ValidationError]:
    """RF002-CRE: reconciliação de créditos (C190+D190) → E110.

    Referência: apuration.reconciler.ts — reconciliarCreditos()
    """
    # Etapa 1a: créditos C190 (entradas de mercadorias)
    cre_c190 = 0.0
    for rec in c190_list:
        cfop = get_field(rec, F_C190_CFOP)
        cst = trib(get_field(rec, F_C190_CST))
        vl_icms = to_float(get_field(rec, F_C190_VL_ICMS))
        if cfop and cfop[0] in ("1", "2", "3") and cst in _CST_C190_CREDITO:
            cre_c190 += vl_icms

    # Etapa 1b: créditos D190 (tomador de transporte — IND_EMIT implícito via CFOP)
    cre_d190 = 0.0
    for rec in d190_list:
        cfop = get_field(rec, "CFOP")
        cst = trib(get_field(rec, "CST_ICMS"))
        vl_icms = to_float(get_field(rec, "VL_ICMS"))
        cod_sit = get_field(rec, "COD_SIT") if hasattr(rec, 'fields') else ""
        if cod_sit == "02":
            continue  # EX-D-004: CT-e cancelado
        # Entrada (CFOP 1xxx/2xxx) com CST de crédito
        if cfop and cfop[0] in ("1", "2") and cst in _CST_D190_CREDITO:
            cre_d190 += vl_icms

    creditos_total = round(cre_c190 + cre_d190, 2)
    declarado = to_float(get_field(e110, F_E110_VL_TOT_CREDITOS))
    diferenca = abs(creditos_total - declarado)

    tolerancia = max(0.01, declarado * 0.00001) if declarado > 0 else 0.01

    if diferenca <= tolerancia:
        return []

    if diferenca > 10000:
        sev_label = "CRITICO"
    elif diferenca > 100:
        sev_label = "ALTO"
    else:
        sev_label = "MEDIO"

    breakdown_parts = [f"C190={cre_c190:,.2f}"]
    if cre_d190 > 0:
        breakdown_parts.append(f"D190={cre_d190:,.2f}")

    return [make_generic_error(
        "RF002_CREDITOS_DIVERGENTE",
        (
            f"RF002-CRE: Creditos calculados ({' + '.join(breakdown_parts)}) = "
            f"R$ {creditos_total:,.2f}, mas E110.VL_TOT_CREDITOS = R$ {declarado:,.2f}. "
            f"Diferenca: R$ {diferenca:,.2f} [{sev_label}]. "
            f"Base legal: GP-317 E110 VL_TOT_CREDITOS, LC-87 art.20, COTEPE-44 Reg.D190."
        ),
        register="E110",
        value=f"{declarado:.2f}",
    )]


# ──────────────────────────────────────────────
# RF003-SALDO: Consistência interna do E110
# ──────────────────────────────────────────────

def _rf003_saldo(e110: SpedRecord) -> list[ValidationError]:
    """RF003-SALDO: fórmula completa do E110 deve fechar.

    VL_SLD_APURADO = (VL_TOT_DEBITOS + VL_AJ_DEBITOS + VL_ESTORNOS_CRED)
                   - (VL_TOT_CREDITOS + VL_AJ_CREDITOS + VL_ESTORNOS_DEB)
                   - VL_SLD_CREDOR_ANT
    """
    errors: list[ValidationError] = []

    tot_deb = to_float(get_field(e110, F_E110_VL_TOT_DEBITOS))
    aj_deb = to_float(get_field(e110, F_E110_VL_AJ_DEBITOS))
    est_cred = to_float(get_field(e110, F_E110_VL_ESTORNOS_CRED))
    tot_cred = to_float(get_field(e110, F_E110_VL_TOT_CREDITOS))
    aj_cred = to_float(get_field(e110, F_E110_VL_AJ_CREDITOS))
    est_deb = to_float(get_field(e110, F_E110_VL_ESTORNOS_DEB))
    sld_ant = to_float(get_field(e110, F_E110_VL_SLD_CREDOR_ANT))
    sld_apurado = to_float(get_field(e110, F_E110_VL_SLD_APURADO))
    tot_ded = to_float(get_field(e110, F_E110_VL_TOT_DED))
    icms_recolher = to_float(get_field(e110, F_E110_VL_ICMS_RECOLHER))
    sld_credor_transp = to_float(get_field(e110, F_E110_VL_SLD_CREDOR_TRANSPORTAR))

    # Fórmula principal
    saldo_calculado = (tot_deb + aj_deb + est_cred) - (tot_cred + aj_cred + est_deb) - sld_ant
    diff_saldo = abs(saldo_calculado - sld_apurado)

    if diff_saldo > 0.01:
        errors.append(make_generic_error(
            "RF003_SALDO_INCONSISTENTE",
            (
                f"RF003-SALDO: VL_SLD_APURADO declarado = R$ {sld_apurado:,.2f}, "
                f"mas recalculado = R$ {saldo_calculado:,.2f} "
                f"(dif = R$ {diff_saldo:,.2f}). "
                f"Formula: (DEB {tot_deb:,.2f} + AJ_DEB {aj_deb:,.2f} + EST_CRED {est_cred:,.2f}) "
                f"- (CRED {tot_cred:,.2f} + AJ_CRED {aj_cred:,.2f} + EST_DEB {est_deb:,.2f}) "
                f"- SLD_ANT {sld_ant:,.2f} = {saldo_calculado:,.2f}. "
                f"Base legal: GP-317 E110 VL_SLD_APURADO, COTEPE-44."
            ),
            register="E110",
            value=f"{sld_apurado:.2f}",
        ))

    # Saldo positivo → deve ter recolhimento ou dedução
    if saldo_calculado > 0:
        esperado_recolher = saldo_calculado - tot_ded
        if esperado_recolher < 0:
            esperado_recolher = 0
        diff_recolher = abs(esperado_recolher - icms_recolher)
        if diff_recolher > 0.01:
            errors.append(make_generic_error(
                "RF003_RECOLHER_INCONSISTENTE",
                (
                    f"RF003-SALDO: VL_ICMS_RECOLHER declarado = R$ {icms_recolher:,.2f}, "
                    f"mas esperado = R$ {esperado_recolher:,.2f} "
                    f"(SLD_APURADO {saldo_calculado:,.2f} - TOT_DED {tot_ded:,.2f}). "
                    f"Diferenca: R$ {diff_recolher:,.2f}."
                ),
                register="E110",
                value=f"{icms_recolher:.2f}",
            ))

    # Saldo negativo → deve transportar crédito
    if saldo_calculado < 0:
        esperado_credor = abs(saldo_calculado)
        diff_credor = abs(esperado_credor - sld_credor_transp)
        if diff_credor > 0.01:
            errors.append(make_generic_error(
                "RF003_CREDOR_INCONSISTENTE",
                (
                    f"RF003-SALDO: VL_SLD_CREDOR_TRANSPORTAR declarado = "
                    f"R$ {sld_credor_transp:,.2f}, mas esperado = "
                    f"R$ {esperado_credor:,.2f}. "
                    f"Diferenca: R$ {diff_credor:,.2f}."
                ),
                register="E110",
                value=f"{sld_credor_transp:.2f}",
            ))

    return errors


# ──────────────────────────────────────────────
# RF004-AJ-SUM: Σ E111 débito == E110.VL_AJ_DEBITOS
# ──────────────────────────────────────────────

def _rf004_ajustes(
    e111_list: list[SpedRecord],
    e110: SpedRecord,
) -> list[ValidationError]:
    """RF004-AJ-SUM: soma dos E111 por categoria deve fechar com E110."""
    errors: list[ValidationError] = []

    soma_aj_debito = 0.0
    soma_aj_credito = 0.0
    soma_est_debito = 0.0
    soma_est_credito = 0.0
    soma_deducao = 0.0

    for rec in e111_list:
        cod_aj = get_field(rec, F_E111_COD_AJ_APUR)
        valor = to_float(get_field(rec, F_E111_VL_AJ_APUR))

        if len(cod_aj) < 4:
            continue

        # Classificar pela posição [3] do código de ajuste (Tabela 5.1.1)
        # 0 = débito especial, 1 = estorno de crédito
        # 2 = outros débitos, 3 = crédito presumido
        # 4 = estorno de débito, 5 = outros créditos
        # 6 = dedução
        tipo = cod_aj[3]
        if tipo in ("0", "2"):
            soma_aj_debito += valor
        elif tipo in ("3", "5"):
            soma_aj_credito += valor
        elif tipo == "1":
            soma_est_credito += valor
        elif tipo == "4":
            soma_est_debito += valor
        elif tipo == "6":
            soma_deducao += valor

    # Comparar com E110
    vl_aj_deb = to_float(get_field(e110, F_E110_VL_AJ_DEBITOS))
    vl_aj_cred = to_float(get_field(e110, F_E110_VL_AJ_CREDITOS))
    vl_tot_ded = to_float(get_field(e110, F_E110_VL_TOT_DED))

    diff_deb = abs(soma_aj_debito - vl_aj_deb)
    if diff_deb > 0.01 and (soma_aj_debito > 0 or vl_aj_deb > 0):
        errors.append(make_generic_error(
            "RF004_AJ_DEBITOS_DIVERGENTE",
            (
                f"RF004-AJ-SUM: Soma E111 ajustes de debito = R$ {soma_aj_debito:,.2f}, "
                f"mas E110.VL_AJ_DEBITOS = R$ {vl_aj_deb:,.2f}. "
                f"Diferenca: R$ {diff_deb:,.2f}. "
                f"Base legal: GP-317 E111, Tab.5.1.1."
            ),
            register="E110",
            value=f"{vl_aj_deb:.2f}",
        ))

    diff_cred = abs(soma_aj_credito - vl_aj_cred)
    if diff_cred > 0.01 and (soma_aj_credito > 0 or vl_aj_cred > 0):
        errors.append(make_generic_error(
            "RF004_AJ_CREDITOS_DIVERGENTE",
            (
                f"RF004-AJ-SUM: Soma E111 ajustes de credito = R$ {soma_aj_credito:,.2f}, "
                f"mas E110.VL_AJ_CREDITOS = R$ {vl_aj_cred:,.2f}. "
                f"Diferenca: R$ {diff_cred:,.2f}. "
                f"Base legal: GP-317 E111, Tab.5.1.1."
            ),
            register="E110",
            value=f"{vl_aj_cred:.2f}",
        ))

    diff_ded = abs(soma_deducao - vl_tot_ded)
    if diff_ded > 0.01 and (soma_deducao > 0 or vl_tot_ded > 0):
        errors.append(make_generic_error(
            "RF004_AJ_DEDUCAO_DIVERGENTE",
            (
                f"RF004-AJ-SUM: Soma E111 deducoes = R$ {soma_deducao:,.2f}, "
                f"mas E110.VL_TOT_DED = R$ {vl_tot_ded:,.2f}. "
                f"Diferenca: R$ {diff_ded:,.2f}."
            ),
            register="E110",
            value=f"{vl_tot_ded:.2f}",
        ))

    return errors


# ──────────────────────────────────────────────
# RF008/RF009: Recolhimento E116
# ──────────────────────────────────────────────

def _rf008_rf009_recolhimento(
    e110: SpedRecord,
    e116_list: list[SpedRecord],
) -> list[ValidationError]:
    """RF008: E116 presente quando há saldo devedor.
    RF009: Σ E116.VL_OR fecha com VL_ICMS_RECOLHER + VL_TOT_DED.
    """
    errors: list[ValidationError] = []

    recolher = to_float(get_field(e110, F_E110_VL_ICMS_RECOLHER))
    tot_ded = to_float(get_field(e110, F_E110_VL_TOT_DED))
    sld_credor = to_float(get_field(e110, F_E110_VL_SLD_CREDOR_TRANSPORTAR))

    # RF008: E116 deve existir quando há saldo devedor
    if recolher > 0 and not e116_list:
        # Exceção EX-RF008-01: DEB_ESP (DIFAL) pode ter recolhimento separado
        deb_esp = to_float(get_field(e110, "DEB_ESP"))
        if deb_esp > 0 and abs(recolher - deb_esp) < 0.01:
            pass  # DIFAL pode explicar — não gerar erro
        else:
            errors.append(make_generic_error(
                "RF008_E116_AUSENTE",
                (
                    f"RF008-E116-EXIST: E110.VL_ICMS_RECOLHER = R$ {recolher:,.2f} "
                    f"mas nenhum registro E116 de recolhimento foi encontrado. "
                    f"Base legal: GP-317 E116."
                ),
                register="E116",
                value="0",
            ))

    # RF009: Somatório E116 fecha com saldo
    if e116_list and recolher > 0:
        soma_e116 = sum(
            to_float(get_field(rec, "VL_OR"))
            for rec in e116_list
        )
        esperado = recolher + tot_ded
        diff = abs(soma_e116 - esperado)
        if diff > 0.01:
            errors.append(make_generic_error(
                "RF009_E116_VALOR_DIVERGENTE",
                (
                    f"RF009-E116-VALOR: Soma E116.VL_OR = R$ {soma_e116:,.2f}, "
                    f"mas esperado = R$ {esperado:,.2f} "
                    f"(VL_ICMS_RECOLHER {recolher:,.2f} + VL_TOT_DED {tot_ded:,.2f}). "
                    f"Diferenca: R$ {diff:,.2f}. "
                    f"Base legal: GP-317 E116 VL_OR, Tab.5.4."
                ),
                register="E116",
                value=f"{soma_e116:.2f}",
            ))

    # RF014: Saldo credor com E116 de recolhimento normal
    if sld_credor > 0:
        for rec in e116_list:
            cod_or = get_field(rec, "COD_OR")
            if cod_or == "001":
                vl_or = to_float(get_field(rec, "VL_OR"))
                errors.append(make_generic_error(
                    "RF014_SALDO_CREDOR_COM_RECOLHIMENTO",
                    (
                        f"RF014-SALDO-CRE: Saldo credor de R$ {sld_credor:,.2f} "
                        f"mas E116 com COD_OR='001' e VL_OR=R$ {vl_or:,.2f} presente. "
                        f"Saldo credor nao deveria ter recolhimento normal."
                    ),
                    register="E116",
                    value=f"{vl_or:.2f}",
                ))
                break  # Um é suficiente

    return errors
