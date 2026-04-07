"""Validações do Bloco K (Controle de Produção e Estoque).

Regras K_001 a K_005: integridade referencial, fechamento de bloco,
consistência de quantidades.
"""

from __future__ import annotations

from ..models import SpedRecord, ValidationError
from .helpers import get_field, make_error, to_float


def validate_bloco_k(
    records: list[SpedRecord],
    context: object = None,
) -> list[ValidationError]:
    errors: list[ValidationError] = []

    k210_records = [r for r in records if r.register == "K210"]
    k220_records = [r for r in records if r.register == "K220"]
    k230_records = [r for r in records if r.register == "K230"]
    reg_0200_codes = {get_field(r, "COD_ITEM") for r in records if r.register == "0200"}

    # K_001: K001 com IND_MOV=1 mas existem registros analíticos
    for r in records:
        if r.register == "K001":
            ind_mov = get_field(r, "IND_MOV")
            has_k_detail = bool(k210_records or k220_records or k230_records)
            if ind_mov == "1" and has_k_detail:
                errors.append(make_error(
                    r,
                    field_name="IND_MOV",
                    error_type="K_BLOCO_SEM_MOVIMENTO_COM_REGISTROS",
                    message="K001 com IND_MOV=1 (sem movimento) mas existem registros K210/K220/K230. "
                            "IND_MOV deve ser 0 quando há registros analíticos no Bloco K.",
                    field_no=2,
                    value=ind_mov,
                ))

    # K_002: COD_ITEM no K200 deve existir no 0200
    for r in records:
        if r.register == "K200":
            cod_item = get_field(r, "COD_ITEM")
            if cod_item and cod_item not in reg_0200_codes:
                errors.append(make_error(
                    r,
                    field_name="COD_ITEM",
                    error_type="K_REF_ITEM_INEXISTENTE",
                    message=f"COD_ITEM {cod_item!r} do K200 não encontrado no cadastro 0200. "
                            "Verifique se o item está corretamente cadastrado.",
                    value=cod_item,
                ))

    # K_003: QTD no K200 não pode ser negativa
    for r in records:
        if r.register == "K200":
            qtd = to_float(get_field(r, "QTD"))
            if qtd < 0:
                errors.append(make_error(
                    r,
                    field_name="QTD",
                    error_type="K_QTD_NEGATIVA",
                    message=f"Quantidade no K200 não pode ser negativa: {qtd}. "
                            "Saldo de estoque negativo indica erro de escrituração.",
                    value=str(qtd),
                ))

    # K_004: COD_ITEM no K230 deve existir no 0200
    for r in records:
        if r.register == "K230":
            cod_item = get_field(r, "COD_ITEM")
            if cod_item and cod_item not in reg_0200_codes:
                errors.append(make_error(
                    r,
                    field_name="COD_ITEM",
                    error_type="K_REF_ITEM_INEXISTENTE",
                    message=f"COD_ITEM {cod_item!r} do K230 não encontrado no 0200.",
                    value=cod_item,
                ))

    # K_005: K230 (ordem de produção) sem K235 (componentes)
    k235_doc_ops: set[str] = set()
    for r in records:
        if r.register == "K235":
            # K235 é filho de K230 — agrupado pelo COD_DOC_OP pai
            pass
    # Simplificado: verificar se existem K235 filhos de algum K230
    has_any_k235 = any(r.register == "K235" for r in records)

    for r in records:
        if r.register == "K230":
            if not has_any_k235:
                cod_doc_op = get_field(r, "COD_DOC_OP")
                errors.append(make_error(
                    r,
                    field_name="COD_DOC_OP",
                    error_type="K_ORDEM_SEM_COMPONENTES",
                    message=f"Ordem de produção {cod_doc_op!r} no K230 sem registros K235 (componentes). "
                            "Verifique se a estrutura do produto está completa.",
                    value=cod_doc_op,
                ))
                break  # Apenas um aviso geral

    return errors
