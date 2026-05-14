"""Dedup C190 fiscal vs cruzamento XML (XML_C190 ja persistido em nfe_cruzamento)."""

from __future__ import annotations

from src.models import SpedRecord
from src.services.context_builder import ValidationContext
from src.validators.c190_validator import validate_c190
from src.validators.helpers import fields_to_dict


def rec(register: str, fields: list[str], line: int = 1) -> SpedRecord:
    raw = "|" + "|".join(fields) + "|"
    return SpedRecord(line_number=line, register=register, fields=fields_to_dict(register, fields), raw_line=raw)


def _c100_com_chave(line: int, chave_44: str) -> SpedRecord:
    return rec("C100", [
        "C100", "1", "0", "FORN", "55", "00", "001", "123", chave_44,
        "10012024", "10012024", "1500,00", "0", "0", "0", "1500,00",
        "0", "0", "0", "0", "0", "0", "0", "0", "0", "0",
    ], line=line)


def _contexto_xml_ja_cruzado(chave: str) -> ValidationContext:
    """Simula pos-cruzar_xml_vs_sped: ha linhas em nfe_cruzamento + itens por grupo no contexto."""
    ctx = ValidationContext(file_id=1)
    ctx.xml_cruzamento_executado = True
    ctx.xml_by_chave = {
        chave: {
            "por_grupo": {
                ("00", "5102", 18.0): {
                    "vl_prod_liq": 1500.0,
                    "vl_icms": 270.0,
                    "vbc_icms": 1500.0,
                    "vl_prod": 1500.0,
                    "vl_desc": 0.0,
                    "qtd_itens": 2,
                },
            },
        },
    }
    return ctx


def test_sem_dedup_sem_flag_xml_cruzamento_emite_c190() -> None:
    """Com XML no contexto mas sem xml_cruzamento_executado, mantem erro fiscal C190."""
    chave = "3" * 44
    c100 = _c100_com_chave(1, chave)
    c170_1 = rec("C170", [
        "C170", "1", "P1", "D", "10", "UN", "1000,00",
        "0", "0", "00", "5102", "001", "1000,00", "18", "180,00",
        "0", "0", "0", "0", "0", "0", "0", "0", "0",
        "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0",
    ], line=2)
    c170_2 = rec("C170", [
        "C170", "2", "P2", "D", "5", "UN", "500,00",
        "0", "0", "00", "5102", "001", "500,00", "18", "90,00",
        "0", "0", "0", "0", "0", "0", "0", "0", "0",
        "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0",
    ], line=3)
    c190 = rec("C190", [
        "C190", "00", "5102", "18,00", "1500,00", "1500,00", "180,00",
        "0", "0", "0", "0",
    ], line=4)
    records = [c100, c170_1, c170_2, c190]

    ctx = ValidationContext(file_id=1)
    ctx.xml_cruzamento_executado = False
    ctx.xml_by_chave = _contexto_xml_ja_cruzado(chave).xml_by_chave

    errors = validate_c190(records, ctx)
    icms = [e for e in errors if e.error_type == "C190_DIVERGE_C170" and e.field_name == "VL_ICMS"]
    assert len(icms) >= 1


def test_com_xml_cruzamento_executado_nao_suprime_c190_diverge() -> None:
    """C190 vs C170 deve ser emitido MESMO com xml_cruzamento_executado=True.

    A validacao C190 vs C170 (integridade interna do SPED) e COMPLEMENTAR ao
    cruzamento XML, nao substituta. Ambas devem rodar sempre.
    Neste cenario: C170.VL_ICMS = 180+90 = 270, mas C190.VL_ICMS = 180 → diverge.
    """
    chave = "4" * 44
    c100 = _c100_com_chave(1, chave)
    c170_1 = rec("C170", [
        "C170", "1", "P1", "D", "10", "UN", "1000,00",
        "0", "0", "00", "5102", "001", "1000,00", "18", "180,00",
        "0", "0", "0", "0", "0", "0", "0", "0", "0",
        "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0",
    ], line=2)
    c170_2 = rec("C170", [
        "C170", "2", "P2", "D", "5", "UN", "500,00",
        "0", "0", "00", "5102", "001", "500,00", "18", "90,00",
        "0", "0", "0", "0", "0", "0", "0", "0", "0",
        "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0",
    ], line=3)
    c190 = rec("C190", [
        "C190", "00", "5102", "18,00", "1500,00", "1500,00", "180,00",
        "0", "0", "0", "0",
    ], line=4)
    records = [c100, c170_1, c170_2, c190]

    ctx = _contexto_xml_ja_cruzado(chave)
    errors = validate_c190(records, ctx)
    icms = [e for e in errors if e.error_type == "C190_DIVERGE_C170" and e.field_name == "VL_ICMS"]
    # Agora o erro DEVE ser emitido (C170 soma=270, C190=180 → dif=90)
    assert len(icms) >= 1, (
        f"C190_DIVERGE_C170 VL_ICMS deve ser emitido mesmo com XML cruzado. "
        f"Erros encontrados: {[e.error_type for e in errors]}"
    )
    # E deve conter referencia cruzada XML no diagnostico
    assert "XML" in icms[0].message


def test_com_xml_sem_divergencia_nao_gera_erro() -> None:
    """Quando C170 soma bate com C190, nenhum erro independente do modo XML."""
    chave = "5" * 44
    c100 = _c100_com_chave(1, chave)
    c170 = rec("C170", [
        "C170", "1", "P1", "D", "10", "UN", "1500,00",
        "0", "0", "00", "5102", "001", "1500,00", "18", "270,00",
        "0", "0", "0", "0", "0", "0", "0", "0", "0",
        "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0",
    ], line=2)
    c190 = rec("C190", [
        "C190", "00", "5102", "18,00", "1500,00", "1500,00", "270,00",
        "0", "0", "0", "0",
    ], line=3)
    records = [c100, c170, c190]

    ctx = _contexto_xml_ja_cruzado(chave)
    errors = validate_c190(records, ctx)
    c190_errs = [e for e in errors if e.error_type == "C190_DIVERGE_C170"]
    assert len(c190_errs) == 0, f"Nao deveria gerar erro quando C170 bate com C190: {c190_errs}"
