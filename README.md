# SPED EFD - Sistema de Conversao, Validacao e Busca na Documentacao

Sistema local com API REST + Frontend React para converter documentacao fiscal brasileira (PDFs, DOCX, TXT) em texto estruturado, indexar em banco de dados com busca hibrida (exata + semantica), e validar arquivos SPED EFD detectando erros com sugestoes automaticas de correcao baseadas na documentacao oficial (Guia Pratico EFD v3.2.2).

---

## Visao Geral

O SPED (Sistema Publico de Escrituracao Digital) EFD (Escrituracao Fiscal Digital) e um arquivo texto com registros fiscais (ICMS/IPI/PIS/COFINS) no formato pipe-delimited. Erros de lancamento sao comuns e a correcao exige consultar manuais extensos da Receita Federal.

Este sistema resolve isso automatizando:

1. **Conversao** de PDFs/DOCX/TXT da documentacao oficial para Markdown estruturado
2. **Indexacao** com Full-Text Search (FTS5) + embeddings vetoriais para busca semantica
3. **Validacao** em 22 camadas dos arquivos SPED (estrutural, semantica fiscal, monofasicos, auditoria de beneficios, aliquotas, C190, DIFAL/FCP, base de calculo, destinatario, parametrizacao, governanca, **Simples Nacional**) com 186 regras implementadas, governanca de correcoes (4 niveis: automatico/proposta/investigar/impossivel), materialidade financeira estimada e workflow de resolucao de apontamentos
4. **Busca automatica** da documentacao relevante para cada erro encontrado
5. **API REST** (FastAPI) com endpoints para upload, validacao, correcao e exportacao
6. **Frontend React** com interface para upload, visualizacao de erros e relatorios

---

## Como Executar

### Opcao 1: start.bat (Windows - recomendado)

Duplo clique em `start.bat` — inicia API + Frontend automaticamente.

### Opcao 2: Manual (PowerShell)

**Terminal 1 (API):**
```powershell
cd <diretorio-do-projeto>
.\.venv-win\Scripts\Activate.ps1
$env:PYTHONPATH = (Get-Location).Path
$env:API_KEY = "sua-chave-aqui-minimo-32-caracteres"
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

**Terminal 2 (Frontend):**
```powershell
cd <diretorio-do-projeto>\frontend
npm run dev
```

**Acessar:**
- App: http://localhost:3000
- API Docs: http://localhost:8000/docs

### Configuracao da API Key

A API exige autenticacao via header `X-API-Key` em todos os endpoints (exceto `/api/health`).

1. Copie `.env.example` para `.env` e defina uma chave com no minimo 32 caracteres:
   ```
   API_KEY=sua-chave-secreta-com-pelo-menos-32-caracteres
   ```

2. Exporte a variavel de ambiente antes de iniciar a API:
   - **Linux/macOS:** `export API_KEY="sua-chave-aqui"`
   - **PowerShell:** `$env:API_KEY = "sua-chave-aqui"`
   - **Docker:** ja configurado via `.env`

3. Envie a chave em todas as requisicoes:
   ```bash
   curl -H "X-API-Key: sua-chave-aqui" http://localhost:8000/api/files
   ```

**Modo desenvolvimento:** Se `API_KEY` nao estiver definida, a API aceita qualquer chave (ou nenhuma). Nao use em producao.

### Git Push

Execute `git-push.bat` no Windows — pede a mensagem do commit, faz rebase na main e push.

---

## Arquitetura

```
                        PIPELINE DE INGESTAO
                        ====================

  SPED2.0/guia pratico/     SPED2.0/legislaacao/
  (PDFs, TXT, DOCX)         (PDFs, DOCX, TXT)
          |                          |
          v                          v
    +-----------+              +-----------+
    | converter |              | converter |
    | (PDF/DOCX |              | (PDF/DOCX |
    |  /TXT->MD)|              |  /TXT->MD)|
    +-----------+              +-----------+
          |                          |
          v                          v
   data/markdown/guia/       data/markdown/legislacao/
   (4 arquivos .md)          (78 arquivos .md)
          |                          |
          +----------+---------------+
                     |
                     v
              +-------------+
              |   indexer    |
              | (chunking + |
              |  embeddings)|
              +-------------+
                     |
                     v
            +------------------+
            |    SQLite DB     |
            |  (FTS5 + BLOB)  |
            |  53.784 chunks  |
            |  657 reg fields |
            +------------------+


                    PIPELINE DE VALIDACAO
                    =====================

          arquivo_sped.txt
          (pipe-delimited)
                |
                v
          +----------+
          |  parser  |
          | (latin-1)|
          +----------+
                |
                v
         +------------+
         | validator  |
         | (campo a   |
         |  campo)    |
         +------------+
                |
                v
          erros encontrados
                |
                v
         +------------+         +------------------+
         |  searcher  | ------> |    SQLite DB     |
         | (FTS5 +    |         | (busca hibrida)  |
         |  semantico)|         +------------------+
         +------------+
                |
                v
        relatorio.md
        (erros + documentacao + sugestoes)
