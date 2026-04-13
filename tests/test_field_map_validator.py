"""Motor field_map C100 ↔ XML (modo sped_xml)."""

from __future__ import annotations

import json
import sqlite3

from src.models import SpedRecord
from src.services.context_builder import ValidationContext, TaxRegime
from src.services.database import init_audit_db
from src.validators.field_map_validator import (
    validate_field_map_c100,
    validate_field_map_c170,
    validate_field_map_c190,
)


def _db() -> sqlite3.Connection:
    return init_audit_db(":memory:")


def test_field_map_vazio_em_sped_only() -> None:
    db = _db()
    cur = db.execute(
        "INSERT INTO sped_files (filename, hash_sha256, status) VALUES (?, ?, ?)",
        ("t.txt", "h", "parsed"),
    )
    fid = cur.lastrowid
    db.commit()
    ctx = ValidationContext(file_id=fid, mode="sped_only", regime=TaxRegime.NORMAL, has_xmls=True)
    rec = SpedRecord(
        line_number=10,
        register="C100",
        fields={"REG": "C100", "CHV_NFE": "1" * 44, "VL_DOC": "100,00"},
        raw_line="",
    )
    assert validate_field_map_c100(db, fid, [rec], ctx) == []


def test_field_map_detecta_vl_doc_divergente() -> None:
    db = _db()
    cur = db.execute(
        "INSERT INTO sped_files (filename, hash_sha256, status) VALUES (?, ?, ?)",
        ("t.txt", "h", "parsed"),
    )
    fid = cur.lastrowid
    ch = "1" * 44
    db.execute(
        "INSERT INTO nfe_xmls (file_id, chave_nfe, numero_nfe, serie, vl_doc, vl_icms, "
        "vl_icms_st, vl_ipi, prot_cstat, status, mod_nfe, dh_emissao) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)",
        (fid, ch, "1", "1", 1000.0, 0.0, 0.0, 0.0, "100", 55, "2024-01-15T10:00:00-03:00"),
    )
    db.commit()
    ctx = ValidationContext(file_id=fid, mode="sped_xml", regime=TaxRegime.NORMAL, has_xmls=True)
    rec = SpedRecord(
        line_number=20,
        register="C100",
        fields={
            "REG": "C100",
            "IND_OPER": "0",
            "IND_EMIT": "0",
            "COD_PART": "",
            "COD_MOD": "55",
            "COD_SIT": "00",
            "SER": "1",
            "NUM_DOC": "1",
            "CHV_NFE": ch,
            "DT_DOC": "15012024",
            "DT_E_S": "",
            "VL_DOC": "5000,00",
            "IND_PGTO": "0",
            "VL_DESC": "0",
            "VL_ABAT_NT": "0",
            "VL_MERC": "0",
            "IND_FRT": "0",
            "VL_FRT": "0",
            "VL_SEG": "0",
            "VL_OUT_DA": "0",
            "VL_BC_ICMS": "0",
            "VL_ICMS": "0",
            "VL_BC_ICMS_ST": "0",
            "VL_ICMS_ST": "0",
            "VL_IPI": "0",
            "VL_PIS": "0",
            "VL_COFINS": "0",
            "VL_PIS_ST": "0",
            "VL_COFINS_ST": "0",
        },
        raw_line="",
    )
    errs = validate_field_map_c100(db, fid, [rec], ctx)
    tipos = {e.field_name for e in errs}
    assert "VL_DOC" in tipos
    vl = next(e for e in errs if e.field_name == "VL_DOC")
    assert vl.categoria == "field_map_xml"
    assert vl.error_type.startswith("FM_")
    assert "1000" in (vl.expected_value or "")


