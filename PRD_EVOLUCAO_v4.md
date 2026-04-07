# PRD — Evolucao do Sistema SPED EFD para Maturidade Profissional

**Versao:** 4.0
**Data:** 2026-04-06
**Autor:** Bruno
**Status:** Concluido
**Contexto:** Sistema local para escritorio contabil, poucos usuarios, audit.db separado ja existente
**Objetivo:** Elevar as notas de maturidade, risco e potencial para >= 9.0 em todos os eixos

---

## 1. ESTADO ATUAL vs. ESTADO ALVO

| Dimensao | Nota Atual | Nota Alvo | Justificativa do Gap |
|---|---|---|---|
| Maturidade tecnica | 7.5 | 9.5 | Premissas fiscais incorretas (SN), inconsistencias de documentacao, meta-regras misturadas, vigencia nao enforced |
| Risco operacional | 6.0 | 9.0 | Correcao automatica sem confirmacao humana, falsos positivos SN, conformidade% sem escopo, achados sem flag de dependencia externa |
| Potencial do sistema | 9.0 | 9.5 | Bloco K ausente, sem workflow de resolucao de apontamentos, sem materialidade financeira, frontend basico |

**Premissa do PRD:** nenhuma mudanca de infraestrutura e necessaria. SQLite e adequado para escritorio. A arquitetura atual e solida. Os problemas sao de logica fiscal, governanca de correcoes e UX analitica.

---

## 2. MAPA DE MELHORIAS

As melhorias estao organizadas em quatro grupos por natureza:

| Grupo | Foco | Impacto nas Notas |
|---|---|---|
| **A** | Correcoes de logica fiscal (SN_003, SN_012, vigencia, deduplicacao) | Maturidade + Risco |
| **B** | Governanca de correcoes e transparencia de escopo | Risco |
| **C** | Schema e catalogo do rules.yaml | Maturidade |
| **D** | Frontend e workflow analitico | Maturidade + Potencial |

---

## 3. GRUPO A — CORRECOES DE LOGICA FISCAL

### 3.1 SN_003 — Reescrita da Regra de Credito pCredSN

**Problema atual:**
A regra usa teto fixo de 4.01% para a aliquota de credito do Simples Nacional. Isso e uma simplificacao que nao corresponde a LC 123/2006. O pCredSN e determinado por Anexo (I-V) e por faixa de Receita Bruta dos ultimos 12 meses (RBT12), conforme tabelas introduzidas pela LC 155/2016. O SPED Fiscal nao contem o campo RBT12, o que limita a verificacao — mas o sistema pode fazer muito mais do que faz hoje.

**Regra atual (incorreta):**
```yaml
condition: CSOSN in {101,201} AND (ALIQ==0 OR ALIQ > 4.01%)
```

**Comportamento incorreto:**
- Empresa do Anexo I na faixa 1 tem pCredSN de 0.40% — o teto de 4.01% nao captura esse cenario
- Empresa com aliquota de 3.50% (dentro do permitido em certas faixas) recebe falso positivo se o teto for interpretado como 4.01% sendo o unico limite valido
- Aliquota zero para CSOSN 101/201 e corretamente um erro — essa parte esta certa

**Reescrita proposta:**

```yaml
- id: SN_003
  register: C170
  fields: [CST_ICMS, ALIQ_ICMS, VL_ICMS]
  error_type: SN_CREDITO_ZERADO_OU_FORA_RANGE
  severity: warning
  description: >
    CSOSN 101/201 com aliquota de credito zerada (erro provavel) ou acima de 3.95%
    (acima do teto maximo da LC 123, Anexo I-V, todas as faixas, LC 155/2016).
    Sem o RBT12 no arquivo SPED nao e possivel determinar a faixa exata — portanto
    o sistema sinaliza como indicio, nao como erro objetivo.
  condition: >
    CSOSN in {101,201}
    AND (
      (ALIQ_ICMS == 0 AND VL_ICMS != 0) OR
      (ALIQ_ICMS == 0 AND VL_BC_ICMS > 0) OR
      (ALIQ_ICMS > 3.95)
    )
  certeza: indicio
  impacto: relevante
  severity: warning
  legislation: "LC 123/2006 art. 23 + LC 155/2016 — Tabelas Anexos I-V"
  mensagem_padrao: >
    CSOSN {CSOSN}: aliquota de credito ({ALIQ_ICMS}%) fora do range esperado para
    o Simples Nacional (max 3.95% conforme LC 155/2016, Anexos I-V).
    Verificar faixa de RBT12 e Anexo aplicavel ao contribuinte.
  acao_recomendada: >
    Consultar o DAS do periodo para verificar o Anexo e a faixa de RBT12.
    O pCredSN correto esta no proprio documento de apuracao do Simples Nacional.
  corrigivel: investigar
  depende_externo: true
  fontes_externas: [DAS, PGDAS-D]
  notas_tecnicas: >
    Teto de 3.95% derivado de: Anexo I faixa 6 (3.95%), Anexo II faixa 6 (3.30%),
    Anexo III faixa 6 (3.50%), Anexo IV sem credito, Anexo V faixa 6 (3.02%).
    O teto absoluto de qualquer faixa de qualquer Anexo e 3.95%.
    Aliquota zero + VL_BC preenchido = erro provavel (credito nao exercido ou
    empresa optou por nao segregar — requer confirmacao).
  implemented: true
  module: simples_validator.py
  vigencia_de: "2018-01-01"
  vigencia_ate: null
  version: "3.0"
  last_updated: "2026-04-06"
```

**Criterios de aceitacao:**
- [x] Empresa com pCredSN de 1.60% (Anexo I faixa 2) nao gera falso positivo
- [x] Empresa com ALIQ_ICMS = 0.00 e VL_BC > 0 gera warning
- [x] Empresa com ALIQ_ICMS = 5.00% gera warning
- [x] Empresa com ALIQ_ICMS = 3.95% nao gera alerta
- [x] Severidade e warning (nao error), certeza e indicio
- [x] mensagem_padrao exibe os valores reais do item

---

### 3.2 SN_012 — Reescrita ou Reclassificacao da Regra de Uniformidade

**Problema atual:**
A regra SN_012 dispara quando `max(ALIQ_ICMS) - min(ALIQ_ICMS) > 0.01` para CSOSN 101/201, com a premissa de que "a aliquota de credito deveria ser uniforme." Essa premissa e incorreta:

1. Produtos de Anexos diferentes (ex: produto industrial Anexo II vs. produto comercial Anexo I) podem ter pCredSN distintos para o mesmo contribuinte no mesmo periodo
2. A aliquota pode mudar entre meses se a empresa mudar de faixa de RBT12
3. A variacao de pCredSN dentro do mesmo Anexo e faixa e improvavel, mas nao impossivel em situacoes de arredondamento ou aplicacao por item

**Decisao necessaria — tres opcoes:**

**Opcao A (recomendada): Reformular como deteccao de anomalia, nao de erro**
```yaml
- id: SN_012
  description: >
    Aliquotas de credito ICMS variam significativamente entre itens (delta > 1pp)
    para CSOSN 101/201. Isso pode indicar: mistura de Anexos diferentes (correto mas
    raro), mudanca de faixa de RBT12 durante o periodo (improvavel), ou parametrizacao
    inconsistente no ERP (provavel erro).
  condition: >
    CSOSN in {101,201}
    AND count(distinct ALIQ_ICMS) > 1
    AND (max(ALIQ_ICMS) - min(ALIQ_ICMS)) > 1.0
  certeza: indicio
  severity: info
  corrigivel: investigar
```

