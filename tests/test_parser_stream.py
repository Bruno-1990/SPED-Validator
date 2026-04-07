"""Testes para parse_sped_file_stream — parser com streaming."""

import pytest
from pathlib import Path
from src.parser import parse_sped_file_stream


MINIMAL_SPED = """|0000|017|0|01012024|31012024|EMPRESA LTDA|12345678000190||ES|29|6210800|6210800|00000000000000000||A|1|
|0001|0|
|0990|2|
|9001|0|
|9900|0000|1|
|9990|1|
|9999|6|
"""


def test_stream_yields_records(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text(MINIMAL_SPED, encoding="latin-1")
    records = list(parse_sped_file_stream(str(f)))
    assert len(records) > 0
    assert records[0].register == "0000"


def test_stream_raises_on_file_too_large(tmp_path):
    f = tmp_path / "big.txt"
    f.write_text(MINIMAL_SPED, encoding="latin-1")
    with pytest.raises(ValueError, match="muito grande"):
        list(parse_sped_file_stream(str(f), max_bytes=1))


def test_stream_raises_on_missing_file():
    with pytest.raises(FileNotFoundError):
        list(parse_sped_file_stream("/nao/existe.txt"))


def test_stream_memory_efficient(tmp_path):
    lines = ["|0000|017|0|01012024|31012024|EMP|12345678000190||ES|29|6210800|6210800|||A|1|"]
    for i in range(1000):
        lines.append(f"|C170|{i}|ITEM{i}|DESC|100|UN|10.00|0|0|00|5101||1000.00|18.00|180.00|||||||||||||||||||||||")
    f = tmp_path / "large.txt"
    f.write_text("\n".join(lines), encoding="latin-1")

    gen = parse_sped_file_stream(str(f))
    first = next(gen)
    assert first.register == "0000"


def test_stream_encoding_detection(tmp_path):
    f = tmp_path / "latin.txt"
    f.write_bytes("|0000|017|0||||||EMPRESA LTDA com acentuação|||||||A|1|\n".encode("latin-1"))
    records = list(parse_sped_file_stream(str(f)))
    assert any(r.register == "0000" for r in records)


def test_stream_fields_are_dict(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text(MINIMAL_SPED, encoding="latin-1")
    records = list(parse_sped_file_stream(str(f)))
    assert isinstance(records[0].fields, dict)
    assert records[0].fields.get("REG") == "0000"
