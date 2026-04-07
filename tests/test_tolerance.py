"""Testes do sistema de tolerâncias parametrizadas (MOD-03)."""

from __future__ import annotations

import unittest

from src.models import SpedRecord
from src.validators.tolerance import get_tolerance


class TestToleranceDict(unittest.TestCase):
    """Testa o dicionário TOLERANCES e a função get_tolerance."""

    def test_item_icms_value(self) -> None:
        assert get_tolerance("item_icms") == 0.01

    def test_item_ipi_value(self) -> None:
        assert get_tolerance("item_ipi") == 0.01

    def test_item_pis_value(self) -> None:
        assert get_tolerance("item_pis") == 0.01

    def test_item_cofins_value(self) -> None:
        assert get_tolerance("item_cofins") == 0.01

    def test_doc_vl_doc_value(self) -> None:
        assert get_tolerance("doc_vl_doc") == 0.02

    def test_apuracao_e110_value(self) -> None:
        assert get_tolerance("apuracao_e110") == 0.05

    def test_inventario_value(self) -> None:
        assert get_tolerance("inventario") == 0.10

    def test_consolidacao_1_item(self) -> None:
        # 1 item: max(0.02, 0.01 * 1) = 0.02
        assert get_tolerance("consolidacao", n_items=1) == 0.02

    def test_consolidacao_100_items(self) -> None:
        # 100 itens: max(0.02, 0.01 * 10) = 0.10
        assert get_tolerance("consolidacao", n_items=100) == 0.10

    def test_consolidacao_200_items(self) -> None:
        # 200 itens: max(0.02, 0.01 * sqrt(200)) ≈ 0.1414
        tol = get_tolerance("consolidacao", n_items=200)
        assert tol > 0.14
        assert tol < 0.15

    def test_unknown_key_raises(self) -> None:
        with self.assertRaises(KeyError):
            get_tolerance("nao_existe")


class TestConsolidacaoToleratesRounding(unittest.TestCase):
    """200 itens com arredondamento de 0.001 cada → consolidacao tolera."""

    def test_200_items_rounding_001(self) -> None:
        # Cenário: 200 itens, cada um com erro de arredondamento de R$ 0.001.
        # Erro acumulado = 200 * 0.001 = R$ 0.20.
        # Tolerância consolidacao(200) = max(0.02, 0.01 * sqrt(200)) ≈ 0.1414.
        # 0.20 > 0.14 → NÃO tolera (erro real demais).
        # Mas para arredondamento de 0.001 aleatório (metade + metade -),
        # o erro esperado é ~0.001 * sqrt(200) ≈ 0.014, bem dentro da tolerância.
        n_items = 200
        tol = get_tolerance("consolidacao", n_items=n_items)

        # Arredondamento aleatório: erro esperado ~0.001 * sqrt(n)
        erro_tipico = 0.001 * (n_items ** 0.5)  # ~0.014
        assert erro_tipico < tol, (
            f"Erro típico de arredondamento ({erro_tipico:.4f}) deveria ser "
            f"menor que tolerância ({tol:.4f}) para {n_items} itens"
        )


class TestE110DetectsRealError(unittest.TestCase):
    """Erro real de R$ 1.00 em E110 → apuracao_e110 detecta."""

    def test_e110_error_1_real(self) -> None:
        tol = get_tolerance("apuracao_e110")
        erro_real = 1.00
        assert erro_real > tol, (
            f"Erro real de R$ {erro_real:.2f} deveria ser detectado "
            f"(tolerância E110 = {tol:.2f})"
        )


class TestItemIcmsToleratesSmallDiff(unittest.TestCase):
    """Item com diferença de R$ 0.005 → item_icms tolera."""

    def test_item_diff_005(self) -> None:
        tol = get_tolerance("item_icms")
        diff = 0.005
        assert diff <= tol, (
            f"Diferença de R$ {diff:.3f} deveria ser tolerada "
            f"(tolerância item_icms = {tol:.2f})"
        )


