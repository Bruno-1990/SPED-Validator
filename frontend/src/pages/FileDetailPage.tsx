import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, Link, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { ErrorSummary, FileInfo, LegalBasis, PipelineEvent, StructuredReport, ValidationError } from '../types/sped'
import RecordEditModal from '../components/Records/RecordEditModal'
import ErrorChart from '../components/Dashboard/ErrorChart'
import AuditScopePanel from '../components/Dashboard/AuditScopePanel'
import CorrectionApprovalPanel from '../components/Corrections/CorrectionApprovalPanel'

// ── Modal de Confirmacao ──

interface ConfirmModalState {
  open: boolean
  title: string
  message: string
  confirmLabel: string
  confirmColor: 'red' | 'green' | 'blue'
  onConfirm: () => void
}

const CONFIRM_INITIAL: ConfirmModalState = {
  open: false, title: '', message: '', confirmLabel: 'Confirmar',
  confirmColor: 'blue', onConfirm: () => {},
}

function ConfirmModal({ state, onClose }: { state: ConfirmModalState; onClose: () => void }) {
  if (!state.open) return null

  const colorClasses = {
    red: 'bg-red-600 hover:bg-red-700 focus:ring-red-500',
    green: 'bg-green-600 hover:bg-green-700 focus:ring-green-500',
    blue: 'bg-blue-600 hover:bg-blue-700 focus:ring-blue-500',
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onClick={onClose}>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/40 backdrop-blur-sm transition-opacity" />

      {/* Modal */}
      <div
        className="relative bg-white rounded-2xl shadow-2xl max-w-md w-full p-6 transform transition-all"
        onClick={e => e.stopPropagation()}
      >
        <h3 className="text-lg font-semibold text-gray-900 mb-2">{state.title}</h3>
        <p className="text-sm text-gray-600 mb-6 leading-relaxed">{state.message}</p>

        <div className="flex justify-end gap-3">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors focus:outline-none focus:ring-2 focus:ring-gray-300"
          >
            Cancelar
          </button>
          <button
            onClick={() => { state.onConfirm(); onClose() }}
            className={`px-4 py-2 text-sm font-medium text-white rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-offset-2 ${colorClasses[state.confirmColor]}`}
          >
            {state.confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

/** Converte **texto** em <strong>texto</strong> para exibicao formatada. */
function renderBold(text: string) {
  const parts = text.split(/\*\*(.*?)\*\*/g)
  return parts.map((part, i) =>
    i % 2 === 1 ? <strong key={i} className="font-semibold">{part}</strong> : part
  )
}

const STAGE_LABELS: Record<string, string> = {
  estrutural: 'Analise Estrutural',
  cruzamento: 'Cruzamento fiscal (SPED)',
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
  const fromXml = searchParams.get('fromXml') === '1'
  const validateMode = searchParams.get('mode') === 'sped_xml' ? 'sped_xml' as const : 'sped_only' as const
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
  const [confirmModal, setConfirmModal] = useState<ConfirmModalState>(CONFIRM_INITIAL)
  const closeModal = useCallback(() => setConfirmModal(CONFIRM_INITIAL), [])

  const loadData = useCallback(async () => {
    const f = await api.getFile(id)
    setFile(f)
    if (f.status === 'validated') {
      const [s, fiscalErrors, xmlErrors] = await Promise.all([
        api.getSummary(id),
        api.getErrors(id, { page_size: '2000' }),
        api.getErrors(id, { page_size: '2000', categoria: 'cruzamento_xml' }),
      ])
      const allErrors = [...fiscalErrors, ...xmlErrors]
      setSummary(s)
      setErrorItems(allErrors.filter(e => e.severity === 'critical' || e.severity === 'error'))
      setAlertItems(allErrors.filter(e => e.severity === 'warning' || e.severity === 'info'))
    } else if (f.status === 'parsed') {
      // Erros de cruzamento XML persistidos (apos upload na UploadPage, sem pipeline ainda)
      try {
        const xmlErrors = await api.getErrors(id, { page_size: '2000', categoria: 'cruzamento_xml' })
        setErrorItems(xmlErrors.filter(e => e.severity === 'critical' || e.severity === 'error'))
        setAlertItems(xmlErrors.filter(e => e.severity === 'warning' || e.severity === 'info'))
      } catch { /* sem erros XML ainda */ }
    }
  }, [id])

  useEffect(() => { loadData() }, [loadData])

  const autoValidatedRef = useRef(false)
  useEffect(() => {
    if (autoValidate && file && !autoValidatedRef.current) {
      // Disparar validacao automatica tanto para arquivos novos (parsed)
      // quanto para re-validacao apos upload de novos XMLs (validated)
      if (file.status === 'parsed' || file.status === 'validated') {
        autoValidatedRef.current = true
        handleValidateStream()
      }
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

    const es = api.validateStream(
      id,
      (event: PipelineEvent) => {
        setPipelineEvent(event)
        if (event.type === 'done') {
          done = true
          setValidating(false)
          loadData()
        } else if (event.type === 'error') {
          done = true
          setValidating(false)
        }
      },
      { mode: validateMode },
    )

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
  }, [id, loadData, validateMode])

  useEffect(() => {
    return () => { eventSourceRef.current?.close() }
  }, [])

  // Auto-navigate to errors/alerts tab when data loads
  useEffect(() => {
    if (validating) return
    if (fromXml && (errorItems.length > 0 || alertItems.length > 0)) {
      setTab('errors')
      return
    }
    if (errorItems.length > 0) setTab('errors')
    else if (alertItems.length > 0) setTab('alerts')
    else if (file?.status === 'validated') setTab('summary')
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [errorItems.length, alertItems.length, fromXml, validating])

  const handleDeleteFile = useCallback(() => {
    setConfirmModal({
      open: true,
      title: 'Excluir arquivo',
      message: 'Tem certeza que deseja excluir este arquivo e todos os dados associados? Esta acao nao pode ser desfeita.',
      confirmLabel: 'Excluir',
      confirmColor: 'red',
      onConfirm: async () => {
        try {
          await api.deleteFile(id)
          window.location.href = '/files'
        } catch { /* */ }
      },
    })
  }, [id])

  if (!file) return <p className="text-gray-500">Carregando...</p>

  // Conformidade: registros com erro / total de registros (limitado a 0-100%)
  // Usa unique record_ids dos erros para nao contar multiplos erros no mesmo registro
  const uniqueErrorRecords = new Set(errorItems.concat(alertItems).filter(e => e.record_id && e.status === 'open').map(e => e.record_id)).size
  const conformidade = file.total_records > 0
    ? Math.max(0, (100 - (uniqueErrorRecords / file.total_records * 100))).toFixed(1)
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
            {validating
              ? 'Validando...'
              : file.status === 'validated'
                ? 'Revalidar'
                : autoValidate && file.status === 'parsed'
                  ? 'Validar'
                  : (fromXml || errorItems.some(e => e.categoria === 'cruzamento_xml'))
                    ? 'Validar SPED completo'
                    : 'Validar'}
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

      {/* Banner: pos-upload XML — divergencias listadas; pipeline SPED e opcional neste momento */}
      {file.status === 'parsed' && !validating && fromXml && !autoValidate && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <p className="text-blue-800 font-medium text-sm">Cruzamento XML x SPED concluido</p>
            <p className="text-blue-600 text-xs mt-0.5">
              As divergencias entre XML e SPED estao na aba Erros (e Alertas, se houver).
              A etapa seguinte e a auditoria fiscal completa do arquivo SPED — execute quando quiser.
            </p>
          </div>
          <button onClick={handleValidateStream} className="bg-blue-600 text-white px-4 py-2 rounded text-sm hover:bg-blue-700 whitespace-nowrap shrink-0 self-start sm:self-auto">
            Validar SPED completo
          </button>
        </div>
      )}

      {/* Audit Scope — always visible when validated */}
      {file.status === 'validated' && !validating && <AuditScopePanel fileId={id} />}

      {/* Pipeline Progress */}
      {validating && pipelineEvent && <PipelineProgressPanel event={pipelineEvent} />}

      {/* Tabs */}
      {(file.status === 'validated' || fromXml || errorItems.length > 0 || alertItems.length > 0) && !validating && (
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
              onRequestConfirm={(s) => setConfirmModal({ ...s, open: true })}
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
              onRequestConfirm={(s) => setConfirmModal({ ...s, open: true })}
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

      <ConfirmModal state={confirmModal} onClose={closeModal} />
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

      {/* Cross-validation links */}
      <div className="text-center pt-2 flex gap-6 justify-center">
        <Link to={`/files/${fileId}/cross`} className="text-sm text-blue-600 hover:underline">
          Ver cruzamentos entre blocos &rarr;
        </Link>
        <Link to={`/files/${fileId}/xml`} className="text-sm text-green-600 hover:underline font-medium">
          Cruzar com NF-e (XML) &rarr;
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
  onRequestConfirm: (state: Omit<ConfirmModalState, 'open'>) => void
}

// ── Helpers para agrupamento por error_type ──

/** Labels descritivos para error_types conhecidos */
const ERROR_TYPE_LABELS: Record<string, string> = {
  // Cruzamento XML vs SPED
  XML001: 'NF-e ausente no SPED',
  XML002: 'NF-e sem XML correspondente',
  XML003: 'Valor do documento divergente (VL_DOC)',
  XML004: 'Valor ICMS divergente (VL_ICMS)',
  XML005: 'Valor ICMS-ST divergente (VL_ICMS_ST)',
  XML006: 'Valor IPI divergente (VL_IPI)',
  XML012: 'Quantidade de itens divergente',
  NF_CANCELADA_ESCRITURADA: 'NF-e cancelada escriturada como ativa',
  NF_DENEGADA_ESCRITURADA: 'NF-e denegada escriturada como ativa',
  NF_ATIVA_ESCRITURADA_CANCELADA: 'NF-e autorizada escriturada como cancelada',
  NF_ATIVA_ESCRITURADA_DENEGADA: 'NF-e autorizada escriturada como denegada',
  COD_SIT_DIVERGENTE_XML: 'Situacao do documento divergente (COD_SIT)',
  // ST
  ST_APURACAO_INCONSISTENTE: 'Apuracao ST inconsistente com documentos',
  ST_APURACAO_DIVERGENTE: 'Apuracao ST divergente (E210 vs docs)',
  ST_CST60_DEBITO_INDEVIDO: 'CST 60 com debito indevido de ST',
  ST_BC_MENOR_QUE_ITEM: 'Base ST menor que valor do item',
  ST_MISTURA_DIFAL: 'Mistura ST com DIFAL',
  ST_MVA_DIVERGENTE: 'Base/valor ST diverge do MVA',
  ST_MVA_AUSENTE: 'Produto com ST mas BC zerada',
  ST_MVA_NCM_SEM_ST: 'NCM sujeito a ST sem retencao',
  ST_ALIQ_INCORRETA: 'Aliquota ST diverge da tabela',
  // Apuracao
  APURACAO_DEBITO_DIVERGENTE: 'Debitos divergentes na apuracao (E110)',
  APURACAO_CREDITO_DIVERGENTE: 'Creditos divergentes na apuracao (E110)',
  APURACAO_SALDO_DIVERGENTE: 'Saldo divergente na apuracao (E110)',
  // Beneficios / Ajustes
  BENEFICIO_VALOR_DESPROPORCIONAL: 'Beneficio fiscal desproporcional',
  BENEFICIO_SOBREPOSICAO: 'Sobreposicao de beneficios',
  AJUSTE_CODIGO_GENERICO: 'Ajuste com codigo generico (E111)',
  AJUSTE_NUMERICO_SEM_VALIDADE_JURIDICA: 'Ajuste sem validade juridica',
  AJUSTE_SEM_RASTREABILIDADE: 'Ajuste sem rastreabilidade (E112/E113)',
  AJUSTE_SOMA_DIVERGENTE: 'Soma dos ajustes diverge do E110',
  AJUSTE_UF_INCOMPATIVEL: 'Codigo de ajuste incompativel com UF',
  // Simples Nacional
  SN_PERFIL_INVALIDO: 'Perfil invalido para Simples Nacional',
  SN_CREDITO_INCONSISTENTE: 'Credito ICMS inconsistente no SN',
  // Estrutural
  CAMPO_OBRIGATORIO: 'Campo obrigatorio ausente',
  VALOR_INVALIDO: 'Valor invalido',
  REGISTRO_DUPLICADO: 'Registro duplicado',
  REFERENCIA_INVALIDA: 'Referencia a registro inexistente',
  // Inventario
  INVENTARIO_VL_ZERO: 'Item no inventario com valor zero',
  INVENTARIO_QTD_EXCESSIVA: 'Quantidade excessiva no inventario',
  INVENTARIO_ITEM_NAO_CADASTRADO: 'Item do inventario sem cadastro (0200)',
  // Bloco K
  K_BLOCO_SEM_MOVIMENTO_COM_REGISTROS: 'Bloco K sem movimento com registros',
  K_REF_ITEM_INEXISTENTE: 'Bloco K referencia item inexistente',
  K_QTD_NEGATIVA: 'Bloco K com quantidade negativa',
  K_ORDEM_SEM_COMPONENTES: 'Ordem de producao sem componentes',
  // Calculo
  CALCULO_DIVERGENTE: 'Calculo de imposto divergente',
  CALCULO_ARREDONDAMENTO: 'Arredondamento de calculo (centavos)',
  // C190
  C190_SOMA_DIVERGENTE: 'Soma C190 diverge do C100',
  C190_DIVERGE_C170: 'C190 diverge da soma dos itens C170',
  // Encadeamento
  ENCADEAMENTO_VL_DOC: 'Soma itens diverge do documento',
  // Checklist / Meta
  CHECKLIST_INCOMPLETO: 'Checklist de auditoria incompleto',
  CLASSIFICACAO_TIPO_ERRO: 'Classificacao de tipo de erro',
  ACHADO_LIMITADO_AO_SPED: 'Achado limitado ao SPED',
  AMOSTRAGEM_MATERIALIDADE: 'Amostragem por materialidade',
}

/** Gera label amigavel a partir do error_type */
function friendlyTypeLabel(errorType: string): string {
  if (ERROR_TYPE_LABELS[errorType]) return ERROR_TYPE_LABELS[errorType]

  // Fallback: converter snake_case para titulo
  return errorType
    .replace(/^(XML|FM|ST|SN|RET|K)_/, '$1 — ')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase())
    .replace(/\bXml\b/g, 'XML')
    .replace(/\bSt\b/g, 'ST')
    .replace(/\bIcms\b/g, 'ICMS')
    .replace(/\bIpi\b/g, 'IPI')
    .replace(/\bBc\b/g, 'BC')
    .replace(/\bMva\b/g, 'MVA')
    .replace(/\bCst\b/g, 'CST')
    .replace(/\bCfop\b/g, 'CFOP')
    .replace(/\bNfe\b/g, 'NF-e')
    .replace(/\bSped\b/g, 'SPED')
}

interface ErrorGroup {
  errorType: string
  label: string
  items: ValidationError[]
  openCount: number
  correctableCount: number
  maxSeverity: string
}

function buildGroups(items: ValidationError[]): ErrorGroup[] {
  const map = new Map<string, ValidationError[]>()
  for (const e of items) {
    const list = map.get(e.error_type) || []
    list.push(e)
    map.set(e.error_type, list)
  }

  const severityOrder: Record<string, number> = { critical: 0, error: 1, warning: 2, info: 3 }

  const groups: ErrorGroup[] = []
  for (const [errorType, groupItems] of map.entries()) {
    const openCount = groupItems.filter(e => e.status === 'open').length
    const correctableCount = groupItems.filter(e => e.auto_correctable && e.expected_value && e.status === 'open').length
    let maxSeverity = 'info'
    for (const e of groupItems) {
      if ((severityOrder[e.severity] ?? 9) < (severityOrder[maxSeverity] ?? 9)) {
        maxSeverity = e.severity
      }
    }
    groups.push({ errorType, label: friendlyTypeLabel(errorType), items: groupItems, openCount, correctableCount, maxSeverity })
  }

  // Ordenar: mais severo primeiro, depois por quantidade
  groups.sort((a, b) => {
    const sa = severityOrder[a.maxSeverity] ?? 9
    const sb = severityOrder[b.maxSeverity] ?? 9
    if (sa !== sb) return sa - sb
    return b.openCount - a.openCount
  })

  return groups
}

function ErrorsAlertsList({ items, variant, expandedError, onToggleExpand, fileId, onReload, onRequestConfirm }: ListProps) {
  const [activeGroup, setActiveGroup] = useState<string | null>(null)
  const [showCorrected, setShowCorrected] = useState(false)

  // Agrupar por error_type
  const baseItems = showCorrected ? items : items.filter(e => e.status === 'open')
  const groups = buildGroups(baseItems)

  // Selecionar primeiro grupo por default
  const currentGroupKey = activeGroup && groups.some(g => g.errorType === activeGroup) ? activeGroup : (groups[0]?.errorType ?? null)
  const currentGroup = groups.find(g => g.errorType === currentGroupKey)
  const groupItems = currentGroup?.items ?? []

  // Ordenar itens do grupo por severidade e linha
  const severityOrder: Record<string, number> = { critical: 0, error: 1, warning: 2, info: 3 }
  const displayItems = [...groupItems].sort((a, b) => {
    const sv = (severityOrder[a.severity] ?? 9) - (severityOrder[b.severity] ?? 9)
    if (sv !== 0) return sv
    return a.line_number - b.line_number
  })

  const totalOpen = items.filter(e => e.status === 'open').length
  const correctedCount = items.filter(e => e.status === 'corrected').length

  // Modal de edicao de registro
  const [editModalError, setEditModalError] = useState<ValidationError | null>(null)

  const handleOpenRecordDetail = (error: ValidationError) => {
    if (!error.record_id) return
    setEditModalError(error)
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

  // Ignorar grupo inteiro
  const [dismissingGroup, setDismissingGroup] = useState(false)
  const handleDismissGroup = () => {
    if (!currentGroupKey || !currentGroup) return
    onRequestConfirm({
      title: 'Ignorar grupo',
      message: `Ignorar todos os ${currentGroup.openCount} apontamentos do grupo "${currentGroup.label}"? Eles serao removidos da lista de erros.`,
      confirmLabel: 'Ignorar Todos',
      confirmColor: 'red',
      onConfirm: async () => {
        setDismissingGroup(true)
        try {
          await api.dismissErrorGroup(fileId, currentGroupKey!)
          onReload()
        } catch { /* */ }
        setDismissingGroup(false)
      },
    })
  }

  // Corrigir grupo inteiro
  const [correctingGroup, setCorrectingGroup] = useState(false)
  const handleCorrectGroup = () => {
    if (!currentGroup) return
    const correctable = currentGroup.items.filter(e => e.auto_correctable && e.expected_value && e.record_id && e.status === 'open')
    if (correctable.length === 0) return
    onRequestConfirm({
      title: 'Corrigir grupo',
      message: `Aplicar ${correctable.length} correcoes automaticas do grupo "${currentGroup.label}"? Os valores serao atualizados no SPED conforme sugerido.`,
      confirmLabel: 'Aplicar Correcoes',
      confirmColor: 'green',
      onConfirm: async () => {
        setCorrectingGroup(true)
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
        setCorrectingGroup(false)
      },
    })
  }

  // Revisao IA (tribunal de validacao)
  const [reviewing, setReviewing] = useState(false)
  const [reviewResult, setReviewResult] = useState<{
    veredito: string; confianca: string; justificativa: string; dados_sustentacao: string;
    recomendacao: string; analise_claude: string; analise_gpt: string;
    base_legal_relevante: string; consenso: string;
    amostras_analisadas: number; cached: boolean;
  } | null>(null)
  const [reviewGroupKey, setReviewGroupKey] = useState<string | null>(null)

  const handleReviewGroup = async () => {
    if (!currentGroupKey) return
    setReviewing(true)
    setReviewResult(null)
    setReviewGroupKey(currentGroupKey)
    try {
      const result = await api.reviewErrorGroup(fileId, currentGroupKey)
      setReviewResult(result)
    } catch (e) {
      setReviewResult({
        veredito: 'inconclusivo', confianca: 'baixa',
        justificativa: e instanceof Error ? e.message : 'Erro na revisao',
        dados_sustentacao: '', recomendacao: '',
        analise_claude: '', analise_gpt: '', base_legal_relevante: '',
        consenso: '', amostras_analisadas: 0, cached: false,
      })
    }
    setReviewing(false)
  }

  // Limpar review ao trocar de grupo
  const activeReview = reviewGroupKey === currentGroupKey ? reviewResult : null

  // Exportar lista de NF-e (XML001 / XML002)
  const handleExportGroup = () => {
    if (!currentGroup) return
    const openErrors = currentGroup.items.filter(e => e.status === 'open')
    if (openErrors.length === 0) return

    const lines: string[] = []
    const tipo = currentGroup.errorType
    const titulo = currentGroup.label

    lines.push(`=== ${titulo} ===`)
    lines.push(`Total: ${openErrors.length} apontamento(s)`)
    lines.push(`Exportado em: ${new Date().toLocaleString('pt-BR')}`)
    lines.push('')
    lines.push('---')
    lines.push('')

    for (const e of openErrors) {
      const msg = e.message || ''
      // Extrair numero da NF: "NF 575361" ou do friendly_message "NF-e 575361"
      const nfMatch = msg.match(/NF[- ]?e?\s*(\d+)/) || (e.friendly_message || '').match(/NF[- ]?e?\s*(\d+)/)
      const numNf = nfMatch ? nfMatch[1] : '?'

      // Extrair chave: 44 digitos consecutivos
      const chaveMatch = msg.match(/(\d{44})/) || (e.friendly_message || '').match(/(\d{44})/) || (e.value || '').match(/(\d{44})/)
      const chave = chaveMatch ? chaveMatch[1] : (e.value || '?')

      lines.push(`Numero da NF: ${numNf}`)
      lines.push(`Chave da NF:  ${chave}`)
      lines.push('')
    }

    const blob = new Blob([lines.join('\r\n')], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${tipo}_${openErrors.length}_notas.txt`
    a.click()
    URL.revokeObjectURL(url)
  }

  // Tipos exportaveis (erros que listam NF-e com chave)
  const exportableTypes = new Set(['XML001', 'XML002', 'NF_CANCELADA_ESCRITURADA', 'NF_DENEGADA_ESCRITURADA', 'NF_ATIVA_ESCRITURADA_CANCELADA', 'NF_ATIVA_ESCRITURADA_DENEGADA', 'COD_SIT_DIVERGENTE_XML'])

  // Tipos que NAO precisam de revisao IA (ausencia pura, sem dados para cruzar)
  const skipReviewTypes = new Set([
    'XML001',                          // NF-e ausente no SPED — so ausencia
    'XML002',                          // NF-e sem XML — so ausencia
    'CAMPO_OBRIGATORIO',               // Campo vazio — objetivo
    'VALOR_INVALIDO',                  // Formato errado — objetivo
    'REGISTRO_DUPLICADO',              // Duplicata — objetivo
    'REFERENCIA_INVALIDA',             // Ref inexistente — objetivo
    'CHECKLIST_INCOMPLETO',            // Meta — nao e erro fiscal
    'CLASSIFICACAO_TIPO_ERRO',         // Meta
    'ACHADO_LIMITADO_AO_SPED',         // Meta
    'AMOSTRAGEM_MATERIALIDADE',        // Meta
  ])

  const isError = variant === 'error'

  const sevColor = (sev: string) =>
    sev === 'critical' ? 'bg-red-500' :
    sev === 'error' ? 'bg-orange-500' :
    sev === 'warning' ? 'bg-yellow-400' : 'bg-blue-400'

  return (
    <div>
      {/* Banner resumo */}
      {totalOpen > 0 && (
        <div className={`rounded p-4 mb-4 ${isError ? 'bg-red-50 border border-red-200' : 'bg-yellow-50 border border-yellow-200'}`}>
          <span className={`font-semibold ${isError ? 'text-red-800' : 'text-yellow-800'}`}>
            {totalOpen} {isError ? 'erro' : 'alerta'}{totalOpen !== 1 ? 's' : ''} em {groups.length} grupo{groups.length !== 1 ? 's' : ''}
          </span>
          {correctedCount > 0 && (
            <label className="flex items-center gap-2 text-sm text-gray-500 mt-2">
              <input type="checkbox" checked={showCorrected} onChange={e => setShowCorrected(e.target.checked)} />
              Incluir corrigidos ({correctedCount})
            </label>
          )}
        </div>
      )}

      {groups.length === 0 && (
        <p className="text-gray-500 text-center py-8">
          {isError ? 'Nenhum erro encontrado.' : 'Nenhum alerta encontrado.'}
        </p>
      )}

      {groups.length > 0 && (
        <div className="flex gap-0">
          {/* Sidebar com abas de grupos */}
          <div className="w-72 flex-shrink-0 border-r border-gray-200 pr-0 space-y-0.5 max-h-[75vh] overflow-y-auto">
            {groups.map(g => {
              const isActive = g.errorType === currentGroupKey
              return (
                <button
                  key={g.errorType}
                  onClick={() => { setActiveGroup(g.errorType); setEditModalError(null) }}
                  className={`w-full text-left px-3 py-2.5 rounded-l-lg transition-colors text-sm ${
                    isActive
                      ? 'bg-white border border-r-0 border-gray-200 shadow-sm font-medium'
                      : 'hover:bg-gray-50 text-gray-600'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span className={`w-2 h-2 rounded-full flex-shrink-0 ${sevColor(g.maxSeverity)}`} />
                    <span className="truncate flex-1" title={g.label}>{g.label}</span>
                    <span className={`text-xs px-1.5 py-0.5 rounded-full flex-shrink-0 ${
                      g.openCount === 0 ? 'bg-green-100 text-green-600' : 'bg-gray-200 text-gray-600'
                    }`}>
                      {g.openCount}
                    </span>
                  </div>
                  {g.correctableCount > 0 && (
                    <div className="text-xs text-green-600 mt-0.5 ml-4">
                      {g.correctableCount} corrigive{g.correctableCount !== 1 ? 'is' : 'l'}
                    </div>
                  )}
                </button>
              )
            })}
          </div>

          {/* Conteudo do grupo selecionado */}
          <div className="flex-1 min-w-0 pl-4">
            {currentGroup && (
              <>
                {/* Header do grupo com acoes */}
                <div className="flex flex-wrap items-center gap-3 mb-4 pb-3 border-b border-gray-200">
                  <div className="flex-1 min-w-0">
                    <h3 className="font-semibold text-gray-800">{currentGroup.label}</h3>
                    <p className="text-xs text-gray-500 mt-0.5 font-mono">{currentGroup.errorType}</p>
                  </div>
                  <div className="flex gap-2 flex-shrink-0">
                    {currentGroup.openCount > 0 && !skipReviewTypes.has(currentGroup.errorType) && (
                      <button
                        onClick={handleReviewGroup}
                        disabled={reviewing}
                        className="text-sm text-purple-700 px-3 py-1.5 rounded border border-purple-300 hover:bg-purple-50 font-medium disabled:opacity-50"
                      >
                        {reviewing ? 'Analisando...' : 'Revisar com IA'}
                      </button>
                    )}
                    {exportableTypes.has(currentGroup.errorType) && currentGroup.openCount > 0 && (
                      <button
                        onClick={handleExportGroup}
                        className="text-sm text-blue-600 px-3 py-1.5 rounded border border-blue-300 hover:bg-blue-50 font-medium"
                      >
                        Exportar TXT ({currentGroup.openCount})
                      </button>
                    )}
                    {currentGroup.correctableCount > 0 && (
                      <button
                        onClick={handleCorrectGroup}
                        disabled={correctingGroup}
                        className="bg-green-600 text-white px-3 py-1.5 rounded text-sm font-medium hover:bg-green-700 disabled:opacity-50"
                      >
                        {correctingGroup ? 'Corrigindo...' : `Corrigir Grupo (${currentGroup.correctableCount})`}
                      </button>
                    )}
                    {currentGroup.openCount > 0 && (
                      <button
                        onClick={handleDismissGroup}
                        disabled={dismissingGroup}
                        className="text-sm text-gray-500 px-3 py-1.5 rounded border border-gray-300 hover:bg-gray-100 disabled:opacity-50"
                      >
                        {dismissingGroup ? 'Ignorando...' : `Ignorar Grupo (${currentGroup.openCount})`}
                      </button>
                    )}
                  </div>
                </div>

                {/* Painel de veredito IA */}
                {activeReview && (
                  <div className={`rounded-lg border p-4 mb-4 ${
                    activeReview.veredito === 'valido' ? 'bg-green-50 border-green-300' :
                    activeReview.veredito === 'falso_positivo' ? 'bg-amber-50 border-amber-300' :
                    'bg-gray-50 border-gray-300'
                  }`}>
                    {/* Header com veredito + confianca */}
                    <div className="flex items-center gap-3 mb-3 flex-wrap">
                      <span className={`text-lg font-bold ${
                        activeReview.veredito === 'valido' ? 'text-green-700' :
                        activeReview.veredito === 'falso_positivo' ? 'text-amber-700' :
                        'text-gray-600'
                      }`}>
                        {activeReview.veredito === 'valido' ? 'Apontamento Valido' :
                         activeReview.veredito === 'falso_positivo' ? 'Falso Positivo' :
                         'Inconclusivo'}
                      </span>
                      {activeReview.confianca && (
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                          activeReview.confianca === 'alta' ? 'bg-green-200 text-green-800' :
                          activeReview.confianca === 'media' ? 'bg-yellow-200 text-yellow-800' :
                          'bg-gray-200 text-gray-600'
                        }`}>
                          Confianca {activeReview.confianca}
                        </span>
                      )}
                      {activeReview.consenso === 'unanime' && (
                        <span className="px-2 py-0.5 rounded text-xs bg-purple-100 text-purple-700 font-medium">
                          Claude + GPT concordam
                        </span>
                      )}
                      {activeReview.consenso === 'divergente' && (
                        <span className="px-2 py-0.5 rounded text-xs bg-red-100 text-red-700 font-medium">
                          Modelos divergem
                        </span>
                      )}
                      <span className="text-xs text-gray-400 ml-auto">
                        {activeReview.amostras_analisadas} amostra(s){activeReview.cached ? ' (cache)' : ''}
                      </span>
                    </div>

                    {/* Justificativa */}
                    {activeReview.justificativa && (
                      <p className="text-sm text-gray-800 mb-3">{activeReview.justificativa}</p>
                    )}

                    {/* Analises individuais (colapsavel) */}
                    {(activeReview.analise_claude || activeReview.analise_gpt) && (
                      <details className="mb-3">
                        <summary className="text-xs font-medium text-gray-500 cursor-pointer hover:text-gray-700">
                          Analises individuais (Claude / GPT)
                        </summary>
                        <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-3">
                          {activeReview.analise_claude && (
                            <div className="text-xs bg-white rounded border p-3">
                              <div className="flex items-center gap-2 mb-1">
                                <span className="font-semibold text-purple-700">Claude</span>
                              </div>
                              <p className="text-gray-600 whitespace-pre-line">{activeReview.analise_claude}</p>
                            </div>
                          )}
                          {activeReview.analise_gpt && (
                            <div className="text-xs bg-white rounded border p-3">
                              <div className="flex items-center gap-2 mb-1">
                                <span className="font-semibold text-emerald-700">GPT-4o</span>
                              </div>
                              <p className="text-gray-600 whitespace-pre-line">{activeReview.analise_gpt}</p>
                            </div>
                          )}
                        </div>
                      </details>
                    )}

                    {/* Base legal */}
                    {activeReview.base_legal_relevante && (
                      <details className="mb-3">
                        <summary className="text-xs font-medium text-gray-500 cursor-pointer hover:text-gray-700">Base legal consultada</summary>
                        <p className="text-xs text-gray-600 mt-1 whitespace-pre-line">{activeReview.base_legal_relevante}</p>
                      </details>
                    )}

                    {/* Recomendacao */}
                    {activeReview.recomendacao && (
                      <div className="text-sm text-blue-800 bg-blue-50 rounded p-2">
                        <span className="font-medium">Recomendacao:</span> {activeReview.recomendacao}
                      </div>
                    )}
                  </div>
                )}

                {reviewing && (
                  <div className="flex items-center gap-3 p-4 mb-4 bg-purple-50 border border-purple-200 rounded-lg">
                    <div className="animate-spin h-5 w-5 border-2 border-purple-500 border-t-transparent rounded-full" />
                    <span className="text-sm text-purple-700">Analisando dados do SPED e XMLs com IA (Claude Sonnet 4 + GPT-4o)...</span>
                  </div>
                )}

                {/* Cards do grupo */}
                <div className="space-y-2 max-h-[65vh] overflow-y-auto pr-1">
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
                        loadingRecord={false}
                      />
                    </div>
                  ))}
                </div>

                {displayItems.length === 0 && (
                  <p className="text-gray-400 text-center py-6 text-sm">Todos os apontamentos deste grupo foram tratados.</p>
                )}

                {/* Modal de edicao de registro */}
                {editModalError && (
                  <RecordEditModal
                    fileId={fileId}
                    error={editModalError}
                    onClose={() => setEditModalError(null)}
                    onSaved={onReload}
                  />
                )}
              </>
            )}
          </div>
        </div>
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
            {error.error_hash && (
              <span
                className="font-mono text-xs text-gray-400 cursor-pointer hover:text-gray-600 select-all"
                title="Clique para copiar o hash"
                onClick={(ev) => { ev.stopPropagation(); navigator.clipboard.writeText(error.error_hash!) }}
              >
                #{error.error_hash.slice(0, 8)}
              </span>
            )}
            <span className="font-mono text-xs text-gray-500">Linha {error.line_number}</span>
            <span className="font-mono text-xs bg-gray-100 px-1.5 py-0.5 rounded">{error.register}</span>
            {error.field_name && <span className="text-xs text-gray-500">{error.field_name}</span>}
            <SeverityBadge severity={error.severity} />
            {(error.categoria === 'cruzamento_xml' || error.error_type?.startsWith('XML')) && (
              <span className="px-2 py-0.5 rounded text-xs bg-emerald-100 text-emerald-700 border border-emerald-300 font-medium">
                XML
              </span>
            )}
            {error.materialidade > 0 && (
              <span className="px-2 py-0.5 rounded text-xs bg-amber-100 text-amber-800 font-medium" title="Materialidade financeira">
                R$ {error.materialidade.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
            )}
            {error.certeza === 'indicio' && <span className="px-2 py-0.5 rounded text-xs bg-purple-100 text-purple-700">Indicio</span>}
            {isCorrected && <span className="px-2 py-0.5 rounded text-xs bg-green-100 text-green-700">Corrigido</span>}
          </div>
          <p className="text-sm text-gray-800 whitespace-pre-line">{renderBold(displayMessage)}</p>
          {legalBasis && (
            <p className="text-xs text-gray-400 mt-0.5">
              <span className="font-medium text-gray-500">Base legal:</span> {legalBasis.fonte}
              {legalBasis.artigo && <span> — {legalBasis.artigo}</span>}
            </p>
          )}
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
              <div className="text-sm text-gray-800 whitespace-pre-line leading-relaxed space-y-2">
                {error.doc_suggestion.split(/\*\*(O que foi encontrado|Por que isso importa|Como corrigir|Base legal):\*\*/g).map((part, i) => {
                  const trimmed = part.trim()
                  if (!trimmed) return null
                  // Partes impares sao os titulos capturados pelo regex
                  if (['O que foi encontrado', 'Por que isso importa', 'Como corrigir', 'Base legal'].includes(trimmed)) {
                    const colors: Record<string, string> = {
                      'O que foi encontrado': 'text-red-700',
                      'Por que isso importa': 'text-amber-700',
                      'Como corrigir': 'text-blue-800',
                      'Base legal': 'text-gray-600',
                    }
                    return <p key={i} className={`font-semibold mt-2 ${colors[trimmed] || 'text-gray-700'}`}>{trimmed}:</p>
                  }
                  // Conteudo da secao
                  return <p key={i} className="text-gray-700 ml-0">{renderBold(trimmed)}</p>
                })}
              </div>
            ) : error.friendly_message ? (
              <p className="text-sm text-gray-800 whitespace-pre-line">{renderBold(error.friendly_message)}</p>
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

            {/* Detalhe tecnico removido — conteudo agora esta no "Como corrigir" */}
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