```

---

## Estrutura do Projeto

```
SPED/
|-- README.md                       # Este arquivo
|-- rules.yaml                      # Catalogo de 186 regras com corrigivel obrigatorio (automatico|proposta|investigar|impossivel)
|-- pyproject.toml                  # Dependencias e metadados (v0.1.0)
|-- config.py                       # Caminhos, modelo embedding, parametros
|-- start.bat                       # Inicia API + Frontend (Windows)
|-- start-api.bat                   # Inicia apenas a API (porta 8000)
|-- start-frontend.bat              # Inicia apenas o Frontend (porta 3000)
|-- git-push.bat                    # Commit + rebase + push automatizado
|-- cli.py                          # Interface de linha de comando (argparse)
|
|-- src/
|   |-- __init__.py
|   |-- models.py                   # 5 dataclasses centrais
|   |-- parser.py                   # Parser de arquivos SPED EFD
|   |-- converter.py                # PDF/DOCX/TXT -> Markdown
|   |-- indexer.py                  # Markdown -> SQLite (FTS5 + embeddings)
|   |-- embeddings.py               # Wrapper do modelo sentence-transformers
|   |-- validator.py                # Validacao campo a campo
|   |-- searcher.py                 # Busca hibrida (FTS5 + vetorial + RRF)
|   |-- rules.py                    # Loader/CLI do rules.yaml (--check valida corrigivel, --pending, --block)
|   |-- validators/
|   |   |-- __init__.py
|   |   |-- format_validator.py     # CNPJ, CPF, datas, CEP, CFOP, NCM, chave NFe
|   |   |-- intra_register_validator.py  # Regras C100, C170, C190, E110
|   |   |-- cross_block_validator.py     # Cruzamento 0 vs C/D, C vs E, bloco 9
|   |   |-- tax_recalc.py               # Recalculo ICMS, ICMS-ST, IPI, PIS/COFINS, E110
|   |   |-- cst_validator.py            # CSTs ICMS, isencoes, Bloco H estoque
|   |   |-- fiscal_semantics.py         # Semantica fiscal: CST x CFOP, aliquota zero, monofasicos
|   |   |-- aliquota_validator.py       # Aliquotas interestaduais, internas, media indevida
|   |   |-- beneficio_audit_validator.py # 50 regras de auditoria de beneficios fiscais
|   |   |-- beneficio_validator.py       # Beneficio contaminando aliquota/DIFAL/base
|   |   |-- c190_validator.py            # C190 vs C170, combinacoes incompativeis
|   |   |-- difal_validator.py           # DIFAL/FCP: faltante, indevido, base, UF, perfil
|   |   |-- base_calculo_validator.py    # Recalculo BC, frete CIF/FOB, despesas acessorias
|   |   |-- ipi_validator.py             # IPI reflexo BC, recalculo, CST vs monetario
|   |   |-- destinatario_validator.py    # IE inconsistente, UF vs IE, UF vs CEP
|   |   |-- cfop_validator.py            # CFOP interestadual/interno vs UF
|   |   |-- st_validator.py              # ST vs DIFAL, ST sem reflexo apuracao
|   |   |-- devolucao_validator.py       # Devolucao: espelhamento, DIFAL, aliquota historica
|   |   |-- parametrizacao_validator.py  # Erros sistematicos por item/UF/data
|   |   |-- ncm_validator.py             # NCM tributacao incompativel, generico
|   |   |-- bloco_c_servicos_validator.py # Servicos no Bloco C
|   |   |-- bloco_d_validator.py         # Bloco D: transporte
|   |   |-- pendentes_validator.py       # Regras pendentes de contexto externo
|   |   |-- audit_rules.py              # Regras de auditoria gerais
|   |   |-- simples_validator.py          # Simples Nacional: CSOSN, CST PIS/COFINS, credito ICMS (11 regras)
|   |   |-- retificador_validator.py     # Validacoes de retificacao
|   |   |-- helpers.py                   # Funcoes auxiliares dos validadores
|   |   |-- tolerance.py                 # Constantes de tolerancia de calculo
|   |   |-- correction_hypothesis.py     # Hipoteses de correcao automatica
|   |   |-- cst_hypothesis.py            # Hipoteses de correcao de CST
|   |-- services/
|   |   |-- reference_loader.py          # Carrega tabelas YAML de referencia (lazy loading)
|   |   |-- __init__.py
|   |   |-- database.py                 # Schema SQLite de auditoria (8 tabelas, 10 migracoes)
|   |   |-- file_service.py             # Upload, hash, parse, metadados, CRUD, clear_audit
|   |   |-- validation_service.py       # Orquestrador de validacao (7 camadas, 4 severidades)
|   |   |-- pipeline.py                 # Pipeline estagiado com SSE (progresso em tempo real)
|   |   |-- error_messages.py           # 30+ tipos de erro com mensagens amigaveis e orientacao
|   |   |-- auto_correction_service.py  # Correcoes automaticas deterministicas
|   |   |-- correction_service.py       # Aplicar/desfazer correcoes com governanca (automatico/proposta/investigar/impossivel)
|   |   |-- export_service.py           # Exportar SPED, relatorio MD/CSV/JSON
|
|-- api/
|   |-- __init__.py
|   |-- main.py                         # FastAPI app + CORS + routers
|   |-- deps.py                         # Dependency injection (banco por request)
|   |-- schemas/
|   |   |-- models.py                   # 10 Pydantic models (request/response)
|   |-- routers/
|   |   |-- files.py                    # Upload, listar, detalhe, deletar
|   |   |-- records.py                  # Listar registros, detalhe, corrigir
|   |   |-- validation.py              # Validar, erros, resumo
|   |   |-- report.py                   # Relatorio MD/CSV/JSON, download SPED
|   |   |-- search.py                   # Busca na documentacao
|   |   |-- rules.py                    # Gerar, listar e implementar regras via API
|
|-- frontend/
|   |-- package.json                    # React 18 + Vite + TailwindCSS + TypeScript
|   |-- src/
|   |   |-- main.tsx                    # Ponto de entrada React
|   |   |-- api/
|   |   |   |-- client.ts              # Cliente HTTP para a API
|   |   |-- components/
|   |   |   |-- Layout.tsx             # Layout principal da aplicacao
|   |   |-- pages/
|   |   |   |-- UploadPage.tsx         # Upload de arquivos SPED
|   |   |   |-- FilesPage.tsx          # Listagem de arquivos processados
|   |   |   |-- FileDetailPage.tsx     # Detalhe: erros, resumo, relatorio
|   |   |   |-- RulesPage.tsx          # Criador de regras: texto livre -> regra estruturada -> YAML
|   |   |-- types/                     # Tipos TypeScript
|
|-- db/
|   |-- sped.db                     # Banco SQLite (126 MB, criado em runtime)
|   |-- audit.db                    # Banco de auditoria (arquivos, erros, correcoes)
|
|-- data/
|   |-- reference/                  # Tabelas YAML de referencia fiscal
|   |   |-- aliquotas_internas_uf.yaml    # Aliquota interna padrao por UF (CONFAZ)
|   |   |-- fcp_por_uf.yaml               # Fundo de Combate a Pobreza por UF
|   |   |-- ibge_municipios.yaml           # Codigos IBGE de municipios
|   |   |-- ncm_tipi_categorias.yaml       # NCM: normal/isento/monofasico/NT
|   |   |-- codigos_ajuste_uf.yaml         # Tabela 5.1.1 - codigos de ajuste
|   |   |-- mva_por_ncm_uf.yaml            # MVA por NCM para ST
|   |   |-- csosn_tabela_b.yaml            # CSOSN Tabela B - Simples Nacional
|   |   |-- cst_pis_cofins_sn.yaml         # CST PIS/COFINS validos/proibidos para SN
|   |   |-- sn_anexos_aliquotas.yaml       # Anexos I-V com aliquotas por faixa (LC 155/2016)
|   |   |-- sn_sublimites_uf.yaml          # Sublimites ICMS/ISS por UF
|   |   |-- vigencias/                     # Tabelas versionadas por periodo
|   |-- markdown/
|   |   |-- guia/                   # Guia Pratico EFD v3.2.2 + cabecalhos + exemplos
|   |   |-- legislacao/             # 78 arquivos convertidos da legislacao
|   |-- sped_files/                 # Arquivos SPED EFD para validar
|
|-- tests/
|   |-- __init__.py
|   |-- conftest.py                 # Fixtures compartilhadas (db em memoria, records, field_defs)
|   |-- test_models.py              # Testes dos dataclasses
|   |-- test_parser.py              # Testes do parser (parse, encoding, hierarquia, malformed)
|   |-- test_validator.py           # Testes do validador (tipo, tamanho, required, valid_values)
|   |-- test_converter.py           # Testes do conversor (TXT, PDF mock, DOCX mock, tabelas)
|   |-- test_indexer.py             # Testes do indexador (chunking, fields, FTS, index_all)
|   |-- test_searcher.py            # Testes do buscador (FTS, semantico, RRF, search_for_error)
|   |-- test_embeddings.py          # Testes de embeddings (blob roundtrip, mock model)
|   |-- test_fiscal_semantics.py    # Testes semantica fiscal: aliquota zero, CST x CFOP, monofasicos (73 testes)
|   |-- fixtures/
|   |   |-- sped_minimal.txt        # SPED minimo (0000 + blocos vazios + 9999)
|   |   |-- sped_valid.txt          # SPED completo com NFs, itens, apuracao (57 registros)
|   |   |-- sped_errors.txt         # SPED com erros conhecidos (tipo, valor, malformed)
```

**Repositorio remoto:** https://github.com/Bruno-1990/SPED-Validator.git

---

## Componentes Detalhados

### 1. Modelos de Dados (`src/models.py`)

5 dataclasses que representam as entidades do sistema:

| Classe | Descricao | Campos Principais |
|--------|-----------|-------------------|
| `SpedRecord` | Uma linha do arquivo SPED | `line_number`, `register` (ex: C100), `fields` (lista), `raw_line` |
| `RegisterField` | Definicao de campo extraida da documentacao | `register`, `field_no`, `field_name`, `field_type` (C/N), `field_size`, `required` (O/OC/N), `valid_values` |
| `ValidationError` | Erro encontrado na validacao | `line_number`, `register`, `field_no`, `field_name`, `value`, `error_type`, `message` |
| `Chunk` | Trecho de documentacao indexado | `source_file`, `category` (guia/legislacao), `register`, `field_name`, `heading`, `content`, `embedding` (384-dim) |
| `SearchResult` | Resultado de busca | `chunk`, `score` (0-1), `source` (fts/semantic/hybrid) |

### 2. Parser SPED (`src/parser.py`)

Le arquivos SPED EFD no formato pipe-delimited da Receita Federal.

**Formato SPED:**
```
|0000|017|0|01012024|31012024|EMPRESA LTDA|12345678000190|ES|...|
|C100|0|1|FOR001|55|00|1|000000001|12345678|01012024|...|
|C170|1|ITEM001|Descricao|100|UN|10.00|1000.00|...|
|9999|500|
```

**Funcoes principais:**

| Funcao | Descricao |
|--------|-----------|
| `parse_sped_file(filepath)` | Le arquivo com fallback de encoding (latin-1 -> cp1252 -> utf-8) |
| `group_by_register(records)` | Agrupa registros por codigo (ex: todos C100 juntos) |
| `get_register_hierarchy(records)` | Identifica relacao pai-filho (C100 -> C170, C190) |

**Hierarquia de registros:**
- **Nivel 1** - Abertura/fechamento de bloco: `0001`, `0990`, `9999`
- **Nivel 2** - Registros pai (terminam em 00): `C100`, `D100`, `E100`
- **Nivel 3** - Registros filho: `C170`, `C190`, `D150`

### 3. Conversor (`src/converter.py`)

Converte documentos em 3 formatos para Markdown estruturado.

**Formatos suportados:**

| Formato | Biblioteca | Estrategia |
|---------|-----------|------------|
| `.pdf` | pdfplumber | Extracao de texto + tabelas, deteccao de headings por tamanho de fonte |
| `.docx` | python-docx (ou zipfile fallback) | Leitura de estilos de paragrafo + tabelas |
| `.txt` / sem extensao | stdlib | Leitura com deteccao de encoding |

**Deteccao de headings em PDFs:**
- Calcula o tamanho de fonte mais frequente nas primeiras 5 paginas (= corpo)
- Linhas com fonte > corpo + 1.5pt sao classificadas como heading
- Niveis de heading baseados no conteudo:
  - `##` para `BLOCO X`
  - `###` para `REGISTRO XXXX`
  - `####` para `CAMPOS`, `OBSERVACOES`, `REGRAS`

**Extracao de tabelas:**
- Identifica tabelas via `pdfplumber.find_tables()`
- Extrai texto fora das tabelas separadamente (evita duplicacao)
- Converte tabelas para formato Markdown com pipes

**Exemplo de saida:**
```markdown
## BLOCO C - DOCUMENTOS FISCAIS

### REGISTRO C100: NOTA FISCAL

Descricao: Este registro deve ser apresentado por todos os...

#### Campos do Registro C100

| No | Campo     | Descricao                     | Tipo | Tam | Obrig |
|----|-----------|-------------------------------|------|-----|-------|
| 01 | REG       | Texto fixo "C100"             | C    | 4   | O     |
| 02 | IND_OPER  | Indicador do tipo de operacao | C    | 1   | O     |
```

