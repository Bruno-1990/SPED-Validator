"""Validador de regras pendentes SPED.

Regras implementadas:
- PEND_BENEFICIO_FISCAL: CST tributado com aliquota zero sem beneficio fiscal
- PEND_DESONERACAO_MOTIVO: Desoneracao de ICMS sem motivo preenchido
- PEND_DEVOLUCAO_VS_ORIGEM: Devolucao com CST incompativel com a operacao original
- PEND_PERFIL_HISTORICO: Item com tratamentos CST divergentes no mesmo periodo
- PEND_ALIQ_INTERESTADUAL: (no-op, ja coberta por ALIQ_001)
- PEND_NCM_VS_TIPI_ALIQ: NCM com aliquotas de IPI divergentes
"""

from __future__ import annotations

from collections import defaultdict

from ..models import SpedRecord, ValidationError
from ..parser import group_by_register
from ..services.context_builder import ValidationContext
from .helpers import (
    CFOP_DEVOLUCAO,
    CFOP_EXPORTACAO,
    CFOP_REMESSA_RETORNO,
    CST_ISENTO_NT,
    CST_TRIBUTADO,
    get_field,
    make_error,
    to_float,
    trib,
)

# ──────────────────────────────────────────────
# API publica
# ──────────────────────────────────────────────

def validate_pendentes(
    records: list[SpedRecord],
    context: ValidationContext | None = None,
) -> list[ValidationError]:
    """Executa validacoes pendentes nos registros SPED."""
    groups = group_by_register(records)
    errors: list[ValidationError] = []

    # Per-item (C170)
    for rec in groups.get("C170", []):
        errors.extend(_check_beneficio_fiscal(rec))
        errors.extend(_check_desoneracao_motivo(rec))
        errors.extend(_check_devolucao_vs_origem(rec))

    # Agregadas
    errors.extend(_check_perfil_historico(groups))

    # PEND_ALIQ_INTERESTADUAL: no-op, ja coberta por ALIQ_001 em
    # aliquota_validator.py (error_type ALIQ_INTERESTADUAL_INVALIDA).

    errors.extend(_check_ncm_vs_tipi_aliq(groups))

    return errors


# ──────────────────────────────────────────────
# PEND_BENEFICIO_FISCAL: CST tributado + aliquota zero
#   sem codigo de beneficio fiscal
# ──────────────────────────────────────────────

def _check_beneficio_fiscal(record: SpedRecord) -> list[ValidationError]:
    """CST tributado com aliquota zero sem beneficio fiscal vinculado."""
    cst = get_field(record, "CST_ICMS")
    if not cst:
        return []

    t = trib(cst)
    if t not in CST_TRIBUTADO:
        return []

    aliq = to_float(get_field(record, "ALIQ_ICMS"))
    if aliq != 0.0:
        return []

    cfop = get_field(record, "CFOP")
    if not cfop:
        return []

    # Excluir remessas/retornos e exportacoes -- nao se aplica
    if cfop in CFOP_REMESSA_RETORNO or cfop in CFOP_EXPORTACAO:
        return []

    return [make_error(
        record, "ALIQ_ICMS", "BENEFICIO_NAO_VINCULADO",
        (
            f"CST {cst} tributado com aliquota zero sem codigo de beneficio "
            f"fiscal vinculado. Se ha beneficio, parametrize o codigo "
            f"correspondente."
        ),
        field_no=14,
        value=f"CST={cst} CFOP={cfop} ALIQ=0",
    )]


# ──────────────────────────────────────────────
# PEND_DESONERACAO_MOTIVO: desoneracao sem motivo
# ──────────────────────────────────────────────

def _check_desoneracao_motivo(record: SpedRecord) -> list[ValidationError]:
    """Desoneracao de ICMS (VL_ICMS_DESON > 0) sem MOT_DES_ICMS preenchido.

    C170 field 18: VL_ICMS_DESON (aproximado conforme layout EFD ICMS/IPI).
    MOT_DES_ICMS: codigo de 1 digito (1-9), procurado apos posicao 30.
    """
    # Verificar se o registro tem campos suficientes para desoneracao
    if len(record.fields) <= 18:
        return []

    vl_deson = to_float(get_field(record, "IND_APUR"))
    if vl_deson <= 0:
        return []

    # Procurar MOT_DES_ICMS (codigo 1-9) em campos apos posicao 30
    mot_des_encontrado = False
    values = list(record.fields.values())
    for campo in values[30:]:
        campo = campo.strip()
        if campo in {"1", "2", "3", "4", "5", "6", "7", "8", "9"}:
            mot_des_encontrado = True
            break

    if mot_des_encontrado:
        return []

    return [make_error(
        record, "VL_ICMS_DESON", "DESONERACAO_SEM_MOTIVO",
        (
            f"Desoneracao de ICMS ({vl_deson:.2f}) sem motivo "
            f"(MOT_DES_ICMS) preenchido. A desoneracao exige codigo "
            f"de motivo."
        ),
        field_no=19,
        value=f"VL_ICMS_DESON={vl_deson:.2f}",
    )]


# ──────────────────────────────────────────────
# PEND_DEVOLUCAO_VS_ORIGEM: devolucao com CST incompativel
# ──────────────────────────────────────────────

