# PRD - Motor de Regras de Validacao SPED EFD

**Versao:** 5.0
**Data:** 2026-04-07
**Autor:** Bruno
**Status:** Concluido v5

---

## 1. Visao Geral

O motor de validacao SPED EFD conta com **191 regras** definidas no `rules.yaml`, **todas implementadas** em 23 blocos de validacao, com campo `corrigivel` obrigatorio em todas as regras (automatico|proposta|investigar|impossivel). O catalogo completo cobre cenarios de formato, cruzamento, recalculo, semantica fiscal, auditoria de beneficios, aliquotas, DIFAL/FCP, base de calculo, destinatario, devolucoes, parametrizacao, governanca, **Simples Nacional** e **Bloco K (producao e estoque)**.

**Novidades v5:**
- **Bloco K**: 5 regras de producao e estoque (K_001 a K_005) — integridade referencial, fechamento, quantidades
- **Governanca aprimorada**: 22 campos sensiveis bloqueados para correcao automatica (CNPJ, CPF, valores, CST, CFOP); FMT_CNPJ/FMT_CPF reclassificados para `investigar`
- **Tolerancia por contexto**: `ToleranceResolver` com 8 tipos (item R$0,01, consolidacao R$0,10, apuracao R$1,00)
- **FieldRegistry**: acesso seguro a campos por nome via singleton com fallback DB/memoria
- **RegimeDetector**: deteccao multi-sinal (IND_PERFIL + CSOSN + CST) com grau de confianca
- **ErrorDeduplicator**: remove apontamentos duplicados por grupo semantico na mesma linha/campo
- **Rate limiting**: 10 uploads/min, 5 validacoes/min por IP nos endpoints criticos
- **Streaming**: `parse_sped_file_stream()` para arquivos grandes sem carregar em memoria
- **Aliquotas por UF**: 27 UFs parametrizadas com fontes legislativas (AM=20%, CE=20%, SP=18%)
- **Audit scope**: endpoint GET /api/audit-scope com escopo e limitacoes da validacao
- **6 fixtures fiscais**: cenarios reais (SN, ST, exportacao, devolucao, erros multiplos)
- **Lint AST**: check_hardcoded_indices.py proibe `fields[N]` com N >= 2

**Novidades v4:**
- Campo `corrigivel` em 100% das regras, com governanca de correcoes no `correction_service.py`
- Workflow de resolucao de apontamentos (accepted/rejected/deferred/noted) via tabela `finding_resolutions`
- Materialidade financeira estimada (R$) por apontamento
- Filtros UI no frontend: severidade, registro, certeza, ordenacao
- Vigencia de regras enforced no engine (regras de 2024 nao aplicam a arquivo de 2022)

**Estado atual:** 191 regras implementadas | 1601 testes automatizados | campo corrigivel em 100% das regras

---

## 2. Situacao Atual

### 2.1 Regras Implementadas (191)

| Bloco | Qtd | Modulo |
|---|---|---|
| formato | 9 | format_validator.py |
| campo_a_campo | 4 | validator.py |
| intra_registro | 10 | intra_register_validator.py |
| cruzamento | 13 | cross_block_validator.py |
| recalculo | 8 | tax_recalc.py |
| cst_isencoes | 6 | cst_validator.py |
| semantica_aliquota_zero | 5 | fiscal_semantics.py |
| semantica_cst_cfop | 3 | fiscal_semantics.py |
| monofasicos | 5 | fiscal_semantics.py |
| pendentes | 6 | pendentes_validator.py |
| auditoria_beneficios | 50 | beneficio_audit_validator.py |
| aliquotas | 7 | aliquota_validator.py |
| c190_consolidacao | 2 | c190_validator.py |
| cst_expandido | 4 | cst_validator.py |
| difal | 12 | difal_validator.py |
| base_calculo | 15 | base_calculo_validator.py |
| beneficio_fiscal | 3 | beneficio_validator.py |
| devolucoes | 3 | devolucao_validator.py |
| parametrizacao | 3 | parametrizacao_validator.py |
| ncm | 2 | ncm_validator.py |
| governanca | 5 | audit_rules.py |
| simples_nacional | 11 | simples_validator.py |
| **bloco_k** | **5** | **bloco_k_validator.py** *(novo v5)* |

**Severidades:** 50 critical, 43 error, 75 warning, 21 info

### 2.2 Detalhamento — Bloco `auditoria_beneficios` (50 regras)

