-- Schema PostgreSQL para SPED Audit
-- Migrado de SQLite com JSONB e indices GIN

CREATE TABLE IF NOT EXISTS sped_files (
    id SERIAL PRIMARY KEY,
    filename TEXT NOT NULL,
    hash_sha256 TEXT NOT NULL,
    upload_date TIMESTAMP DEFAULT NOW(),
    period_start TEXT,
    period_end TEXT,
    company_name TEXT,
    cnpj TEXT,
    uf TEXT,
    total_records INTEGER DEFAULT 0,
    total_errors INTEGER DEFAULT 0,
    status TEXT DEFAULT 'uploaded',
    validation_stage TEXT,
    auto_corrections_applied INTEGER DEFAULT 0,
    regime_tributario TEXT,
    cod_ver INTEGER DEFAULT 0,
    original_file_id INTEGER REFERENCES sped_files(id),
    is_retificador INTEGER DEFAULT 0,
    regime_override TEXT,
    ind_regime TEXT DEFAULT 'DESCONHECIDO',
    regime_confidence REAL DEFAULT 0.0,
    regime_signals TEXT DEFAULT '[]',
    xml_crossref_completed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sped_records (
    id SERIAL PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES sped_files(id),
    line_number INTEGER NOT NULL,
    register TEXT NOT NULL,
    block TEXT NOT NULL,
    parent_id INTEGER,
    fields_json JSONB NOT NULL,
    raw_line TEXT NOT NULL,
    status TEXT DEFAULT 'pending'
);
CREATE INDEX IF NOT EXISTS idx_sr_file ON sped_records(file_id);
CREATE INDEX IF NOT EXISTS idx_sr_register ON sped_records(register);
CREATE INDEX IF NOT EXISTS idx_sr_file_reg ON sped_records(file_id, register);
CREATE INDEX IF NOT EXISTS idx_sr_fields ON sped_records USING GIN (fields_json);

CREATE TABLE IF NOT EXISTS validation_errors (
    id SERIAL PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES sped_files(id),
    record_id INTEGER REFERENCES sped_records(id),
    line_number INTEGER NOT NULL,
    register TEXT NOT NULL,
    field_no INTEGER,
    field_name TEXT,
    value TEXT,
    expected_value TEXT,
    error_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'error',
    message TEXT NOT NULL,
    friendly_message TEXT,
    doc_suggestion TEXT,
    legal_basis TEXT,
    auto_correctable INTEGER DEFAULT 0,
    status TEXT DEFAULT 'open',
    categoria TEXT DEFAULT 'fiscal',
    certeza TEXT DEFAULT 'objetivo',
    impacto TEXT DEFAULT 'relevante',
    materialidade REAL DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ve_file ON validation_errors(file_id);
CREATE INDEX IF NOT EXISTS idx_ve_type ON validation_errors(error_type);
CREATE INDEX IF NOT EXISTS idx_ve_cat ON validation_errors(file_id, categoria);

CREATE TABLE IF NOT EXISTS cross_validations (
    id SERIAL PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES sped_files(id),
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
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_cv_file ON cross_validations(file_id);

CREATE TABLE IF NOT EXISTS corrections (
    id SERIAL PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES sped_files(id),
    record_id INTEGER NOT NULL REFERENCES sped_records(id),
    field_no INTEGER NOT NULL,
    field_name TEXT NOT NULL,
    old_value TEXT NOT NULL,
    new_value TEXT NOT NULL,
    error_id INTEGER REFERENCES validation_errors(id),
    applied_by TEXT DEFAULT 'user',
    applied_at TIMESTAMP DEFAULT NOW(),
    justificativa TEXT,
    correction_type TEXT,
    rule_id TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES sped_files(id),
    action TEXT NOT NULL,
    details TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS embedding_metadata (
    id SERIAL PRIMARY KEY,
    model_name TEXT NOT NULL,
    model_version TEXT,
    indexed_at TIMESTAMP DEFAULT NOW(),
    chunks_count INTEGER
);

CREATE TABLE IF NOT EXISTS nfe_xmls (
    id SERIAL PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES sped_files(id),
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
    parsed_json JSONB,
    upload_date TIMESTAMP DEFAULT NOW(),
    crt_emitente INTEGER,
    uf_emitente TEXT,
    uf_dest TEXT,
    mod_nfe INTEGER DEFAULT 55,
    dentro_periodo INTEGER DEFAULT 1,
    c_sit TEXT,
    content_hash TEXT,
    UNIQUE(file_id, chave_nfe)
);
CREATE INDEX IF NOT EXISTS idx_nx_file ON nfe_xmls(file_id);
CREATE INDEX IF NOT EXISTS idx_nx_cstat ON nfe_xmls(prot_cstat);
CREATE INDEX IF NOT EXISTS idx_nx_crt ON nfe_xmls(crt_emitente);
CREATE INDEX IF NOT EXISTS idx_nx_periodo ON nfe_xmls(file_id, dentro_periodo);

CREATE TABLE IF NOT EXISTS nfe_itens (
    id SERIAL PRIMARY KEY,
    nfe_id INTEGER NOT NULL REFERENCES nfe_xmls(id) ON DELETE CASCADE,
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
    vl_cofins REAL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_ni_nfe ON nfe_itens(nfe_id, num_item);

CREATE TABLE IF NOT EXISTS nfe_cruzamento (
    id SERIAL PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES sped_files(id),
    nfe_id INTEGER REFERENCES nfe_xmls(id),
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
    created_at TIMESTAMP DEFAULT NOW(),
    nfe_item_id INTEGER,
    xml_xpath TEXT,
    tipo_comp TEXT
);
CREATE INDEX IF NOT EXISTS idx_nc_file ON nfe_cruzamento(file_id, rule_id, severity);
CREATE INDEX IF NOT EXISTS idx_nc_chave ON nfe_cruzamento(chave_nfe);

CREATE TABLE IF NOT EXISTS ai_error_cache (
    id SERIAL PRIMARY KEY,
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
    gerado_em TIMESTAMP DEFAULT NOW(),
    hits INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_ac_hash ON ai_error_cache(chave_hash);
CREATE INDEX IF NOT EXISTS idx_ac_type ON ai_error_cache(error_type, regime, uf);

CREATE TABLE IF NOT EXISTS sped_file_versions (
    id SERIAL PRIMARY KEY,
    original_file_id INTEGER NOT NULL REFERENCES sped_files(id),
    retificador_file_id INTEGER NOT NULL REFERENCES sped_files(id),
    cod_ver INTEGER NOT NULL,
    linked_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS finding_resolutions (
    id SERIAL PRIMARY KEY,
    file_id TEXT NOT NULL,
    finding_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('open','accepted','rejected','deferred','noted')),
    user_id TEXT,
    justificativa TEXT,
    prazo_revisao DATE,
    resolved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(file_id, finding_id)
);
CREATE INDEX IF NOT EXISTS idx_fr_file ON finding_resolutions(file_id);

CREATE TABLE IF NOT EXISTS clientes (
    id SERIAL PRIMARY KEY,
    cnpj TEXT UNIQUE NOT NULL,
    razao_social TEXT NOT NULL,
    regime TEXT NOT NULL CHECK(regime IN ('LP','LR','SN','MEI','Imune','Isento')),
    regime_override TEXT,
    uf TEXT DEFAULT 'ES',
    cnae_principal TEXT,
    porte TEXT CHECK(porte IN ('ME','EPP','Medio','Grande')),
    ativo INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_cl_cnpj ON clientes(cnpj);

CREATE TABLE IF NOT EXISTS beneficios_ativos (
    id SERIAL PRIMARY KEY,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    codigo_beneficio TEXT NOT NULL,
    tipo TEXT NOT NULL,
    competencia_inicio TEXT NOT NULL,
    competencia_fim TEXT,
    ato_concessorio TEXT,
    aliq_icms_efetiva REAL,
    reducao_base_pct REAL,
    debito_integral INTEGER DEFAULT 0,
    observacoes TEXT,
    ativo INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_ba_cli ON beneficios_ativos(cliente_id, competencia_inicio, competencia_fim);

CREATE TABLE IF NOT EXISTS emitentes_crt (
    cnpj_emitente TEXT PRIMARY KEY,
    crt INTEGER NOT NULL CHECK(crt IN (1, 2, 3)),
    razao_social TEXT,
    uf_emitente TEXT,
    last_seen TIMESTAMP DEFAULT NOW(),
    fonte TEXT DEFAULT 'xml' CHECK(fonte IN ('xml','manual'))
);

CREATE TABLE IF NOT EXISTS validation_runs (
    id SERIAL PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES sped_files(id),
    mode TEXT NOT NULL CHECK(mode IN ('sped_only','sped_xml')),
    cliente_id INTEGER REFERENCES clientes(id),
    regime_usado TEXT,
    regime_source TEXT,
    beneficios_json TEXT,
    context_hash TEXT,
    rules_version TEXT,
    xml_cobertura_pct REAL,
    executed_rules INTEGER DEFAULT 0,
    skipped_rules INTEGER DEFAULT 0,
    total_findings INTEGER DEFAULT 0,
    coverage_score REAL,
    risk_score REAL,
    started_at TIMESTAMP DEFAULT NOW(),
    finished_at TIMESTAMP,
    status TEXT DEFAULT 'running' CHECK(status IN ('running','done','error','blocked'))
);
CREATE INDEX IF NOT EXISTS idx_vr_file ON validation_runs(file_id, mode);

CREATE TABLE IF NOT EXISTS xml_match_index (
    id SERIAL PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES validation_runs(id),
    xml_id INTEGER REFERENCES nfe_xmls(id),
    sped_c100_id INTEGER,
    match_status TEXT CHECK(match_status IN ('matched','sem_xml','sem_c100','fora_periodo','cancelada')),
    chave_nfe TEXT,
    confidence REAL DEFAULT 1.0,
    reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_xm_run ON xml_match_index(run_id, match_status);

CREATE TABLE IF NOT EXISTS coverage_gaps (
    id SERIAL PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES validation_runs(id),
    gap_type TEXT NOT NULL,
    description TEXT,
    affected_rule TEXT,
    severity TEXT CHECK(severity IN ('critical','high','medium','low'))
);
CREATE INDEX IF NOT EXISTS idx_cg_run ON coverage_gaps(run_id, gap_type);

CREATE TABLE IF NOT EXISTS fiscal_context_snapshots (
    id SERIAL PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES validation_runs(id),
    cnpj TEXT,
    uf TEXT,
    periodo TEXT,
    regime TEXT,
    ind_perfil TEXT,
    beneficios_json TEXT,
    tables_available_json TEXT,
    context_hash TEXT
);

-- Migration 16: Motor de Cruzamento v.FINAL

CREATE TABLE IF NOT EXISTS suggested_action_types (
    code        TEXT PRIMARY KEY,
    label_pt    TEXT NOT NULL,
    description TEXT
);
INSERT INTO suggested_action_types VALUES
    ('corrigir_no_sped',          'Corrigir no SPED',           'Campo do arquivo EFD deve ser corrigido'),
    ('revisar_xml_emissor',       'Revisar XML com emissor',    'Inconsistencia na NF-e emitida'),
    ('revisar_parametrizacao_erp','Revisar parametrizacao ERP', 'Regra de escrituracao incorreta no sistema'),
    ('revisar_cadastro',          'Revisar cadastro',           'Dado cadastral divergente ou ausente'),
    ('revisar_beneficio',         'Revisar beneficio fiscal',   'Aplicacao incorreta de beneficio'),
    ('revisar_apuracao',          'Revisar apuracao',           'Erro ou omissao no bloco de apuracao'),
    ('investigar',                'Investigar',                 'Indicio nao conclusivo — requer analise manual')
ON CONFLICT (code) DO NOTHING;

CREATE TABLE IF NOT EXISTS cross_validation_findings (
    id                      SERIAL PRIMARY KEY,
    file_id                 INTEGER NOT NULL REFERENCES sped_files(id),
    document_scope_id       INTEGER,
    chave_nfe               TEXT,
    rule_id                 TEXT NOT NULL,
    legacy_rule_id          TEXT,
    rule_version            TEXT,
    reference_pack_version  TEXT,
    benefit_context_version TEXT,
    layout_version_detected TEXT,
    config_hash             TEXT,
    error_type              TEXT NOT NULL,
    rule_outcome            TEXT NOT NULL CHECK (rule_outcome IN (
                                'EXECUTED_ERROR', 'EXECUTED_OK', 'NOT_APPLICABLE',
                                'NOT_EXECUTED_MISSING_DATA', 'SUPPRESSED_BY_ROOT_CAUSE',
                                'NEUTRALIZED_BY_BENEFIT', 'AMBIGUOUS_MATCH'
                            )),
    tipo_irregularidade     TEXT,
    severity                TEXT NOT NULL CHECK (severity IN ('critico', 'error', 'warning', 'info')),
    confidence              TEXT,
    sped_register           TEXT,
    sped_field              TEXT,
    value_sped              TEXT,
    xml_field               TEXT,
    value_xml               TEXT,
    description             TEXT,
    evidence                TEXT,
    regime_context          TEXT,
    benefit_context         TEXT,
    suggested_action        TEXT NOT NULL DEFAULT 'investigar',
    root_cause_group        TEXT,
    is_derived              INTEGER DEFAULT 0,
    risk_score              REAL,
    technical_risk_score    REAL,
    fiscal_impact_estimate  REAL,
    action_priority         TEXT CHECK (action_priority IN ('P1','P2','P3','P4')),
    review_status           TEXT DEFAULT 'novo' CHECK (review_status IN (
                                'novo', 'em_revisao', 'justificado',
                                'corrigido', 'ignorado', 'falso_positivo'
                            )),
    reviewed_by             TEXT,
    reviewed_at             TIMESTAMP,
    review_reason           TEXT,
    review_evidence_ref     TEXT,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_xvf_file ON cross_validation_findings(file_id);
CREATE INDEX IF NOT EXISTS idx_xvf_rule ON cross_validation_findings(file_id, rule_id);
CREATE INDEX IF NOT EXISTS idx_xvf_severity ON cross_validation_findings(file_id, severity);
CREATE INDEX IF NOT EXISTS idx_xvf_priority ON cross_validation_findings(file_id, action_priority);
CREATE INDEX IF NOT EXISTS idx_xvf_root_cause ON cross_validation_findings(root_cause_group);
CREATE INDEX IF NOT EXISTS idx_xvf_review ON cross_validation_findings(review_status);

-- Extensoes xml_match_index (migration 16)
ALTER TABLE xml_match_index ADD COLUMN IF NOT EXISTS is_complementar INTEGER DEFAULT 0;
ALTER TABLE xml_match_index ADD COLUMN IF NOT EXISTS xml_eligible INTEGER DEFAULT 1;
ALTER TABLE xml_match_index ADD COLUMN IF NOT EXISTS xml_effective_version TEXT;
ALTER TABLE xml_match_index ADD COLUMN IF NOT EXISTS xml_effective_event_set TEXT;
ALTER TABLE xml_match_index ADD COLUMN IF NOT EXISTS xml_resolution_reason TEXT;

CREATE TABLE IF NOT EXISTS field_equivalence_map (
    id              SERIAL PRIMARY KEY,
    register_sped   TEXT NOT NULL,
    field_sped      TEXT NOT NULL,
    xml_xpath       TEXT,
    calculo         TEXT,
    fonte           TEXT,
    tolerancia_abs  REAL DEFAULT 0.02,
    tolerancia_rel  REAL DEFAULT 0.0,
    leiaute_min     TEXT,
    leiaute_max     TEXT,
    vigencia_ini    DATE,
    vigencia_fim    DATE,
    UNIQUE (register_sped, field_sped, xml_xpath, leiaute_min)
);

-- Schema version
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);
INSERT INTO schema_version VALUES (16) ON CONFLICT (version) DO UPDATE SET version = 16;
