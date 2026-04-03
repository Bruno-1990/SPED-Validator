"""Validador intra-registro: regras de consistência dentro do mesmo registro SPED."""

from __future__ import annotations

from dataclasses import dataclass

from ..models import SpedRecord, ValidationError
from .format_validator import cfop_matches_operation, date_in_period, validate_date

TOLERANCE = 0.02  # Tolerância para comparações monetárias


@dataclass
class SpedContext:
    """Contexto global do arquivo SPED para validações."""
    dt_ini: str = ""  # DT_INI do registro 0000
    dt_fin: str = ""  # DT_FIN do registro 0000


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _get_field(record: SpedRecord, idx: int) -> str:
    """Retorna o campo na posição idx (0-based) ou string vazia."""
    if idx < len(record.fields):
        return record.fields[idx].strip()
    return ""


def _to_float(value: str) -> float | None:
    """Converte string para float (aceita vírgula brasileira)."""
    if not value:
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def _make_error(
    record: SpedRecord,
    field_name: str,
    error_type: str,
    message: str,
    field_no: int = 0,
) -> ValidationError:
    return ValidationError(
        line_number=record.line_number,
        register=record.register,
        field_no=field_no,
        field_name=field_name,
        value="",
        error_type=error_type,
        message=message,
    )


# ──────────────────────────────────────────────
# API pública
# ──────────────────────────────────────────────

def validate_intra_register(
    records: list[SpedRecord],
    context: SpedContext | None = None,
) -> list[ValidationError]:
    """Executa validações intra-registro em todos os registros.

    Args:
        records: Lista de registros parseados.
        context: Contexto com DT_INI/DT_FIN do 0000.
    """
    if context is None:
        context = _build_context(records)

    errors: list[ValidationError] = []
    hierarchy = _build_parent_map(records)

    for record in records:
        reg = record.register
        if reg == "C100":
            errors.extend(_validate_c100(record, context))
        elif reg == "C170":
            parent = hierarchy.get(record.line_number)
            errors.extend(_validate_c170(record, parent))
        elif reg == "C190":
            parent = hierarchy.get(record.line_number)
            siblings = _get_c170_siblings(record, parent, records)
            errors.extend(_validate_c190(record, siblings))
        elif reg == "E110":
            errors.extend(_validate_e110(record))

    return errors


def _build_context(records: list[SpedRecord]) -> SpedContext:
    """Extrai DT_INI e DT_FIN do registro 0000."""
    for rec in records:
        if rec.register == "0000":
            return SpedContext(
                dt_ini=_get_field(rec, 3),
                dt_fin=_get_field(rec, 4),
            )
    return SpedContext()


def _build_parent_map(records: list[SpedRecord]) -> dict[int, SpedRecord]:
    """Mapeia line_number de filhos para o registro pai mais recente.

    Ex: C170 na linha 15 -> C100 na linha 13.
    """
    parent_map: dict[int, SpedRecord] = {}
    current_parent: SpedRecord | None = None

    for rec in records:
        reg = rec.register
        # Registros pai (C100, D100, etc.)
        if len(reg) == 4 and reg[1:].isdigit() and int(reg[1:]) % 100 == 0:
            suffix = reg[-3:]
            if suffix not in ("001", "990"):
                current_parent = rec
        # Registros de abertura/fechamento resetam o pai
        elif reg.endswith("001") or reg.endswith("990"):
            current_parent = None
        elif current_parent is not None:
            parent_map[rec.line_number] = current_parent

    return parent_map


def _get_c170_siblings(
    c190: SpedRecord,
    parent: SpedRecord | None,
    records: list[SpedRecord],
) -> list[SpedRecord]:
    """Encontra todos os C170 filhos do mesmo C100 pai de um C190."""
    if parent is None:
        return []

    siblings: list[SpedRecord] = []
    in_scope = False
    for rec in records:
        if rec.line_number == parent.line_number:
            in_scope = True
            continue
        if in_scope:
            if rec.register == "C170":
                siblings.append(rec)
            elif rec.register in ("C100", "C990") or rec.register.endswith("001"):
                break
    return siblings


# ──────────────────────────────────────────────
# C100 - Nota Fiscal
# ──────────────────────────────────────────────

