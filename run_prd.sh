#!/bin/bash
# =============================================================================
# run_prd.sh — Executa os 28 módulos do PRD v3.0 módulo a módulo
# Uso: chmod +x run_prd.sh && ./run_prd.sh
# Uso parcial: ./run_prd.sh 5        (começa do módulo 5)
# Uso intervalo: ./run_prd.sh 5 10   (executa do 5 ao 10)
# =============================================================================

START=${1:-1}
END=${2:-28}
PRD_FILE="PRD - CLAUDE.txt"
LOG_FILE="prd_execution.log"

echo "=============================================" | tee -a "$LOG_FILE"
echo "Iniciando PRD v3.0 — módulos $START até $END" | tee -a "$LOG_FILE"
echo "$(date)" | tee -a "$LOG_FILE"
echo "=============================================" | tee -a "$LOG_FILE"

run_module() {
  local num=$1
  local prompt=$2

  if [ "$num" -lt "$START" ] || [ "$num" -gt "$END" ]; then
    return
  fi

  echo "" | tee -a "$LOG_FILE"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$LOG_FILE"
  echo "▶ MÓDULO $num/28 — $(date +%H:%M:%S)" | tee -a "$LOG_FILE"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$LOG_FILE"

  claude --dangerously-skip-permissions -p "$prompt" 2>&1 | tee -a "$LOG_FILE"

  local exit_code=${PIPESTATUS[0]}
  if [ $exit_code -ne 0 ]; then
    echo "⚠ MÓDULO $num retornou código $exit_code — verifique o log" | tee -a "$LOG_FILE"
  else
    echo "✓ MÓDULO $num concluído" | tee -a "$LOG_FILE"
  fi

  sleep 3
}

# =============================================================================
# FASE 1 — FUNDAÇÃO FISCAL (Módulos 1-7, bloqueantes)
# =============================================================================

run_module 1 "
Leia o arquivo 'PRD - CLAUDE.txt' na raiz do projeto, seção MÓDULO 1.
Implemente COMPLETAMENTE o MOD-01: Identificação de Regime Tributário.

O que deve ser criado/alterado:
1. src/services/context_builder.py
   - Enum TaxRegime com valores: NORMAL, SIMPLES_NACIONAL, MEI, UNKNOWN
   - Dataclass ValidationContext com todos os campos do PRD (file_id, regime,
     uf_contribuinte, periodo_ini, periodo_fim, ind_perfil, cod_ver, cnpj,
     company_name, available_tables, participantes, produtos, naturezas,
     active_rules, found_errors)
   - Função build_context(file_id, db) que lê o registro 0000 do banco,
     determina regime pelo IND_PERFIL (C = Simples Nacional, A/B = Normal),
     popula caches de participantes (0150), produtos (0200) e naturezas (0400)

2. src/services/database.py
   - Adicionar coluna regime_tributario TEXT na tabela sped_files
   - Script de migração inline (ALTER TABLE IF NOT EXISTS column)

3. src/services/file_service.py
   - Após o parse do 0000, chamar build_context() e salvar regime no banco

4. Todos os validators em src/validators/
   - Adicionar parâmetro opcional context: ValidationContext = None
   - Regras de CST Tabela A (CSTs 00-90): pular se context.regime == SIMPLES_NACIONAL
   - Não quebrar assinatura existente (context é opcional)

5. tests/test_context_builder.py
   - Teste: IND_PERFIL='C' → regime=SIMPLES_NACIONAL
   - Teste: IND_PERFIL='A' → regime=NORMAL
   - Teste: IND_PERFIL='B' → regime=NORMAL
   - Teste: context popula participantes do 0150
   - Teste: arquivo Simples Nacional com CSTs 101-900 → zero falsos positivos de CST

Ao final, rode: pytest tests/test_context_builder.py -v --tb=short
Corrija qualquer falha antes de finalizar.
Confirme com: echo 'MOD-01 CONCLUIDO'
"

run_module 2 "
Leia o arquivo 'PRD - CLAUDE.txt' na raiz do projeto, seção MÓDULO 2.
Implemente COMPLETAMENTE o MOD-02: Correção de Lógica no C190.

O que deve ser alterado:
1. src/validators/intra_register_validator.py
   - Regras C190_SOMA_VL_OPR, C190_SOMA_VL_BC_ICMS, C190_SOMA_VL_ICMS
   - Mudar agrupamento de apenas CFOP para (CST_ICMS, CFOP, ALIQ_ICMS)
   - Antes: soma C170 onde c170.CFOP == c190.CFOP
   - Depois: soma C170 onde (c170.CST_ICMS, c170.CFOP, c170.ALIQ_ICMS) == (c190.CST_ICMS, c190.CFOP, c190.ALIQ_ICMS)

2. src/validators/c190_validator.py
   - Mesma correção para C190_001

3. src/validators/cross_block_validator.py
   - Verificar se o cruzamento C vs E usa o mesmo agrupamento e corrigir se necessário

4. Atualizar os testes existentes afetados pela mudança de agrupamento

5. Adicionar novos testes:
   - Teste: documento com CST 00 + CST 40 no mesmo CFOP → dois C190, cada um validado separadamente
   - Teste: C190 com CST 40 e ALIQ 0 → aceito sem erro
   - Teste: C190 com soma errada por CFOP+CST+ALIQ → erro detectado

Rode: pytest --tb=short -q
Zero regressões obrigatório. Corrija qualquer falha.
Confirme com: echo 'MOD-02 CONCLUIDO'
"

run_module 3 "
Leia o arquivo 'PRD - CLAUDE.txt' na raiz do projeto, seção MÓDULO 3.
Implemente COMPLETAMENTE o MOD-03: Sistema de Tolerâncias Parametrizadas.

O que deve ser criado/alterado:
1. src/validators/tolerance.py (arquivo novo)
   - Dicionário TOLERANCES com as chaves:
     item_icms: 0.01
     item_ipi: 0.01
     item_pis: 0.01
     item_cofins: 0.01
     doc_vl_doc: 0.02
     consolidacao: lambda n: max(0.02, 0.01 * (n ** 0.5))
     apuracao_e110: 0.05
     inventario: 0.10
   - Função get_tolerance(comparison_type: str, n_items: int = 1) -> float

2. rules.yaml
   - Adicionar campo tolerance_type em cada regra de recálculo:
     C190_SOMA_VL_OPR → consolidacao
     C190_SOMA_VL_BC_ICMS → consolidacao
     C190_SOMA_VL_ICMS → consolidacao
     E110_SALDO_APURADO → apuracao_e110
     E110_ICMS_RECOLHER → apuracao_e110
     E110_SALDO_CREDOR → apuracao_e110
     C170 recálculos → item_icms / item_ipi etc.

3. Todos os validators que usam tolerância hardcoded (0.01 ou 0.02)
   - Substituir pela chamada get_tolerance(tipo, n_items)