| ID | Titulo | Severidade |
|---|---|---|
| AUD_COMPETE_DEBITO_INTEGRAL | Debito nao integral na apuracao | critical |
| AUD_E111_SEM_RASTREABILIDADE | Ajuste E111 sem E112/E113 | warning (*) |
| AUD_E111_SOMA_VS_E110 | Soma E111 diverge de E110 | critical |
| AUD_DEVOLUCAO_SEM_REVERSAO_BENEFICIO | Devolucao sem reversao de beneficio | warning (*) |
| AUD_SALDO_CREDOR_RECORRENTE | Saldo credor recorrente | warning |
| AUD_SOBREPOSICAO_BENEFICIOS | CST 020 + credito presumido | warning (*) |
| AUD_BENEFICIO_DESPROPORCIONAL | Ajuste desproporcional ao volume | warning (*) |
| AUD_ST_NOTA_OK_APURACAO_ERRADA | ST correto no item, apuracao errada | critical |
| AUD_E111_CODIGO_GENERICO | Codigo ajuste generico | warning |
| AUD_XML_SPED_DIVERGENCIA | Escrituracao diverge do documento | critical |
| AUD_CHECKLIST_AUDITORIA_MINIMA | Checklist minimo de 10 pontos | info |
| AUD_TRILHA_BENEFICIO_INCOMPLETA | Beneficio sem trilha transparente | critical |
| AUD_ICMS_EFETIVO_SEM_TRILHA | Debito interestadual sem trilha | critical |
| AUD_BENEFICIO_FORA_ESCOPO | Ajuste sobre operacoes nao elegiveis | critical |
| AUD_DIAGNOSTICO_CAUSA_RAIZ | Divergencia documento/escrituracao/calculo | warning |
| AUD_AJUSTE_SEM_LASTRO | Ajuste relevante sem E112/E113 | warning (*) |
| AUD_ST_APURACAO_DIVERGE | ST item vs apuracao inconsistente | critical |
| AUD_C190_MISTURA_CST | C190 com consolidacao indevida | critical |
| AUD_CREDITO_SEM_SAIDA | Credito entrada sem saida compativel | warning |
| AUD_INVENTARIO_REFLEXO_TRIBUTARIO | Inventario com reflexo tributario | warning |
| AUD_BENEFICIO_SEM_GOVERNANCA | Beneficio sem documentacao | critical |
| AUD_TOTALIZACAO_BENEFICIADA | Saidas beneficiadas vs totais | warning |
| AUD_MISTURA_INSTITUTOS | Mistura credito presumido + reducao | warning (*) |
| AUD_PERFIL_OPERACIONAL_BENEFICIO | Beneficio sem aderencia ao perfil | warning |
| AUD_BENEFICIO_PARAMETRIZACAO_ERRADA | Beneficio com parametrizacao incompativel | critical |
| AUD_DESTINATARIO_SEGREGACAO | Beneficio sem segregacao destinatario | warning |
| AUD_BASE_BENEFICIO_INFLADA | Base inflada com operacoes excluidas | critical |
| AUD_SPED_VS_CONTRIBUICOES | Divergencia Fiscal vs EFD-Contribuicoes | warning |
| AUD_E111_NUMERICO_JURIDICO | Ajuste fecha mas codigo inadequado | critical |
| AUD_CODIGO_AJUSTE_INCOMPATIVEL | Codigo ajuste incompativel com regime | critical |
| AUD_TRILHA_BENEFICIO_AUSENTE | Beneficio sem vinculo documental | critical |
| AUD_CLASSIFICACAO_ERRO | Meta: classificar tipo do erro | info |
| AUD_ESCOPO_APENAS_SPED | Meta: achado depende so do SPED | info |

(*) **Regras rebaixadas de critical para warning em 2026-04-05:**
Essas regras sao heuristicas/analiticas e dependem de contexto externo (legislacao do beneficio,
tabela 5.1.1, regime tributario) para confirmar o achado. Sem esse contexto, geram falso positivo.
Permanecem como alerta de revisao (warning), nao como erro objetivo (critical).

**Correcoes de logica aplicadas em 2026-04-05:**
- `AUD_E111_SOMA_VS_E110`: comparacao corrigida para usar VL_TOT_AJ_CREDITOS/DEBITOS (nao VL_AJ_CREDITOS/DEBITOS)
- `AUD_SOBREPOSICAO_BENEFICIOS` / `AUD_MISTURA_INSTITUTOS`: `eh_credito_presumido` corrigido — agora exige descricao com "presumido"/"outorgado", nao mais qualquer natureza 2
- `AUD_BENEFICIO_DESPROPORCIONAL`: soma corrigida para usar apenas E111 de natureza credito (nat 2), nao todos os E111
- `C190_001`: rateio de despesas agora inclui IPI, ICMS-ST e residual VL_DOC-VL_MERC
- `IPI_003` / `IPI_CST_ALIQ_ZERO`: CST 49/99 removidos do set tributado (sao residuais); aliquota 0% na TIPI aceita quando BC preenchida

---

## 3. Novas Regras - Catalogo Aliquotas, DIFAL e Parametrizacao (55)

### 3.1 Aliquotas (7 regras)

| ID | Titulo | Tipo | Achado | Severidade | Automatizavel |
|---|---|---|---|---|---|
| ALIQ_001 | Aliquota interestadual invalida | semantica | erro_objetivo | critica | sim |
| ALIQ_002 | Aliquota interna em operacao interestadual | semantica | erro_objetivo | critica | sim |
| ALIQ_003 | Aliquota interestadual em operacao interna | semantica | erro_objetivo | alta | sim |
| ALIQ_004 | Aliquota 7/12 incompativel com UFs | juridica | inconsistencia | alta | parcial |
| ALIQ_005 | Aliquota 4% sem suporte de importacao | hibrida | indicio | alta | parcial |
| ALIQ_006 | Mesmo item com aliquotas divergentes | hibrida | indicio | media | sim |
| ALIQ_007 | Aliquota media indevida em documento | matematica | erro_objetivo | critica | sim |