def test_field_map_omitido_se_cruzamento_xml_mesmo_campo() -> None:
    """Nao duplica VL_DOC se ja existe erro aberto de cruzamento XML na mesma linha."""
    db = _db()
    cur = db.execute(
        "INSERT INTO sped_files (filename, hash_sha256, status) VALUES (?, ?, ?)",
        ("t.txt", "h", "parsed"),
    )
    fid = cur.lastrowid
    ch = "2" * 44
    db.execute(
        "INSERT INTO nfe_xmls (file_id, chave_nfe, numero_nfe, serie, vl_doc, vl_icms, "
        "vl_icms_st, vl_ipi, prot_cstat, status, mod_nfe, dh_emissao) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)",
        (fid, ch, "1", "1", 1000.0, 0.0, 0.0, 0.0, "100", 55, "2024-01-15T10:00:00-03:00"),
    )
    db.execute(
        """INSERT INTO validation_errors
           (file_id, line_number, register, field_name, value, error_type, severity, message, categoria, status)
           VALUES (?, 20, 'C100', 'VL_DOC', '5000', 'CRUZAMENTO_DIVERGENTE', 'error', 'cruzamento', 'cruzamento_xml', 'open')""",
        (fid,),
    )
    db.commit()
    ctx = ValidationContext(file_id=fid, mode="sped_xml", regime=TaxRegime.NORMAL, has_xmls=True)
    rec = SpedRecord(
        line_number=20,
        register="C100",
        fields={
            "REG": "C100",
            "IND_OPER": "0",
            "IND_EMIT": "0",
            "COD_PART": "",
            "COD_MOD": "55",
            "COD_SIT": "00",
            "SER": "1",
            "NUM_DOC": "1",
            "CHV_NFE": ch,
            "DT_DOC": "15012024",
            "DT_E_S": "",
            "VL_DOC": "5000,00",
            "IND_PGTO": "0",
            "VL_DESC": "0",
            "VL_ABAT_NT": "0",
            "VL_MERC": "0",
            "IND_FRT": "0",
            "VL_FRT": "0",
            "VL_SEG": "0",
            "VL_OUT_DA": "0",
            "VL_BC_ICMS": "0",
            "VL_ICMS": "0",
            "VL_BC_ICMS_ST": "0",
            "VL_ICMS_ST": "0",
            "VL_IPI": "0",
            "VL_PIS": "0",
            "VL_COFINS": "0",
            "VL_PIS_ST": "0",
            "VL_COFINS_ST": "0",
        },
        raw_line="",
    )
    errs = validate_field_map_c100(db, fid, [rec], ctx)
    assert not any(e.field_name == "VL_DOC" for e in errs)


