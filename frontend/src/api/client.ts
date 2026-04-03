import type { ErrorSummary, FileInfo, RecordInfo, ValidationError, ValidationResponse } from '../types/sped'

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

  // Validation
  validate: (fileId: number) => request<ValidationResponse>(`/files/${fileId}/validate`, { method: 'POST' }),
  getErrors: (fileId: number, params?: Record<string, string>) => {
    const qs = params ? '?' + new URLSearchParams(params).toString() : ''
    return request<ValidationError[]>(`/files/${fileId}/errors${qs}`)
  },
  getSummary: (fileId: number) => request<ErrorSummary>(`/files/${fileId}/summary`),

  // Records
  getRecords: (fileId: number, params?: Record<string, string>) => {
    const qs = params ? '?' + new URLSearchParams(params).toString() : ''
    return request<RecordInfo[]>(`/files/${fileId}/records${qs}`)
  },
  updateRecord: (fileId: number, recordId: number, data: { field_no: number; field_name: string; new_value: string }) =>
    request<{ corrected: boolean }>(`/files/${fileId}/records/${recordId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),

  // Report
  getReport: async (fileId: number, format: string = 'md'): Promise<string> => {
    const res = await fetch(`${BASE}/files/${fileId}/report?format=${format}`)
    return res.text()
  },
  downloadSped: (fileId: number) => `${BASE}/files/${fileId}/download`,
}