**Registros envolvidos:** 0000, 0150, 0200, C170, C190
**Dependencias externas:** FCI, matriz UF origem-destino, cadastro tributario do item

### 3.2 DIFAL (8 regras)

| ID | Titulo | Tipo | Achado | Severidade | Automatizavel |
|---|---|---|---|---|---|
| DIFAL_001 | DIFAL faltante em consumo final | hibrida | risco_fiscal | critica | parcial |
| DIFAL_002 | DIFAL indevido em revenda/industrializacao | hibrida | inconsistencia | alta | parcial |
| DIFAL_003 | UF destino inconsistente no DIFAL | cadastral | indicio | alta | parcial |
| DIFAL_004 | Aliquota interna destino incorreta no DIFAL | juridica | risco_fiscal | critica | parcial |
| DIFAL_005 | Base DIFAL inconsistente com operacao | matematica | inconsistencia | alta | sim |
| DIFAL_006 | FCP ausente ou incoerente | juridica | risco_fiscal | alta | parcial |
| DIFAL_007 | Perfil destinatario incompativel com DIFAL | hibrida | indicio | alta | parcial |
| DIFAL_008 | Consumo final sem marcadores consistentes | semantica | alerta_informativo | media | parcial |

**Registros envolvidos:** 0000, 0150, 0200, C170, E300
**Dependencias externas:** tabela aliquotas internas por UF, FCP por UF, XML, cadastro destinatario, IE

### 3.3 Base de Calculo (6 regras)

| ID | Titulo | Tipo | Achado | Severidade | Automatizavel |
|---|---|---|---|---|---|
| BASE_001 | Recalculo ICMS divergente | matematica | erro_objetivo | critica | sim |
| BASE_002 | Base menor que esperado sem justificativa | matematica | inconsistencia | alta | sim |
| BASE_003 | Base superior ao razoavel | matematica | inconsistencia | media | sim |
| BASE_004 | Frete CIF nao incluido na base | hibrida | inconsistencia | alta | parcial |
| BASE_005 | Frete FOB incluido indevidamente | hibrida | indicio | media | parcial |
| BASE_006 | Despesas acessorias fora da base | matematica | inconsistencia | media | sim |

**Registros envolvidos:** C170
**Dependencias externas:** modalidade frete, CT-e, XML

### 3.4 IPI (3 regras)

| ID | Titulo | Tipo | Achado | Severidade | Automatizavel |
|---|---|---|---|---|---|
| IPI_001 | IPI reflexo incorreto na base ICMS | hibrida | inconsistencia | alta | parcial |
| IPI_002 | Recalculo IPI divergente | matematica | erro_objetivo | alta | sim |
| IPI_003 | CST IPI incompativel com campos monetarios | semantica | erro_objetivo | alta | sim |

**Registros envolvidos:** C170
**Dependencias externas:** perfil destinatario, finalidade mercadoria

### 3.5 Destinatario (3 regras)

| ID | Titulo | Tipo | Achado | Severidade | Automatizavel |
|---|---|---|---|---|---|
| DEST_001 | IE inconsistente com tratamento fiscal | cadastral | indicio | alta | parcial |
| DEST_002 | UF incompativel com IE | cadastral | inconsistencia | media | parcial |
| DEST_003 | UF incompativel com CEP | cadastral | indicio | media | parcial |

**Registros envolvidos:** 0150, C170
**Dependencias externas:** SINTEGRA, base CEP/UF, regra prefixo IE

### 3.6 CFOP (3 regras)

| ID | Titulo | Tipo | Achado | Severidade | Automatizavel |
|---|---|---|---|---|---|
| CFOP_001 | CFOP interestadual com destino mesma UF | semantica | erro_objetivo | critica | sim |
| CFOP_002 | CFOP interno com destino outra UF | semantica | erro_objetivo | critica | sim |
| CFOP_003 | CFOP incompativel com tratamento DIFAL | semantica | indicio | alta | parcial |

**Registros envolvidos:** 0000, 0150, C170, E300

### 3.7 CST (5 regras)

| ID | Titulo | Tipo | Achado | Severidade | Automatizavel |
|---|---|---|---|---|---|
| CST_001 | CST tributado com aliquota zero | semantica | erro_objetivo | alta | sim |
| CST_002 | CST isento/NT com valor de ICMS | semantica | erro_objetivo | alta | sim |
| CST_003 | CST 020 sem reducao real de base | matematica | inconsistencia | alta | sim |
| CST_004 | CST 020 com aliquota reduzida indevidamente | hibrida | inconsistencia | alta | parcial |
| CST_005 | Diferimento com debito indevido | semantica | erro_objetivo | alta | sim |

**Registros envolvidos:** C170

### 3.8 C190 - Consolidacao (2 regras)