### 4. Indexador (`src/indexer.py`)

Transforma Markdown em chunks pesquisaveis no SQLite.

**Estrategia de chunking:**
1. Split por headings `##` e `###` (nivel de registro)
2. Dentro de cada secao:
   - 1 chunk para texto descritivo (se > 20 caracteres)
   - **1 chunk por campo** de cada tabela de definicao
3. Cada chunk recebe: `register`, `field_name`, `heading`, `content`, `category`

**Por que 1 chunk por campo?**
Quando o validador encontra erro no campo 3 do registro C100, a busca retorna exatamente a especificacao daquele campo, sem ruido de campos adjacentes.

**Extracao de register_fields:**
O indexador detecta tabelas que parecem definicoes de campos SPED (colunas como No, Campo, Descricao, Tipo, Tam) e extrai os metadados estruturados para a tabela `register_fields`.

**Geracoes de embeddings:**
- Modelo: `all-MiniLM-L6-v2` (384 dimensoes)
- Embeddings normalizados (cosine similarity = dot product)
- Batch size: 64
- Armazenados como BLOB no SQLite (1.536 bytes por chunk)

### 5. Embeddings (`src/embeddings.py`)

Wrapper fino sobre `sentence-transformers`.

| Funcao | Descricao |
|--------|-----------|
| `get_model()` | Lazy loading do modelo (carrega uma vez) |
| `embed_texts(texts, batch_size)` | Batch encoding -> array (N, 384) |
| `embed_single(text)` | Encoding de texto unico -> vetor (384,) |
| `embedding_to_blob(emb)` | numpy -> bytes (para SQLite) |
| `blob_to_embedding(blob)` | bytes -> numpy (do SQLite) |
| `info()` | Retorna nome do modelo, dimensao e notas |

**CLI:** `python -m src.embeddings --info` exibe modelo carregado em tempo de execucao.

**Notas:** Modelo multilingue leve (384 dims). Pode nao distinguir nuances fiscais como "credito presumido" vs "credito outorgado". Configurado em `config.py` com `EMBEDDING_MODEL_NOTES`.

### 6. Buscador (`src/searcher.py`)

Busca hibrida combinando FTS5 (exata) e similaridade vetorial (semantica).

**Fluxo de busca:**

```
Query: "indicador emitente C100"
         |
         +---> [FTS5] -----> resultados exatos (rank)
         |                        |
         +---> [Semantico] -> resultados por similaridade (score)
                                  |
                     +------------+
                     |
                     v
              [Reciprocal Rank Fusion]
              Score = sum(1 / (60 + rank))
                     |
                     v
              Top-K resultados mesclados
```

**Funcoes principais:**

| Funcao | Uso |
|--------|-----|
| `search(query, db_path, register, field_name, top_k)` | Busca geral na documentacao |
| `search_for_error(register, field_name, field_no, error_message, db_path)` | Busca especializada para erros de validacao - prioriza match exato por registro+campo |

**Otimizacao:** Quando o registro e conhecido (ex: C100), a busca vetorial filtra apenas chunks daquele registro (~50-200 vetores em vez de 53.784), levando microsegundos.

### 7. API REST (`api/`)

FastAPI com 5 routers e banco SQLite de auditoria.

**Endpoints:**

| Router | Endpoints | Funcao |
|--------|-----------|--------|
| `files.py` | `POST /api/files/upload`, `GET /api/files`, `GET /api/files/{id}`, `DELETE /api/files/{id}`, `DELETE /api/files/{id}/audit` | Upload, listagem, detalhe, exclusao e limpeza de audit |
| `validation.py` | `POST /api/files/{id}/validate`, `GET /api/files/{id}/errors`, `GET /api/files/{id}/summary`, `POST /api/findings/{id}/resolve` | Validacao, erros, resumo, workflow de resolucao |
| `records.py` | `GET /api/files/{id}/records`, `PATCH /api/records/{id}` | Listagem de registros, correcao de campos |
| `report.py` | `GET /api/files/{id}/report` | Relatorio em MD/CSV/JSON, download do SPED corrigido |
| `search.py` | `GET /api/search` | Busca na documentacao oficial |
| `rules.py` | `GET /api/rules`, `POST /api/rules/generate`, `POST /api/rules/implement` | Listar, gerar e implementar regras de validacao |

**Banco de auditoria (`db/audit.db`):**

| Tabela | Funcao |
|--------|--------|
| `sped_files` | Metadados dos arquivos (hash, periodo, empresa, CNPJ, status, regime_override) |
| `sped_records` | Registros parseados (line_number, register, fields_json) |
| `validation_errors` | Erros encontrados (tipo, severidade, mensagem, sugestao, materialidade R$) |
| `cross_validations` | Cruzamentos entre blocos (expected vs actual, diferenca) |
| `corrections` | Historico de correcoes aplicadas (old/new value, audit trail) |
| `audit_log` | Log de acoes (upload, validacao, correcao) |
| `finding_resolutions` | Workflow de resolucao (accepted/rejected/deferred/noted + justificativa) |
| `sped_file_versions` | Vinculos entre arquivos originais e retificadores |

**Configuracao:** SQLite com `check_same_thread=False` para compatibilidade com FastAPI (endpoints rodam em threads diferentes).

### 8. Frontend React (`frontend/`)

Interface web em React 18 + TypeScript + TailwindCSS + Vite.

| Pagina | Funcao |
|--------|--------|
| `UploadPage` | Upload de arquivos SPED via drag-and-drop |
| `FilesPage` | Listagem de arquivos processados com status |
| `FileDetailPage` | Detalhe: erros com filtros (severidade/registro/certeza), graficos, materialidade R$, editor inline, workflow de resolucao |
| `RulesPage` | Criador de regras: texto livre, geracao automatica com base legal, implementacao no YAML |

**Stack:** React 18, React Router 6, Vite 5, TailwindCSS 3, TypeScript 5.

### 10. Validador (`src/validator.py`)

Valida cada campo de cada registro SPED contra as definicoes extraidas da documentacao.

**Tipos de erro detectados:**

| Tipo | Descricao | Exemplo |
|------|-----------|---------|
| `MISSING_REQUIRED` | Campo obrigatorio vazio ou ausente | Campo `IND_OPER` (O) esta vazio |
| `WRONG_TYPE` | Campo numerico contem texto | `VL_DOC` contem "ABC" |
| `WRONG_SIZE` | Campo excede tamanho maximo | `NUM_DOC` com 20 chars (max: 9) |
| `INVALID_VALUE` | Valor fora da lista permitida | `IND_OPER` = "3" (aceita: "0", "1") |

**Fluxo:**
1. Carrega `register_fields` do banco em dict na memoria
2. Para cada registro SPED, busca as definicoes daquele tipo
3. Valida cada campo: obrigatoriedade, tipo, tamanho, valores validos
4. Gera lista de `ValidationError`

**Relatorio:**
- Formato Markdown
- Agrupado por tipo de erro
- Inclui valor encontrado, mensagem de erro, e trecho da documentacao relevante

### 11. Configuracao (`config.py`)

```python
# Fonte dos documentos
DOCS_ROOT = os.getenv("DOCS_ROOT", str(ROOT_DIR / "data" / "source"))
GUIA_DIR = DOCS_ROOT / "guia pratico"
LEGISLACAO_DIR = DOCS_ROOT / "legislaacao"

# Saida Markdown (por categoria)
MARKDOWN_GUIA_DIR = ROOT_DIR / "data" / "markdown" / "guia"
MARKDOWN_LEGISLACAO_DIR = ROOT_DIR / "data" / "markdown" / "legislacao"

# Banco de dados
DB_PATH = ROOT_DIR / "db" / "sped.db"

# Modelo de embeddings
EMBEDDING_MODEL = "all-MiniLM-L6-v2"    # 384 dimensoes, ~80MB
EMBEDDING_BATCH_SIZE = 64
EMBEDDING_MODEL_NOTES = "Modelo multilingue leve. Pode nao distinguir nuances fiscais."

# Busca
SEARCH_TOP_K = 5
RRF_K = 60                               # parametro do Reciprocal Rank Fusion
```

---

## Schema dos Bancos de Dados

### Banco de Documentacao (`db/sped.db`)

