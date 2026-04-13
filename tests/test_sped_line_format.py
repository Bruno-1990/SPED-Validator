"""Reconstrução de linha SPED e formatação de valores."""

from __future__ import annotations

from src.services.sped_line_format import format_value_for_sped_field, rebuild_raw_line
from src.validators.helpers import REGISTER_FIELDS, fields_to_dict


def test_rebuild_raw_line_ordem_c100() -> None:
    ch = "1" * 44
    fields_list = [
        "C100", "0", "0", "", "55", "00", "1", "1", ch,
        "01012024", "", "100,00",
        "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0",
    ]
    assert len(fields_list) == len(REGISTER_FIELDS["C100"])
    d = fields_to_dict("C100", fields_list)
    d["VL_DOC"] = "200,50"
    raw = rebuild_raw_line("C100", d)
    parts = raw.strip("|").split("|")
    assert parts[REGISTER_FIELDS["C100"].index("VL_DOC")] == "200,50"


def test_format_decimal_respeita_virgula() -> None:
    s = format_value_for_sped_field("C100", "VL_DOC", "1234.5", "99,00")
    assert "," in s
    assert "1234" in s.replace(",", ".")


def test_format_data_iso_para_sped() -> None:
    s = format_value_for_sped_field("C100", "DT_DOC", "2024-03-05T12:00:00", "05032024")
    assert s == "05032024"
