import type { AuditScope, AuditScopeRaw, CorrectionSuggestion, CrossValidationItem, ErrorSummary, FileInfo, GeneratedRule, PipelineEvent, RecordInfo, RuleSummary, SearchResult, StructuredReport, ValidationError, ValidationResponse } from '../types/sped'

const BASE = '/api'

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, options)
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

  // Validation
  validate: (fileId: number) => request<ValidationResponse>(`/files/${fileId}/validate`, { method: 'POST' }),

  validateStream: (fileId: number, onEvent: (event: PipelineEvent) => void): EventSource => {
    const es = new EventSource(`${BASE}/files/${fileId}/validate/stream`)

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
    return {
      coverage_pct: raw.cobertura_estimada_pct,
      checks: raw.checks_executados.map(c => ({
        name: c.id.replace(/_/g, ' '),
        status: statusMap[c.status] || 'not_run',
        detail: c.motivo_parcial,
      })),
      missing_tables: Object.entries(raw.tabelas_externas)
        .filter(([, v]) => v === 'indisponivel')
        .map(([k]) => k),
    }
  },

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
    const res = await fetch(`${BASE}/files/${fileId}/report?format=${format}`)
    return res.text()
  },
  downloadSped: (fileId: number) => `${BASE}/files/${fileId}/download`,
}