**Opcao B: Desativar a regra**
Marcar `implemented: false` e documentar o motivo: sem o contexto do Anexo e da faixa de RBT12, a regra gera mais ruido do que valor.

**Opcao C: Manter como info com threshold maior (2pp)**
Reduzir o falso positivo aumentando o threshold para 2.0pp — variacao de mais de 2 pontos percentuais e muito mais suspeita.

**Criterios de aceitacao (Opcao A):**
- [x] Empresa com dois itens: ALIQ 1.60% e ALIQ 2.78% (delta 1.18pp) → gera info
- [x] Empresa com dois itens: ALIQ 1.60% e ALIQ 1.62% (delta 0.02pp) → nao gera alerta
- [x] Mensagem explica que pode ser correto (multiplos Anexos) ou erro de ERP
- [x] Severidade e info (nao warning nem error)

---

### 3.3 Validacao de Vigencia de Regras no Engine

**Problema atual:**
As regras no YAML tem campos `vigencia_de` e `vigencia_ate`, mas nao ha evidencia de que o orquestrador `run_full_validation()` utiliza esses campos para filtrar as regras aplicaveis ao periodo do arquivo sendo validado.

**Comportamento incorreto atual:**
Um arquivo SPED do periodo 01/2022 a 31/01/2022 pode receber apontamentos de regras criadas em 2024, que nao existiam ou nao eram aplicaveis em 2022.

**Implementacao necessaria em `validation_service.py`:**

```python
def filter_rules_by_period(rules: list[Rule], dt_ini: date, dt_fin: date) -> list[Rule]:
    """
    Aplica apenas regras vigentes para o periodo de escrituracao do arquivo.
    Logica:
      - vigencia_de <= dt_ini (regra ja existia quando o periodo iniciou)
      - vigencia_ate is None OR vigencia_ate >= dt_fin (regra ainda nao expirou)
    """
    return [
        r for r in rules
        if r.vigencia_de <= dt_ini
        and (r.vigencia_ate is None or r.vigencia_ate >= dt_fin)
    ]
```

Esse filtro deve ser chamado no inicio de `run_full_validation()` antes de qualquer stage, usando o periodo extraido do registro 0000 (`DT_INI`, `DT_FIN`).

**Criterios de aceitacao:**
- [x] Arquivo de 2022 nao recebe apontamentos de regras com `vigencia_de: 2024-01-01`
- [x] Arquivo de 2023 nao recebe apontamentos de regras com `vigencia_ate: 2022-12-31`
- [x] Log da validacao registra quantas regras foram filtradas por vigencia
- [x] Regras sem `vigencia_ate` (null) sao tratadas como permanentemente vigentes

---

### 3.4 Eliminacao de Regras Duplicadas

**Problema identificado:**
`REF_COD_PART_D100` em `cross_block_validator.py` e `D_001` em `bloco_d_validator.py` verificam a mesma condicao: `COD_PART do D100 nao encontrado no cadastro 0150`. Se ambos os modulos rodam no pipeline, o analista recebe dois apontamentos identicos para o mesmo registro.

**Acao necessaria:**
Escolher um dos dois como canonico e desativar o outro:

```yaml
# Manter: D_001 em bloco_d_validator.py (mais especifico, modulo correto)
# Desativar:
- id: REF_COD_PART_D100
  ...
  implemented: false
  deprecation_note: "Duplica D_001 em bloco_d_validator.py. Desativado em 2026-04-06."
```

**Criterios de aceitacao:**
- [x] Um unico apontamento por COD_PART ausente no D100
- [x] `REF_COD_PART_D100` marcado como `implemented: false` com nota de deprecacao
- [x] Teste de regressao confirma que o apontamento ainda e gerado (por D_001)

---

### 3.5 Correcao da Inconsistencia de Contagem no README

**Problema:** README cita "175 em 21 blocos" e "186 regras" em trechos diferentes. O PRD e o YAML confirmam 186.

**Acao necessaria:** Atualizar o README para consistencia:
- Tabela de metricas: `186 (22 blocos)`
- Texto descritivo: `186 regras implementadas em 22 blocos de validacao`
- Adicionar nota: "O numero inclui 5 meta-regras de governanca (GOV/AMOSTRA) e 6 regras do bloco pendentes, que geram alertas estruturais, nao apontamentos de campo."

---

## 4. GRUPO B — GOVERNANCA DE CORRECOES E TRANSPARENCIA DE ESCOPO

### 4.1 Campo `corrigivel` no Schema de Regras

Este e o mecanismo central de governanca. Cada regra no `rules.yaml` deve declarar seu nivel de corrigibilidade, e o `correction_service.py` deve enforcar esse nivel antes de aplicar qualquer correcao.

**Novo campo no schema:**

```yaml
corrigivel: automatico | proposta | investigar | impossivel
```

**Definicoes:**

| Valor | Significado | Comportamento no sistema |
|---|---|---|
| `automatico` | Correcao inequivoca, sem ambiguidade fiscal. Ex: formato de data, zeros de CNPJ, contagem do bloco 9. | Sistema pode propor E aplicar sem confirmacao adicional. Registra no audit_log. |
| `proposta` | Sistema sabe o que corrigir, mas a correcao tem impacto fiscal. Ex: recalculo de BC com delta pequeno, CST incompativel. | Sistema propoe o valor correto. Requer clique explícito de "Confirmar correcao" no frontend. Registra autor + justificativa no audit_log. |
| `investigar` | Sistema detectou anomalia mas nao tem dados suficientes para propor correcao correta. Ex: qualquer regra com certeza: indicio, regras SN, regras que dependem de contexto externo. | Sistema exibe o achado com orientacao de investigacao. Botao de correcao desabilitado. Usuario pode registrar "Verificado — sem correcao necessaria" com justificativa. |
| `impossivel` | Sistema nao tem dados para sugerir correcao. Ex: AUD_XML_SPED_DIVERGENCIA (requer o XML externo). | Sistema exibe apontamento apenas. Nenhuma acao de correcao disponivel. |

**Aplicacao por regra (amostra):**

| Regra | Corrigivel atual | Correto |
|---|---|---|
| FMT_CNPJ | (nao declarado) | `automatico` |
| FMT_DATA | (nao declarado) | `automatico` |
| BLOCO9_TOTAL_LINHAS | (nao declarado) | `automatico` |
| BASE_001 (recalculo BC) | (nao declarado) | `proposta` |
| C170_CFOP_VS_OPERACAO | (nao declarado) | `proposta` |
| SN_003 | sim | `investigar` |
| SN_012 | sim | `investigar` |
| DIFAL_001 | parcial | `investigar` |
| AUD_BENEFICIO_SEM_GOVERNANCA | nao | `investigar` |
| AUD_XML_SPED_DIVERGENCIA | nao | `impossivel` |

**Implementacao em `correction_service.py`:**

```python
def apply_correction(finding_id: str, new_value: str, user_id: str, justificativa: str) -> CorrectionResult:
    rule = get_rule_for_finding(finding_id)

    if rule.corrigivel == "impossivel":
        raise CorrectionNotAllowed("Esta regra nao permite correcao — dados externos necessarios.")

    if rule.corrigivel == "investigar":
        raise CorrectionNotAllowed(
            "Esta regra requer investigacao antes de correcao. "
            "Use 'Registrar verificacao' para documentar a analise."
        )

    if rule.corrigivel == "proposta":
        if not justificativa or len(justificativa.strip()) < 10:
            raise MissingJustificativa("Correce com impacto fiscal exige justificativa.")

    # Aplica correcao e registra no audit_log com user_id + justificativa
    ...
```

