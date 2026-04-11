# Plano Mestre de Melhorias — SPED EFD Validator v5.1

## Contexto

O sistema atual (v3.0.0) possui 177 regras em 37 validadores, mas tem lacunas criticas identificadas em 3 PRDs (`upgrade/1 PRD_SPED.md`, `upgrade/2 PRD_SPED.md`, `upgrade/3 PRD_SPED.md`) e no `melhorias.txt`. Este plano consolida TODOS os pontos de melhoria sem duplicacao, priorizados em 7 fases de entrega. O objetivo final: transformar o sistema em uma plataforma de auditoria fiscal ICMS/IPI defensavel perante SEFAZ-ES e RFB.

**Escopo definitivo:** EFD ICMS/IPI exclusivamente. PIS/COFINS parseados para consistencia estrutural, mas fora do escopo de validacao de conteudo. EFD Contribuicoes em sistema separado.

**Origem:** Consolidacao de PRDs v5.0 + PRDs v5.1 (`upgrade/1 PRD_SPED_EFD_Validator_v5.1_FINAL.md`, `upgrade/2 PRD_SPED_EFD_Validator_v5.1_FINAL.md`) e `melhorias.txt` (deletado).

---

## FASE 1 — Correcoes Criticas Obrigatorias (Pre-requisito absoluto)

> Nenhuma feature nova sem que TODOS estes bugs estejam corrigidos e validados com arquivos reais.

### BUG-001: Deteccao de Regime por CST (nao por IND_PERFIL)
- **Problema:** `regime_detector.py` usa `IND_PERFIL` (nivel de escrituracao A/B/C) como regime fiscal. Incorreto em 100% dos casos.
- **Correcao:** Detectar regime pelos CSTs reais do arquivo:
  - CSTs 101-900 ou CSOSN → Simples Nacional
  - CSTs 00-90 sem CSOSN → Regime Normal (LP/LR)
  - Confirmar com tabela `clientes` do MySQL. Se conflito → `regime_source='CONFLITO'` + alerta no relatorio
- **Normalizar CST 6 digitos (SN):** Ultimos 2 digitos antes de qualquer validacao
- **Arquivos:** `src/validators/regime_detector.py`, `src/services/context_builder.py`
- **Teste:** Perfil C + CSTs 101+ → `regime=SN`; Perfil A + CSTs 00-90 + MySQL=LR → `regime=NORMAL`

### BUG-002: ICMS-ST com MVA — Formula Completa em 4 Etapas
- **Problema:** Valida apenas ICMS-ST ja escriturado. Nao detecta BC subdimensionada por MVA incorreto.
- **Correcao:** Implementar formula completa:
  1. `BC_ST = (VL_ITEM + VL_FRT + VL_SEG + VL_OUT_DA - VL_DESC) * (1 + MVA/100)`
  2. Ajuste para remetente SN: `BC_ST_aj = BC_ST * (1 - aliq_inter/aliq_interna_dest)`
  3. `VL_ICMS_ST_esp = (BC_ST_aj * ALIQ_ST/100) - VL_ICMS_proprio`
  4. Divergencia com tolerancia proporcional
- **Novos error types:** `ST_MVA_AUSENTE`, `ST_MVA_DIVERGENTE`, `ST_MVA_NAO_MAPEADO`, `ST_ALIQ_INCORRETA`, `ST_REGIME_REMETENTE`
- **Tabela:** `mva_por_ncm_uf.yaml` (NCM → UF → MVA%)
- **Arquivos:** `src/validators/st_validator.py`, `data/reference/mva_por_ncm_uf.yaml`

### BUG-003: NF Cancelada/Denegada vs. Escriturada
- **Problema:** `COD_SIT` do C100 nao cruza com `cStat` do XML
- **Mapeamento:**
  - cStat 100 → COD_SIT 00 (Autorizada → Normal)
  - cStat 101/135 → COD_SIT 02 (Cancelada)
  - cStat 110/301 → COD_SIT 05 (Denegada)
  - COD_SIT=00 com cStat=101/135 → `NF_CANCELADA_ESCRITURADA` (error, critico)
  - COD_SIT=00 com cStat=110/301 → `NF_DENEGADA_ESCRITURADA` (error)
  - Qualquer incompatibilidade → `COD_SIT_DIVERGENTE_XML` (error)
- **Arquivos:** `src/services/xml_service.py`

### BUG-004: Eliminacao do Bypass de Autenticacao
- **Problema:** `API_KEY` nao configurada aceita qualquer valor
- **Correcao:**
  - `API_KEY` ausente → HTTP 500: "API Key nao configurada"
  - `API_KEY` < 32 chars → HTTP 500: "API Key deve ter minimo 32 caracteres"
  - Header ausente → HTTP 401 (mantido)