def _validate_c100(record: SpedRecord, context: SpedContext) -> list[ValidationError]:
    """Validações intra-registro do C100.

    Campos C100 (posições 0-based):
    0:REG, 1:IND_OPER, 2:IND_EMIT, 3:COD_PART, 4:COD_MOD, 5:COD_SIT,
    6:SER, 7:NUM_DOC, 8:CHV_NFE(depende do modelo), 9:DT_DOC, 10:DT_E_S,
    ...campos de valor variam por modelo. Para modelo 55 (NFe):
    8:DT_DOC, 9:DT_E_S, 10:VL_DOC, 11:IND_PGTO, 12:VL_DESC,
    13:VL_ABAT_NT, 14:VL_MERC, ...

    Nota: A posição exata dos campos pode variar. Usamos a estrutura padrão do Guia Prático.
    Posições para modelo 55: 1:IND_OPER, 5:COD_SIT, 8:DT_DOC, 9:DT_E_S, 10:VL_DOC
    """
    errors: list[ValidationError] = []

    ind_oper = _get_field(record, 1)
    cod_sit = _get_field(record, 5)
    dt_doc = _get_field(record, 8)
    dt_e_s = _get_field(record, 9)
    vl_doc = _to_float(_get_field(record, 10))

    # Regra: Se IND_OPER=0 (entrada), DT_E_S deve existir
    if ind_oper == "0" and not dt_e_s:
        errors.append(_make_error(
            record, "DT_E_S", "MISSING_CONDITIONAL",
            "Operação de entrada (IND_OPER=0) exige DT_E_S preenchido.",
            field_no=10,
        ))

    # Regra: COD_SIT cancelada/inutilizada -> valores devem ser zero
    if cod_sit in ("02", "03", "04") and vl_doc is not None and vl_doc > 0:
        errors.append(_make_error(
            record, "VL_DOC", "INCONSISTENCY",
            f"Documento cancelado/inutilizado (COD_SIT={cod_sit}) não deve ter VL_DOC > 0 (encontrado: {vl_doc}).",
            field_no=11,
        ))

    # Regra: DT_DOC e DT_E_S devem ser datas válidas
    if dt_doc and not validate_date(dt_doc):
        errors.append(_make_error(
            record, "DT_DOC", "INVALID_DATE",
            f"DT_DOC '{dt_doc}' não é uma data válida (DDMMAAAA).",
            field_no=9,
        ))

    if dt_e_s and not validate_date(dt_e_s):
        errors.append(_make_error(
            record, "DT_E_S", "INVALID_DATE",
            f"DT_E_S '{dt_e_s}' não é uma data válida (DDMMAAAA).",
            field_no=10,
        ))

    # Regra: DT_DOC <= DT_E_S
    if dt_doc and dt_e_s and validate_date(dt_doc) and validate_date(dt_e_s) and dt_doc > dt_e_s:
        # Comparação DDMMAAAA não funciona direto, converter
        from .format_validator import _parse_date
        try:
            if _parse_date(dt_doc) > _parse_date(dt_e_s):
                errors.append(_make_error(
                    record, "DT_DOC", "DATE_ORDER",
                    f"DT_DOC ({dt_doc}) é posterior a DT_E_S ({dt_e_s}).",
                    field_no=9,
                ))
        except (ValueError, IndexError):
            pass

    # Regra: Datas dentro do período do 0000
    if context.dt_ini and context.dt_fin:
        if dt_doc and validate_date(dt_doc) and not date_in_period(dt_doc, context.dt_ini, context.dt_fin):
            errors.append(_make_error(
                record, "DT_DOC", "DATE_OUT_OF_PERIOD",
                f"DT_DOC ({dt_doc}) fora do período {context.dt_ini}..{context.dt_fin}.",
                field_no=9,
            ))

        if dt_e_s and validate_date(dt_e_s) and not date_in_period(dt_e_s, context.dt_ini, context.dt_fin):
            errors.append(_make_error(
                record, "DT_E_S", "DATE_OUT_OF_PERIOD",
                f"DT_E_S ({dt_e_s}) fora do período {context.dt_ini}..{context.dt_fin}.",
                field_no=10,
            ))

    return errors


# ──────────────────────────────────────────────
# C170 - Itens da NF
# ──────────────────────────────────────────────

