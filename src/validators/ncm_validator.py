"""Regras de validacao NCM: tratamento tributario e NCM generico.

NCM_001 — NCM com tratamento tributario incompativel (TIPI vs CST)
NCM_002 — NCM generico com reflexo fiscal relevante (termina em 0000)
"""

from __future__ import annotations

from ..models import SpedRecord, ValidationError
from ..parser import group_by_register
from ..services.context_builder import ValidationContext
from .helpers import (
    CST_TRIBUTADO,
    F_0200_COD_ITEM,
    F_0200_NCM,
    F_C170_COD_ITEM,
    F_C170_CST_ICMS,
    F_C170_VL_ITEM,
    get_field,
    make_error,
    make_generic_error,
    to_float,
    trib,
)

# Threshold para NCM generico com reflexo fiscal
_NCM_GENERICO_THRESHOLD = 1000.0


# ──────────────────────────────────────────────
# API publica
# ──────────────────────────────────────────────

def validate_ncm(
    records: list[SpedRecord],
    context: ValidationContext | None = None,
) -> list[ValidationError]:
    """Executa regras de validacao de NCM."""
    groups = group_by_register(records)
    if not groups:
        return []

    # Construir mapa COD_ITEM -> NCM a partir do 0200
    item_ncm: dict[str, str] = {}
    for r in groups.get("0200", []):
        cod = get_field(r, F_0200_COD_ITEM)
        ncm = get_field(r, F_0200_NCM)
        if cod and ncm:
            item_ncm[cod] = ncm

    errors: list[ValidationError] = []
    errors.extend(_check_ncm_001(groups, item_ncm, context))
    errors.extend(_check_ncm_002(groups, item_ncm))

    return errors


# ──────────────────────────────────────────────
# NCM_001: NCM com tratamento tributario incompativel
# ──────────────────────────────────────────────

def _check_ncm_001(
    groups: dict[str, list[SpedRecord]],
    item_ncm: dict[str, str],
    context: ValidationContext | None = None,
) -> list[ValidationError]:
    """NCM_001: NCM classificado na TIPI como isento/NT/monofasico vs CST tributado."""
    errors: list[ValidationError] = []

    # Verificar se reference_loader esta disponivel
    if not context or not context.reference_loader:
        return [make_generic_error(
            "NCM_REFERENCIA_INDISPONIVEL",
            (
                "Tabela de referencia NCM/TIPI nao disponivel. "
                "A validacao NCM_001 (tratamento tributario incompativel) "
                "requer a tabela ncm_tipi_categorias.yaml em data/reference/."
            ),
            register="SPED",
            value="ncm_tipi_categorias indisponivel",
        )]

    loader = context.reference_loader

    # Verificar se a tabela NCM esta carregada
    ncm_checked: set[str] = set()

    for r in groups.get("C170", []):
        cod_item = get_field(r, F_C170_COD_ITEM)
        ncm = item_ncm.get(cod_item, "")
        if not ncm:
            continue

        # Evitar verificar o mesmo NCM+CST repetidamente
        cst = get_field(r, F_C170_CST_ICMS)
        if not cst:
            continue
        key = f"{ncm}:{trib(cst)}"
        if key in ncm_checked:
            continue
        ncm_checked.add(key)

        tributacao = loader.get_ncm_tributacao(ncm)
        if tributacao is None:
            continue  # NCM nao catalogado, sem como validar

        t = trib(cst)

        # NCM isento/NT na TIPI + CST tributado
        if tributacao in ("isento", "nt") and t in CST_TRIBUTADO:
            errors.append(make_error(
                r, "CST_ICMS", "NCM_TRIBUTACAO_INCOMPATIVEL",
                (
                    f"NCM {ncm} classificado como '{tributacao}' na TIPI, "
                    f"mas CST {cst} indica tributacao normal. Verifique se "
                    f"a classificacao fiscal do produto esta correta ou se "
                    f"o CST deveria refletir isencao/nao-tributacao."
                ),
                field_no=10,
                value=f"NCM={ncm} CST={cst} TIPI={tributacao}",
            ))

        # NCM monofasico + CST que nao reflete monofasia
        if tributacao == "monofasico" and t not in ("60", "70", "90"):
            errors.append(make_error(
                r, "CST_ICMS", "NCM_TRIBUTACAO_INCOMPATIVEL",
                (
                    f"NCM {ncm} classificado como monofasico na TIPI, "
                    f"mas CST {cst} nao reflete regime monofasico. "
                    f"Operacoes com produtos monofasicos geralmente usam "
                    f"CST 60 (ICMS cobrado por ST) ou 70/90."
                ),
                field_no=10,
                value=f"NCM={ncm} CST={cst} TIPI={tributacao}",
            ))

    return errors


# ──────────────────────────────────────────────
# NCM_002: NCM generico com reflexo fiscal relevante
# ──────────────────────────────────────────────

def _check_ncm_002(
    groups: dict[str, list[SpedRecord]],
    item_ncm: dict[str, str],
) -> list[ValidationError]:
    """NCM_002: NCM terminado em 0000 + VL_ITEM > R$ 1.000."""
    errors: list[ValidationError] = []
    ncm_alertado: set[str] = set()

    for r in groups.get("C170", []):
        cod_item = get_field(r, F_C170_COD_ITEM)
        ncm = item_ncm.get(cod_item, "")
        if not ncm or len(ncm) < 8:
            continue

        # NCM generico: termina em 0000
        if not ncm.endswith("0000"):
            continue

        # Ja alertou para esse NCM
        if ncm in ncm_alertado:
            continue

        vl_item = to_float(get_field(r, F_C170_VL_ITEM))
        if vl_item > _NCM_GENERICO_THRESHOLD:
            ncm_alertado.add(ncm)
            errors.append(make_error(
                r, "COD_ITEM", "NCM_GENERICO_RELEVANTE",
                (
                    f"NCM {ncm} e generico (termina em 0000) e o item "
                    f"{cod_item} tem valor de R$ {vl_item:,.2f}. NCM generico "
                    f"pode ocultar produto com tratamento tributario especifico "
                    f"(ST, monofasia, reducao de BC). Recomenda-se "
                    f"classificacao NCM mais precisa."
                ),
                field_no=3,
                value=f"NCM={ncm} COD_ITEM={cod_item} VL_ITEM={vl_item:.2f}",
            ))

    return errors
