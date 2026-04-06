"""Testes do MOD-16: Suporte a Retificadores (COD_VER/COD_FIN)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.services.database import init_audit_db
from src.services.file_service import get_file, upload_file
from src.validators.retificador_validator import validate_retificador

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _make_sped_content(cod_fin: int = 0, cnpj: str = "11222333000181",
                       dt_ini: str = "01012024", dt_fin: str = "31012024") -> str:
    """Gera conteudo SPED minimo com COD_FIN parametrizado."""
    return (
        f"|0000|017|{cod_fin}|{dt_ini}|{dt_fin}|EMPRESA TESTE LTDA|{cnpj}||SP|1234567890|351880|55||1|\n"
        "|0001|0|\n"
        "|0005|EMPRESA TESTE LTDA|12345678|Rua Teste 123||01001000|SP|1134567890||empresa@teste.com|\n"
        "|0990|3|\n"
        "|C001|1|\n"
        "|C990|1|\n"
        "|D001|1|\n"
        "|D990|1|\n"
        "|E001|1|\n"
        "|E990|1|\n"
        "|H001|1|\n"
        "|H990|1|\n"
        "|9001|0|\n"
        "|9900|0000|1|\n"
        "|9990|2|\n"
        "|9999|15|\n"
    )


def _write_sped(tmp_path: Path, content: str, name: str = "sped.txt") -> Path:
    filepath = tmp_path / name
    filepath.write_text(content, encoding="latin-1")
    return filepath


@pytest.fixture
def audit_db(tmp_path: Path) -> sqlite3.Connection:
    path = tmp_path / "audit.db"
    conn = init_audit_db(path)
    conn.row_factory = sqlite3.Row
    return conn


# ──────────────────────────────────────────────
# Testes de upload e modelo de dados
# ──────────────────────────────────────────────

class TestRetificadorUpload:
    def test_original_file_cod_ver_zero(self, audit_db: sqlite3.Connection, tmp_path: Path) -> None:
        """Upload de arquivo COD_FIN=0 -> cod_ver=0, is_retificador=False."""
        filepath = _write_sped(tmp_path, _make_sped_content(cod_fin=0))
        file_id = upload_file(audit_db, filepath)

        info = get_file(audit_db, file_id)
        assert info is not None
        assert info["cod_ver"] == 0
        assert info["is_retificador"] == 0
        assert info["original_file_id"] is None

    def test_retificador_with_original(self, audit_db: sqlite3.Connection, tmp_path: Path) -> None:
        """Upload retificador com original existente -> linked corretamente."""
        # Upload original
        orig_path = _write_sped(tmp_path, _make_sped_content(cod_fin=0), name="original.txt")
        orig_id = upload_file(audit_db, orig_path)

        # Upload retificador (mesmo CNPJ, mesmo periodo, COD_FIN=1)
        ret_path = _write_sped(tmp_path, _make_sped_content(cod_fin=1), name="retificador.txt")
        ret_id = upload_file(audit_db, ret_path)

        info = get_file(audit_db, ret_id)
        assert info is not None
        assert info["cod_ver"] == 1
        assert info["is_retificador"] == 1
        assert info["original_file_id"] == orig_id

        # Verificar tabela sped_file_versions
        row = audit_db.execute(
            "SELECT * FROM sped_file_versions WHERE retificador_file_id = ?",
            (ret_id,),
        ).fetchone()
        assert row is not None
        assert row["original_file_id"] == orig_id
        assert row["cod_ver"] == 1

    def test_retificador_without_original(self, audit_db: sqlite3.Connection, tmp_path: Path) -> None:
        """Upload retificador sem original -> cod_ver>0, original_file_id=None."""
        filepath = _write_sped(tmp_path, _make_sped_content(cod_fin=1), name="ret_sem_orig.txt")
        file_id = upload_file(audit_db, filepath)

        info = get_file(audit_db, file_id)
        assert info is not None
        assert info["cod_ver"] == 1
        assert info["is_retificador"] == 1
        assert info["original_file_id"] is None


# ──────────────────────────────────────────────
# Testes de validacao (RET_001, RET_002)
# ──────────────────────────────────────────────

class TestRetificadorValidation:
    def test_ret_002_warning_sem_original(self, audit_db: sqlite3.Connection, tmp_path: Path) -> None:
        """RET_002: retificador sem original no sistema -> warning."""
        filepath = _write_sped(tmp_path, _make_sped_content(cod_fin=1))
        file_id = upload_file(audit_db, filepath)

        # Parsear registros para validacao
        from src.parser import parse_sped_file
        records = parse_sped_file(filepath)

        errors = validate_retificador(records, db=audit_db, file_id=file_id)
        assert len(errors) == 1
        assert errors[0].error_type == "RET_002"
        assert "sem arquivo original" in errors[0].message

    def test_ret_001_periodo_diferente(self, audit_db: sqlite3.Connection, tmp_path: Path) -> None:
        """RET_001: retificador com periodo diferente da original -> error."""
        # Upload original (jan/2024)
        orig_path = _write_sped(
            tmp_path,
            _make_sped_content(cod_fin=0, dt_ini="01012024", dt_fin="31012024"),
            name="original.txt",
        )
        upload_file(audit_db, orig_path)

        # Upload retificador com periodo diferente (fev/2024)
        ret_path = _write_sped(
            tmp_path,
            _make_sped_content(cod_fin=1, dt_ini="01022024", dt_fin="29022024"),
            name="retificador.txt",
        )
        ret_id = upload_file(audit_db, ret_path)

        from src.parser import parse_sped_file
        records = parse_sped_file(ret_path)

        errors = validate_retificador(records, db=audit_db, file_id=ret_id)
        assert len(errors) == 1
        assert errors[0].error_type == "RET_001"
        assert "periodo" in errors[0].message.lower()

    def test_no_errors_for_original(self, audit_db: sqlite3.Connection, tmp_path: Path) -> None:
        """Arquivo original (COD_FIN=0) nao gera erros de retificacao."""
        filepath = _write_sped(tmp_path, _make_sped_content(cod_fin=0))
        file_id = upload_file(audit_db, filepath)

        from src.parser import parse_sped_file
        records = parse_sped_file(filepath)

        errors = validate_retificador(records, db=audit_db, file_id=file_id)
        assert errors == []

    def test_no_errors_when_linked_correctly(self, audit_db: sqlite3.Connection, tmp_path: Path) -> None:
        """Retificador com original e mesmo periodo -> sem erros."""
        orig_path = _write_sped(tmp_path, _make_sped_content(cod_fin=0), name="original.txt")
        upload_file(audit_db, orig_path)

        ret_path = _write_sped(tmp_path, _make_sped_content(cod_fin=1), name="retificador.txt")
        ret_id = upload_file(audit_db, ret_path)

        from src.parser import parse_sped_file
        records = parse_sped_file(ret_path)

        errors = validate_retificador(records, db=audit_db, file_id=ret_id)
        assert errors == []
