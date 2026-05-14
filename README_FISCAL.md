# Detalhamento Tecnico-Fiscal — SPED EFD Validator v3.0.0

**Documento de referencia para analista fiscal senior e engenheiro de software**

Este documento descreve, de ponta a ponta, a arquitetura, o motor de regras e a logica fiscal do sistema: desde o upload do arquivo SPED ate o relatorio analitico final, passando pelo cruzamento NF-e XML x SPED e pela revisao por IA. Cada modulo, validador, fonte de dados, tabela e cruzamento esta documentado para permitir auditoria, melhoria continua e extensao do motor.

> Stack: Python 3.10+ (FastAPI), React 18 + TypeScript + Vite, SQLite (auditoria local) ou PostgreSQL 16 (producao), MySQL DCTF_WEB (cadastro de clientes), embeddings `all-MiniLM-L6-v2`, Anthropic Claude Sonnet 4.6 + OpenAI GPT-4o (revisao por IA).

---

## Indice

1. [Visao Geral do Sistema](#1-visao-geral-do-sistema)
2. [Estrutura do Repositorio](#2-estrutura-do-repositorio)
3. [Camadas e Componentes](#3-camadas-e-componentes)
4. [Banco de Dados (SQLite/PostgreSQL)](#4-banco-de-dados-sqlitepostgresql)
5. [API REST — Endpoints](#5-api-rest--endpoints)
6. [Frontend — SPA React](#6-frontend--spa-react)
7. [Entrada de Dados — Upload e Parsing](#7-entrada-de-dados--upload-e-parsing)
8. [ValidationContext — Arquitetura Context-First](#8-validationcontext--arquitetura-context-first)
9. [Fontes de Dados e Tabelas de Referencia](#9-fontes-de-dados-e-tabelas-de-referencia)
10. [Pipeline de Validacao — 4 Estagios](#10-pipeline-de-validacao--4-estagios)
11. [Estagio 1 — Validacao Estrutural](#11-estagio-1--validacao-estrutural)
12. [Estagio 2 — Cruzamentos e Recalculo Tributario](#12-estagio-2--cruzamentos-e-recalculo-tributario)
13. [Estagio 2.5 — Motor de Cruzamento XC (XML x SPED)](#13-estagio-25--motor-de-cruzamento-xc-xml-x-sped)
14. [Estagio 3 — Enriquecimento](#14-estagio-3--enriquecimento)
15. [Deduplicacao Inteligente de Erros](#15-deduplicacao-inteligente-de-erros)
16. [Governanca de Correcoes](#16-governanca-de-correcoes)
17. [Revisao por IA — Tribunal Claude x GPT](#17-revisao-por-ia--tribunal-claude-x-gpt)
18. [Score de Risco e Cobertura](#18-score-de-risco-e-cobertura)
19. [Saida Analitica — Relatorio Final](#19-saida-analitica--relatorio-final)
20. [Mapeamento Completo de Registros SPED](#20-mapeamento-completo-de-registros-sped)
21. [Catalogo de Tipos de Erro](#21-catalogo-de-tipos-de-erro)
22. [Configuracao, Deploy e Execucao](#22-configuracao-deploy-e-execucao)
23. [Testes e Garantia de Qualidade](#23-testes-e-garantia-de-qualidade)
24. [Oportunidades de Melhoria](#24-oportunidades-de-melhoria)

---

## 1. Visao Geral do Sistema

O **SPED EFD Validator** e um sistema de auditoria fiscal automatica para arquivos da Escrituracao Fiscal Digital (EFD ICMS/IPI). Ele recebe o `.txt` do SPED (e, opcionalmente, os XMLs das NF-e do periodo), executa um pipeline de validacoes determinas (estrutura, calculos, cruzamentos, semantica fiscal, beneficios), enriquece os achados com mensagens amigaveis e base legal, e produz um relatorio analitico em Markdown/JSON/CSV — alem de gerar o SPED corrigido.

### Caracteristicas chave

- **193 regras** versionadas em `rules.yaml` com vigencia, severidade, certeza e impacto
- **38 validadores** Python independentes em `src/validators/`
- **Motor de Cruzamento XC** com regras XC001–XC095 (NF-e XML x SPED) — 10 etapas
- **Context-First**: contexto fiscal montado integralmente antes de qualquer validacao, imutavel apos montagem
- **Revisao por IA** com triangulacao Claude Sonnet 4.6 + GPT-4o (tribunal de validacao para grupos de erros)
- **Score de Risco** (materialidade) e **Score de Cobertura** (% da auditoria executada)
- **Cache incremental de IA** por hash de contexto — reutilizavel entre arquivos
- **Auto-correcao governada** com niveis (`automatico`, `proposta`, `investigar`, `impossivel`)
- **Auditoria completa** (`audit_log`, `corrections`, `validation_runs`, `fiscal_context_snapshots`)
- **86 arquivos de teste** com pytest (cobertura alvo >= 80%)

### Stack

| Camada | Tecnologias |
|---|---|
| API | FastAPI 0.100+, Uvicorn, Pydantic v2, autenticacao via `X-API-Key` |
| Frontend | React 18, TypeScript 5, Vite 5, Tailwind 3, Recharts, React Router 6 |
| Persistencia | SQLite 3 (dev local) **ou** PostgreSQL 16 + JSONB/GIN (producao) |
| Cadastro de clientes | MySQL 8 — schema `DCTF_WEB` (regime tributario, beneficios ativos) |
| Documentacao indexada | SQLite FTS5 + embeddings `all-MiniLM-L6-v2` (384 dims, CPU-only) |
| IA (opcional) | Anthropic Claude Sonnet 4.6 (`claude-sonnet-4-6`), OpenAI GPT-4o / GPT-4o-mini |
| Containers | Docker + Compose (api + frontend + db) |

---

## 2. Estrutura do Repositorio

```
SPED/
├── api/                              # FastAPI app + routers + schemas
│   ├── main.py                       # Entry point (CORS, exception handler, healthcheck)
│   ├── auth.py                       # X-API-Key middleware (verify_api_key)
│   ├── deps.py                       # Dependency injection (db, current_file)
│   ├── routers/
│   │   ├── files.py                  # /api/files — upload, list, delete, download
│   │   ├── records.py                # /api/files/{id}/records — leitura/edicao por linha
│   │   ├── validation.py             # /api/files/{id}/validate — pipeline + SSE
│   │   ├── report.py                 # /api/files/{id}/report — md / json / csv / sped
│   │   ├── xml.py                    # /api/files/{id}/xml — upload XMLs + cruzamento
│   │   ├── rules.py                  # /api/rules — listagem/geracao/implementacao de regras
│   │   ├── search.py                 # /api/search — busca FTS5 + semantica na documentacao
│   │   ├── audit_scope.py            # /api/audit-scope — cobertura/limitacoes do arquivo
│   │   ├── clientes.py               # /api/clientes — consulta MySQL DCTF_WEB
│   │   └── ai.py                     # /api/ai — explicacao + revisao por IA
│   └── schemas/models.py             # Pydantic models (request/response)
│
├── src/
│   ├── parser.py                     # Parser SPED pipe-delimited (streaming)
│   ├── models.py                     # SpedRecord, ValidationError
│   ├── validator.py                  # Carregamento de field_defs do sped.db
│   ├── converter.py                  # PDF do Guia Pratico/legislacao → markdown
│   ├── indexer.py                    # Indexacao FTS5 + embeddings
│   ├── searcher.py                   # Busca hibrida (FTS5 + cosine) com RRF
│   ├── embeddings.py                 # Carregamento lazy do modelo
│   ├── rules.py                      # Schema YAML + DSL de condicoes
│   ├── validators/                   # 38 validadores (ver §3.4)
│   └── services/                     # Camada de servico (ver §3.3)
│
├── frontend/
│   ├── src/
│   │   ├── pages/                    # UploadPage, FilesPage, FileDetailPage,
│   │   │                             # XMLCrossPage, CrossValidationPage, RulesPage
│   │   ├── components/
│   │   │   ├── Layout.tsx
│   │   │   ├── Dashboard/            # ErrorChart, AuditScopePanel
│   │   │   ├── Records/              # RecordDetail, RecordEditModal, FieldEditor, SuggestionPanel
│   │   │   └── Corrections/          # CorrectionApprovalPanel
│   │   ├── api/client.ts             # fetch wrapper com X-API-Key
│   │   └── types/                    # Tipos compartilhados
│   ├── package.json
│   ├── vite.config.ts
│   └── tailwind.config.js
│
├── data/
│   ├── JSON/                         # Tabelas fiscais (CST, NCM, DIFAL, beneficios ES)
│   ├── reference/                    # YAML: aliquotas UF, FCP, MVA, IBGE, CSOSN, CST PIS/COFINS
│   │   ├── typescript-spec/          # specs compartilhadas (campos C100/C170/C190)
│   │   └── vigencias/                # janelas de vigencia por UF/regra
│   ├── tabelas/                      # Aliasing leve de tabelas YAML
│   └── config/field_map.yaml         # mapeamento declarativo SPED ↔ XML
│
├── db/
│   ├── audit.db                      # SQLite: arquivos, records, errors, xml, ai_cache
│   └── sped.db                       # SQLite: chunks, register_fields, embeddings
│
├── scripts/
│   ├── pg_schema.sql                 # schema PostgreSQL (24 tabelas)
│   ├── migrate_fields_json.py        # migracao JSON ↔ JSONB
│   └── check_hardcoded_indices.py    # CI — proibe acesso posicional (fields[3])
│
├── tests/                            # 86 arquivos pytest + conftest + fixtures
├── docs/                             # MIGRATION_PG.md, PRD_REGRAS.md
├── upgrade/motor_cruzamento_v_final.txt  # spec do Motor XC
├── prd/                              # PRD.md, PRD_v5.md, PRD_v6_motor_xc_cache.md
├── conferencia/                      # XMLs e SPEDs de teste
├── SPED/                             # arquivos SPED de exemplo
├── rules.yaml                        # 193 regras versionadas (vigencia + DSL)
├── cli.py                            # CLI (validate / report)
├── ingest.py                         # ingestao em batch
├── config.py                         # paths, env, EMBEDDING_MODEL, ENGINE_VERSION
├── pyproject.toml                    # build + ruff + mypy + coverage
├── requirements.txt                  # FastAPI, pydantic, pdfplumber, torch CPU, ST...
├── docker-compose.yml                # api + frontend
├── docker-compose.db.yml             # postgres 16 (sped_audit)
├── docker-compose.dev.yml            # variante dev
├── Dockerfile                        # multi-stage backend
├── Dockerfile.frontend               # Vite build
├── start.sh / start.bat              # bootstrap local (venv + npm + dev servers)
└── Makefile                          # lint, test, check-indices, ci
```

---

## 3. Camadas e Componentes

### 3.1 Camada de API (`api/`)

FastAPI com **autenticacao via `X-API-Key`** (header obrigatorio em todos os endpoints exceto `/api/health`).
CORS configuravel via `ALLOWED_ORIGINS` (lista por virgula). Exception handler global loga traceback completo e retorna `{"detail": str(exc)}` com status 500. Modelo de embeddings pre-carregado em thread daemon no `@app.on_event("startup")` para evitar latencia na primeira validacao.

### 3.2 Camada de Servico (`src/services/`)

Orquestra a logica de negocio entre routers e validadores.

| Modulo | Linhas | Responsabilidade |
|---|---|---|
| `pipeline.py` | 940 | Pipeline 4 estagios, eventos de progresso, snapshot atomico de erros |
| `context_builder.py` | 637 | Monta `ValidationContext` imutavel (regime, periodo, beneficios, etc.) |
| `cross_engine.py` | 1.534 | Motor XC — pipeline de 10 etapas, regras XC001–XC095 |
| `cross_engine_models.py` | 434 | Enums (`RuleOutcome`, `ItemMatchState`, `ItemNature`), dataclasses |
| `document_scope_builder.py` | 560 | Constroi `DocumentScope` por chave NFe (pareamento NF-e ↔ SPED) |
| `xml_service.py` | 1.553 | Parser XML NF-e, normalizacao, regras XML001–XML017 |
| `field_comparator.py` | 230 | Comparacao tolerante (numerico, string, data, CNPJ) |
| `reference_loader.py` | 1.117 | Cache de tabelas fiscais (JSON/YAML) com lazy loading |
| `validation_service.py` | 592 | Persistencia de erros, severidade, hash de erro (UNIQUE INDEX) |
| `error_messages.py` | 738 | Catalogo de mensagens amigaveis e guidance por error_type |
| `correction_service.py` | 418 | Aplicacao de correcoes, audit trail, undo |
| `auto_correction_service.py` | 214 | Filtra somente tipos deterministicos seguros |
| `export_service.py` | 659 | Geracao Markdown / JSON estruturado / CSV / SPED corrigido |
| `file_service.py` | 343 | Upload, hash SHA-256, vinculacao de retificadores |
| `database.py` | 602 | Schema SQLite + migrations idempotentes |
| `database_pg.py` | 389 | Adapter PostgreSQL (`?` → `%s`, JSONB, GIN, execute_values) |
| `client_service.py` | 185 | Consulta MySQL DCTF_WEB (regime + beneficios ativos) |
| `beneficio_engine.py` | 318 | Motor de beneficios (CST, aliquota, E111) |
| `risk_score.py` | 210 | Score de risco (materialidade) + cobertura (%) |
| `ai_service.py` | 337 | Explicacao IA por erro, cache por hash de contexto |
| `ai_review_service.py` | 854 | Triangulacao Claude (Sonnet 4.6) x GPT-4o — veredito por grupo |
| `rule_loader.py` | 166 | Carrega `rules.yaml`, filtra por vigencia, indexa por `error_type` |
| `rate_limiter.py` | 101 | Rate limit nas chamadas de IA |
| `sped_line_format.py` | 102 | Reconstroi linhas pipe-delimited a partir do dict |

### 3.3 Camada de Validacao (`src/validators/`) — 38 modulos

| Validador | Linhas | Cobertura |
|---|---|---|
| `beneficio_audit_validator.py` | 1.711 | 50+ regras de auditoria de beneficios fiscais |
| `field_map_validator.py` | 714 | Conferencia declarativa SPED x XML (C100/C170/C190) |
| `difal_validator.py` | 696 | DIFAL EC 87/2015 + LC 190/2022 + FCP |
| `cst_hypothesis.py` | 692 | Hipoteses inteligentes de CST |
| `fiscal_semantics.py` | 641 | Coerencia CST x aliquota, CST x CFOP, monofasicos |
| `cst_validator.py` | 634 | Validacao CST ICMS, isencoes, Bloco H |
| `beneficio_cross_validator.py` | 576 | Cruzamento beneficios x regras JSON |
| `apuracao_validator.py` | 525 | Apuracao ICMS — reconciliacao C190 x E110 x E111 x E116 |
| `aliquota_validator.py` | 474 | Aliquotas internas/interestaduais (4%, 7%, 12%, 17, 18, 20) |
| `tax_recalc.py` | 461 | Recalculo ICMS, ICMS-ST, IPI, PIS/COFINS por C170 |
| `audit_rules.py` | 467 | Auditoria fiscal avancada (CFOP x UF, remessas, inventario) |
| `c190_validator.py` | 438 | Consolidacao C190 vs C170 (CST+CFOP+ALIQ) |
| `intra_register_validator.py` | 453 | Coerencia intra-registro (C100, C170, C190, E110) |
| `simples_validator.py` | 379 | CSOSN, sublimites, anexos, credito SN |
| `bloco_d_validator.py` | 361 | CT-e e servicos de transporte |
| `ncm_validator.py` | 338 | NCM generico, tratamento tributario, monofasicos |
| `beneficio_validator.py` | 334 | Beneficios BENE_001/002/003 |
| `encadeamento_validator.py` | 316 | C100→C170, ST apuracao, IPI apuracao |
| `parametrizacao_validator.py` | 315 | Erros sistematicos por item / UF / data |
| `correction_hypothesis.py` | 309 | Hipotese ALIQ_ICMS ausente |
| `pendentes_validator.py` | 300 | Beneficio nao vinculado, anomalia historica |
| `base_calculo_validator.py` | 300 | BASE_001 a BASE_006 |
| `st_validator.py` | 288 | ICMS-ST: apuracao, CST 60, MVA por NCM/UF |
| `devolucao_validator.py` | 269 | DEV_001 a DEV_003 |
| `destinatario_validator.py` | 244 | IE, UF, CEP do 0150 vs documento |
| `bloco_c_servicos_validator.py` | 232 | C400/C490/C500/C590 |
| `pis_cofins_validator.py` | 222 | Direcao + consistencia CST x campos PIS/COFINS |
| `tolerance.py` | 202 | Politica de tolerancia (0.02 default) |
| `ipi_validator.py` | 185 | IPI: reflexo BC, CST monetario |
| `format_validator.py` | 225 | CNPJ/CPF/CFOP/NCM/CEP/Chave NFe/Codigo IBGE |
| `cross_block_validator.py` | 184 | Cruzamento entre blocos (C100×C170, E110×blocoC, contagem 9900) |
| `regime_detector.py` | 118 | Score de confianca do regime tributario |
| `error_deduplicator.py` | 107 | Deduplica erros por estrategias (1, 2, 3) |
| `field_registry.py` | 109 | Registro de campos validos por registro |
| `bloco_k_validator.py` | 104 | K200/K220/K230/K235 — estoque/producao |
| `cfop_validator.py` | 96 | CFOP interestadual x destino |
| `retificador_validator.py` | 93 | Vinculacao com SPED original |
| `helpers.py` | 538 | `REGISTER_FIELDS`, parsing de valores, fields_to_dict |

### 3.4 CLI

`cli.py` permite executar o pipeline sem subir a API:
- `python cli.py validate caminho/arquivo.txt`
- `python cli.py report <file_id> --format md`

### 3.5 Indexador de Documentacao

`indexer.py` converte PDFs do Guia Pratico EFD e legislacao em chunks markdown, gera embeddings com `all-MiniLM-L6-v2` e popula `sped.db` (FTS5 + matrix de embeddings). `searcher.py` faz busca hibrida (FTS5 + cosine + RRF, top_k=5).

---

## 4. Banco de Dados (SQLite/PostgreSQL)

O sistema suporta **dois backends** com schema equivalente. SQLite e o padrao local; PostgreSQL e usado em producao com JSONB e indices GIN.

### 4.1 Tabelas Principais (`db/audit.db` ou `sped_audit`)

| Tabela | Conteudo |
|---|---|
| `sped_files` | id, filename, hash_sha256, upload_date, period_start/end, company_name, cnpj, uf, total_records, total_errors, status, validation_stage, regime_tributario, cod_ver, original_file_id, is_retificador, **ind_regime**, **regime_confidence**, **regime_signals**, **regime_override**, xml_crossref_completed_at |
| `sped_records` | id, file_id, line_number, register, block, parent_id, **fields_json** (JSONB no PG), raw_line, status (`pending` / `corrected`). Indices em `(file_id, register)` e GIN em `fields_json` |
| `validation_errors` | id, file_id, record_id, line_number, register, field_no, field_name, value, expected_value, **error_type**, severity, message, friendly_message, doc_suggestion, legal_basis, auto_correctable, status (`open`/`resolved`/`rejected`), categoria, certeza, impacto, materialidade, created_at, **error_hash** (UNIQUE INDEX) |
| `cross_validations` | Resultados de cruzamentos antigos (legacy) |
| `corrections` | id, file_id, error_id, field_name, old_value, new_value, justificativa, correction_type (`auto`/`proposta`/`manual`), rule_id, applied_at, applied_by |
| `audit_log` | id, file_id, action, details (JSON), user, created_at |
| `clientes` | cnpj, razao_social, regime_tributario, uf, atualizado_em — espelho local do MySQL |
| `beneficios_ativos` | cliente_id, codigo_beneficio, vigencia_de, vigencia_ate |
| `emitentes_crt` | cnpj, crt, uf — coletado dos XMLs (CRT=1 Simples, 2 SN-excesso, 3 Normal) |

### 4.2 Cruzamento XML x SPED

| Tabela | Conteudo |
|---|---|
| `nfe_xmls` | id, file_id, chave, numero, serie, cnpj_emit, cnpj_dest, dh_emi, vNF, vICMS, vIPI, vPIS, vCOFINS, status (101/135 = cancelada) |
| `nfe_itens` | id, nfe_id, n_item, cProd, xProd, NCM, CFOP, CST, vBC, pICMS, vICMS, vIPI, vPIS, vCOFINS |
| `nfe_cruzamento` | id, file_id, nfe_id, chave, rule_id, severity, campo_xml, valor_xml, campo_sped, valor_sped, diferenca, suggestion (legado XML001–XML017) |
| `cross_validation_findings` | Resultados do Motor XC (xc_rule_id, scope_id, item_pair_id, outcome, confidence, friendly_message) |
| `xml_match_index` | Cache do pareamento `(file_id, chave) → state` para reuso |

### 4.3 Auditoria de Cobertura e Contexto

| Tabela | Conteudo |
|---|---|
| `validation_runs` | id, file_id, context_hash, started_at, ended_at, engine_version, total_rules_active |
| `fiscal_context_snapshots` | run_id, regime, periodo, uf, beneficios_ativos[], tabelas_disponiveis[] (JSON) |
| `coverage_gaps` | run_id, area, motivo (tabela ausente, dado insuficiente, regra desabilitada) |
| `suggested_action_types` | catalogo de acoes sugeridas por error_type |
| `field_equivalence_map` | mapeamento declarativo SPED ↔ XML (override do `field_map.yaml`) |
| `schema_version` | Versao do schema aplicado (idempotencia das migrations) |

### 4.4 IA e Resolucao

| Tabela | Conteudo |
|---|---|
| `ai_error_cache` | chave_hash, rule_id, error_type, regime, uf, beneficio_codigo, ind_oper, campo, valor_hash, exp_hash, prompt_version, modelo, explanation, hits, created_at, last_used_at |
| `finding_resolutions` | error_id, status (`accepted`/`rejected`/`deferred`/`noted`), justificativa, resolvido_por, resolvido_em |
| `sped_file_versions` | original_file_id, retificador_file_id, vinculo (CNPJ+periodo) |
| `embedding_metadata` | model_name, dimensions, last_indexed |

### 4.5 Indices Criticos

- `idx_sr_file_reg` em `sped_records(file_id, register)` — leitura por bloco
- `GIN(fields_json)` em PG — busca por campo nested
- `idx_ve_file`, `idx_ve_type`, `idx_ve_cat` — filtragem por severidade/categoria
- `UNIQUE INDEX` em `validation_errors(error_hash)` — previne erros duplicados

---

## 5. API REST — Endpoints

Todos os routers (exceto `/api/health` e `/api/audit-scope`) exigem header `X-API-Key`.

### 5.1 Arquivos (`/api/files`)
| Metodo | Path | Descricao |
|---|---|---|
| POST | `/upload` | Multipart, gera hash SHA-256, deduplicacao por hash, vincula retificadores |
| GET | `` | Lista arquivos com filtros (status, periodo, cnpj) |
| GET | `/{file_id}` | Detalhes do arquivo |
| DELETE | `/{file_id}` | Remove arquivo + records + erros |
| DELETE | `/audit` | Limpa toda auditoria (dev only) |
| DELETE | `/{file_id}/audit` | Reseta auditoria de um arquivo |

### 5.2 Registros (`/api/files/{file_id}/records`)
| Metodo | Path | Descricao |
|---|---|---|
| GET | `` | Lista paginada (filtros: register, block, status) |
| GET | `/{record_id}` | Detalhe + raw_line + fields_json |
| PUT | `/{record_id}` | Edita campos com audit_log |

### 5.3 Validacao (`/api/files/{file_id}`)
| Metodo | Path | Descricao |
|---|---|---|
| POST | `/validate` | Dispara pipeline (sincrono em background thread) |
| GET | `/validate/stream` | SSE: stage, stage_progress, detail, total_errors |
| GET | `/errors` | Lista erros (filtros: severity, error_type, register, status) |
| GET | `/summary` | Sumario por bloco/severidade/error_type |
| GET | `/audit-scope` | Cobertura + tabelas ausentes + checks executados |
| POST | `/findings/{id}/resolve` | accepted/rejected/deferred/noted |
| GET | `/findings/resolutions` | Historico de resolucoes |
| DELETE | `/errors/{id}` | Remove erro individual |
| DELETE | `/errors/group/{error_type}` | Remove grupo de erros |
| DELETE | `/errors` | Limpa todos os erros (re-run) |

### 5.4 Relatorio (`/api/files/{file_id}`)
| Metodo | Path | Descricao |
|---|---|---|
| GET | `/report?format=md|csv` | Relatorio analitico (6 secoes MOD-20) |
| GET | `/report/structured` | JSON estruturado (metadata, summary, findings, conclusion) |
| GET | `/download` | SPED corrigido (.txt com pipes) |

### 5.5 XML NF-e (`/api/files/{file_id}/xml`)
| Metodo | Path | Descricao |
|---|---|---|
| POST | `/upload` | Upload em chunks (multipart, modos: `validar` / `importar_todos` / `pular_fora`) |
| GET | `` | Lista XMLs do arquivo |
| POST | `/cruzar` | Roda regras legacy XML001–XML017 |
| GET | `/cruzar/stream` | SSE de progresso |
| GET | `/cruzamento` | Lista divergencias XML x SPED (legacy) |
| POST | `/cruzar-xc` | Roda Motor XC (XC001–XC095) |
| GET | `/cruzamento-xc` | Findings do Motor XC com agrupamento |
| DELETE | `/{xml_id}` | Remove XML |

### 5.6 Regras (`/api/rules`)
| Metodo | Path | Descricao |
|---|---|---|
| GET | `` | Lista regras vigentes para periodo (filtros: bloco, severidade) |
| POST | `/generate` | Gera nova regra via IA (engenharia assistida) |
| POST | `/implement` | Valida YAML + injeta no `rules.yaml` |

### 5.7 Clientes, IA, Busca
| Path | Funcao |
|---|---|
| `GET /api/clientes/cnpj/{cnpj}` | Consulta MySQL DCTF_WEB |
| `POST /api/ai/explain` | Explicacao por erro (com cache) |
| `POST /api/ai/review/{file_id}/{error_type}` | Tribunal Claude + GPT por grupo |
| `GET /api/ai/cache/stats` | Estatisticas do cache de IA |
| `DELETE /api/ai/cache` | Limpa cache |
| `GET /api/search` | Busca FTS5 + semantica em `sped.db` |
| `GET /api/health` | Healthcheck publico |

---

## 6. Frontend — SPA React

Single Page Application em **React 18 + TypeScript 5**, build com **Vite 5**, estilizada com **Tailwind 3** e graficos com **Recharts**.

### 6.1 Paginas

| Pagina | Rota | Funcao |
|---|---|---|
| `UploadPage` | `/upload` | Drag-and-drop do SPED, extracao automatica do 0000 (CNPJ/periodo/nome), busca de cliente, upload de XMLs em chunks (50/batch, max 10.000) |
| `FilesPage` | `/` | Lista arquivos com filtros, status visual (pendente/validando/auditado) |
| `FileDetailPage` | `/files/:id` | Sumario, dashboard (ErrorChart por severidade/bloco), AuditScopePanel, lista de erros agrupados |
| `XMLCrossPage` | `/files/:id/xml` | Upload de XMLs + dashboard de cruzamento legacy + Motor XC |
| `CrossValidationPage` | `/files/:id/cross` | Tabela de findings com expansao, hash do erro (clique copia) |
| `RulesPage` | `/rules` | Lista de 193 regras com filtros (bloco, severidade, vigencia) |

### 6.2 Componentes Reutilizaveis

- `Layout.tsx` — Header + Sidebar + main
- `Dashboard/ErrorChart.tsx` — barras Recharts por bloco/severidade
- `Dashboard/AuditScopePanel.tsx` — cobertura visual + limitacoes
- `Records/RecordDetail.tsx` — visualizacao linha SPED com campos nomeados
- `Records/RecordEditModal.tsx` — edicao com FieldEditor (validacao em vivo)
- `Records/FieldEditor.tsx` — input tipado (texto/numero/data) + tick verde "Atualizado"
- `Records/SuggestionPanel.tsx` — exibe `expected_value` e `doc_suggestion`
- `Corrections/CorrectionApprovalPanel.tsx` — modal de aprovacao com justificativa (min 10 chars para `proposta`)

### 6.3 Cliente HTTP (`src/api/client.ts`)

`fetch` wrapper que injeta automaticamente `X-API-Key` (lido do localStorage), trata 401/403, e mapeia erros de rede.

---

## 7. Entrada de Dados — Upload e Parsing

### 7.1 Recebimento

- **API REST:** `POST /api/files/upload` (multipart, limite `MAX_UPLOAD_MB`=50 padrao, streaming em chunks de 1 MB)
- **CLI:** `python cli.py validate arquivo.txt`

### 7.2 Deteccao de Encoding

Ordem (padrao PVA da Receita Federal):
1. `latin-1` (padrao da maioria dos SPED gerados pelo PVA)
2. `cp1252` (variantes Windows)
3. `utf-8` (arquivos recentes / sistemas modernos)

Se nenhum decodificar limpo: `latin-1` com `errors="replace"`.

### 7.3 Parsing Pipe-Delimited

Cada linha segue `|CAMPO1|CAMPO2|...|CAMPON|`. O parser:
1. Remove pipes inicial/final
2. Faz split nos pipes intermediarios
3. Identifica registro pelo primeiro campo (ex: `C100`)
4. Converte lista posicional para **dict nomeado** via `REGISTER_FIELDS` (em `src/validators/helpers.py`)
5. Streaming em batches de 1.000 registros para evitar carregar arquivo inteiro em memoria

### 7.4 Mapeamento Posicional → Nome de Campo

`REGISTER_FIELDS` define os nomes por posicao. Registros mapeados:

```
0000, 0001, 0005, 0100, 0150, 0200, 0400, 0990,
C001, C100, C170, C190, C400, C405, C490, C500, C510, C590, C990,
D001, D100, D190, D690, D990,
E001, E100, E110, E111, E116, E200, E210, E300, E500, E510, E520, E530, E990,
H001, H010, H990,
K001, K200, K210, K220, K230, K235, K990,
9001, 9900, 9990, 9999
```

**Politica:** acesso posicional `fields[3]` e **proibido** (validado pelo CI `scripts/check_hardcoded_indices.py`). Sempre usar `fields.get("COD_PART")`.

### 7.5 Persistencia

| Campo DB | Conteudo |
|---|---|
| `file_id` | FK para `sped_files` |
| `line_number` | Linha no `.txt` |
| `register` | `C100`, `C170`, ... |
| `block` | Primeiro char (`C`, `D`, `E`, `H`, `K`, `0`, `9`) |
| `fields_json` | dict nomeado (JSONB no PG, JSON-text no SQLite) |
| `raw_line` | Linha original preservada (para reconstrucao) |
| `parent_id` | FK para registro pai (C170 → C100, C190 → C100) |
| `status` | `pending` → `corrected` |

### 7.6 Hash SHA-256

Calculado durante upload, usado para:
- **Deduplicacao:** Mesmo hash = reuso de `file_id` (evita reprocessamento)
- **Integridade:** Hash exibido no relatorio para rastreabilidade

### 7.7 Deteccao de Retificadores

Se `0000.COD_FIN > 0` (retificador):
1. Busca arquivo original por `(CNPJ, DT_INI, DT_FIN)`
2. Insere em `sped_file_versions` com `original_file_id`
3. Marca `is_retificador = 1`
4. `retificador_validator` valida coerencia com original

---

## 8. ValidationContext — Arquitetura Context-First

Antes de qualquer validacao, o `context_builder.build_context()` monta um objeto **imutavel** com TODO o contexto fiscal do arquivo. Nenhum validador pode altera-lo. Isso garante reprodutibilidade e elimina condicoes de corrida.

### 8.1 Campos do `ValidationContext`

```python
@dataclass
class ValidationContext:
    # Identificacao
    file_id: int
    run_id: int
    mode: str  # "sped_only" | "sped_xml"

    # Regime (detectado por CSTs REAIS, nao por IND_PERFIL — BUG-001 fix)
    regime: TaxRegime  # NORMAL | SIMPLES_NACIONAL | MEI | UNKNOWN
    regime_source: str  # "CST" | "CST+MYSQL" | "CONFLITO" | "MYSQL"
    regime_confidence: float
    regime_signals: list[str]

    # Metadados do 0000
    uf_contribuinte: str
    periodo_ini: date
    periodo_fim: date
    ind_perfil: str  # armazenado MAS nao usado para regime
    ind_ativ: str
    cod_ver: str
    cnpj: str
    company_name: str

    # Cadastro do cliente (MySQL DCTF_WEB ou SQLite local)
    cliente: ClienteInfo
    beneficios_ativos: list[BeneficioProfile]

    # Caches
    participantes: dict  # cod_part → 0150 fields
    produtos: dict       # cod_item → 0200 fields
    naturezas: dict      # cod_nat → 0400 fields
    xml_items_by_chave: dict  # chave → list[item parseado]
    emitentes_sn: set    # CNPJs de emitentes Simples Nacional

    # Regras e tabelas
    active_rules: list[str]
    rule_index: RuleIndex  # filtrado por vigencia
    reference_loader: ReferenceLoader  # tabelas YAML/JSON
    tabelas_disponiveis: list[str]
    tabelas_ausentes: list[str]

    # Cruzamento XML
    has_xmls: bool
```

### 8.2 Deteccao de Regime (4 sinais)

| Sinal | Peso | Origem |
|---|---|---|
| CSTs reais no arquivo (Tabela A vs Tabela B/CSOSN) | ALTO | `_determine_regime_by_cst()` |
| MySQL DCTF_WEB (`regime_tributario`) | ALTO | `_resolve_regime_with_mysql()` |
| `IND_PERFIL` do 0000 | INFORMATIVO | armazenado mas NAO usado |
| Override manual (`regime_override`) | MAX | input do usuario |

Politicas:
- **Conflito** (CST diz NORMAL, MySQL diz SN): gera warning e adota CST como verdade
- **Confidence** calculada em `regime_detector.py` (proporcao de CSTs Tabela A vs B)
- **Override** validado contra valores aceitos; invalido → warning + fallback para deteccao

### 8.3 Snapshot do Contexto

Apos montagem, `save_context_snapshot()` grava em `fiscal_context_snapshots` (run_id, regime, periodo, beneficios, tabelas) — permitindo reproduzir a auditoria mesmo apos mudancas no banco.

### 8.4 Run ID

Cada execucao do pipeline gera novo `run_id` em `validation_runs` (started_at, ended_at, engine_version, total_rules_active). Erros, findings e coverage_gaps sao vinculados ao run_id.

---

## 9. Fontes de Dados e Tabelas de Referencia

### 9.1 Documentacao Indexada (`db/sped.db`)

| Tabela | Conteudo |
|---|---|
| `chunks` + `chunks_fts` | Trechos de Guia Pratico EFD + legislacao com FTS5 |
| `register_fields` | Definicoes oficiais de campos (registro, posicao, nome, tipo, tamanho, obrigatoriedade) |
| `embedding_metadata` | Modelo de embeddings + dimensoes |

Indexador: `src/indexer.py` — converte PDFs em markdown (pdfplumber), gera chunks de 500 tokens, embeddings com `all-MiniLM-L6-v2`.
Buscador: `src/searcher.py` — FTS5 + cosine, fusao via RRF (k=60), top_k=5.

### 9.2 Tabelas JSON (`data/JSON/`)

#### `Tabela_Fiscal_Complementar_v6.json` (~25 mil linhas)
CFOPs (descricao, tipo, uf_destino, natureza, gera_debito, permite_credito), aliquotas internas/interestaduais, FCP.

#### `Tabela_CST_Vigente.json` (~2 mil linhas)
Tabela A (origem) + Tabela B (tributacao). Cada CST tem `efeitos[]` (debito_proprio, tem_st_subsequente, reducao_base_calculo, isencao, sem_debito_proprio, nao_incidencia, icms_recolhido_anteriormente, etc).

#### `Tabela_DIFAL_Vigente.json`
Regras DIFAL por UF destino (aliquota interna, FCP obrigatorio, regime de partilha).

#### `Tabela_NCM_Vigente_20260407.json` (~136 mil linhas)
NCM, descricao, TIPI aliquota, tipo_tratamento (normal / monofasico / st), monofasico (bool).

#### Beneficios Fiscais (ES)
`FUNDAP`, `COMPETE_ATACADISTA`, `COMPETE_VAREJISTA_ECOMMERCE`, `COMPETE_IND_GRAFICAS`, `COMPETE_IND_PAPELAO_MAT_PLAST`, `INVEST_ES_IMPORTACAO`, `INVEST_ES_INDUSTRIA`, `SUBSTITUICAO_TRIBUTARIA_ES`.
Cada um contem: base legal, pre-requisitos, elegibilidade, impactos fiscais, restricoes, reversoes, CNAEs permitidos, matriz de compatibilidade.

### 9.3 Tabelas YAML (`data/reference/`)

| Arquivo | Conteudo |
|---|---|
| `aliquotas_internas_uf.yaml` | ICMS interna por UF (ES=17, SP=18, RJ=20, ...) |
| `fcp_por_uf.yaml` | FCP por UF (RJ=2%, MG=2%, ...) |
| `codigos_ajuste_uf.yaml` | Tabela 5.1.1 por UF (`ESxxxxxx`, `SPxxxxxx`, ...) |
| `ibge_municipios.yaml` | Codigos IBGE (7 digitos) |
| `mva_por_ncm_uf.yaml` | MVA por NCM + UF (ICMS-ST) |
| `ncm_tipi_categorias.yaml` | Categorias de tratamento |
| `csosn_tabela_b.yaml` | CSOSN do SN |
| `cst_pis_cofins_sn.yaml` | CSTs PIS/COFINS aplicaveis ao SN |
| `sn_anexos_aliquotas.yaml` | Aliquotas por faixa de receita |
| `sn_sublimites_uf.yaml` | Sublimites ICMS/ISS por UF |
| `mapeamento_cbenef_xml_sped.yaml` | cbenef XML ↔ codigo de ajuste E111 |
| `vigencias/` | Janelas de vigencia por UF/regra |
| `typescript-spec/` | Specs compartilhadas (C100/C170/C190) |

### 9.4 Field Map Declarativo (`data/config/field_map.yaml`)

Mapeamento campo-a-campo SPED ↔ XML usado por `field_map_validator.py`:

```yaml
C100:
  CHV_NFE: { xml: "infNFe/@Id[3:]", normalize: chave }
  VL_DOC:  { xml: "total/ICMSTot/vNF", compare: numeric_tolerance_0.02 }
  ...
```

Permite estender cruzamento sem mexer em Python.

### 9.5 MySQL DCTF_WEB

Consulta por CNPJ via `client_service.buscar_cliente()`:
- Razao social
- Regime tributario cadastrado
- Beneficios fiscais ativos (com vigencia)
- Situacao cadastral

Resultado e refletido em `clientes` + `beneficios_ativos` (cache local).

### 9.6 Tabelas Ausentes

`_detect_missing_tables()` lista tabelas nao carregadas; sao reportadas em `coverage_gaps` e no relatorio (reduzem percentual de cobertura).

---

## 10. Pipeline de Validacao — 4 Estagios

```
Upload → Parse → Build Context → run_pipeline()
                                       │
                       ┌───────────────┼───────────────┐
                       ▼               ▼               ▼
                  Estagio 1       Estagio 2       Estagio 3
                  Estrutural      Cruzamento      Enriquecimento
                       │               │ + 2.5 XC      │
                       └───────────────┼───────────────┘
                                       ▼
                              Dedup + Persist
                                       ▼
                          Risk Score + Coverage
                                       ▼
                              Status: audited
```

- **Tolerancia global:** 0.02 (2 centavos) — `rules.yaml:tolerance`
- **Snapshot atomico** (BUG-006 fix): erros acumulados em memoria e trocados ao final (evita janela de inconsistencia)
- **Progresso em tempo real:** eventos SSE a cada 0.5s — `{stage, stage_progress, detail, total_errors, errors_by_stage, risk_score, coverage_score}`
- **Filtragem por vigencia:** `RuleIndex` mantem apenas regras vigentes para `(periodo_ini, periodo_fim)`

---

## 11. Estagio 1 — Validacao Estrutural

### 11.1 Campo-a-Campo (via `sped.db.register_fields`)

| Verificacao | Error Type |
|---|---|
| Obrigatorio ausente (`O` no Guia) | `MISSING_REQUIRED` |
| Tipo numerico invalido | `WRONG_TYPE` |
| Tamanho excedido | `WRONG_SIZE` |
| Valor fora do dominio | `INVALID_VALUE` |
| Obrigatorio condicional | `MISSING_CONDITIONAL` |

Registros de abertura/encerramento (X001, X990, 9999) tem layout fixo — pulados.

### 11.2 Formatos Especificos (`format_validator.py`)

| Formato | Algoritmo | Error Type |
|---|---|---|
| CNPJ | 14 digitos + modulo 11 (2 DVs) + rejeicao de repetidos | `FORMATO_INVALIDO` |
| CPF | 11 digitos + modulo 11 (2 DVs) | `FORMATO_INVALIDO` |
| Data DDMMAAAA | 8 digitos + dia/mes/ano validos | `INVALID_DATE` |
| Data no periodo | Dentro de DT_INI..DT_FIN do 0000 | `DATE_OUT_OF_PERIOD` |
| Ordem de datas | DT_E_S ≥ DT_DOC | `DATE_ORDER` |
| CEP | 8 digitos ≠ 00000000 | `FORMATO_INVALIDO` |
| CFOP | 4 digitos, primeiro 1-7 | `FORMATO_INVALIDO` |
| NCM | 8 digitos numericos | `FORMATO_INVALIDO` |
| Chave NFe | 44 digitos + DV modulo 11 (pesos 2-9) | `FORMATO_INVALIDO` |
| Cod Municipio | 7 digitos + tabela IBGE | `FORMATO_INVALIDO` |

### 11.3 Intra-Registro (`intra_register_validator.py`)

#### C100 — Documento
| Regra | Condicao | Error Type |
|---|---|---|
| CFOP x IND_OPER | Entrada com CFOP 5/6/7 ou saida com 1/2/3 | `CFOP_MISMATCH` |
| Soma VL_DOC | VL_DOC ≠ VL_MERC − VL_DESC + VL_FRT + VL_SEG + VL_OUT_DA | `SOMA_DIVERGENTE` |
| ICMS coerente | BC>0 e ICMS=0 (ou vice-versa) | `C100_ICMS_INCONSISTENTE` |
| ICMS-ST coerente | BC_ST>0 e ICMS_ST=0 | `C100_ICMS_ST_INCONSISTENTE` |
| IPI coerente | Inconsistencia campos IPI | `C100_IPI_INCONSISTENTE` |
| Sem itens | C100 sem C170 vinculado | `C100_SEM_ITENS` |

#### C170 — Itens
| Regra | Condicao | Error Type |
|---|---|---|
| ICMS = BC × Aliq | `\|VL_ICMS − (BC × ALIQ/100)\| > tolerancia` | `CALCULO_DIVERGENTE` |
| IPI = BC × Aliq | idem | `CALCULO_DIVERGENTE` |
| PIS = BC × Aliq | idem | `CALCULO_DIVERGENTE` |
| COFINS = BC × Aliq | idem | `CALCULO_DIVERGENTE` |
| Valor item positivo | VL_ITEM ≤ 0 | `VALOR_NEGATIVO` |
| Item orfao | C170 sem C100 pai | `C170_ORFAO` |
| Ref 0200 | COD_ITEM existe em 0200 | `REF_INEXISTENTE` |
| Ref 0400 | COD_NAT existe em 0400 | `REF_INEXISTENTE` |

#### C190 — Consolidacao
| Regra | Condicao | Error Type |
|---|---|---|
| VL_ICMS = BC × Aliq | calculo divergente | `CALCULO_DIVERGENTE` |

#### E110 — Apuracao ICMS
| Regra | Condicao | Error Type |
|---|---|---|
| Saldo coerente | VL_SLD_APURADO ≠ Σ debitos − Σ creditos | `CALCULO_DIVERGENTE` |

---

## 12. Estagio 2 — Cruzamentos e Recalculo Tributario

Estagio executado pelos validadores listados em §3.3 (ordem do `pipeline.py`):

`cross_blocks → field_map_C100 → tax_recalc → field_map_C170 → field_map_C190 → cst_validator → fiscal_semantics → pis_cofins → audit_rules → parametrizacao → ncm → aliquotas → c190 → bloco_d → beneficio_audit → pendentes → base_calculo → difal → beneficio → beneficio_cross → beneficio_engine → devolucao → ipi → destinatario → cfop → st → st_mva → simples → apuracao → bloco_c_servicos → bloco_k → retificador → encadeamento → correction_hypothesis → cst_hypothesis`

### 12.1 Cruzamentos entre Blocos (`cross_block_validator`)

| Cruzamento | Origem | Destino | Error Type |
|---|---|---|---|
| Σ VL_ICMS itens vs C100 | C170 | C100 | `CRUZAMENTO_DIVERGENTE` |
| Σ VL_IPI itens vs C100 | C170 | C100 | `CRUZAMENTO_DIVERGENTE` |
| Σ VL_PIS/COFINS itens vs C100 | C170 | C100 | `CRUZAMENTO_DIVERGENTE` |
| Σ VL_ITEM vs VL_DOC | C170 | C100 | `SOMA_DIVERGENTE` |
| C190 por (CST,CFOP,ALIQ) vs Σ C170 | C170 | C190 | `C190_DIVERGE_C170` |
| Combinacao C190 sem C170 | — | C190 | `C190_COMBINACAO_INCOMPATIVEL` |
| Σ debitos saidas vs E110.VL_TOT_DEBITOS | C100/C170 | E110 | `CRUZAMENTO_DIVERGENTE` |
| Σ creditos entradas vs E110.VL_TOT_CREDITOS | C100/C170 | E110 | `CRUZAMENTO_DIVERGENTE` |
| QTD_LIN_C do C990 vs real | C990 | linhas | `CONTAGEM_DIVERGENTE` |
| QTD_REG_BLC do 9900 vs real | 9900 | registro | `CONTAGEM_DIVERGENTE` |
| Ref 0150 ↔ COD_PART | C100 | 0150 | `REF_INEXISTENTE` |

### 12.2 Recalculo Tributario (`tax_recalc.py`)

```
ICMS_esperado    = VL_BC_ICMS × (ALIQ_ICMS / 100)
ICMS_ST_esperado = VL_BC_ICMS_ST × (ALIQ_ST / 100) − VL_ICMS
IPI_esperado     = VL_BC_IPI × (ALIQ_IPI / 100)
PIS_esperado     = VL_BC_PIS × (ALIQ_PIS / 100)
COFINS_esperado  = VL_BC_COFINS × (ALIQ_COFINS / 100)
```

Diferenca > tolerancia → `CALCULO_DIVERGENTE` com `expected_value`. Diferenca == arredondamento → `CALCULO_ARREDONDAMENTO` (warning, auto-corrigivel com aprovacao).

### 12.3 Validacao CST (`cst_validator` + `fiscal_semantics`)

| Regra | Error Type | Certeza |
|---|---|---|
| CST nao em dominio 00-90/CSOSN | `CST_INVALIDO` | objetivo |
| CST 020 sem reducao BC | `CST_020_SEM_REDUCAO` | objetivo |
| CST 40/41 com BC>0 | `ISENCAO_INCONSISTENTE` | objetivo |
| CST 40/41 com ICMS>0 | `TRIBUTACAO_INCONSISTENTE` | objetivo |
| CST tributado com aliq=0 (forte) | `CST_ALIQ_ZERO_FORTE` | objetivo |
| CST tributado com aliq=0 (moderado) | `CST_ALIQ_ZERO_MODERADO` | provavel |
| CST tributado com aliq=0 (info) | `CST_ALIQ_ZERO_INFO` | indicio |
| CST × CFOP incompativel | `CST_CFOP_INCOMPATIVEL` | provavel |
| CST incompativel com regime | `CST_REGIME_INCOMPATIVEL` | objetivo |
| IPI CST × aliq=0 | `IPI_CST_ALIQ_ZERO` | objetivo |
| PIS/COFINS CST × aliq=0 | `PIS_CST_ALIQ_ZERO` / `COFINS_CST_ALIQ_ZERO` | objetivo |
| Monofasico aliq invalida | `MONOFASICO_ALIQ_INVALIDA` | objetivo |
| Monofasico valor indevido | `MONOFASICO_VALOR_INDEVIDO` | objetivo |
| Monofasico NCM incompativel | `MONOFASICO_NCM_INCOMPATIVEL` | provavel |
| Monofasico CST incorreto | `MONOFASICO_CST_INCORRETO` | objetivo |
| Monofasico entrada CST 04 | `MONOFASICO_ENTRADA_CST04` | objetivo |

### 12.4 Validacao de Aliquotas (`aliquota_validator`)

| Regra | Error Type |
|---|---|
| Aliquota interestadual invalida (≠ 4, 7, 12) | `ALIQ_INTERESTADUAL_INVALIDA` |
| Aliquota interna em CFOP 6xxx | `ALIQ_INTERNA_EM_INTERESTADUAL` |
| Aliquota interestadual em CFOP 5xxx | `ALIQ_INTERESTADUAL_EM_INTERNA` |
| Aliquota nao corresponde a UF | `ALIQ_MEDIA_INDEVIDA` |
| Aliquota incompativel com beneficio | `SPED_ALIQ_BENEFICIO` |

### 12.5 DIFAL (`difal_validator`) — EC 87/2015 + LC 190/2022

| Regra | Error Type |
|---|---|
| CFOP 6xxx para consumidor final sem E300 | `DIFAL_FALTANTE_CONSUMO_FINAL` |
| DIFAL gerado em revenda | `DIFAL_INDEVIDO_REVENDA` |
| Aliquota interna do destino incorreta | `DIFAL_ALIQ_INTERNA_INCORRETA` |
| FCP ausente em UF com FCP | `DIFAL_FCP_AUSENTE` |
| Base DIFAL inconsistente | `DIFAL_BASE_INCONSISTENTE` |
| Consumo final sem marcador | `DIFAL_CONSUMO_FINAL_SEM_MARCADOR` |
| UF destino inconsistente | `DIFAL_UF_DESTINO_INCONSISTENTE` |
| Perfil incompativel | `DIFAL_PERFIL_INCOMPATIVEL` |

### 12.6 Auditoria de Beneficios (`beneficio_audit_validator` — 50+ regras)

| Categoria | Exemplos |
|---|---|
| Debito integral | Debito nao-integral com beneficio ativo |
| Ajustes E111 | Ajuste sem lastro, soma divergente — `AJUSTE_SEM_LASTRO_DOCUMENTAL`, `AJUSTE_SOMA_DIVERGENTE` |
| Devolucoes | Beneficio nao revertido — `DEVOLUCAO_BENEFICIO_NAO_REVERTIDO` |
| Saldo credor | Recorrente com beneficio |
| Sobreposicao | Multiplos beneficios incompativeis |
| Proporcionalidade | Desproporcao receita x beneficio |
| Segregacao | Sem segregacao por destinatario |
| Trilha | `TRILHA_BENEFICIO_AUSENTE` |
| Governanca | Sem procedimento documentado |
| CST/aliquota beneficio | `SPED_CST_BENEFICIO`, `SPED_ALIQ_BENEFICIO` |
| Carga reduzida | `BENEFICIO_CARGA_REDUZIDA_DOCUMENTO` |
| Sem ajuste E111 | `BENEFICIO_SEM_AJUSTE_E111` |

### 12.7 Auditoria Fiscal Avancada (`audit_rules`, `parametrizacao_validator`, `pendentes_validator`)

| Regra | Error Type |
|---|---|
| CFOP interestadual com destino interno | `CFOP_INTERESTADUAL_DESTINO_INTERNO` |
| Diferimento com debito | `DIFERIMENTO_COM_DEBITO` |
| IPI sem reflexo na BC ICMS | `IPI_REFLEXO_INCORRETO` / `IPI_REFLEXO_BC_AUSENTE` |
| Volume isento atipico | `VOLUME_ISENTO_ATIPICO` |
| Remessa sem retorno | `REMESSA_SEM_RETORNO` |
| Inventario item parado | `INVENTARIO_ITEM_PARADO` |
| Credito uso/consumo indevido | `CREDITO_USO_CONSUMO_INDEVIDO` |
| Parametrizacao sistemica | `PARAMETRIZACAO_SISTEMICA_INCORRETA` |
| Anomalia historica | `ANOMALIA_HISTORICA` |
| Beneficio nao vinculado | `BENEFICIO_NAO_VINCULADO` |
| Registros essenciais ausentes | `REGISTROS_ESSENCIAIS_AUSENTES` |

### 12.8 ICMS-ST (`st_validator`)

| Regra | Error Type |
|---|---|
| Aliquota ST incorreta | `ST_ALIQ_INCORRETA` |
| Apuracao ST divergente (E210) | `ST_APURACAO_DIVERGENTE` |
| MVA ausente | `ST_MVA_AUSENTE` |
| MVA divergente | `ST_MVA_DIVERGENTE` |
| MVA nao mapeado | `ST_MVA_NAO_MAPEADO` |

### 12.9 Hipoteses Inteligentes

- `correction_hypothesis.validate_with_hypotheses` — quando `ALIQ_ICMS` esta vazia/zero em item tributado: busca aliquota interna da UF do contribuinte, verifica interestadual pela UF do participante, propoe `expected_value`. Error: `ALIQ_ICMS_AUSENTE` (certeza `provavel`, auto-corrigivel com aprovacao).
- `cst_hypothesis.validate_cst_hypotheses` — analisa CFOP, aliquota, valores. Propoe CST alternativo. Error: `CST_HIPOTESE`.

---

## 13. Estagio 2.5 — Motor de Cruzamento XC (XML x SPED)

Disparado quando `context.mode == "sped_xml"` e ha XMLs uploadeados. Implementacao em `cross_engine.py` segue `upgrade/motor_cruzamento_v_final.txt`.

### 13.1 Pipeline de 10 Etapas

1. **Carregamento** — XMLs (`nfe_xmls`) e SPED (`sped_records`) do `file_id`
2. **DocumentScope** — agrupa por chave NFe (`document_scope_builder`)
3. **Pareamento de itens** — XML.det vs SPED.C170 com 5 estados (`ItemMatchState`)
4. **Classificacao por natureza** — `ItemNature` (revenda/uso_consumo/ativo/servico/bonificacao/outro)
5. **Verificacao de elegibilidade** — modelos eligibles `{55, 65}` (`XML_ELIGIBLE_MODELS`)
6. **Neutralizacao por beneficio** — finding marcada `NEUTRALIZED_BY_BENEFIT` se beneficio ativo justifica divergencia
7. **Supressao por causa raiz** — `SUPPRESSED_BY_ROOT_CAUSE`
8. **Execucao de regras XC001-XC095** com `RuleOutcome` (EXECUTED_ERROR / EXECUTED_OK / NOT_APPLICABLE / NOT_EXECUTED_MISSING_DATA / AMBIGUOUS_MATCH / SUPPRESSED_BY_ROOT_CAUSE / NEUTRALIZED_BY_BENEFIT)
9. **Persistencia** — batch insert em `cross_validation_findings` + tabela legacy `nfe_cruzamento`
10. **Sumario** — `xc_engine.get_summary()` com total_findings, total_errors, total_scopes

### 13.2 Categorias XC

| Faixa | Tema |
|---|---|
| XC001-XC008 | Presenca/ausencia de NF-e, cancelamento, denegacao |
| XC012-XC032 | Divergencias de cabecalho (vNF, vICMS, vIPI, CFOP, CST, data) |
| XC051-XC074 | Item-a-item (NCM, CFOP, CST, aliquota, valor) |
| XC080-XC095 | Coerencia com C190 e E110 |

### 13.3 Estados de Pareamento

| Estado | Significado |
|---|---|
| `MATCH_EXATO` | Mesmo cProd + qCom + vUnCom |
| `MATCH_PROVAVEL` | NCM + CFOP + valor (tolerancia 0.02) |
| `MATCH_HEURISTICO` | Descricao similar (fuzzy) |
| `AMBIGUO` | Multiplas candidaturas — gera `AMBIGUOUS_MATCH` |
| `SEM_MATCH` | Item em XML sem par em SPED (ou vice-versa) |

### 13.4 Grupos sem BC ICMS

`GRUPOS_SEM_BC_ICMS = {ICMS40, ICMS41, ICMS50, ICMSST, ICMSSN102, ICMSSN103, ICMSSN300, ICMSSN400}` — regras de comparacao adaptadas.

### 13.5 Grupos PIS/COFINS

`PIS_GRUPO_MAP` e `COFINS_GRUPO_MAP` definem modalidade (ad valorem / por quantidade / nao tributado / outros) com campos correspondentes (`vBC`, `pPIS`, `vPIS`).

### 13.6 Regras Legacy XML001-XML017

Ainda mantidas em `xml_service.cruzar_xml_vs_sped()` para compatibilidade. **XML012** respeita Excecao 2 do Guia Pratico EFD v3.2.2 (CNPJ emit/dest pode divergir em retorno de remessa).

---

## 14. Estagio 3 — Enriquecimento

### 14.1 Agrupamento por Chave

Erros agrupados por `(error_type, register, field_name)` para evitar buscas redundantes: 500 erros iguais ⇒ 1 busca de base legal.

### 14.2 Mensagens Amigaveis (`error_messages.py`)

89 tipos catalogados. Cada `error_type` tem:
- `friendly` — texto em portugues para o contador
- `guidance` — orientacao breve (1-2 frases)
- `icon` — Lucide icon name para o frontend

Exemplo:
```
CALCULO_DIVERGENTE:
  friendly: "O valor de ICMS (campo VL_ICMS) na linha 1234 esta com R$ 180,00,
             mas o calculo BC × Aliquota resulta em R$ 175,50. Diferenca de R$ 4,50."
  guidance: "Verifique BC e aliquota. Se houver reducao, confira CST=020."
```

### 14.3 Base Legal

Pesquisa em `sped.db.chunks_fts` + embeddings:
1. Busca exata por registro + campo (FTS5)
2. Busca semantica com a mensagem como query (cosine)
3. Fusao via RRF (k=60), top_k=1

Retorna `{fonte, artigo, trecho, score}`.

### 14.4 Doc Suggestion

Para erros com `expected_value`, gera `doc_suggestion` (linha SPED reconstruida com o campo corrigido) — usada pelo frontend no `SuggestionPanel`.

### 14.5 Classificacao de Auto-Corrigibilidade

Conforme `corrigivel` definido em `rules.yaml`:

| Nivel | Acao do sistema |
|---|---|
| `automatico` | Aplica sem confirmacao (somente `CALCULO_DIVERGENTE`, `SOMA_DIVERGENTE`, `CONTAGEM_DIVERGENTE`) |
| `proposta` | Sugere correcao; aplicacao requer justificativa ≥ 10 chars |
| `investigar` | Bloqueado para auto-correcao; exige analise externa |
| `impossivel` | Bloqueado totalmente (dado externo necessario) |

---

## 15. Deduplicacao Inteligente de Erros

`error_deduplicator.py` aplica 3 estrategias apos Estagio 2:

| Estrategia | Logica |
|---|---|
| **1. Hipoteses supersede genericos** | Se `ALIQ_ICMS_AUSENTE` existe na linha, suprime `CST_ALIQ_ZERO_FORTE` genericos (hipotese tem expected_value, mais acionavel) |
| **2. Causa raiz** | Se `CST_ALIQ_ZERO_MODERADO` existe, suprime `BENEFICIO_NAO_VINCULADO` e `CST_CFOP_INCOMPATIVEL` (sintomas da mesma causa) |
| **3. Mesmo (linha, campo), preferir acionavel** | Mantem o que tem `expected_value` |

Alem disso, `UNIQUE INDEX` em `error_hash` previne duplicatas exatas a nivel de banco (hash de `(file_id, error_type, register, line_number, field_no, value, expected_value)`).

---

## 16. Governanca de Correcoes

### 16.1 Campos Bloqueados para Auto-Correcao

Configurados em `auto_correction_service`:
- **Identificadores fiscais**: CNPJ, CPF, IE, CHV_NFE, CHV_CTE
- **Chaves de documento**: NUM_DOC, SER, COD_MOD
- **Valores monetarios**: VL_DOC, VL_ICMS, VL_BC_ICMS, VL_ICMS_ST, VL_IPI, VL_PIS, VL_COFINS
- **Classificacoes fiscais**: CST_ICMS, CSOSN, CST_PIS, CST_COFINS, CFOP
- **Datas de documento**: DT_DOC

### 16.2 Audit Trail

```json
{
  "field_name": "VL_ICMS",
  "old_value": "180.00",
  "new_value": "175.50",
  "justificativa": "Recalculo BC x Aliquota",
  "correction_type": "auto",
  "rule_id": "CALC_ICMS_C170",
  "record_id": 12345,
  "field_no": 15,
  "applied_at": "2026-05-14T12:34:56",
  "applied_by": "system"
}
```

Toda correcao tambem registra em `audit_log` (action: `correction.apply`).

### 16.3 Undo

`correction_service.undo_correction(correction_id)` restaura o valor original, reabre o erro e adiciona linha em `audit_log` (action: `correction.undo`).

### 16.4 Resolucao de Apontamentos (`finding_resolutions`)

| Status | Justificativa minima |
|---|---|
| `accepted` | Nao requer (correcao sera aplicada) |
| `rejected` | 20 chars |
| `deferred` | Nao requer |
| `noted` | Nao requer |

---

## 17. Revisao por IA — Tribunal Claude x GPT

`ai_review_service.py` implementa um "tribunal" para validar grupos de erros (analisar se sao verdadeiros positivos ou falsos positivos).

### 17.1 Pipeline

1. **Coleta de amostras** — ate 5 erros do mesmo `error_type` no `file_id`
2. **Montagem do dossie** — para cada amostra, busca dados reais (C100, C170, C190, E210) + XML correspondente (se houver)
3. **Triangulacao**:
   - Se ambas chaves disponiveis (`ANTHROPIC_API_KEY` + `OPENAI_API_KEY`): roda **Claude Sonnet 4.6** (`claude-sonnet-4-6`) e **GPT-4o** em paralelo; resultado vence por concordancia ou peso por confianca
   - Apenas Claude → roda Claude
   - Apenas OpenAI → roda GPT-4o
4. **Refino** — se inconclusivo, faz 2a rodada com dados adicionais
5. **Veredito** — `valido` | `falso_positivo` | `inconclusivo`
6. **Cache** — resultado armazenado em `ai_error_cache` por `(file_id, error_type)`

### 17.2 System Prompt (resumo)

> "Voce e um auditor fiscal senior especializado em SPED EFD ICMS/IPI. Analise se um apontamento e CORRETO ou FALSO POSITIVO com base nos dados reais do SPED e XML."

Regras instruidas:
- `COD_SIT=02/03` (cancelada): campos monetarios devem ser vazios
- `COD_SIT=06` (NF complementar): valores podem divergir legitimamente
- Entrada com ST (CFOP 2403): VL_ICMS pode ser zero
- `C190.VL_OPR` inclui frete, seguro, IPI, ICMS-ST — pode ser > soma `C170.VL_ITEM`

### 17.3 Structured Outputs

Migrado para **Anthropic Structured Outputs** (Sonnet 4.6) — schema JSON valida resposta no servidor. Schema:
```json
{
  "veredito": "valido" | "falso_positivo" | "inconclusivo",
  "confianca": 0.0..1.0,
  "racional": "string",
  "evidencias": ["string"]
}
```

### 17.4 Explicacao por Erro (`ai_service.py`)

Endpoint `/api/ai/explain` — explicacao contextualizada para um erro individual. Cache por hash de `(rule_id, error_type, regime, uf, beneficio, ind_oper, campo, valor_hash, expected_hash)` com `PROMPT_VERSION` para invalidar quando o prompt muda. Hit incrementa contador, `last_used_at` atualizado.

---

## 18. Score de Risco e Cobertura

### 18.1 Risk Score (`risk_score.calculate_risk_score`)

Pondera erros por severidade e impacto financeiro (materialidade):
- `critical` × peso 10
- `error` × peso 5
- `warning` × peso 2
- `info` × peso 0.5

Para erros com `materialidade` preenchida (valor financeiro envolvido), aplica boost proporcional. Score em escala 0–100.

### 18.2 Coverage Score (`risk_score.calculate_coverage_score`)

Percentual = `regras_executadas / regras_aplicaveis` * `(1 - penalidade_tabelas_ausentes)`. Conformidade calculada por registros unicos (nao por erros, evita inflacao).

### 18.3 Persistencia

`persist_scores()` atualiza `sped_files.risk_score` e `sped_files.coverage_score`. Exibidos no frontend (`FileDetailPage`).

---

## 19. Saida Analitica — Relatorio Final

### 19.1 Estrutura MOD-20 (6 secoes obrigatorias)

| Secao | Conteudo |
|---|---|
| **1. Identificacao** | Contribuinte (0000.NOME), CNPJ, periodo, hash SHA-256, data/hora, ENGINE_VERSION |
| **2. Cobertura** | 15 checks executados, tabelas disponiveis/ausentes, % cobertura, limitacoes |
| **3. Sumario** | Por severidade, certeza, bloco, top-10 tipos por frequencia |
| **4. Achados Detalhados** | Linha, registro, campo, valor encontrado/esperado, certeza, impacto, severidade, mensagem amigavel, base legal, orientacao — ordenado por severidade + linha |
| **5. Correcoes Aplicadas** | Historico (`corrections` + `audit_log`) |
| **6. Rodape Legal** | Aviso de nao-vinculacao + responsabilidade do contribuinte |

### 19.2 Formatos de Exportacao

| Formato | Endpoint | Implementacao |
|---|---|---|
| Markdown | `GET /files/{id}/report?format=md` | `export_service.generate_markdown_report` |
| JSON | `GET /files/{id}/report/structured` | `metadata`, `summary`, `findings[]`, `corrections[]`, `conclusion` |
| CSV | `GET /files/{id}/report?format=csv` | Tabela de erros + rodape legal |
| SPED corrigido | `GET /files/{id}/download` | Reconstroi `.txt` com correcoes via `sped_line_format` |

### 19.3 Rodape Legal

```
AVISO LEGAL: Este relatorio foi gerado automaticamente pelo sistema
SPED EFD Validator e nao constitui parecer contabil, fiscal ou
juridico. A conferencia, validacao e retificacao do arquivo SPED
junto a Secretaria da Fazenda e responsabilidade exclusiva do
contribuinte e de seu representante tecnico legalmente habilitado
(CRC/CRA/OAB).
```

---

## 20. Mapeamento Completo de Registros SPED

### Bloco 0 — Abertura e Identificacao

| Registro | Campos Principais | Uso na Validacao |
|---|---|---|
| **0000** | COD_VER, COD_FIN, DT_INI, DT_FIN, NOME, CNPJ, UF, IE, IND_PERFIL, IND_ATIV | Contexto: regime, periodo, UF, retificador |
| **0005** | NOME_FANTASIA, CEP, END, FONE, EMAIL | Validacao CEP |
| **0100** | NOME (contador), CPF, CRC | Validacao CPF |
| **0150** | COD_PART, NOME, CNPJ, CPF, IE, COD_MUN, UF | Cache de participantes |
| **0200** | COD_ITEM, DESCR_ITEM, COD_NCM, ALIQ_ICMS, TIPO_ITEM | Cache de produtos |
| **0400** | COD_NAT, DESCR_NAT | Cache de naturezas |

### Bloco C — Mercadorias

| Registro | Campos Principais | Uso |
|---|---|---|
| **C100** | IND_OPER, COD_PART, CHV_NFE, DT_DOC, DT_E_S, VL_DOC, VL_ICMS, VL_IPI, VL_PIS, VL_COFINS, COD_SIT | Cruzamento C170, C190, XML, E110 |
| **C170** | COD_ITEM, CST_ICMS, CFOP, VL_BC_ICMS, ALIQ_ICMS, VL_ICMS, VL_IPI, VL_PIS, VL_COFINS | Todos os recalculos, semantica |
| **C190** | CST_ICMS, CFOP, ALIQ_ICMS, VL_OPR, VL_BC_ICMS, VL_ICMS | Consolidacao vs C170 |
| **C400/C405/C490** | ECF / Reducao Z / Itens ECF | `bloco_c_servicos_validator` |
| **C500/C510/C590** | Energia/comunicacao | `bloco_c_servicos_validator` |

### Bloco D — Servicos

| Registro | Campos Principais | Uso |
|---|---|---|
| **D100** | IND_OPER, COD_PART, CHV_CTE, VL_DOC, VL_ICMS | `bloco_d_validator` |
| **D190** | CST_ICMS, CFOP, VL_OPR, VL_ICMS | Consolidacao Bloco D |

### Bloco E — Apuracao

| Registro | Campos Principais | Uso |
|---|---|---|
| **E110** | VL_TOT_DEBITOS, VL_TOT_CREDITOS, VL_SLD_APURADO, VL_ICMS_RECOLHER | Cruzamento Bloco C |
| **E111** | COD_AJ_APUR, VL_AJ_APUR | Beneficios, ajustes |
| **E116** | COD_OR, VL_OR | Recolhimentos |
| **E200/E210** | Apuracao ICMS-ST | `st_validator` |
| **E300** | DIFAL EC 87/2015 | `difal_validator` |
| **E500/E510/E520/E530** | Apuracao IPI | `ipi_validator` + `apuracao_validator` |

### Bloco H — Inventario

| Registro | Campos | Uso |
|---|---|---|
| **H010** | COD_ITEM, QTD, VL_ITEM | `audit_rules.INVENTARIO_ITEM_PARADO` |

### Bloco K — Producao/Estoque

| Registro | Campos | Uso |
|---|---|---|
| **K200** | COD_ITEM, QTD, IND_EST | Saldo de estoque |
| **K220** | COD_ITEM_ORI, COD_ITEM_DEST, QTD | Movimentacao |
| **K230/K235** | COD_ITEM, QTD_DEST | Producao |

### Bloco 9 — Controle

| Registro | Campos | Uso |
|---|---|---|
| **9900** | REG_BLC, QTD_REG_BLC | `cross_block_validator` (contagem) |
| **9999** | QTD_LIN | Total de linhas |

---

## 21. Catalogo de Tipos de Erro

> 89 tipos definidos em `error_messages.py`. Todos versionados em `rules.yaml` com `severity`, `certeza`, `corrigivel`, `vigencia_de/ate`.

### Estruturais
| Error Type | Severidade | Auto-corrigivel |
|---|---|---|
| `FORMATO_INVALIDO` | error | Nao |
| `INVALID_DATE` / `DATE_ORDER` / `DATE_OUT_OF_PERIOD` | error | Nao |
| `MISSING_REQUIRED` / `MISSING_CONDITIONAL` | error | Nao |
| `WRONG_TYPE` / `WRONG_SIZE` / `INVALID_VALUE` | error | Nao |
| `REGISTROS_ESSENCIAIS_AUSENTES` | error | Nao |

### Calculo
| Error Type | Severidade | Auto-corrigivel |
|---|---|---|
| `CALCULO_DIVERGENTE` | error | Sim |
| `SOMA_DIVERGENTE` | error | Sim |
| `CONTAGEM_DIVERGENTE` | error | Sim |
| `CALCULO_ARREDONDAMENTO` | warning | Sim (aprovacao) |
| `VALOR_NEGATIVO` | error | Nao |

### Cruzamento
| Error Type | Severidade |
|---|---|
| `REF_INEXISTENTE` | error |
| `CRUZAMENTO_DIVERGENTE` | error |
| `C190_DIVERGE_C170` | error |
| `C190_COMBINACAO_INCOMPATIVEL` | warning |
| `C170_ORFAO` / `C100_SEM_ITENS` | error |
| `XML_C190_DIVERGE` | error |
| `DIVERGENCIA_DOCUMENTO_ESCRITURACAO` | warning |
| `INCONSISTENCY` | warning |

### CST
`CST_INVALIDO`, `CST_020_SEM_REDUCAO`, `ISENCAO_INCONSISTENTE`, `TRIBUTACAO_INCONSISTENTE`, `CST_ALIQ_ZERO_FORTE/MODERADO/INFO`, `CST_CFOP_INCOMPATIVEL`, `CST_HIPOTESE`, `CST_REGIME_INCOMPATIVEL`.

### Aliquota
`ALIQ_INTERESTADUAL_INVALIDA`, `ALIQ_INTERNA_EM_INTERESTADUAL`, `ALIQ_INTERESTADUAL_EM_INTERNA`, `ALIQ_MEDIA_INDEVIDA`, `ALIQ_ICMS_AUSENTE`.

### DIFAL
`DIFAL_FALTANTE_CONSUMO_FINAL`, `DIFAL_INDEVIDO_REVENDA`, `DIFAL_ALIQ_INTERNA_INCORRETA`, `DIFAL_FCP_AUSENTE`, `DIFAL_BASE_INCONSISTENTE`, `DIFAL_CONSUMO_FINAL_SEM_MARCADOR`, `DIFAL_UF_DESTINO_INCONSISTENTE`, `DIFAL_PERFIL_INCOMPATIVEL`.

### IPI / PIS / COFINS
`IPI_CST_ALIQ_ZERO`, `IPI_CST_INCOMPATIVEL`, `IPI_CST_MONETARIO_ZERADO`, `IPI_REFLEXO_INCORRETO`, `IPI_REFLEXO_BC_AUSENTE`, `PIS_CST_ALIQ_ZERO`, `COFINS_CST_ALIQ_ZERO`.

### Beneficios
`BENEFICIO_DEBITO_NAO_INTEGRAL`, `AJUSTE_SEM_LASTRO_DOCUMENTAL`, `AJUSTE_SOMA_DIVERGENTE`, `DEVOLUCAO_BENEFICIO_NAO_REVERTIDO`, `SOBREPOSICAO_BENEFICIOS`, `BENEFICIO_NAO_VINCULADO`, `BENEFICIO_CARGA_REDUZIDA_DOCUMENTO`, `BENEFICIO_SEM_AJUSTE_E111`, `SPED_CST_BENEFICIO`, `SPED_ALIQ_BENEFICIO`, `TRILHA_BENEFICIO_AUSENTE`.

### Auditoria Avancada
`CFOP_INTERESTADUAL_DESTINO_INTERNO`, `CFOP_MISMATCH`, `DIFERIMENTO_COM_DEBITO`, `REMESSA_SEM_RETORNO`, `INVENTARIO_ITEM_PARADO`, `CREDITO_USO_CONSUMO_INDEVIDO`, `VOLUME_ISENTO_ATIPICO`, `PARAMETRIZACAO_SISTEMICA_INCORRETA`, `ANOMALIA_HISTORICA`, `CLASSIFICACAO_TIPO_ERRO`, `ACHADO_LIMITADO_AO_SPED`.

### Monofasico
`MONOFASICO_ALIQ_INVALIDA`, `MONOFASICO_VALOR_INDEVIDO`, `MONOFASICO_NCM_INCOMPATIVEL`, `MONOFASICO_CST_INCORRETO`, `MONOFASICO_ENTRADA_CST04`.

### ICMS-ST
`ST_ALIQ_INCORRETA`, `ST_APURACAO_DIVERGENTE`, `ST_MVA_AUSENTE`, `ST_MVA_DIVERGENTE`, `ST_MVA_NAO_MAPEADO`.

### XML/NFe
`NF_CANCELADA_ESCRITURADA`, `NF_DENEGADA_ESCRITURADA`, `COD_SIT_DIVERGENTE_XML`, `XML_C190_DIVERGE`.

### Intra-C100
`C100_ICMS_INCONSISTENTE`, `C100_ICMS_ST_INCONSISTENTE`, `C100_IPI_INCONSISTENTE`, `C100_SEM_ITENS`.

---

## 22. Configuracao, Deploy e Execucao

### 22.1 Variaveis de Ambiente (`.env`)

```
# Autenticacao
API_KEY=chave-secreta-min-32-chars

# Banco
DATABASE_URL=db/sped.db                # SQLite local (default)
# OU
DATABASE_URL=postgresql://sped:sped2026@localhost:5434/sped_audit  # PG producao

# CORS
ALLOWED_ORIGINS=http://localhost:5175,http://localhost:5173

# Limites
MAX_UPLOAD_MB=50

# Embeddings
EMBEDDING_MODEL=all-MiniLM-L6-v2

# IA (opcional)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...

# MySQL DCTF_WEB (consulta de clientes)
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=...
MYSQL_DATABASE=DCTF_WEB
```

### 22.2 Bootstrap Local

**Linux / WSL:**
```bash
./start.sh           # cria venv, instala deps, sobe API+Vite em paralelo
```

**Windows:**
```cmd
start.bat            # equivalente
```

### 22.3 Docker

```bash
# API + frontend
docker compose up -d --build

# PostgreSQL standalone (dev/producao)
docker compose -f docker-compose.db.yml up -d
# → porta 5434, user sped, db sped_audit, schema aplicado via /docker-entrypoint-initdb.d/01_schema.sql
```

Dockerfile e multi-stage: `backend` (Python 3.12-slim + FastAPI) → `frontend-build` (Node 18) → final (junta artefatos).

### 22.4 Postgres Local (Bruno)

Container `aap-db` na porta `25434`, banco `sped_audit` (ver memoria `reference_postgres.md`).

### 22.5 CI (`Makefile`)

```bash
make lint            # ruff + mypy (nao bloqueante hoje)
make check-indices   # bloqueia fields[3] hardcoded
make test            # pytest -q
make ci              # lint + check-indices + test
```

---

## 23. Testes e Garantia de Qualidade

### 23.1 Estrutura

`tests/` com 86 arquivos, organizados por validador/servico. Fixtures em `tests/fixtures/` (SPEDs sinteticos, XMLs de exemplo, contextos minimos). `conftest.py` provee:
- `tmp_db` (SQLite isolado por teste)
- `tmp_pg_db` (PostgreSQL via testcontainers — opcional)
- `sample_context` (ValidationContext minimo)
- `sample_records` (registros C100/C170/C190)

### 23.2 Cobertura

`pyproject.toml` define `fail_under = 80%` em `tool.coverage.report`.

### 23.3 Testes Importantes

| Suite | Foco |
|---|---|
| `test_cross_engine.py` | Motor XC: pareamento, regras XC, supressao por causa raiz |
| `test_difal_validator.py` + `test_difal_extended.py` | EC 87 + LC 190 + FCP |
| `test_beneficio_audit.py` + `test_beneficio_cross_validator.py` | Beneficios ES |
| `test_cst_validator.py` + `test_cst_hypothesis.py` + `test_cst_expandido.py` | CST e hipoteses |
| `test_field_map_validator.py` | Conferencia declarativa SPED x XML |
| `test_correction_governance.py` + `test_correction_service_concurrency.py` | Audit trail + race conditions |
| `test_database_pg.py` | Schema PG + JSONB + execute_values |
| `test_cors_config.py` + `test_auth.py` | Seguranca da API |
| `test_e2e.py` | Pipeline completo (upload → validate → report) |
| `test_check_hardcoded_indices.py` | Linter customizado (proibe acesso posicional) |

### 23.4 Qualidade Continua

- **Ruff** com regras `E, W, F, I, UP, B, SIM, S` (security)
- **Mypy** com `disallow_untyped_defs = true`
- **Bandit** (security scan) — opcional via `[dev]`

---

## 24. Oportunidades de Melhoria

### 24.1 Cruzamentos Adicionais
- C100 x D100 (frete IND_FRT vs CT-e)
- E110 x E210 (ICMS proprio vs ST)
- C170 x H010 (NCM/quantidade vs inventario)
- 0200 x C170 (ALIQ_ICMS de cadastro vs operacao real)
- K200 x K220 x K230 (estoque vs producao)
- E111 x JSON de beneficios (codigo de ajuste 5.1.1)
- SPED t vs SPED t-1 (saldo credor transportado)

### 24.2 Validacoes a Implementar
| Item | Prioridade |
|---|---|
| ICMS-ST com MVA completo por NCM/UF | Alta |
| Carga tributaria liquida pos-beneficio | Alta |
| Bloco G — CIAP (ativo imobilizado) | Media |
| Bloco 1 — Informacoes complementares (1100, 1200, 1400, 1500) | Media |
| EFD Contribuicoes (PIS/COFINS detalhado) | Alta |
| SPED x DCTF-Web (obrigacao acessoria) | Alta |
| Validacao XML contra XSD oficial antes do cruzamento | Media |

### 24.3 Analise Avancada
- Score de risco fiscal ponderado por materialidade (em andamento)
- Tendencia temporal (regressao/melhoria) entre periodos
- Clusterizacao de erros por causa raiz comum
- Benchmark setorial (CNAE)
- Mapa de calor (registro × bloco × frequencia)
- Alerta de prescricao decadencial (5 anos)

### 24.4 Tecnico
- Cache de validacao por record hash (evitar revalidar registros inalterados)
- Validacao incremental pos-correcao (revalidar somente afetados)
- Paralelismo entre validadores independentes (ThreadPool)
- Webhook de conclusao de auditoria
- Streaming de relatorio para arquivos > 100 MB
- Migracao completa para PostgreSQL com particionamento por periodo

---

*Documento gerado para analistas fiscais senior e engenheiros de software — SPED EFD Validator v3.0.0*
*Central Contabil — Atualizado em 2026-05-14*