**Criterios de aceitacao:**
- [x] `correction_service.apply_correction()` bloqueia chamadas para regras `investigar` e `impossivel`
- [x] `correction_service.apply_correction()` exige `justificativa` nao vazia para regras `proposta`
- [x] audit_log registra: `finding_id`, `rule_id`, `field`, `old_value`, `new_value`, `user_id`, `justificativa`, `timestamp`
- [x] Todas as 186 regras no rules.yaml recebem o campo `corrigivel` com valor correto
- [x] Frontend desabilita botao de correcao para `investigar` e `impossivel`
- [x] Frontend exibe campo obrigatorio de justificativa para `proposta`

---

### 4.2 Workflow de Resolucao de Apontamentos (Aceitar / Rejeitar / Postergar)

**Problema atual:**
O analista ve os apontamentos mas nao tem como registrar suas decisoes sobre eles. Ao revalidar o arquivo, os mesmos apontamentos reaparecem. Nao ha memória do trabalho analitico feito.

**Novo conceito: `FindingResolution`**

Cada apontamento pode ter um dos seguintes estados de resolucao:

```
open        → novo, nao revisado
accepted    → analista confirmou que e um erro e aplicou correcao (ou registrou que sera corrigido na proxima entrega)
rejected    → analista verificou e concluiu que NAO e um erro (com justificativa obrigatoria)
deferred    → analista reconheceu mas posterga a analise (com prazo opcional)
noted       → analista tomou ciencia, nao e acionavel (tipico para info/warning de indicio)
```

**Schema da tabela `finding_resolutions` no audit.db:**

```sql
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

**Comportamento no pipeline de revalidacao:**
- Ao revalidar um arquivo, apontamentos com `status = rejected` sao exibidos com badge "Verificado — sem correcao" e a justificativa registrada
- Apontamentos com `status = accepted` + correcao aplicada nao reaparecem (o campo ja foi corrigido)
- Apontamentos com `status = deferred` reaparecem com badge "Adiado" e a data do prazo

**Criterios de aceitacao:**
- [x] Tabela `finding_resolutions` criada no audit.db com schema correto
- [x] API endpoint `POST /api/findings/{id}/resolve` aceita `status + justificativa + prazo`
- [x] Frontend exibe botoes "Aceitar" / "Rejeitar" / "Postergar" / "Ciência" por apontamento
- [x] Rejeicao exige justificativa com minimo 20 caracteres
- [x] Ao revalidar, apontamentos rejeitados aparecem com badge verde "Verificado"
- [x] Relatorio exportado inclui coluna `status_resolucao` e `justificativa`

---

### 4.3 Comunicacao de Escopo no Frontend

**Problema atual:**
O dashboard exibe `conformidade%` sem comunicar o escopo das validacoes. Um arquivo com 0 erros detectados pode ter problemas reais fora do escopo do sistema.

**Mudancas necessarias no frontend:**

**4.3.1 Renomear a metrica**
```
ANTES: "Conformidade: 97%"
DEPOIS: "Conformidade verificavel: 97%"
         (escopo: validacoes internas do arquivo SPED)
```

**4.3.2 Adicionar painel de escopo (collapsible)**
```
[i] O que este sistema NAO valida:
  • Legitimidade de beneficios fiscais (requer ato concessivo/convenio)
  • Cruzamento com XML das NF-e (requer documentos externos)
  • Cruzamento com EFD-Contribuicoes (arquivo separado)
  • Protocolo ICMS-ST por par de UF/NCM (tabela de protocolos)
  • Bloco K — Livro de Controle de Producao e Estoque
  • Escrituracoes anteriores ou posteriores (periodo unico)
```

**4.3.3 Badge por apontamento: "Requer contexto externo"**
Para cada apontamento gerado por regra com `depende_externo: true`, exibir badge amarelo "⚠ Requer validacao externa" com tooltip explicando qual dado externo e necessario.

**Criterios de aceitacao:**
- [x] Metrica renomeada para "Conformidade verificavel" com tooltip de escopo
- [x] Painel de escopo exibido na pagina de detalhes do arquivo (collapsible, fechado por padrao)
- [x] Apontamentos de regras com `depende_externo: true` exibem badge "Requer validacao externa"
- [x] Tooltip do badge cita o campo `fontes_externas` da regra

---

### 4.4 Visibilidade da Vigencia de Regras no Frontend

Para apontamentos gerados por regras com `vigencia_de` recente (regra nova), exibir um indicador discreto:

```
[NOVA REGRA — vigente desde 01/01/2026]
```

Isso informa o analista que aquele tipo de apontamento e recente e pode nao ter ocorrido em analises anteriores do mesmo cliente.

---

## 5. GRUPO C — SCHEMA E CATALOGO DO RULES.YAML

### 5.1 Adicionar Campos Obrigatorios ao Schema

Todos os registros do `rules.yaml` devem ter os seguintes campos padronizados. Campos ausentes devem ser preenchidos ou marcados como `null` explicitamente:

```yaml
# Campos obrigatorios novos (adicionar a todos os registros existentes):
corrigivel: automatico | proposta | investigar | impossivel
tipo_regra: formato | campo | intra | cruzamento | recalculo | semantica | juridica | auditoria | metarregra
tipo_achado: erro_objetivo | inconsistencia | indicio | risco_fiscal | alerta | metarregra
mensagem_padrao: "Texto para o analista com {placeholders} de campo"
acao_recomendada: "O que o analista deve fazer ao ver este apontamento"
depende_externo: true | false
fontes_externas: []   # lista de strings, ex: ["XML NF-e", "DAS", "Convenio X"]
```

**Criterios de aceitacao:**
- [x] `python -m src.rules --check` valida a presenca de todos os campos obrigatorios
- [x] `--check` retorna erro se algum registro nao tem `corrigivel` declarado
- [x] Script de migracao `migrate_rules_schema.py` preenche campos ausentes com valores default razoaveis e lista os que precisam de revisao manual

### 5.2 Separacao de Meta-Regras

GOV_001, GOV_002, GOV_003, GOV_004 e AMOSTRA_001 sao requisitos de comportamento do sistema, nao validacoes de campo do arquivo SPED. Devem ser movidas para uma secao separada:

**No rules.yaml:**
```yaml
# Secao separada, nao processada pelo motor de validacao
meta_comportamento:
- id: GOV_001
  descricao: "Classificar achado como erro material, parametrizacao ou tese fiscal"
  implementado_em: beneficio_audit_validator.py
  categoria: governanca_interna
  # Nao tem: severity, register, fields, condition — nao e uma regra de validacao
