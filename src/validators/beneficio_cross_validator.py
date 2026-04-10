"""Validador de cruzamento: benefícios fiscais (JSON) x cliente (MySQL) x SPED.

Fase 2: regras determinísticas CROSS_004 a CROSS_010.
Só dispara quando ctx.beneficios_ativos está populado.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import SpedRecord, ValidationError
from ..parser import group_by_register
from .helpers import (
    CFOP_EXPORTACAO,
    F_C170_CFOP,
    F_C170_CST_ICMS,
    F_C170_VL_ICMS,
    F_E110_VL_SLD_CREDOR_TRANSPORTAR,
    F_E110_VL_TOT_CREDITOS,
    F_E110_VL_TOT_DEBITOS,
    F_E111_COD_AJ_APUR,
    F_E111_DESCR_COMPL,
    F_E111_VL_AJ_APUR,
    get_field,
    make_generic_error,
    to_float,
    trib,
)

if TYPE_CHECKING:
    from ..services.context_builder import ValidationContext
    from ..services.reference_loader import BeneficioProfile


# ──────────────────────────────────────────────
# Palavras-chave por benefício para identificar E111
# ──────────────────────────────────────────────

_KW_POR_BENEFICIO: dict[str, tuple[str, ...]] = {
    "FUNDAP": ("fundap",),
    "COMPETE_ATACADISTA": ("compete", "atacadista", "380-8"),
    "COMPETE_VAREJISTA_ECOMMERCE": ("compete", "ecommerce", "e-commerce", "varejista", "385-9"),
    "COMPETE_IND_GRAFICAS": ("compete", "grafica", "gráfica", "938-5"),
    "COMPETE_IND_PAPELAO_MAT_PLAST": ("compete", "papelao", "papelão", "plastico", "plástico", "938-5"),
    "INVEST_ES_INDUSTRIA": ("invest", "indústria", "industria"),
    "INVEST_ES_IMPORTACAO": ("invest", "importa"),
    "SUBSTITUICAO_TRIBUTARIA_ES": ("substituicao", "substituição", "icms-st", "icms st"),
}

# Palavras genéricas de benefício fiscal
_KW_BENEFICIO_GERAL = (
    "beneficio", "benefício", "presumido", "reducao", "redução",
    "diferimento", "incentivo", "isencao", "isenção", "outorgado",
)


def _e111_relaciona_beneficio(record: SpedRecord, perfil: BeneficioProfile) -> bool:
    """Verifica se um E111 está relacionado a um benefício específico."""
    descr = get_field(record, F_E111_DESCR_COMPL).lower()
    cod_aj = get_field(record, F_E111_COD_AJ_APUR).lower()

    # 1. Palavras-chave específicas do benefício
    kws = _KW_POR_BENEFICIO.get(perfil.codigo, ())
    if kws and any(kw in descr or kw in cod_aj for kw in kws):
        return True

    # 2. Código de receita na descrição
    for cod_receita in perfil.codigos_receita.values():
        if cod_receita and cod_receita in descr:
            return True

    # 3. Palavras genéricas + natureza do código de ajuste
    cod_aj_raw = get_field(record, F_E111_COD_AJ_APUR)
    tem_natureza_beneficio = len(cod_aj_raw) >= 4 and cod_aj_raw[3] in ("2", "4")
    if tem_natureza_beneficio and any(kw in descr for kw in _KW_BENEFICIO_GERAL):
        return True

    return False


def _encontrar_e111_do_beneficio(
    e111_records: list[SpedRecord],
    perfil: BeneficioProfile,
) -> list[SpedRecord]:
    """Filtra E111 que estão relacionados a um benefício específico."""
    return [r for r in e111_records if _e111_relaciona_beneficio(r, perfil)]


# ──────────────────────────────────────────────
# API pública
# ──────────────────────────────────────────────

def validate_beneficio_cross(
    records: list[SpedRecord],
    context: ValidationContext | None = None,
) -> list[ValidationError]:
    """Cruzamento benefícios fiscais (JSON) x cliente x SPED.

    Só executa quando há benefícios ativos resolvidos no contexto.
    """
    if not context or not context.beneficios_ativos:
        return []

    groups = group_by_register(records)
    errors: list[ValidationError] = []
    e111_all = groups.get("E111", [])
    e116_all = groups.get("E116", [])

    for perfil in context.beneficios_ativos:
        errors.extend(_check_cross_004a(e111_all, perfil))
        errors.extend(_check_cross_004b(e116_all, perfil))
        errors.extend(_check_cross_005(groups, e111_all, perfil))
        errors.extend(_check_cross_008(groups, e111_all, perfil))
        errors.extend(_check_cross_009(groups, perfil))
        errors.extend(_check_cross_010(groups, perfil))

    # Regras inter-benefício
    errors.extend(_check_cross_006(groups, e111_all, context.beneficios_ativos))
    errors.extend(_check_cross_007(e111_all, context.beneficios_ativos))

    return errors


# ──────────────────────────────────────────────
# CROSS_004a — Ajuste segregado ausente
# ──────────────────────────────────────────────

def _check_cross_004a(
    e111_all: list[SpedRecord],
    perfil: BeneficioProfile,
) -> list[ValidationError]:
    """CROSS_004a: benefício com apuração segregada obrigatória sem E111 relacionado."""
    if not perfil.apuracao_segregada:
        return []

    relacionados = _encontrar_e111_do_beneficio(e111_all, perfil)
    if relacionados:
        return []

    return [make_generic_error(
        "BENE_CROSS_APURACAO_NAO_SEGREGADA",
        (
            f"Beneficio {perfil.nome} ({perfil.codigo}) exige apuracao segregada, "
            f"mas nenhum ajuste E111 relacionado foi encontrado no arquivo. "
            f"Registros afetados esperados: {', '.join(perfil.registros_afetados)}."
        ),
        register="E111",
    )]


# ──────────────────────────────────────────────
# CROSS_004b — Código de receita incorreto
# ──────────────────────────────────────────────

def _check_cross_004b(
    e116_all: list[SpedRecord],
    perfil: BeneficioProfile,
) -> list[ValidationError]:
    """CROSS_004b: recolhimento em código de receita incorreto."""
    if not perfil.codigos_receita:
        return []

    # Sem E116 → não há o que verificar (a ausência de E116 é outro problema)
    if not e116_all:
        return []

    codigos_esperados = set(perfil.codigos_receita.values())

    # Verificar se algum E116 contém um dos códigos esperados na descrição
    # E116: REG|COD_OR|VL_OR|DT_VCTO|COD_REC|NUM_PROC|IND_PROC
    for rec in e116_all:
        cod_rec = rec.fields.get("COD_REC", "").strip()
        if cod_rec in codigos_esperados:
            return []  # Encontrou código correto

    # Se tem E116 mas nenhum com código do benefício → alerta
    return [make_generic_error(
        "BENE_CROSS_CODIGO_RECEITA_INCORRETO",
        (
            f"Beneficio {perfil.nome} ({perfil.codigo}) exige recolhimento com "
            f"codigo(s) de receita {codigos_esperados}, mas nenhum E116 com "
            f"esses codigos foi encontrado."
        ),
        register="E116",
    )]


# ──────────────────────────────────────────────
# CROSS_005 — Estorno de crédito ausente
# ──────────────────────────────────────────────

def _check_cross_005(
    groups: dict[str, list[SpedRecord]],
    e111_all: list[SpedRecord],
    perfil: BeneficioProfile,
) -> list[ValidationError]:
    """CROSS_005: estorno obrigatório ausente."""
    if not perfil.exige_estorno:
        return []

    # INVEST-ES Importação: saldo credor sem exportação → exige estorno
    if perfil.codigo == "INVEST_ES_IMPORTACAO":
        return _check_estorno_invest_importacao(groups, e111_all, perfil)

    # COMPETE Ind. Gráficas: estorno proporcional ao crédito >7%
    if perfil.codigo == "COMPETE_IND_GRAFICAS":
        return _check_estorno_graficas(e111_all, perfil)

    return []


def _check_estorno_invest_importacao(
    groups: dict[str, list[SpedRecord]],
    e111_all: list[SpedRecord],
    perfil: BeneficioProfile,
) -> list[ValidationError]:
    """INVEST-ES Importação: saldo credor fora de exportação → exige estorno (GETRI 010/2024)."""
    e110 = groups.get("E110", [])
    if not e110:
        return []

    sld_credor = to_float(get_field(e110[0], F_E110_VL_SLD_CREDOR_TRANSPORTAR))
    if sld_credor <= 0:
        return []  # Sem saldo credor → OK

    # Verificar se tem exportação (CFOP 7xxx) que justifique o saldo credor
    c190_all = groups.get("C190", [])
    tem_exportacao = any(
        get_field(r, "CFOP").startswith("7") for r in c190_all
    )

    if tem_exportacao:
        return []  # Exportação pode justificar saldo credor

    # Verificar se tem E111 de estorno
    for rec in e111_all:
        descr = get_field(rec, F_E111_DESCR_COMPL).lower()
        cod_aj = get_field(rec, F_E111_COD_AJ_APUR)
        # Estorno: natureza débito ([3]=0 ou [3]=1) com palavras de estorno
        if len(cod_aj) >= 4 and cod_aj[3] in ("0", "1"):
            if any(kw in descr for kw in ("estorno", "invest", "importa")):
                return []

    return [make_generic_error(
        "BENE_CROSS_ESTORNO_AUSENTE",
        (
            f"INVEST-ES Importacao: saldo credor de R$ {sld_credor:,.2f} transportado "
            f"sem exportacao (CFOP 7xxx) e sem estorno em E111. "
            f"Conforme GETRI 010/2024, saldo credor fora das hipoteses legais "
            f"deve ser estornado."
        ),
        register="E110",
    )]


def _check_estorno_graficas(
    e111_all: list[SpedRecord],
    perfil: BeneficioProfile,
) -> list[ValidationError]:
    """COMPETE Ind. Gráficas: estorno proporcional crédito entrada >7% (§único Art. 10)."""
    # Verificar se existe E111 de estorno (ajuste de débito)
    for rec in e111_all:
        descr = get_field(rec, F_E111_DESCR_COMPL).lower()
        cod_aj = get_field(rec, F_E111_COD_AJ_APUR)
        # Estorno de crédito: ajuste a débito
        if len(cod_aj) >= 4 and cod_aj[3] in ("0", "1"):
            if any(kw in descr for kw in ("estorno", "compete", "grafica", "gráfica", "proporcional")):
                return []

    # Se tem E111 de benefício gráficas mas sem estorno → alerta
    relacionados = _encontrar_e111_do_beneficio(e111_all, perfil)
    if not relacionados:
        return []  # Sem ajuste de benefício → CROSS_004a já cobre

    return [make_generic_error(
        "BENE_CROSS_ESTORNO_AUSENTE",
        (
            f"COMPETE Ind. Graficas: ajuste de beneficio encontrado em E111, "
            f"mas sem estorno proporcional do credito de entrada excedente a 7%. "
            f"Conforme par. unico Art. 10 Lei 10.568/2016, o estorno e obrigatorio."
        ),
        register="E111",
    )]


# ──────────────────────────────────────────────
# CROSS_006 — Cumulação vedada entre benefícios
# ──────────────────────────────────────────────

# Pares de benefícios com vedação de cumulação na mesma operação
_PARES_VEDADOS: list[tuple[str, str]] = [
    ("FUNDAP", "COMPETE_ATACADISTA"),
    ("INVEST_ES_INDUSTRIA", "COMPETE_ATACADISTA"),
    ("INVEST_ES_INDUSTRIA", "COMPETE_IND_GRAFICAS"),
    ("INVEST_ES_INDUSTRIA", "COMPETE_IND_PAPELAO_MAT_PLAST"),
    ("INVEST_ES_INDUSTRIA", "COMPETE_VAREJISTA_ECOMMERCE"),
    ("INVEST_ES_IMPORTACAO", "COMPETE_ATACADISTA"),
    ("INVEST_ES_IMPORTACAO", "COMPETE_IND_GRAFICAS"),
    ("INVEST_ES_IMPORTACAO", "COMPETE_IND_PAPELAO_MAT_PLAST"),
    ("INVEST_ES_IMPORTACAO", "COMPETE_VAREJISTA_ECOMMERCE"),
]


def _check_cross_006(
    groups: dict[str, list[SpedRecord]],
    e111_all: list[SpedRecord],
    beneficios: list[BeneficioProfile],
) -> list[ValidationError]:
    """CROSS_006: cumulação vedada entre benefícios."""
    errors: list[ValidationError] = []
    codigos_ativos = {b.codigo for b in beneficios}

    for cod_a, cod_b in _PARES_VEDADOS:
        if cod_a not in codigos_ativos or cod_b not in codigos_ativos:
            continue

        perfil_a = next(b for b in beneficios if b.codigo == cod_a)
        perfil_b = next(b for b in beneficios if b.codigo == cod_b)

        # Nível período: verificar se ambos têm E111 no mesmo arquivo
        e111_a = _encontrar_e111_do_beneficio(e111_all, perfil_a)
        e111_b = _encontrar_e111_do_beneficio(e111_all, perfil_b)

        if e111_a and e111_b:
            # Ambos têm ajuste no período — alerta (podem ser operações distintas)
            errors.append(make_generic_error(
                "BENE_CROSS_CUMULACAO_VEDADA_PERIODO",
                (
                    f"Beneficios {perfil_a.nome} e {perfil_b.nome} ambos possuem "
                    f"ajustes em E111 no mesmo periodo de apuracao. "
                    f"Coexistencia admitida somente em operacoes distintas — "
                    f"verificar segregacao."
                ),
                register="E111",
            ))

        # Nível documento (FUNDAP + COMPETE): verificar C100 com mistura
        if cod_a == "FUNDAP" or cod_b == "FUNDAP":
            errors.extend(_check_cumulacao_documento(groups, perfil_a, perfil_b))

    return errors


def _check_cumulacao_documento(
    groups: dict[str, list[SpedRecord]],
    perfil_a: BeneficioProfile,
    perfil_b: BeneficioProfile,
) -> list[ValidationError]:
    """Verifica cumulação no nível documento — analisa C190 por coerência CFOP+CST.

    C190 já é um consolidado por documento/CST/CFOP, então se ambos os perfis
    aparecem com sinais de fruição no mesmo arquivo, é um indicativo forte.
    SpedRecord não tem parent_id, então usamos C190 como proxy.
    """
    cfops_a = perfil_a.cfops
    cfops_b = perfil_b.cfops
    csts_a = perfil_a.csts
    csts_b = perfil_b.csts

    tem_sinal_a = False
    tem_sinal_b = False

    for rec in groups.get("C190", []):
        cfop = get_field(rec, "CFOP")
        cst = trib(get_field(rec, "CST_ICMS"))

        if cfop in cfops_a and cst in csts_a:
            tem_sinal_a = True
        if cfop in cfops_b and cst in csts_b:
            tem_sinal_b = True

    if tem_sinal_a and tem_sinal_b:
        return [make_generic_error(
            "BENE_CROSS_CUMULACAO_VEDADA_DOCUMENTO",
            (
                f"Arquivo contem operacoes com sinais de fruicao de "
                f"{perfil_a.nome} (CFOPs {sorted(cfops_a)}, CSTs {sorted(csts_a)}) e "
                f"{perfil_b.nome} (CFOPs {sorted(cfops_b)}, CSTs {sorted(csts_b)}) "
                f"simultaneamente. Cumulacao vedada na mesma operacao — verificar "
                f"se os beneficios estao aplicados em operacoes distintas."
            ),
            register="C190",
        )]

    return []


# ──────────────────────────────────────────────
# CROSS_007 — Limite de crédito de entrada (alerta)
# ──────────────────────────────────────────────

def _check_cross_007(
    e111_all: list[SpedRecord],
    beneficios: list[BeneficioProfile],
) -> list[ValidationError]:
    """CROSS_007: limite de crédito de entrada sem estorno aparente (alerta, não erro)."""
    errors: list[ValidationError] = []

    for perfil in beneficios:
        if not perfil.limite_credito_entrada:
            continue

        # Tem benefício com limite de crédito → verificar se há E111 de estorno
        relacionados = _encontrar_e111_do_beneficio(e111_all, perfil)
        if not relacionados:
            continue  # CROSS_004a já cobre a ausência total

        # Verificar se algum E111 indica estorno de crédito
        tem_estorno = False
        for rec in e111_all:
            descr = get_field(rec, F_E111_DESCR_COMPL).lower()
            cod_aj = get_field(rec, F_E111_COD_AJ_APUR)
            if len(cod_aj) >= 4 and cod_aj[3] in ("0", "1"):
                if any(kw in descr for kw in ("estorno", "limite", "7%", "credito")):
                    tem_estorno = True
                    break

        if not tem_estorno:
            errors.append(make_generic_error(
                "BENE_CROSS_CREDITO_ENTRADA_ALERTA",
                (
                    f"Beneficio {perfil.nome} tem limite de credito de entrada de "
                    f"{perfil.limite_credito_entrada}, mas nenhum ajuste de estorno "
                    f"foi identificado em E111. Verificar se o credito de entrada "
                    f"excedente esta sendo corretamente estornado."
                ),
                register="E111",
            ))

    return errors


# ──────────────────────────────────────────────
# CROSS_008 — Crédito presumido sobre base incorreta (INVEST-ES Indústria)
# ──────────────────────────────────────────────

def _check_cross_008(
    groups: dict[str, list[SpedRecord]],
    e111_all: list[SpedRecord],
    perfil: BeneficioProfile,
) -> list[ValidationError]:
    """CROSS_008: crédito presumido > 70% do ICMS efetivamente apurado."""
    if perfil.codigo != "INVEST_ES_INDUSTRIA":
        return []
    if "credito_presumido" not in perfil.tipo_beneficio:
        return []

    e110 = groups.get("E110", [])
    if not e110:
        return []

    vl_debitos = to_float(get_field(e110[0], F_E110_VL_TOT_DEBITOS))
    vl_creditos = to_float(get_field(e110[0], F_E110_VL_TOT_CREDITOS))
    icms_apurado = vl_debitos - vl_creditos

    if icms_apurado <= 0:
        return []  # Sem ICMS a pagar → crédito presumido não se aplica

    # Somar E111 de crédito presumido relacionados ao INVEST
    total_presumido = 0.0
    for rec in e111_all:
        if not _e111_relaciona_beneficio(rec, perfil):
            continue
        cod_aj = get_field(rec, F_E111_COD_AJ_APUR)
        # Natureza crédito ([3]=2) ou dedução ([3]=4) → é o benefício
        if len(cod_aj) >= 4 and cod_aj[3] in ("2", "4"):
            total_presumido += abs(to_float(get_field(rec, F_E111_VL_AJ_APUR)))

    if total_presumido <= 0:
        return []

    percentual = (total_presumido / icms_apurado) * 100
    if percentual <= 70.0:
        return []

    return [make_generic_error(
        "BENE_CROSS_CREDITO_PRESUMIDO_BASE_INCORRETA",
        (
            f"INVEST-ES Industria: credito presumido de R$ {total_presumido:,.2f} "
            f"equivale a {percentual:.1f}% do ICMS efetivamente apurado "
            f"(R$ {icms_apurado:,.2f} = debitos - creditos). "
            f"O limite e de 70% (Art. 3 par.6 Lei 10.550/2016, Parecer 884/2024). "
            f"O credito presumido deve incidir sobre o ICMS efetivamente apurado "
            f"(debitos menos creditos), nao sobre o debito bruto."
        ),
        register="E111",
    )]


# ──────────────────────────────────────────────
# CROSS_009 — Diferimento de compras internas creditado (INVEST-ES Indústria)
# ──────────────────────────────────────────────

def _check_cross_009(
    groups: dict[str, list[SpedRecord]],
    perfil: BeneficioProfile,
) -> list[ValidationError]:
    """CROSS_009: diferimento de compras internas escriturado como crédito (Parecer 310/2024)."""
    if perfil.codigo != "INVEST_ES_INDUSTRIA":
        return []

    errors: list[ValidationError] = []
    for rec in groups.get("C170", []):
        cfop = get_field(rec, F_C170_CFOP)
        cst = trib(get_field(rec, F_C170_CST_ICMS))
        vl_icms = to_float(get_field(rec, F_C170_VL_ICMS))

        # Compra interna (1xxx) com CST 51 (diferimento) e crédito escriturado
        if cfop.startswith("1") and cst == "51" and vl_icms > 0:
            errors.append(make_generic_error(
                "BENE_CROSS_DIFERIMENTO_CREDITADO",
                (
                    f"INVEST-ES Industria: C170 com CFOP {cfop} (compra interna) "
                    f"e CST 51 (diferimento) tem VL_ICMS={vl_icms:,.2f} escriturado "
                    f"como credito. Diferimento nao gera direito a credito "
                    f"(Parecer 310/2024)."
                ),
                register="C170",
            ))

    return errors


# ──────────────────────────────────────────────
# CROSS_010 — NCM não autorizada em diferimento de importação (COMPETE Papelão)
# ──────────────────────────────────────────────

_NCM_POLIMEROS_AUTORIZADOS = ("3901", "3902", "3903")


def _check_cross_010(
    groups: dict[str, list[SpedRecord]],
    perfil: BeneficioProfile,
) -> list[ValidationError]:
    """CROSS_010: diferimento de importação em NCM fora de 3901/3902/3903."""
    if perfil.codigo != "COMPETE_IND_PAPELAO_MAT_PLAST":
        return []

    errors: list[ValidationError] = []
    # Buscar NCM dos itens via 0200 (cache de produtos no contexto seria melhor,
    # mas aqui usamos os registros diretamente)
    ncm_por_item: dict[str, str] = {}
    for rec in groups.get("0200", []):
        cod_item = rec.fields.get("COD_ITEM", "").strip()
        ncm = rec.fields.get("COD_NCM", "").strip()
        if cod_item:
            ncm_por_item[cod_item] = ncm

    for rec in groups.get("C170", []):
        cfop = get_field(rec, F_C170_CFOP)
        cst = trib(get_field(rec, F_C170_CST_ICMS))

        # Importação (CFOP 3101) com diferimento (CST 51)
        if cfop != "3101" or cst != "51":
            continue

        cod_item = rec.fields.get("COD_ITEM", "").strip()
        ncm = ncm_por_item.get(cod_item, "")

        if not ncm:
            continue

        ncm_4 = ncm[:4]
        if ncm_4 not in _NCM_POLIMEROS_AUTORIZADOS:
            errors.append(make_generic_error(
                "BENE_CROSS_NCM_NAO_AUTORIZADA_DIFERIMENTO",
                (
                    f"COMPETE Ind. Papelao: importacao com diferimento (CFOP 3101, "
                    f"CST 51) para item {cod_item} com NCM {ncm}. "
                    f"Diferimento restrito a polimeros NCM 3901, 3902 e 3903 "
                    f"(Art. 14 III-a Lei 10.568/2016)."
                ),
                register="C170",
            ))

    return errors
