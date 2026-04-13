"""Testes do Motor de Cruzamento NF-e XML x SPED EFD (cross_engine)."""

from __future__ import annotations

import json
import sqlite3

import pytest

from src.services.cross_engine import (
    CrossValidationEngine,
    _make_finding,
    assign_priority,
    deduplicate_findings,
    run_layer_a,
    run_layer_d_identity,
    run_layer_d_totals,
    run_layer_e_items,
)
from src.services.cross_engine_models import (
    GRUPOS_SEM_BC_ICMS,
    CST_FROM_XML_GROUP,
    CrossValidationFinding,
    DocumentScope,
    ItemMatchState,
    ItemNature,
    ItemPair,
    RuleOutcome,
    SpedC170Item,
    XmlItemParsed,
    classify_item_nature,
)
from src.services.database import init_audit_db
from src.services.document_scope_builder import (
    _heuristic_score,
    _match_items_exact,
)


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def db():
    """Banco SQLite em memoria com schema completo."""
    conn = init_audit_db(":memory:")
    yield conn
    conn.close()


def _insert_sped_file(db, file_id=1):
    db.execute(
        "INSERT INTO sped_files (id, filename, hash_sha256) VALUES (?, 'test.txt', 'abc123')",
        (file_id,),
    )
    db.commit()


def _insert_c100(db, file_id=1, line_number=10, fields=None):
    f = fields or {}
    row_id = db.execute(
        "INSERT INTO sped_records (file_id, line_number, register, block, fields_json, raw_line) "
        "VALUES (?, ?, 'C100', 'C', ?, '|C100|...')",
        (file_id, line_number, json.dumps(f)),
    ).lastrowid
    db.commit()
    return row_id


def _insert_c170(db, file_id=1, parent_id=None, line_number=20, fields=None):
    f = fields or {}
    db.execute(
        "INSERT INTO sped_records (file_id, line_number, register, block, parent_id, fields_json, raw_line) "
        "VALUES (?, ?, 'C170', 'C', ?, ?, '|C170|...')",
        (file_id, line_number, parent_id, json.dumps(f)),
    )
    db.commit()


def _insert_xml(db, file_id=1, chave="12345678901234567890123456789012345678901234", **kwargs):
    defaults = {
        "numero_nfe": "1000", "serie": "1", "cnpj_emitente": "12345678000190",
        "cnpj_destinatario": "98765432000111", "vl_doc": 1000.0,
        "vl_icms": 120.0, "vl_icms_st": 0.0, "vl_ipi": 50.0,
        "vl_pis": 16.50, "vl_cofins": 76.0, "qtd_itens": 1,
        "prot_cstat": "100", "status": "active",
    }
    defaults.update(kwargs)
    nfe_id = db.execute(
        """INSERT INTO nfe_xmls (file_id, chave_nfe, numero_nfe, serie,
           cnpj_emitente, cnpj_destinatario, vl_doc, vl_icms, vl_icms_st,
           vl_ipi, vl_pis, vl_cofins, qtd_itens, prot_cstat, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (file_id, chave, defaults["numero_nfe"], defaults["serie"],
         defaults["cnpj_emitente"], defaults["cnpj_destinatario"],
         defaults["vl_doc"], defaults["vl_icms"], defaults["vl_icms_st"],
         defaults["vl_ipi"], defaults["vl_pis"], defaults["vl_cofins"],
         defaults["qtd_itens"], defaults["prot_cstat"], defaults["status"]),
    ).lastrowid
    db.commit()
    return nfe_id


def _insert_xml_item(db, nfe_id, num_item=1, **kwargs):
    defaults = {
        "cod_produto": "PROD01", "ncm": "84719012", "cfop": "5102",
        "vl_prod": 500.0, "vl_desc": 0.0, "cst_icms": "000",
        "vbc_icms": 500.0, "aliq_icms": 18.0, "vl_icms": 90.0,
        "cst_ipi": "50", "vl_ipi": 25.0,
        "cst_pis": "01", "vl_pis": 8.25,
        "cst_cofins": "01", "vl_cofins": 38.0,
    }
    defaults.update(kwargs)
    db.execute(
        """INSERT INTO nfe_itens (nfe_id, num_item, cod_produto, ncm, cfop,
           vl_prod, vl_desc, cst_icms, vbc_icms, aliq_icms, vl_icms,
           cst_ipi, vl_ipi, cst_pis, vl_pis, cst_cofins, vl_cofins)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (nfe_id, num_item, defaults["cod_produto"], defaults["ncm"],
         defaults["cfop"], defaults["vl_prod"], defaults["vl_desc"],
         defaults["cst_icms"], defaults["vbc_icms"], defaults["aliq_icms"],
         defaults["vl_icms"], defaults["cst_ipi"], defaults["vl_ipi"],
         defaults["cst_pis"], defaults["vl_pis"],
         defaults["cst_cofins"], defaults["vl_cofins"]),
    )
    db.commit()


