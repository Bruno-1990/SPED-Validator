# PRD — SPED EFD Validator v5.1
## Auditoria Fiscal ICMS/IPI — Arquitetura Context-First com Dual-Path

| Campo | Valor |
|---|---|
| **Versão** | v5.1 |
| **Data** | Abril 2026 |
| **Empresa** | Central Contábil — Vitória, ES |
| **Status** | DOCUMENTO MESTRE — APROVADO PARA DESENVOLVIMENTO |
| **Escopo** | EFD ICMS/IPI exclusivamente — EFD Contribuições tratada em sistema separado |
| **Base** | Fusão de PRD v3.0 + PRD v4.1 + PRD Fechamento + PLANO_MELHORIAS_v5 |

---

## Sumário

1. [Premissas e Escopo](#1-premissas-e-escopo)
2. [Vetores de Risco — Diagnóstico](#2-vetores-de-risco--diagnóstico)
3. [Correções Críticas Obrigatórias](#3-correções-críticas-obrigatórias)
4. [Princípio Arquitetural — Context-First](#4-princípio-arquitetural--context-first)
5. [Dual-Path — Visão Geral](#5-dual-path--visão-geral)
6. [Frontend — Interface e UX](#6-frontend--interface-e-ux)
7. [Stage 0 — Montagem de Contexto](#7-stage-0--montagem-de-contexto)
8. [BeneficioEngine](#8-beneficioengine)
9. [Pipeline Caminho A — Validação SPED](#9-pipeline-caminho-a--validação-sped)
10. [Pipeline Caminho B — Validação SPED × XML](#10-pipeline-caminho-b--validação-sped--xml)
11. [Mapa de Equivalência SPED ↔ XML (ICMS/IPI)](#11-mapa-de-equivalência-sped--xml-icmsipi)
12. [Motor de Cruzamento Campo-a-Campo](#12-motor-de-cruzamento-campo-a-campo)
13. [Cadeia de Fechamento Fiscal](#13-cadeia-de-fechamento-fiscal)
14. [Catálogo Completo de Regras — ICMS e IPI](#14-catálogo-completo-de-regras--icms-e-ipi)
15. [Tolerância Proporcional por Magnitude](#15-tolerância-proporcional-por-magnitude)
16. [Score de Risco Fiscal](#16-score-de-risco-fiscal)
17. [Banco de Dados — Modelo Completo](#17-banco-de-dados--modelo-completo)
18. [Especificação de API](#18-especificação-de-api)
19. [Contrato SSE](#19-contrato-sse)
20. [Base Legal por Categoria de Erro (ICMS/IPI)](#20-base-legal-por-categoria-de-erro-icmsipi)
21. [Casos de Borda](#21-casos-de-borda)
22. [Critérios de Aceite](#22-critérios-de-aceite)
23. [Roadmap de Entrega](#23-roadmap-de-entrega)
24. [Glossário Técnico-Fiscal](#24-glossário-técnico-fiscal)

---

## 1. Premissas e Escopo

### 1.1 Escopo Definitivo

> **FOCO EXCLUSIVO: EFD ICMS/IPI**
>
> Este sistema valida erros de **ICMS e IPI** no arquivo EFD ICMS/IPI. PIS, COFINS e EFD Contribuições são tratados por sistema separado e **não fazem parte deste escopo**. Qualquer regra, error type ou campo relacionado a PIS/COFINS deve ser omitido ou marcado como `FORA_DO_ESCOPO`.

Campos C170 de PIS/COFINS (`CST_PIS`, `VL_PIS`, `CST_COFINS`, `VL_COFINS`, etc.) são **parseados para consistência estrutural** mas não são objeto de validação de conteúdo neste sistema.

### 1.2 Premissa Central

> **O validador deve ser o primeiro adversário do contribuinte — encontrar e documentar tudo que a SEFAZ-ES e a Receita Federal identificariam em uma análise fiscal do arquivo EFD ICMS/IPI, antes que elas encontrem.**

### 1.3 Regra de Ouro do Motor

Nenhuma validação relevante é executada sem contexto completo. Cada regra recebe obrigatoriamente:

- modo de execução (`SPED_ONLY` | `SPED_XML_RECON`)
- regime tributário efetivo
- UF e período
- benefícios fiscais ativos e suas restrições
- natureza da operação e tipo de documento
- tabelas de referência disponíveis

Se uma validação depende de tabela ou dado externo ausente, a regra é marcada como `NAO_EXECUTADA`, a limitação é registrada em `coverage_gaps` e o score de cobertura é reduzido.

---

## 2. Vetores de Risco — Diagnóstico

| Vetor | Natureza | Criticidade | Impacto |
|---|---|---|---|
| `IND_PERFIL` usado como regime | Bug de lógica crítica | 🔴 CRÍTICO | Detecção de regime incorreta em 100% das validações |
| ST sem MVA calculado | Lacuna fiscal grave | 🔴 CRÍTICO | ICMS-ST não auditado corretamente em NF de entrada com ST |
| Benefícios não auditados vs. XML | Lacuna de produto | 🔴 CRÍTICO | CST/alíquota incompatíveis com benefício não detectados |
| CRT emitente ignorado (CST × CSOSN) | Bug fiscal | 🔴 CRÍTICO | Falso positivo para toda NF-e de fornecedor SN |
| Cruzamento XML superficial | Lacuna fiscal | 🔴 CRÍTICO | Apenas totais cruzados; campos de item não auditados |
| Cadeia fiscal não fechada | Lacuna de cobertura | 🔴 CRÍTICO | C190 → E110 → E111 → E116 não validado fim a fim |
| NF cancelada escriturada como ativa | Bug de regra | 🟠 ALTO | Crédito indevido não detectado |
| Tolerância global R$ 0,02 | Limitação de precisão | 🟠 ALTO | Falsos positivos em itens de alto valor |
| Bypass de autenticação em dev | Risco de segurança | 🟠 ALTO | Dados fiscais de clientes acessíveis sem auth |
| DELETE não-atômico no pipeline | Risco operacional | 🟠 ALTO | Janela de "zero erros" durante re-validação |
| `parsed_json` como fonte duplicada | Débito técnico | 🟡 MÉDIO | Pressão de memória + fonte de verdade duplicada |
| Período dos XMLs não validado | Lacuna de UX | 🟡 MÉDIO | XMLs de mês errado geram centenas de falsos ausentes |

---

## 3. Correções Críticas Obrigatórias

> Pré-requisito absoluto. Nenhuma nova funcionalidade deve ser entregue sem que todas estejam resolvidas e validadas com arquivos reais de clientes pelo analista fiscal sênior.

### BUG-001 — Correção da Detecção de Regime Tributário

**Problema:** `regime_detector.py` usa `IND_PERFIL` do registro 0000 como indicador de regime. `IND_PERFIL` indica **nível de escrituração** (A/B/C) — não tem qualquer relação com regime fiscal.

**Regra Fiscal Correta:**

| Evidência no Arquivo | Regime Detectado | Prioridade |
|---|---|---|
| Qualquer CST ∈ {101..900} (Tabela B do SN) em C170 | Simples Nacional | 1ª — determinante |
| CSOSN em qualquer C190 | Simples Nacional | 1ª — determinante |
| `regime = 'SN'` na tabela `clientes` | Simples Nacional | 2ª — confirmatória |
| CSTs 00–90 (Tabela A) sem CSOSN | Lucro Real ou Presumido | 1ª — determinante |
| `IND_PERFIL = A, B ou C` | **Nível de escrituração — IGNORAR para regime** | — |

**CST de 6 dígitos (Simples):** Normalizar para 2 dígitos (últimos dois) antes de qualquer validação. Não gerar erro estrutural; ajustar regime para `SIMPLES`.

**Conflito CST × tabela `clientes`:** `regime_source = 'CONFLITO'` → alerta obrigatório na Seção 2 do relatório.

**Mapeamento de CSOSN → CST equivalente (para comparação SPED × XML):**

Cada CSOSN mapeia para um CST específico. Agrupamentos genéricos causam falsos negativos — usar a tabela precisa abaixo:

| CSOSN | CST Equivalente | Efeito Tributário | Base Legal |
|---|---|---|---|
| 101 | 00 | Tributada integralmente com permissão de crédito | Res. CGSN 140/2018 Art. 59 |
| 102 | 20 | Tributada com redução de BC | Res. CGSN 140/2018 Art. 59 |
| 103 | 40 | Isenta — sem tributação | Res. CGSN 140/2018 Art. 59 |
| 201 | 10 | Com ST (débito próprio + ST prospectiva) | Res. CGSN 140/2018 Art. 60 |
| 202 | 10 | Com ST sem tributação própria | Res. CGSN 140/2018 Art. 60 |
| 203 | 30 | ST sem débito próprio (não tributada) | Res. CGSN 140/2018 Art. 60 |
| 300 | 41 | Imune | Res. CGSN 140/2018 Art. 59 |
| 400 | 40 | Não tributada (SN não cobra ICMS na operação) | Res. CGSN 140/2018 Art. 59 |
| 500 | 60 | ST já retida anteriormente | Res. CGSN 140/2018 Art. 60 |
| 900 | 90 | Outros | Res. CGSN 140/2018 |

> **Atenção:** 102→20 e 103→40 são distintos — agrupar ambos em "40" é erro fiscal. 201 e 202 mapam para 10 mas têm efeitos diferentes (201 tem débito próprio; 202 não). O `FieldComparator._cst_aware()` deve usar esta tabela exata via `CSOSN_TO_CST` dict.

---

### BUG-002 — ICMS-ST com MVA — Fórmula Completa em 4 Etapas

**Problema:** A fórmula atual valida apenas o ICMS-ST já escriturado. Não detecta BC subdimensionada por MVA incorreto ou omitido.

```python
# Etapa 1 — Base ST com MVA original
BC_ST = (VL_ITEM + VL_FRT + VL_SEG + VL_OUT_DA - VL_DESC) * (1 + MVA_original / 100)
# Fonte: C170 + mva_por_ncm_uf.yaml[NCM][UF_DEST]

# Etapa 2 — Ajuste para remetente Simples Nacional
# Aplicar se 0150.regime = SIMPLES ou CRT=1 no XML
BC_ST_aj = BC_ST * (1 - (aliq_interestadual / aliq_interna_uf_dest))
# Fonte: aliquotas_internas_uf.yaml + aliquotas_interestaduais_resolucao_22.yaml

# Etapa 3 — ICMS-ST esperado
VL_ICMS_ST_esp = (BC_ST_aj * ALIQ_ST / 100) - VL_ICMS_proprio
# ALIQ_ST: tabela por NCM/UF do RICMS-ES ou convênio aplicável

# Etapa 4 — Divergência com tolerância proporcional (ver Seção 15)
diff = abs(VL_ICMS_ST_escriturado - VL_ICMS_ST_esp)
if diff > tolerancia_proporcional(VL_ICMS_ST_esp):
    gerar ST_MVA_DIVERGENTE(expected=VL_ICMS_ST_esp, found=VL_ICMS_ST_escriturado)
```

**Error Types novos:**

| Error Type | Severidade | Certeza | Descrição |
|---|---|---|---|
| `ST_MVA_AUSENTE` | error | objetivo | Produto sujeito a ST sem MVA calculado |
| `ST_MVA_DIVERGENTE` | error | provável | BC_ICMS_ST incompatível com MVA tabelado |
| `ST_MVA_NAO_MAPEADO` | warning | indício | NCM/UF sem MVA na tabela de referência |
| `ST_ALIQ_INCORRETA` | error | objetivo | Alíquota ST diferente da tabela por NCM/UF |
| `ST_REGIME_REMETENTE` | warning | provável | MVA ajustado não aplicado para remetente SN |

---

### BUG-003 — NF Cancelada vs. Escriturada

**Cruzamento COD_SIT (C100) × cSit (XML):**

| COD_SIT no C100 | cSit no XML | Situação | Error Type |
|---|---|---|---|
| `00` (Normal) | `100` (autorizada) | ✅ Correto | — |
| `00` (Normal) | `101` ou `135` (cancelada) | ❌ Irregular | `NF_CANCELADA_ESCRITURADA` (error, objetivo) |
| `02` (Cancelada) | `101` ou `135` | ✅ Correto | — |
| `00` (Normal) | `110` ou `301` (denegada) | ❌ Irregular | `NF_DENEGADA_ESCRITURADA` (error, objetivo) |
| Qualquer | Mapeamento incompatível | ❌ Irregular | `COD_SIT_DIVERGENTE_XML` (error, objetivo) |

**Mapeamento completo cSit → COD_SIT esperado:**

| cSit | Descrição | COD_SIT esperado |
|---|---|---|
| 100 | Autorizada | 00 |
| 101 | Cancelada | 02 |
| 135 | Cancelada fora prazo | 02 |
| 110 | Denegada | 05 |
| 301 | Uso indevido | 05 |
| — | Ausente (sem XML) | — (XML002 warning) |

---

### BUG-004 — Eliminação do Bypass de Autenticação

| Cenário | Comportamento Atual | Comportamento Exigido |
|---|---|---|
| `API_KEY` não configurada | Aceita qualquer valor | HTTP 500: `API Key não configurada. Configure no .env` |
| `API_KEY` < 32 chars | Aceita | HTTP 500: `API Key deve ter mínimo 32 caracteres` |
| Header ausente | HTTP 401 | HTTP 401 (mantido) |
| Header com valor errado | HTTP 401 | HTTP 401 (mantido) |

---

### BUG-005 — Tolerância Proporcional por Magnitude (ver Seção 15 completa)

Substituir a tolerância global `R$ 0,02` por tabela proporcional de 4 faixas.

---

### BUG-006 — DELETE Não-Atômico no Pipeline

**Problema:** O pipeline faz `DELETE FROM validation_errors WHERE file_id = ?` antes de processar. Re-validação durante navegação deixa o sistema sem erros por minutos.

**Correção — Troca Atômica:**

```python
new_errors = []  # acumula todos os novos erros em memória durante o pipeline

# Ao final de todos os estágios:
with db.transaction():
    db.execute("DELETE FROM validation_errors WHERE file_id = ?", [file_id])
    db.bulk_insert("validation_errors", new_errors)
    db.finish_validation_run(run_id)
# Erros antigos só somem quando os novos estão prontos
```

---

### BUG-007 — Docker Compose de Produção

| Arquivo | Incorreto | Correto |
|---|---|---|
| `docker-compose.yml` (prod) | `uvicorn ... --reload` | `uvicorn ... --workers 2 --no-access-log` |
| `docker-compose.dev.yml` (novo) | — | `uvicorn ... --reload --log-level debug` |
| `Dockerfile` prod | Sem healthcheck | `HEALTHCHECK CMD curl -f http://localhost:8021/api/health \|\| exit 1` |

---

## 4. Princípio Arquitetural — Context-First

```
REGRA ABSOLUTA: Zero validações iniciam antes que o ValidationContext
v2 esteja completamente montado e disponível para todos os estágios.

Se o contexto estiver incompleto (cliente não cadastrado, período sem
regime, tabelas ausentes) → pipeline bloqueado com erro acionável.
```

### 4.1 ValidationContext v2

```python
@dataclass
class ClienteInfo:
    id: int
    cnpj: str
    razao_social: str
    regime: Literal["LP", "LR", "SN", "Imune", "Isento"]
    regime_override: str | None      # bypassa regime_detector quando definido
    uf: str                          # default "ES"
    cnae_principal: str
    porte: Literal["ME", "EPP", "Medio", "Grande"]

@dataclass
class BeneficioAtivo:
    codigo: str                      # "COMPETE_ATACADISTA", "FUNDAP", "INVEST_ES", "ST"
    tipo: str
    competencia_inicio: str          # "YYYY-MM"
    competencia_fim: str | None      # None = indeterminado
    ato_concessorio: str             # decreto/portaria
    aliq_icms_efetiva: float | None  # ex: 0.03 = 3%; None = sem redução específica
    cst_icms_validos: list[str]      # CSTs compatíveis com o benefício (via BeneficioEngine)
    cfop_aplicaveis: list[str]       # prefixos: ["5","6"] para saídas
    reducao_base_pct: float | None   # % de redução da BC (ex: 29.41 para COMPETE)
    debito_integral_obrigatorio: bool

@dataclass
class ValidationContext:
    # Identificação
    file_id: int
    run_id: int
    mode: Literal["SPED_ONLY", "SPED_XML_RECON"]
    cnpj_contribuinte: str
    periodo: Periodo
    ind_perfil: str                  # A/B/C — armazenado mas NÃO usado para regime

    # Dados mestres do cliente
    cliente: ClienteInfo
    beneficios_periodo: list[BeneficioAtivo]

    # Lookups derivados pelo ContextBuilder
    cst_validos_saida: set[str]      # CSTs válidos para saídas com benefício
    aliq_esperada_por_cfop: dict[str, float]
    emitentes_sn: set[str]          # CNPJs de fornecedores com CRT=1 (do histórico XML)
    mva_ncm_uf: dict                 # NCM → UF → MVA%
    aliq_interna_uf: dict            # UF → alíquota interna
    fcp_uf: dict                     # UF → % FCP (0 se não tem)
    aliq_interestadual: dict         # (uf_orig, uf_dest) → alíquota

    # Regime (detectado a partir dos CSTs, não do IND_PERFIL)
    regime: Literal["SIMPLES", "NORMAL"]
    regime_source: Literal["CST", "CLIENTES_TABLE", "CONFLITO"]

    # SPED data
    sped_meta: SpedMeta
    ind_ativ: str                    # 0=industrial/equiparado, 1=outros

    # XML (apenas no modo SPED_XML_RECON)
    xml_by_chave: dict[str, NFeXmlData]
    has_xmls: bool
    xml_periodo_ok: bool
    xml_cobertura_pct: float
    xml_cobertura: CoberturaMap

    # Controle de qualidade do contexto
    context_hash: str
    rules_version: str
    tabelas_ausentes: list[str]      # tabelas não carregadas (reduzem score de cobertura)
    context_warnings: list[str]      # ex: "CONFLITO de regime detectado"
```

---

## 5. Dual-Path — Visão Geral

| Dimensão | Caminho A — Validação SPED | Caminho B — Validação SPED × XML |
|---|---|---|
| **Objetivo** | Auditoria escritural e fiscal completa do EFD sem confronto com documentos-fonte | Auditoria reconciliatória entre EFD e NF-e originais da SEFAZ |
| **Entradas** | 1 arquivo SPED (.txt, até 100 MB, chunks) | 1 SPED + N XMLs (upload em lote, chunks por arquivo) |
| **Fonte primária de verdade** | SPED EFD + tabelas fiscais | XML NF-e > Tabelas Fiscais > SPED EFD |
| **Contexto** | Regime + Benefícios + Tabelas fiscais + MVA + FCP | Tudo do A + Mapeamento XML↔SPED + emitentes_crt |
| **Capacidade de detecção** | Inconsistências internas, recálculos, benefícios, DIFAL, ST, apuração | Tudo do A + divergências campo a campo + NF cancelada escriturada |
| **Estágios** | 5 estágios (Stage 0 + 4 validação) | 7 estágios (Stage 0 + 4 validação + 2 XML) |
| **Quando usar** | Sem NF-e disponíveis; validação periódica; Blocos D, H, K | Auditoria pré-fiscalização; validação de C100/C170 contra documentos originais |

---

## 6. Frontend — Interface e UX

### 6.1 Tela Inicial — Seletor de Modo

```
┌──────────────────────────────────────────────────────────────────────────┐
│  [ClientContextBadge — exibido quando cliente já cadastrado]             │
│  🏢 DISTRIBUIDORA EXEMPLO LTDA · 12.345.678/0001-90                     │
│  Regime: Lucro Presumido · UF: ES · Benefícios: COMPETE Atacadista ⚠    │
│  (⚠ = vencimento em 45 dias)                                            │
├──────────────────────────────┬───────────────────────────────────────────┤
│  📋  VALIDAÇÃO SPED          │  🔗  VALIDAÇÃO SPED × XML                 │
│                              │                                           │
│  Auditoria completa do EFD   │  Auditoria reconciliatória entre          │
│  ICMS/IPI com regime,        │  EFD e NF-e originais da SEFAZ.          │
│  benefícios, ST, DIFAL e     │  Campo a campo. Maior precisão e          │
│  fechamento de apuração.     │  defensabilidade fiscal.                  │
│                              │                                           │
│  ✔ Validação estrutural      │  ✔ Tudo da Validação SPED, mais:          │
│  ✔ Recálculo ICMS/IPI        │  ✔ Cruzamento XML × C100/C170            │
│  ✔ Benefícios fiscais        │  ✔ NF cancelada escriturada               │
│  ✔ DIFAL e FCP               │  ✔ CST, CFOP, alíq. item a item          │
│  ✔ ST com MVA                │  ✔ ST/MVA vs. XML do emitente             │
│  ✔ Fechamento C190→E110      │  ✔ Score enriquecido                     │
│                              │                                           │
│  [ Iniciar Validação SPED ]  │  [ Iniciar SPED × XML ]                  │
└──────────────────────────────┴───────────────────────────────────────────┘
```

**Regras de comportamento:**
- Se `clienteInfo === null` → ambos os cards exibem aviso "Cliente não cadastrado. Cadastre antes de validar." + botão de ação.
- Arrastar `.txt` sobre qualquer card → seleciona automaticamente Caminho A com toast.
- Arrastar `.xml` sobre qualquer card → toast: "Para cruzamento com XML, selecione primeiro o modo SPED × XML."
- Troca de modo com arquivos já carregados → modal de confirmação.
- `⚠` no badge de benefício quando `competencia_fim` ≤ 90 dias.

### 6.2 Caminho A — SpedOnlyUploadPanel

```
[ ClientContextBadge ]
[ Label: "Modo: Validação SPED · EFD ICMS/IPI" ]

┌────────────────────────────────────────────────────────┐
│  📄  Arraste o arquivo SPED EFD (.txt)                  │
│      ou clique para selecionar · Máx. 100 MB           │
└────────────────────────────────────────────────────────┘

Painel de Contexto (após parsing do 0000):
  CNPJ · Razão Social · Período · UF · Perfil · Versão layout
  Regime: Simples Nacional [detectado por CSTs 101+]
  Benefícios: COMPETE Atacadista (ativo) · FUNDAP (ativo)
  Tabelas carregadas: MVA ✅ · Alíquotas UF ✅ · FCP ✅ · NCM ✅
  Cobertura estimada: 94% (ST/CIAP requer tabelas adicionais)

[ Botão "Validar SPED" ] ← ativo após upload + contexto carregado

Progresso SSE:
  ① Montagem de Contexto  ② Estrutural e Formato
  ③ Cruzamentos SPED      ④ Apuração e Benefícios
  ⑤ Enriquecimento + Score
```

### 6.3 Caminho B — SpedXmlUploadPanel

```
[ ClientContextBadge ]
[ Label: "Modo: Validação SPED × XML · EFD ICMS/IPI" ]

┌──────────────────────────┐   ┌──────────────────────────────────┐
│  📄 SPED EFD (.txt)      │   │  📦 NF-e XMLs (.xml)             │
│                          │   │                                  │
│  [ ✓ sped_jan26.txt ]    │   │  148/150 processados  98%        │
│  100 MB · CNPJ OK        │   │  ✓ Autorizadas:  146             │
│                          │   │  ⚠ Canceladas:   2               │
│                          │   │  ✗ Malformados:  0               │
│                          │   │  ⚠ Fora do período: 0            │
└──────────────────────────┘   └──────────────────────────────────┘

Painel de Cobertura Documental:
  146 NF-e com XML correspondente (97,3%)
  4 C100 sem XML → cruzamento parcial ⚠
  2 XMLs sem C100 → possível omissão de escrituração

[ Botão "Validar SPED + XMLs" ] ← ativo quando AMBOS completos

Progresso SSE:
  ① Montagem de Contexto   ② Estrutural e Formato
  ③ Cruzamentos SPED       ④ Apuração e Benefícios
  ⑤ Parsing XML (148 NF-e) ⑥ Cruzamento Campo a Campo
  ⑦ Enriquecimento + Score
```

---

## 7. Stage 0 — Montagem de Contexto

Executa **antes de qualquer validação**, em ambos os caminhos. Falha com erro claro e acionável se contexto incompleto.

```python
def build_full_context(file_id: int, mode: str, db: Database) -> ValidationContext:

    # 1. Parsing inicial do 0000
    sped_meta = db.get_sped_meta(file_id)
    cnpj      = sped_meta.cnpj_contribuinte
    periodo   = Periodo(sped_meta.dt_ini, sped_meta.dt_fim)

    # 2. Carregar cliente do cadastro mestre
    cliente = db.get_cliente_by_cnpj(cnpj)
    if not cliente:
        raise ContextBuildError(
            f"Cliente {cnpj} não cadastrado. Cadastre com regime "
            f"tributário antes de validar.",
            action="Ir para /clientes"
        )

    # 3. Detectar regime a partir dos CSTs do SPED (BUG-001)
    regime, regime_source = detect_regime_from_cst(file_id, db, cliente)

    # 4. Carregar benefícios ativos no período
    beneficios = db.get_beneficios_ativos(cliente.id, periodo)
    engine     = BeneficioEngine(cliente, beneficios, periodo.ini)

    # 5. Carregar tabelas fiscais
    mva_ncm_uf    = load_yaml("data/config/mva_por_ncm_uf.yaml")
    aliq_int_uf   = load_yaml("data/config/aliquotas_internas_uf.yaml")
    fcp_uf        = load_yaml("data/config/fcp_por_uf.yaml")
    tabelas_aus   = detect_missing_tables(mva_ncm_uf, aliq_int_uf, fcp_uf)

    # 6. Carregar caches do Bloco 0 (imutáveis durante a validação)
    participantes = db.get_bloco_0_by_register(file_id, "0150")  # dict cnpj → 0150
    produtos      = db.get_bloco_0_by_register(file_id, "0200")  # dict cod_item → 0200
    naturezas     = db.get_bloco_0_by_register(file_id, "0400")  # dict cod_nat → 0400
    # Usados pelos validadores sem queries adicionais ao banco durante os estágios

    # 7. Carregar emitentes_crt do histórico
    emitentes_sn = db.get_emitentes_sn()   # set[str] CNPJs com CRT=1

    # 7. Validar e carregar XMLs (só no modo SPED_XML_RECON)
    xml_data = {}
    if mode == "SPED_XML_RECON":
        xml_data = build_xml_context(file_id, db, periodo)

    # 8. Montar context_hash (para invalidar cache IA se contexto mudar)
    context_hash = _hash_context(regime, beneficios, periodo)

    # 9. Registrar run de validação
    run_id = db.create_validation_run(
        file_id, mode, cliente, regime, beneficios, context_hash
    )

    return ValidationContext(
        file_id=file_id, run_id=run_id, mode=mode,
        cnpj_contribuinte=cnpj, periodo=periodo,
        ind_perfil=sped_meta.ind_perfil,   # armazenado mas NÃO usado como regime
        cliente=cliente, beneficios_periodo=beneficios,
        regime=regime, regime_source=regime_source,
        cst_validos_saida=engine.get_cst_validos_saida_all(),
        aliq_esperada_por_cfop=engine.get_aliq_map(),
        emitentes_sn=emitentes_sn,
        mva_ncm_uf=mva_ncm_uf, aliq_interna_uf=aliq_int_uf, fcp_uf=fcp_uf,
        sped_meta=sped_meta, ind_ativ=sped_meta.ind_ativ,
        tabelas_ausentes=tabelas_aus,
        context_hash=context_hash, rules_version=RULES_VERSION,
        **xml_data,
    )
```

### 7.1 Detecção de Regime por CST (BUG-001 fix)

```python
def detect_regime_from_cst(file_id, db, cliente) -> tuple[str, str]:
    # Varrer C170 e C190 em busca de CSTs SN
    has_sn_cst = db.query_one("""
        SELECT 1 FROM sped_records
        WHERE file_id = ? AND register IN ('C170','C190')
          AND (
            CAST(cst_icms AS INTEGER) BETWEEN 101 AND 900
            OR cst_icms IN ('101','102','103','201','202','203','300','400','500','900')
          )
        LIMIT 1
    """, [file_id])

    regime_cst = "SIMPLES" if has_sn_cst else "NORMAL"
    regime_table = cliente.regime if cliente else None

    if regime_table and regime_table != "SN" and regime_cst == "SIMPLES":
        return "SIMPLES", "CONFLITO"
    if regime_table and regime_table == "SN" and regime_cst == "NORMAL":
        return "SIMPLES", "CONFLITO"   # cadastro diz SN mas CSTs são normais

    return regime_cst, "CST"
```

### 7.2 Validação de Período dos XMLs

```python
def build_xml_context(file_id, db, periodo) -> dict:
    xmls = db.get_nfe_xmls(file_id)
    if not xmls:
        return {"xml_by_chave": {}, "has_xmls": False,
                "xml_periodo_ok": True, "xml_cobertura_pct": 0.0,
                "xml_cobertura": CoberturaMap.empty()}

    fora = [x for x in xmls if not periodo.contains(x.dh_emissao)]
    if len(fora) / max(len(xmls), 1) > 0.10:
        raise ContextBuildError(
            f"{len(fora)} de {len(xmls)} XMLs fora do período "
            f"{periodo.ini}–{periodo.fim}. Verifique o mês dos arquivos.",
            severity="warning_bloqueante"
        )

    # Rejeitar namespaces inválidos (MDF-e, CT-e)
    invalidos = [x for x in xmls if x.namespace != "http://www.portalfiscal.inf.br/nfe"]
    for x in invalidos:
        x.status = "rejected"
        x.rejection_reason = "Namespace inválido — apenas NF-e aceita"

    chaves_c100 = db.get_chaves_c100(file_id)
    chaves_xml  = {x.chave_nfe for x in xmls if x.status == "active"}
    matched     = chaves_c100 & chaves_xml

    return {
        "xml_by_chave":      {x.chave_nfe: x for x in xmls if x.status == "active"},
        "has_xmls":          True,
        "xml_periodo_ok":    len(fora) == 0,
        "xml_cobertura_pct": len(matched) / max(len(chaves_c100), 1),
        "xml_cobertura":     CoberturaMap(
            matched=matched,
            sem_xml=chaves_c100 - chaves_xml,
            sem_c100=chaves_xml - chaves_c100
        )
    }
```

---

## 8. BeneficioEngine

### 8.1 Responsabilidade

Lê os JSONs de benefícios (`COMPETE_ES_Atacadista.json`, `FUNDAP.json`, `INVEST_ES_*.json`, `SUBSTITUICAO_TRIBUTARIA_ES.json`) e responde perguntas fiscais concretas, levando em conta múltiplos benefícios simultâneos.

### 8.2 Interface Pública

```python
class BeneficioEngine:

    def __init__(self, cliente, beneficios, periodo, json_dir="data/JSON"):
        self._active = [b for b in beneficios if self._is_active(b, periodo)]
        self._rules  = self._load_and_merge(self._active, json_dir)

    def get_cst_validos_saida(self, cfop: str) -> set[str]:
        """CSTs ICMS válidos para saídas dado CFOP e benefícios ativos.
        Union dos conjuntos de todos os benefícios aplicáveis ao CFOP."""

    def get_aliq_esperada(self, cfop: str, ncm: str | None = None) -> float | None:
        """Alíquota ICMS efetiva após benefício. None = sem benefício aplicável.
        Conflito (dois benefícios, alíqs diferentes) → registrar warning."""

    def get_reducao_bc(self, cfop: str, ncm: str | None = None) -> float | None:
        """% de redução da BC (ex: 29.41 para COMPETE atacadista em determinadas ops)."""

    def get_debito_integral(self, cfop: str) -> bool:
        """Benefício exige débito integral? (relevante para crédito presumido)."""

    def is_ncm_no_escopo(self, ncm: str, beneficio_codigo: str) -> bool:
        """NCM está no escopo do benefício? (cruzar com Tabela_NCM_Vigente.json)."""

    def audit_item_xml(self, item: NFeItem, emitente_crt: int,
                       cfop: str) -> list[BeneficioAuditResult]:
        """Audita item da NF-e de saída contra regras de benefício.
        Retorna lista de violações (vazia = OK)."""

    def get_crt_expected_cst_set(self, crt: int) -> tuple[str, set[str]]:
        """(campo_cst, valores_válidos) baseado no CRT do emitente."""
        if crt == 1:   # Simples Nacional
            return ("CSOSN", {"101","102","103","201","202","203","300","400","500","900"})
        return ("CST_ICMS", {"00","10","20","30","40","41","50","51","60","70","90"})

    def get_conflitos_beneficios(self) -> list[str]:
        """Lista de avisos de conflito entre benefícios simultâneos."""

    def get_beneficios_expirando(self, dias: int = 90) -> list[BeneficioAtivo]:
        """Benefícios com competencia_fim dentro dos próximos N dias.
        Usado pelo ClientContextBadge para exibir o ⚠ de vencimento."""
```

### 8.3 Regras de Benefícios ICMS — Espírito Santo

| Benefício | Alíq. Efetiva | CSTs Esperados (saída) | Obriga Débito Integral |
|---|---|---|---|
| COMPETE-ES Atacadista | 3% (crédito presumido) | 00 (trib. integral) com ajuste E111 | Sim |
| COMPETE-ES E-commerce | 3% a 6% conforme produto | 00 | Sim |
| COMPETE-ES Logística | 0% a 3% | 40 ou 00 com ajuste | Depende |
| INVEST-ES | Diferimento parcial ou total | 51 (diferido) ou conforme ato | Não (diferimento) |
| FUNDAP | Regime especial de crédito | 00 com crédito sobre pauta | Sim |
| ST (contribuinte substituto) | Conforme MVA/NCM/UF | 10, 30, 70 | N/A |

---

## 9. Pipeline Caminho A — Validação SPED

### Estágio 1 — Ingestão e Parsing

| Sub-etapa | Processamento |
|---|---|
| 1.1 Detecção de encoding | `latin-1` → `cp1252` → `utf-8` → fallback `latin-1 errors="replace"` |
| 1.2 Parsing linha a linha | Split pipe-delimited; `REGISTER_FIELDS` → dict nomeado; batch de 1.000 linhas |
| 1.3 Extração do 0000 | CNPJ, UF, DT_INI, DT_FIN, IND_PERFIL, IND_ATIV, COD_VER, COD_FIN |
| 1.4 Detecção de regime | Por CSTs (BUG-001 fix) — `IND_PERFIL` ignorado para regime |
| 1.5 Confirmação regime | Tabela `clientes`; conflito → `regime_source='CONFLITO'` + alerta |
| 1.6 Carga de benefícios | JSONs por CNAE e vigência; instancia BeneficioEngine |
| 1.7 Detecção de retificador | `COD_FIN > 0`; busca original por CNPJ+período |
| 1.8 Hash SHA-256 | Deduplicação; reuso de análise se arquivo idêntico |

---

### Estágio 2 — Validação Estrutural (Context-Aware)

| Validador | Adaptação por Regime | Adaptação por Benefício |
|---|---|---|
| `format_validator` | Nenhuma | Nenhuma |
| `intra_register_validator (C100)` | SN: tolera CHV_NFE de 44 dígitos com CSOSN emitente | FUNDAP: VL_FRT com tratamento diferenciado |
| `intra_register_validator (C170)` | SN: CSOSN em vez de CST; normalizar 6 dígitos → 2 | COMPETE: ALIQ_ICMS pode ser 12% com crédito presumido |
| `simples_validator` | Ativado apenas se `regime=SIMPLES` | Verifica CSOSN permitidos por CNAE do benefício SN |
| `beneficio_audit_validator` | Regime determina CSTs compatíveis | 50+ regras usando `ctx.beneficios_ativos` |

---

### Estágio 3 — Cruzamentos e Recálculo Tributário

#### 3.1 Cruzamento C100 × Soma C170

Para cada C100:

| Campo C100 | Verificação | Error Type |
|---|---|---|
| `VL_DOC` | = Σ C170.VL_ITEM − Σ C170.VL_DESC + Σ C170.VL_ICMS_ST + Σ C170.VL_IPI + C100.VL_FRT | `C100_VL_DOC_INCONSISTENTE` |
| `VL_ICMS` | = Σ C170.VL_ICMS | `C100_ICMS_INCONSISTENTE` |
| `VL_ICMS_ST` | = Σ C170.VL_ICMS_ST | `C100_ICMS_ST_INCONSISTENTE` |
| `VL_IPI` | = Σ C170.VL_IPI | `C100_IPI_INCONSISTENTE` |

#### 3.2 Recálculo ICMS-ST com MVA (BUG-002 fix)

Fórmula completa de 4 etapas — ver Seção 3 (BUG-002).

#### 3.3 Recálculo de DIFAL e FCP

```python
# EC 87/2015 + LC 190/2022
# Para operações interestaduais com consumidor final não contribuinte

aliq_interestadual = ctx.aliq_interestadual[(uf_orig, uf_dest)]
aliq_interna_dest  = ctx.aliq_interna_uf[uf_dest]
FCP_pct            = ctx.fcp_uf.get(uf_dest, 0.0)

BC_DIFAL  = VL_BC_ICMS  # base de cálculo da operação
VL_DIFAL_ESP = BC_DIFAL * (aliq_interna_dest - aliq_interestadual) / 100
VL_FCP_ESP   = BC_DIFAL * FCP_pct / 100

# Período de transição EC 87/2015 (2016-2018): partilha ORIGEM/DESTINO
# A partir de 2019: 100% DESTINO
if periodo.ini >= "2019-01":
    partilha_dest = 1.0
else:
    partilha_dest = PARTILHA_TABLE[periodo.ano]

VL_DIFAL_DEST_ESP = VL_DIFAL_ESP * partilha_dest

divergencia = abs(C100.VL_ICMS_DESON - VL_DIFAL_DEST_ESP)
if divergencia > tolerancia_proporcional(VL_DIFAL_DEST_ESP):
    gerar DIFAL_VALOR_DIVERGENTE(...)
```

#### 3.4 Validação de Benefícios com Cruzamento de Contexto

| Regra | Fonte SPED | Fonte Contexto | Error Type |
|---|---|---|---|
| Benefício usado sem estar ativo | `E111.COD_AJ_APUR` com código de benefício | `ctx.beneficios_ativos` por período | `BENEFICIO_NAO_ATIVO` (error) |
| CNAE inelegível ao benefício | CNPJ → CNAE em `clientes` | `ctx.beneficio_cnae_map` | `BENEFICIO_CNAE_INELEGIVEL` (error) |
| Benefício fora da vigência | `E111` período vs. `competencia_fim` | `BeneficioAtivo.competencia_fim` | `BENEFICIO_FORA_VIGENCIA` (error) |
| Sobreposição de benefícios incompatíveis | 2+ E111 com benefícios conflitantes | `ctx.beneficio_restricoes` | `SOBREPOSICAO_BENEFICIOS` (error) |
| Débito integral não mantido | ALIQ reduzida com benefício de débito integral | `BeneficioAtivo.debito_integral_obrigatorio` | `BENEFICIO_DEBITO_NAO_INTEGRAL` (error) |
| Código de ajuste E111 incompatível | `E111.COD_AJ_APUR` | `ctx.codigos_ajuste_uf[UF][beneficio]` | `CODIGO_AJUSTE_INCOMPATIVEL` (error) |
| Crédito presumido sem lastro | Crédito em E111 sem NF de entrada correspondente | Cruzamento C190 × E111 | `CREDITO_PRESUMIDO_SEM_LASTRO` (error) |

---

### Estágio 4 — Apuração e Coerência Fiscal

Ver Seção 13 (Cadeia de Fechamento Fiscal) para especificação completa.

---

### Estágio 5 — Enriquecimento, Deduplicação e Score

| Sub-etapa | Processamento |
|---|---|
| Mensagens amigáveis | PT-BR por `error_type`; valores concretos (campo, linha, encontrado vs. esperado) |
| Base legal por regra | `rules.yaml[rule.base_legal]`; obrigatório em 100% das regras |
| Explicabilidade | Cada erro informa: fonte do dado, XPath/campo comparado, caminho de derivação |
| Hipótese vs. objetivo | Certeza `objetivo`/`provável`/`indício` obrigatória; hipóteses rotuladas explicitamente |
| Cobertura | Marcar regras `NAO_EXECUTADA` quando tabelas ausentes; registrar em `coverage_gaps` |
| Deduplicação | Estratégia: hipóteses supersede genéricos; mesma causa raiz agrupa; campo repetido mantém mais acionável |
| Score de risco | Ver Seção 16 |

---

## 10. Pipeline Caminho B — Validação SPED × XML

**Estágios 1 a 5 idênticos ao Caminho A**, executados integralmente antes do cruzamento XML.

### Estágio 6 — Parsing e Indexação de XMLs

| Parâmetro | Especificação |
|---|---|
| Paralelismo | Até 5 XMLs em paralelo via `ThreadPoolExecutor(max_workers=5)` |
| Chunk size | 512 KB por chunk |
| Timeout por arquivo | 30 segundos → `XML_TIMEOUT` (warning) |
| Namespace aceito | `http://www.portalfiscal.inf.br/nfe` exclusivamente; MDF-e e CT-e rejeitados |
| Envelope aceito | `<nfeProc>` (com protocolo) e `<NFe>` (sem protocolo); nenhum gera erro |
| CRT persistido | Extrair e salvar `emit/CRT` → `emitentes_crt` e `nfe_xmls.crt_emitente` |
| Período validado | `dh_emissao` fora do período → marcado em `nfe_xmls.dentro_periodo = 0` |

---

### Estágio 7 — Cruzamento Campo a Campo com Contexto

#### Algoritmo de Vinculação

```
1. Para cada XML active: extrair chave 44 dígitos de //infNFe/@Id
2. Buscar C100 onde CHV_NFE = chave → vínculo 1:1
3. Para cada //det[N]: buscar C170 com NUM_ITEM = N AND c100_id correspondente → 1:1
4. C100 sem XML → XML002 (warning) — registrar em xml_match_index
5. XML sem C100 → XML001 (error) — possível omissão de escrituração
```

#### Camadas de Enriquecimento

| Camada | Dado do Contexto | Como Altera o Cruzamento |
|---|---|---|
| Regime | `ctx.regime` | SN: aceitar CSOSN no XML; Normal: exigir CST 2 dígitos |
| CRT emitente | `ctx.emitentes_sn` + `nfe_xmls.crt_emitente` | CST_AWARE: CST vs. CSOSN conforme CRT |
| Benefícios ativos | `ctx.beneficios_ativos` | COMPETE: ALIQ_ICMS 12% com crédito presumido → não gerar XML010 para itens elegíveis |
| Alíquotas por UF | `ctx.aliq_interna_uf` | ALIQ_ICMS do XML deve ser correta para UF origem/destino |
| MVA por NCM | `ctx.mva_ncm_uf` | VL_BC_ICMS_ST no XML revalidado contra MVA tabelado |
| FCP por UF | `ctx.fcp_uf` | UF com FCP: verificar `vFCPST` no XML |
| Status NF | `cSit` no XML | BUG-003: cancelada/denegada × COD_SIT no C100 |

---

## 11. Mapa de Equivalência SPED ↔ XML (ICMS/IPI)

### 11.1 Configuração Externalizada

O mapa é armazenado em dois lugares complementares:
- `data/config/field_map.yaml` — configuração de comparação (carregada em runtime)
- Tabela `field_equivalence_catalog` no banco (versionada, mantida via CRUD)

```yaml
# data/config/field_map.yaml
c100_header:
  - sped_campo: CHV_NFE
    xml_xpath: ".//protNFe/infProt/chNFe"
    tipo: EXACT
    join_key: true
    normalizacao: "remove_prefix_NFe; assert_len_44; validate_dv"

  - sped_campo: VL_DOC
    xml_xpath: ".//total/ICMSTot/vNF"
    tipo: MONETARY
    tolerancia_tier: proporcional
    regra_id: XML_C100_VL_DOC
    severidade: high

  - sped_campo: VL_ICMS
    xml_xpath: ".//total/ICMSTot/vICMS"
    tipo: MONETARY
    tolerancia_tier: proporcional
    regra_id: XML_C100_VL_ICMS
    severidade: high
    contexto_beneficio: true   # verificar aliq_efetiva do BeneficioEngine

c170_items:
  - sped_campo: CST_ICMS
    xml_xpath: ".//imposto/ICMS/*/CST | .//imposto/ICMS/*/CSOSN"
    tipo: CST_AWARE
    regra_id: XML008
    severidade: high
    contexto_regime: true

  - sped_campo: ALIQ_ICMS
    xml_xpath: ".//imposto/ICMS/*/pICMS"
    tipo: PERCENTAGE
    tolerancia: 0.001
    regra_id: XML010
    severidade: high
    contexto_beneficio: true

  - sped_campo: CST_IPI
    xml_xpath: ".//imposto/IPI/*/CST"
    tipo: EXACT
    regra_id: XML_CST_IPI_DIVERGENTE
    severidade: warning
    condicao: "ind_ativ == '0'"   # apenas para industriais
```

### 11.2 Tipos de Comparação

| Tipo | Descrição | Exemplo |
|---|---|---|
| `EXACT` | Igualdade de string após normalização (trim, uppercase) | CNPJ, chave NF-e, série, NUM_DOC, COD_MOD |
| `MONETARY` | Comparação decimal com tolerância proporcional (ver Seção 15) | VL_DOC, VL_ICMS, VL_IPI, VL_BC_ICMS |
| `PERCENTAGE` | Comparação decimal com tolerância 0,001% | ALIQ_ICMS, ALIQ_ST, ALIQ_IPI |
| `DATE` | Normalização para AAAA-MM-DD antes de comparar | DT_DOC, DT_E_S |
| `CST_AWARE` | CST ou CSOSN conforme CRT do emitente (resolve BUG-001 no cruzamento XML) | CST_ICMS em C170 |
| `DERIVED` | Campo calculado sem equivalente direto; regra específica | SIT_DOC derivado de cSit |
| `SKIP` | Sem equivalente no XML; comparação não aplicável | COD_SIT exceto via DERIVED |

### 11.3 Nível 1 — Cabeçalho NF-e ↔ C100

XPaths relativos a `/NFe/infNFe/`

| C100 Campo | XML XPath | Tipo | Tol. | Regra | Observação |
|---|---|---|---|---|---|
| `CHV_NFE` | `/protNFe/infProt/chNFe` | EXACT | — | XML016 | 44 dígitos; DV validado; **join key** |
| `CNPJ_EMIT` | `/emit/CNPJ` | EXACT | — | XML012 | Remove não-dígitos; 14 chars |
| `CNPJ_DEST` | `/dest/CNPJ` ou `/dest/CPF` | EXACT | — | XML012 | Pessoa física: CPF |
| `NUM_DOC` | `/ide/nNF` | EXACT | — | `XML_NUM_DIVERGENTE` | Sem zeros à esquerda |
| `SER` | `/ide/serie` | EXACT | — | XML017 | Pad zeros até 3 chars |
| `COD_MOD` | `/ide/mod` | EXACT | — | — | 55=NF-e, 65=NFC-e |
| `DT_DOC` | `/ide/dhEmi` | DATE | — | XML015 | XML tem horário → truncar para data |
| `DT_E_S` | `/ide/dhSaiEnt` | DATE | — | `XML_DT_ES_DIV` | Pode ser ausente em NF-e de entrada |
| `VL_DOC` | `/total/ICMSTot/vNF` | MONETARY | proporcional | XML004 | |
| `VL_ICMS` | `/total/ICMSTot/vICMS` | MONETARY | proporcional | XML_C100_VL_ICMS | Com verificação de benefício |
| `VL_BC_ICMS` | `/total/ICMSTot/vBC` | MONETARY | proporcional | `XML_BC_ICMS_TOT` | |
| `VL_ICMS_ST` | `/total/ICMSTot/vST` | MONETARY | proporcional | `XML_ST_TOTAL_DIV` | |
| `VL_IPI` | `/total/ICMSTot/vIPI` | MONETARY | proporcional | XML_C100_VL_IPI | Só para ind_ativ='0' (industriais) |
| `VL_FRT` | `/total/ICMSTot/vFrete` | MONETARY | proporcional | `XML_FRETE_DIVERGENTE` | Relevante para MVA |
| `VL_DESC` | `/total/ICMSTot/vDesc` | MONETARY | proporcional | `XML_DESC_DIVERGENTE` | |
| `VL_PROD` | `/total/ICMSTot/vProd` | MONETARY | proporcional | — | Valor bruto produtos |
| `SIT_DOC` | `/protNFe/infProt/cStat` | DERIVED | — | BUG-003 | cSit 100→00; 101/135→02; 110/301→05 |
| `IND_OPER` | `/ide/tpNF` | DERIVED | — | — | 0=entrada, 1=saída |
| `IND_PGTO` | `/ide/indPag` | EXACT | — | `XML_PGTO_DIV` | 0=à vista; 1=prazo; 2=outros |
| `IE dest` | `/dest/IE` | EXACT | — | XML013 | |
| `UF dest` | `/dest/enderDest/UF` | EXACT | — | XML014 | |

### 11.4 Nível 2 — Itens NF-e ↔ C170 (ICMS e IPI — sem PIS/COFINS)

XPaths relativos a `/det[N]/`

| C170 Campo | XML XPath | Tipo | Tol. | Regra | Observação |
|---|---|---|---|---|---|
| `NUM_ITEM` | `/@nItem` | EXACT | — | — | **Join key**; @nItem é 1-based |
| `COD_ITEM` | `/prod/cProd` | EXACT | — | `XML_COD_ITEM_DIV` | Código do produto no ERP emitente |
| `QTD` | `/prod/qCom` | MONETARY | 0,001 | `XML_QTD_DIVERGENTE` | Até 4 casas decimais |
| `UNID` | `/prod/uCom` | EXACT | — | `XML_UNID_DIVERGENTE` | Uppercase antes de comparar |
| `VL_ITEM` | `/prod/vProd` | MONETARY | proporcional | XML011_A | Valor bruto do item |
| `VL_DESC` | `/prod/vDesc` | MONETARY | proporcional | `XML_DESC_ITEM_DIV` | |
| `VL_FRT` | `/prod/vFrete` | MONETARY | proporcional | `XML_FRETE_ITEM_DIV` | Rateio do frete no item |
| `NCM` | `/prod/NCM` | EXACT | — | XML009 | 8 dígitos sem pontuação |
| `CFOP` | `/prod/CFOP` | EXACT | — | XML007 | 4 dígitos |
| `CST_ICMS` | `/imposto/ICMS/*/CST` **ou** `/imposto/ICMS/*/CSOSN` | CST_AWARE | — | XML008 | **Usar CSOSN se CRT=1; CST se CRT=3** |
| `VL_BC_ICMS` | `/imposto/ICMS/*/vBC` | MONETARY | proporcional | `XML_BC_ICMS_DIVERGENTE` | |
| `VL_RED_BC` | `/imposto/ICMS/*/pRedBC` derivado | PERCENTAGE | 0,001% | `XML_RED_BC_DIVERGENTE` | CST 20: verificar % redução |
| `ALIQ_ICMS` | `/imposto/ICMS/*/pICMS` | PERCENTAGE | 0,001% | XML010 | Verificar vs. tabela UF e benefício |
| `VL_ICMS` | `/imposto/ICMS/*/vICMS` | MONETARY | proporcional | XML011 | |
| `VL_BC_ICMS_ST` | `/imposto/ICMS/*/vBCST` | MONETARY | proporcional | `XML_BC_ST_DIVERGENTE` | Validar vs. MVA (BUG-002) |
| `ALIQ_ST` | `/imposto/ICMS/*/pICMSST` | PERCENTAGE | 0,001% | `XML_ALIQ_ST_DIVERGENTE` | |
| `VL_ICMS_ST` | `/imposto/ICMS/*/vICMSST` | MONETARY | proporcional | `XML_ICMS_ST_DIVERGENTE` | |
| `FCP` (ctx) | `/imposto/ICMS/*/vFCPST` | MONETARY | proporcional | `XML_FCP_AUSENTE_XML` | Ausente quando UF tem FCP |
| `CST_IPI` | `/imposto/IPI/*/CST` | EXACT | — | `XML_CST_IPI_DIVERGENTE` | Só se `ind_ativ='0'` |
| `VL_BC_IPI` | `/imposto/IPI/*/vBC` | MONETARY | proporcional | `XML_BC_IPI_DIVERGENTE` | |
| `ALIQ_IPI` | `/imposto/IPI/*/pIPI` | PERCENTAGE | 0,001% | `XML_ALIQ_IPI_DIVERGENTE` | |
| `VL_IPI` | `/imposto/IPI/*/vIPI` | MONETARY | proporcional | `XML_IPI_DIVERGENTE` | |

### 11.5 Nível 3 — C190 ↔ XML (Totalização Indireta)

C190 não tem campo direto no XML. Verificação por agregação:

```
Para cada NF-e com XML correspondente:
  1. Agrupar det[] por (CST_ICMS_normalizado, CFOP, pICMS)
  2. Somar: vBC_grupo, vICMS_grupo, vBCST_grupo

Para cada C190 do SPED (mesmo CST/CFOP/ALIQ):
  3. Comparar:
     C190.VL_BC_CONT   vs soma_xml.vBC_grupo   (tol. proporcional)
     C190.VL_ICMS_TOT  vs soma_xml.vICMS_grupo  (tol. proporcional)
     C190.VL_BC_ICMS_ST vs soma_xml.vBCST_grupo (tol. proporcional)

  4. Divergência → XML_C190_DIVERGE
     "C190 CST={cst} CFOP={cfop}: SPED R${sped} vs XML R${xml} (diff R${diff})"
```

### 11.6 Campos sem Equivalente XML

| Campo SPED | Registro | Motivo |
|---|---|---|
| `IND_APUR` | C170/C190 | Indicador de período de apuração — apenas no SPED |
| `COD_CTA` | C170 | Conta contábil — dado do ERP |
| `TXT_COMPL` | C100 | Texto livre — sem regra de comparação |
| `VL_ABAT_NT` | C100 | Abatimento fiscal do contribuinte |
| `COD_MOT_REST` | E111 | Código de motivo de ajuste — sem XML equivalente |

---

## 12. Motor de Cruzamento Campo-a-Campo

### 12.1 FieldComparator

```python
class FieldComparator:

    def compare(self, sped_val, xml_val, field_def, context) -> CompareResult:
        tipo = field_def["tipo"]
        if tipo == "EXACT"     : return self._exact(sped_val, xml_val)
        if tipo == "MONETARY"  : return self._monetary(sped_val, xml_val, field_def)
        if tipo == "PERCENTAGE": return self._percentage(sped_val, xml_val)
        if tipo == "DATE"      : return self._date(sped_val, xml_val)
        if tipo == "CST_AWARE" : return self._cst_aware(sped_val, xml_val, context)
        return CompareResult.SKIP

    def _monetary(self, sped, xml, field_def) -> CompareResult:
        sped_d = Decimal(str(sped or 0))
        xml_d  = Decimal(str(xml or 0))
        diff   = abs(sped_d - xml_d)
        tol    = tolerancia_proporcional(max(sped_d, xml_d))   # Seção 15
        if diff <= tol:
            if diff > 0:
                return CompareResult.ok_arredondamento(diff=float(diff))
            return CompareResult.ok()
        return CompareResult.diverge(
            sped_val=float(sped_d), xml_val=float(xml_d),
            diferenca=float(diff),
            percentual=float(diff / max(sped_d, Decimal("0.01")) * 100)
        )

    def _cst_aware(self, sped_cst, xml_cst, context) -> CompareResult:
        """Resolve BUG-001: CST vs CSOSN conforme CRT do emitente."""
        # Normalizar: remover zeros à esquerda, uppercase
        sped_n = sped_cst.lstrip("0").upper() if sped_cst else ""
        xml_n  = xml_cst.lstrip("0").upper() if xml_cst else ""

        emitente_sn = xml_n in {"101","102","103","201","202","203",
                                  "300","400","500","900"}

        if emitente_sn:
            # XML tem CSOSN → verificar se SPED tem CST equivalente
            cst_equiv = CSOSN_TO_CST.get(xml_n)  # tabela da Seção 3.1
            if sped_n != cst_equiv:
                return CompareResult.diverge(
                    sped_val=sped_cst, xml_val=xml_cst,
                    nota=f"Emitente SN: CSOSN {xml_n} → CST equivalente esperado {cst_equiv}"
                )
        else:
            if sped_n != xml_n:
                return CompareResult.diverge(sped_val=sped_cst, xml_val=xml_cst)

        return CompareResult.ok()
```

### 12.2 Política de Campos Ausentes

```
SPED tem valor, XML ausente:
  join_key=true       → ERROR "Campo obrigatório ausente no XML"
  campo opcional      → WARN "Campo {campo} presente no SPED mas ausente no XML"
  MONETARY e XML=0    → comparar contra 0,0 (legítimo p/ SN)

XML tem valor, SPED ausente ou zero:
  abs(xml) > tol × 10 → ERROR
  abs(xml) ≤ tol × 10 → WARN

Ambos ausentes ou zero → OK — sem divergência

"0,00" vs ausente → tratar como equivalentes
```

---

## 13. Cadeia de Fechamento Fiscal

Esta é a espinha dorsal da auditoria do Caminho A. Cada elo valida que o elo anterior se refletiu corretamente.

### 13.1 Documento → Item (C100 × C170)

```
Para cada C100:
  VL_DOC_calculado = Σ(C170.VL_ITEM) - Σ(C170.VL_DESC)
                   + Σ(C170.VL_ICMS_ST) + Σ(C170.VL_IPI)
                   + C100.VL_FRT + C100.VL_SEG + C100.VL_OUT_DA

  diff = abs(C100.VL_DOC - VL_DOC_calculado)
  if diff > tolerancia_proporcional(C100.VL_DOC):
      ERROR C100_VL_DOC_INCONSISTENTE
      "C100 linha {n}: VL_DOC={C100.VL_DOC} mas soma dos C170 = {VL_DOC_calculado}"

  # Item com tributo sem reflexo no cabeçalho
  if any(c170.vl_icms_st > 0) and C100.VL_ICMS_ST == 0:
      ERROR C100_ICMS_ST_AUSENTE_CABECALHO

  # C100 sem nenhum C170 vinculado
  if count(C170) == 0:
      ERROR C100_SEM_ITENS
```

### 13.2 Item → Consolidação (C170 × C190)

```
Para cada grupo (CST_ICMS, CFOP, ALIQ_ICMS):
  soma_c170 = {
    VL_BC_CONT: Σ C170.VL_BC_ICMS,
    VL_ICMS_TOT: Σ C170.VL_ICMS,
    VL_BC_ICMS_ST: Σ C170.VL_BC_ICMS_ST,
    VL_ICMS_ST: Σ C170.VL_ICMS_ST,
  }
  c190 = buscar C190 com (CST=cst, CFOP=cfop, ALIQ=aliq)

  if c190 is None:
      ERROR C190_AUSENTE_PARA_GRUPO
      "Grupo CST={cst} CFOP={cfop} ALIQ={aliq} presente em C170 sem C190"

  for campo in ["VL_BC_CONT","VL_ICMS_TOT","VL_BC_ICMS_ST","VL_ICMS_ST"]:
      diff = abs(c190[campo] - soma_c170[campo])
      if diff > tolerancia_proporcional(c190[campo]):
          ERROR C190_DIVERGE_SOMA_C170
          "C190 {campo}: R${c190[campo]} vs soma C170: R${soma_c170[campo]}"
```

### 13.3 Consolidação → Apuração (C190 × E110)

```
Soma de débitos do período:
  total_debitos = Σ C190.VL_ICMS_TOT onde CFOP de saída (5xxx, 6xxx, 7xxx)
                + E110.VL_OUT_DEBITOS

Soma de créditos:
  total_creditos = Σ C190.VL_ICMS_TOT onde CFOP de entrada (1xxx, 2xxx, 3xxx)
                 + E110.VL_OUT_CREDITOS + E110.VL_SLD_CREDOR_ANT

Saldo esperado:
  VL_SLD_ESP = total_debitos - total_creditos

diff = abs(E110.VL_SLD_APURADO - VL_SLD_ESP)
if diff > tolerancia_proporcional(max(VL_SLD_ESP, 1.0)):
    ERROR E110_SALDO_INCONSISTENTE

# E110 com VL_ICMS_RECOLHER = 0 e débitos > créditos sem E111
if E110.VL_ICMS_RECOLHER == 0 and VL_SLD_ESP > 0:
    has_ajuste = exists E111 with COD_AJ_APUR explaining the difference
    if not has_ajuste:
        ERROR ICMS_ZERADO_SEM_AJUSTE
```

### 13.4 Apuração → Ajuste (E110 × E111)

```
# Cada E111 deve ter COD_AJ_APUR válido para UF e período
for e111 in bloco_e.e111_registros:
    cod_aj = e111.cod_aj_apur
    if cod_aj not in ctx.codigos_ajuste_uf[ctx.uf]:
        ERROR CODIGO_AJUSTE_INVALIDO_UF
        f"E111: COD_AJ_APUR={cod_aj} não válido para UF={ctx.uf}"

    # Benefício ativo no E111 deve estar em ctx.beneficios_ativos
    if cod_aj in CODIGOS_BENEFICIO_MAP:
        beneficio = CODIGOS_BENEFICIO_MAP[cod_aj]
        if beneficio not in {b.codigo for b in ctx.beneficios_ativos}:
            ERROR BENEFICIO_NAO_ATIVO

# Soma E111 deve se reconciliar com E110
soma_e111_debitos  = Σ E111.VL_AJ_APUR where is_debito(cod_aj)
soma_e111_creditos = Σ E111.VL_AJ_APUR where is_credito(cod_aj)

if abs((E110.VL_OUT_DEBITOS - soma_e111_debitos)) > tol:
    ERROR E110_OUT_DEBITOS_INCONSISTENTE
```

### 13.5 Ajuste → Recolhimento (E111 × E116)

```
# E116 deve existir para cada ICMS a recolher
if E110.VL_ICMS_RECOLHER > 0:
    e116_list = buscar E116 vinculados ao E110
    if not e116_list:
        ERROR E116_AUSENTE_COM_ICMS_RECOLHER
    else:
        soma_e116 = Σ E116.VL_OR
        diff = abs(soma_e116 - E110.VL_ICMS_RECOLHER)
        if diff > tolerancia_proporcional(E110.VL_ICMS_RECOLHER):
            ERROR E116_SOMA_DIVERGE_ICMS_RECOLHER
            f"Σ E116 = R${soma_e116} ≠ E110.VL_ICMS_RECOLHER = R${E110.VL_ICMS_RECOLHER}"
```

### 13.6 Benefício → Ajuste → Apuração

```
Para cada benefício ativo em ctx.beneficios_ativos:
    # Deve existir reflexo no E111
    e111_beneficio = buscar E111 com código compatível
    if not e111_beneficio:
        WARN BENEFICIO_SEM_REFLEXO_E111
        f"Benefício {b.codigo} ativo mas sem E111 correspondente"

    # Crédito presumido: verificar lastro em entradas
    if b.tipo == "credito_presumido":
        total_entradas = Σ C170.VL_ITEM onde CFOP de entrada e NCM elegível
        credito_max = total_entradas * b.aliq_credito_presumido
        if e111.VL_AJ_APUR > credito_max * 1.02:   # 2% tolerância
            ERROR CREDITO_PRESUMIDO_ACIMA_DO_LIMITE

    # Débito integral: débito em C190 deve ser pela alíquota cheia
    if b.debito_integral_obrigatorio:
        for c190 in c190_saidas:
            if c190.ALIQ_ICMS < aliq_interna_ES:
                ERROR BENEFICIO_DEBITO_NAO_INTEGRAL
```

### 13.7 ICMS-ST na Apuração (C170/C100 × E210)

Fecha a trilha específica de Substituição Tributária até o bloco de apuração.

```python
# E210 — Apuração do ICMS-ST

# Trilha de saídas (contribuinte substituto)
vl_icms_st_saidas = Σ C170.VL_ICMS_ST onde CFOP saída (5xxx/6xxx)
diff_recol = abs(E210.VL_ICMS_RECOL_ST - vl_icms_st_saidas)
if diff_recol > tolerancia_proporcional(E210.VL_ICMS_RECOL_ST):
    ERROR ST_APURACAO_DIVERGENTE
    f"E210.VL_ICMS_RECOL_ST={E210.VL_ICMS_RECOL_ST} ≠ " +
    f"Σ C170.VL_ICMS_ST saídas={vl_icms_st_saidas} (diff R${diff_recol})"

# Trilha de entradas (contribuinte substituído)
vl_icms_st_entradas = Σ C100.VL_ICMS_ST onde CFOP entrada (1xxx/2xxx)
diff_reten = abs(E210.VL_RETENCAO_ST - vl_icms_st_entradas)
if diff_reten > tolerancia_proporcional(E210.VL_RETENCAO_ST):
    ERROR ST_RETENCAO_DIVERGENTE
    f"E210.VL_RETENCAO_ST={E210.VL_RETENCAO_ST} ≠ " +
    f"Σ C100.VL_ICMS_ST entradas={vl_icms_st_entradas} (diff R${diff_reten})"
```

| Error Type | Sev. | Certeza | Descrição |
|---|---|---|---|
| `ST_APURACAO_DIVERGENTE` | error | objetivo | E210.VL_ICMS_RECOL_ST ≠ soma VL_ICMS_ST das saídas em C170 |
| `ST_RETENCAO_DIVERGENTE` | error | objetivo | E210.VL_RETENCAO_ST ≠ soma VL_ICMS_ST das entradas em C100 |

---

### 13.8 IPI na Apuração (C170 × E510)

Aplicável apenas quando `ind_ativ = '0'` (industrial ou equiparado ao industrial).

```python
# E510 — Apuração do IPI por CST_IPI

for cst_ipi in cst_ipi_distintos_no_c170:
    soma_c170_ipi = Σ C170.VL_IPI onde CST_IPI = cst_ipi
    e510 = buscar E510 com IND_APUR=cst_ipi
    if e510 is None:
        WARN IPI_APURACAO_GRUPO_AUSENTE
        continue
    diff = abs(e510.VL_IPI - soma_c170_ipi)
    if diff > tolerancia_proporcional(e510.VL_IPI):
        ERROR IPI_APURACAO_DIVERGENTE
        f"E510 CST_IPI={cst_ipi}: R${e510.VL_IPI} ≠ Σ C170={soma_c170_ipi}"

# CST IPI tributado (49/99) com VL_IPI = 0 em C170
for c170 in c170_com_ipi:
    if c170.CST_IPI in {"49", "99"} and c170.VL_IPI == 0:
        ERROR IPI_CST_MONETARIO_ZERADO
        f"C170 item {c170.NUM_ITEM}: CST_IPI={c170.CST_IPI} (tributado) com VL_IPI=0"

# IPI deve compor BC do ICMS para industriais
# Base: RIPI Art. 153 — IPI integra o valor da operação para fins de ICMS
for c170 in c170_industriais_saida:
    if c170.VL_IPI > 0:
        vl_item_com_ipi = c170.VL_ITEM + c170.VL_IPI
        # BC_ICMS esperada inclui VL_IPI quando destinatário não é contribuinte de IPI
        # Verificar se CFOP indica saída para consumidor final (CFOP 5xxx com destino PF)
        if is_saida_consumidor_final(c170.CFOP) and c170.VL_BC_ICMS < vl_item_com_ipi * 0.95:
            WARN IPI_REFLEXO_BC_AUSENTE
            f"C170 item {c170.NUM_ITEM}: VL_IPI={c170.VL_IPI} pode não estar " +
            f"compondo BC_ICMS={c170.VL_BC_ICMS}. Verificar RIPI Art. 153."
```

| Error Type | Sev. | Certeza | Descrição |
|---|---|---|---|
| `IPI_APURACAO_DIVERGENTE` | error | objetivo | E510.VL_IPI ≠ soma VL_IPI dos C170 para o mesmo CST_IPI |
| `IPI_APURACAO_GRUPO_AUSENTE` | warning | objetivo | CST_IPI presente em C170 sem E510 correspondente |
| `IPI_CST_MONETARIO_ZERADO` | error | objetivo | CST IPI tributado (49/99) com VL_IPI=0 em C170 |
| `IPI_REFLEXO_BC_AUSENTE` | warning | provável | VL_IPI não compõe BC_ICMS em saída para consumidor final (RIPI Art. 153) |

---

## 14. Catálogo Completo de Regras — ICMS e IPI

> PIS e COFINS excluídos conforme escopo. Campos de PIS/COFINS parseados para consistência estrutural mas sem validação de conteúdo.

### 14.1 Presença e Situação da NF-e

| Error Type | Nível | Sev. | Certeza | Descrição |
|---|---|---|---|---|
| `XML001` | C100 | error | objetivo | NF-e no XML sem C100 no SPED — possível omissão de escrituração |
| `XML002` | C100 | warning | objetivo | C100 no SPED sem XML correspondente — cobertura parcial |
| `XML003_B` | C100 | error | objetivo | NF cancelada (cSit=101/135) escriturada como ativa (COD_SIT=00) |
| `XML003_C` | C100 | error | objetivo | NF denegada (cSit=110/301) escriturada como ativa |
| `COD_SIT_DIVERGENTE_XML` | C100 | error | objetivo | COD_SIT do C100 incompatível com mapeamento cSit do XML |
| `NF_CANCELADA_ESCRITURADA` | C100 | error | objetivo | Crédito de ICMS tomado sobre NF com evento de cancelamento |
| `NF_DENEGADA_ESCRITURADA` | C100 | error | objetivo | NF com autorização denegada escriturada |

### 14.2 Totais do Documento (C100 × XML)

| Error Type | Sev. | Certeza | Descrição |
|---|---|---|---|
| `XML004` | error | objetivo | VL_DOC diverge de vNF do XML |
| `XML_C100_VL_ICMS` | error | objetivo | VL_ICMS total diverge de vICMS do XML |
| `XML_ST_TOTAL_DIV` | error | objetivo | VL_ICMS_ST total diverge de vST do XML |
| `XML_C100_VL_IPI` | warning | objetivo | VL_IPI total diverge de vIPI do XML (ind_ativ=0 apenas) |
| `XML_FRETE_DIVERGENTE` | warning | objetivo | VL_FRT diverge de vFrete do XML — impacta base MVA |
| `XML_DESC_DIVERGENTE` | warning | objetivo | VL_DESC total diverge de vDesc do XML |

### 14.3 Cabeçalho do Documento (C100 × XML)

| Error Type | Sev. | Certeza | Descrição |
|---|---|---|---|
| `XML012` | error | objetivo | CNPJ emitente/destinatário diverge entre XML e 0150 |
| `XML013` | warning | objetivo | IE diverge entre XML e 0150 |
| `XML014` | warning | objetivo | UF diverge entre XML e 0150 |
| `XML015` | warning | objetivo | DT_DOC diverge de dhEmi do XML |
| `XML_DT_ES_DIV` | warning | objetivo | DT_E_S diverge de dhSaiEnt do XML |
| `XML016` | error | objetivo | CHV_NFE com formato inválido (≠44 dígitos ou DV incorreto) |
| `XML017` | warning | objetivo | SER diverge da série do XML |
| `XML_NUM_DIVERGENTE` | warning | objetivo | NUM_DOC diverge de nNF do XML |

### 14.4 Itens — ICMS (C170 × XML det[])

| Error Type | Sev. | Certeza | Descrição |
|---|---|---|---|
| `XML007` | error | objetivo | CFOP diverge entre XML e C170 |
| `XML008` | error | objetivo | CST ICMS (ou CSOSN) diverge entre XML e C170 — context-aware |
| `XML009` | warning | objetivo | NCM diverge entre XML e 0200 |
| `XML010` | error | objetivo | ALIQ_ICMS diverge entre XML e C170 |
| `XML010_ALIQ_INCORRETA` | error | objetivo | ALIQ_ICMS do XML incorreta vs. tabela de alíquotas UF/RICMS-ES |
| `XML011` | error | objetivo | VL_ICMS do item diverge entre XML e C170 |
| `XML011_A` | error | objetivo | VL_ITEM (vProd) diverge entre XML e C170 |
| `XML_BC_ICMS_DIVERGENTE` | error | objetivo | VL_BC_ICMS diverge entre XML e C170 |
| `XML_RED_BC_DIVERGENTE` | warning | provável | % redução de BC diverge — CST 20 sem redução compatível |
| `XML_BC_ST_DIVERGENTE` | error | objetivo | VL_BC_ICMS_ST diverge entre XML e C170 |
| `XML_BC_ST_MVA_DIVERGENTE` | error | provável | VL_BC_ICMS_ST do XML incompatível com MVA tabelado |
| `XML_ALIQ_ST_DIVERGENTE` | error | objetivo | ALIQ_ST diverge entre XML e C170 |
| `XML_ICMS_ST_DIVERGENTE` | error | objetivo | VL_ICMS_ST diverge entre XML e C170 |
| `XML_FCP_AUSENTE_XML` | warning | provável | UF com FCP: XML sem vFCPST ou valor zero |
| `XML_CST_EFEITO_DIVERGENTE` | error | objetivo | Efeito do CST violado no XML (ex: CST 40 isento com ICMS > 0) |

### 14.5 Itens — IPI (C170 × XML det[])

*Aplicável apenas quando `ind_ativ = '0'` (industrial ou equiparado)*

| Error Type | Sev. | Certeza | Descrição |
|---|---|---|---|
| `XML_CST_IPI_DIVERGENTE` | warning | objetivo | CST IPI diverge entre XML e C170 |
| `XML_BC_IPI_DIVERGENTE` | warning | objetivo | VL_BC_IPI diverge entre XML e C170 |
| `XML_ALIQ_IPI_DIVERGENTE` | warning | objetivo | ALIQ_IPI diverge entre XML e C170 |
| `XML_IPI_DIVERGENTE` | warning | objetivo | VL_IPI do item diverge entre XML e C170 |

### 14.6 C190 × XML (Agregação)

| Error Type | Sev. | Certeza | Descrição |
|---|---|---|---|
| `XML_C190_DIVERGE` | error | objetivo | Soma XML do grupo CST/CFOP/ALIQ diverge do C190 correspondente |
| `C190_AUSENTE_PARA_GRUPO` | error | objetivo | Grupo CST/CFOP/ALIQ em C170 sem C190 correspondente |

### 14.7 Contexto Fiscal — ICMS

| Error Type | Sev. | Certeza | Descrição |
|---|---|---|---|
| `XML_BENEFICIO_ALIQ_DIVERGENTE` | error | provável | ALIQ_ICMS incompatível com benefício ativo do destinatário |
| `XML_REGIME_CST_INCOMPATIVEL` | error | objetivo | CST no XML incompatível com regime detectado (Tabela A para empresa SN) |
| `XML018` | error | provável | CST do item incompatível com benefício fiscal ativo no período |
| `XML019` | error | provável | Alíquota ICMS incompatível com alíquota efetiva do benefício |
| `XML020` | warning | objetivo | XMLs fora do período DT_INI–DT_FIN do SPED |
| `XML021` | warning | objetivo | Cobertura de cruzamento < 100%: X NF-e sem XML correspondente |

### 14.8 Cadeia de Fechamento SPED-Only

| Error Type | Sev. | Certeza | Descrição |
|---|---|---|---|
| `C100_VL_DOC_INCONSISTENTE` | error | objetivo | VL_DOC do C100 ≠ soma dos C170 |
| `C100_ICMS_INCONSISTENTE` | error | objetivo | VL_ICMS do C100 ≠ soma VL_ICMS dos C170 |
| `C100_ICMS_ST_INCONSISTENTE` | error | objetivo | VL_ICMS_ST do C100 ≠ soma VL_ICMS_ST dos C170 |
| `C100_IPI_INCONSISTENTE` | error | objetivo | VL_IPI do C100 ≠ soma VL_IPI dos C170 |
| `C100_SEM_ITENS` | error | objetivo | C100 sem nenhum C170 vinculado |
| `C170_ORFAO` | error | objetivo | C170 sem C100 pai |
| `C190_AUSENTE_PARA_GRUPO` | error | objetivo | Grupo CST/CFOP em C170 sem C190 correspondente |
| `C190_COMBINACAO_INCOMPATIVEL` | error | objetivo | C190 com combinação CST/CFOP/ALIQ sem lastro em nenhum C170 do período |
| `C190_DIVERGE_SOMA_C170` | error | objetivo | Soma C170 por grupo diverge do C190 |
| `APURACAO_DEBITO_DIVERGENTE` | error | objetivo | Σ C190 saídas (CFOP 5/6/7) + E110.VL_OUT_DEBITOS ≠ E110.VL_TOT_DEBITOS |
| `APURACAO_CREDITO_DIVERGENTE` | error | objetivo | Σ C190 entradas (CFOP 1/2/3) + créditos ≠ E110.VL_TOT_CREDITOS |
| `APURACAO_SALDO_DIVERGENTE` | error | objetivo | E110.VL_SLD_APURADO ≠ total_débitos − total_créditos calculados |
| `E110_SALDO_INCONSISTENTE` | error | objetivo | E110.VL_SLD_APURADO calculado diverge (alias mais genérico) |
| `ICMS_ZERADO_SEM_AJUSTE` | error | objetivo | VL_ICMS_RECOLHER=0 com saldo positivo sem E111 explicativo |
| `E116_AUSENTE_COM_ICMS_RECOLHER` | error | objetivo | ICMS a recolher > 0 sem E116 correspondente |
| `E116_SOMA_DIVERGE_ICMS_RECOLHER` | error | objetivo | Σ E116 ≠ E110.VL_ICMS_RECOLHER |
| `CODIGO_AJUSTE_INVALIDO_UF` | error | objetivo | E111.COD_AJ_APUR não válido para a UF do contribuinte |
| `SALDO_CREDOR_DIVERGENTE_ANTERIOR` | error | objetivo | VL_SLD_CREDOR_TRANSPORTADO ≠ VL_SLD_CREDOR do período anterior |

### 14.9 Benefícios Fiscais

| Error Type | Sev. | Certeza | Descrição |
|---|---|---|---|
| `BENEFICIO_NAO_ATIVO` | error | objetivo | Benefício usado em E111 não ativo no período |
| `BENEFICIO_CNAE_INELEGIVEL` | error | objetivo | CNAE da empresa não elegível ao benefício declarado |
| `BENEFICIO_FORA_VIGENCIA` | error | objetivo | Benefício fora do período de vigência no ato concessório |
| `SOBREPOSICAO_BENEFICIOS` | error | objetivo | Dois ou mais benefícios incompatíveis ativos simultaneamente |
| `BENEFICIO_DEBITO_NAO_INTEGRAL` | error | objetivo | Benefício exige débito integral; alíquota reduzida encontrada |
| `CODIGO_AJUSTE_INCOMPATIVEL` | error | objetivo | E111.COD_AJ_APUR incompatível com o benefício declarado |
| `CREDITO_PRESUMIDO_SEM_LASTRO` | error | objetivo | Crédito presumido em E111 sem NF de entrada correspondente |
| `CREDITO_PRESUMIDO_ACIMA_DO_LIMITE` | error | provável | Valor do crédito presumido excede limite calculado |
| `BENEFICIO_SEM_REFLEXO_E111` | warning | provável | Benefício ativo sem E111 correspondente no período |
| `SPED_CST_BENEFICIO` | error | provável | CST do item incompatível com o benefício fiscal ativo |
| `SPED_ALIQ_BENEFICIO` | error | provável | Alíquota do item incompatível com alíquota efetiva do benefício |
| `SPED_ICMS_DEVERIA_ZERO` | error | objetivo | Benefício zera ICMS mas VL_ICMS > 0 em C170 |
| `SPED_BC_REDUCAO_DIVERGE` | error | objetivo | BC_ICMS ≠ VL_ITEM × (1 − reducao_base_pct do benefício) |
| `SPED_ICMS_ZERADO_SEM_BENEFICIO` | warning | provável | CFOP de saída com VL_ICMS=0 sem benefício cadastrado que justifique |
| `AJUSTE_SEM_BENEFICIO_CADASTRADO` | error | objetivo | E111 com código de benefício não cadastrado em `beneficios_ativos` |
| `NCM_FORA_ESCOPO_BENEFICIO` | error | objetivo | NCM do item não está no escopo do benefício ativo (cruzar com Tabela_NCM_Vigente) |

### 14.10 ST — Substituição Tributária

| Error Type | Sev. | Certeza | Descrição |
|---|---|---|---|
| `ST_MVA_AUSENTE` | error | objetivo | Produto sujeito a ST sem MVA calculado |
| `ST_MVA_DIVERGENTE` | error | provável | BC_ICMS_ST incompatível com MVA tabelado |
| `ST_MVA_NAO_MAPEADO` | warning | indício | NCM/UF sem MVA na tabela de referência |
| `ST_ALIQ_INCORRETA` | error | objetivo | Alíquota ST diferente da tabela por NCM/UF |
| `ST_REGIME_REMETENTE` | warning | provável | MVA ajustado não aplicado para remetente SN |
| `ST_APURACAO_DIVERGENTE` | error | objetivo | E210.VL_ICMS_RECOL_ST ≠ soma VL_ICMS_ST das saídas em C170 |
| `ST_RETENCAO_DIVERGENTE` | error | objetivo | E210.VL_RETENCAO_ST ≠ soma VL_ICMS_ST das entradas em C100 |

### 14.11 IPI — Imposto sobre Produtos Industrializados

*Aplicável apenas quando `ind_ativ = '0'` (industrial ou equiparado ao industrial)*

| Error Type | Sev. | Certeza | Descrição |
|---|---|---|---|
| `XML_CST_IPI_DIVERGENTE` | warning | objetivo | CST IPI diverge entre XML e C170 |
| `XML_BC_IPI_DIVERGENTE` | warning | objetivo | VL_BC_IPI diverge entre XML e C170 |
| `XML_ALIQ_IPI_DIVERGENTE` | warning | objetivo | ALIQ_IPI diverge entre XML e C170 |
| `XML_IPI_DIVERGENTE` | warning | objetivo | VL_IPI do item diverge entre XML e C170 |
| `IPI_APURACAO_DIVERGENTE` | error | objetivo | E510.VL_IPI ≠ soma VL_IPI dos C170 para o mesmo CST_IPI |
| `IPI_APURACAO_GRUPO_AUSENTE` | warning | objetivo | CST_IPI presente em C170 sem E510 correspondente |
| `IPI_CST_MONETARIO_ZERADO` | error | objetivo | CST IPI tributado (49/99) com VL_IPI=0 em C170 |
| `IPI_REFLEXO_BC_AUSENTE` | warning | provável | VL_IPI não compõe BC_ICMS em saída para consumidor final (RIPI Art. 153) |

### 14.12 DIFAL e FCP

| Error Type | Sev. | Certeza | Descrição |
|---|---|---|---|
| `DIFAL_VALOR_DIVERGENTE` | error | objetivo | DIFAL calculado ≠ DIFAL escriturado |
| `DIFAL_BC_INCORRETA` | error | objetivo | BC do DIFAL incorreta |
| `DIFAL_PARTILHA_INCORRETA` | error | objetivo | Partilha ORIGEM/DESTINO do período transitório incorreta |
| `FCP_NAO_CALCULADO` | warning | objetivo | UF de destino com FCP sem vFCPST declarado |
| `FCP_VALOR_DIVERGENTE` | warning | objetivo | vFCPST calculado ≠ esperado para a alíquota da UF |

### 14.13 Regime Tributário

| Error Type | Sev. | Certeza | Descrição |
|---|---|---|---|
| `REGIME_MISTO_NO_PERIODO` | warning | objetivo | CSTs Tabela A e B misturados no mesmo arquivo |
| `REGIME_CONFLITO_TABELA_CST` | warning | objetivo | Regime detectado por CST difere do cadastro de clientes |
| `CSOSN_INVALIDO` | error | objetivo | CSOSN não pertence ao conjunto válido do SN |
| `CST_SN_INVALIDO` | error | objetivo | Empresa SN com CST Tabela A (00-90) sem CSOSN |

### 14.14 Recorrência Temporal

| Error Type | Sev. | Certeza | Descrição |
|---|---|---|---|
| `ERRO_RECORRENTE_NAO_CORRIGIDO` | warning | objetivo | Mesmo error_type em ≥ 3 períodos consecutivos |
| `RISCO_PRESCRICAO_90D` | info | objetivo | Irregularidade com prazo decadencial ≤ 90 dias |
| `VOLUME_VARIACAO_ATIPICA` | warning | indício | Variação > 50% no volume de ICMS sem justificativa |

### 14.15 Frete × CT-e

| Error Type | Sev. | Certeza | Descrição |
|---|---|---|---|
| `FRETE_SEM_CTE_VINCULADO` | warning | provável | VL_FRT no C100 sem D100 com chave CT-e correspondente |
| `FRETE_CTE_VALOR_DIVERGENTE` | error | objetivo | VL_FRT C100 ≠ VL_DOC D100 (tolerância proporcional) |
| `CREDITO_FRETE_NAO_ESCRITURADO` | warning | provável | CT-e com ICMS calculado sem crédito no E110 |

---

## 15. Tolerância Proporcional por Magnitude

Substitui a tolerância global `R$ 0,02`. Configurável via `TOLERANCE_TIERS` em `config.py`.

| VL_ITEM ou VL comparado | Tolerância Absoluta | Tolerância Relativa | Critério Aplicado |
|---|---|---|---|
| Até R$ 100,00 | R$ 0,02 | 0,02% | O MENOR entre abs e rel |
| R$ 100,01 a R$ 10.000,00 | R$ 0,05 | 0,01% | O MENOR entre abs e rel |
| R$ 10.000,01 a R$ 500.000,00 | R$ 0,10 | 0,005% | O MENOR entre abs e rel |
| Acima de R$ 500.000,00 | R$ 0,50 | 0,001% | O MENOR entre abs e rel |

```python
def tolerancia_proporcional(valor: Decimal) -> Decimal:
    tiers = [
        (Decimal("100"),       Decimal("0.02"), Decimal("0.0002")),
        (Decimal("10000"),     Decimal("0.05"), Decimal("0.0001")),
        (Decimal("500000"),    Decimal("0.10"), Decimal("0.00005")),
        (None,                 Decimal("0.50"), Decimal("0.00001")),
    ]
    v = abs(valor)
    for limite, abs_tol, rel_tol in tiers:
        if limite is None or v <= limite:
            return min(abs_tol, v * rel_tol)
    return Decimal("0.50")

# Arredondamentos dentro da tolerância → CALCULO_ARREDONDAMENTO (warning, info)
```

---

## 16. Score de Risco Fiscal

Score 0–100 calculado após o Estágio 5 (Enriquecimento). Exibido no relatório MOD-20 Seção 2.

### 16.1 Fórmula de Ponderação

```
Score = min(100,
    peso_critico      × (erros_critical / total_docs)       × 40
  + peso_provavel     × (erros_high_provavel / total_items)  × 25
  + peso_beneficio    × (erros_beneficio / 1)                × 20
  + peso_st_difal     × (erros_st_difal / total_docs)        × 10
  + peso_sistemico    × (erros_sistemicos / 1)               × 5
)
```

### 16.2 Faixas de Risco

| Score | Classificação | Ação Recomendada |
|---|---|---|
| 0–20 | 🟢 BAIXO RISCO | Revisão de rotina — regularização preventiva |
| 21–50 | 🟡 RISCO MODERADO | Revisão prioritária pelo contador responsável |
| 51–75 | 🟠 RISCO ELEVADO | Retificação recomendada — exposure financeiro relevante |
| 76–100 | 🔴 RISCO CRÍTICO | Ação imediata — padrão compatível com irregularidade grave |

### 16.3 Score de Cobertura

Complementar ao score de risco. Mede a qualidade da auditoria realizada.

```
Cobertura = (regras_executadas / regras_totais) × (docs_reconciliados / docs_totais)^0.5
```

Exibido no relatório como: "Esta auditoria cobriu 87% das regras disponíveis e reconciliou 94% dos documentos."

---

## 17. Banco de Dados — Modelo Completo

### 17.1 Tabelas de Domínio Mestre (Migration 13)

```sql
-- Contribuintes cadastrados
CREATE TABLE clientes (
    id              INTEGER PRIMARY KEY,
    cnpj            TEXT UNIQUE NOT NULL,
    razao_social    TEXT NOT NULL,
    regime          TEXT NOT NULL CHECK(regime IN ('LP','LR','SN','Imune','Isento')),
    regime_override TEXT,           -- quando preenchido, bypassa regime_detector
    uf              TEXT DEFAULT 'ES',
    cnae_principal  TEXT,
    porte           TEXT,
    ativo           INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- Benefícios fiscais por cliente e período
CREATE TABLE beneficios_ativos (
    id                    INTEGER PRIMARY KEY,
    cliente_id            INTEGER NOT NULL REFERENCES clientes(id),
    codigo_beneficio      TEXT NOT NULL,   -- 'COMPETE_ATACADISTA', 'FUNDAP', etc.
    tipo                  TEXT NOT NULL,   -- 'COMPETE_ES', 'INVEST_ES', 'FUNDAP', 'ST'
    competencia_inicio    TEXT NOT NULL,   -- 'YYYY-MM'
    competencia_fim       TEXT,            -- NULL = indeterminado
    ato_concessorio       TEXT,            -- decreto/portaria
    aliq_icms_efetiva     REAL,
    reducao_base_pct      REAL,
    debito_integral       INTEGER DEFAULT 0,
    observacoes           TEXT,
    ativo                 INTEGER DEFAULT 1
);

-- Registro de CRT de fornecedores (acumulado de XMLs históricos)
CREATE TABLE emitentes_crt (
    cnpj_emitente   TEXT PRIMARY KEY,
    crt             INTEGER NOT NULL,   -- 1=SN, 2=SN Excesso Receita Bruta, 3=Normal
    razao_social    TEXT,
    last_seen       TEXT DEFAULT (datetime('now')),
    fonte           TEXT DEFAULT 'xml'  -- 'xml' ou 'manual'
);
```

### 17.2 Tabelas de Execução (Migration 13 complementar)

```sql
-- Registro principal de execução
CREATE TABLE validation_runs (
    id                    INTEGER PRIMARY KEY,
    file_id               INTEGER NOT NULL,
    mode                  TEXT NOT NULL,    -- 'SPED_ONLY' | 'SPED_XML_RECON'
    cliente_id            INTEGER REFERENCES clientes(id),
    regime_detectado      TEXT,
    regime_source         TEXT,             -- 'CST' | 'CLIENTES_TABLE' | 'CONFLITO'
    beneficios_json       TEXT,             -- snapshot JSON dos benefícios usados
    context_hash          TEXT,
    rules_version         TEXT,
    xml_cobertura_pct     REAL,
    regras_executadas     INTEGER,
    regras_puladas        INTEGER,
    total_achados         INTEGER,
    score_risco           REAL,
    score_cobertura       REAL,
    started_at            TEXT DEFAULT (datetime('now')),
    finished_at           TEXT,
    status                TEXT DEFAULT 'running'
);

-- Lacunas de cobertura (regras não executadas por falta de dado)
CREATE TABLE coverage_gaps (
    id              INTEGER PRIMARY KEY,
    run_id          INTEGER NOT NULL REFERENCES validation_runs(id),
    gap_type        TEXT NOT NULL,        -- 'tabela_ausente' | 'dado_insuficiente'
    description     TEXT,
    affected_rule   TEXT,                 -- rule_id afetada
    severity        TEXT                  -- impacto no score de cobertura
);

-- Índice de pareamento XML × SPED
CREATE TABLE xml_match_index (
    id              INTEGER PRIMARY KEY,
    run_id          INTEGER NOT NULL REFERENCES validation_runs(id),
    xml_id          INTEGER REFERENCES nfe_xmls(id),
    sped_c100_id    INTEGER,
    match_status    TEXT,    -- 'matched' | 'sem_xml' | 'sem_c100'
    match_type      TEXT,    -- 'chave_nfe' | 'manual'
    confidence      REAL,    -- 0.0 a 1.0
    reason          TEXT
);

-- Catálogo formal de equivalência de campos
CREATE TABLE field_equivalence_catalog (
    id                  INTEGER PRIMARY KEY,
    domain              TEXT,        -- 'header', 'item_icms', 'item_ipi'
    xml_path            TEXT,
    sped_register       TEXT,
    sped_field          TEXT,
    normalization_rule  TEXT,
    comparison_type     TEXT,        -- EXACT | MONETARY | PERCENTAGE | DATE | CST_AWARE
    tolerancia          REAL,
    regra_id            TEXT,
    active              INTEGER DEFAULT 1,
    version             INTEGER DEFAULT 1
);

-- Snapshots de contexto fiscal para audit trail
CREATE TABLE fiscal_context_snapshots (
    id                      INTEGER PRIMARY KEY,
    run_id                  INTEGER NOT NULL REFERENCES validation_runs(id),
    cnpj                    TEXT,
    uf                      TEXT,
    periodo                 TEXT,
    regime                  TEXT,
    ind_perfil              TEXT,       -- armazenado, não usado como regime
    beneficios_json         TEXT,
    tables_available_json   TEXT,
    context_hash            TEXT
);
```

### 17.3 Correções nas Tabelas XML (Migration 12 complementar)

```sql
-- Campos adicionados à nfe_xmls para eliminar dependência de parsed_json
ALTER TABLE nfe_xmls ADD COLUMN crt_emitente    INTEGER;
ALTER TABLE nfe_xmls ADD COLUMN uf_emitente     TEXT;
ALTER TABLE nfe_xmls ADD COLUMN uf_dest         TEXT;
ALTER TABLE nfe_xmls ADD COLUMN mod_nfe         INTEGER DEFAULT 55;
ALTER TABLE nfe_xmls ADD COLUMN dentro_periodo  INTEGER DEFAULT 1;
ALTER TABLE nfe_xmls ADD COLUMN content_hash    TEXT;   -- SHA256 para deduplicação
ALTER TABLE nfe_xmls ADD COLUMN namespace_valido INTEGER DEFAULT 1;
ALTER TABLE nfe_xmls ADD COLUMN rejection_reason TEXT;

-- Rastreabilidade de divergências por item
ALTER TABLE nfe_cruzamento ADD COLUMN nfe_item_id INTEGER REFERENCES nfe_itens(id);

-- NOTA: parsed_json marcado como DEPRECATED
-- Não remover por compatibilidade; novos campos vão para colunas explícitas
```

### 17.4 Índices

```sql
CREATE INDEX idx_clientes_cnpj ON clientes(cnpj);
CREATE INDEX idx_beneficios_cliente_periodo
    ON beneficios_ativos(cliente_id, competencia_inicio, competencia_fim);
CREATE INDEX idx_validation_runs_file ON validation_runs(file_id, mode);
CREATE INDEX idx_coverage_gaps_run ON coverage_gaps(run_id, gap_type);
CREATE INDEX idx_xml_match_run ON xml_match_index(run_id, match_status);
CREATE INDEX idx_nfe_xmls_periodo ON nfe_xmls(file_id, dentro_periodo);
CREATE INDEX idx_nfe_xmls_crt ON nfe_xmls(crt_emitente);
```

---

## 18. Especificação de API

### 18.1 Versionamento

| Versão | Prefixo | Status |
|---|---|---|
| v1 | `/api/v1/*` | Ativo — todos os endpoints migram para `/api/v1/` |
| v2 | `/api/v2/*` | Futuro — multi-período, CIAP, DCTF-Web |
| `/api/*` (legado) | — | Deprecado em 6 meses com header `Deprecation: true` |

### 18.2 Endpoints

| Método | Rota | Caminho | Descrição |
|---|---|---|---|
| `POST` | `/api/v1/files/upload` | A + B | Upload SPED chunked (multipart, até 100 MB) |
| `GET` | `/api/v1/files/{id}/context` | A + B | ValidationContext: regime, benefícios, tabelas, cobertura |
| `POST` | `/api/v1/files/{id}/validate/sped` | A | Dispara Caminho A — 5 estágios |
| `GET` | `/api/v1/files/{id}/validate/sped/stream` | A | SSE stream Caminho A |
| `POST` | `/api/v1/files/{id}/xml/upload` | B | Upload batch XMLs chunked |
| `GET` | `/api/v1/files/{id}/xml/coverage` | B | Cobertura XML: % NF-e com XML; lista sem cobertura |
| `POST` | `/api/v1/files/{id}/validate/sped-xml` | B | Dispara Caminho B — 7 estágios |
| `GET` | `/api/v1/files/{id}/validate/sped-xml/stream` | B | SSE stream Caminho B |
| `GET` | `/api/v1/files/{id}/xml/divergences` | B | Resumo de divergências por campo e por NF-e |
| `GET` | `/api/v1/files/{id}/report?mode=sped` | A | Relatório MOD-20 Caminho A |
| `GET` | `/api/v1/files/{id}/report?mode=sped-xml` | B | Relatório MOD-20 Caminho B |
| `GET` | `/api/v1/validation/{run_id}/coverage` | A + B | Regras executadas, puladas e lacunas |
| `GET` | `/api/v1/clientes` | — | CRUD de clientes |
| `GET` | `/api/v1/equivalences` | — | Catálogo de equivalências ativo |

---

## 19. Contrato SSE

```json
// Progresso — ambos os caminhos
{
  "event": "progress",
  "stage": 3,
  "stage_name": "Cruzamentos SPED",
  "stage_progress": 67,
  "total_stages": 5,
  "errors_found": { "error": 12, "warning": 34, "info": 5 },
  "detail": "C190 linha 4521 — grupo CST=020 CFOP=5102 diverge da soma C170",
  "eta_seconds": 45
}

// Progresso XML — Caminho B apenas
{
  "event": "xml_progress",
  "stage": 6,
  "stage_name": "Cruzamento Campo a Campo",
  "xmls_parsed": 47,
  "xmls_total": 120,
  "pairs_checked": 1240,
  "divergences": 23,
  "eta_seconds": 90
}

// Conclusão
{
  "event": "done",
  "mode": "SPED_XML_RECON",
  "run_id": 42,
  "total_errors": 89,
  "score_risco": 67,
  "score_cobertura": 87,
  "xml_coverage_pct": 84.5,
  "total_comparisons": 14800,
  "errors_by_stage": { "sped": 52, "xml": 37 },
  "regras_nao_executadas": 3,
  "regime_detectado": "SIMPLES",
  "regime_source": "CST"
}

// Erro de contexto — aborta pipeline
{
  "event": "context_error",
  "message": "Cliente 12.345.678/0001-90 não cadastrado. Cadastre antes de validar.",
  "action": "Ir para /clientes",
  "stage": 0
}
```

---

## 20. Base Legal por Categoria de Erro (ICMS/IPI)

| Categoria | Error Types | Base Legal Principal |
|---|---|---|
| ICMS — Operações internas ES | `ALIQ_INTERNA_*`, `CST_*` | RICMS-ES (Dec. 1.090-R/2002) Arts. 1 a 65 |
| ICMS — Operações interestaduais | `ALIQ_INTERESTADUAL_*` | Resolução SF 22/1989 (4%, 7%, 12%) |
| DIFAL | `DIFAL_*` | EC 87/2015 + LC 190/2022 + RICMS-ES Arts. 102–109 |
| FCP | `FCP_*` | Lei estadual de cada UF (RJ Lei 7.428/2016; MG Dec. 46.927/2016) |
| Substituição Tributária | `ST_*` | Convênio ICMS 142/2018 + Protocolos por produto + RICMS-ES |
| CIAP / Ativo Imobilizado | `CIAP_*` | LC 87/1996 Art. 20 (1/48 avos) + Art. 33 + RICMS-ES |
| Simples Nacional — ICMS | `SN_*`, `CSOSN_*` | LC 123/2006 + LC 155/2016 + Res. CGSN 140/2018 |
| Benefícios fiscais ES | `BENEFICIO_*`, `AJUSTE_*` | Dec. COMPETE-ES 1.663-R/2005 + INVEST-ES + FUNDAP |
| IPI | `XML_IPI_*`, `XML_CST_IPI_*`, `IPI_*` | Decreto 7.212/2010 (RIPI) + Tabela TIPI + IN RFB 1.911/2019 |
| Cruzamento NF-e × SPED | `XML001–XML021`, `XML_*` | NT 2019.001 + Manual de Orientação NF-e v7.0 |
| Apuração — cadeia fiscal | `C190_*`, `E110_*`, `E116_*` | RICMS-ES Arts. 78–95 + Ajuda de Custo IN SEFAZ-ES |
| Crédito indevido | `CREDITO_USO_CONSUMO_*` | LC 87/1996 Art. 33, I (prazo até 2033) |
| Cruzamento CT-e × Frete | `FRETE_*` | Convênio SINIEF 06/89 + CT-e Manual v3.0 |

---

## 21. Casos de Borda

| Caso de Borda | Comportamento Exigido | Error Type |
|---|---|---|
| CST de 6 dígitos (SN) em C170 | Normalizar para 2 dígitos (últimos dois) antes de validar; sem erro estrutural | `REGIME_AJUSTADO_CSOSN` (info) |
| Mudança de regime no período (CSTs A e B mistos) | Detectar e alertar; não bloquear validação | `REGIME_MISTO_NO_PERIODO` (warning) |
| Retificador parcial | Identificar registros alterados; revalidar e vincular versões via `sped_file_versions` | Informar % retificado no relatório |
| NF complementar (COD_SIT=07) sem original vinculada | Buscar original por NUM_DOC+SER+CNPJ; alertar se ausente | `NF_COMPLEMENTAR_SEM_ORIGINAL` (warning) |
| Nota de ajuste ST (CFOP 1603/2603) | Não aplicar regras ST padrão; validar base de ajuste específica | Tratamento CFOP-específico |
| C170 órfão (sem C100 pai) | Gerar erro estrutural; excluir do pipeline de cruzamento | `C170_ORFAO` (error, objetivo) |
| E110 com VL_ICMS_RECOLHER=0 e débitos > créditos | Verificar E111 de ajuste; se ausente → erro | `ICMS_ZERADO_SEM_AJUSTE` (error) |
| Bloco G ausente para industrial Perfil A | Informar no relatório; não gerar erro se Perfil B/C | `CIAP_BLOCO_AUSENTE` (info para Perfil A industrial) |
| CNPJ com IE de UF diferente do 0000 | Alerta de inconsistência cadastral | `IE_UF_DIVERGE_CNPJ` (warning) |
| XML com namespace inválido (MDF-e, CT-e) | Rejeitar: `Namespace inválido — apenas NF-e aceita`; incrementar contador rejeitados | Não processar |
| C100 com CHV_NFE vazia e COD_SIT=00 | Erro de formato + desabilitar cruzamento para esta NF | `CHV_NFE_AUSENTE` (error) |
| 500+ XMLs carregados | Alertar impacto de performance; prosseguir com fila; paralelo 5 threads | Warning no painel de contexto |
| Benefício com dois registros para o mesmo período | Detectar sobreposição; avaliar incompatibilidade | `SOBREPOSICAO_BENEFICIOS` |
| Arquivo SHA-256 idêntico a run anterior | Oferecer reutilização de análise ou forçar nova execução | Toast: "Arquivo idêntico ao run {n}. Reutilizar análise?" |
| MVA não mapeado para NCM/UF | Não recalcular ST; registrar em `coverage_gaps`; gerar warning | `ST_MVA_NAO_MAPEADO` (warning) |
| Tabela fiscal ausente (ex: MVA desatualizado) | Marcar regras dependentes como `NAO_EXECUTADA`; reduzir score de cobertura | — |

---

## 22. Critérios de Aceite

### 22.1 Geral (ambos os caminhos)

| Critério | Condição de Aceite |
|---|---|
| Stage 0 obrigatório | CNPJ não cadastrado retorna erro claro antes de qualquer registro processado |
| Regime por CST | Arquivo com CSTs 101+ detecta `regime=SIMPLES` independente do IND_PERFIL |
| Tolerância proporcional | VL_ITEM R$ 800.000 — tolerância R$ 0,50 aplicada; sem falsos positivos |
| DELETE transacional | Re-validação não exibe janela de "zero erros" — erros antigos visíveis até commit |
| Cobertura no relatório | Score de cobertura exibido; regras `NAO_EXECUTADA` listadas com motivo |
| Base legal | 100% das regras ativas com `base_legal` preenchido no `rules.yaml` |

### 22.2 Caminho A — Validação SPED

| Critério | Condição de Aceite |
|---|---|
| Cadeia C100 × C170 | VL_DOC do C100 ≠ soma C170 detectado com diff e linha |
| Cadeia C190 × E110 | Saldo apurado divergente com expected calculado |
| Cadeia E111 × E116 | ICMS a recolher sem E116 correspondente detectado |
| ST com MVA | BC_ST com MVA incorreto gera `ST_MVA_DIVERGENTE` com expected_value |
| DIFAL | DIFAL escriturado incorreto para operação interestadual identificado |
| Benefício CNAE | Benefício usado sem elegibilidade de CNAE detectado |
| Regime conflito | CSTs mistos geram `REGIME_MISTO_NO_PERIODO`; alerta no relatório |

### 22.3 Caminho B — Validação SPED × XML

| Critério | Condição de Aceite |
|---|---|
| NF cancelada | NF com cSit=101 escriturada como COD_SIT=00 detectada com `NF_CANCELADA_ESCRITURADA` |
| CST × CRT | NF-e de fornecedor SN não gera falso positivo XML008 — CSOSN aceito |
| Benefício × CST | COMPETE ativo: CST incompatível detectado pela XML018 |
| Benefício × Alíquota | ALIQ_ICMS 12% em saída com benefício gera XML019 |
| C190 × XML | Divergência na agregação por grupo CST/CFOP detectada |
| Período XMLs | Upload de XMLs de mês errado gera XML020 antes do cruzamento |
| Cobertura | Percentual exibido (ex: 94%); lista de chaves sem XML disponível |
| IPI industrial | VL_IPI divergente para `ind_ativ=0` detectado; ignorado para `ind_ativ=1` |

---

## 23. Roadmap de Entrega

| Sprint | Duração | Entregas | Critério de Conclusão |
|---|---|---|---|
| **Sprint 1 — Correções Críticas** | 2 semanas | BUG-001 (Regime por CST), BUG-003 (NF cancelada), BUG-004 (Auth), BUG-007 (Docker) | 4 bugs com testes passando; validado com arquivos reais pelo analista sênior |
| **Sprint 2 — ST, Tolerância, Contexto** | 2 semanas | BUG-002 (ST+MVA 4 etapas), BUG-005 (Tolerância proporcional), BUG-006 (DELETE atômico), Migration 13 (tabelas mestres) | ST_MVA_DIVERGENTE detectado em arquivo-teste; DELETE sem janela de zero erros |
| **Sprint 3 — Frontend Dual-Path** | 2 semanas | Seletor de modo, SpedOnlyUploadPanel, SpedXmlUploadPanel, ClientContextBadge, SSE adaptativo | Teste de usabilidade com 5 analistas aprovado; ambos os modos funcionais |
| **Sprint 4 — Cadeia de Fechamento** | 2 semanas | C100×C170, C190×E110, E111×E116, regras SPED_REG01–04, benefício→ajuste | C190_DIVERGE_SOMA_C170 e E116_SOMA_DIVERGE detectados em arquivos reais |
| **Sprint 5 — Motor XML Completo** | 3 semanas | field_map.yaml completo, FieldComparator, XML001–XML021, C190×XML, field_equivalence_catalog | 100% dos campos mapeados com teste de divergência; XML018/019 passando |
| **Sprint 6 — Score e Relatório** | 2 semanas | Score de risco, score de cobertura, coverage_gaps, relatório MOD-20 Seção 2 completa | Score exibido no resultado; regras `NAO_EXECUTADA` listadas com motivo |
| **Sprint 7 — Qualidade** | 1 semana | base_legal 100% das regras, coverage ≥ 85%, casos de borda Seção 21 | CI/CD verde; zero itens pendentes de base legal |

> **Regra de ouro:** Nenhuma feature nova é entregue sem que os Sprints 1 e 2 estejam completos e validados com arquivos reais de clientes.

---

## 24. Glossário Técnico-Fiscal

| Termo | Significado |
|---|---|
| `IND_PERFIL` | Nível de escrituração do EFD: A=completo, B=simplificado, C=com vedações. **NÃO indica regime tributário.** |
| CST Tabela A | Origem da mercadoria (primeiro dígito do CST ICMS): 0=Nacional, 1=Estrangeira, etc. |
| CST Tabela B | Tributação (dois últimos dígitos): 00=Tributada, 20=Redução BC, 40=Isenta, 60=ST já retida, etc. |
| CSOSN | Código de Situação da Operação no Simples Nacional. Substitui CST para empresas do SN. |
| CRT | Código de Regime Tributário no XML: 1=SN, 2=SN Excesso Receita, 3=Regime Normal. |
| MVA | Margem de Valor Agregado. % aplicado sobre BC para calcular BC_ICMS_ST na substituição prospectiva. |
| DIFAL | Diferencial de Alíquota. ICMS em operações interestaduais para consumidor final não contribuinte (EC 87/2015). |
| FCP | Fundo de Combate à Pobreza. Adicional ao DIFAL em UF que o instituíram (ex: RJ 2%, MG 2%). |
| CIAP | Controle de Crédito do ICMS do Ativo Permanente. Bloco G; crédito em 48 parcelas mensais. |
| `COD_SIT` C100 | Situação do documento no SPED: 00=Normal, 02=Cancelada, 05=Denegada, 07=Complementar. |
| `cSit` XML | Situação da NF-e na SEFAZ: 100=Autorizada, 101=Cancelada, 135=Cancelada fora prazo, 110/301=Denegada. |
| MOD-20 | Modelo de relatório de auditoria com 6 seções obrigatórias (Identificação, Contexto, Achados, Apuração, Limitações, Conclusão). |
| Score de Risco | Índice 0–100 orientando a prioridade de revisão do analista fiscal. |
| Score de Cobertura | Índice 0–100 medindo a completude da auditoria executada. |
| Dual-Path | Arquitetura de dois caminhos: Caminho A (SPED puro) e Caminho B (SPED × XML). |
| Context-First | Princípio: contexto fiscal completo montado no Stage 0 antes de qualquer validação. |
| Context-Aware | Validação que adapta suas regras ao contexto: regime, benefícios, UF, período, CRT emitente. |
| Certeza `objetivo` | Divergência determinada sem ambiguidade por comparação direta de campos. |
| Certeza `provável` | Divergência calculada com fórmula fiscal; exige confirmação do analista. |
| Certeza `indício` | Alerta baseado em padrão suspeito; não é conclusivo sem análise adicional. |
| `NAO_EXECUTADA` | Regra não executada por ausência de dado necessário (tabela fiscal, CRT, etc.). Reduz score de cobertura. |
| Campo `ind_ativ` | `0`=industrial ou equiparado (sujeito a IPI); `1`=outros (sem IPI). Presente no registro 0000. |
| Débito Integral | Obrigatoriedade de calcular o ICMS pela alíquota cheia antes de aplicar o benefício via E111. |
| Crédito Presumido | Benefício que permite creditar ICMS não efetivamente pago, registrado em E111. |

---

*SPED EFD Validator v5.1 — PRD de Auditoria Fiscal ICMS/IPI*
*Foco exclusivo: EFD ICMS/IPI · EFD Contribuições tratada em sistema separado*
*Central Contábil · Vitória, Espírito Santo · Abril 2026*
*Documento mestre — fusão de PRD v3.0 + PRD v4.1 + PRD Fechamento + PLANO_MELHORIAS_v5*
