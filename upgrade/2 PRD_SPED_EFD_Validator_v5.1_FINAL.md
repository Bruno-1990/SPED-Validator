# PRD — SPED EFD Validator · Edição Definitiva
## Auditoria Fiscal ICMS/IPI — Dual-Path · Context-First · Fechamento de Apuração

**Central Contábil — Uso Interno | Abril 2026**
**Versão:** 5.1.0-final
**Escopo:** EFD ICMS/IPI exclusivamente — PIS/COFINS parseados para consistência estrutural, fora do escopo de validação de conteúdo. EFD Contribuições em sistema separado.
**Histórico:** Consolida PRD v3 Context-First + PRD v4.1 Dual-Path + PRD v5.0 Fechamento + PLANO_MELHORIAS_v5

---

## Índice

1. [Visão do Produto e Diagnóstico](#1-visão-do-produto-e-diagnóstico)
2. [Princípio Arquitetural: Context-First](#2-princípio-arquitetural-context-first)
3. [Stage 0 — Montagem de Contexto Obrigatória](#3-stage-0--montagem-de-contexto-obrigatória)
4. [BeneficioEngine](#4-beneficioengine)
5. [Schema de Banco de Dados — Migration 13](#5-schema-de-banco-de-dados--migration-13)
6. [Pipeline Dual-Path](#6-pipeline-dual-path)
7. [Frontend — Interface de Seleção de Trilha](#7-frontend--interface-de-seleção-de-trilha)
8. [Trilha A — Motor de Validação SPED (ICMS/IPI)](#8-trilha-a--motor-de-validação-sped-icmsipi)
9. [Encadeamento Fiscal Completo](#9-encadeamento-fiscal-completo)
10. [Trilha B — Motor de Cruzamento SPED × XML](#10-trilha-b--motor-de-cruzamento-sped--xml)
11. [Mapeamento de Campos SPED ↔ XML (ICMS/IPI)](#11-mapeamento-de-campos-sped--xml-icmsipi)
12. [Catálogo de Error Types — ICMS/IPI](#12-catálogo-de-error-types--icmsipi)
13. [Correções Críticas Obrigatórias](#13-correções-críticas-obrigatórias)
14. [Camada de IA — Cache e Explicabilidade](#14-camada-de-ia--cache-e-explicabilidade)
15. [Score de Risco Fiscal e Cobertura](#15-score-de-risco-fiscal-e-cobertura)
16. [Especificação de API](#16-especificação-de-api)
17. [Requisitos de Relatório](#17-requisitos-de-relatório)
18. [Casos de Borda Fiscais](#18-casos-de-borda-fiscais)
19. [Plano de Testes e Critérios de Aceite](#19-plano-de-testes-e-critérios-de-aceite)
20. [Roadmap de Entrega](#20-roadmap-de-entrega)
21. [Glossário Técnico-Fiscal](#21-glossário-técnico-fiscal)
22. [Base Legal de Referência](#22-base-legal-de-referência)

---

## 1. Visão do Produto e Diagnóstico

### 1.1 Objetivo Central

Transformar o SPED EFD Validator em uma plataforma de **auditoria fiscal automatizada de ICMS/IPI** com dois caminhos de execução explícitos e independentes, operando como um auditor fiscal que conhece o contexto completo do contribuinte — regime tributário, benefícios fiscais ativos e CRT dos emitentes — **antes** de qualquer comparação.

> **Premissa:** O validador deve encontrar e documentar tudo que a SEFAZ-ES e a RFB encontrariam em uma autuação. Cada apontamento deve ser defensável em termos de legislação específica.

---

### 1.2 Diagnóstico — Problemas Raiz Identificados

#### Críticos — Corrupção de Resultados

| # | Problema | Impacto |
|---|---|---|
| P1 | **Detecção de regime por `IND_PERFIL`** — campo indica nível de escrituração, não regime fiscal | Todas as validações de CST e benefício estão erradas para Simples Nacional com Perfil A |
| P2 | **CRT do emitente não persiste** — `crt_emitente` ausente de `nfe_xmls` | Falso positivo em cada NF-e de fornecedor SN (CST vs CSOSN) |
| P3 | **Benefícios fiscais não auditados contra XML** — JSONs COMPETE/FUNDAP/INVEST existem mas nenhuma regra XML os consulta | A verificação mais importante da SEFAZ-ES não é executada |
| P4 | **ST sem MVA** — recálculo valida apenas ICMS-ST já escriturado, não detecta BC subdimensionada | Principal fonte de autuação em ST não detectada |
| P5 | **NF cancelada não detectada** — `COD_SIT` do C100 não cruza com `cStat` do XML | Escrituração de nota cancelada passa sem erro |
| P6 | **DELETE não-atômico** — pipeline apaga todos os erros ao iniciar sem transação | Janela de "zero erros" durante revalidação |

#### Altos — Lacunas de Cobertura

| # | Problema | Impacto |
|---|---|---|
| P7 | **Período dos XMLs não validado** — XMLs de outro mês geram centenas de falsos positivos | Resultados de cruzamento não confiáveis |
| P8 | **Cobertura binária no audit-scope** — reporta `xml_crossref=ok` com 40% sem XML | Falsa segurança sobre abrangência da auditoria |
| P9 | **Cache IA com chave incompleta** — CST 040 e CST 090 compartilham a mesma explicação | Explicações incorretas para erros distintos |
| P10 | **Encadeamento C190→E110→E111→E116 incompleto** | Fechamento de apuração não auditado |
| P11 | **Modo dev sem autenticação** — API_KEY ausente aceita qualquer valor | Risco de segurança em dados fiscais de clientes |
| P12 | **Tolerância única R$ 0,02** — inadequada para itens de alto valor | Falsos positivos em indústria e comércio atacadista |

---

### 1.3 O Que Este PRD Especifica

1. **Stage 0 obrigatório** — contexto completo antes de qualquer validação
2. **BeneficioEngine** — módulo dedicado que responde perguntas fiscais sobre benefícios ES
3. **Migration 13** — tabelas mestres de clientes, benefícios e CRT de emitentes
4. **Pipeline dual-path** — `SPED_ONLY` e `SPED_XML_RECON` como fluxos completamente distintos
5. **Encadeamento fiscal completo** — Documento → Item → Consolidação → Apuração → Benefício
6. **Cruzamento XML campo a campo** — 45+ campos mapeados com `FieldComparator` tipado
7. **Score de risco e nota de cobertura** — métricas mensuráveis por auditoria
8. **Correções críticas P1–P12** — nenhuma nova feature sem esses fixes

### 1.4 Fora do Escopo

- EFD Contribuições (PIS/COFINS em nível de detalhe) — módulo separado
- Conexão em tempo real com portal SEFAZ-ES para verificar protocolo de NF-e
- Validação multi-período com carryover de CIAP
- Bloco G (CIAP) — fase posterior

---

## 2. Princípio Arquitetural: Context-First

> **Regra-mãe:** O motor de validação nunca deve descobrir o regime tributário ou os benefícios ativos *durante* a validação. Todos esses dados são montados, validados e injetados **antes** do primeiro registro do SPED ser verificado.

Se o contexto estiver incompleto — cliente não cadastrado, período sem regime definido — a validação é **bloqueada** com erro claro e acionável. Não existe validação parcial com contexto incompleto.

```
┌─────────────────────────────────────────────────────────────┐
│  Stage 0 — Montagem de Contexto (OBRIGATÓRIO, BLOQUEANTE)   │
│  Carrega: Cliente · Regime · Benefícios · CRTs emitentes    │
│  Instancia BeneficioEngine · Valida XMLs (modo B)          │
│  Resultado: ValidationContext completo e validado           │
└──────────────────────┬──────────────────────────────────────┘
                       │ context injetado em todos os estágios
         ┌─────────────┼─────────────────┐
         ▼             ▼                 ▼
    Stage 1        Stage 2          Stage 2.5
  Estrutural     Cruzamento       Cruzamento XML
   (SPED)      SPED interno     [MODO B APENAS]
         └─────────────┼─────────────────┘
                       ▼
                   Stage 3
              Enriquecimento + IA
                       ▼
              TROCA ATÔMICA de erros
              (delete → insert na mesma tx)
```

**Consequências arquiteturais inegociáveis:**
- O contexto é imutável após o Stage 0 — nenhum validador altera o contexto
- Cada regra recebe: `(record, context, errors_list)` — nunca busca contexto por conta própria
- `context_hash` é calculado no Stage 0 e armazenado em `validation_runs` — invalida cache quando contexto muda

---

## 3. Stage 0 — Montagem de Contexto Obrigatória

### 3.1 Fluxo do ContextBuilder

```python
def build_full_context(file_id: int, db: Database, mode: str) -> ValidationContext:
    """
    Stage 0 obrigatório. Falha com ContextBuildError se contexto incompleto.
    Nenhum DELETE é executado antes desta função completar com sucesso.
    """
    sped_meta = db.get_sped_meta(file_id)
    cnpj      = sped_meta.cnpj_contribuinte
    periodo   = Periodo(sped_meta.dt_ini, sped_meta.dt_fim)

    # 1. Cliente obrigatório — bloqueante
    cliente = db.get_cliente_by_cnpj(cnpj)
    if not cliente:
        raise ContextBuildError(
            code="CLIENTE_NAO_CADASTRADO",
            message=f"CNPJ {cnpj} não cadastrado no sistema. "
                    f"Cadastre o cliente com regime tributário antes de validar.",
            action="Ir para /clientes → Novo Cliente"
        )

    # 2. Regime — detectado por CSTs do SPED, confirmado pelo MySQL
    regime_cst    = detectar_regime_por_cst(file_id, db)   # SN se CST 101-900; Normal se 00-90
    regime_mysql  = cliente.regime_override or db.get_regime_mysql(cnpj)
    regime, regime_source = resolver_regime(regime_cst, regime_mysql)

    # 3. Benefícios ativos no período
    beneficios = db.get_beneficios_ativos(cliente.id, periodo)
    engine     = BeneficioEngine(cliente, beneficios, periodo.ini)

    # 4. CRTs dos emitentes (necessário para CST_AWARE)
    emitentes_sn = db.get_emitentes_sn()   # CNPJs com crt=1

    # 5. Caches do Bloco 0
    participantes = db.get_participantes(file_id)   # 0150
    produtos      = db.get_produtos(file_id)         # 0200
    naturezas     = db.get_naturezas(file_id)        # 0400

    # 6. Tabelas fiscais (lazy, marca ausentes)
    tabelas, ausentes = carregar_tabelas_fiscais()

    # 7. Regras vigentes para o período
    regras_ativas = filtrar_regras_por_vigencia(RULES_VERSION, periodo)

    # 8. Contexto XML (modo B apenas)
    xml_ctx = build_xml_context(file_id, db, periodo) if mode == "sped_xml" else None

    # 9. Bloquear se 0000 tem erros críticos de estrutura
    erros_0000 = validar_registro_0000(sped_meta)
    if erros_0000.has_critical():
        raise PipelineBlockedError(
            "Registro 0000 com erros críticos. Corrija a estrutura do "
            "arquivo antes de executar o cruzamento.",
            erros=erros_0000
        )

    return ValidationContext(
        file_id=file_id, cnpj=cnpj, periodo=periodo,
        cliente=cliente,
        regime=regime, regime_source=regime_source,
        beneficios_periodo=beneficios,
        beneficio_engine=engine,
        emitentes_sn=emitentes_sn,
        cst_validos_saida=engine.get_cst_validos_saida_all_cfops(),
        aliq_esperada_por_cfop=engine.get_aliq_map(),
        participantes=participantes,
        produtos=produtos,
        naturezas=naturezas,
        aliquotas_uf=tabelas.aliquotas_uf,
        fcp_uf=tabelas.fcp_uf,
        mva_ncm_uf=tabelas.mva_ncm_uf,
        tabelas_ausentes=ausentes,
        regras_ativas=regras_ativas,
        xml_ctx=xml_ctx,
        context_hash=_hash_context(regime, beneficios, RULES_VERSION),
        rules_version=RULES_VERSION,
    )
```

### 3.2 Detecção de Regime por CST (Correção P1)

```python
def detectar_regime_por_cst(file_id: int, db: Database) -> str:
    """
    Regime é detectado pelos CSTs reais do arquivo — NUNCA por IND_PERFIL.
    IND_PERFIL = nível de escrituração (A/B/C), NÃO é indicador de regime.
    """
    csts_usados = db.get_csts_distintos(file_id)   # CSTs de todos os C170/C190

    # CSTs da Tabela B (101-900) → Simples Nacional
    csts_sn = {c for c in csts_usados if c.isdigit() and int(c) >= 101}
    # CSOSN → Simples Nacional
    csosn   = {c for c in csts_usados if c in {"101","102","103","201","202","203",
                                                 "300","400","500","900"}}
    if csts_sn or csosn:
        return "SN"
    return "NORMAL"   # LP ou LR — diferenciado pelo regime_override ou MySQL

def resolver_regime(regime_cst: str, regime_mysql: str | None) -> tuple[str, str]:
    if regime_mysql is None:
        return regime_cst, "CST"
    if regime_cst == regime_mysql:
        return regime_cst, "CST+MYSQL"
    # Conflito: CST detectou SN mas MySQL diz Normal (ou vice-versa)
    # Regra: CST do arquivo é a evidência primária; MySQL é confirmatória
    return regime_cst, "CONFLITO"   # Gera WARNING no relatório — requer revisão manual
```

### 3.3 Validação de Período dos XMLs (Correção P7)

```python
def build_xml_context(file_id: int, db: Database, periodo: Periodo) -> XmlContext:
    xmls = db.get_nfe_xmls(file_id)
    if not xmls:
        return XmlContext.vazio()

    fora_periodo = [x for x in xmls if not periodo.contains(x.dh_emissao)]
    pct_fora     = len(fora_periodo) / len(xmls)

    if pct_fora > 0.10:
        raise ContextBuildError(
            code="XMLS_FORA_PERIODO",
            message=f"{len(fora_periodo)} de {len(xmls)} XMLs fora do período "
                    f"{periodo.ini}–{periodo.fim}. Verifique se os arquivos são do mês correto.",
            severity="warning_bloqueante",
            detalhe=[x.chave_nfe for x in fora_periodo]
        )

    chaves_c100 = db.get_chaves_c100(file_id)
    chaves_xml  = {x.chave_nfe for x in xmls if x.dentro_periodo}
    matched     = chaves_c100 & chaves_xml

    return XmlContext(
        xml_by_chave     = {x.chave_nfe: x for x in xmls},
        has_xmls         = True,
        cobertura_pct    = len(matched) / len(chaves_c100) if chaves_c100 else 1.0,
        matched          = matched,
        sem_xml          = chaves_c100 - chaves_xml,  # SPED sem XML
        sem_c100         = chaves_xml - chaves_c100,  # XML sem SPED
        fora_periodo     = {x.chave_nfe for x in fora_periodo},
    )
```

---

## 4. BeneficioEngine

### 4.1 Responsabilidade

O `BeneficioEngine` lê os JSONs de benefícios (COMPETE_ES_Atacadista, FUNDAP, INVEST_ES, etc.) e **responde perguntas fiscais concretas** no contexto do contribuinte. É instanciado uma vez no Stage 0 e fica disponível para todos os estágios.

### 4.2 Interface Pública Completa

```python
class BeneficioEngine:

    def __init__(self, cliente: ClienteInfo,
                 beneficios: list[BeneficioAtivo],
                 periodo: str,
                 json_dir: str = "data/JSON"):
        self._rules   = self._load_and_merge(beneficios, json_dir)
        self._periodo = periodo
        self._cliente = cliente

    # ── Consultas para validadores SPED ──────────────────────────────

    def get_cst_validos_saida(self, cfop: str) -> set[str]:
        """CSTs válidos para NF-e de saída dado CFOP e benefícios ativos."""

    def get_aliq_esperada(self, cfop: str, ncm: str | None = None) -> float | None:
        """Alíquota ICMS esperada. None = sem benefício aplicável ao CFOP/NCM."""

    def get_reducao_bc(self, cfop: str, ncm: str | None = None) -> float | None:
        """Percentual de redução de BC esperado. None = sem redução."""

    def is_ncm_no_escopo(self, ncm: str, codigo_beneficio: str) -> bool:
        """Verifica se o NCM está no escopo do benefício (ex: COMPETE atacadista)."""

    def get_aliq_map(self) -> dict[str, float]:
        """Mapa cfop_prefix → alíquota para todos os benefícios ativos."""

    def get_cst_validos_saida_all_cfops(self) -> set[str]:
        """União de todos os CSTs válidos para saídas, considerando todos os benefícios."""

    def get_debito_integral(self, cfop: str) -> bool:
        """
        Retorna True se o benefício ativo para o CFOP exige débito integral
        (não redução de alíquota). Ex: COMPETE Atacadista exige CST 00 com
        alíquota cheia no débito e crédito presumido separado via E111.
        """

    def get_conflitos_beneficios(self) -> list[str]:
        """
        Retorna lista de pares de benefícios mutuamente exclusivos ativos
        simultaneamente. Ex: ['COMPETE_ATACADISTA × COMPETE_ECOMMERCE'].
        Registrado como WARNING no contexto — auditor deve revisar.
        """

    # ── Auditoria de item (XML × benefício) ──────────────────────────

    def audit_item_xml(self, item: NFeItem, emitente_crt: int) -> list[BeneficioAuditResult]:
        """
        Audita um item da NF-e contra as regras de benefício ativo.
        Leva em conta: CRT do emitente, benefícios ativos, CFOP, NCM, período.
        Retorna lista de violações (vazia = OK).
        """

    # ── Resolução de CRT do emitente ─────────────────────────────────

    def get_crt_expected_cst_set(self, crt: int) -> tuple[str, set[str]]:
        """
        Retorna (campo_cst, valores_válidos) baseado no CRT do emitente.
        CRT 1 (Simples Nacional) → usa CSOSN, não CST_ICMS.
        """
        if crt == 1:
            return ("CSOSN", {"101","102","103","201","202","203","300","400","500","900"})
        # CRT 2 (SN Excesso de receita bruta) → validar como SN no contexto ICMS
        if crt == 2:
            return ("CSOSN", {"101","102","103","201","202","203","300","400","500","900"})
        # CRT 3 (Regime Normal)
        return ("CST_ICMS", {"00","10","20","30","40","41","50","51","60","70","90"})

    # ── Mapeamento CSOSN → CST para cruzamento SPED ──────────────────

    CSOSN_TO_CST: dict[str, str] = {
        "101": "00",   # Tributada com permissão de crédito
        "102": "20",   # Tributada sem permissão de crédito
        "103": "40",   # Isenção do ICMS para faixa de receita bruta
        "201": "10",   # Tributada com ST e com permissão de crédito
        "202": "10",   # Tributada com ST e sem permissão de crédito
        "203": "30",   # Isenção do ICMS para faixa de receita bruta com ST retida anteriormente
        "300": "41",   # Imune
        "400": "40",   # Não tributada pelo SN
        "500": "60",   # ICMS cobrado anteriormente por ST
        "900": "90",   # Outros
    }

    # ── Alertas de expiração ─────────────────────────────────────────

    def get_beneficios_expirando(self, dias: int = 90) -> list[BeneficioAtivo]:
        """Benefícios com competencia_fim dentro dos próximos N dias."""
```

### 4.4 Regras Fiscais Específicas por Benefício ES

| Benefício | CST Obrigatório | Alíquota Efetiva | Débito Integral? | Observação |
|---|---|---|---|---|
| COMPETE Atacadista | **00** | 3% (crédito presumido via E111) | **Sim** — alíquota cheia no débito, crédito presumido separa | Dec. 1.663-R/2005 |
| COMPETE E-commerce | **00** | 3–6% conforme faixa de faturamento | **Sim** | Dec. específico e-commerce |
| COMPETE Ind. Gráficas | **00** | Conforme decreto | **Sim** | Conforme ato concessório |
| COMPETE Papelão/Plástico | **00** | Conforme decreto | **Sim** | Conforme ato concessório |
| INVEST-ES Indústria | **51** | Diferimento parcial/total | Não — débito diferido | Dec. 1.599-R/2005 |
| INVEST-ES Importação | **51** | Diferimento na importação | Não | Conforme decreto |
| FUNDAP | **00** | Crédito sobre pauta de valores | Sim | Lei 2.508/1970 |

> **Regra de débito integral (COMPETE):** O sistema deve verificar que C190 de saídas apresenta CST 00 com `ALIQ_ICMS` igual à alíquota interna da UF (não 3%). O crédito presumido de 3% é ajuste via E111, não redução de alíquota em C170/C190. Se o contador reduzir a alíquota diretamente em C170, isso é `BENEFICIO_DEBITO_NAO_INTEGRAL`.

Quando o cliente tem COMPETE-ES Atacadista + FUNDAP ativos no mesmo período:
- CSTs válidos: **union** dos dois conjuntos (OR lógico)
- Alíquota: aplica a **mais favorável** para o CFOP em questão
- Conflitos (dois benefícios com alíquotas diferentes para o mesmo CFOP): registrar como `CONFLITO_BENEFICIOS` (warning) no contexto, alertar o auditor humano

---

## 5. Schema de Banco de Dados — Migration 13

### 5.1 Tabelas Mestres (novas)

```sql
-- Migration 13 — Dados mestres do contribuinte
CREATE TABLE clientes (
    id              INTEGER PRIMARY KEY,
    cnpj            TEXT UNIQUE NOT NULL,
    razao_social    TEXT NOT NULL,
    regime          TEXT NOT NULL
                    CHECK(regime IN ('LP','LR','SN','MEI','Imune','Isento')),
    regime_override TEXT,        -- sobrescreve RegimeDetector quando definido
    uf              TEXT DEFAULT 'ES',
    cnae_principal  TEXT,
    porte           TEXT CHECK(porte IN ('ME','EPP','Medio','Grande')),
    ativo           INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- Benefícios fiscais ativos por cliente e período
CREATE TABLE beneficios_ativos (
    id                  INTEGER PRIMARY KEY,
    cliente_id          INTEGER NOT NULL REFERENCES clientes(id),
    codigo_beneficio    TEXT NOT NULL,
                        -- 'COMPETE_ATACADISTA' | 'COMPETE_ECOMMERCE' |
                        -- 'COMPETE_IND_GRAFICAS' | 'COMPETE_PAPELAO' |
                        -- 'FUNDAP' | 'INVEST_ES_IMPORTACAO' | 'INVEST_ES_INDUSTRIA'
    tipo                TEXT NOT NULL,
                        -- 'credito_presumido' | 'diferimento' | 'reducao_bc' | 'isencao'
    competencia_inicio  TEXT NOT NULL,   -- 'YYYY-MM'
    competencia_fim     TEXT,            -- NULL = indeterminado
    ato_concessorio     TEXT,            -- decreto/portaria de concessão
    aliq_icms_efetiva   REAL,            -- ex: 0.03 = 3%; NULL = verificar JSON
    observacoes         TEXT,
    ativo               INTEGER DEFAULT 1
);

-- CRT dos emitentes (populado durante parsing de XMLs)
CREATE TABLE emitentes_crt (
    cnpj_emitente  TEXT PRIMARY KEY,
    crt            INTEGER NOT NULL
                   CHECK(crt IN (1, 2, 3)),
                   -- 1=SN | 2=SN excesso receita | 3=Regime Normal
    razao_social   TEXT,
    uf_emitente    TEXT,
    last_seen      TEXT DEFAULT (datetime('now')),
    fonte          TEXT DEFAULT 'xml'
                   CHECK(fonte IN ('xml', 'manual'))
);

-- Snapshot de cada execução de auditoria
CREATE TABLE validation_runs (
    id                 INTEGER PRIMARY KEY,
    file_id            INTEGER NOT NULL REFERENCES sped_files(id),
    mode               TEXT NOT NULL CHECK(mode IN ('sped_only','sped_xml')),
    cliente_id         INTEGER REFERENCES clientes(id),
    regime_usado       TEXT,
    regime_source      TEXT,      -- 'CST' | 'MYSQL' | 'CST+MYSQL' | 'CONFLITO'
    beneficios_json    TEXT,      -- JSON snapshot dos benefícios ativos
    context_hash       TEXT,      -- SHA256(regime + beneficios + rules_version)
    rules_version      TEXT,
    xml_cobertura_pct  REAL,
    executed_rules     INTEGER DEFAULT 0,
    skipped_rules      INTEGER DEFAULT 0,
    total_findings     INTEGER DEFAULT 0,
    coverage_score     REAL,
    started_at         TEXT DEFAULT (datetime('now')),
    finished_at        TEXT,
    status             TEXT DEFAULT 'running'
                       CHECK(status IN ('running','done','error','blocked'))
);

-- Índice de pareamento XML ↔ C100 (Trilha B)
CREATE TABLE xml_match_index (
    id            INTEGER PRIMARY KEY,
    run_id        INTEGER NOT NULL REFERENCES validation_runs(id),
    xml_id        INTEGER REFERENCES nfe_xmls(id),
    sped_c100_id  INTEGER REFERENCES sped_records(id),
    match_status  TEXT CHECK(match_status IN
                  ('matched','sem_xml','sem_c100','fora_periodo','cancelada')),
    chave_nfe     TEXT,
    confidence    REAL DEFAULT 1.0,
    reason        TEXT
);

-- Lacunas de cobertura registradas
CREATE TABLE coverage_gaps (
    id            INTEGER PRIMARY KEY,
    run_id        INTEGER NOT NULL REFERENCES validation_runs(id),
    gap_type      TEXT,   -- 'tabela_ausente' | 'regra_pulada' | 'xml_sem_par'
    description   TEXT,
    affected_rule TEXT,
    severity      TEXT CHECK(severity IN ('critical','high','medium','low'))
);

-- Índices
CREATE INDEX idx_clientes_cnpj ON clientes(cnpj);
CREATE INDEX idx_beneficios_cliente_periodo
    ON beneficios_ativos(cliente_id, competencia_inicio, competencia_fim);
CREATE INDEX idx_emitentes_crt ON emitentes_crt(cnpj_emitente);
CREATE INDEX idx_xml_match_run ON xml_match_index(run_id);
CREATE INDEX idx_coverage_gaps_run ON coverage_gaps(run_id);
```

### 5.2 Alterações em Tabelas Existentes

```sql
-- nfe_xmls — campos que estavam ausentes (Correção P2)
ALTER TABLE nfe_xmls ADD COLUMN crt_emitente  INTEGER;   -- 1/2/3
ALTER TABLE nfe_xmls ADD COLUMN uf_emitente   TEXT;
ALTER TABLE nfe_xmls ADD COLUMN uf_dest       TEXT;
ALTER TABLE nfe_xmls ADD COLUMN mod_nfe       INTEGER DEFAULT 55;  -- 55=NF-e, 65=NFC-e
ALTER TABLE nfe_xmls ADD COLUMN dentro_periodo INTEGER DEFAULT 1;
ALTER TABLE nfe_xmls ADD COLUMN c_sit         TEXT;      -- cStat do protocolo (100/101/135/110)
ALTER TABLE nfe_xmls ADD COLUMN content_hash  TEXT;      -- SHA256 para dedup

-- nfe_cruzamento — rastreabilidade ao nível de item
ALTER TABLE nfe_cruzamento ADD COLUMN nfe_item_id INTEGER REFERENCES nfe_itens(id);
ALTER TABLE nfe_cruzamento ADD COLUMN xml_xpath    TEXT;   -- XPath do campo divergente
ALTER TABLE nfe_cruzamento ADD COLUMN tipo_comp    TEXT;   -- EXACT|MONETARY|PERCENTAGE|CST_AWARE
```

---

## 6. Pipeline Dual-Path

### 6.1 Execução com DELETE Transacional (Correção P6)

```python
def run_pipeline(file_id: int,
                 mode: Literal["sped_only", "sped_xml"],
                 db: Database,
                 on_progress: Callable | None = None) -> None:

    # Stage 0 — DEVE completar antes de qualquer DELETE
    context = build_full_context(file_id, db, mode)
    run_id  = db.create_validation_run(file_id, context, mode)

    new_errors: list[ValidationError] = []

    # Estágios de validação — acumulam em memória
    run_stage_estrutural(context, new_errors, on_progress)        # Stage 1
    run_stage_cruzamento_sped(context, new_errors, on_progress)   # Stage 2

    if mode == "sped_xml":
        if not context.xml_ctx or not context.xml_ctx.has_xmls:
            raise PipelineError(
                code="XML_NAO_CARREGADO",
                message="Modo SPED×XML selecionado mas nenhum XML carregado. "
                        "Faça o upload dos XMLs antes de executar a validação."
            )
        run_stage_cruzamento_xml(context, new_errors, on_progress)  # Stage 2.5

    run_stage_enriquecimento(context, new_errors, on_progress)    # Stage 3

    # TROCA ATÔMICA — erros antigos só desaparecem quando os novos estão prontos
    with db.transaction():
        db.execute("DELETE FROM validation_errors WHERE file_id = ?", [file_id])
        db.execute("DELETE FROM xml_match_index WHERE run_id = ?", [run_id])
        db.bulk_insert("validation_errors", new_errors)
        db.finish_validation_run(run_id, context)

    on_progress and on_progress("done", context.xml_ctx.cobertura_pct if context.xml_ctx else None)
```

### 6.2 Eventos SSE por Modo

```
MODO SPED_ONLY (4 estágios):
  ① Montagem de Contexto  → { stage: 0, regime, beneficios_count, tabelas_ok }
  ② Estrutural            → { stage: 1, records_checked, errors_found }
  ③ Cruzamento SPED       → { stage: 2, rules_run, errors_found }
  ④ Enriquecimento + IA   → { stage: 3, enriched, score }
  ⑤ done                  → { total_errors, score, coverage_score }

MODO SPED_XML (5 estágios):
  ① Montagem de Contexto  → { stage: 0, regime, xmls_loaded, cobertura_pct }
  ② Estrutural            → { stage: 1, records_checked, errors_found }
  ③ Cruzamento SPED       → { stage: 2, rules_run, errors_found }
  ④ Cruzamento XML        → { stage: 2.5, nfes_checked, pairs_checked, divergencias }
  ⑤ Enriquecimento + IA   → { stage: 3, enriched, score }
  ⑥ done                  → { total_errors, score, xml_coverage_pct, total_comparisons }
```

---

## 7. Frontend — Interface de Seleção de Trilha

### 7.1 Tela Inicial — Decisão de Caminho

A tela inicial do módulo **não inicia mais no upload genérico**. O usuário escolhe a trilha antes de fazer qualquer upload.

```
┌────────────────────────────────────────────────────────────────────┐
│                                                                    │
│   [🏢  DISTRIBUIDORA EXEMPLO LTDA — 12.345.678/0001-90]           │
│   Regime: Lucro Presumido · UF: ES · Benefícios: COMPETE + FUNDAP │
│   [FUNDAP vence em 45 dias ⚠]  [ Editar cadastro ]               │
│   (ClientContextBadge — exibido quando cliente identificado)       │
│                                                                    │
├──────────────────────────────┬─────────────────────────────────────┤
│   📋  VALIDAÇÃO SPED         │  🔗  VALIDAÇÃO SPED × XML           │
│                              │                                     │
│  Auditoria completa da       │  Auditoria reconciliatória com      │
│  escrituração EFD ICMS/IPI   │  confronto campo a campo entre      │
│  com regime e benefícios     │  SPED e NF-e originais.             │
│  fiscais aplicados.          │                                     │
│                              │  Detecta: NF cancelada escriturada, │
│  ✔ Validação estrutural       │  CST/alíquota divergente por item,  │
│  ✔ Recálculo ICMS/IPI/ST     │  BC_ST com MVA incorreto e          │
│  ✔ Auditoria de benefícios   │  benefício fiscal não aplicado.     │
│  ✔ Encadeamento de apuração  │                                     │
│  ✔ Score de risco fiscal     │  ✔ Tudo da Validação SPED +         │
│                              │  ✔ Cruzamento XML 45+ campos         │
│  [ Iniciar Validação SPED ]  │  [ Iniciar SPED × XML ]             │
└──────────────────────────────┴─────────────────────────────────────┘
```

**Regra bloqueante:** Se `cliente === null` (CNPJ não cadastrado), ambos os cards são bloqueados com: *"Cliente não cadastrado. Cadastre antes de validar."* + botão `Cadastrar agora → /clientes`.

---

### 7.2 ClientContextBadge

Exibido acima dos cards em todas as telas. Mostra ao contador o contexto que será usado antes de iniciar.

```
┌──────────────────────────────────────────────────────────────────┐
│  🏢 DISTRIBUIDORA EXEMPLO LTDA — 12.345.678/0001-90             │
│  Regime: Lucro Presumido  │  UF: ES  │  CNAE: 4691-5/00         │
│  ──────────────────────────────────────────────────────────────  │
│  Benefícios ativos em Jan/2026:                                  │
│  ✅ COMPETE-ES Atacadista   alíq. efetiva: 3%  (vigência: aberta)│
│  ✅ FUNDAP                  diferimento     (vence Mar/2026) ⚠   │
│  ──────────────────────────────────────────────────────────────  │
│  Tabelas carregadas: ✅ Alíquotas UF  ✅ FCP  ✅ MVA  ✅ ST-ES  │
│  [ Editar cadastro do cliente ]                                  │
└──────────────────────────────────────────────────────────────────┘
```

`⚠` = benefício com `competencia_fim` dentro de 90 dias.
`🔴` = benefício expirado sendo usado no arquivo.

---

### 7.3 Trilha A — SPEDOnlyUploadPage (`/upload/sped`)

```
[ ClientContextBadge ]

[ Dropzone SPED EFD (.txt · até 100MB · upload em chunks) ]
  ↓ upload completo
[ Painel de Metadados: CNPJ · Razão Social · Período · UF · Perfil · Versão ]
[ Painel de Contexto: Regime detectado · Benefícios carregados · Tabelas ]

Estágios SSE:
  ① Montagem de Contexto   ② Estrutural
  ③ Cruzamento SPED        ④ Enriquecimento + IA

[ Botão "Validar SPED" — ativo após upload + contexto OK ]
```

---

### 7.4 Trilha B — SPEDXMLUploadPage (`/upload/sped-xml`)

```
[ ClientContextBadge ]

┌──────────────────────────┐  ┌────────────────────────────────────┐
│  📄  SPED EFD (.txt)     │  │  📦  NF-e XMLs (.xml)              │
│                          │  │                                    │
│  Arraste ou selecione    │  │  Múltiplos arquivos simultâneos    │
│  o arquivo SPED          │  │  Upload paralelo em chunks         │
│                          │  │                                    │
│  [ ✓ sped_jan26.txt ]    │  │  148 / 150 processados  98.7%      │
│  12.4 MB · Período OK    │  │  ✔ Autorizadas: 146                │
│                          │  │  ⚠ Canceladas: 2                   │
│                          │  │  ✗ Fora do período: 0              │
└──────────────────────────┘  └────────────────────────────────────┘

Cobertura documental: 94,2% (142/150 NF-e do SPED têm XML)
⚠ 8 NF-e sem XML — impacto estimado: R$ 43.200 em ICMS não cruzado

Estágios SSE:
  ① Montagem de Contexto  ② Estrutural
  ③ Cruzamento SPED       ④ Cruzamento XML (148 NF-e · 2.960 itens)
  ⑤ Enriquecimento + IA

[ Botão "Validar SPED + XMLs" — ativo quando AMBOS prontos ]
```

---

### 7.5 Página de Cadastro de Clientes (`/clientes`)

- CRUD de clientes (CNPJ, razão social, regime, CNAE, porte)
- Aba **Benefícios**: cadastro de benefícios ativos com vigência e ato concessório
- Importação em lote via CSV (para cadastrar a carteira completa)
- Indicador de "clientes sem regime definido" no dashboard
- Alerta 90 dias antes do vencimento de benefício

---

## 8. Trilha A — Motor de Validação SPED (ICMS/IPI)

### 8.1 Stage 1 — Validação Estrutural (Context-Aware)

| Validador | Adaptação por Regime | Adaptação por Benefício (ES) |
|---|---|---|
| `format_validator` | Nenhuma | Nenhuma |
| `intra_register_validator (C100)` | SN: aceita CST 6 dígitos (CSOSN); Normal: exige CST 2 dígitos | FUNDAP: VL_FRT pode ter tratamento diferenciado por decreto |
| `intra_register_validator (C170)` | SN: valida CSOSN em vez de CST; Normal: valida CST 00–90 | COMPETE Atacadista: ALIQ_ICMS pode ser 3% ou crédito presumido |
| `cst_validator` | SN: CSOSN; LP/LR: CST padrão | CSTs do conjunto `engine.get_cst_validos_saida(cfop)` |
| `simples_validator` | Ativo apenas se `regime=SN` | Verifica CSOSN permitidos por CNAE de cada benefício SN |
| `format_validator (CNPJ/CPF)` | Regime não altera | Nenhuma |

---

### 8.2 Stage 2 — Cruzamentos e Recálculo Tributário ICMS/IPI

#### A. Cruzamento C100 × C170 × C190

| Cruzamento | Campo C100 | Campo C170/C190 | Error Type |
|---|---|---|---|
| Soma ICMS dos itens | `VL_ICMS` | `SUM(C170.VL_ICMS)` | `CRUZAMENTO_DIVERGENTE` |
| Soma IPI dos itens | `VL_IPI` | `SUM(C170.VL_IPI)` | `CRUZAMENTO_DIVERGENTE` |
| Soma ST dos itens | `VL_ICMS_ST` | `SUM(C170.VL_ICMS_ST)` | `CRUZAMENTO_DIVERGENTE` |
| Soma VL_DOC | `VL_DOC` | `SUM(C170.VL_ITEM)` ± desc/frt/seg | `SOMA_DIVERGENTE` |
| C190 VL_BC por grupo | `C190.VL_BC_CONT` | `SUM(C170.VL_BC_ICMS)` por CST+CFOP+ALIQ | `C190_DIVERGE_C170` |
| C190 VL_ICMS por grupo | `C190.VL_ICMS_TOT` | `SUM(C170.VL_ICMS)` por CST+CFOP+ALIQ | `C190_DIVERGE_C170` |
| Combinação C190 sem lastro | `C190.(CST,CFOP,ALIQ)` | Ausente em C170 | `C190_COMBINACAO_INCOMPATIVEL` |

#### B. Recálculo de ICMS (Fórmulas)

```
ICMS_esperado = VL_BC_ICMS × (ALIQ_ICMS / 100)
Se benefício com reducao_bc: VL_BC_esperada = VL_ITEM × (1 - reducao_bc)
Se |VL_ICMS - ICMS_esperado| > tolerancia_proporcional → CALCULO_DIVERGENTE
```

#### C. Recálculo de ICMS-ST com MVA (Correção P4 — completo)

```python
# Etapa 1: Base ST com MVA original
mva = ctx.mva_ncm_uf.get(f"{ncm}|{uf_dest}")
if mva is None:
    gerar ST_MVA_NAO_MAPEADO(warning)
    return  # pular recálculo ST para este item

BC_ST = (VL_ITEM + VL_FRT + VL_SEG + VL_OUT_DA - VL_DESC) * (1 + mva/100)

# Etapa 2: Ajuste para remetente Simples Nacional
if cnpj_remetente in ctx.emitentes_sn:
    aliq_inter = aliq_interestadual(uf_origem, uf_dest)  # 4%, 7% ou 12%
    aliq_int   = ctx.aliquotas_uf[uf_dest]
    BC_ST = BC_ST * (1 - aliq_inter / aliq_int)  # MVA ajustado

# Etapa 3: ICMS-ST esperado
ICMS_ST_esp = (BC_ST * ALIQ_ST/100) - VL_ICMS_proprio

# Etapa 4: Divergência
if abs(VL_ICMS_ST - ICMS_ST_esp) > tolerancia_proporcional(VL_ITEM):
    gerar ST_MVA_DIVERGENTE(expected_value=ICMS_ST_esp)
```

#### D. Recálculo de IPI

```
IPI_esperado = VL_BC_IPI × (ALIQ_IPI / 100)
Verificar reflexo na BC ICMS quando CST IPI tributado:
  BC_ICMS deve incluir VL_IPI se contribuinte for industrial (IND_ATIV=0)
```

#### E. Validações CST ICMS (Context-Aware)

| Regra | Condição | Error Type |
|---|---|---|
| CST inválido para o regime | SN usando CST 00-90 (sem CSOSN) | `CST_REGIME_INCOMPATIVEL` |
| CST 20 sem redução | `VL_RED_BC = 0` | `CST_020_SEM_REDUCAO` |
| CST 40/41 com ICMS > 0 | Isenção mas com débito | `ISENCAO_INCONSISTENTE` |
| CST tributado com ALIQ = 0 | CST 00/10/20 e ALIQ_ICMS = 0 | `CST_ALIQ_ZERO_FORTE` |
| CST incompatível com CFOP | CST 40 (isento) + CFOP 5102 (tributado) | `CST_CFOP_INCOMPATIVEL` |
| **CST incompatível com benefício ativo** | CST não está em `engine.get_cst_validos_saida(cfop)` | `SPED_CST_BENEFICIO` |
| **Alíquota incompatível com benefício** | ALIQ_ICMS ≠ `engine.get_aliq_esperada(cfop, ncm)` | `SPED_ALIQ_BENEFICIO` |
| ICMS > 0 com benefício que zera | Benefício com `aliq_icms_efetiva=0` e VL_ICMS > 0 | `SPED_ICMS_DEVERIA_ZERO` |
| BC diverge da redução do benefício | VL_BC_ICMS ≠ VL_ITEM × (1 - `reducao_bc`) | `SPED_BC_REDUCAO_DIVERGE` |
| ICMS zerado sem benefício ativo | CFOP saída (5/6xxx) e VL_ICMS = 0 sem benefício | `SPED_ICMS_ZERADO_SEM_BENEFICIO` |

#### F. Validação DIFAL (EC 87/2015 + LC 190/2022)

| Regra | Condição | Error Type |
|---|---|---|
| DIFAL faltante | CFOP 6xxx, consumidor final, sem E300 para UF destino | `DIFAL_FALTANTE_CONSUMO_FINAL` |
| DIFAL indevido em revenda | CFOP 6xxx, destinatário contribuinte, com DIFAL | `DIFAL_INDEVIDO_REVENDA` |
| Alíquota interna incorreta | `ALIQ_ICMS_DIFAL ≠ ctx.aliquotas_uf[uf_dest]` | `DIFAL_ALIQ_INTERNA_INCORRETA` |
| FCP ausente | `ctx.fcp_uf[uf_dest] > 0` sem FCP no E300 | `DIFAL_FCP_AUSENTE` |
| Base DIFAL inconsistente | `VL_BC_ICMS_DIFAL ≠ VL_OPR` | `DIFAL_BASE_INCONSISTENTE` |

#### G. Validação de NCM × Benefício

Para cada item com benefício ativo, verificar se o NCM está no escopo:

```python
if not engine.is_ncm_no_escopo(ncm, beneficio.codigo_beneficio):
    gerar NCM_FORA_ESCOPO_BENEFICIO(warning,
        message=f"NCM {ncm} não está no escopo do benefício {beneficio.codigo_beneficio}. "
                f"Verificar se a fruição é correta para este produto.")
```

---

## 9. Encadeamento Fiscal Completo

O sistema deve validar não apenas campos isolados, mas a **cadeia lógica completa** da apuração ICMS/IPI.

### 9.1 Cadeia de Apuração ICMS

```
C100 (Documento)
  └─ C170 (Itens)         → Recálculo ICMS/IPI/ST por item
       └─ C190 (Consolid.) → Totalização por CST+CFOP+ALIQ
            └─ E110 (Apuração) → Débitos − Créditos = Saldo
                 └─ E111 (Ajustes) → Benefícios, créditos presumidos
                      └─ E116 (Recolhimentos) → GNREs, códigos de receita
```

### 9.2 Trilhas de Fechamento Obrigatórias

#### Trilha 1: Documento → Item → Consolidação

| Verificação | Registros | Error Type |
|---|---|---|
| Soma VL_ICMS C170 fecha com C100 | C100 × SUM(C170.VL_ICMS) | `CRUZAMENTO_DIVERGENTE` |
| Soma VL_IPI C170 fecha com C100 | C100 × SUM(C170.VL_IPI) | `CRUZAMENTO_DIVERGENTE` |
| Soma VL_ICMS_ST C170 fecha com C100 | C100 × SUM(C170.VL_ICMS_ST) | `CRUZAMENTO_DIVERGENTE` |
| Soma VL_DOC C170 fecha com C100 | C100.VL_DOC vs SUM(C170.VL_ITEM) ± desc/frt/seg | `SOMA_DIVERGENTE` |
| C100 sem nenhum C170 | C100 × C170 | `C100_SEM_ITENS` (warning) |
| C170 sem C100 pai (órfão) | C170 órfão | `C170_ORFAO` (error, objetivo) |
| Todos os C170 têm C190 correspondente | C170 × C190 por CST+CFOP+ALIQ | `C190_DIVERGE_C170` |
| C190 sem lastro em C170 | C190 × C170 | `C190_COMBINACAO_INCOMPATIVEL` |
| Grupo CST+CFOP+ALIQ em C170 sem C190 | C170 → C190 | `C190_AUSENTE_PARA_GRUPO` (warning) |

#### Trilha 2: Consolidação → Apuração

| Verificação | Registros | Fórmula Completa | Error Type |
|---|---|---|---|
| C190 alimenta E110 débitos | C190 saídas → E110.VL_TOT_DEBITOS | `SUM(C190.VL_ICMS_TOT) CFOP 5/6/7 + E110.VL_OUT_DEBITOS ≈ E110.VL_TOT_DEBITOS` | `APURACAO_DEBITO_DIVERGENTE` |
| C190 alimenta E110 créditos | C190 entradas → E110.VL_TOT_CREDITOS | `SUM(C190.VL_ICMS_TOT) CFOP 1/2/3 + E110.VL_OUT_CREDITOS + E110.VL_SLD_CREDOR_ANT ≈ E110.VL_TOT_CREDITOS` | `APURACAO_CREDITO_DIVERGENTE` |
| Saldo E110 fecha | E110 | `VL_SLD_APURADO = VL_TOT_DEBITOS − VL_TOT_CREDITOS` | `APURACAO_SALDO_DIVERGENTE` |
| E111 débitos fecham com E110 | E111 × E110 | `SUM(E111.VL_AJ_APUR) débitos ≈ E110.VL_OUT_DEBITOS` | `E110_OUT_DEBITOS_INCONSISTENTE` |
| E111 créditos fecham com E110 | E111 × E110 | `SUM(E111.VL_AJ_APUR) créditos ≈ E110.VL_OUT_CREDITOS` | `E110_OUT_CREDITOS_INCONSISTENTE` |

> **`VL_SLD_CREDOR_ANT`:** Saldo credor transportado do período anterior. Sem este campo na fórmula, qualquer empresa com crédito acumulado geraria `APURACAO_CREDITO_DIVERGENTE` falso. Obrigatório incluir na verificação.

#### Trilha 3: Ajuste → Recolhimento (E111 × E116)

| Verificação | Registros | Condição | Error Type |
|---|---|---|---|
| Código de ajuste válido para a UF | E111 × `codigos_ajuste_uf.yaml` | `E111.COD_AJ_APUR` não consta na tabela 5.1.1 da UF | `CODIGO_AJUSTE_INVALIDO_UF` |
| E111 com benefício sem cadastro | E111 × `beneficios_ativos` | Código de benefício em E111 não cadastrado no período | `BENEFICIO_NAO_ATIVO` |
| **E116 obrigatório se há ICMS a recolher** | E116 × E110 | `E110.VL_ICMS_RECOLHER > 0` e nenhum E116 registrado | **`E116_AUSENTE_COM_ICMS_RECOLHER`** (error, objetivo) |
| **Soma E116 fecha com ICMS a recolher** | E116 × E110 | `SUM(E116.VL_OR) ≈ E110.VL_ICMS_RECOLHER` | **`E116_SOMA_DIVERGE_ICMS_RECOLHER`** (error, objetivo) |
| Código de receita E116 válido | E116 | `E116.COD_OR` inválido para o tipo de ICMS | `E116_CODIGO_RECEITA_INVALIDO` (warning) |

> **Por que E116 é crítico:** A SEFAZ-ES cruza os E116 com os pagamentos de GNRE/DAE. Se o ICMS a recolher existe mas o E116 não foi escriturado, há declaração de débito sem recolhimento — gatilho automático de malha.

| Verificação | Condição | Error Type |
|---|---|---|
| Benefício ativo sem ajuste E111 | `ctx.beneficios_periodo` não vazio e E111 ausente | `BENEFICIO_SEM_AJUSTE_E111` |
| Ajuste E111 sem benefício cadastrado | E111 com código de benefício não cadastrado | `AJUSTE_SEM_BENEFICIO_CADASTRADO` |
| Benefício com débito integral exigido | Benefício que exige débito integral + C190 com alíq reduzida | `BENEFICIO_DEBITO_NAO_INTEGRAL` |
| Crédito presumido calculado errado | E111.VL_AJ_APUR ≠ SUM(C190.VL_ICMS_TOT × fator_beneficio) | `CREDITO_PRESUMIDO_DIVERGENTE` |
| Benefício não ativo no período | E111 com código de benefício em período sem `beneficios_ativos` | `BENEFICIO_FORA_VIGENCIA` |
| CNAE incompatível com benefício | CNAE do cliente não elegível ao benefício | `BENEFICIO_CNAE_INELEGIVEL` |
| Sobreposição de benefícios incompatíveis | Dois E111 com benefícios mutuamente exclusivos | `SOBREPOSICAO_BENEFICIOS` |

#### Trilha 4: ICMS-ST na Apuração

| Verificação | Registros | Error Type |
|---|---|---|
| ST escriturado em E210 bate com C170 | E210.VL_ICMS_RECOL_ST ≈ SUM(C170.VL_ICMS_ST) saídas | `ST_APURACAO_DIVERGENTE` |
| Retenção ST em E210 bate com C100 entradas | E210.VL_RETENCAO_ST ≈ SUM(C100.VL_ICMS_ST) entradas | `ST_RETENCAO_DIVERGENTE` |

#### Trilha 5: IPI na Apuração

| Verificação | Registros | Error Type |
|---|---|---|
| IPI E500 bate com C170 | E510 × SUM(C170.VL_IPI) por CST_IPI | `IPI_APURACAO_DIVERGENTE` |
| CST IPI monetário sem valor | CST IPI tributado com VL_IPI = 0 | `IPI_CST_MONETARIO_ZERADO` |
| Reflexo IPI na BC ICMS | BC_ICMS deve incluir VL_IPI se industrial | `IPI_REFLEXO_BC_AUSENTE` |

---

## 10. Trilha B — Motor de Cruzamento SPED × XML

### 10.1 Algoritmo de Pareamento

```python
def parear_nfes(xml_ctx: XmlContext, c100_records: list, run_id: int, db: Database):
    """Executa o pareamento entre XMLs e C100, populando xml_match_index."""

    for c100 in c100_records:
        chave = c100.fields["CHV_NFE"]
        xml   = xml_ctx.xml_by_chave.get(chave)

        if not xml:
            db.insert_match(run_id, xml_id=None, c100_id=c100.id,
                            status="sem_xml", chave=chave)
            gerar XML002(c100)   # NF-e no SPED sem XML
            continue

        if xml.dentro_periodo == 0:
            db.insert_match(run_id, xml_id=xml.id, c100_id=c100.id,
                            status="fora_periodo", chave=chave)
            gerar XML020(c100, xml)
            continue

        # Verificar se NF cancelada está escriturada como ativa
        if xml.c_sit in ("101", "135") and c100.fields["COD_SIT"] == "00":
            gerar NF_CANCELADA_ESCRITURADA(c100, xml)

        db.insert_match(run_id, xml_id=xml.id, c100_id=c100.id,
                        status="matched", chave=chave)

    for chave, xml in xml_ctx.xml_by_chave.items():
        if chave not in {c.fields["CHV_NFE"] for c in c100_records}:
            gerar XML001(xml)   # XML sem C100
```

### 10.2 FieldComparator — Motor de Comparação Tipado

```python
class FieldComparator:
    """
    Motor de comparação tipado. Cada campo do field_map.yaml especifica
    qual tipo de comparação aplicar.
    """

    def compare(self, sped_val, xml_val, field_def, context) -> CompareResult:
        tipo = field_def["tipo"]
        match tipo:
            case "EXACT"      : return self._exact(sped_val, xml_val)
            case "MONETARY"   : return self._monetary(sped_val, xml_val,
                                                       field_def["tolerancia"],
                                                       context)
            case "PERCENTAGE" : return self._percentage(sped_val, xml_val)
            case "DATE"       : return self._date(sped_val, xml_val)
            case "CST_AWARE"  : return self._cst_aware(sped_val, xml_val, context)
            case "DERIVED"    : return self._derived(sped_val, xml_val, field_def)
            case "SKIP"       : return CompareResult.SKIP

    def _monetary(self, sped, xml, tol_fixo, context) -> CompareResult:
        """Tolerância proporcional à magnitude do valor."""
        sped_d = Decimal(str(sped or 0))
        xml_d  = Decimal(str(xml or 0))
        diff   = abs(sped_d - xml_d)
        tol    = tolerancia_proporcional(float(sped_d))  # BUG-005 corrigido
        if diff <= tol:
            return CompareResult.ok()
        return CompareResult.diverge(sped_val=sped, xml_val=xml,
                                     diferenca=float(diff),
                                     percentual=float(diff/sped_d*100) if sped_d else None)

    def _cst_aware(self, sped_cst, xml_cst, context) -> CompareResult:
        """
        Compara CST ou CSOSN dependendo do CRT do emitente.
        Corrige P2: falsos positivos para fornecedor SN.
        """
        emitente_sn = xml_cst in context.emitentes_sn  # CRT=1 ou CRT=2
        if emitente_sn:
            # XML usa CSOSN → mapear para CST equivalente esperado no SPED
            expected_cst = BeneficioEngine.CSOSN_TO_CST.get(xml_cst)
            if sped_cst != expected_cst:
                return CompareResult.diverge(
                    sped_val=sped_cst, xml_val=xml_cst,
                    nota=f"Emitente SN (CRT=1): CSOSN {xml_cst} → "
                         f"CST esperado no SPED: {expected_cst}"
                )
        else:
            if sped_cst != xml_cst:
                return CompareResult.diverge(sped_val=sped_cst, xml_val=xml_cst)
        return CompareResult.ok()

    def _exact(self, sped, xml) -> CompareResult:
        """Comparação exata após normalização."""
        n = lambda v: str(v or "").strip().upper().replace(".", "").replace("-", "")
        return CompareResult.ok() if n(sped) == n(xml) else \
               CompareResult.diverge(sped_val=sped, xml_val=xml)
```

### 10.3 Política de Campos Ausentes no XML

```
SPED tem valor, XML ausente:
  join_key=true  → ERROR "Campo obrigatório ausente no XML"
  MONETARY e XML=0/ausente → comparar contra 0.0 (legítimo para SN)
  campo opcional → WARN "Campo {campo} presente no SPED mas ausente no XML"

XML tem valor, SPED ausente ou zero:
  valor > tolerancia × 10 → ERROR
  valor ≤ tolerancia × 10 → WARN

Ambos ausentes ou zero → OK (sem divergência)
"0.00" vs ausente → tratar como equivalentes
```

### 10.4 Regras XML com Contexto de Benefício (Novas — Críticas)

#### XML018 — CST × Benefício Ativo

```
Aplicação: NF-e de SAÍDA (CFOP 5xxx/6xxx) do contribuinte auditado

Para cada item da NF-e:
  cst_validos = engine.get_cst_validos_saida(item.cfop)
  se item.cst_icms ∉ cst_validos:
    ERROR severity=high
    "CST {item.cst_icms} incompatível com benefício {beneficio.codigo} ativo
     no período {periodo}. CSTs válidos para CFOP {cfop}: {cst_validos}."
    campo_xml: "det[n].imposto.ICMS.CST"
    base_legal: beneficio.ato_concessorio
```

#### XML019 — Alíquota × Benefício Ativo

```
Para cada item com benefício ativo:
  aliq_esp = engine.get_aliq_esperada(item.cfop, item.ncm)
  se aliq_esp is not None:
    diff = abs(item.aliq_icms - aliq_esp)
    se diff > 0.001:
      ERROR severity=high
      "Alíq. ICMS {item.aliq_icms*100:.1f}% diverge do benefício {codigo}
       para CFOP {cfop}: esperado {aliq_esp*100:.1f}%."
      campo_xml: "det[n].imposto.ICMS.pICMS"
```

#### XML020 — Período dos XMLs

```
# Executado no Stage 0 (Context Builder)
Para cada XML fora do período DT_INI..DT_FIN:
  WARNING "NF-e chave {chave} com data {data} fora do período {periodo}.
           Excluída do cruzamento. Verifique se é do mês correto."
```

#### XML021 — Cobertura do Cruzamento

```python
cobertura_pct = xml_ctx.cobertura_pct * 100
n_sem_xml     = len(xml_ctx.sem_xml)
severity      = "high" if cobertura_pct < 80 else "medium" if cobertura_pct < 95 else "low"

message = (f"Cobertura: {cobertura_pct:.0f}% — {n_sem_xml} NF-e(s) do SPED "
           f"sem XML correspondente. Impacto em ICMS não cruzado estimado.")
detail  = list(xml_ctx.sem_xml)  # chaves das NF-es sem XML
```

---

## 11. Mapeamento de Campos SPED ↔ XML (ICMS/IPI)

### 11.1 field_map.yaml — Configuração Externalizada

O mapeamento é um arquivo YAML versionado. Mudanças de leiaute não exigem alteração de código Python.

```yaml
# data/config/field_map.yaml  ·  v2.0
# Foco: ICMS e IPI exclusivamente
# PIS/COFINS: mapeados apenas como reflexo de ICMS

version: "2.0"
namespace_nfe: "http://www.portalfiscal.inf.br/nfe"
xpath_base: "/NFe/infNFe"

tipos_comparacao:
  EXACT:      "Igualdade de string após normalização (trim, uppercase, remove pontuação)"
  MONETARY:   "Decimal com tolerância proporcional à magnitude (BUG-005)"
  PERCENTAGE: "Decimal com tolerância 0,001%"
  DATE:       "Normaliza para AAAA-MM-DD antes de comparar"
  CST_AWARE:  "CST ou CSOSN dependendo do CRT do emitente (CRT=1/2 → CSOSN)"
  DERIVED:    "Campo calculado sem equivalente direto — regra específica"
  SKIP:       "Sem equivalente no XML — não comparar"

c100_header:
  - sped_campo: CHV_NFE
    xml_xpath: ".//protNFe/infProt/chNFe"
    tipo: EXACT
    join_key: true
    descricao: "Chave 44 dígitos — join key entre SPED e XML"

  - sped_campo: NUM_DOC
    xml_xpath: ".//ide/nNF"
    tipo: EXACT
    normalizacao: "remover zeros à esquerda"

  - sped_campo: SER
    xml_xpath: ".//ide/serie"
    tipo: EXACT

  - sped_campo: COD_MOD
    xml_xpath: ".//ide/mod"
    tipo: EXACT
    descricao: "55=NF-e, 65=NFC-e"

  - sped_campo: DT_DOC
    xml_xpath: ".//ide/dhEmi"
    tipo: DATE
    normalizacao: "truncar horário — XML tem T00:00:00-03:00"
    regra_id: XML015
    severidade: medium

  - sped_campo: DT_E_S
    xml_xpath: ".//ide/dhSaiEnt"
    tipo: DATE
    opcional: true
    descricao: "Pode ser ausente em NF-e de entrada"

  - sped_campo: COD_SIT
    xml_xpath: ".//protNFe/infProt/cStat"
    tipo: DERIVED
    mapeamento:
      "100": "00"    # Autorizada → Normal
      "101": "02"    # Cancelada → Cancelada
      "135": "02"    # Cancelada fora do prazo → Cancelada
      "110": "05"    # Denegada → Denegada
      "301": "05"    # Denegada → Denegada
    regra_id: XML003_B
    descricao: "NF cancelada escriturada como ativa → ERROR crítico"
    severidade: critical

  - sped_campo: CNPJ_EMIT
    xml_xpath: ".//emit/CNPJ"
    tipo: EXACT
    normalizacao: "remover não-dígitos, pad 14"
    regra_id: XML_C100_CNPJ_EMIT
    severidade: critical

  - sped_campo: CNPJ_DEST
    xml_xpath: ".//dest/CNPJ"
    tipo: EXACT
    normalizacao: "remover não-dígitos ou CPF se PF"
    alternativa_xpath: ".//dest/CPF"

  - sped_campo: IE_DEST
    xml_xpath: ".//dest/IE"
    tipo: EXACT
    via: "0150.IE via COD_PART"
    regra_id: XML013

  - sped_campo: UF_DEST
    xml_xpath: ".//dest/enderDest/UF"
    tipo: EXACT
    via: "0150.UF via COD_PART"
    regra_id: XML014

  - sped_campo: VL_DOC
    xml_xpath: ".//total/ICMSTot/vNF"
    tipo: MONETARY
    regra_id: XML_C100_VL_DOC
    severidade: high

  - sped_campo: VL_ICMS
    xml_xpath: ".//total/ICMSTot/vICMS"
    tipo: MONETARY
    regra_id: XML_C100_VL_ICMS
    severidade: high
    contexto_beneficio: true   # verificar contra BeneficioEngine se aliq=0

  - sped_campo: VL_BC_ICMS
    xml_xpath: ".//total/ICMSTot/vBC"
    tipo: MONETARY
    regra_id: XML_C100_VL_BC
    severidade: high

  - sped_campo: VL_ICMS_ST
    xml_xpath: ".//total/ICMSTot/vST"
    tipo: MONETARY
    regra_id: XML_C100_VL_ST
    severidade: high

  - sped_campo: VL_IPI
    xml_xpath: ".//total/IPI/vIPI"
    tipo: MONETARY
    regra_id: XML_C100_VL_IPI
    severidade: high
    descricao: "Apenas NF-e industriais — ausente é válido"
    opcional: true

  - sped_campo: VL_DESC
    xml_xpath: ".//total/ICMSTot/vDesc"
    tipo: MONETARY
    severidade: medium

  - sped_campo: VL_FRT
    xml_xpath: ".//total/ICMSTot/vFrete"
    tipo: MONETARY
    severidade: medium

c170_items:
  - sped_campo: NUM_ITEM
    xml_xpath: "./@nItem"
    tipo: EXACT
    join_key: true
    descricao: "1-based — âncora de vinculação item XML ↔ C170"

  - sped_campo: COD_ITEM
    xml_xpath: "./prod/cProd"
    tipo: EXACT
    via: "0200.COD_ITEM"

  - sped_campo: NCM
    xml_xpath: "./prod/NCM"
    tipo: EXACT
    normalizacao: "remover não-dígitos, primeiros 8 chars"
    regra_id: XML009
    severidade: medium

  - sped_campo: CFOP
    xml_xpath: "./prod/CFOP"
    tipo: EXACT
    normalizacao: "remover não-dígitos, primeiros 4 chars"
    regra_id: XML007
    severidade: high

  - sped_campo: QTD
    xml_xpath: "./prod/qCom"
    tipo: MONETARY
    tolerancia: 0.001
    severidade: medium

  - sped_campo: VL_ITEM
    xml_xpath: "./prod/vProd"
    tipo: MONETARY
    regra_id: XML011_A
    severidade: high

  - sped_campo: VL_DESC
    xml_xpath: "./prod/vDesc"
    tipo: MONETARY
    severidade: medium
    opcional: true

  - sped_campo: CST_ICMS
    xml_xpath: "./imposto/ICMS/*/CST | ./imposto/ICMS/*/CSOSN"
    tipo: CST_AWARE
    regra_id: XML005
    severidade: high
    contexto_regime: true   # usa CRT do emitente para escolher CST vs CSOSN
    contexto_beneficio: true  # valida contra engine.get_cst_validos_saida
    descricao: "Se CRT=1/2 → usar CSOSN e mapear para CST via CSOSN_TO_CST"

  - sped_campo: VL_BC_ICMS
    xml_xpath: "./imposto/ICMS/*/vBC"
    tipo: MONETARY
    regra_id: XML_C170_VL_BC
    severidade: high
    contexto_beneficio: true  # verificar redução de BC do benefício

  - sped_campo: ALIQ_ICMS
    xml_xpath: "./imposto/ICMS/*/pICMS"
    tipo: PERCENTAGE
    regra_id: XML006
    severidade: high
    contexto_beneficio: true  # verificar contra engine.get_aliq_esperada

  - sped_campo: VL_ICMS
    xml_xpath: "./imposto/ICMS/*/vICMS"
    tipo: MONETARY
    regra_id: XML_C170_VL_ICMS
    severidade: high
    contexto_beneficio: true

  - sped_campo: VL_BC_ICMS_ST
    xml_xpath: "./imposto/ICMS/*/vBCST"
    tipo: MONETARY
    regra_id: XML_C170_VL_BC_ST
    severidade: high
    opcional: true
    contexto_mva: true   # revalidar contra MVA tabelado

  - sped_campo: ALIQ_ST
    xml_xpath: "./imposto/ICMS/*/pICMSST"
    tipo: PERCENTAGE
    regra_id: XML_C170_ALIQ_ST
    severidade: high
    opcional: true

  - sped_campo: VL_ICMS_ST
    xml_xpath: "./imposto/ICMS/*/vICMSST"
    tipo: MONETARY
    regra_id: XML_C170_VL_ICMS_ST
    severidade: high
    opcional: true

  - sped_campo: VL_IPI
    xml_xpath: "./imposto/IPI/*/vIPI"
    tipo: MONETARY
    regra_id: XML_C170_VL_IPI
    severidade: high
    opcional: true

  - sped_campo: CST_IPI
    xml_xpath: "./imposto/IPI/*/CST"
    tipo: EXACT
    severidade: medium
    opcional: true

  - sped_campo: ALIQ_IPI
    xml_xpath: "./imposto/IPI/*/pIPI"
    tipo: PERCENTAGE
    severidade: medium
    opcional: true

c190_xml_aggregation:
  descricao: |
    C190 não tem equivalente direto no XML. Verificação por agrupamento:
    Agrupar det[] do XML por (CST_ICMS, CFOP, pICMS) e somar valores.
    Comparar com C190 do SPED pelo mesmo grupo.
  algoritmo:
    1: "Para cada NF-e com XML: agrupar det[] por (CST, CFOP, pICMS)"
    2: "Somar: vBC_grupo, vICMS_grupo, vBCST_grupo, vICMSST_grupo"
    3: "Buscar C190 com (CST_ICMS, CFOP, ALIQ_ICMS) correspondente"
    4: "Comparar C190.VL_BC_CONT vs soma.vBC_grupo (tol R$0,01)"
    5: "Comparar C190.VL_ICMS_TOT vs soma.vICMS_grupo (tol R$0,01)"
    6: "Divergência → XML_C190_DIVERGE"
  regra_id: XML_C190_VL_BC
  severidade: high
```

### 11.2 Campos sem Equivalente no XML

| Campo SPED | Registro | Motivo |
|---|---|---|
| `IND_APUR` | C170 | Indicador de apuração — conceito existe apenas no SPED |
| `COD_CTA` | C170 | Código de conta contábil — dado do ERP, não da NF-e |
| `VL_ABAT_NT` | C100 | Abatimento por nota — campo fiscal do contribuinte |
| `TXT_COMPL` | C100 | Texto complementar livre |
| `IND_EMIT` | C100 | Derivado do CFOP — não existe na NF-e |
| `COD_NAT` | C170 | Natureza de operação — conceito do SPED |

---

## 12. Catálogo de Error Types — ICMS/IPI

### 12.1 Estruturais (Context-Aware)

| Error Type | Severidade | Certeza | Descrição |
|---|---|---|---|
| `FORMATO_INVALIDO` | error | objetivo | Campo com formato inválido (CNPJ, CPF, data, CEP, CFOP, NCM) |
| `MISSING_REQUIRED` | error | objetivo | Campo obrigatório ausente |
| `WRONG_TYPE` | error | objetivo | Campo numérico com valor não-numérico |
| `WRONG_SIZE` | error | objetivo | Valor excede tamanho máximo definido |
| `C170_ORFAO` | error | objetivo | Registro C170 sem C100 pai |
| `CST_REGIME_INCOMPATIVEL` | error | objetivo | CST da Tabela A em empresa SN (ou CSOSN em empresa Normal) |

### 12.2 Recálculo ICMS/ST

| Error Type | Severidade | Certeza | Auto-corrigível | Descrição |
|---|---|---|---|---|
| `CALCULO_DIVERGENTE` | error | objetivo | Sim | VL_ICMS ≠ VL_BC × (ALIQ/100) |
| `CALCULO_ARREDONDAMENTO` | warning | objetivo | Sim (aprovação) | Divergência dentro da tolerância proporcional |
| `ST_MVA_DIVERGENTE` | error | provável | Sim (aprovação) | BC_ICMS_ST incompatível com MVA tabelado |
| `ST_MVA_AUSENTE` | error | objetivo | Não | Produto sujeito a ST sem MVA calculado |
| `ST_MVA_NAO_MAPEADO` | warning | indício | Não | NCM/UF sem MVA na tabela de referência |
| `ST_ALIQ_INCORRETA` | error | objetivo | Não | Alíquota ST diferente da tabelada por NCM/UF |
| `ST_REGIME_REMETENTE` | warning | provável | Não | MVA ajustado não aplicado para remetente SN |
| `IPI_CST_MONETARIO_ZERADO` | error | objetivo | Não | CST IPI tributado com VL_IPI = 0 |
| `IPI_REFLEXO_BC_AUSENTE` | error | objetivo | Não | BC ICMS não inclui VL_IPI em empresa industrial |
| `IPI_APURACAO_DIVERGENTE` | error | objetivo | Não | E510 diverge de SUM(C170.VL_IPI) por CST_IPI |

### 12.3 CST e Semântica Fiscal

| Error Type | Severidade | Certeza | Descrição |
|---|---|---|---|
| `CST_INVALIDO` | error | objetivo | CST fora do domínio válido para o registro |
| `CST_020_SEM_REDUCAO` | error | objetivo | CST 020 e VL_RED_BC = 0 |
| `ISENCAO_INCONSISTENTE` | error | objetivo | CST 040/041 com VL_BC_ICMS > 0 |
| `TRIBUTACAO_INCONSISTENTE` | error | objetivo | CST 040/041 com VL_ICMS > 0 |
| `CST_ALIQ_ZERO_FORTE` | error | objetivo | CST tributado (00/10/20/70/90) com ALIQ_ICMS = 0 |
| `CST_ALIQ_ZERO_MODERADO` | warning | provável | CST 51/70 com ALIQ_ICMS = 0 (pode ter motivo) |
| `CST_CFOP_INCOMPATIVEL` | warning | provável | CST isento (40) com CFOP de venda tributada (5102) |
| `CST_HIPOTESE` | warning | provável | Hipótese de CST correto com expected_value |

### 12.4 Alíquotas

| Error Type | Severidade | Certeza | Descrição |
|---|---|---|---|
| `ALIQ_INTERESTADUAL_INVALIDA` | error | objetivo | ALIQ_ICMS em operação interestadual ≠ 4%, 7% ou 12% |
| `ALIQ_INTERNA_EM_INTERESTADUAL` | warning | provável | CFOP 6xxx com alíquota = alíquota interna da UF |
| `ALIQ_INTERESTADUAL_EM_INTERNA` | warning | provável | CFOP 5xxx com alíquota = 4%, 7% ou 12% |
| `ALIQ_ICMS_AUSENTE` | error | provável | ALIQ_ICMS vazia em item tributado — hipótese gerada |

### 12.5 Cruzamentos entre Blocos SPED

| Error Type | Severidade | Certeza | Descrição |
|---|---|---|---|
| `CRUZAMENTO_DIVERGENTE` | error | objetivo | C100 × SUM(C170): ICMS/IPI/ST não batem |
| `SOMA_DIVERGENTE` | error | objetivo | C100 × SUM(C170): VL_DOC não fecha |
| `CONTAGEM_DIVERGENTE` | error | objetivo | 9900 × contagem real de registros diverge |
| `C190_DIVERGE_C170` | error | objetivo | C190 × SUM(C170) por grupo CST+CFOP+ALIQ diverge |
| `C190_COMBINACAO_INCOMPATIVEL` | warning | provável | C190 com combinação CST+CFOP+ALIQ sem lastro em C170 |
| `REF_INEXISTENTE` | error | objetivo | COD_PART/COD_ITEM/COD_NAT referenciados mas ausentes no Bloco 0 |

### 12.6 Encadeamento de Apuração

| Error Type | Severidade | Certeza | Descrição |
|---|---|---|---|
| `E116_AUSENTE_COM_ICMS_RECOLHER` | error | objetivo | `E110.VL_ICMS_RECOLHER > 0` sem nenhum E116 registrado |
| `E116_SOMA_DIVERGE_ICMS_RECOLHER` | error | objetivo | `SUM(E116.VL_OR) ≠ E110.VL_ICMS_RECOLHER` |
| `E116_CODIGO_RECEITA_INVALIDO` | warning | provável | `E116.COD_OR` inválido para o tipo de ICMS |
| `E110_OUT_DEBITOS_INCONSISTENTE` | error | objetivo | `SUM(E111 débitos) ≠ E110.VL_OUT_DEBITOS` |
| `E110_OUT_CREDITOS_INCONSISTENTE` | error | objetivo | `SUM(E111 créditos) ≠ E110.VL_OUT_CREDITOS` |
| `C100_SEM_ITENS` | warning | objetivo | C100 sem nenhum C170 vinculado |
| `C190_AUSENTE_PARA_GRUPO` | warning | objetivo | Grupo CST+CFOP+ALIQ em C170 sem C190 correspondente |
| `APURACAO_CREDITO_DIVERGENTE` | error | objetivo | SUM(C190 entradas) ≠ E110.VL_TOT_CREDITOS |
| `APURACAO_SALDO_DIVERGENTE` | error | objetivo | E110: débitos − créditos + ajustes ≠ VL_SLD_APURADO |
| `ST_APURACAO_DIVERGENTE` | error | objetivo | SUM(C170.VL_ICMS_ST) saídas ≠ E210.VL_ICMS_RECOL_ST |
| `ST_RETENCAO_DIVERGENTE` | error | objetivo | SUM(C100.VL_ICMS_ST) entradas ≠ E210.VL_RETENCAO_ST |
| `CODIGO_AJUSTE_INVALIDO` | error | objetivo | E111.COD_AJ_APUR não consta na tabela 5.1.1 da UF |

### 12.7 Benefícios Fiscais

| Error Type | Severidade | Certeza | Descrição |
|---|---|---|---|
| `SPED_CST_BENEFICIO` | error | objetivo | CST incompatível com conjunto válido do benefício ativo |
| `SPED_ALIQ_BENEFICIO` | error | objetivo | ALIQ_ICMS ≠ alíquota efetiva do benefício para o CFOP |
| `SPED_ICMS_DEVERIA_ZERO` | error | provável | Benefício zera ICMS mas VL_ICMS > 0 |
| `SPED_BC_REDUCAO_DIVERGE` | error | provável | BC_ICMS ≠ VL_ITEM × (1 − redução_do_benefício) |
| `SPED_ICMS_ZERADO_SEM_BENEFICIO` | warning | indício | CFOP saída com VL_ICMS = 0 sem benefício cadastrado |
| `BENEFICIO_SEM_AJUSTE_E111` | error | provável | Benefício ativo no período sem ajuste E111 correspondente |
| `AJUSTE_SEM_BENEFICIO_CADASTRADO` | warning | provável | E111 com código de benefício não cadastrado em `beneficios_ativos` |
| `BENEFICIO_DEBITO_NAO_INTEGRAL` | error | provável | Benefício que exige débito integral com alíquota reduzida em C190 |
| `CREDITO_PRESUMIDO_DIVERGENTE` | error | provável | E111.VL_AJ_APUR ≠ SUM(C190.VL_ICMS_TOT × fator_beneficio) |
| `CREDITO_PRESUMIDO_ACIMA_DO_LIMITE` | error | objetivo | Crédito presumido calculado excede o limite máximo previsto no ato concessório |
| `BENEFICIO_FORA_VIGENCIA` | error | objetivo | Código de benefício usado fora da vigência cadastrada |
| `BENEFICIO_CNAE_INELEGIVEL` | error | objetivo | CNAE da empresa não está na lista de elegíveis do benefício |
| `SOBREPOSICAO_BENEFICIOS` | error | provável | Dois benefícios mutuamente exclusivos ativos simultaneamente |
| `NCM_FORA_ESCOPO_BENEFICIO` | warning | provável | NCM do item não está no escopo do benefício em fruição |

### 12.8 DIFAL/FCP

| Error Type | Severidade | Certeza | Descrição |
|---|---|---|---|
| `DIFAL_FALTANTE_CONSUMO_FINAL` | error | objetivo | CFOP 6xxx, consumidor final, sem E300 para UF destino |
| `DIFAL_INDEVIDO_REVENDA` | warning | provável | DIFAL gerado para destinatário contribuinte (não deveria) |
| `DIFAL_ALIQ_INTERNA_INCORRETA` | error | objetivo | Alíquota interna do DIFAL ≠ tabela por UF destino |
| `DIFAL_FCP_AUSENTE` | warning | provável | UF com FCP obrigatório sem FCP no E300 |
| `DIFAL_BASE_INCONSISTENTE` | error | objetivo | VL_BC_ICMS_DIFAL ≠ VL_OPR do item |

### 12.9 Cruzamento XML — Presença e Situação

| Error Type | Nível | Severidade | Certeza | Descrição |
|---|---|---|---|---|
| `XML001` | C100 | error | objetivo | NF-e no XML sem C100 no SPED |
| `XML002` | C100 | warning | objetivo | C100 no SPED sem XML correspondente |
| `XML003_B` | C100 | **error** | **objetivo** | **NF cancelada (cStat 101/135) escriturada como ativa** |
| `XML003_C` | C100 | error | objetivo | NF denegada no XML escriturada como ativa |
| `NF_CANCELADA_ESCRITURADA` | C100 | error | objetivo | (alias XML003_B — usado no modo SPED_ONLY com COD_SIT) |
| `XML020` | — | warning | objetivo | XML fora do período DT_INI..DT_FIN — excluído do cruzamento |
| `XML021` | — | warning/error | objetivo | Cobertura abaixo do limiar (< 80% → error, 80-95% → medium) |

### 12.10 Cruzamento XML — Campos C100

| Error Type | Severidade | Descrição |
|---|---|---|
| `XML_C100_CNPJ_EMIT` | **critical** | CNPJ emitente diverge entre XML e C100/0150 |
| `XML_C100_VL_DOC` | high | VL_DOC diverge do vNF do XML |
| `XML_C100_VL_ICMS` | high | VL_ICMS diverge do vICMS do XML |
| `XML_C100_VL_BC` | high | VL_BC_ICMS diverge do vBC do XML |
| `XML_C100_VL_ST` | high | VL_ICMS_ST diverge do vST do XML |
| `XML_C100_VL_IPI` | high | VL_IPI diverge do vIPI do XML |
| `XML_C100_DT_DOC` | medium | DT_DOC diverge de dhEmi do XML |
| `XML013` | warning | IE do destinatário diverge |
| `XML014` | warning | UF do destinatário diverge |
| `XML016` | error | CHV_NFE com formato inválido (44 dígitos / DV) |

### 12.11 Cruzamento XML — Campos C170 (ICMS/IPI)

| Error Type | Severidade | Contexto Aplicado | Descrição |
|---|---|---|---|
| `XML005` / `XML_C170_CST` | high | Regime + CRT do emitente | CST_ICMS diverge (considerando CSOSN→CST para SN) |
| `XML006` / `XML_C170_ALIQ` | high | Benefício ativo | ALIQ_ICMS diverge (verificada contra benefício se ativo) |
| `XML007` / `XML_C170_CFOP` | high | — | CFOP do item diverge |
| `XML008` / `XML_C170_VL_ICMS` | high | Benefício ativo | VL_ICMS do item diverge |
| `XML009` / `XML_C170_NCM` | medium | Escopo do benefício | NCM diverge (verifica escopo do benefício) |
| `XML_C170_VL_BC` | high | Benefício (redução BC) | VL_BC_ICMS diverge (verificada contra redução do benefício) |
| `XML_C170_VL_BC_ST` | high | MVA tabelado | VL_BC_ICMS_ST diverge (revalidada contra MVA) |
| `XML_C170_VL_ICMS_ST` | high | — | VL_ICMS_ST do item diverge |
| `XML_C170_VL_IPI` | high | — | VL_IPI do item diverge |
| `XML_C170_VL_ITEM` | high | — | VL_ITEM (vProd) diverge |
| `XML018` | high | Benefício ativo | CST incompatível com conjunto válido do benefício |
| `XML019` | high | Benefício ativo | Alíquota ICMS incompatível com alíquota do benefício |
| `XML_C190_VL_BC` | high | — | C190 × XML agg.: BC do grupo CST/CFOP/Alíq diverge |
| `XML_C190_VL_ICMS` | high | — | C190 × XML agg.: ICMS do grupo diverge |

---

## 13. Correções Críticas Obrigatórias

### BUG-001 — Regime por CST, não por IND_PERFIL ✅ Especificado na Seção 3.2

**Critérios de aceite:**
- `regime_detector.py` não contém referência a `IND_PERFIL` como critério de regime
- Teste: Perfil C + CSTs 101+ → `regime=SN`
- Teste: Perfil A + CSTs 00-90 + MySQL=LR → `regime=NORMAL, source=CST+MYSQL`
- Conflito → `regime_source=CONFLITO` + alerta obrigatório no relatório

---

### BUG-002 — CRT do Emitente Persiste e Guia Comparação ✅ Especificado nas Seções 4.2 e 10.2

**Critérios de aceite:**
- `nfe_xmls.crt_emitente` populado durante parsing do XML (`//emit/CRT`)
- `emitentes_crt` populado e consultado pelo `FieldComparator._cst_aware()`
- Teste: NF-e de fornecedor SN (CRT=1) → zero falsos positivos XML005
- `BeneficioEngine.CSOSN_TO_CST` mapeamento completo implementado

---

### BUG-003 — Benefícios Auditados contra XML ✅ Especificado nas Seções 4 e 10.4

**Critérios de aceite:**
- XML018 e XML019 implementadas e ativas no modo `sped_xml`
- COMPETE-ES Atacadista ativo: CST incompatível detectado pela XML018
- COMPETE-ES Atacadista ativo: alíquota 12% quando deveria ser 3% → XML019
- `BeneficioEngine.audit_item_xml()` implementado e testado

---

### BUG-004 — ST com MVA Completo ✅ Especificado na Seção 8.2-C

**Critérios de aceite:**
- `st_validator.py` usa `mva_por_ncm_uf.yaml` para recalcular BC_ST
- Cobre MVA original (remetente LR) e MVA ajustado (remetente SN)
- NCM sem MVA mapeado → `ST_MVA_NAO_MAPEADO` (não quebra o pipeline)
- Teste com MVA correto → zero erros; com MVA errado → `ST_MVA_DIVERGENTE`

---

### BUG-005 — NF Cancelada vs. Escriturada ✅ Especificado na Seção 12.9

```
Mapeamento cStat → COD_SIT esperado:
  100 → 00 (Autorizada → Normal)
  101 → 02 (Cancelada → Cancelada)
  135 → 02 (Cancelada fora do prazo → Cancelada)
  110 → 05 (Denegada → Denegada)
  301 → 05 (Denegada → Denegada)

Se cStat=101/135 e C100.COD_SIT=00 → NF_CANCELADA_ESCRITURADA (error, critical)
```

---

### BUG-006 — DELETE Transacional ✅ Especificado na Seção 6.1

**Critério de aceite:** Re-validação não exibe janela de "zero erros". Teste: iniciar revalidação e navegar para lista de erros imediatamente — erros antigos devem estar visíveis até a nova carga completa.

---

### BUG-007 — Tolerância Proporcional

```python
def tolerancia_proporcional(vl_item: float) -> Decimal:
    """Correção P12: tolerância escalonada por magnitude."""
    if vl_item <= 100:
        return Decimal("0.02")
    elif vl_item <= 10_000:
        return min(Decimal("0.05"), Decimal(str(vl_item * 0.0001)))
    elif vl_item <= 500_000:
        return min(Decimal("0.10"), Decimal(str(vl_item * 0.00005)))
    else:
        return min(Decimal("0.50"), Decimal(str(vl_item * 0.00001)))
```

---

### BUG-008 — Eliminação do Modo Dev Inseguro

| Cenário | Comportamento Atual | Comportamento Exigido |
|---|---|---|
| `API_KEY` não configurada | Aceita qualquer valor | HTTP 500: `'API Key não configurada. Configure API_KEY no .env'` |
| `API_KEY` < 32 chars | Aceita | HTTP 500: `'API Key deve ter mínimo 32 caracteres'` |
| Header ausente | HTTP 401 | HTTP 401 (mantido) |

---

## 14. Camada de IA — Cache e Explicabilidade

### 14.1 Chave de Cache Corrigida (Correção P9)

```python
def build_cache_key(rule_id: str, regime: str, uf: str,
                    beneficios: list[str], ind_oper: str,
                    campo: str, valor_encontrado: str) -> str:
    """
    Correção: inclui valor_encontrado no hash.
    CST 040 e CST 090 no mesmo campo → explicações diferentes.
    """
    beneficios_str = "|".join(sorted(beneficios))
    valor_hash     = hashlib.md5(str(valor_encontrado).encode()).hexdigest()[:8]
    raw = f"{rule_id}::{regime}::{uf}::{beneficios_str}::{ind_oper}::{campo}::{valor_hash}"
    return hashlib.sha256(raw.encode()).hexdigest()
```

### 14.2 TTL e Prompt Hash Automático

```python
PROMPT_HASH   = hashlib.md5(EXPLANATION_PROMPT_TEMPLATE.encode()).hexdigest()[:8]
MAX_CACHE_AGE = 180  # dias — cobre mudanças legislativas anuais

def cache_lookup(chave_hash: str, rule_version: str) -> str | None:
    row = db.get_cache(chave_hash)
    if not row:                                        return None
    if row.prompt_hash != PROMPT_HASH:                 return None  # prompt mudou
    if row.rule_version != rule_version:               return None  # regra mudou
    if (datetime.now() - row.gerado_em).days > MAX_CACHE_AGE: return None
    db.increment_hits(chave_hash)
    return row.explicacao_texto
```

### 14.3 Cache por Hash de Erros (Frente 4 — Relatório Narrativo)

```python
def gerar_relatorio_narrativo(file_id: int, all_errors: list, context: ValidationContext) -> str:
    snapshot     = sorted([(e.rule_id, e.severity, e.message) for e in all_errors])
    errors_hash  = hashlib.sha256(str(snapshot).encode()).hexdigest()

    existente = db.get_narrative_report(file_id)
    if existente and existente.errors_hash == errors_hash:
        return existente.texto  # zero chamadas à API — erros não mudaram

    texto = call_sonnet_api(context, all_errors)
    db.save_narrative_report(file_id, texto, errors_hash, context.context_hash)
    return texto
```

### 14.4 Frentes de IA e Modelos

| Frente | Modelo | Propósito | Cache |
|---|---|---|---|
| 1 — Explicação de erros | Claude Haiku | Explicação acessível por erro individual ao contador | Sim — incremental por `cache_key` |
| 2 — Agrupamento e priorização | Claude Haiku | Agrupar 2.000+ erros em 3–5 problemas principais | Sim — por `errors_hash` |
| 3 — Sugestão contextual | Claude Haiku | Campo `ai_suggestion` com correção sugerida | Sim — incremental |
| 4 — Relatório narrativo | Claude Sonnet | Parecer de fechamento com risco fiscal consolidado | Sim — por `errors_hash` |

> **Claude Haiku** para frentes 1–3: rápido, baixo custo, adequado para explicações repetitivas com contexto fixo.
> **Claude Sonnet** apenas para o relatório narrativo final: maior qualidade textual para o documento que o contador assina.

**Badge no frontend:** Cada apontamento gerado ou enriquecido por IA deve exibir badge `🤖 IA` com tooltip `"Sugestão não vinculante — verificação do contador é obrigatória"` em cor diferente dos erros determinísticos.

### 14.5 Persona da IA para ICMS/IPI

```
Você é um assistente fiscal especializado em EFD ICMS/IPI para o estado do Espírito Santo.
- Público: contadores, não programadores
- Linguagem: acessível, sem jargão de TI
- Cite base legal: RICMS-ES, EC 87/2015, LC 87/1996, Convênio ICMS, SINIEF
- Formato: 3 parágrafos: O QUE está errado · POR QUE é um problema fiscal · COMO corrigir
- Mencione o benefício fiscal quando relevante (COMPETE-ES, FUNDAP, INVEST-ES, decreto específico)
- Sugestão não vinculante — decisão é do contador responsável (CRC)
- Temperatura: 0.3 (alta precisão, baixa criatividade)
- Max tokens: 500 (Haiku) / 1500 (Sonnet — relatório narrativo)
```

---

## 15. Score de Risco Fiscal e Cobertura

### 15.1 Score de Risco (0–100)

```python
def calcular_score(errors: list[ValidationError], context: ValidationContext) -> float:
    score = 0.0

    # 40% — Erros objetivos críticos
    erros_criticos = [e for e in errors
                      if e.severity == "error" and e.certeza == "objetivo"]
    score += min(40, len(erros_criticos) * 2 * _peso_financeiro(erros_criticos))

    # 25% — Erros prováveis
    erros_provaveis = [e for e in errors
                       if e.severity == "error" and e.certeza == "provavel"]
    score += min(25, len(erros_provaveis) * 1.5 * _peso_financeiro(erros_provaveis))

    # 20% — Erros de benefício fiscal (maior risco de autuação SEFAZ)
    erros_beneficio = [e for e in errors
                       if e.rule_id.startswith(("SPED_", "BENEFICIO_", "XML018", "XML019",
                                                "CREDITO_PRESUMIDO", "SOBREPOSICAO"))]
    score += min(20, len(erros_beneficio) * 3)

    # 10% — ST e DIFAL
    erros_st_difal = [e for e in errors
                      if e.rule_id.startswith(("ST_", "DIFAL_"))]
    score += min(10, len(erros_st_difal) * 2)

    # 5% — Riscos sistêmicos
    if any(e.rule_id == "VOLUME_ISENTO_ATIPICO" for e in errors):
        score += 3
    if any(e.rule_id == "SPED_ICMS_ZERADO_SEM_BENEFICIO" for e in errors):
        score += 2

    return min(100, score)
```

| Faixa | Classificação | Ação Recomendada |
|---|---|---|
| 0–20 | 🟢 BAIXO RISCO | Revisão de rotina — regularização preventiva |
| 21–50 | 🟡 RISCO MODERADO | Revisão prioritária pelo contador responsável |
| 51–75 | 🟠 RISCO ELEVADO | Retificação recomendada — exposure relevante identificado |
| 76–100 | 🔴 RISCO CRÍTICO | Ação imediata — padrão compatível com irregularidade grave |

---

### 15.2 Nota de Cobertura (Tri-dimensional)

```python
# Nota de Cobertura (tri-dimensional)
# Usa raiz quadrada para cobertura documental: penaliza menos acesso parcial a XMLs,
# que frequentemente depende de terceiros (fornecedores que não compartilham XMLs).

COBERTURA_REGRAS      = regras_executadas / regras_ativas  # 0.0 a 1.0
COBERTURA_DOCUMENTAL  = nfe_com_xml / total_nfe_sped        # 0.0 a 1.0 (só Trilha B)
COBERTURA_ITENS       = itens_cruzados / total_itens_sped   # 0.0 a 1.0 (só Trilha B)

# Modo SPED_ONLY
NOTA_COBERTURA = COBERTURA_REGRAS

# Modo SPED_XML_RECON
NOTA_COBERTURA = (COBERTURA_REGRAS * 0.5) + \
                 (COBERTURA_DOCUMENTAL ** 0.5 * 0.3) + \
                 (COBERTURA_ITENS ** 0.5 * 0.2)
# ^^ Raiz quadrada: empresa com 64% de XMLs tem cobertura documental de 0.8 (√0.64),
# não 0.64 — mais justo para escritórios sem acesso a todos os XMLs de fornecedores.
```

**Para cada tabela ausente**, registrar em `coverage_gaps`:
```
gap_type: "tabela_ausente"
description: "aliquotas_internas_uf.yaml ausente — validações de DIFAL e alíquota interestadual desabilitadas"
affected_rule: "DIFAL_*, ALIQ_INTERESTADUAL_*"
severity: "high"
```

---

## 16. Especificação de API

### 16.1 Endpoints

```
# Cadastro de clientes (novo)
GET    /api/v1/clientes                    → lista clientes
POST   /api/v1/clientes                    → criar cliente
GET    /api/v1/clientes/{cnpj}             → detalhe por CNPJ
PUT    /api/v1/clientes/{id}               → atualizar
POST   /api/v1/clientes/{id}/beneficios    → adicionar benefício
PUT    /api/v1/clientes/{id}/beneficios/{bid} → atualizar benefício

# Upload e contexto
POST   /api/v1/files/upload                → upload SPED (chunked)
GET    /api/v1/files/{id}/context          → ValidationContext atual
POST   /api/v1/files/{id}/xml/upload       → upload XMLs (chunked, múltiplos)
GET    /api/v1/files/{id}/xml/coverage     → cobertura documental pré-validação

# Validação
POST   /api/v1/files/{id}/validate/sped         → dispara Trilha A
GET    /api/v1/files/{id}/validate/sped/stream  → SSE Trilha A
POST   /api/v1/files/{id}/validate/sped-xml         → dispara Trilha B
GET    /api/v1/files/{id}/validate/sped-xml/stream  → SSE Trilha B

# Resultados
GET    /api/v1/files/{id}/errors           → erros com filtros e paginação
GET    /api/v1/files/{id}/summary          → resumo por tipo/severidade/certeza
GET    /api/v1/files/{id}/xml/results      → resultados do cruzamento XML
GET    /api/v1/files/{id}/xml/divergences  → ranking de divergências por campo

# Relatório
GET    /api/v1/files/{id}/report?mode=sped      → MOD-20 Trilha A
GET    /api/v1/files/{id}/report?mode=sped-xml  → MOD-20 Trilha B
GET    /api/v1/files/{id}/report/structured     → JSON estruturado

# Validação runs
GET    /api/v1/files/{id}/runs             → histórico de execuções
GET    /api/v1/runs/{run_id}/coverage      → cobertura detalhada por run
GET    /api/v1/runs/{run_id}/gaps          → lacunas de cobertura

# IA
POST   /api/v1/ai/explain                  → explicação de erro específico
GET    /api/v1/ai/cache/stats              → hit rate, economia estimada
DELETE /api/v1/ai/cache                    → limpar cache (admin)
```

### 16.2 Contrato SSE

```json
// Evento de progresso
{
  "event": "progress",
  "stage": 2,
  "stage_name": "Cruzamento SPED",
  "stage_progress": 67,
  "total_stages": 4,
  "errors_found": { "error": 12, "warning": 34, "info": 5 },
  "detail": "C170 linha 4521 — CST 020 sem redução de BC",
  "eta_seconds": 45,
  "context": {
    "regime": "LP",
    "beneficios_ativos": ["COMPETE_ATACADISTA"],
    "regime_source": "CST+MYSQL"
  }
}

// Evento específico Trilha B — progresso XML
{
  "event": "xml_progress",
  "stage": 2.5,
  "xmls_parsed": 47,
  "xmls_total": 120,
  "pairs_checked": 1240,
  "divergencias_icms": 18,
  "divergencias_ipi": 3
}

// Evento de conclusão
{
  "event": "done",
  "mode": "sped_xml",
  "total_errors": 89,
  "score_risco": 67,
  "classificacao": "RISCO_ELEVADO",
  "coverage_score": 0.84,
  "xml_coverage_pct": 94.2,
  "total_comparisons": 14800,
  "errors_by_stage": { "sped": 52, "xml": 37 },
  "errors_by_category": {
    "beneficio": 15,
    "st_mva": 8,
    "apuracao": 6,
    "cst": 12,
    "outros": 48
  }
}
```

---

## 17. Requisitos de Relatório

### 17.1 Seções do Relatório MOD-20 (ambas as trilhas)

| Seção | Conteúdo | Trilha |
|---|---|---|
| 1. Identificação | CNPJ, Razão Social, Período, UF, Regime, Perfil, Hash SHA-256 | A + B |
| 2. Contexto de Auditoria | Regime usado + source, Benefícios ativos com vigências, Tabelas carregadas/ausentes, Score de cobertura | A + B |
| 3. Cobertura da Auditoria | 15 checks executados, tabelas ausentes, lacunas com impacto, `coverage_gaps` | A + B |
| 4. Score de Risco | Pontuação 0-100, classificação, breakdown por categoria | A + B |
| 5. Sumário de Achados | Por severidade, por certeza, por bloco, top-10 tipos por frequência | A + B |
| 6. Encadeamento Fiscal | Status de cada trilha: C100→C170→C190→E110→E111→E116 | A + B |
| 7. Achados Detalhados | Por erro: linha, registro, campo, valor_encontrado, expected_value, certeza, impacto, base_legal, orientação | A + B |
| 8. Cobertura XML | % NF-e com XML, lista sem cobertura, impacto estimado (Trilha B) | B |
| 9. Divergências XML | Ranking de campos com maior frequência de divergência, matriz por NF-e | B |
| 10. Correções Aplicadas | Histórico: campo, valor_original, novo_valor, justificativa, aprovado_por | A + B |
| 11. Limitações | Tabelas ausentes, regras puladas, % cobertura documental | A + B |
| 12. Rodapé Legal | Aviso MOD-20: responsabilidade exclusiva do contribuinte/representante habilitado | A + B |

### 17.2 Rodapé Legal Obrigatório

```
AVISO LEGAL: Este relatório foi gerado automaticamente pelo sistema de
auditoria SPED EFD ICMS/IPI e NÃO constitui parecer contábil, fiscal
ou jurídico. A conferência, validação e retificação do arquivo SPED
junto à Secretaria da Fazenda do Estado do Espírito Santo (SEFAZ-ES)
e à Receita Federal do Brasil (RFB) é responsabilidade exclusiva do
contribuinte e de seu representante técnico legalmente habilitado
(CRC/CRA/OAB). O uso de benefícios fiscais sem ato concessório válido
pode ensejar autuação com multa e juros pela autoridade competente.
```

### 17.3 Separação Clara: Erro Objetivo vs. Provável vs. Hipótese

Cada apontamento deve ter o campo `certeza` explícito e visível:
- `objetivo` — calculado matematicamente, sem margem de interpretação
- `provavel` — indica irregularidade com alta probabilidade, sujeito a confirmação
- `indicio` — sinal de alerta que requer análise do contador
- `hipotese` — sugestão de valor correto gerada pelo motor; não é erro confirmado

---

## 18. Casos de Borda Fiscais

| Cenário | Comportamento Exigido | Error Type |
|---|---|---|
| NF-e com CST de 6 dígitos (Simples) em C170 | Normalizar para 2 dígitos (últimos dois) antes de validar | Sem erro estrutural; regime ajustado |
| Arquivo com CSTs mistos Tabela A e B no mesmo período | Detectar e alertar | `REGIME_MISTO_NO_PERIODO` (warning) |
| Retificador parcial | Identificar registros alterados; revalidar apenas esses | Informar % de registros retificados |
| NF complementar (COD_SIT=07) sem NF original vinculada | Buscar original por NUM_DOC+SER+CNPJ | `NF_COMPLEMENTAR_SEM_ORIGINAL` (warning) |
| C170 sem C100 pai | Gerar erro estrutural e excluir do pipeline | `C170_ORFAO` (error, objetivo) |
| E110 com VL_ICMS_RECOLHER = 0 e débitos > créditos | Verificar E111 que zeram o saldo; sem E111 → erro | `ICMS_ZERADO_SEM_AJUSTE` (error) |
| CNPJ com IE de UF diferente do UF do 0000 | Alerta de inconsistência cadastral | `IE_UF_DIVERGE_CNPJ` (warning) |
| XML com namespace inválido (CT-e, MDF-e) | Rejeitar: `'Namespace inválido — apenas NF-e (55) aceita'` | Não processar; incrementar rejeitados |
| 2 benefícios com alíquotas diferentes para mesmo CFOP | Registrar `CONFLITO_BENEFICIOS` no contexto; alertar auditor | warning no ClientContextBadge |
| E111 com código de ajuste não listado na tabela 5.1.1 da UF | Gerar erro de código inválido | `CODIGO_AJUSTE_INVALIDO` (error) |
| CNPJ não cadastrado no sistema | Bloquear a validação com mensagem acionável | `ContextBuildError` com action link |
| Múltiplos XMLs do mesmo CHV_NFE | Deduplicar por content_hash; manter o mais recente | Aviso de duplicata no log |
| C190 com grupo CST+CFOP+ALIQ inexistente em C170 | Gerar erro | `C190_COMBINACAO_INCOMPATIVEL` |
| Nota de ajuste ST (CFOP 1603/2603) | Não aplicar regras ST padrão; validar base de ajuste | Tratamento específico por CFOP |

---

## 19. Plano de Testes e Critérios de Aceite

### 19.1 Critérios de Aceite — Context-First

| Critério | Condição de Aceite |
|---|---|
| Stage 0 obrigatório | CNPJ não cadastrado retorna erro claro antes de qualquer DELETE |
| Regime por CST | Empresa SN Perfil A → `regime=SN`; zero erros por regime incorreto |
| CRT × CST | NF-e de fornecedor SN não gera falso positivo XML005 |
| Benefício × CST | COMPETE ativo + CST incompatível → XML018 gerado |
| Benefício × Alíquota | COMPETE + alíquota 12% quando esperado 3% → XML019 |
| DELETE transacional | Re-validação não exibe janela de zero erros |
| Contexto hash | Regime alterado → cache IA invalidado na próxima validação |

### 19.2 Suite de Testes de Regressão Fiscal

| Arquivo de Teste | Cenário | Resultado Esperado |
|---|---|---|
| `test_sped_sn_perfil_a.txt` | Empresa SN, Perfil A, CSTs 101–500 | `regime=SN`; zero erros por regime incorreto |
| `test_sped_compete_atacadista.txt` | Empresa com COMPETE ativo, alíq. 3% | Zero `SPED_ALIQ_BENEFICIO` para itens no escopo |
| `test_sped_compete_aliq_errada.txt` | Empresa COMPETE com ALIQ_ICMS=12% | `SPED_ALIQ_BENEFICIO` com `expected_value=0.03` |
| `test_sped_st_mva_correto.txt` | ST com MVA calculado corretamente | Zero `ST_MVA_DIVERGENTE` |
| `test_sped_st_mva_errado.txt` | ST com BC_ST subdimensionada | `ST_MVA_DIVERGENTE` com `expected_value` correto |
| `test_sped_encadeamento.txt` | C190→E110→E111 consistentes | Zero erros de apuração |
| `test_sped_apuracao_divergente.txt` | SUM(C190) ≠ E110 débitos | `APURACAO_DEBITO_DIVERGENTE` |
| `test_sped_sem_regime.txt` | CNPJ não cadastrado | `ContextBuildError` com action link |
| `test_xml_nf_cancelada.txt` | cStat=101 + COD_SIT=00 | `NF_CANCELADA_ESCRITURADA` (error, critical) |
| `test_xml_fornecedor_sn.txt` | CRT=1 no XML, CST no SPED | Zero falsos positivos XML005 |
| `test_xml_compete_cst_errado.txt` | COMPETE ativo + CST errado no XML | `XML018` gerado |
| `test_xml_cobertura_60pct.txt` | 50 XMLs para 83 NF-e do SPED | `xml_coverage_pct=60.2`; XML021 warning |
| `test_xml_st_mva_alto.txt` | BC_ST no XML acima do MVA tabelado | `XML_C170_VL_BC_ST` error |
| `test_xml_200_notas.txt` | 200 XMLs × 20 itens = 4.000 pares | Completado em < 3 min; sem timeout |

### 19.3 Métricas de Cobertura Mínimas

| Componente | Meta |
|---|---|
| `src/validators/` | ≥ 85% |
| `src/core/` (novo) | ≥ 90% |
| `src/services/context_builder.py` | ≥ 95% |
| `BeneficioEngine` | 100% das interfaces públicas |
| Regras `rules.yaml` | 100% com teste positivo e negativo |
| Casos de borda (Seção 18) | 100% com teste dedicado |
| Mapeamento XML→SPED (`field_map.yaml`) | 100% dos campos com teste de divergência |

---

## 20. Roadmap de Entrega

| Sprint | Duração | Entregas | Critério de Conclusão |
|---|---|---|---|
| **Sprint 1 — Fundação** | 2 semanas | Migration 13 (SQL), CRUD de clientes e benefícios, importação CSV de carteira, ClientContextBadge | Todos os clientes ativos com regime definido; badge exibe benefícios corretos |
| **Sprint 2 — Context-First** | 2 semanas | Stage 0 ContextBuilder, BeneficioEngine completo, detecção de regime por CST (BUG-001), CRT do emitente (BUG-002), DELETE transacional (BUG-006) | Suite test_sped_sn_perfil_a.txt passando; zero falsos positivos CST para SN |
| **Sprint 3 — Regras SPED ICMS** | 2 semanas | SPED_REG01–04, ST com MVA completo (BUG-004), encadeamento C190→E110→E111 (Trilha 3), tolerância proporcional (BUG-007), BUG-008 auth | test_sped_encadeamento.txt e test_sped_st_mva_errado.txt passando |
| **Sprint 4 — Frontend Dual-Path** | 1 semana | SPEDOnlyUploadPage, SPEDXMLUploadPage com dois dropzones, SSE adaptativo, page /clientes | Teste de usabilidade com 5 analistas — todos escolhem modo correto sem instrução |
| **Sprint 5 — Motor XML** | 3 semanas | field_map.yaml completo, FieldComparator todos os tipos, XML018–021 (BUG-003), NF cancelada (BUG-005), C190×XML agregação, xml_match_index | 100% dos campos mapeados com teste de divergência; test_xml_compete_cst_errado.txt passando |
| **Sprint 6 — Score e Relatório** | 1 semana | Score de risco fiscal (Seção 15), nota de cobertura tri-dimensional, relatório MOD-20 completo com Seção 2 e rodapé legal | Score exibido no relatório; coverage_gaps populado em cada run |
| **Sprint 7 — IA e Cache** | 1 semana | Cache IA com chave corrigida (BUG-009), TTL 180d, prompt_hash, Frente 4 por hash de erros | CST 040 e CST 090 → explicações diferentes; zero chamadas à API sem mudança de erros |
| **Sprint 8 — Qualidade** | 1 semana | Coverage ≥ 85%, base_legal em 100% das regras, DETALHAMENTO_FISCAL.md v5 atualizado, CI/CD verde | Zero itens pendentes; todos os testes da Seção 19.2 passando |

> **Regra de ouro:** Os Sprints 1 e 2 são bloqueantes para tudo. Nenhuma feature nova sem contexto correto e regime correto.

---

## 21. Glossário Técnico-Fiscal

| Termo | Significado |
|---|---|
| `IND_PERFIL` | Nível de escrituração do EFD: A=completo, B=simplificado, C=com vedações. **NÃO é regime tributário.** |
| `CRT` | Código de Regime Tributário do emitente no XML: 1=SN, 2=SN excesso receita, 3=Regime Normal |
| `CSOSN` | Código de Situação da Operação no SN — substitui CST ICMS para empresas SN |
| CST Tabela A | Origem da mercadoria (1º dígito do CST): 0=Nacional, 1=Estrangeira importada, etc. |
| CST Tabela B | Tributação da operação (2 últimos dígitos): 00=Tributada, 20=Redução, 40=Isenta, 60=ST anterior |
| `MVA` | Margem de Valor Agregado — percentual para calcular BC_ICMS_ST na ST prospectiva |
| `DIFAL` | Diferencial de Alíquota — ICMS em operações interestaduais para consumidor final (EC 87/2015) |
| `FCP` | Fundo de Combate à Pobreza — adicional ao DIFAL (RJ 2%, MG 2%) |
| `BeneficioEngine` | Módulo que responde perguntas fiscais sobre benefícios ES ativos no período |
| `context_hash` | SHA256(regime + benefícios + rules_version) — invalida cache quando contexto muda |
| `coverage_score` | Nota de cobertura tri-dimensional: regras executadas × cobertura documental × itens cruzados |
| `xml_match_index` | Tabela de pareamento NF-e XML ↔ C100 SPED com status e confidence |
| `SPED_ONLY` | Modo de validação sem XMLs — auditoria escritural e de apuração |
| `SPED_XML_RECON` | Modo de validação reconciliatória com XMLs — confronto campo a campo |
| `Stage 0` | Etapa obrigatória e bloqueante de montagem de contexto — antes de qualquer validação |
| `certeza` | Classificação do apontamento: objetivo (matemático), provável (fiscal), indício (preventivo) |
| Crédito presumido | Benefício fiscal ES que permite apropriar crédito de ICMS fictício para reduzir o débito |
| Diferimento | Benefício fiscal que posterga o pagamento do ICMS para etapa posterior da cadeia |

---

## 22. Base Legal de Referência

| Categoria | Legislação | Aplicação |
|---|---|---|
| ICMS — Geral | RICMS-ES (Dec. 1.090-R/2002) — Arts. 1–65 | Base de toda a legislação ICMS no ES |
| ICMS — Interestaduais | Resolução SF nº 22/1989 | Alíquotas 4%, 7%, 12% |
| DIFAL | EC 87/2015 + LC 190/2022 + RICMS-ES Arts. 102–109 | Diferencial de alíquota não contribuinte |
| Substituição Tributária | Convênio ICMS 142/2018 + Protocolos por NCM/UF | ST prospectiva e retrospectiva |
| MVA | Protocolos ICMS ES por produto | Base de cálculo da ST prospectiva |
| Simples Nacional | LC 123/2006 + LC 155/2016 + Res. CGSN 140/2018 | CSOSN, sublimites, alíquotas por faixa |
| COMPETE-ES Atacadista | Dec. ES 1.663-R/2005 e atualizações | Crédito presumido para atacadistas no ES |
| COMPETE-ES E-commerce | Decreto específico E-commerce ES | Crédito presumido para comércio eletrônico |
| FUNDAP | Lei ES 2.508/1970 + regulamentos | Diferimento nas importações via ES |
| INVEST-ES | Dec. ES 1.599-R/2005 | Incentivos industriais e de importação |
| IPI — Geral | RIPI (Dec. 7.212/2010) | Regras gerais do IPI |
| IPI — Reflexo BC | RIPI Art. 14, §1º | IPI compõe BC ICMS quando não recuperável |
| Crédito de ICMS | LC 87/1996 Art. 20 | Direito ao crédito de ICMS de entrada |
| Crédito uso/consumo | LC 87/1996 Art. 33, I (prazo 2033) | Vedação de crédito em material de uso/consumo |
| Emissão NF-e | NT 2019.001 + Manual NF-e v7.0 | Layout, campos obrigatórios, regras de emissão |
| Cancelamento NF-e | NT 2021.001 | cStat 101/135, prazo de cancelamento |
| CST ICMS | Tabela A e Tabela B do SINIEF | Códigos válidos por origem e tributação |
| CSOSN | Res. CGSN 140/2018 Tabela B | Códigos de situação para SN |
| Alíquotas ES | RICMS-ES Art. 19 | Alíquotas internas: 12%, 17%, 27% + adicionais |
| DCTF-Web | IN RFB 2.005/2021 | Cruzamento EFD × declaração federal |

---

*SPED EFD Validator v5.0.0 — PRD Definitivo · Foco ICMS/IPI*
*Central Contábil · Vitória, Espírito Santo · Abril 2026*
*Documento interno — uso restrito à equipe técnica e fiscal*
