# PRD v6 — Motor XC: Camada de Cache e Pareamento Persistido

**Versao:** 1.0
**Data:** 2026-04-13
**Autor:** Bruno / Claude
**Status:** Draft

---

## 1. Problema

O Motor de Cruzamento XC (SPED x XML) reconstroi em memoria o pareamento
completo (DocumentScope + ItemPair + agregados por grupo) toda vez que roda.
Isso significa:

- 6 queries SQL + heuristica de matching refeitos a cada execucao
- Agregados por (CST, CFOP, ALIQ) recalculados no XC051 a cada run
- Sem rastro de auditoria de como itens foram pareados
- Impossibilidade de drill-down na UI (mostrar pares matched)

**Dados ja armazenados:** nfe_xmls, nfe_itens, sped_records (OK)
**Dados NAO armazenados:** pareamento C100-XML, pareamento C170-item, agregados por grupo

---

## 2. Objetivo

Persistir a camada intermediaria de pareamento e pre-computar agregados,
de forma incremental e sem quebrar as 95+ regras XC existentes.

**Resultado esperado:**
- 15-20% de ganho de performance no Motor XC em re-execucoes
- Drill-down de pareamento na UI (futuro)
- Trilha de auditoria completa (quem pareou com quem, com qual score)
- Codigo das regras XC inalterado (leem do DocumentScope como hoje)

---

## 3. Arquitetura Alvo

```
ANTES (toda execucao):
  sped_records ──┐
  nfe_xmls ──────┤──→ DocumentScopeBuilder ──→ [MEMORIA] ──→ Regras XC
  nfe_itens ─────┘        (6 queries)

DEPOIS (1a execucao persiste, proximas leem):
  sped_records ──┐
  nfe_xmls ──────┤──→ DocumentScopeBuilder ──→ document_matches ──┐
  nfe_itens ─────┘                             item_matches ──────┤──→ Regras XC
                                               nfe_group_totals ──┘
                                               (tabelas persistidas)
```

---

## 4. Fases de Implementacao

### FASE 1 — Baseline de Testes (0 mudancas no codigo de producao)

**Objetivo:** Garantir que temos testes solidos ANTES de mexer em qualquer coisa.

**Tarefas:**

1.1. Criar `tests/test_xc_baseline.py` — teste de integracao end-to-end:
  - Upload de SPED + XMLs de conferencia (pasta `conferencia/`)
  - Rodar pipeline completo (validacao + Motor XC)
  - Capturar snapshot dos findings (regra, severidade, chave_nfe, valor)
  - Salvar como fixture JSON para comparacao futura

1.2. Criar `tests/test_document_scope_builder.py`:
  - Testar `build_all()` com cenarios:
    - XML com match exato em C100
    - XML sem C100 (orfao)
    - C100 sem XML
    - XML cancelado
    - Nota complementar (C113)
  - Validar campos do DocumentScope retornado

1.3. Criar `tests/test_xc051_triangular.py` (expandir o existente):
  - Cenario: C190 diverge de C170, XML confirma C170
  - Cenario: C190 diverge de C170, XML confirma C190
  - Cenario: todos convergem (sem finding)
  - Cenario: grupo ausente no XML

**Verificacao:**
```bash
pytest tests/test_xc_baseline.py tests/test_document_scope_builder.py -v
# Todos devem passar com codigo ATUAL (sem mudancas)
```

**Arquivos envolvidos:**
- `tests/test_xc_baseline.py` (novo)
- `tests/test_document_scope_builder.py` (novo)
- `tests/test_cross_engine.py` (existente — expandir TestXC051Triangular)

---

### FASE 2 — Tabela nfe_group_totals (pre-computar agregados XML)

**Objetivo:** Computar agregados por (CST, CFOP, ALIQ) no momento do upload
do XML, eliminando recalculo no XC051.

**Tarefas:**