4. tests/test_tolerance.py (arquivo novo)
   - Teste: 200 itens com arredondamento 0.001 cada → consolidacao tolera
   - Teste: erro real de 1.00 em E110 → apuracao_e110 detecta
   - Teste: item com diferença 0.005 → item_icms tolera

Rode: pytest --tb=short -q
Confirme com: echo 'MOD-03 CONCLUIDO'
"

run_module 4 "
Leia o arquivo 'PRD - CLAUDE.txt' na raiz do projeto, seção MÓDULO 4.
Implemente COMPLETAMENTE o MOD-04: Versionamento de Regras por Vigência Fiscal.

O que deve ser criado/alterado:
1. rules.yaml
   - Adicionar campos em TODAS as 121 regras existentes:
     vigencia_de: 'YYYY-MM-DD'  (use '2000-01-01' quando não houver data específica)
     vigencia_ate: null          (null = vigente até hoje)
     version: '1.0'
     last_updated: '2026-04-05'
   - Regras com base legal específica: use a data real da legislação
     RS 13/2012 → vigencia_de: '2013-01-01'
     EC 87/2015 → vigencia_de: '2016-01-01'

2. src/services/rule_loader.py (arquivo novo)
   - Classe RuleLoader com método:
     load_rules_for_period(period_start: date, period_end: date) -> list[Rule]
   - Uma regra é vigente se:
     rule.vigencia_de <= period_end AND
     (rule.vigencia_ate is None OR rule.vigencia_ate >= period_start)
   - Carregar rules.yaml completo e filtrar

3. src/services/validation_service.py
   - Integrar RuleLoader: antes de validar, carregar apenas regras vigentes
     para o período do arquivo (period_start, period_end do ValidationContext)
   - Passar lista de regras ativas para os validators

4. tests/test_rule_loader.py (arquivo novo)
   - Teste: período 2021-01 → regras com vigencia_de > 2021-12 não carregadas
   - Teste: período 2024-01 → regras vigentes retornadas corretamente
   - Teste: regra com vigencia_ate expirada → não carregada

5. CLI: python -m src.rules --vigentes-para=2024-01 (adicionar ao cli.py)

Rode: pytest --tb=short -q
Confirme com: echo 'MOD-04 CONCLUIDO'
"

run_module 5 "
Leia o arquivo 'PRD - CLAUDE.txt' na raiz do projeto, seção MÓDULO 5.
Implemente COMPLETAMENTE o MOD-05: Pipeline de Contexto de Validação (ValidationContext).

Nota: O ValidationContext foi criado no MOD-01. Este módulo integra ele em TODO o pipeline.

O que deve ser alterado:
1. src/services/validation_service.py
   - No início do run_full_validation():
     a) Chamar build_context(file_id, db) → context
     b) Chamar load_rules_for_period(context.periodo_ini, context.periodo_fim) → rules
     c) Salvar context.active_rules = [r.id for r in rules]
     d) Passar context para TODOS os 14 stages do pipeline

2. Todos os 14 validators em src/validators/
   - Garantir que todos aceitam context: ValidationContext como parâmetro
   - Cada validator que depende de regime verifica context.regime antes de aplicar regra
   - Cada validator que depende de UF usa context.uf_contribuinte
   - Cada validator que depende de período usa context.periodo_ini / context.periodo_fim
   - Usar context.participantes e context.produtos em vez de consultar banco novamente

3. src/services/pipeline.py
   - Atualizar pipeline SSE para construir e passar context entre stages

4. Atualizar tests/conftest.py
   - Fixture make_context() que retorna ValidationContext mockado para testes
   - Todos os testes de validators devem usar a fixture (não banco real)

5. Verificar que todos os testes existentes ainda passam com a nova assinatura

Rode: pytest --tb=short -q
Zero regressões obrigatório.
Confirme com: echo 'MOD-05 CONCLUIDO'
"

run_module 6 "
Leia o arquivo 'PRD - CLAUDE.txt' na raiz do projeto, seção MÓDULO 6.
Implemente COMPLETAMENTE o MOD-06: DIFAL (EC 87/2015 + EC 190/2022).

O que deve ser criado:
1. data/reference/aliquotas_internas_uf.yaml
   Crie o arquivo com as alíquotas de todos os 27 estados + DF conforme o PRD.
   Formato:
     meta:
       fonte: 'CONFAZ + legislações estaduais'
       vigencia_de: '2022-01-01'
       vigencia_ate: null
     aliquotas:
       AC: 17.0
       AL: 17.0
       ... (todos os estados)

2. data/reference/fcp_por_uf.yaml
   Com os estados que têm FCP: RJ (2.0), MA (2.0), PA (2.0), BA (2.0), PI (1.0)
   Demais estados: 0.0

3. src/validators/difal_validator.py (arquivo novo)
   Implementar as 8 regras: DIFAL_001 a DIFAL_008 conforme especificado no PRD.
   Cada regra como método separado, com:
   - Verificação de vigência (usar context.periodo_ini >= 2016-01-01)
   - Verificação de disponibilidade de tabela externa (context.available_tables)
   - Se tabela não disponível: emitir warning 'verificação incompleta', não falso positivo

4. src/services/reference_loader.py (arquivo novo, parcial)
   - Classe ReferenceLoader com métodos:
     get_aliquota_interna(uf, date) -> float | None
     get_fcp(uf, date) -> float
     available_tables() -> list[str]
   - Carregar YAMLs de data/reference/

5. Integrar difal_validator no pipeline como stage 10 em validation_service.py

6. tests/test_difal_validator.py
   - Teste: NF interestadual PF sem IE + sem E300 → DIFAL_001 critical
   - Teste: NF interestadual B2B com IE ativa → DIFAL_001 não dispara
   - Teste: E300 com UF diferente do 0150 → DIFAL_003 error
   - Teste: arquivo de 2015 → regras DIFAL não executadas (vigência)
   - Teste: sem tabela de alíquotas → warning de verificação incompleta

Rode: pytest tests/test_difal_validator.py -v --tb=short
Confirme com: echo 'MOD-06 CONCLUIDO'
"

run_module 7 "
Leia o arquivo 'PRD - CLAUDE.txt' na raiz do projeto, seção MÓDULO 7.
Implemente COMPLETAMENTE o MOD-07: ICMS-ST com MVA e Pauta Fiscal.