| ID | Titulo | Tipo | Achado | Severidade | Automatizavel |
|---|---|---|---|---|---|
| C190_001 | C190 nao fecha com C170 | matematica | erro_objetivo | critica | sim |
| C190_002 | Combinacao incompativel CST/CFOP/ALIQ | semantica | inconsistencia | alta | sim |

**Registros envolvidos:** C170, C190

### 3.9 Apuracao (3 regras)

| ID | Titulo | Tipo | Achado | Severidade | Automatizavel |
|---|---|---|---|---|---|
| APUR_001 | E110 nao fecha com debitos C190 | matematica | erro_objetivo | critica | sim |
| APUR_002 | Ajuste E111 sem lastro suficiente | semantica | risco_fiscal | critica | parcial |
| APUR_003 | Codigo ajuste incompativel com regime | juridica | risco_fiscal | alta | parcial |

**Registros envolvidos:** C190, E110, E111, E112, E113

### 3.10 Beneficio Fiscal (3 regras)

| ID | Titulo | Tipo | Achado | Severidade | Automatizavel |
|---|---|---|---|---|---|
| BENE_001 | Beneficio contaminando aliquota documento | semantica | risco_fiscal | critica | sim |
| BENE_002 | Beneficio contaminando calculo DIFAL | juridica | indicio | alta | nao |
| BENE_003 | Base beneficio com operacoes nao elegiveis | juridica | risco_fiscal | critica | parcial |

**Registros envolvidos:** C170, C190, E111, E300

### 3.11 Substituicao Tributaria (2 regras)

| ID | Titulo | Tipo | Achado | Severidade | Automatizavel |
|---|---|---|---|---|---|
| ST_001 | Mistura indevida ST e DIFAL | hibrida | indicio | alta | parcial |
| ST_002 | ST no item sem reflexo na apuracao | semantica | inconsistencia | alta | sim |

**Registros envolvidos:** C170, E200, E210, E300

### 3.12 Devolucoes (3 regras)

| ID | Titulo | Tipo | Achado | Severidade | Automatizavel |
|---|---|---|---|---|---|
| DEV_001 | Devolucao sem espelhamento da original | hibrida | inconsistencia | alta | parcial |
| DEV_002 | Devolucao sem tratamento do DIFAL | hibrida | risco_fiscal | alta | nao |
| DEV_003 | Devolucao com aliquota atual vs historica | hibrida | indicio | media | nao |

**Registros envolvidos:** C170, E300

### 3.13 Parametrizacao / Metarregras (3 regras)

| ID | Titulo | Tipo | Achado | Severidade | Automatizavel |
|---|---|---|---|---|---|
| PARAM_001 | Erro sistemico por item | metarregra | metarregra | alta | sim |
| PARAM_002 | Erro sistemico por UF destino | metarregra | metarregra | alta | sim |
| PARAM_003 | Erro sistemico iniciado em data especifica | metarregra | metarregra | media | sim |

**Registros envolvidos:** 0150, 0200, C170, E300

### 3.14 NCM (2 regras)

| ID | Titulo | Tipo | Achado | Severidade | Automatizavel |
|---|---|---|---|---|---|
| NCM_001 | NCM com tratamento tributario incompativel | hibrida | indicio | alta | parcial |
| NCM_002 | NCM generico com reflexo fiscal relevante | cadastral | indicio | media | sim |

**Registros envolvidos:** 0200, C170

### 3.15 Governanca e Operacional (5 regras)

| ID | Titulo | Tipo | Achado | Severidade | Automatizavel |
|---|---|---|---|---|---|
| AMOSTRA_001 | Amostragem por materialidade e risco | metarregra | alerta_informativo | informativa | sim |
| GOV_001 | Classificar erro (material/param/tese) | metarregra | metarregra | informativa | sim |
| GOV_002 | Explicitar grau de confianca | metarregra | metarregra | informativa | sim |
| GOV_003 | Explicitar dependencia externa | metarregra | metarregra | informativa | sim |
| GOV_004 | Checklist mestre aliquotas/DIFAL | metarregra | metarregra | informativa | sim |

### 3.16 Simples Nacional (11 regras)

| ID | Titulo | Tipo | Achado | Severidade | Automatizavel |
|---|---|---|---|---|---|
| SN_001 | CST Tabela A em contribuinte SN | semantica | erro_objetivo | error | sim |
| SN_002 | CSOSN invalido (fora Tabela B) | semantica | erro_objetivo | error | sim |
| SN_003 | Credito ICMS zerado ou acima do teto pCredSN | matematica | erro_objetivo | error | sim |
| SN_004 | CSOSN com ST sem base/valor ST | semantica | erro_objetivo | error | sim |
| SN_005 | CSOSN 300 (imune) com ICMS preenchido | semantica | erro_objetivo | warning | sim |
| SN_006 | CSOSN 400 (nao tributada) com ICMS preenchido | semantica | erro_objetivo | warning | sim |
| SN_007 | CSOSN 500 sem base ST retida | semantica | erro_objetivo | warning | sim |
| SN_009 | CST PIS/COFINS proibido para SN (01/02/03/05) | semantica | erro_objetivo | error | sim |
| SN_010 | IND_PERFIL diferente de C para SN | semantica | inconsistencia | warning | sim |
| SN_011 | CST PIS 04 (monofasico) em NCM nao monofasico | hibrida | indicio | warning | sim |
| SN_012 | Aliquota credito ICMS inconsistente entre itens | matematica | indicio | warning | sim |

