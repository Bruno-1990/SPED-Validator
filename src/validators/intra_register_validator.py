"""Validador intra-registro: regras de consistência dentro do mesmo registro SPED."""

from __future__ import annotations

from dataclasses import dataclass

from ..models import SpedRecord, ValidationError
from ..services.context_builder import ValidationContext
from .format_validator import cfop_matches_operation, date_in_period, validate_date
from .helpers import (
    get_field,
    make_error,
)
from .tolerance import get_tolerance


@dataclass
class SpedContext:
    """Contexto global do arquivo SPED para validacoes."""
    dt_ini: str = ""  # DT_INI do registro 0000
    dt_fin: str = ""  # DT_FIN do registro 0000


# ──────────────────────────────────────────────
# Helpers locais
# ──────────────────────────────────────────────

def _to_float(value: str) -> float | None:
    """Converte string para float, retornando None se vazio (diferente de to_float)."""
    if not value:
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


# ──────────────────────────────────────────────
# API pública
# ──────────────────────────────────────────────

def validate_intra_register(
    records: list[SpedRecord],
    context: ValidationContext | SpedContext | None = None,
) -> list[ValidationError]:
    """Executa validações intra-registro em todos os registros.

    Args:
        records: Lista de registros parseados.
        context: ValidationContext do pipeline ou SpedContext legado.
    """
    # Aceita ValidationContext do pipeline — extrai SpedContext interno
    if isinstance(context, ValidationContext):
        sped_ctx = SpedContext(
            dt_ini=context.periodo_ini.strftime("%d%m%Y") if context.periodo_ini else "",
            dt_fin=context.periodo_fim.strftime("%d%m%Y") if context.periodo_fim else "",
        )
    elif isinstance(context, SpedContext):
        sped_ctx = context
    else:
        sped_ctx = _build_context(records)

    errors: list[ValidationError] = []
    hierarchy = _build_parent_map(records)

    for record in records:
        reg = record.register
        if reg == "C100":
            errors.extend(_validate_c100(record, sped_ctx))
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
                dt_ini=get_field(rec, "DT_INI"),
                dt_fin=get_field(rec, "DT_FIN"),
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
    """Encontra todos os C170 filhos do mesmo C100 pai de um C190.

    Filtra automaticamente itens de documentos cancelados/inutilizados
    (COD_SIT 02, 03, 04) para evitar falsos positivos na soma.
    """
    if parent is None:
        return []

    # Verificar se o C100 pai é documento cancelado/inutilizado
    cod_sit = get_field(parent, "COD_SIT")
    if cod_sit in ("02", "03", "04"):
        return []  # Documentos cancelados não participam da soma

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

    Campos C100 (posições 0-based após strip de pipes):
    0:REG, 1:IND_OPER, 2:IND_EMIT, 3:COD_PART, 4:COD_MOD, 5:COD_SIT,
    6:SER, 7:NUM_DOC, 8:CHV_NFE, 9:DT_DOC, 10:DT_E_S, 11:VL_DOC,
    12:IND_PGTO, 13:VL_DESC, 14:VL_ABAT_NT, 15:VL_MERC, ...
    """
    errors: list[ValidationError] = []

    ind_oper = get_field(record, "IND_OPER")
    cod_sit = get_field(record, "COD_SIT")
    dt_doc = get_field(record, "DT_DOC")
    dt_e_s = get_field(record, "DT_E_S")
    vl_doc = _to_float(get_field(record, "VL_DOC"))

    # Regra: Se IND_OPER=0 (entrada) e documento regular/extemporâneo, DT_E_S deve existir.
    # Documentos cancelados, inutilizados ou denegados (COD_SIT 02-08) não exigem DT_E_S.
    if ind_oper == "0" and not dt_e_s and cod_sit in ("00", "01", ""):
        errors.append(make_error(
            record, "DT_E_S", "MISSING_CONDITIONAL",
            "Operação de entrada (IND_OPER=0) com documento regular exige DT_E_S preenchido.",
            field_no=10,
        ))

    # Regra: COD_SIT cancelada/inutilizada -> valores devem ser zero
    if cod_sit in ("02", "03", "04") and vl_doc is not None and vl_doc > 0:
        errors.append(make_error(
            record, "VL_DOC", "INCONSISTENCY",
            f"Documento cancelado/inutilizado (COD_SIT={cod_sit}) não deve ter VL_DOC > 0 (encontrado: {vl_doc}).",
            field_no=11,
        ))

    # Regra: DT_DOC e DT_E_S devem ser datas válidas
    if dt_doc and not validate_date(dt_doc):
        errors.append(make_error(
            record, "DT_DOC", "INVALID_DATE",
            f"DT_DOC '{dt_doc}' não é uma data válida (DDMMAAAA).",
            field_no=9,
        ))

    if dt_e_s and not validate_date(dt_e_s):
        errors.append(make_error(
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
                errors.append(make_error(
                    record, "DT_DOC", "DATE_ORDER",
                    f"DT_DOC ({dt_doc}) é posterior a DT_E_S ({dt_e_s}).",
                    field_no=9,
                ))
        except (ValueError, IndexError):
            pass

    # Regra: Datas dentro do período do 0000
    if context.dt_ini and context.dt_fin:
        if dt_doc and validate_date(dt_doc) and not date_in_period(dt_doc, context.dt_ini, context.dt_fin):
            errors.append(make_error(
                record, "DT_DOC", "DATE_OUT_OF_PERIOD",
                f"DT_DOC ({dt_doc}) fora do período {context.dt_ini}..{context.dt_fin}.",
                field_no=9,
            ))

        if dt_e_s and validate_date(dt_e_s) and not date_in_period(dt_e_s, context.dt_ini, context.dt_fin):
            errors.append(make_error(
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

    Campos C170 (posições 0-based após strip de pipes):
    0:REG, 1:NUM_ITEM, 2:COD_ITEM, 3:DESCR_COMPL, 4:QTD, 5:UNID,
    6:VL_ITEM, 7:VL_DESC, 8:IND_MOV, 9:CST_ICMS, 10:CFOP, 11:COD_NAT,
    12:VL_BC_ICMS, 13:ALIQ_ICMS, 14:VL_ICMS, ...
    """
    errors: list[ValidationError] = []

    cfop = get_field(record, "CFOP")
    _vl_bc_icms = _to_float(get_field(record, "VL_BC_ICMS"))
    _aliq_icms = _to_float(get_field(record, "ALIQ_ICMS"))
    _vl_icms = _to_float(get_field(record, "VL_ICMS"))

    # Regra: CFOP coerente com IND_OPER do C100 pai
    if parent and cfop:
        ind_oper = get_field(parent, "IND_OPER")
        if not cfop_matches_operation(cfop, ind_oper):
            op_tipo = "entrada" if ind_oper == "0" else "saída"
            errors.append(make_error(
                record, "CFOP", "CFOP_MISMATCH",
                f"CFOP {cfop} incompatível com operação de {op_tipo} (IND_OPER={ind_oper}).",
                field_no=10,
            ))

    # Nota: recalculo VL_ICMS = BC * ALIQ delegado ao tax_recalc.py
    # que trata arredondamento de aliquota (Simples Nacional, etc.)

    return errors