O que deve ser criado:
1. src/validators/st_validator.py (arquivo novo)
   Implementar 4 regras sem necessidade de tabelas externas:

   ST_001 — ST no item sem reflexo na apuração (E200)
   Condição: C170 com CST 10 ou 30 tem VL_ICMS_ST > 0 MAS E200/E210 ausente ou zerado
   Severidade: error

   ST_002 — CST 60 com débito indevido
   Condição: C170.CST_ICMS = '60' E VL_ICMS_ST > 0 (CST 60 = ST retida anteriormente, sem novo débito)
   Severidade: error

   ST_003 — BC_ICMS_ST menor que VL_ITEM (heurística)
   Condição: BC_ICMS_ST < VL_ITEM para CST 10 ou 30
   Severidade: warning (indicio)

   ST_004 — Mistura indevida ST com DIFAL
   Condição: CST 10 ou 30 + CFOP 6xxx + E300 preenchido simultaneamente
   Severidade: warning (indicio)

2. Integrar st_validator no pipeline após tax_recalc em validation_service.py

3. Atualizar tax_recalc.py:
   - Verificação de CST 10/30 deve conferir se BC_ICMS_ST existe (não apenas VL_ICMS_ST)
   - Não quebrar testes existentes

4. tests/test_st_validator.py
   - Teste para cada uma das 4 regras (positivo + negativo)
   - Teste: CSTs 201, 202, 203, 500 (Simples Nacional ST) com comportamento correto

Rode: pytest tests/test_st_validator.py -v --tb=short
Confirme com: echo 'MOD-07 CONCLUIDO'
"

# =============================================================================
# FASE 2 — QUALIDADE E REFERÊNCIAS (Módulos 8-14)
# =============================================================================

run_module 8 "
Leia o arquivo 'PRD - CLAUDE.txt' na raiz do projeto, seção MÓDULO 9.
Implemente COMPLETAMENTE o MOD-09: Substituição do fields_json por Schema Nomeado.

ATENÇÃO: Esta é uma mudança estrutural. Execute com cuidado e sem pressa.

O que deve ser alterado:
1. src/parser.py
   - Função parse_line deve retornar dict nomeado em vez de list posicional
   - Usar as definições de campos do banco (tabela reg_fields) para nomear cada campo
   - Formato: {'CAMPO_1': 'val1', 'CAMPO_2': 'val2', ...}
   - O JSON salvo em fields_json deve ser o dict serializado

2. scripts/migrate_fields_json.py (arquivo novo)
   - Script que lê todos os registros do banco com fields_json em formato array
   - Detecta formato antigo: json.loads(fields_json) retorna list
   - Converte para dict usando definição de campos do reg_fields
   - Atualiza o banco

3. Todos os validators em src/validators/
   - Substituir todo acesso por índice (fields[2]) por acesso por nome (fields['NOME'])
   - Buscar todos os usos de fields_json e garantir que são por nome
   - Usar método helper: get_field(record, 'NOME', default='')

4. src/models.py
   - Adicionar helper get_field(record, field_name, default='') -> str

5. tests/ — garantir que todos os fixtures de teste usam o novo formato dict

Rode: pytest --tb=short -q
Zero regressões. Corrija tudo que quebrar.
Confirme com: echo 'MOD-09 CONCLUIDO'
"

run_module 9 "
Leia o arquivo 'PRD - CLAUDE.txt' na raiz do projeto, seção MÓDULO 10.
Implemente COMPLETAMENTE o MOD-10: Controle Obrigatório de Correções (Aprovação Humana).

O que deve ser criado/alterado:
1. api/schemas/models.py
   - Modelo CorrectionRequest: adicionar campos obrigatórios:
     justificativa: str (min_length=20)
     correction_type: Literal['deterministic', 'assisted', 'manual']
     rule_id: str
   - Validação Pydantic: justificativa com @validator min 20 chars

2. api/routers/records.py — endpoint PUT /records/{rec_id}
   - Validar CorrectionRequest com os novos campos
   - Retornar 422 se justificativa < 20 caracteres
   - Retornar 400 com mensagem explicativa se field_name em ('CST_ICMS', 'CFOP',
     'ALIQ_ICMS', 'CST_IPI', 'COD_AJ_APUR', 'VL_AJ_APUR') — campos proibidos
   - Salvar justificativa e rule_id no banco

3. src/services/database.py — tabela corrections
   - Adicionar colunas: justificativa TEXT, correction_type TEXT, rule_id TEXT

4. src/services/correction_service.py
   - apply_correction() deve receber e salvar justificativa obrigatoriamente
   - audit_log deve incluir: justificativa, correction_type, rule_id, field_name

5. src/services/auto_correction_service.py
   - Remover qualquer lógica que aplica correção de CST, CFOP ou alíquota
   - Deixar apenas correções determinísticas (formato de data, CNPJ, numérico)
   - Cada sugestão automática deve vir com suggested=True, não applied=True

6. tests/test_correction_control.py
   - Teste: justificativa vazia → 422
   - Teste: justificativa < 20 chars → 422
   - Teste: corrigir CST_ICMS → 400
   - Teste: corrigir CFOP → 400
   - Teste: correção válida com justificativa → 200 e salvo no audit_log

Rode: pytest tests/test_correction_control.py -v --tb=short
Confirme com: echo 'MOD-10 CONCLUIDO'
"

run_module 10 "
Leia o arquivo 'PRD - CLAUDE.txt' na raiz do projeto, seções MÓDULO 11 e MÓDULO 12.
Implemente COMPLETAMENTE o MOD-11 e MOD-12 juntos.

MOD-11: Dashboard de Escopo da Auditoria

1. api/routers/validation.py — novo endpoint:
   GET /api/files/{id}/audit-scope
   Retorna JSON com:
   - regime_identificado
   - periodo
   - checks_executados: lista com id, status (ok/parcial/nao_executado/nao_aplicavel), regras, motivo_parcial
   - tabelas_externas: dict com disponibilidade de cada tabela
   - cobertura_estimada_pct: calculado com base nos checks executados
   - aviso: string de texto quando cobertura < 100%

2. api/schemas/models.py — modelo AuditScope com todos os campos acima

MOD-12: Separação de Metarregras do Pipeline Fiscal

3. src/services/database.py — tabela validation_errors
   - Adicionar coluna: categoria TEXT DEFAULT 'fiscal'

4. src/validators/beneficio_audit_validator.py e audit_rules.py
   - Marcar como categoria='governance':
     AUD_CHECKLIST_MESTRE → categoria='governance', severity='info'
     AUD_CLASSIFICACAO_ERRO → categoria='governance'
     AUD_ESCOPO_APENAS_SPED → categoria='governance'

5. api/routers/validation.py — endpoint GET /errors
   - Adicionar parâmetro opcional: categoria (default='fiscal')
   - Filtrar por categoria no SQL

6. api/schemas/models.py — ValidationError model
   - Adicionar campo categoria: str = 'fiscal'

7. tests/test_audit_scope.py
   - Teste: endpoint retorna estrutura completa
   - Teste: metarregras não aparecem em /errors?categoria=fiscal
   - Teste: /errors?categoria=governance retorna apenas metarregras

Rode: pytest --tb=short -q
Confirme com: echo 'MOD-11-12 CONCLUIDO'
"

