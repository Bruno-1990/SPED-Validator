"""Testes com cenários fiscais representativos."""

import pytest
from pathlib import Path
from src.parser import parse_sped_file

FIXTURES = Path("tests/fixtures")


def test_simples_nacional_sem_erros():
    records = parse_sped_file(str(FIXTURES / "sped_simples_nacional.txt"))
    assert records is not None
    assert len(records) > 0
    assert any(r.register == "0000" for r in records)


def test_simples_nacional_erros_parseia():
    records = parse_sped_file(str(FIXTURES / "sped_simples_nacional_erros.txt"))
    assert records is not None
    assert len(records) > 0
    # Deve ter registros C170 com CST 00 (erro para SN)
    c170s = [r for r in records if r.register == "C170"]
    csts = {r.fields.get("CST_ICMS", "") for r in c170s}
    assert "00" in csts  # CST Tabela A indevido em SN


def test_regime_normal_icms_st_parseia():
    records = parse_sped_file(str(FIXTURES / "sped_regime_normal_icms_st.txt"))
    assert records is not None
    c170s = [r for r in records if r.register == "C170"]
    assert any(r.fields.get("CST_ICMS") == "10" for r in c170s)


def test_exportacao_parseia():
    records = parse_sped_file(str(FIXTURES / "sped_exportacao.txt"))
    assert records is not None
    c170s = [r for r in records if r.register == "C170"]
    assert any(r.fields.get("CFOP") == "7101" for r in c170s)


def test_devolucao_parseia():
    records = parse_sped_file(str(FIXTURES / "sped_devolucao.txt"))
    assert records is not None
    c170s = [r for r in records if r.register == "C170"]
    cfops = {r.fields.get("CFOP", "") for r in c170s}
    assert "5101" in cfops
    assert "1201" in cfops


def test_erros_multiplos_parseia():
    records = parse_sped_file(str(FIXTURES / "sped_erros_multiplos.txt"))
    assert records is not None
    assert len(records) > 0


def test_todos_fixtures_parseiam_sem_erro():
    for fixture in sorted(FIXTURES.glob("sped_*.txt")):
        records = parse_sped_file(str(fixture))
        assert records is not None, f"Falhou ao parsear {fixture.name}"
        assert len(records) > 0, f"Nenhum registro em {fixture.name}"
