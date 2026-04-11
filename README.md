# SPED EFD Validator v3.0.0

**Sistema de Auditoria, Validacao e Correcao de Escrituracao Fiscal Digital (EFD ICMS/IPI)**

Plataforma completa para auditoria fiscal automatizada de arquivos SPED EFD. Combina motor de regras deterministico (177 regras implementadas), busca hibrida em legislacao (FTS5 + embeddings semanticos), cruzamento NF-e XML, e inteligencia artificial (OpenAI GPT-4o-mini) para explicacao contextualizada de erros — tudo em portugues brasileiro.

---

## Indice

- [Arquitetura](#arquitetura)
- [Stack Tecnologica](#stack-tecnologica)
- [Estrutura do Projeto](#estrutura-do-projeto)
- [Banco de Dados](#banco-de-dados)
- [Motor de Regras](#motor-de-regras)
- [Pipeline de Validacao](#pipeline-de-validacao)
- [Validadores](#validadores)
- [Servicos](#servicos)
- [Fontes de Dados e JSONs de Referencia](#fontes-de-dados-e-jsons-de-referencia)
- [Cruzamento NF-e XML x SPED](#cruzamento-nf-e-xml-x-sped)
- [Inteligencia Artificial](#inteligencia-artificial)
- [API REST (FastAPI)](#api-rest-fastapi)
- [Frontend (React)](#frontend-react)
- [CLI](#cli)
- [Testes](#testes)
- [Configuracao e Ambiente](#configuracao-e-ambiente)
- [Como Rodar](#como-rodar)
- [Docker](#docker)
- [Seguranca](#seguranca)

---

## Arquitetura

```
                   +------------------+
                   |   Frontend React |  :5175
                   |   (Vite + TS)    |
                   +--------+---------+
                            |
                      fetch /api/*
                            |
                   +--------v---------+
                   |   FastAPI (REST)  |  :8021
                   |   + SSE Stream   |
                   +--------+---------+
                            |
              +-------------+-------------+
              |             |             |
     +--------v--+   +-----v-----+  +----v--------+
     | SQLite     |   | OpenAI    |  | MySQL       |
     | audit.db   |   | GPT-4o   |  | DCTF_WEB    |
     | sped.db    |   | (cache)  |  | (clientes)  |
     +------------+   +----------+  +-------------+
```

**Fluxo principal:**

1. **Upload** — Usuario envia arquivo SPED EFD (.txt) pelo frontend
2. **Parsing** — Parser pipe-delimited com deteccao automatica de encoding (latin-1/cp1252/utf-8)
3. **Persistencia** — Registros salvos no SQLite em batches de 1000 (streaming)
4. **Contexto** — Identificacao automatica de regime tributario, periodo, UF, CNPJ
5. **Validacao** — Pipeline de 4 estagios com 177 regras em 37 validadores
6. **Enriquecimento** — Mensagens amigaveis + busca de base legal na documentacao
7. **IA (opcional)** — Explicacao contextualizada via OpenAI com cache incremental
8. **Cruzamento XML** — Upload de NF-e XMLs e cruzamento com registros C100/C170
9. **Correcao** — Sugestoes deterministicas + aprovacao humana + audit trail
10. **Exportacao** — SPED corrigido, relatorio Markdown, relatorio estruturado JSON

---

## Stack Tecnologica

### Backend (Python 3.10+)

| Tecnologia | Versao | Uso |
|---|---|---|
| **FastAPI** | >=0.100.0 | API REST com SSE streaming |
| **Uvicorn** | >=0.23.0 | Servidor ASGI |
| **Pydantic** | >=2.0.0 | Schemas de request/response |
| **SQLite3** | stdlib | Banco principal (WAL mode, foreign keys) |
| **PyYAML** | >=6.0 | Regras de validacao (rules.yaml) |
| **Sentence-Transformers** | >=2.2.0 | Embeddings semanticos (all-MiniLM-L6-v2, 384 dims) |
| **NumPy** | >=1.24.0 | Operacoes vetoriais (cosine similarity) |
| **PyTorch** | >=2.0.0 | Backend para sentence-transformers |
| **pdfplumber** | >=0.10.0 | Conversao PDF -> Markdown |
| **python-docx** | >=0.8.0 | Conversao DOCX -> Markdown |
| **OpenAI SDK** | dinamico | Explicacao de erros via GPT-4o-mini |
| **mysql-connector-python** | >=8.0.0 | Integracao DCTF_WEB (dados de clientes) |
| **tqdm** | >=4.65.0 | Barras de progresso |

### Frontend

| Tecnologia | Versao | Uso |
|---|---|---|
| **React** | ^18.2.0 | UI reativa |
| **TypeScript** | ^5.3.0 | Tipagem estatica |
| **Vite** | ^5.0.0 | Build tool e dev server |
| **React Router** | ^6.20.0 | Navegacao SPA |
| **Recharts** | ^3.8.1 | Graficos de erros (dashboard) |
| **Tailwind CSS** | ^3.x | Estilizacao utility-first |

### Dev & Quality

| Ferramenta | Uso |
|---|---|
| **pytest** | Testes unitarios e de integracao (70+ arquivos) |
| **pytest-cov** | Cobertura de codigo (target 80%) |
| **ruff** | Linter + formatter (pycodestyle, pyflakes, isort, bugbear, bandit) |
| **mypy** | Verificacao de tipos estatica |
| **bandit** | Analise de seguranca |
| **httpx** | Testes de API |

### Infraestrutura

| Componente | Detalhes |
|---|---|
| **Docker Compose** | 2 servicos (api + frontend) |
| **SQLite WAL** | Modo journal WAL para concorrencia |
| **Redis** | *Nao utilizado neste modulo* (usado apenas no webapp-01) |

---

## Estrutura do Projeto

```
SPED/
├── api/                              # FastAPI REST API
│   ├── main.py                       # App principal + health check + CORS
│   ├── auth.py                       # Autenticacao por API Key
│   ├── deps.py                       # Dependency injection (get_db)
│   ├── schemas/
│   │   └── models.py                 # Pydantic models (request/response)
│   └── routers/
│       ├── files.py                  # Upload, listagem, exclusao de SPED
│       ├── validation.py             # Validacao sync + SSE streaming
│       ├── records.py                # Consulta/edicao de registros
│       ├── rules.py                  # CRUD de regras + geracao IA
│       ├── search.py                 # Busca hibrida na documentacao
│       ├── report.py                 # Relatorios (Markdown, JSON)
│       ├── xml.py                    # Cruzamento NF-e XML
│       ├── ai.py                     # Explicacao de erros via IA
│       ├── audit_scope.py            # Dashboard de escopo da auditoria
│       └── clientes.py              # Consulta MySQL (DCTF_WEB)
│
├── src/                              # Core engine
│   ├── parser.py                     # Parser SPED EFD (pipe-delimited)
│   ├── models.py                     # Dataclasses: SpedRecord, ValidationError, Chunk
│   ├── converter.py                  # PDF/DOCX/TXT -> Markdown
│   ├── indexer.py                    # Markdown -> SQLite (FTS5 + embeddings)
│   ├── searcher.py                   # Busca hibrida (FTS5 + vetorial + RRF)
│   ├── embeddings.py                 # Wrapper sentence-transformers
│   ├── validator.py                  # Validacao campo-a-campo por definicoes
│   ├── rules.py                      # Loader e verificador do rules.yaml
│   │
│   ├── validators/                   # 37 modulos de validacao
│   │   ├── format_validator.py       # CNPJ, CPF, datas, CEP, CFOP
│   │   ├── intra_register_validator.py # Regras dentro de C100, C170, C190
│   │   ├── cross_block_validator.py  # Cruzamento entre blocos (0 vs C/D/E)
│   │   ├── tax_recalc.py            # Recalculo ICMS, IPI, PIS/COFINS
│   │   ├── cst_validator.py          # CST ICMS + isencoes
│   │   ├── fiscal_semantics.py       # CST x CFOP, monofasicos, aliquota zero
│   │   ├── aliquota_validator.py     # Aliquotas interestaduais/internas
│   │   ├── c190_validator.py         # Consolidacao C190 vs C170
│   │   ├── base_calculo_validator.py # Base de calculo ICMS
│   │   ├── difal_validator.py        # DIFAL + FCP (EC 87/2015)
│   │   ├── st_validator.py           # Substituicao tributaria + MVA
│   │   ├── ipi_validator.py          # IPI: reflexo BC, CST monetario
│   │   ├── pis_cofins_validator.py   # PIS/COFINS por regime
│   │   ├── beneficio_validator.py    # Beneficios fiscais (BENE_001-003)
│   │   ├── beneficio_audit_validator.py # Auditoria completa de beneficios (50+ regras)
│   │   ├── beneficio_cross_validator.py # Cruzamento beneficio x documento
│   │   ├── cfop_validator.py         # CFOP interestadual vs interno
│   │   ├── destinatario_validator.py # IE, UF, CEP do destinatario
│   │   ├── devolucao_validator.py    # Devolucoes (DEV_001-003)
│   │   ├── ncm_validator.py          # NCM: tratamento tributario, generico
│   │   ├── parametrizacao_validator.py # Erros sistematicos por item/UF/data
│   │   ├── pendentes_validator.py    # Beneficios nao vinculados, anomalias
│   │   ├── audit_rules.py           # Regras de governanca fiscal
│   │   ├── bloco_d_validator.py      # Bloco D (servicos de transporte)
│   │   ├── bloco_c_servicos_validator.py # Servicos no Bloco C
│   │   ├── bloco_k_validator.py      # Bloco K (producao/inventario)
│   │   ├── simples_validator.py      # Simples Nacional
│   │   ├── apuracao_validator.py     # Apuracao de impostos
│   │   ├── retificador_validator.py  # Arquivos retificadores
│   │   ├── correction_hypothesis.py  # Hipoteses de correcao (aliquota)
│   │   ├── cst_hypothesis.py         # Hipoteses de CST
│   │   ├── regime_detector.py        # Deteccao automatica de regime
│   │   ├── error_deduplicator.py     # Deduplicacao inteligente
│   │   ├── field_registry.py         # Registro de campos SPED
│   │   ├── tolerance.py              # Materialidade e tolerancia
│   │   └── helpers.py                # Funcoes auxiliares (fields_to_dict, etc.)
│   │
│   └── services/                     # Servicos de negocio
│       ├── pipeline.py               # Pipeline estagiado com progresso SSE
│       ├── validation_service.py     # Orquestrador de validacao
│       ├── database.py               # Schema SQLite + 7 migracoes
│       ├── file_service.py           # Upload streaming + SHA256
│       ├── context_builder.py        # Regime tributario + caches
│       ├── reference_loader.py       # Tabelas YAML (aliquotas, FCP, NCM)
│       ├── rule_loader.py            # rules.yaml com filtragem por vigencia
│       ├── auto_correction_service.py # Correcoes deterministicas seguras
│       ├── correction_service.py     # Aplicacao + historico de correcoes
│       ├── ai_service.py             # OpenAI GPT-4o-mini + cache incremental
│       ├── xml_service.py            # Parser NF-e XML + 17 regras cruzamento
│       ├── export_service.py         # Exportacao SPED corrigido + relatorios
│       ├── error_messages.py         # Mensagens amigaveis em PT-BR
│       └── client_service.py         # Integracao MySQL DCTF_WEB
│
├── frontend/                         # React + TypeScript + Vite
│   └── src/
│       ├── main.tsx                  # Router (5 rotas)
│       ├── api/client.ts             # Funcoes fetch para API
│       ├── types/sped.ts             # Interfaces TypeScript
│       ├── pages/
│       │   ├── UploadPage.tsx        # Upload de SPED + validacao
│       │   ├── FilesPage.tsx         # Lista de arquivos processados
│       │   ├── FileDetailPage.tsx    # Detalhes + erros + correcoes
│       │   ├── CrossValidationPage.tsx # Cruzamento XML
│       │   └── RulesPage.tsx         # Gerenciamento de regras
│       └── components/
│           ├── Layout.tsx            # Shell da aplicacao
│           ├── Dashboard/            # ErrorChart, AuditScopePanel
│           ├── Records/              # FieldEditor, RecordDetail, SuggestionPanel
│           └── Corrections/          # CorrectionApprovalPanel
│
├── data/
│   ├── JSON/                         # Tabelas de referencia fiscal
│   │   ├── Tabela_CST_Vigente.json   # Codigos de Situacao Tributaria
│   │   ├── Tabela_DIFAL_Vigente.json # Aliquotas DIFAL por UF
│   │   ├── Tabela_NCM_Vigente_*.json # Classificacao NCM
│   │   ├── Tabela_Fiscal_Complementar_v6.json # CFOP + aliquotas + FCP (25K linhas)
│   │   ├── COMPETE_*.json            # Beneficios COMPETE-ES
│   │   ├── INVEST_ES_*.json          # Beneficios INVEST-ES
│   │   ├── FUNDAP.json               # Beneficio FUNDAP
│   │   ├── SUBSTITUICAO_TRIBUTARIA_ES.json # ST no ES
│   │   ├── XML_SCHEMA.json           # Schema de validacao XML
│   │   └── XML_PAYLOAD.json          # Payload de testes XML
│   ├── reference/                    # Tabelas YAML
│   │   ├── aliquotas_internas_uf.yaml
│   │   ├── fcp_por_uf.yaml
│   │   ├── codigos_ajuste_uf.yaml
│   │   ├── csosn_tabela_b.yaml
│   │   ├── cst_pis_cofins_sn.yaml
│   │   ├── ibge_municipios.yaml
│   │   ├── mva_por_ncm_uf.yaml
│   │   ├── ncm_tipi_categorias.yaml
│   │   ├── sn_anexos_aliquotas.yaml
│   │   └── sn_sublimites_uf.yaml
│   └── tabelas/                      # Tabelas adicionais
│
├── tests/                            # 70+ arquivos de teste (pytest)
├── db/                               # Bancos SQLite (audit.db, sped.db)
├── rules.yaml                        # 177 regras de validacao
├── config.py                         # Configuracoes centrais
├── cli.py                            # Interface de linha de comando
├── pyproject.toml                    # Dependencias + tooling
├── requirements.txt                  # Dependencias (pip)
├── docker-compose.yml                # API + Frontend containers
├── Dockerfile                        # Backend
├── Dockerfile.frontend               # Frontend
├── .env.example                      # Template de variaveis
└── melhorias.txt                     # Planos futuros (Plano 17, 18)
```

---

## Banco de Dados

O sistema utiliza **dois bancos SQLite** em modo WAL (Write-Ahead Logging):

### `db/sped.db` — Documentacao indexada

| Tabela | Descricao |
|---|---|
| `chunks` | Trechos de documentacao (Guia Pratico, legislacao) |
| `chunks_fts` | Indice FTS5 (busca full-text com unicode61) |
| `register_fields` | Definicoes de campos por registro SPED |
| `indexed_files` | Controle de arquivos ja indexados |
| `embedding_metadata` | Metadados do modelo de embeddings |

### `db/audit.db` — Auditoria e validacao

| Tabela | Descricao |
|---|---|
| `sped_files` | Arquivos SPED (CNPJ, UF, periodo, status, regime, cod_ver) |
| `sped_records` | Registros parseados (fields_json, block, status) |
| `sped_file_versions` | Vinculo original x retificador |
| `validation_errors` | Erros (177 tipos, severidade, certeza, impacto, auto_correctable) |
| `cross_validations` | Cruzamentos entre blocos |
| `corrections` | Correcoes aplicadas (justificativa, correction_type, rule_id) |
| `audit_log` | Log de auditoria (acoes do analista) |
| `ai_error_cache` | Cache incremental de explicacoes IA (chave_hash, hits) |
| `nfe_xmls` | NF-e importadas (chave, valores, ICMS, IPI) |
| `nfe_itens` | Itens das NF-e (NCM, CFOP, CST, valores) |
| `nfe_cruzamento` | Resultados do cruzamento XML x SPED |
| `finding_resolutions` | Resolucao de achados (status, justificativa) |

**Migracoes:** 7 versoes incrementais gerenciadas via `PRAGMA user_version`.

### MySQL — DCTF_WEB (externo)

Conexao com banco MySQL para consulta de dados de clientes, regime tributario e beneficios ativos. Configurado via `.env` (`MYSQL_HOST`, `MYSQL_DATABASE=DCTF_WEB`).

---

## Motor de Regras

### `rules.yaml` — 177 regras implementadas

Arquivo YAML com todas as regras de validacao, organizadas por bloco:

```yaml
version: '1.0'
tolerance: 0.02      # Tolerancia global (2 centavos)

formato:             # Regras de formato (CNPJ, CPF, datas)
intra_registro:      # Regras dentro do registro (C100, C170)
cruzamento:          # Cruzamentos entre blocos
recalculo:           # Recalculos tributarios
cst:                 # CST ICMS + isencoes
semantica_fiscal:    # CST x CFOP, monofasicos
aliquotas:           # Aliquotas interestaduais/internas
beneficios:          # Beneficios fiscais
difal:               # DIFAL + FCP
```

Cada regra contém:

| Campo | Descricao |
|---|---|
| `id` | Identificador unico (ex: FMT_CNPJ, CST_001) |
| `register` | Registro SPED alvo (ex: C100, C170, *) |
| `fields` | Campos validados |
| `error_type` | Tipo de erro gerado |
| `severity` | error, warning, info |
| `description` | Descricao em portugues |
| `condition` | Condicao logica da regra |
| `module` | Modulo Python que implementa |
| `legislation` | Base legal (quando aplicavel) |
| `vigencia_de` / `vigencia_ate` | Periodo de vigencia da regra |
| `certeza` | objetivo, provavel, indicio |
| `impacto` | critico, relevante, informativo |

### Tipos de erro implementados (85+)

```
FORMATO_INVALIDO, INVALID_DATE, DATE_OUT_OF_PERIOD, MISSING_REQUIRED,
WRONG_TYPE, WRONG_SIZE, INVALID_VALUE, MISSING_CONDITIONAL, INCONSISTENCY,
SOMA_DIVERGENTE, CALCULO_DIVERGENTE, REF_INEXISTENTE, CRUZAMENTO_DIVERGENTE,
CONTAGEM_DIVERGENTE, CST_INVALIDO, ISENCAO_INCONSISTENTE, CST_ALIQ_ZERO_FORTE,
CST_CFOP_INCOMPATIVEL, MONOFASICO_ALIQ_INVALIDA, ALIQ_INTERESTADUAL_INVALIDA,
C190_DIVERGE_C170, BENEFICIO_DEBITO_NAO_INTEGRAL, AJUSTE_SEM_LASTRO_DOCUMENTAL,
DIFAL_FALTANTE_CONSUMO_FINAL, ALIQ_ICMS_AUSENTE, CST_HIPOTESE, ...
```

---

## Pipeline de Validacao

O pipeline executa em **4 estagios** com progresso em tempo real via SSE:

### Estagio 1: Estrutural
- Validacao campo-a-campo (tipo, tamanho, obrigatoriedade)
- Validacao de formatos (CNPJ, CPF, datas, CFOP)
- Regras intra-registro (C100, C170, C190, E110)

### Estagio 2: Cruzamento
- Cruzamento C100 x C170 x C190 (totais vs itens)
- Referencias 0150 (participantes) e 0200 (produtos)
- Recalculo ICMS, ICMS-ST, IPI, PIS/COFINS
- CST ICMS + isencoes + Bloco H
- Analise semantica (CST x CFOP, monofasicos)
- Auditoria fiscal (CFOP x UF, parametrizacao)
- NCM, aliquotas, C190, Bloco D
- Beneficios fiscais, base de calculo, DIFAL
- Devolucoes, IPI, destinatario
- Hipoteses inteligentes de correcao

### Estagio 3: Enriquecimento
- Mensagens amigaveis em portugues (contadores, nao programadores)
- Busca de base legal na documentacao indexada
- Agrupamento por (error_type, register, field_name) para evitar buscas redundantes
- Classificacao de auto-corrigibilidade

### Estagio 4: Conclusao
- Persistencia final + audit log
- Limpeza do pipeline

### Deduplicacao inteligente

Tres estrategias para evitar erros duplicados:
1. **Hipoteses supersede genericos** — ALIQ_ICMS_AUSENTE substitui CST_ALIQ_ZERO_FORTE
2. **Mesma causa raiz** — CST_ALIQ_ZERO_MODERADO suprime BENEFICIO_NAO_VINCULADO
3. **Mesmo campo** — Manter o mais acionavel (com expected_value)

---

## Validadores

### Modulos (37 validadores)

| Validador | Regras | Descricao |
|---|---|---|
| `format_validator` | 9 | CNPJ, CPF, datas, CEP, CFOP, NCM |
| `intra_register_validator` | 10 | C100, C170, C190, E110 (calculos internos) |
| `cross_block_validator` | 7 | Bloco 0 vs C/D/E (referencias, contagens) |
| `tax_recalc` | 8 | Recalculo ICMS, IPI, PIS/COFINS |
| `cst_validator` | 6 | CST ICMS + reducoes + isencoes |
| `fiscal_semantics` | 13 | CST x CFOP, monofasicos, aliquota zero |
| `aliquota_validator` | 4 | Interestaduais, internas, media indevida |
| `c190_validator` | 2 | Consolidacao C190 vs C170 |
| `base_calculo_validator` | 6 | BASE_001 a BASE_006 |
| `difal_validator` | 8 | DIFAL + FCP (EC 87/2015, LC 190/2022) |
| `beneficio_audit_validator` | 50+ | Auditoria completa de beneficios fiscais |
| `beneficio_validator` | 3 | BENE_001 a BENE_003 |
| `ipi_validator` | 3 | Reflexo BC, CST monetario |
| `destinatario_validator` | 3 | IE, UF, CEP |
| `devolucao_validator` | 3 | DEV_001 a DEV_003 |
| `cfop_validator` | 4 | Interestadual vs interno |
| `ncm_validator` | 2 | Tratamento tributario, generico |
| `parametrizacao_validator` | 1 | Erros sistematicos |
| `pendentes_validator` | 4 | Beneficio nao vinculado, anomalias |
| `correction_hypothesis` | 1 | Hipotese de aliquota ICMS |
| `cst_hypothesis` | 1 | Hipotese de CST |
| `audit_rules` | 15 | Governanca: remessas, inventario, creditos |
| `bloco_d_validator` | 3 | Servicos de transporte |
| `bloco_c_servicos_validator` | 2 | Servicos no Bloco C |
| `bloco_k_validator` | 5 | Producao e inventario |
| `simples_validator` | 10 | Simples Nacional |
| `st_validator` | 4 | Substituicao tributaria + MVA |
| `pis_cofins_validator` | 3 | PIS/COFINS por regime |
| `apuracao_validator` | 3 | Apuracao de impostos |
| `retificador_validator` | 2 | Arquivos retificadores |

### Contexto de Validacao (`ValidationContext`)

Construido automaticamente antes do pipeline:

```python
@dataclass
class ValidationContext:
    file_id: int
    regime: TaxRegime          # NORMAL, SIMPLES_NACIONAL, MEI
    uf_contribuinte: str       # Ex: "ES"
    periodo_ini: date          # Inicio do periodo
    periodo_fim: date          # Fim do periodo
    ind_perfil: str            # Perfil do contribuinte
    cod_ver: str               # Versao do leiaute
    cnpj: str
    available_tables: list     # Tabelas externas disponiveis
    participantes: dict        # Cache 0150 (cod_part -> dados)
    produtos: dict             # Cache 0200 (cod_item -> dados)
    naturezas: dict            # Cache nat. operacao
    active_rules: list         # Regras vigentes para o periodo
```

---

## Servicos

### Pipeline (`services/pipeline.py`)
Orquestrador com 4 estagios, progresso em tempo real via `PipelineProgress`, e cleanup apos SSE.

### Auto-Correcao (`services/auto_correction_service.py`)
- **Deterministicas (seguras):** CALCULO_DIVERGENTE, SOMA_DIVERGENTE, CONTAGEM_DIVERGENTE
- **Proibidas (requerem humano):** CST_ICMS, CFOP, ALIQ_ICMS, COD_AJ_APUR
- Campos sensíveis **nunca** sao auto-corrigidos

### Correcoes (`services/correction_service.py`)
- Aplicacao com audit trail completo
- Justificativa obrigatoria
- Tipos: `auto`, `assisted`, `manual`

### Busca Hibrida (`searcher.py`)
- **FTS5** — Busca exata (unicode61, remove diacritics)
- **Vetorial** — Embeddings all-MiniLM-L6-v2 (384 dims) + cosine similarity
- **Fusao** — Reciprocal Rank Fusion (k=60)

### Contexto (`services/context_builder.py`)
- Deteccao automatica de regime tributario (Normal, Simples, MEI)
- Cache de participantes (0150), produtos (0200), naturezas
- Filtragem de regras por vigencia

### Tabelas de Referencia (`services/reference_loader.py`)
Carregamento lazy de:
- Aliquotas internas por UF
- FCP por UF
- Municipios IBGE
- NCM/TIPI categorias
- MVA por NCM/UF
- Codigos de ajuste por UF
- Sublimites e anexos do Simples Nacional

---

## Fontes de Dados e JSONs de Referencia

### `data/JSON/` — Tabelas fiscais estruturadas

| Arquivo | Linhas | Conteudo |
|---|---|---|
| `Tabela_Fiscal_Complementar_v6.json` | 25.073 | CFOP + aliquotas internas/interestaduais + FCP por UF + bases legais |
| `Tabela_CST_Vigente.json` | ~2.000 | CST ICMS/IPI/PIS/COFINS com efeitos e regimes validos |
| `Tabela_DIFAL_Vigente.json` | ~500 | Aliquotas DIFAL por UF |
| `Tabela_NCM_Vigente_*.json` | ~13.000 | Classificacao NCM com tratamento tributario |
| `COMPETE_*.json` | varios | Beneficios COMPETE-ES (atacadista, varejista, graficas, papelao) |
| `INVEST_ES_*.json` | varios | Beneficios INVEST-ES (importacao, industria) |
| `FUNDAP.json` | ~200 | Beneficio FUNDAP |
| `SUBSTITUICAO_TRIBUTARIA_ES.json` | ~1.000 | ST no Espirito Santo |

### `data/reference/` — Tabelas YAML parametrizaveis

| Arquivo | Descricao |
|---|---|
| `aliquotas_internas_uf.yaml` | Aliquota geral de ICMS por estado |
| `fcp_por_uf.yaml` | FCP (Fundo de Combate a Pobreza) por estado |
| `codigos_ajuste_uf.yaml` | Tabela 5.1.1 por UF |
| `csosn_tabela_b.yaml` | Tabela B do CSOSN (Simples Nacional) |
| `cst_pis_cofins_sn.yaml` | CST PIS/COFINS para Simples |
| `ibge_municipios.yaml` | Codigos IBGE de municipios |
| `mva_por_ncm_uf.yaml` | MVA (Margem de Valor Agregado) por NCM e UF |
| `ncm_tipi_categorias.yaml` | Categorias NCM/TIPI |
| `sn_anexos_aliquotas.yaml` | Aliquotas por faixa do Simples Nacional |
| `sn_sublimites_uf.yaml` | Sublimites ICMS/ISS do Simples por UF |

### Documentacao Indexada

- **Guia Pratico EFD** — Convertido de PDF para Markdown e indexado
- **Legislacao** — Normas, ajustes SINIEF, convênios ICMS
- Busca via FTS5 + embeddings semanticos

---

## Cruzamento NF-e XML x SPED

### Servico (`services/xml_service.py`)

**17 regras de cruzamento (XML001-XML017):**

| Regra | Descricao |
|---|---|
| XML001-003 | Presenca/ausencia de NF-e no SPED |
| XML004-006 | Divergencia de totais (VL_DOC, VL_ICMS, VL_IPI) |
| XML007-011 | Item a item (CFOP, CST, NCM, aliquotas, valores) |
| XML012-014 | Participante (CNPJ, IE inconsistente) |
| XML015-017 | Datas, chave NF-e, serie |

### Fluxo:

1. Upload batch de XMLs vinculados ao SPED
2. Parsing com namespace `http://www.portalfiscal.inf.br/nfe`
3. Normalizacao (CNPJ, CFOP, CST, NCM, datas)
4. Cruzamento com registros C100/C170/0200
5. Resultados salvos em `nfe_cruzamento`
6. Modo de periodo: `validar`, `importar_todos`, `pular_fora`

### Endpoints:
- `POST /api/files/{id}/xml/upload` — Upload batch
- `GET /api/files/{id}/xml` — Listar XMLs importados
- `POST /api/files/{id}/xml/cross` — Executar cruzamento
- `GET /api/files/{id}/xml/results` — Resultados

---

## Inteligencia Artificial

### OpenAI GPT-4o-mini (`services/ai_service.py`)

**Funcao:** Gerar explicacoes contextualizadas de erros para contadores (nao programadores).

**Arquitetura de cache incremental:**

```
1. Busca no cache (ai_error_cache) por chave_hash
2. Se encontrar → retorna texto cacheado, incrementa hits
3. Se nao encontrar → chama OpenAI → salva no cache → retorna
```

**Chave do cache:** SHA256 de `{rule_id}|{error_type}|{regime}|{uf}|{beneficio}|{ind_oper}|{campo}`

**Prompt do sistema (persona):**
```
Voce e um assistente fiscal especializado em SPED EFD ICMS/IPI.
- Linguagem acessivel ao contador
- Cite base legal (LC 87/1996, Guia Pratico, RICMS)
- Maximo 3 paragrafos: O QUE, POR QUE, COMO
- Sugestao nao vinculante
```

**Modelo:** `gpt-4o-mini` (rapido, baixo custo)
**Temperatura:** 0.3 (pouca criatividade, alta precisao)
**Max tokens:** 500

**Endpoints:**
- `POST /api/ai/explain` — Explicacao de erro
- `GET /api/ai/cache/stats` — Estatisticas do cache
- `DELETE /api/ai/cache` — Limpar cache

**Seguranca IA:**
- IA **nunca cria regras** — apenas explica erros ja detectados
- Respostas marcadas como "sugestao nao vinculante"
- Fallback para mensagem tecnica se API key ausente

### Embeddings Semanticos (`embeddings.py`)

- **Modelo:** `all-MiniLM-L6-v2` (Sentence-Transformers)
- **Dimensao:** 384 (float32)
- **Uso:** Busca semantica na documentacao + enriquecimento de erros
- **Pre-carregamento:** Thread daemon no startup da API

---

## API REST (FastAPI)

### Endpoints principais

| Metodo | Rota | Descricao |
|---|---|---|
| `GET` | `/api/health` | Health check |
| **Arquivos** | | |
| `POST` | `/api/files/upload` | Upload SPED (max 100 MB, streaming) |
| `GET` | `/api/files` | Listar todos os arquivos |
| `GET` | `/api/files/{id}` | Detalhes de um arquivo |
| `DELETE` | `/api/files/{id}` | Remover arquivo |
| `DELETE` | `/api/files/{id}/audit` | Limpar auditoria |
| **Validacao** | | |
| `POST` | `/api/files/{id}/validate` | Validacao sincrona |
| `GET` | `/api/files/{id}/validate/stream` | Validacao com SSE (progresso real-time) |
| `GET` | `/api/files/{id}/errors` | Erros com filtros e paginacao |
| `GET` | `/api/files/{id}/summary` | Resumo por tipo/severidade |
| `DELETE` | `/api/files/{id}/errors/{eid}` | Ignorar erro individual |
| **Registros** | | |
| `GET` | `/api/files/{id}/records` | Listar registros |
| `PUT` | `/api/files/{id}/records/{rid}` | Corrigir campo (com justificativa) |
| **Relatorios** | | |
| `GET` | `/api/files/{id}/report` | Relatorio Markdown |
| `GET` | `/api/files/{id}/report/structured` | Relatorio JSON estruturado |
| `GET` | `/api/files/{id}/download` | Download SPED corrigido |
| **Regras** | | |
| `GET` | `/api/rules` | Listar regras |
| `POST` | `/api/rules/generate` | Gerar regra via IA |
| `POST` | `/api/rules/implement` | Implementar regra |
| **Busca** | | |
| `GET` | `/api/search` | Busca hibrida na documentacao |
| **XML** | | |
| `POST` | `/api/files/{id}/xml/upload` | Upload NF-e XMLs |
| `POST` | `/api/files/{id}/xml/cross` | Cruzamento XML x SPED |
| **IA** | | |
| `POST` | `/api/ai/explain` | Explicacao de erro |
| `GET` | `/api/ai/cache/stats` | Stats do cache |
| **Escopo** | | |
| `GET` | `/api/files/{id}/audit-scope` | Dashboard de cobertura |

### SSE (Server-Sent Events)

O endpoint `/validate/stream` emite eventos em tempo real:

```
event: progress    → { stage, stage_progress, detail, total_errors }
event: stage_complete → { stage, errors_found }
event: done        → { total_errors, status, errors_by_stage }
event: error       → { error }
```

### Autenticacao

- Header `X-API-Key` em todas as rotas (exceto `/api/health`)
- **Modo dev:** Se `API_KEY` nao configurada, aceita qualquer valor
- **Modo prod:** Match exato obrigatorio

---

## Frontend (React)

### Paginas

| Rota | Pagina | Descricao |
|---|---|---|
| `/` | UploadPage | Upload de SPED + inicio de validacao |
| `/files` | FilesPage | Lista de arquivos processados |
| `/files/:id` | FileDetailPage | Erros, correcoes, relatorio, escopo |
| `/files/:id/cross` | CrossValidationPage | Cruzamento XML |
| `/rules` | RulesPage | Gerenciamento de regras |

### Componentes

- **Layout** — Shell com navegacao
- **ErrorChart** — Grafico de erros por tipo (Recharts)
- **AuditScopePanel** — Painel de cobertura da auditoria
- **FieldEditor** — Edicao inline de campos SPED
- **RecordDetail** — Visualizacao de registro expandido
- **SuggestionPanel** — Sugestoes de correcao
- **CorrectionApprovalPanel** — Workflow de aprovacao

### Tipos TypeScript (`types/sped.ts`)

```typescript
FileInfo, RecordInfo, ValidationError, SearchResult,
ErrorSummary, ValidationResponse, RuleSummary, GeneratedRule,
CrossValidationItem, AuditScope, CorrectionSuggestion,
PipelineEvent, StructuredReport, LegalBasis
```

---

## CLI

```bash
# Converter documentacao (PDF/DOCX/TXT -> Markdown)
python cli.py convert --force

# Indexar Markdown no SQLite (FTS5 + embeddings)
python cli.py index --db db/sped.db

# Validar arquivo SPED com relatorio
python cli.py validate arquivo_sped.txt --output relatorio.md

# Buscar na documentacao
python cli.py search "substituicao tributaria" --category legislacao --top-k 5

# Verificar regras implementadas
python -m src.rules --check

# Listar regras pendentes
python -m src.rules --pending

# Regras vigentes para periodo
python -m src.rules --vigentes-para 2026-03
```

---

## Testes

**70+ arquivos** de teste com pytest:

```bash
# Rodar todos os testes
pytest

# Com cobertura
pytest --cov=src --cov-report=html

# Testes especificos
pytest tests/test_aliquota_validator.py -v
pytest tests/test_api_validation.py -v
pytest tests/test_beneficio_audit.py -v
```

### Categorias de teste:

| Categoria | Arquivos | Cobertura |
|---|---|---|
| Validadores | 25+ | Cada validador tem testes dedicados |
| API | 5+ | Endpoints, autenticacao, rate limiting |
| Core | 5+ | Parser, converter, indexer, searcher |
| Servicos | 5+ | Auto-correcao, correcao, contexto |
| Integracao | 3+ | E2E, infraestrutura |
| Governanca | 3+ | Controle de correcao |
| Especificos | 5+ | Bloco K, Simples, retificadores, XML |

---

## Configuracao e Ambiente

### Variaveis de ambiente (`.env`)

```bash
# API
API_KEY=sua-chave-minimo-32-chars     # Autenticacao da API

# IA
OPENAI_API_KEY=sk-proj-...           # OpenAI para explicacoes de erros

# MySQL (DCTF_WEB - dados de clientes)
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=***
MYSQL_DATABASE=DCTF_WEB
```

### `config.py` — Parametros centrais

```python
ENGINE_VERSION = "3.0.0"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # 384 dims
EMBEDDING_BATCH_SIZE = 64
SEARCH_TOP_K = 5
RRF_K = 60                            # Reciprocal Rank Fusion
MAX_UPLOAD_MB = 50
```

---

## Como Rodar

### Pre-requisitos

- Python 3.10+
- Node.js 18+ (para frontend)
- MySQL (opcional, para DCTF_WEB)

### Backend

```bash
# 1. Criar ambiente virtual
python -m venv .venv
source .venv/bin/activate   # Linux/Mac
.venv\Scripts\activate      # Windows

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Configurar .env
cp .env.example .env
# Editar .env com suas chaves

# 4. Converter e indexar documentacao (primeira vez)
python cli.py convert
python cli.py index

# 5. Iniciar API
uvicorn api.main:app --host 0.0.0.0 --port 8021 --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev    # Vite dev server em :5175
```

### Atalho (Windows)

```bash
# start.bat (se disponivel)
start.bat
```

---

## Docker

```yaml
# docker-compose.yml
services:
  api:
    build: .
    ports: ["8021:8021"]
    volumes:
      - db-data:/app/db
      - ./src:/app/src
      - ./api:/app/api
    command: uvicorn api.main:app --host 0.0.0.0 --port 8021 --reload

  frontend:
    build:
      context: ./frontend
      dockerfile: ../Dockerfile.frontend
    ports: ["5175:5175"]
    environment:
      - VITE_API_URL=http://api:8021
    depends_on: [api]

volumes:
  db-data:
```

```bash
docker compose up -d --build
```

---

## Seguranca

### Autenticacao
- API Key via header `X-API-Key` (min 32 chars recomendado)
- Modo dev automatico se `API_KEY` nao configurada

### Protecao de dados
- Queries SQL parametrizadas (sem concatenacao)
- Upload com limite de 100 MB e leitura streaming
- Campos sensíveis (CST, CFOP, ALIQ_ICMS) **nunca** auto-corrigidos
- Audit trail completo de todas as correcoes

### IA
- OpenAI API Key armazenada apenas em `.env` (nao versionado)
- Cache local evita chamadas desnecessarias
- Respostas marcadas como "sugestao nao vinculante"
- Temperatura 0.3 (baixa alucinacao)

### `.gitignore`
- `.env`, `db/*.db`, `__pycache__/`, `node_modules/`, `.venv/`

---

## Licenca

Projeto interno — Central Contabil.

---

*SPED EFD Validator v3.0.0 — Motor de regras com 177 regras implementadas, 37 validadores, busca hibrida semantica e IA.*
