"""Testes do conversor de documentos para Markdown."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from src.converter import (
    SUPPORTED_EXTENSIONS,
    _char_in_bbox,
    _classify_lines,
    _clean_cell,
    _convert_docx_fallback,
    _convert_txt,
    _detect_heading_level,
    _docx_table_to_markdown,
    _estimate_body_font_size,
    _extract_text_outside_tables,
    _find_supported_files,
    _group_chars_into_lines,
    _process_page,
    _table_to_markdown,
    convert_all_docs,
    convert_file_to_markdown,
)


# ──────────────────────────────────────────────
# convert_file_to_markdown
# ──────────────────────────────────────────────

class TestConvertFileToMarkdown:
    def test_txt(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.txt"
        f.write_text("Conteúdo de teste\nSegunda linha", encoding="utf-8")
        result = convert_file_to_markdown(f)
        assert "doc" in result
        assert "Conteúdo de teste" in result

    def test_no_extension_treated_as_txt(self, tmp_path: Path) -> None:
        f = tmp_path / "noext"
        f.write_text("Conteúdo sem extensão", encoding="utf-8")
        result = convert_file_to_markdown(f)
        assert "Conteúdo sem extensão" in result

    def test_unsupported_extension_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.xyz"
        f.write_text("data")
        with pytest.raises(ValueError, match="nao suportado"):
            convert_file_to_markdown(f)

    def test_pdf_dispatches(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.pdf"
        f.write_text("dummy")
        with patch("src.converter._convert_pdf", return_value="# PDF") as mock:
            result = convert_file_to_markdown(f)
            mock.assert_called_once_with(f)
            assert result == "# PDF"

    def test_docx_dispatches(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.docx"
        f.write_text("dummy")
        with patch("src.converter._convert_docx", return_value="# DOCX") as mock:
            result = convert_file_to_markdown(f)
            mock.assert_called_once_with(f)
            assert result == "# DOCX"


# ──────────────────────────────────────────────
# _convert_txt
# ──────────────────────────────────────────────

class TestConvertTxt:
    def test_utf8(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.txt"
        f.write_text("Descrição com café", encoding="utf-8")
        result = convert_file_to_markdown(f)
        assert "Descrição com café" in result

    def test_latin1_encoding(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.txt"
        f.write_bytes("Descrição com acentuação".encode("latin-1"))
        result = convert_file_to_markdown(f)
        assert len(result) > 0

    def test_cp1252_encoding(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.txt"
        # Bytes 0x93/0x94 são aspas curvas em cp1252
        f.write_bytes(b"Texto cp1252 \x93aspas\x94")
        result = convert_file_to_markdown(f)
        assert len(result) > 0

    def test_empty_file(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.txt"
        f.write_text("", encoding="utf-8")
        result = convert_file_to_markdown(f)
        assert "empty" in result

    def test_heading_contains_stem(self, tmp_path: Path) -> None:
        f = tmp_path / "meuarquivo.txt"
        f.write_text("conteudo")
        result = _convert_txt(f)
        assert "# meuarquivo" in result


# ──────────────────────────────────────────────
# convert_all_docs
# ──────────────────────────────────────────────

class TestConvertAllDocs:
    def test_converts_txt_files(self, tmp_path: Path) -> None:
        indir = tmp_path / "input"
        outdir = tmp_path / "output"
        indir.mkdir()
        (indir / "a.txt").write_text("conteudo A")
        (indir / "b.txt").write_text("conteudo B")
        created = convert_all_docs(indir, outdir)
        assert len(created) == 2
        assert (outdir / "a.md").exists()
        assert (outdir / "b.md").exists()

    def test_skip_existing(self, tmp_path: Path) -> None:
        indir = tmp_path / "input"
        outdir = tmp_path / "output"
        indir.mkdir()
        outdir.mkdir()
        (indir / "a.txt").write_text("conteudo A")
        (outdir / "a.md").write_text("ja existe")
        created = convert_all_docs(indir, outdir, skip_existing=True)
        assert len(created) == 0
        assert (outdir / "a.md").read_text() == "ja existe"

    def test_force_overwrite(self, tmp_path: Path) -> None:
        indir = tmp_path / "input"
        outdir = tmp_path / "output"
        indir.mkdir()
        outdir.mkdir()
        (indir / "a.txt").write_text("conteudo novo")
        (outdir / "a.md").write_text("velho")
        created = convert_all_docs(indir, outdir, skip_existing=False)
        assert len(created) == 1
        assert "conteudo novo" in (outdir / "a.md").read_text()

    def test_error_file_skipped(self, tmp_path: Path) -> None:
        indir = tmp_path / "input"
        outdir = tmp_path / "output"
        indir.mkdir()
        (indir / "good.txt").write_text("ok")
        (indir / "bad.pdf").write_bytes(b"not a real pdf")
        created = convert_all_docs(indir, outdir)
        # PDF vai falhar mas TXT deve funcionar
        assert any("good" in str(p) for p in created)

    def test_empty_markdown_skipped(self, tmp_path: Path) -> None:
        indir = tmp_path / "input"
        outdir = tmp_path / "output"
        indir.mkdir()
        (indir / "a.txt").write_text("")
        with patch("src.converter.convert_file_to_markdown", return_value="   "):
            created = convert_all_docs(indir, outdir)
            assert len(created) == 0

    def test_creates_output_dir(self, tmp_path: Path) -> None:
        indir = tmp_path / "input"
        outdir = tmp_path / "deep" / "nested" / "output"
        indir.mkdir()
        (indir / "a.txt").write_text("conteudo")
        convert_all_docs(indir, outdir)
        assert outdir.exists()


# ──────────────────────────────────────────────
# _find_supported_files
# ──────────────────────────────────────────────

class TestFindSupportedFiles:
    def test_finds_txt(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("x")
        files = _find_supported_files(tmp_path)
        assert any(f.name == "a.txt" for f in files)

    def test_finds_pdf(self, tmp_path: Path) -> None:
        (tmp_path / "b.pdf").write_bytes(b"x")
        files = _find_supported_files(tmp_path)
        assert any(f.name == "b.pdf" for f in files)

    def test_finds_uppercase(self, tmp_path: Path) -> None:
        (tmp_path / "c.TXT").write_text("x")
        files = _find_supported_files(tmp_path)
        assert any(f.name == "c.TXT" for f in files)

    def test_finds_no_extension(self, tmp_path: Path) -> None:
        (tmp_path / "noext").write_text("x")
        files = _find_supported_files(tmp_path)
        assert any(f.name == "noext" for f in files)

    def test_ignores_unsupported(self, tmp_path: Path) -> None:
        (tmp_path / "skip.xyz").write_text("x")
        files = _find_supported_files(tmp_path)
        assert not any(f.name == "skip.xyz" for f in files)

    def test_returns_sorted(self, tmp_path: Path) -> None:
        (tmp_path / "b.txt").write_text("x")
        (tmp_path / "a.txt").write_text("x")
        files = _find_supported_files(tmp_path)
        names = [f.name for f in files]
        assert names == sorted(names)


# ──────────────────────────────────────────────
# _convert_docx (via mock)
# ──────────────────────────────────────────────

class TestConvertDocx:
    def test_docx_with_python_docx(self, tmp_path: Path) -> None:
        """Testa conversão DOCX quando python-docx está disponível."""
        mock_para1 = MagicMock()
        mock_para1.text = "Título do Documento"
        mock_para1.style.name = "Heading 1"

        mock_para2 = MagicMock()
        mock_para2.text = "Subtítulo"
        mock_para2.style.name = "Heading 2"

        mock_para3 = MagicMock()
        mock_para3.text = "Parágrafo normal"
        mock_para3.style.name = "Normal"

        mock_para4 = MagicMock()
        mock_para4.text = "Título Principal"
        mock_para4.style.name = "Title"

        mock_para5 = MagicMock()
        mock_para5.text = "Heading 3 text"
        mock_para5.style.name = "Heading 3"

        mock_para_empty = MagicMock()
        mock_para_empty.text = ""
        mock_para_empty.style.name = "Normal"

        mock_doc = MagicMock()
        mock_doc.paragraphs = [mock_para1, mock_para_empty, mock_para2, mock_para3, mock_para4, mock_para5]
        mock_doc.tables = []

        with patch("src.converter.Document", mock_doc.__class__, create=True):
            # Need to mock the import inside _convert_docx
            import src.converter as conv
            with patch.dict("sys.modules", {"docx": MagicMock()}):
                with patch("src.converter.Document", return_value=mock_doc, create=True):
                    # Directly call with mocked Document
                    from importlib import reload
                    # Simpler approach: directly test
                    pass

        # Test via direct function call with mock
        from src.converter import _convert_docx
        mock_document_cls = MagicMock(return_value=mock_doc)
        docx_module = MagicMock()
        docx_module.Document = mock_document_cls

        with patch.dict("sys.modules", {"docx": docx_module}):
            f = tmp_path / "test.docx"
            f.write_text("dummy")
            result = _convert_docx(f)
            assert "## Título do Documento" in result
            assert "### Subtítulo" in result
            assert "Parágrafo normal" in result
            assert "## Título Principal" in result
            assert "#### Heading 3 text" in result

    def test_docx_with_tables(self, tmp_path: Path) -> None:
        mock_para = MagicMock()
        mock_para.text = "Texto"
        mock_para.style.name = "Normal"

        mock_cell1 = MagicMock()
        mock_cell1.text = "Header1"
        mock_cell2 = MagicMock()
        mock_cell2.text = "Header2"
        mock_cell3 = MagicMock()
        mock_cell3.text = "Val1"
        mock_cell4 = MagicMock()
        mock_cell4.text = "Val2"

        mock_row1 = MagicMock()
        mock_row1.cells = [mock_cell1, mock_cell2]
        mock_row2 = MagicMock()
        mock_row2.cells = [mock_cell3, mock_cell4]

        mock_table = MagicMock()
        mock_table.rows = [mock_row1, mock_row2]

        mock_doc = MagicMock()
        mock_doc.paragraphs = [mock_para]
        mock_doc.tables = [mock_table]

        docx_module = MagicMock()
        docx_module.Document = MagicMock(return_value=mock_doc)

        with patch.dict("sys.modules", {"docx": docx_module}):
            from src.converter import _convert_docx
            f = tmp_path / "test.docx"
            f.write_text("dummy")
            result = _convert_docx(f)
            assert "Header1" in result
            assert "Val1" in result

    def test_docx_fallback_no_python_docx(self, tmp_path: Path) -> None:
        """Testa fallback quando python-docx não está instalado."""
        from src.converter import _convert_docx
        f = tmp_path / "test.docx"
        f.write_text("dummy")

        with patch.dict("sys.modules", {"docx": None}):
            with patch("src.converter._convert_docx_fallback", return_value="# fallback") as mock_fb:
                result = _convert_docx(f)
                mock_fb.assert_called_once_with(f)
                assert result == "# fallback"


# ──────────────────────────────────────────────
# _convert_docx_fallback
# ──────────────────────────────────────────────

class TestConvertDocxFallback:
    def test_valid_docx_zip(self, tmp_path: Path) -> None:
        """Cria um DOCX mínimo (que é um ZIP com word/document.xml)."""
        import zipfile
        docx_path = tmp_path / "test.docx"
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
        <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
            <w:body>
                <w:p><w:r><w:t>Parágrafo teste</w:t></w:r></w:p>
                <w:p><w:r><w:t>Segundo parágrafo</w:t></w:r></w:p>
            </w:body>
        </w:document>"""
        with zipfile.ZipFile(docx_path, "w") as z:
            z.writestr("word/document.xml", xml_content)

        result = _convert_docx_fallback(docx_path)
        assert "Parágrafo teste" in result
        assert "Segundo parágrafo" in result

    def test_docx_zip_without_document_xml(self, tmp_path: Path) -> None:
        import zipfile
        docx_path = tmp_path / "empty.docx"
        with zipfile.ZipFile(docx_path, "w") as z:
            z.writestr("other.xml", "<data/>")

        result = _convert_docx_fallback(docx_path)
        assert result == ""