2.1. Criar tabela `nfe_group_totals`:
```sql
CREATE TABLE nfe_group_totals (
    id SERIAL PRIMARY KEY,
    nfe_id INTEGER NOT NULL REFERENCES nfe_xmls(id) ON DELETE CASCADE,
    file_id INTEGER NOT NULL,
    cst_icms TEXT NOT NULL,
    cfop TEXT NOT NULL,
    aliq_icms REAL NOT NULL DEFAULT 0,
    qtd_itens INTEGER NOT NULL DEFAULT 0,
    vl_opr REAL NOT NULL DEFAULT 0,      -- SUM(vl_prod - vl_desc)
    vl_prod REAL NOT NULL DEFAULT 0,
    vl_desc REAL NOT NULL DEFAULT 0,
    vl_bc_icms REAL NOT NULL DEFAULT 0,
    vl_icms REAL NOT NULL DEFAULT 0,
    vl_bc_icms_st REAL NOT NULL DEFAULT 0,
    vl_icms_st REAL NOT NULL DEFAULT 0,
    vl_ipi REAL NOT NULL DEFAULT 0,
    vl_pis REAL NOT NULL DEFAULT 0,
    vl_cofins REAL NOT NULL DEFAULT 0,
    UNIQUE(nfe_id, cst_icms, cfop, aliq_icms)
);
CREATE INDEX idx_nfe_groups_file ON nfe_group_totals(file_id);
CREATE INDEX idx_nfe_groups_nfe ON nfe_group_totals(nfe_id);
```

2.2. Criar funcao `compute_nfe_group_totals(db, file_id, nfe_id)`:
  - Agregar nfe_itens por (nfe_id, cst_icms, cfop[:4], aliq_icms)
  - INSERT INTO nfe_group_totals
  - Chamada ao final de `upload_nfe_xmls()` (apos inserir itens)

2.3. Criar `tests/test_nfe_group_totals.py`:
  - Inserir XML com itens conhecidos
  - Chamar compute_nfe_group_totals()
  - Verificar agregados com valores esperados
  - Testar idempotencia (chamar 2x nao duplica)

**Verificacao:**
```bash
pytest tests/test_nfe_group_totals.py -v
pytest tests/test_xc_baseline.py -v   # baseline NAO deve quebrar
```

**Arquivos envolvidos:**
- `src/services/database.py` — adicionar CREATE TABLE (SQLite)
- `src/services/database_pg.py` — adicionar CREATE TABLE (PostgreSQL)
- `src/services/xml_service.py` — funcao compute + chamar apos upload
- `tests/test_nfe_group_totals.py` (novo)

---

### FASE 3 — Tabela document_matches (pareamento C100-XML persistido)

**Objetivo:** Salvar o resultado do matching chave_nfe entre C100 e XML.

**Tarefas:**

3.1. Criar tabela `document_matches`:
```sql
CREATE TABLE document_matches (
    id SERIAL PRIMARY KEY,
    file_id INTEGER NOT NULL,
    run_id INTEGER,                       -- qual execucao gerou o match
    c100_record_id INTEGER,               -- FK sped_records.id (pode ser NULL se orfao XML)
    nfe_id INTEGER,                       -- FK nfe_xmls.id (pode ser NULL se C100 sem XML)
    chave_nfe TEXT NOT NULL,
    match_status TEXT NOT NULL,            -- matched|sem_xml|sem_c100|cancelada
    is_complementar INTEGER DEFAULT 0,
    c170_count INTEGER DEFAULT 0,         -- qtd itens SPED
    xml_item_count INTEGER DEFAULT 0,     -- qtd itens XML
    matched_pair_count INTEGER DEFAULT 0, -- qtd pares matched
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(file_id, chave_nfe, run_id)
);
CREATE INDEX idx_doc_matches_file ON document_matches(file_id);
```

3.2. Modificar `DocumentScopeBuilder.build_all()`:
  - Apos construir scopes, INSERT INTO document_matches
  - Adicionar parametro `run_id` (vem de validation_runs)
  - Logica: se ja existe match para este file_id+run_id, pular (idempotente)

3.3. Criar `tests/test_document_matches.py`:
  - Rodar build_all() com dados de teste
  - Verificar que document_matches foi populada
  - Verificar contagens (c170_count, xml_item_count, matched_pair_count)
  - Testar re-execucao (idempotencia)

**Verificacao:**
```bash
pytest tests/test_document_matches.py -v
pytest tests/test_xc_baseline.py -v   # baseline NAO deve quebrar
pytest tests/test_cross_engine.py -v  # testes existentes intactos
```

**Arquivos envolvidos:**
- `src/services/database.py` — CREATE TABLE
- `src/services/database_pg.py` — CREATE TABLE
- `src/services/document_scope_builder.py` — persistir apos build
- `tests/test_document_matches.py` (novo)

---

### FASE 4 — Tabela item_matches (pareamento C170-XML item persistido)

**Objetivo:** Salvar o resultado do matching heuristico entre C170 e itens XML.

