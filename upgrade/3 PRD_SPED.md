# PRD MESTRE — VALIDADOR SPED EFD ICMS/IPI
## Versão consolidada e robusta do produto
### Foco exclusivo: validação de erros de ICMS e IPI no SPED EFD ICMS/IPI e no cruzamento SPED × XML

**Versão:** v5.0.0  
**Data:** 11/04/2026  
**Status:** Base consolidada para desenvolvimento  
**Escopo:** ICMS + IPI apenas  
**Fora de escopo:** EFD Contribuições, PIS, COFINS, DCTFWeb e módulos federais paralelos

---

# 1. Resumo executivo

Este documento consolida os pontos fortes dos três documentos anteriores e incorpora as melhorias necessárias para fechar o sistema de forma mais segura, técnica e aderente à legislação aplicável ao **SPED EFD ICMS/IPI**, com foco em **ICMS** e **IPI**.

A nova proposta parte de quatro premissas obrigatórias:

1. **Contexto antes da validação**  
   Nenhuma regra fiscal relevante poderá ser executada sem que o sistema conheça previamente o contexto do contribuinte: regime tributário, UF, período, produtos, participantes, benefícios fiscais, tabelas vigentes e parâmetros essenciais.

2. **Dois caminhos explícitos de validação**  
   O produto deve operar com dois fluxos claros no frontend:
   - **Validação SPED**
   - **Validação SPED × XML**

3. **Validação fiscal orientada à realidade operacional**  
   O sistema não deve ser apenas um validador sintático. Ele deve detectar inconsistências de estrutura, classificação, cálculo, consolidação, apuração e reflexo fiscal, com comportamento aderente às rotinas reais de escrituração e fiscalização.

4. **Foco em erro objetivo, risco fiscal e ação corretiva**  
   O sistema deve diferenciar:
   - erro estrutural;
   - erro fiscal objetivo;
   - hipótese provável;
   - limitação de cobertura;
   - risco de parametrização sistêmica.

Este PRD elimina do escopo qualquer dependência de **EFD Contribuições** e concentra o produto em sua vocação principal: **auditoria e validação robusta do ICMS/IPI**.

---

# 2. Objetivo do produto

## 2.1 Objetivo principal

Transformar o sistema em uma plataforma de auditoria fiscal automatizada para **SPED EFD ICMS/IPI**, com capacidade de:

- validar o arquivo SPED com profundidade técnica;
- cruzar SPED e XML de NF-e de forma robusta;
- aplicar regras com base em regime tributário, contexto fiscal e benefício ativo;
- recalcular tributos e apontar divergências;
- fechar a cadeia entre documento, item, consolidação e apuração;
- produzir relatórios confiáveis, rastreáveis e defensáveis.

## 2.2 Objetivos específicos

- tornar obrigatória a montagem do contexto fiscal antes da auditoria;
- corrigir bugs conceituais de regime tributário;
- endurecer a validação de ICMS-ST com MVA;
- tornar o cruzamento XML realmente reconciliatório, e não apenas comparativo de totais;
- melhorar o fechamento do SPED nas trilhas C100 → C170 → C190 → E110 → E111 → E116;
- reforçar a validação de IPI em itens, bases e reflexos;
- elevar a qualidade do frontend para guiar o analista ao caminho correto;
- reduzir falso positivo, falso negativo e cobertura ilusória.

---

# 3. Escopo e não escopo

## 3.1 Dentro do escopo

Este PRD cobre:

- SPED EFD ICMS/IPI;
- blocos 0, C, D, E, H, K, 9;
- validações de ICMS próprio;
- validações de ICMS-ST;
- validações de DIFAL/FCP quando aplicável ao ICMS;
- validações de IPI;
- cruzamento SPED × XML;
- contexto fiscal por regime;
- contexto fiscal por benefício;
- regras por vigência;
- score de cobertura;
- trilha de auditoria;
- governança de correções.

## 3.2 Fora do escopo

Ficam expressamente fora desta versão:

- EFD Contribuições;
- validações de PIS/COFINS;
- DCTFWeb;
- eSocial;
- REINF;
- apurações federais fora de IPI;
- integrações externas com portais SEFAZ em tempo real;
- workflows de transmissão.

---

# 4. Diagnóstico consolidado do estado atual