```

O pipeline de validacao (`run_full_validation()`) nao deve iterar sobre `meta_comportamento` — apenas sobre as secoes de regras reais.

**Criterios de aceitacao:**
- [x] GOV_001-004 e AMOSTRA_001 movidas para secao `meta_comportamento` no YAML
- [x] `run_full_validation()` nao gera apontamentos para registros em `meta_comportamento`
- [x] `python -m src.rules --check` conta meta-regras separadamente das regras de validacao
- [x] Contagem oficial passa a ser: "181 regras de validacao + 5 meta-comportamentos = 186 total"

---

## 6. GRUPO D — FRONTEND E WORKFLOW ANALITICO

### 6.1 Editor de Campo Inline (Implementar funcionalidade existente na API)

A API ja tem o endpoint de correcao. O frontend nao tem a UI correspondente. Esta e a lacuna mais critica do frontend.

**Comportamento esperado:**
1. Na aba "Erros", cada linha da tabela tem um botao de edicao (icone de lapis)
2. Clicar no botao abre um painel inline com:
   - Campo: nome do campo
   - Valor atual: leitura de apenas
   - Novo valor: input editavel
   - Justificativa: textarea obrigatorio para regras `proposta`
   - Botao "Confirmar" (desabilitado se `corrigivel: investigar` ou `impossivel`)
3. Ao confirmar, chama `PATCH /api/records/{id}/field`
4. O registro na tabela atualiza para `status: corrected` com badge verde

**Criterios de aceitacao:**
- [x] Editor inline funcional para todos os registros com apontamentos
- [x] Botao desabilitado (com tooltip explicativo) para regras `investigar` e `impossivel`
- [x] Campo justificativa exibido e obrigatorio para regras `proposta`
- [x] Apos correcao, badge `CORRIGIDO` aparece na linha sem recarregar a pagina
- [x] Undo da correcao disponivel (chama o endpoint de reversao ja existente)

---

### 6.2 Graficos de Erros no Dashboard

Os dados ja estao disponiveis no endpoint `/api/files/{id}/summary`. Falta a visualizacao.

**Graficos necessarios (usando Recharts, ja disponivel no frontend):**

**Grafico 1 — Distribuicao por Severidade (PieChart)**
```
critical: N | error: N | warning: N | info: N
```

**Grafico 2 — Top 10 Tipos de Erro (BarChart horizontal)**
```
SOMA_DIVERGENTE       |████████████| 42
CFOP_MISMATCH         |████████    | 31
CALCULO_DIVERGENTE    |██████      | 23
...
```

**Grafico 3 — Apontamentos por Registro (BarChart)**
```
C170 |██████████████| 87
E110 |████          | 18
C190 |███           | 12
...
```

**Grafico 4 — Status de Resolucao (PieChart)**
Disponivel apos implementacao do Grupo B:
```
Abertos: 45 | Verificados: 12 | Corrigidos: 8 | Postergados: 3
```

**Criterios de aceitacao:**
- [x] Graficos 1, 2 e 3 implementados na aba "Resumo" do FileDetailPage
- [x] Grafico 4 implementado apos item 4.2 (workflow de resolucao)
- [x] Graficos sao responsivos (funcionam em tela menor)
- [x] Clicar em barra/fatia do grafico filtra a tabela de apontamentos

---

### 6.3 Filtros e Ordenacao na Tabela de Apontamentos

**Problema atual:**
A tabela de erros nao tem filtros. Em um arquivo com 200+ apontamentos, o analista nao consegue priorizar nem focar em uma categoria especifica.

**Filtros necessarios:**
```
[Severidade: Todos | Critical | Error | Warning | Info     ]
[Registro:   Todos | C100 | C170 | C190 | E110 | ...       ]
[Status:     Todos | Aberto | Corrigido | Verificado | ...  ]
[Certeza:    Todos | Objetivo | Provavel | Indicio          ]
[Externo:    Todos | Apenas internos | Requer dados externos]
```

**Ordenacao:**
- Por severidade (descendente por default)
- Por registro
- Por tipo de erro
- Por materialidade financeira (quando disponivel — ver item 6.4)

**Criterios de aceitacao:**
- [x] Cinco filtros implementados com UI dropdown/chips
- [x] Filtros sao combinaveis (AND logico)
- [x] Ordenacao por coluna funcional
- [x] Estado dos filtros preservado ao navegar entre abas
- [x] Contador "X de Y apontamentos" atualiza ao filtrar

---

### 6.4 Materialidade Financeira Estimada por Apontamento

Para apontamentos de natureza matematica (recalculo divergente, soma incorreta, base errada), o sistema ja tem os valores. O que falta e exibir o impacto financeiro estimado.

**Logica por tipo:**

| Tipo de achado | Materialidade estimada |
|---|---|
| BASE_001 (recalculo BC) | `abs(BC_calculada - BC_declarada) * ALIQ / 100` |
| E110_SALDO_APURADO | `abs(saldo_calculado - saldo_declarado)` |
| C190_SOMA_VL_ICMS | `abs(soma_c170 - c190_declarado)` |
| AUD_E111_SOMA_VS_E110 | `abs(soma_e111 - campo_e110)` |
| SN_003 | `VL_BC_ICMS * (ALIQ_informada - ALIQ_esperada_max) / 100` |

Para apontamentos de natureza semantica ou cadastral (CFOP errado, CST incompativel), exibir o valor do documento como proxy de materialidade.

**Exibicao no frontend:**
```
[!] BASE_001 — C170 linha 847      R$ 1.247,83 estimado
    Base de calculo ICMS divergente: R$ 45.632,00 declarado vs R$ 44.384,17 calculado
```

**Criterios de aceitacao:**
- [x] Coluna "Materialidade" adicionada a tabela de apontamentos
- [x] Materialidade calculada para regras matematicas (BASE, E110, C190, AUD_E111_SOMA)
- [x] Para regras nao matematicas, exibir valor do documento (VL_DOC ou VL_ICMS)
- [x] Ordenacao por materialidade disponivel
- [x] Totaliza materialidade dos apontamentos `critical` no score card do dashboard

---

### 6.5 Documentar o Modelo de Embedding Usado

**Problema:** `src/embeddings.py` e um wrapper do sentence-transformers mas o modelo especifico nao e documentado em nenhum lugar publico.

**Acao necessaria em `config.py`:**
```python
# Modelo de embedding para busca semantica na documentacao SPED
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"  # ou o modelo real
EMBEDDING_MODEL_NOTES = (
    "Modelo multilingue treinado em dados genericos. Funciona razoavelmente para "
    "terminologia fiscal em portugues mas pode nao distinguir nuances tecnicas como "
    "'credito presumido' vs 'credito outorgado'. Candidato a substituicao por modelo "
    "especializado em documentos legais/fiscais brasileiros."
)
```

**Adicionar ao README:**
```markdown
### Modelo de Embedding
- **Modelo atual:** [nome do modelo]
- **Dimensao:** [N] dimensoes
- **Lingua:** Multilingue / Portugues
- **Limitacao conhecida:** Terminologia fiscal especifica (beneficios, CST, DIFAL)
  pode ter representacao subotima. Resultados de busca semantica para termos muito
  tecnicos devem ser verificados manualmente.
```

**Criterios de aceitacao:**
- [x] `config.py` tem `EMBEDDING_MODEL` e `EMBEDDING_MODEL_NOTES` documentados
- [x] README tem secao "Modelo de Embedding" com nome, dimensao e limitacoes
- [x] `python -m src.embeddings --info` exibe o modelo carregado em tempo de execucao

---

## 7. MELHORIAS DE POTENCIAL (EXPANSAO FUTURA)

Estas melhorias nao sao bloqueantes para atingir 9.0 nas notas atuais, mas elevam o potencial de 9.0 para 9.5+.

### 7.1 Tabela de Protocolos ICMS-ST

**Problema:** `st_validator.py` valida ST sem saber quais NCMs tem ST por par de UF origem-destino.

**Proposta:**
```yaml
# data/protocolos_st.yaml
# Fonte: Portal SEFAZ Nacional, tabela de convenios e protocolos
protocolos:
  - protocolo: "ICMS 41/2008"
    produto: "Automoveis e Veiculos"
    ncm_prefixos: ["8703", "8704", "8711"]
    uf_pares:
      - {origem: SP, destino: MG, mva: 34.15, vigencia_de: "2008-06-01"}
      - {origem: SP, destino: RJ, mva: 34.15, vigencia_de: "2008-06-01"}
