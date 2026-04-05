import type { ErrorSummary, FileInfo, GeneratedRule, PipelineEvent, RecordInfo, RuleSummary, StructuredReport, ValidationError, ValidationResponse } from '../types/sped'

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
  uploadFile: async (file: File): Promise<{ file_id: number; total_records: number; status: string }> => {
    const form = new FormData()
    form.append('file', file)
    return request('/files/upload', { method: 'POST', body: form })
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
    es.addEventListener('auto_correction', (e) => {
      onEvent({ type: 'auto_correction', ...JSON.parse(e.data) })
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

  getErrors: (fileId: number, params?: Record<string, string>) => {
    const qs = params ? '?' + new URLSearchParams(params).toString() : ''
    return request<ValidationError[]>(`/files/${fileId}/errors${qs}`)
  },
  getSummary: (fileId: number) => request<ErrorSummary>(`/files/${fileId}/summary`),

  dismissError: (fileId: number, errorId: number) =>
    request<{ dismissed: boolean; total_errors: number }>(`/files/${fileId}/errors/${errorId}`, { method: 'DELETE' }),

  dismissAllErrors: (fileId: number) =>
    request<{ dismissed: number; total_errors: number }>(`/files/${fileId}/errors`, { method: 'DELETE' }),

  // Records
  getRecords: (fileId: number, params?: Record<string, string>) => {
    const qs = params ? '?' + new URLSearchParams(params).toString() : ''
    return request<RecordInfo[]>(`/files/${fileId}/records${qs}`)
  },
  updateRecord: (fileId: number, recordId: number, data: { field_no: number; field_name: string; new_value: string; error_id?: number }) =>
    request<{ corrected: boolean }>(`/files/${fileId}/records/${recordId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
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

  // Report
  getStructuredReport: (fileId: number) => request<StructuredReport>(`/files/${fileId}/report/structured`),
  getReport: async (fileId: number, format: string = 'md'): Promise<string> => {
    const res = await fetch(`${BASE}/files/${fileId}/report?format=${format}`)
    return res.text()
  },
  downloadSped: (fileId: number) => `${BASE}/files/${fileId}/download`,
}
