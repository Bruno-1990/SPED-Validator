"""Testes para alíquotas internas por UF."""

import pytest
from src.services.reference_loader import get_aliquota_interna_uf, load_aliquotas_internas_uf


def test_aliquota_sp():
    assert get_aliquota_interna_uf("SP") == 18.0


def test_aliquota_pa():
    assert get_aliquota_interna_uf("PA") == 17.0


def test_aliquota_rj():
    assert get_aliquota_interna_uf("RJ") == 20.0


def test_aliquota_pr():
    assert get_aliquota_interna_uf("PR") == 19.0


def test_aliquota_desconhecida_usa_default():
    assert get_aliquota_interna_uf("XX", default=17.0) == 17.0


def test_todas_ufs_carregadas():
    tabela = load_aliquotas_internas_uf()
    ufs_obrigatorias = {"SP", "RJ", "MG", "RS", "PR", "SC", "BA", "GO", "AM", "ES"}
    for uf in ufs_obrigatorias:
        assert uf in tabela, f"UF {uf} não encontrada na tabela"
        assert 15.0 <= tabela[uf] <= 25.0, f"Alíquota de {uf} fora do range esperado"


def test_am_20_percent():
    assert get_aliquota_interna_uf("AM") == 20.0


def test_ce_20_percent():
    assert get_aliquota_interna_uf("CE") == 20.0
