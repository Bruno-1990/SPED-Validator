"""Testes para governança de correções — campos sensíveis bloqueados."""

import pytest
from src.services.correction_service import (
    _validate_correction_governance,
    CorrectionBlockedError,
    FIELDS_BLOCKED_FROM_AUTO_CORRECTION,
    FIELDS_NO_AUTOMATICO_MESMO_COM_REF_XML,
)


def test_blocks_auto_correction_of_cnpj():
    with pytest.raises(CorrectionBlockedError, match="não pode ser corrigido automaticamente"):
        _validate_correction_governance("CNPJ", "automatico", "12345678000190")


def test_blocks_auto_correction_of_vl_icms():
    with pytest.raises(CorrectionBlockedError):
        _validate_correction_governance("VL_ICMS", "automatico", "100.00")


def test_blocks_impossivel():
    with pytest.raises(CorrectionBlockedError, match="impossível de corrigir"):
        _validate_correction_governance("QUALQUER_CAMPO", "impossivel", "valor")


def test_allows_auto_correction_of_safe_fields():
    # Campos seguros para automação (ex: contagem bloco 9)
    _validate_correction_governance("QTD_REG", "automatico", "42")  # não deve levantar


def test_blocks_investigar_without_value():
    with pytest.raises(CorrectionBlockedError, match="requer análise externa"):
        _validate_correction_governance("CST_ICMS", "investigar", "")


def test_allows_proposta_for_blocked_fields_with_human_review():
    # Proposta (com revisão humana) deve ser permitida mesmo para campos sensíveis
    _validate_correction_governance("CNPJ", "proposta", "12345678000190")  # não deve levantar


def test_cnpj_in_blocked_set():
    assert "CNPJ" in FIELDS_BLOCKED_FROM_AUTO_CORRECTION
    assert "CPF" in FIELDS_BLOCKED_FROM_AUTO_CORRECTION
    assert "CHV_NFE" in FIELDS_BLOCKED_FROM_AUTO_CORRECTION
    assert "VL_ICMS" in FIELDS_BLOCKED_FROM_AUTO_CORRECTION


def test_blocks_auto_correction_of_cst_icms():
    with pytest.raises(CorrectionBlockedError):
        _validate_correction_governance("CST_ICMS", "automatico", "00")


def test_blocks_auto_correction_of_cfop():
    with pytest.raises(CorrectionBlockedError):
        _validate_correction_governance("CFOP", "automatico", "5101")


def test_vl_icms_auto_permitido_com_ref_xml():
    """Com referência XML, valores monetários podem ser automáticos (regra FM_*)."""
    _validate_correction_governance(
        "VL_ICMS", "automatico", "100,00", xml_ref_correction=True
    )


def test_num_doc_auto_bloqueado_mesmo_com_ref_xml():
    with pytest.raises(CorrectionBlockedError, match="referência no XML"):
        _validate_correction_governance(
            "NUM_DOC", "automatico", "12345", xml_ref_correction=True
        )


def test_cfop_auto_bloqueado_mesmo_com_ref_xml():
    with pytest.raises(CorrectionBlockedError, match="referência no XML"):
        _validate_correction_governance(
            "CFOP", "automatico", "5102", xml_ref_correction=True
        )


def test_proposta_permite_cfop_mesmo_com_ref_xml():
    _validate_correction_governance("CFOP", "proposta", "5102", xml_ref_correction=True)


def test_num_doc_consta_em_lista_xml_sem_auto():
    assert "NUM_DOC" in FIELDS_NO_AUTOMATICO_MESMO_COM_REF_XML