**Registros envolvidos:** 0000, 0200, C170
**Tabelas de referencia:** csosn_tabela_b.yaml, cst_pis_cofins_sn.yaml, sn_anexos_aliquotas.yaml, sn_sublimites_uf.yaml
**Legislacao:** LC 123/2006, LC 155/2016, Ajuste SINIEF 07/2005, IN RFB 1.252/2012, Tabela 4.3.3 EFD-Contribuicoes

**Validacao inteligente SN_003 (sem RBT12):**
O SPED Fiscal nao contem o campo RBT12 (receita bruta acumulada). A validacao opera por range:
- `ALIQ_ICMS = 0` para CSOSN 101/201 → erro (credito nao preenchido)
- `ALIQ_ICMS > 4,01%` → erro (usando aliquota cheia ao inves de pCredSN)
- Itens com aliquotas divergentes entre si → alerta (SN_012)
Os limites sao calculados a partir dos Anexos I-V da LC 155/2016.

---

## 4. Resumo Consolidado

### 4.1 Total por Origem

| Origem | Qtd | Status |
|---|---|---|
| Regras implementadas (rules.yaml) | 191 | Todas implementadas |
| Regras com error_type no codigo | 140 | Produzem alertas |
| Regras planejadas (error_type futuro) | 40 | Definidas no YAML, implementacao futura |
| **TOTAL** | **191** | |

### 4.2 Total por Severidade

| Severidade | Pendentes | Novas | Total |
|---|---|---|---|
| Critica / critical | 14 | 14 | 28 |
| Alta / error | 5 | 24 | 29 |
| Media / warning | 17 | 7 | 24 |
| Informativa / info | 3 | 10 | 13 |
| **Total** | **39** | **55** | **94** |

### 4.3 Total por Automatizabilidade (novas)

| Status | Qtd |
|---|---|
| Totalmente automatizavel (sim) | 27 |
| Parcialmente automatizavel | 23 |
| Nao automatizavel (fila humana) | 5 |

### 4.4 Dependencias Externas

| Fonte Externa | Regras que dependem |
|---|---|
| XML / documento fiscal | DIFAL_001/002/003/008, BASE_004/005, DEV_001/002/003, BENE_002 |
| Tabela aliquotas internas por UF | ALIQ_004, DIFAL_004, DIFAL_006 |
| FCI / origem mercadoria | ALIQ_005, ALIQ_006 |
| SINTEGRA / cadastro destinatario | DEST_001, DEST_002, DIFAL_007 |
| Tabela TIPI / NCM | NCM_001, NCM_002 |
| Ato concessivo / legislacao beneficio | BENE_001/002/003, APUR_003 |
| Modalidade frete (CT-e) | BASE_004, BASE_005 |
| Base CEP/UF | DEST_003 |

---

## 5. Arquitetura de Implementacao

### 5.1 Modulos Alvo

```
src/validators/
  aliquota_validator.py      # ALIQ_001..007
  difal_validator.py          # DIFAL_001..008
  base_calculo_validator.py   # BASE_001..006
  ipi_validator.py            # IPI_001..003
  destinatario_validator.py   # DEST_001..003
  cfop_validator.py           # CFOP_001..003 (expandir existente)
  cst_validator.py            # CST_001..005 (expandir existente)
  c190_validator.py           # C190_001..002
  apuracao_validator.py       # APUR_001..003
  beneficio_validator.py      # BENE_001..003
  st_validator.py             # ST_001..002
  devolucao_validator.py      # DEV_001..003
  parametrizacao_validator.py # PARAM_001..003
  ncm_validator.py            # NCM_001..002
  governanca.py               # GOV_001..004, AMOSTRA_001
  simples_validator.py        # SN_001..012
  bloco_k_validator.py        # K_001..005 (novo v5)
  audit_rules.py              # AUD_* pendentes (expandir existente)
  fiscal_semantics.py         # PEND_* (expandir existente)
```

### 5.2 Schema de Regra (extendido)

Campos adicionais ao `rules.yaml` existente para suportar o catalogo novo:

```yaml
- id: ALIQ_001
  register: C170
  fields: [CFOP, ALIQ_ICMS]
  error_type: ALIQ_INTERESTADUAL_INVALIDA
  severity: critical
  description: "Operacao interestadual com aliquota fora do padrao"
  condition: "CFOP iniciado por 6 e ALIQ_ICMS not in {4,7,12}"
  implemented: false
  module: aliquota_validator.py
  legislation: "Resolucao Senado 22/1989, RS 13/2012"
  # Novos campos do catalogo:
  tema: aliquota
  subtema: interestadual
  tipo_regra: semantica           # matematica|cadastral|semantica|juridica|hibrida|metarregra
  tipo_achado: erro_objetivo      # erro_objetivo|inconsistencia|indicio|risco_fiscal|alerta|metarregra
  nivel_confianca: alto           # alto|medio|baixo
  automatizavel: sim              # sim|parcial|nao
  depende_externo: false
  fontes_externas: []
  mensagem_padrao: "Operacao interestadual com aliquota de ICMS fora do padrao esperado."
  acao_recomendada: "Revisar UF de origem, UF de destino e regra de tributacao do item."
```