A partir da análise dos materiais anteriores, os maiores pontos fracos do sistema atual podem ser agrupados em oito eixos.

## 4.1 Falta de contexto fiscal obrigatório antes da validação
O problema de raiz mais importante é o início da auditoria sem contexto completo do contribuinte. Isso gera:
- leitura equivocada do regime;
- benefício fiscal não considerado;
- CST/CSOSN avaliados fora do contexto;
- XML cruzado de forma genérica;
- divergências falsas.

## 4.2 Detecção de regime tributário insuficiente ou incorreta
O sistema não pode tratar `IND_PERFIL` como regime tributário.  
`IND_PERFIL` é nível de escrituração, não regime fiscal.  
A detecção precisa considerar evidências como:
- CST/CSOSN encontrados;
- dados mestres do contribuinte;
- confirmação externa cadastral quando disponível.

## 4.3 Cruzamento XML superficial
O cruzamento XML atual já existe, mas precisa sair do nível "totais e alguns campos" para o nível:
- documento;
- participante;
- item;
- tributo;
- reflexo fiscal;
- situação do documento;
- aderência ao benefício fiscal;
- aderência ao regime tributário.

## 4.4 Fechamento insuficiente da cadeia de apuração
O produto ainda precisa endurecer o fechamento:
- C100 x C170;
- C170 x C190;
- C190 x E110;
- E110 x E111;
- E111 x E116.

Sem isso, o sistema audita bem a escrituração, mas ainda não fecha com o rigor necessário a lógica completa da apuração.

## 4.5 ICMS-ST com MVA ainda não suficientemente robusto
A auditoria de ST precisa considerar:
- NCM;
- UF;
- MVA;
- alíquota interna;
- alíquota interestadual;
- regime do remetente;
- fórmula completa da BC-ST;
- casos com ausência de tabela;
- segregação entre erro fiscal e lacuna cadastral.

## 4.6 NF cancelada, denegada ou irregular ainda não tratada no nível ideal
É indispensável vincular a situação documental do XML ao `COD_SIT` do C100 e bloquear a falsa aparência de regularidade quando houver:
- NF cancelada escriturada como ativa;
- NF denegada escriturada;
- situação documental incompatível.

## 4.7 Governança técnica e operacional ainda desigual
Há riscos operacionais que afetam a confiabilidade do produto:
- transação insuficiente na troca de erros;
- ambiente de produção com configuração inadequada;
- segurança relaxada em modo dev;
- cache de IA sem chave suficientemente discriminante;
- cobertura XML reportada de forma binária.

## 4.8 Cobertura de auditoria ainda pouco transparente
O sistema precisa informar claramente:
- o que foi validado;
- o que não foi validado;
- por falta de qual tabela;
- por falta de XML;
- por ausência de contexto;
- por restrição de escopo.

---

# 5. Princípios obrigatórios da arquitetura

## 5.1 Context-First obrigatório
Nenhuma validação fiscal pode rodar sem contexto completo.

## 5.2 Dual-Path obrigatório
O sistema precisa oferecer dois modos de auditoria, não um fluxo híbrido confuso.

## 5.3 Erro fiscal ≠ hipótese ≠ limitação
Cada apontamento deve ser classificado corretamente.

## 5.4 Tabelas de referência fazem parte da auditoria
Sem tabela de alíquota, MVA, ajuste ou benefício, não existe cobertura plena.

## 5.5 Toda divergência deve ser explicável
O sistema deve mostrar:
- campo;
- registro;
- valor encontrado;
- valor esperado;
- regra acionada;
- base legal;
- orientação de correção.

## 5.6 Campos sensíveis não podem ser autocorrigidos
Não pode haver autocorreção em:
- CST;
- CSOSN;
- CFOP;
- chaves;
- datas fiscais;
- bases nucleares;
- alíquotas nucleares;
- valores principais de documento.

---

# 6. Base legal oficial da solução

A versão consolidada deste PRD deve ser implementada à luz dos seguintes fundamentos normativos:

## 6.1 EFD ICMS/IPI
- **Ajuste SINIEF 02/2009** — institui a Escrituração Fiscal Digital.  
- **Guia Prático da EFD ICMS/IPI** — versão vigente em 2026.  
- **Portal SPED / Receita Federal** — manual e publicações vigentes.

