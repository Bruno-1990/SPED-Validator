"""Motor de hipotese de CST ICMS: sugestao inteligente de enquadramento fiscal.

Camada de inteligencia para CST — apos detectar inconsistencia entre o CST
informado e os demais campos do item, o motor testa hipoteses de
enquadramento e sugere o CST mais compativel com as evidencias.

Fluxo:
1. Detectar incompatibilidade CST vs campos numericos
2. Classificar grupo fiscal provavel (tributacao, isencao, ST, etc)
3. Sugerir CST especifico dentro do grupo
4. Calcular score de confianca
5. Explicar raciocinio ao usuario

Grupos fiscais:
- A: Tributacao integral (000)
- B: Tributacao com reducao de base (020)
- C: Isenta / nao tributada (040, 041)
- D: Diferimento / suspensao (050, 051)
- E: Substituicao tributaria (010, 030, 060, 070)
- F: Outras (090)

Score de confianca:
- Coerencia matematica com tributacao: +30
- Coerencia com CFOP: +20
- Confirmacao C190: +20
- Padrao itens irmaos: +10
- Ausencia de conflito com ST/isencao/diferimento: +10

Resultado:
- >= 80: sugestao forte
- 60-79: sugestao provavel
- 40-59: indicio (apenas grupo, nao codigo exato)
- < 40: nao sugerir

Base legal: Ajuste SINIEF 03/01 (Tabela B - CST ICMS),
Guia Pratico EFD ICMS/IPI, Convenio s/n de 1970.
"""

from __future__ import annotations

from collections import defaultdict

from ..models import SpedRecord, ValidationError
from ..parser import group_by_register
from .correction_hypothesis import CorrectionHypothesis
from .helpers import (
    CST_ISENTO_NT,
    CST_ST,
    CST_TRIBUTADO,
    CFOP_EXPORTACAO,
    CFOP_REMESSA_RETORNO,
    F_C170_ALIQ_ICMS,
    F_C170_ALIQ_ST,
    F_C170_CFOP,
    F_C170_CST_ICMS,
    F_C170_VL_BC_ICMS,
    F_C170_VL_BC_ICMS_ST,
    F_C170_VL_DESC,
    F_C170_VL_ICMS,
    F_C170_VL_ICMS_ST,
    F_C170_VL_ITEM,
    F_C190_ALIQ,
    F_C190_CFOP,
    F_C190_CST,
    TOLERANCE,
    get_field,
    make_error,
    to_float,
    trib,
)

# ──────────────────────────────────────────────
# Tipos de incompatibilidade detectavel
# ──────────────────────────────────────────────

_ISENTO_COM_TRIBUTO = "isento_com_tributo"
_TRIBUTADO_SEM_TRIBUTO = "tributado_sem_tributo"
_SEM_ST_COM_CAMPOS_ST = "sem_st_com_campos_st"
_INTEGRAL_COM_REDUCAO = "integral_com_reducao"

# Limiar minimo de reducao de base para considerar CST 020
# 15% garante que nao e apenas arredondamento ou rateio de frete/seguro
_REDUCAO_MIN = 0.15


# ──────────────────────────────────────────────
# API publica
# ──────────────────────────────────────────────

def validate_cst_hypotheses(records: list[SpedRecord]) -> list[ValidationError]:
    """Analisa CST de cada C170 e gera hipoteses de correcao quando incompativel.

    Nao duplica validacoes existentes — foca em SUGERIR o CST correto,
    nao apenas em apontar que esta errado.
    """
    groups = group_by_register(records)
    errors: list[ValidationError] = []

    # Construir hierarquia C100 -> C170 -> C190
    all_recs: list[SpedRecord] = []
    for reg_type in ("C100", "C170", "C190"):
        all_recs.extend(groups.get(reg_type, []))
    all_recs.sort(key=lambda r: r.line_number)

    current_c100: SpedRecord | None = None
    doc_c170: dict[int, list[SpedRecord]] = defaultdict(list)
    doc_c190: dict[int, list[SpedRecord]] = defaultdict(list)

    for r in all_recs:
        if r.register == "C100":
            current_c100 = r
        elif r.register == "C170" and current_c100 is not None:
            doc_c170[current_c100.line_number].append(r)
        elif r.register == "C190" and current_c100 is not None:
            doc_c190[current_c100.line_number].append(r)

    # Analisar cada documento
    for c100_line, items in doc_c170.items():
        c190_recs = doc_c190.get(c100_line, [])

        for item in items:
            incompat = _detect_inconsistency(item)
            if incompat is None:
                continue

            incompat_type, context = incompat
            hyp = _build_hypothesis(
                item, incompat_type, context, items, c190_recs,
            )
            if hyp and hyp.score >= 40:
                errors.append(_hypothesis_to_error(item, hyp, incompat_type))

    return errors