### 5.3 Integracao no Pipeline

```
pipeline.py
  run_full_validation()
    1. format_validation        (existente)
    2. field_validation          (existente)
    3. intra_register_validation (existente)
    4. cross_block_validation    (existente)
    5. tax_recalculation         (existente)
    6. cst_validation            (existente)
    7. fiscal_semantics          (existente)
    8. audit_rules               (existente)
    --- NOVOS STAGES ---
    9.  aliquota_validation      # ALIQ_001..007
    10. difal_validation         # DIFAL_001..008
    11. base_calculo_validation  # BASE_001..006
    12. destinatario_validation  # DEST_001..003
    13. parametrizacao_analysis  # PARAM_001..003
    14. governanca_check         # GOV_001..004
```

### 5.4 Tabelas Externas Necessarias

Para regras com `depende_externo: true`, o motor precisara de tabelas de referencia:

| Tabela | Formato | Uso |
|---|---|---|
| `matriz_aliquotas_uf.yaml` | UF_origem x UF_destino -> aliquota | ALIQ_004 |
| `aliquotas_internas_uf.yaml` | UF -> aliquota interna padrao | DIFAL_004 |
| `fcp_por_uf.yaml` | UF -> percentual FCP | DIFAL_006 |
| `prefixo_ie_uf.yaml` | UF -> regex IE | DEST_002 |
| `faixa_cep_uf.yaml` | faixa CEP -> UF | DEST_003 |
| `ncm_tributacao.yaml` | NCM -> regime esperado | NCM_001 |
| `codigos_ajuste_uf.yaml` | COD_AJ -> descricao + vigencia | APUR_003 |
| `csosn_tabela_b.yaml` | CSOSN -> descricao + permite_credito + aplica_st | SN_001..007 |
| `cst_pis_cofins_sn.yaml` | CST -> permitido/proibido + motivo | SN_009 |
| `sn_anexos_aliquotas.yaml` | Anexo x Faixa -> aliquota + partilha | SN_003, SN_012 |
| `sn_sublimites_uf.yaml` | UF -> sublimite ICMS/ISS | (futuro) |

---

## 6. Plano de Execucao por Fases

### Fase 1 - Regras Matematicas Puras (sem dependencia externa)

**Prioridade:** Alta | **Estimativa:** 14 regras

Regras 100% automatizaveis que operam apenas com dados do SPED:

- BASE_001 - Recalculo ICMS
- IPI_002 - Recalculo IPI
- IPI_003 - CST IPI vs campos monetarios
- CST_001 - CST tributado com aliquota zero
- CST_002 - CST isento com valor ICMS
- CST_003 - CST 020 sem reducao real
- CST_005 - Diferimento com debito
- C190_001 - C190 vs C170
- C190_002 - Combinacoes impossiveis
- APUR_001 - E110 vs C190
- ALIQ_001 - Aliquota interestadual invalida
- ALIQ_002 - Aliquota interna em interestadual
- ALIQ_003 - Aliquota interestadual em interna
- ALIQ_007 - Aliquota media indevida

### Fase 2 - CFOP, Destinatario e Beneficios no Documento

**Prioridade:** Alta | **Estimativa:** 12 regras

- CFOP_001 - Interestadual mesma UF
- CFOP_002 - Interno outra UF
- BENE_001 - Beneficio contaminando aliquota
- BASE_002 - Base menor sem justificativa
- BASE_003 - Base superior ao razoavel
- BASE_006 - Despesas acessorias fora da base
- PEND_BENEFICIO_FISCAL
- PEND_DESONERACAO_MOTIVO
- PEND_DEVOLUCAO_VS_ORIGEM
- PEND_ALIQ_INTERESTADUAL
- PEND_NCM_VS_TIPI_ALIQ
- PEND_PERFIL_HISTORICO

### Fase 3 - Auditoria de Beneficios e Apuracao

**Prioridade:** Alta | **Estimativa:** 20 regras

- AUD_COMPETE_DEBITO_INTEGRAL
- AUD_E111_SEM_RASTREABILIDADE
- AUD_E111_SOMA_VS_E110
- AUD_DEVOLUCAO_SEM_REVERSAO_BENEFICIO
- AUD_SOBREPOSICAO_BENEFICIOS
- AUD_BENEFICIO_DESPROPORCIONAL
- AUD_ST_NOTA_OK_APURACAO_ERRADA
- AUD_E111_CODIGO_GENERICO
- AUD_TRILHA_BENEFICIO_INCOMPLETA
- AUD_ICMS_EFETIVO_SEM_TRILHA
- AUD_BENEFICIO_FORA_ESCOPO
- AUD_AJUSTE_SEM_LASTRO
- AUD_ST_APURACAO_DIVERGE
- AUD_C190_MISTURA_CST
- AUD_BENEFICIO_SEM_GOVERNANCA
- AUD_MISTURA_INSTITUTOS
- AUD_BENEFICIO_PARAMETRIZACAO_ERRADA
- AUD_BASE_BENEFICIO_INFLADA
- AUD_CODIGO_AJUSTE_INCOMPATIVEL
- AUD_TRILHA_BENEFICIO_AUSENTE