# ──────────────────────────────────────────────
# C190 - Resumo por CFOP
# ──────────────────────────────────────────────

def _validate_c190(
    record: SpedRecord,
    c170_siblings: list[SpedRecord],
) -> list[ValidationError]:
    """Validações do C190: soma dos C170 deve bater com C190.

    Conforme Guia Prático EFD v3.2.2, o C190 consolida por combinação de
    CST_ICMS + CFOP + ALIQ_ICMS. O matching deve usar os 3 campos.

    Campos C190 (posições 0-based após strip de pipes):
    0:REG, 1:CST_ICMS, 2:CFOP, 3:ALIQ_ICMS, 4:VL_OPR, 5:VL_BC_ICMS,
    6:VL_ICMS, 7:VL_BC_ICMS_ST, 8:VL_ICMS_ST, 9:VL_RED_BC, 10:VL_IPI
    """
    errors: list[ValidationError] = []

    if not c170_siblings:
        return errors

    c190_cst = get_field(record, "CST_ICMS")
    c190_cfop = get_field(record, "CFOP")
    c190_aliq = get_field(record, "ALIQ_ICMS")
    _c190_vl_opr = _to_float(get_field(record, "VL_OPR"))
    c190_vl_bc = _to_float(get_field(record, "VL_BC_ICMS"))
    c190_vl_icms = _to_float(get_field(record, "VL_ICMS"))

    # Normalizar alíquota para comparação (ex: "18,00" e "18" devem bater)
    c190_aliq_f = _to_float(c190_aliq)

    # Filtrar C170 pela combinação CST + CFOP + ALIQ (conforme Guia Prático)
    # C170: pos 9=CST_ICMS, pos 10=CFOP, pos 13=ALIQ_ICMS
    matching_c170: list[SpedRecord] = []
    for c in c170_siblings:
        c170_cfop = get_field(c, "CFOP")
        if c170_cfop != c190_cfop:
            continue
        # CST: comparar o código completo (3 dígitos).
        # O 1o dígito indica origem (0=nacional, 1=estrangeira-direta, 2=estrangeira-mercado,
        # 5/6/7=Simples Nacional). CST 000 e 500 têm tributação "00" mas são categorias
        # distintas e devem gerar C190 separados.
        # Se CST tem 2 dígitos, normaliza para 3 com padding "0" na frente.
        c170_cst = get_field(c, "CST_ICMS")
        c170_norm = c170_cst.zfill(3) if len(c170_cst) == 2 else c170_cst
        c190_norm = c190_cst.zfill(3) if len(c190_cst) == 2 else c190_cst
        if c170_norm != c190_norm:
            continue
        # Alíquota: comparar como float para evitar diferença de formatação
        c170_aliq_f = _to_float(get_field(c, "ALIQ_ICMS"))
        if (c190_aliq_f is not None and c170_aliq_f is not None
                and abs(c190_aliq_f - c170_aliq_f) > 0.01):
            continue
        matching_c170.append(c)

    if not matching_c170:
        return errors

    # Soma dos valores dos C170 com mesma combinação CST+CFOP+ALIQ
    soma_vl_bc = sum(_to_float(get_field(c, "VL_BC_ICMS")) or 0.0 for c in matching_c170)
    soma_vl_icms = sum(_to_float(get_field(c, "VL_ICMS")) or 0.0 for c in matching_c170)

    chave = f"CST={c190_cst} CFOP={c190_cfop} ALIQ={c190_aliq}"

    # Nota: VL_OPR do C190 NÃO é validado aqui porque inclui frete, seguro
    # e despesas do C100 (não disponíveis neste contexto). A validação de
    # VL_OPR com rateio proporcional está em c190_validator.py.

    # Tolerancia de consolidacao baseada no numero de itens
    tol_consol = get_tolerance("consolidacao", n_items=len(matching_c170))

    # Regra: VL_BC_ICMS do C190 = soma VL_BC_ICMS dos C170
    if c190_vl_bc is not None and abs(soma_vl_bc - c190_vl_bc) > tol_consol:
        errors.append(make_error(
            record, "VL_BC_ICMS", "SOMA_DIVERGENTE",
            (
                f"VL_BC_ICMS do C190 ({c190_vl_bc:.2f}) diverge da soma dos "
                f"C170 ({soma_vl_bc:.2f}) para {chave}. "
                f"Confianca: alta (100 pontos)."
            ),
            field_no=6,
            expected_value=f"{soma_vl_bc:.2f}",
            value=f"{c190_vl_bc:.2f}",
        ))

    # Regra: VL_ICMS do C190 = soma VL_ICMS dos C170
    if c190_vl_icms is not None and abs(soma_vl_icms - c190_vl_icms) > tol_consol:
        errors.append(make_error(
            record, "VL_ICMS", "SOMA_DIVERGENTE",
            (
                f"VL_ICMS do C190 ({c190_vl_icms:.2f}) diverge da soma dos "
                f"C170 ({soma_vl_icms:.2f}) para {chave}. "
                f"Confianca: alta (100 pontos)."
            ),
            field_no=7,
            expected_value=f"{soma_vl_icms:.2f}",
            value=f"{c190_vl_icms:.2f}",
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

    vl_tot_debitos = _to_float(get_field(record, "VL_TOT_DEBITOS")) or 0.0
    vl_aj_debitos = _to_float(get_field(record, "VL_AJ_DEBITOS")) or 0.0
    vl_tot_aj_debitos = _to_float(get_field(record, "VL_TOT_AJ_DEBITOS")) or 0.0
    vl_estornos_cred = _to_float(get_field(record, "VL_ESTORNOS_CRED")) or 0.0
    vl_tot_creditos = _to_float(get_field(record, "VL_TOT_CREDITOS")) or 0.0
    vl_aj_creditos = _to_float(get_field(record, "VL_AJ_CREDITOS")) or 0.0
    vl_tot_aj_creditos = _to_float(get_field(record, "VL_TOT_AJ_CREDITOS")) or 0.0
    vl_estornos_deb = _to_float(get_field(record, "VL_ESTORNOS_DEB")) or 0.0
    vl_sld_credor_ant = _to_float(get_field(record, "VL_SLD_CREDOR_ANT")) or 0.0
    vl_sld_apurado = _to_float(get_field(record, "VL_SLD_APURADO"))
    vl_tot_ded = _to_float(get_field(record, "VL_TOT_DED")) or 0.0
    vl_icms_recolher = _to_float(get_field(record, "VL_ICMS_RECOLHER"))
    vl_sld_credor_transp = _to_float(get_field(record, "VL_SLD_CREDOR_TRANSPORTAR"))

    # Fórmula: VL_SLD_APURADO = débitos - créditos
    sld_calc = (
        vl_tot_debitos + vl_aj_debitos + vl_tot_aj_debitos + vl_estornos_cred
        - vl_tot_creditos - vl_aj_creditos - vl_tot_aj_creditos
        - vl_estornos_deb - vl_sld_credor_ant
    )

    tol_e110 = get_tolerance("apuracao_e110")

    if vl_sld_apurado is not None:
        diff = abs(sld_calc - vl_sld_apurado)
        if diff > tol_e110:
            errors.append(make_error(
                record, "VL_SLD_APURADO", "CALCULO_DIVERGENTE",
                f"VL_SLD_APURADO: calculado={sld_calc:.2f} vs declarado={vl_sld_apurado:.2f} (dif={diff:.2f}).",
                field_no=11,
                expected_value=f"{sld_calc:.2f}",
                value=f"{vl_sld_apurado:.2f}",
            ))

    # Se saldo > 0: VL_ICMS_RECOLHER = VL_SLD_APURADO - VL_TOT_DED
    if vl_sld_apurado is not None and vl_sld_apurado > 0 and vl_icms_recolher is not None:
        recolher_calc = vl_sld_apurado - vl_tot_ded
        diff = abs(recolher_calc - vl_icms_recolher)
        if diff > tol_e110:
            errors.append(make_error(
                record, "VL_ICMS_RECOLHER", "CALCULO_DIVERGENTE",
                f"VL_ICMS_RECOLHER: calculado={recolher_calc:.2f} vs declarado={vl_icms_recolher:.2f}.",
                field_no=13,
                expected_value=f"{recolher_calc:.2f}",
                value=f"{vl_icms_recolher:.2f}",
            ))

    # Se saldo <= 0: VL_SLD_CREDOR_TRANSPORTAR = abs(VL_SLD_APURADO)
    if vl_sld_apurado is not None and vl_sld_apurado <= 0 and vl_sld_credor_transp is not None:
        credor_calc = abs(vl_sld_apurado)
        diff = abs(credor_calc - vl_sld_credor_transp)
        if diff > tol_e110:
            errors.append(make_error(
                record, "VL_SLD_CREDOR_TRANSPORTAR", "CALCULO_DIVERGENTE",
                f"VL_SLD_CREDOR_TRANSPORTAR: calculado={credor_calc:.2f} vs declarado={vl_sld_credor_transp:.2f}.",
                field_no=14,
                expected_value=f"{credor_calc:.2f}",
                value=f"{vl_sld_credor_transp:.2f}",
            ))

    return errors