# ──────────────────────────────────────────────
# Deteccao de incompatibilidade
# ──────────────────────────────────────────────

def _detect_inconsistency(
    item: SpedRecord,
) -> tuple[str, dict] | None:
    """Detecta se o CST do item e incompativel com os campos numericos.

    Retorna (tipo_incompatibilidade, contexto) ou None se CST parece coerente.
    """
    cst_raw = get_field(item, F_C170_CST_ICMS)
    if not cst_raw or len(cst_raw) < 2:
        return None

    cst = trib(cst_raw)
    cfop = get_field(item, F_C170_CFOP)

    vl_bc = to_float(get_field(item, F_C170_VL_BC_ICMS))
    aliq = to_float(get_field(item, F_C170_ALIQ_ICMS))
    vl_icms = to_float(get_field(item, F_C170_VL_ICMS))
    vl_item = to_float(get_field(item, F_C170_VL_ITEM))
    vl_desc = to_float(get_field(item, F_C170_VL_DESC))
    vl_bc_st = to_float(get_field(item, F_C170_VL_BC_ICMS_ST))
    vl_icms_st = to_float(get_field(item, F_C170_VL_ICMS_ST))

    ctx = {
        "cst_raw": cst_raw,
        "cst": cst,
        "cfop": cfop,
        "vl_bc": vl_bc,
        "aliq": aliq,
        "vl_icms": vl_icms,
        "vl_item": vl_item,
        "vl_desc": vl_desc,
        "vl_bc_st": vl_bc_st,
        "vl_icms_st": vl_icms_st,
    }

    tem_tributacao = vl_bc > TOLERANCE and aliq > TOLERANCE and vl_icms > TOLERANCE
    sem_tributacao = vl_bc <= TOLERANCE and vl_icms <= TOLERANCE
    tem_st = vl_bc_st > TOLERANCE or vl_icms_st > TOLERANCE

    # Caso 1: CST isento/NT/suspensao mas item tem tributacao normal
    # CST 40 (isenta), 41 (nao tributada), 50 (suspensao)
    if cst in ("40", "41", "50") and tem_tributacao:
        return (_ISENTO_COM_TRIBUTO, ctx)

    # Caso 2: CST tributado integral mas sem nenhuma tributacao
    # CST 00 com tudo zerado
    if cst == "00" and sem_tributacao:
        # Ignorar se CFOP de remessa/retorno (pode ser legítimo)
        if cfop not in CFOP_REMESSA_RETORNO:
            return (_TRIBUTADO_SEM_TRIBUTO, ctx)

    # Caso 3: CST sem ST mas campos de ST preenchidos
    # Exemplos: CST 00, 20, 40, 41 mas tem BC_ST e ICMS_ST
    if cst not in CST_ST and tem_st:
        return (_SEM_ST_COM_CAMPOS_ST, ctx)

    # Caso 4: CST 00 (integral) mas base indica reducao
    if cst == "00" and tem_tributacao:
        vl_tributavel = vl_item - vl_desc if vl_item > 0 else 0
        if vl_tributavel > TOLERANCE:
            reducao = 1 - (vl_bc / vl_tributavel)
            if reducao >= _REDUCAO_MIN:
                ctx["reducao_pct"] = reducao
                return (_INTEGRAL_COM_REDUCAO, ctx)

    return None


# ──────────────────────────────────────────────
# Construcao da hipotese
# ──────────────────────────────────────────────

def _build_hypothesis(
    item: SpedRecord,
    incompat_type: str,
    ctx: dict,
    siblings: list[SpedRecord],
    c190_recs: list[SpedRecord],
) -> CorrectionHypothesis | None:
    """Constroi hipotese de CST com score de confianca."""
    cst = ctx["cst"]

    if incompat_type == _ISENTO_COM_TRIBUTO:
        return _hyp_isento_com_tributo(item, ctx, siblings, c190_recs)
    elif incompat_type == _TRIBUTADO_SEM_TRIBUTO:
        return _hyp_tributado_sem_tributo(item, ctx, siblings, c190_recs)
    elif incompat_type == _SEM_ST_COM_CAMPOS_ST:
        return _hyp_sem_st_com_campos(item, ctx, siblings, c190_recs)
    elif incompat_type == _INTEGRAL_COM_REDUCAO:
        return _hyp_integral_com_reducao(item, ctx, siblings, c190_recs)

    return None