run_module 11 "
Leia o arquivo 'PRD - CLAUDE.txt' na raiz do projeto, seção MÓDULO 13.
Implemente COMPLETAMENTE o MOD-13: Escala Ortogonal de Achados.

O que deve ser criado/alterado:
1. src/services/database.py — tabela validation_errors
   - Adicionar colunas:
     certeza TEXT DEFAULT 'objetivo'   -- objetivo | provavel | indicio
     impacto TEXT DEFAULT 'relevante'  -- critico | relevante | informativo

2. rules.yaml — adicionar campos em TODAS as 121 regras:
   certeza: objetivo | provavel | indicio
   impacto: critico | relevante | informativo
   
   Exemplos de mapeamento:
   - Erros matemáticos (BC*ALIQ≠VL_ICMS): certeza=objetivo, impacto=critico
   - Erros de formato (CNPJ, data): certeza=objetivo, impacto=relevante
   - Indícios de benefício fiscal: certeza=indicio, impacto=critico
   - Metarregras: certeza=objetivo, impacto=informativo

3. src/services/validation_service.py
   - Ao persistir erro, ler certeza e impacto da regra no rules.yaml e salvar

4. api/routers/validation.py — endpoint /errors
   - Adicionar filtros opcionais: ?certeza=objetivo e ?impacto=critico

5. api/schemas/models.py — ValidationError model
   - Adicionar campos: certeza: str = 'objetivo', impacto: str = 'relevante'

6. tests/test_ortogonal_scale.py
   - Teste: regra de recálculo salva com certeza=objetivo, impacto=critico
   - Teste: filtro ?certeza=indicio retorna apenas indícios

Rode: pytest --tb=short -q
Confirme com: echo 'MOD-13 CONCLUIDO'
"

run_module 12 "
Leia o arquivo 'PRD - CLAUDE.txt' na raiz do projeto, seção MÓDULO 14.
Implemente COMPLETAMENTE o MOD-14: Tabelas de Referência Externas.

O que deve ser criado:
1. Estrutura de pastas:
   data/reference/
   data/reference/vigencias/
   data/reference/vigencias/aliquotas_internas_uf/
   data/reference/vigencias/fcp_por_uf/
   data/reference/vigencias/matriz_aliquotas_uf/

2. data/reference/ibge_municipios.yaml
   - Lista completa dos 5.570 municípios brasileiros com código IBGE de 7 dígitos
   - Formato: lista de {codigo: '1100015', nome: 'Alta Floresta D Oeste', uf: 'RO'}
   - Use dados oficiais do IBGE (você conhece os municípios brasileiros)
   - Ao menos os 100 maiores municípios por população — o resto pode ser gerado
     como lista parcial com nota de que precisa ser completada

3. data/reference/ncm_tipi_categorias.yaml
   - Lista de NCMs com tratamento especial: isentos, monofásicos, NT
   - Não precisa ser completa — ao menos os mais comuns (combustíveis, medicamentos,
     alimentos da cesta básica, bebidas, cigarros)

4. src/services/reference_loader.py (expandir o criado no MOD-06)
   - Adicionar métodos:
     is_municipio_valido(cod_mun: str) -> bool
     get_ncm_tributacao(ncm: str) -> str | None  -- 'normal'|'isento'|'monofasico'|None
     get_matriz_aliquota(uf_origem: str, uf_destino: str, date: date) -> float | None
   - available_tables() deve retornar lista completa de tabelas disponíveis

5. src/validators/format_validator.py — FMT_COD_MUNICIPIO
   - Atualizar para validar contra ibge_municipios.yaml (não só primeiro dígito)
   - Fallback: se tabela não disponível, usar validação atual de dígito

6. ValidationContext (context_builder.py)
   - Adicionar reference_loader: ReferenceLoader como campo do context
   - build_context() instancia e injeta o loader

7. tests/test_reference_loader.py
   - Teste: município válido → True
   - Teste: código fictício → False
   - Teste: UF com FCP → percentual correto
   - Teste: tabela não disponível → available_tables() lista corretamente

Rode: pytest --tb=short -q
Confirme com: echo 'MOD-14 CONCLUIDO'
"

run_module 13 "
Leia o arquivo 'PRD - CLAUDE.txt' na raiz do projeto, seção MÓDULO 15.
Implemente COMPLETAMENTE o MOD-15: Autenticação e Autorização (API Key).

O que deve ser criado/alterado:
1. api/auth.py (arquivo novo)
   - Função verify_api_key(x_api_key: str = Header(None)) -> str
   - Lê API_KEY da variável de ambiente (os.getenv('API_KEY'))
   - Se API_KEY não configurada: log de aviso, aceita qualquer key (modo dev)
   - Se API_KEY configurada e key diverge: raise HTTPException(401)
   - Retorna a key validada

2. api/deps.py
   - Adicionar depend verify_api_key para todos os routers

3. api/main.py
   - Aplicar verify_api_key em todos os routers EXCETO /api/health
   - /api/health continua público

4. api/routers/ (files, records, validation, report, search)
   - Adicionar Depends(verify_api_key) em cada router ou em cada endpoint

5. .env.example (arquivo novo na raiz)
   API_KEY=sua-chave-aqui-minimo-32-caracteres
   DATABASE_URL=db/sped.db

6. README.md
   - Remover o caminho pessoal 'C:\Users\bmb19\...'
   - Substituir por instruções genéricas com variável de ambiente
   - Adicionar seção de configuração da API_KEY

7. config.py
   - Carregar API_KEY do ambiente

8. tests/test_auth.py
   - Teste: sem API_KEY no header → 401 quando env configurado
   - Teste: com API_KEY correta → 200
   - Teste: /api/health sem key → 200 (público)
   - Teste: modo dev sem env → aceita qualquer key

Rode: pytest tests/test_auth.py -v --tb=short
Confirme com: echo 'MOD-15 CONCLUIDO'
"

run_module 14 "
Leia o arquivo 'PRD - CLAUDE.txt' na raiz do projeto, seção MÓDULO 16.
Implemente COMPLETAMENTE o MOD-16: Suporte a Retificadores (COD_VER).

O que deve ser criado/alterado:
1. src/services/database.py
   - Tabela sped_files: adicionar colunas:
     cod_ver INTEGER DEFAULT 0
     original_file_id INTEGER (FK para sped_files.id, nullable)
     is_retificador INTEGER DEFAULT 0
   
   - Nova tabela sped_file_versions:
     CREATE TABLE IF NOT EXISTS sped_file_versions (
       id INTEGER PRIMARY KEY,
       original_file_id INTEGER NOT NULL,
       retificador_file_id INTEGER NOT NULL,
       cod_ver INTEGER NOT NULL,
       linked_at TEXT DEFAULT (datetime('now')),
       FOREIGN KEY (original_file_id) REFERENCES sped_files(id),
       FOREIGN KEY (retificador_file_id) REFERENCES sped_files(id)
     )

