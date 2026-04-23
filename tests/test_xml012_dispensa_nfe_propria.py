"""Testes da Excecao 2 do Guia Pratico EFD v3.2.2 na regra XML012.

Guia Pratico EFD-ICMS/IPI v3.2.2, linhas 3087-3091:
  'Notas Fiscais Eletronicas - NF-e de emissao propria: regra geral, devem ser
  apresentados somente os registros C100 e C190 [...]; somente sera admitida a
  informacao do registro C170 quando tambem houver sido informado o registro
  C176, C180, C181 ou o Registro C177.'

Isso significa que a regra XML012 (qtd_xml != count(C170)) NAO deve gerar
finding para NF-e propria de saida sem C170 — a menos que o SPED tenha
C176/C180/C181/C177 (onde a informacao do C170 volta a ser obrigatoria).
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from src.services.database import init_audit_db
from src.services.xml_service import cruzar_xml_vs_sped


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = init_audit_db(":memory:")
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def _seed_file(db: sqlite3.Connection) -> int:
    cur = db.execute(
        "INSERT INTO sped_files (filename, hash_sha256, status) VALUES (?, ?, ?)",
        ("teste.txt", "abc", "validated"),
    )
    db.commit()
    return cur.lastrowid


def _insert_0000(db: sqlite3.Connection, file_id: int, cnpj: str = "07550459000108") -> None:
    fields = {
        "REG": "0000", "COD_VER": "018", "COD_FIN": "0",
        "DT_INI": "01012026", "DT_FIN": "31012026",
        "NOME": "Teste", "CNPJ": cnpj, "UF": "ES", "IND_PERFIL": "A",
    }
    db.execute(
        "INSERT INTO sped_records (file_id, line_number, register, block, fields_json, raw_line) "
        "VALUES (?, ?, '0000', '0', ?, '')",
        (file_id, 1, json.dumps(fields)),
    )
    db.commit()


def _insert_c100(
    db: sqlite3.Connection, file_id: int, line: int,
    chave: str, ind_emit: str = "0", cod_mod: str = "55", cod_sit: str = "00",
) -> int:
    fields = {
        "REG": "C100",
        "IND_OPER": "1",
        "IND_EMIT": ind_emit,
        "COD_PART": "99999",
        "COD_MOD": cod_mod,
        "COD_SIT": cod_sit,
        "SER": "1",
        "NUM_DOC": chave[25:34].lstrip("0") or "1",
        "CHV_NFE": chave,
        "DT_DOC": "15012026",
        "DT_E_S": "15012026",
        "VL_DOC": "100.00",
        "VL_ICMS": "17.00",
    }
    cur = db.execute(
        "INSERT INTO sped_records (file_id, line_number, register, block, fields_json, raw_line) "
        "VALUES (?, ?, 'C100', 'C', ?, '')",
        (file_id, line, json.dumps(fields)),
    )
    db.commit()
    return cur.lastrowid


def _insert_c190(db: sqlite3.Connection, file_id: int, line: int) -> None:
    fields = {"REG": "C190", "CST_ICMS": "000", "CFOP": "5101", "ALIQ_ICMS": "17",
              "VL_OPR": "100.00", "VL_BC_ICMS": "100.00", "VL_ICMS": "17.00"}
    db.execute(
        "INSERT INTO sped_records (file_id, line_number, register, block, fields_json, raw_line) "
        "VALUES (?, ?, 'C190', 'C', ?, '')",
        (file_id, line, json.dumps(fields)),
    )
    db.commit()


def _insert_c177(db: sqlite3.Connection, file_id: int, line: int) -> None:
    fields = {"REG": "C177", "COD_INF_COMPL_AUTOMOV": "001"}
    db.execute(
        "INSERT INTO sped_records (file_id, line_number, register, block, fields_json, raw_line) "
        "VALUES (?, ?, 'C177', 'C', ?, '')",
        (file_id, line, json.dumps(fields)),
    )
    db.commit()


def _insert_xml(db: sqlite3.Connection, file_id: int, chave: str, qtd_itens: int = 1) -> None:
    db.execute(
        "INSERT INTO nfe_xmls (file_id, chave_nfe, numero_nfe, serie, cnpj_emitente, "
        "cnpj_destinatario, vl_doc, vl_icms, qtd_itens, prot_cstat, status) "
        "VALUES (?, ?, ?, '1', ?, ?, 100.0, 17.0, ?, '100', 'active')",
        (file_id, chave, chave[25:34], "07550459000108", "12345678000199", qtd_itens),
    )
    db.commit()


CHAVE = "32260107550459000108550010000000011000000011"


class TestXml012DispensaNfePropriaSaida:
    def test_nfe_propria_saida_sem_c170_nao_gera_xml012(self, db):
        """Excecao 2 GP EFD v3.2.2: NF-e propria (cod_mod=55, ind_emit=0) sem C170
        nao deve gerar XML012, mesmo que o XML tenha itens."""
        fid = _seed_file(db)
        _insert_0000(db, fid)
        _insert_c100(db, fid, 10, CHAVE, ind_emit="0", cod_mod="55")
        _insert_c190(db, fid, 11)
        _insert_xml(db, fid, CHAVE, qtd_itens=3)  # XML tem 3 itens, SPED tem 0 C170

        findings = cruzar_xml_vs_sped(db, fid)
        xml012 = [f for f in findings if f.get("rule_id") == "XML012"]
        assert not xml012, (
            f"XML012 nao deve ser gerado (Excecao 2 GP EFD v3.2.2). Findings: {xml012}"
        )

    def test_nfe_propria_com_c177_exige_c170(self, db):
        """Se ha C177 filho (info complementar item), C170 volta a ser obrigatorio
        (Excecao 10 do C100). XML012 deve ser gerado se C170 ausente."""
        fid = _seed_file(db)
        _insert_0000(db, fid)
        _insert_c100(db, fid, 10, CHAVE, ind_emit="0", cod_mod="55")
        _insert_c177(db, fid, 11)  # C177 filho — exige C170
        _insert_c190(db, fid, 12)
        _insert_xml(db, fid, CHAVE, qtd_itens=1)

        findings = cruzar_xml_vs_sped(db, fid)
        xml012 = [f for f in findings if f.get("rule_id") == "XML012"]
        assert xml012, "XML012 DEVE ser gerado quando ha C177 sem C170 correspondente"

    def test_nfe_terceiros_entrada_sem_c170_gera_xml012(self, db):
        """NF-e de terceiros (ind_emit=1) ou entrada nao tem dispensa. XML012 normal."""
        fid = _seed_file(db)
        _insert_0000(db, fid)
        _insert_c100(db, fid, 10, CHAVE, ind_emit="1", cod_mod="55")  # terceiros
        _insert_c190(db, fid, 11)
        _insert_xml(db, fid, CHAVE, qtd_itens=2)

        findings = cruzar_xml_vs_sped(db, fid)
        xml012 = [f for f in findings if f.get("rule_id") == "XML012"]
        assert xml012, "XML012 deve ser gerado para NF-e de terceiros sem C170"