```sql
-- Chunks de documentacao (texto + embedding)
CREATE TABLE chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file TEXT NOT NULL,          -- ex: "Guia Pratico EFD - Versao 3.2.2.md"
    category    TEXT NOT NULL,          -- "guia" ou "legislacao"
    register    TEXT,                   -- ex: "C100" (NULL se nao especifico)
    field_name  TEXT,                   -- ex: "IND_OPER" (NULL se nao especifico)
    heading     TEXT NOT NULL,          -- titulo da secao
    content     TEXT NOT NULL,          -- conteudo textual do chunk
    page_number INTEGER,               -- pagina original do PDF
    embedding   BLOB                   -- vetor 384-dim float32 (1.536 bytes)
);

-- Indice Full-Text Search (busca exata com suporte a portugues)
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    category, register, field_name, heading, content,
    content='chunks', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'   -- "operacao" encontra "operacao"
);

-- Definicoes estruturadas de campos por registro
CREATE TABLE register_fields (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    register    TEXT NOT NULL,          -- "C100"
    field_no    INTEGER NOT NULL,       -- 1, 2, 3...
    field_name  TEXT NOT NULL,          -- "IND_OPER"
    field_type  TEXT,                   -- "C" (char), "N" (numerico)
    field_size  INTEGER,               -- tamanho maximo
    decimals    INTEGER,               -- casas decimais
    required    TEXT,                   -- "O" (obrigatorio), "OC", "N"
    valid_values TEXT,                  -- JSON: ["0", "1"]
    description TEXT,                   -- descricao do campo
    UNIQUE(register, field_no)
);

-- Controle de arquivos ja indexados
CREATE TABLE indexed_files (
    source_file TEXT PRIMARY KEY,
    category    TEXT NOT NULL,          -- "guia" ou "legislacao"
    indexed_at  TEXT DEFAULT (datetime('now'))
);

-- Triggers para manter FTS sincronizado automaticamente
CREATE TRIGGER chunks_ai AFTER INSERT ON chunks ...
CREATE TRIGGER chunks_ad AFTER DELETE ON chunks ...
```

---

### Banco de Auditoria (`db/audit.db`)

```sql
-- Arquivos SPED processados
CREATE TABLE sped_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    hash_sha256 TEXT NOT NULL,
    upload_date TEXT DEFAULT (datetime('now')),
    period_start TEXT, period_end TEXT,
    company_name TEXT, cnpj TEXT, uf TEXT,
    total_records INTEGER DEFAULT 0,
    total_errors INTEGER DEFAULT 0,
    status TEXT DEFAULT 'uploaded'
);

-- Registros parseados
CREATE TABLE sped_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    line_number INTEGER, register TEXT, block TEXT,
    fields_json TEXT NOT NULL, raw_line TEXT NOT NULL,
    FOREIGN KEY (file_id) REFERENCES sped_files(id)
);

-- Erros de validacao
CREATE TABLE validation_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    line_number INTEGER, register TEXT,
    field_no INTEGER, field_name TEXT, value TEXT,
    error_type TEXT NOT NULL, severity TEXT DEFAULT 'error',
    message TEXT NOT NULL, doc_suggestion TEXT,
    materialidade REAL DEFAULT 0,       -- impacto financeiro estimado (R$)
    FOREIGN KEY (file_id) REFERENCES sped_files(id)
);

-- Correcoes aplicadas (audit trail)
CREATE TABLE corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER, record_id INTEGER,
    field_no INTEGER, field_name TEXT,
    old_value TEXT, new_value TEXT,
    applied_by TEXT DEFAULT 'user',
    applied_at TEXT DEFAULT (datetime('now'))
);

-- Resolucoes de apontamentos (workflow analitico)
CREATE TABLE finding_resolutions (
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
);
```

---

## Comandos CLI

### Converter documentos para Markdown

```bash
python cli.py convert              # Converte guia pratico + legislacao
python cli.py convert --force      # Reconverte tudo (ignora existentes)
```

Saida:
```
==================================================
[1/2] Convertendo GUIA PRATICO
==================================================
Convertendo guia pratico: 100%|##########| 4/4
  4 arquivo(s) criado(s)

==================================================
[2/2] Convertendo LEGISLACAO
==================================================
Convertendo legislaacao: 100%|##########| 90/90
  78 arquivo(s) criado(s)

Total: 82 arquivo(s) Markdown criado(s).
```

### Indexar no banco

```bash
python cli.py index                # Indexa tudo (skip existentes)
python cli.py index --force        # Reindexa tudo
python cli.py index --db outro.db  # Banco customizado
```

Saida:
```
[1/2] Indexando GUIA PRATICO
  13.712 chunks do guia indexados.

[2/2] Indexando LEGISLACAO
  40.072 chunks da legislacao indexados.

Total: 53.784 chunks indexados no banco.
```

### Validar arquivo SPED

```bash
python cli.py validate arquivo_sped.txt
python cli.py validate arquivo.txt --output relatorio.md
python cli.py validate arquivo.txt --no-search    # sem busca na documentacao (rapido)
```

Saida:
```
Parseando arquivo_sped.txt...
  12.543 registros encontrados.
Validando...
  23 erro(s) encontrado(s).
Buscando documentacao para os erros...
Relatorio salvo em: arquivo_sped_relatorio.md

--- Resumo ---
  INVALID_VALUE: 8
  MISSING_REQUIRED: 10
  WRONG_SIZE: 3
  WRONG_TYPE: 2
```

**Exemplo de relatorio gerado:**

```markdown
# Relatorio de Validacao SPED

**Total de erros:** 23

## INVALID_VALUE (8 ocorrencias)

### Linha 1847 | C100 | Campo 03 (IND_EMIT)
- **Valor encontrado:** `3`
- **Problema:** Campo 'IND_EMIT' contem valor '3' invalido. Valores aceitos: ['0', '1']

**Documentacao relevante:**
> C100 | IND_EMIT | Indicador de emissao (emitente ou destinatario)
> Valores: 0 - Emissao propria; 1 - Terceiros
```

### Buscar na documentacao

```bash
# Busca geral
python cli.py search "substituicao tributaria"

# Filtrar por registro
python cli.py search "indicador emitente" --register C100

# Filtrar por campo
python cli.py search "IND_OPER" --register C100 --field IND_OPER

# Filtrar por categoria
python cli.py search "CFOP" --category legislacao

# Mais resultados
python cli.py search "base calculo ICMS" --top-k 10
```

Saida:
```
Buscando: "indicador emitente"
  Filtro registro: C100

3 resultado(s):

--- Resultado 1 (score: 0.0328, fonte: hybrid, cat: guia) ---
Arquivo: SPED-description-block.md
Registro: C100
Campo: IND_EMIT
Secao: SPED-description-block

C100 | IND_EMIT | Indicador de emissao (emitente ou destinatario)
```

---

## Estatisticas do Banco

| Metrica | Valor |
|---------|-------|
| **Tamanho do banco** | 126 MB |
| **Total de chunks** | 53.784 |
| Chunks do Guia Pratico | 13.712 |
| Chunks da Legislacao | 40.072 |
| **Definicoes de campos** | 657 |
| **Registros SPED mapeados** | 93 |
| **Arquivos indexados** | 82 (4 guia + 78 legislacao) |
| Dimensao dos embeddings | 384 (float32) |
| Bytes por embedding | 1.536 |

**Registros com definicao de campos (amostra):**

```
Bloco 0: 0000, 0002, 0100, 0150, 0200, 0400
Bloco B: B001, B030, B350, B440, B460, B470, B500, B510
Bloco C: C100, C112-C116, C130, C140, C165, C170-C175, C179,
         C190, C195, C321, C350, C370, C400-C470, C490,
         C510, C595, C790-C791, C800, C850-C895, C990
Bloco D: D150-D180, D350-D400, D410, D530, D590, D610, D690-D696, D990
Bloco E: E100, E110, E112, E200, E210, E500-E530, E990
Bloco G: G001, G110, G126, G130, G140
Bloco H: H001, H005, H010, H020, H990
Bloco K: K001, K200, K210, K215, K220, K230, K235, K250-K292
```

---

## Instalacao e Dependencias

**Requisitos:**
- Python >= 3.10
- Node.js >= 18
- Windows 10/11 (desenvolvimento via WSL2 ou PowerShell)

**Dependencias Backend:**

| Biblioteca | Versao | Uso |
|-----------|--------|-----|
| `fastapi` | >= 0.100.0 | API REST |
| `uvicorn` | >= 0.23.0 | Servidor ASGI |
| `pdfplumber` | >= 0.10.0 | Extracao de texto e tabelas de PDFs |
| `sentence-transformers` | >= 2.2.0 | Embeddings vetoriais (all-MiniLM-L6-v2) |
| `numpy` | >= 1.24.0 | Operacoes vetoriais para busca semantica |
| `tqdm` | >= 4.65.0 | Barras de progresso |
| `python-multipart` | >= 0.0.6 | Upload de arquivos na API |

**Dependencias Frontend:**

| Biblioteca | Versao | Uso |
|-----------|--------|-----|
| `react` | ^18.2.0 | Interface de usuario |
| `react-router-dom` | ^6.20.0 | Navegacao SPA |
| `vite` | ^5.0.0 | Build tool e dev server |
| `tailwindcss` | ^3.4.0 | Estilizacao |
| `typescript` | ^5.3.0 | Tipagem estatica |

**Instalacao:**

```powershell
# Backend
cd <diretorio-do-projeto>
python -m venv .venv-win
.\.venv-win\Scripts\Activate.ps1
pip install -r requirements.txt

# Frontend
cd frontend
npm install
```

**Primeiro uso:**

```powershell
# Ou simplesmente:
start.bat
```

---

## Decisoes Tecnicas