2. src/services/file_service.py
   - Ao fazer upload, ler COD_VER do registro 0000
   - Se COD_VER > 0: buscar arquivo original (mesmo CNPJ + mesmo período + COD_VER=0)
   - Se encontrar original: vincular via sped_file_versions
   - Salvar cod_ver e is_retificador na tabela sped_files

3. src/validators/ — duas regras novas:
   RET_001: retificador com período diferente da original → error
   RET_002: COD_VER > 0 sem original no sistema → warning informativo

4. api/schemas/models.py — FileInfo model
   - Adicionar campos: cod_ver, is_retificador, original_file_id

5. api/routers/files.py — endpoint GET /files/{id}
   - Retornar cod_ver, is_retificador, original_file_id no response

6. tests/test_retificadores.py
   - Teste: upload de arquivo COD_VER=0 → cod_ver=0, is_retificador=False
   - Teste: upload retificador com original existente → linked corretamente
   - Teste: upload retificador sem original → RET_002 warning

Rode: pytest --tb=short -q
Confirme com: echo 'MOD-16 CONCLUIDO'
"

# =============================================================================
# FASE 3 — VALIDAÇÕES AVANÇADAS (Módulos 15-20)
# =============================================================================

run_module 15 "
Leia o arquivo 'PRD - CLAUDE.txt' na raiz do projeto, seção MÓDULO 8.
Implemente COMPLETAMENTE o MOD-08: Bloco D (CT-e e Documentos de Transporte).

O que deve ser criado:
1. src/validators/bloco_d_validator.py (arquivo novo)
   Implementar 6 regras:

   D_001 — COD_PART do D100 deve existir no 0150
   (equivalente ao REF_COD_PART_C100, aplicado ao D100)

   D_002 — CFOP do D100 compatível com direção da operação
   (entrada=1/2/3, saída=5/6/7 — mesma lógica do C170)

   D_003 — D190 deve fechar com soma dos D100 correspondentes por CST+CFOP+ALIQ
   (equivalente ao C190_001)

   D_004 — D690 deve compor VL_TOT_DEBITOS do E110
   (cruzamento D vs E, similar ao C vs E)

   D_005 — CST_ICMS do D100 compatível com regime (usando ValidationContext.regime)

   D_006 — Chave CT-e deve ter 44 dígitos com DV válido módulo 11
   (usar mesma lógica do FMT_CHAVE_NFE)

2. Integrar bloco_d_validator no pipeline como stage após bloco C

3. src/validators/cross_block_validator.py
   - Incluir D690 no cruzamento de débitos/créditos vs E110

4. rules.yaml — adicionar as 6 regras D_001 a D_006

5. tests/test_bloco_d_validator.py
   - Fixture: arquivo SPED com bloco D válido
   - Fixture: arquivo com erros no bloco D
   - Teste para cada uma das 6 regras

Rode: pytest tests/test_bloco_d_validator.py -v --tb=short
Confirme com: echo 'MOD-08 CONCLUIDO'
"

run_module 16 "
Leia o arquivo 'PRD - CLAUDE.txt' na raiz do projeto, seção MÓDULO 19.
Implemente COMPLETAMENTE o MOD-19: Segurança, Performance e Infraestrutura.

O que deve ser criado/alterado:
1. api/routers/files.py — endpoint POST /upload
   - Adicionar validação de tamanho máximo: 100 MB
   - Retornar 413 se arquivo > 100 MB
   - Implementar leitura streaming com aiofiles ou processamento em chunks

2. src/parser.py
   - Refatorar para leitura linha a linha (não carregar arquivo inteiro em memória)
   - Processar em batches de 1000 linhas com persistência incremental
   - Função parse_file_streaming(filepath, file_id, db) -> Generator

3. api/routers/records.py — GET /records
   - Adicionar parâmetros: page: int = 1, page_size: int = 100
   - Response incluir: total, page, page_size, has_next, data: list

4. api/routers/validation.py — GET /errors
   - Mesma paginação: page, page_size, total, has_next

5. api/schemas/models.py
   - Modelo PaginatedResponse genérico com campos acima

6. src/services/database.py — nova tabela embedding_metadata:
   CREATE TABLE IF NOT EXISTS embedding_metadata (
     id INTEGER PRIMARY KEY,
     model_name TEXT NOT NULL,
     model_version TEXT,
     indexed_at TEXT DEFAULT (datetime('now')),
     chunks_count INTEGER
   )

7. src/indexer.py
   - Ao indexar, salvar model_name na tabela embedding_metadata

8. src/embeddings.py ou src/searcher.py
   - Ao iniciar, comparar modelo configurado com o indexado
   - Se divergir: logar aviso 'Modelo de embeddings mudou desde a indexação'

9. README.md e config.py
   - Remover path pessoal C:\Users\bmb19\ de todos os lugares restantes

10. tests/test_infrastructure.py
    - Teste: upload > 100 MB → 413
    - Teste: paginação em /records retorna estrutura correta
    - Teste: paginação em /errors com page=2 retorna próxima página

Rode: pytest --tb=short -q
Confirme com: echo 'MOD-19 CONCLUIDO'
"

run_module 17 "
Leia o arquivo 'PRD - CLAUDE.txt' na raiz do projeto, seção MÓDULO 20.
Implemente COMPLETAMENTE o MOD-20: Relatório de Auditoria com Responsabilidade Legal.

O que deve ser criado/alterado:
1. src/services/export_service.py
   Refatorar generate_report() para incluir as 6 seções obrigatórias:

   SEÇÃO 1 — CABEÇALHO DE IDENTIFICAÇÃO
   - Nome do contribuinte, CNPJ, período, hash SHA-256 do original,
     data/hora da auditoria, versão do motor de regras

   SEÇÃO 2 — COBERTURA DA AUDITORIA
   - Checks executados com status
   - Tabelas externas disponíveis e ausentes
   - Percentual de cobertura
   - Limitações conhecidas

   SEÇÃO 3 — SUMÁRIO DE ACHADOS
   - Por severidade: N críticos, N erros, N warnings, N info
   - Por certeza: N objetivos, N prováveis, N indícios
   - Por bloco: C, D, E, H
   - Top-10 tipos por frequência

   SEÇÃO 4 — ACHADOS DETALHADOS
   - Ordenados por impacto (crítico primeiro)
   - Cada achado: linha, registro, campo, valor encontrado, esperado,
     certeza, impacto, base legal, orientação de correção

   SEÇÃO 5 — CORREÇÕES APLICADAS
   - Lista com campo, valor original, novo valor, justificativa, aprovado por, data

   SEÇÃO 6 — RODAPÉ LEGAL OBRIGATÓRIO
   Texto exato:
   'AVISO LEGAL: Este relatório foi gerado automaticamente pelo sistema de
    auditoria SPED EFD e não constitui parecer contábil, fiscal ou jurídico.
    A conferência, validação e retificação do arquivo SPED junto à Secretaria
    da Fazenda é responsabilidade exclusiva do contribuinte e de seu representante
    técnico legalmente habilitado (CRC/CRA/OAB).
    Verificações não realizadas nesta auditoria: [lista].
    Versão do motor: [versão]. Data: [data].'

