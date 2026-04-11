# Detalhamento Fiscal — SPED EFD Validator v3.0.0

**Documento tecnico para analista fiscal senior e engenheiro de software**

Este documento descreve, passo a passo, toda a logica fiscal do sistema: desde a entrada do arquivo SPED ate a emissao do relatorio analitico final. Cada etapa, cada campo checado, cada fonte de dados e cada cruzamento estao documentados para permitir auditoria, melhoria e extensao do motor de regras.

---

## Indice

1. [Entrada de Dados — Upload e Parsing](#1-entrada-de-dados--upload-e-parsing)
2. [Construcao do Contexto Fiscal](#2-construcao-do-contexto-fiscal)
3. [Fontes de Dados e Tabelas de Referencia](#3-fontes-de-dados-e-tabelas-de-referencia)
4. [Pipeline de Validacao — 4 Estagios](#4-pipeline-de-validacao--4-estagios)
5. [Estagio 1 — Validacao Estrutural](#5-estagio-1--validacao-estrutural)
6. [Estagio 2 — Cruzamentos e Recalculo Tributario](#6-estagio-2--cruzamentos-e-recalculo-tributario)
7. [Estagio 3 — Enriquecimento](#7-estagio-3--enriquecimento)
8. [Cruzamento NF-e XML x SPED](#8-cruzamento-nf-e-xml-x-sped)
9. [Deduplicacao Inteligente de Erros](#9-deduplicacao-inteligente-de-erros)
10. [Governanca de Correcoes](#10-governanca-de-correcoes)
11. [Saida Analitica — Relatorio Final](#11-saida-analitica--relatorio-final)
12. [Mapeamento Completo de Registros SPED](#12-mapeamento-completo-de-registros-sped)
13. [Catalogo de Tipos de Erro](#13-catalogo-de-tipos-de-erro)
14. [Oportunidades de Melhoria](#14-oportunidades-de-melhoria)

---

## 1. Entrada de Dados — Upload e Parsing

### 1.1 Recebimento do Arquivo

O arquivo SPED EFD ICMS/IPI (.txt, pipe-delimited) entra no sistema por:

- **API REST:** `POST /api/files/upload` (multipart, limite 100 MB, leitura streaming em chunks de 1 MB)
- **CLI:** `python cli.py validate arquivo.txt`

### 1.2 Deteccao de Encoding

O parser tenta tres encodings na ordem (padrao PVA da Receita Federal):

1. `latin-1` (padrao da maioria dos SPED)
2. `cp1252` (variante Windows)
3. `utf-8` (usado em arquivos mais recentes)

Se nenhum funcionar: `latin-1` com `errors="replace"`.

### 1.3 Parsing Pipe-Delimited

Cada linha do SPED segue o formato `|CAMPO1|CAMPO2|...|CAMPON|`:

```
|C100|0|1|PART001|55|00|001|000001|...|
```

O parser:
1. Remove pipes inicial e final
2. Faz split nos pipes intermediarios
3. Identifica o registro pelo primeiro campo (ex: `C100`)
4. Converte a lista posicional para **dict nomeado** usando `REGISTER_FIELDS`

### 1.4 Mapeamento Posicional → Nome de Campo

O dicionario `REGISTER_FIELDS` (em `src/validators/helpers.py`) define o nome de cada campo por posicao para cada registro SPED. Exemplo:

```python
"C100": [
    "REG", "IND_OPER", "IND_EMIT", "COD_PART", "COD_MOD", "COD_SIT",
    "SER", "NUM_DOC", "CHV_NFE", "DT_DOC", "DT_E_S", "VL_DOC",
    "IND_PGTO", "VL_DESC", "VL_ABAT_NT", "VL_MERC", "IND_FRT",
    "VL_FRT", "VL_SEG", "VL_OUT_DA", "VL_BC_ICMS", "VL_ICMS",
    "VL_BC_ICMS_ST", "VL_ICMS_ST", "VL_IPI", "VL_PIS", "VL_COFINS",
    "VL_PIS_ST", "VL_COFINS_ST",
]
```

**Registros mapeados:** 0000, 0001, 0005, 0100, 0150, 0200, 0400, C001, C100, C170, C190, C400, C405, C490, C500, C510, C590, D001, D100, D190, D690, E001, E100, E110, E111, E116, E200, E210, E300, E500, E510, E520, E530, H001, H010, K001, K200, K210, K220, K230, K235, 9001, 9900, 9999.

### 1.5 Persistencia no Banco

Cada registro e salvo no SQLite (`audit.db`) como:

| Campo DB | Conteudo |
|---|---|
| `file_id` | ID do arquivo |
| `line_number` | Numero da linha no .txt |
| `register` | Codigo do registro (ex: C100) |
| `block` | Bloco (primeiro char: C, D, E, H, K) |
| `fields_json` | Dict JSON com campos nomeados |
| `raw_line` | Linha original preservada |
| `status` | `pending` → `corrected` |

### 1.6 Extracao de Metadados (Registro 0000)

Do registro 0000, o sistema extrai automaticamente:

| Campo 0000 | Uso |
|---|---|
| `DT_INI` / `DT_FIN` | Periodo do arquivo (filtragem de regras por vigencia) |
| `NOME` | Razao social do contribuinte |
| `CNPJ` | CNPJ (usado para busca no MySQL DCTF_WEB e vinculacao de retificadores) |
| `UF` | UF do contribuinte (usado para aliquotas, DIFAL, FCP) |
| `IND_PERFIL` | Perfil do contribuinte (A, B, C) |
| `IND_ATIV` | Atividade (0=industrial/equiparado, 1=outros) |
| `COD_VER` | Versao do leiaute SPED |
| `COD_FIN` | Finalidade (0=original, 1=retificadora) |

### 1.7 Deteccao de Retificadores

Se `COD_FIN > 0`, o arquivo e retificador. O sistema:
1. Busca o arquivo original pelo CNPJ + periodo
2. Vincula na tabela `sped_file_versions`
3. Marca `is_retificador = 1`

### 1.8 Hash SHA-256

O sistema calcula hash SHA-256 do arquivo original para:
- **Deduplicacao:** Mesmo hash = mesmo arquivo (reuso do file_id)
- **Integridade:** Hash preservado no relatorio final para rastreabilidade

---

## 2. Construcao do Contexto Fiscal

Antes da validacao, o sistema constroi um `ValidationContext` que informa todos os validadores:

### 2.1 Deteccao Automatica de Regime Tributario

O regime e detectado a partir do registro 0000:

| Sinal | Regime |
|---|---|
| `IND_PERFIL` = A, B ou C + CSTs Tabela A (00-90) | **Normal** (Lucro Real/Presumido) |
| CSTs Tabela B (101-900) ou CSOSN | **Simples Nacional** |
| Microempreendedor Individual | **MEI** |

Alem disso, o sistema consulta o **MySQL DCTF_WEB** para confirmar/complementar o regime.

### 2.2 Cache de Participantes (Registro 0150)

Todos os registros 0150 sao carregados em memoria como `dict[cod_part → dados]`:

```python
participantes = {
    "PART001": {"CNPJ": "12345678000100", "UF": "SP", "IE": "123456789", ...},
    ...
}
```

**Uso:** Validacao de destinatario, cruzamento CFOP x UF, DIFAL.

### 2.3 Cache de Produtos (Registro 0200)

Todos os registros 0200 sao carregados como `dict[cod_item → dados]`:

```python
produtos = {
    "ITEM001": {"COD_NCM": "84818099", "ALIQ_ICMS": "18", "TIPO_ITEM": "00", ...},
    ...
}
```

**Uso:** Validacao NCM, aliquota por item, tipo de item.

### 2.4 Cache de Naturezas de Operacao (Registro 0400)

```python
naturezas = {"COD_NAT": "DESCR_NAT", ...}
```

### 2.5 Filtragem de Regras por Vigencia

Cada regra no `rules.yaml` tem `vigencia_de` e `vigencia_ate`. O sistema filtra apenas as regras vigentes para o periodo do arquivo (DT_INI/DT_FIN do 0000).

### 2.6 Tabelas Externas Disponiveis

O sistema verifica quais tabelas de referencia existem em `data/reference/`:
- `aliquotas_internas_uf.yaml` — Aliquotas ICMS por UF
- `fcp_por_uf.yaml` — FCP por UF
- `ibge_municipios.yaml` — Codigos de municipio
- `mva_por_ncm_uf.yaml` — MVA por NCM e UF
- `codigos_ajuste_uf.yaml` — Tabela 5.1.1

Tabelas ausentes reduzem a cobertura da auditoria (informado no relatorio).

---

## 3. Fontes de Dados e Tabelas de Referencia

### 3.1 Arquivo SPED EFD (.txt)

Fonte primaria. Todos os registros (0000 a 9999) sao parseados e persistidos.

### 3.2 Banco SQLite — `audit.db`

Armazena registros, erros, correcoes, log. Tabelas principais:

| Tabela | Registros | Uso |
|---|---|---|
| `sped_files` | Metadados do arquivo | Identificacao, status, regime |
| `sped_records` | Registros parseados | Base para validacao |
| `validation_errors` | Erros encontrados | Resultado da auditoria |
| `corrections` | Correcoes aplicadas | Historico de ajustes |
| `audit_log` | Acoes do sistema/analista | Rastreabilidade |
| `nfe_xmls` | NF-e importadas | Cruzamento XML |
| `nfe_itens` | Itens das NF-e | Cruzamento item a item |
| `nfe_cruzamento` | Resultados cruzamento | Divergencias XML x SPED |
| `ai_error_cache` | Cache de IA | Explicacoes reutilizaveis |

### 3.3 Banco SQLite — `sped.db`

Documentacao indexada (Guia Pratico EFD, legislacao):

| Tabela | Conteudo |
|---|---|
| `chunks` + `chunks_fts` | Trechos de documentacao com busca FTS5 |
| `register_fields` | Definicoes oficiais de campos por registro |
| `embedding_metadata` | Modelo de embeddings usado |

### 3.4 Tabelas JSON de Referencia Fiscal

#### `Tabela_Fiscal_Complementar_v6.json` (25.073 linhas)

Tabela principal com dados de CFOP, aliquotas e FCP:

```json
{
  "metadata": {"versao": "6.0.0", "ultima_revisao": "2026-04-10"},
  "cfops": {
    "5102": {
      "descricao": "Venda de mercadoria adquirida...",
      "tipo": "saida",
      "uf_destino": "interna",
      "natureza": "venda",
      "gera_debito": true,
      "permite_credito_destinatario": true,
      ...
    }
  },
  "aliquotas_internas_uf": {"ES": 17, "SP": 18, "RJ": 20, ...},
  "fcp_por_uf": {"RJ": 2, "MG": 2, ...},
  "aliquotas_interestaduais": {"4": [...], "7": [...], "12": [...]}
}
```

**Usado por:** fiscal_semantics, aliquota_validator, difal_validator, cfop_validator.

#### `Tabela_CST_Vigente.json` (~2.000 linhas)

Classificacao completa de CSTs por tributo:

```json
{
  "blocos": {
    "CST_ICMS": {
      "tabela_a_origem": {
        "0": {"descricao": "Nacional", "efeitos": ["origem_nacional"]},
        ...
      },
      "tabela_b_tributacao": {
        "00": {"descricao": "Tributada integralmente", "efeitos": ["debito_proprio"]},
        "10": {"descricao": "Tributada com ST", "efeitos": ["debito_proprio", "tem_st_subsequente"]},
        "20": {"descricao": "Com reducao de BC", "efeitos": ["reducao_base_calculo"]},
        "40": {"descricao": "Isenta", "efeitos": ["isencao", "sem_debito_proprio"]},
        "41": {"descricao": "Nao tributada", "efeitos": ["nao_incidencia"]},
        "60": {"descricao": "ICMS cobrado anteriormente por ST", "efeitos": ["icms_recolhido_anteriormente"]},
        ...
      }
    }
  }
}
```

**Usado por:** cst_validator, fiscal_semantics, cst_hypothesis, beneficio_validator.

#### `Tabela_DIFAL_Vigente.json` (~639 linhas)

Regras DIFAL por UF de destino:

**Usado por:** difal_validator.

#### `Tabela_NCM_Vigente.json` (~136.000 linhas)

Catalogo NCM com tratamento tributario:

```json
{
  "ncm": "84818099",
  "descricao": "Torneiras, valvulas...",
  "tipi_aliquota": 10,
  "tipo_tratamento": "normal",
  "monofasico": false
}
```

**Usado por:** ncm_validator, fiscal_semantics (deteccao de monofasicos).

#### Tabelas de Beneficios Fiscais (ES)

| Arquivo | Beneficio | Conteudo |
|---|---|---|
| `FUNDAP.json` | FUNDAP | Importacao via portos do ES |
| `COMPETE_ATACADISTA.json` | COMPETE-ES Atacadista | Credito presumido atacado |
| `COMPETE_VAREJISTA_ECOMMERCE.json` | COMPETE-ES Varejo/E-commerce | Credito presumido varejo |
| `COMPETE_IND_GRAFICAS.json` | COMPETE-ES Graficas | Industria grafica |
| `COMPETE_IND_PAPELAO_MAT_PLAST.json` | COMPETE-ES Papelao/Plastico | Industria papelao |
| `INVEST_ES_IMPORTACAO.json` | INVEST-ES Importacao | Diferimento importacao |
| `INVEST_ES_INDUSTRIA.json` | INVEST-ES Industria | Incentivo industrial |
| `SUBSTITUICAO_TRIBUTARIA_ES.json` | ST no ES | Regras de ST |

Cada arquivo contém: base legal, pre-requisitos, elegibilidade, impactos fiscais, restricoes, reversoes, CNAEs permitidos, e matriz de compatibilidade com outros beneficios.

**Usado por:** beneficio_validator, beneficio_audit_validator, beneficio_cross_validator.

### 3.5 Tabelas YAML de Referencia

| Arquivo | Conteudo | Usado por |
|---|---|---|
| `aliquotas_internas_uf.yaml` | Aliquota geral ICMS por UF (ES=17, SP=18...) | aliquota_validator, difal_validator |
| `fcp_por_uf.yaml` | FCP por UF (RJ=2%, MG=2%...) | difal_validator |
| `codigos_ajuste_uf.yaml` | Tabela 5.1.1 por UF | beneficio_audit_validator |
| `ibge_municipios.yaml` | Codigos IBGE de municipios | format_validator |
| `mva_por_ncm_uf.yaml` | MVA por NCM e UF | st_validator |
| `ncm_tipi_categorias.yaml` | Categorias NCM/TIPI | ncm_validator |
| `csosn_tabela_b.yaml` | Tabela B do CSOSN | simples_validator |
| `cst_pis_cofins_sn.yaml` | CST PIS/COFINS para SN | pis_cofins_validator |
| `sn_anexos_aliquotas.yaml` | Aliquotas por faixa do SN | simples_validator |
| `sn_sublimites_uf.yaml` | Sublimites ICMS/ISS do SN por UF | simples_validator |

### 3.6 Banco MySQL — DCTF_WEB (Externo)

Consulta por CNPJ para obter:
- Razao social
- Regime tributario cadastrado
- Beneficios fiscais ativos
- Situacao cadastral

**Usado por:** context_builder (complementa regime), file_service (log).

### 3.7 Documentacao Indexada

- **Guia Pratico EFD** (PDFs convertidos em Markdown e indexados)
- **Legislacao** (normas, ajustes SINIEF, convenios ICMS)
- Indexacao: FTS5 (busca exata) + embeddings semanticos (all-MiniLM-L6-v2)

**Usado por:** pipeline (enriquecimento de erros com base legal).

---

## 4. Pipeline de Validacao — 4 Estagios

```
Upload → Parsing → Contexto → PIPELINE
                                 │
                   ┌─────────────┼─────────────┐
                   ▼             ▼             ▼
              Estagio 1     Estagio 2     Estagio 3
              Estrutural    Cruzamento    Enriquecimento
                   │             │             │
                   └─────────────┼─────────────┘
                                 ▼
                          Deduplicacao
                                 ▼
                         Resultado Final
```

**Tolerancia global:** 0.02 (2 centavos) — definida em `rules.yaml`.

**Progresso em tempo real:** O pipeline emite eventos SSE a cada 0.5s com stage, progresso (%), e descricao da etapa atual.

---

## 5. Estagio 1 — Validacao Estrutural

### 5.1 Validacao Campo-a-Campo (via definicoes do `sped.db`)

Para cada registro, carrega definicoes de campo do banco de documentacao e valida:

| Verificacao | Error Type | Descricao |
|---|---|---|
| Campo obrigatorio ausente | `MISSING_REQUIRED` | Campo marcado "O" no Guia Pratico esta vazio |
| Tipo numerico invalido | `WRONG_TYPE` | Campo tipo "N" contem valor nao-numerico |
| Tamanho excedido | `WRONG_SIZE` | Valor excede tamanho maximo definido |
| Valor fora do dominio | `INVALID_VALUE` | Valor nao esta na lista de valores aceitos |

**Registros excluidos:** Abertura/encerramento (X001, X990, 9999) — tem layout fixo.

### 5.2 Validacao de Formatos Especificos

| Formato | Campos | Algoritmo | Error Type |
|---|---|---|---|
| **CNPJ** | CNPJ em qualquer registro | 14 digitos + modulo 11 (2 DVs) + rejeicao de repetidos | `FORMATO_INVALIDO` |
| **CPF** | CPF | 11 digitos + modulo 11 (2 DVs) | `FORMATO_INVALIDO` |
| **Data DDMMAAAA** | DT_DOC, DT_E_S, DT_INI, DT_FIN | 8 digitos + dia/mes/ano validos | `INVALID_DATE` |
| **Data no periodo** | DT_DOC, DT_E_S em C100, C170 | Data dentro de DT_INI..DT_FIN do 0000 | `DATE_OUT_OF_PERIOD` |
| **CEP** | CEP | 8 digitos, ≠ 00000000 | `FORMATO_INVALIDO` |
| **CFOP** | CFOP | 4 digitos, primeiro 1-7 | `FORMATO_INVALIDO` |
| **NCM** | COD_NCM | 8 digitos numericos | `FORMATO_INVALIDO` |
| **Chave NFe** | CHV_NFE | 44 digitos + DV modulo 11 (pesos 2-9) | `FORMATO_INVALIDO` |
| **Cod Municipio** | COD_MUN | 7 digitos, validado contra tabela IBGE | `FORMATO_INVALIDO` |

### 5.3 Validacao Intra-Registro

Regras de consistencia dentro de um mesmo registro:

#### C100 — Nota Fiscal (documento)

| Regra | Campos | Condicao de Erro |
|---|---|---|
| CFOP x IND_OPER | CFOP, IND_OPER | Entrada (IND_OPER=0) com CFOP 5/6/7, ou saida (IND_OPER=1) com CFOP 1/2/3 |
| Soma de valores | VL_DOC, VL_MERC, VL_DESC, VL_FRT, VL_SEG, VL_OUT_DA | VL_DOC ≠ VL_MERC - VL_DESC + VL_FRT + VL_SEG + VL_OUT_DA (tolerancia 0.02) |
| ICMS calculado | VL_ICMS, VL_BC_ICMS | Se VL_BC_ICMS > 0 e VL_ICMS = 0, ou vice-versa |
| Data de emissao/ES | DT_DOC, DT_E_S | DT_E_S anterior a DT_DOC (quando ambos preenchidos) |

#### C170 — Itens da Nota

| Regra | Campos | Condicao de Erro |
|---|---|---|
| ICMS = BC x Aliquota | VL_ICMS, VL_BC_ICMS, ALIQ_ICMS | VL_ICMS ≠ VL_BC_ICMS × (ALIQ_ICMS/100) (tolerancia 0.02) |
| IPI = BC x Aliquota | VL_IPI, VL_BC_IPI, ALIQ_IPI | VL_IPI ≠ VL_BC_IPI × (ALIQ_IPI/100) |
| PIS = BC x Aliquota | VL_PIS, VL_BC_PIS, ALIQ_PIS | VL_PIS ≠ VL_BC_PIS × (ALIQ_PIS/100) |
| COFINS = BC x Aliquota | VL_COFINS, VL_BC_COFINS, ALIQ_COFINS | Idem PIS |
| Valor item positivo | VL_ITEM | VL_ITEM <= 0 |
| COD_ITEM existe em 0200 | COD_ITEM | Referencia inexistente no Bloco 0 |

#### C190 — Consolidacao Analitica

| Regra | Campos | Condicao de Erro |
|---|---|---|
| VL_ICMS = VL_BC_ICMS x ALIQ_ICMS | Todos | Calculo divergente |

#### E110 — Apuracao ICMS

| Regra | Campos | Condicao de Erro |
|---|---|---|
| Saldo = Debitos - Creditos | VL_SLD_APURADO, VL_TOT_DEBITOS, VL_TOT_CREDITOS | Saldo nao fecha |

---

## 6. Estagio 2 — Cruzamentos e Recalculo Tributario

### 6.1 Cruzamento Entre Blocos

#### C100 x C170 (Documento x Itens)

| Cruzamento | Campos C100 | Campos C170 | Error Type |
|---|---|---|---|
| Soma VL_ICMS dos itens | VL_ICMS | SUM(VL_ICMS) | `CRUZAMENTO_DIVERGENTE` |
| Soma VL_IPI dos itens | VL_IPI | SUM(VL_IPI) | `CRUZAMENTO_DIVERGENTE` |
| Soma VL_PIS dos itens | VL_PIS | SUM(VL_PIS) | `CRUZAMENTO_DIVERGENTE` |
| Soma VL_COFINS dos itens | VL_COFINS | SUM(VL_COFINS) | `CRUZAMENTO_DIVERGENTE` |
| Soma VL_DOC dos itens | VL_DOC | SUM(VL_ITEM) | `SOMA_DIVERGENTE` |

#### C170 x C190 (Itens x Consolidacao)

| Cruzamento | Error Type |
|---|---|
| Soma VL_OPR por (CST_ICMS, CFOP, ALIQ_ICMS) | `C190_DIVERGE_C170` |
| Soma VL_BC_ICMS por combinacao | `C190_DIVERGE_C170` |
| Soma VL_ICMS por combinacao | `C190_DIVERGE_C170` |
| Combinacao CST+CFOP inexistente nos C170 | `C190_COMBINACAO_INCOMPATIVEL` |

#### Bloco 0 x Bloco C/D (Referencias)

| Cruzamento | Error Type |
|---|---|
| COD_PART do C100 existe no 0150 | `REF_INEXISTENTE` |
| COD_ITEM do C170 existe no 0200 | `REF_INEXISTENTE` |
| COD_NAT do C170 existe no 0400 | `REF_INEXISTENTE` |

#### Bloco C x E110 (Apuracao)

| Cruzamento | Error Type |
|---|---|
| SUM(VL_ICMS) das saidas (CFOP 5/6/7) ≈ VL_TOT_DEBITOS do E110 | `CRUZAMENTO_DIVERGENTE` |
| SUM(VL_ICMS) das entradas (CFOP 1/2/3) ≈ VL_TOT_CREDITOS do E110 | `CRUZAMENTO_DIVERGENTE` |

#### Contagem de Registros (Bloco 9)

| Cruzamento | Error Type |
|---|---|
| QTD_LIN_C do C990 ≠ contagem real de linhas do Bloco C | `CONTAGEM_DIVERGENTE` |
| QTD_REG_BLC do 9900 ≠ contagem real do registro | `CONTAGEM_DIVERGENTE` |

### 6.2 Recalculo Tributario

Para cada registro C170, o sistema **recalcula** os tributos e compara:

#### ICMS

```
ICMS_esperado = VL_BC_ICMS × (ALIQ_ICMS / 100)
Se |VL_ICMS - ICMS_esperado| > tolerancia → CALCULO_DIVERGENTE
```

#### ICMS-ST

```
ICMS_ST_esperado = VL_BC_ICMS_ST × (ALIQ_ST / 100) - VL_ICMS
```

#### IPI

```
IPI_esperado = VL_BC_IPI × (ALIQ_IPI / 100)
```

#### PIS

```
PIS_esperado = VL_BC_PIS × (ALIQ_PIS / 100)
```

#### COFINS

```
COFINS_esperado = VL_BC_COFINS × (ALIQ_COFINS / 100)
```

**Error types gerados:** `CALCULO_DIVERGENTE` (com expected_value contendo o valor recalculado).

**Tolerancia:** 0.02 por item. Arredondamentos dentro da tolerancia geram `CALCULO_ARREDONDAMENTO` (warning).

### 6.3 Validacao CST ICMS

| Regra | Condicao | Error Type |
|---|---|---|
| CST com valor invalido | CST_ICMS nao esta no dominio 00-90 | `CST_INVALIDO` |
| CST 20 sem reducao | CST=020 e VL_RED_BC = 0 | `CST_020_SEM_REDUCAO` |
| CST 40/41 com BC > 0 | CST=040/041 e VL_BC_ICMS > 0 | `ISENCAO_INCONSISTENTE` |
| CST 40/41 com ICMS > 0 | CST=040/041 e VL_ICMS > 0 | `TRIBUTACAO_INCONSISTENTE` |
| CST 60 em saida | CST=060 em IND_OPER=1 (ST cobrado anteriormente) | Verificacao de coerencia |
| CST tributado (00,10,20,70,90) com aliquota zero | ALIQ_ICMS = 0 | `CST_ALIQ_ZERO_FORTE` |

### 6.4 Analise Semantica Fiscal

Regras de coerencia logica entre campos fiscais:

| Regra | Campos | Condicao | Error Type | Certeza |
|---|---|---|---|---|
| CST tributado, aliquota zero | CST_ICMS, ALIQ_ICMS | CST 00/10/20/70/90 com ALIQ=0 | `CST_ALIQ_ZERO_FORTE` | objetivo |
| CST tributado, aliquota zero (moderado) | CST_ICMS, ALIQ_ICMS | CST 51/70 com ALIQ=0 (pode ter motivo) | `CST_ALIQ_ZERO_MODERADO` | provavel |
| CST x CFOP incompativel | CST_ICMS, CFOP | CST isento (40) com CFOP de venda tributada (5102) | `CST_CFOP_INCOMPATIVEL` | provavel |
| IPI CST x aliquota zero | CST_IPI, ALIQ_IPI | CST IPI tributado com aliquota zero | `IPI_CST_ALIQ_ZERO` | objetivo |
| PIS CST x aliquota zero | CST_PIS, ALIQ_PIS | Idem para PIS | `PIS_CST_ALIQ_ZERO` | objetivo |
| COFINS CST x aliquota zero | CST_COFINS, ALIQ_COFINS | Idem para COFINS | `COFINS_CST_ALIQ_ZERO` | objetivo |
| Monofasico: aliquota invalida | NCM + ALIQ_PIS/COFINS | NCM monofasico com aliquota diferente da tabelada | `MONOFASICO_ALIQ_INVALIDA` | objetivo |
| Monofasico: valor indevido | NCM + VL_PIS/VL_COFINS | NCM monofasico com PIS/COFINS na saida | `MONOFASICO_VALOR_INDEVIDO` | objetivo |
| Monofasico: NCM incompativel | NCM + CST | CST monofasico para NCM nao-monofasico | `MONOFASICO_NCM_INCOMPATIVEL` | objetivo |

### 6.5 Validacao de Aliquotas

| Regra | Campos | Condicao | Error Type |
|---|---|---|---|
| Aliquota interestadual invalida | ALIQ_ICMS, UF origem, UF destino | ALIQ nao e 4%, 7% ou 12% em operacao interestadual | `ALIQ_INTERESTADUAL_INVALIDA` |
| Aliquota interna em interestadual | ALIQ_ICMS, CFOP | CFOP 6xxx com aliquota = aliquota interna da UF | `ALIQ_INTERNA_EM_INTERESTADUAL` |
| Aliquota interestadual em interna | ALIQ_ICMS, CFOP | CFOP 5xxx com aliquota = 4/7/12% | `ALIQ_INTERESTADUAL_EM_INTERNA` |
| Aliquota media indevida | ALIQ_ICMS | Aliquota que nao corresponde a nenhuma UF | `ALIQ_MEDIA_INDEVIDA` |

**Tabelas usadas:** `aliquotas_internas_uf.yaml`, `Tabela_Fiscal_Complementar_v6.json`.

### 6.6 Validacao DIFAL (EC 87/2015 + LC 190/2022)

| Regra | Campos | Condicao | Error Type |
|---|---|---|---|
| DIFAL faltante | CFOP 6xxx, IND_OPER=1, destinatario consumidor final | Sem registro E300 para UF destino | `DIFAL_FALTANTE_CONSUMO_FINAL` |
| DIFAL indevido em revenda | CFOP 6xxx, destinatario contribuinte | DIFAL gerado indevidamente | `DIFAL_INDEVIDO_REVENDA` |
| Aliquota interna incorreta | ALIQ_ICMS destino | Aliquota diferente da tabela `aliquotas_internas_uf.yaml` | `DIFAL_ALIQ_INTERNA_INCORRETA` |
| FCP ausente | UF com FCP obrigatorio | Sem FCP no DIFAL | `DIFAL_FCP_AUSENTE` |
| Base inconsistente | VL_BC_ICMS_DIFAL | Base diferente de VL_OPR | `DIFAL_BASE_INCONSISTENTE` |

### 6.7 Auditoria de Beneficios Fiscais (50+ regras)

O `beneficio_audit_validator.py` (maior validador, ~66KB) executa:

| Categoria | Regras | Exemplos |
|---|---|---|
| Debito integral | 5+ | Debito nao-integral com beneficio ativo |
| Ajustes E111 | 5+ | Ajuste sem lastro documental, soma divergente |
| Devolucoes | 3+ | Beneficio nao revertido em devolucao |
| Saldo credor | 2+ | Saldo credor recorrente com beneficio |
| Sobreposicao | 3+ | Multiplos beneficios incompativeis no mesmo item |
| Proporcionalidade | 2+ | Valor do beneficio desproporcional ao faturamento |
| Segregacao | 2+ | Beneficio sem segregacao por destinatario |
| Trilha | 3+ | Beneficio sem trilha documental completa |
| Governanca | 2+ | Beneficio sem procedimento de governanca |

### 6.8 Regras de Auditoria Fiscal Avancada

| Regra | Condicao | Error Type |
|---|---|---|
| CFOP interestadual com destino interno | CFOP 6xxx para mesma UF | `CFOP_INTERESTADUAL_DESTINO_INTERNO` |
| Diferimento com debito | CST diferimento e VL_ICMS > 0 | `DIFERIMENTO_COM_DEBITO` |
| IPI reflexo incorreto | VL_IPI sem reflexo na BC ICMS | `IPI_REFLEXO_INCORRETO` |
| Volume isento atipico | % de operacoes isentas > threshold | `VOLUME_ISENTO_ATIPICO` |
| Remessa sem retorno | CFOP de remessa sem CFOP de retorno correspondente | `REMESSA_SEM_RETORNO` |
| Inventario item parado | Item no H010 sem movimentacao | `INVENTARIO_ITEM_PARADO` |
| Credito uso/consumo indevido | Credito de ICMS para material de uso/consumo | `CREDITO_USO_CONSUMO_INDEVIDO` |

### 6.9 Outras Validacoes do Estagio 2

| Validador | Registros | Descricao |
|---|---|---|
| `base_calculo_validator` | C170 | BASE_001: BC zero com ICMS, BASE_002: BC negativa, etc. |
| `ipi_validator` | C170 | Reflexo IPI na BC ICMS, CST IPI monetario |
| `destinatario_validator` | C100 + 0150 | IE invalida, UF inconsistente, CEP incompativel |
| `devolucao_validator` | C100/C170 | CFOP devolucao sem nota referenciada |
| `cfop_validator` | C170 | CFOP interestadual x interno, CFOP x DIFAL |
| `ncm_validator` | C170 + 0200 | NCM generico (0000), tratamento tributario |
| `parametrizacao_validator` | C170 | Erros sistematicos por item, UF, data |
| `pendentes_validator` | C170 | Beneficio nao vinculado, anomalia historica |
| `bloco_d_validator` | D100/D190 | Servicos de transporte |
| `bloco_c_servicos_validator` | C100/C170 | Servicos no Bloco C |
| `correction_hypothesis` | C170 | Hipotese de aliquota ICMS ausente |
| `cst_hypothesis` | C170 | Hipotese de CST correto |

### 6.10 Hipoteses Inteligentes de Correcao

O sistema nao apenas detecta erros, mas **propoe valores corrigidos**:

#### Hipotese de Aliquota (`correction_hypothesis.py`)

Quando ALIQ_ICMS esta vazia ou zero em item tributado:
1. Busca aliquota interna da UF do contribuinte
2. Verifica aliquota interestadual pela UF do participante
3. Propoe o valor mais provavel como `expected_value`
4. Gera `ALIQ_ICMS_AUSENTE` com certeza "provavel"

#### Hipotese de CST (`cst_hypothesis.py`)

Quando CST parece incorreto:
1. Analisa CFOP, aliquota, valores
2. Propoe CST alternativo baseado na semantica fiscal
3. Gera `CST_HIPOTESE` com certeza "provavel"

---

## 7. Estagio 3 — Enriquecimento

### 7.1 Agrupamento por Chave

Erros sao agrupados por `(error_type, register, field_name)` para evitar buscas redundantes. Exemplo: 500 erros iguais fazem apenas 1 busca de base legal.

### 7.2 Mensagens Amigaveis

Cada `error_type` tem uma mensagem em portugues voltada para o contador (nao programador):

```
CALCULO_DIVERGENTE → "O valor de ICMS (campo VL_ICMS) na linha 1234 do registro
C170 esta com R$ 180,00, mas o calculo BC × Aliquota resulta em R$ 175,50.
Diferenca de R$ 4,50."
```

### 7.3 Orientacao de Correcao

Cada tipo de erro tem orientacao:

```
CALCULO_DIVERGENTE → "Verifique se a base de calculo (VL_BC_ICMS) e a aliquota
(ALIQ_ICMS) estao corretas. O ICMS deveria ser recalculado como BC × Aliquota.
Se houver reducao de base de calculo, verifique o CST (020)."
```

### 7.4 Base Legal

O sistema busca na documentacao indexada (`sped.db`):
1. Busca exata por registro + campo no indice
2. Busca semantica com a mensagem de erro como query
3. Retorna fonte, artigo e trecho relevante

```json
{
  "fonte": "Guia Pratico Efd V3 2 2",
  "artigo": "Registro C170 — Itens do Documento",
  "trecho": "Campo 15 (VL_ICMS): Valor do ICMS creditado/debitado...",
  "score": 0.875
}
```

### 7.5 Classificacao de Auto-Corrigibilidade

O sistema classifica cada erro:

| Tipo | Auto-corrigivel? | Motivo |
|---|---|---|
| `CALCULO_DIVERGENTE` com expected_value | Sim | Valor determinisitco recalculavel |
| `SOMA_DIVERGENTE` com expected_value | Sim | Soma recalculavel |
| `CONTAGEM_DIVERGENTE` com expected_value | Sim | Contagem recalculavel |
| `ALIQ_ICMS_AUSENTE` com expected_value | Sim (com aprovacao) | Requer confirmacao humana |
| `CST_HIPOTESE` com expected_value | Sim (com aprovacao) | Requer confirmacao humana |
| `CST_INVALIDO` | Nao | Requer analise fiscal |
| `CFOP_INTERESTADUAL_DESTINO_INTERNO` | Nao | Requer investigacao |

---

## 8. Cruzamento NF-e XML x SPED

### 8.1 Upload de XMLs

- Upload batch via `POST /api/files/{id}/xml/upload`
- Suporta multiplos XMLs de NF-e simultaneos
- Modos de periodo: `validar` (bloqueia fora do periodo), `importar_todos`, `pular_fora`

### 8.2 Parsing do XML

O parser extrai do namespace `http://www.portalfiscal.inf.br/nfe`:

| Elemento XML | Campo Normalizado |
|---|---|
| `//infNFe/@Id` | Chave NFe (44 digitos) |
| `//ide/nNF` | Numero da NF |
| `//ide/serie` | Serie |
| `//emit/CNPJ` | CNPJ emitente |
| `//dest/CNPJ` | CNPJ destinatario |
| `//total/ICMSTot/vNF` | VL_DOC |
| `//total/ICMSTot/vICMS` | VL_ICMS |
| `//total/ICMSTot/vIPI` | VL_IPI |
| `//total/ICMSTot/vPIS` | VL_PIS |
| `//total/ICMSTot/vCOFINS` | VL_COFINS |
| `//det/prod/NCM` | NCM do item |
| `//det/prod/CFOP` | CFOP do item |
| `//det/imposto/ICMS/*/CST` | CST ICMS do item |
| `//det/imposto/ICMS/*/vBC` | VL_BC_ICMS do item |
| `//det/imposto/ICMS/*/pICMS` | ALIQ_ICMS do item |
| `//det/imposto/ICMS/*/vICMS` | VL_ICMS do item |

### 8.3 Normalizacao

| Funcao | Transformacao |
|---|---|
| `_norm_cnpj` | Remove nao-digitos, pad 14 chars |
| `_norm_cfop` | Remove nao-digitos, primeiros 4 chars |
| `_norm_cst` | Pad 3 chars (2 digitos → 0XX) |
| `_norm_ncm` | Remove nao-digitos, primeiros 8 chars |
| `_norm_date_iso` | ISO 8601 → DDMMAAAA |

### 8.4 Regras de Cruzamento (XML001-XML017)

| Regra | Descricao | Campos XML | Campos SPED | Severidade |
|---|---|---|---|---|
| XML001 | NF-e presente no XML mas ausente no SPED | Chave | CHV_NFE (C100) | error |
| XML002 | NF-e no SPED mas ausente no XML | CHV_NFE (C100) | Chave | warning |
| XML003 | NF-e cancelada no XML mas presente no SPED | cStat=101/135 | C100 com COD_SIT ativo | error |
| XML004 | VL_DOC divergente | vNF | VL_DOC (C100) | error |
| XML005 | VL_ICMS total divergente | vICMS | VL_ICMS (C100) | error |
| XML006 | VL_IPI total divergente | vIPI | VL_IPI (C100) | warning |
| XML007 | CFOP divergente no item | CFOP item | CFOP (C170) | error |
| XML008 | CST ICMS divergente no item | CST item | CST_ICMS (C170) | error |
| XML009 | NCM divergente no item | NCM item | COD_NCM (0200) | warning |
| XML010 | Aliquota ICMS divergente no item | pICMS | ALIQ_ICMS (C170) | error |
| XML011 | Valor ICMS divergente no item | vICMS item | VL_ICMS (C170) | error |
| XML012 | CNPJ emitente/destinatario divergente | CNPJ | COD_PART → 0150.CNPJ | error |
| XML013 | IE inconsistente | IE | 0150.IE | warning |
| XML014 | UF inconsistente | UF | 0150.UF | warning |
| XML015 | Data do documento divergente | dhEmi | DT_DOC (C100) | warning |
| XML016 | Chave NFe formato invalido | Id | CHV_NFE (C100) | error |
| XML017 | Serie divergente | serie | SER (C100) | warning |

### 8.5 Resultados do Cruzamento

Salvos na tabela `nfe_cruzamento` com: `rule_id`, `severity`, `campo_xml`, `valor_xml`, `campo_sped`, `valor_sped`, `diferenca`.

---

## 9. Deduplicacao Inteligente de Erros

Apos o Estagio 2, tres estrategias evitam duplicidade:

### Estrategia 1 — Hipoteses supersede genericos

Se na mesma linha existe `ALIQ_ICMS_AUSENTE` (hipotese com correcao proposta), suprime `CST_ALIQ_ZERO_FORTE` (generico sem correcao).

### Estrategia 2 — Mesma causa raiz

Se na mesma linha existe `CST_ALIQ_ZERO_MODERADO`, suprime `BENEFICIO_NAO_VINCULADO` e `CST_CFOP_INCOMPATIVEL` (sintomas da mesma causa).

### Estrategia 3 — Mesmo campo, manter o mais acionavel

Quando dois erros apontam para o mesmo (linha, campo), manter o que tem `expected_value` (acionavel pelo usuario).

---

## 10. Governanca de Correcoes

### 10.1 Niveis de Corrigibilidade

Cada regra no `rules.yaml` define um nivel:

| Nivel | Descricao | Acao |
|---|---|---|
| `automatico` | Correcao deterministica segura | Sistema aplica sem confirmacao |
| `proposta` | Correcao com impacto fiscal | Requer justificativa (min 10 chars) |
| `investigar` | Requer analise externa | Bloqueado para auto-correcao |
| `impossivel` | Dados externos necessarios | Bloqueado totalmente |

### 10.2 Campos Bloqueados para Auto-Correcao

Campos que **nunca** sao corrigidos automaticamente:

- **Identificadores fiscais:** CNPJ, CPF, IE, CHV_NFE, CHV_CTE
- **Chaves de documento:** NUM_DOC, SER, COD_MOD
- **Valores monetarios:** VL_DOC, VL_ICMS, VL_BC_ICMS, VL_ICMS_ST, VL_IPI, VL_PIS, VL_COFINS
- **Classificacoes fiscais:** CST_ICMS, CSOSN, CST_PIS, CST_COFINS, CFOP
- **Datas de documento:** DT_DOC

### 10.3 Tipos Deterministicos Seguros

Apenas estes tipos sao auto-corrigiveis:

- `CALCULO_DIVERGENTE` — Recalculo matematico
- `SOMA_DIVERGENTE` — Soma recalculavel
- `CONTAGEM_DIVERGENTE` — Contagem recalculavel

### 10.4 Audit Trail

Cada correcao gera registro em `corrections` e `audit_log`:

```json
{
  "field_name": "VL_ICMS",
  "old_value": "180.00",
  "new_value": "175.50",
  "justificativa": "Recalculo BC x Aliquota",
  "correction_type": "auto",
  "rule_id": "CALC_ICMS_C170",
  "record_id": 12345,
  "field_no": 15
}
```

### 10.5 Desfazer Correcao

Funcao `undo_correction` restaura o valor original e reabre o erro.

### 10.6 Resolucao de Apontamentos

O analista pode registrar resolucao para cada apontamento:

| Status | Descricao | Requer justificativa |
|---|---|---|
| `accepted` | Aceito — correcao sera aplicada | Nao |
| `rejected` | Rejeitado — sem correcao | Sim (min 20 chars) |
| `deferred` | Adiado — revisao futura | Nao |
| `noted` | Ciencia — sem acao | Nao |

---

## 11. Saida Analitica — Relatorio Final

### 11.1 Relatorio de Auditoria (6 Secoes Obrigatorias — MOD-20)

#### Secao 1 — Cabecalho de Identificacao

| Campo | Fonte |
|---|---|
| Contribuinte | 0000.NOME |
| CNPJ | 0000.CNPJ |
| Periodo | DT_INI a DT_FIN |
| Hash SHA-256 original | Calculado no upload |
| Data/hora da auditoria | Timestamp da geracao |
| Versao do motor | ENGINE_VERSION (3.0.0) |

#### Secao 2 — Cobertura da Auditoria

Lista de 15 checks executados:
1. Validacao campo-a-campo
2. Validacao de formatos (CNPJ, CPF, datas, CFOP)
3. Validacao intra-registro
4. Cruzamento entre blocos
5. Recalculo tributario (ICMS, ICMS-ST, IPI, PIS/COFINS)
6. Validacao CST e isencoes + Bloco H
7. Semantica fiscal (CST x aliquota, CST x CFOP)
8. Regras de auditoria fiscal avancadas
9. Validacao de aliquotas
10. Consolidacao C190
11. Auditoria de beneficios fiscais
12. Regras pendentes
13. DIFAL
14. Hipoteses de correcao inteligente
15. Validacao de retificadores

Tabelas externas disponiveis/ausentes + cobertura percentual + limitacoes.

#### Secao 3 — Sumario de Achados

- Por severidade: critical, error, warning, info
- Por certeza: objetivo, provavel, indicio
- Por bloco: C, D, E, H, K
- Top-10 tipos por frequencia

#### Secao 4 — Achados Detalhados

Cada erro com: linha, registro, campo, valor encontrado, valor esperado, certeza, impacto, severidade, mensagem amigavel, base legal, orientacao.

Ordenados por severidade (critical primeiro) e linha.

#### Secao 5 — Correcoes Aplicadas

Historico de correcoes com: campo, valor original, novo valor, justificativa, aprovado por, data.

#### Secao 6 — Rodape Legal Obrigatorio

```
AVISO LEGAL: Este relatório foi gerado automaticamente pelo sistema de
auditoria SPED EFD e não constitui parecer contábil, fiscal ou jurídico.
A conferência, validação e retificação do arquivo SPED junto à Secretaria
da Fazenda é responsabilidade exclusiva do contribuinte e de seu
representante técnico legalmente habilitado (CRC/CRA/OAB).
```

### 11.2 Formatos de Exportacao

| Formato | Endpoint | Conteudo |
|---|---|---|
| **Markdown** | `GET /files/{id}/report?format=md` | Relatorio completo 6 secoes |
| **JSON estruturado** | `GET /files/{id}/report/structured` | Metadata, summary, findings, corrections, conclusion |
| **CSV** | `GET /files/{id}/report?format=csv` | Erros tabulados + rodape legal |
| **SPED corrigido** | `GET /files/{id}/download` | Arquivo .txt com correcoes aplicadas |

### 11.3 Explicacao de Erros via IA (Opcional)

O analista pode solicitar explicacao contextualizada via `POST /api/ai/explain`:

- **Modelo:** GPT-4o-mini (temperatura 0.3)
- **Persona:** Assistente fiscal especializado em SPED EFD
- **Formato:** 3 paragrafos (O QUE, POR QUE, COMO corrigir)
- **Cache:** Incremental por hash de contexto (reutiliza entre arquivos)
- **Aviso:** "Sugestao nao vinculante"

---

## 12. Mapeamento Completo de Registros SPED

### Bloco 0 — Abertura e Identificacao

| Registro | Campos Principais | Uso na Validacao |
|---|---|---|
| **0000** | REG, COD_VER, COD_FIN, DT_INI, DT_FIN, NOME, CNPJ, UF, IE, IND_PERFIL, IND_ATIV | Contexto: regime, periodo, UF, retificador |
| **0005** | NOME_FANTASIA, CEP, END, FONE, EMAIL | Validacao CEP |
| **0100** | NOME (contador), CPF, CRC, CNPJ | Validacao CPF/CNPJ |
| **0150** | COD_PART, NOME, CNPJ, CPF, IE, COD_MUN, UF | Cache participantes, cruzamento C100 |
| **0200** | COD_ITEM, DESCR_ITEM, COD_NCM, ALIQ_ICMS, TIPO_ITEM | Cache produtos, NCM, aliquota |
| **0400** | COD_NAT, DESCR_NAT | Cache naturezas |

### Bloco C — Documentos Fiscais (Mercadorias)

| Registro | Campos Principais | Uso na Validacao |
|---|---|---|
| **C100** | IND_OPER, COD_PART, CHV_NFE, DT_DOC, VL_DOC, VL_ICMS, VL_IPI, VL_PIS, VL_COFINS | Cruzamento C170, C190, XML, E110 |
| **C170** | COD_ITEM, CST_ICMS, CFOP, VL_BC_ICMS, ALIQ_ICMS, VL_ICMS, VL_IPI, VL_PIS, VL_COFINS | Todos os recalculos, semantica |
| **C190** | CST_ICMS, CFOP, ALIQ_ICMS, VL_OPR, VL_BC_ICMS, VL_ICMS | Consolidacao vs C170 |

### Bloco D — Documentos Fiscais (Servicos)

| Registro | Campos Principais | Uso |
|---|---|---|
| **D100** | IND_OPER, COD_PART, CHV_CTE, VL_DOC, VL_ICMS | Cruzamento D190 |
| **D190** | CST_ICMS, CFOP, VL_OPR, VL_ICMS | Consolidacao |

### Bloco E — Apuracao

| Registro | Campos Principais | Uso |
|---|---|---|
| **E110** | VL_TOT_DEBITOS, VL_TOT_CREDITOS, VL_SLD_APURADO, VL_ICMS_RECOLHER | Cruzamento Bloco C |
| **E111** | COD_AJ_APUR, VL_AJ_APUR | Beneficios, ajustes |
| **E210** | VL_RETENCAO_ST, VL_ICMS_RECOL_ST | ST |

### Bloco H — Inventario

| Registro | Campos Principais | Uso |
|---|---|---|
| **H010** | COD_ITEM, QTD, VL_ITEM | Item parado, inventario |

### Bloco K — Producao/Estoque

| Registro | Campos Principais | Uso |
|---|---|---|
| **K200** | COD_ITEM, QTD, IND_EST | Saldo de estoque |
| **K220** | COD_ITEM_ORI, COD_ITEM_DEST, QTD | Movimentacao interna |
| **K230/K235** | COD_ITEM, QTD_DEST | Producao |

### Bloco 9 — Controle

| Registro | Campos Principais | Uso |
|---|---|---|
| **9900** | REG_BLC, QTD_REG_BLC | Contagem de registros |
| **9999** | QTD_LIN | Total de linhas |

---

## 13. Catalogo de Tipos de Erro

### Erros Estruturais

| Error Type | Severidade | Certeza | Auto-corrigivel |
|---|---|---|---|
| `FORMATO_INVALIDO` | error | objetivo | Nao |
| `INVALID_DATE` | error | objetivo | Nao |
| `DATE_OUT_OF_PERIOD` | error | objetivo | Nao |
| `MISSING_REQUIRED` | error | objetivo | Nao |
| `WRONG_TYPE` | error | objetivo | Nao |
| `WRONG_SIZE` | error | objetivo | Nao |
| `INVALID_VALUE` | error | objetivo | Nao |

### Erros de Calculo

| Error Type | Severidade | Certeza | Auto-corrigivel |
|---|---|---|---|
| `CALCULO_DIVERGENTE` | error | objetivo | Sim |
| `SOMA_DIVERGENTE` | error | objetivo | Sim |
| `CONTAGEM_DIVERGENTE` | error | objetivo | Sim |
| `CALCULO_ARREDONDAMENTO` | warning | objetivo | Sim (com aprovacao) |
| `VALOR_NEGATIVO` | error | objetivo | Nao |

### Erros de Cruzamento

| Error Type | Severidade | Certeza | Auto-corrigivel |
|---|---|---|---|
| `REF_INEXISTENTE` | error | objetivo | Nao |
| `CRUZAMENTO_DIVERGENTE` | error | objetivo | Nao |
| `C190_DIVERGE_C170` | error | objetivo | Sim |
| `C190_COMBINACAO_INCOMPATIVEL` | warning | provavel | Nao |

### Erros de CST

| Error Type | Severidade | Certeza | Auto-corrigivel |
|---|---|---|---|
| `CST_INVALIDO` | error | objetivo | Nao |
| `CST_020_SEM_REDUCAO` | error | objetivo | Nao |
| `ISENCAO_INCONSISTENTE` | error | objetivo | Nao |
| `TRIBUTACAO_INCONSISTENTE` | error | objetivo | Nao |
| `CST_ALIQ_ZERO_FORTE` | error | objetivo | Nao |
| `CST_ALIQ_ZERO_MODERADO` | warning | provavel | Nao |
| `CST_CFOP_INCOMPATIVEL` | warning | provavel | Nao |
| `CST_HIPOTESE` | warning | provavel | Sim (com aprovacao) |

### Erros de Aliquota

| Error Type | Severidade | Certeza | Auto-corrigivel |
|---|---|---|---|
| `ALIQ_INTERESTADUAL_INVALIDA` | error | objetivo | Nao |
| `ALIQ_INTERNA_EM_INTERESTADUAL` | warning | provavel | Nao |
| `ALIQ_INTERESTADUAL_EM_INTERNA` | warning | provavel | Nao |
| `ALIQ_ICMS_AUSENTE` | error | provavel | Sim (com aprovacao) |

### Erros de DIFAL

| Error Type | Severidade | Certeza | Auto-corrigivel |
|---|---|---|---|
| `DIFAL_FALTANTE_CONSUMO_FINAL` | error | objetivo | Nao |
| `DIFAL_INDEVIDO_REVENDA` | warning | provavel | Nao |
| `DIFAL_ALIQ_INTERNA_INCORRETA` | error | objetivo | Nao |
| `DIFAL_FCP_AUSENTE` | warning | provavel | Nao |

### Erros de Beneficios

| Error Type | Severidade | Certeza | Auto-corrigivel |
|---|---|---|---|
| `BENEFICIO_DEBITO_NAO_INTEGRAL` | error | provavel | Nao |
| `AJUSTE_SEM_LASTRO_DOCUMENTAL` | error | provavel | Nao |
| `DEVOLUCAO_BENEFICIO_NAO_REVERTIDO` | error | provavel | Nao |
| `SOBREPOSICAO_BENEFICIOS` | error | provavel | Nao |
| `BENEFICIO_NAO_VINCULADO` | warning | indicio | Nao |

### Erros de Auditoria

| Error Type | Severidade | Certeza | Auto-corrigivel |
|---|---|---|---|
| `CFOP_INTERESTADUAL_DESTINO_INTERNO` | error | objetivo | Nao |
| `DIFERIMENTO_COM_DEBITO` | error | objetivo | Nao |
| `REMESSA_SEM_RETORNO` | warning | provavel | Nao |
| `INVENTARIO_ITEM_PARADO` | info | indicio | Nao |
| `CREDITO_USO_CONSUMO_INDEVIDO` | error | provavel | Nao |

### Erros de Monofasico

| Error Type | Severidade | Certeza | Auto-corrigivel |
|---|---|---|---|
| `MONOFASICO_ALIQ_INVALIDA` | error | objetivo | Nao |
| `MONOFASICO_VALOR_INDEVIDO` | error | objetivo | Nao |
| `MONOFASICO_NCM_INCOMPATIVEL` | warning | provavel | Nao |

---

## 14. Oportunidades de Melhoria

### 14.1 Cruzamentos Adicionais

| Oportunidade | Registros | Descricao |
|---|---|---|
| C100 x D100 | Mercadoria x Servico | Cruzar frete do C100 (IND_FRT) com CT-e do D100 |
| E110 x E210 | ICMS Proprio x ICMS-ST | Verificar consistencia entre apuracoes |
| C170 x H010 | Itens x Inventario | Cruzar NCM/quantidade dos itens com inventario |
| 0200 x C170 | Cadastro x Operacao | ALIQ_ICMS do 0200 vs ALIQ_ICMS real nos C170 |
| K200 x K220 x K230 | Estoque x Producao | Conciliacao de saldos de estoque com producao |
| E111 x beneficio JSON | Ajuste x Beneficio | Validar codigo de ajuste contra tabela de beneficios |
| Multiplos periodos | SPED t vs SPED t-1 | Saldo credor transportado vs saldo credor anterior |

### 14.2 Validacoes Nao Implementadas

| Item | Descricao | Prioridade |
|---|---|---|
| ST com MVA | Recalculo ICMS-ST usando MVA por NCM/UF | Alta |
| ICMS efetivo (carga tributaria liquida) | Calculo do ICMS efetivo apos beneficio | Alta |
| Bloco G (CIAP) | Validacao de ativo imobilizado | Media |
| Bloco 1 (Informacoes complementares) | Registros 1100, 1200, 1400, 1500 | Media |
| EFD Contribuicoes | PIS/COFINS em nivel de detalhe | Alta |
| SPED x DCTF-Web | Cruzamento com obrigacao acessoria | Alta |
| Nota cancelada vs escriturada | Validar COD_SIT do C100 contra protocolo do XML | Alta |

### 14.3 Melhorias de Analise

| Item | Descricao |
|---|---|
| Score de risco fiscal | Ponderar erros por impacto financeiro (materialidade) |
| Tendencia temporal | Comparar erros entre periodos (regressao/melhoria) |
| Clusterizacao de erros | Agrupar erros com causa raiz comum |
| Benchmark setorial | Comparar metricas com media do setor (CNAE) |
| Mapa de calor | Visualizar concentracao de erros por registro/bloco |
| Alerta de prescricao | Prazo decadencial de 5 anos para retificacao |

### 14.4 Melhorias Tecnicas

| Item | Descricao |
|---|---|
| Cache de validacao | Nao revalidar registros inalterados |
| Validacao incremental | Revalidar apenas registros afetados por correcao |
| Paralelismo | Validadores independentes em threads separadas |
| Pre-validacao XML | Validar XML contra XSD oficial da NF-e antes do cruzamento |
| Webhook de resultado | Notificar sistema externo quando auditoria concluir |

---

*Documento gerado para analistas fiscais senior e engenheiros de software — SPED EFD Validator v3.0.0*
*Central Contabil — Abril 2026*
