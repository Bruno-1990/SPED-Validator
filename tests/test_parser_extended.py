"""Extended tests for src/parser.py — covering uncovered lines.

Targets:
- _detect_encoding (line 52-59): encoding fallback logic
- parse_file_streaming (lines 75-109): streaming + batch persistence
- _persist_batch (lines 114-120): batch insert
- _read_with_fallback (lines 129-132): fallback to replace mode
- get_register_hierarchy (lines 143-174): parent/child hierarchy
- _register_level (lines 177-199): level classification
- parse_sped_file edge cases (empty line, line without pipe, short parts)
"""

from __future__ import annotations

import json
import sqlite3
import warnings
from pathlib import Path

warnings.filterwarnings(
    "ignore",
    message='Field name "register".*shadows an attribute',
    category=UserWarning,
)


from src.models import SpedRecord  # noqa: E402
from src.parser import (  # noqa: E402
    _detect_encoding,
    _read_with_fallback,
    _register_level,
    get_register_hierarchy,
    group_by_register,
    parse_file_streaming,
    parse_sped_file,
)

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _write_sped(tmp_path: Path, content: str, encoding: str = "latin-1",
                filename: str = "test.txt") -> Path:
    fp = tmp_path / filename
    fp.write_bytes(content.encode(encoding))
    return fp


def _create_streaming_db() -> sqlite3.Connection:
    """Create in-memory db with sped_records table for streaming."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sped_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL,
            line_number INTEGER NOT NULL,
            register TEXT NOT NULL,
            block TEXT NOT NULL,
            fields_json TEXT NOT NULL,
            raw_line TEXT NOT NULL
        )
    """)
    return conn


# ──────────────────────────────────────────────
# Tests: parse_sped_file edge cases
# ──────────────────────────────────────────────

class TestParseSped:
    def test_empty_file(self, tmp_path):
        fp = _write_sped(tmp_path, "")
        records = parse_sped_file(fp)
        assert records == []

    def test_lines_without_pipe(self, tmp_path):
        fp = _write_sped(tmp_path, "no pipes here\nstill no pipes\n")
        records = parse_sped_file(fp)
        assert records == []

    def test_blank_lines_skipped(self, tmp_path):
        content = "\n\n|C100|0|0|P001|55|00|1|100||01012024||1000|\n\n"
        fp = _write_sped(tmp_path, content)
        records = parse_sped_file(fp)
        assert len(records) == 1
        assert records[0].register == "C100"
        assert records[0].line_number == 3

    def test_short_parts(self, tmp_path):
        """A line with just || should produce empty parts and be skipped."""
        content = "||\n|C100|0|\n"
        fp = _write_sped(tmp_path, content)
        records = parse_sped_file(fp)
        # || produces ['', '', ''] -> parts[1:-1] = [''] -> register = ''
        # |C100|0| -> register = C100
        assert any(r.register == "C100" for r in records)

    def test_normal_parsing(self, tmp_path):
        content = (
            "|0000|017|0|01012024|31012024|Empresa|12345678000195||SP|123|3550308||||||A|0|\n"
            "|C100|1|0|P001|55|00|1|100||01012024||1000||\n"
        )
        fp = _write_sped(tmp_path, content)
        records = parse_sped_file(fp)
        assert len(records) == 2
        assert records[0].register == "0000"
        assert records[1].register == "C100"


# ──────────────────────────────────────────────
# Tests: _detect_encoding
# ──────────────────────────────────────────────

class TestDetectEncoding:
    def test_latin1_default(self, tmp_path):
        fp = _write_sped(tmp_path, "|0000|teste|", encoding="latin-1")
        enc = _detect_encoding(fp)
        assert enc == "latin-1"

    def test_utf8_file(self, tmp_path):
        # Write a file with only ASCII chars — all encodings will match,
        # latin-1 comes first in the list
        fp = _write_sped(tmp_path, "|0000|teste|", encoding="utf-8")
        enc = _detect_encoding(fp)
        # ASCII is valid in all encodings, so latin-1 wins (first in list)
        assert enc == "latin-1"

    def test_file_with_accents(self, tmp_path):
        # latin-1 handles most accented chars
        content = "|0000|Empresa Acucar e Alcool|"
        fp = _write_sped(tmp_path, content, encoding="latin-1")
        enc = _detect_encoding(fp)
        assert enc == "latin-1"