```

**Regras habilitadas:** ST_001, ST_002, DIFAL_002 (ST vs DIFAL)

---

### 7.2 Tabela de CFOPs Validos com Restricoes

**Proposta:**
```yaml
# data/cfop_validos.yaml
cfops:
  - cfop: "1101"
    descricao: "Compra para industrializacao ou producao rural"
    tipo_operacao: entrada
    tipo_contribuinte: [industrial, produtor_rural]
    gera_credito: true
  - cfop: "5101"
    descricao: "Venda de producao do estabelecimento"
    tipo_operacao: saida
    ...
```

Permite validar CFOPs que existem no formato mas nao na tabela oficial, ou CFOPs usados por tipos de contribuinte incorretos.

---

### 7.3 Cruzamento com EFD-Contribuicoes

**Problema:** `AUD_SPED_VS_CONTRIBUICOES` e implementada mas sem dados externos para cruzar.

**Proposta minima de UI:**
- Adicionar endpoint `POST /api/files/{id}/contribuicoes` que aceita o arquivo EFD-Contribuicoes correspondente
- Quando presente, habilitar `AUD_SPED_VS_CONTRIBUICOES` com dados reais
- Exibir no dashboard: "EFD-Contribuicoes: [Nao carregado | Carregado - periodo X]"

---

### 7.4 Suporte ao Bloco K (Controle de Producao e Estoque)

**Escopo:** Empresas industriais e atacadistas obrigados ao Bloco K representam um subconjunto de clientes do escritorio. Para esses clientes, o sistema atualmente nao valida o bloco mais relevante.

**Validacoes do Bloco K:**
- K200 vs K230: estoque declarado vs. producao acumulada
- K230 vs K235: insumos declarados vs. componentes de producao
- K230 vs C170: producao declarada vs. saidas documentadas

**Prioridade:** Baixa (nao bloqueia as notas de 9.0, mas e o proximo ganho de cobertura fiscal mais relevante)

---

## 8. TABELA DE IMPACTO NAS NOTAS

| Item | Grupo | Impacto Maturidade | Impacto Risco | Impacto Potencial |
|---|---|---|---|---|
| 3.1 SN_003 reescrita | A | +0.3 | +0.5 | — |
| 3.2 SN_012 reformulacao | A | +0.2 | +0.3 | — |
| 3.3 Vigencia no engine | A | +0.3 | +0.2 | — |
| 3.4 Deduplicacao D_001 | A | +0.1 | +0.1 | — |
| 3.5 Inconsistencia README | A | +0.1 | — | — |
| 4.1 Campo `corrigivel` | B | +0.3 | +0.7 | — |
| 4.2 Workflow resolucao | B | +0.2 | +0.4 | +0.2 |
| 4.3 Escopo no frontend | B | — | +0.4 | — |
| 4.4 Vigencia no frontend | B | +0.1 | — | — |
| 5.1 Schema obrigatorio | C | +0.2 | +0.1 | — |
| 5.2 Meta-regras separadas | C | +0.2 | +0.1 | — |
| 6.1 Editor inline | D | +0.2 | — | +0.2 |
| 6.2 Graficos dashboard | D | +0.1 | — | +0.2 |
| 6.3 Filtros tabela | D | +0.1 | — | +0.1 |
| 6.4 Materialidade financeira | D | +0.1 | +0.1 | +0.3 |
| 6.5 Embedding documentado | D | +0.1 | — | — |
| **TOTAL ESTIMADO** | | **+2.4** → **9.9** | **+2.9** → **9.0+** | **+1.0** → **10.0** |

*Notas atuais: Maturidade 7.5 / Risco 6.0 (invertido: 10 = sem risco) / Potencial 9.0*
*Nota sobre "Risco": na auditoria, 10 = risco zero = sistema mais seguro*

---

## 9. PLANO DE EXECUCAO

### Sprint 1 — Correcoes Fiscais Criticas (Semana 1-2)
**Prioridade maxima. Executar antes de qualquer nova validacao de cliente.**

| Tarefa | Arquivo | Estimativa |
|---|---|---|
| Reescrever SN_003 | `simples_validator.py`, `rules.yaml` | 4h |
| Reformular SN_012 | `simples_validator.py`, `rules.yaml` | 2h |
| Implementar filtro de vigencia | `validation_service.py` | 3h |
| Desativar REF_COD_PART_D100 | `cross_block_validator.py`, `rules.yaml` | 1h |
| Corrigir contagem no README | `README.md` | 30min |
| Testes das correcoes | `test_simples_validator.py`, `test_cross_block.py` | 4h |

**Total Sprint 1: ~15h**

---

### Sprint 2 — Governanca de Correcoes (Semana 2-3)
**Impacto direto no risco. Executar antes de usar o sistema com clientes reais.**

| Tarefa | Arquivo | Estimativa |
|---|---|---|
| Adicionar campo `corrigivel` ao schema YAML | `rules.yaml` (186 entradas) | 3h |
| Script de validacao do schema | `src/rules.py --check` | 2h |
| Enforcar `corrigivel` em `correction_service.py` | `correction_service.py` | 4h |
| Criar tabela `finding_resolutions` | `database.py` | 2h |
| Endpoint `POST /api/findings/{id}/resolve` | `api/routers/findings.py` | 3h |
| Testes de governanca | `test_correction_service.py` | 3h |

**Total Sprint 2: ~17h**

---

### Sprint 3 — Frontend Analitico (Semana 3-4)

| Tarefa | Arquivo | Estimativa |
|---|---|---|
| Editor inline (botao + painel + API call) | `FileDetailPage.tsx` | 6h |
| Graficos Recharts (4 graficos) | `FileDetailPage.tsx` | 5h |
| Filtros e ordenacao tabela | `FileDetailPage.tsx` | 4h |
| Coluna materialidade financeira | `FileDetailPage.tsx` + `validation_service.py` | 5h |
| Badge "Requer contexto externo" | `FileDetailPage.tsx` | 2h |
| Painel de escopo (collapsible) | `FileDetailPage.tsx` | 2h |
| Botoes workflow (Aceitar/Rejeitar/Postergar) | `FileDetailPage.tsx` | 4h |

**Total Sprint 3: ~28h**

---

### Sprint 4 — Schema e Qualidade (Semana 4-5)

| Tarefa | Arquivo | Estimativa |
|---|---|---|
| Separar meta-regras no rules.yaml | `rules.yaml` | 2h |
| Adicionar campos obrigatorios ao schema (todos registros) | `rules.yaml`, `src/rules.py` | 4h |
| Documentar modelo de embedding | `config.py`, `README.md` | 1h |
| Testes de regressao completos | `pytest` | 2h |
| Atualizar PRD_REGRAS.md com estado final | `PRD_REGRAS.md` | 1h |

**Total Sprint 4: ~10h**

---

### Sprint 5 — Expansao de Potencial (Semana 6+, opcional)

| Tarefa | Estimativa |
|---|---|
| `data/cfop_validos.yaml` + validacao | 8h |
| `data/protocolos_st.yaml` (parcial, principais protocolos) | 12h |
| Endpoint upload EFD-Contribuicoes | 6h |
| UI: status EFD-Contribuicoes carregado | 2h |

**Total Sprint 5: ~28h**

---

## 10. CRITERIOS DE ACEITACAO GLOBAIS (NOTAS 9.0+)

Para considerar o sistema como 9.0+ em maturidade, risco e potencial, os seguintes criterios devem ser verificados:

### Maturidade (9.0+)
- [x] SN_003 e SN_012 com premissas fiscais corretas e testes cobrindo as correcoes
- [x] Vigencia de regras enforced no engine com teste de arquivo de periodo passado
- [x] Sem apontamentos duplicados (D_001 / REF_COD_PART_D100)
- [x] Todos os 186 registros do rules.yaml com campos obrigatorios preenchidos
- [x] Meta-regras separadas do catalogo de validacao
- [x] Contagem consistente em todos os arquivos de documentacao
- [x] Modelo de embedding documentado em config.py e README

### Risco (9.0+ = risco minimo)
- [x] `correction_service.py` bloqueia correcao automatica para regras `investigar` e `impossivel`
- [x] Correcoes de regras `proposta` exigem justificativa registrada no audit_log
- [x] Workflow de resolucao de apontamentos funcional (aceitar/rejeitar/postergar)
- [x] Metrica `conformidade%` renomeada e com painel de escopo
- [x] Badge "Requer validacao externa" em apontamentos com `depende_externo: true`
- [x] Vigencia enforced (arquivo de 2022 nao recebe regras de 2025)

### Potencial (9.5+)
- [x] Editor inline funcional
- [x] Graficos de distribuicao de erros implementados
- [x] Filtros e ordenacao na tabela de apontamentos
- [x] Materialidade financeira estimada por apontamento
- [x] Workflow de resolucao integrado ao relatorio exportado

---

## 11. RISCOS DO PROPRIO PRD

| Risco | Probabilidade | Mitigacao |
|---|---|---|
| SN_003 reescrita gera regressao em testes existentes | Media | Reescrever testes junto com a regra |
| Campo `corrigivel` em 186 entradas com valores incorretos | Alta | Revisao manual por bloco + `--check` automatico |
| Editor inline com comportamento inconsistente entre registros | Media | Testes de componente React antes de deploy |
| Materialidade financeira calculada incorretamente em casos extremos | Media | Exibir como "estimativa" no tooltip; nunca como valor definitivo |

---

## 12. DEFINICAO DE PRONTO (DoD)

Uma melhoria e considerada "Pronta" quando:
1. Implementacao concluida no modulo alvo
2. Testes unitarios (positivo e negativo) passando
3. `python -m src.rules --check` retorna 0 erros
4. Lint: 0 ruff, 0 mypy, 0 bandit
5. Sem regressao nos 1473 testes existentes
6. Documentacao no YAML (se for regra) ou no README (se for funcionalidade) atualizada
7. PRD_REGRAS.md atualizado com novo estado

---

*Estimativa total para atingir 9.0+ em todos os eixos: ~70h distribuidas em 4 sprints*
*Sprint 5 (expansao de potencial) e opcional e independente das notas 9.0*

---

## 13. INSTRUCOES DE EXECUCAO PARA CLAUDE CLI

Esta secao define as regras de comportamento para execucao autonoma via `claude` (Claude Code CLI). O objetivo e que o agente execute cada passo sem pedir confirmacao, validando o resultado antes de avancar.

### 13.1 Arquivo CLAUDE.md — Colocar na raiz do projeto

Criar o arquivo `CLAUDE.md` na raiz do repositorio com o seguinte conteudo. Esse arquivo e lido automaticamente pelo Claude Code a cada sessao e define o contrato de execucao do agente neste projeto.

```markdown
# CLAUDE.md — Contrato de Execucao Autonoma

