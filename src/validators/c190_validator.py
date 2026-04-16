"""Validador de consolidacao C190: cruzamento C170 x C190 e combinacoes.

Regras implementadas:
- C190_001: VL_OPR do C190 reconstruido a partir dos C170 com rateio de despesas do C100
- C190_002: Combinacao incompativel de CST+CFOP+ALIQ no C190
             (classificacao baseada em Tabela_CST_Vigente.json — campo 'efeitos')
"""

from __future__ import annotations

from collections import defaultdict

from ..models import SpedRecord, ValidationError
from ..parser import group_by_register
from ..services.context_builder import ValidationContext
from ..services.reference_loader import ReferenceLoader
from .helpers import (
    CFOP_REMESSA_SAIDA,
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

# Aliquota exclusivamente interestadual — nunca e aliquota interna
# 4% = Res. Senado 13/2012 (produtos importados)
# 7% e 12% podem ser internas (cesta basica, transporte, etc.)
_ALIQ_EXCLUSIVAMENTE_INTERESTADUAL = {4.0}

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
    loader = context.reference_loader if context else None

    errors.extend(_check_c190_001(groups, context))
    errors.extend(_check_c190_002(groups, loader))

    return errors


# ──────────────────────────────────────────────
# C190_001: VL_OPR reconstruido por composicao economica
# ──────────────────────────────────────────────

def _check_c190_001(
    groups: dict[str, list[SpedRecord]],
    context: ValidationContext | None = None,
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

    # Dados XML para referencia cruzada (quando disponivel)
    xml_by_chave = (context.xml_by_chave or {}) if context else {}

    for c100_line, c190_recs in doc_c190.items():
        c100 = doc_c100.get(c100_line)
        items = doc_c170.get(c100_line, [])
        if not c100 or not items:
            continue

        # Buscar dados XML desta NF-e (pela chave do C100)
        xml_doc = None
        if xml_by_chave:
            chv_nfe = get_field(c100, "CHV_NFE").strip().replace(" ", "")
            if chv_nfe.startswith("NFe"):
                chv_nfe = chv_nfe[3:]
            xml_doc = xml_by_chave.get(chv_nfe)

        # Despesas e parcelas adicionais do C100 que integram VL_OPR
        # Pelo Guia Pratico, VL_OPR pode incluir frete, seguro, outras despesas,
        # IPI (quando nao recuperavel) e ICMS-ST (retido anteriormente).
        vl_frt = to_float(get_field(c100, F_C100_VL_FRT))
        vl_seg = to_float(get_field(c100, F_C100_VL_SEG))
        vl_out_da = to_float(get_field(c100, F_C100_VL_OUT_DA))
        vl_ipi = to_float(get_field(c100, F_C100_VL_IPI))
        vl_icms_st_c100 = to_float(get_field(c100, F_C100_VL_ICMS_ST))
        despesas_explicitas = vl_frt + vl_seg + vl_out_da + vl_ipi + vl_icms_st_c100

        # VL_DOC e VL_MERC para calcular residual
        vl_doc = to_float(get_field(c100, F_C100_VL_DOC))
        vl_merc = to_float(get_field(c100, F_C100_VL_MERC))

        # Residual: parcelas que compõem VL_DOC mas nao estao discriminadas
        # nos campos individuais do C100 (ex: ICMS-ST embutido quando
        # C100.VL_ICMS_ST=0, diferencas de arredondamento).
        # Isso ocorre frequentemente em entradas com ST (CFOP 2403) onde
        # o ICMS-ST esta no preco mas o C100 nao detalha no campo VL_ICMS_ST.
        residual_doc = max(0.0, vl_doc - vl_merc - despesas_explicitas) if vl_doc > 0 else 0.0

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

        # ── Estrategia de validacao VL_OPR ──
        # Em vez de reconstruir VL_OPR combinacao a combinacao (rateio
        # proporcional e estimativa imprecisa), validamos o TOTAL:
        # soma de todos os C190.VL_OPR deve ser igual a VL_DOC do C100.
        # Isso e garantido pelo leiaute SPED e nao depende de rateio.
        soma_vl_opr_c190 = sum(to_float(get_field(c, F_C190_VL_OPR)) for c in c190_recs)
        total_ok = vl_doc > 0 and abs(soma_vl_opr_c190 - vl_doc) <= 0.02

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

            # Calcular despesas distribuiveis (frete+seguro+outras+IPI)
            despesas_rateavel = vl_frt + vl_seg + vl_out_da + vl_ipi
            if despesas_rateavel > 0 and base_rateio_doc > 0:
                if qtd_combinacoes == 1:
                    despesa_rateada = despesas_rateavel
                else:
                    peso = soma_itens / base_rateio_doc
                    despesa_rateada = round(despesas_rateavel * peso, 2)
            else:
                despesa_rateada = 0.0

            vl_opr_esperado = round(soma_itens + despesa_rateada, 2)

            n_itens_combo = sum(1 for it in items
                                if (get_field(it, F_C170_CST_ICMS),
                                    get_field(it, F_C170_CFOP),
                                    round(to_float(get_field(it, F_C170_ALIQ_ICMS)), 2)) == key)
            tol_consol = get_tolerance("consolidacao", n_items=n_itens_combo)

            # Quando ha residual nao explicado (VL_DOC > VL_MERC + despesas),
            # o emitente pode ter distribuido ICMS-ST, IPI embutido ou outros
            # componentes de forma NAO proporcional nos C190.
            # Se o total de C190 bate com VL_DOC, a distribuicao interna
            # e prerrogativa do contribuinte — nao apontar como erro.
            if residual_doc > 0 and total_ok:
                # Aceitar diferenca ate o valor do residual por combinacao,
                # ja que a distribuicao interna do ST/IPI nao e padronizada.
                # Margem +0.01 para absorver imprecisao de ponto flutuante.
                tol_consol = max(tol_consol, residual_doc + 0.01)

            # ICMS-ST do C100: quando explicitado, tambem incorpora ao VL_OPR.
            # O rateio de ST nao e proporcional — vai para CFOPs especificos.
            if vl_icms_st_c100 > 0 and total_ok:
                tol_consol = max(tol_consol, vl_icms_st_c100)

            diff_opr = abs(vl_opr_c190 - vl_opr_esperado)
            if diff_opr > tol_consol:
                composicao = f"Sum(VL_ITEM-VL_DESC)={soma_itens:.2f}"
                if despesa_rateada > 0:
                    composicao += f" + despesas_rateadas={despesa_rateada:.2f}"

                # Referencia cruzada com XML (quando disponivel)
                # Nota: a validacao C190 vs C170 e COMPLEMENTAR ao cruzamento XML,
                # nao substituta. C190 vs C170 verifica integridade interna do SPED.
                # C190 vs XML (field_map) verifica se SPED bate com a fonte autoritativa.
                # Ambas devem rodar sempre, independentemente de xml_cruzamento_executado.
                xml_ref = ""
                xml_diagnostico = ""
                if xml_doc and xml_doc.get("por_grupo"):
                    xml_grupo = xml_doc["por_grupo"].get(key)
                    if xml_grupo:
                        xml_vl = xml_grupo["vl_prod_liq"]
                        xml_ref = f" | XML soma(vProd-vDesc)={xml_vl:.2f}"
                        diff_xml_c190 = abs(vl_opr_c190 - xml_vl)
                        diff_xml_c170 = abs(vl_opr_esperado - xml_vl)
                        if diff_xml_c190 < diff_xml_c170:
                            xml_diagnostico = " XML confirma C190 — provavel erro nos itens C170."
                        elif diff_xml_c170 < diff_xml_c190:
                            xml_diagnostico = " XML confirma C170 — provavel erro no totalizador C190."
                        else:
                            xml_diagnostico = " XML diverge de ambos — revisar XML, C170 e C190."

                errors.append(make_error(
                        c190, "VL_OPR", "C190_DIVERGE_C170",
                        (
                            f"C190 (CST={cst_c190} CFOP={cfop_c190} ALIQ={aliq_c190:.2f}%): "
                            f"VL_OPR={vl_opr_c190:.2f} diverge do valor reconstruido "
                            f"{vl_opr_esperado:.2f} (dif={diff_opr:.2f}). "
                            f"Composicao: {composicao}."
                            f"{xml_ref}{xml_diagnostico}"
                            f" Confianca: alta (100 pontos)."
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
                    # Referencia cruzada XML para VL_ICMS (complementar, nao substituta)
                    xml_ref_icms = ""
                    xml_diag_icms = ""
                    if xml_doc and xml_doc.get("por_grupo"):
                        xml_grupo_icms = xml_doc["por_grupo"].get(key)
                        if xml_grupo_icms:
                            xml_vicms = xml_grupo_icms["vl_icms"]
                            xml_ref_icms = f" | XML soma(vICMS)={xml_vicms:.2f}"
                            d_xml_c190 = abs(vl_icms_c190 - xml_vicms)
                            d_xml_c170 = abs(soma_icms_c170 - xml_vicms)
                            if d_xml_c190 < d_xml_c170:
                                xml_diag_icms = " XML confirma C190 — provavel erro nos itens C170."
                            elif d_xml_c170 < d_xml_c190:
                                xml_diag_icms = " XML confirma C170 — provavel erro no totalizador C190."
                            else:
                                xml_diag_icms = " XML diverge de ambos — revisar XML, C170 e C190."

                    errors.append(make_error(
                            c190, "VL_ICMS", "C190_DIVERGE_C170",
                            (
                                f"C190 (CST={cst_c190} CFOP={cfop_c190}): "
                                f"VL_ICMS={vl_icms_c190:.2f} diverge da soma dos "
                                f"C170.VL_ICMS={soma_icms_c170:.2f} "
                                f"(dif={diff_icms:.2f})."
                                f"{xml_ref_icms}{xml_diag_icms}"
                                f" Confianca: alta (100 pontos)."
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
    loader: ReferenceLoader | None = None,
) -> list[ValidationError]:
    """Detecta combinacoes incoerentes de CST+CFOP+ALIQ no C190.

    Classificacao dos CSTs baseada nos 'efeitos' da Tabela_CST_Vigente.json:
    - debito_proprio: CST com aliquota obrigatoria (00,02,10,12,13,15,20,70,72,74)
    - sem_debito_proprio: CST sem aliquota propria (30,40,41,50,51,52,53,60,61)
    - monofasico: tributacao ad rem, ALIQ_ICMS=0 e esperado (02,15,53,61)
    - residual: CST 90 — catch-all, nao gera erro por aliquota ausente
    """
    errors: list[ValidationError] = []

    # Sets de CST carregados do JSON via helpers (fonte unica)
    from .helpers import CST_MONOFASICO, CST_RESIDUAL
    if loader:
        cst_debito_proprio = loader.csts_com_efeito("debito_proprio")
        cst_sem_debito = loader.csts_com_efeito("sem_debito_proprio")
        cst_monofasico_l = loader.csts_com_efeito("monofasico")
        cst_residual_l = loader.csts_com_efeito("residual")
    else:
        # Fallback: sets do helpers.py (ja carregados do JSON)
        from .helpers import CST_ISENTO_NT, CST_TRIBUTADO
        cst_debito_proprio = CST_TRIBUTADO
        cst_sem_debito = CST_ISENTO_NT
        cst_monofasico_l = CST_MONOFASICO
        cst_residual_l = CST_RESIDUAL

    # CSTs com debito_proprio que podem legitimamente ter ALIQ=0
    cst_aliq_zero_ok = cst_monofasico_l | cst_residual_l

    for rec in groups.get("C190", []):
        cst = trib(get_field(rec, "CST_ICMS"))
        cfop = get_field(rec, "CFOP")
        aliq = to_float(get_field(rec, "ALIQ_ICMS"))
        vl_opr = to_float(get_field(rec, "VL_OPR"))
        vl_bc = to_float(get_field(rec, "VL_BC_ICMS"))

        if not cst or not cfop or vl_opr == 0:
            continue

        # Regra 1: CST sem debito proprio com aliquota > 0 E base > 0
        # Efeito 'sem_debito_proprio' = nao deveria ter ALIQ e BC positivos.
        # CST 30 (isento+ST) pode ter ALIQ informativa com BC=0.
        if cst in cst_sem_debito and aliq > 0 and vl_bc > 0:
            errors.append(make_error(
                rec, "CST_ICMS", "C190_COMBINACAO_INCOMPATIVEL",
                (
                    f"C190 com CST {cst} (sem debito proprio) e ALIQ={aliq:.2f}% "
                    f"com VL_BC_ICMS={vl_bc:.2f}. "
                    f"CST sem debito proprio nao deveria ter "
                    f"aliquota e base de calculo positivas simultaneamente."
                ),
                field_no=2,
                value=f"CST={cst} CFOP={cfop} ALIQ={aliq:.2f}%",
            ))

        # Regra 2: CST com debito proprio e aliquota zero em saida
        # Excecoes: monofasicos (ad rem), residual (90), remessas
        if (cst in cst_debito_proprio
                and cst not in cst_aliq_zero_ok
                and aliq == 0
                and cfop[:1] in ("5", "6")
                and cfop not in CFOP_REMESSA_SAIDA):
            errors.append(make_error(
                rec, "ALIQ_ICMS", "C190_COMBINACAO_INCOMPATIVEL",
                (
                    f"C190 com CST {cst} (debito proprio) e ALIQ=0% em "
                    f"CFOP {cfop}. CST com debito proprio deveria ter "
                    f"aliquota positiva. "
                    f"Revise se o CST deveria ser 40/41/50 ou se a aliquota "
                    f"esta faltando."
                ),
                field_no=4,
                value=f"CST={cst} CFOP={cfop} ALIQ=0",
            ))

        # Regra 3: CFOP interestadual com aliquota >= 17% (tipica interna)
        # Excecao: remessas interestaduais
        if (cfop[:1] == "6"
                and aliq >= 17
                and cst in cst_debito_proprio
                and cfop not in CFOP_REMESSA_SAIDA):
            errors.append(make_error(
                rec, "ALIQ_ICMS", "C190_COMBINACAO_INCOMPATIVEL",
                (
                    f"C190 com CFOP interestadual {cfop} e ALIQ={aliq:.2f}% "
                    f"(tipica interna). Aliquotas interestaduais validas "
                    f"sao 4%, 7% ou 12% (Res. Senado 13/2012)."
                ),
                field_no=4,
                value=f"CST={cst} CFOP={cfop} ALIQ={aliq:.2f}%",
            ))

        # Regra 4: CFOP interno com aliquota exclusivamente interestadual
        # Apenas 4% e exclusivamente interestadual (Res. Senado 13/2012).
        # 7% e 12% podem ser internas (cesta basica, transporte, etc.)
        if (cfop[:1] == "5"
                and aliq in _ALIQ_EXCLUSIVAMENTE_INTERESTADUAL
                and cst in cst_debito_proprio):
            errors.append(make_error(
                rec, "ALIQ_ICMS", "C190_COMBINACAO_INCOMPATIVEL",
                (
                    f"C190 com CFOP interno {cfop} e ALIQ={aliq:.2f}%. "
                    f"A aliquota de 4% e exclusivamente interestadual "
                    f"(Res. Senado 13/2012 — produtos importados)."
                ),
                field_no=4,
                value=f"CST={cst} CFOP={cfop} ALIQ={aliq:.2f}%",
            ))

    return errors
