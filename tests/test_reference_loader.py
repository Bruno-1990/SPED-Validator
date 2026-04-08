"""Testes do MOD-14: ReferenceLoader — tabelas de referência externas."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.services.reference_loader import ReferenceLoader

# ── Fixtures ──

@pytest.fixture
def loader() -> ReferenceLoader:
    """ReferenceLoader usando o diretório data/reference/ real do projeto."""
    return ReferenceLoader()


@pytest.fixture
def empty_loader(tmp_path: Path) -> ReferenceLoader:
    """ReferenceLoader apontando para diretório vazio (sem tabelas)."""
    return ReferenceLoader(data_dir=tmp_path)


# ──────────────────────────────────────────────
# Testes de municípios (ibge_municipios.yaml)
# ──────────────────────────────────────────────

class TestMunicipios:
    def test_municipio_valido_sp(self, loader: ReferenceLoader) -> None:
        """São Paulo (3550308) deve ser válido."""
        assert loader.is_municipio_valido("3550308") is True

    def test_municipio_valido_rj(self, loader: ReferenceLoader) -> None:
        """Rio de Janeiro (3304557) deve ser válido."""
        assert loader.is_municipio_valido("3304557") is True

    def test_municipio_valido_manaus(self, loader: ReferenceLoader) -> None:
        """Manaus (1302603) deve ser válido."""
        assert loader.is_municipio_valido("1302603") is True

    def test_municipio_valido_brasilia(self, loader: ReferenceLoader) -> None:
        """Brasília (5300108) deve ser válida."""
        assert loader.is_municipio_valido("5300108") is True

    def test_codigo_ficticio_invalido(self, loader: ReferenceLoader) -> None:
        """Código fictício (9999999) deve ser inválido."""
        assert loader.is_municipio_valido("9999999") is False

    def test_codigo_ficticio_regiao_valida(self, loader: ReferenceLoader) -> None:
        """Código fictício com primeiro dígito válido mas inexistente na tabela."""
        assert loader.is_municipio_valido("3599999") is False

    def test_sem_tabela_fallback_permissivo(self, empty_loader: ReferenceLoader) -> None:
        """Sem tabela de municípios, deve retornar True (fallback)."""
        assert empty_loader.is_municipio_valido("9999999") is True

    def test_has_municipios_table(self, loader: ReferenceLoader) -> None:
        assert loader.has_municipios_table() is True

    def test_has_municipios_table_empty(self, empty_loader: ReferenceLoader) -> None:
        assert empty_loader.has_municipios_table() is False


# ──────────────────────────────────────────────
# Testes de NCM tributação
# ──────────────────────────────────────────────

class TestNCMTributacao:
    def test_gasolina_monofasico(self, loader: ReferenceLoader) -> None:
        assert loader.get_ncm_tributacao("27101159") == "monofasico"

    def test_cigarro_monofasico(self, loader: ReferenceLoader) -> None:
        assert loader.get_ncm_tributacao("24022000") == "monofasico"

    def test_medicamento_isento(self, loader: ReferenceLoader) -> None:
        assert loader.get_ncm_tributacao("30049099") == "isento"

    def test_arroz_isento(self, loader: ReferenceLoader) -> None:
        assert loader.get_ncm_tributacao("10063011") == "isento"

    def test_notebook_normal(self, loader: ReferenceLoader) -> None:
        assert loader.get_ncm_tributacao("84713012") == "normal"

    def test_ncm_desconhecido_none(self, loader: ReferenceLoader) -> None:
        assert loader.get_ncm_tributacao("00000000") is None

    def test_ncm_nt(self, loader: ReferenceLoader) -> None:
        assert loader.get_ncm_tributacao("01012100") == "nt"


# ──────────────────────────────────────────────
# Testes de FCP
# ──────────────────────────────────────────────

class TestFCP:
    def test_rj_fcp_2(self, loader: ReferenceLoader) -> None:
        """RJ tem FCP de 2%."""
        assert loader.get_fcp("RJ") == 2.0

    def test_ba_fcp_2(self, loader: ReferenceLoader) -> None:
        """BA tem FCP de 2%."""
        assert loader.get_fcp("BA") == 2.0

    def test_pi_fcp_1(self, loader: ReferenceLoader) -> None:
        """PI tem FCP de 1%."""
        assert loader.get_fcp("PI") == 1.0

    def test_sp_fcp_zero(self, loader: ReferenceLoader) -> None:
        """SP não tem FCP."""
        assert loader.get_fcp("SP") == 0.0

    def test_uf_inexistente(self, loader: ReferenceLoader) -> None:
        """UF inexistente retorna 0.0."""
        assert loader.get_fcp("XX") == 0.0


# ──────────────────────────────────────────────
# Testes de alíquota interna
# ──────────────────────────────────────────────

class TestAliquotaInterna:
    def test_sp_18(self, loader: ReferenceLoader) -> None:
        assert loader.get_aliquota_interna("SP") == 18.0

    def test_rj_20(self, loader: ReferenceLoader) -> None:
        assert loader.get_aliquota_interna("RJ") == 20.0

    def test_uf_inexistente_none(self, loader: ReferenceLoader) -> None:
        assert loader.get_aliquota_interna("XX") is None


# ──────────────────────────────────────────────
# Testes de matriz de alíquotas interestaduais
# ──────────────────────────────────────────────

class TestMatrizAliquotas:
    def test_sp_para_ba_7(self, loader: ReferenceLoader) -> None:
        """SP (Sul/Sudeste) para BA (Nordeste) = 7%."""
        assert loader.get_matriz_aliquota("SP", "BA") == 7.0

    def test_ba_para_sp_12(self, loader: ReferenceLoader) -> None:
        """BA (Nordeste) para SP (Sul/Sudeste) = 12%."""
        assert loader.get_matriz_aliquota("BA", "SP") == 12.0

    def test_sp_para_rj_12(self, loader: ReferenceLoader) -> None:
        """SP para RJ (ambos Sul/Sudeste) = 12%."""
        assert loader.get_matriz_aliquota("SP", "RJ") == 12.0

    def test_mesma_uf_none(self, loader: ReferenceLoader) -> None:
        """Mesma UF = operação interna, retorna None."""
        assert loader.get_matriz_aliquota("SP", "SP") is None

    def test_com_data(self, loader: ReferenceLoader) -> None:
        """Com data específica, deve funcionar."""
        result = loader.get_matriz_aliquota("MG", "CE", date(2024, 6, 1))
        assert result == 7.0


# ──────────────────────────────────────────────
# Testes de available_tables
# ──────────────────────────────────────────────

class TestAvailableTables:
    def test_tabelas_disponiveis(self, loader: ReferenceLoader) -> None:
        tables = loader.available_tables()
        assert "aliquotas_internas_uf" in tables
        assert "fcp_por_uf" in tables
        assert "ibge_municipios" in tables
        assert "ncm_tipi_categorias" in tables

    def test_vigencias_listadas(self, loader: ReferenceLoader) -> None:
        tables = loader.available_tables()
        vigencias = [t for t in tables if t.startswith("vigencias/")]
        assert len(vigencias) >= 1

    def test_diretorio_vazio(self, empty_loader: ReferenceLoader) -> None:
        tables = empty_loader.available_tables()
        # tabelas do sped.db independem do diretorio de YAMLs
        _DB_TABLES = {"ncm_vigente", "cst_vigente", "difal_vigente"}
        yaml_tables = [t for t in tables if t not in _DB_TABLES]
        assert yaml_tables == []
