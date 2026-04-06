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
  auto_corrections_applied: number
  cod_ver: string | null
  is_retificador: boolean | null
  original_file_id: number | null
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

export interface StructuredReport {
  metadata: {
    filename: string
    cnpj: string | null
    uf: string | null
    period_start: string | null
    period_end: string | null
    company_name: string | null
  }
  summary: {
    total_records: number
    total_errors: number
    total_warnings: number
    compliance_pct: number
    pending_suggestions: number
    applied_corrections: number
  }
  top_findings: Array<{
    error_type: string
    severity: string
    count: number
    description: string
  }>
  corrections: Array<{
    register: string
    field_name: string
    old_value: string
    new_value: string
    applied_by: string
    applied_at: string
  }>
  conclusion: string
}

export interface ValidationError {
  id: number
  file_id: number
  record_id: number | null
  line_number: number
  register: string
  field_no: number | null
  field_name: string | null
  value: string | null
  error_type: string
  severity: string
  message: string
  friendly_message: string | null
  doc_suggestion: string | null
  legal_basis: string | null
  expected_value: string | null
  auto_correctable: boolean
  status: string
  certeza: string | null
  impacto: string | null
  categoria: string | null
}

export interface SearchResult {
  source_file: string
  register: string | null
  field_name: string | null
  heading: string
  content: string
  score: number
  source: string
}

export interface LegalBasis {
  fonte: string
  artigo: string
  trecho: string
  score?: number
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

export interface RuleSummary {
  id: string
  block: string
  register: string
  error_type: string
  severity: string
  description: string
  implemented: boolean
}

export interface GeneratedRule {
  id: string
  block: string
  register: string
  fields: string[]
  error_type: string
  severity: string
  description: string
  condition: string
  module: string
  legislation: string | null
  legal_sources: Array<{
    fonte: string
    heading: string
    content: string
    register: string | null
    score: number
  }> | null
}

export interface CrossValidationItem {
  id: number
  error_type: string
  categoria: string
  register: string
  line_number: number
  dest_register: string | null
  dest_line: number | null
  value: string | null
  expected_value: string | null
  difference: number | null
  severity: string
  message: string
  friendly_message: string | null
}

export interface AuditScopeCheck {
  name: string
  status: 'ok' | 'partial' | 'not_run'
  detail: string | null
}

export interface AuditScope {
  coverage_pct: number
  checks: AuditScopeCheck[]
  missing_tables: string[]
}

export interface CorrectionSuggestion {
  error_id: number
  record_id: number
  register: string
  field_no: number
  field_name: string
  old_value: string
  expected_value: string
  error_type: string
  certeza: string | null
  impacto: string | null
  line_number: number
  message: string
  friendly_message: string | null
  decision?: 'approved' | 'rejected' | 'skipped'
}

export interface PipelineEvent {
  type: 'progress' | 'stage_complete' | 'auto_correction' | 'done' | 'error'
  stage?: string
  stage_progress?: number
  detail?: string
  total_errors?: number
  errors_by_stage?: Record<string, number>
  errors_found?: number
  corrected?: number
  auto_corrected?: number
  status?: string
  error?: string
}