# ── Testes dos modelos ───────────────────────────────────────────────

class TestModels:
    def test_rule_outcome_values(self):
        assert RuleOutcome.EXECUTED_ERROR.value == "EXECUTED_ERROR"
        assert RuleOutcome.NOT_APPLICABLE.value == "NOT_APPLICABLE"

    def test_item_match_state(self):
        assert ItemMatchState.MATCH_EXATO.value == "MATCH_EXATO"
        assert ItemMatchState.AMBIGUO.value == "AMBIGUO"

    def test_classify_item_nature(self):
        assert classify_item_nature("1102") == ItemNature.REVENDA
        assert classify_item_nature("1556") == ItemNature.USO_CONSUMO
        assert classify_item_nature("1551") == ItemNature.ATIVO
        assert classify_item_nature("9999") == ItemNature.OUTRO

    def test_finding_cache_key(self):
        f = CrossValidationFinding(rule_id="XC024", sped_field="VL_BC_ICMS")
        key = f.build_cache_key()
        assert len(key) == 64  # SHA256 hex

    def test_cst_from_xml_group(self):
        assert CST_FROM_XML_GROUP["ICMS00"] == "000"
        assert CST_FROM_XML_GROUP["ICMSSN101"] == "101"

    def test_grupos_sem_bc(self):
        assert "ICMS40" in GRUPOS_SEM_BC_ICMS
        assert "ICMS00" not in GRUPOS_SEM_BC_ICMS


# ── Testes de pareamento ─────────────────────────────────────────────

class TestItemMatching:
    def test_match_exact_by_nitem(self):
        c170 = [SpedC170Item(num_item=1, vl_item=100), SpedC170Item(num_item=2, vl_item=200)]
        xml = [XmlItemParsed(num_item=1, vl_prod=100), XmlItemParsed(num_item=2, vl_prod=200)]
        pairs, xml_rem, c170_rem = _match_items_exact(c170, xml)
        assert len(pairs) == 2
        assert len(xml_rem) == 0
        assert len(c170_rem) == 0
        assert all(p.match_state == ItemMatchState.MATCH_EXATO for p in pairs)

    def test_match_exact_partial(self):
        c170 = [SpedC170Item(num_item=1), SpedC170Item(num_item=3)]
        xml = [XmlItemParsed(num_item=1), XmlItemParsed(num_item=2)]
        pairs, xml_rem, c170_rem = _match_items_exact(c170, xml)
        assert len(pairs) == 1
        assert len(xml_rem) == 1
        assert len(c170_rem) == 1

    def test_heuristic_score_perfect(self):
        c170 = SpedC170Item(cod_item="PROD01", ncm="84719012", cfop="5102", vl_item=500.0)
        xi = XmlItemParsed(cod_produto="PROD01", ncm="84719012", cfop="5102", vl_prod=500.0)
        score = _heuristic_score(c170, xi)
        assert score == 1.0

    def test_heuristic_score_low(self):
        c170 = SpedC170Item(cod_item="A", ncm="11111111", cfop="1102", vl_item=10.0)
        xi = XmlItemParsed(cod_produto="B", ncm="99999999", cfop="5102", vl_prod=9999.0)
        score = _heuristic_score(c170, xi)
        assert score < 0.3