def _hyp_isento_com_tributo(
    item: SpedRecord,
    ctx: dict,
    siblings: list[SpedRecord],
    c190_recs: list[SpedRecord],
) -> CorrectionHypothesis:
    """CST isento/NT/suspensao mas item tem BC, aliquota e ICMS destacados.

    Base legal: Ajuste SINIEF 03/01, Tabela B:
    - CST 00: tributada integralmente
    - CST 40: isenta (nao pode ter destaque de ICMS)
    - CST 41: nao tributada (idem)
    - CST 50: com suspensao (idem)
    """
    cst = ctx["cst"]
    vl_bc = ctx["vl_bc"]
    aliq = ctx["aliq"]
    vl_icms = ctx["vl_icms"]
    vl_item = ctx["vl_item"]
    vl_desc = ctx["vl_desc"]
    tem_st = ctx["vl_bc_st"] > TOLERANCE or ctx["vl_icms_st"] > TOLERANCE

    # Determinar CST sugerido
    vl_tributavel = vl_item - vl_desc if vl_item > 0 else 0
    tem_reducao = (
        vl_tributavel > TOLERANCE
        and vl_bc < vl_tributavel * (1 - _REDUCAO_MIN)
    )

    if tem_st and tem_reducao:
        suggested = "70"  # Com reducao + ST
    elif tem_st:
        suggested = "10"  # Tributado + ST
    elif tem_reducao:
        suggested = "20"  # Reducao de base
    else:
        suggested = "00"  # Tributacao integral

    hyp = CorrectionHypothesis(
        field_name="CST_ICMS",
        current_value=ctx["cst_raw"],
        suggested_value=suggested,
    )

    # Score: coerencia matematica — item tem tributo, CST diz isento
    hyp.score += 30
    hyp.reasons.append(
        f"CST {cst} indica operacao {'isenta' if cst == '40' else 'nao tributada' if cst == '41' else 'com suspensao'}, "
        f"mas o item possui VL_BC_ICMS={vl_bc:.2f}, ALIQ_ICMS={aliq:.2f}% e VL_ICMS={vl_icms:.2f}"
    )

    # Verificar se recalculo bate
    icms_check = round(vl_bc * aliq / 100, 2)
    if abs(icms_check - vl_icms) <= TOLERANCE:
        hyp.score += 10
        hyp.reasons.append(
            f"Recalculo confirma: {vl_bc:.2f} x {aliq:.2f}% = {icms_check:.2f} (igual ao VL_ICMS)"
        )

    # Score: CFOP compativel com tributacao
    _score_cfop(hyp, ctx)

    # Score: C190 confirma
    _score_c190(hyp, item, suggested, c190_recs)

    # Score: irmaos no documento
    _score_siblings(hyp, item, suggested, siblings)

    # Score: ausencia de conflito
    if not tem_st and suggested in ("00", "20"):
        hyp.score += 10
        hyp.reasons.append(
            "Sem campos de ST preenchidos — consistente com tributacao propria"
        )

    return hyp


