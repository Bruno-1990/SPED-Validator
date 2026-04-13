"""Formatação de valores e reconstrução de linha SPED (pipe) por layout EFD."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from ..validators.helpers import REGISTER_FIELDS


def rebuild_raw_line(register: str, fields: dict[str, str]) -> str:
    """Monta raw_line na ordem oficial do registro (REGISTER_FIELDS)."""
    names = REGISTER_FIELDS.get(register, [])
    if not names:
        return "|" + "|".join(fields.values()) + "|"
    parts = [str(fields.get(n, "") or "") for n in names]
    return "|" + "|".join(parts) + "|"


def ordered_fields_dict(register: str, fields: dict[str, str]) -> dict[str, str]:
    """Garante dict na mesma ordem do leiaute (útil para JSON estável)."""
    names = REGISTER_FIELDS.get(register, [])
    if not names:
        return dict(fields)
    out: dict[str, str] = {}
    for n in names:
        if n in fields:
            out[n] = fields[n]
        else:
            out[n] = ""
    # Preserva campos extras não listados (defensivo)
    for k, v in fields.items():
        if k not in out:
            out[k] = v
    return out


def _decimal_from_any(s: str) -> Decimal | None:
    t = (s or "").strip().replace(" ", "")
    if not t:
        return None
    if "," in t and "." not in t:
        t = t.replace(",", ".")
    elif "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


def format_value_for_sped_field(
    register: str,
    field_name: str,
    new_value: str,
    old_value: str,
) -> str:
    """Normaliza new_value para o estilo já usado no registro (vírgula vs ponto em números, DDMMAAAA em datas)."""
    fn = (field_name or "").upper()
    old = old_value or ""

    if fn in ("DT_DOC", "DT_E_S", "DT_INI", "DT_FIN", "DT_OPER"):
        return _to_sped_date(new_value, old)

    if fn.startswith("VL_") or fn in (
        "ALIQ_ICMS", "ALIQ_ST", "ALIQ_IPI", "VL_ITEM", "QTD",
        "VL_BC_ICMS", "VL_BC_ICMS_ST", "VL_BC_IPI", "VL_BC_PIS", "VL_BC_COFINS",
    ):
        return _to_sped_decimal_string(new_value, old)

    return (new_value or "").strip()


def _to_sped_decimal_string(new_value: str, old_sample: str) -> str:
    d = _decimal_from_any(new_value)
    if d is None:
        return (new_value or "").strip()
    use_comma = "," in (old_sample or "") and "." not in (old_sample or "").replace(",", "")
    s = f"{d:.2f}"
    if use_comma:
        return s.replace(".", ",")
    return s


def _to_sped_date(new_value: str, old_sample: str) -> str:
    """Converte ISO AAAA-MM-DD ou similar para DDMMAAAA; se já for 8 dígitos, repassa."""
    s = (new_value or "").strip()
    if re.fullmatch(r"\d{8}", s):
        return s
    # ISO date prefix
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        y, mo, da = m.group(1), m.group(2), m.group(3)
        return f"{da}{mo}{y}"
    # Já estilo BR curto
    if len(s) >= 8 and s[2] == "/" and s[5] == "/":
        parts = s.split("/")
        if len(parts) == 3:
            return f"{parts[0].zfill(2)}{parts[1].zfill(2)}{parts[2].zfill(4)}"
    if len(old_sample or "") == 8 and (old_sample or "").isdigit():
        return old_sample or ""
    return s[:8] if len(s) == 8 and s.isdigit() else s
