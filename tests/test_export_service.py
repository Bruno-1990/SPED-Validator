"""Testes para MOD-20: Relatório de Auditoria com Responsabilidade Legal."""

from __future__ import annotations

import json
import sqlite3

import pytest

from src.services.database import init_audit_db
from src.services.export_service import (
    export_errors_csv,
    export_errors_json,
    export_report_markdown,
    generate_report,
)

# ─────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────

@pytest.fixture
def audit_db() -> sqlite3.Connection:
    """Banco de auditoria em memória com schema + migrations completas."""
    conn = init_audit_db(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def populated_db(audit_db: sqlite3.Connection) -> tuple[sqlite3.Connection, int]:
    """DB com um arquivo, erros variados e correções para testar relatório completo."""
    db = audit_db

    # Inserir arquivo
    db.execute(
        """INSERT INTO sped_files
           (filename, hash_sha256, period_start, period_end, company_name, cnpj, uf,
            total_records, total_errors, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("teste.txt", "abc123def456", "01012024", "31012024",
         "Empresa Teste Ltda", "12345678000195", "SP", 500, 10, "validated"),
    )
    file_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Inserir um sped_record mínimo para foreign key das corrections
    db.execute(
        """INSERT INTO sped_records (file_id, line_number, register, block, fields_json, raw_line)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (file_id, 10, "C100", "C", '{"REG":"C100"}', "|C100|"),
    )
    record_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Erros variados (severidade, certeza, blocos)
    errors = [
        (file_id, record_id, 10, "C100", 7, "VL_DOC", "999", "VALOR_INVALIDO", "critical",
         "Valor do documento inválido", "open", "objetivo", "critico",
         "Art. 176 RICMS", "100.00", "Valor incorreto no documento"),
        (file_id, record_id, 10, "C170", 5, "ALIQ_ICMS", "25", "ALIQUOTA_INCORRETA", "error",
         "Alíquota ICMS incorreta", "open", "provavel", "relevante",
         "Art. 52 RICMS", "18.00", "Alíquota não corresponde à UF"),
        (file_id, None, 20, "D100", None, None, "", "REGISTRO_AUSENTE", "warning",
         "Registro D100 ausente", "open", "indicio", "informativo",
         None, None, None),
        (file_id, None, 30, "E110", 3, "VL_ICMS", "0", "RECALCULO_E110", "error",
         "E110 diverge do recálculo", "open", "objetivo", "relevante",
         "Guia Prático 2.5", "1500.00", "Valor ICMS recalculado difere"),
        (file_id, None, 40, "C190", 4, "VL_BC_ICMS", "100", "C190_DIVERGE", "info",
         "C190 diverge de C170", "open", "objetivo", "informativo",
         None, None, None),
    ]
    for e in errors:
        db.execute(
            """INSERT INTO validation_errors
               (file_id, record_id, line_number, register, field_no, field_name, value,
                error_type, severity, message, status, certeza, impacto,
                legal_basis, expected_value, friendly_message)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            e,
        )

    # Correção aplicada
    db.execute(
        """INSERT INTO corrections
           (file_id, record_id, field_no, field_name, old_value, new_value,
            error_id, applied_by, applied_at, justificativa)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (file_id, record_id, 7, "VL_DOC", "999", "100.00",
         None, "analista", "2024-01-15 10:00:00", "Valor corrigido conforme NF-e"),
    )
    db.commit()
    return db, file_id


# ─────────────────────────────────────────────────
# Testes generate_report (dict com 6 seções)
# ─────────────────────────────────────────────────

class TestGenerateReport:

    def test_arquivo_nao_encontrado(self, audit_db: sqlite3.Connection):
        result = generate_report(audit_db, 9999)
        assert "error" in result

    def test_todas_6_secoes_presentes(self, populated_db):
        db, file_id = populated_db
        report = generate_report(db, file_id)

        assert "secao1_cabecalho" in report
        assert "secao2_cobertura" in report
        assert "secao3_sumario" in report
        assert "secao4_achados" in report
        assert "secao5_correcoes" in report
        assert "secao6_rodape" in report

    def test_secao1_cabecalho(self, populated_db):
        db, file_id = populated_db
        s1 = generate_report(db, file_id)["secao1_cabecalho"]

        assert s1["contribuinte"] == "Empresa Teste Ltda"
        assert s1["cnpj"] == "12345678000195"
        assert "01012024" in s1["periodo"]
        assert s1["hash_sha256_original"] == "abc123def456"
        assert s1["versao_motor"]  # não vazio
        assert s1["data_hora_auditoria"]  # não vazio

    def test_secao2_cobertura(self, populated_db):
        db, file_id = populated_db
        s2 = generate_report(db, file_id)["secao2_cobertura"]

        assert len(s2["checks"]) > 0
        assert "cobertura_pct" in s2
        assert isinstance(s2["cobertura_pct"], float)
        assert s2["cobertura_pct"] > 0
        assert "tabelas_disponiveis" in s2
        assert "tabelas_ausentes" in s2
        assert "limitacoes" in s2

    def test_secao3_sumario(self, populated_db):
        db, file_id = populated_db
        s3 = generate_report(db, file_id)["secao3_sumario"]

        sev = s3["por_severidade"]
        assert sev["critical"] == 1
        assert sev["error"] == 2
        assert sev["warning"] == 1
        assert sev["info"] == 1

        cert = s3["por_certeza"]
        assert cert["objetivo"] == 3
        assert cert["provavel"] == 1
        assert cert["indicio"] == 1

        bloco = s3["por_bloco"]
        assert "C" in bloco
        assert "D" in bloco
        assert "E" in bloco

        assert len(s3["top10_tipos"]) > 0

    def test_secao4_achados_ordenados_por_severidade(self, populated_db):
        db, file_id = populated_db
        s4 = generate_report(db, file_id)["secao4_achados"]

        assert len(s4) == 5
        # Primeiro é critical
        assert s4[0]["severidade"] == "critical"
        # Campos obrigatórios
        for a in s4:
            assert "linha" in a
            assert "registro" in a
            assert "campo" in a
            assert "valor_encontrado" in a
            assert "valor_esperado" in a
            assert "certeza" in a
            assert "impacto" in a
            assert "base_legal" in a
            assert "orientacao" in a

    def test_secao5_correcoes(self, populated_db):
        db, file_id = populated_db
        s5 = generate_report(db, file_id)["secao5_correcoes"]

        assert len(s5) == 1
        c = s5[0]
        assert c["campo"] == "VL_DOC"
        assert c["valor_original"] == "999"
        assert c["novo_valor"] == "100.00"
        assert c["justificativa"] == "Valor corrigido conforme NF-e"
        assert c["aprovado_por"] == "analista"
        assert c["data"]

    def test_secao6_rodape_legal(self, populated_db):
        db, file_id = populated_db
        s6 = generate_report(db, file_id)["secao6_rodape"]

        texto = s6["texto"]
        assert "AVISO LEGAL" in texto
        assert "não constitui parecer contábil, fiscal ou jurídico" in texto
        assert "CRC/CRA/OAB" in texto
        assert "Verificações não realizadas" in texto
        assert "Versão do motor" in texto


# ─────────────────────────────────────────────────
# Testes Markdown
# ─────────────────────────────────────────────────

class TestMarkdown:

    def test_md_contem_6_secoes(self, populated_db):
        db, file_id = populated_db
        md = export_report_markdown(db, file_id)

        assert "## 1. Cabeçalho de Identificação" in md
        assert "## 2. Cobertura da Auditoria" in md
        assert "## 3. Sumário de Achados" in md
        assert "## 4. Achados Detalhados" in md
        assert "## 5. Correções Aplicadas" in md
        assert "## 6. Rodapé Legal" in md

    def test_md_rodape_legal(self, populated_db):
        db, file_id = populated_db
        md = export_report_markdown(db, file_id)

        assert "AVISO LEGAL" in md
        assert "CRC/CRA/OAB" in md

    def test_md_cabecalho_hash(self, populated_db):
        db, file_id = populated_db
        md = export_report_markdown(db, file_id)

        assert "abc123def456" in md
        assert "Empresa Teste Ltda" in md
        assert "12345678000195" in md

    def test_md_arquivo_nao_encontrado(self, audit_db):
        md = export_report_markdown(audit_db, 9999)
        assert "não encontrado" in md


# ─────────────────────────────────────────────────
# Testes CSV
# ─────────────────────────────────────────────────

class TestCSV:

    def test_csv_rodape_legal(self, populated_db):
        db, file_id = populated_db
        csv_out = export_errors_csv(db, file_id)

        assert "AVISO LEGAL" in csv_out
        assert "CRC/CRA/OAB" in csv_out

    def test_csv_contem_dados(self, populated_db):
        db, file_id = populated_db
        csv_out = export_errors_csv(db, file_id)

        lines = csv_out.strip().split("\n")
        # Header + 5 erros + linha vazia + rodapé
        assert len(lines) >= 7
        assert "linha" in lines[0]  # header


# ─────────────────────────────────────────────────
# Testes JSON
# ─────────────────────────────────────────────────

class TestJSON:

    def test_json_contem_6_secoes(self, populated_db):
        db, file_id = populated_db
        json_str = export_errors_json(db, file_id)
        data = json.loads(json_str)

        assert "secao1_cabecalho" in data
        assert "secao2_cobertura" in data
        assert "secao3_sumario" in data
        assert "secao4_achados" in data
        assert "secao5_correcoes" in data
        assert "secao6_rodape" in data

    def test_json_rodape_legal(self, populated_db):
        db, file_id = populated_db
        json_str = export_errors_json(db, file_id)
        data = json.loads(json_str)

        texto = data["secao6_rodape"]["texto"]
        assert "AVISO LEGAL" in texto
        assert "CRC/CRA/OAB" in texto

    def test_json_valido(self, populated_db):
        db, file_id = populated_db
        json_str = export_errors_json(db, file_id)
        data = json.loads(json_str)  # Não deve lançar exceção
        assert isinstance(data, dict)

    def test_json_arquivo_nao_encontrado(self, audit_db):
        json_str = export_errors_json(audit_db, 9999)
        data = json.loads(json_str)
        assert "error" in data