# ──────────────────────────────────────────────
# Tests: _read_with_fallback
# ──────────────────────────────────────────────

class TestReadWithFallback:
    def test_reads_latin1(self, tmp_path):
        content = "|0000|cafe com leite|"
        fp = _write_sped(tmp_path, content, encoding="latin-1")
        result = _read_with_fallback(fp)
        assert "cafe com leite" in result

    def test_reads_utf8(self, tmp_path):
        content = "|0000|utf8 data|"
        fp = _write_sped(tmp_path, content, encoding="utf-8")
        result = _read_with_fallback(fp)
        assert "utf8 data" in result

    def test_binary_data_falls_through(self, tmp_path):
        """File with invalid bytes in all encodings still returns something."""
        fp = tmp_path / "binary.txt"
        # Write bytes that are valid in latin-1 (all single bytes are valid)
        fp.write_bytes(b"|0000|\xff\xfe|")
        result = _read_with_fallback(fp)
        assert "|0000|" in result


# ──────────────────────────────────────────────
# Tests: parse_file_streaming
# ──────────────────────────────────────────────

class TestParseFileStreaming:
    def test_streaming_persists_records(self, tmp_path):
        content = (
            "|0000|017|0|01012024|31012024|Empresa|12345678000195|\n"
            "|C100|1|0|P001|55|00|1|100||01012024||1000|\n"
            "|C170|1|ITEM1|Prod|10|UN|1000|\n"
        )
        fp = _write_sped(tmp_path, content)
        db = _create_streaming_db()

        totals = list(parse_file_streaming(fp, file_id=1, db=db, batch_size=1000))
        # All records in one batch (< batch_size)
        assert len(totals) == 1
        assert totals[0] == 3

        rows = db.execute("SELECT COUNT(*) FROM sped_records").fetchone()[0]
        assert rows == 3
        db.close()

    def test_streaming_multiple_batches(self, tmp_path):
        """With small batch_size, should yield multiple times."""
        lines = [f"|C170|{i}|ITEM{i}|Prod|10|UN|1000|" for i in range(5)]
        content = "\n".join(lines) + "\n"
        fp = _write_sped(tmp_path, content)
        db = _create_streaming_db()

        totals = list(parse_file_streaming(fp, file_id=1, db=db, batch_size=2))
        # 5 records with batch_size=2 => yields at 2, 4, then 5 (remainder)
        assert len(totals) == 3
        assert totals[0] == 2
        assert totals[1] == 4
        assert totals[2] == 5

        rows = db.execute("SELECT COUNT(*) FROM sped_records").fetchone()[0]
        assert rows == 5
        db.close()

    def test_streaming_skips_empty_lines(self, tmp_path):
        content = "\n\n|0000|017|\n\n|C100|1|\n\n"
        fp = _write_sped(tmp_path, content)
        db = _create_streaming_db()

        totals = list(parse_file_streaming(fp, file_id=1, db=db))
        assert totals[-1] == 2
        db.close()

    def test_streaming_fields_json(self, tmp_path):
        content = "|C190|000|5102|18|1000|1000|180|0|0|0|0||\n"
        fp = _write_sped(tmp_path, content)
        db = _create_streaming_db()

        list(parse_file_streaming(fp, file_id=1, db=db))

        row = db.execute(
            "SELECT register, fields_json FROM sped_records WHERE file_id = 1"
        ).fetchone()
        assert row[0] == "C190"
        fields = json.loads(row[1])
        assert fields["CST_ICMS"] == "000"
        db.close()

    def test_streaming_empty_file(self, tmp_path):
        fp = _write_sped(tmp_path, "")
        db = _create_streaming_db()

        totals = list(parse_file_streaming(fp, file_id=1, db=db))
        assert totals == []
        db.close()