- **Arquivos:** `api/auth.py`

### BUG-005: Tolerancia Proporcional por Magnitude
- **Problema:** Tolerancia global fixa R$ 0,02 gera falsos positivos em itens de alto valor
- **Correcao:** 4 faixas proporcionais:
  - Ate R$ 100 → R$ 0,02 ou 0,02%
  - R$ 100-10.000 → R$ 0,05 ou 0,01%
  - R$ 10.000-500.000 → R$ 0,10 ou 0,005%
  - Acima R$ 500.000 → R$ 0,50 ou 0,001%
  - Criterio: o MENOR entre absoluto e relativo
- **Arquivos:** `src/validators/tolerance.py`, `config.py`

### BUG-006: DELETE Nao-Atomico no Pipeline
- **Problema:** DELETE antes de processar deixa sistema sem erros durante re-validacao
- **Correcao:** Acumular novos erros em memoria; troca atomica ao final:
  ```
  with db.transaction():
      DELETE FROM validation_errors WHERE file_id = ?
      bulk_insert(new_errors)
  ```
- **Arquivos:** `src/services/pipeline.py`

### BUG-007: Docker Compose de Producao
- **Problema:** `--reload` em producao, sem healthcheck
- **Correcao:**
  - Separar `docker-compose.yml` (prod) de `docker-compose.dev.yml`
  - Prod: `--workers 2 --no-access-log`
  - Healthcheck: `curl -f http://localhost:8021/api/health`
- **Arquivos:** `docker-compose.yml`, `docker-compose.dev.yml`, `Dockerfile`

---

## FASE 2 — Arquitetura Context-First + Stage 0 Obrigatorio

### 2.1 Stage 0 — Montagem de Contexto Obrigatorio
- **Regra:** Nenhuma validacao fiscal inicia sem contexto completo
- **Implementar `build_full_context()`:**
  1. Parsing 0000 → CNPJ, periodo, UF, perfil
  2. Cliente obrigatorio → `clientes` table (se nao cadastrado → erro bloqueante)
  3. Regime por CST (BUG-001) + confirmacao MySQL
  4. Beneficios ativos no periodo → `beneficios_ativos` table
  5. Instanciar `BeneficioEngine`
  6. CRTs dos emitentes → `emitentes_crt` table
  7. Caches Bloco 0: participantes (0150), produtos (0200), naturezas (0400)
  8. Tabelas fiscais: aliquotas, FCP, MVA, ajustes, beneficios
  9. Regras vigentes por periodo
  10. Contexto XML (modo B apenas)
  11. Calcular `context_hash` (para invalidar cache IA)
- **Se contexto incompleto:** Pipeline bloqueado com erro claro e acionavel
- **Contexto imutavel:** Nenhum validador altera o contexto apos Stage 0
- **Arquivos:** `src/services/context_builder.py` (reescrever), `src/services/pipeline.py`

### 2.2 ValidationContext v2
- **Novo dataclass expandido:**
  - `mode`: `SPED_ONLY` | `SPED_XML_RECON`
  - `run_id`, `context_hash`, `rules_version`
  - `cliente: ClienteInfo` (cnpj, regime, regime_override, uf, cnae, porte)
  - `beneficios_periodo: list[BeneficioAtivo]`
  - `beneficio_engine: BeneficioEngine`
  - `cst_validos_saida: set[str]`
  - `aliq_esperada_por_cfop: dict[str, float]`
  - `emitentes_sn: set[str]` (CNPJs com CRT=1)
  - `mva_ncm_uf: dict`, `aliq_interna_uf: dict`, `fcp_uf: dict`
  - `xml_by_chave: dict` (modo B), `has_xmls: bool`, `xml_cobertura_pct: float`
  - `tabelas_ausentes: list[str]`, `context_warnings: list[str]`
- **Arquivos:** `src/models.py`