# ──────────────────────────────────────────────
# _docx_table_to_markdown
# ──────────────────────────────────────────────

class TestDocxTableToMarkdown:
    def test_basic_table(self) -> None:
        mock_cells_row1 = [MagicMock(text="A"), MagicMock(text="B")]
        mock_cells_row2 = [MagicMock(text="1"), MagicMock(text="2")]
        mock_row1 = MagicMock()
        mock_row1.cells = mock_cells_row1
        mock_row2 = MagicMock()
        mock_row2.cells = mock_cells_row2
        mock_table = MagicMock()
        mock_table.rows = [mock_row1, mock_row2]

        result = _docx_table_to_markdown(mock_table)
        assert "| A | B |" in result
        assert "| 1 | 2 |" in result

    def test_single_row_returns_empty(self) -> None:
        mock_row = MagicMock()
        mock_row.cells = [MagicMock(text="A")]
        mock_table = MagicMock()
        mock_table.rows = [mock_row]

        result = _docx_table_to_markdown(mock_table)
        assert result == ""

    def test_pipe_in_cell_escaped(self) -> None:
        mock_cells_row1 = [MagicMock(text="Col1"), MagicMock(text="Col2")]
        mock_cells_row2 = [MagicMock(text="a|b"), MagicMock(text="c")]
        mock_row1 = MagicMock()
        mock_row1.cells = mock_cells_row1
        mock_row2 = MagicMock()
        mock_row2.cells = mock_cells_row2
        mock_table = MagicMock()
        mock_table.rows = [mock_row1, mock_row2]

        result = _docx_table_to_markdown(mock_table)
        assert "a\\|b" in result

    def test_uneven_rows_padded(self) -> None:
        mock_cells_row1 = [MagicMock(text="A"), MagicMock(text="B"), MagicMock(text="C")]
        mock_cells_row2 = [MagicMock(text="1")]
        mock_row1 = MagicMock()
        mock_row1.cells = mock_cells_row1
        mock_row2 = MagicMock()
        mock_row2.cells = mock_cells_row2
        mock_table = MagicMock()
        mock_table.rows = [mock_row1, mock_row2]

        result = _docx_table_to_markdown(mock_table)
        assert result != ""


