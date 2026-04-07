import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, Link, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { ErrorSummary, FileInfo, LegalBasis, PipelineEvent, RecordInfo, StructuredReport, ValidationError } from '../types/sped'
import RecordDetail from '../components/Records/RecordDetail'
import FieldEditor from '../components/Records/FieldEditor'
import SuggestionPanel from '../components/Records/SuggestionPanel'
import ErrorChart from '../components/Dashboard/ErrorChart'
import AuditScopePanel from '../components/Dashboard/AuditScopePanel'
import CorrectionApprovalPanel from '../components/Corrections/CorrectionApprovalPanel'

const STAGE_LABELS: Record<string, string> = {
  estrutural: 'Analise Estrutural',
  cruzamento: 'Cruzamento de Dados',
  enriquecimento: 'Consultando Base Legal',
  concluido: 'Concluido',
}

const STAGE_ORDER = ['estrutural', 'cruzamento', 'enriquecimento']

const SEVERITY_LABELS: Record<string, string> = {
  critical: 'Critico',
  error: 'Erro',
  warning: 'Aviso',
  info: 'Info',
}

type TabType = 'summary' | 'errors' | 'alerts' | 'corrections' | 'report'

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

    let done = false

    const es = api.validateStream(id, (event: PipelineEvent) => {
      setPipelineEvent(event)
      if (event.type === 'done') {
        done = true
        setValidating(false)
        loadData()
      } else if (event.type === 'error') {
        done = true
        setValidating(false)
      }
    })

    // Fallback: se a conexao SSE fechar sem evento 'done',
    // fazer polling para verificar se o pipeline terminou
    const pollInterval = setInterval(async () => {
      if (done) {
        clearInterval(pollInterval)
        return
      }
      try {
        const f = await api.getFile(id)
        if (f.status === 'validated' || f.status === 'error') {
          done = true
          clearInterval(pollInterval)
          es.close()
          setValidating(false)
          if (f.status === 'validated') loadData()
        }
      } catch { /* */ }
    }, 5000)

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

  const handleDeleteFile = useCallback(async () => {
    if (!confirm(`Excluir este arquivo e todos os dados associados?`)) return
    try {
      await api.deleteFile(id)
      window.location.href = '/files'
    } catch { /* */ }
  }, [id])

  if (!file) return <p className="text-gray-500">Carregando...</p>

  const conformidade = file.total_records > 0
    ? ((file.total_records - file.total_errors) / file.total_records * 100).toFixed(1)
    : '100.0'

  const openErrors = errorItems.filter(e => e.status === 'open')
  const openAlerts = alertItems.filter(e => e.status === 'open')

  return (
    <div>
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6">
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
              onClick={handleDeleteFile}
              disabled={validating}
              className="text-sm text-red-600 px-4 py-2 rounded border border-red-300 hover:bg-red-50 disabled:opacity-50"
            >
              Excluir Arquivo
            </button>
          )}
        </div>
      </div>

      {/* Score cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 md:gap-4 mb-6">
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
          <p className="text-sm text-gray-500" title="Escopo: validacoes internas do arquivo SPED">Conformidade verificavel</p>
          <p className={`text-2xl font-bold ${Number(conformidade) >= 95 ? 'text-green-600' : 'text-orange-600'}`}>{conformidade}%</p>
        </div>
      </div>

      {/* Audit Scope — always visible when validated */}
      {file.status === 'validated' && !validating && <AuditScopePanel fileId={id} />}

      {/* Pipeline Progress */}
      {validating && pipelineEvent && <PipelineProgressPanel event={pipelineEvent} />}

      {/* Tabs */}
      {(file.status === 'validated' || errorItems.length > 0 || alertItems.length > 0) && !validating && (
        <>
          <div className="flex gap-1 border-b mb-4 overflow-x-auto">
            {([
              { key: 'summary' as TabType, label: 'Resumo' },
              { key: 'errors' as TabType, label: `Erros (${openErrors.length})`, color: openErrors.length > 0 ? 'text-red-600' : '' },
              { key: 'alerts' as TabType, label: `Alertas (${openAlerts.length})`, color: openAlerts.length > 0 ? 'text-yellow-600' : '' },
              { key: 'corrections' as TabType, label: 'Correcoes', color: '' },
              { key: 'report' as TabType, label: 'Relatorio' },
            ]).map((t) => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={`pb-2 px-3 text-sm whitespace-nowrap ${
                  tab === t.key
                    ? 'border-b-2 border-blue-600 font-semibold'
                    : `text-gray-500 hover:text-gray-700 ${t.color || ''}`
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          {tab === 'summary' && summary && <SummaryTab summary={summary} fileId={id} />}
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
          {tab === 'corrections' && (
            <CorrectionApprovalPanel
              fileId={id}
              errors={[...errorItems, ...alertItems]}
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
    </div>
  )
}


// ── Summary Tab ──

function SummaryTab({ summary, fileId }: { summary: ErrorSummary; fileId: number }) {
  return (
    <div className="space-y-6">
      {/* Charts */}
      <ErrorChart fileId={fileId} />

      {/* Tables */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="overflow-x-auto">
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
        <div className="overflow-x-auto">
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

      {/* Cross-validation link */}
      <div className="text-center pt-2">
        <Link to={`/files/${fileId}/cross`} className="text-sm text-blue-600 hover:underline">
          Ver cruzamentos entre blocos &rarr;
        </Link>
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

function ErrorsAlertsList({ items, variant, expandedError, onToggleExpand, fileId, onReload }: ListProps) {
  const openItems = items.filter(e => e.status === 'open')
  const [showCorrected, setShowCorrected] = useState(false)
  const [filterSeverity, setFilterSeverity] = useState<string>('')
  const [filterRegister, setFilterRegister] = useState<string>('')
  const [filterCerteza, setFilterCerteza] = useState<string>('')
  const [sortBy, setSortBy] = useState<string>('severity')

  // Compute unique values for filters
  const allRegisters = [...new Set(items.map(e => e.register))].sort()

  // Apply filters
  const baseItems = showCorrected ? items : openItems
  const filteredItems = baseItems.filter(e => {
    if (filterSeverity && e.severity !== filterSeverity) return false
    if (filterRegister && e.register !== filterRegister) return false
    if (filterCerteza && (e.certeza || '') !== filterCerteza) return false
    return true
  })

  // Sort
  const severityOrder: Record<string, number> = { critical: 0, error: 1, warning: 2, info: 3 }
  const displayItems = [...filteredItems].sort((a, b) => {
    if (sortBy === 'severity') return (severityOrder[a.severity] ?? 9) - (severityOrder[b.severity] ?? 9)
    if (sortBy === 'register') return a.register.localeCompare(b.register)
    if (sortBy === 'type') return a.error_type.localeCompare(b.error_type)
    if (sortBy === 'line') return a.line_number - b.line_number
    return 0
  })

  const autoCorrectableCount = openItems.filter(e => e.auto_correctable && e.expected_value).length
  const correctedCount = items.filter(e => e.status === 'corrected').length

  // RecordDetail / FieldEditor state
  const [selectedRecord, setSelectedRecord] = useState<RecordInfo | null>(null)
  const [selectedRecordErrors, setSelectedRecordErrors] = useState<ValidationError[]>([])
  const [editingField, setEditingField] = useState<{ fieldName: string; error: ValidationError } | null>(null)
  const [loadingRecord, setLoadingRecord] = useState<number | null>(null)

  const handleOpenRecordDetail = async (error: ValidationError) => {
    if (!error.record_id) return
    // If clicking the same error that's already expanded, close it
    if (selectedRecord && selectedRecord.id === error.record_id && !editingField) {
      setSelectedRecord(null)
      setSelectedRecordErrors([])
      return
    }
    setEditingField(null)
    setLoadingRecord(error.record_id)
    try {
      const record = await api.getRecord(fileId, error.record_id!)
      setSelectedRecord(record)
      // Gather all errors for this record
      const recordErrors = items.filter(e => e.record_id === error.record_id)
      setSelectedRecordErrors(recordErrors)
    } catch { /* */ }
    setLoadingRecord(null)
  }

  const handleFieldClick = (fieldName: string, error: ValidationError) => {
    setEditingField({ fieldName, error })
  }

  const handleFieldSave = async (newValue: string) => {
    if (!editingField || !selectedRecord) return
    await api.updateRecord(fileId, selectedRecord.id, {
      field_no: editingField.error.field_no || 0,
      field_name: editingField.error.field_name || editingField.fieldName,
      new_value: newValue,
      error_id: editingField.error.id,
    })
    setEditingField(null)
    setSelectedRecord(null)
    onReload()
  }

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

  const [correctingAll, setCorrectingAll] = useState(false)

  const handleCorrectAll = async () => {
    const correctable = openItems.filter(e => e.auto_correctable && e.expected_value && e.record_id)
    if (correctable.length === 0) return
    if (!confirm(`Aplicar ${correctable.length} correcoes sugeridas?`)) return
    setCorrectingAll(true)
    try {
      for (const error of correctable) {
        await api.updateRecord(fileId, error.record_id!, {
          field_no: error.field_no || 0,
          field_name: error.field_name || '',
          new_value: error.expected_value!,
          error_id: error.id,
        })
      }
      onReload()
    } catch { /* */ }
    setCorrectingAll(false)
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
            onClick={handleCorrectAll}
            disabled={correctingAll}
            className="bg-green-600 text-white px-4 py-2 rounded hover:bg-green-700 text-sm font-semibold disabled:opacity-50"
          >
            {correctingAll ? 'Corrigindo...' : `Corrigir Todos (${autoCorrectableCount})`}
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
          <div key={e.id}>
            <ErrorCard
              error={e}
              variant={variant}
              expanded={expandedError === e.id}
              onToggle={() => onToggleExpand(expandedError === e.id ? null : e.id)}
              onCorrect={() => handleCorrect(e)}
              onDismiss={() => handleDismiss(e.id)}
              onOpenRecord={() => handleOpenRecordDetail(e)}
              loadingRecord={loadingRecord === e.record_id}
            />
            {/* RecordDetail inline below the card */}
            {selectedRecord && selectedRecord.id === e.record_id && !editingField && (
              <RecordDetail
                record={selectedRecord}
                errors={selectedRecordErrors}
                onClose={() => { setSelectedRecord(null); setSelectedRecordErrors([]) }}
                onFieldClick={handleFieldClick}
              />
            )}
            {/* FieldEditor + SuggestionPanel inline below the card */}
            {editingField && selectedRecord && selectedRecord.id === e.record_id && (
              <div className="flex flex-col md:flex-row gap-4 items-start">
                <div className="flex-1 min-w-0 w-full">
                  <FieldEditor
                    record={selectedRecord}
                    fieldName={editingField.fieldName}
                    error={editingField.error}
                    onSave={handleFieldSave}
                    onCancel={() => setEditingField(null)}
                  />
                </div>
                <SuggestionPanel
                  error={editingField.error}
                  onSearch={(query) => api.searchDocs(query, editingField.error.field_name || undefined, editingField.error.register)}
                />
              </div>
            )}
          </div>
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


// ── Confidence Badge ──

function ConfidenceBadge({ message }: { message: string }) {
  // Extrai "Confianca: alta (80 pontos)" da mensagem técnica
  const match = message.match(/Confianca:\s*(alta|provavel|indicio|baixa)\s*\((\d+)\s*pontos?\)/)
  if (!match) return null

  const [, level, scoreStr] = match
  const score = parseInt(scoreStr, 10)

  const config = {
    alta:     { label: 'Alta',      color: 'bg-green-100 text-green-800',  barColor: 'bg-green-500' },
    provavel: { label: 'Provavel',  color: 'bg-blue-100 text-blue-800',   barColor: 'bg-blue-500' },
    indicio:  { label: 'Indicio',   color: 'bg-yellow-100 text-yellow-800', barColor: 'bg-yellow-500' },
    baixa:    { label: 'Baixa',     color: 'bg-gray-100 text-gray-600',   barColor: 'bg-gray-400' },
  }[level] || { label: level, color: 'bg-gray-100 text-gray-600', barColor: 'bg-gray-400' }

  const pct = Math.min(score, 100)

  return (
    <div className="flex items-center gap-2" title={`Confianca: ${config.label} (${score} pontos)`}>
      <div className="w-16 h-1.5 bg-gray-200 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${config.barColor}`} style={{ width: `${pct}%` }} />
      </div>
      <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${config.color}`}>
        {score}%
      </span>
    </div>
  )
}


// ── Error Card ──

function ErrorCard({
  error, variant, expanded, onToggle, onCorrect, onDismiss, onOpenRecord, loadingRecord,
}: {
  error: ValidationError
  variant: 'error' | 'alert'
  expanded: boolean
  onToggle: () => void
  onCorrect: () => void
  onDismiss: () => void
  onOpenRecord?: () => void
  loadingRecord?: boolean
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
            {error.certeza === 'indicio' && <span className="px-2 py-0.5 rounded text-xs bg-purple-100 text-purple-700">Indicio</span>}
            {isCorrected && <span className="px-2 py-0.5 rounded text-xs bg-green-100 text-green-700">Corrigido</span>}
          </div>
          <p className="text-sm text-gray-800">{displayMessage}</p>
          {/* Inline correction preview + confidence */}
          {!isCorrected && error.expected_value && error.value && (
            <div className="mt-1.5 flex items-center gap-3 flex-wrap">
              <div className="text-sm">
                <span className="text-gray-500 font-medium">Correcao: </span>
                <span className="text-red-600 line-through">
                  {error.value}{error.field_name?.includes('ALIQ') ? '%' : ''}
                </span>
                <span className="text-gray-400 mx-1">&rarr;</span>
                <span className="text-green-600 font-semibold">
                  {error.expected_value}{error.field_name?.includes('ALIQ') ? '%' : ''}
                </span>
              </div>
              <ConfidenceBadge message={error.message} />
            </div>
          )}
        </div>

        <div className="flex gap-1 flex-shrink-0">
          {error.record_id && onOpenRecord && (
            <button
              onClick={(ev) => { ev.stopPropagation(); onOpenRecord() }}
              disabled={loadingRecord}
              className="text-xs text-blue-600 px-2 py-1 rounded hover:bg-blue-50 disabled:opacity-50"
              title="Ver registro completo"
            >
              {loadingRecord ? '...' : 'Ver Registro'}
            </button>
          )}
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
          {/* Card de explicacao — tudo dentro do card azul */}
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 space-y-3">
            {/* Explicacao principal */}
            {error.doc_suggestion ? (
              <div className="text-sm text-gray-800 whitespace-pre-line leading-relaxed">
                {error.doc_suggestion.split('**Como corrigir:**').map((part, i) =>
                  i === 0 ? (
                    <p key={i}>{part.trim()}</p>
                  ) : (
                    <div key={i} className="mt-3 pt-3 border-t border-blue-200">
                      <span className="font-semibold text-blue-800">Como corrigir: </span>
                      <span className="text-gray-700">{part.trim()}</span>
                    </div>
                  )
                )}
              </div>
            ) : error.friendly_message ? (
              <p className="text-sm text-gray-800">{error.friendly_message}</p>
            ) : null}

            {/* Dados do erro */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-2 md:gap-4 text-xs pt-2 border-t border-blue-200">
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
                  <span className="text-gray-500">Valor sugerido:</span>{' '}
                  <span className="font-mono text-green-600">{error.expected_value}</span>
                </div>
              )}
            </div>

            {/* Detalhe tecnico — colapsavel dentro do card */}
            {error.message && error.message !== error.friendly_message && (
              <details className="text-xs text-gray-500 pt-1 border-t border-blue-100">
                <summary className="cursor-pointer font-semibold hover:text-gray-700 py-1">Detalhe tecnico</summary>
                <p className="mt-1 pl-3 border-l-2 border-blue-200 text-gray-600 whitespace-pre-line">{error.message}</p>
              </details>
            )}
          </div>

          {/* Base legal — referencia modesta */}
          {legalBasis && (
            <div className="flex items-center gap-2 text-xs text-gray-400">
              <span>Ref:</span>
              <span className="font-medium text-gray-500">{legalBasis.fonte}</span>
              {legalBasis.artigo && <span className="text-gray-400">— {legalBasis.artigo}</span>}
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
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
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
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 md:gap-4">
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
            <p className="text-xs text-gray-500" title="Escopo: validacoes internas do arquivo SPED">Conformidade verificavel</p>
          </div>
          <div className="text-center p-3 bg-blue-50 rounded">
            <p className="text-2xl font-bold text-blue-600">{summary.pending_suggestions}</p>
            <p className="text-xs text-gray-500">Sugestoes</p>
          </div>
        </div>
      </div>

      {/* 3. Principais Achados */}
      {top_findings.length > 0 && (
        <div className="bg-white rounded shadow p-6">
          <h3 className="font-semibold text-lg mb-4">Principais Achados</h3>
          <div className="overflow-x-auto"><table className="w-full text-sm">
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
          </table></div>
        </div>
      )}

      {/* 4. Correcoes Aplicadas pelo Analista */}
      <div className="bg-white rounded shadow p-6">
        <h3 className="font-semibold text-lg mb-4">Correcoes Aplicadas pelo Analista</h3>
        {corrections.length === 0 ? (
          <p className="text-gray-500 text-sm">Nenhuma correcao aplicada ainda. As sugestoes do motor de inteligencia aguardam aprovacao na aba Erros.</p>
        ) : (
          <div className="overflow-x-auto"><table className="w-full text-sm">
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
          </table></div>
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
