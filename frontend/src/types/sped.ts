export interface FileInfo {
  id: number
  filename: string
  hash_sha256: string
  upload_date: string | null
  period_start: string | null
  period_end: string | null
  company_name: string | null
  cnpj: string | null
  uf: string | null
  total_records: number
  total_errors: number
  status: string
}

export interface RecordInfo {
  id: number
  file_id: number
  line_number: number
  register: string
  block: string
  fields_json: string
  raw_line: string
  status: string
}

export interface ValidationError {
  id: number
  file_id: number
  line_number: number
  register: string
  field_no: number | null
  field_name: string | null
  value: string | null
  error_type: string
  severity: string
  message: string
  status: string
}

export interface ErrorSummary {
  total: number
  by_type: Record<string, number>
  by_severity: Record<string, number>
}

export interface ValidationResponse {
  file_id: number
  total_errors: number
  status: string
}