## 6.2 ICMS
- **Lei Complementar nº 87/1996 (Lei Kandir)**  
- **Emenda Constitucional nº 87/2015**  
- **Lei Complementar nº 190/2022**

## 6.3 IPI
- **TIPI vigente**, aprovada pelo **Decreto nº 11.158/2022** e alterações posteriores.  
- Regras de classificação fiscal conforme a própria TIPI e sua estrutura normativa.

## 6.4 Regras infralegais e manuais técnicos
- tabelas oficiais da EFD;
- atos e manuais divulgados no ambiente SPED;
- codificações do leiaute;
- regras de registros, campos, obrigatoriedades e domínios.

> Observação importante: a implementação do motor deve tratar a base legal como **fonte de governança de regra**, e não apenas como material de consulta textual.

---

# 7. Visão consolidada do produto

O sistema passará a operar com dois caminhos explícitos, ambos iniciando pela montagem do contexto.

## 7.1 Caminho A — Validação SPED
Auditoria do arquivo SPED sem confronto com documentos XML.

### O que cobre
- integridade estrutural;
- formatos;
- obrigatoriedades;
- consistência entre registros;
- recálculos;
- semântica fiscal;
- regime;
- benefício;
- apuração;
- blocos de controle.

## 7.2 Caminho B — Validação SPED × XML
Auditoria reconciliatória entre o SPED e os XMLs vinculados.

### O que cobre
- tudo do Caminho A;
- presença documental;
- situação documental;
- equivalência de cabeçalho;
- equivalência de participante;
- equivalência item a item;
- equivalência tributária;
- divergência de classificação;
- divergência de reflexo fiscal.

---

# 8. Frontend consolidado

## 8.1 Tela inicial obrigatória
A entrada do módulo deve apresentar dois cards de escolha:

### Card 1 — Validação SPED
Texto de apoio:
“Validação completa da escrituração EFD ICMS/IPI com base em regras fiscais, cruzamentos internos, benefícios fiscais, regime tributário e coerência da apuração.”

### Card 2 — Validação SPED × XML
Texto de apoio:
“Validação reconciliatória entre SPED e XMLs da NF-e, com confronto de documentos, itens, tributos, classificação fiscal, benefícios e situação documental.”

## 8.2 Comportamento esperado
- ao escolher **Validação SPED**, o frontend exibe um dropzone para SPED;
- ao escolher **Validação SPED × XML**, o frontend exibe dois dropzones: SPED e XML;
- o usuário deve visualizar o contexto detectado antes de executar;
- o sistema deve mostrar cobertura, limitações e estágio do pipeline.

## 8.3 Painel de contexto fiscal
Deve exibir no mínimo:
- CNPJ;
- razão social;
- período;
- UF;
- perfil;
- regime detectado;
- fonte do regime;
- benefícios ativos;
- tabelas carregadas;
- tabelas ausentes;
- status da cobertura.

## 8.4 Painel de progresso
O progresso deve ser detalhado por estágio:
- montagem de contexto;
- parsing;
- validação estrutural;
- cruzamentos SPED;
- parsing XML;
- cruzamento SPED × XML;
- enriquecimento;
- conclusão.

---

# 9. Stage 0 obrigatório — Montagem de contexto

## 9.1 Regra central
Se o contexto estiver incompleto em ponto crítico, a validação deve ser:
- bloqueada; ou
- executada com limitação formalmente registrada, quando a falta não impedir o restante da auditoria.

## 9.2 Fontes de contexto
O sistema deve carregar, em ordem lógica:

1. Registro 0000  
2. Registros 0150  
3. Registros 0200  
4. Registros 0400  
5. Regras vigentes por período  
6. Tabelas de alíquota por UF  
7. Tabelas de FCP por UF  
8. Tabelas de MVA por NCM/UF  
9. Tabelas de códigos de ajuste  
10. Tabelas de benefício fiscal  
11. Dados mestres do cliente  
12. XML schema e field map, quando for modo SPED × XML

## 9.3 Dados mínimos do ValidationContext
O `ValidationContext` consolidado deve conter:
- identificação do contribuinte;
- período;
- perfil;
- atividade;
- regime detectado;
- fonte do regime;
- participantes;
- produtos;
- naturezas;
- alíquotas internas;
- FCP;
- MVA;
- benefícios ativos;
- restrições de benefício;
- regras ativas;
- tabelas ausentes;
- cobertura XML, quando aplicável.