def _hyp_tributado_sem_tributo(
    item: SpedRecord,
    ctx: dict,
    siblings: list[SpedRecord],
    c190_recs: list[SpedRecord],
) -> CorrectionHypothesis:
    """CST 00 (tributacao integral) mas sem BC, aliquota e ICMS.

    Base legal: Ajuste SINIEF 03/01, Tabela B:
    - CST 00 exige destaque integral de ICMS
    - Ausencia de BC e imposto sugere isencao ou nao incidencia
    """
    cfop = ctx["cfop"]

    # Para CST 00 sem tributacao, as opcoes sao limitadas
    # Nao conseguimos distinguir 040 de 041 apenas pelos numeros
    # Mas CFOP pode dar pista
    if cfop in CFOP_EXPORTACAO:
        suggested = "41"  # Exportacao = nao tributada
        motivo_cfop = "CFOP de exportacao indica nao incidencia do ICMS"
    elif cfop in CFOP_REMESSA_RETORNO:
        suggested = "41"  # Remessa/retorno geralmente nao tributada
        motivo_cfop = "CFOP de remessa/retorno compativel com nao tributacao"
    else:
        # Sem CFOP indicativo, sugerimos grupo mas nao codigo exato
        suggested = "40"  # Default para isenta (mais comum)
        motivo_cfop = None

    hyp = CorrectionHypothesis(
        field_name="CST_ICMS",
        current_value=ctx["cst_raw"],
        suggested_value=suggested,
    )

    # Score base: incompatibilidade clara
    hyp.score += 25
    hyp.reasons.append(
        "CST 00 indica tributacao integral, mas VL_BC_ICMS, ALIQ_ICMS e "
        "VL_ICMS estao todos zerados — incompativel com destaque de ICMS"
    )

    # Score: CFOP apoia a sugestao
    if motivo_cfop:
        hyp.score += 20
        hyp.reasons.append(motivo_cfop)

    # CFOP de venda/devolucao sem ICMS = sinal adicional
    from .helpers import CFOP_VENDA, CFOP_DEVOLUCAO
    if cfop in CFOP_VENDA | CFOP_DEVOLUCAO and not motivo_cfop:
        hyp.score += 15
        hyp.reasons.append(
            f"CFOP {cfop} (venda/devolucao) normalmente exige destaque de ICMS "
            f"— ausencia reforça inconsistencia do CST 00"
        )

    # Score: C190
    _score_c190(hyp, item, suggested, c190_recs)

    # Score: irmaos
    _score_siblings(hyp, item, suggested, siblings)

    # Nota: confianca tende a ser menor pois nao da pra cravar
    # entre 040, 041 e 090 so pelos numeros
    if suggested in ("40", "41") and not motivo_cfop:
        hyp.reasons.append(
            "Nota: nao e possivel distinguir entre isencao (040), "
            "nao incidencia (041) ou outras (090) apenas pelos campos numericos. "
            "Verificar enquadramento fiscal da operacao."
        )

    return hyp


def _hyp_sem_st_com_campos(
    item: SpedRecord,
    ctx: dict,
    siblings: list[SpedRecord],
    c190_recs: list[SpedRecord],
) -> CorrectionHypothesis:
    """CST sem ST mas campos de ST preenchidos.

    Base legal: Ajuste SINIEF 03/01, Tabela B:
    - CST 10: tributada com cobranca de ICMS por ST
    - CST 30: isenta/NT com cobranca de ICMS por ST
    - CST 60: ICMS cobrado anteriormente por ST
    - CST 70: com reducao de base e cobranca de ICMS por ST
    """
    cst = ctx["cst"]
    vl_bc = ctx["vl_bc"]
    aliq = ctx["aliq"]
    vl_icms = ctx["vl_icms"]
    vl_bc_st = ctx["vl_bc_st"]
    vl_icms_st = ctx["vl_icms_st"]

    tem_tributacao_propria = vl_bc > TOLERANCE and vl_icms > TOLERANCE
    vl_tributavel = ctx["vl_item"] - ctx["vl_desc"] if ctx["vl_item"] > 0 else 0
    tem_reducao = (
        tem_tributacao_propria
        and vl_tributavel > TOLERANCE
        and vl_bc < vl_tributavel * (1 - _REDUCAO_MIN)
    )

    # Determinar CST com ST mais provavel
    if tem_tributacao_propria and tem_reducao:
        suggested = "70"  # Com reducao + ST
    elif tem_tributacao_propria:
        suggested = "10"  # Tributado + ST
    elif vl_bc <= TOLERANCE and vl_icms <= TOLERANCE:
        suggested = "30"  # Isento/NT + ST
    else:
        suggested = "10"  # Default: tributado + ST

    hyp = CorrectionHypothesis(
        field_name="CST_ICMS",
        current_value=ctx["cst_raw"],
        suggested_value=suggested,
    )

    # Score: campos de ST presentes com CST incompativel
    hyp.score += 30
    hyp.reasons.append(
        f"CST {cst} nao contempla substituicao tributaria, "
        f"mas o item possui VL_BC_ICMS_ST={vl_bc_st:.2f} e VL_ICMS_ST={vl_icms_st:.2f}"
    )

    # Score: coerencia do CST sugerido com tributacao propria
    if suggested == "10" and tem_tributacao_propria:
        hyp.score += 15
        hyp.reasons.append(
            f"Item tem ICMS proprio destacado (BC={vl_bc:.2f}, ICMS={vl_icms:.2f}) "
            f"— compativel com CST 10 (tributado + ST)"
        )
    elif suggested == "30" and not tem_tributacao_propria:
        hyp.score += 15
        hyp.reasons.append(
            "Item sem ICMS proprio — compativel com CST 30 (isento/NT + ST)"
        )
    elif suggested == "70" and tem_reducao:
        hyp.score += 15
        reducao_pct = (1 - vl_bc / vl_tributavel) * 100
        hyp.reasons.append(
            f"Base reduzida em {reducao_pct:.1f}% com ST — compativel com CST 70"
        )

    # Score: CFOP e C190
    _score_cfop(hyp, ctx)
    _score_c190(hyp, item, suggested, c190_recs)
    _score_siblings(hyp, item, suggested, siblings)

    return hyp


