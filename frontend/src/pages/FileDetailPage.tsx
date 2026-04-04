import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, Link, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { ErrorSummary, FileInfo, LegalBasis, PipelineEvent, StructuredReport, ValidationError } from '../types/sped'

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
  info: 'Info',
}

type TabType = 'summary' | 'errors' | 'alerts' | 'report'

export default function FileDetailPage() {
  const { fileId } = useParams<{ fileId: string }>()
  const [searchParams] = useSearchParams()
  const autoValidate = searchParams.get('validate') === '1'
  const id = Number(fileId)
  const [file, setFile] = useState<FileInfo | null>(null)
  const [summary, setSummary] = useState<ErrorSummary | null>(null)
  const [errorItems, setErrorItems] = useState<ValidationError[]>([])
  const [alertItems, setAlertItems] = useState<ValidationError[]>([])
  const [validating, setValidating] = useState(false)
  const [tab, setTab] = useState<TabType>('summary')
  const [pipelineEvent, setPipelineEvent] = useState<PipelineEvent | null>(null)
  const [expandedError, setExpandedError] = useState<number | null>(null)
  const eventSourceRef = useRef<EventSource | null>(null)

  const loadData = useCallback(async () => {
    const f = await api.getFile(id)
    setFile(f)
    if (f.status === 'validated') {
      const [s, allErrors] = await Promise.all([
        api.getSummary(id),
        api.getErrors(id, { limit: '2000' }),
      ])
      setSummary(s)
      setErrorItems(allErrors.filter(e => e.severity === 'critical' || e.severity === 'error'))
      setAlertItems(allErrors.filter(e => e.severity === 'warning' || e.severity === 'info'))
    }
  }, [id])

  useEffect(() => { loadData() }, [loadData])

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
    setErrorItems([])
    setAlertItems([])
    setSummary(null)

    if (eventSourceRef.current) eventSourceRef.current.close()

    const es = api.validateStream(id, (event: PipelineEvent) => {
      setPipelineEvent(event)
      if (event.type === 'done') {
        setValidating(false)
        loadData().then(() => {
          // Navigate to most relevant tab
        })
      } else if (event.type === 'error') {
        setValidating(false)
      }
    })
    eventSourceRef.current = es
  }, [id, loadData])

  useEffect(() => {
    return () => { eventSourceRef.current?.close() }
  }, [])

  // Auto-navigate after data loads post-validation
  useEffect(() => {
    if (!validating && file?.status === 'validated') {
      if (errorItems.length > 0) setTab('errors')
      else if (alertItems.length > 0) setTab('alerts')
      else setTab('summary')
    }
  // Only run when items change after validation
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [errorItems.length, alertItems.length])

  const handleClearAudit = useCallback(async () => {
    const total = file?.total_errors ?? 0
    if (!confirm(`Limpar toda a validacao e audit deste arquivo? (${total} apontamentos serao removidos)`)) return
    try {
      await api.clearAudit(id)
      setSummary(null)
      setErrorItems([])
      setAlertItems([])
      setTab('summary')
      loadData()
    } catch { /* */ }
  }, [id, file, loadData])

  if (!file) return <p className="text-gray-500">Carregando...</p>

  const conformidade = file.total_records > 0
    ? ((file.total_records - file.total_errors) / file.total_records * 100).toFixed(1)
    : '100.0'

  const openErrors = errorItems.filter(e => e.status === 'open')
  const openAlerts = alertItems.filter(e => e.status === 'open')

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <Link to="/files" className="text-sm text-blue-600 hover:underline">&larr; Voltar</Link>
          <h2 className="text-2xl font-bold">{file.company_name || file.filename}</h2>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-gray-500 mt-1">
            {file.cnpj && <span>CNPJ: <span className="font-mono">{formatCnpj(file.cnpj)}</span></span>}
            {file.uf && <span>UF: {file.uf}</span>}
            {file.period_start && file.period_end && (
              <span>Periodo: {formatDate(file.period_start)} a {formatDate(file.period_end)}</span>
            )}
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
            <a href={api.downloadSped(id)} className="bg-green-600 text-white px-4 py-2 rounded hover:bg-green-700">
              Baixar SPED
            </a>
          )}
          {file.status === 'validated' && (
            <button
              onClick={handleClearAudit}
              disabled={validating}
              className="text-sm text-red-600 px-4 py-2 rounded border border-red-300 hover:bg-red-50 disabled:opacity-50"
            >
              Limpar Audit
            </button>
          )}
        </div>
      </div>

      {/* Score cards */}
      <div className="grid grid-cols-5 gap-4 mb-6">
        <div className="bg-white p-4 rounded shadow">
          <p className="text-sm text-gray-500">Registros</p>
          <p className="text-2xl font-bold">{file.total_records}</p>
        </div>
        <div className="bg-white p-4 rounded shadow border-l-4 border-red-500">
          <p className="text-sm text-gray-500">Erros</p>
          <p className="text-2xl font-bold text-red-600">{openErrors.length}</p>
        </div>
        <div className="bg-white p-4 rounded shadow border-l-4 border-yellow-400">
          <p className="text-sm text-gray-500">Alertas</p>
          <p className="text-2xl font-bold text-yellow-600">{openAlerts.length}</p>
        </div>
        <div className="bg-white p-4 rounded shadow">
          <p className="text-sm text-gray-500">Conformidade</p>
          <p className={`text-2xl font-bold ${Number(conformidade) >= 95 ? 'text-green-600' : 'text-orange-600'}`}>{conformidade}%</p>
        </div>
        <div className="bg-white p-4 rounded shadow border-l-4 border-green-500">
          <p className="text-sm text-gray-500">Correcoes</p>
          <p className="text-2xl font-bold text-green-600">{pipelineEvent?.auto_corrected ?? file.auto_corrections_applied ?? 0}</p>
        </div>
      </div>

      {/* Auto-correction banner */}
      {file.status === 'validated' && file.auto_corrections_applied > 0 && !validating && (
        <div className="bg-green-50 border border-green-200 rounded p-4 mb-6 flex items-center justify-between">
          <span className="text-green-800">
            {file.auto_corrections_applied} erro{file.auto_corrections_applied !== 1 ? 's' : ''} corrigido{file.auto_corrections_applied !== 1 ? 's' : ''} automaticamente.
          </span>
          <a href={api.downloadSped(id)} className="bg-green-600 text-white px-4 py-2 rounded text-sm hover:bg-green-700">
            Baixar Arquivo Corrigido
          </a>
        </div>
      )}

      {/* Pipeline Progress */}
      {validating && pipelineEvent && <PipelineProgressPanel event={pipelineEvent} />}

      {/* Tabs */}
      {(file.status === 'validated' || errorItems.length > 0 || alertItems.length > 0) && !validating && (
        <>
          <div className="flex gap-1 border-b mb-4">
            {([
              { key: 'summary' as TabType, label: 'Resumo' },
              { key: 'errors' as TabType, label: `Erros (${openErrors.length})`, color: openErrors.length > 0 ? 'text-red-600' : '' },
              { key: 'alerts' as TabType, label: `Alertas (${openAlerts.length})`, color: openAlerts.length > 0 ? 'text-yellow-600' : '' },
              { key: 'report' as TabType, label: 'Relatorio' },
            ]).map((t) => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={`pb-2 px-3 text-sm ${
                  tab === t.key
                    ? 'border-b-2 border-blue-600 font-semibold'
                    : `text-gray-500 hover:text-gray-700 ${t.color || ''}`
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          {tab === 'summary' && summary && <SummaryTab summary={summary} />}
          {tab === 'errors' && (
            <ErrorsAlertsList
              items={errorItems}
              variant="error"
              expandedError={expandedError}
              onToggleExpand={setExpandedError}
              fileId={id}
              onReload={loadData}
              onRevalidate={handleValidateStream}
            />
          )}
          {tab === 'alerts' && (
            <ErrorsAlertsList
              items={alertItems}
              variant="alert"
              expandedError={expandedError}
              onToggleExpand={setExpandedError}
              fileId={id}
              onReload={loadData}
              onRevalidate={handleValidateStream}
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
            <div key={stage}>
              <div className="flex items-center gap-3">
                <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${
                  isDone ? 'bg-green-500 text-white' :
                  isCurrent ? 'bg-blue-500 text-white animate-pulse' :
                  'bg-gray-200 text-gray-400'
                }`}>
                  {isDone ? '\u2713' : isCurrent ? '\u25CF' : (idx + 1)}
                </div>
                <span className={`flex-1 text-sm ${isCurrent ? 'font-semibold' : isDone ? 'text-gray-600' : 'text-gray-400'}`}>
                  {STAGE_LABELS[stage]}
                </span>
                <span className="text-sm text-gray-500 w-32 text-right">
                  {isDone && errorsForStage !== undefined && (
                    <span className={errorsForStage > 0 ? 'text-red-600 font-semibold' : 'text-green-600'}>
                      {errorsForStage} apontamento{errorsForStage !== 1 ? 's' : ''}
                    </span>
                  )}
                  {isCurrent && event.stage_progress !== undefined && (
                    <span className="text-blue-600">{event.stage_progress}%</span>
                  )}
                </span>
              </div>
              {isCurrent && event.detail && (
                <div className="ml-9 mt-1"><span className="text-xs text-gray-400 italic">{event.detail}</span></div>
              )}
            </div>
          )
        })}
      </div>
      <div className="mt-4 bg-gray-200 rounded-full h-2">
        <div
          className="bg-blue-600 h-2 rounded-full transition-all duration-300"
          style={{
            width: `${event.stage === 'concluido' ? 100 :
              ((currentStageIdx + (event.stage_progress || 0) / 100) / STAGE_ORDER.length) * 100}%`
          }}
        />
      </div>
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
                <td className="p-2 font-mono text-xs">{type}</td>
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
                <td className="p-2"><SeverityBadge severity={sev} /></td>
                <td className="p-2 text-right font-semibold">{count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}