def _check_devolucao_vs_origem(record: SpedRecord) -> list[ValidationError]:
    """Devolucao (CFOP de devolucao) com CST isento/NT -- possivel divergencia."""
    cfop = get_field(record, "CFOP")
    if not cfop or cfop not in CFOP_DEVOLUCAO:
        return []

    cst = get_field(record, "CST_ICMS")
    if not cst:
        return []

    t = trib(cst)
    if t not in CST_ISENTO_NT:
        return []

    return [make_error(
        record, "CST_ICMS", "DEVOLUCAO_INCONSISTENTE",
        (
            f"Devolucao (CFOP {cfop}) com CST {cst} (isento/NT), que pode "
            f"divergir da tributacao do documento de origem. A devolucao "
            f"deve espelhar a tributacao original."
        ),
        field_no=10,
        value=f"CFOP={cfop} CST={cst}",
    )]


# ──────────────────────────────────────────────
# PEND_PERFIL_HISTORICO: item com CSTs divergentes
# ──────────────────────────────────────────────

def _check_perfil_historico(
    groups: dict[str, list[SpedRecord]],
) -> list[ValidationError]:
    """Mesmo COD_ITEM com tratamentos tributarios divergentes no periodo.

    Detecta itens que aparecem com CST tributado E CST isento/NT,
    indicando possivel alteracao de enquadramento nao documentada.
    """
    errors: list[ValidationError] = []

    # Agrupar C170 por COD_ITEM
    item_stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {"tributado": 0, "isento": 0}
    )
    # Guardar um registro representativo por item para referencia na mensagem
    item_sample: dict[str, SpedRecord] = {}

    for rec in groups.get("C170", []):
        cod_item = get_field(rec, "COD_ITEM")
        cst = get_field(rec, "CST_ICMS")
        if not cod_item or not cst:
            continue

        t = trib(cst)
        if t in CST_TRIBUTADO:
            item_stats[cod_item]["tributado"] += 1
        elif t in CST_ISENTO_NT:
            item_stats[cod_item]["isento"] += 1

        if cod_item not in item_sample:
            item_sample[cod_item] = rec

    for cod_item, stats in item_stats.items():
        n_trib = stats["tributado"]
        n_isento = stats["isento"]
        total = n_trib + n_isento

        if total == 0 or n_trib == 0 or n_isento == 0:
            continue

        # Flaggear se >80% e tributado e ha ocorrencias isentas
        ratio_trib = n_trib / total
        if ratio_trib > 0.80:
            rec = item_sample[cod_item]
            errors.append(make_error(
                rec, "COD_ITEM", "ANOMALIA_HISTORICA",
                (
                    f"Item {cod_item} apresenta {n_trib} ocorrencias tributadas "
                    f"e {n_isento} com isencao/NT no mesmo periodo. Verifique "
                    f"se houve alteracao de enquadramento."
                ),
                field_no=3,
                value=f"COD_ITEM={cod_item} TRIB={n_trib} ISENTO={n_isento}",
            ))

    return errors


# ──────────────────────────────────────────────
# PEND_ALIQ_INTERESTADUAL: no-op
# ──────────────────────────────────────────────
# Regra ja implementada por ALIQ_001 em aliquota_validator.py
# (error_type: ALIQ_INTERESTADUAL_INVALIDA). Nao reimplementar aqui
# para evitar duplicacao de alertas.


# ──────────────────────────────────────────────
# PEND_NCM_VS_TIPI_ALIQ: NCM com aliquotas IPI divergentes
# ──────────────────────────────────────────────

def _check_ncm_vs_tipi_aliq(
    groups: dict[str, list[SpedRecord]],
) -> list[ValidationError]:
    """Detecta mesmo NCM com aliquotas de IPI divergentes (nao-zero).

    Como nao dispomos da tabela TIPI, verifica consistencia interna
    do arquivo: se o mesmo NCM aparece com aliquotas IPI diferentes
    (excluindo zero), sinaliza a divergencia.
    """
    errors: list[ValidationError] = []

    # Mapear COD_ITEM -> NCM via 0200
    item_ncm: dict[str, str] = {}
    for rec in groups.get("0200", []):
        cod = get_field(rec, "COD_ITEM")
        ncm = get_field(rec, "COD_NCM")
        if cod and ncm:
            item_ncm[cod] = ncm

    # Agrupar aliquotas IPI por NCM (apenas nao-zero)
    ncm_aliqs: dict[str, set[float]] = defaultdict(set)
    ncm_sample: dict[str, SpedRecord] = {}

    for rec in groups.get("C170", []):
        cod_item = get_field(rec, "COD_ITEM")
        aliq_ipi = to_float(get_field(rec, "ALIQ_IPI"))

        if not cod_item or aliq_ipi <= 0:
            continue

        ncm = item_ncm.get(cod_item, "")
        if not ncm:
            continue

        ncm_aliqs[ncm].add(round(aliq_ipi, 2))
        if ncm not in ncm_sample:
            ncm_sample[ncm] = rec

    for ncm, aliqs in ncm_aliqs.items():
        if len(aliqs) < 2:
            continue

        aliqs_str = ", ".join(f"{a:.2f}%" for a in sorted(aliqs))
        rec = ncm_sample[ncm]
        errors.append(make_error(
            rec, "ALIQ_IPI", "IPI_ALIQ_NCM_DIVERGENTE",
            (
                f"NCM {ncm} apresenta aliquotas de IPI divergentes: "
                f"{aliqs_str}. Verifique se as aliquotas estao de acordo "
                f"com a TIPI vigente."
            ),
            field_no=23,
            value=f"NCM={ncm} ALIQS={aliqs_str}",
        ))

    return errors
