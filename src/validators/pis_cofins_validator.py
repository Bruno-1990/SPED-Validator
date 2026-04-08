"""Validador de PIS/COFINS — direcao, consistencia de campos e efeitos.

Regras implementadas:
- PC_001: CST PIS/COFINS invalido
- PC_002: CST de saida usado em entrada ou vice-versa
- PC_003: CST tributavel (01-03) sem BC/aliquota/valor
- PC_004: CST credito entrada (50-56) sem BC
- PC_005: CST sem credito (70-75) com valor > 0
- PC_006: CST aliquota zero (06) com ALIQ > 0
- PC_007: CST monofasico (04) com aliquota/valor > 0
"""

from __future__ import annotations

from ..models import SpedRecord, ValidationError
from ..parser import group_by_register
from ..services.context_builder import ValidationContext
from .helpers import (
    get_field,
    make_error,
    to_float,
)

# CSTs PIS/COFINS fallback (conforme cst_vigente)
_CST_PIS_COFINS_VALIDOS = {
    "01", "02", "03", "04", "05", "06", "07", "08", "09",
    "49", "50", "51", "52", "53", "54", "55", "56",
    "60", "61", "62", "63", "64", "65", "66", "67",
    "70", "71", "72", "73", "74", "75",
    "98", "99",
}

# CSTs de SAIDA (operacoes de saida: CFOP 5/6/7xxx)
_CST_SAIDA = {"01", "02", "03", "04", "05", "06", "07", "08", "09", "49"}

# CSTs de ENTRADA (operacoes de entrada: CFOP 1/2/3xxx)
_CST_ENTRADA = {
    "50", "51", "52", "53", "54", "55", "56",
    "60", "61", "62", "63", "64", "65", "66", "67",
    "70", "71", "72", "73", "74", "75",
    "98", "99",
}

# CSTs tributaveis (exigem BC/aliq/valor > 0)
_CST_TRIBUTAVEL = {"01", "02", "03"}

# CSTs com credito de entrada (exigem BC)
_CST_CREDITO = {"50", "51", "52", "53", "54", "55", "56"}

# CSTs credito presumido
_CST_PRESUMIDO = {"60", "61", "62", "63", "64", "65", "66", "67"}

# CSTs sem credito (nao devem ter valor)
_CST_SEM_CREDITO = {"70", "71", "72", "73", "74", "75"}


def validate_pis_cofins(
    records: list[SpedRecord],
    context: ValidationContext | None = None,
) -> list[ValidationError]:
    """Executa validacoes de PIS/COFINS nos registros C170."""
    groups = group_by_register(records)
    errors: list[ValidationError] = []

    loader = context.reference_loader if context else None
    cst_validos = _CST_PIS_COFINS_VALIDOS
    if loader and loader.has_cst_vigente_table():
        db_set = loader.get_csts_validos("CST_PIS_COFINS")
        if db_set:
            cst_validos = db_set

    for rec in groups.get("C170", []):
        cfop = get_field(rec, "CFOP")
        errors.extend(_check_pis(rec, cfop, cst_validos))
        errors.extend(_check_cofins(rec, cfop, cst_validos))

    return errors


def _check_pis(
    record: SpedRecord, cfop: str, cst_validos: set[str],
) -> list[ValidationError]:
    """Valida campos PIS do C170."""
    cst = get_field(record, "CST_PIS")
    if not cst:
        return []

    vl_bc = to_float(get_field(record, "VL_BC_PIS"))
    aliq = to_float(get_field(record, "ALIQ_PIS"))
    vl_pis = to_float(get_field(record, "VL_PIS"))

    return _validate_tributo(record, "PIS", cst, cfop, vl_bc, aliq, vl_pis, cst_validos)


def _check_cofins(
    record: SpedRecord, cfop: str, cst_validos: set[str],
) -> list[ValidationError]:
    """Valida campos COFINS do C170."""
    cst = get_field(record, "CST_COFINS")
    if not cst:
        return []

    vl_bc = to_float(get_field(record, "VL_BC_COFINS"))
    aliq = to_float(get_field(record, "ALIQ_COFINS"))
    vl_cofins = to_float(get_field(record, "VL_COFINS"))

    return _validate_tributo(record, "COFINS", cst, cfop, vl_bc, aliq, vl_cofins, cst_validos)


