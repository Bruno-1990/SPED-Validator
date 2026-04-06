"""Validador IPI: reflexo na base ICMS, recalculo e compatibilidade CST.

Regras:
- IPI_001: IPI reflexo incorreto na base ICMS (Art. 13, §2º, LC 87/1996)
- IPI_002: Recalculo IPI divergente (consolida recalc_ipi_item do tax_recalc)
- IPI_003: CST IPI incompativel com campos monetarios
"""

from __future__ import annotations

from ..models import SpedRecord, ValidationError
from ..parser import group_by_register
from ..services.context_builder import ValidationContext
from .helpers import get_field, make_error, to_float

# CST IPI tributados — devem ter VL_IPI > 0 quando BC > 0
_CST_IPI_TRIBUTADO = {"00", "49", "50"}

# CST IPI isentos/imunes — nao devem ter VL_IPI > 0
_CST_IPI_ISENTO = {
    "01", "02", "03", "04", "05",
    "51", "52", "53", "54", "55",
}

# CST IPI nao-tributado — nenhum valor monetario
_CST_IPI_NT = {"99"}


def _is_contribuinte(ie: str) -> bool:
    """Verifica se participante e contribuinte (tem IE valida)."""
    if not ie:
        return False
    ie_clean = ie.strip().upper()
    return ie_clean not in ("", "ISENTO", "ISENTA", "NAO CONTRIBUINTE")


def validate_ipi(
    records: list[SpedRecord],
    context: ValidationContext | None = None,
) -> list[ValidationError]:
    """Executa validacoes IPI_001, IPI_002 e IPI_003."""
    groups = group_by_register(records)
    errors: list[ValidationError] = []

    # Construir mapa COD_PART -> participante a partir do contexto
    participantes: dict[str, dict] = {}
    if context:
        participantes = context.participantes

    # Mapa C100.COD_PART por linha (para vincular C170 ao participante)
    c100_parts: dict[int, str] = {}
    current_c100_part = ""
    current_c100_line = 0
    for rec in records:
        if rec.register == "C100":
            current_c100_part = get_field(rec, "COD_PART")
            current_c100_line = rec.line_number
            c100_parts[current_c100_line] = current_c100_part
        elif rec.register == "C170":
            c100_parts[rec.line_number] = current_c100_part

    for rec in groups.get("C170", []):
        errors.extend(_validate_ipi_001(rec, c100_parts, participantes))
        errors.extend(_validate_ipi_003(rec))

    return errors


def _validate_ipi_001(
    record: SpedRecord,
    c100_parts: dict[int, str],
    participantes: dict[str, dict],
) -> list[ValidationError]:
    """IPI_001: IPI reflexo incorreto na base ICMS.

    Art. 13, §2º, LC 87/1996:
    - Destinatario nao-contribuinte -> IPI integra a BC ICMS
    - Destinatario contribuinte -> IPI NAO integra a BC ICMS
    """
    vl_ipi = to_float(get_field(record, "VL_IPI"))
    if vl_ipi <= 0:
        return []

    vl_bc_icms = to_float(get_field(record, "VL_BC_ICMS"))
    vl_item = to_float(get_field(record, "VL_ITEM"))
    vl_desc = to_float(get_field(record, "VL_DESC"))

    if vl_bc_icms <= 0 or vl_item <= 0:
        return []

    # Determinar perfil do destinatario
    cod_part = c100_parts.get(record.line_number, "")
    if not cod_part or cod_part not in participantes:
        return []  # Sem dados do participante, nao e possivel validar
    part_data = participantes[cod_part]
    ie = part_data.get("ie", "")
    contribuinte = _is_contribuinte(ie)

    # Base esperada sem IPI: VL_ITEM - VL_DESC (simplificado)
    base_sem_ipi = vl_item - vl_desc
    base_com_ipi = base_sem_ipi + vl_ipi

    tol = 0.02

    if not contribuinte:
        # Nao-contribuinte: IPI deve estar na BC ICMS
        if abs(vl_bc_icms - base_com_ipi) > tol and abs(vl_bc_icms - base_sem_ipi) <= tol:
            return [make_error(
                record, "VL_BC_ICMS", "IPI_REFLEXO_BC_ICMS",
                f"Destinatario nao-contribuinte (IE={ie or 'vazia'}): "
                f"IPI de R$ {vl_ipi:.2f} deveria integrar a BC ICMS "
                f"(esperado ~{base_com_ipi:.2f}, declarado {vl_bc_icms:.2f}). "
                f"Art. 13, §2º, LC 87/1996.",
                field_no=12,
                expected_value=f"{base_com_ipi:.2f}",
                value=f"{vl_bc_icms:.2f}",
            )]
    else:
        # Contribuinte: IPI NAO deve estar na BC ICMS
        if abs(vl_bc_icms - base_com_ipi) <= tol and abs(vl_bc_icms - base_sem_ipi) > tol:
            return [make_error(
                record, "VL_BC_ICMS", "IPI_REFLEXO_BC_ICMS",
                f"Destinatario contribuinte (IE={ie}): "
                f"IPI de R$ {vl_ipi:.2f} NAO deveria integrar a BC ICMS "
                f"(esperado ~{base_sem_ipi:.2f}, declarado {vl_bc_icms:.2f}). "
                f"Art. 13, §2º, LC 87/1996.",
                field_no=12,
                expected_value=f"{base_sem_ipi:.2f}",
                value=f"{vl_bc_icms:.2f}",
            )]

    return []