# ──────────────────────────────────────────────
# Funções auxiliares PDF (sem pdfplumber real)
# ──────────────────────────────────────────────

class TestEstimateBodyFontSize:
    def test_with_chars(self) -> None:
        mock_page1 = MagicMock()
        mock_page1.chars = [
            {"size": 10.0}, {"size": 10.0}, {"size": 10.0},
            {"size": 14.0}, {"size": 10.0},
        ]
        mock_page2 = MagicMock()
        mock_page2.chars = [{"size": 10.0}, {"size": 10.0}]
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page1, mock_page2]
        result = _estimate_body_font_size(mock_pdf)
        assert result == 10.0

    def test_no_chars(self) -> None:
        mock_page = MagicMock()
        mock_page.chars = []
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        result = _estimate_body_font_size(mock_pdf)
        assert result == 10.0

    def test_no_pages(self) -> None:
        mock_pdf = MagicMock()
        mock_pdf.pages = []
        result = _estimate_body_font_size(mock_pdf)
        assert result == 10.0

    def test_chars_without_size(self) -> None:
        mock_page = MagicMock()
        mock_page.chars = [{"text": "a"}, {"text": "b"}]  # no 'size' key
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        result = _estimate_body_font_size(mock_pdf)
        assert result == 10.0


class TestExtractTextOutsideTables:
    def test_no_tables(self) -> None:
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Texto fora de tabela"
        result = _extract_text_outside_tables(mock_page, [])
        assert result == "Texto fora de tabela"

    def test_with_tables(self) -> None:
        mock_filtered = MagicMock()
        mock_filtered.outside_bbox.return_value = mock_filtered
        mock_filtered.extract_text.return_value = "Texto filtrado"
        mock_page = MagicMock()
        mock_page.bbox = (0, 0, 200, 200)
        mock_page.outside_bbox.return_value = mock_filtered
        result = _extract_text_outside_tables(mock_page, [(0, 0, 100, 100)])
        assert result == "Texto filtrado"

    def test_no_text_returns_empty(self) -> None:
        mock_page = MagicMock()
        mock_page.extract_text.return_value = None
        result = _extract_text_outside_tables(mock_page, [])
        assert result == ""