## Identidade do Projeto
Sistema local de validacao SPED EFD ICMS/IPI para escritorio contabil.
Stack: Python 3.12 + FastAPI + SQLite + sentence-transformers + React 18 + TypeScript.
Raiz do projeto: detectar automaticamente via pyproject.toml.

## Regras de Execucao (NUNCA violar)

### 1. Nao pedir confirmacao para acoes seguras
As acoes abaixo sao consideradas seguras e devem ser executadas SEM perguntar:
- Ler qualquer arquivo do projeto (*.py, *.ts, *.yaml, *.md, *.json, *.toml)
- Rodar testes: `pytest`, `npm test`, `npm run build`
- Rodar linters: `ruff check`, `mypy`, `bandit`
- Rodar `python -m src.rules --check`
- Criar arquivos novos em `src/`, `api/`, `frontend/src/`, `data/`, `tests/`
- Editar arquivos existentes dentro do escopo da tarefa atual
- Instalar dependencias listadas no `pyproject.toml` ou `package.json`

### 2. Pedir confirmacao APENAS para acoes destrutivas
- Deletar arquivos (usar `git rm` e explicar o motivo antes)
- Alterar `rules.yaml` em mais de 10 entradas de uma vez
- Modificar `database.py` (schema do banco — requer migracao)
- Alterar endpoints de API que quebram contrato (mudanca de response shape)
- Qualquer acao fora do escopo da tarefa atual do PRD

### 3. Ordem de execucao por tarefa
Para cada tarefa do PRD, seguir sempre esta sequencia:
  1. Ler os arquivos relevantes antes de editar
  2. Implementar a mudanca
  3. Rodar os testes especificos da mudanca
  4. Rodar o suite completo de regressao
  5. Rodar lint
  6. Registrar resultado no LOG (secao 14 do PRD)
  7. Somente entao avancar para a proxima tarefa

### 4. Gate de testes obrigatorio entre tarefas
Nunca avancar para a proxima tarefa se:
- Qualquer teste novo falhar
- Qualquer teste existente que antes passava agora falhar (regressao)
- `ruff check` retornar erros
- `mypy` retornar erros de tipo
- `python -m src.rules --check` retornar inconsistencias

Se o gate falhar: parar, registrar no LOG, reportar ao usuario com o erro exato.
NAO tentar corrigir e avancar silenciosamente.

### 5. Mensagens de commit
Usar formato convencional:
  fix(simples): corrige premissa de uniformidade SN_012
  feat(correction): adiciona campo corrigivel ao schema de regras
  test(vigencia): adiciona testes de filtro por periodo de escrituracao
  refactor(rules): separa meta-regras da secao de validacao

### 6. Variaveis de ambiente necessarias
  export PYTHONPATH=$(pwd)
  export API_KEY="dev-key-local-nao-usar-em-producao"
Definir antes de rodar qualquer comando Python.

### 7. Comandos de teste por modulo
  # Suite completa
  pytest --tb=short -q

  # Por modulo especifico
  pytest tests/test_simples_validator.py -v
  pytest tests/test_correction_service.py -v
  pytest tests/test_cross_block_validator.py -v
  pytest tests/test_validation_service.py -v
  pytest tests/test_e2e.py -v

  # Lint
  ruff check src/ api/ --fix
  mypy src/ api/ --ignore-missing-imports
  bandit -r src/ api/ -ll

  # Regras
  python -m src.rules --check
  python -m src.rules --pending

  # Frontend
  cd frontend && npm run build && npm run lint

### 8. Como reportar progresso
Ao final de cada tarefa concluida, imprimir:
  [OK]  TAREFA: <nome>
  [OK]  TESTES: <N passou> / <N total> | cobertura: <X>%
  [OK]  LINT: 0 erros
  [OK]  REGRAS: <N implementadas> / 186
  [NEXT] Proxima tarefa: <nome>

Se falhar:
  [FAIL] TAREFA: <nome>
  [FAIL] MOTIVO: <mensagem de erro exata>
  [FAIL] ARQUIVO: <arquivo>:<linha>
  [STOP] Aguardando instrucao do usuario.
```

---

### 13.2 Gates de Teste por Sprint

Cada sprint tem um gate de testes que deve passar antes de iniciar o sprint seguinte.

#### Gate Sprint 1 — Correcoes Fiscais

```bash
# Executar apos concluir todos os itens do Sprint 1

echo "=== GATE SPRINT 1 ==="

