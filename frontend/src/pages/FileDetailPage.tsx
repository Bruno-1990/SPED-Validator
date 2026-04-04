import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, Link, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { ErrorSummary, FileInfo, LegalBasis, PipelineEvent, ValidationError } from '../types/sped'

const STAGE_LABELS: Record<string, string> = {
  estrutural: 'Analise Estrutural',
  cruzamento: 'Cruzamento de Dados',
  enriquecimento: 'Consultando Base Legal',
  auto_correcao: 'Correcao Automatica',
  concluido: 'Concluido',
}

const STAGE_ORDER = ['estrutural', 'cruzamento', 'enriquecimento', 'auto_correcao']

const SEVERITY_LABELS: Record<string, string> = {
  critical: 'Critico',
  error: 'Erro',
  warning: 'Aviso',
}

export default function FileDetailPage() {
  const { fileId } = useParams<{ fileId: string }>()
  const [searchParams] = useSearchParams()
  const autoValidate = searchParams.get('validate') === '1'
  const id = Number(fileId)
  const [file, setFile] = useState<FileInfo | null>(null)
  const [summary, setSummary] = useState<ErrorSummary | null>(null)
  const [errors, setErrors] = useState<ValidationError[]>([])
  const [validating, setValidating] = useState(false)
  const [tab, setTab] = useState<'summary' | 'errors' | 'report'>('summary')
  const [pipelineEvent, setPipelineEvent] = useState<PipelineEvent | null>(null)
  const [expandedError, setExpandedError] = useState<number | null>(null)
  const eventSourceRef = useRef<EventSource | null>(null)

  const loadData = useCallback(async () => {
    const f = await api.getFile(id)
    setFile(f)
    if (f.status === 'validated') {
      const [s, e] = await Promise.all([api.getSummary(id), api.getErrors(id)])
      setSummary(s)
      setErrors(e)
    }
  }, [id])

  useEffect(() => { loadData() }, [loadData])

  // Auto-validar se veio do upload
  const autoValidatedRef = useRef(false)
  useEffect(() => {
    if (autoValidate && file && file.status === 'parsed' && !autoValidatedRef.current) {
      autoValidatedRef.current = true
      handleValidateStream()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoValidate, file])

  const handleValidateStream = useCallback(() => {
    setValidating(true)
    setPipelineEvent(null)
    setErrors([])
    setSummary(null)

    if (eventSourceRef.current) {
      eventSourceRef.current.close()
    }

    const es = api.validateStream(id, (event: PipelineEvent) => {
      setPipelineEvent(event)

      if (event.type === 'done') {
        setValidating(false)
        setTab('errors')
        // Recarregar dados completos
        loadData()
      } else if (event.type === 'error') {
        setValidating(false)
      }
    })

    eventSourceRef.current = es
  }, [id, loadData])

  // Limpar EventSource ao desmontar
  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
      }
    }
  }, [])

  const handleAutoCorrectAll = useCallback(async () => {
    // Revalidar para aplicar auto-correções pendentes
    handleValidateStream()
  }, [handleValidateStream])

  if (!file) return <p className="text-gray-500">Carregando...</p>

  const conformidade = file.total_records > 0
    ? ((file.total_records - file.total_errors) / file.total_records * 100).toFixed(1)
    : '100.0'

  const autoCorrectableCount = errors.filter(e => e.auto_correctable && e.status === 'open').length

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <Link to="/files" className="text-sm text-blue-600 hover:underline">&larr; Voltar</Link>
          <h2 className="text-2xl font-bold">{file.company_name || file.filename}</h2>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-gray-500 mt-1">
            {file.cnpj && (
              <span>CNPJ: <span className="font-mono">{formatCnpj(file.cnpj)}</span></span>
            )}
            {file.uf && <span>UF: {file.uf}</span>}
            {file.period_start && file.period_end && (
              <span>Periodo: {formatDate(file.period_start)} a {formatDate(file.period_end)}</span>
            )}
            <span className="text-gray-400">Arquivo: {file.filename}</span>
          </div>
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleValidateStream}
            disabled={validating}
            className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {validating ? 'Validando...' : file.status === 'validated' ? 'Revalidar' : 'Validar'}
          </button>
          {file.status === 'validated' && (
            <a
              href={api.downloadSped(id)}
              className="bg-green-600 text-white px-4 py-2 rounded hover:bg-green-700"
            >
              Baixar SPED
            </a>
          )}
        </div>
      </div>

      {/* Score cards */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        <div className="bg-white p-4 rounded shadow">
          <p className="text-sm text-gray-500">Registros</p>
          <p className="text-2xl font-bold">{file.total_records}</p>
        </div>
        <div className="bg-white p-4 rounded shadow">
          <p className="text-sm text-gray-500">Apontamentos</p>
          <p className={`text-2xl font-bold ${file.total_errors > 0 ? 'text-red-600' : 'text-green-600'}`}>
            {pipelineEvent?.total_errors ?? file.total_errors}
          </p>
        </div>
        <div className="bg-white p-4 rounded shadow">
          <p className="text-sm text-gray-500">Conformidade</p>
          <p className="text-2xl font-bold">{conformidade}%</p>
        </div>
        <div className="bg-white p-4 rounded shadow">
          <p className="text-sm text-gray-500">Status</p>
          <p className={`text-2xl font-bold ${
            validating ? 'text-blue-600' :
            file.status === 'validated' ? 'text-green-600' :
            ''
          }`}>
            {validating ? 'Validando...' : file.status === 'validated' ? 'Validado' : file.status}
          </p>
        </div>
      </div>

      {/* Pipeline Progress */}
      {validating && pipelineEvent && (
        <PipelineProgressPanel event={pipelineEvent} />
      )}

      {/* Tabs */}
      {(file.status === 'validated' || errors.length > 0) && !validating && (
        <>
          <div className="flex gap-4 border-b mb-4">
            {(['summary', 'errors', 'report'] as const).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`pb-2 px-1 text-sm ${tab === t ? 'border-b-2 border-blue-600 font-semibold' : 'text-gray-500'}`}
              >
                {t === 'summary' ? 'Resumo' : t === 'errors' ? 'Apontamentos' : 'Relatorio'}
              </button>
            ))}
          </div>

          {tab === 'summary' && summary && <SummaryTab summary={summary} />}
          {tab === 'errors' && (
            <ErrorsTab
              errors={errors}
              expandedError={expandedError}
              onToggleExpand={setExpandedError}
              autoCorrectableCount={autoCorrectableCount}
              onAutoCorrectAll={handleAutoCorrectAll}
              fileId={id}
              onReload={loadData}
            />
          )}
          {tab === 'report' && <ReportTab fileId={id} />}
        </>
      )}
    </div>
  )
}