// ── Errors / Alerts List (shared component) ──

interface ListProps {
  items: ValidationError[]
  variant: 'error' | 'alert'
  expandedError: number | null
  onToggleExpand: (id: number | null) => void
  fileId: number
  onReload: () => void
  onRevalidate: () => void
}

function ErrorsAlertsList({ items, variant, expandedError, onToggleExpand, fileId, onReload, onRevalidate }: ListProps) {
  const openItems = items.filter(e => e.status === 'open')
  const [showCorrected, setShowCorrected] = useState(false)
  const displayItems = showCorrected ? items : openItems
  const autoCorrectableCount = openItems.filter(e => e.auto_correctable && e.expected_value).length
  const correctedCount = items.filter(e => e.status === 'corrected').length

  const handleCorrect = async (error: ValidationError) => {
    if (!error.expected_value || !error.record_id) return
    try {
      await api.updateRecord(fileId, error.record_id, {
        field_no: error.field_no || 0,
        field_name: error.field_name || '',
        new_value: error.expected_value,
        error_id: error.id,
      })
      onReload()
    } catch { /* */ }
  }

  const handleDismiss = async (errorId: number) => {
    try {
      await api.dismissError(fileId, errorId)
      onReload()
    } catch { /* */ }
  }

  const handleDismissAll = async () => {
    if (!confirm(`Ignorar todos os ${openItems.length} apontamentos abertos?`)) return
    try {
      await api.dismissAllErrors(fileId)
      onReload()
    } catch { /* */ }
  }

  const isError = variant === 'error'

  return (
    <div>
      {/* Banner */}
      {openItems.length > 0 && (
        <div className={`rounded p-4 mb-4 ${isError ? 'bg-red-50 border border-red-200' : 'bg-yellow-50 border border-yellow-200'}`}>
          <span className={`font-semibold ${isError ? 'text-red-800' : 'text-yellow-800'}`}>
            {openItems.length} {isError ? 'erro' : 'alerta'}{openItems.length !== 1 ? 's' : ''}
            {isError ? ' precisam de correcao' : ' para revisao'}
          </span>
        </div>
      )}

      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-3 mb-4">
        {isError && autoCorrectableCount > 0 && (
          <button
            onClick={onRevalidate}
            className="bg-green-600 text-white px-4 py-2 rounded hover:bg-green-700 text-sm font-semibold"
          >
            Corrigir Todos ({autoCorrectableCount})
          </button>
        )}
        {openItems.length > 0 && (
          <button
            onClick={handleDismissAll}
            className="text-sm text-gray-500 px-3 py-1 rounded border border-gray-300 hover:bg-gray-100"
          >
            Ignorar Todos ({openItems.length})
          </button>
        )}
        {correctedCount > 0 && (
          <label className="flex items-center gap-2 text-sm text-gray-500 ml-auto">
            <input type="checkbox" checked={showCorrected} onChange={e => setShowCorrected(e.target.checked)} />
            Mostrar corrigidos ({correctedCount})
          </label>
        )}
      </div>

      {/* Cards */}
      <div className="space-y-2">
        {displayItems.map((e) => (
          <ErrorCard
            key={e.id}
            error={e}
            variant={variant}
            expanded={expandedError === e.id}
            onToggle={() => onToggleExpand(expandedError === e.id ? null : e.id)}
            onCorrect={() => handleCorrect(e)}
            onDismiss={() => handleDismiss(e.id)}
          />
        ))}
      </div>

      {displayItems.length === 0 && (
        <p className="text-gray-500 text-center py-8">
          {isError ? 'Nenhum erro encontrado.' : 'Nenhum alerta encontrado.'}
        </p>
      )}
    </div>
  )
}