---

# 10. Regime tributário — regra consolidada

## 10.1 Correção conceitual obrigatória
`IND_PERFIL` não poderá ser utilizado como critério de regime tributário.

## 10.2 Evidências válidas de regime
A detecção deverá seguir esta lógica:

### Simples Nacional
- presença de CSOSN;
- presença de CSTs compatíveis da Tabela B, quando aplicável ao tratamento interno do sistema;
- confirmação cadastral externa ou mestre.

### Regime normal
- ausência de CSOSN;
- presença de CSTs do regime normal;
- confirmação cadastral externa ou mestre.

### Conflito de regime
Se as evidências divergirem:
- marcar `regime_source = CONFLITO`;
- gerar alerta de contexto;
- não silenciar validações críticas.

## 10.3 Critérios de aceite
- o detector não pode usar `IND_PERFIL` como regime;
- o relatório deve informar a fonte do regime;
- conflitos devem aparecer na cobertura/contexto.

---

# 11. BeneficioEngine consolidado

## 11.1 Função
O `BeneficioEngine` será o módulo responsável por responder, no contexto do contribuinte:

- quais benefícios estão ativos no período;
- quais CSTs são compatíveis;
- quais CFOPs podem receber o tratamento;
- qual alíquota esperada;
- quais NCMs entram ou não no escopo;
- quais restrições, incompatibilidades e vigências devem ser observadas.

## 11.2 Comportamentos obrigatórios
O engine deve:
- suportar múltiplos benefícios no mesmo período;
- resolver conflitos;
- validar vigência;
- validar CNAE elegível quando a regra exigir;
- validar se o benefício pressupõe débito integral, crédito presumido, diferimento ou outra lógica;
- fornecer ao motor tributário a alíquota efetiva esperada.

## 11.3 Regras mínimas a reforçar
- benefício ativo sem reflexo em E111;
- benefício ativo com CST incompatível;
- benefício ativo com alíquota incompatível;
- benefício ativo fora do período;
- benefício com sobreposição indevida;
- devolução sem reversão adequada de benefício;
- benefício sem segregação por destinatário, quando exigido;
- benefício sem trilha documental mínima.

---

# 12. Requisitos de banco e persistência

## 12.1 Estruturas obrigatórias
O banco deve conter ou passar a conter:

### `clientes`
Cadastro mestre do contribuinte.

### `beneficios_ativos`
Benefícios ativos por cliente e vigência.

### `emitentes_crt`
Cadastro incremental do CRT de emitentes identificados pelos XMLs.

### `validation_runs`
Execução consolidada da validação.

### `fiscal_context_snapshots`
Snapshot do contexto usado na execução.

### `field_equivalence_catalog`
Catálogo formal de equivalência entre XML e SPED.

### `coverage_gaps`
Lacunas de cobertura por execução.

## 12.2 Requisitos de rastreabilidade
Cada execução deve registrar:
- modo escolhido;
- contexto usado;
- hash do contexto;
- regras executadas;
- regras puladas;
- lacunas;
- score de cobertura;
- score de risco;
- tempo de execução.

---

# 13. Pipeline consolidado

## 13.1 Pipeline do modo Validação SPED

### Estágio 0 — Montagem de contexto
Obrigatório.

### Estágio 1 — Parsing e persistência
- encoding;
- parsing;
- metadados;
- vínculo de versão;
- hash.

### Estágio 2 — Validação estrutural
- campos obrigatórios;
- tipo;
- tamanho;
- domínio;
- formato;
- datas;
- chaves.

### Estágio 3 — Cruzamentos internos e recálculo
- C100 x C170;
- C170 x C190;
- C190 x E110;
- E110 x E111;
- E111 x E116;
- recálculo de ICMS;
- recálculo de ICMS-ST;
- recálculo de IPI;
- semântica fiscal;
- regra por benefício;
- regra por regime.

### Estágio 4 — Enriquecimento e classificação
- mensagens amigáveis;
- base legal;
- orientação de correção;
- auto-corrigibilidade;
- deduplicação;
- score de risco;
- score de cobertura.

## 13.2 Pipeline do modo Validação SPED × XML

### Estágio 0 a 4
Iguais ao modo SPED.