# ── Testes das regras por camada ─────────────────────────────────────

class TestLayerA:
    def test_xc001_xml_sem_c100(self):
        scope = DocumentScope(match_status="sem_c100", chave_nfe="1234567890")
        findings = run_layer_a(scope)
        assert len(findings) == 1
        assert findings[0].rule_id == "XC001"

    def test_xc002_c100_sem_xml(self):
        scope = DocumentScope(match_status="sem_xml", xml_eligible=1, chave_nfe="abc", c100_line_number=5)
        findings = run_layer_a(scope)
        assert len(findings) == 1
        assert findings[0].rule_id == "XC002"

    def test_no_finding_matched(self):
        scope = DocumentScope(match_status="matched", chave_nfe="abc")
        findings = run_layer_a(scope)
        assert len(findings) == 0


class TestLayerDIdentity:
    def test_xc008_cancelada(self):
        scope = DocumentScope(
            match_status="matched", chave_nfe="abc",
            xml_data={"prot_cstat": "101"},
            cod_sit="00",
        )
        findings = run_layer_d_identity(scope)
        assert any(f.rule_id == "XC008" for f in findings)

    def test_xc008b_denegada(self):
        scope = DocumentScope(
            match_status="matched", chave_nfe="abc",
            xml_data={"prot_cstat": "110"},
            cod_sit="00",
        )
        findings = run_layer_d_identity(scope)
        assert any(f.rule_id == "XC008b" for f in findings)


class TestLayerDTotals:
    def test_xc003_vl_doc_divergente(self):
        scope = DocumentScope(
            match_status="matched", chave_nfe="abc",
            xml_data={"totais": {"vNF": 1000.0, "vICMS": 120.0, "vST": 0.0,
                                 "vIPI": 50.0, "vProd": 800.0}},
            vl_doc=999.0, vl_icms=120.0, vl_icms_st=0.0, vl_ipi=50.0,
            vl_merc=800.0,
        )
        findings = run_layer_d_totals(scope)
        assert any(f.rule_id == "XC003" for f in findings)

    def test_no_finding_when_equal(self):
        scope = DocumentScope(
            match_status="matched", chave_nfe="abc",
            xml_data={"totais": {"vNF": 1000.0, "vICMS": 120.0, "vST": 0.0,
                                 "vIPI": 50.0, "vProd": 800.0, "vFrete": 0.0,
                                 "vSeg": 0.0, "vOutro": 0.0}},
            vl_doc=1000.0, vl_icms=120.0, vl_icms_st=0.0, vl_ipi=50.0,
            vl_merc=800.0,
        )
        findings = run_layer_d_totals(scope)
        assert len(findings) == 0

    def test_complementar_supressao(self):
        scope = DocumentScope(
            match_status="matched", chave_nfe="abc",
            xml_data={"totais": {"vNF": 9999.0}},
            vl_doc=0.0,
            is_complementar=1,
        )
        findings = run_layer_d_totals(scope)
        assert len(findings) == 0


