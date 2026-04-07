"""Funções de conveniência para acesso a campos via FieldRegistry.

Use fval/fnum/fstr em todos os validadores para acesso seguro e nomeado.
"""

from __future__ import annotations

from .field_registry import FieldNotFoundError, get_registry


def fval(fields: list[str], register: str, field_name: str, default: str = "") -> str:
    """Shorthand para get_field_safe. Use em todos os validadores."""
    return get_registry().get_field_safe(fields, register, field_name, default)


def fnum(fields: list[str], register: str, field_name: str, default: float = 0.0) -> float:
    """Retorna campo como float. Retorna default se vazio ou não numérico."""
    val = fval(fields, register, field_name, "")
    if not val:
        return default
    try:
        return float(val.replace(",", "."))
    except ValueError:
        return default


def fstr(fields: list[str], register: str, field_name: str) -> str:
    """Retorna campo como string stripped."""
    return fval(fields, register, field_name, "").strip()