### pdfplumber (nao pymupdf)
pymupdf e 5-10x mais rapido, mas pdfplumber tem extracao de tabelas significativamente superior para as tabelas estruturadas da documentacao SPED. Como a conversao e um batch unico (roda uma vez), velocidade e irrelevante. Precisao importa.

### Busca brute-force com numpy (nao FAISS/sqlite-vec)
Com filtro por registro, a busca vetorial varre ~50-200 vetores. Mesmo sem filtro, 53.784 vetores levam ~200ms com numpy. Adicionar um indice vetorial nao traria beneficio pratico e adicionaria complexidade.

### 1 chunk por campo de tabela
Sistemas RAG tipicos usam chunks maiores (paragrafos, paginas). Aqui, 1 chunk por campo permite buscas precisas: "quais valores validos do campo IND_OPER do registro C100?" retorna exatamente a linha da documentacao daquele campo.

### SQLite com FTS5 (nao Postgres/Elasticsearch)
Para um sistema local processando centenas de documentos, SQLite e imbativel: zero configuracao, FTS5 nativo com suporte a portugues (`remove_diacritics`), WAL mode para performance.

### Sem LLM no pipeline
As sugestoes de correcao sao template-based, construidas a partir dos dados estruturados em `register_fields` e dos resultados de busca. Isso garante:
- Zero alucinacao
- Zero custo de API
- Resultados deterministicos
- Funciona 100% offline

### Reciprocal Rank Fusion (RRF)
Metodo mais simples para combinar resultados de duas listas ranqueadas (FTS5 + vetorial). Cada resultado recebe score `1/(k + rank)` de cada lista, somados. Nao requer tuning. k=60 e o valor padrao da literatura.

### Encoding latin-1 como padrao para SPED
Arquivos SPED gerados pelo PVA (Programa Validador e Assinador) da Receita Federal usam latin-1 (ISO-8859-1). Alguns sistemas geram cp1252. O parser tenta latin-1 primeiro, com fallback para cp1252 e utf-8.

---

## Testes e Cobertura

**1473 testes | 97% de cobertura total | 0 falhas | 4 testes E2E**

**Lint: 0 erros ruff | 0 erros mypy | 0 alertas bandit**

```
pytest tests/ --cov=src --cov-report=term-missing
```

### Fase 1 — Codigo base

| Modulo | Cobertura | O que valida |
|--------|-----------|--------------|
| `models.py` | 100% | Dataclasses, serializacao JSON valid_values |
| `embeddings.py` | 100% | blob roundtrip, embed_texts mock, lazy loading |
| `searcher.py` | 100% | FTS, semantico, RRF, search(), search_for_error() |
| `validator.py` | 99% | Tipo N rejeita texto, tamanho, obrigatorio, valid_values, load_field_definitions |
| `converter.py` | 98% | TXT/PDF(mock)/DOCX(mock), convert_all_docs, tabelas, headings |
| `indexer.py` | 96% | Chunking, field extraction, insert, index_all_markdown |
| `parser.py` | 94% | Parse, encoding fallback, hierarquia, malformed lines |

Estes testes garantem que a infraestrutura funciona: parser le arquivos, validator detecta erros de campo, indexer cria chunks, searcher encontra documentacao.

### Fase 2 — Validacoes fiscais

| Modulo | Cobertura | O que valida |
|--------|-----------|--------------|
| `format_validator.py` | 100% | Formatos especificos: CNPJ/CPF (modulo 11), datas DDMMAAAA, CEP, CFOP (1-7), NCM, chave NFe (44 dig + DV), codigo municipio IBGE |
| `intra_register_validator.py` | 98% | Regras dentro do registro: C100 (entrada exige DT_E_S, cancelada sem valor, datas no periodo), C170 (CFOP vs operacao, BC×ALIQ=ICMS), C190 (soma C170 = C190), E110 (formula completa apuracao ICMS) |
| `cross_block_validator.py` | 96% | Cruzamento entre blocos: 0 vs C/D (COD_PART/COD_ITEM existem no cadastro), C vs E (soma ICMS dos C190 = debitos/creditos do E110), bloco 9 (contagem de registros e total de linhas) |
| `tax_recalc.py` | 95% | Recalculo tributario: ICMS (BC×ALIQ/100), ICMS-ST, IPI, PIS/COFINS, totalizacao E110 (soma C190+D690 vs declarado) |
| `cst_validator.py` | 95% | Validacao de CSTs ICMS (Tabela A+B, CSOSN), consistencia isencoes (CST isento com valor>0), Bloco H (estoque vs cadastro 0200) |
| `fiscal_semantics.py` | **NOVO** | Validacao semantica fiscal: CST x CFOP, classificador de aliquota zero, monofasicos PIS/COFINS x NCM |

Sete camadas de validacao fiscal:

| Camada | Pergunta que responde | Exemplo de erro detectado |
|--------|----------------------|--------------------------|
| **Formato** | O dado esta escrito corretamente? | CNPJ com digito verificador errado |
| **Intra-registro** | Os numeros batem dentro do registro? | BC × aliquota ≠ ICMS declarado |
| **Cruzamento** | Os blocos sao coerentes entre si? | Debitos do E110 ≠ soma dos C190 |
| **Recalculo** | Os tributos foram calculados certo? | IPI recalculado diverge do declarado |
| **CST/Isencoes** | Os codigos tributarios sao consistentes? | CST isento mas ICMS > 0 |
| **Semantica Fiscal** | O tratamento tributario faz sentido? | CFOP de venda + CST isento sem beneficio |
| **Monofasicos** | PIS/COFINS monofasico esta correto? | NCM farmaceutico com CST 01 na revenda |

### Validacao Semantica Fiscal (`fiscal_semantics.py`)

Camada 3 do motor — vai alem da consistencia numerica e verifica se o tratamento tributario informado faz sentido fiscalmente.

**Classificador de aliquota zero (substitui o skip condition cego):**

| Cenario | Resultado | error_type |
|---------|-----------|------------|
| CST tributado + BC > 0 + ALIQ = 0 | Warning | `CST_ALIQ_ZERO_FORTE` |
| CST tributado + tudo zero | Info | `CST_ALIQ_ZERO_MODERADO` |
| CST isento/NT/suspensao + tudo zero | OK | — |
| CST diferimento (51) + tudo zero | OK | — |
| Exportacao/remessa + aliquota zero | OK | — |
| CST_IPI tributado + tudo zero | Info | `IPI_CST_ALIQ_ZERO` |
| CST_PIS/COFINS tributavel + tudo zero | Info | `PIS_CST_ALIQ_ZERO` / `COFINS_CST_ALIQ_ZERO` |

**Cruzamento CST x CFOP:**

| Regra | Deteccao | error_type |
|-------|----------|------------|
| CFOP de venda + CST isento/NT | Warning | `CST_CFOP_INCOMPATIVEL` |
| CFOP interestadual + CST tributado + ALIQ=0 | Warning | `CST_CFOP_INCOMPATIVEL` |
| CFOP exportacao + CST tributado + ALIQ > 0 | Warning | `CST_CFOP_INCOMPATIVEL` |

**Monofasicos PIS/COFINS (5 regras x NCM x CST x CFOP):**

| # | Regra | Severidade | error_type |
|---|-------|------------|------------|
| 1 | CST 04 (monofasico) com aliquota > 0 | Error | `MONOFASICO_ALIQ_INVALIDA` |
| 2 | CST 04 com valor PIS/COFINS > 0 | Error | `MONOFASICO_VALOR_INDEVIDO` |
| 3 | CST 04 em NCM nao monofasico | Warning | `MONOFASICO_NCM_INCOMPATIVEL` |
| 4 | NCM monofasico + CST tributavel na saida | Warning | `MONOFASICO_CST_INCORRETO` |
| 5 | CST 04 em operacao de entrada | Info | `MONOFASICO_ENTRADA_CST04` |

**NCMs monofasicos cobertos (por legislacao):**

| Categoria | Prefixos NCM | Legislacao |
|-----------|-------------|------------|
| Combustiveis/Lubrificantes | 2207, 2710, 2711, 2713, 2714, 3403, 3811, 3826 | Lei 10.865/04 |
| Farmaceuticos | 3001-3006 | Lei 10.147/00 |
| Higiene/Perfumaria | 3303-3307 | Lei 10.147/00 |
| Bebidas Frias | 2106, 2201, 2202 | Lei 10.833/03 |
| Veiculos | 8429, 8432, 8433, 8701-8706, 8711 | Lei 10.485/02 |
| Autopecas | 54 posicoes NCM (4011, 8407-8708, etc.) | Lei 10.485/02 |
| Papel Imune | 4801, 4802 | Lei 10.865/04 |

**4 niveis de severidade:**

| Nivel | Uso | Exemplos |
|-------|-----|----------|
| `critical` | Calculo divergente, cruzamento inconsistente | `CALCULO_DIVERGENTE`, `SOMA_DIVERGENTE` |
| `error` | Inconsistencia fiscal concreta | `MONOFASICO_ALIQ_INVALIDA`, `CST_INVALIDO` |
| `warning` | Situacao suspeita que precisa revisao | `CST_CFOP_INCOMPATIVEL`, `MONOFASICO_CST_INCORRETO` |
| `info` | Cenario aceitavel mas merece atencao | `CST_ALIQ_ZERO_MODERADO`, `MONOFASICO_ENTRADA_CST04` |

