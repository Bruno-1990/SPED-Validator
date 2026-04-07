"""Sistema de tolerâncias parametrizadas por tipo de comparação (MOD-03).

Cada tipo de recálculo usa uma tolerância adequada à sua natureza:
- Itens individuais (C170): tolerância fixa pequena
- Consolidações (C190 vs C170): cresce com sqrt(n) de itens
- Apuração (E110): tolerância maior por envolver múltiplos registros
- Inventário (H010): tolerância mais generosa
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

ToleranceValue = float | Callable[[int], float]


class ToleranceType(str, Enum):
    ITEM_ICMS = "item_icms"          # Cálculo ICMS por item (C170)
    ITEM_IPI = "item_ipi"            # Cálculo IPI por item (C170)
    ITEM_PIS = "item_pis"            # Cálculo PIS por item (C170)
    ITEM_COFINS = "item_cofins"      # Cálculo COFINS por item (C170)
    DOC_VL_DOC = "doc_vl_doc"        # Soma componentes vs VL_DOC (C100)
    CONSOLIDACAO = "consolidacao"    # C190 vs soma C170 (consolidação)
    APURACAO_E110 = "apuracao_e110"  # Apuração ICMS no E110
    INVENTARIO = "inventario"        # Inventário H010
    ABSOLUTE = "absolute"            # Comparação absoluta — zero tolerância
    NONE = "none"                    # Sem tolerância (exato)


@dataclass(frozen=True)
class ToleranceConfig:
    absolute_brl: float        # Tolerância absoluta em R$
    relative_pct: float        # Tolerância relativa em % do valor base (0.0 = desligada)
    description: str


# Mapa de configurações por tipo de contexto
_TOLERANCE_MAP: dict[ToleranceType, ToleranceConfig] = {
    ToleranceType.ITEM_ICMS: ToleranceConfig(
        absolute_brl=0.01,
        relative_pct=0.0,
        description="Cálculo ICMS por item — R$0,01 conforme prática SPED",
    ),
    ToleranceType.ITEM_IPI: ToleranceConfig(
        absolute_brl=0.01,
        relative_pct=0.0,
        description="Cálculo IPI por item",
    ),
    ToleranceType.ITEM_PIS: ToleranceConfig(
        absolute_brl=0.01,
        relative_pct=0.0,
        description="Cálculo PIS por item",
    ),
    ToleranceType.ITEM_COFINS: ToleranceConfig(
        absolute_brl=0.01,
        relative_pct=0.0,
        description="Cálculo COFINS por item",
    ),
    ToleranceType.DOC_VL_DOC: ToleranceConfig(
        absolute_brl=0.02,
        relative_pct=0.0,
        description="Soma de componentes vs VL_DOC no documento",
    ),
    ToleranceType.CONSOLIDACAO: ToleranceConfig(
        absolute_brl=0.10,
        relative_pct=0.0,
        description="Consolidação C190 vs C170 — acumula arredondamentos por item",
    ),
    ToleranceType.APURACAO_E110: ToleranceConfig(
        absolute_brl=1.00,
        relative_pct=0.0,
        description="Apuração E110 — acumulação de arredondamentos de múltiplos documentos",
    ),
    ToleranceType.INVENTARIO: ToleranceConfig(
        absolute_brl=0.10,
        relative_pct=0.0,
        description="Inventário H010 — tolerância generosa",
    ),
    ToleranceType.ABSOLUTE: ToleranceConfig(
        absolute_brl=0.0,
        relative_pct=0.0,
        description="Comparação exata — zero tolerância",
    ),
    ToleranceType.NONE: ToleranceConfig(
        absolute_brl=0.0,
        relative_pct=0.0,
        description="Sem tolerância",
    ),
}


class ToleranceResolver:
    """Resolve se uma diferença está dentro da tolerância para um dado contexto.

    Use is_within_tolerance() em todos os validadores de cálculo.
    """

    @staticmethod
    def get_config(tolerance_type: ToleranceType | str) -> ToleranceConfig:
        if isinstance(tolerance_type, str):
            try:
                tolerance_type = ToleranceType(tolerance_type)
            except ValueError:
                return _TOLERANCE_MAP[ToleranceType.ITEM_ICMS]  # fallback seguro
        return _TOLERANCE_MAP.get(tolerance_type, _TOLERANCE_MAP[ToleranceType.ITEM_ICMS])

    @staticmethod
    def is_within_tolerance(
        difference: float,
        base_value: float = 0.0,
        tolerance_type: ToleranceType | str = ToleranceType.ITEM_ICMS,
    ) -> bool:
        """Retorna True se a diferença está dentro da tolerância aceitável.

        difference: |calculado - declarado|
        base_value: valor de referência para tolerância relativa (ex: VL_ITEM)
        tolerance_type: contexto do cálculo
        """
        config = ToleranceResolver.get_config(tolerance_type)
        abs_diff = abs(difference)

        # Tolerância absoluta
        if abs_diff <= config.absolute_brl:
            return True

        # Tolerância relativa (se configurada)
        if config.relative_pct > 0.0 and base_value > 0:
            if abs_diff <= abs(base_value) * config.relative_pct:
                return True

        return False

    @staticmethod
    def format_tolerance_info(tolerance_type: ToleranceType | str) -> str:
        config = ToleranceResolver.get_config(tolerance_type)
        return f"Tolerância: R${config.absolute_brl:.2f} ({config.description})"


# ──────────────────────────────────────────────────────────
# Compatibilidade retroativa — mantém a API antiga
# ──────────────────────────────────────────────────────────

TOLERANCES: dict[str, ToleranceValue] = {
    "item_icms": 0.01,
    "item_ipi": 0.01,
    "item_pis": 0.01,
    "item_cofins": 0.01,
    "doc_vl_doc": 0.02,
    "consolidacao": lambda n: max(0.02, 0.01 * (n ** 0.5)),
    "apuracao_e110": 0.05,
    "inventario": 0.10,
}

CALCULATION_TOLERANCE = 0.02


def get_tolerance(comparison_type: str, n_items: int = 1) -> float:
    """Retorna a tolerância adequada para o tipo de comparação.

    Args:
        comparison_type: Chave do dicionário TOLERANCES.
        n_items: Número de itens (usado apenas para tipos callable como 'consolidacao').

    Returns:
        Tolerância em reais.
    """
    tol = TOLERANCES[comparison_type]
    return tol(n_items) if callable(tol) else tol