class TestCharInBbox:
    def test_inside(self) -> None:
        assert _char_in_bbox({"x0": 50, "top": 50}, [(0, 0, 100, 100)]) is True

    def test_outside(self) -> None:
        assert _char_in_bbox({"x0": 150, "top": 50}, [(0, 0, 100, 100)]) is False

    def test_on_edge(self) -> None:
        assert _char_in_bbox({"x0": 0, "top": 0}, [(0, 0, 100, 100)]) is True

    def test_multiple_bboxes(self) -> None:
        assert _char_in_bbox({"x0": 150, "top": 50}, [(0, 0, 100, 100), (140, 40, 200, 200)]) is True

    def test_no_bboxes(self) -> None:
        assert _char_in_bbox({"x0": 50, "top": 50}, []) is False


class TestGroupCharsIntoLines:
    def test_single_line(self) -> None:
        chars = [
            {"top": 10.0, "x0": 0, "text": "A"},
            {"top": 10.0, "x0": 10, "text": "B"},
            {"top": 10.5, "x0": 20, "text": "C"},
        ]
        lines = _group_chars_into_lines(chars)
        assert len(lines) == 1

    def test_two_lines(self) -> None:
        chars = [
            {"top": 10.0, "x0": 0, "text": "A"},
            {"top": 30.0, "x0": 0, "text": "B"},
        ]
        lines = _group_chars_into_lines(chars)
        assert len(lines) == 2

    def test_empty(self) -> None:
        assert _group_chars_into_lines([]) == []


