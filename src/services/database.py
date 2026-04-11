"""Schema e gerenciamento do banco de auditoria SPED."""

from __future__ import annotations

import sqlite3
from pathlib import Path

_AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS sped_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    hash_sha256 TEXT NOT NULL,
    upload_date TEXT DEFAULT (datetime('now')),
    period_start TEXT,
    period_end TEXT,
    company_name TEXT,
    cnpj TEXT,
    uf TEXT,
    total_records INTEGER DEFAULT 0,
    total_errors INTEGER DEFAULT 0,
    status TEXT DEFAULT 'uploaded'
);

CREATE TABLE IF NOT EXISTS sped_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    line_number INTEGER NOT NULL,
    register TEXT NOT NULL,
    block TEXT NOT NULL,
    parent_id INTEGER,
    fields_json TEXT NOT NULL,
    raw_line TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    FOREIGN KEY (file_id) REFERENCES sped_files(id)
);

CREATE INDEX IF NOT EXISTS idx_sped_records_file ON sped_records(file_id);
CREATE INDEX IF NOT EXISTS idx_sped_records_register ON sped_records(register);
CREATE INDEX IF NOT EXISTS idx_sped_records_status ON sped_records(status);

CREATE TABLE IF NOT EXISTS validation_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    record_id INTEGER,
    line_number INTEGER NOT NULL,
    register TEXT NOT NULL,
    field_no INTEGER,
    field_name TEXT,
    value TEXT,
    error_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'error',
    message TEXT NOT NULL,
    doc_suggestion TEXT,
    status TEXT DEFAULT 'open',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (file_id) REFERENCES sped_files(id),
    FOREIGN KEY (record_id) REFERENCES sped_records(id)
);

CREATE INDEX IF NOT EXISTS idx_val_errors_file ON validation_errors(file_id);
CREATE INDEX IF NOT EXISTS idx_val_errors_type ON validation_errors(error_type);

CREATE TABLE IF NOT EXISTS cross_validations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    validation_type TEXT NOT NULL,
    source_register TEXT,
    source_line INTEGER,
    target_register TEXT,
    target_line INTEGER,
    expected_value TEXT,
    actual_value TEXT,
    difference REAL,
    severity TEXT NOT NULL DEFAULT 'error',
    message TEXT NOT NULL,
    status TEXT DEFAULT 'open',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (file_id) REFERENCES sped_files(id)
);

CREATE INDEX IF NOT EXISTS idx_cross_val_file ON cross_validations(file_id);

CREATE TABLE IF NOT EXISTS corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    record_id INTEGER NOT NULL,
    field_no INTEGER NOT NULL,
    field_name TEXT NOT NULL,
    old_value TEXT NOT NULL,
    new_value TEXT NOT NULL,
    error_id INTEGER,
    applied_by TEXT DEFAULT 'user',
    applied_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (file_id) REFERENCES sped_files(id),
    FOREIGN KEY (record_id) REFERENCES sped_records(id),
    FOREIGN KEY (error_id) REFERENCES validation_errors(id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    details TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (file_id) REFERENCES sped_files(id)
);