### Estágio 5 — Parsing e indexação de XMLs
- upload em lote;
- paralelismo;
- extração de chave;
- extração de CRT;
- identificação de emitente;
- marcação de período;
- persistência estruturada.

### Estágio 6 — Cruzamento campo a campo
- documento;
- participante;
- item;
- tributo;
- situação documental;
- benefício;
- regime;
- reflexo fiscal.

### Estágio 7 — Enriquecimento consolidado
- cobertura XML;
- notas pareadas;
- notas não pareadas;
- divergências críticas;
- divergências moderadas;
- impacto fiscal;
- score final.

---

# 14. Validações estruturais obrigatórias

O sistema deve manter e reforçar:

- CNPJ;
- CPF;
- IE quando aplicável;
- datas válidas;
- datas dentro do período;
- chave NF-e;
- CFOP;
- NCM;
- município;
- formatos dos campos de IPI;
- tipos numéricos;
- domínios permitidos;
- registros obrigatórios;
- contagens do Bloco 9.

---

# 15. Validações tributárias obrigatórias — ICMS

## 15.1 Recálculo do ICMS próprio
Para cada item tributado, validar:
- base de cálculo;
- alíquota;
- valor do ICMS;
- tolerância por faixa de valor.

## 15.2 Tolerância proporcional
A tolerância deve deixar de ser global fixa e passar a ser por faixa de magnitude do item.

## 15.3 Semântica de CST
Reforçar:
- CST tributado com alíquota zero;
- CST isento com base ou ICMS;
- CST incompatível com CFOP;
- CST incompatível com regime;
- CST incompatível com benefício ativo.

## 15.4 Alíquotas por operação
Reforçar:
- alíquota interestadual inválida;
- alíquota interna usada em interestadual;
- alíquota interestadual usada em interna;
- alíquota média indevida;
- alíquota divergente da tabela da UF de destino quando aplicável.

## 15.5 DIFAL/FCP
Manter no escopo do ICMS:
- DIFAL faltante;
- DIFAL indevido;
- alíquota interna incorreta;
- FCP ausente;
- base inconsistente.

---

# 16. Validações tributárias obrigatórias — ICMS-ST

## 16.1 Regra-mãe
A validação de ST deve considerar a fórmula completa.

## 16.2 Fórmula obrigatória
A BC-ST deve considerar:
- valor da operação;
- frete;
- seguro;
- despesas acessórias;
- desconto;
- MVA;
- ajuste quando aplicável;
- ICMS próprio.

## 16.3 Tabela de referência
Deve usar:
- NCM;
- UF;
- MVA vigente.

## 16.4 Error types mínimos
- `ST_MVA_AUSENTE`
- `ST_MVA_DIVERGENTE`
- `ST_MVA_NAO_MAPEADO`
- `ST_ALIQ_INCORRETA`
- `ST_REGIME_REMETENTE`

## 16.5 Comportamento em ausência de MVA
Se a tabela não existir:
- registrar cobertura parcial;
- não mascarar o ponto;
- não fingir auditoria completa.

---

# 17. Validações tributárias obrigatórias — IPI

## 17.1 Escopo do IPI
O sistema deve validar, no mínimo:
- CST do IPI;
- base do IPI;
- alíquota do IPI;
- valor do IPI;
- coerência entre CST e incidência;
- reflexo do IPI na formação da base do ICMS quando aplicável.

## 17.2 Regras mínimas
- IPI tributado com alíquota zero indevida;
- base de IPI incompatível;
- valor do IPI divergente;
- CST IPI incompatível com operação;
- destaque de IPI no XML divergente da escrituração;
- ausência de reflexo do IPI no comportamento esperado do ICMS, quando a regra fiscal assim exigir.

## 17.3 Base de classificação
As validações de produto e incidência devem respeitar:
- NCM do item;
- TIPI vigente;
- natureza da operação;
- tipo do emitente e da operação.

---

# 18. Fechamento da cadeia de apuração

## 18.1 Documento → Item
Regras:
- soma de itens vs total do documento;
- tributos do item vs totais do cabeçalho;
- divergência de quantidade e valor;
- documento sem item correspondente.

## 18.2 Item → Consolidação
Regras:
- agrupamento por CST/CFOP/alíquota;
- totalização coerente;
- ausência de combinação no C190;
- combinação consolidada sem lastro item a item.