**Tarefas:**

4.1. Criar tabela `item_matches`:
```sql
CREATE TABLE item_matches (
    id SERIAL PRIMARY KEY,
    document_match_id INTEGER NOT NULL REFERENCES document_matches(id) ON DELETE CASCADE,
    c170_record_id INTEGER,               -- FK sped_records.id (NULL se SEM_MATCH XML)
    xml_item_id INTEGER,                  -- FK nfe_itens.id (NULL se SEM_MATCH C170)
    match_state TEXT NOT NULL,            -- MATCH_EXATO|MATCH_PROVAVEL|AMBIGUO|SEM_MATCH
    match_score REAL DEFAULT 0,
    item_nature TEXT,                     -- MERCADORIA|SERVICO|ATIVO|OUTRO
    -- Campos snapshot para nao depender de JOIN na hora de ler
    c170_vl_item REAL,
    c170_cst_icms TEXT,
    c170_cfop TEXT,
    xml_vl_prod REAL,
    xml_cst_icms TEXT,
    xml_cfop TEXT
);
CREATE INDEX idx_item_matches_doc ON item_matches(document_match_id);
```

4.2. Modificar `DocumentScopeBuilder.build_all()`:
  - Apos salvar document_matches, iterar item_pairs e salvar em item_matches
  - Incluir itens sem match (c170_sem_match e xml_items_sem_match)

4.3. Criar `tests/test_item_matches.py`:
  - Inserir C100+C170+XML com matching conhecido
  - Rodar build_all()
  - Verificar item_matches com scores e estados esperados
  - Testar cenarios: match exato, heuristico, ambiguo, sem match

**Verificacao:**
```bash
pytest tests/test_item_matches.py -v
pytest tests/test_xc_baseline.py -v   # baseline NAO deve quebrar
pytest tests/test_cross_engine.py -v  # testes existentes intactos
```

**Arquivos envolvidos:**
- `src/services/database.py` — CREATE TABLE
- `src/services/database_pg.py` — CREATE TABLE
- `src/services/document_scope_builder.py` — persistir item_pairs
- `tests/test_item_matches.py` (novo)

---

### FASE 5 — XC051 usa nfe_group_totals (otimizacao real)

**Objetivo:** Modificar `run_xc051_c190_triangular()` para ler agregados
pre-computados em vez de calcular on-the-fly.

**Tarefas:**

5.1. Adicionar campo `xml_group_totals` ao DocumentScope:
  - Dicionario {(cst, cfop, aliq): {vl_opr, vl_icms, ...}}
  - Populado pelo DocumentScopeBuilder a partir de nfe_group_totals

5.2. Modificar `DocumentScopeBuilder.build_all()`:
  - Query: SELECT * FROM nfe_group_totals WHERE nfe_id = ?
  - Popular scope.xml_group_totals para cada scope matched

5.3. Modificar `run_xc051_c190_triangular()`:
  - ANTES: Loop por item_pairs + xml_items_sem_match para agregar
  - DEPOIS: Ler scope.xml_group_totals diretamente
  - Manter fallback: se xml_group_totals vazio, calcular como antes

5.4. Teste de regressao:
  - Rodar test_xc_baseline.py — findings devem ser IDENTICOS ao snapshot
  - Rodar test_cross_engine.py::TestXC051Triangular — mesmos resultados

**Verificacao:**
```bash
pytest tests/test_xc_baseline.py -v        # snapshot IDENTICO
pytest tests/test_cross_engine.py -v       # testes existentes passam
pytest tests/test_nfe_group_totals.py -v   # agregados corretos
```

**Arquivos envolvidos:**
- `src/services/cross_engine_models.py` — adicionar xml_group_totals ao DocumentScope
- `src/services/document_scope_builder.py` — carregar de nfe_group_totals
- `src/services/cross_engine.py` — run_xc051_c190_triangular() usa cache

---

### FASE 6 — Cache de DocumentScope (skip rebuild em re-runs)

**Objetivo:** Se ja existe pareamento persistido para o file_id, reconstruir
DocumentScope a partir das tabelas de cache em vez de refazer tudo.

**Tarefas:**

6.1. Adicionar metodo `DocumentScopeBuilder.load_from_cache(run_id)`:
  - Query document_matches + item_matches + nfe_group_totals
  - Reconstituir List[DocumentScope] sem refazer matching
  - Retornar None se cache nao existe (fallback para build_all)