def _hyp_integral_com_reducao(
    item: SpedRecord,
    ctx: dict,
    siblings: list[SpedRecord],
    c190_recs: list[SpedRecord],
) -> CorrectionHypothesis:
    """CST 00 (integral) mas base indica reducao significativa.

    Base legal: Ajuste SINIEF 03/01, Tabela B:
    - CST 00: tributada integralmente (base = valor da operacao)
    - CST 20: com reducao de base de calculo
    """
    vl_bc = ctx["vl_bc"]
    vl_item = ctx["vl_item"]
    vl_desc = ctx["vl_desc"]
    aliq = ctx["aliq"]
    reducao_pct = ctx.get("reducao_pct", 0)

    suggested = "20"

    hyp = CorrectionHypothesis(
        field_name="CST_ICMS",
        current_value=ctx["cst_raw"],
        suggested_value=suggested,
    )

    vl_tributavel = vl_item - vl_desc

    # Score: evidencia de reducao
    hyp.score += 25
    hyp.reasons.append(
        f"CST 00 indica tributacao integral, mas VL_BC_ICMS ({vl_bc:.2f}) "
        f"e {reducao_pct * 100:.1f}% menor que o valor tributavel "
        f"({vl_tributavel:.2f}), indicando possivel reducao de base"
    )

    # Verificar se a reducao corresponde a um percentual conhecido
    # Reducoes comuns: 33.33%, 41.67%, 29.41%, 52.94%, 58.33%, etc.
    _REDUCOES_CONHECIDAS = {
        29.41: "carga efetiva ~12% sobre base de 17%",
        33.33: "carga efetiva ~12% sobre base de 18%",
        41.67: "carga efetiva ~10% sobre base de 17%",
        52.94: "carga efetiva ~8% sobre base de 17%",
        58.33: "carga efetiva ~7.5% sobre base de 18%",
        61.11: "carga efetiva ~7% sobre base de 18%",
    }

    reducao_100 = reducao_pct * 100
    for red_conhecida, descricao in _REDUCOES_CONHECIDAS.items():
        if abs(reducao_100 - red_conhecida) <= 2.0:
            hyp.score += 15
            hyp.reasons.append(
                f"Reducao de {reducao_100:.1f}% compativel com percentual "
                f"conhecido ({descricao})"
            )
            break

    # Score: CFOP e cruzamentos
    _score_cfop(hyp, ctx)
    _score_c190(hyp, item, suggested, c190_recs)
    _score_siblings(hyp, item, suggested, siblings)

    return hyp


# ──────────────────────────────────────────────
# Scoring helpers (compartilhados entre hipoteses)
# ──────────────────────────────────────────────

def _score_cfop(hyp: CorrectionHypothesis, ctx: dict) -> None:
    """Pontua compatibilidade entre CFOP e CST sugerido."""
    cfop = ctx["cfop"]
    suggested = hyp.suggested_value

    if not cfop:
        return

    # CFOP de venda/devolucao + CST tributado = coerente
    from .helpers import CFOP_VENDA, CFOP_DEVOLUCAO
    if cfop in CFOP_VENDA | CFOP_DEVOLUCAO:
        if suggested in ("00", "10", "20", "70"):
            hyp.score += 20
            hyp.reasons.append(
                f"CFOP {cfop} (venda/devolucao) compativel com CST {suggested}"
            )
        elif suggested in ("40", "41"):
            # Venda com isencao e possivel, mas incomum
            hyp.score += 5
            hyp.reasons.append(
                f"CFOP {cfop} e de venda — isencao possivel mas requer "
                f"verificacao do fundamento legal"
            )

    # CFOP de exportacao + CST isento/NT = coerente
    if cfop in CFOP_EXPORTACAO:
        if suggested in ("40", "41"):
            hyp.score += 20
            hyp.reasons.append(
                f"CFOP {cfop} (exportacao) compativel com CST {suggested} (nao incidencia)"
            )


