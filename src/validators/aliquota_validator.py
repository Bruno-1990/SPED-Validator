"""Validador de aliquotas: interestaduais, internas e aliquota media.

Regras implementadas:
- ALIQ_001: Aliquota interestadual invalida (CFOP 6xxx + ALIQ fora de {4,7,12})
- ALIQ_002: Aliquota interna usada em operacao interestadual (CFOP 6xxx + ALIQ >= 17)
- ALIQ_003: Aliquota interestadual usada em operacao interna (CFOP 5xxx + ALIQ in {4,7,12})
- ALIQ_007: Aliquota media indevida no C190 (C190 com ALIQ nao suportada pelos C170)
"""

from __future__ import annotations

from collections import defaultdict

from ..models import SpedRecord, ValidationError
from ..parser import group_by_register
from .helpers import (
    ALIQ_INTERESTADUAIS,
    CFOP_EXPORTACAO,
    CFOP_REMESSA_RETORNO,
    CST_TRIBUTADO,
    TOLERANCE,
    get_field,
    make_error,
    to_float,
    trib,
)

# ──────────────────────────────────────────────
# Constantes locais
# ──────────────────────────────────────────────

_ALIQ_INTERNAS_MINIMA = 17.0


# ──────────────────────────────────────────────
# API publica
# ──────────────────────────────────────────────

def validate_aliquotas(records: list[SpedRecord]) -> list[ValidationError]:
    """Executa validacoes de aliquotas nos registros SPED."""
    groups = group_by_register(records)
    errors: list[ValidationError] = []

    # UF do declarante (0000, campo 8)
    uf_declarante = ""
    for r in groups.get("0000", []):
        uf_declarante = get_field(r, 8)
        break

    # Mapa COD_PART -> UF
    part_uf: dict[str, str] = {}
    for r in groups.get("0150", []):
        cod = get_field(r, 1)
        uf = get_field(r, 13)
        if cod and uf:
            part_uf[cod] = uf

    # Mapa C170.line -> C100 pai
    c170_parent = _build_parent_map(groups)

    # Per-item (C170)
    for rec in groups.get("C170", []):
        uf_dest = _get_participant_uf(rec, c170_parent, part_uf)
        errors.extend(_check_aliq_001(rec))
        errors.extend(_check_aliq_002(rec))
        errors.extend(_check_aliq_003(rec, uf_declarante, uf_dest))

    # Aggregate (C170 vs C190)
    errors.extend(_check_aliq_007(groups))

    return errors


# ──────────────────────────────────────────────
# Contexto
# ──────────────────────────────────────────────

def _build_parent_map(
    groups: dict[str, list[SpedRecord]],
) -> dict[int, SpedRecord]:
    """Mapa C170.line_number -> C100 pai."""
    all_recs = []
    for reg_type in ("C100", "C170"):
        for r in groups.get(reg_type, []):
            all_recs.append(r)
    all_recs.sort(key=lambda r: r.line_number)

    parent_map: dict[int, SpedRecord] = {}
    current_c100: SpedRecord | None = None
    for r in all_recs:
        if r.register == "C100":
            current_c100 = r
        elif r.register == "C170" and current_c100 is not None:
            parent_map[r.line_number] = current_c100
    return parent_map


def _get_participant_uf(
    c170: SpedRecord,
    parent_map: dict[int, SpedRecord],
    part_uf: dict[str, str],
) -> str:
    parent = parent_map.get(c170.line_number)
    if not parent:
        return ""
    cod_part = get_field(parent, 3)
    return part_uf.get(cod_part, "")


# ──────────────────────────────────────────────
# ALIQ_001: Aliquota interestadual invalida
# ──────────────────────────────────────────────

def _check_aliq_001(record: SpedRecord) -> list[ValidationError]:
    """CFOP 6xxx com aliquota fora de {4, 7, 12}."""
    cfop = get_field(record, 10)
    if not cfop or cfop[0] != "6":
        return []
    if cfop in CFOP_REMESSA_RETORNO:
        return []

    cst = get_field(record, 9)
    if not cst:
        return []
    t = trib(cst)
    if t not in CST_TRIBUTADO:
        return []

    aliq = to_float(get_field(record, 13))
    if aliq <= 0 or aliq in ALIQ_INTERESTADUAIS:
        return []

    return [make_error(
        record, "ALIQ_ICMS", "ALIQ_INTERESTADUAL_INVALIDA",
        (
            f"Operacao interestadual (CFOP {cfop}) com aliquota {aliq:.2f}%, "
            f"fora do padrao esperado (4%, 7% ou 12%). "
            f"Revise UF de origem, UF de destino, origem da mercadoria "
            f"e regra de tributacao do item."
        ),
        field_no=14,
        value=f"CFOP={cfop} ALIQ={aliq:.2f}%",
    )]


# ──────────────────────────────────────────────
# ALIQ_002: Aliquota interna em interestadual
# ──────────────────────────────────────────────