def _validate_c170(
    record: SpedRecord,
    parent: SpedRecord | None = None,
) -> list[ValidationError]:
    """Validações intra-registro do C170.

    Campos C170 (posições 0-based):
    0:REG, 1:NUM_ITEM, 2:COD_ITEM, 3:DESCR_COMPL, 4:QTD, 5:UNID,
    6:VL_ITEM, 7:VL_DESC, 8:IND_MOV, 9:CST_ICMS, 10:CFOP, 11:COD_NAT,
    12:VL_BC_ICMS, 13:ALIQ_ICMS, 14:VL_ICMS, ...
    """
    errors: list[ValidationError] = []

    cfop = _get_field(record, 9)
    vl_bc_icms = _to_float(_get_field(record, 12))
    aliq_icms = _to_float(_get_field(record, 13))
    vl_icms = _to_float(_get_field(record, 14))

    # Regra: CFOP coerente com IND_OPER do C100 pai
    if parent and cfop:
        ind_oper = _get_field(parent, 1)
        if not cfop_matches_operation(cfop, ind_oper):
            op_tipo = "entrada" if ind_oper == "0" else "saída"
            errors.append(_make_error(
                record, "CFOP", "CFOP_MISMATCH",
                f"CFOP {cfop} incompatível com operação de {op_tipo} (IND_OPER={ind_oper}).",
                field_no=10,
            ))

    # Regra: VL_BC_ICMS * ALIQ_ICMS / 100 ~= VL_ICMS
    if (vl_bc_icms is not None and aliq_icms is not None and vl_icms is not None
            and vl_bc_icms > 0 and aliq_icms > 0):
        icms_calc = vl_bc_icms * aliq_icms / 100
        diff = abs(icms_calc - vl_icms)
        if diff > TOLERANCE:
            errors.append(_make_error(
                record, "VL_ICMS", "CALCULO_DIVERGENTE",
                f"VL_ICMS diverge: calculado={icms_calc:.2f} vs declarado={vl_icms:.2f} (dif={diff:.2f}).",
                field_no=15,
            ))

    return errors


# ──────────────────────────────────────────────
# C190 - Resumo por CFOP
# ──────────────────────────────────────────────

def _validate_c190(
    record: SpedRecord,
    c170_siblings: list[SpedRecord],
) -> list[ValidationError]:
    """Validações do C190: soma dos C170 deve bater com C190.

    Campos C190 (posições 0-based):
    0:REG, 1:CST_ICMS, 2:CFOP, 3:ALIQ_ICMS, 4:VL_OPR, 5:VL_BC_ICMS,
    6:VL_ICMS, 7:VL_BC_ICMS_ST, 8:VL_ICMS_ST, 9:VL_RED_BC, 10:VL_IPI, 11:COD_OBS
    """
    errors: list[ValidationError] = []

    if not c170_siblings:
        return errors

    c190_cfop = _get_field(record, 2)
    c190_vl_opr = _to_float(_get_field(record, 4))
    c190_vl_bc = _to_float(_get_field(record, 5))
    c190_vl_icms = _to_float(_get_field(record, 6))

    # Filtrar C170 pelo CFOP correspondente
    # No C170, CFOP está na posição 9 (campo 10)
    matching_c170 = [c for c in c170_siblings if _get_field(c, 9) == c190_cfop]

    if not matching_c170:
        return errors

    # Soma dos VL_ITEM (posição 6 no C170) dos C170 com mesmo CFOP
    soma_vl_item = sum(_to_float(_get_field(c, 6)) or 0.0 for c in matching_c170)
    soma_vl_bc = sum(_to_float(_get_field(c, 12)) or 0.0 for c in matching_c170)
    soma_vl_icms = sum(_to_float(_get_field(c, 14)) or 0.0 for c in matching_c170)

    # Regra: VL_OPR do C190 = soma VL_ITEM dos C170
    if c190_vl_opr is not None and abs(soma_vl_item - c190_vl_opr) > TOLERANCE:
        errors.append(_make_error(
            record, "VL_OPR", "SOMA_DIVERGENTE",
            f"VL_OPR do C190 ({c190_vl_opr:.2f}) diverge da soma dos C170 ({soma_vl_item:.2f}).",
            field_no=5,
        ))

    # Regra: VL_BC_ICMS do C190 = soma VL_BC_ICMS dos C170
    if c190_vl_bc is not None and abs(soma_vl_bc - c190_vl_bc) > TOLERANCE:
        errors.append(_make_error(
            record, "VL_BC_ICMS", "SOMA_DIVERGENTE",
            f"VL_BC_ICMS do C190 ({c190_vl_bc:.2f}) diverge da soma dos C170 ({soma_vl_bc:.2f}).",
            field_no=6,
        ))

    # Regra: VL_ICMS do C190 = soma VL_ICMS dos C170
    if c190_vl_icms is not None and abs(soma_vl_icms - c190_vl_icms) > TOLERANCE:
        errors.append(_make_error(
            record, "VL_ICMS", "SOMA_DIVERGENTE",
            f"VL_ICMS do C190 ({c190_vl_icms:.2f}) diverge da soma dos C170 ({soma_vl_icms:.2f}).",
            field_no=7,
        ))

    return errors