2. O rodapé deve aparecer em TODOS os formatos: MD, CSV, JSON

3. tests/test_export_service.py — atualizar testes existentes
   - Verificar que todas as 6 seções estão presentes no relatório
   - Verificar rodapé em MD, CSV, JSON

Rode: pytest tests/test_export_service.py -v --tb=short
Confirme com: echo 'MOD-20 CONCLUIDO'
"

run_module 18 "
Leia o arquivo 'PRD - CLAUDE.txt' na raiz do projeto, seção MÓDULO 17.
Implemente COMPLETAMENTE o MOD-17: Bloco C Serviços (C400/C500).

O que deve ser criado:
1. src/validators/bloco_c_servicos_validator.py (arquivo novo)
   Implementar validações básicas para:

   C400/C490 — ECF (Equipamento Emissor de Cupom Fiscal):
   - COD_PART referenciado em C400 deve existir no 0150
   - C490 deve fechar com soma dos C400 por CST+CFOP+ALIQ
   - Datas dentro do período 0000

   C500/C590 — NF Energia Elétrica e Gás:
   - COD_PART do C500 deve existir no 0150
   - CFOP do C500 compatível com operação (entrada=1/2/3, saída=5/6/7)
   - C590 deve fechar com soma dos C510 (equivalente ao C190)
   - Cruzamento C590 vs E110 (incluir no cross_block_validator)

2. src/validators/cross_block_validator.py
   - Incluir C590 no cruzamento de débitos/créditos vs E110

3. rules.yaml — adicionar regras CS_001 a CS_004

4. Integrar no pipeline em validation_service.py

5. tests/test_bloco_c_servicos.py
   - Teste básico com C500/C590 válidos
   - Teste: C590 com soma errada → erro detectado

Rode: pytest tests/test_bloco_c_servicos.py -v --tb=short
Confirme com: echo 'MOD-17 CONCLUIDO'
"

# =============================================================================
# FASE 4 — 55 NOVAS REGRAS (Módulos 19-24)
# =============================================================================

run_module 19 "
Leia o arquivo 'PRD - CLAUDE.txt' na raiz do projeto, seção '24. CATÁLOGO COMPLETO'.
Implemente o GRUPO ALÍQUOTAS (ALIQ_001 a ALIQ_007) completo.

O que deve ser criado/alterado:
1. src/validators/aliquota_validator.py
   As regras ALIQ_001 a ALIQ_003 e ALIQ_007 já existem.
   Adicionar ALIQ_004, ALIQ_005, ALIQ_006:

   ALIQ_004 — Alíquota 7/12% incompatível com par UF origem-destino
   Condição: CFOP 6xxx + par UF não corresponde à alíquota padrão
   Requer: reference_loader.get_matriz_aliquota(uf_orig, uf_dest, date)
   Se tabela indisponível: emitir info 'verificação incompleta'
   Severidade: critical quando detectado

   ALIQ_005 — Alíquota 4% sem suporte de importação
   Condição: CFOP 6xxx + ALIQ=4 + NCM não tipicamente importado
   Severidade: warning (indicio)

   ALIQ_006 — Mesmo item com alíquotas divergentes no período
   Condição: mesmo COD_ITEM com ALIQ_ICMS diferentes em documentos do mesmo período
   Usar context.produtos para verificar histórico do item
   Severidade: warning

2. Corrigir ALIQ_002 conforme auditoria:
   - Rebaixar de critical para error (heurística, não erro objetivo)
   - Ajustar condição: ALIQ >= 17 como proxy, mas marcar certeza=provavel

3. Adicionar as 3 regras novas ao rules.yaml com todos os metadados
   (vigencia_de, certeza, impacto, tolerance_type, legislation)

4. tests/test_aliquota_validator.py — expandir com testes para ALIQ_004/005/006

Rode: pytest tests/test_aliquota_validator.py -v --tb=short
Confirme com: echo 'ALIQ_COMPLETO CONCLUIDO'
"

run_module 20 "
Leia o arquivo 'PRD - CLAUDE.txt' na raiz do projeto, seção '24. CATÁLOGO COMPLETO'.
Implemente o GRUPO BASE DE CÁLCULO (BASE_001 a BASE_006).

O que deve ser criado:
1. src/validators/base_calculo_validator.py (arquivo novo)

   BASE_001 — Recálculo ICMS divergente
   Equivale ao recálculo existente no tax_recalc.py
   Verificar se já existe e consolidar/reutilizar

   BASE_002 — Base menor que esperado sem justificativa
   Condição: VL_BC_ICMS < (VL_ITEM * 0.5) sem CST de redução (020, 070)
   Severidade: error | Certeza: provavel

   BASE_003 — Base superior ao razoável
   Condição: VL_BC_ICMS > VL_ITEM * 1.5
   Severidade: warning | Certeza: indicio

   BASE_004 — Frete CIF não incluído na base
   Condição: VL_FRT > 0 + modalidade CIF estimada + VL_FRT ausente da BC
   Severidade: error | Certeza: provavel | Requer: context externo CT-e

   BASE_005 — Frete FOB incluído indevidamente
   Condição: VL_FRT incluído na BC + indicação FOB
   Severidade: warning | Certeza: indicio

   BASE_006 — Despesas acessórias fora da base
   Condição: VL_OUT_DA > 0 + não incluído em VL_BC_ICMS para CST tributado
   Severidade: warning | Certeza: objetivo
   Base legal: Art. 13, LC 87/1996

2. Integrar no pipeline
3. Adicionar ao rules.yaml com todos os metadados
4. tests/test_base_calculo_validator.py com testes positivo e negativo para cada regra

Rode: pytest tests/test_base_calculo_validator.py -v --tb=short
Confirme com: echo 'BASE_COMPLETO CONCLUIDO'
"

run_module 21 "
Leia o arquivo 'PRD - CLAUDE.txt' na raiz do projeto, seção '24. CATÁLOGO COMPLETO'.
Implemente os GRUPOS IPI, DESTINATÁRIO e CFOP completos.