## 18.3 Consolidação → Apuração
Regras:
- débitos esperados vs E110;
- créditos esperados vs E110;
- saldo apurado coerente;
- inconsistência entre origem do ajuste e reflexo na apuração.

## 18.4 Ajuste → Recolhimento
Regras:
- E111 compatível com código válido;
- E111 compatível com benefício;
- E111 com soma coerente;
- E116 coerente com o ajuste e o valor recolhível;
- código de receita compatível com o ajuste.

---

# 19. Regras obrigatórias do cruzamento SPED × XML

## 19.1 Existência e situação da NF-e
- XML sem C100;
- C100 sem XML;
- NF cancelada escriturada como ativa;
- NF denegada escriturada;
- `COD_SIT` incompatível com a situação do XML.

## 19.2 Cabeçalho
Comparar:
- chave;
- número;
- série;
- data;
- total da nota;
- total ICMS;
- total IPI;
- total ST;
- desconto;
- frete;
- emitente;
- destinatário.

## 19.3 Participante
Comparar:
- CNPJ;
- IE;
- UF;
- vínculo com `COD_PART`.

## 19.4 Itens
Comparar:
- item;
- código;
- NCM;
- CFOP;
- unidade;
- quantidade;
- valor unitário;
- valor do item;
- desconto;
- CST/CSOSN;
- BC ICMS;
- alíquota ICMS;
- valor do ICMS;
- BC ST;
- alíquota ST;
- valor ST;
- CST IPI;
- BC IPI;
- alíquota IPI;
- valor do IPI.

## 19.5 Enriquecimento por contexto
O cruzamento deve interpretar divergências à luz de:
- regime;
- CRT do emitente;
- benefício ativo;
- alíquota esperada;
- CST esperado;
- MVA;
- FCP.

---

# 20. Catálogo mínimo de erros críticos

O sistema consolidado deve manter e/ou criar error types claros para:

- `CST_INVALIDO`
- `CST_CFOP_INCOMPATIVEL`
- `CST_ALIQ_ZERO_FORTE`
- `ALIQ_INTERESTADUAL_INVALIDA`
- `ALIQ_INTERNA_EM_INTERESTADUAL`
- `ALIQ_INTERESTADUAL_EM_INTERNA`
- `CALCULO_DIVERGENTE`
- `SOMA_DIVERGENTE`
- `C190_DIVERGE_C170`
- `CRUZAMENTO_DIVERGENTE`
- `REF_INEXISTENTE`
- `DIFAL_FALTANTE_CONSUMO_FINAL`
- `DIFAL_FCP_AUSENTE`
- `ST_MVA_DIVERGENTE`
- `IPI_CST_ALIQ_ZERO`
- `NF_CANCELADA_ESCRITURADA`
- `NF_DENEGADA_ESCRITURADA`
- `COD_SIT_DIVERGENTE_XML`
- `XML_BENEFICIO_ALIQ_DIVERGENTE`
- `XML_REGIME_CST_INCOMPATIVEL`
- `BENEFICIO_FORA_VIGENCIA`
- `BENEFICIO_CNAE_INELEGIVEL`
- `CODIGO_AJUSTE_INCOMPATIVEL`

---

# 21. Cobertura e score

## 21.1 Score de cobertura
Deve medir:
- % de regras executadas;
- % de regras puladas;
- % de regras limitadas por falta de tabela;
- % de cobertura XML;
- % de cobertura documental;
- % de contexto crítico disponível.

## 21.2 Score de risco fiscal
Deve ponderar:
- criticidade do erro;
- impacto financeiro potencial;
- cadeia atingida;
- recorrência;
- relação com benefício;
- relação com ST;
- relação com apuração.

---

# 22. Regras de IA e enriquecimento

## 22.1 IA não cria regra
A IA apenas explica o que já foi detectado.

## 22.2 Cache de IA
O cache deve usar:
- rule_id;
- campo;
- valor encontrado;
- regime;
- UF;
- benefício;
- hash do prompt;
- versão da regra.

## 22.3 Relatório narrativo
Somente regenerar se:
- os erros mudarem; ou
- o contexto mudar.

---

# 23. Requisitos não funcionais

## 23.1 Segurança
- API Key obrigatória;
- sem bypass em produção;
- sem aceitar API_KEY vazia;
- sem aceitar chave curta;
- trilha completa de correção.