### Sistema de Regras (`rules.yaml` + `src/rules.py`)

Catalogo centralizado de todas as regras de validacao em formato YAML. Permite rastrear, adicionar e auditar regras sem precisar ler o codigo.

**Arquivo `rules.yaml`:** 186 regras em 22 blocos (todas implementadas):

| Bloco | Regras | Descricao |
|-------|--------|-----------|
| `formato` | 9 | CNPJ, CPF, datas, CEP, CFOP, NCM, chave NFe, cod municipio |
| `campo_a_campo` | 4 | Obrigatoriedade, tipo, tamanho, valores validos |
| `intra_registro` | 10 | C100 (datas, cancelamento), C170 (CFOP), C190 (somas), E110 (apuracao) |
| `cruzamento` | 13 | 0150/0200 (referencias), E110 vs C190 (debitos/creditos), bloco 9, bloco D |
| `recalculo` | 8 | ICMS, ICMS-ST, IPI, PIS, COFINS, E110 totais |
| `cst_isencoes` | 6 | CST invalido, isencao com valor, tributado sem ICMS, H010 estoque |
| `semantica_aliquota_zero` | 5 | CST tributado com tudo zerado (ICMS, IPI, PIS, COFINS) |
| `semantica_cst_cfop` | 3 | Venda+isento, interestadual+zero, exportacao+tributado |
| `monofasicos` | 5 | CST 04 x NCM x aliquota x entrada/saida |
| `pendentes` | 6 | Beneficio fiscal, desoneracao, devolucao, historico, interestadual, TIPI |
| `auditoria_beneficios` | 50 | E111/E112/E113 vs E110, lastro documental, sobreposicao, desproporcionalidade, governanca |
| `aliquotas` | 7 | Interestadual invalida, interna em interestadual, interestadual em interna, aliquota media, UF incompativel, importacao, divergente |
| `c190_consolidacao` | 2 | C190 vs C170 com rateio de despesas, combinacoes incompativeis CST/CFOP/ALIQ |
| `cst_expandido` | 4 | CST 020 sem reducao real, IPI CST vs campos monetarios, CST tributado aliq zero, diferimento |
| `difal` | 12 | DIFAL faltante, indevido, UF inconsistente, aliquota incorreta, base, FCP, perfil, CFOP |
| `base_calculo` | 15 | Recalculo BC, frete CIF/FOB, despesas acessorias, base inflada |
| `beneficio_fiscal` | 3 | Beneficio contaminando aliquota/DIFAL/base |
| `devolucoes` | 3 | Espelhamento, DIFAL, aliquota historica |
| `parametrizacao` | 3 | Erros sistematicos por item/UF/data |
| `ncm` | 2 | NCM tributacao incompativel, generico |
| `governanca` | 5 | Classificacao erro, grau confianca, dependencia externa, checklist, amostragem |

**Severidades:** 50 critical, 39 error, 70 warning, 16 info

**CLI (`python -m src.rules`):**

| Comando | Descricao |
|---------|-----------|
| `python -m src.rules` | Resumo geral (total, por bloco, por severidade) |
| `python -m src.rules --check` | Verifica implementacao vs definicao, lista pendencias |
| `python -m src.rules --pending` | Lista apenas regras nao implementadas |
| `python -m src.rules --block monofasicos` | Mostra regras de um bloco especifico |

**Frontend (aba "Regras"):**

Interface para criar novas regras sem editar codigo:

1. Usuario escreve regra em texto livre (ex: "Quando NCM for farmaceutico e CST PIS for 01, alertar que deveria ser monofasico")
2. Clica "Gerar Regra" — sistema busca base legal na documentacao (53k chunks) e estrutura a regra automaticamente
3. Visualiza regra estruturada com ID, bloco, registro, campos, severidade, error_type, legislacao e fontes legais (somente leitura)
4. Clica "Implementar Regra Fiscal" — salva no `rules.yaml` com status pendente

**Endpoints da API:**

| Endpoint | Metodo | Descricao |
|----------|--------|-----------|
| `GET /api/rules` | GET | Lista todas as regras do YAML |
| `POST /api/rules/generate` | POST | Recebe texto livre, busca base legal, retorna regra estruturada |
| `POST /api/rules/implement` | POST | Adiciona regra gerada ao `rules.yaml` |

**Como adicionar regra manualmente:**

1. Adicione entrada no bloco adequado do `rules.yaml` com `implemented: false`
2. Execute `python -m src.rules --pending` para confirmar
3. Implemente a logica no `module` indicado
4. Mude para `implemented: true`
5. Execute `python -m src.rules --check` para validar

### Correcoes de Indexacao (Abril 2026)

Correcoes criticas nos indices de campos dos validadores, alinhando com o Guia Pratico EFD v3.2.2:

**Validadores corrigidos:**

| Arquivo | Registro | Campo | Antes (errado) | Depois (correto) |
|---------|----------|-------|-----------------|-------------------|
| `intra_register_validator.py` | C100 | DT_DOC | `fields[8]` | `fields[9]` |
| `intra_register_validator.py` | C100 | DT_E_S | `fields[9]` | `fields[10]` |
| `intra_register_validator.py` | C100 | VL_DOC | `fields[10]` | `fields[11]` |
| `intra_register_validator.py` | C170 | CFOP | `fields[9]` | `fields[10]` |
| `cst_validator.py` | C170 | CST_ICMS | `fields[11]` | `fields[9]` |
| `tax_recalc.py` | C170 | CST_ICMS | `fields[11]` | `fields[9]` |
| `tax_recalc.py` | C170 | VL_BC_IPI | `fields[19]` | `fields[21]` |
| `tax_recalc.py` | C170 | ALIQ_IPI | `fields[20]` | `fields[22]` |
| `tax_recalc.py` | C170 | VL_IPI | `fields[21]` | `fields[23]` |
| `tax_recalc.py` | C170 | VL_BC_PIS | `fields[22]` | `fields[25]` |
| `tax_recalc.py` | C170 | ALIQ_PIS | `fields[23]` | `fields[26]` |
| `tax_recalc.py` | C170 | VL_PIS | `fields[24]` | `fields[29]` |
| `tax_recalc.py` | C170 | VL_BC_COFINS | `fields[25]` | `fields[31]` |
| `tax_recalc.py` | C170 | ALIQ_COFINS | `fields[26]` | `fields[32]` |
| `tax_recalc.py` | C170 | VL_COFINS | `fields[27]` | `fields[35]` |

**Banco de definicoes (`sped.db`) corrigido:**

| Registro | Problema | Correcao |
|----------|----------|----------|
| B001 | 4 campos (REG, QTD_LIN_0, COD_CCUS, CCUS) | 2 campos (REG, IND_MOV) |
| H001 | Campo QTD_LIN_G em vez de IND_MOV | Campo IND_MOV |

**Base de referencia (`SPED-cabecalho.md`) corrigida:**

| Registro | Problema | Correcao |
|----------|----------|----------|
| 0000 | Faltava campo COD_FIN | Adicionado COD_FIN na posicao 03 |
| C190 | CFOP e CST_ICMS invertidos | Ordem correta: CST_ICMS (02), CFOP (03) |

### Regras de Validacao Implementadas

O sistema valida arquivos SPED EFD seguindo rigorosamente o **Guia Pratico EFD v3.2.2** como fonte de autoridade maxima. Quando o codigo ou banco de definicoes diverge do Guia, o Guia prevalece.

**Registros de abertura/fechamento de bloco:**
- IND_MOV = 0: bloco com dados — registros analiticos obrigatorios
- IND_MOV = 1: bloco sem movimento — apenas abertura (xx01) + fechamento (xx90), nenhum registro interno permitido

**C100 - Nota Fiscal:**
- IND_OPER define o tipo da operacao (entrada/saida) — todos os filhos herdam
- COD_SIT cancelado (02/03/04): apenas campos minimos + CHV_NFE, sem registros filhos (C170/C190)
- CHV_NFE obrigatoria para COD_MOD 55/65, tamanho fixo 44 digitos
- DT_DOC e DT_E_S devem estar dentro do periodo DT_INI..DT_FIN do 0000
- VL_DOC deve ser zero para documentos cancelados

**C170 - Itens da NF:**
- COD_ITEM deve existir no 0200
- CFOP deve ser coerente com IND_OPER do C100 pai (entrada: 1/2/3xxx, saida: 5/6/7xxx)
- QTD deve ser > 0 (exceto COD_SIT 06/07)
- VL_BC_ICMS x ALIQ_ICMS / 100 deve bater com VL_ICMS (tolerancia R$ 0,02)
- CST isento (40/41/50/60): VL_BC_ICMS e VL_ICMS devem ser zero
- CST tributado (00/10/20/70/90) com BC > 0: VL_ICMS nao pode ser zero

**C190 - Totalizador:**
- VL_OPR deve bater com soma dos VL_ITEM dos C170 com mesmo CFOP
- VL_BC_ICMS deve bater com soma dos VL_BC_ICMS dos C170
- VL_ICMS deve bater com soma dos VL_ICMS dos C170