// ── Pipeline Progress Panel ──

function PipelineProgressPanel({ event }: { event: PipelineEvent }) {
  const currentStageIdx = STAGE_ORDER.indexOf(event.stage || '')

  return (
    <div className="bg-white rounded shadow p-6 mb-6">
      <h3 className="font-semibold mb-4">Pipeline de Validacao</h3>
      <div className="space-y-3">
        {STAGE_ORDER.map((stage, idx) => {
          const isDone = idx < currentStageIdx || event.stage === 'concluido'
          const isCurrent = stage === event.stage
          const errorsForStage = event.errors_by_stage?.[stage]

          return (
            <div key={stage} className="flex items-center gap-3">
              {/* Icon */}
              <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${
                isDone ? 'bg-green-500 text-white' :
                isCurrent ? 'bg-blue-500 text-white animate-pulse' :
                'bg-gray-200 text-gray-400'
              }`}>
                {isDone ? '\u2713' : isCurrent ? '\u25CF' : (idx + 1)}
              </div>

              {/* Label */}
              <span className={`flex-1 text-sm ${isCurrent ? 'font-semibold' : isDone ? 'text-gray-600' : 'text-gray-400'}`}>
                {STAGE_LABELS[stage]}
              </span>

              {/* Progress or count */}
              <span className="text-sm text-gray-500 w-32 text-right">
                {isDone && errorsForStage !== undefined && (
                  <span className={errorsForStage > 0 ? 'text-red-600 font-semibold' : 'text-green-600'}>
                    {errorsForStage} apontamento{errorsForStage !== 1 ? 's' : ''}
                  </span>
                )}
                {isCurrent && event.stage_progress !== undefined && (
                  <span className="text-blue-600">{event.stage_progress}%</span>
                )}
                {!isDone && !isCurrent && '\u2014'}
              </span>
            </div>
          )
        })}
      </div>

      {/* Progress bar */}
      <div className="mt-4 bg-gray-200 rounded-full h-2">
        <div
          className="bg-blue-600 h-2 rounded-full transition-all duration-300"
          style={{
            width: `${event.stage === 'concluido' ? 100 :
              ((currentStageIdx + (event.stage_progress || 0) / 100) / STAGE_ORDER.length) * 100}%`
          }}
        />
      </div>

      {/* Auto-correction result */}
      {event.auto_corrected && event.auto_corrected > 0 && (
        <div className="mt-3 bg-green-50 text-green-700 text-sm p-2 rounded">
          {event.auto_corrected} apontamento{event.auto_corrected !== 1 ? 's' : ''} corrigido{event.auto_corrected !== 1 ? 's' : ''} automaticamente
        </div>
      )}
    </div>
  )
}


// ── Summary Tab ──

function SummaryTab({ summary }: { summary: ErrorSummary }) {
  return (
    <div className="grid grid-cols-2 gap-6">
      <div>
        <h3 className="font-semibold mb-2">Por Tipo</h3>
        <table className="w-full text-sm">
          <tbody>
            {Object.entries(summary.by_type).sort((a, b) => b[1] - a[1]).map(([type, count]) => (
              <tr key={type} className="border-t">
                <td className="p-2 font-mono">{type}</td>
                <td className="p-2 text-right font-semibold">{count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <h3 className="font-semibold mb-2">Por Severidade</h3>
        <table className="w-full text-sm">
          <tbody>
            {Object.entries(summary.by_severity).map(([sev, count]) => (
              <tr key={sev} className="border-t">
                <td className="p-2">
                  <SeverityBadge severity={sev} />
                </td>
                <td className="p-2 text-right font-semibold">{count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}


// ── Errors Tab ──

interface ErrorsTabProps {
  errors: ValidationError[]
  expandedError: number | null
  onToggleExpand: (id: number | null) => void
  autoCorrectableCount: number
  onAutoCorrectAll: () => void
  fileId: number
  onReload: () => void
}

function ErrorsTab({ errors, expandedError, onToggleExpand, autoCorrectableCount, onAutoCorrectAll, fileId, onReload }: ErrorsTabProps) {
  const openErrors = errors.filter(e => e.status === 'open')

  const handleManualCorrect = async (error: ValidationError) => {
    if (!error.expected_value || !error.field_no) return
    try {
      await api.updateRecord(fileId, error.id, {
        field_no: error.field_no,
        field_name: error.field_name || '',
        new_value: error.expected_value,
        error_id: error.id,
      })
      onReload()
    } catch {
      // silently fail
    }
  }

  const handleDismiss = async (errorId: number) => {
    try {
      await api.dismissError(fileId, errorId)
      onReload()
    } catch {
      // silently fail
    }
  }

  const handleDismissAll = async () => {
    if (!confirm(`Ignorar todos os ${openErrors.length} apontamentos abertos?`)) return
    try {
      await api.dismissAllErrors(fileId)
      onReload()
    } catch {
      // silently fail
    }
  }

  return (
    <div>
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-3 mb-4">
        {autoCorrectableCount > 0 && (
          <div className="flex items-center gap-3 bg-blue-50 p-3 rounded">
            <span className="text-sm text-blue-700">
              {autoCorrectableCount} apontamento{autoCorrectableCount !== 1 ? 's' : ''} pode{autoCorrectableCount === 1 ? '' : 'm'} ser corrigido{autoCorrectableCount !== 1 ? 's' : ''} automaticamente
            </span>
            <button
              onClick={onAutoCorrectAll}
              className="bg-blue-600 text-white px-3 py-1 rounded text-sm hover:bg-blue-700"
            >
              Corrigir Todos
            </button>
          </div>
        )}
        {openErrors.length > 0 && (
          <button
            onClick={handleDismissAll}
            className="text-sm text-gray-500 px-3 py-1 rounded border border-gray-300 hover:bg-gray-100"
          >
            Ignorar Todos ({openErrors.length})
          </button>
        )}
      </div>

      {/* Error cards */}
      <div className="space-y-2">
        {errors.map((e) => (
          <ErrorCard
            key={e.id}
            error={e}
            expanded={expandedError === e.id}
            onToggle={() => onToggleExpand(expandedError === e.id ? null : e.id)}
            onCorrect={() => handleManualCorrect(e)}
            onDismiss={() => handleDismiss(e.id)}
          />
        ))}
      </div>

      {errors.length === 0 && (
        <p className="text-gray-500 text-center py-8">Nenhum apontamento encontrado.</p>
      )}
    </div>
  )
}


// ── Error Card ──

function ErrorCard({
  error,
  expanded,
  onToggle,
  onCorrect,
  onDismiss,
}: {
  error: ValidationError
  expanded: boolean
  onToggle: () => void
  onCorrect: () => void
  onDismiss: () => void
}) {
  const displayMessage = error.friendly_message || error.message
  const legalBasis = parseLegalBasis(error.legal_basis)
  const isCorrected = error.status === 'corrected'

  return (
    <div className={`bg-white rounded shadow border-l-4 ${
      isCorrected ? 'border-green-400 opacity-60' :
      error.severity === 'critical' ? 'border-red-500' :
      error.severity === 'warning' ? 'border-yellow-500' :
      'border-orange-500'
    }`}>
      {/* Header - always visible */}
      <div
        className="flex items-start gap-3 p-4 cursor-pointer hover:bg-gray-50"
        onClick={onToggle}
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="font-mono text-xs text-gray-500">Linha {error.line_number}</span>
            <span className="font-mono text-xs bg-gray-100 px-1.5 py-0.5 rounded">{error.register}</span>
            {error.field_name && (
              <span className="text-xs text-gray-500">{error.field_name}</span>
            )}
            <SeverityBadge severity={error.severity} />
            {isCorrected && (
              <span className="px-2 py-0.5 rounded text-xs bg-green-100 text-green-700">Corrigido</span>
            )}
          </div>
          <p className="text-sm text-gray-800">{displayMessage}</p>
        </div>

        {/* Actions */}
        <div className="flex gap-1 flex-shrink-0">
          {error.auto_correctable && !isCorrected && error.expected_value && (
            <button
              onClick={(ev) => { ev.stopPropagation(); onCorrect() }}
              className="text-xs bg-green-50 text-green-700 px-2 py-1 rounded hover:bg-green-100"
            >
              Corrigir
            </button>
          )}
          {!isCorrected && (
            <button
              onClick={(ev) => { ev.stopPropagation(); onDismiss() }}
              className="text-xs text-gray-400 px-2 py-1 rounded hover:bg-gray-100 hover:text-gray-600"
              title="Ignorar este apontamento"
            >
              Ignorar
            </button>
          )}
          <button
            onClick={(ev) => { ev.stopPropagation(); onToggle() }}
            className="text-xs text-gray-400 px-2 py-1 hover:text-gray-600"
          >
            {expanded ? '\u25B2' : '\u25BC'}
          </button>
        </div>
      </div>

      {/* Expanded details */}
      {expanded && (
        <div className="border-t px-4 pb-4 pt-3 space-y-3 bg-gray-50">
          {/* Technical details */}
          <div className="grid grid-cols-3 gap-4 text-xs">
            <div>
              <span className="text-gray-500">Tipo:</span>{' '}
              <span className="font-mono">{error.error_type}</span>
            </div>
            {error.value && (
              <div>
                <span className="text-gray-500">Valor atual:</span>{' '}
                <span className="font-mono text-red-600">{error.value}</span>
              </div>
            )}
            {error.expected_value && (
              <div>
                <span className="text-gray-500">Valor correto:</span>{' '}
                <span className="font-mono text-green-600">{error.expected_value}</span>
              </div>
            )}
          </div>

          {/* Original technical message */}
          {error.friendly_message && error.message !== error.friendly_message && (
            <div className="text-xs text-gray-500">
              <span className="font-semibold">Detalhe tecnico:</span> {error.message}
            </div>
          )}

          {/* Legal basis */}
          {legalBasis && (
            <div className="bg-white border rounded p-3">
              <h4 className="text-xs font-semibold text-gray-700 mb-1">Base Legal</h4>
              <p className="text-sm font-medium text-blue-800">{legalBasis.fonte}</p>
              {legalBasis.artigo && (
                <p className="text-xs text-gray-600">{legalBasis.artigo}</p>
              )}
              {legalBasis.trecho && (
                <blockquote className="mt-2 text-xs text-gray-600 border-l-2 border-blue-300 pl-3 italic">
                  {legalBasis.trecho.length > 300
                    ? legalBasis.trecho.substring(0, 300) + '...'
                    : legalBasis.trecho}
                </blockquote>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}


// ── Severity Badge ──

function SeverityBadge({ severity }: { severity: string }) {
  const label = SEVERITY_LABELS[severity] || severity
  return (
    <span className={`px-2 py-0.5 rounded text-xs ${
      severity === 'critical' ? 'bg-red-100 text-red-700' :
      severity === 'warning' ? 'bg-yellow-100 text-yellow-700' :
      'bg-orange-100 text-orange-700'
    }`}>
      {label}
    </span>
  )
}


// ── Report Tab ──

function ReportTab({ fileId }: { fileId: number }) {
  const [report, setReport] = useState('')
  const [format, setFormat] = useState('md')

  useEffect(() => {
    api.getReport(fileId, format).then(setReport)
  }, [fileId, format])

  return (
    <div>
      <div className="flex gap-2 mb-4">
        {['md', 'csv', 'json'].map((f) => (
          <button
            key={f}
            onClick={() => setFormat(f)}
            className={`px-3 py-1 rounded text-sm ${format === f ? 'bg-blue-600 text-white' : 'bg-gray-200'}`}
          >
            {f.toUpperCase()}
          </button>
        ))}
      </div>
      <pre className="bg-gray-900 text-gray-100 p-4 rounded overflow-auto text-xs max-h-[600px]">
        {report}
      </pre>
    </div>
  )
}


// ── Helpers ──

function parseLegalBasis(raw: string | null): LegalBasis | null {
  if (!raw) return null
  try {
    return JSON.parse(raw) as LegalBasis
  } catch {
    return null
  }
}

function formatCnpj(cnpj: string): string {
  const digits = cnpj.replace(/\D/g, '')
  if (digits.length !== 14) return cnpj
  return `${digits.slice(0, 2)}.${digits.slice(2, 5)}.${digits.slice(5, 8)}/${digits.slice(8, 12)}-${digits.slice(12)}`
}

function formatDate(date: string): string {
  // DDMMAAAA -> DD/MM/AAAA
  if (date.length === 8 && /^\d+$/.test(date)) {
    return `${date.slice(0, 2)}/${date.slice(2, 4)}/${date.slice(4)}`
  }
  return date
}