6.2. Modificar `CrossValidationEngine.run()`:
  - Tentar load_from_cache() primeiro
  - Se retornar None, chamar build_all() (comportamento atual)
  - Flag `force_rebuild=True` para ignorar cache quando necessario

6.3. Teste de cache hit/miss:
  - 1a execucao: build_all() + persist
  - 2a execucao: load_from_cache() deve retornar scopes identicos
  - Comparar findings da 1a e 2a execucao (devem ser iguais)
  - Medir tempo: 2a execucao deve ser mais rapida

**Verificacao:**
```bash
pytest tests/test_scope_cache.py -v        # cache hit/miss
pytest tests/test_xc_baseline.py -v        # snapshot IDENTICO
pytest tests/test_cross_engine.py -v       # testes existentes passam
```

**Arquivos envolvidos:**
- `src/services/document_scope_builder.py` — load_from_cache()
- `src/services/cross_engine.py` — try cache first
- `tests/test_scope_cache.py` (novo)

---

## 5. Ordem de Dependencia

```
FASE 1 (testes baseline)
  │
  ├──→ FASE 2 (nfe_group_totals) ──→ FASE 5 (XC051 usa cache)
  │
  └──→ FASE 3 (document_matches) ──→ FASE 4 (item_matches) ──→ FASE 6 (scope cache)
```

Fases 2 e 3 podem ser feitas em paralelo.
Fase 5 depende de 2. Fase 6 depende de 3+4.

---

## 6. Criterios de Aceite por Fase

| Fase | Criterio | Como verificar |
|------|----------|----------------|
| 1 | Testes baseline passam com codigo atual | `pytest tests/test_xc_baseline.py -v` |
| 2 | nfe_group_totals populada apos upload XML | Query + teste unitario |
| 3 | document_matches populada apos build_all() | Query + teste unitario |
| 4 | item_matches populada com scores corretos | Query + teste unitario |
| 5 | XC051 produz findings IDENTICOS ao baseline | Comparar snapshot JSON |
| 6 | 2a execucao mais rapida que 1a | Benchmark (print tempo) |

---

## 7. Riscos e Mitigacoes

| Risco | Mitigacao |
|-------|-----------|
| Regras XC quebram apos mudanca | Fase 1 cria baseline; cada fase compara contra ele |
| Performance piora com mais INSERTs | Agregados sao poucos (~50-200 rows por NF); batch INSERT |
| Cache desatualizado apos re-upload XML | DELETE CASCADE nas FKs; recomputar na re-importacao |
| Complexidade do DocumentScope dificulta serializar | Fases 3-4 salvam dados flat, nao o objeto inteiro |

---

## 8. Arquivos Criticos (Referencia Rapida)

| Arquivo | Linhas | O que faz |
|---------|--------|-----------|
| `src/services/cross_engine.py` | 1342-1407 | run() — orquestracao do Motor XC |
| `src/services/cross_engine.py` | 1113-1263 | run_xc051_c190_triangular() |
| `src/services/cross_engine_models.py` | 364-435 | DocumentScope dataclass |
| `src/services/cross_engine_models.py` | 354-362 | ItemPair dataclass |
| `src/services/cross_engine_models.py` | 35-41 | ItemMatchState enum |
| `src/services/document_scope_builder.py` | 280-404 | build_all() — 6 queries |
| `src/services/document_scope_builder.py` | 123-248 | Heuristica de matching |
| `src/services/xml_service.py` | 445-584 | upload_nfe_xmls() |
| `src/services/pipeline.py` | 307-331 | Chamada do Motor XC |
| `src/services/database.py` | 188-237 | Schema nfe_xmls/nfe_itens |
| `src/services/database_pg.py` | 39-135 | Migrations PostgreSQL |
| `tests/test_cross_engine.py` | 461-560 | TestXC051Triangular |

---

## 9. Estimativa

| Fase | Esforco | Pode paralelizar? |
|------|---------|-------------------|
| 1 — Baseline testes | 1 dia | Nao (precisa ser primeiro) |
| 2 — nfe_group_totals | 1 dia | Sim (com fase 3) |
| 3 — document_matches | 1 dia | Sim (com fase 2) |
| 4 — item_matches | 1 dia | Nao (depende de 3) |
| 5 — XC051 otimizado | 0.5 dia | Nao (depende de 2) |
| 6 — Scope cache | 1 dia | Nao (depende de 3+4) |
| **Total** | **~5 dias** | |