def test_field_map_c170_cfop_divergente_parsed_json() -> None:
    """Onda 2: C170.CFOP vs CFOP do item no XML (parsed_json em nfe_xmls)."""
    from src.services.xml_service import parse_nfe_xml
    from tests.test_xml_service import _SAMPLE_XML

    parsed = parse_nfe_xml(_SAMPLE_XML)
    assert parsed
    db = _db()
    cur = db.execute(
        "INSERT INTO sped_files (filename, hash_sha256, status) VALUES (?, ?, ?)",
        ("t.txt", "h", "parsed"),
    )
    fid = cur.lastrowid
    ch = parsed["chave_nfe"]
    crt = int(parsed["crt_emitente"]) if str(parsed.get("crt_emitente") or "").isdigit() else 3
    db.execute(
        """INSERT INTO nfe_xmls (file_id, chave_nfe, numero_nfe, serie, cnpj_emitente,
           cnpj_destinatario, dh_emissao, vl_doc, vl_icms, vl_icms_st, vl_ipi, prot_cstat,
           status, mod_nfe, parsed_json, qtd_itens, crt_emitente)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)""",
        (
            fid,
            ch,
            parsed["numero_nfe"],
            parsed["serie"],
            parsed.get("cnpj_emitente") or "",
            parsed.get("cnpj_destinatario") or "",
            parsed["dh_emissao"],
            parsed["vl_doc"],
            parsed["vl_icms"],
            parsed["vl_icms_st"],
            parsed["vl_ipi"],
            parsed["prot_cstat"],
            55,
            json.dumps(parsed, ensure_ascii=False),
            parsed["qtd_itens"],
            crt,
        ),
    )
    db.commit()
    ctx = ValidationContext(file_id=fid, mode="sped_xml", regime=TaxRegime.NORMAL, has_xmls=True)

    c100 = SpedRecord(
        line_number=10,
        register="C100",
        fields={
            "REG": "C100",
            "IND_OPER": "0",
            "IND_EMIT": "0",
            "COD_PART": "",
            "COD_MOD": "55",
            "COD_SIT": "00",
            "SER": parsed["serie"],
            "NUM_DOC": parsed["numero_nfe"],
            "CHV_NFE": ch,
            "DT_DOC": "10042026",
            "DT_E_S": "",
            "VL_DOC": "1000,00",
            "IND_PGTO": "0",
            "VL_DESC": "0",
            "VL_ABAT_NT": "0",
            "VL_MERC": "0",
            "IND_FRT": "0",
            "VL_FRT": "0",
            "VL_SEG": "0",
            "VL_OUT_DA": "0",
            "VL_BC_ICMS": "1000,00",
            "VL_ICMS": "120,00",
            "VL_BC_ICMS_ST": "0",
            "VL_ICMS_ST": "0",
            "VL_IPI": "0",
            "VL_PIS": "0",
            "VL_COFINS": "0",
            "VL_PIS_ST": "0",
            "VL_COFINS_ST": "0",
        },
        raw_line="",
    )
    c170 = SpedRecord(
        line_number=11,
        register="C170",
        fields={
            "REG": "C170",
            "NUM_ITEM": "001",
            "COD_ITEM": "ABC123",
            "DESCR_COMPL": "Item teste",
            "QTD": "2,0000",
            "UNID": "UN",
            "VL_ITEM": "1000,00",
            "VL_DESC": "0",
            "IND_MOV": "0",
            "CST_ICMS": "000",
            "CFOP": "5102",
            "COD_NAT": "",
            "VL_BC_ICMS": "1000,00",
            "ALIQ_ICMS": "12,00",
            "VL_ICMS": "120,00",
            "VL_BC_ICMS_ST": "0",
            "ALIQ_ST": "0",
            "VL_ICMS_ST": "0",
            "IND_APUR": "0",
            "CST_IPI": "",
            "COD_ENQ": "",
            "VL_BC_IPI": "0",
            "ALIQ_IPI": "0",
            "VL_IPI": "0",
            "CST_PIS": "",
            "VL_BC_PIS": "0",
            "ALIQ_PIS": "0",
            "QUANT_BC_PIS": "0",
            "ALIQ_PIS_REAIS": "0",
            "VL_PIS": "0",
            "CST_COFINS": "",
            "VL_BC_COFINS": "0",
            "ALIQ_COFINS": "0",
            "QUANT_BC_COFINS": "0",
            "ALIQ_COFINS_REAIS": "0",
            "VL_COFINS": "0",
            "COD_CTA": "",
            "VL_ABAT_NT": "0",
        },
        raw_line="",
    )

    errs = validate_field_map_c170(db, fid, [c100, c170], ctx)
    cfop_e = [e for e in errs if e.field_name == "CFOP"]
    assert len(cfop_e) == 1
    assert cfop_e[0].register == "C170"
    assert cfop_e[0].error_type.startswith("FM_")
    assert cfop_e[0].categoria == "field_map_xml"