// ── Error Card ──

function ErrorCard({
  error, variant, expanded, onToggle, onCorrect, onDismiss,
}: {
  error: ValidationError
  variant: 'error' | 'alert'
  expanded: boolean
  onToggle: () => void
  onCorrect: () => void
  onDismiss: () => void
}) {
  const displayMessage = error.friendly_message || error.message
  const legalBasis = parseLegalBasis(error.legal_basis)
  const isCorrected = error.status === 'corrected'
  const isError = variant === 'error'

  const borderColor = isCorrected ? 'border-green-400' :
    error.severity === 'critical' ? 'border-red-500' :
    error.severity === 'error' ? 'border-orange-500' :
    error.severity === 'warning' ? 'border-yellow-400' :
    'border-blue-300'

  const bgColor = isCorrected ? 'bg-green-50 opacity-60' :
    isError ? 'bg-red-50' : 'bg-white'

  return (
    <div className={`rounded shadow border-l-4 ${borderColor} ${bgColor}`}>
      <div className="flex items-start gap-3 p-4 cursor-pointer hover:bg-opacity-80" onClick={onToggle}>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <span className="font-mono text-xs text-gray-500">Linha {error.line_number}</span>
            <span className="font-mono text-xs bg-gray-100 px-1.5 py-0.5 rounded">{error.register}</span>
            {error.field_name && <span className="text-xs text-gray-500">{error.field_name}</span>}
            <SeverityBadge severity={error.severity} />
            {isCorrected && <span className="px-2 py-0.5 rounded text-xs bg-green-100 text-green-700">Corrigido</span>}
          </div>
          <p className="text-sm text-gray-800">{displayMessage}</p>
          {/* Inline correction preview for errors */}
          {isError && !isCorrected && error.expected_value && error.value && (
            <div className="mt-1 text-xs">
              <span className="text-red-600 line-through">{error.value}</span>
              <span className="text-gray-400 mx-1">&rarr;</span>
              <span className="text-green-600 font-semibold">{error.expected_value}</span>
            </div>
          )}
        </div>

        <div className="flex gap-1 flex-shrink-0">
          {error.auto_correctable && !isCorrected && error.expected_value && (
            <button
              onClick={(ev) => { ev.stopPropagation(); onCorrect() }}
              className={`text-xs px-2 py-1 rounded ${
                isError
                  ? 'bg-green-600 text-white hover:bg-green-700'
                  : 'bg-green-50 text-green-700 hover:bg-green-100'
              }`}
            >
              Corrigir
            </button>
          )}
          {!isCorrected && (
            <button
              onClick={(ev) => { ev.stopPropagation(); onDismiss() }}
              className="text-xs text-gray-400 px-2 py-1 rounded hover:bg-gray-100 hover:text-gray-600"
              title="Ignorar"
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

      {expanded && (
        <div className="border-t px-4 pb-4 pt-3 space-y-3 bg-gray-50 bg-opacity-50">
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
          {error.friendly_message && error.message !== error.friendly_message && (
            <div className="text-xs text-gray-500">
              <span className="font-semibold">Detalhe tecnico:</span> {error.message}
            </div>
          )}
          {legalBasis && (
            <div className="bg-white border rounded p-3">
              <h4 className="text-xs font-semibold text-gray-700 mb-1">Base Legal</h4>
              <p className="text-sm font-medium text-blue-800">{legalBasis.fonte}</p>
              {legalBasis.artigo && <p className="text-xs text-gray-600">{legalBasis.artigo}</p>}
              {legalBasis.trecho && (
                <blockquote className="mt-2 text-xs text-gray-600 border-l-2 border-blue-300 pl-3 italic">
                  {legalBasis.trecho.length > 300 ? legalBasis.trecho.substring(0, 300) + '...' : legalBasis.trecho}
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
      severity === 'info' ? 'bg-blue-100 text-blue-700' :
      'bg-orange-100 text-orange-700'
    }`}>
      {label}
    </span>
  )
}


// ── Report Tab ──

function ReportTab({ fileId }: { fileId: number }) {
  const [report, setReport] = useState<StructuredReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [exportFormat, setExportFormat] = useState<string | null>(null)
  const [exportContent, setExportContent] = useState('')

  useEffect(() => {
    api.getStructuredReport(fileId).then(setReport).finally(() => setLoading(false))
  }, [fileId])

  const handleExport = async (fmt: string) => {
    const content = await api.getReport(fileId, fmt)
    setExportContent(content)
    setExportFormat(fmt)
  }

  if (loading) return <p className="text-gray-500">Carregando relatorio...</p>
  if (!report) return <p className="text-gray-500">Relatorio nao disponivel.</p>

  const { metadata, summary, top_findings, corrections, conclusion } = report

  return (
    <div className="space-y-6">
      {/* 1. Dados do Arquivo */}
      <div className="bg-white rounded shadow p-6">
        <h3 className="font-semibold text-lg mb-4">Dados do Arquivo</h3>
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div><span className="text-gray-500">Empresa:</span> <span className="font-medium">{metadata.company_name || '-'}</span></div>
          <div><span className="text-gray-500">CNPJ:</span> <span className="font-mono">{metadata.cnpj ? formatCnpj(metadata.cnpj) : '-'}</span></div>
          <div><span className="text-gray-500">UF:</span> {metadata.uf || '-'}</div>
          <div>
            <span className="text-gray-500">Periodo:</span>{' '}
            {metadata.period_start && metadata.period_end
              ? `${formatDate(metadata.period_start)} a ${formatDate(metadata.period_end)}`
              : '-'}
          </div>
          <div><span className="text-gray-500">Arquivo:</span> {metadata.filename}</div>
        </div>
      </div>

      {/* 2. Resumo da Auditoria */}
      <div className="bg-white rounded shadow p-6">
        <h3 className="font-semibold text-lg mb-4">Resumo da Auditoria</h3>
        <div className="grid grid-cols-5 gap-4">
          <div className="text-center p-3 bg-gray-50 rounded">
            <p className="text-2xl font-bold">{summary.total_records.toLocaleString()}</p>
            <p className="text-xs text-gray-500">Registros</p>
          </div>
          <div className="text-center p-3 bg-red-50 rounded">
            <p className="text-2xl font-bold text-red-600">{summary.total_errors}</p>
            <p className="text-xs text-gray-500">Erros</p>
          </div>
          <div className="text-center p-3 bg-yellow-50 rounded">
            <p className="text-2xl font-bold text-yellow-600">{summary.total_warnings}</p>
            <p className="text-xs text-gray-500">Alertas</p>
          </div>
          <div className="text-center p-3 bg-gray-50 rounded">
            <p className={`text-2xl font-bold ${summary.compliance_pct >= 95 ? 'text-green-600' : 'text-orange-600'}`}>
              {summary.compliance_pct}%
            </p>
            <p className="text-xs text-gray-500">Conformidade</p>
          </div>
          <div className="text-center p-3 bg-green-50 rounded">
            <p className="text-2xl font-bold text-green-600">{summary.auto_corrected}</p>
            <p className="text-xs text-gray-500">Correcoes</p>
          </div>
        </div>
      </div>

      {/* 3. Principais Achados */}
      {top_findings.length > 0 && (
        <div className="bg-white rounded shadow p-6">
          <h3 className="font-semibold text-lg mb-4">Principais Achados</h3>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-gray-500 border-b">
                <th className="pb-2">Tipo</th>
                <th className="pb-2">Severidade</th>
                <th className="pb-2 text-right">Qtd</th>
                <th className="pb-2">Descricao</th>
              </tr>
            </thead>
            <tbody>
              {top_findings.map((f, i) => (
                <tr key={i} className="border-t">
                  <td className="py-2 font-mono text-xs">{f.error_type}</td>
                  <td className="py-2"><SeverityBadge severity={f.severity} /></td>
                  <td className="py-2 text-right font-semibold">{f.count}</td>
                  <td className="py-2 text-xs text-gray-600">{f.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* 4. Correcoes Aplicadas */}
      <div className="bg-white rounded shadow p-6">
        <h3 className="font-semibold text-lg mb-4">Correcoes Aplicadas</h3>
        {corrections.length === 0 ? (
          <p className="text-gray-500 text-sm">Nenhuma correcao aplicada.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-gray-500 border-b">
                <th className="pb-2">Registro</th>
                <th className="pb-2">Campo</th>
                <th className="pb-2">Antes</th>
                <th className="pb-2">Depois</th>
                <th className="pb-2">Por</th>
              </tr>
            </thead>
            <tbody>
              {corrections.map((c, i) => (
                <tr key={i} className="border-t">
                  <td className="py-2 font-mono text-xs">{c.register}</td>
                  <td className="py-2 text-xs">{c.field_name}</td>
                  <td className="py-2 font-mono text-xs text-red-600">{c.old_value}</td>
                  <td className="py-2 font-mono text-xs text-green-600">{c.new_value}</td>
                  <td className="py-2 text-xs text-gray-500">{c.applied_by}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* 5. Conclusao */}
      <div className="bg-gray-50 rounded shadow p-6">
        <h3 className="font-semibold text-lg mb-3">Conclusao</h3>
        <p className="text-gray-700">{conclusion}</p>
      </div>

      {/* Export buttons */}
      <div className="flex gap-2 items-center">
        <span className="text-sm text-gray-500">Exportar:</span>
        {['md', 'csv', 'json'].map((f) => (
          <button
            key={f}
            onClick={() => handleExport(f)}
            className={`px-3 py-1 rounded text-sm ${exportFormat === f ? 'bg-blue-600 text-white' : 'bg-gray-200 hover:bg-gray-300'}`}
          >
            {f.toUpperCase()}
          </button>
        ))}
      </div>
      {exportFormat && (
        <pre className="bg-gray-900 text-gray-100 p-4 rounded overflow-auto text-xs max-h-[400px]">
          {exportContent}
        </pre>
      )}
    </div>
  )
}


// ── Helpers ──

function parseLegalBasis(raw: string | null): LegalBasis | null {
  if (!raw) return null
  try { return JSON.parse(raw) as LegalBasis } catch { return null }
}

function formatCnpj(cnpj: string): string {
  const d = cnpj.replace(/\D/g, '')
  if (d.length !== 14) return cnpj
  return `${d.slice(0, 2)}.${d.slice(2, 5)}.${d.slice(5, 8)}/${d.slice(8, 12)}-${d.slice(12)}`
}

function formatDate(date: string): string {
  if (date.length === 8 && /^\d+$/.test(date)) {
    return `${date.slice(0, 2)}/${date.slice(2, 4)}/${date.slice(4)}`
  }
  return date
}
