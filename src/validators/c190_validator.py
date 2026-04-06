"""Validador de consolidacao C190: cruzamento C170 x C190 e combinacoes.

Regras implementadas:
- C190_001: VL_OPR do C190 reconstruido a partir dos C170 com rateio de despesas do C100
- C190_002: Combinacao incompativel de CST+CFOP+ALIQ no C190
"""

from __future__ import annotations

from collections import defaultdict

from ..models import SpedRecord, ValidationError
from ..parser import group_by_register
from ..services.context_builder import ValidationContext
from .helpers import (
    ALIQ_INTERESTADUAIS,
    CFOP_REMESSA_SAIDA,
    CST_ISENTO_NT,
    CST_TRIBUTADO,
    F_C100_VL_DOC,
    F_C100_VL_FRT,
    F_C100_VL_ICMS_ST,
    F_C100_VL_IPI,
    F_C100_VL_MERC,
    F_C100_VL_OUT_DA,
    F_C100_VL_SEG,
    F_C170_ALIQ_ICMS,
    F_C170_CFOP,
    F_C170_CST_ICMS,
    F_C170_VL_BC_ICMS,
    F_C170_VL_DESC,
    F_C170_VL_ICMS,
    F_C170_VL_ITEM,
    F_C190_ALIQ,
    F_C190_CFOP,
    F_C190_CST,
    F_C190_VL_BC,
    F_C190_VL_ICMS,
    F_C190_VL_OPR,
    get_field,
    make_error,
    to_float,
    trib,
)
from .tolerance import get_tolerance

# ──────────────────────────────────────────────
# API publica
# ──────────────────────────────────────────────

def validate_c190(
    records: list[SpedRecord],
    context: ValidationContext | None = None,
) -> list[ValidationError]:
    """Executa validacoes de consolidacao C190."""
    groups = group_by_register(records)
    errors: list[ValidationError] = []

    errors.extend(_check_c190_001(groups))
    errors.extend(_check_c190_002(groups))

    return errors


# ──────────────────────────────────────────────
# C190_001: VL_OPR reconstruido por composicao economica
# ──────────────────────────────────────────────