class TestLayerEItems:
    def test_xc018_item_xml_sem_c170(self):
        scope = DocumentScope(
            match_status="matched", chave_nfe="abc",
            xml_data={"totais": {}},
            xml_items_sem_match=[XmlItemParsed(num_item=1, cod_produto="P1")],
        )
        findings = run_layer_e_items(scope)
        assert any(f.rule_id == "XC018" for f in findings)

    def test_xc019_c170_sem_xml(self):
        scope = DocumentScope(
            match_status="matched", chave_nfe="abc",
            xml_data={"totais": {}},
            c170_sem_match=[SpedC170Item(num_item=1, cod_item="I1")],
        )
        findings = run_layer_e_items(scope)
        assert any(f.rule_id == "XC019" for f in findings)

    def test_xc019b_ambiguo(self):
        pair = ItemPair(
            c170=SpedC170Item(num_item=1),
            xml_item=XmlItemParsed(num_item=1),
            match_state=ItemMatchState.AMBIGUO,
            match_score=0.65,
        )
        scope = DocumentScope(
            match_status="matched", chave_nfe="abc",
            xml_data={"totais": {}},
            item_pairs=[pair],
        )
        findings = run_layer_e_items(scope)
        assert any(f.rule_id == "XC019b" for f in findings)
        # Deve bloquear regras subsequentes — so XC019b
        xc019b = [f for f in findings if f.rule_id == "XC019b"]
        assert len(xc019b) == 1

    def test_xc024b_bc_indevida_grupo_isento(self):
        pair = ItemPair(
            c170=SpedC170Item(num_item=1, vl_bc_icms=500.0),
            xml_item=XmlItemParsed(num_item=1, grupo_icms="ICMS40"),
            match_state=ItemMatchState.MATCH_EXATO,
        )
        scope = DocumentScope(
            match_status="matched", chave_nfe="abc",
            xml_data={"totais": {}},
            item_pairs=[pair],
        )
        findings = run_layer_e_items(scope)
        assert any(f.rule_id == "XC024b" for f in findings)


# ── Testes de deduplicacao e prioridade ──────────────────────────────

class TestDeduplication:
    def test_root_cause_dedup(self):
        f1 = _make_finding("XC020", "CST_DIVERGENTE", root_cause_group="XC020|C170|CST")
        f2 = _make_finding("XC024", "BC_DIVERGENTE", root_cause_group="XC020|C170|CST")
        f3 = _make_finding("XC025", "ALIQ_DIVERGENTE", root_cause_group="XC020|C170|CST")
        result = deduplicate_findings([f1, f2, f3])
        assert len(result) == 3
        root = [f for f in result if not f.is_derived]
        derived = [f for f in result if f.is_derived]
        assert len(root) == 1
        assert len(derived) == 2

    def test_no_group_preserved(self):
        f1 = _make_finding("XC018", "SEM_C170")
        f2 = _make_finding("XC019", "SEM_XML")
        result = deduplicate_findings([f1, f2])
        assert len(result) == 2
        assert all(not f.is_derived for f in result)


class TestPriority:
    def test_p1_critico(self):
        f = _make_finding("XC003", "VL_DOC", severity="critico")
        assert assign_priority(f) == "P1"

    def test_p2_error(self):
        f = _make_finding("XC021", "CFOP", severity="error", sped_field="CFOP")
        assert assign_priority(f) == "P2"

    def test_p1_error_impactante(self):
        f = _make_finding("XC026", "VL_ICMS", severity="error")
        f.sped_field = "VL_ICMS"
        assert assign_priority(f) == "P1"


# ── Teste de integracao com banco ────────────────────────────────────

