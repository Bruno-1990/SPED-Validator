"""Testes para alíquotas internas por UF.

Os valores esperados sao lidos do arquivo de referencia (aliquotas_internas_uf.yaml)
para que os testes nunca fiquem desatualizados quando as aliquotas mudarem.
"""

import pytest
from src.services.reference_loader import get_aliquota_interna_uf, load_aliquotas_internas_uf


# Carrega a tabela de referencia uma unica vez — fonte de verdade
_TABELA = load_aliquotas_internas_uf()


def test_tabela_carregada():
    """A tabela deve carregar com pelo menos 27 UFs."""
    assert len(_TABELA) >= 27, f"Tabela carregou apenas {len(_TABELA)} UFs"


def test_todas_ufs_obrigatorias_presentes():
    ufs_obrigatorias = {
        "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO",
        "MA", "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR",
        "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
    }
    for uf in ufs_obrigatorias:
        assert uf in _TABELA, f"UF {uf} não encontrada na tabela de referência"


def test_aliquotas_dentro_do_range_legal():
    """Alíquotas internas devem estar entre 15% e 25% (range constitucional)."""
    for uf, aliq in _TABELA.items():
        assert 15.0 <= aliq <= 25.0, (
            f"Alíquota de {uf} = {aliq}% fora do range constitucional [15%, 25%]"
        )


@pytest.mark.parametrize("uf", ["SP", "RJ", "MG", "RS", "PR", "SC", "BA", "GO", "AM", "ES", "PA", "CE"])
def test_aliquota_por_uf_bate_com_referencia(uf):
    """O valor retornado por get_aliquota_interna_uf deve bater com a tabela YAML."""
    esperado = _TABELA[uf]
    obtido = get_aliquota_interna_uf(uf)
    assert obtido == esperado, (
        f"UF {uf}: get_aliquota_interna_uf retornou {obtido}, "
        f"mas a tabela de referência tem {esperado}"
    )


def test_aliquota_desconhecida_usa_default():
    assert get_aliquota_interna_uf("XX", default=17.0) == 17.0


def test_aliquota_case_insensitive():
    """Deve funcionar com minúsculas."""
    assert get_aliquota_interna_uf("sp") == _TABELA["SP"]
