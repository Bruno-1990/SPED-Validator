"""Testes para validações do Bloco K."""

import pytest
from src.models import SpedRecord
from src.validators.helpers import fields_to_dict
from src.validators.bloco_k_validator import validate_bloco_k


def _rec(register: str, fields_list: list[str], line: int = 1) -> SpedRecord:
    return SpedRecord(
        line_number=line,
        register=register,
        fields=fields_to_dict(register, fields_list),
        raw_line="|" + "|".join(fields_list) + "|",
    )


def _k001(ind_mov: str = "0") -> SpedRecord:
    return _rec("K001", ["K001", ind_mov])


def _k200(cod_item: str = "ITEM01", qtd: str = "100") -> SpedRecord:
    return _rec("K200", ["K200", "31012024", cod_item, qtd, "0", ""])


def _k210() -> SpedRecord:
    return _rec("K210", ["K210", "01012024"])


def _k230(cod_item: str = "ITEM01", cod_doc_op: str = "OP001") -> SpedRecord:
    return _rec("K230", ["K230", "01012024", "31012024", cod_doc_op, cod_item, "100"])


def _k235(cod_item: str = "COMP01") -> SpedRecord:
    return _rec("K235", ["K235", "01012024", cod_item, "50", "", ""])


def _reg0200(cod_item: str = "ITEM01") -> SpedRecord:
    return _rec("0200", ["0200", cod_item, "DESC", "", "", "UN", "0", "12345678", "", "", "", ""])


class TestBlocoK:
    def test_k001_ind_mov_1_with_details_error(self):
        records = [_k001("1"), _k210()]
        errors = validate_bloco_k(records)
        assert any(e.error_type == "K_BLOCO_SEM_MOVIMENTO_COM_REGISTROS" for e in errors)

    def test_k001_ind_mov_0_with_details_ok(self):
        records = [_k001("0"), _k210()]
        errors = validate_bloco_k(records)
        assert not any(e.error_type == "K_BLOCO_SEM_MOVIMENTO_COM_REGISTROS" for e in errors)

    def test_k001_ind_mov_1_without_details_ok(self):
        records = [_k001("1")]
        errors = validate_bloco_k(records)
        assert not any(e.error_type == "K_BLOCO_SEM_MOVIMENTO_COM_REGISTROS" for e in errors)

    def test_k200_item_not_in_0200(self):
        records = [_k200("ITEM_INEXISTENTE"), _reg0200("ITEM01")]
        errors = validate_bloco_k(records)
        k_ref = [e for e in errors if e.error_type == "K_REF_ITEM_INEXISTENTE" and e.register == "K200"]
        assert len(k_ref) == 1

    def test_k200_item_in_0200_ok(self):
        records = [_k200("ITEM01"), _reg0200("ITEM01")]
        errors = validate_bloco_k(records)
        k_ref = [e for e in errors if e.error_type == "K_REF_ITEM_INEXISTENTE" and e.register == "K200"]
        assert len(k_ref) == 0

    def test_k200_qtd_negativa(self):
        records = [_k200("ITEM01", "-10")]
        errors = validate_bloco_k(records)
        assert any(e.error_type == "K_QTD_NEGATIVA" for e in errors)

    def test_k200_qtd_positiva_ok(self):
        records = [_k200("ITEM01", "100")]
        errors = validate_bloco_k(records)
        assert not any(e.error_type == "K_QTD_NEGATIVA" for e in errors)

    def test_k230_item_not_in_0200(self):
        records = [_k230("ITEM_INEXISTENTE"), _reg0200("ITEM01")]
        errors = validate_bloco_k(records)
        k_ref = [e for e in errors if e.error_type == "K_REF_ITEM_INEXISTENTE" and e.register == "K230"]
        assert len(k_ref) == 1

    def test_k230_without_k235(self):
        records = [_k230()]
        errors = validate_bloco_k(records)
        assert any(e.error_type == "K_ORDEM_SEM_COMPONENTES" for e in errors)

    def test_k230_with_k235_ok(self):
        records = [_k230(), _k235()]
        errors = validate_bloco_k(records)
        assert not any(e.error_type == "K_ORDEM_SEM_COMPONENTES" for e in errors)

    def test_empty_records(self):
        errors = validate_bloco_k([])
        assert errors == []