### 2.3 Migration 13 — Novas Tabelas de Banco
- **`clientes`** — Cadastro mestre do contribuinte (cnpj, regime, regime_override, uf, cnae, porte)
- **`beneficios_ativos`** — Beneficios por cliente e vigencia (codigo, tipo, competencia_inicio/fim, ato_concessorio, aliq_efetiva, reducao_bc, debito_integral)
- **`emitentes_crt`** — CRT de emitentes (populado durante parsing XML; cnpj, crt 1/2/3, razao_social, uf)
- **`validation_runs`** — Snapshot de cada execucao (file_id, mode, regime_usado, regime_source, beneficios_json, context_hash, scores, status)
- **`xml_match_index`** — Indice de pareamento XML ↔ C100 (match_status: matched/sem_xml/sem_c100/fora_periodo/cancelada)
- **`coverage_gaps`** — Lacunas de cobertura por execucao (tabela_ausente, regra_pulada, xml_sem_par)
- **`fiscal_context_snapshots`** — Snapshot do contexto para audit trail
- **`field_equivalence_catalog`** — Catalogo formal de equivalencia XML ↔ SPED
- **Alteracoes em existentes:**
  - `nfe_xmls` += crt_emitente, uf_emitente, uf_dest, mod_nfe, dentro_periodo, c_sit, content_hash
  - `nfe_cruzamento` += nfe_item_id, xml_xpath, tipo_comp
- **Arquivos:** `src/services/database.py`

---

## FASE 3 — BeneficioEngine + Validacao de Beneficios Robusta

### 3.1 BeneficioEngine — Modulo Dedicado
- **Responsabilidade:** Responder perguntas fiscais sobre beneficios no contexto do contribuinte
- **Interface publica:**
  - `get_cst_validos_saida(cfop) → set[str]`
  - `get_aliq_esperada(cfop, ncm) → float | None`
  - `get_reducao_bc(cfop, ncm) → float | None`
  - `get_debito_integral(cfop) → bool`
  - `is_ncm_no_escopo(ncm, codigo_beneficio) → bool`
  - `audit_item_xml(item, emitente_crt, cfop) → list[BeneficioAuditResult]`
  - `get_crt_expected_cst_set(crt) → (campo, set[str])`
  - `get_conflitos_beneficios() → list[str]`
  - `get_beneficios_expirando(dias=90) → list[BeneficioAtivo]`
- **CSOSN → CST mapping (Res. CGSN 140/2018 Art. 59/60):**
  - 101→00 (tributada com permissao de credito)
  - 102→20 (tributada com reducao de BC) — **DISTINTO de 103**
  - 103→40 (isenta — sem tributacao)
  - 201→10 (com ST + debito proprio) — **efeito diferente de 202**
  - 202→10 (com ST sem tributacao propria)
  - 203→30 (ST sem debito proprio)
  - 300→41 (imune)
  - 400→40 (nao tributada pelo SN)
  - 500→60 (ST ja retida anteriormente)
  - 900→90 (outros)
  > **Atencao:** 201 e 202 ambos mapeiam para CST 10 mas tem efeitos fiscais distintos. O `FieldComparator._cst_aware()` deve usar esta tabela exata.
- **Multiplos beneficios:** Union de CSTs (OR), aliquota mais favoravel, conflitos como warning
- **Regras de beneficios ICMS-ES:**

  | Beneficio | CST Obrigatorio | Aliq. Efetiva | Debito Integral? | Base Legal |
  |-----------|----------------|---------------|------------------|------------|
  | COMPETE Atacadista | **00** | 3% (credito presumido via E111) | **Sim** — aliquota cheia no debito | Dec. 1.663-R/2005 |
  | COMPETE E-commerce | **00** | 3-6% conforme faixa | **Sim** | Dec. especifico e-commerce |
  | COMPETE Ind. Graficas | **00** | Conforme decreto | **Sim** | Conforme ato concessorio |
  | COMPETE Papelao/Plastico | **00** | Conforme decreto | **Sim** | Conforme ato concessorio |
  | INVEST-ES Industria | **51** | Diferimento parcial/total | Nao — debito diferido | Dec. 1.599-R/2005 |
  | INVEST-ES Importacao | **51** | Diferimento na importacao | Nao | Conforme decreto |
  | FUNDAP | **00** | Credito sobre pauta | Sim | Lei 2.508/1970 |
  | ST (substituto) | 10/30/70 | Conforme MVA/NCM/UF | N/A | Convenio ICMS 142/2018 |

  > **Regra de debito integral (COMPETE):** C190 de saidas deve ter CST 00 com ALIQ_ICMS = aliquota interna da UF (nao 3%). O credito presumido de 3% e ajuste via E111, nao reducao de aliquota em C170/C190. Se o contador reduzir a aliquota diretamente → `BENEFICIO_DEBITO_NAO_INTEGRAL`.
- **Arquivo novo:** `src/services/beneficio_engine.py`