# 1. Testes especificos das correcoes
pytest tests/test_simples_validator.py -v --tb=short
pytest tests/test_cross_block_validator.py -v --tb=short

# 2. Casos criticos do SN_003 reescrito
pytest tests/test_simples_validator.py::test_sn003_aliq_dentro_range_nao_dispara -v
pytest tests/test_simples_validator.py::test_sn003_aliq_zero_com_bc_dispara -v
pytest tests/test_simples_validator.py::test_sn003_acima_395_dispara -v
pytest tests/test_simples_validator.py::test_sn003_abaixo_395_nao_dispara -v

# 3. SN_012
pytest tests/test_simples_validator.py::test_sn012_delta_pequeno_nao_dispara -v
pytest tests/test_simples_validator.py::test_sn012_delta_grande_gera_info -v

# 4. Vigencia
pytest tests/test_validation_service.py::test_regra_futura_nao_aplicada_a_arquivo_antigo -v
pytest tests/test_validation_service.py::test_regra_expirada_nao_aplicada -v

# 5. Sem duplicata D_001
pytest tests/test_cross_block_validator.py::test_sem_duplicata_cod_part_d100 -v

# 6. Regressao completa — ZERO quebras permitidas
pytest --tb=short -q

echo "=== RESULTADO GATE SPRINT 1 ==="
# Se qualquer teste falhar: STOP — nao iniciar Sprint 2
```

**Condicao de avanco:** 0 falhas. Qualquer falha bloqueia Sprint 2.

---

#### Gate Sprint 2 — Governanca de Correcoes

```bash
echo "=== GATE SPRINT 2 ==="

# 1. Corrigivel enforced
pytest tests/test_correction_service.py::test_bloqueia_correcao_investigar -v
pytest tests/test_correction_service.py::test_bloqueia_correcao_impossivel -v
pytest tests/test_correction_service.py::test_exige_justificativa_para_proposta -v
pytest tests/test_correction_service.py::test_permite_correcao_automatico_sem_justificativa -v
pytest tests/test_correction_service.py::test_audit_log_registra_autor_e_justificativa -v

# 2. Workflow de resolucao
pytest tests/test_finding_resolutions.py -v

# 3. Schema rules.yaml — todos os 186 registros com corrigivel preenchido
python -m src.rules --check
# Deve retornar: "186/186 regras validas. 0 erros de schema."

# 4. Regressao completa
pytest --tb=short -q

# 5. Lint
ruff check src/ api/ --statistics
mypy src/ api/ --ignore-missing-imports

echo "=== RESULTADO GATE SPRINT 2 ==="
```

**Condicao de avanco:** 0 falhas, 0 erros de lint, `--check` retorna 0 erros.

---

#### Gate Sprint 3 — Frontend Analitico

```bash
echo "=== GATE SPRINT 3 ==="

# 1. Build sem erros TypeScript
cd frontend && npm run build
# Deve retornar: 0 errors TypeScript

# 2. Lint frontend
npm run lint
# Deve retornar: 0 warnings, 0 errors

# 3. Testes de componente (se implementados)
npm test -- --watchAll=false

# 4. API — endpoints novos respondem corretamente
pytest tests/test_api_findings.py -v

# 5. Regressao Python
cd .. && pytest --tb=short -q

echo "=== RESULTADO GATE SPRINT 3 ==="
```

**Condicao de avanco:** Build TypeScript sem erros, lint clean, regressao Python zerada.

---

#### Gate Sprint 4 — Schema e Qualidade Final

```bash
echo "=== GATE SPRINT 4 — GATE FINAL ==="

# 1. Meta-regras separadas — pipeline nao gera apontamentos para GOV/AMOSTRA
pytest tests/test_validation_service.py::test_meta_regras_nao_geram_findings -v

# 2. Schema completo
python -m src.rules --check
# Esperado: "186/186 validas. 0 erros. 181 regras de validacao + 5 meta-comportamentos."

# 3. Embedding documentado
python -c "from config import EMBEDDING_MODEL; assert EMBEDDING_MODEL, 'EMBEDDING_MODEL nao definido'"

# 4. Suite completa — meta final: >= 1480 testes (novos adicionados nos sprints)
pytest --tb=short -q --co -q | tail -5
pytest --tb=short -q

# 5. Cobertura — manter >= 97%
pytest --cov=src --cov=api --cov-report=term-missing --cov-fail-under=97

# 6. Lint final — zero tolerancia
ruff check src/ api/ --statistics
mypy src/ api/ --ignore-missing-imports
bandit -r src/ api/ -ll

# 7. Build frontend final
cd frontend && npm run build

echo ""
echo "=== RESULTADO FINAL ==="
echo "Se todos os gates passaram: sistema pronto para uso profissional (nota >= 9.0)"
```

**Condicao de conclusao:** Todos os comandos retornam 0. Cobertura >= 97%. Build TypeScript limpo.

---

### 13.3 Sequencia de Execucao Autonoma Completa

Para executar todo o PRD de uma vez via Claude CLI, usar o prompt abaixo como ponto de entrada:

```
Execute o PRD_EVOLUCAO_v4.md completo seguindo as instrucoes do CLAUDE.md.

Regras obrigatorias:
1. Execute cada tarefa do Sprint sem pedir confirmacao
2. Rode o gate de testes apos cada sprint antes de prosseguir
3. Se qualquer gate falhar: pare imediatamente, registre no LOG (secao 14) e reporte
4. Ao final de cada tarefa, imprima o status [OK] ou [FAIL] conforme o CLAUDE.md
5. Ao final de cada sprint, imprima o resultado do gate completo
6. Ao terminar todos os sprints, imprima o resumo final do LOG

Ordem: Sprint 1 → Gate 1 → Sprint 2 → Gate 2 → Sprint 3 → Gate 3 → Sprint 4 → Gate Final
```

---

## 14. LOG DE EXECUCAO

Esta secao e preenchida pelo agente durante a execucao. Nao editar manualmente.
Formato: o agente adiciona entradas conforme executa cada tarefa e gate.

---

### LOG — Sprint 1: Correcoes Fiscais

```
[    ] 3.1  SN_003 reescrita
            arquivo: src/validators/simples_validator.py
            status:  pendente
            testes:  pendente
            erro:    -

[    ] 3.2  SN_012 reformulacao
            arquivo: src/validators/simples_validator.py
            status:  pendente
            testes:  pendente
            erro:    -

[    ] 3.3  Filtro de vigencia no engine
            arquivo: src/services/validation_service.py
            status:  pendente
            testes:  pendente
            erro:    -

[    ] 3.4  Desativar REF_COD_PART_D100
            arquivo: src/validators/cross_block_validator.py, rules.yaml
            status:  pendente
            testes:  pendente
            erro:    -

[    ] 3.5  Correcao inconsistencia README
            arquivo: README.md
            status:  pendente
            testes:  n/a
            erro:    -

--- GATE SPRINT 1 ---
[    ] pytest tests/test_simples_validator.py       resultado: pendente
[    ] pytest tests/test_cross_block_validator.py   resultado: pendente
[    ] pytest (regressao completa)                  resultado: pendente  falhas: -
[    ] ruff check                                   resultado: pendente  erros: -
[    ] mypy                                         resultado: pendente  erros: -
[    ] python -m src.rules --check                  resultado: pendente  erros: -

AVANCO PARA SPRINT 2: [ ] liberado  [ ] bloqueado
MOTIVO BLOQUEIO: -
```

---

### LOG — Sprint 2: Governanca de Correcoes

```
[    ] 4.1  Campo corrigivel no schema (186 entradas)
            arquivo: rules.yaml, src/rules.py
            status:  pendente
            testes:  pendente
            erro:    -

