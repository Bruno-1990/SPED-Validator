"""Sistema de tolerâncias parametrizadas por tipo de comparação (MOD-03).

Cada tipo de recálculo usa uma tolerância adequada à sua natureza:
- Itens individuais (C170): tolerância fixa pequena
- Consolidações (C190 vs C170): cresce com sqrt(n) de itens
- Apuração (E110): tolerância maior por envolver múltiplos registros
- Inventário (H010): tolerância mais generosa
"""

from __future__ import annotations

from collections.abc import Callable

ToleranceValue = float | Callable[[int], float]

TOLERANCES: dict[str, ToleranceValue] = {
    # Comparações item a item (C170)
    "item_icms": 0.01,       # BC * ALIQ/100 vs VL_ICMS por item
    "item_ipi": 0.01,        # BC * ALIQ/100 vs VL_IPI por item
    "item_pis": 0.01,        # BC * ALIQ/100 vs VL_PIS por item
    "item_cofins": 0.01,     # BC * ALIQ/100 vs VL_COFINS por item
    # Comparações de documento (C100)
    "doc_vl_doc": 0.02,      # Soma de componentes vs VL_DOC
    # Comparações de consolidação (C190 vs soma C170)
    "consolidacao": lambda n: max(0.02, 0.01 * (n ** 0.5)),
                              # n = número de itens. Para 100 itens: 0.10
    # Comparações de apuração (E110)
    "apuracao_e110": 0.05,   # Soma C190+D690 vs E110
    # Comparações de inventário (H010)
    "inventario": 0.10,
}


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