def _validate_tributo(
    record: SpedRecord,
    tributo: str,
    cst: str,
    cfop: str,
    vl_bc: float,
    aliq: float,
    vl_tributo: float,
    cst_validos: set[str],
) -> list[ValidationError]:
    """Validacao generica para PIS ou COFINS."""
    errors: list[ValidationError] = []
    field_cst = f"CST_{tributo}"
    field_vl = f"VL_{tributo}"

    # PC_001: CST invalido
    if cst not in cst_validos:
        errors.append(make_error(
            record, field_cst, f"{tributo}_CST_INVALIDO",
            f"CST {tributo} '{cst}' nao e um codigo valido.",
            value=f"CST_{tributo}={cst}",
        ))
        return errors

    # PC_002: Direcao incompativel (saida vs entrada)
    if cfop:
        eh_saida = cfop[0] in ("5", "6", "7")
        eh_entrada = cfop[0] in ("1", "2", "3")

        if eh_saida and cst in _CST_ENTRADA:
            errors.append(make_error(
                record, field_cst, f"{tributo}_DIRECAO_INCOMPATIVEL",
                (
                    f"CST {tributo} {cst} e de ENTRADA (credito/aquisicao), "
                    f"mas CFOP {cfop} indica operacao de SAIDA. "
                    f"CSTs 50-99 sao para entradas, CSTs 01-49 para saidas."
                ),
                value=f"CST_{tributo}={cst} CFOP={cfop}",
            ))

        if eh_entrada and cst in _CST_SAIDA:
            errors.append(make_error(
                record, field_cst, f"{tributo}_DIRECAO_INCOMPATIVEL",
                (
                    f"CST {tributo} {cst} e de SAIDA, "
                    f"mas CFOP {cfop} indica operacao de ENTRADA. "
                    f"CSTs 01-49 sao para saidas, CSTs 50-99 para entradas."
                ),
                value=f"CST_{tributo}={cst} CFOP={cfop}",
            ))

    # PC_003: CST tributavel sem valores
    if cst in _CST_TRIBUTAVEL and vl_bc == 0 and aliq == 0 and vl_tributo == 0:
        errors.append(make_error(
            record, field_vl, f"{tributo}_TRIBUTAVEL_SEM_VALORES",
            (
                f"CST {tributo} {cst} indica operacao tributavel, mas "
                f"BC, aliquota e valor estao todos zerados. "
                f"Se a operacao e tributavel, os campos devem estar preenchidos."
            ),
            value=f"CST_{tributo}={cst} BC=0 ALIQ=0 VL=0",
        ))

    # PC_004: CST credito sem BC
    if cst in _CST_CREDITO and vl_bc == 0 and vl_tributo > 0:
        errors.append(make_error(
            record, f"VL_BC_{tributo}", f"{tributo}_CREDITO_SEM_BC",
            (
                f"CST {tributo} {cst} indica credito de entrada, "
                f"VL_{tributo}={vl_tributo:.2f} mas BC=0. "
                f"Para apropriar credito, a base de calculo deve estar informada."
            ),
            value=f"CST_{tributo}={cst} BC=0 VL={vl_tributo:.2f}",
        ))

    # PC_005: CST sem credito com valor
    if cst in _CST_SEM_CREDITO and vl_tributo > 0:
        errors.append(make_error(
            record, field_vl, f"{tributo}_SEM_CREDITO_COM_VALOR",
            (
                f"CST {tributo} {cst} indica entrada sem direito a credito, "
                f"mas VL_{tributo}={vl_tributo:.2f}. "
                f"O valor deveria ser zero para CSTs 70-75."
            ),
            value=f"CST_{tributo}={cst} VL={vl_tributo:.2f}",
        ))

    # PC_006: CST aliquota zero com aliquota > 0
    if cst == "06" and aliq > 0:
        errors.append(make_error(
            record, f"ALIQ_{tributo}", f"{tributo}_ALIQUOTA_INCONSISTENTE",
            (
                f"CST {tributo} 06 indica aliquota zero, "
                f"mas ALIQ_{tributo}={aliq:.4f}. "
                f"A aliquota deveria ser zero."
            ),
            value=f"CST_{tributo}=06 ALIQ={aliq:.4f}",
        ))

    # PC_007: CST monofasico com valor
    if cst == "04" and aliq > 0:
        errors.append(make_error(
            record, f"ALIQ_{tributo}", f"{tributo}_MONOFASICO_COM_ALIQ",
            (
                f"CST {tributo} 04 (monofasico/revenda) indica que o "
                f"tributo ja foi recolhido na etapa anterior, "
                f"mas ALIQ_{tributo}={aliq:.4f}. "
                f"Na revenda monofasica, a aliquota deve ser zero."
            ),
            value=f"CST_{tributo}=04 ALIQ={aliq:.4f}",
        ))

    return errors