[    ] 4.1b Enforcar corrigivel em correction_service.py
            arquivo: src/services/correction_service.py
            status:  pendente
            testes:  pendente
            erro:    -

[    ] 4.2  Tabela finding_resolutions
            arquivo: src/services/database.py
            status:  pendente
            testes:  pendente
            erro:    -

[    ] 4.2b Endpoint POST /api/findings/{id}/resolve
            arquivo: api/routers/findings.py
            status:  pendente
            testes:  pendente
            erro:    -

[    ] 4.3  Transparencia de escopo no frontend
            arquivo: frontend/src/pages/FileDetailPage.tsx
            status:  pendente
            testes:  pendente
            erro:    -

[    ] 4.4  Badge vigencia no frontend
            arquivo: frontend/src/pages/FileDetailPage.tsx
            status:  pendente
            testes:  pendente
            erro:    -

--- GATE SPRINT 2 ---
[    ] pytest tests/test_correction_service.py      resultado: pendente  falhas: -
[    ] pytest tests/test_finding_resolutions.py     resultado: pendente  falhas: -
[    ] pytest (regressao completa)                  resultado: pendente  falhas: -
[    ] ruff check                                   resultado: pendente  erros: -
[    ] mypy                                         resultado: pendente  erros: -
[    ] python -m src.rules --check                  resultado: pendente  erros: -

AVANCO PARA SPRINT 3: [ ] liberado  [ ] bloqueado
MOTIVO BLOQUEIO: -
```

---

### LOG — Sprint 3: Frontend Analitico

```
[    ] 6.1  Editor inline
            arquivo: frontend/src/pages/FileDetailPage.tsx
            status:  pendente
            testes:  pendente
            erro:    -

[    ] 6.2  Graficos Recharts (4 graficos)
            arquivo: frontend/src/pages/FileDetailPage.tsx
            status:  pendente
            testes:  pendente
            erro:    -

[    ] 6.3  Filtros e ordenacao na tabela
            arquivo: frontend/src/pages/FileDetailPage.tsx
            status:  pendente
            testes:  pendente
            erro:    -

[    ] 6.4  Materialidade financeira
            arquivo: frontend/src/pages/FileDetailPage.tsx
                     src/services/validation_service.py
            status:  pendente
            testes:  pendente
            erro:    -

[    ] 6.4b Botoes workflow (Aceitar/Rejeitar/Postergar)
            arquivo: frontend/src/pages/FileDetailPage.tsx
            status:  pendente
            testes:  pendente
            erro:    -

--- GATE SPRINT 3 ---
[    ] npm run build (frontend)                     resultado: pendente  erros TS: -
[    ] npm run lint                                 resultado: pendente  erros: -
[    ] pytest tests/test_api_findings.py            resultado: pendente  falhas: -
[    ] pytest (regressao completa)                  resultado: pendente  falhas: -

AVANCO PARA SPRINT 4: [ ] liberado  [ ] bloqueado
MOTIVO BLOQUEIO: -
```

---

### LOG — Sprint 4: Schema e Qualidade Final

```
[    ] 5.2  Meta-regras separadas no rules.yaml
            arquivo: rules.yaml
            status:  pendente
            testes:  pendente
            erro:    -

[    ] 5.1  Campos obrigatorios schema (todos os registros)
            arquivo: rules.yaml, src/rules.py
            status:  pendente
            testes:  pendente
            erro:    -

[    ] 6.5  Documentar modelo de embedding
            arquivo: config.py, README.md
            status:  pendente
            testes:  n/a
            erro:    -

--- GATE FINAL ---
[    ] pytest (suite completa)                      resultado: pendente
            total testes:  -  |  passou: -  |  falhou: -
[    ] cobertura >= 97%                             resultado: pendente  cobertura: -%
[    ] ruff check                                   resultado: pendente  erros: -
[    ] mypy                                         resultado: pendente  erros: -
[    ] bandit                                       resultado: pendente  alertas: -
[    ] python -m src.rules --check                  resultado: pendente  erros: -
[    ] npm run build                                resultado: pendente  erros TS: -
[    ] npm run lint                                 resultado: pendente  erros: -

CONCLUSAO: [ ] aprovado  [ ] reprovado
```

---

### LOG — Erros Registrados

Tabela de todos os erros encontrados durante a execucao. Preenchida pelo agente.

| # | Sprint | Tarefa | Arquivo | Linha | Tipo | Mensagem | Status |
|---|---|---|---|---|---|---|---|
| — | — | — | — | — | — | Nenhum erro registrado ate o momento | — |

---

### LOG — Erros Previsiveis e Como Tratar

Esta subsecao documenta erros que provavelmente ocorrerao e como o agente deve proceder.

| Erro Previsto | Causa Provavel | Como Tratar |
|---|---|---|
| `AssertionError` em `test_sn003_*` | Testes existentes assumem o threshold antigo de 4.01% | Reescrever os testes junto com a regra — os testes antigos estao errados, nao a implementacao nova |
| `KeyError: 'corrigivel'` em `src/rules.py --check` | Registros do YAML ainda sem o campo novo | Rodar o script de migracao `migrate_rules_schema.py` antes de rodar `--check` |
| `sqlite3.OperationalError: no such table: finding_resolutions` | Migracao de schema nao rodou | Rodar `python -m src.services.database --migrate` antes dos testes de resolucao |
| `TypeError` em `correction_service.apply_correction` | Assinatura da funcao mudou (novo param `justificativa`) | Atualizar todos os call sites: testes, endpoints, e2e |
| `TS2305: Module has no exported member` no frontend | Novo tipo `FindingResolution` nao exportado de `types/sped.ts` | Adicionar o tipo em `types/sped.ts` antes de usar nos componentes |
| `FAIL test_e2e.py::test_full_flow_error_file` | Endpoint de correcao agora exige `justificativa` | Atualizar o teste E2E para incluir o campo `justificativa` no payload |
| `ruff E501` (linha muito longa) em `rules.yaml` mensagens | `mensagem_padrao` e `acao_recomendada` sao strings longas | Usar bloco `>` no YAML para strings multilinhas |
| `mypy error: Argument 1 to "filter_rules_by_period"` | Tipo de `vigencia_de` no dataclass pode ser `str` em vez de `date` | Garantir que o parser do YAML converte `vigencia_de` para `datetime.date` ao carregar |
| `ImportError: cannot import name 'FindingStatus'` | Enum novo nao adicionado a `src/models.py` | Adicionar `FindingStatus` ao `models.py` antes de importar em outros modulos |
| `npm ERR! peer recharts` | Recharts nao instalado no frontend | Rodar `cd frontend && npm install recharts` antes de usar os componentes de grafico |

---

### LOG — Resumo Final

```
Data conclusao:      ___________
Sprints concluidos:  [ ] 1  [ ] 2  [ ] 3  [ ] 4
Sprint 5 (opcional): [ ] executado  [ ] pulado

Testes finais:
  Total:      ____
  Passou:     ____
  Falhou:     ____
  Cobertura:  ____%

Lint:
  ruff:    ____ erros
  mypy:    ____ erros
  bandit:  ____ alertas

Regras:
  Total rules.yaml:       186
  Validacao (real):       ____
  Meta-comportamento:     ____
  --check erros:          ____

Notas estimadas pos-execucao:
  Maturidade:  _____ / 10
  Risco:       _____ / 10
  Potencial:   _____ / 10

Observacoes finais do agente:
  ___________________________________________________________
  ___________________________________________________________
```