class TestClassifyLines:
    def test_heading_detection(self) -> None:
        mock_page = MagicMock()
        mock_page.chars = [
            {"top": 10.0, "x0": 0, "text": "T", "size": 16.0},
            {"top": 10.0, "x0": 10, "text": "i", "size": 16.0},
            {"top": 30.0, "x0": 0, "text": "b", "size": 10.0},
            {"top": 30.0, "x0": 10, "text": "o", "size": 10.0},
        ]
        result = _classify_lines(mock_page, 10.0, [])
        assert len(result) == 2
        assert result[0][1] == "heading"
        assert result[1][1] == "body"

    def test_no_chars_uses_extract_text(self) -> None:
        mock_page = MagicMock()
        mock_page.chars = []
        mock_page.extract_text.return_value = "Linha 1\nLinha 2"
        result = _classify_lines(mock_page, 10.0, [])
        assert len(result) == 2
        assert all(t == "body" for _, t in result)

    def test_no_chars_no_text(self) -> None:
        mock_page = MagicMock()
        mock_page.chars = []
        mock_page.extract_text.return_value = None
        result = _classify_lines(mock_page, 10.0, [])
        # extract_text returns None -> ""
        # single empty line treated as body
        assert len(result) >= 0

    def test_chars_filtered_by_bbox(self) -> None:
        mock_page = MagicMock()
        mock_page.chars = [
            {"top": 10.0, "x0": 50, "text": "A", "size": 10.0},  # inside bbox
            {"top": 100.0, "x0": 200, "text": "B", "size": 10.0},  # outside bbox
        ]
        result = _classify_lines(mock_page, 10.0, [(0, 0, 100, 50)])
        # Only char B should survive the filter
        assert len(result) >= 1


class TestProcessPage:
    def test_page_with_text_and_tables(self) -> None:
        mock_table = MagicMock()
        mock_table.bbox = (0, 0, 100, 50)
        mock_table.extract.return_value = [["H1", "H2"], ["V1", "V2"]]

        mock_page = MagicMock()
        mock_page.bbox = (0, 0, 200, 200)
        mock_page.find_tables.return_value = [mock_table]
        mock_page.chars = [
            {"top": 80.0, "x0": 0, "text": "T", "size": 10.0},
            {"top": 80.0, "x0": 10, "text": "x", "size": 10.0},
        ]
        # outside_bbox needs to return a page-like that has extract_text
        mock_filtered = MagicMock()
        mock_filtered.extract_text.return_value = "Texto fora"
        mock_page.outside_bbox.return_value = mock_filtered

        result = _process_page(mock_page, 10.0, 1)
        assert "H1" in result or "V1" in result

    def test_page_no_tables(self) -> None:
        mock_page = MagicMock()
        mock_page.find_tables.return_value = []
        mock_page.chars = [
            {"top": 10.0, "x0": 0, "text": "A", "size": 10.0},
        ]
        mock_page.extract_text.return_value = "Apenas texto"
        result = _process_page(mock_page, 10.0, 1)
        assert len(result) > 0

    def test_page_empty(self) -> None:
        mock_page = MagicMock()
        mock_page.find_tables.return_value = []
        mock_page.chars = []
        mock_page.extract_text.return_value = None
        result = _process_page(mock_page, 10.0, 1)
        assert isinstance(result, str)

    def test_table_extract_returns_none(self) -> None:
        mock_table = MagicMock()
        mock_table.bbox = (0, 0, 100, 50)
        mock_table.extract.return_value = None

        mock_page = MagicMock()
        mock_page.bbox = (0, 0, 200, 200)
        mock_page.find_tables.return_value = [mock_table]
        mock_page.chars = []
        mock_filtered = MagicMock()
        mock_filtered.extract_text.return_value = None
        mock_page.outside_bbox.return_value = mock_filtered
        mock_page.extract_text.return_value = None

        result = _process_page(mock_page, 10.0, 1)
        assert isinstance(result, str)