### Fase 4 - DIFAL e Tabelas Externas

**Prioridade:** Media | **Estimativa:** 18 regras

Requer construcao de tabelas de referencia externas:

- DIFAL_001..008 (8)
- ALIQ_004, ALIQ_005, ALIQ_006 (3)
- BASE_004, BASE_005 (2)
- IPI_001 (1)
- DEST_001, DEST_002, DEST_003 (3)
- CFOP_003 (1)

### Fase 5 - Metarregras, Governanca e Parametrizacao

**Prioridade:** Media | **Estimativa:** 13 regras

- PARAM_001..003 (3)
- DEV_001..003 (3)
- ST_001, ST_002 (2)
- NCM_001, NCM_002 (2)
- BENE_002, BENE_003 (2)
- APUR_002, APUR_003 (parcial, expandir)

### Fase 6 - Governanca e UX

**Prioridade:** Baixa | **Estimativa:** 17 regras

- GOV_001..004 (4)
- AMOSTRA_001 (1)
- CST_004 (1)
- AUD_SALDO_CREDOR_RECORRENTE (1)
- AUD_CHECKLIST_AUDITORIA_MINIMA (1)
- AUD_XML_SPED_DIVERGENCIA (1)
- AUD_DIAGNOSTICO_CAUSA_RAIZ (1)
- AUD_CREDITO_SEM_SAIDA (1)
- AUD_INVENTARIO_REFLEXO_TRIBUTARIO (1)
- AUD_TOTALIZACAO_BENEFICIADA (1)
- AUD_PERFIL_OPERACIONAL_BENEFICIO (1)
- AUD_DESTINATARIO_SEGREGACAO (1)
- AUD_SPED_VS_CONTRIBUICOES (1)
- AUD_E111_NUMERICO_JURIDICO (1)
- AUD_CLASSIFICACAO_ERRO (1)
- AUD_ESCOPO_APENAS_SPED (1)
- DIFAL_008 (1)

---

## 7. Criterios de Aceitacao

### 7.1 Por Regra

- [x] Regra definida no `rules.yaml` com todos os campos do schema
- [x] Implementacao no modulo correto com `error_type` registrado em `_KNOWN_ERROR_TYPES`
- [x] Teste unitario cobrindo caso positivo (dispara) e negativo (nao dispara)
- [x] Mensagem de erro clara com `friendly_message`, `legal_basis` quando aplicavel
- [x] Integrada no pipeline via `run_full_validation()`
- [x] Visivel no frontend (lista de apontamentos)

### 7.2 Por Fase

- [x] Todas as regras da fase implementadas e testadas
- [x] Pipeline completo roda sem regressao
- [x] Relatorio de validacao inclui novos apontamentos
- [x] `python -m src.rules --check` mostra regras como implementadas

---

## 8. Riscos e Mitigacoes

| Risco | Impacto | Mitigacao |
|---|---|---|
| Falsos positivos em regras de indicio | Ruido para o usuario | Rebaixar regras analiticas/heuristicas para warning; exigir contexto externo (beneficio fiscal, legislacao) para critical |
| Tabelas externas desatualizadas | Resultados incorretos | Versionar tabelas com periodo de vigencia |
| Performance com 94+ regras | Lentidao na validacao | Executar por stage com streaming; cache de lookups |
| Regras juridicas sem contexto | Conclusoes erradas | Marcar como "depende_externo" e exibir aviso no frontend |
| Sobreposicao com regras existentes | Apontamentos duplicados | Mapear error_types unicos; deduplicar no pipeline |

---

## 9. Metricas de Sucesso

- **Cobertura atual:** 191/191 regras implementadas (100%)
- **Falsos positivos:** < 5% em arquivo de referencia (regras analiticas rebaixadas para warning)
- **Performance:** Validacao completa < 30s para arquivo de 15k registros
- **Testes:** 1601 testes automatizados passando (78 novos v5)
- **Regressao:** Zero regras existentes quebradas

---

## 10. Melhorias PRD v4 (2026-04-06)

### Governanca de Correcoes
- Campo `corrigivel` obrigatorio em todas as 186 regras
  - `automatico`: correcao inequivoca (formato, contagem bloco 9)
  - `proposta`: correcao com impacto fiscal, requer justificativa (min 10 chars)
  - `investigar`: anomalia detectada, correcao bloqueada — requer analise externa
  - `impossivel`: dados externos necessarios, sem acao possivel
- `correction_service.py` enforce governanca antes de aplicar correcao
- `python -m src.rules --check` valida presenca de corrigivel