### 3.2 Novas Regras de Beneficio
- `SPED_CST_BENEFICIO` — CST incompativel com beneficio ativo
- `SPED_ALIQ_BENEFICIO` — Aliquota incompativel com beneficio
- `SPED_ICMS_DEVERIA_ZERO` — Beneficio zera ICMS mas VL_ICMS > 0
- `SPED_BC_REDUCAO_DIVERGE` — BC ≠ VL_ITEM × (1 - reducao)
- `SPED_ICMS_ZERADO_SEM_BENEFICIO` — CFOP saida com VL_ICMS=0 sem beneficio
- `BENEFICIO_SEM_AJUSTE_E111` — Beneficio ativo sem E111 correspondente
- `AJUSTE_SEM_BENEFICIO_CADASTRADO` — E111 com codigo nao cadastrado
- `BENEFICIO_NAO_ATIVO` — Beneficio usado em E111 nao ativo no periodo
- `BENEFICIO_CNAE_INELEGIVEL` — CNAE nao elegivel ao beneficio
- `BENEFICIO_FORA_VIGENCIA` — Beneficio fora da vigencia
- `SOBREPOSICAO_BENEFICIOS` — Beneficios mutuamente exclusivos
- `CREDITO_PRESUMIDO_DIVERGENTE` — E111.VL_AJ_APUR ≠ calculo esperado
- `CREDITO_PRESUMIDO_ACIMA_DO_LIMITE` — Credito presumido excede limite
- `NCM_FORA_ESCOPO_BENEFICIO` — NCM nao esta no escopo do beneficio
- `CODIGO_AJUSTE_INCOMPATIVEL` — E111 com codigo incompativel
- `CST_REGIME_INCOMPATIVEL` — SN usando CST 00-90 sem CSOSN (ou Normal usando CSOSN)
- `REGIME_AJUSTADO_CSOSN` — Info quando normaliza CST 6 digitos para 2

---

## FASE 4 — Cadeia de Fechamento Fiscal Completa

### 4.1 Trilha 1: Documento → Item → Consolidacao
- C100 × SUM(C170): VL_DOC, VL_ICMS, VL_ICMS_ST, VL_IPI
- C100 sem itens → `C100_SEM_ITENS`
- C170 orfao (sem C100 pai) → `C170_ORFAO`
- C170 × C190 por grupo (CST+CFOP+ALIQ): VL_BC_CONT, VL_ICMS_TOT
- C190 sem lastro em C170 → `C190_COMBINACAO_INCOMPATIVEL`
- C190 ausente para grupo → `C190_AUSENTE_PARA_GRUPO`

### 4.2 Trilha 2: Consolidacao → Apuracao
- SUM(C190 saidas CFOP 5/6/7) + E110.VL_OUT_DEBITOS ≈ E110.VL_TOT_DEBITOS → `APURACAO_DEBITO_DIVERGENTE`
- SUM(C190 entradas CFOP 1/2/3) + E110.VL_OUT_CREDITOS + E110.VL_SLD_CREDOR_ANT ≈ E110.VL_TOT_CREDITOS → `APURACAO_CREDITO_DIVERGENTE`
- E110.VL_SLD_APURADO ≠ debitos - creditos → `APURACAO_SALDO_DIVERGENTE`
- VL_ICMS_RECOLHER=0 com saldo positivo sem E111 → `ICMS_ZERADO_SEM_AJUSTE`

### 4.3 Trilha 3: Ajuste → Recolhimento (E111 × E116)
- E111.COD_AJ_APUR validado contra tabela 5.1.1 da UF → `CODIGO_AJUSTE_INVALIDO_UF`
- E111 com codigo de beneficio sem cadastro → `BENEFICIO_NAO_ATIVO`
- Soma E111 debitos ≈ E110.VL_OUT_DEBITOS → `E110_OUT_DEBITOS_INCONSISTENTE`
- E116 deve existir se VL_ICMS_RECOLHER > 0 → `E116_AUSENTE_COM_ICMS_RECOLHER`
- SUM(E116.VL_OR) ≈ E110.VL_ICMS_RECOLHER → `E116_SOMA_DIVERGE_ICMS_RECOLHER`

### 4.4 Trilha 4: Beneficio → Ajuste → Apuracao
- Beneficio ativo sem reflexo E111 → `BENEFICIO_SEM_REFLEXO_E111`
- Credito presumido: verificar lastro em entradas → `CREDITO_PRESUMIDO_ACIMA_DO_LIMITE`
- Debito integral: C190 saidas com aliquota cheia → `BENEFICIO_DEBITO_NAO_INTEGRAL`

### 4.5 Trilha 5: ICMS-ST na Apuracao
- E210.VL_ICMS_RECOL_ST ≈ SUM(C170.VL_ICMS_ST) saidas → `ST_APURACAO_DIVERGENTE`
- E210.VL_RETENCAO_ST ≈ SUM(C100.VL_ICMS_ST) entradas → `ST_RETENCAO_DIVERGENTE`

