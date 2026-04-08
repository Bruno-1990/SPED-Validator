"""Validador de CSTs, isencoes e Bloco H (estoque)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import SpedRecord, ValidationError
from ..parser import group_by_register
from .helpers import (
    CFOP_EXPORTACAO,
    CFOP_REMESSA_RETORNO,
    CST_DIFERIMENTO,
    CST_ISENTO_NT,
    CST_TRIBUTADO,
    get_field,
    make_error,
    to_float,
    trib,
)

if TYPE_CHECKING:
    from ..services.context_builder import ValidationContext

# ──────────────────────────────────────────────
# CSTs validos por tipo de imposto (locais)
# ──────────────────────────────────────────────

# ICMS - Tabela A (Origem) + Tabela B (Tributacao)
# Origem: 0-8, Tributacao: 00,10,20,30,40,41,50,51,60,70,90
_CST_ICMS_TRIBUTACAO = {
    "00", "02", "10", "12", "13", "15", "20", "30", "40", "41",
    "50", "51", "52", "53", "60", "61", "70", "72", "74", "90",
}

# ICMS Simples Nacional (CSOSN)
_CSOSN_VALIDOS = {
    "101", "102", "103", "201", "202", "203",
    "300", "400", "500", "900",
}

# CSTs de IPI
_CST_IPI_VALIDOS = {
    "00", "01", "02", "03", "04", "05",
    "49", "50", "51", "52", "53", "54", "55",
    "99",
}

# CSTs de PIS/COFINS
_CST_PIS_COFINS_VALIDOS = {
    "01", "02", "03", "04", "05", "06", "07", "08", "09",
    "49", "50", "51", "52", "53", "54", "55", "56",
    "60", "61", "62", "63", "64", "65", "66", "67",
    "70", "71", "72", "73", "74", "75",
    "98", "99",
}

# CSTs de IPI que indicam tributacao efetiva (exigem BC/aliq/valor)
# 49 (Outras Entradas) e 99 (Outras Saidas) sao residuais e nao exigem valores
_CST_IPI_TRIBUTADO = {"00", "50"}

# CSTs de IPI isentos/NT/imune/suspenso
_CST_IPI_SEM_IMPOSTO = {"02", "03", "04", "05", "52", "53", "54", "55"}


# ──────────────────────────────────────────────
# API publica
# ──────────────────────────────────────────────

def validate_cst_and_exemptions(
    records: list[SpedRecord],
    context: ValidationContext | None = None,
) -> list[ValidationError]:
    """Valida CSTs, consistencia de isencoes e Bloco H.

    Se context.regime == SIMPLES_NACIONAL, pula validações de CST Tabela A
    (CSTs 00-90) pois Simples usa Tabela B (CSTs 101-900).
    """
    groups = group_by_register(records)
    errors: list[ValidationError] = []

    # Detectar se é Simples Nacional
    is_simples = False
    if context is not None:
        from ..services.context_builder import TaxRegime
        is_simples = context.regime == TaxRegime.SIMPLES_NACIONAL

    # Validar CSTs nos C170
    for rec in groups.get("C170", []):
        if not is_simples:
            # Regras de CST Tabela A — só se aplicam ao Regime Normal
            errors.extend(_validate_cst_c170(rec))
            errors.extend(_validate_exemptions_c170(rec))
            errors.extend(_validate_cst020_reducao(rec))
            errors.extend(_validate_cst_tributado_aliq_zero(rec))
            errors.extend(_validate_cst020_aliq_reduzida(rec))
            errors.extend(_validate_diferimento_debito(rec))
        errors.extend(_validate_ipi_cst_campos(rec))

    # Validar Bloco H (estoque) vs cadastro
    errors.extend(_validate_bloco_h(groups))

    return errors


# ──────────────────────────────────────────────
# Validacao de CST nos C170
# ──────────────────────────────────────────────

def _validate_cst_c170(record: SpedRecord) -> list[ValidationError]:
    """Valida se CST_ICMS do C170 e um codigo valido.

    Campos C170 (0-based): 9:CST_ICMS
    O CST pode ter 2 digitos (Tabela B) ou 3 digitos (Origem + Tabela B).
    """
    errors: list[ValidationError] = []
    cst_icms = get_field(record, "CST_ICMS")

    if not cst_icms:
        return errors

    # CST pode ser 3 digitos (origem + tributacao) ou 2 digitos (so tributacao)
    if len(cst_icms) == 3:
        origem = cst_icms[0]
        tributacao = cst_icms[1:]
        # Verificar se e CSOSN (Simples Nacional)
        if cst_icms in _CSOSN_VALIDOS:
            return errors
        # Origem deve ser 0-8
        if origem not in "012345678":
            errors.append(make_error(
                record, "CST_ICMS", "CST_INVALIDO",
                f"Origem do CST ICMS '{origem}' invalida (deve ser 0-8).",
            ))
        if tributacao not in _CST_ICMS_TRIBUTACAO:
            errors.append(make_error(
                record, "CST_ICMS", "CST_INVALIDO",
                f"Tributacao do CST ICMS '{tributacao}' invalida.",
            ))
    elif len(cst_icms) == 2:
        if cst_icms not in _CST_ICMS_TRIBUTACAO:
            errors.append(make_error(
                record, "CST_ICMS", "CST_INVALIDO",
                f"CST ICMS '{cst_icms}' nao e um codigo valido.",
            ))
    # CSTs com 1 digito ou >3 digitos sao invalidos
    elif cst_icms not in _CSOSN_VALIDOS:
        errors.append(make_error(
            record, "CST_ICMS", "CST_INVALIDO",
            f"CST ICMS '{cst_icms}' formato invalido (esperado 2 ou 3 digitos).",
        ))

    return errors


# ──────────────────────────────────────────────
# Validacao de isencoes/exclusoes
# ──────────────────────────────────────────────

def _validate_exemptions_c170(record: SpedRecord) -> list[ValidationError]:
    """Valida consistencia entre CST e valores de ICMS.

    Se CST indica isencao (40,41,50), BC e VL_ICMS devem ser zero.
    """
    errors: list[ValidationError] = []
    cst_icms = get_field(record, "CST_ICMS")

    if not cst_icms:
        return errors

    # Extrair parte da tributacao (ultimos 2 digitos)
    t = cst_icms[-2:] if len(cst_icms) >= 2 else cst_icms

    vl_bc_icms = to_float(get_field(record, "VL_BC_ICMS"))
    vl_icms = to_float(get_field(record, "VL_ICMS"))

    # CST isento/nao-tributado: valores devem ser zero
    if t in CST_ISENTO_NT and (vl_bc_icms > 0 or vl_icms > 0):
        errors.append(make_error(
            record, "VL_ICMS", "ISENCAO_INCONSISTENTE",
            f"CST {cst_icms} indica isencao/nao-tributacao, "
            f"mas BC={vl_bc_icms:.2f} e ICMS={vl_icms:.2f} (deveriam ser zero).",
        ))

    # NOTE: TRIBUTACAO_INCONSISTENTE check (CST tributado + BC > 0 + ICMS = 0)
    # removed here -- it duplicates the CST_ALIQ_ZERO_FORTE rule in
    # fiscal_semantics.py which provides a more detailed analysis.

    return errors


# ──────────────────────────────────────────────
# CST_003: CST 020 sem reducao real de base
# ──────────────────────────────────────────────

def _validate_cst020_reducao(record: SpedRecord) -> list[ValidationError]:
    """Detecta CST 020 sem reducao efetiva de base.

    CST 020 indica reducao de base de calculo. Se VL_BC_ICMS ~= VL_ITEM - VL_DESC,
    nao houve reducao real.
    """
    cst_icms = get_field(record, "CST_ICMS")
    if not cst_icms:
        return []

    t = cst_icms[-2:] if len(cst_icms) >= 2 else cst_icms
    if t != "20":
        return []

    vl_item = to_float(get_field(record, "VL_ITEM"))
    vl_desc = to_float(get_field(record, "VL_DESC"))
    vl_bc_icms = to_float(get_field(record, "VL_BC_ICMS"))

    if vl_item <= 0 or vl_bc_icms <= 0:
        return []

    base_esperada = vl_item - vl_desc
    if base_esperada <= 0:
        return []

    # Se a base e >= 95% do valor do item, nao houve reducao real
    ratio = vl_bc_icms / base_esperada
    if ratio >= 0.95:
        return [make_error(
            record, "VL_BC_ICMS", "CST_020_SEM_REDUCAO",
            (
                f"CST {cst_icms} indica reducao de base, mas "
                f"VL_BC_ICMS={vl_bc_icms:.2f} e {ratio:.0%} do valor "
                f"tributavel ({base_esperada:.2f}). A base deveria estar "
                f"efetivamente reduzida. Verifique se a reducao foi aplicada "
                f"ou se o CST deveria ser 00 (tributacao integral)."
            ),
        )]

    return []


# ──────────────────────────────────────────────
# CST_001: CST tributado com aliquota zero
# ──────────────────────────────────────────────

def _validate_cst_tributado_aliq_zero(record: SpedRecord) -> list[ValidationError]:
    """CST_001: CST tributado (00,10,20,70,90) com ALIQ_ICMS = 0 e VL_ITEM > 0.

    CST 020 com aliquota zero apos reducao de 100% deveria ser CST 40.
    Exportacoes e remessas com aliquota zero sao ignoradas.
    """
    cst_icms = get_field(record, "CST_ICMS")
    if not cst_icms:
        return []

    t = trib(cst_icms)
    if t not in CST_TRIBUTADO:
        return []

    aliq = to_float(get_field(record, "ALIQ_ICMS"))
    if aliq > 0:
        return []

    vl_item = to_float(get_field(record, "VL_ITEM"))
    if vl_item <= 0:
        return []

    cfop = get_field(record, "CFOP")
    if cfop in CFOP_EXPORTACAO or cfop in CFOP_REMESSA_RETORNO:
        return []

    suggestion = "CST 40 (isento)" if t == "20" else "CST 40/41/50/51"
    return [make_error(
        record, "ALIQ_ICMS", "CST_TRIBUTADO_ALIQ_ZERO",
        (
            f"CST {cst_icms} indica tributacao, mas ALIQ_ICMS=0 com "
            f"VL_ITEM={vl_item:.2f}. Se a operacao for isenta ou nao "
            f"tributada, considere alterar para {suggestion}."
        ),
        value=f"CST={cst_icms} ALIQ=0 VL_ITEM={vl_item:.2f}",
    )]


# ──────────────────────────────────────────────
# CST_004: CST 020 com aliquota reduzida sem decreto
# ──────────────────────────────────────────────

def _validate_cst020_aliq_reduzida(record: SpedRecord) -> list[ValidationError]:
    """CST_004: CST 020 com aliquota menor que o piso interno (17%).

    CST 020 = reducao de base de calculo. A aliquota deve permanecer a
    padrao do estado; apenas a base e reduzida. Se a aliquota tambem
    esta reduzida, pode indicar beneficio nao amparado por decreto.
    """
    cst_icms = get_field(record, "CST_ICMS")
    if not cst_icms:
        return []

    t = trib(cst_icms)
    if t != "20":
        return []

    aliq = to_float(get_field(record, "ALIQ_ICMS"))
    if aliq <= 0 or aliq >= 17.0:
        return []

    cfop = get_field(record, "CFOP")
    # Aliquotas interestaduais (4, 7, 12) sao normais para CFOPs 6xxx
    if cfop and cfop.startswith("6"):
        return []

    return [make_error(
        record, "ALIQ_ICMS", "CST_020_ALIQ_REDUZIDA",
        (
            f"CST {cst_icms} (reducao de base) com ALIQ_ICMS={aliq:.2f}%, "
            f"abaixo do piso interno de 17%. No CST 020, apenas a base "
            f"deve ser reduzida; a aliquota deve permanecer a padrao. "
            f"Verifique se ha decreto estadual autorizando a reducao "
            f"cumulativa de base e aliquota."
        ),
        value=f"CST={cst_icms} ALIQ={aliq:.2f}%",
    )]


# ──────────────────────────────────────────────
# CST_005: Diferimento com debito indevido
# ──────────────────────────────────────────────

def _validate_diferimento_debito(record: SpedRecord) -> list[ValidationError]:
    """CST_005: CST 051 (diferimento) com VL_ICMS > 0.

    No diferimento total, o imposto e adiado para a etapa seguinte e
    nao deve gerar debito no periodo corrente.
    """
    cst_icms = get_field(record, "CST_ICMS")
    if not cst_icms:
        return []

    t = trib(cst_icms)
    if t not in CST_DIFERIMENTO:
        return []

    vl_icms = to_float(get_field(record, "VL_ICMS"))
    if vl_icms <= 0:
        return []

    return [make_error(
        record, "VL_ICMS", "CST_051_DIFERIMENTO_DEBITO",
        (
            f"CST {cst_icms} indica diferimento, mas VL_ICMS={vl_icms:.2f}. "
            f"No diferimento total, o imposto e adiado e nao deve gerar "
            f"debito no periodo. Verifique se o diferimento e total ou "
            f"parcial e se o debito esta correto."
        ),
        value=f"CST={cst_icms} VL_ICMS={vl_icms:.2f}",
    )]


# ──────────────────────────────────────────────
# IPI_003: CST IPI incompativel com campos monetarios
# ──────────────────────────────────────────────

def _validate_ipi_cst_campos(record: SpedRecord) -> list[ValidationError]:
    """Detecta incompatibilidade entre CST IPI e campos monetarios.

    - CST tributado sem base/valor -> erro
    - CST isento/NT com base/valor > 0 -> erro
    """
    errors: list[ValidationError] = []
    cst_ipi = get_field(record, "CST_IPI")

    if not cst_ipi:
        return errors

    vl_bc_ipi = to_float(get_field(record, "VL_BC_IPI"))
    _aliq_ipi = to_float(get_field(record, "ALIQ_IPI"))
    vl_ipi = to_float(get_field(record, "VL_IPI"))

    # CST tributado com base zerada (aliquota 0% na TIPI e valido, so exige BC)
    if cst_ipi in _CST_IPI_TRIBUTADO and vl_bc_ipi == 0:
        errors.append(make_error(
            record, "CST_IPI", "IPI_CST_INCOMPATIVEL",
            (
                f"CST_IPI {cst_ipi} indica tributacao, mas VL_BC_IPI esta "
                f"zerado. O CST deveria ser 02 (isento), "
                f"03 (nao tributado), 04 (imune) ou 05 (suspenso), ou a "
                f"base de calculo do IPI esta faltando."
            ),
        ))

    # CST isento/NT com valores > 0
    if cst_ipi in _CST_IPI_SEM_IMPOSTO and (vl_bc_ipi > 0 or vl_ipi > 0):
        errors.append(make_error(
            record, "CST_IPI", "IPI_CST_INCOMPATIVEL",
            (
                f"CST_IPI {cst_ipi} indica isencao/NT/imunidade/suspensao, "
                f"mas BC_IPI={vl_bc_ipi:.2f} e VL_IPI={vl_ipi:.2f}. "
                f"Esses valores deveriam ser zero para o CST informado."
            ),
        ))

    return errors


# ──────────────────────────────────────────────
# Bloco H - Estoque vs Cadastro
# ──────────────────────────────────────────────

def _validate_bloco_h(groups: dict[str, list[SpedRecord]]) -> list[ValidationError]:
    """Valida Bloco H (inventario).

    H010: itens do inventario
    - COD_ITEM do H010 deve existir no 0200 (cadastro de itens)
    - VL_ITEM do H010 nao pode ser negativo
    - QTD do H010 nao pode ser negativa

    H010 campos (0-based): 0:REG, 1:COD_ITEM, 2:UNID, 3:QTD, 4:VL_UNIT, 5:VL_ITEM
    """
    errors: list[ValidationError] = []

    h010_records = groups.get("H010", [])
    if not h010_records:
        return errors

    # Cadastro de itens
    cod_items_cadastro = set()
    for rec in groups.get("0200", []):
        cod = get_field(rec, "COD_ITEM")
        if cod:
            cod_items_cadastro.add(cod)

    for rec in h010_records:
        cod_item = get_field(rec, "COD_ITEM")
        qtd = to_float(get_field(rec, "QTD"))
        vl_item = to_float(get_field(rec, "VL_ITEM"))

        # Item deve existir no cadastro
        if cod_item and cod_items_cadastro and cod_item not in cod_items_cadastro:
            errors.append(make_error(
                rec, "COD_ITEM", "REF_INEXISTENTE",
                f"COD_ITEM '{cod_item}' no H010 nao existe no cadastro 0200.",
            ))

        # Quantidade nao pode ser negativa
        if qtd < 0:
            errors.append(make_error(
                rec, "QTD", "VALOR_NEGATIVO",
                f"Quantidade negativa no inventario: {qtd}.",
            ))

        # Valor nao pode ser negativo
        if vl_item < 0:
            errors.append(make_error(
                rec, "VL_ITEM", "VALOR_NEGATIVO",
                f"Valor negativo no inventario: {vl_item}.",
            ))

    return errors