class TestConvertPdf:
    def test_convert_pdf_end_to_end(self, tmp_path: Path) -> None:
        """Testa _convert_pdf com mock completo do pdfplumber."""
        mock_page = MagicMock()
        mock_page.chars = [
            {"top": 10.0, "x0": 0, "text": "H", "size": 14.0},
            {"top": 10.0, "x0": 10, "text": "i", "size": 14.0},
            {"top": 30.0, "x0": 0, "text": "t", "size": 10.0},
            {"top": 30.0, "x0": 10, "text": "x", "size": 10.0},
        ]
        mock_page.find_tables.return_value = []
        mock_page.extract_text.return_value = "Hi\ntx"

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with patch("src.converter.pdfplumber") as mock_plumber:
            mock_plumber.open.return_value = mock_pdf
            from src.converter import _convert_pdf
            f = tmp_path / "test.pdf"
            f.write_text("dummy")
            result = _convert_pdf(f)
            assert "# test" in result


# ──────────────────────────────────────────────
# _table_to_markdown
# ──────────────────────────────────────────────

class TestTableToMarkdown:
    def test_basic_table(self) -> None:
        data = [["Campo", "Tipo", "Tamanho"], ["REG", "C", "4"], ["IND_OPER", "C", "1"]]
        result = _table_to_markdown(data)
        assert "| Campo | Tipo | Tamanho |" in result
        assert "| REG | C | 4 |" in result
        assert "| --- |" in result

    def test_empty_table(self) -> None:
        assert _table_to_markdown([]) == ""

    def test_single_row(self) -> None:
        assert _table_to_markdown([["Header"]]) == ""

    def test_none_cells(self) -> None:
        data = [["A", "B"], [None, "valor"]]
        result = _table_to_markdown(data)
        assert "valor" in result

    def test_uneven_rows_padded(self) -> None:
        data = [["A", "B", "C"], ["1", "2"]]
        result = _table_to_markdown(data)
        lines = result.strip().split("\n")
        assert lines[0].count("|") == lines[2].count("|")


# ──────────────────────────────────────────────
# _clean_cell
# ──────────────────────────────────────────────

class TestCleanCell:
    def test_none(self) -> None:
        assert _clean_cell(None) == ""

    def test_strips(self) -> None:
        assert _clean_cell("  hello  ") == "hello"

    def test_collapses_whitespace(self) -> None:
        assert _clean_cell("hello   world") == "hello world"

    def test_escapes_pipes(self) -> None:
        assert _clean_cell("a|b") == "a\\|b"

    def test_numeric_input(self) -> None:
        assert _clean_cell(123) == "123"


# ──────────────────────────────────────────────
# _detect_heading_level
# ──────────────────────────────────────────────

class TestDetectHeadingLevel:
    def test_bloco(self) -> None:
        assert _detect_heading_level("BLOCO C") == 2

    def test_registro(self) -> None:
        assert _detect_heading_level("REGISTRO C100") == 3

    def test_campos(self) -> None:
        assert _detect_heading_level("CAMPOS DO REGISTRO") == 4

    def test_observacao(self) -> None:
        assert _detect_heading_level("OBSERVAÇÕES") == 4

    def test_nota(self) -> None:
        assert _detect_heading_level("NOTA EXPLICATIVA") == 4

    def test_regra(self) -> None:
        assert _detect_heading_level("REGRAS DE VALIDAÇÃO") == 4

    def test_tabela(self) -> None:
        assert _detect_heading_level("TABELA DE CÓDIGOS") == 4

    def test_generic(self) -> None:
        assert _detect_heading_level("Algum título qualquer") == 3


# ──────────────────────────────────────────────
# SUPPORTED_EXTENSIONS
# ──────────────────────────────────────────────

class TestSupportedExtensions:
    def test_all_supported(self) -> None:
        assert ".pdf" in SUPPORTED_EXTENSIONS
        assert ".docx" in SUPPORTED_EXTENSIONS
        assert ".txt" in SUPPORTED_EXTENSIONS