class TestEngineIntegration:
    def test_engine_empty_scopes(self, db):
        _insert_sped_file(db)
        engine = CrossValidationEngine(db, 1, regime="normal")
        findings = engine.run()
        assert findings == []

    def test_engine_with_data(self, db):
        _insert_sped_file(db)
        chave = "12345678901234567890123456789012345678901234"

        # C100 com chave
        c100_id = _insert_c100(db, fields={
            "CHV_NFE": chave, "COD_MOD": "55", "IND_EMIT": "0",
            "COD_SIT": "00", "VL_DOC": "1000.00", "VL_MERC": "800.00",
            "VL_ICMS": "120.00", "VL_ICMS_ST": "0.00", "VL_IPI": "50.00",
        })

        # C170 com item
        _insert_c170(db, parent_id=c100_id, fields={
            "NUM_ITEM": "1", "COD_ITEM": "PROD01", "NCM": "84719012",
            "CFOP": "5102", "VL_ITEM": "500.00", "CST_ICMS": "000",
            "VL_BC_ICMS": "500.00", "ALIQ_ICMS": "18.00", "VL_ICMS": "90.00",
            "VL_IPI": "25.00",
        })

        # XML com mesma chave
        nfe_id = _insert_xml(db, chave=chave, vl_doc=1000.0, vl_icms=120.0, vl_ipi=50.0)
        _insert_xml_item(db, nfe_id, num_item=1, vl_prod=500.0, vbc_icms=500.0,
                         aliq_icms=18.0, vl_icms=90.0, vl_ipi=25.0)

        engine = CrossValidationEngine(db, 1, regime="normal")
        findings = engine.run()

        # Nao deve ter divergencias criticas pois os dados batem
        criticos = [f for f in findings if f.severity == "critico"]
        assert len(criticos) == 0

    def test_engine_divergencia_vl_doc(self, db):
        _insert_sped_file(db)
        chave = "12345678901234567890123456789012345678901234"

        c100_id = _insert_c100(db, fields={
            "CHV_NFE": chave, "COD_MOD": "55", "IND_EMIT": "0",
            "COD_SIT": "00", "VL_DOC": "999.00",
            "VL_ICMS": "120.00", "VL_ICMS_ST": "0.00", "VL_IPI": "50.00",
        })

        nfe_id = _insert_xml(db, chave=chave, vl_doc=1000.0, vl_icms=120.0, vl_ipi=50.0)

        engine = CrossValidationEngine(db, 1, regime="normal")
        findings = engine.run()

        # Deve ter XC003 (VL_DOC divergente)
        xc003 = [f for f in findings if f.rule_id == "XC003"]
        assert len(xc003) == 1
        assert xc003[0].severity == "critico"

    def test_engine_persist_findings(self, db):
        _insert_sped_file(db)
        chave = "12345678901234567890123456789012345678901234"

        c100_id = _insert_c100(db, fields={
            "CHV_NFE": chave, "COD_MOD": "55", "IND_EMIT": "0",
            "COD_SIT": "00", "VL_DOC": "999.00",
        })

        nfe_id = _insert_xml(db, chave=chave, vl_doc=1000.0)

        engine = CrossValidationEngine(db, 1, regime="normal")
        engine.run()
        count = engine.persist_findings()
        assert count > 0

        # Verificar que os findings estao na tabela
        rows = db.execute(
            "SELECT COUNT(*) FROM cross_validation_findings WHERE file_id = 1"
        ).fetchone()
        assert rows[0] > 0

    def test_engine_xc008_cancelada(self, db):
        _insert_sped_file(db)
        chave = "12345678901234567890123456789012345678901234"

        c100_id = _insert_c100(db, fields={
            "CHV_NFE": chave, "COD_MOD": "55", "COD_SIT": "00",
            "IND_EMIT": "0", "VL_DOC": "1000.00",
        })

        nfe_id = _insert_xml(db, chave=chave, prot_cstat="101", vl_doc=1000.0)

        engine = CrossValidationEngine(db, 1, regime="normal")
        findings = engine.run()

        xc008 = [f for f in findings if f.rule_id == "XC008"]
        assert len(xc008) == 1
        assert xc008[0].severity == "critico"
        assert xc008[0].tipo_irregularidade == "CANCELAMENTO"


# ── Testes XC051 — Triangular C190 vs C170 vs XML ───────────────────

