# SPED EFD Audit & Validator v4.0.0

**Sistema completo de auditoria, validacao e correcao de arquivos SPED EFD ICMS/IPI** com Motor de Cruzamento NF-e XML (95+ regras XC), 40 validadores especializados, 193 regras fiscais versionadas, IA explicativa, scores de risco e cobertura, e interface web React.

**Versao:** 4.0.0
**Licenca:** Proprietario — Central Contabil
**Autor:** Bruno (CentralContabil)

---

## Indice

1. [Visao Geral](#visao-geral)
2. [Arquitetura](#arquitetura)
3. [Stack Tecnologico](#stack-tecnologico)
4. [Estrutura do Projeto](#estrutura-do-projeto)
5. [Backend — API e Servicos](#backend--api-e-servicos)
6. [API — Endpoints Completos](#api--endpoints-completos)
7. [Frontend — Interface Web](#frontend--interface-web)
8. [Banco de Dados — Schema Completo](#banco-de-dados--schema-completo)
9. [Pipeline de Validacao](#pipeline-de-validacao)
10. [Validadores (40 modulos)](#validadores-40-modulos)
11. [Motor de Cruzamento XC (cross_engine)](#motor-de-cruzamento-xc-cross_engine)
12. [Cruzamento XML Legacy (17 Regras)](#cruzamento-xml-legacy-17-regras)
13. [Regras de Validacao (rules.yaml)](#regras-de-validacao-rulesyaml)
14. [Sistema de Tolerancias](#sistema-de-tolerancias)
15. [Motor de Beneficios Fiscais](#motor-de-beneficios-fiscais)
16. [IA Explicativa](#ia-explicativa)
17. [Tabelas de Referencia](#tabelas-de-referencia)
18. [Configuracao e Execucao](#configuracao-e-execucao)
19. [Testes](#testes)
20. [Infraestrutura e Deploy](#infraestrutura-e-deploy)

---

## Visao Geral

O SPED EFD Audit & Validator e uma plataforma de auditoria fiscal que:

- **Parseia** arquivos SPED EFD ICMS/IPI (todos os blocos: 0, C, D, E, G, H, K, 1, 9)
- **Valida** com 40 validadores especializados e 193 regras fiscais versionadas
- **Cruza** NF-e XML x SPED com Motor XC (95+ regras em 10 camadas)
- **Recalcula** tributos (ICMS, ICMS-ST, IPI, PIS/COFINS) item a item
- **Detecta** regime tributario automaticamente por CSTs reais do arquivo
- **Audita** beneficios fiscais (COMPETE, INVEST-ES, FUNDAP) com 50+ regras
- **Sugere** correcoes automaticas com hipoteses inteligentes de CST e aliquota
- **Explica** erros via IA com cache incremental por contexto fiscal
- **Exporta** relatorios estruturados e arquivo SPED corrigido
- **Pontua** risco fiscal e cobertura de auditoria por execucao

### Numeros do Sistema

| Componente | Quantidade |
|---|---|
| Validadores Python | 40 modulos |
| Regras em rules.yaml | 193 regras / 22 secoes |
| Regras Motor XC (XML x SPED) | 95+ regras (XC001-XC095 + variantes) |
| Endpoints API | 40+ |
| Tabelas no banco | 28+ |
| Tabelas de referencia (JSON/YAML) | 40+ arquivos |
| Arquivos de teste | 75 arquivos / 21.000+ linhas |
| LOC Python (sem testes) | ~22.800 |

---

## Arquitetura

```
Browser (React + Vite :5175)
  |
  v
FastAPI REST API (:8021)
  |
  +-- Pipeline de Validacao (3 estagios, 30+ validadores)
  +-- Motor de Cruzamento XC (10 etapas, 95+ regras)
  +-- Motor de Beneficios Fiscais (COMPETE, INVEST, FUNDAP)
  +-- IA Explicativa (OpenAI/Anthropic com cache)
  +-- Score de Risco + Cobertura
  |
  v
SQLite (audit.db) / PostgreSQL (opcional)
  +-- 28+ tabelas com 16 migracoes incrementais
  +-- WAL journal, foreign keys, indices otimizados
```

### Fluxo Principal

```
1. Upload SPED .txt → parsing linha a linha → sped_records
2. Construcao do ValidationContext (regime, beneficios, tabelas)
3. Pipeline de validacao (formato → intra → cruzamento → recalculo → auditoria → beneficios)
4. Upload XMLs NF-e → parse → nfe_xmls + nfe_itens
5. Motor XC: DocumentScopeBuilder → pareamento → regras XC por camada → deduplicacao
6. Scores de risco e cobertura
7. Enriquecimento (mensagens amigaveis, base legal)
8. Frontend exibe erros, sugere correcoes, exporta relatorio
```

---

## Stack Tecnologico

| Camada | Tecnologias |
|---|---|
| **Backend** | Python 3.10+, FastAPI 0.100+, Uvicorn, Pydantic 2.0+ |
| **Banco** | SQLite (WAL) / PostgreSQL (psycopg2) |
| **Frontend** | React 18.2+, TypeScript 5.3+, Vite 5.0+, Tailwind 3.4+, Recharts |
| **IA** | sentence-transformers, OpenAI SDK, cache por hash |
| **Referencia** | PyYAML, JSON (CST, NCM, DIFAL, FCP, beneficios) |
| **MySQL** | mysql-connector (consulta DCTF_WEB para regime) |
| **Deploy** | Docker, docker-compose (multi-stage build) |
| **Qualidade** | pytest (75 arquivos), ruff, mypy strict, bandit |

---

## Estrutura do Projeto

```
SPED/
|-- api/
|   |-- main.py                         # FastAPI app, CORS, health check, 11 routers
|   |-- deps.py                         # Dependency injection (DB, paths)
|   |-- routers/
|   |   |-- files.py                    # Upload, listagem, exclusao de arquivos
|   |   |-- validation.py              # Validacao sincrona/SSE, erros, audit-scope
|   |   |-- records.py                 # Registros SPED (CRUD)
|   |   |-- report.py                  # Relatorio estruturado, HTML, download corrigido
|   |   |-- xml.py                     # Upload XML, cruzamento legacy + XC, findings
|   |   |-- ai.py                      # Explicacao IA, cache stats
|   |   |-- rules.py                   # Catalogo de regras, geracao IA
|   |   |-- search.py                  # Busca semantica (embeddings)
|   |   |-- clients.py                 # Consulta CNPJ (MySQL DCTF_WEB)
|   |   |-- audit_scope.py            # Escopo de auditoria
|   |   +-- __init__.py
|   +-- schemas/
|       +-- models.py                   # 19 Pydantic schemas (FileInfo, ValidationError, etc.)
|
|-- src/
|   |-- models.py                       # Dataclasses: SpedRecord, ValidationError
|   |-- parser.py                       # Parser SPED EFD (blocos 0-9)
|   |-- services/                       # 25 servicos
|   |   |-- cross_engine.py            # Motor de Cruzamento XC (95+ regras)
|   |   |-- cross_engine_models.py     # Modelos: DocumentScope, Finding, enums
|   |   |-- document_scope_builder.py  # Builder de escopos + pareamento de itens
|   |   |-- xml_service.py            # Cruzamento legacy (XML001-XML017) + parser XML
|   |   |-- validation_service.py      # Orquestrador de validacao
|   |   |-- pipeline.py               # Pipeline estagiado (3 estagios + Motor XC)
|   |   |-- context_builder.py        # ValidationContext + regime por CST
|   |   |-- beneficio_engine.py       # Motor de beneficios (COMPETE, INVEST, FUNDAP)
|   |   |-- reference_loader.py       # Carregamento de tabelas externas
|   |   |-- rule_loader.py            # Versionamento de regras por vigencia
|   |   |-- ai_service.py             # IA explicativa com cache
|   |   |-- correction_service.py     # Servico de correcao
|   |   |-- auto_correction_service.py # Auto-correcao deterministica
|   |   |-- export_service.py         # Exportacao relatorios + SPED corrigido
|   |   |-- error_messages.py         # Mensagens amigaveis (700+ mapeamentos)
|   |   |-- risk_score.py             # Scores de risco e cobertura
|   |   |-- file_service.py           # Upload e gerenciamento
|   |   |-- client_service.py         # Consulta MySQL DCTF_WEB
|   |   |-- field_comparator.py       # Comparacao tipada SPED x XML
|   |   |-- database.py               # Schema SQLite (16 migracoes)
|   |   |-- database_pg.py            # Adapter PostgreSQL
|   |   |-- db_types.py               # Tipos conexao
|   |   |-- rate_limiter.py           # Rate limiter (janela deslizante)
|   |   +-- sped_line_format.py       # Formatacao de linhas SPED
|   |
|   +-- validators/                     # 40 validadores
|       |-- format_validator.py         # CNPJ, CPF, datas, CEP, CFOP, NCM, chave NFe
|       |-- intra_register_validator.py # Consistencia intra-registro (C100, C170, etc.)
|       |-- cross_block_validator.py    # Cruzamento entre blocos (0150 x C100, etc.)
|       |-- cst_validator.py           # CST ICMS, isencoes, Bloco H
|       |-- cst_hypothesis.py          # Hipoteses inteligentes de CST
|       |-- fiscal_semantics.py        # CST x CFOP, CST x aliquota, monofasicos
|       |-- aliquota_validator.py      # Aliquotas internas/interestaduais
|       |-- tax_recalc.py             # Recalculo: ICMS, ICMS-ST, IPI, PIS/COFINS
|       |-- c190_validator.py          # Consolidacao C190 x C170
|       |-- apuracao_validator.py      # E110, E111, E116 reconciliacao
|       |-- beneficio_validator.py     # BENE_001-003 (contaminacao)
|       |-- beneficio_cross_validator.py # 9 regras cross-beneficio
|       |-- beneficio_audit_validator.py # 50+ regras audit beneficio
|       |-- difal_validator.py         # DIFAL interestadual (696 linhas)
|       |-- st_validator.py            # ICMS-ST, MVA
|       |-- simples_validator.py       # Simples Nacional (CSOSN, credito)
|       |-- ncm_validator.py           # NCM vigencia e tratamento
|       |-- ipi_validator.py           # IPI reflexo BC e CST
|       |-- pis_cofins_validator.py    # PIS/COFINS direcao e consistencia
|       |-- devolucao_validator.py     # DEV_001-003 (devolucoes)
|       |-- destinatario_validator.py  # IE, UF, CEP destinatario
|       |-- cfop_validator.py          # CFOP x UF destino
|       |-- bloco_d_validator.py       # CT-e e transporte (Bloco D)
|       |-- bloco_k_validator.py       # Producao e estoque (Bloco K)
|       |-- bloco_c_servicos_validator.py # C400/C490 (ECF), C500/C590 (energia)
|       |-- base_calculo_validator.py  # BASE_001-006
|       |-- parametrizacao_validator.py # Erros sistematicos de ERP
|       |-- audit_rules.py            # Regras de auditoria avancadas
|       |-- encadeamento_validator.py  # Encadeamento C100→C170, ST, IPI
|       |-- pendentes_validator.py     # Regras pendentes
|       |-- retificador_validator.py   # Validacao de retificadores
|       |-- correction_hypothesis.py   # Hipoteses multi-step
|       |-- field_map_validator.py     # C100/C170/C190 x XML (field_map.yaml)
|       |-- error_deduplicator.py      # Deduplicacao de apontamentos
|       |-- tolerance.py              # Tolerancias parametrizadas
|       |-- regime_detector.py        # Deteccao regime por CST
|       |-- field_registry.py         # Registry de campos SPED
|       |-- helpers.py                # Constantes e funcoes auxiliares
|       |-- helpers_registry.py       # Conveniencia acesso campos
|       +-- __init__.py
|
|-- frontend/
|   |-- src/
|   |   |-- pages/
|   |   |   |-- UploadPage.tsx         # Upload SPED + regime override
|   |   |   |-- FilesPage.tsx          # Lista arquivos com status
|   |   |   |-- FileDetailPage.tsx     # Erros, registros, audit-scope (47KB)
|   |   |   |-- XMLCrossPage.tsx       # Upload XMLs + cruzamento (15KB)
|   |   |   |-- CrossValidationPage.tsx # Findings XC
|   |   |   +-- RulesPage.tsx          # Catalogo de regras
|   |   |-- components/
|   |   |   |-- Layout.tsx             # Header, nav, footer
|   |   |   |-- Dashboard/            # ErrorChart, AuditScopePanel
|   |   |   |-- Records/              # RecordDetail, FieldEditor, SuggestionPanel
|   |   |   +-- Corrections/          # CorrectionApprovalPanel
|   |   |-- api/
|   |   |   +-- client.ts             # Funcoes fetch tipadas
|   |   |-- App.tsx                    # Rotas React Router
|   |   +-- vite-env.d.ts
|   |-- vite.config.ts
|   |-- tailwind.config.js
|   |-- tsconfig.json
|   +-- package.json
|
|-- data/
|   |-- JSON/                           # 12 tabelas de referencia
|   |   |-- Tabela_CST_Vigente.json    # CST ICMS (74KB)
|   |   |-- Tabela_DIFAL_Vigente.json  # Aliquotas DIFAL por UF (43KB)
|   |   |-- Tabela_NCM_Vigente_20260407.json # NCM atualizado (4.1MB)
|   |   |-- Tabela_Fiscal_Complementar_v6.json # TIPI/ICMS (916KB)
|   |   +-- Beneficios (8 JSONs)       # COMPETE, INVEST, FUNDAP, ST-ES
|   |-- reference/                      # 24 arquivos YAML
|   |   |-- aliquotas_internas_uf.yaml
|   |   |-- fcp_por_uf.yaml
|   |   |-- ibge_municipios.yaml
|   |   |-- csosn_tabela_b.yaml
|   |   |-- mva_por_ncm_uf.yaml
|   |   |-- ncm_tipi_categorias.yaml
|   |   |-- sn_anexos_aliquotas.yaml
|   |   |-- sn_sublimites_uf.yaml
|   |   +-- vigencias/ (4 arquivos versionados)
|   |-- config/
|   |   +-- field_map.yaml             # Mapeamento declarativo C100/C170 x XML
|   +-- tabelas/
|       +-- aliquotas, fcp por UF
|
|-- tests/                              # 75 arquivos, 21.000+ linhas
|-- scripts/
|   +-- pg_schema.sql                  # Schema PostgreSQL
|-- db/                                 # SQLite databases (gitignored)
|-- rules.yaml                          # 193 regras / 22 secoes (120KB)
|-- config.py                          # Paths e parametros
|-- cli.py                             # CLI offline
|-- docker-compose.yml                 # API + frontend
|-- docker-compose.db.yml             # Com PostgreSQL
|-- Dockerfile / Dockerfile.frontend
|-- requirements.txt
|-- pyproject.toml
+-- .env.example
```

---

## Backend — API e Servicos

### Servicos (src/services/) — 25 modulos

| Servico | Linhas | Descricao |
|---|---|---|
| `cross_engine.py` | 1.331 | Motor de Cruzamento XC (95+ regras, 10 etapas, deduplicacao) |
| `xml_service.py` | 1.440 | Parser NF-e XML + cruzamento legacy (XML001-XML017) |
| `reference_loader.py` | 1.117 | Carregamento de tabelas externas (aliquotas, NCM, FCP, municipios) |
| `error_messages.py` | 738 | 700+ mapeamentos de mensagens amigaveis e base legal |
| `pipeline.py` | 729 | Pipeline estagiado: formato → cruzamento → Motor XC → enriquecimento |
| `export_service.py` | 658 | Relatorio auditoria + SPED corrigido (JSON, HTML) |
| `context_builder.py` | 637 | ValidationContext: regime, beneficios, participantes, produtos |
| `database.py` | 595 | Schema SQLite com 16 migracoes incrementais |
| `validation_service.py` | 590 | Orquestrador principal de validacao |
| `document_scope_builder.py` | 502 | Builder de escopos: pareamento C100 x XML, itens C170 x det |
| `cross_engine_models.py` | 431 | Modelos: DocumentScope, CrossValidationFinding, enums, constantes |
| `correction_service.py` | 412 | Correcao de registros com justificativa e auditoria |
| `file_service.py` | 343 | Upload, hash SHA256, parsing e persistencia |
| `ai_service.py` | 328 | Explicacao IA com cache por hash (regra + regime + UF + beneficio) |
| `beneficio_engine.py` | 318 | Motor de beneficios: COMPETE, INVEST-ES, FUNDAP (CSOSN→CST) |
| `database_pg.py` | 281 | Adapter PostgreSQL (interface identica a SQLite) |
| `field_comparator.py` | 230 | Comparacao tipada SPED x XML por campo |
| `auto_correction_service.py` | 215 | Auto-correcao deterministica com regras de precedencia |
| `risk_score.py` | 210 | Score de risco fiscal + score de cobertura por run |
| `client_service.py` | 185 | Consulta clientes MySQL DCTF_WEB (regime, CNAE, porte) |
| `rule_loader.py` | 166 | Carregamento de regras.yaml com filtragem por vigencia |
| `sped_line_format.py` | 102 | Formatacao de valores e reconstrucao de linhas SPED |
| `rate_limiter.py` | 101 | Rate limiter janela deslizante (IA e APIs externas) |

---

## API — Endpoints Completos

### Arquivos (`/api/files`) — 6 endpoints

| Metodo | Rota | Descricao |
|---|---|---|
| `POST` | `/api/files/upload` | Upload arquivo SPED EFD (multipart + regime_override) |
| `GET` | `/api/files` | Lista todos os arquivos com status |
| `GET` | `/api/files/{file_id}` | Detalhes de um arquivo |
| `DELETE` | `/api/files/{file_id}` | Remove arquivo e dados associados |
| `DELETE` | `/api/files/audit` | Limpa validacao de TODOS arquivos |
| `DELETE` | `/api/files/{file_id}/audit` | Limpa validacao do arquivo |

### Validacao (`/api/files/{file_id}`) — 9 endpoints

| Metodo | Rota | Descricao |
|---|---|---|
| `POST` | `/validate` | Validacao sincrona completa (pipeline 3 estagios) |
| `GET` | `/validate/stream` | Validacao assincrona com streaming SSE em tempo real |
| `GET` | `/errors` | Lista erros com filtros (tipo, severidade, registro, paginacao) |
| `GET` | `/summary` | Resumo: total, por tipo, por severidade, por registro |
| `GET` | `/audit-scope` | Escopo/cobertura: 30+ validators rastreados |
| `POST` | `/findings/{finding_id}/resolve` | Resolve achado (accepted/rejected/deferred/noted) |
| `GET` | `/findings/resolutions` | Lista resolucoes de achados |
| `DELETE` | `/errors/{error_id}` | Remove erro individual |
| `DELETE` | `/errors/group/{error_type}` | Remove todos os erros de um tipo especifico |
| `DELETE` | `/errors` | Limpa todos os erros |

### Registros (`/api/files/{file_id}/records`) — 3 endpoints

| Metodo | Rota | Descricao |
|---|---|---|
| `GET` | `/` | Lista registros SPED (filtro por bloco, registro, paginacao) |
| `GET` | `/{record_id}` | Detalhes de um registro (campos parseados) |
| `PUT` | `/{record_id}` | Atualiza campo do registro |

### Relatorio (`/api/files/{file_id}/report`) — 3 endpoints

| Metodo | Rota | Descricao |
|---|---|---|
| `GET` | `/report/structured` | Relatorio JSON estruturado (erros + resumo + metadados) |
| `GET` | `/report` | Relatorio HTML renderizado |
| `GET` | `/download` | Download do arquivo SPED corrigido (.txt) |

### XML e Cruzamento (`/api/files/{file_id}/xml`) — 8 endpoints

| Metodo | Rota | Descricao |
|---|---|---|
| `POST` | `/upload` | Upload batch de XMLs NF-e (multipart, modo_periodo) |
| `GET` | `/` | Lista XMLs vinculados (autorizadas, canceladas, total) |
| `POST` | `/cruzar` | Executa cruzamento legacy (XML001-XML017) |
| `GET` | `/cruzar/stream` | Cruzamento legacy com streaming SSE |
| `GET` | `/cruzamento` | Resultados cruzamento legacy (filtros: rule_id, severity) |
| `POST` | `/cruzar-xc` | **Motor XC**: cruzamento avancado (XC001-XC095) |
| `GET` | `/cruzamento-xc` | **Findings XC** com filtros (rule_id, severity, priority, review_status, hide_derived) |
| `DELETE` | `/{xml_id}` | Remove XML e cruzamentos associados |

### Regras (`/api/rules`) — 3 endpoints

| Metodo | Rota | Descricao |
|---|---|---|
| `GET` | `/` | Lista 193 regras de rules.yaml (22 secoes) |
| `POST` | `/generate` | Gera nova regra via IA |
| `POST` | `/implement` | Implementa regra no rules.yaml |

### IA (`/api/ai`) — 3 endpoints

| Metodo | Rota | Descricao |
|---|---|---|
| `POST` | `/explain` | Explicacao IA do erro (cache por hash de contexto) |
| `GET` | `/cache/stats` | Estatisticas do cache (hits, misses, tamanho) |
| `DELETE` | `/cache` | Limpa cache IA |

### Outros

| Metodo | Rota | Descricao |
|---|---|---|
| `GET` | `/api/search` | Busca semantica por embeddings |
| `GET` | `/api/clientes/cnpj/{cnpj}` | Consulta cliente MySQL DCTF_WEB |
| `GET` | `/api/health` | Health check (publico) |

---

## Frontend — Interface Web

### Paginas

| Pagina | Arquivo | Descricao |
|---|---|---|
| Upload | `UploadPage.tsx` | Upload SPED + selecao de pasta de XMLs (webkitdirectory) |
| Arquivos | `FilesPage.tsx` | Lista com status, acoes rapidas |
| Detalhes | `FileDetailPage.tsx` | Erros agrupados por tipo em abas, correcoes, graficos, audit-scope |
| XML | `XMLCrossPage.tsx` | Upload XMLs, cruzamento, divergencias |
| Cruzamento XC | `CrossValidationPage.tsx` | Findings XC com filtros e deduplicacao |
| Regras | `RulesPage.tsx` | Catalogo 193 regras, geracao IA |

### Componentes

- **Layout.tsx** — Header com navegacao, footer
- **Dashboard/ErrorChart.tsx** — Grafico pizza/barra de erros (Recharts)
- **Dashboard/AuditScopePanel.tsx** — Painel de cobertura e escopo
- **Records/RecordDetail.tsx** — Detalhes de registro com campos editaveis
- **Records/FieldEditor.tsx** — Editor inline de campo SPED
- **Records/SuggestionPanel.tsx** — Sugestoes de correcao
- **Corrections/CorrectionApprovalPanel.tsx** — Aprovacao/rejeicao de correcoes
- **ConfirmModal** (inline em FileDetailPage) — Modal de confirmacao com backdrop blur

### Erros Agrupados por Tipo (Abas)

O `FileDetailPage` exibe erros agrupados por `error_type` em sidebar com abas:

- Sidebar com lista de grupos ordenados por severidade maxima
- Bolinha colorida indica severidade (vermelho/laranja/amarelo/azul)
- Badge com contagem de erros abertos por grupo
- Indicador de quantos sao auto-corrigiveis
- **Acoes por grupo**: "Corrigir Grupo (N)", "Ignorar Grupo (N)", "Exportar TXT (N)"
- **Exportar TXT**: disponivel para XML001, XML002 e divergencias de NF-e — gera arquivo com numero e chave de cada NF-e
- Labels descritivos para ~45 error_types (ex: `XML001` = "NF-e ausente no SPED")
- Modal de confirmacao moderno (substitui `window.confirm`) com cores por contexto

### Tecnologias Frontend

- React 18.2+ com TypeScript 5.3+
- Vite 5.0+ (build tool)
- Tailwind CSS 3.4+ (estilizacao)
- Recharts 3.8+ (graficos)
- React Router (navegacao SPA)

---

## Banco de Dados — Schema Completo

16 migracoes incrementais. SQLite com WAL journal e foreign keys. PostgreSQL opcional via `DATABASE_URL`.

### Tabelas Principais

#### `sped_files` — Arquivos SPED processados

| Coluna | Tipo | Descricao |
|---|---|---|
| id | INTEGER PK | Auto-incremento |
| filename | TEXT | Nome do arquivo |
| hash_sha256 | TEXT | Hash do conteudo |
| upload_date | TEXT | Data de upload |
| period_start, period_end | TEXT | Periodo do arquivo (DDMMAAAA) |
| company_name | TEXT | Razao social (0000) |
| cnpj | TEXT | CNPJ contribuinte |
| uf | TEXT | UF contribuinte |
| total_records | INTEGER | Total de registros parseados |
| total_errors | INTEGER | Total de erros encontrados |
| status | TEXT | uploaded, validating, validated, error |
| validation_stage | TEXT | Estagio atual do pipeline |
| auto_corrections_applied | INTEGER | Correcoes auto aplicadas |
| regime_tributario | TEXT | Regime detectado |
| cod_ver | INTEGER | Versao do leiaute (0000) |
| original_file_id | INTEGER FK | ID do original (se retificador) |
| is_retificador | INTEGER | Flag retificador |
| regime_override | TEXT | Override manual de regime |
| ind_regime | TEXT | Indicador regime (NORMAL, SN, etc.) |
| regime_confidence | REAL | Confianca na deteccao |
| regime_signals | TEXT | Sinais usados (JSON) |
| xml_crossref_completed_at | TEXT | Timestamp fim cruzamento XML |

#### `sped_records` — Registros parseados

| Coluna | Tipo | Descricao |
|---|---|---|
| id | INTEGER PK | |
| file_id | INTEGER FK | Referencia sped_files |
| line_number | INTEGER | Linha no arquivo |
| register | TEXT | Tipo: C100, C170, E110, etc. |
| block | TEXT | Bloco: 0, C, D, E, H, K, 1 |
| parent_id | INTEGER | ID do registro pai (ex: C100 para C170) |
| fields_json | TEXT | Campos parseados como JSON |
| raw_line | TEXT | Linha original |
| status | TEXT | pending, validated, error |

#### `validation_errors` — Erros de validacao

| Coluna | Tipo | Descricao |
|---|---|---|
| id | INTEGER PK | |
| file_id | INTEGER FK | |
| record_id | INTEGER FK | Registro associado |
| line_number | INTEGER | Linha do erro |
| register | TEXT | Tipo de registro |
| field_no | INTEGER | Indice do campo |
| field_name | TEXT | Nome do campo |
| value | TEXT | Valor atual |
| error_type | TEXT | Tipo do erro (ex: CNPJ_INVALIDO) |
| severity | TEXT | error, warning, critical |
| message | TEXT | Mensagem tecnica |
| friendly_message | TEXT | Mensagem amigavel |
| legal_basis | TEXT | Base legal |
| expected_value | TEXT | Valor esperado |
| auto_correctable | INTEGER | 0/1 |
| doc_suggestion | TEXT | Sugestao de correcao |
| status | TEXT | open, resolved, dismissed |
| categoria | TEXT | fiscal, governance |
| certeza | TEXT | objetivo, provavel, indicio |
| impacto | TEXT | critico, relevante, informativo |
| materialidade | REAL | Impacto em R$ |

#### `cross_validation_findings` — Findings do Motor XC (Migration 16)

| Coluna | Tipo | Descricao |
|---|---|---|
| id | INTEGER PK | |
| file_id | INTEGER FK | |
| document_scope_id | INTEGER | Escopo do documento |
| rule_id | TEXT | XC001-XC095 + variantes |
| legacy_rule_id | TEXT | XML001-XML017 (retrocompat) |
| rule_version | TEXT | Versao da regra |
| reference_pack_version | TEXT | Versao tabelas fiscais |
| benefit_context_version | TEXT | Versao JSON beneficios |
| layout_version_detected | TEXT | COD_VER detectado |
| config_hash | TEXT | Hash da configuracao |
| error_type | TEXT | Ex: BC_ICMS_INDEVIDA_EM_CST_SEM_TRIBUTACAO |
| rule_outcome | TEXT | EXECUTED_ERROR, EXECUTED_OK, NOT_APPLICABLE, NOT_EXECUTED_MISSING_DATA, SUPPRESSED_BY_ROOT_CAUSE, NEUTRALIZED_BY_BENEFIT, AMBIGUOUS_MATCH |
| tipo_irregularidade | TEXT | CANCELAMENTO, DENEGACAO, REGULAR, etc. |
| severity | TEXT | critico, error, warning, info |
| confidence | TEXT | alta, media, baixa, indicio |
| sped_register | TEXT | Ex: C170 |
| sped_field | TEXT | Ex: VL_BC_ICMS |
| value_sped | TEXT | Valor no SPED |
| xml_field | TEXT | Ex: det/imposto/ICMS/*/vBC |
| value_xml | TEXT | Valor no XML |
| description | TEXT | Descricao do finding |
| evidence | TEXT | Evidencia JSON serializada |
| regime_context | TEXT | Regime do declarante |
| benefit_context | TEXT | Beneficio ativo |
| suggested_action | TEXT | FK suggested_action_types |
| root_cause_group | TEXT | Ex: XC020\|C170\|CST_ICMS |
| is_derived | INTEGER | 1 = derivado de causa raiz |
| risk_score | REAL | Score de risco |
| technical_risk_score | REAL | Score tecnico |
| fiscal_impact_estimate | REAL | Estimativa R$ |
| action_priority | TEXT | P1, P2, P3, P4 |
| review_status | TEXT | novo, em_revisao, justificado, corrigido, ignorado, falso_positivo |
| reviewed_by | TEXT | Usuario revisor |
| reviewed_at | DATETIME | Data revisao |
| review_reason | TEXT | Justificativa |
| review_evidence_ref | TEXT | Referencia evidencia |

#### `nfe_xmls` — NF-e XMLs uploadados

| Coluna | Tipo | Descricao |
|---|---|---|
| id | INTEGER PK | |
| file_id | INTEGER FK | SPED associado |
| chave_nfe | TEXT | 44 digitos |
| numero_nfe | TEXT | Numero da nota |
| serie | TEXT | Serie |
| cnpj_emitente | TEXT | CNPJ emitente (14 digitos) |
| cnpj_destinatario | TEXT | CNPJ destinatario |
| dh_emissao | TEXT | Data/hora emissao (ISO) |
| vl_doc, vl_icms, vl_icms_st, vl_ipi, vl_pis, vl_cofins | REAL | Totais |
| qtd_itens | INTEGER | Quantidade de itens |
| prot_cstat | TEXT | Status protocolo (100=autorizada, 101=cancelada, etc.) |
| status | TEXT | active, deleted |
| parsed_json | TEXT | JSON completo parseado |
| crt_emitente | INTEGER | CRT do emitente (1=SN, 2=SN sub, 3=Normal) |
| uf_emitente | TEXT | UF do emitente |
| uf_dest | TEXT | UF destino |
| mod_nfe | INTEGER | Modelo (55=NF-e, 65=NFC-e) |
| dentro_periodo | INTEGER | 1=dentro, 0=fora |
| c_sit | TEXT | Situacao |
| content_hash | TEXT | Hash do XML |

#### `nfe_itens` — Itens das NF-e

| Coluna | Tipo | Descricao |
|---|---|---|
| id | INTEGER PK | |
| nfe_id | INTEGER FK | Referencia nfe_xmls |
| num_item | INTEGER | Numero do item (nItem) |
| cod_produto | TEXT | cProd |
| ncm | TEXT | NCM (8 digitos) |
| cfop | TEXT | CFOP (4 digitos) |
| vl_prod | REAL | Valor produto |
| vl_desc | REAL | Desconto |
| cst_icms | TEXT | CST/CSOSN (orig+CST) |
| vbc_icms, aliq_icms, vl_icms | REAL | ICMS |
| cst_ipi, vl_ipi | TEXT/REAL | IPI |
| cst_pis, vl_pis | TEXT/REAL | PIS |
| cst_cofins, vl_cofins | TEXT/REAL | COFINS |

#### `nfe_cruzamento` — Cruzamento legacy (XML001-XML017)

| Coluna | Tipo | Descricao |
|---|---|---|
| id | INTEGER PK | |
| file_id | INTEGER FK | |
| nfe_id | INTEGER FK | |
| chave_nfe | TEXT | |
| rule_id | TEXT | XML001-XML017 ou XC### |
| severity | TEXT | critical, error, warning |
| campo_xml, valor_xml | TEXT | Campo e valor do XML |
| campo_sped, valor_sped | TEXT | Campo e valor do SPED |
| diferenca | REAL | Diferenca numerica |
| message | TEXT | Descricao |
| status | TEXT | open, resolved |
| nfe_item_id | INTEGER | Item associado |
| xml_xpath | TEXT | XPath do campo XML |
| tipo_comp | TEXT | Tipo de comparacao |

### Tabelas de Contexto e Auditoria

#### `clientes` — Cadastro mestre contribuintes

| Coluna | Tipo |
|---|---|
| id, cnpj (UNIQUE), razao_social, regime (LP/LR/SN/MEI/Imune/Isento), regime_override, uf, cnae_principal, porte (ME/EPP/Medio/Grande), ativo, created_at, updated_at |

#### `beneficios_ativos` — Beneficios por cliente/periodo

| Coluna | Tipo |
|---|---|
| id, cliente_id (FK), codigo_beneficio, tipo, competencia_inicio, competencia_fim, ato_concessorio, aliq_icms_efetiva, reducao_base_pct, debito_integral, observacoes, ativo |

#### `emitentes_crt` — CRT dos emitentes (de XMLs)

| Coluna | Tipo |
|---|---|
| cnpj_emitente (PK), crt (1/2/3), razao_social, uf_emitente, last_seen, fonte (xml/manual) |

#### `validation_runs` — Snapshots de execucao

| Coluna | Tipo |
|---|---|
| id, file_id (FK), mode (sped_only/sped_xml), cliente_id (FK), regime_usado, regime_source, beneficios_json, context_hash, rules_version, xml_cobertura_pct, executed_rules, skipped_rules, total_findings, coverage_score, risk_score, started_at, finished_at, status |

#### `xml_match_index` — Pareamento XML x C100

| Coluna | Tipo |
|---|---|
| id, run_id (FK), xml_id (FK), sped_c100_id, match_status (matched/sem_xml/sem_c100/fora_periodo/cancelada), chave_nfe, confidence, reason, is_complementar, xml_eligible, xml_effective_version, xml_effective_event_set, xml_resolution_reason |

#### Outras tabelas

| Tabela | Descricao |
|---|---|
| `corrections` | Correcoes aplicadas (old_value, new_value, justificativa, rule_id) |
| `audit_log` | Log de acoes (file_id, action, details) |
| `finding_resolutions` | Status de achados (open/accepted/rejected/deferred/noted) |
| `ai_error_cache` | Cache IA por hash (regra + regime + UF + beneficio) |
| `sped_file_versions` | Rastreabilidade original → retificador |
| `embedding_metadata` | Metadados de indexacao semantica |
| `suggested_action_types` | 7 tipos de acao sugerida |
| `field_equivalence_map` | Mapeamento campo SPED ↔ XML com tolerancias e vigencia |
| `coverage_gaps` | Lacunas de cobertura por run |
| `fiscal_context_snapshots` | Snapshot de contexto fiscal para auditoria |

---

## Pipeline de Validacao

O pipeline executa em 3 estagios principais + Motor XC:

### Estagio 1 — Parsing

- Parser SPED EFD (blocos 0, C, D, E, G, H, K, 1, 9)
- Extrai register, block, fields_json, raw_line, parent_id
- Persiste em sped_records

### Estagio 2 — Validacao (30+ validadores)

```
Contextualizacao (ValidationContext)
  |-- Regime por CSTs reais (BUG-001 fix)
  |-- Beneficios ativos (MySQL + JSON)
  |-- Caches: participantes, produtos, naturezas
  |-- Tabelas de referencia disponiveis
  |
  v
Formato → Intra-registro → Cruzamento inter-bloco → Recalculo tributario
  → CST/isencoes → Semantica fiscal → PIS/COFINS → Auditoria
  → Parametrizacao → NCM → Aliquotas → C190 → Bloco D
  → Beneficios (audit + cross + engine) → Devolucoes → IPI
  → Destinatario → CFOP → ICMS-ST/MVA → Simples Nacional
  → Apuracao E110 → Bloco C servicos → Bloco K → Retificador
  → Encadeamento → Hipoteses (aliquota + CST)
  → Deduplicacao → Filtragem por vigencia
```

### Estagio 2.5 — Motor de Cruzamento XC (se XMLs presentes)

```
DocumentScopeBuilder
  |-- Carrega C100 + C170 + XMLs + itens XML
  |-- Pareamento exato (nItem) + heuristico (cProd/NCM/CFOP/valor)
  |-- Deteccao NF complementar (2 sinais: COD_SIT=06 + C113)
  |-- Elegibilidade por COD_MOD (55/65)
  |
  v
CrossValidationEngine (10 etapas)
  |-- Etapa 1: Camada A — Estrutural (XC001-XC007)
  |-- Etapa 2: Camada D — Identidade (XC008-XC013)
  |-- Etapa 3: Camada D — Totais (XC003-XC006, XC015, XC023d/e/f)
  |-- Etapa 4: Pareamento de itens (MATCH_EXATO/PROVAVEL/HEURISTICO/AMBIGUO)
  |-- Etapa 5: Camada E — Itens (XC018-XC030 + extensoes)
  |-- Etapa 6: Camada F — Regime (XC031-XC032)
  |-- Etapa 8: Familias avancadas (XC07x, XC08x, XC09x)
  |-- Etapa 9: Deduplicacao por root_cause_group
  |-- Priorizacao P1-P4
  |
  v
Persistencia em cross_validation_findings + nfe_cruzamento (retrocompat)
```

### Estagio 3 — Enriquecimento

- Mensagens amigaveis (700+ mapeamentos hardcoded)
- **IA Explicativa integrada ao pipeline** (GPT-4o-mini): gera `doc_suggestion` estruturado
  com secoes "O que foi encontrado", "Por que isso importa", "Como corrigir", "Base legal"
- Contexto fiscal (regime, UF, beneficio) passado ao prompt para respostas especificas
- Resultados cacheados em `ai_error_cache` (1 chamada por grupo de erros identicos)
- Fallback para mensagem hardcoded quando API indisponivel
- Base legal via busca semantica (embeddings + FTS5)
- Scores de risco e cobertura
- Finalizacao do status

---

## Validadores (40 modulos)

### Tier 1 — Formato e Estrutura

| Validador | Linhas | Regras | Descricao |
|---|---|---|---|
| `format_validator.py` | 225 | CNPJ, CPF, datas, CEP, CFOP, NCM, chave NFe, cod municipio | Formato de campos |
| `intra_register_validator.py` | 453 | C100, C170, C190, E110, E111, E116, E200, E210 | Consistencia intra-registro |
| `field_registry.py` | 109 | — | Indice (register, field_name) → posicao |

### Tier 2 — Cruzamento Inter-blocos

| Validador | Linhas | Regras | Descricao |
|---|---|---|---|
| `cross_block_validator.py` | 184 | 0150 x C100, 0200 x C170, E110 | Referencia entre blocos |
| `bloco_d_validator.py` | 361 | CT-e, D100-D190, D300-D500 | Documentos transporte |
| `bloco_k_validator.py` | 104 | K100, K200, K220, K230 | Producao e estoque |
| `bloco_c_servicos_validator.py` | 232 | C400/C490, C500/C590 | ECF e energia |

### Tier 3 — Tributacao

| Validador | Linhas | Regras | Descricao |
|---|---|---|---|
| `cst_validator.py` | 634 | CST ICMS, isencoes, Bloco H | Validacao de CSTs |
| `cst_hypothesis.py` | 692 | Hipoteses CST | Motor sugestao inteligente |
| `fiscal_semantics.py` | 641 | CST x CFOP, CST x aliq, monofasicos | Semantica fiscal |
| `aliquota_validator.py` | 474 | Interestaduais, internas, media | Aliquotas ICMS |
| `tax_recalc.py` | 431 | ICMS, ICMS-ST, IPI, PIS/COFINS, E110 | Recalculo tributario |
| `st_validator.py` | 292 | ICMS-ST, MVA, CST 60 | ST com fallback C170→C100→C190 |
| `ipi_validator.py` | 185 | Reflexo BC, CST, recalculo | IPI |
| `pis_cofins_validator.py` | 222 | Direcao, CST, campos | PIS/COFINS |
| `base_calculo_validator.py` | 300 | BASE_001-006 | Base de calculo ICMS |
| `difal_validator.py` | 696 | DIFAL completo | Diferencial aliquota interestadual |
| `ncm_validator.py` | 338 | Vigencia, NCM generico | NCM e tratamento |
| `cfop_validator.py` | 96 | CFOP x UF, DIFAL | CFOP |
| `simples_validator.py` | 379 | CSOSN, credito, PIS/COFINS SN | Simples Nacional |

### Tier 4 — Beneficios Fiscais

| Validador | Linhas | Regras | Descricao |
|---|---|---|---|
| `beneficio_validator.py` | 334 | BENE_001-003 | Deteccao contaminacao |
| `beneficio_cross_validator.py` | 576 | 9 regras cross-beneficio | Cruzamento beneficio x SPED |
| `beneficio_audit_validator.py` | 1.587 | 50+ regras | Auditoria: E111, ST com E220/saldo/devolucoes |

### Tier 5 — Avancado

| Validador | Linhas | Regras | Descricao |
|---|---|---|---|
| `c190_validator.py` | 423 | Consolidacao C170 x C190 | Reconciliacao (valida total antes de apontar por grupo) |
| `apuracao_validator.py` | 525 | E110, E111, E116 | Apuracao ICMS |
| `devolucao_validator.py` | 269 | DEV_001-003 | Devolucoes |
| `destinatario_validator.py` | 244 | IE, UF, CEP | Destinatario |
| `parametrizacao_validator.py` | 315 | Erros sistematicos | Deteccao falha ERP |
| `audit_rules.py` | 467 | Regras avancadas | Auditoria fiscal |
| `encadeamento_validator.py` | 269 | C100→C170, ST, IPI | Encadeamento com fallback C170→C100→C190 |
| `correction_hypothesis.py` | 309 | Multi-step | Hipoteses correcao |
| `field_map_validator.py` | 714 | C100/C170/C190 x XML | Conferencia declarativa |
| `pendentes_validator.py` | 300 | Pendentes | Regras pendentes |
| `retificador_validator.py` | 94 | Retificador | Validacao retificadores |
| `error_deduplicator.py` | 107 | — | Deduplicacao |
| `tolerance.py` | 202 | — | Sistema tolerancias |
| `regime_detector.py` | 118 | — | Deteccao regime CST |

---

## Motor de Cruzamento XC (cross_engine)

O Motor XC e o sistema de cruzamento NF-e XML x SPED de nova geracao, implementando a especificacao `motor_cruzamento_v_final.txt`.

### Arquitetura

```
cross_engine_models.py     # Enums, dataclasses, constantes
document_scope_builder.py  # Builder de escopos + pareamento
cross_engine.py            # Pipeline 10 etapas + regras XC
```

### Hierarquia de Verdade

1. XML autorizada + eventos (fonte primaria absoluta)
2. Estrutura SPED (registros parseados)
3. Cadastros internos (0150, 0200, 0190, 0220, 0400)
4. Tabelas fiscais (CST, NCM, CFOP, aliquotas)
5. Cadastro externo (MySQL DCTF_WEB)
6. Cadastro de beneficios (JSONs modulares)
7. Heuristica (inferencia por padrao)

### Estados de Execucao (rule_outcome)

| Estado | Descricao |
|---|---|
| EXECUTED_ERROR | Regra executada, divergencia encontrada |
| EXECUTED_OK | Regra executada, tudo correto |
| NOT_APPLICABLE | Pre-condicao nao satisfeita |
| NOT_EXECUTED_MISSING_DATA | Dados insuficientes |
| SUPPRESSED_BY_ROOT_CAUSE | Derivado de causa raiz ja reportada |
| NEUTRALIZED_BY_BENEFIT | Coberto por beneficio fiscal |
| AMBIGUOUS_MATCH | Pareamento ambiguo |

### Estados de Pareamento de Itens

| Estado | Criterio |
|---|---|
| MATCH_EXATO | nItem XML == nItem C170 |
| MATCH_PROVAVEL | Score heuristico >= 70% |
| MATCH_HEURISTICO | Score >= 50% e < 70% |
| AMBIGUO | 2+ candidatos com score equivalente |
| SEM_MATCH | Nenhum candidato >= 50% |

### Catalogo de Regras XC

#### Camada A — Estrutural (XC001-XC007)

| Regra | Tipo | Severidade | Descricao |
|---|---|---|---|
| XC001 | XML_SEM_C100_CORRESPONDENTE | critico | NF-e no XML sem C100 no SPED |
| XC002 | C100_SEM_XML_CORRESPONDENTE | error | C100 com CHV_NFE sem XML |

#### Camada D — Identidade (XC008-XC013)

| Regra | Tipo | Severidade | Descricao |
|---|---|---|---|
| XC008 | XML_NOTA_CANCELADA_ESCRITURADA | critico | Nota cancelada (cStat 101/135) no SPED |
| XC008b | NOTA_DENEGADA_ESCRITURADA | critico | Nota denegada (cStat 110/301/302) no SPED |
| XC012 | C100_CNPJ_DIVERGENTE | error | CNPJ divergente XML vs 0150 |
| XC013 | C100_UF_DIVERGENTE | warning | UF divergente XML vs 0150 |

#### Camada D — Totais (XC003-XC006, XC015)

| Regra | Tipo | Severidade | Descricao |
|---|---|---|---|
| XC003 | VL_DOC_DIVERGENTE | critico | VL_DOC C100 vs vNF XML |
| XC004 | VL_ICMS_DIVERGENTE | critico | VL_ICMS C100 vs vICMS XML |
| XC005 | VL_ICMS_ST_DIVERGENTE | error | VL_ICMS_ST C100 vs vST XML |
| XC006 | VL_IPI_DIVERGENTE | error | VL_IPI C100 vs vIPI XML |
| XC015 | C100_MERC_DIVERGENTE | error | VL_MERC C100 vs vProd XML |
| XC023d | FRETE_DOCUMENTO_DIVERGENTE | warning | VL_FRT C100 vs vFrete XML |
| XC023e | SEGURO_DOCUMENTO_DIVERGENTE | warning | VL_SEG C100 vs vSeg XML |
| XC023f | OUTRAS_DESPESAS_DIVERGENTE | warning | VL_OUT_DA C100 vs vOutro XML |

#### Camada E — Itens (XC018-XC030)

| Regra | Tipo | Severidade | Descricao |
|---|---|---|---|
| XC018 | ITEM_XML_SEM_C170 | warning | Item XML sem C170 correspondente |
| XC019 | C170_SEM_ITEM_XML | warning | C170 sem item XML correspondente |
| XC019b | ITEM_PAREAMENTO_AMBIGUO | warning | Pareamento ambiguo (bloqueia regras subsequentes) |
| XC020 | CST_DIVERGENTE | error | CST divergente (com logica IND_EMIT) |
| XC021 | CFOP_DIVERGENTE | warning | CFOP divergente item |
| XC022 | NCM_DIVERGENTE | warning | NCM divergente item |
| XC023 | VL_ITEM_DIVERGENTE | error | VL_ITEM C170 vs vProd XML |
| XC023b | QUANTIDADE_ITEM_DIVERGENTE | warning | QTD C170 vs qCom XML |
| XC023c | DESCONTO_ITEM_DIVERGENTE | warning | VL_DESC C170 vs vDesc XML |
| XC024 | BC_ICMS_DIVERGENTE | error | VL_BC_ICMS C170 vs vBC XML |
| XC024b | BC_ICMS_INDEVIDA_SEM_TRIBUTACAO | error | BC ICMS > 0 em grupo isento/ST |
| XC025 | ALIQ_ICMS_DIVERGENTE | error | ALIQ_ICMS C170 vs pICMS XML |
| XC025b | ALIQ_INDEVIDA_SEM_TRIBUTACAO | error | Aliquota > 0 em grupo isento/ST |
| XC026 | VL_ICMS_ITEM_DIVERGENTE | error | VL_ICMS C170 vs vICMS XML |
| XC026b | ICMS_INDEVIDO_SEM_TRIBUTACAO | error | ICMS > 0 em grupo isento/ST |
| XC028 | IPI_DIVERGENTE | error | VL_IPI C170 vs vIPI XML |
| XC028b | IPI_SEM_RESPALDO_XML | warning | IPI no SPED sem grupo IPI no XML |
| XC028c | IPI_INDEVIDO_ITEM_ISENTO | error | IPI > 0 com grupo IPINT |
| XC029 | VL_PIS_DIVERGENTE | warning | VL_PIS C170 vs vPIS XML |
| XC029b | PIS_INDEVIDO_NAO_TRIBUTADO | warning | PIS > 0 com grupo PISNT |
| XC030 | VL_COFINS_DIVERGENTE | warning | VL_COFINS C170 vs vCOFINS XML |

#### Camada F — Regime (XC031-XC032)

| Regra | Tipo | Severidade | Descricao |
|---|---|---|---|
| XC031 | CSOSN_EM_REGIME_NORMAL | error | CSOSN (>=100) em empresa normal |
| XC032 | CST_NORMAL_EM_REGIME_SN | warning | CST normal (<100) em empresa SN |

#### Familia XC07x — Devolucao/Complemento

| Regra | Tipo | Severidade | Descricao |
|---|---|---|---|
| XC070 | DEVOLUCAO_SEM_NOTA_ORIGEM | warning | CFOP devolucao sem C113 |
| XC074 | NOTA_COMPLEMENTAR_IDENTIFICADA | info | NF complementar (COD_SIT=06 + C113) |

#### Familia XC08x — Importacao

| Regra | Tipo | Severidade | Descricao |
|---|---|---|---|
| XC080 | IMPORTACAO_SEM_C120 | warning | CFOP importacao sem C120 |

#### Familia XC09x — Desoneracao

| Regra | Tipo | Severidade | Descricao |
|---|---|---|---|
| XC093 | VICMSDESON_SEM_AJUSTE | warning | vICMSDeson > 0 sem E111 correspondente |

### Constantes do Motor XC

```python
# Modelos elegiveis para cruzamento XML
XML_ELIGIBLE_MODELS = {"55", "65"}

# Grupos sem campo de calculo ICMS (vBC, pICMS, vICMS)
GRUPOS_SEM_BC_ICMS = {
    "ICMS40", "ICMS41", "ICMS50", "ICMSST",
    "ICMSSN102", "ICMSSN103", "ICMSSN300", "ICMSSN400",
}

# Mapeamento PIS por grupo XML
PIS_GRUPO_MAP = {
    "PISAliq":  {"tipo": "ad_valorem"},
    "PISQtde":  {"tipo": "qtde"},
    "PISNT":    {"tipo": "nao_trib"},
    "PISOutr":  {"tipo": "outros"},
}
```

### Deduplicacao por Causa Raiz

```
root_cause_group = rule_id_raiz + "|" + register + "|" + campo
Exemplo: "XC020|C170|CST_ICMS"

XC020 (CST errado) → causa raiz de XC024, XC025, XC026
XC008 (cancelada) → causa raiz de todos findings do scope
```

### Priorizacao (action_priority)

| Prioridade | Criterio |
|---|---|
| P1 | Impacto direto na apuracao (ICMS, PIS, COFINS, IPI) |
| P2 | Divergencia com reflexo provavel na BC |
| P3 | Revisao cadastral/documental |
| P4 | Indicio/investigacao |

---

## Cruzamento XML Legacy (19 Regras)

O cruzamento legacy (xml_service.py) permanece ativo para retrocompatibilidade:

| Regra | Severidade | Descricao | Corrigivel |
|---|---|---|---|
| XML001 | critical | NF-e no XML sem C100 no SPED (exibe chave NF-e) | Nao |
| XML002 | error | C100 com CHV_NFE sem XML | Nao |
| XML003 | critical | VL_DOC divergente | Proposta |
| XML004 | critical | VL_ICMS divergente | Proposta |
| XML005 | error | VL_ICMS_ST divergente | Proposta |
| XML006 | error | VL_IPI divergente | Proposta |
| XML011 | error | NF-e cancelada | Nao |
| XML012 | error | Qtd itens divergente | Nao |
| XML013 | error | CNPJ participante divergente | Investigar |
| XML014 | warning | Data documento divergente | Investigar |
| XML015 | warning | Data entrada/saida divergente | Investigar |
| XML_C190 | high | Consolidacao C190 vs XML | Investigar |
| NF_CANCELADA_ESCRITURADA | critical | NF-e cancelada escriturada como ativa | Nao |
| NF_DENEGADA_ESCRITURADA | critical | NF-e denegada escriturada como ativa | Nao |
| NF_ATIVA_ESCRITURADA_CANCELADA | critical | NF-e autorizada escriturada como cancelada | Nao |
| NF_ATIVA_ESCRITURADA_DENEGADA | critical | NF-e autorizada escriturada como denegada | Nao |
| COD_SIT_DIVERGENTE_XML | error | COD_SIT incompativel com cStat do XML | Nao |

### Logica de Validacao COD_SIT

O cruzamento valida primeiro a consistencia entre `C100.COD_SIT` e `XML.cStat`:

```
1. Validar COD_SIT vs cStat (gerar erro de status se divergente)
   - cStat=101/135 + COD_SIT=00 → NF_CANCELADA_ESCRITURADA
   - cStat=110/301 + COD_SIT=00 → NF_DENEGADA_ESCRITURADA
   - cStat=100 + COD_SIT=02/03  → NF_ATIVA_ESCRITURADA_CANCELADA
   - cStat=100 + COD_SIT=04/05  → NF_ATIVA_ESCRITURADA_DENEGADA
2. Se COD_SIT=02/03/04/05 → skip comparacoes monetarias (XML003-XML012)
   Campos vazios sao corretos para docs cancelados/denegados
3. Comparar valores apenas quando COD_SIT permite (00/01)
```

---

## Regras de Validacao (rules.yaml)

**193 regras em 22 secoes**, versionadas por vigencia fiscal.

### Secoes

| Secao | Descricao | Exemplo de regra |
|---|---|---|
| formato | CNPJ, CPF, datas, CEP | CNPJ_INVALIDO |
| campo_a_campo | Campos obrigatorios | CAMPO_OBRIGATORIO |
| intra_registro | Consistencia interna | C100_VL_DOC_ZERO |
| cruzamento | Inter-blocos | REF_COD_PART_C100 |
| recalculo | Recalculo impostos | RECALC_ICMS_C170 |
| cst_isencoes | CST e isencoes | CST_INVALIDO |
| semantica_aliquota_zero | Aliquota zero | ALIQ_ZERO_CST_00 |
| semantica_cst_cfop | CST x CFOP | CST_CFOP_INCOMPATIVEL |
| monofasicos | Monofasicos | MONOFASICO_PIS |
| pendentes | Pendentes SPED | PENDING_RULE |
| auditoria_beneficios | Beneficios | BEN_CST_INCORRETO |
| aliquotas | Aliquotas | ALIQ_INTERNA_INCORRETA |
| cst_expandido | CST expandido | CST_NOVO_NAO_RECONHECIDO |
| difal | DIFAL | DIFAL_AUSENTE |
| base_calculo | Base ICMS | BASE_001 |
| beneficio_fiscal | Beneficios | BENE_001 |
| devolucoes | Devolucoes | DEV_001 |
| parametrizacao | Parametrizacao | PARAM_SISTEMATICO |
| ncm | NCM | NCM_GENERICO |
| governanca | Governanca | GOV_001 |
| simples_nacional | SN | SN_CSOSN_INVALIDO |
| bloco_k | Producao | K200_SEM_K100 |

### Estrutura de cada regra

```yaml
- id: RECALC_ICMS_C170
  register: C170
  fields: [VL_BC_ICMS, ALIQ_ICMS, VL_ICMS]
  error_type: RECALC_DIVERGENTE
  severity: error
  corrigivel: proposta
  certeza: objetivo
  impacto: critico
  vigencia_de: '2009-01-01'
  version: 1
  module: tax_recalc.py
  description: "Recalculo ICMS divergente no C170"
  condition: "abs(VL_BC * ALIQ / 100 - VL_ICMS) > tolerancia"
  base_legal: "Dec. 1.090-R/2002, Art. XXX"
```

---

## Sistema de Tolerancias

```python
# Por nivel de comparacao
ITEM:           R$ 0,02 (valor) | 0,001 (quantidade decimal)
DOCUMENTO:      R$ 0,02
CONSOLIDACAO:   R$ 1,00
APURACAO:       R$ 1,00

# Tolerancia proporcional ao valor
def tolerancia_proporcional(valor: float) -> float:
    if valor <= 100:    return 0.02
    if valor <= 1000:   return 0.05
    if valor <= 10000:  return 0.10
    return 0.50

# Residuo abaixo da tolerancia: severity="info", nao entra no risk_score
```

---

## Motor de Beneficios Fiscais

### Programas Suportados

| Programa | Tipo | Descricao |
|---|---|---|
| COMPETE_ATACADISTA | Credito presumido 3% | Atacado ES |
| COMPETE_VAREJISTA_ECOMMERCE | Credito presumido | Varejo/e-commerce ES |
| COMPETE_IND_GRAFICAS | Credito presumido | Industria grafica ES |
| COMPETE_IND_PAPELAO_MAT_PLAST | Credito presumido | Papelao/plastico ES |
| INVEST_ES_INDUSTRIA | Diferimento | Investimento industrial ES |
| INVEST_ES_IMPORTACAO | Diferimento | Investimento importacao ES |
| FUNDAP | Credito pauta | Fundo de financiamento ES |

### Mapeamento CSOSN → CST

```
101→00, 102→20, 103→40, 201→10, 202→10, 203→30,
300→41, 400→40, 500→60, 900→90
```

### Regras de Beneficio (50+)

- Validacao E111 (codigos de ajuste por UF)
- NCM no escopo do beneficio
- CST obrigatorio por tipo de beneficio
- CFOP elegivel
- Calculo de credito presumido
- Exclusividade mutua entre programas
- Trilha completa: cBenef → C179 → C197 → E111 → E112/E113

---

## IA Explicativa

### Funcionamento

A IA e integrada em dois pontos:

**1. Pipeline de Validacao (automatico):** Durante o estagio de enriquecimento, cada grupo de erros
recebe uma explicacao estruturada via GPT-4o-mini com secoes formatadas:

```
**O que foi encontrado:** [descricao do erro com valores e campos]
**Por que isso importa:** [impacto fiscal — credito indevido, omissao, risco]
**Como corrigir:** [instrucoes objetivas citando campos e registros]
**Base legal:** [LC 87/96, Guia Pratico EFD, RICMS, etc.]
```

O frontend renderiza cada secao com cor distinta (vermelho/amarelo/azul/cinza).

**2. Endpoint sob demanda** (`POST /api/ai/explain`): Permite consultar explicacao
para qualquer erro especifico, retornando explicacao + sugestao.

### Cache

1. Recebe erro + contexto (regime, UF, beneficio, operacao, valor, expected)
2. Gera hash SHA256 do contexto para cache
3. Busca no cache (`ai_error_cache`)
4. Se miss: chama OpenAI GPT-4o-mini (temperature=0.2, max_tokens=600)
5. Retorna explicacao estruturada
6. Persiste no cache (1 chamada por grupo de erros identicos)

### Cache Key

```python
hash = SHA256(rule_id + error_type + regime + uf + beneficio + campo + valor_bucket)
```

### Buckets de valor (para cache)

```
0        → "zero"
< 10     → "centavos"
< 100    → "dezenas"
< 1.000  → "centenas"
< 10.000 → "milhares"
>= 10.000 → "alto"
```

---

## Tabelas de Referencia

### JSON (data/JSON/)

| Arquivo | Tamanho | Descricao |
|---|---|---|
| Tabela_CST_Vigente.json | 74KB | CST ICMS completo com descricoes |
| Tabela_DIFAL_Vigente.json | 43KB | Aliquotas DIFAL por UF origem/destino |
| Tabela_NCM_Vigente_20260407.json | 4.1MB | 10.000+ NCMs com tributacao |
| Tabela_Fiscal_Complementar_v6.json | 916KB | TIPI/ICMS complementar |
| COMPETE_*.json (4 arquivos) | ~50KB | Regras COMPETE por modalidade |
| INVEST_ES_*.json (2 arquivos) | ~30KB | Regras INVEST-ES |
| FUNDAP.json | ~15KB | Regras FUNDAP |
| SUBSTITUICAO_TRIBUTARIA_ES.json | ~20KB | ST no ES |

### YAML (data/reference/)

| Arquivo | Descricao |
|---|---|
| aliquotas_internas_uf.yaml | ICMS interno por UF (versionado por data) |
| fcp_por_uf.yaml | FCP por UF |
| ibge_municipios.yaml | Codigos IBGE |
| csosn_tabela_b.yaml | CSOSN Simples Nacional |
| cst_pis_cofins_sn.yaml | CST PIS/COFINS para SN |
| mva_por_ncm_uf.yaml | MVA (Margem Valor Agregado) |
| ncm_tipi_categorias.yaml | Categorias NCM |
| sn_anexos_aliquotas.yaml | Anexos SN com aliquotas |
| sn_sublimites_uf.yaml | Sublimites SN por UF |
| field_map.yaml | Mapeamento declarativo SPED x XML |

---

## Configuracao e Execucao

### Variaveis de Ambiente

```bash
# API
API_KEY=sua_chave_32_caracteres_minimo
PORT=8021

# Banco
DATABASE_URL=                          # Vazio = SQLite | postgresql://... = PG

# MySQL (DCTF_WEB — opcional)
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=secret
MYSQL_DATABASE=dctf_web

# IA (opcional)
OPENAI_API_KEY=sk-...
```

### Execucao Local

```bash
# Backend
pip install -r requirements.txt
uvicorn api.main:app --host 0.0.0.0 --port 8021

# Frontend
cd frontend
npm install
npm run dev  # porta 5175

# CLI offline
python cli.py arquivo.txt --modo completo
```

### Docker

```bash
# Stack basica (API + frontend)
docker-compose up -d --build

# Com PostgreSQL
docker-compose -f docker-compose.db.yml up -d --build
```

---

## Testes

**75 arquivos de teste | 21.000+ linhas | 1.770+ testes**

### Executar

```bash
# Todos os testes
pytest tests/ -v

# Com cobertura
pytest tests/ --cov=src --cov-report=html

# Testes especificos
pytest tests/test_cross_engine.py -v           # Motor XC (32 testes)
pytest tests/test_xml_service.py -v            # Cruzamento XML
pytest tests/test_beneficio_audit.py -v        # Beneficios
pytest tests/test_fiscal_scenarios.py -v       # Cenarios fiscais E2E
```

### Cobertura por Area

| Area | Arquivos de Teste | Testes |
|---|---|---|
| Motor XC (cross_engine) | test_cross_engine.py | 32 |
| Validadores SPED | 28 arquivos | ~800 |
| Integracao API | test_api*.py, test_e2e.py | ~200 |
| Servicos | 15 arquivos | ~400 |
| Parser e modelos | test_parser*.py, test_models.py | ~150 |
| Referencia e regras | test_rule_loader.py, test_reference*.py | ~100 |

---

## Infraestrutura e Deploy

### Docker

```yaml
# docker-compose.yml
services:
  api:
    build: .
    ports: ["8021:8021"]
    volumes: ["db-data:/app/db"]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8021/api/health"]
  frontend:
    build:
      context: .
      dockerfile: Dockerfile.frontend
    ports: ["5175:3000"]
```

### PostgreSQL (opcional)

```yaml
# docker-compose.db.yml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: sped_audit
      POSTGRES_USER: sped
      POSTGRES_PASSWORD: secret
    ports: ["25434:5432"]
```

### Qualidade de Codigo

```bash
# Linting
ruff check src/ api/ tests/

# Type checking
mypy src/ api/ --strict

# Seguranca
bandit -r src/ api/
```

---

## Mapeamento Legacy XML### → XC###

| Legacy | XC | Status |
|---|---|---|
| XML001 | XC001 | Implementado |
| XML002 | XC002 | Implementado |
| XML003 | XC003 | Implementado |
| XML004 | XC004 | Implementado |
| XML005 | XC005 | Implementado |
| XML006 | XC006 | Implementado |
| XML007 | XC018 | Implementado |
| XML008 | XC019 | Implementado |
| XML009 | XC021 | Implementado |
| XML010 | XC022 | Implementado |
| XML011 | XC023 | Implementado |
| XML012 | XC014 | Implementado |
| XML013 | XC015 | Implementado |
| XML014 | XC016 | Implementado |
| XML015 | XC017 | Implementado |
| XML016 | XC012 | Implementado |
| XML017 | XC013 | Implementado |

---

**Central Contabil** — Auditoria Fiscal SPED EFD ICMS/IPI v4.0.0