### 4.6 Trilha 6: IPI na Apuracao
- E510 × SUM(C170.VL_IPI) por CST_IPI → `IPI_APURACAO_DIVERGENTE`
- CST IPI tributado com VL_IPI=0 → `IPI_CST_MONETARIO_ZERADO`
- BC_ICMS deve incluir VL_IPI se industrial (IND_ATIV=0) → `IPI_REFLEXO_BC_AUSENTE`

### Arquivos principais: `src/validators/apuracao_validator.py` (reescrever), novo `src/validators/encadeamento_validator.py`

---

## FASE 5 — Motor de Cruzamento XML Robusto + Dual-Path

### 5.1 Frontend Dual-Path
- **Tela inicial:** 2 cards de escolha (Validacao SPED | Validacao SPED × XML)
- **ClientContextBadge:** CNPJ, regime, beneficios, tabelas, alertas de expiracao
- **SpedOnlyUploadPanel:** Dropzone SPED + Painel de contexto + Progresso SSE (5 estagios)
- **SpedXmlUploadPanel:** 2 dropzones (SPED + XMLs) + Cobertura documental + Progresso SSE (7 estagios)
- **Bloqueio:** Se cliente nao cadastrado → cards bloqueados com mensagem acionavel
- **Pagina /clientes:** CRUD de clientes + aba Beneficios com vigencia + importacao CSV
- **Arquivos:** `frontend/src/pages/` (novas paginas), `frontend/src/components/`

### 5.2 Pipeline Unificado (Pipeline Unico)
- Cruzamento XML integrado como estagio 2.5 do pipeline
- Se nao tem XMLs, estagio pulado
- Um botao, um processo, um resultado (sem 2 processos separados)
- DELETE transacional (BUG-006): erros antigos visiveis ate nova carga completa
- Progresso SSE por estagio com detalhamento
- **Estagios modo SPED_ONLY:** 0-Contexto → 1-Estrutural → 2-Cruzamento SPED → 3-Enriquecimento
- **Estagios modo SPED_XML:** 0-Contexto → 1-Estrutural → 2-Cruzamento SPED → 2.5-Cruzamento XML → 3-Enriquecimento
- **Arquivos:** `src/services/pipeline.py`

### 5.3 Motor de Cruzamento Campo a Campo (FieldComparator)
- **field_map.yaml** — Configuracao externalizada de 45+ campos mapeados
- **Tipos de comparacao:** EXACT, MONETARY, PERCENTAGE, DATE, CST_AWARE, DERIVED, SKIP
- **CST_AWARE:** Resolve CRT do emitente (CRT=1/2 → CSOSN, CRT=3 → CST) — elimina falsos positivos para fornecedor SN
- **Nivel 1 — C100 × XML cabecalho:** CHV_NFE, NUM_DOC, SER, DT_DOC, VL_DOC, VL_ICMS, VL_BC_ICMS, VL_ICMS_ST, VL_IPI, VL_FRT, VL_DESC, COD_SIT (DERIVED), CNPJ emit/dest, IE, UF
- **Nivel 2 — C170 × XML itens:** NUM_ITEM, COD_ITEM, NCM, CFOP, QTD, VL_ITEM, CST_ICMS (CST_AWARE), VL_BC_ICMS, ALIQ_ICMS, VL_ICMS, VL_BC_ICMS_ST, ALIQ_ST, VL_ICMS_ST, CST_IPI, VL_BC_IPI, ALIQ_IPI, VL_IPI
- **Nivel 3 — C190 × XML agregacao:** Agrupar det[] por (CST, CFOP, pICMS), comparar totais
- **Contexto no cruzamento:** regime, CRT emitente, beneficios ativos, aliquotas UF, MVA, FCP
- **Regras XML com contexto de beneficio:** XML018 (CST × beneficio), XML019 (aliquota × beneficio), XML020 (periodo), XML021 (cobertura)
- **Politica de campos ausentes:**
  - SPED tem valor, XML ausente: join_key → ERROR; MONETARY com XML=0 → comparar contra 0.0; campo opcional → WARN
  - XML tem valor, SPED ausente/zero: valor > tolerancia×10 → ERROR; valor ≤ tolerancia×10 → WARN
  - Ambos ausentes ou zero → OK (sem divergencia)
  - "0,00" vs ausente → tratar como equivalentes
- **Arquivo novo:** `src/services/field_comparator.py`, `data/config/field_map.yaml`

### 5.4 Validacao de Periodo dos XMLs
- XMLs fora do periodo → marcar `dentro_periodo=0`, excluir do cruzamento
- Se >10% fora do periodo → warning bloqueante
- **Arquivo:** `src/services/xml_service.py`