def _score_c190(
    hyp: CorrectionHypothesis,
    item: SpedRecord,
    suggested_cst: str,
    c190_recs: list[SpedRecord],
) -> None:
    """Pontua confirmacao do CST sugerido pelo C190."""
    cfop_item = get_field(item, F_C170_CFOP)

    for c190 in c190_recs:
        c190_cst = trib(get_field(c190, F_C190_CST))
        c190_cfop = get_field(c190, F_C190_CFOP)

        if c190_cfop != cfop_item:
            continue

        if c190_cst == suggested_cst:
            hyp.score += 20
            hyp.reasons.append(
                f"C190 (CFOP={c190_cfop}) utiliza CST {c190_cst} — confirma sugestao"
            )
            return
        elif c190_cst == trib(hyp.current_value):
            # C190 usa o mesmo CST que o item (errado tambem?)
            hyp.score += 5
            hyp.reasons.append(
                f"C190 (CFOP={c190_cfop}) tambem usa CST {c190_cst} "
                f"— possivel inconsistencia propagada"
            )
            return


def _score_siblings(
    hyp: CorrectionHypothesis,
    item: SpedRecord,
    suggested_cst: str,
    siblings: list[SpedRecord],
) -> None:
    """Pontua se itens irmaos do mesmo documento usam o CST sugerido."""
    cfop_item = get_field(item, F_C170_CFOP)
    siblings_same = 0
    siblings_checked = 0

    for sib in siblings:
        if sib.line_number == item.line_number:
            continue

        sib_cfop = get_field(sib, F_C170_CFOP)
        if sib_cfop != cfop_item:
            continue

        siblings_checked += 1
        sib_cst = trib(get_field(sib, F_C170_CST_ICMS))
        if sib_cst == suggested_cst:
            siblings_same += 1

    if siblings_checked > 0 and siblings_same == siblings_checked:
        hyp.score += 10
        hyp.reasons.append(
            f"Todos os {siblings_checked} itens irmaos com CFOP {cfop_item} "
            f"usam CST {suggested_cst}"
        )
    elif siblings_same > 0:
        hyp.score += 5
        hyp.reasons.append(
            f"{siblings_same} de {siblings_checked} itens irmaos com "
            f"CFOP {cfop_item} usam CST {suggested_cst}"
        )


# ──────────────────────────────────────────────
# Conversao para ValidationError
# ──────────────────────────────────────────────

_INCOMPAT_LABELS = {
    _ISENTO_COM_TRIBUTO: "CST de isencao/nao tributacao com ICMS destacado",
    _TRIBUTADO_SEM_TRIBUTO: "CST de tributacao integral sem destaque de ICMS",
    _SEM_ST_COM_CAMPOS_ST: "CST sem ST com campos de ST preenchidos",
    _INTEGRAL_COM_REDUCAO: "CST integral com evidencia de reducao de base",
}

# Mapeamento de CST para descricao legivel
_CST_DESCRICAO = {
    "00": "Tributada integralmente",
    "10": "Tributada com cobranca de ICMS por ST",
    "20": "Com reducao de base de calculo",
    "30": "Isenta/nao tributada com cobranca de ICMS por ST",
    "40": "Isenta",
    "41": "Nao tributada",
    "50": "Com suspensao",
    "51": "Com diferimento",
    "60": "ICMS cobrado anteriormente por ST",
    "70": "Com reducao de base e cobranca de ICMS por ST",
    "90": "Outras",
}


def _hypothesis_to_error(
    record: SpedRecord,
    hyp: CorrectionHypothesis,
    incompat_type: str,
) -> ValidationError:
    """Converte hipotese de CST em ValidationError com mensagem explicativa."""
    label = _INCOMPAT_LABELS.get(incompat_type, "CST incompativel")
    descr = _CST_DESCRICAO.get(hyp.suggested_value, "")

    parts = [
        f"{label}.",
        f"CST informado: {hyp.current_value}.",
        f"CST sugerido: {hyp.suggested_value} ({descr}).",
        f"Confianca: {hyp.confidence} ({hyp.score} pontos).",
    ]

    for reason in hyp.reasons:
        parts.append(f"- {reason}")

    suggested = hyp.suggested_value if hyp.auto_correctable else None

    return make_error(
        record,
        "CST_ICMS",
        "CST_HIPOTESE",
        " ".join(parts[:4]) + "\n" + "\n".join(parts[4:]),
        field_no=F_C170_CST_ICMS + 1,  # 1-based para o usuario
        value=hyp.current_value,
        expected_value=suggested,
    )