O que deve ser criado:
1. src/validators/ipi_validator.py (ou expandir tax_recalc.py)
   IPI_001 — IPI reflexo incorreto na base ICMS
   Condição: destinatário não-contribuinte → IPI deve entrar na BC ICMS
             destinatário contribuinte → IPI não deve entrar na BC ICMS
   Requer: perfil destinatário (context.participantes + 0150.IE)
   Severidade: warning | Certeza: provavel
   Base legal: Art. 13, §2º, LC 87/1996

   IPI_002 — Recálculo IPI divergente (verificar se já existe no tax_recalc, consolidar)
   IPI_003 — CST IPI incompatível com campos monetários (verificar se já existe, consolidar)

2. src/validators/destinatario_validator.py (arquivo novo)
   DEST_001 — IE inconsistente com tratamento fiscal
   DEST_002 — UF incompatível com IE (usar prefixo_ie_uf se disponível)
   DEST_003 — UF incompatível com CEP (usar faixa_cep_uf se disponível)

3. src/validators/cfop_validator.py (arquivo novo ou expandir existente)
   CFOP_001 — CFOP interestadual com destino mesma UF
   CFOP_002 — CFOP interno com destino outra UF
   CFOP_003 — CFOP incompatível com tratamento DIFAL

4. Adicionar todas as regras ao rules.yaml com metadados completos
5. Integrar todos os novos validators no pipeline
6. Tests para cada grupo: test_ipi_validator, test_destinatario_validator, test_cfop_validator

Rode: pytest --tb=short -q
Confirme com: echo 'IPI_DEST_CFOP CONCLUIDO'
"

run_module 22 "
Leia o arquivo 'PRD - CLAUDE.txt' na raiz do projeto, seção '24. CATÁLOGO COMPLETO'.
Implemente os GRUPOS CST EXPANDIDO, BENEFÍCIO FISCAL e DEVOLUÇÕES.

O que deve ser criado/alterado:
1. src/validators/cst_validator.py — expandir com CST_001 a CST_005:
   CST_001 — CST tributado com alíquota zero (verificar se já existe, consolidar)
   CST_002 — CST isento/NT com valor de ICMS (verificar se já existe, consolidar)
   CST_003 — CST 020 sem redução real (verificar se já existe no cst_expandido, consolidar)
   CST_004 — CST 020 com alíquota reduzida sem decreto (certeza=provavel, warning)
   CST_005 — Diferimento com débito indevido (CST 051 + VL_ICMS > 0)

2. src/validators/beneficio_validator.py (arquivo novo)
   BENE_001 — Benefício contaminando alíquota do documento
   BENE_002 — Benefício contaminando cálculo DIFAL
   BENE_003 — Base do benefício com operações não elegíveis

3. src/validators/devolucao_validator.py (arquivo novo)
   DEV_001 — Devolução sem espelhamento da NF original
   DEV_002 — Devolução sem tratamento do DIFAL
   DEV_003 — Devolução com alíquota atual vs. histórica

4. Adicionar todas ao rules.yaml com metadados completos
5. Integrar no pipeline
6. Tests: test_cst_expandido, test_beneficio_validator, test_devolucao_validator

Rode: pytest --tb=short -q
Confirme com: echo 'CST_BENE_DEV CONCLUIDO'
"

run_module 23 "
Leia o arquivo 'PRD - CLAUDE.txt' na raiz do projeto, seção '24. CATÁLOGO COMPLETO'.
Implemente os GRUPOS PARAMETRIZAÇÃO, NCM e GOVERNANÇA.

O que deve ser criado:
1. src/validators/parametrizacao_validator.py (arquivo novo)
   PARAM_001 — Erro sistemático por item
   Condição: mesmo COD_ITEM com mesmo tipo de erro em >80% de suas ocorrências
   Mensagem: 'Possível erro de parametrização no ERP para o produto [X]'
   Usar context.found_errors para análise de padrão

   PARAM_002 — Erro sistemático por UF destino
   Condição: mesmo tipo de erro em >80% das operações para mesma UF destino

   PARAM_003 — Erro sistemático iniciado em data específica
   Condição: tipo de erro concentrado após determinada data

2. src/validators/ncm_validator.py (arquivo novo)
   NCM_001 — NCM com tratamento tributário incompatível
   Requer: reference_loader.get_ncm_tributacao(ncm)
   Se indisponível: emitir info

   NCM_002 — NCM genérico com reflexo fiscal relevante
   Condição: NCM terminado em '0000' + VL_ITEM > R$ 1.000

3. Regras de governança já em audit_rules.py — garantir que estão com categoria=governance
   GOV_001 a GOV_004, AMOSTRA_001

4. Adicionar todas ao rules.yaml
5. Integrar PARAM e NCM no pipeline (governança já está)
6. tests/test_parametrizacao_validator.py, tests/test_ncm_validator.py

Rode: pytest --tb=short -q
Confirme com: echo 'PARAM_NCM_GOV CONCLUIDO'
"

# =============================================================================
# FASE 5 — FRONTEND (Módulo 24-26)
# =============================================================================

run_module 24 "
Leia o arquivo 'PRD - CLAUDE.txt' na raiz do projeto, seção MÓDULO 18.
Implemente os componentes de frontend: RecordDetail e FieldEditor.

O que deve ser criado em frontend/src/:
1. components/Records/RecordDetail.tsx
   - Componente expandível: clique em uma linha da tabela → expande detalhes
   - Lista todos os campos do registro com nome + valor atual
   - Campos com erro: fundo vermelho claro + ícone de alerta
   - Campos corrigidos: fundo verde claro + ícone de check
   - Botão 'Ver documentação' → dispara busca semântica via GET /api/search
   - Props: record: RecordInfo, errors: ValidationError[], onClose: () => void

2. components/Records/FieldEditor.tsx
   - Exibido ao clicar em um campo com erro
   - Exibe: nome do campo, valor atual, tipo esperado, mensagem de erro
   - Para campos com valid_values: <select> com as opções
   - Para campos livres: <input> com validação onChange
   - Campo obrigatório 'Justificativa' (textarea, mínimo 20 chars)
   - Campos proibidos (CST_ICMS, CFOP, ALIQ_ICMS, COD_AJ_APUR):
     input desabilitado + mensagem 'Alteração não permitida automaticamente'
   - Botão 'Aplicar Correção' → chama PUT /api/files/{id}/records/{recId}
   - Botão 'Cancelar'
   - Props: record, fieldName, error, onSave, onCancel

3. Integrar RecordDetail na ErrorsTab do FileDetailPage.tsx
   - Ao clicar em uma linha de erro → abre RecordDetail
   - Ao clicar em campo com erro → abre FieldEditor

4. Atualizar types/sped.ts
   - Adicionar campos certeza, impacto, categoria em ValidationError
   - Adicionar campos cod_ver, is_retificador, original_file_id em FileInfo

Confirme com: echo 'FRONTEND_EDITOR CONCLUIDO'
"

run_module 25 "
Leia o arquivo 'PRD - CLAUDE.txt' na raiz do projeto, seção MÓDULO 18.
Implemente os componentes: SuggestionPanel, CrossValidationPage e Gráficos.

