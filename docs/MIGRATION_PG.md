# Migracao PostgreSQL — SPED Audit

## Resumo

O banco de dados do SPED Audit foi migrado de **SQLite** para **PostgreSQL 16** como unico backend de producao.
O SQLite permanece apenas como mock leve para testes unitarios.

## Infraestrutura

### Docker Compose

```bash
# Subir apenas o banco
docker compose -f docker-compose.db.yml up -d

# Verificar saude
docker exec sped-db pg_isready -U sped -d sped_audit
```

| Parametro | Valor |
|-----------|-------|
| Container | `sped-db` |
| Imagem | `postgres:16-alpine` |
| Porta host | `5434` |
| Porta container | `5432` |
| Usuario | `sped` |
| Senha | `sped2026` |
| Banco | `sped_audit` |
| Volume | `sped-pgdata` |

### Variavel de Ambiente

```env
DATABASE_URL=postgresql://sped:sped2026@localhost:5434/sped_audit
```

**Obrigatoria** em producao. Sem ela, o sistema nao inicia.

---

## Schema Completo

O schema definitivo esta em `scripts/pg_schema.sql` (v16, 20 tabelas).

### Tabelas Principais

| Tabela | Descricao | Registros tipicos |
|--------|-----------|-------------------|
| `sped_files` | Arquivos SPED enviados | 1 por upload |
| `sped_records` | Linhas do SPED parseadas | 10k-500k por arquivo |
| `validation_errors` | Erros encontrados pela auditoria | 0-5k por arquivo |
| `nfe_xmls` | XMLs de NF-e vinculados | 0-5k por arquivo |
| `nfe_itens` | Itens das NF-e | 0-50k por arquivo |
| `nfe_cruzamento` | Divergencias XML x SPED (legacy) | 0-2k por arquivo |
| `cross_validation_findings` | Divergencias XC engine (v2) | 0-5k por arquivo |
| `corrections` | Correcoes aplicadas | 0-500 por arquivo |
| `audit_log` | Log de acoes | ilimitado |

### Tabelas de Contexto (Migration 14+)

| Tabela | Descricao |
|--------|-----------|
| `clientes` | Cadastro de contribuintes |
| `beneficios_ativos` | Beneficios fiscais por periodo |
| `emitentes_crt` | CRT dos emitentes (populado dos XMLs) |
| `validation_runs` | Snapshots de cada execucao |
| `xml_match_index` | Pareamento XML <-> C100 |
| `coverage_gaps` | Lacunas de cobertura |
| `fiscal_context_snapshots` | Contexto fiscal para audit trail |

### Tabelas Auxiliares

| Tabela | Descricao |
|--------|-----------|
| `cross_validations` | Validacoes cruzadas (legacy) |
| `embedding_metadata` | Metadados de embeddings |
| `ai_error_cache` | Cache de explicacoes IA |
| `sped_file_versions` | Versionamento original/retificador |
| `finding_resolutions` | Resolucoes de apontamentos |
| `suggested_action_types` | Tipos de acao sugerida |
| `field_equivalence_map` | Mapa de equivalencia campo SPED <-> XML |

### Controle de Versao

```sql
SELECT version FROM schema_version;  -- Esperado: 16
```

---

## Diferencas PG vs SQLite

| Aspecto | SQLite | PostgreSQL |
|---------|--------|------------|
| JSON | `json_extract(col, '$.key')` | `col->>'key'` (JSONB nativo) |
| ID auto | `INTEGER PRIMARY KEY AUTOINCREMENT` | `SERIAL PRIMARY KEY` |
| Upsert | `INSERT OR REPLACE` | `INSERT ... ON CONFLICT DO UPDATE` |
| Ignora dup | `INSERT OR IGNORE` | `INSERT ... ON CONFLICT DO NOTHING` |
| Datetime | `datetime('now')` | `NOW()` / `CURRENT_TIMESTAMP` |
| Indice JSON | Nao suportado | `GIN (fields_json)` |
| LIKE em JSONB | `fields_json LIKE '%x%'` | `CAST(fields_json AS TEXT) LIKE '%x%'` |
| Savepoint | Opcional | Obrigatorio para retry em transacao |
| Concorrencia | WAL (single writer) | MVCC (multi writer) |

---

## Aplicar Schema em Banco Novo

```bash
# Via Docker (automatico no primeiro boot)
docker compose -f docker-compose.db.yml up -d

# Manual (banco existente)
psql -U sped -d sped_audit -f scripts/pg_schema.sql
```

## Resetar Banco (desenvolvimento)

```bash
docker compose -f docker-compose.db.yml down -v
docker compose -f docker-compose.db.yml up -d
```

---

## Testes

Testes unitarios usam SQLite in-memory via `init_audit_db(":memory:")`.
O schema SQLite e mantido em `database.py` apenas para testes e replica o schema PG.

Para rodar testes contra PostgreSQL real:

```bash
DATABASE_URL=postgresql://sped:sped2026@localhost:5434/sped_test pytest tests/
```

---

## Arquivos Relevantes

| Arquivo | Funcao |
|---------|--------|
| `scripts/pg_schema.sql` | Schema PG definitivo (source of truth) |
| `docker-compose.db.yml` | Docker do PostgreSQL |
| `src/services/database.py` | Conexao + schema SQLite (testes) |
| `src/services/database_pg.py` | Wrapper PG -> interface SQLite-compativel |
| `src/services/db_types.py` | Tipo `AuditConnection` (Union SQLite/PG) |
| `api/deps.py` | Dependency injection da conexao |
