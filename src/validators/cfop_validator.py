"""Validador CFOP: cruzamento CFOP x UF destino e DIFAL.

Regras:
- CFOP_001: CFOP interestadual (6xxx) com destino mesma UF
- CFOP_002: CFOP interno (5xxx) com destino outra UF
- CFOP_003: CFOP incompativel com tratamento DIFAL
"""

from __future__ import annotations

from ..models import SpedRecord, ValidationError
from ..parser import group_by_register
from ..services.context_builder import ValidationContext
from .helpers import (
    CFOP_REMESSA_RETORNO,
    get_field,
    make_error,
)


def validate_cfop(
    records: list[SpedRecord],
    context: ValidationContext | None = None,
) -> list[ValidationError]:
    """Executa validacoes CFOP_001, CFOP_002 e CFOP_003."""
    if not context or not context.uf_contribuinte:
        return []

    errors: list[ValidationError] = []
    groups = group_by_register(records)
    uf_contrib = context.uf_contribuinte.upper()

    # Mapear C100 -> COD_PART para vincular C170 ao participante
    current_c100_part = ""
    c170_to_part: dict[int, str] = {}
    for rec in records:
        if rec.register == "C100":
            current_c100_part = get_field(rec, "COD_PART")
        elif rec.register == "C170":
            c170_to_part[rec.line_number] = current_c100_part

    # Detectar presenca de E300 (DIFAL)
    has_e300 = len(groups.get("E300", [])) > 0

    for rec in groups.get("C170", []):
        cfop = get_field(rec, "CFOP")
        if not cfop or len(cfop) < 4:
            continue

        cod_part = c170_to_part.get(rec.line_number, "")
        part = context.participantes.get(cod_part, {})
        uf_dest = part.get("uf", "").upper()

        if not uf_dest:
            continue

        # CFOP_001: CFOP interestadual (6xxx) com destino mesma UF
        if cfop.startswith("6") and uf_dest == uf_contrib:
            errors.append(make_error(
                rec, "CFOP", "CFOP_INTERESTADUAL_MESMA_UF",
                f"CFOP {cfop} indica operacao interestadual, mas "
                f"destinatario {cod_part} esta na mesma UF ({uf_dest}) "
                f"que o contribuinte ({uf_contrib}). "
                f"Deveria usar CFOP 5xxx (operacao interna).",
                field_no=10,
                expected_value=f"5{cfop[1:]}",
                value=cfop,
            ))

        # CFOP_002: CFOP interno (5xxx) com destino outra UF
        elif cfop.startswith("5") and uf_dest != uf_contrib:
            errors.append(make_error(
                rec, "CFOP", "CFOP_INTERNO_OUTRA_UF",
                f"CFOP {cfop} indica operacao interna, mas "
                f"destinatario {cod_part} esta em {uf_dest}, "
                f"diferente do contribuinte ({uf_contrib}). "
                f"Deveria usar CFOP 6xxx (operacao interestadual).",
                field_no=10,
                expected_value=f"6{cfop[1:]}",
                value=cfop,
            ))

        # CFOP_003: CFOP incompativel com DIFAL
        # E300 preenchido indica que ha DIFAL declarado.
        # CFOPs de remessa/retorno nao geram DIFAL.
        if has_e300 and cfop.startswith("6") and cfop in CFOP_REMESSA_RETORNO:
            errors.append(make_error(
                rec, "CFOP", "CFOP_DIFAL_INCOMPATIVEL",
                f"CFOP {cfop} (remessa/retorno) nao gera DIFAL, mas "
                f"o arquivo possui E300 (apuracao DIFAL). "
                f"Verificar se este item deveria compor a base DIFAL.",
                field_no=10,
                value=cfop,
            ))

    return errors