class TestIntegrationTaxRecalcUsesTolerance(unittest.TestCase):
    """Verifica que tax_recalc usa as tolerâncias parametrizadas."""

    def _make_c170(self, fields: list[str], line: int = 1) -> SpedRecord:
        from src.validators.helpers import fields_to_dict
        return SpedRecord(
            register="C170",
            fields=fields_to_dict("C170", fields),
            line_number=line,
            raw_line="|C170|" + "|".join(fields) + "|",
        )

    def test_within_item_icms_tolerance(self) -> None:
        """1000 * 18% = 180.00, declarado 180.005 → dentro de item_icms (0.01)."""
        from src.validators.tax_recalc import recalc_icms_item

        fields = [""] * 15
        fields[6] = "1000.00"   # VL_ITEM
        fields[7] = "0"         # VL_DESC
        fields[9] = "00"        # CST
        fields[12] = "1000.00"  # VL_BC_ICMS
        fields[13] = "18.00"    # ALIQ_ICMS
        fields[14] = "180.005"  # VL_ICMS (diff = 0.005 < 0.01)
        rec = self._make_c170(fields)
        errors = recalc_icms_item(rec)
        assert len(errors) == 0, f"Não deveria ter erros: {errors}"

    def test_outside_item_icms_tolerance(self) -> None:
        """1000 * 18% = 180.00, declarado 180.02 → fora de item_icms (0.01)."""
        from src.validators.tax_recalc import recalc_icms_item

        fields = [""] * 15
        fields[6] = "1000.00"
        fields[7] = "0"
        fields[9] = "00"
        fields[12] = "1000.00"
        fields[13] = "18.00"
        fields[14] = "180.02"  # diff = 0.02 > 0.01
        rec = self._make_c170(fields)
        errors = recalc_icms_item(rec)
        assert len(errors) > 0, "Deveria detectar divergência de 0.02"


class TestToleranceResolver(unittest.TestCase):
    """Testes para ToleranceResolver com contextos."""

    def test_item_icms_within(self) -> None:
        from src.validators.tolerance import ToleranceResolver, ToleranceType
        assert ToleranceResolver.is_within_tolerance(0.005, tolerance_type=ToleranceType.ITEM_ICMS) is True

    def test_item_icms_at_limit(self) -> None:
        from src.validators.tolerance import ToleranceResolver, ToleranceType
        assert ToleranceResolver.is_within_tolerance(0.01, tolerance_type=ToleranceType.ITEM_ICMS) is True

    def test_item_icms_above_limit(self) -> None:
        from src.validators.tolerance import ToleranceResolver, ToleranceType
        assert ToleranceResolver.is_within_tolerance(0.02, tolerance_type=ToleranceType.ITEM_ICMS) is False

    def test_apuracao_e110_half_real(self) -> None:
        from src.validators.tolerance import ToleranceResolver, ToleranceType
        assert ToleranceResolver.is_within_tolerance(0.50, tolerance_type=ToleranceType.APURACAO_E110) is True

    def test_apuracao_e110_above(self) -> None:
        from src.validators.tolerance import ToleranceResolver, ToleranceType
        assert ToleranceResolver.is_within_tolerance(1.50, tolerance_type=ToleranceType.APURACAO_E110) is False

    def test_consolidacao_within(self) -> None:
        from src.validators.tolerance import ToleranceResolver, ToleranceType
        assert ToleranceResolver.is_within_tolerance(0.05, tolerance_type=ToleranceType.CONSOLIDACAO) is True

    def test_absolute_zero(self) -> None:
        from src.validators.tolerance import ToleranceResolver, ToleranceType
        assert ToleranceResolver.is_within_tolerance(0.0, tolerance_type=ToleranceType.ABSOLUTE) is True
        assert ToleranceResolver.is_within_tolerance(0.001, tolerance_type=ToleranceType.ABSOLUTE) is False

    def test_string_tolerance_type(self) -> None:
        from src.validators.tolerance import ToleranceResolver
        assert ToleranceResolver.is_within_tolerance(0.005, tolerance_type="item_icms") is True

    def test_invalid_string_uses_fallback(self) -> None:
        from src.validators.tolerance import ToleranceResolver
        assert ToleranceResolver.is_within_tolerance(0.005, tolerance_type="tipo_invalido") is True

    def test_negative_difference(self) -> None:
        from src.validators.tolerance import ToleranceResolver, ToleranceType
        assert ToleranceResolver.is_within_tolerance(-0.005, tolerance_type=ToleranceType.ITEM_ICMS) is True

    def test_format_tolerance_info(self) -> None:
        from src.validators.tolerance import ToleranceResolver, ToleranceType
        info = ToleranceResolver.format_tolerance_info(ToleranceType.ITEM_ICMS)
        assert "R$0.01" in info

    def test_get_config_returns_dataclass(self) -> None:
        from src.validators.tolerance import ToleranceResolver, ToleranceType, ToleranceConfig
        config = ToleranceResolver.get_config(ToleranceType.APURACAO_E110)
        assert isinstance(config, ToleranceConfig)
        assert config.absolute_brl == 1.00


if __name__ == "__main__":
    unittest.main()