## 23.2 Produção
- sem `--reload` em produção;
- healthcheck;
- separação entre compose dev e compose prod.

## 23.3 Performance
- upload por chunks;
- parsing em lote;
- parsing paralelo de XML;
- revalidação incremental;
- cache de contexto quando seguro.

## 23.4 Atomicidade
A substituição de erros deve ser transacional.

---

# 24. Roadmap consolidado

## Fase 1 — Correções críticas
- corrigir regime;
- criar Stage 0;
- criar ValidationContext consolidado;
- transação na troca de erros;
- endurecer segurança;
- remover falsa cobertura.

## Fase 2 — Robustez SPED
- reforçar cadeia de apuração;
- reforçar ST;
- reforçar IPI;
- reforçar benefício.

## Fase 3 — Robustez XML
- catálogo formal de equivalência;
- CRT do emitente persistido;
- cobertura XML real;
- cruzamento item a item enriquecido;
- NF cancelada / denegada.

## Fase 4 — Fechamento operacional
- score de risco;
- score de cobertura;
- relatórios consolidados;
- frontend maduro;
- governança completa.

---

# 25. Critérios de aceite

A versão será aceita quando:

1. o usuário puder escolher claramente entre SPED e SPED × XML;
2. nenhuma validação relevante iniciar sem contexto;
3. o regime não depender de `IND_PERFIL`;
4. ST com MVA estiver implementado corretamente;
5. o IPI estiver validado em base, alíquota, valor e reflexo;
6. NF cancelada ou denegada for detectada no cruzamento;
7. o XML for comparado em nível de documento e item;
8. o benefício fiscal afetar efetivamente o julgamento das divergências;
9. o relatório mostrar cobertura real e lacunas;
10. a troca de erros for transacional e segura;
11. a produção estiver endurecida;
12. o escopo permanecer focado em ICMS/IPI sem depender de EFD Contribuições.

---

# 26. Conclusão

A versão consolidada do produto deve preservar o que já existe de mais forte:
- arquitetura por validadores;
- pipeline em estágios;
- contexto fiscal;
- busca de base legal;
- deduplicação;
- trilha de auditoria;
- hipóteses inteligentes controladas.

Ao mesmo tempo, deve corrigir os pontos realmente sensíveis:
- contexto insuficiente;
- regime mal inferido;
- benefício fora do motor decisório;
- XML ainda superficial;
- ST incompleto;
- apuração ainda não totalmente fechada;
- IPI subaproveitado;
- cobertura pouco transparente.

O resultado esperado é um produto mais confiável, mais fiscalmente defensável, mais aderente ao Guia Prático e mais útil no dia a dia de auditoria do escritório.

---

# 27. Referências normativas e técnicas oficiais

## Legislação e manuais-base
- Ajuste SINIEF 02/2009 — instituição da EFD
- Guia Prático da EFD ICMS/IPI — versão vigente em 2026
- Portal SPED — EFD ICMS/IPI
- Lei Complementar nº 87/1996
- Emenda Constitucional nº 87/2015
- Lei Complementar nº 190/2022
- TIPI vigente — Decreto nº 11.158/2022 e alterações posteriores

## Referências oficiais consultadas em 11/04/2026
- SPED — EFD ICMS IPI: https://sped.rfb.gov.br/item/show/274
- Guia Prático da EFD ICMS/IPI: https://sped.rfb.gov.br/arquivo/download/8112
- Página de manuais SPED: https://sped.rfb.gov.br/item/show/1573
- Ajuste SINIEF 02/2009: https://www.confaz.fazenda.gov.br/legislacao/ajustes/2009/AJ_002_09
- Guia Prático no CONFAZ: https://www.confaz.fazenda.gov.br/legislacao/arquivo-manuais/06___anexoguia_pratico_da_escrituracao_fiscal_digital___efd.pdf
- Lei Complementar 87/1996: https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp87.htm
- Emenda Constitucional 87/2015: https://www.planalto.gov.br/ccivil_03/constituicao/emendas/emc/emc87.htm
- Lei Complementar 190/2022: https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp190.htm
- TIPI — Decreto 11.158/2022: https://www.planalto.gov.br/ccivil_03/_ato2019-2022/2022/decreto/d11158.htm
- Alteração posterior da TIPI: https://www.planalto.gov.br/ccivil_03/_ato2023-2026/2025/decreto/d12549.htm