class TestXC051Triangular:
    """Testes da regra XC051 — validacao triangular C190 x C170 x XML."""

    def test_xc051_c190_diverge_xml_confirma_c170(self):
        """C190.VL_OPR diverge de C170. XML concorda com C170 → erro no C190."""
        from src.services.cross_engine import run_xc051_c190_triangular

        scope = DocumentScope(
            match_status="matched",
            chave_nfe="abc",
            xml_data={"totais": {}},
            item_pairs=[
                ItemPair(
                    c170=SpedC170Item(num_item=1, cst_icms="000", cfop="5102",
                                      aliq_icms=18.0, vl_item=1000.0, vl_desc=0.0, vl_icms=180.0),
                    xml_item=XmlItemParsed(num_item=1, cst_icms="000", cfop="5102",
                                           aliq_icms=18.0, vl_prod=1000.0, vl_desc=0.0, vl_icms=180.0),
                    match_state=ItemMatchState.MATCH_EXATO,
                ),
            ],
            c190_records=[{
                "CST_ICMS": "000", "CFOP": "5102", "ALIQ_ICMS": 18.0,
                "VL_OPR": 1500.0,  # Diverge! C170=1000, XML=1000
                "VL_ICMS": 180.0,
            }],
        )

        findings = run_xc051_c190_triangular(scope)
        xc051 = [f for f in findings if f.rule_id == "XC051"]
        assert len(xc051) >= 1
        assert "XML confirma C170" in xc051[0].description

    def test_xc051_c190_diverge_xml_confirma_c190(self):
        """C190.VL_OPR diverge de C170. XML concorda com C190 → erro nos C170."""
        from src.services.cross_engine import run_xc051_c190_triangular

        scope = DocumentScope(
            match_status="matched",
            chave_nfe="abc",
            xml_data={"totais": {}},
            item_pairs=[
                ItemPair(
                    c170=SpedC170Item(num_item=1, cst_icms="000", cfop="5102",
                                      aliq_icms=18.0, vl_item=800.0, vl_desc=0.0, vl_icms=144.0),
                    xml_item=XmlItemParsed(num_item=1, cst_icms="000", cfop="5102",
                                           aliq_icms=18.0, vl_prod=1000.0, vl_desc=0.0, vl_icms=180.0),
                    match_state=ItemMatchState.MATCH_EXATO,
                ),
            ],
            c190_records=[{
                "CST_ICMS": "000", "CFOP": "5102", "ALIQ_ICMS": 18.0,
                "VL_OPR": 1000.0,  # Bate com XML (1000), diverge de C170 (800)
                "VL_ICMS": 180.0,
            }],
        )

        findings = run_xc051_c190_triangular(scope)
        xc051 = [f for f in findings if f.rule_id == "XC051"]
        assert len(xc051) >= 1
        assert "XML confirma C190" in xc051[0].description

    def test_xc051_sem_divergencia(self):
        """Quando tudo bate, nenhum finding XC051."""
        from src.services.cross_engine import run_xc051_c190_triangular

        scope = DocumentScope(
            match_status="matched",
            chave_nfe="abc",
            xml_data={"totais": {}},
            item_pairs=[
                ItemPair(
                    c170=SpedC170Item(num_item=1, cst_icms="000", cfop="5102",
                                      aliq_icms=18.0, vl_item=1000.0, vl_desc=0.0, vl_icms=180.0),
                    xml_item=XmlItemParsed(num_item=1, cst_icms="000", cfop="5102",
                                           aliq_icms=18.0, vl_prod=1000.0, vl_desc=0.0, vl_icms=180.0),
                    match_state=ItemMatchState.MATCH_EXATO,
                ),
            ],
            c190_records=[{
                "CST_ICMS": "000", "CFOP": "5102", "ALIQ_ICMS": 18.0,
                "VL_OPR": 1000.0,  # Bate com C170 e XML
                "VL_ICMS": 180.0,
            }],
        )

        findings = run_xc051_c190_triangular(scope)
        assert len(findings) == 0

    def test_xc051_sem_xml_nao_executa(self):
        """Sem XML no scope, XC051 nao executa."""
        from src.services.cross_engine import run_xc051_c190_triangular

        scope = DocumentScope(
            match_status="sem_xml",
            chave_nfe="abc",
            c190_records=[{"CST_ICMS": "000", "CFOP": "5102", "ALIQ_ICMS": 18.0, "VL_OPR": 1000.0, "VL_ICMS": 180.0}],
        )
        findings = run_xc051_c190_triangular(scope)
        assert len(findings) == 0