**E110 - Apuracao ICMS:**
- VL_TOT_DEBITOS = soma ICMS dos C190 de saida (CFOP 5/6/7xxx)
- VL_TOT_CREDITOS = soma ICMS dos C190 de entrada (CFOP 1/2/3xxx)
- VL_SLD_APURADO = debitos - creditos (formula completa)
- VL_ICMS_RECOLHER = VL_SLD_APURADO - VL_TOT_DED (se saldo > 0)

**Referencias cruzadas:**
- COD_PART do C100/D100 deve existir no 0150
- COD_ITEM do C170 deve existir no 0200
- UNID do C170 deve existir no 0190
- UNID diferente da UNID_INV do 0200 exige 0220 (exceto TIPO_ITEM = 07)
- Bloco 9: contagem de cada registro (9900) e total de linhas (9999) deve bater com contagem real

**Tolerancia de calculo:** R$ 0,02 para todos os recalculos (ICMS, ICMS-ST, IPI, PIS, COFINS).

### Qualidade de codigo (lint)

| Ferramenta | Status | O que verifica |
|-----------|--------|----------------|
| **ruff** | 0 erros | Estilo, imports, seguranca (flake8+isort+bandit rules) |
| **mypy** | 0 erros | Tipos estaticos (--ignore-missing-imports) |
| **bandit** | 0 alertas | Vulnerabilidades de seguranca |

Correcoes de lint aplicadas:
- 62 erros ruff corrigidos (45 auto-fix + 17 manuais: imports, `Optional` -> `X | None`, `zip(strict=)`, `any()`, f-strings longas, `if` aninhados)
- 11 erros mypy corrigidos (`json.loads` -> `list()`, tipagem de retorno em embeddings, `pdfplumber.Page` -> `Any`, variancia de listas)
- 2 alertas bandit silenciados com `# nosec` (XML parse em DOCX fallback — fonte local confiavel)

### Detalhamento das validacoes fiscais

**format_validator.py** — O dado esta no formato correto?
- CNPJ: 14 digitos + 2 DVs modulo 11. Rejeita todos iguais, pontuacao, tamanho errado
- CPF: 11 digitos + 2 DVs modulo 11. Rejeita todos iguais
- Data DDMMAAAA: dia/mes/ano validos, ano entre 1900-2100, verifica bissexto
- Data no periodo: verifica se esta entre DT_INI e DT_FIN do registro 0000
- CEP: 8 digitos, nao pode ser zeros
- CFOP: 4 digitos, primeiro 1-7. Verifica coerencia com IND_OPER (entrada 1/2/3, saida 5/6/7)
- NCM: 8 digitos
- Chave NFe: 44 digitos + DV modulo 11 (pesos 2-9 ciclicos)
- Codigo municipio: 7 digitos IBGE, primeiro digito 1-5 (regioes)

**intra_register_validator.py** — Os numeros batem dentro do registro?
- C100: entrada (IND_OPER=0) exige DT_E_S; cancelada (COD_SIT=02/03/04) nao pode ter valor>0; DT_DOC<=DT_E_S; datas no periodo
- C170: CFOP coerente com operacao do C100 pai; BC_ICMS × ALIQ_ICMS / 100 ≈ VL_ICMS (tolerancia R$0.02)
- C190: soma VL_ITEM dos C170 com mesmo CFOP = VL_OPR do C190; idem para BC e ICMS
- E110: formula completa: saldo = debitos + aj_deb + estornos_cred - creditos - aj_cred - estornos_deb - sld_anterior; recolher = saldo - deducoes; credor = abs(saldo)

**cross_block_validator.py** — Os blocos sao coerentes entre si?
- 0 vs C/D: COD_PART no C100/D100 deve existir no 0150; COD_ITEM no C170 deve existir no 0200
- C vs E: soma ICMS dos C190 com CFOP saida = VL_TOT_DEBITOS do E110; entrada = VL_TOT_CREDITOS
- Bloco 9: cada 9900 declara contagem por registro — confere com contagem real; 9999 declara total de linhas

**tax_recalc.py** — Os tributos foram calculados corretamente?
- ICMS: BC = VL_ITEM - VL_DESC; ICMS = BC × ALIQ / 100; compara com declarado
- ICMS-ST: para CSTs 10,30,60,70,201,202,203,500 — BC_ST × ALIQ_ST = VL_ICMS_ST
- IPI: VL_BC_IPI × ALIQ_IPI / 100 = VL_IPI
- PIS: VL_BC_PIS × ALIQ_PIS / 100 = VL_PIS
- COFINS: VL_BC_COFINS × ALIQ_COFINS / 100 = VL_COFINS
- Totalizacao E110: soma C190 (saida=debitos, entrada=creditos) + D690; compara com E110

**cst_validator.py** — Os codigos tributarios sao consistentes?
- CST ICMS: valida Tabela A (origem 0-8) + Tabela B (00,10,20,30,40,41,50,51,60,70,90)
- CSOSN Simples Nacional: 101,102,103,201,202,203,300,400,500,900
- Isencoes: CST isento (40,41,50,60) com BC>0 ou ICMS>0 = erro ISENCAO_INCONSISTENTE
- Tributacao: CST tributado (00,10,20,70,90) com BC>0 mas ICMS=0 = erro TRIBUTACAO_INCONSISTENTE
- Bloco H: COD_ITEM no H010 deve existir no 0200; QTD e VL_ITEM nao podem ser negativos

### Fase 4 — Persistencia e services

| Modulo | O que faz |
|--------|-----------|
| `database.py` | Schema SQLite com 6 tabelas: sped_files (metadados), sped_records (registros parseados), validation_errors (erros com severidade), cross_validations (cruzamentos), corrections (historico de correcoes), audit_log (rastreabilidade) |
| `file_service.py` | Upload com hash SHA-256 (detecta duplicata), parse, extracao de metadados do 0000 (empresa, CNPJ, periodo), persistencia dos registros, delete cascade, listagem |
| `validation_service.py` | Orquestrador: executa 22 camadas de validacao (186 regras) em sequencia, classifica severidade (critical/error/warning/info), persiste erros, permite revalidacao sem duplicar |
| `fiscal_semantics.py` | Validacao semantica: CST x CFOP (3 regras), classificador aliquota zero (7 cenarios), monofasicos PIS/COFINS x NCM (5 regras, 100+ NCMs) |
| `pipeline.py` | Pipeline estagiado com progresso em tempo real via SSE: 4 estagios (estrutural, cruzamento+semantica, enriquecimento, auto-correcao) com detalhes por sub-passo |
| `error_messages.py` | 71 tipos de erro com template amigavel, orientacao de correcao e icone. Cobre monofasicos, CST x CFOP, aliquota zero, auditoria de beneficios, DIFAL, C190 |
| `correction_service.py` | Aplica correcao em campo especifico (atualiza fields_json + raw_line), salva historico (old_value → new_value), marca erro como corrigido, undo que restaura valor original |
| `export_service.py` | 4 formatos: SPED corrigido (.txt pipe-delimited), relatorio Markdown (resumo + erros + correcoes), CSV, JSON |

Fluxo completo persistido: upload → parse → validar → consultar erros → corrigir → revalidar → exportar. Tudo rastreado com audit_log.

### Fase 5 — API REST (FastAPI)

14 endpoints que expõem todas as funcionalidades via HTTP:

| Endpoint | Metodo | Funcao |
|----------|--------|--------|
| `/api/health` | GET | Health check |
| `/api/files/upload` | POST | Upload arquivo SPED (multipart) |
| `/api/files` | GET | Listar arquivos processados |
| `/api/files/{id}` | GET | Detalhes (CNPJ, periodo, total erros) |
| `/api/files/{id}` | DELETE | Remover arquivo + dados (cascade) |
| `/api/files/{id}/validate` | POST | Validacao completa (6 camadas) |
| `/api/files/{id}/errors` | GET | Listar erros (?severity=critical&error_type=...) |
| `/api/files/{id}/summary` | GET | Resumo por tipo e severidade |
| `/api/files/{id}/records` | GET | Listar registros (?block=C&status=error) |
| `/api/files/{id}/records/{rec}` | GET | Detalhe de registro |
| `/api/files/{id}/records/{rec}` | PUT | Corrigir campo (field_no, new_value) |
| `/api/files/{id}/report` | GET | Relatorio (?format=md/csv/json) |
| `/api/files/{id}/download` | GET | Baixar SPED corrigido (.txt) |
| `/api/search` | GET | Busca na documentacao (?q=ICMS&register=C100) |

Infraestrutura:
- CORS habilitado para frontend local
- Dependency injection: banco SQLite por request, override nos testes
- Pydantic models: validacao automatica de tipos em requests/responses
- Swagger automatico em `/docs`

Para rodar: `uvicorn api.main:app --reload` → http://localhost:8000/docs

### Fase 6 — Frontend (React + TypeScript + Tailwind)

Stack: React 18 + TypeScript 5 + Vite 5 + Tailwind CSS 3 + React Router 6