### 5.5 CRT do Emitente Persistido
- Extrair `//emit/CRT` durante parsing XML
- Salvar em `nfe_xmls.crt_emitente` E em `emitentes_crt` (tabela incremental)
- Disponivel para `FieldComparator._cst_aware()`
- **Arquivos:** `src/services/xml_service.py`, `src/services/database.py`

### 5.6 Novos Endpoints API
- `GET /api/v1/files/{id}/context` — ValidationContext com regime, beneficios, tabelas
- `POST /api/v1/files/{id}/validate/sped` — Caminho A
- `POST /api/v1/files/{id}/validate/sped-xml` — Caminho B
- `GET /api/v1/files/{id}/xml/coverage` — Cobertura XML (% NF-e com XML)
- `GET /api/v1/files/{id}/xml/divergences` — Resumo divergencias por campo/NF-e
- `GET /api/v1/validation/{run_id}/coverage` — Regras executadas, puladas, lacunas
- `GET/POST /api/v1/clientes` — CRUD de clientes
- `GET /api/v1/equivalences` — Catalogo de equivalencias ativo
- **Arquivos:** `api/routers/` (novos routers)

---

## FASE 6 — Score de Risco, Cobertura e IA

### 6.1 Score de Risco Fiscal (0-100)
- **Formula ponderada:**
  - Erros critical × 40 peso
  - Erros high provavel × 25 peso
  - Erros beneficio × 20 peso
  - Erros ST/DIFAL × 10 peso
  - Erros sistemicos × 5 peso
- **Faixas:** 0-20 Baixo | 21-50 Moderado | 51-75 Elevado | 76-100 Critico
- **Arquivo novo:** `src/services/risk_score.py`

### 6.2 Score de Cobertura (tri-dimensional)
- `(regras_executadas / regras_totais) × sqrt(xml_coverage_pct) × (itens_reconciliados / total_itens)`
- O `sqrt()` no XML coverage penaliza menos cobertura parcial (XMLs dependem de terceiros)
- Registrar em `coverage_gaps`: tabela_ausente, regra_pulada, xml_sem_par
- Regras `NAO_EXECUTADA` listadas com motivo no relatorio
- **Arquivos:** `src/services/pipeline.py`, `src/services/export_service.py`

### 6.3 Cache de IA Corrigido
- **Chave ampliada:** rule_id + regime + uf + beneficio + ind_oper + campo + valor_encontrado + rule_version + prompt_version
- **Invalidacao:** Se prompt_version ou rule_version mudar → cache ignorado, IA regenera
- **Frentes de IA:**
  1. Explicacao inteligente de erros (cache incremental)
  2. Agrupamento e priorizacao de 2000+ erros em 3-5 problemas principais
  3. Sugestao de correcao contextual (campo `ai_suggestion`)
  4. Relatorio narrativo (parecer de fechamento)
- **Modelo preferido:** Claude Haiku (rapido/barato) para explicacoes, Claude Sonnet para narrativo
- **Frontend:** Badge "IA" + disclaimer "sugestao nao vinculante" + cor diferente
- **Arquivo:** `src/services/ai_service.py`

---

## FASE 7 — Qualidade, Relatorio e Casos de Borda

### 7.1 Base Legal 100%
- Toda regra em `rules.yaml` deve ter `base_legal` preenchido
- **Categorias de base legal:**
  - ICMS internas ES: RICMS-ES (Dec. 1.090-R/2002)
  - Interestaduais: Resolucao SF 22/1989
  - DIFAL: EC 87/2015 + LC 190/2022
  - ST: Convenio ICMS 142/2018
  - SN: LC 123/2006 + Res. CGSN 140/2018
  - Beneficios ES: Dec. COMPETE-ES 1.663-R/2005 + INVEST-ES + FUNDAP
  - IPI: Decreto 7.212/2010 (RIPI) + TIPI
  - XML: NT 2019.001 + Manual NF-e v7.0
  - Apuracao: RICMS-ES Arts. 78-95

### 7.2 Relatorio MOD-20 Completo (6 Secoes)
1. Cabecalho de identificacao (contribuinte, periodo, hash, versao)
2. Cobertura da auditoria (score, regras executadas/puladas, tabelas, limitacoes)
3. Sumario de achados (por severidade, certeza, bloco, top-10)
4. Achados detalhados (com base legal e orientacao)
5. Correcoes aplicadas (historico completo)
6. Rodape legal obrigatorio

### 7.3 Casos de Borda