# ──────────────────────────────────────────────
# E110 - Apuração ICMS
# ──────────────────────────────────────────────

def _validate_e110(record: SpedRecord) -> list[ValidationError]:
    """Validações do E110: fórmula completa da apuração ICMS.

    Campos E110 (posições 0-based):
    0:REG, 1:VL_TOT_DEBITOS, 2:VL_AJ_DEBITOS, 3:VL_TOT_AJ_DEBITOS,
    4:VL_ESTORNOS_CRED, 5:VL_TOT_CREDITOS, 6:VL_AJ_CREDITOS,
    7:VL_TOT_AJ_CREDITOS, 8:VL_ESTORNOS_DEB, 9:VL_SLD_CREDOR_ANT,
    10:VL_SLD_APURADO, 11:VL_TOT_DED, 12:VL_ICMS_RECOLHER,
    13:VL_SLD_CREDOR_TRANSPORTAR, 14:DEB_ESP
    """
    errors: list[ValidationError] = []

    vl_tot_debitos = _to_float(_get_field(record, 1)) or 0.0
    vl_aj_debitos = _to_float(_get_field(record, 2)) or 0.0
    vl_tot_aj_debitos = _to_float(_get_field(record, 3)) or 0.0
    vl_estornos_cred = _to_float(_get_field(record, 4)) or 0.0
    vl_tot_creditos = _to_float(_get_field(record, 5)) or 0.0
    vl_aj_creditos = _to_float(_get_field(record, 6)) or 0.0
    vl_tot_aj_creditos = _to_float(_get_field(record, 7)) or 0.0
    vl_estornos_deb = _to_float(_get_field(record, 8)) or 0.0
    vl_sld_credor_ant = _to_float(_get_field(record, 9)) or 0.0
    vl_sld_apurado = _to_float(_get_field(record, 10))
    vl_tot_ded = _to_float(_get_field(record, 11)) or 0.0
    vl_icms_recolher = _to_float(_get_field(record, 12))
    vl_sld_credor_transp = _to_float(_get_field(record, 13))

    # Fórmula: VL_SLD_APURADO = débitos - créditos
    sld_calc = (
        vl_tot_debitos + vl_aj_debitos + vl_tot_aj_debitos + vl_estornos_cred
        - vl_tot_creditos - vl_aj_creditos - vl_tot_aj_creditos
        - vl_estornos_deb - vl_sld_credor_ant
    )

    if vl_sld_apurado is not None:
        diff = abs(sld_calc - vl_sld_apurado)
        if diff > TOLERANCE:
            errors.append(_make_error(
                record, "VL_SLD_APURADO", "CALCULO_DIVERGENTE",
                f"VL_SLD_APURADO: calculado={sld_calc:.2f} vs declarado={vl_sld_apurado:.2f} (dif={diff:.2f}).",
                field_no=11,
            ))

    # Se saldo > 0: VL_ICMS_RECOLHER = VL_SLD_APURADO - VL_TOT_DED
    if vl_sld_apurado is not None and vl_sld_apurado > 0 and vl_icms_recolher is not None:
        recolher_calc = vl_sld_apurado - vl_tot_ded
        diff = abs(recolher_calc - vl_icms_recolher)
        if diff > TOLERANCE:
            errors.append(_make_error(
                record, "VL_ICMS_RECOLHER", "CALCULO_DIVERGENTE",
                f"VL_ICMS_RECOLHER: calculado={recolher_calc:.2f} vs declarado={vl_icms_recolher:.2f}.",
                field_no=13,
            ))

    # Se saldo <= 0: VL_SLD_CREDOR_TRANSPORTAR = abs(VL_SLD_APURADO)
    if vl_sld_apurado is not None and vl_sld_apurado <= 0 and vl_sld_credor_transp is not None:
        credor_calc = abs(vl_sld_apurado)
        diff = abs(credor_calc - vl_sld_credor_transp)
        if diff > TOLERANCE:
            errors.append(_make_error(
                record, "VL_SLD_CREDOR_TRANSPORTAR", "CALCULO_DIVERGENTE",
                f"VL_SLD_CREDOR_TRANSPORTAR: calculado={credor_calc:.2f} vs declarado={vl_sld_credor_transp:.2f}.",
                field_no=14,
            ))

    return errors