CREATE TABLE IF NOT EXISTS embedding_metadata (
    id INTEGER PRIMARY KEY,
    model_name TEXT NOT NULL,
    model_version TEXT,
    indexed_at TEXT DEFAULT (datetime('now')),
    chunks_count INTEGER
);
"""


_MIGRATIONS: dict[int, list[str]] = {
    1: [
        "ALTER TABLE validation_errors ADD COLUMN friendly_message TEXT",
        "ALTER TABLE validation_errors ADD COLUMN legal_basis TEXT",
        "ALTER TABLE validation_errors ADD COLUMN expected_value TEXT",
        "ALTER TABLE validation_errors ADD COLUMN auto_correctable INTEGER DEFAULT 0",
        "ALTER TABLE sped_files ADD COLUMN validation_stage TEXT",
        "ALTER TABLE sped_files ADD COLUMN auto_corrections_applied INTEGER DEFAULT 0",
    ],
    2: [
        "ALTER TABLE validation_errors ADD COLUMN record_id INTEGER REFERENCES sped_records(id)",
    ],
    3: [
        "ALTER TABLE sped_files ADD COLUMN regime_tributario TEXT",
    ],
    4: [
        "ALTER TABLE corrections ADD COLUMN justificativa TEXT",
        "ALTER TABLE corrections ADD COLUMN correction_type TEXT",
        "ALTER TABLE corrections ADD COLUMN rule_id TEXT",
    ],
    5: [
        "ALTER TABLE validation_errors ADD COLUMN categoria TEXT DEFAULT 'fiscal'",
    ],
    6: [
        "ALTER TABLE validation_errors ADD COLUMN certeza TEXT DEFAULT 'objetivo'",
        "ALTER TABLE validation_errors ADD COLUMN impacto TEXT DEFAULT 'relevante'",
    ],
    7: [
        "ALTER TABLE sped_files ADD COLUMN cod_ver INTEGER DEFAULT 0",
        "ALTER TABLE sped_files ADD COLUMN original_file_id INTEGER REFERENCES sped_files(id)",
        "ALTER TABLE sped_files ADD COLUMN is_retificador INTEGER DEFAULT 0",
        """CREATE TABLE IF NOT EXISTS sped_file_versions (
            id INTEGER PRIMARY KEY,
            original_file_id INTEGER NOT NULL,
            retificador_file_id INTEGER NOT NULL,
            cod_ver INTEGER NOT NULL,
            linked_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (original_file_id) REFERENCES sped_files(id),
            FOREIGN KEY (retificador_file_id) REFERENCES sped_files(id)
        )""",
    ],
    8: [
        "ALTER TABLE sped_files ADD COLUMN regime_override TEXT",
    ],
    9: [
        """CREATE TABLE IF NOT EXISTS finding_resolutions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id       TEXT NOT NULL,
            finding_id    TEXT NOT NULL,
            rule_id       TEXT NOT NULL,
            status        TEXT NOT NULL CHECK(status IN ('open','accepted','rejected','deferred','noted')),
            user_id       TEXT,
            justificativa TEXT,
            prazo_revisao DATE,
            resolved_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(file_id, finding_id)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_finding_res_file ON finding_resolutions(file_id)",
    ],
    10: [
        "ALTER TABLE validation_errors ADD COLUMN materialidade REAL DEFAULT 0",
    ],
    11: [
        "ALTER TABLE sped_files ADD COLUMN ind_regime TEXT DEFAULT 'DESCONHECIDO'",
        "ALTER TABLE sped_files ADD COLUMN regime_confidence REAL DEFAULT 0.0",
        "ALTER TABLE sped_files ADD COLUMN regime_signals TEXT DEFAULT '[]'",
    ],
    12: [
        # NF-e XMLs uploadados
        """CREATE TABLE IF NOT EXISTS nfe_xmls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL,
            chave_nfe TEXT NOT NULL,
            numero_nfe TEXT,
            serie TEXT,
            cnpj_emitente TEXT,
            cnpj_destinatario TEXT,
            dh_emissao TEXT,
            vl_doc REAL DEFAULT 0,
            vl_icms REAL DEFAULT 0,
            vl_icms_st REAL DEFAULT 0,
            vl_ipi REAL DEFAULT 0,
            vl_pis REAL DEFAULT 0,
            vl_cofins REAL DEFAULT 0,
            qtd_itens INTEGER DEFAULT 0,
            prot_cstat TEXT,
            status TEXT DEFAULT 'active',
            parsed_json TEXT,
            upload_date TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (file_id) REFERENCES sped_files(id)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_nfe_xmls_file ON nfe_xmls(file_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_nfe_xmls_file_chave ON nfe_xmls(file_id, chave_nfe)",
        "CREATE INDEX IF NOT EXISTS idx_nfe_xmls_cstat ON nfe_xmls(prot_cstat)",
        # Itens da NF-e
        """CREATE TABLE IF NOT EXISTS nfe_itens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nfe_id INTEGER NOT NULL,
            num_item INTEGER,
            cod_produto TEXT,
            ncm TEXT,
            cfop TEXT,
            vl_prod REAL DEFAULT 0,
            vl_desc REAL DEFAULT 0,
            cst_icms TEXT,
            vbc_icms REAL DEFAULT 0,
            aliq_icms REAL DEFAULT 0,
            vl_icms REAL DEFAULT 0,
            cst_ipi TEXT,
            vl_ipi REAL DEFAULT 0,
            cst_pis TEXT,
            vl_pis REAL DEFAULT 0,
            cst_cofins TEXT,
            vl_cofins REAL DEFAULT 0,
            FOREIGN KEY (nfe_id) REFERENCES nfe_xmls(id) ON DELETE CASCADE
        )""",
        "CREATE INDEX IF NOT EXISTS idx_nfe_itens_nfe ON nfe_itens(nfe_id, num_item)",
        # Resultado do cruzamento
        """CREATE TABLE IF NOT EXISTS nfe_cruzamento (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL,
            nfe_id INTEGER,
            chave_nfe TEXT NOT NULL,
            rule_id TEXT NOT NULL,
            severity TEXT NOT NULL,
            campo_xml TEXT,
            valor_xml TEXT,
            campo_sped TEXT,
            valor_sped TEXT,
            diferenca REAL,
            message TEXT,
            status TEXT DEFAULT 'open',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (file_id) REFERENCES sped_files(id),
            FOREIGN KEY (nfe_id) REFERENCES nfe_xmls(id)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_nfe_cruz_file ON nfe_cruzamento(file_id, rule_id, severity)",
        "CREATE INDEX IF NOT EXISTS idx_nfe_cruz_chave ON nfe_cruzamento(chave_nfe)",
        # Cache de IA para explicações de erros
        """CREATE TABLE IF NOT EXISTS ai_error_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chave_hash TEXT UNIQUE NOT NULL,
            rule_id TEXT,
            error_type TEXT,
            regime TEXT,
            uf TEXT,
            beneficio_codigo TEXT,
            ind_oper TEXT,
            campo_principal TEXT,
            explicacao_texto TEXT,
            sugestao_texto TEXT,
            modelo_usado TEXT,
            prompt_version INTEGER DEFAULT 1,
            rule_version INTEGER DEFAULT 1,
            gerado_em TEXT DEFAULT (datetime('now')),
            hits INTEGER DEFAULT 0
        )""",
        "CREATE INDEX IF NOT EXISTS idx_ai_cache_hash ON ai_error_cache(chave_hash)",
        "CREATE INDEX IF NOT EXISTS idx_ai_cache_type ON ai_error_cache(error_type, regime, uf)",
    ],
    13: [
        # Corrige UNIQUE index de nfe_xmls: era global por chave_nfe, agora por (file_id, chave_nfe)
        "DROP INDEX IF EXISTS idx_nfe_xmls_chave",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_nfe_xmls_file_chave ON nfe_xmls(file_id, chave_nfe)",
    ],
    14: [
        # ── Migration 14: Context-First — Dados mestres e rastreabilidade (Fase 2) ──

        # Cadastro mestre de contribuintes
        """CREATE TABLE IF NOT EXISTS clientes (
            id              INTEGER PRIMARY KEY,
            cnpj            TEXT UNIQUE NOT NULL,
            razao_social    TEXT NOT NULL,
            regime          TEXT NOT NULL
                            CHECK(regime IN ('LP','LR','SN','MEI','Imune','Isento')),
            regime_override TEXT,
            uf              TEXT DEFAULT 'ES',
            cnae_principal  TEXT,
            porte           TEXT CHECK(porte IN ('ME','EPP','Medio','Grande')),
            ativo           INTEGER DEFAULT 1,
            created_at      TEXT DEFAULT (datetime('now')),
            updated_at      TEXT DEFAULT (datetime('now'))
        )""",
        "CREATE INDEX IF NOT EXISTS idx_clientes_cnpj ON clientes(cnpj)",

        # Beneficios fiscais ativos por cliente e periodo
        """CREATE TABLE IF NOT EXISTS beneficios_ativos (
            id                  INTEGER PRIMARY KEY,
            cliente_id          INTEGER NOT NULL REFERENCES clientes(id),
            codigo_beneficio    TEXT NOT NULL,
            tipo                TEXT NOT NULL,
            competencia_inicio  TEXT NOT NULL,
            competencia_fim     TEXT,
            ato_concessorio     TEXT,
            aliq_icms_efetiva   REAL,
            reducao_base_pct    REAL,
            debito_integral     INTEGER DEFAULT 0,
            observacoes         TEXT,
            ativo               INTEGER DEFAULT 1
        )""",
        "CREATE INDEX IF NOT EXISTS idx_beneficios_cliente_periodo ON beneficios_ativos(cliente_id, competencia_inicio, competencia_fim)",

        # CRT dos emitentes (populado durante parsing de XMLs)
        """CREATE TABLE IF NOT EXISTS emitentes_crt (
            cnpj_emitente  TEXT PRIMARY KEY,
            crt            INTEGER NOT NULL CHECK(crt IN (1, 2, 3)),
            razao_social   TEXT,
            uf_emitente    TEXT,
            last_seen      TEXT DEFAULT (datetime('now')),
            fonte          TEXT DEFAULT 'xml' CHECK(fonte IN ('xml', 'manual'))
        )""",
        "CREATE INDEX IF NOT EXISTS idx_emitentes_crt ON emitentes_crt(cnpj_emitente)",

        # Snapshot de cada execucao de auditoria
        """CREATE TABLE IF NOT EXISTS validation_runs (
            id                 INTEGER PRIMARY KEY,
            file_id            INTEGER NOT NULL REFERENCES sped_files(id),
            mode               TEXT NOT NULL CHECK(mode IN ('sped_only','sped_xml')),
            cliente_id         INTEGER REFERENCES clientes(id),
            regime_usado       TEXT,
            regime_source      TEXT,
            beneficios_json    TEXT,
            context_hash       TEXT,
            rules_version      TEXT,
            xml_cobertura_pct  REAL,
            executed_rules     INTEGER DEFAULT 0,
            skipped_rules      INTEGER DEFAULT 0,
            total_findings     INTEGER DEFAULT 0,
            coverage_score     REAL,
            risk_score         REAL,
            started_at         TEXT DEFAULT (datetime('now')),
            finished_at        TEXT,
            status             TEXT DEFAULT 'running'
                               CHECK(status IN ('running','done','error','blocked'))
        )""",
        "CREATE INDEX IF NOT EXISTS idx_validation_runs_file ON validation_runs(file_id, mode)",

        # Indice de pareamento XML <-> C100 (Trilha B)
        """CREATE TABLE IF NOT EXISTS xml_match_index (
            id            INTEGER PRIMARY KEY,
            run_id        INTEGER NOT NULL REFERENCES validation_runs(id),
            xml_id        INTEGER REFERENCES nfe_xmls(id),
            sped_c100_id  INTEGER,
            match_status  TEXT CHECK(match_status IN
                          ('matched','sem_xml','sem_c100','fora_periodo','cancelada')),
            chave_nfe     TEXT,
            confidence    REAL DEFAULT 1.0,
            reason        TEXT
        )""",
        "CREATE INDEX IF NOT EXISTS idx_xml_match_run ON xml_match_index(run_id, match_status)",

        # Lacunas de cobertura registradas por execucao
        """CREATE TABLE IF NOT EXISTS coverage_gaps (
            id            INTEGER PRIMARY KEY,
            run_id        INTEGER NOT NULL REFERENCES validation_runs(id),
            gap_type      TEXT NOT NULL,
            description   TEXT,
            affected_rule TEXT,
            severity      TEXT CHECK(severity IN ('critical','high','medium','low'))
        )""",
        "CREATE INDEX IF NOT EXISTS idx_coverage_gaps_run ON coverage_gaps(run_id, gap_type)",

        # Snapshot de contexto fiscal para audit trail
        """CREATE TABLE IF NOT EXISTS fiscal_context_snapshots (
            id                      INTEGER PRIMARY KEY,
            run_id                  INTEGER NOT NULL REFERENCES validation_runs(id),
            cnpj                    TEXT,
            uf                      TEXT,
            periodo                 TEXT,
            regime                  TEXT,
            ind_perfil              TEXT,
            beneficios_json         TEXT,
            tables_available_json   TEXT,
            context_hash            TEXT
        )""",

        # Campos adicionais em nfe_xmls (correcao P2: CRT do emitente)
        "ALTER TABLE nfe_xmls ADD COLUMN crt_emitente INTEGER",
        "ALTER TABLE nfe_xmls ADD COLUMN uf_emitente TEXT",
        "ALTER TABLE nfe_xmls ADD COLUMN uf_dest TEXT",
        "ALTER TABLE nfe_xmls ADD COLUMN mod_nfe INTEGER DEFAULT 55",
        "ALTER TABLE nfe_xmls ADD COLUMN dentro_periodo INTEGER DEFAULT 1",
        "ALTER TABLE nfe_xmls ADD COLUMN c_sit TEXT",
        "ALTER TABLE nfe_xmls ADD COLUMN content_hash TEXT",

        # Rastreabilidade de divergencias por item no cruzamento
        "ALTER TABLE nfe_cruzamento ADD COLUMN nfe_item_id INTEGER",
        "ALTER TABLE nfe_cruzamento ADD COLUMN xml_xpath TEXT",
        "ALTER TABLE nfe_cruzamento ADD COLUMN tipo_comp TEXT",

        # Indices adicionais
        "CREATE INDEX IF NOT EXISTS idx_nfe_xmls_crt ON nfe_xmls(crt_emitente)",
        "CREATE INDEX IF NOT EXISTS idx_nfe_xmls_periodo ON nfe_xmls(file_id, dentro_periodo)",
    ],
}


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Executa migrações incrementais usando PRAGMA user_version."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for version in sorted(_MIGRATIONS):
        if version > current:
            for stmt in _MIGRATIONS[version]:
                try:
                    conn.execute(stmt)
                except sqlite3.OperationalError as e:
                    if "duplicate column" not in str(e).lower():
                        raise
            conn.execute(f"PRAGMA user_version = {version}")
            conn.commit()


def init_audit_db(db_path: str | Path) -> sqlite3.Connection:
    """Cria o banco de auditoria com todas as tabelas."""
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_AUDIT_SCHEMA)
    _run_migrations(conn)
    return conn


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """Abre conexão com o banco de auditoria existente."""
    conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    _run_migrations(conn)
    return conn