| Caso | Comportamento | Error Type |
|------|--------------|------------|
| CST 6 digitos (SN) | Normalizar ultimos 2 digitos, sem erro estrutural | `REGIME_AJUSTADO_CSOSN` (info) |
| Regime misto no periodo (CSTs A e B) | Alertar, nao bloquear validacao | `REGIME_MISTO_NO_PERIODO` (warning) |
| Retificador parcial | Identificar registros alterados, vincular versoes | Info % retificado no relatorio |
| NF complementar (COD_SIT=07) sem original | Buscar por NUM_DOC+SER+CNPJ, alertar se ausente | `NF_COMPLEMENTAR_SEM_ORIGINAL` (warning) |
| Nota de ajuste ST (CFOP 1603/2603) | Nao aplicar regras ST padrao; base de ajuste especifica | Tratamento CFOP-especifico |
| C170 orfao (sem C100 pai) | Erro estrutural + excluir do cruzamento | `C170_ORFAO` (error, objetivo) |
| E110 VL_ICMS_RECOLHER=0 com debitos > creditos | Verificar E111; se ausente → erro | `ICMS_ZERADO_SEM_AJUSTE` (error) |
| Bloco G ausente para industrial Perfil A | Info no relatorio (nao erro se Perfil B/C) | `CIAP_BLOCO_AUSENTE` (info) |
| XML namespace invalido (MDF-e, CT-e) | Rejeitar com `rejection_reason`; incrementar contador | Nao processar |
| C100 com CHV_NFE vazia e COD_SIT=00 | Erro de formato + desabilitar cruzamento | `CHV_NFE_AUSENTE` (error) |
| CNPJ com IE de UF diferente do 0000 | Alerta de inconsistencia cadastral | `IE_UF_DIVERGE_CNPJ` (warning) |
| 500+ XMLs | Alertar performance; prosseguir com fila paralelo 5 threads | Warning no painel |
| Beneficio com sobreposicao no periodo | Detectar incompatibilidade entre beneficios | `SOBREPOSICAO_BENEFICIOS` (error) |
| Arquivo SHA-256 identico a run anterior | Toast: "Arquivo identico ao run {n}. Reutilizar analise?" | — |
| MVA nao mapeado para NCM/UF | Nao recalcular ST; registrar em coverage_gaps | `ST_MVA_NAO_MAPEADO` (warning) |
| Tabela fiscal ausente | Marcar regras como `NAO_EXECUTADA`; reduzir score | Registrar em coverage_gaps |

### 7.4 Recorrencia Temporal (futuro)
- `ERRO_RECORRENTE_NAO_CORRIGIDO` — Mesmo error_type em ≥3 periodos
- `RISCO_PRESCRICAO_90D` — Irregularidade com prazo decadencial ≤ 90 dias
- `VOLUME_VARIACAO_ATIPICA` — Variacao >50% no volume de ICMS

### 7.5 Frete × CT-e (futuro)
- `FRETE_SEM_CTE_VINCULADO` — VL_FRT no C100 sem D100
- `FRETE_CTE_VALOR_DIVERGENTE` — VL_FRT C100 ≠ VL_DOC D100
- `CREDITO_FRETE_NAO_ESCRITURADO` — CT-e com ICMS sem credito E110

---

## Roadmap de Sprints

| Sprint | Duracao | Entregas | Criterio |
|--------|---------|----------|----------|
| **1 — Bugs Criticos** | 2 sem | BUG-001 (Regime), BUG-003 (NF cancelada), BUG-004 (Auth), BUG-007 (Docker) | 4 bugs com testes; validado com arquivos reais |
| **2 — ST, Tolerancia, Contexto** | 2 sem | BUG-002 (ST+MVA), BUG-005 (Tolerancia), BUG-006 (DELETE atomico), Migration 13 | ST_MVA_DIVERGENTE em arquivo-teste; DELETE sem janela zero |
| **3 — Frontend Dual-Path** | 2 sem | Seletor de modo, SpedOnlyPanel, SpedXmlPanel, ClientContextBadge, SSE | Teste usabilidade; ambos modos funcionais |
| **4 — Cadeia de Fechamento** | 2 sem | C100×C170, C190×E110, E111×E116, Beneficio→Ajuste | C190_DIVERGE e E116_SOMA detectados em arquivos reais |
| **5 — Motor XML Completo** | 3 sem | field_map.yaml, FieldComparator, XML001-021, C190×XML | 100% campos mapeados; XML018/019 passando |
| **6 — Score e Relatorio** | 2 sem | Score risco, score cobertura, coverage_gaps, MOD-20 completo | Score exibido; regras NAO_EXECUTADA listadas |
| **7 — Qualidade** | 1 sem | base_legal 100%, coverage ≥85%, casos de borda | CI verde; zero pendencias base legal |