# ──────────────────────────────────────────────
# Tests: get_register_hierarchy
# ──────────────────────────────────────────────

class TestGetRegisterHierarchy:
    def _make_rec(self, register: str, line: int) -> SpedRecord:
        from src.models import SpedRecord
        return SpedRecord(
            line_number=line, register=register,
            fields={"REG": register}, raw_line=f"|{register}|",
        )

    def test_basic_hierarchy(self):
        records = [
            self._make_rec("C001", 1),  # block open (level 1)
            self._make_rec("C100", 2),  # parent (level 2)
            self._make_rec("C170", 3),  # child (level 3)
            self._make_rec("C170", 4),  # child
            self._make_rec("C190", 5),  # child
            self._make_rec("C100", 6),  # new parent
            self._make_rec("C170", 7),  # child
            self._make_rec("C990", 8),  # block close (level 1)
        ]
        hierarchy = get_register_hierarchy(records)
        assert len(hierarchy) == 2
        # First parent C100 at line 2 with 3 children
        assert hierarchy[0][0].line_number == 2
        assert len(hierarchy[0][1]) == 3
        # Second parent C100 at line 6 with 1 child
        assert hierarchy[1][0].line_number == 6
        assert len(hierarchy[1][1]) == 1

    def test_empty_records(self):
        assert get_register_hierarchy([]) == []

    def test_only_block_records(self):
        records = [
            self._make_rec("C001", 1),
            self._make_rec("C990", 2),
        ]
        hierarchy = get_register_hierarchy(records)
        assert hierarchy == []

    def test_parent_without_children(self):
        records = [
            self._make_rec("C100", 1),
            self._make_rec("C100", 2),
        ]
        hierarchy = get_register_hierarchy(records)
        assert len(hierarchy) == 2
        assert len(hierarchy[0][1]) == 0
        assert len(hierarchy[1][1]) == 0


# ──────────────────────────────────────────────
# Tests: _register_level
# ──────────────────────────────────────────────

class TestRegisterLevel:
    def test_block_open_close(self):
        assert _register_level("C001") == 1
        assert _register_level("C990") == 1
        assert _register_level("9999") == 1
        assert _register_level("0000") == 1
        assert _register_level("0001") == 1
        assert _register_level("9900") == 2  # 9900 % 100 == 0, so parent level

    def test_parent_level(self):
        assert _register_level("C100") == 2
        assert _register_level("D100") == 2
        assert _register_level("E100") == 2
        assert _register_level("C500") == 2

    def test_child_level(self):
        assert _register_level("C170") == 3
        assert _register_level("C190") == 3
        assert _register_level("D150") == 3

    def test_empty_or_short(self):
        assert _register_level("") == 0
        assert _register_level("A") == 0

    def test_non_numeric(self):
        assert _register_level("XABC") == 0


# ──────────────────────────────────────────────
# Tests: group_by_register
# ──────────────────────────────────────────────

class TestGroupByRegister:
    def _make_rec(self, register: str, line: int = 1) -> SpedRecord:
        from src.models import SpedRecord
        return SpedRecord(
            line_number=line, register=register,
            fields={"REG": register}, raw_line=f"|{register}|",
        )

    def test_groups_correctly(self):
        records = [
            self._make_rec("C100", 1),
            self._make_rec("C170", 2),
            self._make_rec("C100", 3),
            self._make_rec("C190", 4),
        ]
        groups = group_by_register(records)
        assert len(groups["C100"]) == 2
        assert len(groups["C170"]) == 1
        assert len(groups["C190"]) == 1

    def test_empty_list(self):
        assert group_by_register([]) == {}
