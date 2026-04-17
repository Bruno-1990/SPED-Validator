import type { AuditScope, AuditScopeRaw, CorrectionSuggestion, CrossValidationItem, ErrorSummary, FileInfo, GeneratedRule, PipelineEvent, RecordInfo, RuleSummary, SearchResult, StructuredReport, ValidationError, ValidationResponse } from '../types/sped'

/** Base da API: igual ao proxy (`/api`) ou valor de `VITE_API_BASE` no build. */
export const API_BASE = (import.meta.env.VITE_API_BASE || '/api').replace(/\/$/, '') || '/api'

/** Chave alinhada ao `API_KEY` do backend — defina `VITE_API_KEY` em `.env.local`. */
const API_KEY =
  (import.meta.env.VITE_API_KEY && String(import.meta.env.VITE_API_KEY).trim()) ||
  'sped-audit-dev-key-2026-central-contabil'

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers)
  headers.set('X-API-Key', API_KEY)
  const res = await fetch(`${API_BASE}${url}`, { ...options, headers })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(error.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export const api = {
  // Files
  uploadFile: async (file: File, regime?: string): Promise<{ file_id: number; total_records: number; status: string }> => {
    const form = new FormData()
    form.append('file', file)
    const qs = regime ? `?regime=${regime}` : ''
    return request(`/files/upload${qs}`, { method: 'POST', body: form })
  },
  listFiles: () => request<FileInfo[]>('/files'),
  getFile: (id: number) => request<FileInfo>(`/files/${id}`),
  deleteFile: (id: number) => request<{ deleted: boolean }>(`/files/${id}`, { method: 'DELETE' }),
  clearAudit: (id: number) => request<{ cleared: boolean; removed: number }>(`/files/${id}/audit`, { method: 'DELETE' }),
  clearAllAudit: () => request<{ cleared: boolean; removed: number }>('/files/audit', { method: 'DELETE' }),

  // Validation (mode: sped_only default | sped_xml — exige XMLs ativos)
  validate: (fileId: number, mode: 'sped_only' | 'sped_xml' = 'sped_only') => {
    const qs = mode !== 'sped_only' ? `?mode=${encodeURIComponent(mode)}` : ''
    return request<ValidationResponse>(`/files/${fileId}/validate${qs}`, { method: 'POST' })
  },

  validateStream: (
    fileId: number,
    onEvent: (event: PipelineEvent) => void,
    opts?: { mode?: 'sped_only' | 'sped_xml' },
  ): EventSource => {
    const mode = opts?.mode && opts.mode !== 'sped_only' ? `&mode=${encodeURIComponent(opts.mode)}` : ''
    const es = new EventSource(`${API_BASE}/files/${fileId}/validate/stream?api_key=${encodeURIComponent(API_KEY)}${mode}`)

    es.addEventListener('progress', (e) => {
      onEvent({ type: 'progress', ...JSON.parse(e.data) })
    })
    es.addEventListener('stage_complete', (e) => {
      onEvent({ type: 'stage_complete', ...JSON.parse(e.data) })
    })
    es.addEventListener('done', (e) => {
      onEvent({ type: 'done', ...JSON.parse(e.data) })
      es.close()
    })
    es.addEventListener('error', (e) => {
      if (e instanceof MessageEvent) {
        onEvent({ type: 'error', error: JSON.parse(e.data).error })
        es.close()
      }
      // Erros de conexao: nao fechar — EventSource reconecta automaticamente
    })

    return es
  },

  getErrors: async (fileId: number, params?: Record<string, string>): Promise<ValidationError[]> => {
    const qs = params ? '?' + new URLSearchParams(params).toString() : ''
    const res = await request<{ total: number; page: number; page_size: number; has_next: boolean; data: ValidationError[] }>(`/files/${fileId}/errors${qs}`)
    return res.data
  },
  getSummary: (fileId: number) => request<ErrorSummary>(`/files/${fileId}/summary`),

  dismissError: (fileId: number, errorId: number) =>
    request<{ dismissed: boolean; total_errors: number }>(`/files/${fileId}/errors/${errorId}`, { method: 'DELETE' }),

  dismissAllErrors: (fileId: number) =>
    request<{ dismissed: number; total_errors: number }>(`/files/${fileId}/errors`, { method: 'DELETE' }),

  dismissErrorGroup: (fileId: number, errorType: string) =>
    request<{ dismissed: number; error_type: string; total_errors: number }>(`/files/${fileId}/errors/group/${encodeURIComponent(errorType)}`, { method: 'DELETE' }),

  // Records
  getRecords: async (fileId: number, params?: Record<string, string>): Promise<RecordInfo[]> => {
    const qs = params ? '?' + new URLSearchParams(params).toString() : ''
    const res = await request<{ total: number; data: RecordInfo[] }>(`/files/${fileId}/records${qs}`)
    return res.data
  },
  getRecord: (fileId: number, recordId: number) =>
    request<RecordInfo>(`/files/${fileId}/records/${recordId}`),
  updateRecord: (fileId: number, recordId: number, data: { field_no: number; field_name: string; new_value: string; error_id?: number; justificativa?: string; correction_type?: string; rule_id?: string }) =>
    request<{ corrected: boolean }>(`/files/${fileId}/records/${recordId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),

  // Correction approval: approve a suggested correction
  approveCorrection: (fileId: number, suggestion: CorrectionSuggestion, justificativa: string) =>
    request<{ corrected: boolean }>(`/files/${fileId}/records/${suggestion.record_id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        field_no: suggestion.field_no,
        field_name: suggestion.field_name,
        new_value: suggestion.expected_value,
        error_id: suggestion.error_id,
        justificativa,
        correction_type: 'assisted',
        rule_id: suggestion.error_type,
      }),
    }),

  // Rules
  listRules: () => request<RuleSummary[]>('/rules'),
  generateRule: (description: string) => request<GeneratedRule>('/rules/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ description }),
  }),
  implementRule: (rule: GeneratedRule) => request<{ added: boolean; rule_id: string }>('/rules/implement', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ rule }),
  }),

  // Finding resolutions (workflow aceitar/rejeitar/postergar)
  resolveFinding: (fileId: number, findingId: number, body: { status: string; rule_id: string; justificativa?: string; user_id?: string; prazo_revisao?: string }) =>
    request<{ resolved: boolean; finding_id: number; status: string }>(`/files/${fileId}/findings/${findingId}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  getResolutions: (fileId: number) =>
    request<Array<{ id: number; file_id: string; finding_id: string; rule_id: string; status: string; justificativa: string | null; prazo_revisao: string | null; resolved_at: string }>>(`/files/${fileId}/findings/resolutions`),

  // Cross-validation errors
  getCrossValidation: async (fileId: number, tipo?: string): Promise<CrossValidationItem[]> => {
    const params: Record<string, string> = { categoria: 'cruzamento' }
    if (tipo) params.tipo = tipo
    const res = await request<{ total: number; data: CrossValidationItem[] }>(`/files/${fileId}/errors?${new URLSearchParams(params)}`)
    return res.data
  },

  // Audit scope
  getAuditScope: async (fileId: number): Promise<AuditScope> => {
    const raw = await request<AuditScopeRaw>(`/files/${fileId}/audit-scope`)
    const statusMap: Record<string, 'ok' | 'partial' | 'not_run' | 'not_applicable'> = {
      ok: 'ok', parcial: 'partial', nao_executado: 'not_run', nao_aplicavel: 'not_applicable',
    }
    const nameMap: Record<string, string> = {
      format_validation: 'Validação de Formato',
      field_validation: 'Validação de Campos',
      intra_register: 'Validação Intra-registro',
      cross_block: 'Cruzamento entre Blocos',
      tax_recalculation: 'Recálculo Tributário',
      cst_validation: 'Validação de CST',
      fiscal_semantics: 'Semântica Fiscal',
      benefit_audit: 'Auditoria de Benefícios',
      aliquota_validation: 'Validação de Alíquotas',
      c190_consolidation: 'Consolidação C190',
      difal_validation: 'Validação DIFAL',
      simples_nacional: 'Simples Nacional',
      apuracao_icms: 'Apuração ICMS',
      beneficio_cross: 'Cruzamento de Benefícios',
      base_calculo: 'Base de Cálculo',
      bloco_d: 'Bloco D (Transporte)',
      cfop_validation: 'Validação de CFOP',
      devolucao: 'Devoluções',
      ipi_validation: 'Validação de IPI',
      destinatario: 'Destinatário',
      st_validation: 'Substituição Tributária',
      parametrizacao: 'Parametrização',
      ncm_validation: 'Validação de NCM',
      pis_cofins: 'PIS/COFINS',
      pendentes: 'Pendentes',
      bloco_k: 'Bloco K (Produção)',
      bloco_c_servicos: 'Bloco C (Serviços)',
      retificador: 'Retificador',
      xml_crossref: 'Cruzamento XML x SPED (NF-e)',
    }
    return {
      coverage_pct: raw.cobertura_estimada_pct,
      checks: raw.checks_executados.map(c => ({
        name: nameMap[c.id] || c.id.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()),
        status: statusMap[c.status] || 'not_run',
        detail: c.motivo_parcial,
      })),
      missing_tables: Object.entries(raw.tabelas_externas)
        .filter(([, v]) => v === 'indisponivel')
        .map(([k]) => k),
    }
  },

  // Clientes (MySQL DCTF_WEB)
  buscarCliente: (cnpj: string) => request<{
    cnpj: string
    razao_social: string
    fantasia: string
    regime_tributario: string
    beneficios_fiscais: string[]
    simples_optante: boolean
    uf: string
    tipo_empresa: string
    porte: string
    situacao_cadastral: string
  }>(`/clientes/cnpj/${cnpj.replace(/\D/g, '')}`),

  // Search
  searchDocs: (query: string, fieldName?: string, register?: string, topK: number = 5) => {
    const params = new URLSearchParams({ q: query, top_k: String(topK) })
    if (register) params.set('register', register)
    if (fieldName) params.set('field_name', fieldName)
    return request<SearchResult[]>(`/search?${params}`)
  },

  // Report
  getStructuredReport: (fileId: number) => request<StructuredReport>(`/files/${fileId}/report/structured`),
  getReport: async (fileId: number, format: string = 'md'): Promise<string> => {
    const res = await fetch(`${API_BASE}/files/${fileId}/report?format=${format}`, {
      headers: { 'X-API-Key': API_KEY },
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.text()
  },
  /** URL para `<a href>` / `window.open` — inclui `api_key` (SSE/download não enviam header). */
  downloadSped: (fileId: number) =>
    `${API_BASE}/files/${fileId}/download?api_key=${encodeURIComponent(API_KEY)}`,

  // XML NF-e cross-reference
  uploadXmls: async (fileId: number, files: File[], modoPeriodo?: string): Promise<{
    status?: string; total: number; autorizadas: number; canceladas: number; duplicadas: number; invalidos: number;
    fora_periodo?: {filename: string; chave_nfe: string; dh_emissao: string}[];
    dentro_periodo_count?: number; period_start_fmt?: string; period_end_fmt?: string;
  }> => {
    const form = new FormData()
    files.forEach(f => form.append('files', f))
    const qs = modoPeriodo ? `?modo_periodo=${modoPeriodo}` : ''
    return request(`/files/${fileId}/xml/upload${qs}`, { method: 'POST', body: form })
  },
  listXmls: (fileId: number) => request<{file_id: number; total: number; autorizadas: number; canceladas: number; xmls: any[]}>(`/files/${fileId}/xml`),
  cruzarXml: (fileId: number) => request<{file_id: number; xmls_analisados: number; divergencias: number; por_severidade: Record<string, number>}>(`/files/${fileId}/xml/cruzar`, { method: 'POST' }),
  cruzarXmlStream: (fileId: number, onProgress: (pct: number, msg: string) => void, onDone: (result: {divergencias: number; por_severidade: Record<string, number>; total_erros_fiscal?: number; pipeline_completo?: boolean; status?: string}) => void, onError?: (err: string) => void): EventSource => {
    const es = new EventSource(`${API_BASE}/files/${fileId}/xml/cruzar/stream?api_key=${encodeURIComponent(API_KEY)}`)
    es.addEventListener('progress', (e) => {
      const d = JSON.parse(e.data)
      onProgress(d.pct, d.msg)
    })
    es.addEventListener('done', (e) => {
      const d = JSON.parse(e.data)
      onDone(d)
      es.close()
    })
    // Erros do servidor: evento dedicado (evita confundir com o `error` nativo ao encerrar o stream).
    es.addEventListener('cruzar_error', (e) => {
      try {
        const d = JSON.parse((e as MessageEvent).data)
        onError?.(d.error ?? 'Erro no cruzamento')
      } catch {
        onError?.('Erro no cruzamento')
      }
      es.close()
    })
    return es
  },
  getCruzamento: (fileId: number, ruleId?: string, severity?: string) => {
    const params = new URLSearchParams()
    if (ruleId) params.set('rule_id', ruleId)
    if (severity) params.set('severity', severity)
    const qs = params.toString() ? `?${params}` : ''
    return request<{file_id: number; total: number; divergencias: any[]}>(`/files/${fileId}/xml/cruzamento${qs}`)
  },
  deleteXml: (fileId: number, xmlId: number) => request<{deleted: boolean}>(`/files/${fileId}/xml/${xmlId}`, { method: 'DELETE' }),

  // AI explanation
  explainError: (data: {error_type: string; message: string; regime?: string; uf?: string; register?: string; severity?: string; value?: string; expected_value?: string}) =>
    request<{explicacao: string; sugestao: string; cached: boolean; hits?: number}>('/ai/explain', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data) }),
  aiCacheStats: () => request<{total_entries: number; total_hits: number; model: string}>('/ai/cache/stats'),

  // AI review (tribunal de validacao)
  reviewErrorGroup: (fileId: number, errorType: string) =>
    request<{
      veredito: 'valido' | 'falso_positivo' | 'inconclusivo'
      justificativa: string
      dados_sustentacao: string
      recomendacao: string
      amostras_analisadas: number
      cached: boolean
    }>(`/ai/review/${fileId}/${encodeURIComponent(errorType)}`, { method: 'POST' }),
}