def _check_aliq_002(record: SpedRecord) -> list[ValidationError]:
    """CFOP 6xxx com aliquota >= 17% (tipica interna)."""
    cfop = get_field(record, 10)
    if not cfop or cfop[0] != "6":
        return []
    if cfop in CFOP_REMESSA_RETORNO:
        return []

    cst = get_field(record, 9)
    if not cst:
        return []
    t = trib(cst)
    if t not in CST_TRIBUTADO:
        return []

    aliq = to_float(get_field(record, 13))
    if aliq < _ALIQ_INTERNAS_MINIMA:
        return []

    return [make_error(
        record, "ALIQ_ICMS", "ALIQ_INTERNA_EM_INTERESTADUAL",
        (
            f"Operacao interestadual (CFOP {cfop}) com aliquota {aliq:.2f}%, "
            f"tipica de operacao interna. Aliquotas interestaduais validas "
            f"sao 4%, 7% ou 12%. Confirme UF do destinatario, natureza "
            f"da operacao e parametrizacao do ERP."
        ),
        field_no=14,
        value=f"CFOP={cfop} ALIQ={aliq:.2f}%",
    )]


# ──────────────────────────────────────────────
# ALIQ_003: Aliquota interestadual em interna
# ──────────────────────────────────────────────

def _check_aliq_003(
    record: SpedRecord,
    uf_declarante: str,
    uf_dest: str,
) -> list[ValidationError]:
    """CFOP 5xxx com aliquota in {4, 7, 12} e destinatario da mesma UF."""
    cfop = get_field(record, 10)
    if not cfop or cfop[0] != "5":
        return []
    if cfop in CFOP_REMESSA_RETORNO:
        return []

    aliq = to_float(get_field(record, 13))
    if aliq not in ALIQ_INTERESTADUAIS:
        return []

    # Se temos UF do destinatario, confirmar que e mesma UF
    if uf_dest and uf_declarante:
        if uf_dest.upper() != uf_declarante.upper():
            return []  # Pode ser CFOP errado, mas nao esta regra

    return [make_error(
        record, "ALIQ_ICMS", "ALIQ_INTERESTADUAL_EM_INTERNA",
        (
            f"Operacao interna (CFOP {cfop}) com aliquota {aliq:.2f}%, "
            f"tipica de operacao interestadual. Revise cadastro do cliente, "
            f"UF do participante e regra fiscal do CFOP."
        ),
        field_no=14,
        value=f"CFOP={cfop} ALIQ={aliq:.2f}%",
    )]


# ──────────────────────────────────────────────
# ALIQ_007: Aliquota media indevida no C190
# ──────────────────────────────────────────────

def _check_aliq_007(
    groups: dict[str, list[SpedRecord]],
) -> list[ValidationError]:
    """C190 com aliquota intermediaria nao suportada pelos itens C170.

    Agrupa C170 por C100 pai -> verifica se C190 desse documento tem
    aliquota que nao existe nos itens.
    """
    errors: list[ValidationError] = []

    # Construir mapa: C100.line -> [C170 records]
    c100_items: dict[int, list[SpedRecord]] = defaultdict(list)
    all_recs = []
    for reg_type in ("C100", "C170", "C190"):
        for r in groups.get(reg_type, []):
            all_recs.append(r)
    all_recs.sort(key=lambda r: r.line_number)

    current_c100_line = -1
    c100_c190: dict[int, list[SpedRecord]] = defaultdict(list)

    for r in all_recs:
        if r.register == "C100":
            current_c100_line = r.line_number
        elif r.register == "C170" and current_c100_line >= 0:
            c100_items[current_c100_line].append(r)
        elif r.register == "C190" and current_c100_line >= 0:
            c100_c190[current_c100_line].append(r)

    for c100_line, c190_recs in c100_c190.items():
        items = c100_items.get(c100_line, [])
        if len(items) < 2:
            continue  # Documento com 1 item nao pode ter media

        # Aliquotas presentes nos itens
        item_aliqs: set[float] = set()
        for it in items:
            aliq = to_float(get_field(it, 13))
            if aliq > 0:
                item_aliqs.add(round(aliq, 2))

        if not item_aliqs:
            continue

        for c190 in c190_recs:
            aliq_c190 = to_float(get_field(c190, 3))
            if aliq_c190 <= 0:
                continue

            aliq_c190_r = round(aliq_c190, 2)
            if aliq_c190_r not in item_aliqs:
                # Verificar se e uma aliquota "entre" as dos itens
                min_aliq = min(item_aliqs)
                max_aliq = max(item_aliqs)
                if min_aliq < aliq_c190_r < max_aliq:
                    errors.append(make_error(
                        c190, "ALIQ_ICMS", "ALIQ_MEDIA_INDEVIDA",
                        (
                            f"C190 com aliquota {aliq_c190:.2f}% que nao corresponde "
                            f"a nenhum item do documento. Aliquotas nos itens: "
                            f"{', '.join(f'{a:.2f}%' for a in sorted(item_aliqs))}. "
                            f"Ha indicio de aliquota media indevida -- cada item "
                            f"deve ser tratado com sua propria aliquota."
                        ),
                        field_no=4,
                        value=f"ALIQ_C190={aliq_c190:.2f}% ITENS={sorted(item_aliqs)}",
                    ))

    return errors