O que deve ser criado em frontend/src/:
1. components/Records/SuggestionPanel.tsx
   - Painel lateral exibido junto ao FieldEditor
   - Seção 'Documentação relevante': lista top-3 chunks da busca semântica
   - Seção 'O que o sistema encontrou': descrição do erro em linguagem clara
   - Seção 'Orientação de correção': texto da regra + ação recomendada
   - Seção 'Base legal': artigo/resolução/convênio da regra
   - Seção 'Certeza': badge objetivo/provável/indício com tooltip
   - Seção 'Impacto': badge crítico/relevante/informativo com ícone
   - Props: error: ValidationError, onSearch: (query: string) => Promise<SearchResult[]>

2. pages/CrossValidationPage.tsx
   - Tabela com cruzamentos entre blocos
   - Colunas: Tipo, Registro Origem, Linha, Registro Destino, Linha,
              Valor Esperado, Valor Encontrado, Diferença, Severidade
   - Filtro por tipo: 'C_vs_E' | '0_vs_C' | 'bloco9' | 'C_vs_H' | 'D_vs_E'
   - Diferença em vermelho quando acima da tolerância
   - Busca os dados via GET /api/files/{id}/errors?categoria=cruzamento
     (ou endpoint específico se existir)
   - Adicionar rota '/files/:id/cross' no App.tsx ou Layout.tsx

3. components/Dashboard/ErrorChart.tsx
   - Gráfico de barras (Recharts BarChart): erros por bloco (C, D, E, H)
   - Gráfico de pizza (Recharts PieChart): por severidade (critical/error/warning/info)
   - Gráfico de barras: por certeza (objetivo/provavel/indicio)
   - Dados vindos de GET /api/files/{id}/summary
   - Integrar no FileDetailPage na aba Resumo

4. components/Dashboard/AuditScopePanel.tsx
   - Busca GET /api/files/{id}/audit-scope
   - Banner vermelho se cobertura < 80%, amarelo se < 100%
   - Lista de checks com ícone de status (✓ ok, ⚠ parcial, ✗ não executado)
   - Lista de tabelas externas ausentes
   - Texto de cobertura: 'Auditoria com X% de cobertura'
   - Integrar no topo do FileDetailPage (sempre visível)

Confirme com: echo 'FRONTEND_PANELS CONCLUIDO'
"

run_module 26 "
Leia o arquivo 'PRD - CLAUDE.txt' na raiz do projeto, seção MÓDULO 18.
Implemente o CorrectionApprovalPanel e responsividade mobile.

O que deve ser criado em frontend/src/:
1. components/Corrections/CorrectionApprovalPanel.tsx
   - Lista de auto_corrections em staging (suggested=True, applied=False)
   - Para cada item: campo, valor antigo → valor novo, regra, certeza, impacto
   - Botões: 'Aprovar' (abre modal com campo justificativa) | 'Rejeitar' | 'Pular'
   - Modal de aprovação: textarea justificativa (min 20 chars) + botão confirmar
   - Barra de progresso: N/total decididas
   - Botão 'Exportar SPED Corrigido': desabilitado até todas terem decisão
   - Quando habilitado: chama GET /api/files/{id}/download

2. Responsividade mobile básica
   - Layout.tsx: sidebar recolhível em telas < 768px (hamburger menu)
   - Tabelas: scroll horizontal em mobile
   - UploadPage: drag & drop adaptado para touch
   - FileDetailPage: tabs empilhadas em mobile

3. Integrar CorrectionApprovalPanel no FileDetailPage como nova aba 'Correções'

4. Verificar que o build não tem erros TypeScript:
   cd frontend && npx tsc --noEmit

Confirme com: echo 'FRONTEND_APPROVAL CONCLUIDO'
"

# =============================================================================
# FASE 6 — CONSOLIDAÇÃO FINAL (Módulos 27-28)
# =============================================================================

run_module 27 "
Execute a consolidação completa do projeto:

1. Rode a suite de testes completa:
   pytest --tb=short -q --cov=src --cov=api --cov-report=term-missing

2. Se cobertura caiu abaixo de 90%: identifique os módulos novos sem cobertura
   e adicione testes suficientes para voltar a >= 90%

3. Rode o lint completo:
   ruff check src/ api/ tests/
   mypy src/ api/ --ignore-missing-imports
   bandit -r src/ api/ -ll

4. Corrija TODOS os problemas de lint/tipo encontrados. Zero erros obrigatório.

5. Verifique que o rules.yaml tem os campos obrigatórios em TODAS as regras:
   python -m src.rules --check
   Todos devem aparecer como 'implemented: true'

6. Verifique que todos os 121+ regras têm:
   - vigencia_de preenchido
   - certeza preenchido
   - impacto preenchido
   - tolerance_type (para regras de cálculo)

7. Gere relatório de cobertura:
   pytest --cov=src --cov=api --cov-report=html
   echo 'Relatório em htmlcov/index.html'

Confirme com: echo 'CONSOLIDACAO CONCLUIDA'
"

run_module 28 "
Execute a validação final e atualização de documentação:

1. Construa o frontend e verifique zero erros TypeScript:
   cd frontend && npm run build
   Se houver erros: corrija todos antes de continuar

2. Atualize o README.md:
   - Remover QUALQUER caminho pessoal restante
   - Atualizar a tabela de métricas (testes, cobertura, módulos, endpoints)
   - Atualizar a seção 'O que já existe' para incluir todos os módulos novos
   - Adicionar seção 'Configuração' com instrução da API_KEY e variáveis de ambiente
   - Adicionar seção 'Tabelas de Referência' explicando como atualizar os YAMLs

3. Atualize o PRD - CLAUDE.txt:
   - Marcar todos os módulos implementados com [x]
   - Atualizar contagem de regras (de 121 para o novo total)
   - Atualizar contagem de testes

4. Rode o teste end-to-end completo:
   pytest tests/test_e2e.py -v --tb=short

5. Verifique o Docker Compose:
   docker-compose config  (valida a sintaxe)
   Se docker disponível: docker-compose build --no-cache

6. Gere o sumário final com:
   echo '========================================='
   echo 'IMPLEMENTAÇÃO PRD v3.0 CONCLUÍDA'
   echo '========================================='
   python -m src.rules --check | tail -5
   pytest --tb=no -q 2>&1 | tail -3
   echo '========================================='

Confirme com: echo 'PRD_v3_COMPLETO'
"

echo "" | tee -a "$LOG_FILE"
echo "=============================================" | tee -a "$LOG_FILE"
echo "Todos os módulos executados." | tee -a "$LOG_FILE"
echo "Log completo em: $LOG_FILE" | tee -a "$LOG_FILE"
echo "$(date)" | tee -a "$LOG_FILE"
echo "=============================================" | tee -a "$LOG_FILE"