### Correcoes Fiscais
- SN_003: teto corrigido para 3.95% (LC 155/2016 Anexos I-V)
- SN_012: threshold uniformidade aumentado para 1.0pp, severity rebaixado para info
- REF_COD_PART_D100 desativado (duplicava D_001 em bloco_d_validator)
- Vigencia de regras enforced no pipeline (regras de 2024 nao aplicam a arquivo de 2022)

### Workflow de Resolucao
- Tabela `finding_resolutions` no audit.db
- Status: open | accepted | rejected | deferred | noted
- Endpoint `POST /api/findings/{id}/resolve`
- Rejeicao exige justificativa (min 20 chars)

### Frontend
- Filtros dropdown: severidade, registro, certeza, ordenacao
- Contador "X de Y apontamentos"
- Materialidade financeira (R$) como badge por apontamento
- Graficos de distribuicao (ErrorChart.tsx — Recharts)
- Painel de escopo (AuditScopePanel)

### Embedding
- config.py: EMBEDDING_MODEL_NOTES documentado
- python -m src.embeddings --info

---

## 11. Melhorias PRD v5 (2026-04-07)

### Bloco K — Producao e Estoque (5 regras)

| ID | Registro | error_type | Severidade | Descricao |
|---|---|---|---|---|
| K_001 | K001 | K_BLOCO_SEM_MOVIMENTO_COM_REGISTROS | error | K001 IND_MOV=1 com registros analiticos K210/K220/K230 |
| K_002 | K200 | K_REF_ITEM_INEXISTENTE | warning | COD_ITEM do K200 nao encontrado no cadastro 0200 |
| K_003 | K200 | K_QTD_NEGATIVA | error | Quantidade no inventario K200 negativa |
| K_004 | K230 | K_REF_ITEM_INEXISTENTE | warning | COD_ITEM do K230 nao encontrado no 0200 |
| K_005 | K230 | K_ORDEM_SEM_COMPONENTES | info | Ordem de producao K230 sem registros K235 de componentes |

### Governanca de Correcoes Aprimorada

- `CorrectionBlockedError`: levantado quando correcao automatica tenta alterar campo sensivel
- 22 campos bloqueados: CNPJ, CPF, IE, CHV_NFE, CHV_CTE, NUM_DOC, SER, COD_MOD, VL_DOC, VL_ICMS, VL_BC_ICMS, VL_ICMS_ST, VL_IPI, VL_PIS, VL_COFINS, VL_TOT_DEBITOS, VL_TOT_CREDITOS, CST_ICMS, CSOSN, CST_PIS, CST_COFINS, CFOP, DT_DOC
- FMT_CNPJ e FMT_CPF reclassificados de `automatico` para `investigar`
- Validacao integrada no inicio de `apply_correction()`

### Tolerancia por Contexto

- `ToleranceResolver` com `ToleranceType` enum (8 tipos) e `ToleranceConfig` dataclass
- Substitui tolerancia unica de R$0,02 por tolerancias diferenciadas:
  - Item (ICMS/IPI/PIS/COFINS): R$0,01
  - Documento (VL_DOC): R$0,02
  - Consolidacao (C190 vs C170): R$0,10
  - Apuracao (E110): R$1,00
  - Inventario (H010): R$0,10
- API retrocompativel: `get_tolerance()` e `CALCULATION_TOLERANCE` mantidos

### Novos Modulos de Infraestrutura

| Modulo | Funcao |
|---|---|
| `field_registry.py` | FieldRegistry singleton — acesso a campos por nome via DB ou REGISTER_FIELDS |
| `helpers_registry.py` | fval/fnum/fstr — shorthand para acesso seguro a campos |
| `regime_detector.py` | RegimeDetector multi-sinal com confianca (IND_PERFIL + CSOSN + CST) |
| `error_deduplicator.py` | ErrorDeduplicator — agrupa por (linha, campo, grupo semantico), mantém o de maior impacto |
| `rate_limiter.py` | SlidingWindowRateLimiter — 10 uploads/min, 5 validacoes/min por IP |
| `audit_scope.py` | GET /api/audit-scope — escopo e limitacoes do sistema |

### Aliquotas Internas por UF

- `aliquotas_internas_uf.yaml` atualizado com 27 UFs e fontes legislativas
- AM=20% (Dec. 20.686/2000), CE=20% (Dec. 24.569/97), RJ=20% (Lei 2.657/96)
- `get_aliquota_interna_uf(uf, default)` para consulta direta
- Usado na regra CST_004 para parametrizar piso por UF

### Streaming e Limites

- `parse_sped_file_stream()`: generator para arquivos grandes (>50MB) sem OOM
- `MAX_UPLOAD_MB` configuravel via env (padrao: 50MB)
- Upload retorna HTTP 413 com detalhes estruturados se exceder limite

### Qualidade e Testes

- 78 novos testes (total: 1601)
- 6 fixtures de cenarios fiscais reais
- `scripts/check_hardcoded_indices.py`: lint AST para proibir campos hardcoded
- `Makefile` com targets: lint, check-indices, test, ci
- Migracao DB v11: ind_regime, regime_confidence, regime_signals em sped_files