| Arquivo | Funcao |
|---------|--------|
| `types/sped.ts` | 5 interfaces TypeScript espelhando Pydantic models da API (FileInfo, RecordInfo, ValidationError, ErrorSummary, ValidationResponse) |
| `api/client.ts` | Cliente HTTP tipado: 12 funcoes para todos os endpoints (upload, validate, getErrors, getRecords, updateRecord, getReport, download) |
| `components/Layout.tsx` | Shell: sidebar fixa com navegacao + area de conteudo (Outlet) |
| `pages/UploadPage.tsx` | Drag & drop de arquivo SPED com feedback visual, "Processando...", redirect ao completar |
| `pages/FilesPage.tsx` | Tabela de arquivos: empresa, CNPJ, periodo, registros, erros (vermelho se >0), status (badge) |
| `pages/FileDetailPage.tsx` | Dashboard completo: 4 score cards (registros, erros, conformidade%, status), botao validar/revalidar, download SPED corrigido, 3 abas (resumo por tipo/severidade, tabela de erros, preview relatorio MD/CSV/JSON) |

Fluxo do usuario: upload → validar → ver score cards → aba resumo (erros agrupados) → aba erros (tabela detalhada) → aba relatorio (preview MD/CSV/JSON) → baixar SPED corrigido

```bash
# Terminal 1: API
uvicorn api.main:app --reload

# Terminal 2: Frontend
cd frontend && npm run dev
# http://localhost:3000 (proxy /api → localhost:8000)
```

Build: 0 erros TypeScript (strict mode), 183KB JS + 5KB CSS gzipped

### Fase 7 — Integracao e Polish

**Docker Compose** (`docker-compose.yml` + 2 Dockerfiles):
- Service `api`: Python 3.12 + FastAPI na porta 8000, hot reload de `src/` e `api/`, volume persistente `db-data` para SQLite
- Service `frontend`: Node 18 + Vite na porta 3000, depende do `api`
- `docker-compose up --build` sobe tudo

**Script de setup** (`setup.sh`):
- [1/4] Instala deps Python (detecta `uv` ou usa `pip`, cria venv)
- [2/4] Instala deps frontend (`npm install`)
- [3/4] Verifica banco de documentacao (instrui `cli.py convert && index` se nao existe)
- [4/4] Roda todos os testes para validar instalacao

**Testes end-to-end** (`test_e2e.py` — 4 testes):
- `test_full_flow_valid_file`: upload → validar → resumo → exportar relatorio MD/CSV/JSON → exportar SPED corrigido
- `test_full_flow_error_file`: upload → validar (encontra erros) → consultar erros → aplicar correcao (IND_OPER→"0") → verificar registro "corrected" → revalidar (sem duplicatas) → exportar
- `test_duplicate_upload`: hash SHA-256 detecta duplicata, retorna mesmo file_id
- `test_audit_log_tracks_all_actions`: log contem "upload" e "validate"

```bash
# Setup rapido
chmod +x setup.sh && ./setup.sh

# Ou com Docker
docker-compose up --build
# API: http://localhost:8000/docs
# App: http://localhost:3000
```

---

## Numeros finais do projeto

| Metrica | Valor |
|---------|-------|
| **Testes** | 1473 (unitarios + integracao + API + E2E) |
| **Cobertura** | 97% |
| **Regras de validacao** | 186 em 22 blocos (todas implementadas) |
| **Lint** | 0 ruff, 0 mypy, 0 bandit |
| **Modulos validadores** | 28 arquivos em `src/validators/` |
| **Modulos Python** | 40+ arquivos em `src/` + `api/` |
| **Componentes React** | 7 arquivos (types, client, layout, 4 pages) |
| **Endpoints API** | 17 |
| **Tabelas SQLite** | 6 (auditoria) + 3 (documentacao) |
| **Fases completas** | 7/7 |

---

## Configuracao

### Variaveis de Ambiente

| Variavel | Obrigatoria | Descricao |
|----------|-------------|-----------|
| `API_KEY` | Sim (producao) | Chave de autenticacao da API (minimo 32 caracteres). Se nao definida, modo dev aceita qualquer chave |
| `DOCS_ROOT` | Nao | Caminho para documentos fonte (default: `data/source`) |
| `PYTHONPATH` | Sim | Raiz do projeto (para imports relativos) |

**Linux/macOS:**
```bash
export API_KEY="sua-chave-secreta-com-pelo-menos-32-caracteres"
export PYTHONPATH=$(pwd)
```

**PowerShell:**
```powershell
$env:API_KEY = "sua-chave-secreta-com-pelo-menos-32-caracteres"
$env:PYTHONPATH = (Get-Location).Path
```

**Docker:** Defina no arquivo `.env` (copiado de `.env.example`).

---

## Tabelas de Referencia

O motor de validacao utiliza tabelas YAML em `data/` para regras que dependem de dados externos. Para atualizar:

1. Edite o arquivo YAML correspondente
2. Reinicie a API (as tabelas sao carregadas em memoria no startup)
3. Revalide os arquivos SPED para aplicar as novas regras

| Tabela | Arquivo | Uso |
|--------|---------|-----|
| Aliquotas internas por UF | `aliquotas_internas_uf.yaml` | DIFAL_004, validacao aliquota interna |
| FCP por UF | `fcp_por_uf.yaml` | DIFAL_006, percentual FCP |
| NCMs monofasicos | `monofasicos_ncm.yaml` | Regras monofasicos PIS/COFINS |
| Regras de validacao | `rules.yaml` | Catalogo central de 186 regras |

**Como adicionar uma regra ao `rules.yaml`:**

```yaml
- id: NOVA_001
  register: C170
  fields: [CAMPO1, CAMPO2]
  error_type: NOVO_TIPO_ERRO
  severity: warning
  description: "Descricao da regra"
  implemented: false          # Mude para true apos implementar
  module: modulo_validator.py
```

Apos adicionar, execute `python -m src.rules --check` para validar a integridade do catalogo.

---

### Itens pendentes (melhorias futuras)

- Editor de campo inline no frontend (API de correcao existe, falta UI)
- Graficos de erros (Recharts/Chart.js — dados ja disponiveis no summary)
- Testes de componentes React (React Testing Library)
- Responsividade mobile
- Cache de embeddings para performance em arquivos grandes
- Cruzamento K vs C (producao vs documentos)

---

## Codigo-fonte - Metricas

| Arquivo | Linhas | Descricao |
|---------|--------|-----------|
| `src/models.py` | 77 | Dataclasses centrais |
| `src/parser.py` | 122 | Parser SPED EFD |
| `src/converter.py` | 400 | Conversor PDF/DOCX/TXT -> Markdown |
| `src/indexer.py` | 455 | Indexador + schema SQLite |
| `src/embeddings.py` | 45 | Wrapper sentence-transformers |
| `src/searcher.py` | 262 | Busca hibrida + RRF |
| `src/validator.py` | 208 | Validacao de campos |
| `src/validators/format_validator.py` | 160 | Formatos: CNPJ, CPF, datas, CFOP, chave NFe |
| `src/validators/intra_register_validator.py` | 280 | Regras intra-registro: C100, C170, C190, E110 |
| `src/validators/cross_block_validator.py` | 160 | Cruzamento entre blocos: cadastros, C vs E, bloco 9 |
| `src/validators/tax_recalc.py` | 270 | Recalculo ICMS, ICMS-ST, IPI, PIS/COFINS, totalizacao E110 |
| `src/validators/cst_validator.py` | 190 | Validacao CSTs, isencoes, Bloco H |
| `src/services/database.py` | 110 | Schema SQLite de auditoria (6 tabelas + indices) |
| `src/services/file_service.py` | 130 | Upload, hash, parse, metadados, CRUD |
| `src/services/validation_service.py` | 150 | Orquestrador de validacao completa |
| `src/services/correction_service.py` | 120 | Aplicar/desfazer correcoes com historico |
| `src/services/export_service.py` | 140 | Exportar SPED corrigido, relatorio MD/CSV/JSON |
| `api/main.py` | 35 | FastAPI app + CORS + routers |
| `api/deps.py` | 35 | Dependency injection |
| `api/schemas/models.py` | 100 | Pydantic models |
| `api/routers/files.py` | 65 | Endpoints de arquivos |
| `api/routers/records.py` | 70 | Endpoints de registros |
| `api/routers/validation.py` | 45 | Endpoints de validacao |
| `api/routers/report.py` | 55 | Endpoints de relatorio/exportacao |
| `api/routers/search.py` | 45 | Endpoints de busca |
| `frontend/src/types/sped.ts` | 50 | Interfaces TypeScript |
| `frontend/src/api/client.ts` | 55 | Cliente HTTP tipado |
| `frontend/src/components/Layout.tsx` | 30 | Shell da aplicacao |
| `frontend/src/pages/UploadPage.tsx` | 65 | Upload drag & drop |
| `frontend/src/pages/FilesPage.tsx` | 60 | Lista de arquivos |
| `frontend/src/pages/FileDetailPage.tsx` | 200 | Dashboard completo (score cards, erros, relatorio) |
| `cli.py` | 275 | Interface de linha de comando |
| `config.py` | 38 | Configuracoes |
| **Total** | **~4.502** | |