def test_field_map_c170_vl_icms_divergente_parsed_json() -> None:
    """C170.VL_ICMS divergente do XML gera FM_* (pos-recalculo no pipeline nao altera valores)."""
    from src.services.xml_service import parse_nfe_xml
    from tests.test_xml_service import _SAMPLE_XML

    parsed = parse_nfe_xml(_SAMPLE_XML)
    assert parsed
    db = _db()
    cur = db.execute(
        "INSERT INTO sped_files (filename, hash_sha256, status) VALUES (?, ?, ?)",
        ("t.txt", "h", "parsed"),
    )
    fid = cur.lastrowid
    ch = parsed["chave_nfe"]
    crt = int(parsed["crt_emitente"]) if str(parsed.get("crt_emitente") or "").isdigit() else 3
    db.execute(
        """INSERT INTO nfe_xmls (file_id, chave_nfe, numero_nfe, serie, cnpj_emitente,
           cnpj_destinatario, dh_emissao, vl_doc, vl_icms, vl_icms_st, vl_ipi, prot_cstat,
           status, mod_nfe, parsed_json, qtd_itens, crt_emitente)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)""",
        (
            fid,
            ch,
            parsed["numero_nfe"],
            parsed["serie"],
            parsed.get("cnpj_emitente") or "",
            parsed.get("cnpj_destinatario") or "",
            parsed["dh_emissao"],
            parsed["vl_doc"],
            parsed["vl_icms"],
            parsed["vl_icms_st"],
            parsed["vl_ipi"],
            parsed["prot_cstat"],
            55,
            json.dumps(parsed, ensure_ascii=False),
            parsed["qtd_itens"],
            crt,
        ),
    )
    db.commit()
    ctx = ValidationContext(file_id=fid, mode="sped_xml", regime=TaxRegime.NORMAL, has_xmls=True)

    c100 = SpedRecord(
        line_number=10,
        register="C100",
        fields={
            "REG": "C100",
            "IND_OPER": "0",
            "IND_EMIT": "0",
            "COD_PART": "",
            "COD_MOD": "55",
            "COD_SIT": "00",
            "SER": parsed["serie"],
            "NUM_DOC": parsed["numero_nfe"],
            "CHV_NFE": ch,
            "DT_DOC": "10042026",
            "DT_E_S": "",
            "VL_DOC": "1000,00",
            "IND_PGTO": "0",
            "VL_DESC": "0",
            "VL_ABAT_NT": "0",
            "VL_MERC": "0",
            "IND_FRT": "0",
            "VL_FRT": "0",
            "VL_SEG": "0",
            "VL_OUT_DA": "0",
            "VL_BC_ICMS": "1000,00",
            "VL_ICMS": "120,00",
            "VL_BC_ICMS_ST": "0",
            "VL_ICMS_ST": "0",
            "VL_IPI": "0",
            "VL_PIS": "0",
            "VL_COFINS": "0",
            "VL_PIS_ST": "0",
            "VL_COFINS_ST": "0",
        },
        raw_line="",
    )
    c170 = SpedRecord(
        line_number=11,
        register="C170",
        fields={
            "REG": "C170",
            "NUM_ITEM": "001",
            "COD_ITEM": "ABC123",
            "DESCR_COMPL": "Item teste",
            "QTD": "2,0000",
            "UNID": "UN",
            "VL_ITEM": "1000,00",
            "VL_DESC": "0",
            "IND_MOV": "0",
            "CST_ICMS": "000",
            "CFOP": "6102",
            "COD_NAT": "",
            "VL_BC_ICMS": "1000,00",
            "ALIQ_ICMS": "12,00",
            "VL_ICMS": "99,00",
            "VL_BC_ICMS_ST": "0",
            "ALIQ_ST": "0",
            "VL_ICMS_ST": "0",
            "IND_APUR": "0",
            "CST_IPI": "",
            "COD_ENQ": "",
            "VL_BC_IPI": "0",
            "ALIQ_IPI": "0",
            "VL_IPI": "0",
            "CST_PIS": "",
            "VL_BC_PIS": "0",
            "ALIQ_PIS": "0",
            "QUANT_BC_PIS": "0",
            "ALIQ_PIS_REAIS": "0",
            "VL_PIS": "0",
            "CST_COFINS": "",
            "VL_BC_COFINS": "0",
            "ALIQ_COFINS": "0",
            "QUANT_BC_COFINS": "0",
            "ALIQ_COFINS_REAIS": "0",
            "VL_COFINS": "0",
            "COD_CTA": "",
            "VL_ABAT_NT": "0",
        },
        raw_line="",
    )

    errs = validate_field_map_c170(db, fid, [c100, c170], ctx)
    icms_e = [e for e in errs if e.field_name == "VL_ICMS"]
    assert len(icms_e) == 1
    assert icms_e[0].error_type.startswith("FM_")
    assert "120" in (icms_e[0].expected_value or "")