def _check_c190_001(
    groups: dict[str, list[SpedRecord]],
) -> list[ValidationError]:
    """Reconstroi VL_OPR do C190 a partir dos C170 + rateio de despesas do C100.

    Para cada C190 dentro de um C100:
    1. Soma liquida dos itens C170 da mesma combinacao (CST+CFOP+ALIQ):
       SOMA_ITENS = Sum(VL_ITEM - VL_DESC)
    2. Calcula base total liquida do documento para rateio:
       BASE_RATEIO = Sum(VL_ITEM - VL_DESC) de todos os C170 do C100
    3. Rateia frete, seguro e outras despesas do C100 proporcionalmente
    4. VL_OPR_ESPERADO = SOMA_ITENS + rateio de despesas
    5. Compara com C190.VL_OPR (tolerancia 0.02)
    """
    errors: list[ValidationError] = []

    # Ordenar todos os registros C por linha para agrupar por documento
    all_recs = []
    for reg_type in ("C100", "C170", "C190"):
        for r in groups.get(reg_type, []):
            all_recs.append(r)
    all_recs.sort(key=lambda r: r.line_number)

    # Agrupar por documento C100
    current_c100: SpedRecord | None = None
    doc_c100: dict[int, SpedRecord] = {}
    doc_c170: dict[int, list[SpedRecord]] = defaultdict(list)
    doc_c190: dict[int, list[SpedRecord]] = defaultdict(list)

    for r in all_recs:
        if r.register == "C100":
            current_c100 = r
            doc_c100[r.line_number] = r
        elif r.register == "C170" and current_c100 is not None:
            doc_c170[current_c100.line_number].append(r)
        elif r.register == "C190" and current_c100 is not None:
            doc_c190[current_c100.line_number].append(r)

    for c100_line, c190_recs in doc_c190.items():
        c100 = doc_c100.get(c100_line)
        items = doc_c170.get(c100_line, [])
        if not c100 or not items:
            continue

        # Despesas e parcelas adicionais do C100 que integram VL_OPR
        # Pelo Guia Pratico, VL_OPR pode incluir frete, seguro, outras despesas,
        # IPI (quando nao recuperavel) e ICMS-ST (retido anteriormente).
        vl_frt = to_float(get_field(c100, F_C100_VL_FRT))
        vl_seg = to_float(get_field(c100, F_C100_VL_SEG))
        vl_out_da = to_float(get_field(c100, F_C100_VL_OUT_DA))
        vl_ipi = to_float(get_field(c100, F_C100_VL_IPI))
        vl_icms_st = to_float(get_field(c100, F_C100_VL_ICMS_ST))
        despesas_explicitas = vl_frt + vl_seg + vl_out_da + vl_ipi + vl_icms_st

        # Residual: parcelas que compõem VL_DOC mas nao estao discriminadas
        # (ex: ICMS-ST embutido no preco em CST 060, diferenças de arredondamento)
        vl_doc = to_float(get_field(c100, F_C100_VL_DOC))
        vl_merc = to_float(get_field(c100, F_C100_VL_MERC))
        residual_doc = max(0.0, vl_doc - vl_merc - despesas_explicitas) if vl_doc > 0 else 0.0
        despesas_comuns = despesas_explicitas + residual_doc

        # Base total liquida do documento para rateio
        base_rateio_doc = 0.0
        for it in items:
            vl_item = to_float(get_field(it, F_C170_VL_ITEM))
            vl_desc = to_float(get_field(it, F_C170_VL_DESC))
            base_rateio_doc += max(0.0, vl_item - vl_desc)

        # Somar C170 por combinacao analitica (CST+CFOP+ALIQ)
        # Usa CST completo (3 digitos) para nao colapsar origens diferentes
        # (ex: 090 vs 290 devem ser combinacoes distintas)
        c170_vl_liq: dict[tuple[str, str, float], float] = defaultdict(float)
        c170_vl_icms: dict[tuple[str, str, float], float] = defaultdict(float)
        c170_vl_bc: dict[tuple[str, str, float], float] = defaultdict(float)
        for it in items:
            cst = get_field(it, F_C170_CST_ICMS)
            cfop = get_field(it, F_C170_CFOP)
            aliq = round(to_float(get_field(it, F_C170_ALIQ_ICMS)), 2)
            vl_item = to_float(get_field(it, F_C170_VL_ITEM))
            vl_desc = to_float(get_field(it, F_C170_VL_DESC))
            key = (cst, cfop, aliq)
            c170_vl_liq[key] += max(0.0, vl_item - vl_desc)
            c170_vl_icms[key] += to_float(get_field(it, F_C170_VL_ICMS))
            c170_vl_bc[key] += to_float(get_field(it, F_C170_VL_BC_ICMS))

        qtd_combinacoes = len(c170_vl_liq)

        # Validar cada C190
        for c190 in c190_recs:
            cst_c190 = get_field(c190, F_C190_CST)
            cfop_c190 = get_field(c190, F_C190_CFOP)
            aliq_c190 = round(to_float(get_field(c190, F_C190_ALIQ)), 2)
            vl_opr_c190 = to_float(get_field(c190, F_C190_VL_OPR))
            _vl_bc_c190 = to_float(get_field(c190, F_C190_VL_BC))
            vl_icms_c190 = to_float(get_field(c190, F_C190_VL_ICMS))

            # -- Validacao 1: VL_OPR por reconstrucao com rateio --
            key = (cst_c190, cfop_c190, aliq_c190)
            soma_itens = c170_vl_liq.get(key, 0.0)

            if soma_itens == 0.0 and vl_opr_c190 > 0:
                # Combinacao no C190 sem itens C170 correspondentes
                continue

            # Calcular rateio de despesas comuns
            if despesas_comuns > 0 and base_rateio_doc > 0:
                if qtd_combinacoes == 1:
                    # Unica combinacao: 100% das despesas
                    despesa_rateada = despesas_comuns
                else:
                    # Multiplas combinacoes: rateio proporcional
                    peso = soma_itens / base_rateio_doc
                    despesa_rateada = round(despesas_comuns * peso, 2)
            else:
                despesa_rateada = 0.0

            vl_opr_esperado = round(soma_itens + despesa_rateada, 2)

            n_itens_combo = sum(1 for it in items
                                if (get_field(it, F_C170_CST_ICMS),
                                    get_field(it, F_C170_CFOP),
                                    round(to_float(get_field(it, F_C170_ALIQ_ICMS)), 2)) == key)
            tol_consol = get_tolerance("consolidacao", n_items=n_itens_combo)
            diff_opr = abs(vl_opr_c190 - vl_opr_esperado)
            if diff_opr > tol_consol:
                composicao = f"Sum(VL_ITEM-VL_DESC)={soma_itens:.2f}"
                if despesa_rateada > 0:
                    composicao += f" + despesas_rateadas={despesa_rateada:.2f}"

                errors.append(make_error(
                    c190, "VL_OPR", "C190_DIVERGE_C170",
                    (
                        f"C190 (CST={cst_c190} CFOP={cfop_c190} ALIQ={aliq_c190:.2f}%): "
                        f"VL_OPR={vl_opr_c190:.2f} diverge do valor reconstruido "
                        f"{vl_opr_esperado:.2f} (dif={diff_opr:.2f}). "
                        f"Composicao: {composicao}. "
                        f"Confianca: alta (100 pontos)."
                    ),
                    field_no=5,
                    value=f"{vl_opr_c190:.2f}",
                    expected_value=f"{vl_opr_esperado:.2f}",
                ))

            # -- Validacao 2: VL_ICMS do C190 vs soma dos C170.VL_ICMS --
            # Nao recalcular BC x ALIQ pois arredondamento item a item gera
            # centavos de diferenca legitima. A referencia correta e a soma
            # dos VL_ICMS ja arredondados de cada C170.
            soma_icms_c170 = c170_vl_icms.get(key, 0.0)
            if soma_icms_c170 > 0 or vl_icms_c190 > 0:
                diff_icms = abs(soma_icms_c170 - vl_icms_c190)
                if diff_icms > tol_consol:
                    errors.append(make_error(
                        c190, "VL_ICMS", "C190_DIVERGE_C170",
                        (
                            f"C190 (CST={cst_c190} CFOP={cfop_c190}): "
                            f"VL_ICMS={vl_icms_c190:.2f} diverge da soma dos "
                            f"C170.VL_ICMS={soma_icms_c170:.2f} "
                            f"(dif={diff_icms:.2f}). "
                            f"Confianca: alta (100 pontos)."
                        ),
                        field_no=7,
                        value=f"{vl_icms_c190:.2f}",
                        expected_value=f"{soma_icms_c170:.2f}",
                    ))

    return errors