---

## Suite de Testes (arquivos esperados)

| Arquivo de Teste | Valida | Error Types Esperados |
|-----------------|--------|----------------------|
| `test_sped_sn_perfil_a.txt` | BUG-001: Regime por CST | `regime=SN` independente de IND_PERFIL |
| `test_sped_compete_atacadista.txt` | Beneficio CST + debito integral | `BENEFICIO_DEBITO_NAO_INTEGRAL` se aliq reduzida |
| `test_xml_compete_cst_errado.txt` | XML018: CST × beneficio | `XML018` gerado para CST incompativel |
| `test_xml_fornecedor_sn.txt` | CRT-aware: zero falsos positivos | Zero `XML008` para fornecedor SN |
| `test_xml_nf_cancelada.txt` | BUG-003: NF cancelada escriturada | `NF_CANCELADA_ESCRITURADA` |
| `test_xml_cobertura_60pct.txt` | Coverage scoring | `XML021` severity=high (<80%) |
| `test_sped_st_mva.txt` | BUG-002: ST com MVA completo | `ST_MVA_DIVERGENTE` com expected_value |
| `test_sped_encadeamento.txt` | Cadeia C190→E110→E111→E116 | `E116_SOMA_DIVERGE_ICMS_RECOLHER` |
| `test_xml_200_notas.txt` | Performance (< 3 min) | Pipeline completo |
| `test_sped_regime_conflito.txt` | Conflito CST vs MySQL | `regime_source=CONFLITO` + warning |

---

## Glossario Tecnico-Fiscal

| Termo | Significado |
|-------|------------|
| `IND_PERFIL` | Nivel de escrituracao (A/B/C). **NAO indica regime tributario.** |
| CST Tabela A | Origem da mercadoria (1o digito CST ICMS): 0=Nacional, 1=Estrangeira |
| CST Tabela B | Tributacao (2 ultimos digitos): 00=Tributada, 20=Reducao BC, 40=Isenta, 60=ST retida |
| CSOSN | Codigo de Situacao da Operacao no Simples Nacional. Substitui CST para empresas SN |
| CRT | Codigo de Regime Tributario no XML: 1=SN, 2=SN Excesso Receita, 3=Normal |
| MVA | Margem de Valor Agregado. % para calcular BC_ICMS_ST na ST prospectiva |
| DIFAL | Diferencial de Aliquota. ICMS interestadual para consumidor final nao contribuinte (EC 87/2015) |
| FCP | Fundo de Combate a Pobreza. Adicional ao DIFAL em UFs que o instituiram (RJ 2%, MG 2%) |
| `COD_SIT` C100 | Situacao do documento no SPED: 00=Normal, 02=Cancelada, 05=Denegada, 07=Complementar |
| `cSit` XML | Situacao na SEFAZ: 100=Autorizada, 101=Cancelada, 135=Cancelada fora prazo, 110/301=Denegada |
| MOD-20 | Modelo de relatorio de auditoria com 6 secoes obrigatorias |
| Debito Integral | Obrigatoriedade de calcular ICMS pela aliquota cheia antes de aplicar beneficio via E111 |
| Credito Presumido | Beneficio que permite creditar ICMS nao efetivamente pago, registrado em E111 |
| Context-First | Principio: contexto fiscal completo montado no Stage 0 antes de qualquer validacao |
| `NAO_EXECUTADA` | Regra nao executada por ausencia de dado (tabela, CRT, etc.). Reduz score de cobertura |
| `ind_ativ` | 0=industrial/equiparado (sujeito a IPI); 1=outros (sem IPI). Registro 0000 |

---

## Historico

- `melhorias.txt` — deletado (conteudo absorvido neste plano)
- PRDs v5.0 originais (3 arquivos) — consolidados na v5.0 deste plano
- `upgrade/1 PRD_SPED_EFD_Validator_v5.1_FINAL.md` — PRD v5.1 com correcoes (incorporado)
- `upgrade/2 PRD_SPED_EFD_Validator_v5.1_FINAL.md` — PRD v5.1 edicao definitiva (incorporado)
- **Correcoes v5.1 incorporadas:** CSOSN mapping com base legal, debito integral COMPETE, coverage tri-dimensional, politica campos ausentes, 6 novos error types de borda, suite de testes, glossario
- Este documento substitui TODA documentacao de melhorias anterior

---

## Verificacao

- Rodar `pytest` apos cada fase para garantir nao-regressao
- Validar com arquivos SPED reais de clientes apos Fases 1 e 2
- Teste de usabilidade com analistas apos Fase 3
- Coverage ≥85% apos Fase 7