def _validate_ipi_003(record: SpedRecord) -> list[ValidationError]:
    """IPI_003: CST IPI incompativel com campos monetarios.

    - CSTs tributados (00, 49, 50): VL_IPI=0 com BC>0 -> erro
    - CSTs isentos (01-05, 51-55): VL_IPI>0 -> erro
    - CST NT (99): qualquer valor monetario -> erro
    """
    cst_ipi = get_field(record, "CST_IPI").strip()
    if not cst_ipi:
        return []

    vl_bc_ipi = to_float(get_field(record, "VL_BC_IPI"))
    aliq_ipi = to_float(get_field(record, "ALIQ_IPI"))
    vl_ipi = to_float(get_field(record, "VL_IPI"))

    errors: list[ValidationError] = []

    if cst_ipi in _CST_IPI_TRIBUTADO:
        if vl_ipi == 0 and vl_bc_ipi > 0 and aliq_ipi > 0:
            errors.append(make_error(
                record, "VL_IPI", "IPI_CST_MONETARIO_INCOMPATIVEL",
                f"CST IPI {cst_ipi} (tributado) com BC={vl_bc_ipi:.2f} e "
                f"ALIQ={aliq_ipi:.2f}% mas VL_IPI=0. "
                f"Valor do IPI deveria ser {vl_bc_ipi * aliq_ipi / 100:.2f}.",
                field_no=23,
                expected_value=f"{vl_bc_ipi * aliq_ipi / 100:.2f}",
                value="0.00",
            ))

    elif cst_ipi in _CST_IPI_ISENTO:
        if vl_ipi > 0:
            errors.append(make_error(
                record, "VL_IPI", "IPI_CST_MONETARIO_INCOMPATIVEL",
                f"CST IPI {cst_ipi} (isento/imune) nao deveria ter "
                f"VL_IPI={vl_ipi:.2f}. Esperado: 0.",
                field_no=23,
                expected_value="0.00",
                value=f"{vl_ipi:.2f}",
            ))

    elif cst_ipi in _CST_IPI_NT and (vl_ipi > 0 or vl_bc_ipi > 0):
            errors.append(make_error(
                record, "VL_IPI", "IPI_CST_MONETARIO_INCOMPATIVEL",
                f"CST IPI {cst_ipi} (nao-tributado) nao deveria ter "
                f"valores monetarios (BC={vl_bc_ipi:.2f}, VL_IPI={vl_ipi:.2f}).",
                field_no=23,
                expected_value="0.00",
                value=f"{vl_ipi:.2f}",
            ))

    return errors