# ──────────────────────────────────────────────
# C190_002: Combinacoes incompativeis
# ──────────────────────────────────────────────

def _check_c190_002(
    groups: dict[str, list[SpedRecord]],
) -> list[ValidationError]:
    """Detecta combinacoes incoerentes de CST+CFOP+ALIQ no C190."""
    errors: list[ValidationError] = []

    for rec in groups.get("C190", []):
        cst = trib(get_field(rec, "CST_ICMS"))
        cfop = get_field(rec, "CFOP")
        aliq = to_float(get_field(rec, "ALIQ_ICMS"))
        vl_opr = to_float(get_field(rec, "VL_OPR"))

        if not cst or not cfop or vl_opr == 0:
            continue

        # Regra 1: CST isento/NT com aliquota > 0
        if cst in CST_ISENTO_NT and aliq > 0:
            errors.append(make_error(
                rec, "CST_ICMS", "C190_COMBINACAO_INCOMPATIVEL",
                (
                    f"C190 com CST {cst} (isento/NT) e ALIQ={aliq:.2f}%. "
                    f"CST de isencao ou nao-tributacao nao deveria ter aliquota "
                    f"positiva. Revise a classificacao fiscal dos itens."
                ),
                field_no=2,
                value=f"CST={cst} CFOP={cfop} ALIQ={aliq:.2f}%",
            ))

        # Regra 2: CST tributado com aliquota zero em CFOP de venda (nao remessa)
        if (cst in CST_TRIBUTADO
                and aliq == 0
                and cfop[:1] in ("5", "6")
                and cfop not in CFOP_REMESSA_SAIDA):
            errors.append(make_error(
                rec, "ALIQ_ICMS", "C190_COMBINACAO_INCOMPATIVEL",
                (
                    f"C190 com CST {cst} (tributado) e ALIQ=0% em "
                    f"CFOP {cfop}. CST tributado deveria ter aliquota positiva. "
                    f"Revise se o CST deveria ser 40/41/50 ou se a aliquota "
                    f"esta faltando."
                ),
                field_no=4,
                value=f"CST={cst} CFOP={cfop} ALIQ=0",
            ))

        # Regra 3: CFOP interestadual com aliquota interna
        if cfop[:1] == "6" and aliq >= 17 and cst in CST_TRIBUTADO:
            errors.append(make_error(
                rec, "ALIQ_ICMS", "C190_COMBINACAO_INCOMPATIVEL",
                (
                    f"C190 com CFOP interestadual {cfop} e ALIQ={aliq:.2f}% "
                    f"(tipica interna). Aliquotas interestaduais validas "
                    f"sao 4%, 7% ou 12%."
                ),
                field_no=4,
                value=f"CST={cst} CFOP={cfop} ALIQ={aliq:.2f}%",
            ))

        # Regra 4: CFOP interno com aliquota interestadual
        if (cfop[:1] == "5"
                and aliq in ALIQ_INTERESTADUAIS
                and cst in CST_TRIBUTADO):
            errors.append(make_error(
                rec, "ALIQ_ICMS", "C190_COMBINACAO_INCOMPATIVEL",
                (
                    f"C190 com CFOP interno {cfop} e ALIQ={aliq:.2f}% "
                    f"(tipica interestadual). Operacoes internas geralmente "
                    f"usam aliquotas de 17% a 25%."
                ),
                field_no=4,
                value=f"CST={cst} CFOP={cfop} ALIQ={aliq:.2f}%",
            ))

    return errors