def test_field_map_c190_vl_icms_st_divergente_agregado() -> None:
    """C190.VL_ICMS_ST consolidado diverge da soma vICMSST nos itens do XML (parsed_json)."""
    from src.services.xml_service import parse_nfe_xml
    from tests.test_xml_service import _SAMPLE_XML

    parsed = parse_nfe_xml(_SAMPLE_XML)
    assert parsed
    db = _db()
    cur = db.execute(
        "INSERT INTO sped_files (filename, hash_sha256, status) VALUES (?, ?, ?)",
        ("t.txt", "h", "parsed"),
    )
    fid = cur.lastrowid
    ch = parsed["chave_nfe"]
    crt = int(parsed["crt_emitente"]) if str(parsed.get("crt_emitente") or "").isdigit() else 3
    db.execute(
        """INSERT INTO nfe_xmls (file_id, chave_nfe, numero_nfe, serie, cnpj_emitente,
           cnpj_destinatario, dh_emissao, vl_doc, vl_icms, vl_icms_st, vl_ipi, prot_cstat,
           status, mod_nfe, parsed_json, qtd_itens, crt_emitente)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)""",
        (
            fid,
            ch,
            parsed["numero_nfe"],
            parsed["serie"],
            parsed.get("cnpj_emitente") or "",
            parsed.get("cnpj_destinatario") or "",
            parsed["dh_emissao"],
            parsed["vl_doc"],
            parsed["vl_icms"],
            parsed["vl_icms_st"],
            parsed["vl_ipi"],
            parsed["prot_cstat"],
            55,
            json.dumps(parsed, ensure_ascii=False),
            parsed["qtd_itens"],
            crt,
        ),
    )
    db.commit()
    ctx = ValidationContext(file_id=fid, mode="sped_xml", regime=TaxRegime.NORMAL, has_xmls=True)

    c100 = SpedRecord(
        line_number=10,
        register="C100",
        fields={
            "REG": "C100",
            "IND_OPER": "0",
            "IND_EMIT": "0",
            "COD_PART": "",
            "COD_MOD": "55",
            "COD_SIT": "00",
            "SER": parsed["serie"],
            "NUM_DOC": parsed["numero_nfe"],
            "CHV_NFE": ch,
            "DT_DOC": "10042026",
            "DT_E_S": "",
            "VL_DOC": "1000,00",
            "IND_PGTO": "0",
            "VL_DESC": "0",
            "VL_ABAT_NT": "0",
            "VL_MERC": "0",
            "IND_FRT": "0",
            "VL_FRT": "0",
            "VL_SEG": "0",
            "VL_OUT_DA": "0",
            "VL_BC_ICMS": "1000,00",
            "VL_ICMS": "120,00",
            "VL_BC_ICMS_ST": "0",
            "VL_ICMS_ST": "0",
            "VL_IPI": "0",
            "VL_PIS": "0",
            "VL_COFINS": "0",
            "VL_PIS_ST": "0",
            "VL_COFINS_ST": "0",
        },
        raw_line="",
    )
    c190 = SpedRecord(
        line_number=20,
        register="C190",
        fields={
            "REG": "C190",
            "CST_ICMS": "000",
            "CFOP": "6102",
            "ALIQ_ICMS": "12,00",
            "VL_OPR": "1000,00",
            "VL_BC_ICMS": "1000,00",
            "VL_ICMS": "120,00",
            "VL_BC_ICMS_ST": "0",
            "VL_ICMS_ST": "50,00",
            "VL_RED_BC": "0",
            "VL_IPI": "0",
            "COD_OBS": "",
        },
        raw_line="",
    )

    errs = validate_field_map_c190(db, fid, [c100, c190], ctx)
    st_e = [e for e in errs if e.field_name == "VL_ICMS_ST"]
    assert len(st_e) == 1
    assert st_e[0].register == "C190"
    assert st_e[0].error_type.startswith("FM_")
    assert st_e[0].categoria == "field_map_xml"
